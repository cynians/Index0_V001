"""Map interaction over ontology entities and disposable worldgen products.

Architecture invariants: the ontology is the sole durable source for entities
and semantic facts; local mappings are startup/query caches. No generated
planet is presently a persistence target, so changed worldgen contracts may
invalidate old maps without compatibility code.
"""

import copy
import math
import re
import shutil
import time
from pathlib import Path

from engine.logger import logger
from world.year_utils import parse_year
from simulations.world_gen.natural_materials import (
    derive_planet_surface_palette,
    material_display_color,
    material_geological_map_color,
)
from simulations.world_gen.coastal_geomorphology import ensure_coastal_model_current
from simulations.world_gen.surface_exposure import derive_surface_exposure_model
from simulations.world_gen.true_color import (
    TRUE_COLOR_MODEL_VERSION,
    derive_true_color_model,
    true_color_model_sources_match,
)
from simulations.map.projection import (
    project_map_world_point,
    project_map_world_line,
    project_map_world_ring,
    unproject_map_world_point,
    unproject_normalized_point,
)


class MapSimulation:
    """
    Pure map simulation (entity-driven).

    In map mode, planets are rendered as 2D surface containers rather than
    physical spheres. Child regions are expected to use projected map-space
    coordinates inside that container.

    Selection ownership also lives here:
    * click handling is map-specific
    * picking is done in world/map coordinates
    * selected entity state is stored on the simulation
    * hover state is stored on the simulation

    Map-space convention:
    * 1 world unit is one projected longitude/latitude degree
    * Earth-facing map data stores X as longitude and Y as negative latitude
      so the renderer can stay in its native positive-Y-down coordinate system
    * planet roots use a 2:1 equirectangular frame derived from radius
    """

    MAP_KM_PER_WORLD_UNIT = 111.195
    MAP_METERS_PER_WORLD_UNIT = MAP_KM_PER_WORLD_UNIT * 1000.0
    KEYDOWN_EVENT_TYPE = 768
    MOUSEBUTTONDOWN_EVENT_TYPE = 1025
    MOUSEBUTTONUP_EVENT_TYPE = 1026
    DRAFT_DOUBLE_CLICK_SECONDS = 0.35
    DRAFT_DOUBLE_CLICK_DISTANCE_PX = 10.0
    POLYGON_POINT_HIT_RADIUS_PX = 10.0
    SQUARE_HANDLE_HIT_RADIUS_PX = 10.0
    CAMERA_DRAG_THRESHOLD_PX = 4.0
    MIN_SQUARE_SIDE_WORLD = 0.001

    DEFAULT_PLANET_WORLD_WIDTH = 4000.0
    DEFAULT_PLANET_WORLD_HEIGHT = 2000.0
    MAP_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "locations"

    VISUAL_MAP_LAYER_KIND = "visual_map"
    LOCATION_LAYER_KIND = "locations"
    REGION_LAYER_KIND = "regions"
    HEIGHTMAP_LAYER_KIND = "heightmap"
    TRUE_COLOR_LAYER_KIND = "true_color"
    HYDROLOGY_LAYER_KIND = "hydrology"
    COASTAL_LAYER_KIND = "coastal_geomorphology"
    GROUND_MATERIALS_LAYER_KIND = "ground_materials"
    MATERIAL_HEATMAP_LAYER_KIND = "material_heatmaps"
    BIOSPHERE_PATCH_LOCATION_CLASS = "biosphere_patch"
    BIOSPHERE_SPECIES_COLLECTION_ID = "coll_micro_biosphere_species_starter"
    LOCALIZED_BIOSPHERE_ROSTER_CLASS = "localized_biosphere_species_roster"
    ORBITAL_LOCATION_CLASSES = {
        "star",
        "star_system",
        "planet",
        "moon",
        "dwarf_planet",
        "asteroid",
        "comet",
        "orbital_body",
        "spacecraft",
        "space_station",
        "station",
        "orbital_spacecraft",
        "planetary_spacecraft",
        "system_spacecraft",
        "interstellar_spacecraft",
    }

    LAYER_LABELS = {
        "visual_map": "Visual Map",
        "locations": "Map + Locations",
        "regions": "Regions",
        "heightmap": "Heightmap",
        "true_color": "True Color",
        "hydrology": "Hydrology + Climate",
        "coastal_geomorphology": "Coastal Geomorphology",
        "ground_materials": "Regions",
        "material_heatmaps": "Material Distribution",
    }

    SPATIAL_LAYER_COLORS = {
        "regions": (116, 132, 164),
        "ecoregions": (74, 132, 82),
        "faction_borders": (150, 82, 82),
        "political_control": (150, 82, 82),
        "settlement_extent": (92, 132, 184),
        "resource_claims": (158, 128, 72),
        "infrastructure_corridors": (138, 118, 170),
        "city_margins": (160, 142, 78),
        "sites": (86, 118, 158),
        "rooms": (112, 146, 172),
        "ground_materials": (156, 118, 74),
        "iron_ore": (178, 96, 70),
    }

    AUTHORABLE_HISTORY_LAYER_KINDS = [LOCATION_LAYER_KIND, GROUND_MATERIALS_LAYER_KIND]
    MAP_SURFACE_FIELDS = (
        "bounds",
        "geometry",
        "map_canvas_width_px",
        "map_canvas_height_px",
        "map_status",
        "map_generation_recipe",
        "map_layers",
        "map_image_path",
        "heightmap_model",
        "water_cycle_model",
        "coastal_geomorphology_model",
        "material_heatmap_model",
        "surface_exposure_model",
        "true_color_model",
    )
    VISUAL_SURFACE_FIELDS = (
        "map_image_path",
        "heightmap_model",
        "water_cycle_model",
        "coastal_geomorphology_model",
        "material_heatmap_model",
        "surface_exposure_model",
        "true_color_model",
        "map_layers",
    )

    def __init__(self, simulation_context):
        from engine.clock import Clock
        from engine.simulation_manager import SimulationManager

        self.render_mode = "map"
        self.world_units_to_meters = self.MAP_METERS_PER_WORLD_UNIT

        self.context = simulation_context
        self.world_model = simulation_context.world_model
        root_entity = self.world_model.get_entity(simulation_context.root_entity_id) or {}
        if root_entity.get("map_coordinate_space") == "site_meters":
            self.world_units_to_meters = 1.0

        self.sim_clock = Clock(base_dt=1.0)

        class _DummySystem:
            def update(self, dt):
                pass

        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 0.02
        self.max_zoom = 80.0
        self.preferred_zoom = 4.0
        if root_entity.get("map_coordinate_space") == "site_meters":
            self.min_zoom = 1.0
            self.preferred_zoom = 7.0

        self._layer_cache = None
        self._cache_year = None
        self._cache_layer_kind = None
        self._last_hover_pick_time = 0.0
        self._last_hover_pick_screen_pos = None
        self._last_hover_pick_camera_state = None

        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.active_material_heatmap_layer_id = "composite"
        self.active_climate_layer_id = "koppen"
        self.atmosphere_visible = True
        self.height_contours_visible = True

        self.selected_entity_id = None
        self.selected_material_occurrence_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        self.is_creating_spatial_feature = False
        self.is_creating_biosphere_patch = False
        self.draft_location_class = "region"
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_creating_point_location = False
        self.draft_point_location_class = "site"
        self.draft_point_location_pos = None
        self.draft_point_hover_pos = None
        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.return_to_repository_entity_id = None
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
        self.last_saved_location_id = None
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self.square_drag_handle = None
        self.square_drag_start_pos = None
        self.square_drag_start_bounds = None
        self.square_drag_opposite_point = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self._selection_last_click_time = None
        self._selection_last_click_screen_pos = None
        self._selection_last_click_target = None
        self._pending_inspector_target = None
        self._pending_floating_card_target = None
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False
        self.map_projection_focus_x = 0.0
        self.map_projection_focus_y = 0.0
        self.map_projection_dragging = False
        self.map_projection_drag_start = None
        self._layer_projection_focus_key = None
        self._inherited_surface_context_cache = None
        self._surface_model_validation_cache_key = None
        self._map_focus_last_click_time = None
        self._map_focus_last_click_screen_pos = None
        self.last_saved_spatial_feature_id = None

        self.bounds = self._resolve_root_bounds()
        self.max_zoom = self._maximum_camera_zoom()
        if not self._root_has_visual_surface():
            self.active_layer_kind = self.LOCATION_LAYER_KIND

    def _maximum_camera_zoom(self):
        """Allow each refinement map to frame the next physical detail scale."""
        root = self.get_root_entity() or {}
        try:
            detail_level = max(0, int(root.get("map_detail_level", 0) or 0))
        except (TypeError, ValueError):
            detail_level = 0
        return {
            0: 2_048.0,
            1: 16_384.0,
            2: 131_072.0,
            3: 1_000_000.0,
        }.get(detail_level, 1_000_000.0)

    @property
    def year(self):
        return getattr(self.context, "year", 0)

    def set_year(self, year):
        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        if self.is_map_editor_active():
            return False

        if year == self.year:
            return False

        self.context.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0

        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = None
        self._pending_floating_card_target = None
        self._selection_last_click_time = None
        self._selection_last_click_screen_pos = None
        self._selection_last_click_target = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Selected history year {year}")
        return True

    def _repository_loader(self):
        return getattr(self.world_model, "loader", None) if self.world_model is not None else None

    def _persist_repository_entity(self, entity, dataset_name):
        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        entity["_dataset"] = dataset_name
        if not entity.get("type") and dataset_name == "locations":
            entity["type"] = "location"
        return loader.persist_entity(entity)

    def _notify_incremental_repository_change(self, *, rebuild_relations=True):
        """Update in-memory consumers after a local map write.

        Polygon finishing already updates ``loader.entities`` and persists the
        changed records.  Calling ``WorldModel.refresh`` here used to reopen
        the complete ontology, reconstruct every index, and reapply reference
        models just to display the newly created card.  Refresh the lightweight
        relation graph instead; a full reload remains available at normal
        repository-boundary operations.
        """
        world_model = self.world_model
        if rebuild_relations:
            touch_degrees = getattr(world_model, "touch_degrees", None)
            if touch_degrees is not None and hasattr(touch_degrees, "refresh"):
                touch_degrees.refresh()
        if hasattr(world_model, "repository_revision"):
            world_model.repository_revision += 1

    def _update_repository_entity_fields(self, entity_id, updates):
        loader = self._repository_loader()
        entity = getattr(loader, "entities", {}).get(entity_id) if loader is not None else None
        if not isinstance(entity, dict):
            return False
        changed_updates = {
            field_name: value
            for field_name, value in dict(updates or {}).items()
            if entity.get(field_name) != value
        }
        if not changed_updates:
            return True

        entity.update(changed_updates)
        persist_fields = getattr(loader, "persist_entity_fields", None)
        if callable(persist_fields):
            return bool(persist_fields(entity, changed_updates.keys()))
        return loader.persist_entity(entity) if hasattr(loader, "persist_entity") else False

    def _remove_repository_entity(self, entity_id, dataset_name=None):
        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "remove_entity"):
            return False
        return loader.remove_entity(entity_id, dataset_name=dataset_name)

    def get_year_context_label(self):
        year = int(self.year)
        root_entity = self.get_root_entity() or {}
        relative_context = self._get_relative_year_context(root_entity)

        if relative_context is None:
            return f"Year {year}"

        epoch_year = relative_context["epoch_year"]
        label = relative_context["label"]
        delta = year - epoch_year

        if delta == 0:
            return f"Year {year} | {label} +0"

        if delta > 0:
            return f"Year {year} | {delta} years since {label}"

        return f"Year {year} | {abs(delta)} years before {label}"

    def _get_relative_year_context(self, root_entity):
        if not root_entity:
            return None

        context_candidates = []
        for key in ("relative_year_context", "relative_time_context", "history_epoch"):
            value = root_entity.get(key)
            if isinstance(value, list):
                context_candidates.extend(value)
            elif isinstance(value, dict):
                context_candidates.append(value)

        for context in context_candidates:
            epoch_year = None
            for key in ("epoch_year", "start_year", "year"):
                epoch_year = self._normalize_year_value(context.get(key))
                if epoch_year is not None:
                    break

            if epoch_year is None:
                continue

            label = (
                context.get("label")
                or context.get("name")
                or context.get("description")
                or f"arrival on {self.get_root_name()}"
            )
            return {"epoch_year": epoch_year, "label": str(label)}

        epoch_year = None
        for key in (
            "history_epoch_year",
            "arrival_year",
            "settlement_start_year",
            "relative_year_start",
        ):
            epoch_year = self._normalize_year_value(root_entity.get(key))
            if epoch_year is not None:
                break

        if epoch_year is None:
            return None

        label = (
            root_entity.get("history_epoch_label")
            or root_entity.get("arrival_label")
            or f"arrival on {self.get_root_name()}"
        )
        return {"epoch_year": epoch_year, "label": str(label)}

    def _normalize_year_value(self, value):
        yearer = getattr(self.world_model, "yearer", None)
        if yearer is not None and hasattr(yearer, "normalize_year"):
            return yearer.normalize_year(value)

        return parse_year(value)

    def get_root_entity(self):
        return self.world_model.get_entity(self.context.root_entity_id)

    def get_root_name(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return self.context.root_entity_id
        return root_entity.get("name", self.context.root_entity_id)

    def world_to_surface_lon_lat(self, world_x, world_y):
        root = self.get_root_entity()
        if not isinstance(root, dict) or root.get("location_class") not in {"planet", "moon"}:
            return None
        rect = self._planet_rect_from_entity(root)
        width = max(1e-9, float(rect.get("width_world", 1.0) or 1.0))
        height = max(1e-9, float(rect.get("height_world", 1.0) or 1.0))
        nx = (float(world_x) - (rect["x"] - width * 0.5)) / width
        ny = (float(world_y) - (rect["y"] - height * 0.5)) / height
        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            return None
        source_nx, source_ny = unproject_normalized_point(
            nx, ny, self.map_projection_focus_x, self.map_projection_focus_y,
        )
        return source_nx * 360.0 - 180.0, 90.0 - source_ny * 180.0

    def get_projection_focus_label(self):
        if (self.get_root_entity() or {}).get("location_class") not in {"planet", "moon"}:
            return "Regional projection | Drag to pan; double-click to center; zoom selects refinement footprint"
        longitude = (self.map_projection_focus_x * 360.0 + 180.0) % 360.0 - 180.0
        latitude = -self.map_projection_focus_y * 180.0
        return f"Globe center: {longitude:+.1f} deg, {latitude:+.1f} deg | Drag to pan; double-click to refocus"
        return f"Globe center: {longitude:+.1f}°, {latitude:+.1f}° | Drag to rotate"

    def can_regenerate_region(self):
        root = self.get_root_entity()
        if not isinstance(root, dict) or not isinstance(root.get("heightmap_model"), dict) or self.is_map_editor_active():
            return False
        from simulations.world_gen.regional_refinement import (
            MAX_DETAIL_LEVEL, map_physical_dimensions_m, refinement_floor_reached,
        )
        width_m, height_m = map_physical_dimensions_m(root)
        if width_m > 0.0 and height_m > 0.0:
            return not refinement_floor_reached(root)
        return int(root.get("map_detail_level", 0) or 0) < MAX_DETAIL_LEVEL

    def can_regenerate_current_region(self):
        root = self.get_root_entity()
        if not isinstance(root, dict) or self.is_map_editor_active():
            return False
        return self._current_region_regeneration_request() is not None

    def get_current_region_regeneration_label(self):
        root = self.get_root_entity() or {}
        profile = root.get("map_detail_profile") or {}
        detail_label = profile.get("label")
        return f"Regenerate This Region - {detail_label}" if detail_label else "Regenerate This Region"

    def _surface_models_for_generation(self, entity):
        if not isinstance(entity, dict):
            return None
        if entity.get("id") == getattr(self.context, "root_entity_id", None):
            return self._root_surface_context()
        if self._grid_rows(entity.get("heightmap_model")):
            return {
                "source": entity,
                "heightmap_model": entity.get("heightmap_model"),
                "water_cycle_model": entity.get("water_cycle_model"),
                "coastal_geomorphology_model": entity.get("coastal_geomorphology_model"),
            }
        return self._inherited_surface_context(entity)

    def _current_region_regeneration_request(self):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return None
        is_generated = (
            root.get("location_class") == "generated_region"
            and root.get("location_role") == "map_refinement_region"
        )
        if is_generated:
            parent_id = root.get("refinement_parent_map_id") or self._structural_parent_location_id(root)
            generation_root = self.world_model.get_entity(parent_id) if parent_id else None
            requested_bounds = root.get("bounds") or {}
        else:
            # Authored regions opened through "Open Region Map" inherit their
            # terrain from a higher map. Generate a full-footprint refinement
            # beneath that authored region so it remains the semantic parent.
            if not self._structural_parent_location_id(root):
                return None
            generation_root = root
            requested_bounds = self._entity_map_bounds(root) or {}

        parent_bounds = self._entity_map_bounds(generation_root)
        surface_context = self._surface_models_for_generation(generation_root)
        if (
            not isinstance(generation_root, dict)
            or not isinstance(parent_bounds, dict)
            or not isinstance(surface_context, dict)
            or not self._grid_rows(surface_context.get("heightmap_model"))
            or requested_bounds.get("type", "bbox") != "bbox"
        ):
            return None

        generation_parent = dict(generation_root)
        generation_parent["bounds"] = {"type": "bbox", **{
            key: float(parent_bounds[key])
            for key in ("min_x", "max_x", "min_y", "max_y")
        }}
        for field_name in (
            "heightmap_model",
            "water_cycle_model",
            "coastal_geomorphology_model",
        ):
            model = surface_context.get(field_name)
            if isinstance(model, dict):
                generation_parent[field_name] = model
        source = surface_context.get("source")
        if isinstance(source, dict):
            for field_name in (
                "atmosphere_model",
                "atmosphere_visual_model",
                "surface_palette",
                "surface_weathering_model",
                "natural_material_model",
                "terrain_seed_model",
                "display_color",
            ):
                if generation_parent.get(field_name) is None and source.get(field_name) is not None:
                    generation_parent[field_name] = source[field_name]

        bounds = {
            key: float(requested_bounds[key])
            for key in ("min_x", "max_x", "min_y", "max_y")
        }
        return (
            generation_parent,
            bounds,
            str(root.get("refinement_seed_suffix") or "regional-refinement"),
            (
                (root.get("generated_truth_lineage") or {}).get(
                    "focus_occurrence_id"
                )
                or (root.get("regional_material_model") or {}).get(
                    "focus_occurrence_id"
                )
            ),
        )

    def regenerate_current_region(self):
        """Re-run the open refinement from its parent using the same footprint."""
        if self.is_map_editor_active():
            return None
        from simulations.world_gen.regional_refinement import generate_refined_region

        request = self._current_region_regeneration_request()
        if request is None:
            return None
        generation_parent, bounds, seed_suffix, focus_occurrence_id = request
        parent_heightmap = generation_parent.get("heightmap_model") or {}
        parent_grid = parent_heightmap.get("sample_grid") or {}
        logger.info(
            "[RegionalRefinement] Starting regeneration "
            f"parent={generation_parent.get('id')} "
            f"level={int(generation_parent.get('map_detail_level', 0) or 0) + 1} "
            f"bounds={bounds} "
            f"source_uv={parent_heightmap.get('source_uv_bounds')} "
            f"parent_grid={parent_grid.get('width')}x{parent_grid.get('height')} "
            f"physical_m={parent_heightmap.get('region_width_m')}x"
            f"{parent_heightmap.get('region_height_m')}"
        )
        regenerated = generate_refined_region(
            self.world_model,
            generation_parent,
            bounds,
            seed_suffix=seed_suffix,
            focus_occurrence_id=focus_occurrence_id,
            sample_dimensions=getattr(self.context, "regional_sample_dimensions", None),
            feedback_iterations=getattr(self.context, "regional_feedback_iterations", None),
            storage_root=getattr(self.context, "worldgen_storage_root", None),
        )
        regenerated_heightmap = (regenerated or {}).get("heightmap_model") or {}
        regenerated_grid = regenerated_heightmap.get("sample_grid") or {}
        logger.info(
            "[RegionalRefinement] Regeneration stored "
            f"entity={(regenerated or {}).get('id')} "
            f"bounds={(regenerated or {}).get('bounds')} "
            f"source_uv={regenerated_heightmap.get('source_uv_bounds')} "
            f"grid={regenerated_grid.get('width')}x{regenerated_grid.get('height')} "
            f"physical_m={regenerated_heightmap.get('region_width_m')}x"
            f"{regenerated_heightmap.get('region_height_m')}"
        )
        self._invalidate_layer_cache()
        return regenerated

    def refresh_generated_map_layers(self):
        """Discard cached map layers after a refinement changes repository truth."""
        self._invalidate_layer_cache()
        return True

    def can_reset_planet_view(self):
        root = self.get_root_entity()
        return bool(isinstance(root, dict) and root.get("location_class") in {"planet", "moon"} and self._root_has_visual_surface())

    def reset_planet_view(self):
        if not self.can_reset_planet_view():
            return False
        self.map_projection_focus_x = 0.0
        self.map_projection_focus_y = 0.0
        self._reset_camera_drag()
        self._invalidate_layer_cache()
        return True

    def _is_map_refocus_double_click(self, screen_pos):
        if self._map_focus_last_click_time is None or self._map_focus_last_click_screen_pos is None:
            return False
        if time.monotonic() - self._map_focus_last_click_time > self.DRAFT_DOUBLE_CLICK_SECONDS:
            return False
        dx = float(screen_pos[0]) - float(self._map_focus_last_click_screen_pos[0])
        dy = float(screen_pos[1]) - float(self._map_focus_last_click_screen_pos[1])
        return dx * dx + dy * dy <= self.DRAFT_DOUBLE_CLICK_DISTANCE_PX ** 2

    def _record_map_focus_click(self, screen_pos):
        self._map_focus_last_click_time = time.monotonic()
        self._map_focus_last_click_screen_pos = tuple(screen_pos)

    def _refocus_map_at_screen_point(self, camera, screen_pos):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return False
        world_x, world_y = self._screen_to_world(camera, screen_pos)
        if root.get("location_class") in {"planet", "moon"} and self._root_has_visual_surface():
            lon_lat = self.world_to_surface_lon_lat(world_x, world_y)
            if lon_lat is None:
                return False
            longitude, latitude = lon_lat
            self.map_projection_focus_x = (float(longitude) / 360.0) % 1.0
            self.map_projection_focus_y = max(-0.5, min(0.5, -float(latitude) / 180.0))
            # Re-centre the camera as well as the spherical projection.  A
            # prior pan must not leave the chosen point off-centre after it
            # becomes the new globe focus.
            rect = self._planet_rect_from_entity(root)
            camera.x = float(rect["x"])
            camera.y = float(rect["y"])
            self._invalidate_layer_cache()
        else:
            camera.x = float(world_x)
            camera.y = float(world_y)
        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        return True

    def _focus_material_occurrence(self, camera, layer):
        if (
            camera is None
            or not isinstance(layer, dict)
            or not isinstance(layer.get("material_occurrence"), dict)
        ):
            return False
        try:
            focus_zoom = float(layer.get("material_focus_zoom") or 0.0)
            center_x = float(layer.get("x"))
            center_y = float(layer.get("y"))
        except (TypeError, ValueError):
            return False
        if focus_zoom <= 0.0:
            return False
        occurrence = layer["material_occurrence"]
        occurrence_id = str(occurrence.get("id") or "")
        if occurrence_id:
            self.selected_material_occurrence_id = occurrence_id
            self.active_material_heatmap_layer_id = occurrence_id
        camera.x = center_x
        camera.y = center_y
        camera.zoom = min(
            float(self.max_zoom),
            max(float(getattr(camera, "zoom", 1.0) or 1.0), focus_zoom),
        )
        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        return True

    def _selected_material_occurrence(self, root_entity=None):
        occurrence_id = str(self.selected_material_occurrence_id or "")
        if not occurrence_id:
            return None
        root_entity = root_entity or self.get_root_entity()
        regional_model = (
            root_entity.get("regional_material_model")
            if isinstance(root_entity, dict)
            else None
        )
        if not isinstance(regional_model, dict):
            return None
        return next(
            (
                occurrence
                for occurrence in regional_model.get("occurrences") or []
                if isinstance(occurrence, dict)
                and str(occurrence.get("id") or "") == occurrence_id
            ),
            None,
        )

    def get_next_detail_level_label(self):
        from simulations.world_gen.regional_refinement import MAX_DETAIL_LEVEL, detail_level_spec
        current = int((self.get_root_entity() or {}).get("map_detail_level", 0) or 0)
        level = min(MAX_DETAIL_LEVEL, current + 1)
        suffix = " (toward 10 m)" if current >= MAX_DETAIL_LEVEL else ""
        return f"Regenerate Region - {detail_level_spec(level)['label']}{suffix}"

    @staticmethod
    def _format_refinement_distance(distance_m):
        distance_m = max(0.0, float(distance_m or 0.0))
        if distance_m >= 1_000_000.0:
            return f"{distance_m / 1_000_000.0:.2g} Mm"
        if distance_m >= 1_000.0:
            return f"{distance_m / 1_000.0:.3g} km"
        if distance_m >= 1.0:
            return f"{distance_m:.3g} m"
        return f"{distance_m * 100.0:.2g} cm"

    def get_map_generation_detail_label(self):
        from simulations.world_gen.regional_refinement import map_physical_dimensions_m
        root = self.get_root_entity() or {}
        level = int(root.get("map_detail_level", 0) or 0)
        profile = root.get("map_detail_profile") or {}
        heightmap = root.get("heightmap_model") or {}
        water = root.get("water_cycle_model") or {}
        drainage = water.get("drainage_network_model") or {}
        level_label = profile.get("label") or ("Planetary" if level == 0 else f"LOD {level}")
        width_m, height_m = map_physical_dimensions_m(root)
        grid = heightmap.get("sample_grid") or {}
        sample_spacing = max(
            width_m / max(1, int(grid.get("width", 1) or 1) - 1),
            height_m / max(1, int(grid.get("height", 1) or 1) - 1),
        )
        extent_label = ""
        if width_m > 0.0 and height_m > 0.0:
            extent_label = (
                f" | {self._format_refinement_distance(width_m)} x {self._format_refinement_distance(height_m)}"
                f" | {self._format_refinement_distance(sample_spacing)}/sample"
            )
        return (
            f"Detail: {level_label}{extent_label} | "
            f"{len(drainage.get('drainage_basins') or [])} basins, "
            f"{int(drainage.get('river_segment_count', 0) or 0)} river segments, "
            f"{int(drainage.get('lake_count', 0) or 0)} lakes"
        )

    def regenerate_visible_region(self, camera, viewport_width, viewport_height, viewport_rect=None):
        if not self.can_regenerate_region() or camera is None:
            return None
        from simulations.world_gen.regional_refinement import generate_refined_region
        root = self.get_root_entity()
        rect = self._planet_rect_from_entity(root)
        parent_bounds = {"type": "bbox", "min_x": rect["x"] - rect["width_world"] * 0.5,
                         "max_x": rect["x"] + rect["width_world"] * 0.5,
                         "min_y": rect["y"] - rect["height_world"] * 0.5,
                         "max_y": rect["y"] + rect["height_world"] * 0.5}
        parent_width = parent_bounds["max_x"] - parent_bounds["min_x"]
        parent_height = parent_bounds["max_y"] - parent_bounds["min_y"]
        visible_bounds = self._visible_refinement_bounds(
            camera, viewport_width, viewport_height, parent_bounds, root, viewport_rect=viewport_rect,
        )
        if visible_bounds is None:
            return None
        region_width = min(parent_width, visible_bounds["max_x"] - visible_bounds["min_x"])
        region_height = min(parent_height, visible_bounds["max_y"] - visible_bounds["min_y"])
        if region_width >= parent_width * 0.98 and region_height >= parent_height * 0.98:
            logger.info(
                "[MapSimulation] Zoom into a region before generating a refinement patch",
                key="map_refinement_requires_zoom",
                interval=0.5,
            )
            return None
        center_x = (visible_bounds["min_x"] + visible_bounds["max_x"]) * 0.5
        center_y = (visible_bounds["min_y"] + visible_bounds["max_y"]) * 0.5
        focused_occurrence = self._selected_material_occurrence(root)
        if isinstance(focused_occurrence, dict):
            occurrence_center = focused_occurrence.get("center") or {}
            center_x = parent_bounds["min_x"] + float(
                occurrence_center.get("x", 0.5) or 0.5
            ) * parent_width
            center_y = parent_bounds["min_y"] + float(
                occurrence_center.get("y", 0.5) or 0.5
            ) * parent_height
        min_x = max(parent_bounds["min_x"], min(parent_bounds["max_x"] - region_width, center_x - region_width * 0.5))
        min_y = max(parent_bounds["min_y"], min(parent_bounds["max_y"] - region_height, center_y - region_height * 0.5))
        generation_parent = dict(root)
        generation_parent["bounds"] = parent_bounds
        region = generate_refined_region(self.world_model, generation_parent, {
            "min_x": min_x, "max_x": min_x + region_width, "min_y": min_y, "max_y": min_y + region_height,
        }, focus_occurrence_id=self.selected_material_occurrence_id,
        sample_dimensions=getattr(self.context, "regional_sample_dimensions", None),
        feedback_iterations=getattr(self.context, "regional_feedback_iterations", None),
        storage_root=getattr(self.context, "worldgen_storage_root", None))
        self._invalidate_layer_cache()
        return region

    def _visible_refinement_bounds(self, camera, viewport_width, viewport_height, parent_bounds, root, viewport_rect=None):
        """Map the actually visible map rectangle back into the parent's source space."""
        rect = self._planet_rect_from_entity(root)
        center = camera.world_to_screen((rect["x"], rect["y"]))
        if center is None:
            return None
        pixel_w = max(1.0, float(rect["width_world"]) * float(camera.zoom))
        pixel_h = max(1.0, float(rect["height_world"]) * float(camera.zoom))
        viewport_left = float(getattr(viewport_rect, "left", 0.0) if viewport_rect is not None else 0.0)
        viewport_right = float(getattr(viewport_rect, "right", viewport_width) if viewport_rect is not None else viewport_width)
        viewport_top = float(getattr(viewport_rect, "top", 0.0) if viewport_rect is not None else 0.0)
        viewport_bottom = float(getattr(viewport_rect, "bottom", viewport_height) if viewport_rect is not None else viewport_height)
        screen_left = max(viewport_left, float(center[0]) - pixel_w * 0.5)
        screen_right = min(viewport_right, float(center[0]) + pixel_w * 0.5)
        screen_top = max(viewport_top, float(center[1]) - pixel_h * 0.5)
        screen_bottom = min(viewport_bottom, float(center[1]) + pixel_h * 0.5)
        if screen_right <= screen_left or screen_bottom <= screen_top:
            return None

        if root.get("location_class") not in {"planet", "moon"}:
            top_left = self._screen_to_world(camera, (screen_left, screen_top))
            bottom_right = self._screen_to_world(camera, (screen_right, screen_bottom))
            return {
                "min_x": max(parent_bounds["min_x"], min(float(top_left[0]), float(bottom_right[0]))),
                "max_x": min(parent_bounds["max_x"], max(float(top_left[0]), float(bottom_right[0]))),
                "min_y": max(parent_bounds["min_y"], min(float(top_left[1]), float(bottom_right[1]))),
                "max_y": min(parent_bounds["max_y"], max(float(top_left[1]), float(bottom_right[1]))),
            }

        sampled_uv = []
        for iy in range(7):
            sy = screen_top + (screen_bottom - screen_top) * iy / 6.0
            for ix in range(9):
                sx = screen_left + (screen_right - screen_left) * ix / 8.0
                world_x, world_y = self._screen_to_world(camera, (sx, sy))
                lon_lat = self.world_to_surface_lon_lat(world_x, world_y)
                if lon_lat is None:
                    continue
                longitude, latitude = lon_lat
                sampled_uv.append(((float(longitude) + 180.0) / 360.0, (90.0 - float(latitude)) / 180.0))
        if not sampled_uv:
            return None
        center_u = (self.map_projection_focus_x + 0.5) % 1.0
        unwrapped_u = []
        for u, _v in sampled_uv:
            while u - center_u > 0.5:
                u -= 1.0
            while center_u - u > 0.5:
                u += 1.0
            unwrapped_u.append(u)
        min_u, max_u = min(unwrapped_u), max(unwrapped_u)
        min_v, max_v = min(v for _u, v in sampled_uv), max(v for _u, v in sampled_uv)
        # A single persistent rectangular child cannot straddle the storage seam;
        # choose the contiguous side containing the current focus in that rare case.
        if min_u < 0.0 or max_u > 1.0:
            span = min(1.0, max_u - min_u)
            min_u = max(0.0, min(1.0 - span, center_u - span * 0.5))
            max_u = min_u + span
        min_u, max_u = max(0.0, min_u), min(1.0, max_u)
        min_v, max_v = max(0.0, min_v), min(1.0, max_v)
        parent_width = parent_bounds["max_x"] - parent_bounds["min_x"]
        parent_height = parent_bounds["max_y"] - parent_bounds["min_y"]
        return {
            "min_x": parent_bounds["min_x"] + min_u * parent_width,
            "max_x": parent_bounds["min_x"] + max_u * parent_width,
            "min_y": parent_bounds["min_y"] + min_v * parent_height,
            "max_y": parent_bounds["min_y"] + max_v * parent_height,
        }

    def _refined_region_models(self):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return []
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {})
        root_id = str(root.get("id") or "")
        root_planet_id = root.get("refinement_root_planet_id") or (root_id if root.get("location_class") in {"planet", "moon"} else None)
        root_bounds = self._entity_map_bounds(root)
        if not isinstance(root_bounds, dict):
            return []
        # Refinement bounds are stored in the coordinate frame of the open
        # map.  Polygon-authored regions do not have a rectangular ``bounds``
        # record, so routing them through the planet-rectangle fallback used
        # the default 360 x 180 frame.  A child covering the complete authored
        # polygon was consequently composited as a tiny rectangle near the
        # middle of its own regional map.  Normalize against the actual map
        # envelope for every root shape instead.
        left, top = float(root_bounds["min_x"]), float(root_bounds["min_y"])
        width = max(1e-9, float(root_bounds["max_x"]) - left)
        height = max(1e-9, float(root_bounds["max_y"]) - top)
        # A location's own generated_region descendant (refinement_parent_map_id
        # == root_id) is the *source* the base heightmap layer is already built
        # from, not a nested child to overlay on top of it -- descends_from()
        # below matches it too, since that's structurally the same relationship
        # a real nested subregion has. Compositing a region onto its own base
        # doubles the (expensive) true-color render and can leave the result
        # mis-sized against the destination rect. Exclude it explicitly.
        own_generated_id = (self._own_generated_region(root) or {}).get("id")

        def descends_from(candidate):
            current, visited = candidate, set()
            while isinstance(current, dict):
                parent_id = (
                    current.get("refinement_parent_map_id")
                    or self._structural_parent_location_id(current)
                )
                if parent_id == root_id:
                    return True
                if not parent_id or parent_id in visited:
                    return False
                visited.add(parent_id)
                current = self.world_model.get_entity(parent_id)
            return False

        models = []
        for candidate in entities.values():
            if not isinstance(candidate, dict) or not candidate.get("map_detail_level") or not descends_from(candidate):
                continue
            if own_generated_id and candidate.get("id") == own_generated_id:
                continue
            if root_planet_id and candidate.get("refinement_root_planet_id") != root_planet_id:
                continue
            bounds = candidate.get("bounds") or {}
            if bounds.get("type") != "bbox":
                continue
            uv_bounds = {"min_u": (float(bounds["min_x"]) - left) / width,
                         "max_u": (float(bounds["max_x"]) - left) / width,
                         "min_v": (float(bounds["min_y"]) - top) / height,
                         "max_v": (float(bounds["max_y"]) - top) / height}
            logger.debug(
                "[RegionalRefinement] Composite placement "
                f"root={root_id} child={candidate.get('id')} "
                f"root_bounds={root_bounds} child_bounds={bounds} "
                f"normalized={uv_bounds}",
                key=(
                    "regional_refinement_composite_"
                    f"{root_id}_{candidate.get('id')}"
                ),
                interval=1.0,
            )
            if any(
                value < -0.001 or value > 1.001
                for value in uv_bounds.values()
            ):
                # A refinement_parent_map_id can outlive its parent: a draft
                # id can be reused for an unrelated new region (e.g. the
                # user deletes/redraws a region and the id allocator hands
                # the same id to a different polygon), leaving the old
                # generated_region entity as an orphan that still claims
                # the reused id as its parent. Its bounds then no longer fit
                # inside the "parent" it's compositing against at all --
                # treat that as disqualifying rather than merely worth a
                # warning, since compositing it in produces a wildly
                # out-of-frame overlay.
                logger.warn(
                    "[RegionalRefinement] Child bounds extend beyond the open "
                    f"map frame root={root_id} child={candidate.get('id')} "
                    f"root_bounds={root_bounds} child_bounds={bounds} "
                    f"normalized={uv_bounds}"
                )
                continue
            # A refinement covering the entire planet is not a regional LOD.
            # Older builds could create one while fully zoomed out; applying it
            # replaced the authored planet and made the map appear duplicated.
            if (
                root.get("location_class") in {"planet", "moon"}
                and
                uv_bounds["max_u"] - uv_bounds["min_u"] >= 0.98
                and uv_bounds["max_v"] - uv_bounds["min_v"] >= 0.98
            ):
                continue
            models.append({
                "entity_id": candidate.get("id"),
                "detail_level": int(candidate.get("map_detail_level", 0) or 0),
                "refinement_revision": int(candidate.get("refinement_revision", 0) or 0),
                "heightmap_model": candidate.get("heightmap_model"),
                "water_cycle_model": candidate.get("water_cycle_model"),
                "material_heatmap_model": candidate.get("material_heatmap_model"),
                "surface_exposure_model": candidate.get("surface_exposure_model"),
                "natural_material_model": candidate.get("natural_material_model"),
                "surface_evolution_model": candidate.get("surface_evolution_model"),
                "atmosphere_model": candidate.get("atmosphere_model"),
                "surface_palette": candidate.get("surface_palette"),
                "true_color_model": candidate.get("true_color_model"),
                "uv_bounds": uv_bounds,
            })
        return sorted(models, key=lambda item: (item["detail_level"], item.get("refinement_revision", 0)))

    def _relation_entity_ids(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            candidate = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
            return [candidate] if candidate else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                ids.extend(self._relation_entity_ids(item))
            return ids
        return []

    def _structural_parent_location_id(self, entity):
        if not isinstance(entity, dict):
            return None

        entity_id = entity.get("id")
        for field_key in ("parent_location", "parent_entity", "parent_body"):
            for parent_id in self._relation_entity_ids(entity.get(field_key)):
                parent = self.world_model.get_entity(parent_id)
                if parent_id and parent_id != entity_id and self._is_location_entity(parent):
                    return parent_id

        for parent_id in self._relation_entity_ids(entity.get("parents")):
            parent = self.world_model.get_entity(parent_id)
            if parent_id and parent_id != entity_id and self._is_location_entity(parent):
                return parent_id

        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        for candidate_id, candidate in entities.items():
            if candidate_id == entity_id or not self._is_location_entity(candidate):
                continue
            if entity_id in self._relation_entity_ids(candidate.get("constituents")):
                return candidate_id

        return None

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

    def get_parent_root_entity_id(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None
        return self._structural_parent_location_id(root_entity)

    def get_scope_breadcrumb(self):
        """
        Return a root breadcrumb from top ancestor down to the current root.
        """
        breadcrumb = []
        visited = set()
        current_entity = self.get_root_entity()

        while current_entity:
            entity_id = current_entity.get("id")
            if entity_id in visited:
                break

            visited.add(entity_id)
            breadcrumb.append(current_entity.get("name", entity_id))

            parent_id = self._structural_parent_location_id(current_entity)
            if not parent_id:
                break

            current_entity = self.world_model.get_entity(parent_id)

        breadcrumb.reverse()
        return breadcrumb

    def _planet_world_size_from_radius(self, radius_m):
        """
        Derive a 2:1 projected planet frame from physical radius.

        Output world units follow the map convention:
        * 1 world unit ~= 1 projected longitude/latitude degree
        """
        radius_m = float(radius_m)

        circumference_m = 2.0 * math.pi * radius_m
        width_world = circumference_m / self.MAP_METERS_PER_WORLD_UNIT
        height_world = width_world / 2.0

        return width_world, height_world

    def _planet_canvas_size_from_radius(self, radius_m):
        """
        Derive the canonical planet map canvas size in pixels.

        Rule:
        * one projected degree-ish world unit per pixel
        * 2:1 aspect ratio
        """
        width_world, height_world = self._planet_world_size_from_radius(radius_m)

        width_px = max(1, int(round(width_world)))
        height_px = max(1, int(round(height_world)))

        return width_px, height_px

    def _planet_bbox_matches_radius_scale(self, width_world, height_world, radius_m):
        try:
            width_world = abs(float(width_world))
            height_world = abs(float(height_world))
            radius_width, radius_height = self._planet_world_size_from_radius(radius_m)
        except (TypeError, ValueError):
            return True
        if width_world <= 0.0 or height_world <= 0.0:
            return False
        aspect = width_world / max(0.0001, height_world)
        if not 1.6 <= aspect <= 2.4:
            return False
        return width_world >= radius_width * 0.5 and height_world >= radius_height * 0.5

    def _planet_rect_from_radius(self, center_x, center_y, radius_m):
        width_world, height_world = self._planet_world_size_from_radius(radius_m)
        canvas_w, canvas_h = self._planet_canvas_size_from_radius(radius_m)
        center_x, center_y = float(center_x), float(center_y)
        return {
            "x": center_x,
            "y": center_y,
            "width_world": width_world,
            "height_world": height_world,
            "canvas_width_px": canvas_w,
            "canvas_height_px": canvas_h,
        }

    def _planet_rect_from_entity(self, entity):
        """
        Resolve a planet rect from either bbox or radius data.
        """
        coords = entity.get("coords") or {}
        bounds = entity.get("bounds") or {}

        center_x = 0.0
        center_y = 0.0

        if coords.get("type") == "point":
            center_x = coords.get("x", 0.0)
            center_y = coords.get("y", 0.0)

        radius_m = entity.get("radius_m")

        if bounds.get("type") == "bbox":
            min_x = bounds.get("min_x", -self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            max_x = bounds.get("max_x", self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            min_y = bounds.get("min_y", -self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            max_y = bounds.get("max_y", self.DEFAULT_PLANET_WORLD_HEIGHT / 2)

            width_world = max_x - min_x
            height_world = max_y - min_y

            if (
                radius_m not in (None, "")
                and not self._planet_bbox_matches_radius_scale(width_world, height_world, radius_m)
            ):
                return self._planet_rect_from_radius(center_x, center_y, radius_m)

            if coords.get("type") != "point":
                center_x = (min_x + max_x) / 2.0
                center_y = (min_y + max_y) / 2.0

            center_x, center_y = float(center_x), float(center_y)
            canvas_w = entity.get("map_canvas_width_px", max(1, int(round(width_world))))
            canvas_h = entity.get("map_canvas_height_px", max(1, int(round(height_world))))

            return {
                "x": center_x,
                "y": center_y,
                "width_world": width_world,
                "height_world": height_world,
                "canvas_width_px": canvas_w,
                "canvas_height_px": canvas_h,
            }

        if bounds.get("type") == "radius":
            radius_m = bounds.get("value", 0.0)
            width_world, height_world = self._planet_world_size_from_radius(radius_m)
            canvas_w, canvas_h = self._planet_canvas_size_from_radius(radius_m)
            center_x, center_y = float(center_x), float(center_y)

            return {
                "x": center_x,
                "y": center_y,
                "width_world": width_world,
                "height_world": height_world,
                "canvas_width_px": canvas_w,
                "canvas_height_px": canvas_h,
            }

        if radius_m not in (None, ""):
            try:
                return self._planet_rect_from_radius(center_x, center_y, radius_m)
            except (TypeError, ValueError):
                pass

        center_x, center_y = float(center_x), float(center_y)
        return {
            "x": center_x,
            "y": center_y,
            "width_world": self.DEFAULT_PLANET_WORLD_WIDTH,
            "height_world": self.DEFAULT_PLANET_WORLD_HEIGHT,
            "canvas_width_px": int(self.DEFAULT_PLANET_WORLD_WIDTH),
            "canvas_height_px": int(self.DEFAULT_PLANET_WORLD_HEIGHT),
        }

    def _resolve_root_bounds(self):
        """
        Resolve one stable world-space rectangle for the current root scope.

        Rules:
        * bbox roots use their bbox directly
        * planet roots use bbox if present, otherwise derive a 2:1 frame from radius
        * point roots get a small synthetic scope so reset/clamping still work
        * final fallback is the default planet-sized rectangle around origin
        """
        root_entity = self.get_root_entity()
        authoring_fallback = {
            "min_x": -100.0,
            "max_x": 100.0,
            "min_y": -75.0,
            "max_y": 75.0,
        }
        if not root_entity:
            return dict(authoring_fallback)

        coords = root_entity.get("coords") or {}
        bounds = root_entity.get("bounds") or {}

        if root_entity.get("location_class") == "building" and bounds.get("type") not in {"bbox", "polygon"}:
            return {
                "min_x": -24.0,
                "max_x": 24.0,
                "min_y": -16.0,
                "max_y": 16.0,
            }

        if (
            root_entity.get("location_class") in {"planet", "moon"}
            and bounds.get("type") == "bbox"
            and root_entity.get("radius_m") not in (None, "")
        ):
            min_x = bounds.get("min_x", -self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            max_x = bounds.get("max_x", self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            min_y = bounds.get("min_y", -self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            max_y = bounds.get("max_y", self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            if not self._planet_bbox_matches_radius_scale(max_x - min_x, max_y - min_y, root_entity.get("radius_m")):
                rect = self._planet_rect_from_entity(root_entity)
                half_w = rect["width_world"] / 2.0
                half_h = rect["height_world"] / 2.0
                return {
                    "min_x": rect["x"] - half_w,
                    "max_x": rect["x"] + half_w,
                    "min_y": rect["y"] - half_h,
                    "max_y": rect["y"] + half_h,
                }

        if bounds.get("type") == "bbox":
            min_x = bounds.get("min_x", -self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            max_x = bounds.get("max_x", self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            min_y = bounds.get("min_y", -self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            max_y = bounds.get("max_y", self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            world_bounds = self._map_bbox_to_world_bounds(min_x, max_x, min_y, max_y)
            return {
                "min_x": world_bounds["min_x"],
                "max_x": world_bounds["max_x"],
                "min_y": world_bounds["min_y"],
                "max_y": world_bounds["max_y"],
            }

        if bounds.get("type") in {"polygon", "multipolygon"}:
            points = self._get_geometry_points(bounds)
            if len(points) >= 3:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                world_bounds = self._map_bbox_to_world_bounds(min(xs), max(xs), min(ys), max(ys))
                return {
                    "min_x": world_bounds["min_x"],
                    "max_x": world_bounds["max_x"],
                    "min_y": world_bounds["min_y"],
                    "max_y": world_bounds["max_y"],
                }

        center_x = 0.0
        center_y = 0.0
        if coords.get("type") == "point":
            center_x, center_y = self._map_point_to_world(
                coords.get("x", 0.0),
                coords.get("y", 0.0),
            )

        if root_entity.get("location_class") == "planet":
            rect = self._planet_rect_from_entity(root_entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0

            return {
                "min_x": rect["x"] - half_w,
                "max_x": rect["x"] + half_w,
                "min_y": rect["y"] - half_h,
                "max_y": rect["y"] + half_h,
            }

        if coords.get("type") == "point":
            point_half_extent = 500.0
            return {
                "min_x": center_x - point_half_extent,
                "max_x": center_x + point_half_extent,
                "min_y": center_y - point_half_extent,
                "max_y": center_y + point_half_extent,
            }

        return dict(authoring_fallback)

    def _color_for_entity(self, entity):
        card_color = self._coerce_hex_color(entity.get("card_color"))
        if card_color is not None:
            return card_color

        display_color = entity.get("display_color")
        if isinstance(display_color, (list, tuple)) and len(display_color) >= 3:
            try:
                return (int(display_color[0]), int(display_color[1]), int(display_color[2]))
            except (TypeError, ValueError):
                pass

        location_class = entity.get("location_class")

        if location_class == "planet":
            return (70, 90, 120)

        if location_class == "continent":
            return (120, 140, 170)

        if location_class == "country":
            return (155, 170, 195)

        if location_class == "state":
            return (166, 180, 202)

        if location_class == "region":
            return (180, 190, 205)

        if location_class == "city":
            return (220, 220, 220)

        if location_class == "quarter":
            return (212, 210, 198)

        if location_class == "building":
            return (202, 184, 136)

        if location_class == "room":
            return (132, 178, 196)

        return (200, 200, 200)

    def _entity_is_gas_giant(self, entity):
        atmosphere = entity.get("atmosphere_model") if isinstance(entity, dict) else None
        tags = set(entity.get("tags") or []) if isinstance(entity, dict) else set()
        seed = entity.get("world_gen_seed") if isinstance(entity.get("world_gen_seed"), dict) else {}
        class_key = str(
            seed.get("planet_template")
            or seed.get("planet_class")
            or entity.get("world_gen_template")
            or entity.get("planetary_class")
            or entity.get("body_subclass")
            or entity.get("location_class")
            or ""
        ).strip().lower()
        if class_key in {"cratered_airless", "airless_rocky"} or "airless_regolith" in tags:
            return False
        volatile_key = str(seed.get("volatile_inventory") or "").strip().lower()
        try:
            water_fraction = float(seed.get("water_fraction", 1.0) or 0.0)
            radius_earth = float(seed.get("radius_earth", 0.0) or 0.0)
        except (TypeError, ValueError):
            water_fraction = 1.0
            radius_earth = 0.0
        if volatile_key == "none" and water_fraction <= 0.03 and radius_earth < 3.0:
            return False
        return bool(
            entity.get("surface_render_mode") == "gas_giant_bands"
            or entity.get("map_render_mode") == "gas_giant_bands"
            or "gas_giant" in tags
            or class_key in {"gas_giant", "ice_giant", "hot_gas_giant"}
            or (
                isinstance(atmosphere, dict)
                and atmosphere.get("has_solid_surface") is False
                and "solid_surface" not in tags
            )
        )

    def _gas_giant_bands_for_entity(self, entity):
        bands = entity.get("atmosphere_bands")
        if isinstance(bands, list) and bands:
            return bands
        atmosphere = entity.get("atmosphere_model")
        if isinstance(atmosphere, dict):
            try:
                from simulations.world_gen.natural_materials import atmospheric_band_palette

                return atmospheric_band_palette(atmosphere).get("bands") or []
            except ImportError:
                pass
        return []

    def _coerce_hex_color(self, value):
        if not isinstance(value, str):
            return None
        text = value.strip()
        if text.startswith("#"):
            text = text[1:]
        if len(text) != 6:
            return None
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return None

    def _map_point_to_world(self, x, y):
        """
        Convert stored map coordinates to display/world coordinates.

        Authored global data rotates with the same focused spherical projection
        as raster layers. Regional maps retain an identity transform.
        """
        root = self.get_root_entity()
        if isinstance(root, dict) and root.get("location_class") in {"planet", "moon"}:
            focus_x, focus_y = self._vector_projection_focus()
            return project_map_world_point(
                x, y, focus_x, focus_y,
            )
        return float(x), float(y)

    def _vector_projection_focus(self):
        if not self.map_projection_dragging:
            return self.map_projection_focus_x, self.map_projection_focus_y
        return (
            round(float(self.map_projection_focus_x) * 256.0) / 256.0,
            round(float(self.map_projection_focus_y) * 256.0) / 256.0,
        )

    def _vector_projection_focus_key(self):
        focus_x, focus_y = self._vector_projection_focus()
        return round(focus_x, 8), round(focus_y, 8)

    def _world_point_to_map(self, x, y):
        root = self.get_root_entity()
        if isinstance(root, dict) and root.get("location_class") in {"planet", "moon"}:
            return unproject_map_world_point(
                x, y, self.map_projection_focus_x, self.map_projection_focus_y,
            )
        return float(x), float(y)

    def _map_bbox_to_world_bounds(self, min_x, max_x, min_y, max_y):
        return {
            "min_x": min(float(min_x), float(max_x)),
            "max_x": max(float(min_x), float(max_x)),
            "min_y": min(float(min_y), float(max_y)),
            "max_y": max(float(min_y), float(max_y)),
        }

    def _invalidate_layer_cache(self):
        self._layer_cache = None
        self._cache_year = None
        self._cache_layer_kind = None
        self._inherited_surface_context_cache = None
        self._last_hover_pick_screen_pos = None
        self._last_hover_pick_camera_state = None

    def _prepare_layer_cache(self, layers):
        layers = sorted(layers, key=self._render_layer_sort_key)
        for layer in layers:
            if not isinstance(layer, dict) or layer.get("shape") not in {"polygon", "polyline"}:
                continue
            points = layer.get("points") or []
            if len(points) < 2:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            layer["_world_bounds"] = (
                min(xs),
                max(xs),
                min(ys),
                max(ys),
            )
        return layers

    def _render_layer_sort_key(self, layer):
        if not isinstance(layer, dict):
            return (0, 0, 0)
        shape_order = {
            "heightmap_base": -5000,
            "image_rect": -3600,
            "map_rect": -3200,
            "reference_land": -2600,
            "rect": -200,
            "polygon": 0,
            "polyline": 50,
            "marker": 1000,
        }.get(layer.get("shape"), 0)
        draw_order = layer.get("draw_order")
        try:
            draw_order = float(draw_order)
        except (TypeError, ValueError):
            draw_order = shape_order
        depth = int(layer.get("map_hierarchy_depth", 0) or 0)
        pick_priority = int(layer.get("pick_priority", 0) or 0)
        area = float(layer.get("area_world", 0.0) or 0.0)
        return (draw_order, depth, pick_priority, -area)

    def _root_is_building(self):
        root = self.get_root_entity()
        return isinstance(root, dict) and root.get("location_class") == "building"

    def _is_orbital_location(self, entity):
        if not isinstance(entity, dict):
            return False

        location_class = str(entity.get("location_class") or "").strip().lower()
        body_class = str(entity.get("body_class") or "").strip().lower()
        system_role = str(entity.get("system_role") or "").strip().lower()
        location_role = str(entity.get("location_role") or "").strip().lower()
        return (
            location_class in self.ORBITAL_LOCATION_CLASSES
            or body_class in self.ORBITAL_LOCATION_CLASSES
            or system_role in {"orbital_body", "star_system"}
            or location_role in {"orbital_body", "star_system"}
        )

    def _is_surface_map_location(self, entity, *, allow_root=False):
        if not isinstance(entity, dict):
            return False
        if allow_root and entity.get("id") == self.context.root_entity_id:
            return True
        return not self._is_orbital_location(entity)

    def _surface_location_depth(self, entity):
        if not isinstance(entity, dict):
            return 99
        entity_id = entity.get("id")
        if entity_id == self.context.root_entity_id:
            return 0

        visited = set()
        depth = 0
        current = entity
        while isinstance(current, dict):
            current_id = current.get("id")
            if not current_id or current_id in visited:
                return 99
            visited.add(current_id)

            parent_id = self._structural_parent_location_id(current)
            if not parent_id:
                return 99
            depth += 1
            if parent_id == self.context.root_entity_id:
                return depth
            current = self.world_model.get_entity(parent_id)

        return 99

    def _location_min_zoom_for_depth(self, depth, entity=None):
        location_class = str((entity or {}).get("location_class") or "").lower()
        if location_class in {"room", "building", "site", "quarter"}:
            return 12.0
        if location_class in {"city", "settlement"}:
            return 8.0
        if location_class in {"island", "atoll", "archipelago"}:
            return 5.0
        if location_class in {"state", "province"}:
            return 4.5
        if location_class == "country":
            return 3.4
        if location_class in {"river", "waterway"}:
            return 5.0
        if depth <= 1:
            return 0.0
        if depth == 2:
            if location_class in {"continent", "ocean"}:
                return 0.0
            return 2.6
        if depth == 3:
            return 5.5
        if depth == 4:
            return 10.0
        return 16.0

    def _decorate_surface_location_layer(self, layer, entity, area_world=None):
        depth = self._surface_location_depth(entity)
        location_class = str((entity or {}).get("location_class") or "").lower()
        min_zoom = self._location_min_zoom_for_depth(depth, entity)
        root = self.get_root_entity()
        local_site_map = bool(
            isinstance(root, dict)
            and root.get("map_coordinate_space") == "site_meters"
        )
        if local_site_map:
            # Site maps are already opened at their authored local extent.
            # Planetary hierarchy thresholds would otherwise hide buildings
            # until an arbitrary 12 px/m zoom and make the map look empty.
            min_zoom = 0.0
        is_reference_country = (
            location_class == "country"
            and entity.get("bounds_source") == "natural_earth_admin_0_reference"
        )
        if is_reference_country:
            # Keep the geometry selectable at the planet overview without
            # turning the continent view into a political-border map.
            min_zoom = 0.0
            layer["pick_priority"] = 100
            layer["render_when_interacting_only"] = True
        has_reference_land_base = (
            isinstance(root, dict)
            and isinstance(root.get("reference_land_polygons"), dict)
            and bool(root.get("reference_land_polygons", {}).get("polygons"))
        )
        if (
            not local_site_map
            and
            area_world is not None
            and location_class not in {"continent", "ocean"}
            and depth <= 1
            and not is_reference_country
        ):
            try:
                area_value = float(area_world or 0.0)
            except (TypeError, ValueError):
                area_value = 0.0
            if area_value < 150.0:
                min_zoom = max(min_zoom, 8.0)
            elif area_value < 900.0:
                min_zoom = max(min_zoom, 5.0)
        layer["map_hierarchy_depth"] = depth
        layer["min_zoom"] = min_zoom
        layer["draw_order"] = 100 + depth * 100
        layer["is_broad_location_overlay"] = location_class in {"continent", "ocean"}
        if area_world is not None:
            layer["area_world"] = area_world

        if not local_site_map and (
            depth >= 2 or (float(layer.get("min_zoom") or 0.0) >= 3.4 and not is_reference_country)
        ):
            layer["outline_only"] = layer.get("shape") == "polygon"
            layer["suppress_label"] = True
            layer["pickable_min_zoom"] = layer["min_zoom"]
        elif is_reference_country and layer.get("shape") == "polygon":
            layer["outline_only"] = True
            layer["border_width"] = 0
            layer["suppress_label"] = True
        elif depth == 1 and layer.get("shape") == "polygon":
            if has_reference_land_base and location_class in {"continent", "ocean"}:
                layer["outline_only"] = True
                layer["border_color"] = layer.get("color")
                layer["border_width"] = 0 if location_class == "ocean" else 1
                layer["alpha"] = None
                layer["border_alpha"] = None
            elif location_class == "ocean":
                layer["alpha"] = 62
                layer["border_alpha"] = 122
            elif location_class == "continent":
                layer["alpha"] = 128
                layer["border_alpha"] = 210
            else:
                layer["alpha"] = 104
                layer["border_alpha"] = 186
        return layer

    def _entity_has_map_surface(self, entity):
        return isinstance(entity, dict) and any(bool(entity.get(field)) for field in self.MAP_SURFACE_FIELDS)

    def _root_has_visual_surface(self):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return False
        if root.get("location_class") in {"planet", "moon"}:
            return True
        if any(bool(root.get(field)) for field in self.VISUAL_SURFACE_FIELDS):
            return True
        return self._root_surface_context() is not None

    @staticmethod
    def _grid_rows(model):
        grid = model.get("sample_grid") if isinstance(model, dict) else None
        rows = grid.get("rows") if isinstance(grid, dict) else None
        return rows if isinstance(rows, list) and len(rows) >= 2 and len(rows[0]) >= 2 else None

    def _entity_map_bounds(self, entity):
        """Return the stored map-coordinate envelope for a location."""
        if not isinstance(entity, dict):
            return None
        if entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(entity)
            return {
                "min_x": float(rect["x"]) - float(rect["width_world"]) * 0.5,
                "max_x": float(rect["x"]) + float(rect["width_world"]) * 0.5,
                "min_y": float(rect["y"]) - float(rect["height_world"]) * 0.5,
                "max_y": float(rect["y"]) + float(rect["height_world"]) * 0.5,
            }
        bounds = entity.get("bounds") or entity.get("geometry") or {}
        if bounds.get("type") == "bbox":
            try:
                min_x, max_x = float(bounds["min_x"]), float(bounds["max_x"])
                min_y, max_y = float(bounds["min_y"]), float(bounds["max_y"])
            except (KeyError, TypeError, ValueError):
                return None
            return {
                "min_x": min(min_x, max_x), "max_x": max(min_x, max_x),
                "min_y": min(min_y, max_y), "max_y": max(min_y, max_y),
            }
        points = self._get_geometry_points(bounds)
        if len(points) < 3:
            return None
        return {
            "min_x": min(point[0] for point in points),
            "max_x": max(point[0] for point in points),
            "min_y": min(point[1] for point in points),
            "max_y": max(point[1] for point in points),
        }

    @staticmethod
    def _surface_rect_from_bounds(bounds, canvas_width, canvas_height):
        width = max(1e-6, float(bounds["max_x"]) - float(bounds["min_x"]))
        height = max(1e-6, float(bounds["max_y"]) - float(bounds["min_y"]))
        return {
            "x": (float(bounds["min_x"]) + float(bounds["max_x"])) * 0.5,
            "y": (float(bounds["min_y"]) + float(bounds["max_y"])) * 0.5,
            "width_world": width,
            "height_world": height,
            "canvas_width_px": max(2, int(canvas_width)),
            "canvas_height_px": max(2, int(canvas_height)),
        }

    @staticmethod
    def _sample_grid_value(rows, u, v, *, wrap_x=False, categorical=False):
        valid_rows = [row for row in rows if isinstance(row, list) and row]
        if not valid_rows:
            return None
        row_count = len(valid_rows)
        col_count = min(len(row) for row in valid_rows)
        if col_count <= 0:
            return None
        if wrap_x:
            u = float(u) % 1.0
        else:
            u = max(0.0, min(1.0, float(u)))
        v = max(0.0, min(1.0, float(v)))
        if categorical:
            row_index = min(row_count - 1, max(0, int(round(v * (row_count - 1)))))
            col_index = min(col_count - 1, max(0, int(round(u * (col_count - 1)))))
            return valid_rows[row_index][col_index]

        source_x = u * (col_count - 1)
        source_y = v * (row_count - 1)
        left, top = int(math.floor(source_x)), int(math.floor(source_y))
        right, bottom = min(col_count - 1, left + 1), min(row_count - 1, top + 1)
        mix_x, mix_y = source_x - left, source_y - top
        try:
            top_value = float(valid_rows[top][left]) * (1.0 - mix_x) + float(valid_rows[top][right]) * mix_x
            bottom_value = float(valid_rows[bottom][left]) * (1.0 - mix_x) + float(valid_rows[bottom][right]) * mix_x
            return top_value * (1.0 - mix_y) + bottom_value * mix_y
        except (TypeError, ValueError):
            return valid_rows[top][left]

    def _inherited_surface_context(self, root):
        """Crop the closest terrain-bearing parent into a region-local map.

        Region geometry stays in its parent map coordinates.  This projection
        gives it a usable terrain and climate view without duplicating large
        generated rasters into every authored region entry.
        """
        root_bounds = self._entity_map_bounds(root)
        if root_bounds is None:
            return None
        root_width = root_bounds["max_x"] - root_bounds["min_x"]
        root_height = root_bounds["max_y"] - root_bounds["min_y"]
        if root_width <= 1e-9 or root_height <= 1e-9:
            return None

        parent = self.world_model.get_entity(
            root.get("map_context_parent") or self._structural_parent_location_id(root)
        )
        visited = {root.get("id")}
        source = None
        while isinstance(parent, dict) and parent.get("id") not in visited:
            visited.add(parent.get("id"))
            if self._grid_rows(parent.get("heightmap_model")):
                source = parent
                break
            parent = self.world_model.get_entity(self._structural_parent_location_id(parent))
        if source is None:
            return None

        source_star = self.world_model.get_entity(source.get("parent_body")) if source.get("parent_body") else None
        ensure_coastal_model_current(source, star=source_star)

        source_bounds = self._entity_map_bounds(source)
        source_heightmap = source.get("heightmap_model")
        source_rows = self._grid_rows(source_heightmap)
        if source_bounds is None or source_rows is None:
            return None
        source_width = source_bounds["max_x"] - source_bounds["min_x"]
        source_height = source_bounds["max_y"] - source_bounds["min_y"]
        if source_width <= 1e-9 or source_height <= 1e-9:
            return None

        u0 = max(0.0, min(1.0, (root_bounds["min_x"] - source_bounds["min_x"]) / source_width))
        u1 = max(0.0, min(1.0, (root_bounds["max_x"] - source_bounds["min_x"]) / source_width))
        v0 = max(0.0, min(1.0, (root_bounds["min_y"] - source_bounds["min_y"]) / source_height))
        v1 = max(0.0, min(1.0, (root_bounds["max_y"] - source_bounds["min_y"]) / source_height))
        if u1 <= u0 or v1 <= v0:
            return None

        source_columns = min(len(row) for row in source_rows if isinstance(row, list) and row)
        # Keep inherited region maps sufficiently dense for the raster
        # renderer to interpolate smoothly when the user zooms in.  The crop
        # does not invent terrain; it only resamples the parent surface.
        target_columns = min(257, max(129, int(round((source_columns - 1) * (u1 - u0))) + 1))
        target_rows = min(257, max(65, int(round((len(source_rows) - 1) * (v1 - v0))) + 1))
        wrap_x = bool(source_heightmap.get("wrap_x", False))

        def resample_rows(rows, categorical=False):
            if not isinstance(rows, list) or not rows:
                return []
            result = []
            for y_index in range(target_rows):
                local_v = y_index / max(1, target_rows - 1)
                source_v = v0 + (v1 - v0) * local_v
                row = []
                for x_index in range(target_columns):
                    local_u = x_index / max(1, target_columns - 1)
                    source_u = u0 + (u1 - u0) * local_u
                    row.append(self._sample_grid_value(
                        rows, source_u, source_v,
                        wrap_x=wrap_x, categorical=categorical,
                    ))
                result.append(row)
            return result

        inherited_rows = resample_rows(source_rows)
        if not inherited_rows:
            return None
        values = [float(value or 0.0) for row in inherited_rows for value in row]
        source_masks = source_heightmap.get("surface_masks") or {}
        inherited_ice_rows = resample_rows(source_masks.get("ice_rows") or [], categorical=True)
        from simulations.world_gen.regional_refinement import map_physical_dimensions_m
        source_width_m, source_height_m = map_physical_dimensions_m(source)
        source_uv = source_heightmap.get("source_uv_bounds") or {}
        source_u0 = float(source_uv.get("min_u", 0.0) or 0.0)
        source_u1 = float(source_uv.get("max_u", 1.0) or 1.0)
        source_v0 = float(source_uv.get("min_v", 0.0) or 0.0)
        source_v1 = float(source_uv.get("max_v", 1.0) or 1.0)
        heightmap = {
            "status": "parent_surface_inherited",
            "model_version": "region-parent-surface-v1",
            "coverage": "parent_region_crop",
            "projection": "local_equirectangular",
            "wrap_x": False,
            "wrap_y": False,
            "source_location_id": source.get("id"),
            "source_bounds": dict(source_bounds),
            "source_uv_bounds": {
                "min_u": source_u0 + (source_u1 - source_u0) * u0,
                "max_u": source_u0 + (source_u1 - source_u0) * u1,
                "min_v": source_v0 + (source_v1 - source_v0) * v0,
                "max_v": source_v0 + (source_v1 - source_v0) * v1,
            },
            "region_width_m": source_width_m * abs(u1 - u0),
            "region_height_m": source_height_m * abs(v1 - v0),
            "sea_level_m": source_heightmap.get("sea_level_m"),
            "min_elevation_m": min(values),
            "max_elevation_m": max(values),
            "sample_grid": {
                "width": target_columns,
                "height": target_rows,
                "wrap_x": False,
                "wrap_y": False,
                "rows": inherited_rows,
            },
            "surface_masks": {"ice_rows": inherited_ice_rows},
        }

        source_water = source.get("water_cycle_model")
        water_cycle = None
        climate_grid = source_water.get("climate_grid") if isinstance(source_water, dict) else None
        climate_rows = (
            climate_grid.get("koppen_rows") or climate_grid.get("rows")
            if isinstance(climate_grid, dict) else None
        )
        if isinstance(climate_rows, list) and climate_rows:
            cropped_climate = resample_rows(climate_rows, categorical=True)
            source_elevation_rows = climate_grid.get("elevation_rows") if isinstance(climate_grid, dict) else None
            water_cycle = {
                "status": "parent_climate_inherited",
                "source_location_id": source.get("id"),
                "koppen_classes": list(source_water.get("koppen_classes") or []),
                "climate_grid": {
                    "width": target_columns,
                    "height": target_rows,
                    "rows": cropped_climate,
                    "koppen_rows": resample_rows(
                        climate_grid.get("koppen_rows") or climate_grid.get("rows") or [],
                        categorical=True,
                    ),
                    "elevation_rows": (
                        resample_rows(source_elevation_rows)
                        if isinstance(source_elevation_rows, list) and source_elevation_rows
                        else inherited_rows
                    ),
                    "temperature_rows_k": resample_rows(
                        climate_grid.get("temperature_rows_k") or []
                    ),
                    "annual_precipitation_rows_mm": resample_rows(
                        climate_grid.get("annual_precipitation_rows_mm") or []
                    ),
                    "temperature_seasonality_rows_k": resample_rows(
                        climate_grid.get("temperature_seasonality_rows_k") or []
                    ),
                    "source_uv_bounds": dict(
                        heightmap.get("source_uv_bounds") or {}
                    ),
                },
                "rivers": [],
                "lakes": [],
            }

        source_coastal = source.get("coastal_geomorphology_model")
        coastal_model = None
        if isinstance(source_coastal, dict):
            cropped_segments = []
            for source_segment in source_coastal.get("segments") or []:
                centroid = ((source_segment.get("measurements") or {}).get("centroid_uv") or [])
                if len(centroid) < 2 or not (u0 <= float(centroid[0]) <= u1 and v0 <= float(centroid[1]) <= v1):
                    continue
                segment = copy.deepcopy(source_segment)
                geometry = segment.get("geometry") or {}
                geometry["points"] = [
                    [(float(point[0]) - u0) / max(1e-9, u1 - u0), (float(point[1]) - v0) / max(1e-9, v1 - v0)]
                    for point in geometry.get("points") or []
                    if u0 <= float(point[0]) <= u1 and v0 <= float(point[1]) <= v1
                ]
                local_centroid = [(float(centroid[0]) - u0) / max(1e-9, u1 - u0), (float(centroid[1]) - v0) / max(1e-9, v1 - v0)]
                segment.setdefault("measurements", {})["centroid_uv"] = local_centroid
                if len(geometry["points"]) >= 2:
                    cropped_segments.append(segment)
            coastal_model = {
                **source_coastal,
                "status": "parent_coastal_model_inherited",
                "segments": cropped_segments,
                "source_location_id": source.get("id"),
            }

        return {
            "root": root,
            "source": source,
            "heightmap_model": heightmap,
            "water_cycle_model": water_cycle,
            "coastal_geomorphology_model": coastal_model,
            "map_rect": self._surface_rect_from_bounds(root_bounds, target_columns, target_rows),
        }

    def _surface_model_validation_key(self, entity):
        """Cheaply identify surface inputs that require derivative validation."""
        if not isinstance(entity, dict):
            return None
        heightmap = entity.get("heightmap_model")
        if not isinstance(heightmap, dict):
            return None
        grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        derivatives = heightmap.get("derivatives") if isinstance(heightmap.get("derivatives"), dict) else {}
        coastal = (
            entity.get("coastal_geomorphology_model")
            if isinstance(entity.get("coastal_geomorphology_model"), dict)
            else {}
        )
        water_cycle = entity.get("water_cycle_model")
        return (
            id(entity),
            id(heightmap),
            id(rows),
            len(rows),
            grid.get("width", len(rows[0]) if rows else 0),
            grid.get("height", len(rows)),
            heightmap.get("sea_level_m"),
            heightmap.get("source_heightfield_fingerprint"),
            derivatives.get("model_version"),
            derivatives.get("source_heightfield_fingerprint"),
            id(water_cycle),
            water_cycle.get("model_version") if isinstance(water_cycle, dict) else None,
            id(coastal),
            coastal.get("model_version"),
            coastal.get("source_heightfield_fingerprint"),
        )

    def _ensure_surface_models_current(self, entity, **kwargs):
        cache_key = self._surface_model_validation_key(entity)
        if cache_key is None or cache_key == self._surface_model_validation_cache_key:
            return False
        changed = ensure_coastal_model_current(entity, **kwargs)
        # Validation may replace the heightmap and coastal models, so retain
        # the post-validation identity rather than forcing a second full hash.
        self._surface_model_validation_cache_key = self._surface_model_validation_key(entity)
        return changed

    def _own_generated_region(self, root):
        """Return this location's own most-recently regenerated descendant.

        "Regenerate This Region" persists a full-fidelity `generated_region`
        entity and appends it to `root["constituents"]`, but nothing
        previously consumed it for this location's own Map tab -- rendering
        fell through to `_inherited_surface_context`, which walks *upward*
        past structural ancestors and never looks at a location's own
        children. That meant the regenerated data was silently orphaned:
        the Map tab kept showing a coarse crop of the root planet even after
        a fresh, detailed regeneration existed one hop away.
        """
        if not isinstance(root, dict):
            return None
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        best = None
        best_revision = -1
        for constituent_id in root.get("constituents") or []:
            candidate = entities.get(constituent_id) if isinstance(entities, dict) else None
            if candidate is None:
                candidate = self.world_model.get_entity(constituent_id)
            if not isinstance(candidate, dict) or candidate.get("location_class") != "generated_region":
                continue
            if not self._grid_rows(candidate.get("heightmap_model")):
                continue
            revision = int(candidate.get("refinement_revision", 0) or 0)
            if revision > best_revision:
                best_revision = revision
                best = candidate
        return best

    def _root_surface_context(self):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return None
        own_generated = self._own_generated_region(root)
        surface_root = own_generated if isinstance(own_generated, dict) else root
        if isinstance(surface_root.get("heightmap_model"), dict):
            star = self.world_model.get_entity(surface_root.get("parent_body")) if surface_root.get("parent_body") else None
            entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
            satellites = [
                entity for entity in entities.values()
                if isinstance(entity, dict) and entity.get("location_class") == "moon" and entity.get("parent_body") == surface_root.get("id")
            ]
            self._ensure_surface_models_current(
                surface_root,
                star=star,
                satellites=satellites,
                inherited_sea_level_m=(surface_root.get("heightmap_model") or {}).get("sea_level_m") if surface_root.get("location_class") == "generated_region" else None,
            )
        heightmap = surface_root.get("heightmap_model")
        if self._grid_rows(heightmap):
            bounds = self._entity_map_bounds(root)
            if bounds is None:
                return None
            grid = heightmap.get("sample_grid") or {}
            return {
                "root": root,
                "source": surface_root,
                "heightmap_model": heightmap,
                "water_cycle_model": surface_root.get("water_cycle_model"),
                "coastal_geomorphology_model": surface_root.get("coastal_geomorphology_model"),
                "map_rect": self._surface_rect_from_bounds(
                    bounds,
                    root.get("map_canvas_width_px") or grid.get("width") or 2,
                    root.get("map_canvas_height_px") or grid.get("height") or 2,
                ),
            }

        bounds_key = repr(root.get("bounds") or root.get("geometry") or {})
        cache_key = (
            root.get("id"),
            bounds_key,
            getattr(self.world_model, "repository_revision", 0),
        )
        cached = getattr(self, "_inherited_surface_context_cache", None)
        if isinstance(cached, tuple) and cached[0] == cache_key:
            return cached[1]
        context = self._inherited_surface_context(root)
        self._inherited_surface_context_cache = (cache_key, context)
        return context

    def _format_layer_label(self, layer_kind):
        if layer_kind in self.LAYER_LABELS:
            return self.LAYER_LABELS[layer_kind]

        return str(layer_kind).replace("_", " ").title()

    def get_initial_camera_zoom(self, screen_w, screen_h):
        bounds = getattr(self, "bounds", None) or {}
        try:
            world_w = abs(float(bounds["max_x"]) - float(bounds["min_x"]))
            world_h = abs(float(bounds["max_y"]) - float(bounds["min_y"]))
        except (KeyError, TypeError, ValueError):
            return self.preferred_zoom

        if world_w <= 0 or world_h <= 0:
            return self.preferred_zoom

        usable_w = max(120.0, float(screen_w) * 0.72)
        usable_h = max(120.0, float(screen_h) * 0.62)
        padding = 1.18 if self.is_placing_location_polygon else 1.32
        zoom = min(usable_w / (world_w * padding), usable_h / (world_h * padding))
        zoom = max(float(self.min_zoom), min(float(self.max_zoom), zoom))
        return zoom

    def get_active_layer_kind(self):
        available = self.get_available_layer_kinds()
        if available and self.active_layer_kind not in available:
            self.active_layer_kind = available[0]
        return self.active_layer_kind

    def get_active_layer_label(self):
        self.get_active_layer_kind()
        return self._format_layer_label(self.active_layer_kind)

    def get_map_legend_items(self, max_items=12):
        root = self.get_root_entity() or {}
        surface_context = self._root_surface_context()
        surface_heightmap = surface_context.get("heightmap_model") if isinstance(surface_context, dict) else None
        surface_water_cycle = surface_context.get("water_cycle_model") if isinstance(surface_context, dict) else None
        layer_kind = self.get_active_layer_kind()
        items = []
        if layer_kind == self.HYDROLOGY_LAYER_KIND:
            water = surface_water_cycle or {}
            climate_mode = str(self.active_climate_layer_id or "koppen")
            climate_grid = water.get("climate_grid") or {}
            if climate_mode == "annual_temperature":
                rows = climate_grid.get("temperature_rows_k") or []
                values = [
                    float(value)
                    for row in rows
                    for value in row
                    if value is not None
                ]
                low = min(values) if values else 220.0
                high = max(values) if values else 340.0
                midpoint = (low + high) * 0.5
                items.extend([
                    {"label": f"Warmest annual mean  {high - 273.15:.1f} °C", "color": [212, 74, 54]},
                    {"label": f"Midpoint  {midpoint - 273.15:.1f} °C", "color": [202, 192, 112]},
                    {"label": f"Coldest annual mean  {low - 273.15:.1f} °C", "color": [72, 118, 180]},
                ])
            elif climate_mode == "annual_precipitation":
                rows = climate_grid.get("annual_precipitation_rows_mm") or []
                values = sorted(
                    float(value)
                    for row in rows
                    for value in row
                    if value is not None
                )
                low = values[0] if values else 0.0
                median = values[len(values) // 2] if values else 0.0
                high = values[-1] if values else 0.0
                items.extend([
                    {"label": f"Wettest  {high:,.0f} mm/yr", "color": [44, 104, 168]},
                    {"label": f"Median  {median:,.0f} mm/yr", "color": [74, 146, 102]},
                    {"label": f"Driest  {low:,.0f} mm/yr", "color": [206, 178, 108]},
                ])
            else:
                climate_classes = sorted(
                    [
                        climate_class
                        for climate_class in (
                            water.get("koppen_classes")
                            or []
                        )
                        if isinstance(climate_class, dict)
                    ],
                    key=lambda climate_class: float(climate_class.get("fraction", 0.0) or 0.0),
                    reverse=True,
                )
                for climate_class in climate_classes[:max(1, int(max_items) - 3)]:
                    fraction = float(climate_class.get("fraction", 0.0) or 0.0)
                    code = (
                        f"{climate_class.get('id')} · "
                        if water.get("koppen_classes")
                        else ""
                    )
                    items.append({
                        "label": f"{code}{climate_class.get('label') or climate_class.get('id')}  {fraction * 100:.0f}%",
                        "color": list(climate_class.get("color") or [140, 145, 140]),
                    })
            items.extend([
                {"label": "Rivers / streams", "color": [48, 136, 220]},
                {"label": "Warm ocean current", "color": [242, 170, 94]},
                {"label": "Cool ocean current", "color": [104, 210, 232]},
            ])
        elif layer_kind == self.COASTAL_LAYER_KIND:
            coastal = surface_context.get("coastal_geomorphology_model") or {}
            colors = {
                (segment.get("morphology_assemblage") or segment.get("primary_assemblage")): segment.get("display_color")
                for segment in coastal.get("segments") or []
                if isinstance(segment, dict) and (segment.get("morphology_assemblage") or segment.get("primary_assemblage"))
            }
            for row in (coastal.get("summary") or {}).get("dominant_assemblages") or []:
                assemblage = row.get("id")
                label = str(assemblage or "coast").replace("_", " ").title()
                items.append({"label": f"{label}  {float(row.get('length_km', 0.0) or 0.0):,.0f} km", "color": list(colors.get(assemblage) or [180, 180, 180])})
            items.extend([
                {"label": "Wave exposure", "color": [82, 188, 236]},
                {"label": "Tidal range", "color": [112, 232, 218]},
                {"label": "Longshore transport", "color": [244, 174, 76]},
            ])
        elif layer_kind == self.TRUE_COLOR_LAYER_KIND:
            true_color = root.get("true_color_model") or {}
            items = [
                {
                    "label": "Mineral / regolith reflectance",
                    "color": list(true_color.get("base_reflectance_rgb") or [116, 108, 96]),
                },
                {"label": "Terrain illumination", "color": [206, 210, 210]},
            ]
            if float(true_color.get("ocean_fraction", 0.0) or 0.0) > 0.0:
                items.append({"label": "Liquid surface", "color": [18, 52, 76]})
            if float(true_color.get("ice_fraction", 0.0) or 0.0) > 0.0:
                items.append({"label": "Surface ice", "color": [220, 232, 235]})
        elif layer_kind == self.HEIGHTMAP_LAYER_KIND:
            heightmap = surface_heightmap or {}
            sea = heightmap.get("sea_level_m")
            minimum = float(heightmap.get("min_elevation_m", 0.0) or 0.0)
            maximum = float(heightmap.get("max_elevation_m", 0.0) or 0.0)
            midpoint = (minimum + maximum) * 0.5
            datum_label = "Sea level" if sea is not None else "Elevation datum"
            items = [
                {"label": f"Local maximum  {maximum:,.0f} m", "color": [214, 212, 196]},
                {"label": f"Local midpoint  {midpoint:,.0f} m", "color": [116, 134, 112]},
                {"label": f"{datum_label}  {float(sea or 0.0):,.0f} m", "color": [48, 92, 132]},
                {"label": f"Local minimum  {minimum:,.0f} m", "color": [8, 26, 48]},
            ]
            ice_rows = ((heightmap.get("surface_masks") or {}).get("ice_rows") or [])
            if any(any(bool(value) for value in row) for row in ice_rows):
                items.append({"label": "Surface ice", "color": [220, 236, 242]})
        elif layer_kind == self.LOCATION_LAYER_KIND:
            items = [
                {"label": "Ocean / low basin", "color": [42, 84, 124]},
                {"label": "Lowland", "color": [76, 126, 92]},
                {"label": "Dry or upland terrain", "color": [174, 151, 94]},
                {"label": "Highland / ice", "color": [205, 218, 218]},
                {"label": "Equator", "color": [232, 190, 92]},
            ]
        elif layer_kind == self.GROUND_MATERIALS_LAYER_KIND:
            items = [
                {"label": "Region boundaries", "color": [196, 176, 136]},
                {"label": "Elevation contours", "color": [206, 214, 220]},
                {"label": "Sea level / datum", "color": [116, 202, 246]},
            ]
        if (
            isinstance(surface_heightmap, dict)
            and items
            and layer_kind != self.GROUND_MATERIALS_LAYER_KIND
        ):
            items.append({"label": "Elevation contours", "color": [206, 214, 220]})
        atmosphere = root.get("atmosphere_model") or {}
        visual = atmosphere.get("visual_model") or {}
        if visual.get("visible") and items:
            items.append({"label": "Atmospheric tint", "color": list(visual.get("tint_color") or [170, 180, 192])})
        return items[:max(1, int(max_items))]

    def get_available_layer_kinds(self):
        if self._root_is_building():
            return [self.LOCATION_LAYER_KIND]
        layers = [self.LOCATION_LAYER_KIND, self.GROUND_MATERIALS_LAYER_KIND]
        root = self.get_root_entity()
        surface_context = self._root_surface_context()
        heightmap_model = surface_context.get("heightmap_model") if isinstance(surface_context, dict) else None
        if isinstance(heightmap_model, dict):
            layers.append(self.TRUE_COLOR_LAYER_KIND)
            layers.append(self.HEIGHTMAP_LAYER_KIND)
        water_cycle_model = surface_context.get("water_cycle_model") if isinstance(surface_context, dict) else None
        climate_grid = water_cycle_model.get("climate_grid") if isinstance(water_cycle_model, dict) else None
        if isinstance(climate_grid, dict) and climate_grid.get("rows"):
            layers.append(self.HYDROLOGY_LAYER_KIND)
        coastal_model = surface_context.get("coastal_geomorphology_model") if isinstance(surface_context, dict) else None
        if isinstance(coastal_model, dict) and coastal_model.get("segments"):
            layers.append(self.COASTAL_LAYER_KIND)
        heatmap_model, _source_uv_bounds = self._material_heatmap_context(root)
        if isinstance(heatmap_model, dict) and (
            isinstance(heatmap_model.get("composite_layer"), dict)
            or heatmap_model.get("layers")
        ):
            layers.append(self.MATERIAL_HEATMAP_LAYER_KIND)
        return layers

    def has_atmosphere_visual(self):
        root = self.get_root_entity()
        if not isinstance(root, dict):
            return False
        surface_context = self._root_surface_context()
        source = surface_context.get("source") if isinstance(surface_context, dict) else None
        visual = (
            root.get("atmosphere_visual_model")
            or (source.get("atmosphere_visual_model") if isinstance(source, dict) else None)
            or ((source or root).get("atmosphere_model") or {}).get("visual_model")
            or {}
        )
        return bool(visual.get("visible") or float(visual.get("opacity", 0.0) or 0.0) > 0.0)

    def is_atmosphere_visible(self):
        return bool(self.atmosphere_visible and self.has_atmosphere_visual())

    def toggle_atmosphere_visibility(self):
        if not self.has_atmosphere_visual():
            return False
        self.atmosphere_visible = not self.atmosphere_visible
        self._invalidate_layer_cache()
        return True

    def has_height_contours(self):
        surface_context = self._root_surface_context()
        heightmap = surface_context.get("heightmap_model") if isinstance(surface_context, dict) else None
        grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else None
        return bool(isinstance(grid, dict) and grid.get("rows"))

    def is_height_contours_visible(self):
        return bool(self.height_contours_visible and self.has_height_contours())

    def toggle_height_contours_visibility(self):
        if not self.has_height_contours():
            return False
        self.height_contours_visible = not self.height_contours_visible
        return True

    def set_active_layer_kind(self, layer_kind):
        if layer_kind == self.VISUAL_MAP_LAYER_KIND:
            layer_kind = self.LOCATION_LAYER_KIND
        available = self.get_available_layer_kinds()
        if layer_kind not in set(available):
            layer_kind = available[0] if available else self.LOCATION_LAYER_KIND
        if layer_kind not in available:
            layer_kind = self.LOCATION_LAYER_KIND

        if layer_kind == self.active_layer_kind:
            return False

        self.active_layer_kind = layer_kind
        self.selected_entity_id = None
        if layer_kind != self.MATERIAL_HEATMAP_LAYER_KIND:
            self.selected_material_occurrence_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.debug(
            f"[MapSimulation] Active layer changed to {self.get_active_layer_label()}",
            key="map_layer_change",
            interval=0.1
        )
        return True

    def cycle_active_layer_kind(self):
        available = self.get_available_layer_kinds()
        if not available:
            return False

        if self.active_layer_kind not in available:
            return self.set_active_layer_kind(self.LOCATION_LAYER_KIND)

        current_index = available.index(self.active_layer_kind)
        next_index = (current_index + 1) % len(available)
        return self.set_active_layer_kind(available[next_index])

    def get_material_distribution_items(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return []

        heatmap_model, _source_uv_bounds = self._material_heatmap_context(root_entity)
        if not isinstance(heatmap_model, dict):
            return []

        items = []
        composite_layer = heatmap_model.get("composite_layer")
        if self._material_heatmap_layer_has_raster(composite_layer):
            items.append({
                "id": "composite",
                "label": composite_layer.get("name") or "Composite",
                "active": self.active_material_heatmap_layer_id in {None, "", "composite"},
            })

        for layer in heatmap_model.get("layers") or []:
            if not self._material_heatmap_layer_has_raster(layer):
                continue
            item_id = str(
                layer.get("material_id")
                or layer.get("id")
                or layer.get("bundle_layer_id")
                or layer.get("image_path")
            )
            display_semantics = str(
                layer.get("display_semantics")
                or {
                    "mineral_constituent": "constituent_abundance",
                    "sparse_deposit": "deposit_prospectivity",
                }.get(str(layer.get("distribution_role") or ""), "")
            )
            label = layer.get("name") or item_id
            if display_semantics == "deposit_prospectivity":
                label = f"{label} potential"
            elif display_semantics == "constituent_abundance":
                label = f"{label} abundance"
            items.append({
                "id": item_id,
                "label": label,
                "active": item_id == self.active_material_heatmap_layer_id,
                "confidence": layer.get("confidence"),
                "display_semantics": display_semantics,
            })

        existing_ids = {str(item.get("id") or "") for item in items}
        regional_model = root_entity.get("regional_material_model")
        for occurrence in (
            regional_model.get("occurrences") or []
            if isinstance(regional_model, dict)
            else []
        ):
            if not isinstance(occurrence, dict):
                continue
            occurrence_id = str(occurrence.get("id") or "")
            if not occurrence_id or occurrence_id in existing_ids:
                continue
            items.append({
                "id": occurrence_id,
                "label": f"{occurrence.get('name') or occurrence.get('material_id') or 'Material'} deposit",
                "active": occurrence_id == self.active_material_heatmap_layer_id,
                "confidence": occurrence.get("confidence"),
                "occurrence": True,
            })
            existing_ids.add(occurrence_id)

        return items

    def get_climate_display_items(self):
        surface_context = self._root_surface_context()
        water_cycle = (
            surface_context.get("water_cycle_model")
            if isinstance(surface_context, dict)
            else None
        )
        climate_grid = (
            water_cycle.get("climate_grid")
            if isinstance(water_cycle, dict)
            else None
        )
        if not isinstance(climate_grid, dict) or not climate_grid.get("rows"):
            return []
        choices = [
            ("koppen", "Köppen-Geiger Classification", "koppen_rows"),
            ("annual_temperature", "Mean Annual Temperature", "temperature_rows_k"),
            (
                "annual_precipitation",
                "Annual Precipitation",
                "annual_precipitation_rows_mm",
            ),
        ]
        return [
            {
                "id": item_id,
                "label": label,
                "active": item_id == self.active_climate_layer_id,
            }
            for item_id, label, field in choices
            if item_id == "koppen" or climate_grid.get(field)
        ]

    def set_active_climate_display_item(self, item_id):
        item_id = str(item_id or "koppen")
        valid_ids = {
            str(item.get("id")) for item in self.get_climate_display_items()
        }
        if item_id not in valid_ids:
            item_id = "koppen"
        changed = item_id != self.active_climate_layer_id
        self.active_climate_layer_id = item_id
        layer_changed = self.set_active_layer_kind(self.HYDROLOGY_LAYER_KIND)
        if changed and not layer_changed:
            self._invalidate_layer_cache()
        return changed or layer_changed

    def _material_heatmap_layer_has_raster(self, layer):
        return bool(
            isinstance(layer, dict)
            and (
                layer.get("image_path")
                or (layer.get("bundle_path") and layer.get("bundle_layer_id"))
            )
        )

    def set_active_material_distribution_item(self, item_id):
        item_id = str(item_id or "composite")
        valid_ids = {str(item.get("id")) for item in self.get_material_distribution_items()}
        if item_id not in valid_ids:
            item_id = "composite" if "composite" in valid_ids else next(iter(valid_ids), "")
        if not item_id:
            return False

        changed = item_id != self.active_material_heatmap_layer_id
        self.active_material_heatmap_layer_id = item_id
        self.selected_material_occurrence_id = (
            item_id if item_id.startswith("occurrence_") else None
        )
        layer_changed = self.set_active_layer_kind(self.MATERIAL_HEATMAP_LAYER_KIND)
        if changed and not layer_changed:
            self._invalidate_layer_cache()
        return changed or layer_changed

    def _relation_ids(self, value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, dict):
            entity_id = value.get("id") or value.get("entity_id")
            return [str(entity_id)] if entity_id else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []

    def _location_parent_ids(self, entity):
        parent_ids = []
        for key in ("parent_location", "parent_entity", "parents"):
            for entity_id in self._relation_ids(entity.get(key)):
                if entity_id not in parent_ids:
                    parent_ids.append(entity_id)
        return parent_ids

    def get_location_layer_tree_items(self):
        root_entity = self.get_root_entity()
        root_id = str(getattr(self.context, "root_entity_id", "") or "")
        active_locations = [
            entity
            for entity in self.context.get_active_locations()
            if isinstance(entity, dict)
        ]
        by_id = {str(entity.get("id")): entity for entity in active_locations if entity.get("id")}
        children_by_parent = {}

        for entity in active_locations:
            entity_id = str(entity.get("id") or "")
            if not entity_id:
                continue
            for parent_id in self._location_parent_ids(entity):
                if parent_id:
                    children_by_parent.setdefault(str(parent_id), []).append(entity)

        if isinstance(root_entity, dict):
            for child_id in self._relation_ids(root_entity.get("constituents")):
                child = by_id.get(str(child_id))
                if child is not None:
                    children_by_parent.setdefault(root_id, []).append(child)

        def sort_entities(entities):
            deduped = {}
            for entity in entities:
                deduped[str(entity.get("id"))] = entity
            return sorted(
                deduped.values(),
                key=lambda item: str(item.get("name") or item.get("pretty_name") or item.get("id") or "").lower(),
            )

        items = []
        visited = set()

        def append_entity(entity, depth):
            entity_id = str(entity.get("id") or "")
            if not entity_id or entity_id in visited:
                return
            visited.add(entity_id)
            items.append({
                "id": entity_id,
                "label": entity.get("name") or entity.get("pretty_name") or entity_id,
                "depth": max(0, int(depth)),
                "active": entity_id == self.selected_entity_id,
                "location_class": entity.get("location_class"),
            })
            for child in sort_entities(children_by_parent.get(entity_id, [])):
                append_entity(child, depth + 1)

        for child in sort_entities(children_by_parent.get(root_id, [])):
            append_entity(child, 0)

        for entity in sort_entities(active_locations):
            entity_id = str(entity.get("id") or "")
            if entity_id != root_id and entity_id not in visited:
                append_entity(entity, 0)

        return items

    def get_map_location_browser_items(self):
        root_entity = self.get_root_entity()
        root_id = str(getattr(self.context, "root_entity_id", "") or "")
        if not isinstance(root_entity, dict) or not root_id:
            return []

        active_locations = [
            entity
            for entity in self.context.get_active_locations()
            if (
                isinstance(entity, dict)
                and entity.get("id")
                and self._is_surface_map_location(entity, allow_root=True)
            )
        ]
        by_id = {str(entity.get("id")): entity for entity in active_locations}
        if root_id not in by_id:
            by_id[root_id] = root_entity

        children_by_parent = {}
        for entity in by_id.values():
            entity_id = str(entity.get("id") or "")
            if not entity_id:
                continue
            for parent_id in self._location_parent_ids(entity):
                if parent_id:
                    children_by_parent.setdefault(str(parent_id), []).append(entity)

        for child_id in self._relation_ids(root_entity.get("constituents")):
            child = by_id.get(str(child_id))
            if child is not None:
                children_by_parent.setdefault(root_id, []).append(child)

        def sort_entities(entities):
            deduped = {}
            for entity in entities:
                deduped[str(entity.get("id"))] = entity
            return sorted(
                deduped.values(),
                key=lambda item: str(item.get("name") or item.get("pretty_name") or item.get("id") or "").lower(),
            )

        def item_for(entity, depth, role="child"):
            entity_id = str(entity.get("id") or "")
            return {
                "id": entity_id,
                "label": entity.get("name") or entity.get("pretty_name") or entity_id,
                "depth": max(0, int(depth)),
                "active": entity_id == self.selected_entity_id,
                "location_class": entity.get("location_class"),
                "role": role,
            }

        items = []
        parent_id = self.get_parent_root_entity_id()
        parent = self.world_model.get_entity(parent_id) if parent_id else None
        if isinstance(parent, dict):
            items.append(item_for(parent, 0, role="parent"))

        items.append(item_for(root_entity, 0, role="root"))
        visited = {root_id}

        def append_children(parent_id, depth):
            for child in sort_entities(children_by_parent.get(str(parent_id), [])):
                child_id = str(child.get("id") or "")
                if not child_id or child_id in visited:
                    continue
                visited.add(child_id)
                items.append(item_for(child, depth, role="child"))
                append_children(child_id, depth + 1)

        append_children(root_id, 1)
        return items

    def select_location_from_layer_tree(self, entity_id):
        entity_id = str(entity_id or "")
        if not entity_id or self.world_model.get_entity(entity_id) is None:
            return False
        self.set_active_layer_kind(self.LOCATION_LAYER_KIND)
        self.selected_entity_id = entity_id
        self.selected_spatial_feature_id = None
        self.hover_entity_id = entity_id
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        return True

    def get_spatial_feature(self, spatial_feature_id):
        if not spatial_feature_id:
            return None

        if str(spatial_feature_id).startswith("virtual:"):
            return None

        return self.world_model.get_entity(spatial_feature_id)

    def get_location(self, location_id):
        if not location_id:
            return None

        return self.world_model.get_entity(location_id)

    def get_selection_inspector_payload(self):
        entity_id = self.selected_entity_id or self.selected_spatial_feature_id
        if not entity_id:
            return None

        entity = self.world_model.get_entity(entity_id)
        if entity is None:
            return {
                "entity_id": None,
                "title": str(entity_id).removeprefix("virtual:"),
                "kind": "Virtual map aggregate",
                "details": [f"Layer: {self.get_active_layer_label()}"],
                "actions": [],
            }

        entity_class = (
            entity.get("location_class")
            or entity.get("region_class")
            or entity.get("type", "map entity")
        )
        details = [
            f"Class: {entity_class}",
            f"Repository ID: {entity_id}",
            f"Layer: {self.get_active_layer_label()}",
        ]
        start_year = entity.get("start_year")
        end_year = entity.get("end_year")
        if start_year not in (None, "") or end_year not in (None, ""):
            active_start = start_year if start_year not in (None, "") else "?"
            active_end = end_year if end_year not in (None, "") else "present"
            details.append(f"Active: {active_start} to {active_end}")

        return {
            "entity_id": entity_id,
            "title": entity.get("pretty_name") or entity.get("name") or entity_id,
            "kind": "Map selection",
            "details": details,
            "actions": [
                {"id": "open_selection_wiki", "label": "Open Wiki Entry"},
            ],
        }

    def _get_entity_bbox_bounds(self, entity):
        if not entity:
            return None

        bounds = entity.get("bounds") or {}
        if bounds.get("type") != "bbox":
            return None

        return {
            "min_x": float(bounds.get("min_x", 0.0)),
            "max_x": float(bounds.get("max_x", 0.0)),
            "min_y": float(bounds.get("min_y", 0.0)),
            "max_y": float(bounds.get("max_y", 0.0)),
        }

    def _can_open_location_inspector(self, location_id):
        if not location_id:
            return False

        entity = self.get_location(location_id)
        if not entity:
            return False

        if entity.get("_dataset") not in (None, "locations"):
            return False

        if entity.get("type") != "location":
            return False

        return True

    def _get_entity_rectangle_bounds(self, entity):
        if not entity or entity.get("location_class") not in {"planet", "moon"}:
            return None

        bounds = self._get_entity_bbox_bounds(entity)
        if bounds is not None:
            return bounds

        if entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            return {
                "min_x": rect["x"] - half_w,
                "max_x": rect["x"] + half_w,
                "min_y": rect["y"] - half_h,
                "max_y": rect["y"] + half_h,
            }

        return None

    def _can_edit_location_bounds(self, location_id):
        if not self._can_open_location_inspector(location_id):
            return False

        entity = self.get_location(location_id)
        return self._get_entity_rectangle_bounds(entity) is not None

    def _map_image_target_entity_id(self):
        selected_entity = self.get_location(self.selected_entity_id)
        if (
            selected_entity is not None
            and selected_entity.get("_dataset") in (None, "locations")
            and selected_entity.get("type") == "location"
            and self._map_image_rect_from_entity(selected_entity) is not None
        ):
            return selected_entity.get("id")

        root_entity = self.get_root_entity()
        if root_entity is not None and self._map_image_rect_from_entity(root_entity) is not None:
            return root_entity.get("id")

        return None

    def _map_image_rect_from_entity(self, entity):
        if not isinstance(entity, dict):
            return None

        if entity.get("location_class") in {"planet", "moon"}:
            return self._planet_rect_from_entity(entity)

        bounds = self._get_entity_bbox_bounds(entity)
        if bounds is None:
            geometry = entity.get("bounds") or entity.get("geometry") or {}
            points = self._get_geometry_points(geometry)
            if len(points) < 3:
                return None

            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bounds = {
                "min_x": min(xs),
                "max_x": max(xs),
                "min_y": min(ys),
                "max_y": max(ys),
            }

        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]
        x, y = self._map_point_to_world((min_x + max_x) / 2, (min_y + max_y) / 2)
        return {
            "x": x,
            "y": y,
            "width_world": max_x - min_x,
            "height_world": max_y - min_y,
        }

    def can_import_map_image(self):
        return self._map_image_target_entity_id() is not None

    def get_map_image_import_target_label(self):
        target = self.get_location(self._map_image_target_entity_id())
        if not target:
            return "Map Image"
        return target.get("pretty_name") or target.get("name") or target.get("id") or "Map Image"

    def _open_map_image_file_dialog(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return ""

        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title="Select map image",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()

        return selected or ""

    def _prompt_map_image_year(self):
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except ImportError:
            return self.year

        root = tk.Tk()
        root.withdraw()
        try:
            value = simpledialog.askstring(
                "Date map image",
                "Map image year:",
                initialvalue=str(int(self.year)),
            )
        finally:
            root.destroy()

        if value is None:
            return None

        normalized = self._normalize_year_value(value.strip())
        return normalized if normalized is not None else self.year

    def _canonical_map_image_path(self, target_id, source_path, image_year):
        source = Path(source_path)
        suffix = source.suffix.lower() or ".png"
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(target_id)).strip("_") or "map"
        year_part = "undated" if image_year is None else str(int(image_year))
        target_dir = self.MAP_ASSET_ROOT / safe_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"base_map_{year_part}{suffix}"
        return target_path

    def _relative_project_path(self, path):
        project_root = Path(__file__).resolve().parents[2]
        try:
            return str(path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def import_map_image_for_current_target(self):
        target_id = self._map_image_target_entity_id()
        if not target_id:
            return False

        target = self.get_location(target_id)
        if target is None:
            return False

        source_path = self._open_map_image_file_dialog()
        if not source_path:
            return False

        image_year = self._prompt_map_image_year()
        if image_year is None:
            return False

        target_path = self._canonical_map_image_path(target_id, source_path, image_year)
        try:
            shutil.copy2(source_path, target_path)
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to copy map image: {exc}")
            return False

        relative_path = self._relative_project_path(target_path)
        updates = {
            "map_image_path": relative_path,
            "map_image_year": image_year,
            "map_image_fit": "stretch_to_bounds",
        }

        if not self._update_location_map_image_fields(target_id, updates):
            return False

        target.update(updates)
        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.selected_entity_id = target_id
        self.selected_spatial_feature_id = None
        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Imported map image for {target_id}: {relative_path}")
        return True

    def _can_inspect_location(self, location_id):
        return self._can_open_location_inspector(location_id)

    def consume_pending_inspector_target(self):
        target = self._pending_inspector_target
        self._pending_inspector_target = None
        return target

    def open_entity_card(self, entity_id, *, mode="edit", familiarity=None):
        """Request a floating card for entity_id -- drained by UIManager each frame."""
        if not entity_id:
            return False
        self._pending_floating_card_target = {
            "id": entity_id,
            "mode": mode,
            "familiarity": familiarity,
        }
        return True

    def consume_pending_floating_card_target(self):
        target = self._pending_floating_card_target
        self._pending_floating_card_target = None
        return target

    def can_create_spatial_feature_draft(self):
        if self._root_is_building():
            return True
        return self.active_layer_kind in self.AUTHORABLE_HISTORY_LAYER_KINDS

    def get_spatial_feature_draft_button_label(self):
        if self._root_is_building():
            return "New Room"
        if self.active_layer_kind == self.LOCATION_LAYER_KIND:
            return "New Location"
        return f"New {self._format_layer_label(self.active_layer_kind)}"

    def can_create_map_square_draft(self):
        if self.active_layer_kind != self.LOCATION_LAYER_KIND:
            return False

        if self.selected_entity_id and self._can_edit_location_bounds(self.selected_entity_id):
            return True

        return self._can_edit_location_bounds(self.context.root_entity_id)

    def can_create_location_draft(self):
        return self.LOCATION_LAYER_KIND in self.get_available_layer_kinds()

    def begin_point_location_draft(self, location_class="site"):
        if not self.can_create_location_draft():
            return False

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_creating_point_location = True
        self.draft_point_location_class = str(location_class or "site")
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Started point location draft root={self.context.root_entity_id}"
        )
        return True

    def _root_planet_has_map_dimensions(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return True

        if root_entity.get("location_class") not in {"planet", "moon"}:
            return True

        bounds = root_entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon", "radius"}:
            return True

        if root_entity.get("radius_m") not in (None, ""):
            try:
                float(root_entity.get("radius_m"))
                return True
            except (TypeError, ValueError):
                pass

        canvas_w = root_entity.get("map_canvas_width_px")
        canvas_h = root_entity.get("map_canvas_height_px")
        if canvas_w not in (None, "") and canvas_h not in (None, ""):
            return True

        return False

    def _root_requires_dimension_rectangle(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return False

        return (
            root_entity.get("location_class") in {"planet", "moon"}
            and not self._root_planet_has_map_dimensions()
        )

    def is_square_editor_active(self):
        return self.is_creating_map_square or self.is_editing_map_square

    def is_map_editor_active(self):
        return (
            self.is_creating_point_location
            or self.is_polygon_editor_active()
            or self.is_square_editor_active()
        )

    def consumes_global_keydown(self):
        return self.is_map_editor_active()

    def handle_event(self, event):
        if event.type != self.KEYDOWN_EVENT_TYPE or not self.is_map_editor_active():
            return False

        key = getattr(event, "key", None)
        if key in (13, 1073741912):
            self.finish_map_editor()
            return True
        if key == 27:
            self.cancel_map_editor()
            return True
        return False

    def _reset_square_drag_state(self):
        self.square_drag_handle = None
        self.square_drag_start_pos = None
        self.square_drag_start_bounds = None
        self.square_drag_opposite_point = None

    def _set_all_editor_modes_inactive(self):
        self.is_creating_spatial_feature = False
        self.is_creating_biosphere_patch = False
        self.draft_location_class = "region"
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_creating_point_location = False
        self.draft_point_location_class = "site"
        self.draft_point_location_pos = None
        self.draft_point_hover_pos = None
        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()

    def can_finish_map_editor(self):
        if self.is_creating_point_location:
            return self.draft_point_location_pos is not None

        if self.is_creating_map_square:
            return self.can_finish_map_square_draft()

        if self.is_editing_map_square:
            return self.can_finish_map_square_edit()

        return self.can_finish_polygon_editor()

    def finish_map_editor(self):
        if self.is_creating_point_location:
            return self.finish_point_location_draft()

        if self.is_creating_map_square:
            return self.finish_map_square_draft()

        if self.is_editing_map_square:
            return self.finish_map_square_edit()

        return self.finish_polygon_editor()

    def cancel_map_editor(self):
        if self.is_creating_point_location:
            return self.cancel_point_location_draft()

        if self.is_creating_map_square:
            return self.cancel_map_square_draft()

        if self.is_editing_map_square:
            return self.cancel_map_square_edit()

        return self.cancel_polygon_editor()

    def _map_editor_status_with_keys(self, label, finish_ready=False):
        keys = "Enter finish / Esc cancel" if finish_ready else "Esc cancel"
        return f"{label} | {keys}" if label else keys

    def get_map_editor_status_label(self):
        if self.is_creating_point_location:
            label = str(self.draft_point_location_class or "site").replace("_", " ").title()
            if self.draft_point_location_pos is None:
                return self._map_editor_status_with_keys(f"{label} point: choose location")
            return self._map_editor_status_with_keys(f"{label} point: ready", finish_ready=True)

        if self.is_creating_map_square:
            noun = "Planet dimensions" if self.map_square_target_entity_id else "Draft rectangle"
            if self.map_square_anchor is None:
                return self._map_editor_status_with_keys(f"{noun}: choose first corner")
            if self.can_finish_map_square_draft():
                return self._map_editor_status_with_keys(f"{noun}: ready", finish_ready=True)
            return self._map_editor_status_with_keys(f"{noun}: choose opposite corner")

        if self.is_editing_map_square:
            if self.square_drag_handle:
                return self._map_editor_status_with_keys(
                    f"Edit rectangle: dragging {self.square_drag_handle}",
                    finish_ready=True,
                )
            return self._map_editor_status_with_keys("Edit rectangle: drag a handle", finish_ready=True)

        if self.is_polygon_editor_active():
            if self.is_creating_biosphere_patch:
                area_label = self.get_draft_area_label()
                if area_label:
                    label = f"Biosphere patch: {self.get_polygon_editor_point_count()} points | {area_label}"
                else:
                    label = f"Biosphere patch: {self.get_polygon_editor_point_count()} points"
                return self._map_editor_status_with_keys(label, finish_ready=self.can_finish_polygon_editor())
            label = f"{self.get_polygon_editor_mode_label()}: {self.get_polygon_editor_point_count()} points"
            return self._map_editor_status_with_keys(label, finish_ready=self.can_finish_polygon_editor())

        return ""

    def consume_repository_return_entity_id(self):
        entity_id = self.return_to_repository_entity_id
        self.return_to_repository_entity_id = None
        return entity_id

    def is_polygon_editor_active(self):
        return (
            self.is_creating_spatial_feature
            or self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
            or self.is_placing_location_polygon
        )

    def get_polygon_editor_points(self):
        if self.is_placing_location_polygon:
            return self.placing_location_points

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.editing_spatial_feature_points

        return self.draft_spatial_feature_points

    def get_polygon_editor_hover_point(self):
        if self.is_placing_location_polygon:
            return self.placing_hover_map_pos

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.editing_hover_map_pos

        return self.draft_hover_map_pos

    def get_polygon_editor_point_count(self):
        return len(self.get_polygon_editor_points())

    def get_polygon_editor_mode_label(self):
        if self.is_placing_location_polygon:
            return "Place on parent"

        if self.is_evolving_spatial_feature_polygon:
            return "Evolve region"

        if self.is_editing_spatial_feature_polygon:
            return "Edit polygon"

        if self.is_creating_spatial_feature:
            if self.is_creating_biosphere_patch:
                return "Biosphere patch"
            return "Draft selection"

        return "Polygon"

    def can_finish_polygon_editor(self):
        return (
            self.is_polygon_editor_active()
            and self.get_polygon_editor_point_count() >= 3
        )

    def can_finish_spatial_feature_draft(self):
        return (
            self.is_creating_spatial_feature
            and len(self.draft_spatial_feature_points) >= 3
        )

    def begin_spatial_feature_draft(self):
        if not self.can_create_spatial_feature_draft():
            return False

        self._set_all_editor_modes_inactive()
        self.is_creating_spatial_feature = True
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started spatial feature draft "
            f"layer={self.active_layer_kind}"
        )
        return True

    def can_create_biosphere_patch_draft(self):
        return self.LOCATION_LAYER_KIND in self.get_available_layer_kinds()

    def begin_biosphere_patch_draft(self):
        if not self.can_create_biosphere_patch_draft():
            self.set_active_layer_kind(self.LOCATION_LAYER_KIND)

        if not self.can_create_biosphere_patch_draft():
            return False

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_creating_spatial_feature = True
        self.is_creating_biosphere_patch = True
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Started biosphere patch draft root={self.context.root_entity_id}"
        )
        return True

    def begin_map_square_draft(self):
        if not self.can_create_map_square_draft():
            return False

        if self.selected_entity_id and self._can_edit_location_bounds(self.selected_entity_id):
            return self.begin_location_square_edit("location", self.selected_entity_id)

        if self._can_edit_location_bounds(self.context.root_entity_id):
            return self.begin_location_square_edit("location", self.context.root_entity_id)

        self._set_all_editor_modes_inactive()
        self.is_creating_map_square = True
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started map rectangle draft root={self.context.root_entity_id}"
        )
        return True

    def get_location_draft_options(self):
        root = self.get_root_entity() if hasattr(self, "get_root_entity") else None
        root_class = root.get("location_class") if isinstance(root, dict) else None

        if root_class in {"planet", "moon"}:
            return [
                {"id": "continent", "label": "New Continent"},
                {"id": "country", "label": "New Country"},
                {"id": "state", "label": "New State"},
                {"id": "region", "label": "New Region"},
                {"id": "city", "label": "New City"},
                {"id": "site", "label": "New Site"},
            ]

        if root_class in {"continent", "island_chain", "island", "atoll"}:
            return [
                {"id": "country", "label": "New Country"},
                {"id": "region", "label": "New Region"},
                {"id": "city", "label": "New City"},
                {"id": "site", "label": "New Site"},
            ]

        if root_class == "country":
            return [
                {"id": "state", "label": "New State"},
                {"id": "region", "label": "New Region"},
                {"id": "city", "label": "New City"},
                {"id": "site", "label": "New Site"},
            ]

        if root_class in {"state", "province", "region"}:
            return [
                {"id": "city", "label": "New City"},
                {"id": "site", "label": "New Site"},
                {"id": "region", "label": "New Subregion"},
            ]

        if root_class in {"city", "settlement"}:
            return [
                {"id": "quarter", "label": "New Quarter"},
                {"id": "site", "label": "New Site"},
            ]

        return [
            {"id": "region", "label": "New Region"},
            {"id": "site", "label": "New Site"},
        ]

    def get_point_location_draft_options(self):
        return [
            {"id": "site", "label": "Point Site"},
            {"id": "city", "label": "Point City"},
            {"id": "building", "label": "Point Building"},
        ]

    def begin_location_draft(self, location_class="region"):
        if not self.can_create_location_draft():
            return False

        self.active_layer_kind = self.LOCATION_LAYER_KIND

        if not self._root_requires_dimension_rectangle():
            option_ids = {option["id"] for option in self.get_location_draft_options()}
            requested_class = location_class if location_class in option_ids else "region"
            started = self.begin_spatial_feature_draft()
            if started:
                self.draft_location_class = requested_class
            return started

        self._set_all_editor_modes_inactive()
        self.draft_location_class = "region"
        self.is_creating_map_square = True
        self.map_square_target_entity_id = self.context.root_entity_id
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started planet dimension rectangle draft root={self.context.root_entity_id}"
        )
        return True

    def begin_location_parent_polygon_placement(self, location_id, return_to_repository=True):
        location = self.get_location(location_id)
        if not location:
            return False

        if location.get("_dataset") not in (None, "locations"):
            return False

        if location.get("type") != "location":
            return False

        parent_location = self._structural_parent_location_id(location)
        if parent_location != self.context.root_entity_id:
            return False

        bounds = location.get("bounds") or {}
        points = []
        if bounds.get("type") == "polygon":
            points = self._get_geometry_points(bounds)
        elif bounds.get("type") == "bbox":
            points = self._get_geometry_points(bounds)

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_placing_location_polygon = True
        self.placing_location_entity_id = location_id
        self.placing_location_points = list(points)
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = self._placement_ancestor_ids(parent_location)
        self.return_to_repository_entity_id = location_id if return_to_repository else None
        self.selected_entity_id = location_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started parent placement polygon {location_id}")
        return True

    def _placement_ancestor_ids(self, parent_location_id):
        ancestor_ids = []
        visited = set()
        current = self.world_model.get_entity(parent_location_id)
        while current:
            current_id = current.get("id")
            parent_id = self._structural_parent_location_id(current)
            if not parent_id or parent_id in visited:
                break

            visited.add(parent_id)
            parent = self.world_model.get_entity(parent_id)
            if not parent:
                break

            ancestor_ids.append(parent_id)
            current = parent

        return ancestor_ids

    def cancel_spatial_feature_draft(self):
        if not self.is_creating_spatial_feature:
            return False

        self.is_creating_spatial_feature = False
        self.is_creating_biosphere_patch = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None

        logger.info("[MapSimulation] Cancelled spatial feature draft")
        return True

    def cancel_map_square_draft(self):
        if not self.is_creating_map_square:
            return False

        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None

        logger.info("[MapSimulation] Cancelled map rectangle draft")
        return True

    def cancel_location_parent_polygon_placement(self):
        if not self.is_placing_location_polygon:
            return False

        target_id = self.placing_location_entity_id
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.selected_entity_id = target_id
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Cancelled parent placement polygon {target_id}")
        return True

    def begin_location_square_edit(self, target_kind, target_id):
        if target_kind != "location":
            return False

        if not self._can_edit_location_bounds(target_id):
            return False

        entity = self.get_location(target_id)
        bounds = self._get_entity_rectangle_bounds(entity)
        if bounds is None:
            return False

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_editing_map_square = True
        self.editing_map_square_entity_id = target_id
        self.editing_map_square_bounds = dict(bounds)
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started rectangle edit {target_id}")
        return True

    def cancel_map_square_edit(self):
        if not self.is_editing_map_square:
            return False

        target_id = self.editing_map_square_entity_id
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()
        self.selected_entity_id = target_id
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Cancelled rectangle edit {target_id}")
        return True

    def can_finish_map_square_edit(self):
        return (
            self.is_editing_map_square
            and self._square_bounds_side(self.editing_map_square_bounds)
            >= self.MIN_SQUARE_SIDE_WORLD
        )

    def finish_map_square_edit(self):
        if not self.can_finish_map_square_edit():
            return False

        target_id = self.editing_map_square_entity_id
        if not self._update_location_bounds(target_id, self.editing_map_square_bounds):
            return False

        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        self._notify_incremental_repository_change(rebuild_relations=False)

        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Saved rectangle edit {target_id}")
        return True

    def begin_spatial_feature_polygon_edit(self, target_kind, target_id):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False

            feature = self.get_spatial_feature(target_id)
            if feature is None:
                return False
            points = self._get_geometry_points(feature.get("geometry") or feature.get("bounds") or {})
        else:
            if not self._can_open_location_inspector(target_id):
                return False

            feature = self.get_location(target_id)
            if feature is None:
                return False
            points = self._get_geometry_points(feature.get("bounds") or feature.get("geometry") or {})

        if len(points) < 3:
            return False

        layer_kind = feature.get("layer_kind")
        if layer_kind:
            self.active_layer_kind = layer_kind
        elif target_kind == "location":
            self.active_layer_kind = self.LOCATION_LAYER_KIND

        self.is_creating_spatial_feature = False
        self.is_creating_biosphere_patch = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_editing_spatial_feature_polygon = True
        self.editing_spatial_feature_id = target_id
        self.editing_polygon_target_kind = target_kind
        self.editing_spatial_feature_points = list(points)
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = target_id if target_kind == "location" else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id if target_kind == "spatial_feature" else None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started polygon edit {target_id}")
        return True

    def begin_spatial_feature_evolution(self, target_kind, target_id):
        if target_kind != "spatial_feature":
            return False

        if not self._is_real_spatial_feature_id(target_id):
            return False

        feature = self.get_spatial_feature(target_id)
        if feature is None:
            return False

        source_start_year = self._normalize_year_value(feature.get("start_year"))
        source_end_year = self._normalize_year_value(feature.get("end_year"))
        selected_year = int(self.year)

        if source_start_year is not None and selected_year <= source_start_year:
            return False

        if source_end_year is not None and selected_year > source_end_year:
            return False

        points = self._get_geometry_points(feature.get("geometry") or {})
        if len(points) < 3:
            return False

        layer_kind = feature.get("layer_kind")
        if layer_kind:
            self.active_layer_kind = layer_kind

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = True
        self.evolving_source_spatial_feature_id = target_id
        self.editing_spatial_feature_id = target_id
        self.editing_polygon_target_kind = "spatial_feature"
        self.editing_spatial_feature_points = list(points)
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Started spatial feature evolution "
            f"{target_id} year={selected_year}"
        )
        return True

    def cancel_spatial_feature_polygon_edit(self):
        if not (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return False

        target_id = self.editing_spatial_feature_id
        was_evolving = self.is_evolving_spatial_feature_polygon
        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_spatial_feature_id = target_id
        self._invalidate_layer_cache()

        action_label = "evolution" if was_evolving else "edit"
        logger.info(f"[MapSimulation] Cancelled polygon {action_label} {target_id}")
        return True

    def finish_spatial_feature_polygon_edit(self):
        if self.is_evolving_spatial_feature_polygon:
            return self.finish_spatial_feature_evolution()

        if not self.is_editing_spatial_feature_polygon:
            return False

        if len(self.editing_spatial_feature_points) < 3:
            return False

        target_id = self.editing_spatial_feature_id
        target_kind = self.editing_polygon_target_kind or "spatial_feature"
        points = self.editing_spatial_feature_points
        if target_kind == "location":
            bounds = {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            }
            updated = (
                self._update_location_bounds(target_id, bounds)
                and self._update_location_geometry(target_id, points)
            )
        else:
            updated = self._update_spatial_feature_geometry(target_id, points)

        if not updated:
            return False

        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = target_id if target_kind == "location" else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id if target_kind == "spatial_feature" else None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved polygon edit {target_id}")
        return True

    def finish_spatial_feature_evolution(self):
        if not self.is_evolving_spatial_feature_polygon:
            return False

        if len(self.editing_spatial_feature_points) < 3:
            return False

        source_id = self.evolving_source_spatial_feature_id
        source_feature = self.get_spatial_feature(source_id)
        if source_feature is None:
            return False

        selected_year = int(self.year)
        source_start_year = self._normalize_year_value(source_feature.get("start_year"))
        if source_start_year is not None and selected_year <= source_start_year:
            return False

        evolved_feature = self._build_evolved_spatial_feature_record(
            source_feature,
            self.editing_spatial_feature_points,
        )
        source_end_year = selected_year - 1

        try:
            if not self._update_spatial_feature_end_year(source_id, source_end_year):
                return False
            self._append_location_record(evolved_feature)
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save spatial feature evolution: {exc}"
            )
            return False

        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = evolved_feature["id"]
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved spatial feature evolution "
            f"{source_id} -> {evolved_feature['id']}"
        )
        return True

    def finish_location_parent_polygon_placement(self):
        if not self.is_placing_location_polygon:
            return False

        if len(self.placing_location_points) < 3:
            return False

        target_id = self.placing_location_entity_id
        parent_id = self._smallest_placement_parent_for_points(
            self.placing_location_points
        )
        bounds = {
            "type": "polygon",
            "coordinate_space": "map_world",
            "points": list(self.placing_location_points),
        }
        if parent_id and not self._update_location_parent(target_id, parent_id):
            return False

        if not self._update_location_bounds(target_id, bounds):
            return False

        target = self.get_location(target_id)
        if target is not None:
            if parent_id:
                target["parent_location"] = parent_id
            target["bounds"] = bounds

        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved parent placement polygon {target_id}")
        return True

    def _smallest_placement_parent_for_points(self, points):
        candidate_ids = [self.context.root_entity_id]
        for entity_id in self.placement_ancestor_entity_ids:
            if entity_id not in candidate_ids:
                candidate_ids.append(entity_id)

        containing_candidates = []
        for entity_id in candidate_ids:
            entity = self.get_location(entity_id)
            if not entity:
                continue

            candidate_points = self._location_container_points(entity)
            if len(candidate_points) < 3:
                continue

            if not self._polygon_contains_points(candidate_points, points):
                continue

            containing_candidates.append((
                self._polygon_area(candidate_points),
                entity_id,
            ))

        if not containing_candidates:
            return self.context.root_entity_id

        containing_candidates.sort(key=lambda item: item[0])
        return containing_candidates[0][1]

    def _smallest_draft_parent_for_points(self, points, location_class):
        """Choose the smallest valid active location containing a new draft."""
        location_class = str(location_class or "region").strip().lower()
        allowed_parent_classes = {
            "continent": {"planet", "moon"},
            "country": {"continent", "island_chain", "island", "atoll"},
            "state": {"country"},
            "province": {"country", "state"},
            "city": {"state", "province", "region", "country"},
            "settlement": {"state", "province", "region", "country"},
            "quarter": {"city", "settlement"},
        }.get(location_class)

        candidates = []
        root_id = self.context.root_entity_id
        for entity in self.context.get_active_locations():
            if not isinstance(entity, dict):
                continue
            entity_id = entity.get("id")
            if not entity_id:
                continue
            parent_class = str(entity.get("location_class") or "").strip().lower()
            if allowed_parent_classes is not None and parent_class not in allowed_parent_classes:
                continue
            container_points = self._location_container_points(entity)
            if len(container_points) < 3:
                continue
            if not all(
                self._point_in_polygon_points(
                    point[0], point[1], container_points, edge_tolerance=1e-9
                )
                for point in points
            ):
                continue
            candidates.append((self._polygon_area(container_points), entity_id))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
        return root_id

    def _location_container_points(self, entity):
        bounds = entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon"}:
            return self._get_geometry_points(bounds)

        if entity.get("location_class") == "planet":
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            return [
                (rect["x"] - half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] + half_h),
                (rect["x"] - half_w, rect["y"] + half_h),
            ]

        return []

    def _polygon_contains_points(self, container_points, points):
        if len(container_points) < 3 or len(points) < 3:
            return False

        return all(
            self._point_in_polygon_points(
                point[0],
                point[1],
                container_points,
                edge_tolerance=1e-9,
            )
            for point in points
        )

    def finish_polygon_editor(self):
        if self.is_placing_location_polygon:
            return self.finish_location_parent_polygon_placement()

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.finish_spatial_feature_polygon_edit()

        return self.finish_spatial_feature_draft()

    def cancel_polygon_editor(self):
        if self.is_placing_location_polygon:
            return self.cancel_location_parent_polygon_placement()

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.cancel_spatial_feature_polygon_edit()

        return self.cancel_spatial_feature_draft()

    def finish_spatial_feature_draft(self):
        if not self.can_finish_spatial_feature_draft():
            return False

        region = self._build_draft_spatial_feature_record()
        is_location_layer = region.get("layer_kind") == self.LOCATION_LAYER_KIND
        is_biosphere_patch = region.get("location_class") == self.BIOSPHERE_PATCH_LOCATION_CLASS
        biosphere_roster = (
            self._build_biosphere_roster_collection_record(region)
            if is_biosphere_patch
            else None
        )
        biosphere_record = (
            self._build_biosphere_record(region)
            if is_biosphere_patch
            else None
        )

        try:
            self._append_location_record(region)
            if biosphere_roster is not None:
                self._append_collection_record(biosphere_roster)
            if biosphere_record is not None:
                self._append_biosphere_record(biosphere_record)
            parent_id = region.get("parent_location") or self.context.root_entity_id
            linked_parent = self._append_offspring_reference_to_location(parent_id, region["id"])
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save region draft: {exc}"
            )
            return False
        if not linked_parent:
            logger.info(
                f"[MapSimulation] Saved {region['id']} without parent offspring link "
                f"parent={region.get('parent_location') or self.context.root_entity_id}"
            )

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_spatial_feature_id = region["id"]
        self.selected_entity_id = region["id"] if is_location_layer else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None if is_location_layer else region["id"]
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = {
            "kind": "location" if is_location_layer else "spatial_feature",
            "id": region["id"],
        }

        self._notify_incremental_repository_change()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved location draft {region['id']}"
        )
        return True

    def _build_draft_point_location_record(self):
        location_id, index = self._allocate_location_draft_id()
        root_name = self.get_root_name()
        location_class = self.draft_point_location_class or "site"
        label = str(location_class).replace("_", " ").title()
        name = f"Draft {label} {index:03d}"
        point_x, point_y = self.draft_point_location_pos or (0.0, 0.0)
        parent_id = self._smallest_draft_parent_for_points(
            [(point_x, point_y)], location_class
        )
        notes = (
            f"Draft {label.lower()} point created under {root_name}. "
            "Use this for work-in-progress or out-of-scale locations."
        )

        return {
            "id": location_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": location_class,
            "location_role": "point_location",
            "region_class": location_class,
            "wiki_entry": notes,
            "layer_kind": self.LOCATION_LAYER_KIND,
            "parent_location": parent_id,
            "parent_entity": parent_id,
            "parents": [parent_id],
            "coords": {
                "type": "point",
                "coordinate_space": "map_world",
                "x": float(point_x),
                "y": float(point_y),
            },
            "start_year": self.year,
            "entry_status": "draft",
        }

    def finish_point_location_draft(self):
        if not self.is_creating_point_location or self.draft_point_location_pos is None:
            return False

        location = self._build_draft_point_location_record()

        try:
            self._append_location_record(location)
            parent_id = location.get("parent_location") or self.context.root_entity_id
            linked_parent = self._append_offspring_reference_to_location(parent_id, location["id"])
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save point location draft: {exc}"
            )
            return False
        if not linked_parent:
            logger.info(
                f"[MapSimulation] Saved {location['id']} without parent offspring link "
                f"parent={location.get('parent_location') or self.context.root_entity_id}"
            )

        self.is_creating_point_location = False
        self.draft_point_location_pos = None
        self.draft_point_hover_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_location_id = location["id"]
        self.selected_entity_id = location["id"]
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = {
            "kind": "location",
            "id": location["id"],
        }

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved point location draft {location['id']}"
        )
        return True

    def cancel_point_location_draft(self):
        if not self.is_creating_point_location:
            return False

        self.is_creating_point_location = False
        self.draft_point_location_pos = None
        self.draft_point_hover_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self._invalidate_layer_cache()
        return True

    def can_create_biosphere_from_selection(self):
        if not self.selected_entity_id:
            return False

        entity = self.get_location(self.selected_entity_id)
        if not isinstance(entity, dict):
            return False

        if entity.get("location_class") != self.BIOSPHERE_PATCH_LOCATION_CLASS:
            return False

        bounds = entity.get("bounds") or entity.get("geometry") or {}
        return len(self._get_geometry_points(bounds)) >= 3

    def get_biosphere_launch_context(self):
        if not self.can_create_biosphere_from_selection():
            return None

        patch = self.get_location(self.selected_entity_id)
        root = self.get_root_entity() or {}
        metrics = self._biosphere_polygon_metrics(self._get_geometry_points(patch.get("bounds") or patch.get("geometry") or {}))
        return {
            "patch_location_id": patch.get("id"),
            "patch_name": patch.get("name") or patch.get("pretty_name") or patch.get("id"),
            "parent_location_id": patch.get("parent_location") or self.context.root_entity_id,
            "root_location_id": self.context.root_entity_id,
            "root_name": root.get("name") or root.get("pretty_name") or self.context.root_entity_id,
            "year": self.year,
            "source_bounds": patch.get("bounds") or patch.get("geometry"),
            "biosphere_shape": patch.get("biosphere_shape") or metrics.get("shape"),
            "biosphere_area_m2": patch.get("biosphere_area_m2") or metrics.get("area_m2"),
            "biosphere_width_m": patch.get("biosphere_width_m") or metrics.get("width_m"),
            "biosphere_height_m": patch.get("biosphere_height_m") or metrics.get("height_m"),
            "map_context_inherited": bool(patch.get("inherits_location_context_layers", True)),
            "map_size_m": patch.get("biosphere_map_size_m") or metrics.get("map_size_m") or 10.0,
            "species_collection_id": patch.get("biosphere_species_collection") or self.BIOSPHERE_SPECIES_COLLECTION_ID,
            "biosphere_id": patch.get("biosphere_entity_id"),
        }

    def finish_map_square_draft(self):
        if not self.can_finish_map_square_draft():
            return False

        target_entity_id = self.map_square_target_entity_id
        if target_entity_id:
            bounds = self._current_map_square_bounds()
            if bounds is None:
                return False

            if not self._update_location_bounds(target_entity_id, bounds):
                logger.error(
                    f"[MapSimulation] Failed to save planet dimensions: {target_entity_id}"
                )
                return False

            self.is_creating_map_square = False
            self.map_square_anchor = None
            self.map_square_hover_pos = None
            self.map_square_target_entity_id = None
            self._draft_last_click_time = None
            self._draft_last_click_screen_pos = None
            self.last_saved_location_id = target_entity_id
            self.selected_entity_id = target_entity_id
            self.hover_entity_id = None
            self.selected_spatial_feature_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = None

            if hasattr(self.world_model, "refresh"):
                self.world_model.refresh()

            self.bounds = self._resolve_root_bounds()
            self._invalidate_layer_cache()

            logger.info(f"[MapSimulation] Saved planet dimensions {target_entity_id}")
            return True

        location = self._build_draft_map_square_location_record()
        if location.get("bounds") is None:
            return False

        try:
            self._append_location_record(location)
            parent_id = location.get("parent_location") or self.context.root_entity_id
            linked_parent = self._append_offspring_reference_to_location(parent_id, location["id"])
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save map rectangle draft: {exc}"
            )
            return False
        if not linked_parent:
            logger.info(
                f"[MapSimulation] Saved {location['id']} without parent offspring link "
                f"parent={location.get('parent_location') or self.context.root_entity_id}"
            )

        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_location_id = location["id"]
        self.selected_entity_id = location["id"]
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved location rectangle draft {location['id']}")
        return True

    def get_spatial_feature_draft_preview(self):
        if not self.is_polygon_editor_active():
            return None

        editor_points = self.get_polygon_editor_points()
        preview_points = [
            self._map_point_to_world(x, y)
            for x, y in editor_points
        ]
        preview_hover_point = None
        editor_hover_point = self.get_polygon_editor_hover_point()
        if editor_hover_point is not None:
            preview_hover_point = self._map_point_to_world(
                editor_hover_point[0],
                editor_hover_point[1],
            )

        previous_points = None
        if self.is_evolving_spatial_feature_polygon:
            source_feature = self.get_spatial_feature(self.evolving_source_spatial_feature_id)
            if source_feature is not None:
                source_points = self._get_geometry_points(source_feature.get("geometry") or {})
                if len(source_points) >= 3:
                    previous_points = [
                        self._map_point_to_world(x, y)
                        for x, y in source_points
                    ]

        mode = "draft"
        if self.is_placing_location_polygon:
            mode = "place"
        elif self.is_evolving_spatial_feature_polygon:
            mode = "evolve"
        elif self.is_editing_spatial_feature_polygon:
            mode = "edit"

        preview = {
            "points": preview_points,
            "hover_point": preview_hover_point,
            "layer_kind": self.active_layer_kind,
            "can_finish": self.can_finish_polygon_editor(),
            "area_label": self.get_draft_area_label(),
            "mode": mode,
        }

        if previous_points is not None:
            preview["previous_points"] = previous_points

        return preview

    def get_draft_area_label(self):
        editor_points = self.get_polygon_editor_points()
        if len(editor_points) < 3:
            return None

        cache_key = (
            bool(self.is_creating_biosphere_patch),
            tuple((round(float(x), 6), round(float(y), 6)) for x, y in editor_points),
        )
        if getattr(self, "_draft_area_label_cache_key", None) == cache_key:
            return getattr(self, "_draft_area_label_cache_value", None)

        if self.is_creating_biosphere_patch:
            area_label = self._format_area(self._biosphere_polygon_metrics(editor_points)["area_m2"])
        else:
            area_square_meters = self._polygon_area_square_meters(editor_points)
            area_label = self._format_area(area_square_meters)

        self._draft_area_label_cache_key = cache_key
        self._draft_area_label_cache_value = area_label
        return area_label

    def _square_bounds_side(self, bounds):
        if bounds is None:
            return 0.0

        width = abs(float(bounds["max_x"]) - float(bounds["min_x"]))
        height = abs(float(bounds["max_y"]) - float(bounds["min_y"]))
        return min(width, height)

    def _square_bounds_area_label(self, bounds):
        points = self._square_bounds_to_points(bounds)
        if len(points) < 3:
            return None

        return self._format_area(self._polygon_area_square_meters(points))

    def _square_bounds_to_points(self, bounds):
        if bounds is None:
            return []

        return [
            (bounds["min_x"], bounds["min_y"]),
            (bounds["max_x"], bounds["min_y"]),
            (bounds["max_x"], bounds["max_y"]),
            (bounds["min_x"], bounds["max_y"]),
        ]

    def _square_bounds_center(self, bounds):
        return (
            (float(bounds["min_x"]) + float(bounds["max_x"])) / 2.0,
            (float(bounds["min_y"]) + float(bounds["max_y"])) / 2.0,
        )

    def _square_bounds_from_anchor_hover(self, anchor, hover):
        if anchor is None or hover is None:
            return None

        anchor_x, anchor_y = anchor
        hover_x, hover_y = hover
        dx = float(hover_x) - float(anchor_x)
        dy = float(hover_y) - float(anchor_y)
        width = abs(dx)
        height = abs(dy)
        if width < self.MIN_SQUARE_SIDE_WORLD or height < self.MIN_SQUARE_SIDE_WORLD:
            return None

        return {
            "min_x": min(float(anchor_x), float(hover_x)),
            "max_x": max(float(anchor_x), float(hover_x)),
            "min_y": min(float(anchor_y), float(hover_y)),
            "max_y": max(float(anchor_y), float(hover_y)),
        }

    def _square_handle_positions(self, bounds):
        if bounds is None:
            return {}

        center_x, center_y = self._square_bounds_center(bounds)
        return {
            "nw": (bounds["min_x"], bounds["min_y"]),
            "ne": (bounds["max_x"], bounds["min_y"]),
            "se": (bounds["max_x"], bounds["max_y"]),
            "sw": (bounds["min_x"], bounds["max_y"]),
            "center": (center_x, center_y),
        }

    def _square_opposite_point_for_handle(self, bounds, handle):
        handles = self._square_handle_positions(bounds)
        opposites = {
            "nw": "se",
            "ne": "sw",
            "se": "nw",
            "sw": "ne",
        }
        opposite_handle = opposites.get(handle)
        if opposite_handle is None:
            return None

        return handles.get(opposite_handle)

    def _current_map_square_bounds(self):
        if self.is_editing_map_square:
            return self.editing_map_square_bounds

        if self.is_creating_map_square:
            return self._square_bounds_from_anchor_hover(
                self.map_square_anchor,
                self.map_square_hover_pos,
            )

        return None

    def can_finish_map_square_draft(self):
        return (
            self.is_creating_map_square
            and self._current_map_square_bounds() is not None
        )

    def get_map_square_preview(self):
        if not self.is_square_editor_active():
            return None

        bounds = self._current_map_square_bounds()
        handles = []
        if bounds is not None:
            handles = [
                {"id": handle_id, "point": point}
                for handle_id, point in self._square_handle_positions(bounds).items()
            ]

        return {
            "mode": "edit" if self.is_editing_map_square else "draft",
            "bounds": bounds,
            "anchor_point": self.map_square_anchor,
            "hover_point": self.map_square_hover_pos,
            "handles": handles,
            "active_handle": self.square_drag_handle,
            "can_finish": self.can_finish_map_editor(),
            "area_label": self._square_bounds_area_label(bounds),
        }

    def _format_area(self, area_square_meters):
        area_square_meters = abs(float(area_square_meters))

        if area_square_meters >= 1_000_000:
            area_square_km = area_square_meters / 1_000_000
            if area_square_km >= 1_000_000:
                return f"{area_square_km / 1_000_000:.2f}M sq km"
            if area_square_km >= 10_000:
                return f"{area_square_km:,.0f} sq km"
            if area_square_km >= 100:
                return f"{area_square_km:,.1f} sq km"
            return f"{area_square_km:,.2f} sq km"

        if area_square_meters >= 10_000:
            return f"{area_square_meters / 10_000:,.2f} ha"

        return f"{area_square_meters:,.0f} sq m"

    def _biosphere_polygon_metrics(self, points):
        parsed = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                parsed.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        if len(parsed) < 3:
            return {
                "area_m2": 100.0,
                "width_m": 10.0,
                "height_m": 10.0,
                "map_size_m": 10.0,
                "shape": {
                    "type": "polygon",
                    "coordinate_space": "biosphere_local_m",
                    "points": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
                },
            }

        xs = [point[0] for point in parsed]
        ys = [point[1] for point in parsed]
        min_x = min(xs)
        min_y = min(ys)
        local_points = [(x - min_x, y - min_y) for x, y in parsed]
        width_m = max(0.01, max(xs) - min_x)
        height_m = max(0.01, max(ys) - min_y)
        area_m2 = max(0.01, self._polygon_area(local_points))
        return {
            "area_m2": round(area_m2, 3),
            "width_m": round(width_m, 3),
            "height_m": round(height_m, 3),
            "map_size_m": round(max(width_m, height_m), 3),
            "shape": {
                "type": "polygon",
                "coordinate_space": "biosphere_local_m",
                "points": local_points,
            },
        }

    def _get_existing_entity_ids(self):
        loader = getattr(self.world_model, "loader", None)
        entities = getattr(loader, "entities", None)

        if isinstance(entities, dict):
            return set(entities.keys())

        ids = set()
        for entity in self.world_model.get_active_entities(self.year):
            entity_id = entity.get("id")
            if entity_id:
                ids.add(entity_id)

        return ids

    def _sanitize_identifier_part(self, value):
        chars = []

        for char in str(value).lower():
            if char.isalnum():
                chars.append(char)
            elif chars and chars[-1] != "_":
                chars.append("_")

        sanitized = "".join(chars).strip("_")
        return sanitized or "selection"

    def _allocate_spatial_feature_draft_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)
        if self._root_is_building():
            index = 1
            while True:
                room_id = f"loc_room_{root_id}_{index:03d}"
                if room_id not in existing_ids:
                    return room_id, index
                index += 1

        index = 1
        while True:
            feature_id = f"loc_region_{root_id}_{index:03d}"
            if feature_id not in existing_ids:
                return feature_id, index
            index += 1

    def _allocate_spatial_feature_evolution_id(self, source_feature, year):
        existing_ids = self._get_existing_entity_ids()
        source_id = self._sanitize_identifier_part(source_feature.get("id", "feature"))
        year_part = self._sanitize_identifier_part(str(year))

        index = 1
        while True:
            feature_id = f"loc_region_hist_{source_id}_y{year_part}_{index:03d}"
            if feature_id not in existing_ids:
                return feature_id, index
            index += 1

    def _allocate_location_draft_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)
        class_id = self._sanitize_identifier_part(
            self.draft_point_location_class
            if self.is_creating_point_location
            else self.draft_location_class
        )

        index = 1
        while True:
            if class_id == "region":
                location_id = f"loc_draft_{root_id}_{index:03d}"
            else:
                location_id = f"loc_draft_{class_id}_{root_id}_{index:03d}"
            if location_id not in existing_ids:
                return location_id, index
            index += 1

    def _allocate_biosphere_patch_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)

        index = 1
        while True:
            location_id = f"loc_biosphere_patch_{root_id}_{index:03d}"
            if location_id not in existing_ids:
                return location_id, index
            index += 1

    def _allocate_biosphere_roster_id(self, patch_location_id):
        existing_ids = self._get_existing_entity_ids()
        patch_part = self._sanitize_identifier_part(patch_location_id)
        base_id = f"coll_biosphere_roster_{patch_part}"
        if base_id not in existing_ids:
            return base_id

        index = 2
        while True:
            collection_id = f"{base_id}_{index:03d}"
            if collection_id not in existing_ids:
                return collection_id
            index += 1

    def _allocate_biosphere_entity_id(self, patch_location_id):
        existing_ids = self._get_existing_entity_ids()
        patch_part = self._sanitize_identifier_part(patch_location_id)
        base_id = f"biosphere_{patch_part}"
        if base_id not in existing_ids:
            return base_id

        index = 2
        while True:
            biosphere_id = f"{base_id}_{index:03d}"
            if biosphere_id not in existing_ids:
                return biosphere_id
            index += 1

    def _build_draft_spatial_feature_record(self):
        feature_id, index = self._allocate_spatial_feature_draft_id()
        if self._root_is_building():
            root_name = self.get_root_name()
            name = f"Draft Room {index:03d}"
            notes = f"Draft room polygon created inside {root_name}."
            points = list(self.draft_spatial_feature_points)
            return {
                "id": feature_id,
                "pretty_name": name,
                "name": name,
                "type": "location",
                "location_class": "room",
                "location_role": "indoor_room",
                "room_class": "room",
                "layer_kind": "rooms",
                "wiki_entry": notes,
                "parent_location": self.context.root_entity_id,
                "parent_entity": self.context.root_entity_id,
                "parents": [self.context.root_entity_id],
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "start_year": self.year,
                "entry_status": "draft",
            }

        root_name = self.get_root_name()
        if self.is_creating_biosphere_patch:
            feature_id, index = self._allocate_biosphere_patch_id()
            roster_id = self._allocate_biosphere_roster_id(feature_id)
            biosphere_id = self._allocate_biosphere_entity_id(feature_id)
            name = f"Biosphere Patch {index:03d}"
            points = list(self.draft_spatial_feature_points)
            metrics = self._biosphere_polygon_metrics(points)
            notes = (
                f"Draft biosphere design patch selected under {root_name}. "
                "The source polygon remains on the location map while BioSim resolves "
                "soil, hydrology, vegetation, and species at micro scale."
            )
            return {
                "id": feature_id,
                "pretty_name": name,
                "name": name,
                "type": "location",
                "location_class": self.BIOSPHERE_PATCH_LOCATION_CLASS,
                "location_role": "biosphere_design_patch",
                "region_class": self.BIOSPHERE_PATCH_LOCATION_CLASS,
                "wiki_entry": notes,
                "layer_kind": self.LOCATION_LAYER_KIND,
                "parent_location": self.context.root_entity_id,
                "parent_entity": self.context.root_entity_id,
                "parents": [self.context.root_entity_id],
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "biosphere_scale": "micro_polygon",
                "biosphere_area_target_m2": metrics["area_m2"],
                "biosphere_area_m2": metrics["area_m2"],
                "biosphere_width_m": metrics["width_m"],
                "biosphere_height_m": metrics["height_m"],
                "biosphere_map_size_m": metrics["map_size_m"],
                "biosphere_shape": metrics["shape"],
                "biosphere_species_collection": roster_id,
                "biosphere_entity_id": biosphere_id,
                "inherits_location_context_layers": True,
                "start_year": self.year,
                "entry_status": "draft",
            }

        if self.active_layer_kind == self.LOCATION_LAYER_KIND:
            feature_id, index = self._allocate_location_draft_id()
            location_class = self.draft_location_class or "region"
            draft_points = list(self.draft_spatial_feature_points)
            parent_id = self._smallest_draft_parent_for_points(draft_points, location_class)
            parent = self.get_location(parent_id) or {}
            parent_name = parent.get("name") or parent.get("pretty_name") or root_name
            label = str(location_class).replace("_", " ").title()
            name = f"Draft {label} {index:03d}"
            notes = f"Draft {label.lower()} polygon created under {parent_name}."
            region_class = location_class
            location_role = "map_location"
        else:
            layer_label = self.get_active_layer_label()
            name = f"Draft {layer_label} Region {index:03d}"
            notes = f"Draft region polygon created under {root_name}."
            region_class = self.active_layer_kind
            location_role = "map_region"
            location_class = "region"
            parent_id = self.context.root_entity_id

        return {
            "id": feature_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": location_class,
            "location_role": location_role,
            "region_class": region_class,
            "wiki_entry": notes,
            "layer_kind": self.active_layer_kind,
            "parent_location": parent_id,
            "parent_entity": parent_id,
            "parents": [parent_id],
            # A map-created location has its own editable boundary but uses a
            # cropped view of this parent surface until it receives a refined
            # terrain model of its own.
            "map_context_parent": parent_id,
            "inherits_parent_surface": True,
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(self.draft_spatial_feature_points),
            },
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(self.draft_spatial_feature_points),
            },
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _build_biosphere_roster_collection_record(self, patch):
        patch_id = patch.get("id")
        collection_id = patch.get("biosphere_species_collection")
        if not patch_id or not collection_id:
            return None

        patch_name = patch.get("name") or patch.get("pretty_name") or patch_id
        parent_name = self.get_root_name()
        name = f"{patch_name} Species Roster"
        return {
            "id": collection_id,
            "pretty_name": name,
            "name": name,
            "type": "collections",
            "_dataset": "collections",
            "collection_class": self.LOCALIZED_BIOSPHERE_ROSTER_CLASS,
            "biosphere_location": patch_id,
            "scope": f"Species roster for {patch_name} under {parent_name}.",
            "wiki_entry": (
                f"Localized biosphere species roster for {patch_name}. "
                "Link species into the roster buckets to make them selectable in BioSim."
            ),
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _build_biosphere_record(self, patch):
        patch_id = patch.get("id")
        biosphere_id = patch.get("biosphere_entity_id")
        if not patch_id or not biosphere_id:
            return None

        patch_name = patch.get("name") or patch.get("pretty_name") or patch_id
        name = f"{patch_name} Biosphere"
        return {
            "id": biosphere_id,
            "pretty_name": name,
            "name": name,
            "type": "biosphere",
            "_dataset": "biospheres",
            "bioregion_subclass": "terrestrial",
            "overlay_location": patch_id,
            "establishment_status": "draft",
            "wiki_entry": (
                f"Durable Biosphere overlay for {patch_name}. Soil profile is generated from worldgen "
                "where available; ecological-structure fields remain inert placeholders pending the "
                "species/population/behavior-module simulation pass."
            ),
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _build_evolved_spatial_feature_record(self, source_feature, points):
        selected_year = int(self.year)
        feature_id, _index = self._allocate_spatial_feature_evolution_id(
            source_feature,
            selected_year,
        )
        source_id = source_feature.get("id")
        source_name = (
            source_feature.get("name")
            or source_feature.get("pretty_name")
            or source_id
        )
        name = f"{source_name} ({selected_year})"
        notes = (
            f"Historical slice evolved from {source_id} at "
            f"{self.get_year_context_label()}."
        )

        related = list(source_feature.get("related") or [])
        if source_id and source_id not in related:
            related.append(source_id)

        evolved = {
            "id": feature_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "location_role": "map_region",
            "wiki_entry": notes,
            "region_class": source_feature.get("region_class") or source_feature.get("layer_kind", self.active_layer_kind),
            "layer_kind": source_feature.get("layer_kind", self.active_layer_kind),
            "parent_location": (
                source_feature.get("parent_location")
                or source_feature.get("parent_entity")
                or self.context.root_entity_id
            ),
            "parent_entity": (
                source_feature.get("parent_entity")
                or source_feature.get("parent_location")
                or self.context.root_entity_id
            ),
            "owner_entity": source_feature.get("owner_entity"),
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            },
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            },
            "start_year": selected_year,
            "end_year": self._normalize_year_value(source_feature.get("end_year")),
            "entry_status": "draft",
            "related": related,
        }
        if source_id and source_id not in evolved["related"]:
            evolved["related"].append(source_id)

        for key in (
            "resolution_m_per_pixel",
            "coverage_mode",
            "draw_order",
        ):
            if source_feature.get(key) is not None:
                evolved[key] = source_feature.get(key)

        return evolved

    def _build_draft_map_square_location_record(self):
        location_id, index = self._allocate_location_draft_id()
        root_name = self.get_root_name()
        name = f"Draft Location {index:03d}"
        notes = f"Draft location rectangle created under {root_name}."

        return {
            "id": location_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "parent_location": self.context.root_entity_id,
            "parent_entity": self.context.root_entity_id,
            "parents": [self.context.root_entity_id],
            "map_context_parent": self.context.root_entity_id,
            "inherits_parent_surface": True,
            "wiki_entry": notes,
            "bounds": self._current_map_square_bounds(),
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _append_spatial_feature_record(self, feature):
        feature["type"] = "location"
        feature["_dataset"] = "locations"
        if not feature.get("location_class"):
            feature["location_class"] = "region"
        if not self._persist_repository_entity(feature, "locations"):
            raise OSError("Could not persist spatial feature location to ontology")

    def _append_location_record(self, location):
        if not self._persist_repository_entity(location, "locations"):
            raise OSError("Could not persist location to ontology")

    def _append_collection_record(self, collection):
        if not isinstance(collection, dict):
            return False
        collection["type"] = "collections"
        collection["_dataset"] = "collections"
        if not self._persist_repository_entity(collection, "collections"):
            raise OSError("Could not persist collection to ontology")
        return True

    def _append_biosphere_record(self, biosphere):
        if not isinstance(biosphere, dict):
            return False
        biosphere["type"] = "biosphere"
        biosphere["_dataset"] = "biospheres"
        if not self._persist_repository_entity(biosphere, "biospheres"):
            raise OSError("Could not persist biosphere to ontology")
        return True

    def _append_offspring_reference_to_location(self, parent_location_id, child_location_id):
        if not parent_location_id or not child_location_id:
            return False

        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "set_relation"):
            return False
        changed = set()
        changed.update(loader.set_relation(child_location_id, "parents", parent_location_id, persist=False))
        changed.update(loader.set_relation(parent_location_id, "constituents", child_location_id, persist=False))
        child = getattr(loader, "entities", {}).get(child_location_id)
        if isinstance(child, dict) and not child.get("parent_location"):
            changed.update(loader.set_literal(child_location_id, "parent_location", parent_location_id, persist=False))
        if changed:
            loader.save_changed_dataset_files(changed)
        return bool(changed) or parent_location_id in self._relation_entity_ids(
            getattr(loader, "entities", {}).get(child_location_id, {}).get("parents")
        )

    def save_selection_inspector_updates(self, target_kind, target_id, updates):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        name = str(updates.get("name", "")).strip()
        notes = str(updates.get("wiki_entry", updates.get("notes", ""))).strip()

        if not name:
            name = str(target_id)

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False

            updated = self._update_spatial_feature_text_fields(target_id, name, notes)
        else:
            if not self._can_open_location_inspector(target_id):
                return False

            updated = self._update_location_text_fields(target_id, name, notes)

        if not updated:
            return False

        self._notify_incremental_repository_change(rebuild_relations=False)

        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Updated inspector fields {target_kind}:{target_id}")
        return True

    def delete_selection_inspector_target(self, target_kind, target_id):
        if target_kind != "spatial_feature":
            return False
        if not self._is_real_spatial_feature_id(target_id):
            return False

        entity = self.get_spatial_feature(target_id)
        if not isinstance(entity, dict):
            return False

        is_location_region = self._is_location_backed_region(target_id)
        parent_location_id = entity.get("parent_location") or entity.get("parent_entity")

        try:
            removed_from_repository = self._remove_repository_entity(
                target_id,
                dataset_name="locations",
            )
            if removed_from_repository is False:
                return False
            if removed_from_repository and is_location_region and parent_location_id:
                self._remove_offspring_reference_from_location(parent_location_id, target_id)
            elif is_location_region and parent_location_id:
                self._remove_offspring_reference_from_location(parent_location_id, target_id)
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to delete region {target_id}: {exc}")
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        if self.selected_entity_id == target_id:
            self.selected_entity_id = None
        self.hover_entity_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = None
        self._pending_floating_card_target = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Deleted region {target_id}")
        return True

    def reanchor_selection_time(self, target_kind, target_id, year):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False
            entity = self.get_spatial_feature(target_id)
        else:
            if not self._can_open_location_inspector(target_id):
                return False
            entity = self.get_location(target_id)

        if not isinstance(entity, dict):
            return False

        updates = self._build_time_reanchor_updates(entity, year)
        if not updates:
            return False

        try:
            if not self._update_entity_temporal_fields(target_id, updates):
                return False
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to reanchor {target_kind}:{target_id}: {exc}")
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.context.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0
        if target_kind == "spatial_feature":
            self.selected_entity_id = None
            self.selected_spatial_feature_id = target_id
        else:
            self.selected_entity_id = target_id
            self.selected_spatial_feature_id = None
        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = {
            "kind": target_kind,
            "id": target_id,
        }
        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Reanchored {target_kind}:{target_id} to year {year}"
        )
        return True

    def _build_time_reanchor_updates(self, entity, year):
        old_start_year = self._normalize_year_value(entity.get("start_year"))
        old_end_year = self._normalize_year_value(entity.get("end_year"))
        updates = {}

        if "year" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("year"))
            updates["year"] = year
        elif "year_number" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("year_number"))
            updates["year_number"] = year
        elif "start_year" in entity:
            old_anchor_year = old_start_year
            updates["start_year"] = year

            if old_start_year is not None and old_end_year is not None:
                if old_end_year >= old_start_year and old_end_year != old_start_year:
                    updates["end_year"] = old_end_year + (year - old_start_year)
                elif old_end_year == old_start_year:
                    updates["end_year"] = year
        elif "effective_year" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("effective_year"))
            updates["effective_year"] = year
        elif "end_year" in entity:
            old_anchor_year = old_end_year
            updates["end_year"] = year
        else:
            old_anchor_year = None
            updates["start_year"] = year

        if "effective_year" in entity:
            old_effective_year = self._normalize_year_value(entity.get("effective_year"))
            if old_effective_year is None or old_effective_year == old_anchor_year:
                updates["effective_year"] = year

        return updates

    def _is_real_spatial_feature_id(self, spatial_feature_id):
        if not spatial_feature_id:
            return False

        return not str(spatial_feature_id).startswith("virtual:")

    def _is_location_backed_region(self, entity_id):
        entity = self.get_location(entity_id)
        return (
            isinstance(entity, dict)
            and entity.get("_dataset") in (None, "locations")
            and entity.get("type") == "location"
            and entity.get("location_class") in {"region", "state", "quarter"}
        )

    def _remove_offspring_reference_from_location(self, parent_location_id, child_location_id):
        if not parent_location_id or not child_location_id:
            return False

        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "remove_relation"):
            return False
        changed = set()
        changed.update(loader.remove_relation(child_location_id, "parents", parent_location_id, persist=False))
        changed.update(loader.remove_relation(parent_location_id, "constituents", child_location_id, persist=False))
        child = getattr(loader, "entities", {}).get(child_location_id)
        if isinstance(child, dict) and child.get("parent_location") == parent_location_id:
            changed.update(loader.set_literal(child_location_id, "parent_location", "", persist=False))
        if changed:
            loader.save_changed_dataset_files(changed)
        return bool(changed)

    def _update_entity_temporal_fields(self, entity_id, field_values):
        return self._update_repository_entity_fields(entity_id, field_values)

    def _update_spatial_feature_text_fields(self, spatial_feature_id, name, notes):
        if self._is_location_backed_region(spatial_feature_id):
            return self._update_location_text_fields(spatial_feature_id, name, notes)

        updated_repository = self._update_repository_entity_fields(
            spatial_feature_id,
            {"pretty_name": name, "name": name, "wiki_entry": notes},
        )
        return updated_repository

    def _update_location_text_fields(self, location_id, name, notes):
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {"pretty_name": name, "name": name, "wiki_entry": notes},
        )
        return updated_repository

    def _update_location_map_image_fields(self, location_id, updates):
        return self._update_repository_entity_fields(location_id, dict(updates))

    def _update_spatial_feature_geometry(self, spatial_feature_id, points):
        if self._is_location_backed_region(spatial_feature_id):
            bounds = {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            }
            if not self._update_location_bounds(spatial_feature_id, bounds):
                return False
            if not self._update_location_geometry(spatial_feature_id, points):
                return False
            return True

        updated_repository = self._update_repository_entity_fields(
            spatial_feature_id,
            {
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": list(points),
                }
            },
        )
        return updated_repository

    def _update_location_bounds(self, location_id, bounds):
        return self._update_repository_entity_fields(location_id, {"bounds": bounds})

    def _update_location_geometry(self, location_id, points):
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": list(points),
                }
            },
        )
        return updated_repository

    def _update_location_parent(self, location_id, parent_location_id):
        location = self.get_location(location_id)
        previous_parent_id = (
            self._structural_parent_location_id(location)
            if isinstance(location, dict)
            else None
        )
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {
                "parent_location": parent_location_id,
                "parent_entity": parent_location_id,
                "parents": [parent_location_id] if parent_location_id else [],
                "map_context_parent": parent_location_id,
            },
        )
        if not updated_repository:
            return False
        if previous_parent_id and previous_parent_id != parent_location_id:
            self._remove_offspring_reference_from_location(previous_parent_id, location_id)
        if parent_location_id:
            self._append_offspring_reference_to_location(parent_location_id, location_id)
        return updated_repository

    def _update_spatial_feature_end_year(self, spatial_feature_id, end_year):
        return self._update_repository_entity_fields(spatial_feature_id, {"end_year": end_year})

    def _is_draft_double_click(self, screen_pos):
        if self._draft_last_click_time is None:
            return False

        if self._draft_last_click_screen_pos is None:
            return False

        now = time.monotonic()
        if now - self._draft_last_click_time > self.DRAFT_DOUBLE_CLICK_SECONDS:
            return False

        last_x, last_y = self._draft_last_click_screen_pos
        dx = float(screen_pos[0]) - float(last_x)
        dy = float(screen_pos[1]) - float(last_y)
        distance_sq = dx * dx + dy * dy

        return distance_sq <= self.DRAFT_DOUBLE_CLICK_DISTANCE_PX ** 2

    def _record_draft_click(self, screen_pos):
        self._draft_last_click_time = time.monotonic()
        self._draft_last_click_screen_pos = screen_pos

    def _is_selection_double_click(self, target, screen_pos):
        if self._selection_last_click_time is None:
            return False

        if self._selection_last_click_screen_pos is None:
            return False

        if target != self._selection_last_click_target:
            return False

        now = time.monotonic()
        if now - self._selection_last_click_time > self.DRAFT_DOUBLE_CLICK_SECONDS:
            return False

        last_x, last_y = self._selection_last_click_screen_pos
        dx = float(screen_pos[0]) - float(last_x)
        dy = float(screen_pos[1]) - float(last_y)
        distance_sq = dx * dx + dy * dy

        return distance_sq <= self.DRAFT_DOUBLE_CLICK_DISTANCE_PX ** 2

    def _record_selection_click(self, target, screen_pos):
        self._selection_last_click_time = time.monotonic()
        self._selection_last_click_screen_pos = screen_pos
        self._selection_last_click_target = target

    def _begin_camera_drag(self, screen_pos, camera):
        self.is_camera_dragging = True
        self.camera_drag_start_screen_pos = screen_pos
        self.camera_drag_start_camera_pos = (camera.x, camera.y)
        self.camera_drag_has_moved = False
        self.map_projection_dragging = False
        self.map_projection_drag_start = None

    def _reset_camera_drag(self):
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False
        self.map_projection_dragging = False
        self.map_projection_drag_start = None

    def _update_camera_drag(self, screen_pos, camera):
        if not self.is_camera_dragging:
            return False

        if self.camera_drag_start_screen_pos is None:
            return False

        if self.camera_drag_start_camera_pos is None:
            return False

        dx = float(screen_pos[0]) - float(self.camera_drag_start_screen_pos[0])
        dy = float(screen_pos[1]) - float(self.camera_drag_start_screen_pos[1])

        if not self.camera_drag_has_moved:
            distance_sq = dx * dx + dy * dy
            if distance_sq < self.CAMERA_DRAG_THRESHOLD_PX ** 2:
                return False

            self.camera_drag_has_moved = True

        start_camera_x, start_camera_y = self.camera_drag_start_camera_pos
        zoom = max(float(camera.zoom), 1e-9)
        camera.x = start_camera_x - (dx / zoom)
        camera.y = start_camera_y - (dy / zoom)

        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        return True

    def _entity_id_is_in_root_scope(self, entity_id):
        if not entity_id:
            return False

        entity = self.world_model.get_entity(entity_id)
        if not entity:
            return False

        return self.context._is_in_root_subtree(entity)

    def _spatial_feature_is_in_scope(self, feature):
        owner_entity_id = feature.get("owner_entity")
        parent_entity_id = feature.get("parent_location") or feature.get("parent_entity")

        if self._entity_id_is_in_root_scope(owner_entity_id):
            return True

        if self._entity_id_is_in_root_scope(parent_entity_id):
            return True

        return False

    def _get_scoped_spatial_features(self):
        root_entity_id = self.context.root_entity_id
        features = [
            entity for entity in self.world_model.get_active_entities(
                self.year,
                dataset_name="locations",
                entity_type="location",
            )
            if entity.get("location_class") in {"region", "state", "quarter"}
            and (entity.get("geometry") or entity.get("bounds"))
            and entity.get("id") != root_entity_id
        ]

        return [
            feature for feature in features
            if self._spatial_feature_is_in_scope(feature)
        ]

    def _color_for_spatial_layer(self, layer_kind):
        return self.SPATIAL_LAYER_COLORS.get(layer_kind, (120, 112, 145))

    def _get_geometry_points(self, geometry):
        geometry_type = geometry.get("type")

        if geometry_type == "polygon":
            points = geometry.get("points", [])
            return [
                (float(point[0]), float(point[1]))
                for point in points
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]

        if geometry_type == "bbox":
            min_x = float(geometry.get("min_x", 0.0))
            max_x = float(geometry.get("max_x", 0.0))
            min_y = float(geometry.get("min_y", 0.0))
            max_y = float(geometry.get("max_y", 0.0))
            return [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
            ]

        if geometry_type == "multipolygon":
            points = []
            for ring in geometry.get("polygons", []):
                if not isinstance(ring, list):
                    continue
                points.extend(
                    (float(point[0]), float(point[1]))
                    for point in ring
                    if isinstance(point, (list, tuple)) and len(point) >= 2
                )
            return points

        if geometry_type == "polyline":
            points = geometry.get("points", [])
            return [
                (float(point[0]), float(point[1]))
                for point in points
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]

        return []

    def _point_coords_from_entity(self, entity):
        coords = entity.get("coords") if isinstance(entity, dict) else None
        if isinstance(coords, dict) and coords.get("type") == "point":
            return coords

        bounds = entity.get("bounds") if isinstance(entity, dict) else None
        if isinstance(bounds, dict) and bounds.get("type") == "point":
            return bounds

        return None

    def _get_geometry_rings(self, geometry):
        geometry_type = geometry.get("type")
        if geometry_type in {"bbox", "polygon"}:
            points = self._get_geometry_points(geometry)
            return [points] if len(points) >= 3 else []
        if geometry_type == "multipolygon":
            rings = []
            for ring in geometry.get("polygons", []):
                if not isinstance(ring, list):
                    continue
                points = [
                    (float(point[0]), float(point[1]))
                    for point in ring
                    if isinstance(point, (list, tuple)) and len(point) >= 2
                ]
                if len(points) >= 3:
                    rings.append(points)
            return rings
        return []

    def _build_location_geometry_layers(self, entity, geometry, color):
        layers = []
        root = self.get_root_entity()
        if (
            isinstance(root, dict)
            and isinstance(root.get("reference_land_polygons"), dict)
            and entity.get("location_class") == "ocean"
        ):
            # The authored Earth raster already supplies the true coastline and
            # bathymetry. Legacy broad ocean rectangles self-intersect under an
            # oblique projection, so oceans use their projected point labels.
            return layers
        rings = self._get_geometry_rings(geometry)
        entity_id = entity.get("id")
        for ring_index, map_points in enumerate(rings):
            area_world = self._polygon_area(map_points)
            if isinstance(root, dict) and root.get("location_class") in {"planet", "moon"}:
                focus_x, focus_y = self._vector_projection_focus()
                display_rings = project_map_world_ring(
                    map_points, focus_x, focus_y,
                )
            else:
                display_rings = [[self._map_point_to_world(*point) for point in map_points]]
            for copy_index, points in enumerate(display_rings):
                centroid_x, centroid_y = self._polygon_centroid(points)
                layer = {
                    "shape": "polygon", "x": centroid_x, "y": centroid_y,
                    "points": points, "name": entity.get("name"), "entity_id": entity_id,
                    "color": color, "area_world": area_world, "geometry_part": ring_index,
                    "projection_geometry_copy": copy_index,
                }
                self._decorate_surface_location_layer(layer, entity, area_world=area_world)
                if len(rings) > 1 or copy_index > 0:
                    layer["suppress_label"] = True
                    layer["draw_order"] = float(layer.get("draw_order", 0.0) or 0.0) + ring_index * 0.001
                layers.append(layer)
        return layers

    def _build_location_polyline_layers(self, entity, geometry, color):
        if not isinstance(geometry, dict) or geometry.get("type") != "polyline":
            return []
        raw_paths = geometry.get("paths") or [geometry.get("points") or []]
        root = self.get_root_entity()
        entity_id = entity.get("id")
        layers = []
        for path_index, raw_path in enumerate(raw_paths):
            map_points = [
                (float(point[0]), float(point[1]))
                for point in raw_path
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ] if isinstance(raw_path, list) else []
            if len(map_points) < 2:
                continue
            if isinstance(root, dict) and root.get("location_class") in {"planet", "moon"}:
                focus_x, focus_y = self._vector_projection_focus()
                display_paths = project_map_world_line(map_points, focus_x, focus_y)
            else:
                display_paths = [[self._map_point_to_world(*point) for point in map_points]]
            for copy_index, points in enumerate(display_paths):
                if len(points) < 2:
                    continue
                midpoint = points[len(points) // 2]
                layer = {
                    "shape": "polyline",
                    "x": midpoint[0], "y": midpoint[1],
                    "points": points,
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                    "line_width": entity.get("map_line_width", 2),
                    "geometry_part": path_index,
                    "projection_geometry_copy": copy_index,
                }
                self._decorate_surface_location_layer(layer, entity)
                layer["suppress_label"] = True
                layer["draw_order"] = float(layer.get("draw_order", 0.0) or 0.0) + path_index * 0.001
                layers.append(layer)
        return layers

    def _polygon_area(self, points):
        if len(points) < 3:
            return 0.0

        total = 0.0
        previous_x, previous_y = points[-1]

        for x, y in points:
            total += (previous_x * y) - (x * previous_y)
            previous_x = x
            previous_y = y

        return abs(total) / 2.0

    def _polygon_area_square_meters(self, points):
        if len(points) < 3:
            return 0.0

        mean_latitude = 0.0
        for _lon, stored_y in points:
            mean_latitude += -float(stored_y)
        mean_latitude /= len(points)

        latitude_scale_m = self.MAP_METERS_PER_WORLD_UNIT
        longitude_scale_m = latitude_scale_m * max(
            0.01,
            abs(math.cos(math.radians(mean_latitude))),
        )
        projected_points = [
            (
                float(lon) * longitude_scale_m,
                -float(stored_y) * latitude_scale_m,
            )
            for lon, stored_y in points
        ]

        return self._polygon_area(projected_points)

    def _polygon_centroid(self, points):
        if not points:
            return 0.0, 0.0

        total_x = 0.0
        total_y = 0.0

        for x, y in points:
            total_x += x
            total_y += y

        count = max(1, len(points))
        return total_x / count, total_y / count

    def _root_bounds_as_polygon(self):
        bounds = self.bounds
        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]

        return [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        ]

    def _build_virtual_spatial_layer(self, layer_kind):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None

        root_entity_id = root_entity.get("id")
        points = self._root_bounds_as_polygon()
        centroid_x, centroid_y = self._polygon_centroid(points)
        layer_label = self._format_layer_label(layer_kind)

        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": f"{self.get_root_name()} {layer_label}",
            "entity_id": root_entity_id,
            "spatial_feature_id": f"virtual:{layer_kind}:{root_entity_id}",
            "layer_kind": layer_kind,
            "color": self._color_for_spatial_layer(layer_kind),
            "area_world": self._polygon_area(points),
            "resolution_m_per_pixel": None,
            "coverage_mode": "virtual_aggregate",
            "is_virtual_spatial_feature": True,
            "draw_order": -1000,
        }

    def _build_spatial_feature_layer(self, feature):
        if (
            (
                self.is_editing_spatial_feature_polygon
                or self.is_evolving_spatial_feature_polygon
            )
            and feature.get("id") == self.editing_spatial_feature_id
        ):
            return None

        geometry = feature.get("geometry") or feature.get("bounds") or {}
        map_points = self._get_geometry_points(geometry)

        if len(map_points) < 3:
            return None

        points = [
            self._map_point_to_world(x, y)
            for x, y in map_points
        ]
        feature_layer_kind = feature.get("layer_kind") or self.REGION_LAYER_KIND
        layer_kind = self.REGION_LAYER_KIND
        region_class = feature.get("region_class") or feature.get("layer_kind")
        ground_material = str(feature.get("ground_material") or "").strip().lower()
        centroid_x, centroid_y = self._polygon_centroid(points)
        color_key = ground_material if feature_layer_kind == self.GROUND_MATERIALS_LAYER_KIND and ground_material else region_class or layer_kind
        fallback_color = self._color_for_spatial_layer(color_key)
        # The ontology already has a real per-material analytical color (the
        # same one the Materials layer uses) -- resolve it here too instead
        # of always falling through to the generic SPATIAL_LAYER_COLORS
        # swatch, which only names a couple of materials.
        resolved_color = (
            material_geological_map_color(ground_material, fallback=fallback_color)
            if feature_layer_kind == self.GROUND_MATERIALS_LAYER_KIND and ground_material
            else fallback_color
        )

        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": feature.get("name") or feature.get("pretty_name") or feature.get("id"),
            "entity_id": feature.get("owner_entity") or feature.get("id"),
            "spatial_feature_id": feature.get("id"),
            "layer_kind": layer_kind,
            "feature_layer_kind": feature_layer_kind,
            "region_class": region_class,
            "parent_entity": feature.get("parent_location") or feature.get("parent_entity"),
            "ground_material": ground_material,
            "ground_material_intensity": feature.get("ground_material_intensity"),
            "color": resolved_color,
            "area_world": self._polygon_area(map_points),
            "resolution_m_per_pixel": feature.get("resolution_m_per_pixel"),
            "coverage_mode": feature.get("coverage_mode"),
            "draw_order": feature.get("draw_order", 0),
            "wiki_entry": feature.get("wiki_entry"),
        }

    def _spatial_layer_sort_key(self, layer):
        is_virtual = 0 if layer.get("is_virtual_spatial_feature") else 1
        area_world = layer.get("area_world", 0.0)
        resolution = layer.get("resolution_m_per_pixel")

        if resolution is None:
            resolution = 0.0

        return (
            layer.get("draw_order", 0),
            is_virtual,
            -area_world,
            -float(resolution),
        )

    def _map_context_entities(self):
        entities = []
        seen = set()
        current = self.get_root_entity()

        while current:
            entity_id = current.get("id")
            if not entity_id or entity_id in seen:
                break

            seen.add(entity_id)
            entities.append(current)

            parent_id = self._structural_parent_location_id(current)
            if not parent_id:
                break
            current = self.world_model.get_entity(parent_id)

        return entities

    def _location_has_context_geometry(self, entity):
        if not isinstance(entity, dict):
            return False

        bounds = entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon", "multipolygon"}:
            return len(self._get_geometry_points(bounds)) >= 3
        if bounds.get("type") == "polyline":
            paths = bounds.get("paths") or [bounds.get("points") or []]
            return any(isinstance(path, list) and len(path) >= 2 for path in paths)

        if entity.get("location_class") in {"planet", "moon"}:
            return True

        image_path = entity.get("map_image_path")
        return bool(image_path and self._map_image_rect_from_entity(entity) is not None)

    def _map_context_sister_entities(self, context_entities):
        if self.world_model is None:
            return []

        context_ids = {
            entity.get("id")
            for entity in context_entities
            if isinstance(entity, dict) and entity.get("id")
        }
        parent_ids = []
        for entity in context_entities:
            parent_id = self._structural_parent_location_id(entity) if isinstance(entity, dict) else None
            if parent_id and parent_id not in parent_ids:
                parent_ids.append(parent_id)

        locations = self.world_model.get_active_entities(
            self.year,
            dataset_name="locations",
            entity_type="location",
        )
        sisters = []
        seen = set()
        if parent_ids:
            for parent_id in parent_ids:
                for entity in locations:
                    entity_id = entity.get("id")
                    if not entity_id or entity_id in context_ids or entity_id in seen:
                        continue
                    if self._structural_parent_location_id(entity) != parent_id:
                        continue
                    if not self._is_surface_map_location(entity):
                        continue
                    if not self._location_has_context_geometry(entity):
                        continue
                    seen.add(entity_id)
                    sisters.append(entity)

        topology_ids = []
        for entity in context_entities:
            if not isinstance(entity, dict):
                continue
            for field_key in ("neighbours", "overlaps", "constituents"):
                for related_id in self._relation_entity_ids(entity.get(field_key)):
                    if related_id not in topology_ids:
                        topology_ids.append(related_id)

        for related_id in topology_ids:
            if related_id in context_ids or related_id in seen:
                continue
            related = self.world_model.get_entity(related_id)
            if not self._is_location_entity(related):
                continue
            if not self._is_surface_map_location(related):
                continue
            if self.context._is_in_root_subtree(related):
                continue
            if not self._location_has_context_geometry(related):
                continue
            seen.add(related_id)
            sisters.append(related)

        return sisters

    def _label_for_entity(self, entity):
        return (
            entity.get("name")
            or entity.get("pretty_name")
            or entity.get("id")
            or "location"
        )

    def _build_ghost_context_layers(self):
        layers = []
        context_entities = self._map_context_entities()
        if not context_entities:
            return layers

        for index, entity in enumerate(reversed(context_entities)):
            if (
                not self.is_placing_location_polygon
                and entity.get("id") == self.context.root_entity_id
            ):
                continue
            color = self._color_for_entity(entity)
            layer = self._build_location_bounds_layer(
                entity,
                color,
                draw_order=-3000 + index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["pickable"] = False
                if self.is_placing_location_polygon:
                    layer["alpha"] = 4 if index < len(context_entities) - 1 else 10
                    layer["border_alpha"] = 72 if index < len(context_entities) - 1 else 118
                else:
                    layer["alpha"] = 34 if index < len(context_entities) - 1 else 52
                    layer["border_alpha"] = 98 if index < len(context_entities) - 1 else 132
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)

            image_path = entity.get("map_image_path")
            image_rect = self._map_image_rect_from_entity(entity)
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": self._label_for_entity(entity),
                    "entity_id": entity.get("id"),
                    "draw_order": -3100 + index,
                    "is_ghost_context": True,
                    "pickable": False,
                    "alpha": 68,
                })

        sister_start_index = len(context_entities)
        for sister_index, entity in enumerate(self._map_context_sister_entities(context_entities)):
            color = self._color_for_entity(entity)
            draw_index = sister_start_index + sister_index
            layer = self._build_location_bounds_layer(
                entity,
                color,
                draw_order=-2900 + draw_index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["is_ghost_sister"] = True
                layer["pickable"] = False
                layer["alpha"] = 0 if self.is_placing_location_polygon else 24
                layer["border_alpha"] = 52 if self.is_placing_location_polygon else 86
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)

            image_path = entity.get("map_image_path")
            image_rect = self._map_image_rect_from_entity(entity)
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": self._label_for_entity(entity),
                    "entity_id": entity.get("id"),
                    "draw_order": -2950 + draw_index,
                    "is_ghost_context": True,
                    "is_ghost_sister": True,
                    "pickable": False,
                    "alpha": 44,
                })

        return layers

    def _build_spatial_feature_layers(self, year, layer_kind):
        layers = self._build_ghost_context_layers()

        for feature in self._get_scoped_spatial_features():
            feature_layer_kind = feature.get("layer_kind") or self.REGION_LAYER_KIND
            if layer_kind != self.REGION_LAYER_KIND and feature_layer_kind != layer_kind:
                continue
            layer = self._build_spatial_feature_layer(feature)
            if layer is not None:
                if layer_kind == self.GROUND_MATERIALS_LAYER_KIND:
                    # Region authoring uses a contour-only geographic base;
                    # categorical fills would obscure the elevation reference.
                    layer = dict(layer)
                    layer["outline_only"] = True
                    layer["border_color"] = layer.get("color", (190, 178, 150))
                    layer["border_width"] = max(2, int(layer.get("border_width", 0) or 0))
                layers.append(layer)

        layers.sort(key=self._spatial_layer_sort_key)
        return layers

    def _build_location_bounds_layer(self, entity, color, draw_order=0, virtual=False):
        bounds = entity.get("bounds") or {}
        points = []

        if bounds.get("type") == "bbox":
            points = self._get_geometry_points(bounds)
        elif bounds.get("type") == "polygon":
            points = self._get_geometry_points(bounds)
        elif entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            points = [
                (rect["x"] - half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] + half_h),
                (rect["x"] - half_w, rect["y"] + half_h),
            ]

        if len(points) < 3:
            return None

        world_points = [
            self._map_point_to_world(point[0], point[1])
            for point in points
        ]
        centroid_x, centroid_y = self._polygon_centroid(world_points)
        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": world_points,
            "name": entity.get("name"),
            "entity_id": entity.get("id"),
            "color": color,
            "area_world": self._polygon_area(points),
            "draw_order": draw_order,
            "is_virtual_spatial_feature": virtual,
        }

    def _build_default_building_floor_layer(self):
        if not self._root_is_building():
            return None

        root_entity = self.get_root_entity()
        if not root_entity:
            return None

        points = self._root_bounds_as_polygon()
        centroid_x, centroid_y = self._polygon_centroid(points)
        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": root_entity.get("name") or root_entity.get("pretty_name") or self.context.root_entity_id,
            "entity_id": self.context.root_entity_id,
            "color": self._color_for_entity(root_entity),
            "area_world": self._polygon_area(points),
            "draw_order": -2000,
            "is_virtual_building_floor": True,
        }

    def _build_placement_ancestor_layers(self):
        layers = []
        if not self.is_placing_location_polygon:
            return layers

        context_ids = {
            entity.get("id")
            for entity in self._map_context_entities()
            if isinstance(entity, dict) and entity.get("id")
        }

        for index, entity_id in enumerate(reversed(self.placement_ancestor_entity_ids)):
            if entity_id in context_ids:
                continue
            entity = self.get_location(entity_id)
            if not entity:
                continue
            layer = self._build_location_bounds_layer(
                entity,
                self._color_for_entity(entity),
                draw_order=-100 - index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["is_placement_ancestor"] = True
                layer["pickable"] = False
                layer["alpha"] = 0
                layer["border_alpha"] = 118
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)
        return layers

    def _selected_material_heatmap_layer(self, heatmap_model):
        selected_id = str(self.active_material_heatmap_layer_id or "composite")
        occurrence_selected = selected_id.startswith("occurrence_")
        if selected_id == "composite":
            composite = heatmap_model.get("composite_layer")
            if self._material_heatmap_layer_has_raster(composite):
                return composite

        for layer in heatmap_model.get("layers") or []:
            if not isinstance(layer, dict):
                continue
            layer_ids = {
                str(layer.get("material_id") or ""),
                str(layer.get("id") or ""),
                str(layer.get("bundle_layer_id") or ""),
                str(layer.get("image_path") or ""),
            }
            if selected_id in layer_ids and self._material_heatmap_layer_has_raster(layer):
                return layer

        composite = heatmap_model.get("composite_layer")
        if self._material_heatmap_layer_has_raster(composite):
            if not occurrence_selected:
                self.active_material_heatmap_layer_id = "composite"
            return composite

        return next(
            (
                layer
                for layer in heatmap_model.get("layers") or []
                if self._material_heatmap_layer_has_raster(layer)
            ),
            {},
        )

    def _material_heatmap_context(self, root_entity=None):
        root_entity = root_entity or self.get_root_entity()
        if not isinstance(root_entity, dict):
            return None, None
        own_generated = self._own_generated_region(root_entity)
        if isinstance(own_generated, dict) and isinstance(own_generated.get("material_heatmap_model"), dict):
            # Unlike the root_planet fallback below, this raster was
            # generated directly for this region's own full extent (see
            # generate_material_heatmap_model in regional_refinement.py) --
            # it is not a shared planet-wide atlas needing a UV crop. Passing
            # the heightmap's *placement-in-parent* source_uv_bounds here
            # would crop an already-correct, self-contained raster down to a
            # small, wrong sub-rectangle (this is what made True Color render
            # blank after a region regeneration).
            return own_generated.get("material_heatmap_model"), None
        heatmap_model = root_entity.get("material_heatmap_model")
        source_uv_bounds = None
        if (
            not isinstance(heatmap_model, dict)
            and root_entity.get("location_class") == "generated_region"
        ):
            lineage = root_entity.get("generated_truth_lineage") or {}
            root_planet_id = lineage.get("root_planet_id")
            root_planet = (
                self.world_model.get_entity(root_planet_id)
                if root_planet_id
                else None
            )
            if isinstance(root_planet, dict):
                heatmap_model = root_planet.get("material_heatmap_model")
                source_uv_bounds = (
                    (root_entity.get("heightmap_model") or {}).get(
                        "source_uv_bounds"
                    )
                    or lineage.get("source_uv_bounds")
                )
        return heatmap_model, source_uv_bounds

    def _build_material_heatmap_layers(self):
        from simulations.world_gen.regional_refinement import map_physical_dimensions_m

        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return []
        if (
            root_entity.get("location_class") not in {"planet", "moon", "generated_region"}
            and self._own_generated_region(root_entity) is None
        ):
            return []

        heatmap_model, source_uv_bounds = self._material_heatmap_context(
            root_entity
        )
        if not isinstance(heatmap_model, dict):
            return []

        selected_layer = dict(
            self._selected_material_heatmap_layer(heatmap_model)
        )
        image_path = selected_layer.get("image_path")
        bundle_path = selected_layer.get("bundle_path")
        bundle_layer_id = selected_layer.get("bundle_layer_id")
        if not image_path and not (bundle_path and bundle_layer_id):
            return []

        rect = self._planet_rect_from_entity(root_entity)
        layers = [{
            "shape": "image_rect",
            "x": rect["x"],
            "y": rect["y"],
            "width_world": rect["width_world"],
            "height_world": rect["height_world"],
            "image_path": image_path,
            "bundle_path": bundle_path,
            "bundle_layer_id": bundle_layer_id,
            "fit": "stretch_to_bounds",
            "name": selected_layer.get("name") or "Material Distribution",
            "entity_id": root_entity.get("id"),
            "draw_order": -950,
            "alpha": 232,
            "pickable": False,
            "material_heatmap_model": heatmap_model,
            "material_id": selected_layer.get("material_id"),
            "display_color": selected_layer.get("display_color"),
            "geological_map_color": material_geological_map_color(
                selected_layer.get("material_id"),
                selected_layer.get("geological_map_color"),
            ),
            "render_mode": selected_layer.get("render_mode"),
            "formation_category": selected_layer.get("formation_category"),
            "distribution_role": selected_layer.get("distribution_role"),
            "dominance_threshold": selected_layer.get("dominance_threshold"),
        }]
        if isinstance(source_uv_bounds, dict):
            layers[0]["source_uv_bounds"] = dict(source_uv_bounds)

        regional_model = root_entity.get("regional_material_model")
        occurrences = (
            regional_model.get("occurrences") or []
            if isinstance(regional_model, dict)
            else []
        )
        if self.selected_material_occurrence_id:
            selected_occurrences = [
                occurrence
                for occurrence in occurrences
                if isinstance(occurrence, dict)
                and str(occurrence.get("id") or "")
                == self.selected_material_occurrence_id
            ]
            if selected_occurrences:
                occurrences = selected_occurrences
        left = rect["x"] - rect["width_world"] * 0.5
        top = rect["y"] - rect["height_world"] * 0.5
        physical_width_m, physical_height_m = map_physical_dimensions_m(root_entity)
        for index, occurrence in enumerate(occurrences):
            if not isinstance(occurrence, dict):
                continue
            center = occurrence.get("center") or {}
            material_id = str(occurrence.get("material_id") or "")
            color = material_display_color(material_id)
            center_x = float(center.get("x", 0.5) or 0.5)
            center_y = float(center.get("y", 0.5) or 0.5)
            world_x = left + center_x * rect["width_world"]
            world_y = top + center_y * rect["height_world"]
            marker_layer = {
                "shape": "marker",
                "x": world_x,
                "y": world_y,
                "min_screen_size": 8,
                "name": occurrence.get("name") or material_id,
                "entity_id": occurrence.get("id"),
                "color": tuple(color[:3]),
                "draw_order": -900 + index * 0.001,
                "pickable": True,
                "material_occurrence": occurrence,
            }

            spatial_representation = str(
                occurrence.get("spatial_representation") or ""
            )
            if not spatial_representation and isinstance(
                occurrence.get("deposit_body"), dict
            ):
                # Backward compatibility for saved v4 occurrence records.
                spatial_representation = "bounded_deposit"
            if spatial_representation == "bounded_deposit":
                mapped_body = occurrence.get("deposit_body") or {}
            elif spatial_representation in {"bedrock_unit", "surface_cover"}:
                mapped_body = occurrence.get("material_unit") or {}
            else:
                # Rock-forming minerals are modal-abundance fields inside a
                # host lithology.  A marker may identify the observation, but
                # drawing a closed polygon would falsely imply a pure deposit.
                layers.append(marker_layer)
                continue
            deposit_geometry = mapped_body.get("geometry") or {}
            try:
                radius_m = float(
                    deposit_geometry.get("bounding_radius_m")
                    or 0.0
                )
            except (TypeError, ValueError):
                radius_m = 0.0
            if (
                radius_m <= 0.0
                or physical_width_m <= 0.0
                or physical_height_m <= 0.0
            ):
                layers.append(marker_layer)
                continue

            form = str(
                deposit_geometry.get("form")
                or (
                    "irregular_exposure"
                    if spatial_representation == "bounded_deposit"
                    else "irregular_lithologic_contact"
                )
            )
            if "vein" in form:
                aspect_ratio = 4.2
            elif "paleochannel" in form or "lens" in form:
                aspect_ratio = 3.0
            elif "layer" in form or "stratiform" in form:
                aspect_ratio = 3.4
            elif "blanket" in form or "profile" in form:
                aspect_ratio = 1.8
            elif "stockwork" in form:
                aspect_ratio = 2.2
            else:
                aspect_ratio = 1.45
            try:
                orientation_deg = float(
                    deposit_geometry.get("orientation_deg") or 0.0
                )
            except (TypeError, ValueError):
                orientation_deg = 0.0
            orientation_radians = math.radians(orientation_deg)
            cosine = math.cos(orientation_radians)
            sine = math.sin(orientation_radians)
            minor_radius_m = radius_m / aspect_ratio
            points = []
            maximum_world_radius = 0.0
            footprint_vertices = deposit_geometry.get("footprint_vertices")
            if not (
                isinstance(footprint_vertices, list)
                and len(footprint_vertices) >= 8
            ):
                footprint_vertices = [
                    [
                        math.cos(math.tau * point_index / 32.0),
                        math.sin(math.tau * point_index / 32.0),
                    ]
                    for point_index in range(32)
                ]
            for footprint_point in footprint_vertices:
                if not (
                    isinstance(footprint_point, (list, tuple))
                    and len(footprint_point) >= 2
                ):
                    continue
                local_x_m = radius_m * float(footprint_point[0])
                local_y_m = minor_radius_m * float(footprint_point[1])
                rotated_x_m = local_x_m * cosine - local_y_m * sine
                rotated_y_m = local_x_m * sine + local_y_m * cosine
                offset_x = rotated_x_m * rect["width_world"] / physical_width_m
                offset_y = rotated_y_m * rect["height_world"] / physical_height_m
                points.append((world_x + offset_x, world_y + offset_y))
                maximum_world_radius = max(
                    maximum_world_radius,
                    math.hypot(offset_x, offset_y),
                )

            if maximum_world_radius <= 0.0:
                layers.append(marker_layer)
                continue

            transition_zoom = 9.0 / maximum_world_radius
            focus_zoom = min(
                float(self.max_zoom),
                max(transition_zoom, 96.0 / maximum_world_radius),
            )
            marker_layer.update({
                "max_zoom": transition_zoom,
                "strict_zoom_visibility": True,
                "material_focus_zoom": focus_zoom,
            })
            layers.append(marker_layer)
            layers.append({
                "shape": "polygon",
                "x": world_x,
                "y": world_y,
                "points": points,
                "name": occurrence.get("name") or material_id,
                "entity_id": occurrence.get("id"),
                "color": tuple(color[:3]),
                "border_color": tuple(min(255, int(channel * 1.35)) for channel in color[:3]),
                "alpha": 68,
                "border_alpha": 230,
                "border_width": 2,
                "draw_order": -899.999 + index * 0.001,
                "pickable": True,
                "min_zoom": transition_zoom,
                "strict_zoom_visibility": True,
                "label_min_screen_span": 12,
                "material_focus_zoom": focus_zoom,
                "material_occurrence": occurrence,
                "deposit_geometry": dict(deposit_geometry),
                "spatial_representation": spatial_representation,
            })
        return layers

    def _build_hydrology_layers(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return []
        if self._entity_is_gas_giant(root_entity):
            return []

        surface_context = self._root_surface_context()
        if not isinstance(surface_context, dict):
            return []
        water_cycle = surface_context.get("water_cycle_model")
        if not isinstance(water_cycle, dict):
            return []
        climate_grid = water_cycle.get("climate_grid")
        if not isinstance(climate_grid, dict) or not climate_grid.get("rows"):
            return []

        rect = surface_context["map_rect"]
        return [{
            "shape": "hydrology_climate",
            "x": rect["x"],
            "y": rect["y"],
            "width_world": rect["width_world"],
            "height_world": rect["height_world"],
            "canvas_width_px": rect["canvas_width_px"],
            "canvas_height_px": rect["canvas_height_px"],
            "water_cycle_model": water_cycle,
            "climate_display_mode": self.active_climate_layer_id,
            "heightmap_model": surface_context.get("heightmap_model"),
            "name": root_entity.get("name") or "Hydrology",
            "entity_id": root_entity.get("id"),
            "draw_order": -960,
            "pickable": False,
            "refined_region_models": self._refined_region_models(),
        }]

    def _build_coastal_layers(self):
        root_entity = self.get_root_entity()
        surface_context = self._root_surface_context()
        if not isinstance(root_entity, dict) or not isinstance(surface_context, dict):
            return []
        model = surface_context.get("coastal_geomorphology_model")
        if not isinstance(model, dict):
            return []
        rect = surface_context["map_rect"]
        layers = []
        for index, segment in enumerate(model.get("segments") or []):
            uv_points = ((segment.get("geometry") or {}).get("points") or [])
            if len(uv_points) < 2:
                continue
            # Split at the longitude seam so the renderer does not draw a
            # false trans-planet line between adjacent wrapped points.
            runs, run = [], []
            for point in uv_points:
                if run and abs(float(point[0]) - float(run[-1][0])) > 0.5:
                    if len(run) >= 2:
                        runs.append(run)
                    run = []
                run.append(point)
            if len(run) >= 2:
                runs.append(run)
            centroid = (segment.get("measurements") or {}).get("centroid_uv") or uv_points[len(uv_points) // 2]
            for run_index, points in enumerate(runs):
                world_points = [
                    [rect["x"] + float(point[0]) * rect["width_world"], rect["y"] + float(point[1]) * rect["height_world"]]
                    for point in points
                ]
                layers.append({
                    "shape": "polyline",
                    "points": world_points,
                    "x": rect["x"] + float(centroid[0]) * rect["width_world"],
                    "y": rect["y"] + float(centroid[1]) * rect["height_world"],
                    "color": list(segment.get("display_color") or [220, 196, 116]),
                    "line_width": 3 if float(segment.get("confidence", 0.0) or 0.0) >= 0.6 else 2,
                    "name": str(segment.get("morphology_assemblage") or segment.get("primary_assemblage") or "coast").replace("_", " ").title(),
                    "entity_id": segment.get("id"),
                    "draw_order": -940 + index * 0.001 + run_index * 0.0001,
                    "pickable": True,
                    "coastal_segment": segment,
                })
            center = [rect["x"] + float(centroid[0]) * rect["width_world"], rect["y"] + float(centroid[1]) * rect["height_world"]]
            measurements = segment.get("measurements") or {}
            normal = measurements.get("seaward_normal_uv") or [0.0, 1.0]
            normal_length = max(1e-9, math.hypot(float(normal[0]), float(normal[1])))
            exposure = float((segment.get("wave_climate") or {}).get("exposure_index", 0.0) or 0.0)
            wave_scale = 0.006 * (0.35 + exposure * 0.65)
            wave_end = [
                center[0] + float(normal[0]) / normal_length * rect["width_world"] * wave_scale,
                center[1] + float(normal[1]) / normal_length * rect["height_world"] * wave_scale,
            ]
            layers.append({
                "shape": "polyline", "points": [center, wave_end], "x": center[0], "y": center[1],
                "color": [82, 188, 236], "line_width": 1, "draw_order": -939 + index * 0.001,
                "pickable": False, "name": "Wave exposure",
            })
            tidal_range = float((segment.get("tidal_regime") or {}).get("estimated_range_m", 0.0) or 0.0)
            if tidal_range > 0.0:
                tide_scale = 0.003 * (0.35 + max(0.0, min(1.0, tidal_range / 5.0)) * 0.65)
                tide_end = [
                    center[0] - float(normal[0]) / normal_length * rect["width_world"] * tide_scale,
                    center[1] - float(normal[1]) / normal_length * rect["height_world"] * tide_scale,
                ]
                layers.append({
                    "shape": "polyline", "points": [center, tide_end], "x": center[0], "y": center[1],
                    "color": [112, 232, 218], "line_width": 1, "draw_order": -938.5 + index * 0.001,
                    "pickable": False, "name": "Tidal range",
                })
            orientation = float(measurements.get("orientation_rad", 0.0) or 0.0)
            direction = -1.0 if (segment.get("wave_climate") or {}).get("longshore_transport_direction") == "chain_reverse" else 1.0
            transport_scale = 0.008 * (0.4 + float((segment.get("wave_climate") or {}).get("transport_capacity_index", 0.0) or 0.0) * 0.6)
            transport_end = [
                center[0] + math.cos(orientation) * direction * rect["width_world"] * transport_scale,
                center[1] + math.sin(orientation) * direction * rect["height_world"] * transport_scale,
            ]
            layers.append({
                "shape": "polyline", "points": [center, transport_end], "x": center[0], "y": center[1],
                "color": [244, 174, 76], "line_width": 1, "arrow_end": True,
                "draw_order": -938 + index * 0.001, "pickable": False, "name": "Longshore transport",
            })
        return layers

    def _build_reference_land_layers(self, root_entity, draw_order=-2600):
        land_payload = root_entity.get("reference_land_polygons") if isinstance(root_entity, dict) else None
        polygons = land_payload.get("polygons") if isinstance(land_payload, dict) else None
        if not isinstance(polygons, list):
            return []

        world_polygons = []
        for polygon in polygons:
            if not isinstance(polygon, list) or len(polygon) < 3:
                continue
            points = []
            for point in polygon:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                points.append(self._map_point_to_world(point[0], point[1]))
            if len(points) < 3:
                continue
            world_polygons.append(points)
        if not world_polygons:
            return []
        rect = self._planet_rect_from_entity(root_entity)
        return [{
            "shape": "reference_land",
            "x": rect["x"],
            "y": rect["y"],
            "width_world": rect["width_world"],
            "height_world": rect["height_world"],
            "canvas_width_px": rect["canvas_width_px"],
            "canvas_height_px": rect["canvas_height_px"],
            "polygons": world_polygons,
            "name": "Reference land",
            "entity_id": root_entity.get("id"),
            "color": (82, 108, 92),
            "border_color": (218, 236, 220),
            "border_width": 1,
            "pickable": False,
            "suppress_label": True,
            "draw_order": draw_order,
            "is_reference_land": True,
        }]

    def _build_visual_map_layers(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return []

        layers = []
        image_rect = self._map_image_rect_from_entity(root_entity)
        image_path = root_entity.get("map_image_path")
        if image_path and image_rect is not None:
            layers.append({
                "shape": "image_rect",
                "x": image_rect["x"],
                "y": image_rect["y"],
                "width_world": image_rect["width_world"],
                "height_world": image_rect["height_world"],
                "image_path": image_path,
                "image_year": root_entity.get("map_image_year"),
                "fit": root_entity.get("map_image_fit", "stretch_to_bounds"),
                "name": root_entity.get("name"),
                "entity_id": root_entity.get("id"),
            })

        if root_entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(root_entity)
            gas_giant = self._entity_is_gas_giant(root_entity)
            atmosphere_visual = root_entity.get("atmosphere_visual_model") or (root_entity.get("atmosphere_model") or {}).get("visual_model") or {}
            atmosphere_enabled = self.is_atmosphere_visible()
            atmosphere_baked = atmosphere_enabled and not image_path and (not gas_giant) and isinstance(root_entity.get("heightmap_model"), dict)
            layers.append({
                "shape": "map_rect",
                "x": rect["x"],
                "y": rect["y"],
                "width_world": rect["width_world"],
                "height_world": rect["height_world"],
                "canvas_width_px": rect["canvas_width_px"],
                "canvas_height_px": rect["canvas_height_px"],
                "name": root_entity.get("name"),
                "entity_id": root_entity.get("id"),
                "color": self._color_for_entity(root_entity),
                "location_class": root_entity.get("location_class"),
                "label_position": "below_right",
                "has_heightmap_base": (not gas_giant) and isinstance(root_entity.get("heightmap_model"), dict),
                "render_style": "gas_giant_bands" if gas_giant else "surface",
                "bands": self._gas_giant_bands_for_entity(root_entity) if gas_giant else [],
                "atmosphere_tint": list(atmosphere_visual.get("tint_color") or []),
                "atmosphere_opacity": float(atmosphere_visual.get("opacity", 0.0) or 0.0) if atmosphere_enabled else 0.0,
                "atmosphere_baked_into_surface": atmosphere_baked,
            })
            if not gas_giant:
                layers.extend(self._build_reference_land_layers(root_entity))

        layers.extend(self._build_visual_location_overlay_layers())
        return layers

    def _build_visual_location_overlay_layers(self):
        layers = []
        root_id = self.context.root_entity_id

        for index, entity in enumerate(self.context.get_active_locations()):
            if not isinstance(entity, dict):
                continue
            entity_id = entity.get("id")
            if not entity_id or entity_id == root_id:
                continue
            if entity.get("location_role") == "map_refinement_region":
                continue
            if not self._is_surface_map_location(entity):
                continue

            bounds = entity.get("bounds") or {}
            coords = self._point_coords_from_entity(entity) or {}
            color = self._color_for_entity(entity)
            geometry_layers = self._build_location_geometry_layers(entity, bounds, color)
            if not geometry_layers:
                geometry_layers = self._build_location_polyline_layers(entity, bounds, color)
            if geometry_layers:
                for layer in geometry_layers:
                    layer.update({
                        "is_location_overlay": True,
                        "outline_only": True,
                        "suppress_label": True,
                    })
                    layer["draw_order"] = (
                        700
                        + int(layer.get("map_hierarchy_depth", 0) or 0) * 100
                        + index * 0.001
                        + float(layer.get("geometry_part", 0) or 0) * 0.00001
                    )
                    layers.append(layer)
                continue

            if coords.get("type") == "point":
                x, y = self._map_point_to_world(coords.get("x", 0), coords.get("y", 0))
                layer = {
                    "shape": "marker",
                    "x": x,
                    "y": y,
                    "min_screen_size": 7,
                }
                layer.update({
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                    "is_location_overlay": True,
                    "suppress_label": True,
                })
                self._decorate_surface_location_layer(layer, entity)
                layer["draw_order"] = 700 + int(layer.get("map_hierarchy_depth", 0) or 0) * 100 + index * 0.001
                layers.append(layer)

        return layers

    def _build_layers(self, year):
        """
        Build render layers from active entities.

        Supported map geometry:
        * planet       -> map_rect surface container
        * bbox region  -> rect
        * point place  -> marker
        """
        self.get_active_layer_kind()
        if self.active_layer_kind == self.VISUAL_MAP_LAYER_KIND:
            return self._build_visual_map_layers()
        if self.active_layer_kind == self.MATERIAL_HEATMAP_LAYER_KIND:
            return self._build_material_heatmap_layers()
        if self.active_layer_kind == self.TRUE_COLOR_LAYER_KIND:
            base_layer = self.get_heightmap_base_layer(render_mode="true_color")
            return [base_layer] if base_layer is not None else []
        if self.active_layer_kind == self.HEIGHTMAP_LAYER_KIND:
            base_layer = self.get_heightmap_base_layer()
            return [base_layer] if base_layer is not None else []
        if self.active_layer_kind == self.HYDROLOGY_LAYER_KIND:
            return self._build_hydrology_layers()
        if self.active_layer_kind == self.COASTAL_LAYER_KIND:
            return self._build_coastal_layers()
        if self.active_layer_kind != self.LOCATION_LAYER_KIND:
            return self._build_spatial_feature_layers(year, self.active_layer_kind)

        layers = []
        # Location authoring is an overlay workflow. Keep the generated
        # terrain visible beneath boundaries and draft points so users do not
        # have to draw on a black canvas or switch layers mid-edit.
        heightmap_base = self.get_heightmap_base_layer(render_mode="true_color")
        if heightmap_base is not None:
            heightmap_base = dict(heightmap_base)
            heightmap_base["pickable"] = False
            heightmap_base["draw_order"] = -5000
            heightmap_base["is_location_base"] = True
            layers.append(heightmap_base)

        layers.extend(self._build_ghost_context_layers())
        layers.extend(self._build_placement_ancestor_layers())

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entity_id = entity.get("id")
            if (
                entity_id != self.context.root_entity_id
                and entity.get("location_role") == "map_refinement_region"
            ):
                continue
            if (
                self.is_editing_map_square
                and entity_id == self.editing_map_square_entity_id
            ):
                continue
            if (
                self.is_placing_location_polygon
                and entity_id == self.placing_location_entity_id
            ):
                continue
            if (
                entity_id != self.context.root_entity_id
                and not self._is_surface_map_location(entity)
            ):
                continue

            coords = self._point_coords_from_entity(entity) or {}
            bounds = entity.get("bounds") or {}

            x = None
            y = None

            if coords.get("type") == "point":
                x, y = self._map_point_to_world(
                    coords.get("x", 0),
                    coords.get("y", 0),
                )

            location_class = entity.get("location_class")
            color = self._color_for_entity(entity)
            image_rect = self._map_image_rect_from_entity(entity)
            image_path = entity.get("map_image_path")
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "draw_order": 20,
                })

            if location_class in {"planet", "moon"}:
                rect = self._planet_rect_from_entity(entity)
                gas_giant = self._entity_is_gas_giant(entity)
                is_root_entity = entity_id == self.context.root_entity_id

                atmosphere_visual = entity.get("atmosphere_visual_model") or (entity.get("atmosphere_model") or {}).get("visual_model") or {}
                atmosphere_enabled = self.is_atmosphere_visible() if is_root_entity else True
                atmosphere_baked = atmosphere_enabled and is_root_entity and not entity.get("map_image_path") and (not gas_giant) and isinstance(entity.get("heightmap_model"), dict)
                layers.append({
                    "shape": "map_rect",
                    "x": rect["x"],
                    "y": rect["y"],
                    "width_world": rect["width_world"],
                    "height_world": rect["height_world"],
                    "canvas_width_px": rect["canvas_width_px"],
                    "canvas_height_px": rect["canvas_height_px"],
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                    "location_class": location_class,
                    "label_position": "below_right",
                    "has_heightmap_base": (not gas_giant) and isinstance(entity.get("heightmap_model"), dict),
                    "render_style": "gas_giant_bands" if gas_giant else "surface",
                    "bands": self._gas_giant_bands_for_entity(entity) if gas_giant else [],
                    "outline_only": is_root_entity and self.active_layer_kind == self.LOCATION_LAYER_KIND,
                    "atmosphere_tint": list(atmosphere_visual.get("tint_color") or []),
                    "atmosphere_opacity": float(atmosphere_visual.get("opacity", 0.0) or 0.0) if atmosphere_enabled else 0.0,
                    "atmosphere_baked_into_surface": atmosphere_baked,
                    "draw_order": -3000 if is_root_entity else 40,
                    "map_hierarchy_depth": 0 if is_root_entity else self._surface_location_depth(entity),
                })
                if is_root_entity and not gas_giant:
                    layers.extend(self._build_reference_land_layers(entity))
                continue

            geometry_layers = self._build_location_geometry_layers(entity, bounds, color)
            if not geometry_layers:
                geometry_layers = self._build_location_polyline_layers(entity, bounds, color)
            if geometry_layers:
                # The root region's generated terrain is already the map
                # canvas.  Keep its bounds selectable but never paint an
                # opaque location polygon over that terrain.
                if entity_id == self.context.root_entity_id and heightmap_base is not None:
                    for layer in geometry_layers:
                        layer["outline_only"] = True
                        layer["draw_order"] = -3000
                        layer["suppress_label"] = True
                layers.extend(geometry_layers)
                continue

            if x is None or y is None:
                continue

            layer = {
                "shape": "marker",
                "x": x,
                "y": y,
                "min_screen_size": 8,
                "name": entity.get("name"),
                "entity_id": entity_id,
                "color": color,
            }
            self._decorate_surface_location_layer(layer, entity)
            layers.append(layer)

        if self._root_is_building() and not any(
            layer.get("entity_id") == self.context.root_entity_id
            for layer in layers
        ):
            default_floor_layer = self._build_default_building_floor_layer()
            if default_floor_layer is not None:
                layers.insert(0, default_floor_layer)

        return layers

    def get_heightmap_base_layer(self, render_mode="scientific"):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict) or self._entity_is_gas_giant(root_entity):
            return None
        surface_context = self._root_surface_context()
        if not isinstance(surface_context, dict):
            return None
        heightmap = surface_context.get("heightmap_model")
        if not isinstance(heightmap, dict):
            return None

        sample_grid = heightmap.get("sample_grid")
        if not isinstance(sample_grid, dict) or not sample_grid.get("rows"):
            return None

        rect = surface_context["map_rect"]
        source_entity = surface_context.get("source") or root_entity
        # The surface source is authoritative.  For a regenerated region it
        # is the dedicated generated_region child, not the draft/root shell;
        # preferring root data here can pair a child heightfield with a stale
        # parent material recipe.
        natural_material_model = (
            source_entity.get("natural_material_model")
            if isinstance(source_entity.get("natural_material_model"), dict)
            else root_entity.get("natural_material_model")
        )
        surface_palette = source_entity.get("surface_palette") or root_entity.get("surface_palette")
        # Existing generated worlds retain their data, but maps should still
        # render with the current material-aware palette after an application
        # update.  New generations persist this v2 palette normally.
        if (
            isinstance(natural_material_model, dict)
            and (not isinstance(surface_palette, dict) or int(surface_palette.get("palette_version", 0) or 0) < 2)
        ):
            surface_palette = derive_planet_surface_palette(
                natural_material_model,
                atmosphere=source_entity.get("atmosphere_model"),
                terrain=source_entity.get("terrain_seed_model"),
            )
        material_heatmap_model, material_source_uv_bounds = (
            self._material_heatmap_context(root_entity)
        )
        if not isinstance(material_heatmap_model, dict):
            # _material_heatmap_context found nothing at all -- fall back to
            # source_entity directly. Unlike _material_heatmap_context's own
            # branches, this path can't tell whether the raster is a
            # dedicated regional one or a shared planet-wide atlas, so it
            # keeps the pre-existing behaviour of cropping by the heightmap's
            # own placement UV. Do NOT apply this crop when
            # _material_heatmap_context already returned a model (with or
            # without its own uv_bounds) -- overriding a deliberate None
            # there is what made True Color render blank: it re-cropped an
            # already self-contained regional raster to a tiny wrong corner.
            material_heatmap_model = source_entity.get("material_heatmap_model")
            if isinstance(material_heatmap_model, dict):
                material_source_uv_bounds = heightmap.get("source_uv_bounds")
        material_layer = (
            material_heatmap_model.get("composite_layer")
            if isinstance(material_heatmap_model, dict)
            else None
        )
        if not self._material_heatmap_layer_has_raster(material_layer):
            material_layer = None
        elif isinstance(material_source_uv_bounds, dict):
            material_layer = dict(material_layer)
            material_layer["source_uv_bounds"] = dict(material_source_uv_bounds)
        material_layers = []
        if isinstance(material_heatmap_model, dict):
            for candidate_layer in material_heatmap_model.get("layers") or []:
                if not self._material_heatmap_layer_has_raster(candidate_layer):
                    continue
                candidate_layer = dict(candidate_layer)
                if isinstance(material_source_uv_bounds, dict):
                    candidate_layer["source_uv_bounds"] = dict(
                        material_source_uv_bounds
                    )
                material_layers.append(candidate_layer)
        atmosphere_visual = root_entity.get("atmosphere_visual_model") or source_entity.get("atmosphere_visual_model") or (source_entity.get("atmosphere_model") or {}).get("visual_model") or {}
        atmosphere_enabled = self.is_atmosphere_visible()
        surface_exposure_model = (
            source_entity.get("surface_exposure_model")
            or root_entity.get("surface_exposure_model")
        )
        if (
            render_mode == "true_color"
            and not isinstance(surface_exposure_model, dict)
            and isinstance(material_heatmap_model, dict)
        ):
            surface_exposure_model = derive_surface_exposure_model(
                source_entity,
                heightmap=heightmap,
                material_heatmap_model=material_heatmap_model,
                water_cycle=surface_context.get("water_cycle_model"),
                surface_evolution=(
                    root_entity.get("surface_evolution_model")
                    or source_entity.get("surface_evolution_model")
                ),
                surface_geomorphology=(
                    root_entity.get("surface_geomorphology_model")
                    or source_entity.get("surface_geomorphology_model")
                ),
            )
        true_color_model = (
            source_entity.get("true_color_model")
            or root_entity.get("true_color_model")
        )
        if (
            render_mode == "true_color"
            and not true_color_model_sources_match(
                true_color_model, heightmap, material_heatmap_model
            )
        ):
            true_color_model = derive_true_color_model(
                source_entity,
                heightmap=heightmap,
                natural_material_model=natural_material_model,
                material_heatmap_model=material_heatmap_model,
                atmosphere=source_entity.get("atmosphere_model"),
                water_cycle=surface_context.get("water_cycle_model"),
                surface_evolution=source_entity.get("surface_evolution_model"),
                surface_exposure=surface_exposure_model,
                surface_geomorphology=(
                    source_entity.get("surface_geomorphology_model")
                    or root_entity.get("surface_geomorphology_model")
                ),
            )
        return {
            "shape": "heightmap_base",
            "x": rect["x"],
            "y": rect["y"],
            "width_world": rect["width_world"],
            "height_world": rect["height_world"],
            "canvas_width_px": rect["canvas_width_px"],
            "canvas_height_px": rect["canvas_height_px"],
            "heightmap_model": heightmap,
            "render_mode": render_mode,
            "true_color_model": true_color_model,
            "natural_material_model": natural_material_model,
            "water_cycle_model": surface_context.get("water_cycle_model"),
            "surface_evolution_model": (
                root_entity.get("surface_evolution_model")
                or source_entity.get("surface_evolution_model")
            ),
            "surface_exposure_model": surface_exposure_model,
            "surface_geomorphology_model": (
                source_entity.get("surface_geomorphology_model")
                or root_entity.get("surface_geomorphology_model")
            ),
            "atmosphere_model": (
                (source_entity.get("atmosphere_model") or {})
                if atmosphere_enabled
                else {}
            ),
            "surface_palette": surface_palette,
            # The global palette establishes the broad surface phase; this
            # low-opacity composite then places individual materials where
            # their generated geological affinities make them probable.
            "surface_material_layer": material_layer,
            "surface_material_layers": material_layers,
            "surface_material_opacity": 92,
            "color": root_entity.get("display_color") or root_entity.get("color") or source_entity.get("display_color"),
            "display_color": root_entity.get("display_color") or source_entity.get("display_color"),
            "surface_weathering_model": root_entity.get("surface_weathering_model") or source_entity.get("surface_weathering_model"),
            "atmosphere_tint": list(atmosphere_visual.get("tint_color") or []),
            "atmosphere_opacity": (
                float(atmosphere_visual.get("opacity", 0.0) or 0.0)
                if atmosphere_enabled and render_mode != "true_color"
                else 0.0
            ),
            "name": root_entity.get("name"),
            "entity_id": root_entity.get("id"),
            "refined_region_models": self._refined_region_models(),
        }

    def get_layers(self):
        self.get_active_layer_kind()
        year = self.year

        if (
            self._layer_cache is None
            or self._cache_year != year
            or self._cache_layer_kind != self.active_layer_kind
        ):
            logger.debug(
                f"[MapSimulation] Rebuilding layer cache for year {year} "
                f"layer={self.active_layer_kind}",
                key="map_layers_build",
                interval=0.5
            )
            self._layer_cache = self._prepare_layer_cache(self._build_layers(year))
            self._cache_year = year
            self._cache_layer_kind = self.active_layer_kind
            self._layer_projection_focus_key = self._vector_projection_focus_key()

        for layer in self._layer_cache or []:
            if layer.get("shape") in {"heightmap_base", "hydrology_climate", "image_rect", "reference_land"}:
                layer["projection_focus_x"] = self.map_projection_focus_x
                layer["projection_focus_y"] = self.map_projection_focus_y
                layer["projection_interacting"] = bool(self.map_projection_dragging)
                layer["show_planet_equator"] = bool((self.get_root_entity() or {}).get("location_class") in {"planet", "moon"})
        return self._layer_cache

    def get_entries(self):
        entries = []

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entries.append({
                "entity": entity,
                "name": entity.get("name"),
                "entity_id": entity.get("id"),
            })

        return entries

    def get_history_timeline_items(self):
        if not hasattr(self.world_model, "get_timeline_items"):
            return []

        major_periods = []
        scoped_items = []
        for item in self.world_model.get_timeline_items():
            if item.get("timeline_kind") == "major_period":
                major_periods.append(item)
                continue

            entity = self.world_model.get_entity(item.get("entity_id"))
            if self._entity_is_history_timeline_relevant(entity):
                scoped_items.append(item)

        if not scoped_items:
            return []

        return major_periods + scoped_items

    def _entity_is_history_timeline_relevant(self, entity):
        if not entity:
            return False

        entity_id = entity.get("id")
        if entity_id == self.context.root_entity_id:
            return True

        if entity.get("_dataset") == "locations" or entity.get("type") == "location":
            return self.context._is_in_root_subtree(entity)

        if entity.get("_dataset") == "spatial_features" or entity.get("type") == "spatial_feature":
            return self._spatial_feature_is_in_scope(entity)

        referenced_ids = self._collect_history_reference_ids(entity)
        return any(self._entity_id_is_in_root_scope(ref_id) for ref_id in referenced_ids)

    def _collect_history_reference_ids(self, entity):
        reference_keys = (
            "parent_location",
            "parent_entity",
            "owner_entity",
            "associated_locations",
            "locations",
            "location_history",
            "neighbours",
            "constituents",
            "overlaps",
            "related",
            "parents",
        )
        references = []

        for key in reference_keys:
            references.extend(self._relation_entity_ids(entity.get(key)))

        return references

    def _screen_to_world(self, camera, screen_pos):
        sx, sy = screen_pos

        world_x = (sx - camera.width / 2) / camera.zoom + camera.x
        world_y = (sy - camera.height / 2) / camera.zoom + camera.y

        return world_x, world_y

    def _point_in_rect_layer(self, world_x, world_y, layer):
        half_w = layer.get("width_world", 0) / 2
        half_h = layer.get("height_world", 0) / 2

        min_x = layer["x"] - half_w
        max_x = layer["x"] + half_w
        min_y = layer["y"] - half_h
        max_y = layer["y"] + half_h

        return min_x <= world_x <= max_x and min_y <= world_y <= max_y

    def _point_in_marker_layer(self, world_x, world_y, layer, camera):
        pick_radius_world = max(12.0 / max(camera.zoom, 1e-9), 8.0)

        dx = world_x - layer["x"]
        dy = world_y - layer["y"]

        return (dx * dx + dy * dy) <= (pick_radius_world * pick_radius_world)

    def _screen_points_for_polygon_layer(self, layer, camera):
        screen_points = []

        for point in layer.get("points", []):
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return []

            screen_points.append((float(screen_point[0]), float(screen_point[1])))

        return screen_points

    def _point_near_segment(self, x, y, ax, ay, bx, by, tolerance):
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy

        if length_sq <= 1e-9:
            point_dx = x - ax
            point_dy = y - ay
            return (point_dx * point_dx + point_dy * point_dy) <= tolerance * tolerance

        t = ((x - ax) * dx + (y - ay) * dy) / length_sq
        t = max(0.0, min(1.0, t))

        closest_x = ax + t * dx
        closest_y = ay + t * dy
        point_dx = x - closest_x
        point_dy = y - closest_y

        return (point_dx * point_dx + point_dy * point_dy) <= tolerance * tolerance

    def _point_in_polygon_points(self, x, y, points, edge_tolerance=0.0):
        if len(points) < 3:
            return False

        if edge_tolerance > 0.0:
            previous_x, previous_y = points[-1]
            for current_x, current_y in points:
                if self._point_near_segment(
                    x,
                    y,
                    previous_x,
                    previous_y,
                    current_x,
                    current_y,
                    edge_tolerance,
                ):
                    return True

                previous_x = current_x
                previous_y = current_y

        inside = False
        previous_x, previous_y = points[-1]

        for current_x, current_y in points:
            y_crosses = (current_y > y) != (previous_y > y)
            if y_crosses:
                denominator = previous_y - current_y
                if abs(denominator) <= 1e-9:
                    previous_x = current_x
                    previous_y = current_y
                    continue

                x_at_y = (
                    (previous_x - current_x)
                    * (y - current_y)
                    / denominator
                    + current_x
                )
                if x < x_at_y:
                    inside = not inside

            previous_x = current_x
            previous_y = current_y

        return inside

    def _point_in_polygon_layer(self, world_x, world_y, layer):
        return self._point_in_polygon_points(
            x=world_x,
            y=world_y,
            points=layer.get("points", []),
        )

    def _point_in_layer_world_bounds(self, world_x, world_y, layer, tolerance=0.0):
        bounds = layer.get("_world_bounds")
        if bounds is None:
            points = layer.get("points") or []
            if len(points) < 3:
                return False
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bounds = (min(xs), max(xs), min(ys), max(ys))
            layer["_world_bounds"] = bounds

        min_x, max_x, min_y, max_y = bounds
        return (
            min_x - tolerance <= world_x <= max_x + tolerance
            and min_y - tolerance <= world_y <= max_y + tolerance
        )

    def _point_in_polygon_layer_screen(self, screen_pos, layer, camera):
        screen_points = self._screen_points_for_polygon_layer(layer, camera)
        if not screen_points:
            return False

        return self._point_in_polygon_points(
            x=float(screen_pos[0]),
            y=float(screen_pos[1]),
            points=screen_points,
            edge_tolerance=3.0,
        )

    def _point_near_polyline_points(self, x, y, points, tolerance=0.0):
        if len(points) < 2:
            return False
        previous_x, previous_y = points[0]
        for current_x, current_y in points[1:]:
            if self._point_near_segment(
                x, y, previous_x, previous_y, current_x, current_y, tolerance,
            ):
                return True
            previous_x, previous_y = current_x, current_y
        return False

    def _pick_layer_at_world(self, world_x, world_y, camera, screen_pos=None):
        """
        Pick from topmost to bottommost.

        Reverse iteration matters so that:
        * Berlin beats Germany
        * Germany beats Europe
        * Europe beats Earth
        """
        layers = self.get_layers()

        deferred_broad_location_layer = None
        for layer in reversed(layers):
            if layer.get("pickable") is False or layer.get("is_ghost_context"):
                continue

            min_zoom = layer.get("pickable_min_zoom", layer.get("min_zoom"))
            if min_zoom is not None and camera is not None:
                try:
                    if float(getattr(camera, "zoom", 1.0) or 1.0) < float(min_zoom):
                        continue
                except (TypeError, ValueError):
                    pass
            max_zoom = layer.get("pickable_max_zoom", layer.get("max_zoom"))
            if max_zoom is not None and camera is not None:
                try:
                    if float(getattr(camera, "zoom", 1.0) or 1.0) >= float(max_zoom):
                        continue
                except (TypeError, ValueError):
                    pass

            shape = layer.get("shape", "marker")

            if shape in ("map_rect", "rect"):
                if self._point_in_rect_layer(world_x, world_y, layer):
                    if layer.get("is_broad_location_overlay"):
                        deferred_broad_location_layer = deferred_broad_location_layer or layer
                        continue
                    return layer

            elif shape == "polygon":
                tolerance = 0.0
                if screen_pos is not None and camera is not None:
                    tolerance = 3.0 / max(float(getattr(camera, "zoom", 1.0) or 1.0), 1e-9)
                if not self._point_in_layer_world_bounds(world_x, world_y, layer, tolerance=tolerance):
                    continue
                if self._point_in_polygon_points(
                    x=world_x,
                    y=world_y,
                    points=layer.get("points", []),
                    edge_tolerance=tolerance,
                ):
                    if layer.get("is_broad_location_overlay"):
                        deferred_broad_location_layer = deferred_broad_location_layer or layer
                        continue
                    return layer

            elif shape == "polyline":
                tolerance = 4.0 / max(float(getattr(camera, "zoom", 1.0) or 1.0), 1e-9)
                if self._point_near_polyline_points(
                    world_x, world_y, layer.get("points", []), tolerance=tolerance,
                ):
                    return layer

            elif shape == "marker":
                if self._point_in_marker_layer(world_x, world_y, layer, camera):
                    return layer

        return deferred_broad_location_layer

    def _select_picked_layer(self, picked_layer, screen_pos, record_click=False):
        self.hover_screen_pos = screen_pos
        self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None
        self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id") if picked_layer else None

        if picked_layer is None:
            self.selected_entity_id = None
            self.selected_material_occurrence_id = None
            self.selected_spatial_feature_id = None
            return

        self.selected_entity_id = picked_layer.get("entity_id")
        self.selected_spatial_feature_id = picked_layer.get("spatial_feature_id")
        occurrence = picked_layer.get("material_occurrence")
        if isinstance(occurrence, dict):
            occurrence_id = str(occurrence.get("id") or "")
            self.selected_material_occurrence_id = occurrence_id or None
            if occurrence_id:
                self.active_material_heatmap_layer_id = occurrence_id
        else:
            self.selected_material_occurrence_id = None

        if record_click:
            target = None
            if (
                self.active_layer_kind == self.LOCATION_LAYER_KIND
                and self._can_open_location_inspector(self.selected_entity_id)
            ):
                target = ("location", self.selected_entity_id)
            elif self._is_real_spatial_feature_id(self.selected_spatial_feature_id):
                target = ("spatial_feature", self.selected_spatial_feature_id)

            if target is not None and self._is_selection_double_click(target, screen_pos):
                self._pending_inspector_target = {
                    "kind": target[0],
                    "id": target[1],
                }
                self._record_selection_click(None, None)
            else:
                self._record_selection_click(target, screen_pos)

        logger.debug(
            f"[MapSimulation] Selected entity={self.selected_entity_id} "
            f"spatial_feature={self.selected_spatial_feature_id}",
            key="map_selection",
            interval=0.1
        )

    def _set_polygon_editor_hover_point(self, map_point):
        if self.is_placing_location_polygon:
            self.placing_hover_map_pos = map_point
            return

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            self.editing_hover_map_pos = map_point
        elif self.is_creating_spatial_feature:
            self.draft_hover_map_pos = map_point

    def _append_polygon_editor_point(self, map_point):
        if self.is_placing_location_polygon:
            self.placing_location_points.append(map_point)
            return len(self.placing_location_points)

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            self.editing_spatial_feature_points.append(map_point)
            return len(self.editing_spatial_feature_points)

        self.draft_spatial_feature_points.append(map_point)
        return len(self.draft_spatial_feature_points)

    def _can_reuse_existing_polygon_for_editor(self):
        return (
            self.get_polygon_editor_point_count() == 0
            and (
                self.is_creating_spatial_feature
                or self.is_placing_location_polygon
            )
        )

    def _pick_existing_polygon_point_for_editor(self, camera, screen_pos):
        if camera is None or screen_pos is None:
            return None

        layers = self.get_layers()
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])
        best_point = None
        best_distance_sq = self.POLYGON_POINT_HIT_RADIUS_PX ** 2

        for layer in reversed(layers):
            if layer.get("pickable") is False or layer.get("is_ghost_context"):
                continue
            if layer.get("shape") != "polygon":
                continue

            points = layer.get("points") or []
            if len(points) < 3:
                continue

            for point in points:
                point_screen = camera.world_to_screen(point)
                if point_screen is None:
                    continue

                dx = screen_x - float(point_screen[0])
                dy = screen_y - float(point_screen[1])
                distance_sq = dx * dx + dy * dy
                if distance_sq <= best_distance_sq:
                    best_point = self._world_point_to_map(point[0], point[1])
                    best_distance_sq = distance_sq

        return best_point

    def _delete_polygon_editor_point(self, index=None):
        points = self.get_polygon_editor_points()
        if not points:
            return False

        if index is None:
            index = len(points) - 1

        if index < 0 or index >= len(points):
            return False

        del points[index]
        return True

    def _polygon_editor_hit_point_index(self, screen_pos, camera):
        points = self.get_polygon_editor_points()
        if not points:
            return None

        best_index = None
        best_distance_sq = self.POLYGON_POINT_HIT_RADIUS_PX ** 2
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])

        for index, map_point in enumerate(points):
            world_point = self._map_point_to_world(map_point[0], map_point[1])
            point_screen = camera.world_to_screen(world_point)
            if point_screen is None:
                continue

            dx = screen_x - float(point_screen[0])
            dy = screen_y - float(point_screen[1])
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                best_index = index
                best_distance_sq = distance_sq

        return best_index

    def _handle_polygon_editor_pointer_event(
        self,
        event,
        camera,
        screen_pos,
        world_x,
        world_y,
    ):
        if event.type != self.MOUSEBUTTONDOWN_EVENT_TYPE:
            return

        button = getattr(event, "button", None)
        map_point = self._world_point_to_map(world_x, world_y)
        hit_index = self._polygon_editor_hit_point_index(screen_pos, camera)

        if button == 3:
            deleted = self._delete_polygon_editor_point(hit_index)
            if deleted:
                self._set_polygon_editor_hover_point(map_point)
                self._record_draft_click(screen_pos)
                self._invalidate_layer_cache()
            return

        if button != 1:
            return

        if self._can_reuse_existing_polygon_for_editor():
            reuse_point = self._pick_existing_polygon_point_for_editor(camera, screen_pos)
            if reuse_point is not None:
                point_count = self._append_polygon_editor_point(reuse_point)
                self._set_polygon_editor_hover_point(reuse_point)
                self._record_draft_click(screen_pos)
                self._invalidate_layer_cache()
                logger.debug(
                    f"[MapSimulation] Polygon editor reused existing point count={point_count}",
                    key="map_polygon_editor_point_reuse",
                    interval=0.1,
                )
                return

        if hit_index is not None and self.can_finish_polygon_editor():
            self.finish_polygon_editor()
            return

        if self._is_draft_double_click(screen_pos):
            if self.finish_polygon_editor():
                return

            self._record_draft_click(screen_pos)
            return

        point_count = self._append_polygon_editor_point(map_point)
        self._set_polygon_editor_hover_point(map_point)
        self._record_draft_click(screen_pos)
        self._invalidate_layer_cache()
        logger.debug(
            f"[MapSimulation] Polygon editor point added count={point_count}",
            key="map_polygon_editor_point",
            interval=0.1
        )

    def _handle_point_location_pointer_event(self, event, screen_pos, world_x, world_y):
        if event.type != self.MOUSEBUTTONDOWN_EVENT_TYPE:
            return

        button = getattr(event, "button", None)
        if button == 3:
            self.cancel_point_location_draft()
            return

        if button != 1:
            return

        map_point = self._world_point_to_map(world_x, world_y)
        self.draft_point_location_pos = map_point
        self.draft_point_hover_pos = map_point
        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = screen_pos
        self._record_draft_click(screen_pos)
        self._invalidate_layer_cache()

    def get_point_location_draft_preview(self):
        if not self.is_creating_point_location:
            return None

        map_point = self.draft_point_location_pos or self.draft_point_hover_pos
        if map_point is None:
            return None

        world_x, world_y = self._map_point_to_world(map_point[0], map_point[1])
        label = str(self.draft_point_location_class or "site").replace("_", " ").title()
        return {
            "shape": "marker",
            "x": world_x,
            "y": world_y,
            "min_screen_size": 10,
            "name": f"Draft {label}",
            "color": (255, 230, 120),
        }

    def _square_editor_hit_handle(self, screen_pos, camera):
        bounds = self._current_map_square_bounds()
        if bounds is None:
            return None

        best_handle = None
        best_distance_sq = self.SQUARE_HANDLE_HIT_RADIUS_PX ** 2
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])

        for handle_id, point in self._square_handle_positions(bounds).items():
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                continue

            dx = screen_x - float(screen_point[0])
            dy = screen_y - float(screen_point[1])
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                best_handle = handle_id
                best_distance_sq = distance_sq

        return best_handle

    def _move_square_bounds(self, bounds, dx, dy):
        return {
            "min_x": bounds["min_x"] + dx,
            "max_x": bounds["max_x"] + dx,
            "min_y": bounds["min_y"] + dy,
            "max_y": bounds["max_y"] + dy,
        }

    def _begin_square_drag(self, handle, map_point):
        bounds = self._current_map_square_bounds()
        if bounds is None:
            return False

        self.square_drag_handle = handle
        self.square_drag_start_pos = map_point
        self.square_drag_start_bounds = dict(bounds)
        self.square_drag_opposite_point = self._square_opposite_point_for_handle(
            bounds,
            handle,
        )
        return True

    def _update_square_drag(self, map_point):
        if not self.is_editing_map_square or self.square_drag_handle is None:
            return False

        if self.square_drag_handle == "center":
            start_pos = self.square_drag_start_pos
            start_bounds = self.square_drag_start_bounds
            if start_pos is None or start_bounds is None:
                return False

            dx = float(map_point[0]) - float(start_pos[0])
            dy = float(map_point[1]) - float(start_pos[1])
            self.editing_map_square_bounds = self._move_square_bounds(
                start_bounds,
                dx,
                dy,
            )
            return True

        opposite_point = self.square_drag_opposite_point
        if opposite_point is None:
            return False

        bounds = self._square_bounds_from_anchor_hover(opposite_point, map_point)
        if bounds is None:
            return False

        self.editing_map_square_bounds = bounds
        return True

    def _handle_square_editor_motion(self, map_point):
        if self.is_creating_map_square:
            self.map_square_hover_pos = map_point
            return

        if self.is_editing_map_square and self.square_drag_handle is not None:
            if self._update_square_drag(map_point):
                self._invalidate_layer_cache()

    def _handle_square_editor_pointer_event(
        self,
        event,
        camera,
        screen_pos,
        world_x,
        world_y,
    ):
        map_point = self._world_point_to_map(world_x, world_y)

        if self.is_creating_map_square:
            if event.type != self.MOUSEBUTTONDOWN_EVENT_TYPE:
                return

            button = getattr(event, "button", None)
            if button == 3:
                if self.map_square_anchor is None:
                    self.cancel_map_square_draft()
                else:
                    self.map_square_anchor = None
                    self.map_square_hover_pos = None
                self._record_draft_click(screen_pos)
                return

            if button != 1:
                return

            if self.map_square_anchor is None:
                self.map_square_anchor = map_point
                self.map_square_hover_pos = map_point
                self._record_draft_click(screen_pos)
                return

            self.map_square_hover_pos = map_point
            if self.finish_map_square_draft():
                return

            self._record_draft_click(screen_pos)
            return

        if not self.is_editing_map_square:
            return

        if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE:
            if getattr(event, "button", None) != 1:
                return

            handle = self._square_editor_hit_handle(screen_pos, camera)
            if handle is not None:
                self._begin_square_drag(handle, map_point)
            return

        if event.type == self.MOUSEBUTTONUP_EVENT_TYPE:
            if getattr(event, "button", None) == 1:
                self._reset_square_drag_state()

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Update hover state from pointer motion.
        """
        if self._update_camera_drag(screen_pos, camera):
            return

        world_x, world_y = self._screen_to_world(camera, screen_pos)

        if self.is_square_editor_active():
            map_point = self._world_point_to_map(world_x, world_y)
            self._handle_square_editor_motion(map_point)
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = screen_pos
            return

        if self.is_creating_point_location:
            self.draft_point_hover_pos = self._world_point_to_map(world_x, world_y)
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = screen_pos
            return

        if self.is_polygon_editor_active():
            self._set_polygon_editor_hover_point(self._world_point_to_map(world_x, world_y))
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = screen_pos
            return

        now = time.monotonic()
        camera_state = (
            round(float(getattr(camera, "x", 0.0) or 0.0), 4),
            round(float(getattr(camera, "y", 0.0) or 0.0), 4),
            round(float(getattr(camera, "zoom", 1.0) or 1.0), 6),
        )
        if (
            self._last_hover_pick_screen_pos is not None
            and self._last_hover_pick_camera_state == camera_state
            and now - self._last_hover_pick_time < 0.025
        ):
            last_x, last_y = self._last_hover_pick_screen_pos
            dx = float(screen_pos[0]) - float(last_x)
            dy = float(screen_pos[1]) - float(last_y)
            if dx * dx + dy * dy < 36.0:
                return

        picked_layer = self._pick_layer_at_world(world_x, world_y, camera, screen_pos)
        self._last_hover_pick_time = now
        self._last_hover_pick_screen_pos = screen_pos
        self._last_hover_pick_camera_state = camera_state

        if picked_layer is None:
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = None
            return

        self.hover_entity_id = picked_layer.get("entity_id")
        self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id")
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Handle pointer input for the map simulation.

        This method receives screen coordinates from the app and performs
        picking in world/map coordinates.
        """
        world_x, world_y = self._screen_to_world(camera, screen_pos)
        button = getattr(event, "button", None)

        if self.is_square_editor_active():
            self._handle_square_editor_pointer_event(
                event,
                camera,
                screen_pos,
                world_x,
                world_y,
            )
            return

        if self.is_creating_point_location:
            self._handle_point_location_pointer_event(event, screen_pos, world_x, world_y)
            return

        if self.is_polygon_editor_active():
            self._handle_polygon_editor_pointer_event(
                event,
                camera,
                screen_pos,
                world_x,
                world_y,
            )
            return

        picked_layer = self._pick_layer_at_world(world_x, world_y, camera, screen_pos)

        if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE and button == 3:
            entity_id = picked_layer.get("entity_id") if picked_layer else None
            if entity_id:
                self.open_entity_card(entity_id, mode="edit")
            return

        if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE and button == 1:
            self._begin_camera_drag(screen_pos, camera)
            self.hover_screen_pos = screen_pos
            self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None
            self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id") if picked_layer else None
            return

        if event.type == self.MOUSEBUTTONUP_EVENT_TYPE and button == 1:
            was_camera_dragging = self.is_camera_dragging
            was_camera_pan = self.camera_drag_has_moved
            was_projection_drag = self.map_projection_dragging
            self._reset_camera_drag()
            if was_projection_drag:
                self._invalidate_layer_cache()

            if not was_camera_dragging:
                return

            if was_camera_dragging and was_camera_pan:
                self._map_focus_last_click_time = None
                self._map_focus_last_click_screen_pos = None
                return

            if self._is_map_refocus_double_click(screen_pos):
                self._map_focus_last_click_time = None
                self._map_focus_last_click_screen_pos = None
                if not self._focus_material_occurrence(camera, picked_layer):
                    self._refocus_map_at_screen_point(camera, screen_pos)
                return

            self._record_map_focus_click(screen_pos)

            self._select_picked_layer(picked_layer, screen_pos, record_click=True)
            return

        self._select_picked_layer(picked_layer, screen_pos, record_click=False)

    def get_center(self):
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) / 2,
            (self.bounds["min_y"] + self.bounds["max_y"]) / 2,
        )

    def update(self, dt):
        self.sim_manager.update(dt)
