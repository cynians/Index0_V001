"""Map-native biological city builder.

MapSimulation supplies terrain, scale, navigation and rendering contracts.
This class adds a planning layer (introductions) and a derived ecology layer.
"""

from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path

from engine.logger import logger
from simulations.biosphere import terrain_site
from simulations.biosphere.biomes import Biome, biome_at
from simulations.biosphere.ecology import (
    FLOOD_NEVER_YEARS, FLOOD_REWORKING_FIELD, BiosphereEcology, moisture_response, profile_from_entity,
    raw_ground_wetness, salinity_limits, seed_days_of, thermal_response, waterlogging_limits, years_to_grow,
)
from simulations.biosphere.flora import biome_flora, rarity_from_share, save_flora
from simulations.biosphere.plant_pictures import planet_plant_pictures
from simulations.biosphere.resident_start import ResidentFlora
from simulations.biosphere.surroundings import Surroundings
from simulations.species.plant_life_timing import describe_span, life_timing_lines
from simulations.biosphere.representatives import RepresentativePopulationManager
from simulations.biosphere.soil_succession import SoilOrganicMatterField
from engine import asset_files
from simulations.map.map_simulation import MapSimulation
from simulations.map.worldgen_substrate import WorldgenSubstrate
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
    # The builder draws in its own projection and shows its own scale; the
    # engine's bar measures the Map camera, which this view does not use.
    draws_own_scale = True
    PLACEMENT_TOOL = "introduce_species"
    BIOMASSER_ID = "spec_biomasser_13b"
    BASE_SECONDS_PER_SEASON = 30.0
    TIME_SCALES = (0.0, 1.0, 4.0, 16.0, 64.0)
    # Fast-forward runs as fast as the machine simulates, never by banking
    # seasons it then has to work off in one frozen frame.
    MAX_SEASONS_PER_FRAME = 2
    # Seeding tools: by hand, or sown thinly over a disc of this radius.
    SEEDING_BRUSHES_M = (None, 5.0, 20.0, 60.0)
    # Ground is refined under the founding square, and wherever the view rests
    # closer than this: detail follows the eye, not every sown hectare.
    REFINE_VIEW_SCALE_PX_PER_M = 4.0
    REFINE_VIEW_REST_SECONDS = 1.0
    REFINE_COOLDOWN_SECONDS = 6.0
    MOUSEWHEEL_EVENT_TYPE = 1027
    VIEW_ZOOM_LIMITS = (0.25, 8.0)
    # Relief at plant scale is often centimetres; exaggeration is a view aid
    # and never changes the sampled ground.
    RELIEF_SCALES = (1.0, 2.0, 5.0)

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
        source_root = world_model.get_entity(patch_id) or {}
        imported_surface = bool((source_root.get("heightmap_model") or {}).get("sample_grid"))
        if imported_surface:
            b = source_root["bounds"]
            self.maximum_extent_m = max(b["max_x"]-b["min_x"], b["max_y"]-b["min_y"])
        # A site founded on generated terrain: the root's bounds are the whole
        # region in metres, the simulated domain a growing window inside it.
        self.terrain_frame = None
        self.terrain = None
        self._founding_domain = None
        terrain_linked = (
            bool(source_root.get(terrain_site.TERRAIN_SOURCE_FIELD))
            and terrain_site.anchor_region(world_model, source_root) is not None
            and (source_root.get("bounds") or {}).get("type") == "bbox"
        )
        if terrain_linked:
            frame = source_root["bounds"]
            self.terrain_frame = {key: float(frame[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
            if self.biosphere_context.get("founding_point_local_m") and not source_root.get("biosphere_founding_point_local_m"):
                source_root = dict(source_root, biosphere_founding_point_local_m=self.biosphere_context["founding_point_local_m"])
            self._founding_domain = terrain_site.founding_domain(source_root, initial_extent)
            self.maximum_extent_m = min(
                terrain_site.MAX_DOMAIN_EXTENT_M,
                max(frame["max_x"] - frame["min_x"], frame["max_y"] - frame["min_y"]),
            )
        self.replaces_map_view = terrain_linked
        if not source_root or (bootstrap_lifeless and not imported_surface and not terrain_linked):
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
        self.ecology.flood_seed = int.from_bytes(hashlib.sha256(str(patch_id).encode("utf-8")).digest()[:4], "big")
        # The planet whose plants these are; a site off any planet stands for itself.
        self.planet_id = (self.get_root_entity() or {}).get("terrain_root_planet_id") or patch_id
        # The individuals this planet's plants are drawn as.
        self.plant_pictures = planet_plant_pictures(self.world_model, self.planet_id)
        self.ecology.pictures = self.plant_pictures
        if terrain_linked:
            self.substrate = terrain_site.site_substrate(self.world_model, self.get_root_entity())
            self.terrain = terrain_site.TerrainDetail(self.world_model, self.get_root_entity())
        else:
            self.substrate = WorldgenSubstrate(self.get_root_entity(), self.bounds) if imported_surface else None
        self.ecology.substrate = self.substrate
        self.isometric_view_zoom = 1.0
        self.isometric_view_center = None
        self.terrain_vertical_scale = 1.0
        if terrain_linked:
            # A landscape view shows plants at their real size against the
            # ground: a tree stands far above a shrub when seen from close by.
            self.isometric_sprite_height_cap = 320
        self._pointer_screen_pos = None
        self._isometric_drag_start_center = None
        # The app turns this on; a headless or test simulation refines only on request.
        self.auto_resolve_terrain = False
        self.terrain_redraw = None
        self.terrain_progress = None
        self.terrain_error = None
        self._terrain_pending = []
        self._terrain_failed = set()
        self._terrain_resolve_armed = False
        self._terrain_skip_frames = 0
        self._terrain_view = None
        self._terrain_view_changed_at = float("-inf")
        self._terrain_cooldown_until = float("-inf")
        self.seeding_brush_m = None
        # What happened, in the player's terms: failures with their cause,
        # soil stages reached, ground the living area grew into.
        self.field_notes = []
        self._established_species = set()
        self._seeding_species = set()
        self._reported_soil_tier = 0
        self._biomass_history = {}
        self._biomass_peak = {}
        self._dwindling_species = set()
        self.soil = SoilOrganicMatterField(
            self.bounds,
            columns=32,
            rows=32,
            initial_organic_matter_kg_m2=float(
                self.biosphere_context.get("initial_soil_organic_matter_kg_m2", 0.0) or 0.0
            ),
        )
        self.ecology.soil = self.soil
        self.soil.initialize_from_abiotic(self.ecology)
        self.representatives = RepresentativePopulationManager(self.world_model, pictures=self.plant_pictures)
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
        overlay = self.world_model.get_entity(self.biosphere_id) or {}
        self.inspection_population = bool(overlay.get("inspection_introductions"))
        for item in overlay.get("inspection_introductions") or []:
            sid = item["species_id"]
            if sid not in self.ecology.profiles:
                continue
            self.ecology.introduce(sid, item["x"], item["y"], item["radius_m"], .82)
            self.ecology.patches[-1].development_days = self.ecology.profiles[sid].maturity_days * item["development_fraction"]
        if self.inspection_population:
            self.representatives.sync_from_population(self.ecology)
            for rep in self.representatives.items(alive_only=True):
                patches = self.ecology.species_patches(rep.species_id)
                fraction = max(p.development_days / self.ecology.profiles[rep.species_id].maturity_days for p in patches)
                self.representatives.set_maturity(rep, fraction)
        # Ground whose biomes have a flora opens with that flora growing (``resident_start``).
        self.resident_flora = None if self.inspection_population else ResidentFlora.of(self)
        if self.resident_flora is not None:
            residents = self.resident_flora.settle()
            if residents:
                self.representatives.sync_from_population(self.ecology)
                self._note("plan", f"{len(residents)} plants of this ground's flora grow here already")
            elif not self.resident_flora.vegetation().cover:
                self.resident_flora = None
        # What the map shows round the living area: drawn, not simulated (``surroundings``).
        self.surroundings = Surroundings(self.resident_flora) if self.resident_flora is not None else None
        self._refresh_terrain_pending()
        self._order_catalogue_by_site_fit()

    _VERDICT_ORDER = {"pioneer": 0, "suits": 1, "marginal": 2, "sheltered": 3, "unfit": 4}

    def _order_catalogue_by_site_fit(self):
        """Within each tier, list what the site's climate can carry before what it cannot."""
        if self.substrate is None or self.terrain_frame is None:
            return
        fits = {profile.species_id: self.get_species_climate_fit(profile.species_id) for profile in self.species_profiles}
        self.species_profiles.sort(key=lambda profile: (
            profile.species_id != self.BIOMASSER_ID, profile.succession_tier,
            self._VERDICT_ORDER.get((fits[profile.species_id] or {}).get("verdict"), 5),
            -float((fits[profile.species_id] or {}).get("potential", 0.0)),
            profile.label.lower(),
        ))

    def _resolve_root_bounds(self):
        if getattr(self, "terrain_frame", None) is not None:
            # The Map base class frames the root; here the frame is the
            # simulated domain, which the root's regional bounds only contain.
            ecology = getattr(self, "ecology", None)
            return dict(ecology.bounds if ecology is not None else self._founding_domain)
        return super()._resolve_root_bounds()

    # ------------------------------------------------------------------
    # Generated terrain under the domain
    # ------------------------------------------------------------------
    def founding_point(self):
        root = self.get_root_entity() or {}
        point = root.get("biosphere_founding_point_local_m") or self.biosphere_context.get("founding_point_local_m")
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            return float(point[0]), float(point[1])
        if self._founding_domain is not None:
            domain = self._founding_domain
            return (domain["min_x"] + domain["max_x"]) * 0.5, (domain["min_y"] + domain["max_y"]) * 0.5
        return (self.bounds["min_x"] + self.bounds["max_x"]) * 0.5, (self.bounds["min_y"] + self.bounds["max_y"]) * 0.5

    def _wanted_terrain_chunks(self):
        """Chunks worth refining now: the founding ground, and what a close view rests on."""
        wanted = list(self.terrain.chunk_keys_for(self._founding_domain))
        state = self._isometric_projection_state
        if state:
            view = (round(state["center_x"], 2), round(state["center_y"], 2), round(state["scale"], 4))
            now = time.monotonic()
            if view != self._terrain_view:
                self._terrain_view = view
                self._terrain_view_changed_at = now
            if (state["scale"] >= self.REFINE_VIEW_SCALE_PX_PER_M
                    and now - self._terrain_view_changed_at >= self.REFINE_VIEW_REST_SECONDS
                    and now >= self._terrain_cooldown_until):
                key = self.terrain.chunk_key_at(state["center_x"], state["center_y"])
                if key is not None and key not in wanted:
                    wanted.append(key)
        return wanted

    def _refresh_terrain_pending(self):
        if self.terrain is None or not self.terrain.needed():
            self._terrain_pending = []
        else:
            self._terrain_pending = [
                key for key in self._wanted_terrain_chunks()
                if key not in self._terrain_failed and not self.terrain.covered(key)
            ]
        return self._terrain_pending

    def pending_terrain_chunks(self):
        return list(self._terrain_pending)

    def _rebuild_substrate(self):
        self.substrate = terrain_site.site_substrate(self.world_model, self.get_root_entity())
        self.ecology.substrate = self.substrate
        self._invalidate_layer_cache()

    def resolve_next_terrain_chunk(self, progress_callback=None):
        """Refine the nearest unresolved chunk under the domain.  Blocks while worldgen runs."""
        if self.terrain is None or not self.terrain.can_generate():
            return None
        pending = self._refresh_terrain_pending()
        if not pending:
            return None
        key = pending[0]
        total = len(pending)
        self.terrain_progress = {"chunk": key, "progress": 0.0, "detail": "Preparing", "remaining": total}

        def report(progress, detail, preview=None):
            self.terrain_progress = {
                "chunk": key, "progress": max(0.0, min(1.0, float(progress))),
                "detail": str(detail or ""), "remaining": total,
            }
            if callable(progress_callback):
                progress_callback(progress, detail)

        region = None
        try:
            region = self.terrain.generate(
                key, progress_callback=report,
                storage_root=getattr(self.context, "worldgen_storage_root", None),
            )
        except Exception as error:  # worldgen failures must not end the session
            self.terrain_error = f"{type(error).__name__}: {error}"
            logger.error(f"[Biosphere] Terrain chunk {key} could not be refined: {self.terrain_error}")
        finally:
            self.terrain_progress = None
        if isinstance(region, dict):
            self.terrain_error = None
            self._rebuild_substrate()
        else:
            self._terrain_failed.add(key)
        self._refresh_terrain_pending()
        return region

    def resolve_terrain(self, progress_callback=None, limit=None):
        """Refine every pending chunk (or the first ``limit``); returns the new regions."""
        regions = []
        while self._terrain_pending and (limit is None or len(regions) < int(limit)):
            region = self.resolve_next_terrain_chunk(progress_callback)
            if region is None:
                break
            regions.append(region)
        return regions

    def _advance_terrain_resolution(self):
        """One step of on-demand refinement per frame; True while the clock should hold."""
        if self.terrain is None or not self.auto_resolve_terrain:
            return False
        if self._terrain_skip_frames > 0:
            # The frame after a blocking refinement reports its whole duration as dt.
            self._terrain_skip_frames -= 1
            return True
        if not self._refresh_terrain_pending() or not self.terrain.can_generate():
            self._terrain_resolve_armed = False
            return False
        if not self._terrain_resolve_armed:
            # Let one frame draw the notice before worldgen blocks the loop.
            self._terrain_resolve_armed = True
            return True
        self._terrain_resolve_armed = False
        self.resolve_next_terrain_chunk(self.terrain_redraw)
        self._terrain_skip_frames = 1
        self._terrain_cooldown_until = time.monotonic() + self.REFINE_COOLDOWN_SECONDS
        return True

    def get_terrain_status(self):
        """What the ground under the domain is, for the HUD."""
        if self.terrain is None or self.substrate is None:
            return {"linked": False}
        x, y = self.founding_point()
        level = self.substrate.detail_level_at(x, y)
        from simulations.world_gen.regional_refinement import detail_level_spec
        environment = self.substrate.environment_at(x, y)
        pending = len(self._terrain_pending)
        progress = self.terrain_progress
        resolving = progress is not None or (self._terrain_resolve_armed and pending > 0)
        spacing = self.substrate.sample_spacing_at(x, y)
        if resolving:
            fraction = float((progress or {}).get("progress", 0.0))
            label = f"Refining ground · {pending} chunk{'s' if pending != 1 else ''} left · {fraction:.0%}"
        elif pending and not self.terrain.can_generate():
            label = f"Ground: {detail_level_spec(level)['label']} · {spacing:.1f} m samples · cannot refine here"
        elif pending:
            label = f"Ground: {detail_level_spec(level)['label']} · {spacing:.1f} m samples · {pending} chunk{'s' if pending != 1 else ''} queued"
        else:
            label = f"Ground: {detail_level_spec(level)['label']} · {spacing:.1f} m samples"
        koppen = self.substrate.koppen_at(x, y)
        climate = {
            "mean_temperature_c": environment["temperature_k"] - 273.15,
            "annual_precipitation_mm": environment["annual_precipitation_mm"],
            # As the kernel reads the bare ground: its water balance where the map tells one.
            "soil_moisture": raw_ground_wetness(environment),
            "koppen": koppen,
        }
        rain = f"{climate['annual_precipitation_mm']:.0f} mm/yr"
        if "annual_potential_evaporation_mm" in environment:
            climate["annual_demand_mm"] = environment["annual_potential_evaporation_mm"]
            rain = f"{rain} of rain against {climate['annual_demand_mm']:.0f} mm the air asks for"
        if "coldest_month_temperature_k" in environment:
            climate["coldest_month_c"] = environment["coldest_month_temperature_k"] - 273.15
            climate["warmest_month_c"] = environment["warmest_month_temperature_k"] - 273.15
        zone = f"{koppen[1]} ({koppen[0]})" if koppen else "Climate"
        if "coldest_month_c" in climate:
            climate_label = (
                f"{zone} · {climate['coldest_month_c']:.0f} to {climate['warmest_month_c']:.0f} °C monthly · "
                f"{rain} · wetness {climate['soil_moisture']:.2f}"
            )
        else:
            climate_label = (
                f"{zone} · {climate['mean_temperature_c']:.0f} °C mean · "
                f"{rain} · wetness {climate['soil_moisture']:.2f}"
            )
        return {
            "linked": True, "label": label, "climate_label": climate_label, "climate": climate,
            "detail_level": level, "sample_spacing_m": spacing, "pending": pending,
            "resolving": resolving, "progress": float((progress or {}).get("progress", 0.0)),
            "detail": (progress or {}).get("detail"), "error": self.terrain_error,
            "elevation_m": environment["elevation_m"],
            "relief_scale": self.terrain_vertical_scale,
        }

    def get_species_climate_fit(self, species_id):
        """How the founding point suits a species, for the catalogue.

        Judged with the population kernel's own arithmetic in three
        situations: on the raw ground, on built soil in the open, and on built
        soil under a canopy.  The verdict is the first of them in which a
        sparse population would hold.
        """
        profile = self.ecology.profiles.get(species_id)
        if profile is None or self.substrate is None:
            return None
        x, y = self.founding_point()
        environment = self.ecology.environment_at(x, y)
        potential = self.ecology.site_potential(profile, environment)
        thermal, thermal_limit = thermal_response(profile, dict(environment, canopy_shade=0.0))
        abiotic = float(environment.get("abiotic_soil_moisture", environment["soil_moisture"]))
        moisture = float(moisture_response(profile, abiotic))
        if potential.get("reaction", 1.0) < min(potential.get("salt", 1.0), potential.get("rooting", 1.0),
                                                potential["moisture_mature"], potential["thermal_open"]):
            reason = self._describe_limit(profile, "soil reaction", thermal_limit, environment)
        elif potential.get("salt", 1.0) < min(potential.get("rooting", 1.0), potential["moisture_mature"], potential["thermal_open"]):
            reason = self._describe_limit(profile, "salt", thermal_limit, environment)
        elif potential.get("rooting", 1.0) < min(potential["moisture_mature"], potential["thermal_open"]):
            reason = self._describe_limit(profile, "rooting depth", thermal_limit, environment)
        elif potential["moisture_mature"] <= potential["thermal_open"]:
            # The wetness the verdict speaks of: the raw ground's for what can pioneer it, built soil's for the rest.
            situation = "wetness_raw" if self.ecology.sustains(profile, potential["raw"]) else "wetness_mature"
            reason = self._describe_limit(profile, "moisture", thermal_limit,
                                          dict(environment, soil_moisture=potential.get(situation, abiotic)))
        else:
            reason = self._describe_limit(profile, "temperature", thermal_limit, environment)
        sustains = self.ecology.sustains
        every = environment.get(FLOOD_REWORKING_FIELD, FLOOD_NEVER_YEARS)
        if potential.get("flood_standing", 1.0) < self.FLOOD_UNFIT_STANDING:
            # Whatever the ground would give, the river does not leave it the time.
            reason = (f"the river reworks this ground about every {self._years(every)}, "
                      f"and it takes {self._years(years_to_grow(profile))} to grow up")
            verdict, label = "unfit", f"Cannot hold here: {reason}"
        elif sustains(profile, potential["raw"]):
            verdict = "pioneer"
            label = f"Can pioneer the raw ground here, up to {potential['raw']:.0%}"
            if potential["raw"] < 0.6:
                label += f": {reason}"
        elif sustains(profile, potential["open"]):
            if potential["open"] >= 0.6:
                verdict, label = "suits", f"Suits this site once soil is built, up to {potential['open']:.0%}"
            else:
                verdict, label = "marginal", f"Marginal even on built soil, {potential['open']:.0%} at best: {reason}"
        elif sustains(profile, potential["sheltered"]):
            verdict = "sheltered"
            label = f"Needs built soil and a nurse canopy here: {reason} in the open"
        else:
            verdict, label = "unfit", f"Cannot hold here: {reason}"
        if verdict != "unfit" and potential.get("flood_standing", 1.0) < 0.9:
            label += f"; the river reworks this ground about every {self._years(every)}"
        return {"thermal": thermal, "thermal_limit": thermal_limit, "moisture": moisture,
                "suitability": self.ecology._suitability(profile, environment),
                "raw": potential["raw"], "potential": potential["open"], "sheltered": potential["sheltered"],
                "sustainable": verdict != "unfit",
                "verdict": verdict, "label": label, "reason": reason}

    # A species is told it cannot hold where the river leaves under this share of the ground the years it needs.
    FLOOD_UNFIT_STANDING = 0.2

    @staticmethod
    def _years(years):
        """A span of years in the unit a person would use."""
        return describe_span(float(years) * 365.25)

    # ------------------------------------------------------------------
    # Explaining outcomes
    # ------------------------------------------------------------------
    def short_label(self, species_id):
        """A species' everyday name: the part before the scientific one."""
        profile = self.ecology.profiles.get(species_id)
        label = profile.label if profile is not None else str(species_id)
        return label.split(" - ")[0].strip() or label

    @staticmethod
    def _describe_limit(profile, limiting, thermal_limit, environment):
        """A limiting factor in a few plain words."""
        if limiting == "habitat":
            return "open water"
        if limiting == "moisture":
            site = float(environment.get("soil_moisture", 0.0))
            if site < profile.moisture_optimum:
                return f"too dry (wetness {site:.2f}, best near {profile.moisture_optimum:.2f})"
            # More water than it likes harms no plant; water standing in its roots does.
            return f"waterlogged (wetness {site:.2f}, its roots bear {waterlogging_limits(profile)[0]:.2f})"
        if limiting == "temperature" and thermal_limit == "heat" and float(environment.get("canopy_shade", 0.0)) < 0.5:
            return "too hot without shade"
        if limiting == "temperature":
            return {
                "heat": "too hot", "frost": "winters too cold",
                "growing-season warmth": "summers too cold",
            }.get(thermal_limit, "temperature")
        if limiting == "soil reaction":
            low, high = profile.soil_ph_range
            return (f"soil too sour or too limy (it grows from pH {low:g} to {high:g}; "
                    f"this ground has {float(environment.get('soil_ph', float('nan'))):.1f})")
        if limiting == "salt":
            return f"ground water too salty (it bears {salinity_limits(profile)[0]:.0%} sea water)"
        if limiting == "rooting depth":
            from simulations.biosphere.ecology import rootable_depth_of, rooting_depth_m

            return (f"ground too shallow ({float(rootable_depth_of(environment) or 0.0):.2f} m to root in, "
                    f"roots to {rooting_depth_m(profile):.1f} m)")
        if limiting == "light":
            return "too shaded"
        if limiting == "organic soil":
            return f"soil too raw (needs {profile.soil_organic_requirement_kg_m2:.3f} kg/m² organic matter)"
        if limiting in {"nitrogen", "phosphorus"}:
            return f"{limiting}-starved"
        return str(limiting)

    def diagnose(self, species_id, x, y):
        """Why a species does well or badly at one place."""
        profile = self.ecology.profiles.get(species_id)
        if profile is None:
            return None
        environment = self.ecology.environment_at(x, y)
        factors = self.ecology.suitability_factors(profile, environment)
        return {
            "species_id": species_id, "label": self.short_label(species_id),
            "suitability": factors["suitability"], "scores": dict(factors["scores"]),
            "limiting": factors["limiting"],
            # Wetness is the plant's own: the same ground is wetter for roots that reach its water.
            "reason": self._describe_limit(
                profile, factors["limiting"], factors.get("thermal_limit"),
                dict(environment, soil_moisture=factors.get("wetness", environment.get("soil_moisture", 0.0)))),
        }

    def _note(self, kind, text, season=None):
        """Write a field note, dated now or at the ``season`` it speaks of."""
        season = self.ecology.season if season is None else int(season)
        self.field_notes.append({
            "kind": kind, "text": text, "season": season,
            "when": f"Y{1 + season // 4} {('Spring', 'Summer', 'Autumn', 'Winter')[season % 4]}",
        })
        del self.field_notes[:-60]

    def get_field_notes(self, limit=6):
        """Newest first."""
        return list(reversed(self.field_notes[-max(1, int(limit)):]))

    def _population_centres(self):
        centres = {}
        for patch in self.ecology.patches:
            total = centres.setdefault(patch.species_id, [0.0, 0.0, 0.0])
            weight = max(1e-6, patch.abundance)
            total[0] += patch.x * weight
            total[1] += patch.y * weight
            total[2] += weight
        return {species_id: (x / w, y / w) for species_id, (x, y, w) in centres.items()}

    def _population_pressures(self):
        """Per species, ``(competition, overtopping)`` on its heaviest stand."""
        heaviest = {}
        for patch in self.ecology.patches:
            weight = patch.abundance * patch.radius_m ** 2
            if species_weight := heaviest.get(patch.species_id):
                if species_weight[0] >= weight:
                    continue
            heaviest[patch.species_id] = (weight, patch)
        return {species_id: self.ecology._competition_at_patch(patch) for species_id, (_weight, patch) in heaviest.items()}

    def _decline_reason(self, species_id, x, y, pressure):
        """Why a population is losing ground: its neighbours first, then the site."""
        competition, overtopping = pressure or (0.0, 0.0)
        if overtopping >= 0.25:
            return "overgrown by taller plants"
        diagnosis = self.diagnose(species_id, x, y)
        if min(diagnosis["scores"].values(), default=1.0) >= 0.6:
            # Nothing about the ground is wrong enough to explain it.
            return "crowded out by its neighbours" if competition >= 0.35 else "holding too thinly to renew itself"
        return diagnosis["reason"]

    # From here a plant's years to full size are worth telling the player.
    SLOW_MATURITY_DAYS = 2.0 * 365.25

    def _record_season_outcomes(self, before_centres, before_extent, before_pressures=None):
        """Turn one season's changes into field notes."""
        before_pressures = before_pressures or {}
        flood = self.ecology.last_flood
        if flood and flood["season"] == self.ecology.season - 1:
            taken = ", ".join(
                (f"{count} {self.short_label(species_id)}" if count else f"part of the {self.short_label(species_id)}")
                for species_id, count in sorted(flood["lost"].items(), key=lambda item: -item[1]))
            self._note("flood", f"The river rose as it does about every {self._years(flood['return_years'])} "
                                f"and reworked its low ground: took {taken}", season=flood["season"])
        else:
            flood = None
        living = {patch.species_id for patch in self.ecology.patches}
        for species_id, (x, y) in before_centres.items():
            if species_id in living:
                continue
            self._established_species.discard(species_id)
            self._seeding_species.discard(species_id)
            if flood and species_id in flood["lost"]:
                # What the river took did not fail for want of anything the ground could give.
                self._note("failure", f"{self.short_label(species_id)} is gone: the river took its last plants",
                           season=flood["season"])
                continue
            reason = self._decline_reason(species_id, x, y, before_pressures.get(species_id))
            self._note("failure", f"{self.short_label(species_id)} died out: {reason}")
        for species_id in sorted(living):
            if species_id in self._established_species:
                continue
            if any(patch.abundance >= 0.18 and self.ecology.season - patch.season_introduced >= 8
                   for patch in self.ecology.species_patches(species_id)):
                self._established_species.add(species_id)
                self._note("success", f"{self.short_label(species_id)} established")
                self._enter_flora(species_id)
        if self.ecology.season % 4 == 0:
            # Once a year: how common each established plant has become is what the biome's flora says of it.
            for species_id in sorted(living & self._established_species):
                self._enter_flora(species_id)
        # A stand of a slow plant only creeps outward for years.  Say when
        # its first plants set seed: from then on it throws founders.
        for species_id in sorted(living - self._seeding_species):
            profile = self.ecology.profiles[species_id]
            seed_days = seed_days_of(profile)
            if seed_days < self.SLOW_MATURITY_DAYS:
                continue
            if any(patch.development_days >= seed_days for patch in self.ecology.species_patches(species_id)):
                self._seeding_species.add(species_id)
                self._note("success", f"{self.short_label(species_id)} "
                           + ("is full-grown and " if seed_days >= profile.maturity_days else "") + "sets seed")
        biomass = {item["species_id"]: float(item["biomass_kg"]) for item in self.ecology.summary()["species"]}
        for species_id in list(self._biomass_history):
            if species_id not in biomass:
                for record in (self._biomass_history, self._biomass_peak):
                    record.pop(species_id, None)
                self._dwindling_species.discard(species_id)
        for species_id, value in biomass.items():
            history = self._biomass_history.setdefault(species_id, [])
            history.append(value)
            del history[:-9]
            peak = max(self._biomass_peak.get(species_id, 0.0), value)
            self._biomass_peak[species_id] = peak
            # A population that held and has since lost a third of its best is
            # told once, while there is still time to act, not only at its end.
            if species_id in self._established_species:
                if value < peak * 0.65 and species_id not in self._dwindling_species:
                    self._dwindling_species.add(species_id)
                    x, y = self._population_centres()[species_id]
                    reason = self._decline_reason(species_id, x, y, self._population_pressures().get(species_id))
                    self._note("warning", f"{self.short_label(species_id)} is dwindling: {reason}")
                elif value > peak * 0.9:
                    self._dwindling_species.discard(species_id)
        soil = self.soil.summary()
        tier = int(soil["supported_succession_tier"])
        if tier > self._reported_soil_tier:
            newly = sum(
                1 for profile in self.species_profiles
                if self._reported_soil_tier < profile.succession_tier <= tier and profile.growth_form != "aquatic"
            )
            self._reported_soil_tier = tier
            self._note("soil", f"Soil reached {soil['soil_stage']}: {newly} more species can be planted")
        extent = (self.bounds["max_x"] - self.bounds["min_x"], self.bounds["max_y"] - self.bounds["min_y"])
        if extent != before_extent:
            self._note("growth", f"Living area grew to {extent[0]:.0f} × {extent[1]:.0f} m")

    def flora_standing(self, species_id):
        """``(biome, share)``: the biome a species stands in on this site, and the share of the living area it holds."""
        centre = self._population_centres().get(species_id)
        if centre is None:
            return None
        ground = sum(math.pi * patch.radius_m ** 2 * patch.abundance for patch in self.ecology.species_patches(species_id))
        share = min(1.0, ground / max(1e-9, self.ecology.width * self.ecology.height))
        if self.substrate is not None and hasattr(self.substrate, "open_water_array"):
            return biome_at(self.substrate, *centre), share
        return Biome("", ""), share  # a plot off any generated ground

    def _enter_flora(self, species_id):
        """Write an established species into the flora of the biome it stands in, as common as it has become."""
        if self.resident_flora is not None and species_id in self.resident_flora.species:
            return  # it is in the flora already, and one plot does not say how common it is on the planet
        standing = self.flora_standing(species_id)
        if standing is None:
            return
        biome, share = standing
        flora = biome_flora(self.world_model, self.planet_id, biome)
        year = int(self.biosphere_context.get("year", 2400) or 2400) + self.ecology.season // 4
        change = flora.record(species_id, rarity_from_share(share), year=year, cover_share=share,
                              site_id=(self.get_root_entity() or {}).get("id"))
        if change is None:
            return
        save_flora(self.world_model, flora)
        label, rarity = self.short_label(species_id), flora.rarity(species_id)
        if change == "entered":
            self._note("success", f"{label} is now part of the {biome.label} flora ({rarity})")
        else:
            self._note("growth", f"{label} is now {rarity} in the {biome.label} flora")

    def get_population_rows(self, limit=8):
        """One row per living species, heaviest first: what stands where, and which way it is going."""
        centres = self._population_centres()
        rows = []
        for item in self.ecology.summary()["species"]:
            species_id = item["species_id"]
            history = self._biomass_history.get(species_id) or [float(item["biomass_kg"])]
            earlier = history[-5] if len(history) >= 5 else history[0]
            now = float(item["biomass_kg"])
            trend = "up" if now > earlier * 1.03 else "down" if now < earlier * 0.97 else "steady"
            living = [rep for rep in self.representatives.items(species_id, alive_only=True)]
            rows.append({
                "species_id": species_id,
                "label": self.short_label(species_id),
                "stands": int(item["population_patches"]),
                # How many plants, for a species kept as individuals; ``None`` for a crust or a sward.
                "plants": item.get("individuals"),
                "biomass_kg": now,
                # How tall its tallest stand has grown: a wood is years in the making.
                "height_m": max((self.ecology._stature_m(patch) for patch in self.ecology.species_patches(species_id)), default=0.0),
                "trend": trend,
                "dwindling": species_id in self._dwindling_species,
                "established": species_id in self._established_species,
                "centre": centres.get(species_id),
                "representative_id": living[0].representative_id if living else None,
                "selected": any(rep.representative_id == self.selected_representative_id for rep in living),
            })
        rows.sort(key=lambda row: (-row["biomass_kg"], row["label"]))
        return rows[:max(1, int(limit))]

    def focus_population(self, species_id):
        """Bring a species' ground into view and select one of its organisms for inspection."""
        centre = self._population_centres().get(species_id)
        if centre is None:
            return False
        if self.terrain_frame is not None or not self.ecology.contains(*centre):
            self.isometric_view_center = self._clamp_view_center(*centre)
        living = self.representatives.items(species_id, alive_only=True)
        if living:
            nearest = min(living, key=lambda rep: math.hypot(rep.x - centre[0], rep.y - centre[1]))
            self.selected_representative_id = nearest.representative_id
        return True

    def get_view_scale(self):
        """``(pixels per metre along the screen's horizontal, metres across the view)`` or ``None``."""
        state = self._isometric_projection_state
        if not state:
            return None
        # A metre along the screen's horizontal runs diagonally across the ground grid.
        horizontal = float(state["scale"]) * math.sqrt(2.0)
        scene = state.get("scene_rect")
        return horizontal, (scene.width / horizontal if scene is not None else None)

    def get_cursor_readout(self):
        """The ground under the pointer and how the selected species would fare there."""
        state = self._isometric_projection_state
        if self.substrate is None or not state or self._pointer_screen_pos is None:
            return None
        scene = state.get("scene_rect")
        if scene is not None and not scene.collidepoint(self._pointer_screen_pos):
            return None
        x, y = self._screen_to_world(None, self._pointer_screen_pos)
        frame = self.terrain_frame or self.bounds
        if not (frame["min_x"] <= x <= frame["max_x"] and frame["min_y"] <= y <= frame["max_y"]):
            return None
        abiotic = self.substrate.environment_at(x, y)
        inside = self.ecology.contains(x, y)
        raw = raw_ground_wetness(abiotic)
        ground = (
            f"{abiotic['elevation_m']:.1f} m · " + ("open water" if abiotic.get("open_water") else f"wetness {raw:.2f}")
        )
        floods = ""
        if not abiotic.get("open_water"):
            covered = abiotic.get("flood_return_period_years", FLOOD_NEVER_YEARS)
            reworked = abiotic.get(FLOOD_REWORKING_FIELD, FLOOD_NEVER_YEARS)
            if reworked < FLOOD_NEVER_YEARS:
                floods = f" · flooded every {self._years(covered)}, reworked every {self._years(reworked)}"
            elif covered < FLOOD_NEVER_YEARS:
                floods = f" · flooded every {self._years(covered)}"
        if inside:
            soil = self.soil.environment_at(x, y)
            effective = self.ecology.environment_at(x, y)
            if effective.get("moisture_retention_bonus", 0.0) >= 0.005 and not abiotic.get("open_water"):
                ground = (
                    f"{abiotic['elevation_m']:.1f} m · wetness {effective['soil_moisture']:.2f}"
                    f" ({effective.get('abiotic_soil_moisture', raw):.2f} + {effective['moisture_retention_bonus']:.2f} held by soil)"
                )
            ground += floods
            ground += (
                f" · soil organic {soil['soil_organic_matter_kg_m2']:.3f} kg/m²"
                f" · N {soil['available_nitrogen_g_m2']:.2f} P {soil['available_phosphorus_g_m2']:.2f} g/m²"
            )
        else:
            ground += floods + " · outside the living area"
        result = {"x": x, "y": y, "inside_domain": inside, "ground": ground, "species": None}
        if self.selected_species_id in self.ecology.profiles:
            diagnosis = self.diagnose(self.selected_species_id, x, y)
            # In the species' own terms: 60 % suits a lichen well and a tree barely.
            cover = self.ecology.expected_cover(self.ecology.profiles[self.selected_species_id], diagnosis["suitability"])
            verdict = "would thrive" if cover >= 0.6 else "would hold" if cover >= 0.2 else (
                "would barely hold" if cover > 0.0 else "would fail")
            result["species"] = (
                f"{diagnosis['label']} {verdict} here ({diagnosis['suitability']:.0%})"
                + ("" if cover >= 0.6 else f": {diagnosis['reason']}")
            )
            result["suitability"] = diagnosis["suitability"]
            result["cover"] = cover
            result["holds"] = cover > 0.0
        return result

    # ------------------------------------------------------------------
    # Isometric view
    # ------------------------------------------------------------------
    def _view_zoom_limits(self):
        low, high = self.VIEW_ZOOM_LIMITS
        if self.terrain_frame is not None:
            # Far enough out to read the landscape the domain sits in.
            frame_extent = max(self.terrain_frame["max_x"] - self.terrain_frame["min_x"],
                               self.terrain_frame["max_y"] - self.terrain_frame["min_y"])
            low = min(low, max(0.004, self.get_map_size() / max(1.0, min(frame_extent, 2000.0))))
        return low, high

    def _view_center(self):
        if isinstance(self.isometric_view_center, (tuple, list)) and len(self.isometric_view_center) >= 2:
            return float(self.isometric_view_center[0]), float(self.isometric_view_center[1])
        state = self._isometric_projection_state or {}
        if "center_x" in state:
            return float(state["center_x"]), float(state["center_y"])
        return (self.bounds["min_x"] + self.bounds["max_x"]) * 0.5, (self.bounds["min_y"] + self.bounds["max_y"]) * 0.5

    def _clamp_view_center(self, x, y):
        limit = self.terrain_frame or self.bounds
        return (max(limit["min_x"], min(limit["max_x"], float(x))),
                max(limit["min_y"], min(limit["max_y"], float(y))))

    def zoom_isometric_view(self, factor, screen_pos=None):
        """Zoom the builder view, keeping the ground under ``screen_pos`` in place."""
        low, high = self._view_zoom_limits()
        previous = float(self.isometric_view_zoom or 1.0)
        zoom = max(low, min(high, previous * float(factor)))
        if zoom == previous:
            return False
        state = self._isometric_projection_state
        if state and screen_pos is not None:
            # The ground point under the cursor, and where the centre must
            # move so that point is drawn under the cursor at the new scale.
            anchor_x, anchor_y = self._screen_to_world(None, screen_pos)
            scale = max(1e-9, float(state["scale"])) * zoom / previous
            a = (float(screen_pos[0]) - state["origin_x"]) / scale
            b = (float(screen_pos[1]) - state["origin_y"]) / (scale * 0.5)
            center_x, center_y = self._view_center()
            relief = self.substrate is not None and bool(state.get("generated"))
            vertical = float(state.get("vertical_scale", 1.0) or 1.0)
            anchor_z = self.substrate.elevation(anchor_x, anchor_y, True) if relief else 0.0
            for _ in range(4 if relief else 1):
                # The drawing plane follows the ground under the centre.
                lift = (anchor_z - self.substrate.elevation(center_x, center_y, True)) * vertical if relief else 0.0
                center_x, center_y = self._clamp_view_center(
                    anchor_x - (a + b + 2.0 * lift) * 0.5, anchor_y - (b + 2.0 * lift - a) * 0.5,
                )
            self.isometric_view_center = (center_x, center_y)
        self.isometric_view_zoom = zoom
        return True

    def reset_isometric_view(self):
        self.isometric_view_zoom = 1.0
        self.isometric_view_center = None
        return True

    def cycle_terrain_relief(self):
        scales = self.RELIEF_SCALES
        index = scales.index(self.terrain_vertical_scale) if self.terrain_vertical_scale in scales else 0
        self.terrain_vertical_scale = scales[(index + 1) % len(scales)]
        return True

    def _begin_camera_drag(self, screen_pos, camera):
        super()._begin_camera_drag(screen_pos, camera)
        self._isometric_drag_start_center = self._view_center()

    def _update_camera_drag(self, screen_pos, camera):
        """Dragging pans the isometric view; the Map camera is not what is drawn."""
        state = self._isometric_projection_state
        if not state or self._isometric_drag_start_center is None:
            return super()._update_camera_drag(screen_pos, camera)
        if not self.is_camera_dragging or self.camera_drag_start_screen_pos is None:
            return False
        dx = float(screen_pos[0]) - float(self.camera_drag_start_screen_pos[0])
        dy = float(screen_pos[1]) - float(self.camera_drag_start_screen_pos[1])
        if not self.camera_drag_has_moved:
            if dx * dx + dy * dy < self.CAMERA_DRAG_THRESHOLD_PX ** 2:
                return False
            self.camera_drag_has_moved = True
        scale = max(1e-9, float(state["scale"]))
        a, b = dx / scale, dy / (scale * 0.5)
        start_x, start_y = self._isometric_drag_start_center
        self.isometric_view_center = self._clamp_view_center(start_x - (a + b) * 0.5, start_y - (b - a) * 0.5)
        return True

    def handle_pointer_motion(self, event, camera, screen_pos):
        self._pointer_screen_pos = screen_pos
        if self.terrain_frame is not None:
            self._update_camera_drag(screen_pos, camera)
            return
        super().handle_pointer_motion(event, camera, screen_pos)

    def _load_species_profiles(self):
        species = list(self.world_model.get_dataset("species") or []) if hasattr(self.world_model, "get_dataset") else []
        from world.plant_catalogue import PlantCatalogue
        taxonomy = list(self.world_model.get_dataset("cladistics") or []) if hasattr(self.world_model,"get_dataset") else []
        fungi = PlantCatalogue.build({e["id"]:e for e in taxonomy+species if e.get("id")},root_id="cladis_fungi")
        plants = []
        for entity in species:
            entity_id = entity.get("id")
            is_plant = getattr(self.world_model, "is_plant_species", lambda _entity_id: bool(entity.get("plant_growth_form")))(entity_id)
            surface_lichen = (fungi.is_species(entity_id) and entity.get("plant_growth_form")=="lichen"
                              and entity.get("plant_growth_behaviour")=="surface_covering"
                              and bool(entity.get("surface_growth_profile")))
            if not is_plant and not surface_lichen and not entity.get("biosphere_bootstrap_species") and not entity.get("species_simulation_enabled"):
                continue
            resolved = getattr(self.world_model, "resolved_species_entity", lambda _entity_id: None)(entity_id) or entity
            plants.append(profile_from_entity(resolved))
        # The catalogue reads as a ladder: the bootstrap organism, then each
        # succession tier in turn.
        plants.sort(key=lambda profile: (
            profile.species_id != self.BIOMASSER_ID, profile.succession_tier,
            profile.growth_form not in {"lichen", "graminoid", "forb", "shrub", "tree", "aquatic"},
            profile.label.lower(),
        ))
        return plants

    def _default_species_id(self):
        preferred = (self.BIOMASSER_ID, "spec_lolium_perenne", "spec_codonorhiza_elandsmontana", "spec_betula_pendula")
        ids = {profile.species_id for profile in self.species_profiles}
        return next((species_id for species_id in preferred if species_id in ids), next(iter(ids), None))

    def pioneers_unlocked(self):
        return self.soil.support_fraction(SoilOrganicMatterField.requirement_for_tier(1)) > 0.0

    def is_species_unlocked(self, species_id):
        profile = self.ecology.profiles.get(species_id)
        if profile is None:
            return False
        if profile.growth_form == "aquatic":
            # Aquatic succession is parallel to terrestrial soil formation and
            # requires an imported hydrological substrate in this MWP.
            return self.substrate is not None
        return self.soil.support_fraction(profile.soil_organic_requirement_kg_m2) > 0.0

    def get_species_palette_items(self, limit=8):
        items = []
        visible_profiles = [profile for profile in self.species_profiles if self.is_species_unlocked(profile.species_id)]
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

    def cycle_seeding_brush(self):
        brushes = self.SEEDING_BRUSHES_M
        index = brushes.index(self.seeding_brush_m) if self.seeding_brush_m in brushes else 0
        self.seeding_brush_m = brushes[(index + 1) % len(brushes)]
        return True

    def get_seeding_brush_label(self):
        return "Sow by hand" if not self.seeding_brush_m else f"Sow {self.seeding_brush_m:g} m radius"

    def seeding_radius(self, profile):
        """Radius of the population one click introduces with the current tool."""
        if self.seeding_brush_m:
            return float(self.seeding_brush_m)
        radius_multiplier = {
            "tree": 3.2,
            "shrub": 2.3,
            "aquatic": 2.1,
            "graminoid": 1.6,
            "forb": 1.5,
        }.get(profile.growth_form, 1.0)
        return min(self.get_map_size() * 0.34, self.placement_radius_world * radius_multiplier)

    def get_seeding_preview(self):
        """Where a click would sow, for the cursor ring."""
        state = self._isometric_projection_state
        profile = self.ecology.profiles.get(self.selected_species_id)
        if not state or profile is None or self._pointer_screen_pos is None or self.species_picker_open:
            return None
        scene = state.get("scene_rect")
        if scene is not None and not scene.collidepoint(self._pointer_screen_pos):
            return None
        x, y = self._screen_to_world(None, self._pointer_screen_pos)
        return {"x": x, "y": y, "radius_m": self.seeding_radius(profile), "brush": bool(self.seeding_brush_m)}

    def _grow_domain_to(self, x, y, margin_m):
        """On generated terrain the domain follows the player's planting, within its limits."""
        if self.terrain_frame is None:
            return False
        frame = self.terrain_frame
        if not (frame["min_x"] <= x <= frame["max_x"] and frame["min_y"] <= y <= frame["max_y"]):
            return False
        if (self.bounds["min_x"] <= x - margin_m and x + margin_m <= self.bounds["max_x"]
                and self.bounds["min_y"] <= y - margin_m and y + margin_m <= self.bounds["max_y"]):
            return False
        grown = terrain_site.clamp_to_frame({
            "min_x": min(self.bounds["min_x"], x - margin_m), "max_x": max(self.bounds["max_x"], x + margin_m),
            "min_y": min(self.bounds["min_y"], y - margin_m), "max_y": max(self.bounds["max_y"], y + margin_m),
        }, frame)
        if max(grown["max_x"] - grown["min_x"], grown["max_y"] - grown["min_y"]) > self.maximum_extent_m:
            return False
        self._set_domain(grown)
        return True

    def _set_domain(self, bounds):
        previous = dict(self.ecology.bounds)
        self.ecology.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        self.bounds = dict(self.ecology.bounds)
        self.soil.resize_bounds(self.bounds)
        if self.terrain_frame is not None:
            self.soil.seed_abiotic_outside(self.ecology, previous)
            self._refresh_terrain_pending()
        if getattr(self, "resident_flora", None) is not None and self.bounds != previous:
            # The ground the living area has grown into comes with what already grows on it.
            self.resident_flora.settle(previous)
        self._invalidate_layer_cache()

    def place_selected_species(self, x, y, propagule_pressure=0.30):
        if not self.selected_species_id:
            return None
        profile = self.ecology.profiles[self.selected_species_id]
        if self.seeding_brush_m:
            # Sown over an area the stand starts thin; it thickens where it can.
            radius = float(self.seeding_brush_m)
            propagule_pressure = max(0.05, propagule_pressure * math.sqrt(2.0 / radius))
            self._grow_domain_to(x, y, radius + 2.0)
        else:
            self._grow_domain_to(x, y, max(2.0, self.placement_radius_world * 4.0))
            radius = self.seeding_radius(profile)
        introduction = self.ecology.introduce(self.selected_species_id, x, y, radius, propagule_pressure)
        if introduction is not None:
            self.representatives.sync_from_population(self.ecology)
            diagnosis = self.diagnose(self.selected_species_id, x, y)
            if not self.ecology.sustains(profile, diagnosis["suitability"]):
                self._note("warning", f"Introduced {self.short_label(profile.species_id)}; unlikely to hold: {diagnosis['reason']}")
            else:
                # A plant that takes years is said to: nothing will seem to happen for a while.
                slow = profile.maturity_days >= self.SLOW_MATURITY_DAYS
                self._note("plan", f"Introduced {self.short_label(profile.species_id)}"
                           + (f"; full size in about {describe_span(profile.maturity_days)}" if slow else ""))
        return introduction

    def advance_seasons(self, seasons=1):
        for _ in range(max(0, int(seasons))):
            before_centres = self._population_centres()
            before_pressures = self._population_pressures()
            before_extent = (self.bounds["max_x"] - self.bounds["min_x"], self.bounds["max_y"] - self.bounds["min_y"])
            self.last_representative_feedback = self.representatives.advance_season(self.ecology)
            self.ecology.advance(1, representative_feedback=self.last_representative_feedback)
            self._expand_if_population_reaches_edge()
            self.representatives.sync_from_population(self.ecology)
            self._record_season_outcomes(before_centres, before_extent, before_pressures)
        return self.ecology.summary()

    def _expand_if_population_reaches_edge(self):
        """Enlarge a procedural domain, never the fixed extent of a measured import."""
        if self.substrate is not None and self.terrain_frame is None:
            return False  # A measured import has a fixed, authoritative extent.
        # What already grew here stands at every rim; only what was brought in makes the living area grow.
        residents = self.resident_flora.species if self.resident_flora is not None else ()
        if self.get_map_size() >= self.maximum_extent_m or self.ecology.edge_abundance(ignore=residents) < 0.075:
            return False
        if self.terrain_frame is not None:
            # Generated terrain continues beyond the domain: grow into it, and
            # queue the chunks the new ground needs.  The root keeps the frame.
            previous = dict(self.ecology.bounds)
            self.ecology.expand(margin_cells=4, limit=self.terrain_frame)
            grown = dict(self.ecology.bounds)
            if grown == previous:
                return False
            self.ecology.bounds = previous
            self._set_domain(grown)
            return True
        self.ecology.expand(margin_cells=4)
        self.bounds = dict(self.ecology.bounds)
        self.soil.resize_bounds(self.bounds)
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
            moisture_high = min(1.0, waterlogging_limits(profile)[1])
            site_fit = self.get_species_climate_fit(profile.species_id)
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
                "unlock_label": (
                    "Available" if self.is_species_unlocked(profile.species_id)
                    else f"Requires {profile.soil_organic_requirement_kg_m2:.3f} kg/m² local organic matter"
                ),
                "site_fit": site_fit,
                "succession_tier": profile.succession_tier,
                "trait_lines": ([f"Site: {site_fit['label']}"] if site_fit else []) + [
                    f"Growth form: {profile.growth_form.title()}",
                    f"Seasonal growth: {profile.growth_rate:.2f}",
                    f"Dispersal: {profile.dispersal:.2f}",
                    f"Carrying biomass: {profile.carrying_biomass_kg_m2:.1f} kg/m²",
                    *life_timing_lines(profile.maturity_days, profile.maturity_source,
                                       profile.lifespan_days, profile.lifespan_source, seed_days_of(profile)),
                    f"Moisture niche: {moisture_low:.2f}–{moisture_high:.2f}",
                    f"Minimum light: {profile.light_minimum:.2f}",
                    f"Light source: {profile.light_requirement_source}",
                    f"Succession role: {', '.join(str(role).replace('_', ' ') for role in roles[:2]) or 'unresolved'}",
                    f"Succession tier: {profile.succession_tier} ({profile.succession_source})",
                    f"Organic matter required: {profile.soil_organic_requirement_kg_m2:.3f} kg/m²",
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
        soil = summary.get("soil") or self.soil.summary()
        representatives = self.representatives.summary()
        selected = self.ecology.profiles.get(self.selected_species_id)
        return {
            "title": "BIOSPHERE COMMAND",
            "biomass_kg": summary["living_biomass_kg"],
            "footprint_m2": summary["living_footprint_m2"],
            "species_count": len(summary["species"]),
            "representatives": representatives,
            "domain_m": (self.bounds["max_x"] - self.bounds["min_x"], self.bounds["max_y"] - self.bounds["min_y"]),
            "selected_species": self.short_label(selected.species_id) if selected else "None",
            "pioneers_unlocked": self.pioneers_unlocked(),
            "soil_organic_matter_kg_m2": soil["mean_soil_organic_matter_kg_m2"],
            "soil_organic_max_kg_m2": soil["max_soil_organic_matter_kg_m2"],
            "soil_stage": soil["soil_stage"],
            "supported_succession_tier": soil["supported_succession_tier"],
            "available_nitrogen_g_m2": soil["mean_available_nitrogen_g_m2"],
            "available_phosphorus_g_m2": soil["mean_available_phosphorus_g_m2"],
            "time": self.get_biosphere_time_state(),
            "terrain": self.get_terrain_status(),
            "field_notes": self.get_field_notes(8),
            "cursor": self.get_cursor_readout(),
            "seeding_brush": self.get_seeding_brush_label(),
            "populations": self.get_population_rows(),
            "view_scale": self.get_view_scale(),
        }

    def get_biosphere_builder_summary_lines(self):
        summary = self.ecology.summary()
        soil = summary.get("soil") or self.soil.summary()
        representative_summary = self.representatives.summary()
        selected = self.ecology.profiles.get(self.selected_species_id)
        founding = self.biosphere_context.get("founding_point_source")
        return [
            "Biological City Builder",
            f"Tool: introduce species | {'paused' if self.builder_paused else f'{self.builder_time_scale:g}× realtime'}",
            f"Selected: {selected.label if selected else 'none'}",
            f"Season {summary['season']} | introductions {summary['introductions']}",
            f"Living footprint {summary['living_footprint_m2']:.1f} m² | biomass {summary['living_biomass_kg']:.1f} kg",
            f"Soil organic matter {soil['mean_soil_organic_matter_kg_m2']:.3f} kg/m² mean | {soil['max_soil_organic_matter_kg_m2']:.3f} max",
            f"Plant-available N {soil['mean_available_nitrogen_g_m2']:.3f} g/m² | P {soil['mean_available_phosphorus_g_m2']:.3f} g/m²",
            f"Succession: {soil['soil_stage']} | supports tier {soil['supported_succession_tier']}",
            f"Active domain {self.bounds['max_x'] - self.bounds['min_x']:.0f} × {self.bounds['max_y'] - self.bounds['min_y']:.0f} m",
            f"Deep representatives {representative_summary['alive']} alive / {representative_summary['total']} total",
            "Herbaceous pioneers available" if self.pioneers_unlocked() else "Organic soil is still below the pioneer threshold",
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
                # A grass kept as individuals (a bamboo) is drawn as the plant it is, not as a sward symbol.
                "growth_form": ("structural_graminoid" if profile.growth_form == "graminoid"
                                and self.ecology.keeps_individuals(profile) else profile.growth_form),
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
            "plant_calyx_module_ref",
            "plant_stem_texture_set_ref", "plant_branch_texture_set_ref", "plant_bark_texture_set_ref",
        )
        for profile in self.species_profiles:
            entity = (
                getattr(self.world_model, "resolved_species_entity", lambda _species_id: None)(profile.species_id)
                or self.world_model.get_entity(profile.species_id)
                or {}
            )
            refs = [entity.get(field) for field in ref_fields if entity.get(field)]
            if any(asset_files.exists(Path(ref) if Path(ref).is_absolute() else project_root / Path(ref)) for ref in refs):
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
            self.representatives.set_maturity(representative, 0.72)
        self.test_forest_species_ids = list(species_ids)
        return list(species_ids)

    def _screen_to_world(self, camera, screen_pos):
        state = self._isometric_projection_state
        if state:
            if self.substrate is not None:
                return self.substrate.ground_screen_to_world(state, screen_pos)
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
        # Living organisms first: after some years the oldest serials are all
        # dead and would otherwise fill the whole list.
        values.sort(key=lambda item: (
            not item.alive,
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
                f"age: {describe_span(representative.age_days)} | health: {representative.health:.0%}",
                f"stage: {str((outcome.get('life_history') or {}).get('phase') or 'seedling').replace('_', ' ')}"
                f" | {float(outcome.get('maturity', 0.0)):.0%} of full size",
                f"condition: {float(outcome.get('vitality', 0.0)):.0%} | fecundity: {float(outcome.get('fecundity', 0.0)):.0%}",
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
            # Species Sim opens the body it grew: developmental days, not the organism's years.
            "age_days": representative.simulation.age_days,
            "real_age_days": representative.age_days,
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
                # By hand, clicking an organism inspects it.  With an area
                # tool the click is the sowing: stands are full of organisms.
                for representative_id, rect in reversed(self._representative_screen_hitboxes if not self.seeding_brush_m else ()):
                    if rect.collidepoint(screen_pos):
                        self.select_representative(representative_id)
                        return
                world_x, world_y = self._screen_to_world(camera, screen_pos)
                self.place_selected_species(world_x, world_y)
                return
        if self.terrain_frame is not None:
            # The Map base class would build and pick the region's flat map
            # layers, which this view never draws.
            if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE and button == 1:
                self._begin_camera_drag(screen_pos, camera)
            elif event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE and button == 3:
                # Right click inspects an organism whatever tool is in hand.
                for representative_id, rect in reversed(self._representative_screen_hitboxes):
                    if rect.collidepoint(screen_pos):
                        self.select_representative(representative_id)
                        break
            return
        super().handle_pointer_event(event, camera, screen_pos)

    def update(self, dt):
        super().update(dt)
        if self._advance_terrain_resolution():
            return
        if self.builder_paused:
            return
        self._season_accumulator += max(0.0, float(dt)) * self.builder_time_scale
        due = min(int(self._season_accumulator // self.seconds_per_season), self.MAX_SEASONS_PER_FRAME)
        if due > 0:
            self._season_accumulator = min(self._season_accumulator - due * self.seconds_per_season,
                                           self.seconds_per_season)
            self.advance_seasons(due)

    def consumes_global_escape(self):
        return self.species_picker_open

    def handle_event(self, event):
        if self.species_picker_open and event.type == self.KEYDOWN_EVENT_TYPE and getattr(event, "key", None) == 27:
            return self.close_species_picker()
        if event.type == self.MOUSEWHEEL_EVENT_TYPE and not self.species_picker_open:
            wheel = max(-6.0, min(6.0, float(getattr(event, "y", 0.0) or 0.0)))
            if wheel:
                return self.zoom_isometric_view(1.15 ** wheel, self._pointer_screen_pos)
        return super().handle_event(event)
