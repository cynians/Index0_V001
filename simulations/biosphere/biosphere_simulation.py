"""Map-native biological city builder.

MapSimulation supplies terrain, scale, navigation and rendering contracts.
This class adds a planning layer (introductions) and a derived ecology layer.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.representatives import RepresentativePopulationManager
from simulations.map.map_simulation import MapSimulation
from simulations.species.species_simulation import SpeciesSimulation
from world.simulation_context import SimulationContext


class _BiosphereWorldView:
    """Read-only overlay that can add a reference map without repository writes."""

    def __init__(self, base_world=None, root_entity=None, fallback_species=None):
        self.base_world = base_world
        self.root_entity = dict(root_entity or {})
        self.fallback_species = [dict(entity) for entity in (fallback_species or [])]

    @property
    def repository_revision(self):
        return getattr(self.base_world, "repository_revision", 0)

    def get_entity(self, entity_id):
        if entity_id == self.root_entity.get("id"):
            return self.root_entity
        for entity in self.fallback_species:
            if entity.get("id") == entity_id:
                return entity
        return self.base_world.get_entity(entity_id) if self.base_world is not None else None

    def get_dataset(self, dataset_name):
        base = list(self.base_world.get_dataset(dataset_name) or []) if self.base_world is not None and hasattr(self.base_world, "get_dataset") else []
        if dataset_name == "locations":
            return [self.root_entity] + [entity for entity in base if entity.get("id") != self.root_entity.get("id")]
        if dataset_name == "species" and not base:
            return list(self.fallback_species)
        if dataset_name == "species" and self.fallback_species:
            known = {entity.get("id") for entity in base}
            return base + [entity for entity in self.fallback_species if entity.get("id") not in known]
        return base

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        if self.base_world is not None and hasattr(self.base_world, "get_active_entities"):
            try:
                base = list(self.base_world.get_active_entities(year, dataset_name=dataset_name, entity_type=entity_type) or [])
            except TypeError:
                base = list(self.base_world.get_active_entities(year) or [])
        else:
            base = []
        entities = [self.root_entity] + base
        if dataset_name is not None:
            entities = [entity for entity in entities if entity.get("_dataset") == dataset_name]
        if entity_type is not None:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        return entities

    def get_timeline_items(self):
        return list(self.base_world.get_timeline_items() or []) if self.base_world is not None and hasattr(self.base_world, "get_timeline_items") else []

    def is_plant_species(self, entity_id):
        if self.base_world is not None and hasattr(self.base_world, "is_plant_species"):
            return bool(self.base_world.is_plant_species(entity_id))
        return any(entity.get("id") == entity_id for entity in self.fallback_species)

    def resolved_species_entity(self, entity_id):
        if self.base_world is not None and hasattr(self.base_world, "resolved_species_entity"):
            resolved = self.base_world.resolved_species_entity(entity_id)
            if resolved:
                return resolved
        return self.get_entity(entity_id)


class BiosphereSimulation(MapSimulation):
    """Playable builder surface: choose species, place, then advance ecology."""

    simulation_mode = "biosphere_builder"
    PLACEMENT_TOOL = "introduce_species"
    BIOMASSER_ID = "spec_biomasser_13b"
    PIONEER_UNLOCK_BIOMASS_KG = 6.0
    BASE_SECONDS_PER_SEASON = 30.0
    TIME_SCALES = (0.0, 1.0, 4.0, 16.0)

    @classmethod
    def reference_site(cls, world_model=None):
        root = {
            "id": "loc_biosphere_builder_reference_site",
            "type": "location",
            "_dataset": "locations",
            "name": "Biosphere Builder Reference Catchment",
            "location_class": "biosphere_patch",
            "location_role": "biosphere_design_patch",
            "map_coordinate_space": "site_meters",
            "map_detail_level": 4,
            "map_status": "authored high-detail target substrate",
            "display_color": [73, 83, 62],
            "bounds": {"type": "bbox", "min_x": 0.0, "max_x": 10.0, "min_y": 0.0, "max_y": 10.0},
            "biosphere_width_m": 10.0,
            "biosphere_height_m": 10.0,
            "biosphere_area_m2": 100.0,
        }
        fallback_species = [
            {
                "id": "spec_biomasser_13b", "type": "species", "_dataset": "species",
                "pretty_name": "Biomasser 13B", "common_name": "Biomasser 13B",
                "plant_growth_form": "lichen", "species_simulation_enabled": True,
                "biosphere_bootstrap_species": True,
                "biosphere_growth_profile": {
                    "seasonal_growth_rate": 0.58, "seasonal_dispersal": 0.21,
                    "carrying_biomass_kg_m2": 3.2, "moisture_optimum": 0.38,
                    "moisture_tolerance": 0.58, "light_minimum": 0.08,
                },
            },
            {"id": "spec_lolium_perenne", "type": "species", "_dataset": "species", "pretty_name": "Perennial Ryegrass", "plant_growth_form": "graminoid"},
            {"id": "spec_betula_pendula", "type": "species", "_dataset": "species", "pretty_name": "Silver Birch", "plant_growth_form": "tree"},
            {"id": "spec_nymphaea_alba", "type": "species", "_dataset": "species", "pretty_name": "European White Water Lily", "plant_growth_form": "aquatic"},
        ]
        view = _BiosphereWorldView(world_model, root, fallback_species)
        return cls(world_model=view, biosphere_context={
            "patch_location_id": root["id"], "patch_name": root["name"], "year": 2400,
            "bootstrap_lifeless": True, "initial_extent_m": 10.0,
            "founding_point_source": [500.0, 350.0],
        })

    def __init__(self, world_model, biosphere_context, biosphere_id=None):
        self.biosphere_context = dict(biosphere_context or {})
        self.biosphere_id = biosphere_id or self.biosphere_context.get("biosphere_id")
        patch_id = self.biosphere_context.get("patch_location_id")
        if not patch_id:
            raise ValueError("BiosphereSimulation requires a patch_location_id")
        bootstrap_lifeless = bool(self.biosphere_context.get("bootstrap_lifeless"))
        initial_extent = float(self.biosphere_context.get("initial_extent_m") or 10.0)
        requested_extent = max(
            initial_extent,
            float(self.biosphere_context.get("biosphere_width_m") or initial_extent),
            float(self.biosphere_context.get("biosphere_height_m") or initial_extent),
        )
        self.maximum_extent_m = min(1000.0, requested_extent)
        if world_model.get_entity(patch_id) is None or bootstrap_lifeless:
            width = float(self.biosphere_context.get("initial_extent_m") or self.biosphere_context.get("biosphere_width_m") or self.biosphere_context.get("map_size_m") or 10.0)
            height = float(self.biosphere_context.get("initial_extent_m") or self.biosphere_context.get("biosphere_height_m") or self.biosphere_context.get("map_size_m") or width)
            synthetic_root = {
                "id": patch_id,
                "type": "location",
                "_dataset": "locations",
                "name": self.biosphere_context.get("patch_name") or patch_id,
                "location_class": "biosphere_patch",
                "map_coordinate_space": "site_meters",
                "map_detail_level": 4,
                "bounds": {"type": "bbox", "min_x": 0.0, "max_x": width, "min_y": 0.0, "max_y": height},
                "biosphere_width_m": width,
                "biosphere_height_m": height,
                "biosphere_founding_point_source": self.biosphere_context.get("founding_point_source"),
                "map_status": "lifeless founding substrate" if bootstrap_lifeless else "biosphere design substrate",
                "display_color": (world_model.get_entity(patch_id) or {}).get("display_color") or [73, 83, 62],
            }
            world_model = _BiosphereWorldView(world_model, synthetic_root)
        super().__init__(SimulationContext(self.biosphere_context.get("year", 2400), patch_id, world_model))
        self.builder_tool = self.PLACEMENT_TOOL
        self.builder_paused = True
        self.builder_time_scale = 0.0
        self.seconds_per_season = self.BASE_SECONDS_PER_SEASON
        self._season_accumulator = 0.0
        self.placement_radius_world = max(0.45, min(self.bounds["max_x"] - self.bounds["min_x"], self.bounds["max_y"] - self.bounds["min_y"]) * 0.07)
        self.species_profiles = self._load_species_profiles()
        self.selected_species_id = self._default_species_id()
        self.ecology = BiosphereEcology(self.bounds, self.species_profiles, columns=20, rows=20)
        self.representatives = RepresentativePopulationManager(self.world_model)
        self.selected_representative_id = None
        self._representative_screen_hitboxes = []
        self.last_representative_feedback = {}
        self.species_picker_open = False
        self.species_picker_page = 0
        self.species_picker_focus_id = self.selected_species_id
        self._species_preview_simulations = {}
        self._picker_previous_time_scale = None
        self._isometric_projection_state = None
        self.test_forest_species_ids = []

    def _load_species_profiles(self):
        species = list(self.world_model.get_dataset("species") or []) if hasattr(self.world_model, "get_dataset") else []
        plants = []
        for entity in species:
            entity_id = entity.get("id")
            is_plant = getattr(self.world_model, "is_plant_species", lambda _entity_id: bool(entity.get("plant_growth_form")))(entity_id)
            if not is_plant and not entity.get("biosphere_bootstrap_species") and not entity.get("species_simulation_enabled"):
                continue
            resolved = getattr(self.world_model, "resolved_species_entity", lambda _entity_id: None)(entity_id) or entity
            plants.append(profile_from_entity(resolved))
        plants.sort(key=lambda profile: (profile.species_id != self.BIOMASSER_ID, profile.growth_form not in {"lichen", "graminoid", "forb", "shrub", "tree", "aquatic"}, profile.label.lower()))
        return plants

    def _default_species_id(self):
        preferred = (self.BIOMASSER_ID, "spec_lolium_perenne", "spec_codonorhiza_elandsmontana", "spec_betula_pendula")
        ids = {profile.species_id for profile in self.species_profiles}
        return next((species_id for species_id in preferred if species_id in ids), next(iter(ids), None))

    def pioneers_unlocked(self):
        return self.ecology.summary()["living_biomass_kg"] >= self.PIONEER_UNLOCK_BIOMASS_KG

    def is_species_unlocked(self, species_id):
        return species_id == self.BIOMASSER_ID or self.pioneers_unlocked()

    def get_species_palette_items(self, limit=8):
        items = []
        visible_profiles = self.species_profiles if self.pioneers_unlocked() else [
            profile for profile in self.species_profiles if profile.species_id == self.BIOMASSER_ID
        ]
        for profile in visible_profiles[:max(1, int(limit))]:
            items.append({
                "id": profile.species_id,
                "label": profile.label,
                "growth_form": profile.growth_form,
                "color": profile.color,
                "selected": profile.species_id == self.selected_species_id,
                "enabled": self.is_species_unlocked(profile.species_id),
                "provenance": profile.provenance,
            })
        return items

    def select_species(self, species_id):
        if species_id not in self.ecology.profiles or not self.is_species_unlocked(species_id):
            return False
        self.selected_species_id = species_id
        self.species_picker_focus_id = species_id
        return True

    def toggle_species_selection(self, species_id):
        return self.select_species(species_id)

    def place_selected_species(self, x, y, propagule_pressure=0.30):
        if not self.selected_species_id:
            return None
        profile = self.ecology.profiles[self.selected_species_id]
        radius_multiplier = {
            "tree": 3.2,
            "shrub": 2.3,
            "aquatic": 2.1,
            "graminoid": 1.6,
            "forb": 1.5,
        }.get(profile.growth_form, 1.0)
        radius = min(self.get_map_size() * 0.34, self.placement_radius_world * radius_multiplier)
        introduction = self.ecology.introduce(self.selected_species_id, x, y, radius, propagule_pressure)
        if introduction is not None:
            self.representatives.sync_from_population(self.ecology)
        return introduction

    def advance_seasons(self, seasons=1):
        for _ in range(max(0, int(seasons))):
            self.last_representative_feedback = self.representatives.advance_season(self.ecology)
            self.ecology.advance(1, representative_feedback=self.last_representative_feedback)
            self._expand_if_population_reaches_edge()
            self.representatives.sync_from_population(self.ecology)
        return self.ecology.summary()

    def _expand_if_population_reaches_edge(self):
        """Enlarge the active local domain as life colonises its boundary."""
        if self.get_map_size() >= self.maximum_extent_m or self.ecology.edge_abundance() < 0.075:
            return False
        self.ecology.expand(margin_cells=4)
        self.bounds = dict(self.ecology.bounds)
        root = self.get_root_entity()
        if isinstance(root, dict):
            root["bounds"] = {"type": "bbox", **self.bounds}
            root["biosphere_width_m"] = self.bounds["max_x"] - self.bounds["min_x"]
            root["biosphere_height_m"] = self.bounds["max_y"] - self.bounds["min_y"]
        self._invalidate_layer_cache()
        return True

    def toggle_builder_running(self):
        if self.builder_time_scale > 0.0:
            return self.set_builder_time_scale(0.0)
        return self.set_builder_time_scale(1.0)

    def set_builder_time_scale(self, scale):
        scale = float(scale)
        if scale not in self.TIME_SCALES:
            return False
        self.builder_time_scale = scale
        self.builder_paused = scale <= 0.0
        return True

    def get_biosphere_time_state(self):
        season_names = ("Spring", "Summer", "Autumn", "Winter")
        progress = max(0.0, min(0.9999, self._season_accumulator / self.seconds_per_season))
        day = min(91, 1 + int(progress * 91.0))
        return {
            "year": 1 + self.ecology.season // 4,
            "season": season_names[self.ecology.season % 4],
            "day": day,
            "progress": progress,
            "scale": self.builder_time_scale,
            "paused": self.builder_paused,
        }

    def open_species_picker(self):
        if not self.species_picker_open:
            self._picker_previous_time_scale = self.builder_time_scale
            self.set_builder_time_scale(0.0)
        self.species_picker_open = True
        self.species_picker_focus_id = self.selected_species_id or self._default_species_id()
        ids = [profile.species_id for profile in self.species_profiles]
        if self.species_picker_focus_id in ids:
            self.species_picker_page = ids.index(self.species_picker_focus_id) // 8
        return True

    def close_species_picker(self):
        self.species_picker_open = False
        if self._picker_previous_time_scale is not None:
            self.set_builder_time_scale(self._picker_previous_time_scale)
            self._picker_previous_time_scale = None
        return True

    def focus_species_picker_item(self, species_id):
        if species_id not in self.ecology.profiles:
            return False
        self.species_picker_focus_id = species_id
        return True

    def change_species_picker_page(self, delta, page_size=8):
        count = len(self.species_profiles)
        page_size = max(1, int(page_size))
        pages = max(1, (count + page_size - 1) // page_size)
        self.species_picker_page = max(0, min(pages - 1, self.species_picker_page + int(delta)))
        first_index = self.species_picker_page * page_size
        if first_index < count:
            self.species_picker_focus_id = self.species_profiles[first_index].species_id
        return True

    def confirm_species_picker_selection(self):
        if not self.select_species(self.species_picker_focus_id):
            return False
        self.close_species_picker()
        return True

    def get_species_catalog_items(self):
        items = []
        for profile in self.species_profiles:
            entity = self.world_model.get_entity(profile.species_id) or {}
            roles = entity.get("succession_roles") or entity.get("ecological_roles") or []
            if isinstance(roles, str):
                roles = [roles]
            moisture_low = max(0.0, profile.moisture_optimum - profile.moisture_tolerance)
            moisture_high = min(1.0, profile.moisture_optimum + profile.moisture_tolerance)
            items.append({
                "id": profile.species_id,
                "label": profile.label,
                "scientific_name": entity.get("scientific_name") or entity.get("name") or profile.label,
                "description": entity.get("description") or entity.get("wiki_summary") or "No authored ecological summary yet.",
                "growth_form": profile.growth_form,
                "color": profile.color,
                "enabled": self.is_species_unlocked(profile.species_id),
                "selected": profile.species_id == self.selected_species_id,
                "focused": profile.species_id == self.species_picker_focus_id,
                "unlock_label": "Available" if self.is_species_unlocked(profile.species_id) else f"Requires {self.PIONEER_UNLOCK_BIOMASS_KG:.0f} kg biomass",
                "trait_lines": [
                    f"Growth form: {profile.growth_form.title()}",
                    f"Seasonal growth: {profile.growth_rate:.2f}",
                    f"Dispersal: {profile.dispersal:.2f}",
                    f"Carrying biomass: {profile.carrying_biomass_kg_m2:.1f} kg/m²",
                    f"Moisture niche: {moisture_low:.2f}–{moisture_high:.2f}",
                    f"Minimum light: {profile.light_minimum:.2f}",
                    f"Succession role: {', '.join(str(role).replace('_', ' ') for role in roles[:2]) or 'unresolved'}",
                    f"Source: {profile.provenance}",
                ],
            })
        return items

    def get_species_picker_model(self, page_size=8):
        items = self.get_species_catalog_items()
        page_size = max(1, int(page_size))
        page_count = max(1, (len(items) + page_size - 1) // page_size)
        self.species_picker_page = min(self.species_picker_page, page_count - 1)
        start = self.species_picker_page * page_size
        focused = next((item for item in items if item["id"] == self.species_picker_focus_id), items[0] if items else None)
        return {
            "open": self.species_picker_open,
            "items": items[start:start + page_size],
            "focused": focused,
            "page": self.species_picker_page,
            "page_count": page_count,
        }

    def get_species_preview_simulation(self, species_id):
        if species_id not in self.ecology.profiles:
            return None
        cached = self._species_preview_simulations.get(species_id)
        if cached is not None:
            return cached
        entity = self.world_model.get_entity(species_id) or {"id": species_id, "type": "species"}
        digest = hashlib.sha256(f"biosphere-picker:{species_id}".encode("utf-8")).digest()
        preview = SpeciesSimulation(
            world_model=self.world_model,
            species_id=species_id,
            species_entity=entity,
            seed=int.from_bytes(digest[:2], "big"),
        )
        preview.lod = 1
        maturity = 0.72 if self.ecology.profiles[species_id].growth_form == "tree" else 0.58
        preview.set_age(preview.mature_age_days * maturity)
        self._species_preview_simulations[species_id] = preview
        return preview

    def get_biosphere_dashboard_model(self):
        summary = self.ecology.summary()
        representatives = self.representatives.summary()
        selected = self.ecology.profiles.get(self.selected_species_id)
        return {
            "title": "BIOSPHERE COMMAND",
            "biomass_kg": summary["living_biomass_kg"],
            "footprint_m2": summary["living_footprint_m2"],
            "species_count": len(summary["species"]),
            "representatives": representatives,
            "domain_m": (self.bounds["max_x"] - self.bounds["min_x"], self.bounds["max_y"] - self.bounds["min_y"]),
            "selected_species": selected.label if selected else "None",
            "pioneers_unlocked": self.pioneers_unlocked(),
            "unlock_biomass_kg": self.PIONEER_UNLOCK_BIOMASS_KG,
            "time": self.get_biosphere_time_state(),
        }

    def get_biosphere_builder_summary_lines(self):
        summary = self.ecology.summary()
        representative_summary = self.representatives.summary()
        selected = self.ecology.profiles.get(self.selected_species_id)
        founding = self.biosphere_context.get("founding_point_source")
        return [
            "Biological City Builder",
            f"Tool: introduce species | {'paused' if self.builder_paused else f'{self.builder_time_scale:g}× realtime'}",
            f"Selected: {selected.label if selected else 'none'}",
            f"Season {summary['season']} | introductions {summary['introductions']}",
            f"Living footprint {summary['living_footprint_m2']:.1f} m² | biomass {summary['living_biomass_kg']:.1f} kg",
            f"Active domain {self.bounds['max_x'] - self.bounds['min_x']:.0f} × {self.bounds['max_y'] - self.bounds['min_y']:.0f} m",
            f"Deep representatives {representative_summary['alive']} alive / {representative_summary['total']} total",
            "Pioneer plants unlocked" if self.pioneers_unlocked() else f"Pioneers unlock at {self.PIONEER_UNLOCK_BIOMASS_KG:.0f} kg biomass",
            f"Founding point on source map: {founding[0]:.3f}, {founding[1]:.3f}" if isinstance(founding, (list, tuple)) and len(founding) >= 2 else "Founding point: local patch centre",
        ]

    def get_active_layer_label(self):
        return "Isometric biosphere development"

    def get_map_size(self):
        width = (self.bounds["max_x"] - self.bounds["min_x"]) * self.world_units_to_meters
        height = (self.bounds["max_y"] - self.bounds["min_y"]) * self.world_units_to_meters
        return max(width, height)

    def can_create_biosphere_patch_draft(self):
        return False

    def get_layers(self):
        layers = list(super().get_layers() or [])
        for layer in layers:
            if layer.get("entity_id") == self.context.root_entity_id:
                layer["suppress_label"] = True
        for patch in self.ecology.population_footprints():
            points = []
            for index in range(20):
                angle = math.tau * index / 20.0
                points.append((
                    patch["x"] + math.cos(angle) * patch["radius_m"],
                    patch["y"] + math.sin(angle) * patch["radius_m"],
                ))
            abundance = max(0.0, min(1.0, patch["abundance"]))
            color = tuple(round(48 * (1.0 - abundance) + channel * abundance) for channel in patch["color"])
            layers.append({
                "shape": "polygon", "points": points, "color": color,
                "border_color": tuple(min(255, channel + 18) for channel in color),
                "border_width": 1, "name": "Continuous population patch",
                "pickable": False, "draw_order": 820,
            })
        return layers

    def get_species_sprite_instances(self, limit=56):
        """Render only the persistent deep-sim representatives, not decorative clones."""
        instances = []
        for representative in self.representatives.items(alive_only=True):
            profile = self.ecology.profiles[representative.species_id]
            abundance = self.ecology.abundance_at(representative.species_id, representative.x, representative.y)
            instances.append({
                "representative_id": representative.representative_id,
                "species_id": representative.species_id,
                "x": representative.x,
                "y": representative.y,
                "abundance": abundance,
                "growth_form": profile.growth_form,
                "age_bucket": min(3, max(0, int(representative.simulation.render_snapshot.stats.get("maturity", 0.0) * 4.0))),
                "variant": representative.seed % 3,
                "selected": representative.representative_id == self.selected_representative_id,
            })
        return instances[:max(1, int(limit))]

    def get_asset_backed_species_ids(self):
        """Return plant profiles with authored module/texture files on disk."""
        project_root = Path(__file__).resolve().parents[2]
        result = []
        ref_fields = (
            "plant_root_module_ref", "plant_stem_module_ref", "plant_branch_module_ref",
            "plant_leaf_module_ref", "plant_flower_module_ref", "plant_fruit_module_ref",
            "plant_stem_texture_set_ref", "plant_branch_texture_set_ref", "plant_bark_texture_set_ref",
        )
        for profile in self.species_profiles:
            entity = (
                getattr(self.world_model, "resolved_species_entity", lambda _species_id: None)(profile.species_id)
                or self.world_model.get_entity(profile.species_id)
                or {}
            )
            refs = [entity.get(field) for field in ref_fields if entity.get(field)]
            if any((Path(ref) if Path(ref).is_absolute() else project_root / Path(ref)).exists() for ref in refs):
                result.append(profile.species_id)
        return result

    def plant_asset_test_forest(self):
        """Populate a deterministic free-coordinate gallery of every asset plant."""
        species_ids = self.get_asset_backed_species_ids()
        # The minimal reference world has procedural SpeciesSim plants but no authored
        # module paths; keeping them makes the fixture useful in tests and previews.
        if not species_ids:
            species_ids = [profile.species_id for profile in self.species_profiles]
        width = self.bounds["max_x"] - self.bounds["min_x"]
        height = self.bounds["max_y"] - self.bounds["min_y"]
        count = max(1, len(species_ids))
        columns = max(2, math.ceil(math.sqrt(count * width / max(0.1, height))))
        rows = math.ceil(count / columns)
        x_step = width / (columns + 1)
        y_step = height / (rows + 1)
        for index, species_id in enumerate(species_ids):
            row, column = divmod(index, columns)
            # Uneven offsets deliberately avoid a latent visual grid.
            jitter_x = (((index * 37) % 17) / 16.0 - 0.5) * x_step * 0.34
            jitter_y = (((index * 53) % 19) / 18.0 - 0.5) * y_step * 0.30
            x = self.bounds["min_x"] + (column + 1) * x_step + jitter_x
            y = self.bounds["min_y"] + (row + 1) * y_step + jitter_y
            radius = max(0.28, min(x_step, y_step) * 0.26)
            self.ecology.introduce(species_id, x, y, radius, propagule_pressure=0.64)
        self.representatives.sync_from_population(self.ecology)
        for representative in self.representatives.items(alive_only=True):
            representative.age_days = representative.simulation.mature_age_days * 0.72
            representative.simulation.set_age(representative.age_days)
        self.test_forest_species_ids = list(species_ids)
        return list(species_ids)

    def _screen_to_world(self, camera, screen_pos):
        state = self._isometric_projection_state
        if state:
            scale = max(0.001, state["scale"])
            projected_x = (float(screen_pos[0]) - state["origin_x"]) / scale
            projected_y = (float(screen_pos[1]) - state["origin_y"]) / (scale * 0.5)
            dx = (projected_x + projected_y) * 0.5
            dy = (projected_y - projected_x) * 0.5
            return state["center_x"] + dx, state["center_y"] + dy
        return super()._screen_to_world(camera, screen_pos)

    def get_representative_species_simulation(self, representative_id):
        representative = self.representatives.get(representative_id)
        return representative.simulation if representative is not None else None

    def select_representative(self, representative_id):
        representative = self.representatives.get(representative_id)
        if representative is None:
            return False
        self.selected_representative_id = representative_id
        return True

    def get_representative_ui_items(self):
        values = self.representatives.items()
        values.sort(key=lambda item: (
            int(item.representative_id.rsplit("_", 1)[-1]),
            self.ecology.profiles[item.species_id].label.lower(),
        ))
        return [{
            "id": item.representative_id,
            "label": f"{self.ecology.profiles[item.species_id].label} · {item.representative_id.rsplit('_', 1)[-1]}",
            "alive": item.alive,
            "selected": item.representative_id == self.selected_representative_id,
        } for item in values]

    def get_selection_inspector_payload(self):
        representative = self.representatives.get(self.selected_representative_id)
        if representative is None:
            return None
        profile = self.ecology.profiles[representative.species_id]
        outcome = representative.last_outcome or {}
        return {
            "title": profile.label,
            "kind": "Population representative",
            "details": [
                f"id: {representative.representative_id}",
                f"age: {representative.age_days:.0f} days | health: {representative.health:.0%}",
                f"vitality: {float(outcome.get('vitality', 0.0)):.0%} | fecundity: {float(outcome.get('fecundity', 0.0)):.0%}",
                "Feeds its measured outcome back into the spatial population.",
            ],
            "actions": [{"id": "biosphere_launch_representative", "label": "Open Representative in SpeciesSim"}],
        }

    def get_selected_representative_launch_context(self):
        representative = self.representatives.get(self.selected_representative_id)
        if representative is None:
            return None
        return {
            "representative_id": representative.representative_id,
            "species_id": representative.species_id,
            "seed": representative.seed,
            "age_days": representative.age_days,
            "environment": dict(representative.last_outcome),
            "simulation": representative.simulation,
        }

    def handle_pointer_event(self, event, camera, screen_pos):
        button = getattr(event, "button", None)
        if event.type == self.MOUSEBUTTONUP_EVENT_TYPE and button == 1 and self.builder_tool == self.PLACEMENT_TOOL:
            was_dragging = self.is_camera_dragging
            was_pan = self.camera_drag_has_moved
            self._reset_camera_drag()
            if was_dragging and not was_pan:
                for representative_id, rect in reversed(self._representative_screen_hitboxes):
                    if rect.collidepoint(screen_pos):
                        self.select_representative(representative_id)
                        return
                world_x, world_y = self._screen_to_world(camera, screen_pos)
                self.place_selected_species(world_x, world_y)
                return
        super().handle_pointer_event(event, camera, screen_pos)

    def update(self, dt):
        super().update(dt)
        if self.builder_paused:
            return
        self._season_accumulator += max(0.0, float(dt)) * self.builder_time_scale
        while self._season_accumulator >= self.seconds_per_season:
            self._season_accumulator -= self.seconds_per_season
            self.advance_seasons(1)

    def consumes_global_escape(self):
        return self.species_picker_open

    def handle_event(self, event):
        if self.species_picker_open and event.type == self.KEYDOWN_EVENT_TYPE and getattr(event, "key", None) == 27:
            return self.close_species_picker()
        return super().handle_event(event)
