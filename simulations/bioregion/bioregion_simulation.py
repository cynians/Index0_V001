from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from engine.logger import logger
from simulations.bioregion.bioregion_grid import BioregionGrid
from simulations.bioregion.geology import GeologyGenerator
from simulations.bioregion.vegetation import VegetationController
from simulations.bioregion.water_cycle import WaterCycle
from simulations.bioregion.weather import WeatherController


class BioregionSimulation:
    """
    Prototype bioregion simulation.

    Current slice:
    * dedicated render mode
    * stable test-map bounds
    * section/subsection grid geometry
    * geology generation
      - soil
      - bedrock
      - altitude
      - z
    * cached derived terrain display layers
    * orchestration of:
      - grid state
      - weather
      - water cycle
      - vegetation
    """

    MAP_SIZE_M = 10000.0

    SECTIONS_PER_SIDE = 10
    SECTION_SIZE_M = 1000.0

    SUBSECTIONS_PER_SECTION_SIDE = 10
    SUBSECTION_SIZE_M = 100.0
    STARTER_SPECIES_IDS = [
        "spec_lecanora_muralis",
        "spec_morchella_esculenta",
        "spec_rosa_woodsii",
        "spec_cyperus_polystachyos",
        "spec_scirpus_sylvaticus",
        "spec_graphocephala_coccinea",
        "spec_anthrenus_verbasci",
        "spec_mantis_religiosa",
        "spec_lithobates_clamitans",
        "spec_passer_montanus",
        "spec_plantago_major",
    ]
    BIOSPHERE_SPECIES_ROSTER_FIELDS = [
        "microfauna_species",
        "small_animal_species",
        "medium_animal_species",
        "large_animal_species",
        "megafauna_species",
        "sessile_life_species",
    ]
    LEGACY_BIOSPHERE_SPECIES_ROSTER_FIELDS = [
        "plant_species",
    ]

    def __init__(self, world_model=None, biosphere_context=None, biosphere_id=None):
        class _DummySystem:
            def update(self, dt):
                pass

        self.render_mode = "bioregion"
        self.world_units_to_meters = 1.0
        self.world_model = world_model
        self.biosphere_context = dict(biosphere_context or {})
        self.species_collection_id = self.biosphere_context.get("species_collection_id")
        self.selected_species_ids = []
        self.worldgen_context = None
        self.biosphere_id = biosphere_id or self.biosphere_context.get("biosphere_id")
        self.biosphere_entity = self._get_entity(self.biosphere_id) if self.biosphere_id else None
        self.biosphere_shape_points = self._resolve_biosphere_shape_points()
        self.biosphere_width_m = float(self.biosphere_context.get("biosphere_width_m") or self.biosphere_context.get("map_size_m") or self.MAP_SIZE_M)
        self.biosphere_height_m = float(self.biosphere_context.get("biosphere_height_m") or self.biosphere_context.get("map_size_m") or self.MAP_SIZE_M)
        self.biosphere_area_m2 = float(self.biosphere_context.get("biosphere_area_m2") or 0.0)

        if self.biosphere_context:
            self.MAP_SIZE_M = max(
                0.01,
                float(self.biosphere_context.get("map_size_m") or max(self.biosphere_width_m, self.biosphere_height_m, 10.0)),
            )
            self.biosphere_width_m = max(0.01, self.biosphere_width_m)
            self.biosphere_height_m = max(0.01, self.biosphere_height_m)
            self.SECTIONS_PER_SIDE = 2
            self.SECTION_SIZE_M = self.MAP_SIZE_M / self.SECTIONS_PER_SIDE
            self.SUBSECTIONS_PER_SECTION_SIDE = 5
            self.SUBSECTION_SIZE_M = self.SECTION_SIZE_M / self.SUBSECTIONS_PER_SECTION_SIDE
            if not self.biosphere_shape_points:
                self.biosphere_shape_points = [
                    (0.0, 0.0),
                    (self.biosphere_width_m, 0.0),
                    (self.biosphere_width_m, self.biosphere_height_m),
                    (0.0, self.biosphere_height_m),
                ]
            if self.biosphere_area_m2 <= 0.0:
                self.biosphere_area_m2 = self._polygon_area(self.biosphere_shape_points)

        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 0.03
        self.max_zoom = 4.0
        self.preferred_zoom = 0.085

        self.bounds = {
            "min_x": 0.0,
            "max_x": self.biosphere_width_m if self.biosphere_context else self.MAP_SIZE_M,
            "min_y": 0.0,
            "max_y": self.biosphere_height_m if self.biosphere_context else self.MAP_SIZE_M,
        }

        self.grid = BioregionGrid(
            sections_per_side=self.SECTIONS_PER_SIDE,
            subsections_per_section_side=self.SUBSECTIONS_PER_SECTION_SIDE,
            section_size_m=self.SECTION_SIZE_M,
            subsection_size_m=self.SUBSECTION_SIZE_M,
        )
        self._apply_biosphere_shape_mask()

        self.geology = GeologyGenerator()
        self.geology.populate_grid(self.grid, seed=42)
        self.worldgen_context = self._resolve_worldgen_context()
        self._ensure_biosphere_soil_profiles()
        self._apply_worldgen_context_to_grid()
        self.grid.initialize_water_from_soil()
        self._apply_worldgen_water_context_to_grid()

        self.derived_map_layers = self.geology.build_default_map_layers(
            self.grid,
            z_band_size=0.1,
        )

        self.weather = WeatherController(
            rain_check_period_seconds=900.0,
            rain_chance_per_check=0.18,
            rain_duration_seconds=1200.0,
            rain_rate=0.00035,
            start_raining=True,
        )

        self.water_cycle = WaterCycle(
            deep_background_loss_rate=0.000003
        )

        self.vegetation = VegetationController()
        self.vegetation.seed_grid(self.grid)
        self.available_species = self._load_available_species()
        self.species_suitability = self._build_species_suitability_summary()

        self.hover_cell = None
        self.selected_cell = None
        self.hover_screen_pos = None

        logger.info("[BioregionSimulation] Initialized prototype bioregion simulation")
        logger.info(
            "[BioregionSimulation] Starting with immediate rain event "
            f"(duration={self.weather.rain_duration_seconds:.1f}s, "
            f"rate={self.weather.rain_rate:.6f})"
        )
        logger.info(
            "[BioregionSimulation] Derived map layers built | "
            f"height_outline_segments="
            f"{len(self.derived_map_layers.get('height_outline_segments', []))}"
        )

    @property
    def year(self):
        try:
            return int(self.biosphere_context.get("year", 2400))
        except (TypeError, ValueError):
            return 2400

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

    def _get_entity(self, entity_id):
        if self.world_model is None or not entity_id:
            return None
        try:
            entity = self.world_model.get_entity(entity_id)
        except AttributeError:
            return None
        return entity if isinstance(entity, dict) else None

    def _entity_parent_ids(self, entity):
        parent_ids = []
        if not isinstance(entity, dict):
            return parent_ids
        for field_name in ("parent_location", "parent_entity", "parent", "parents"):
            for parent_id in self._relation_ids(entity.get(field_name)):
                if parent_id not in parent_ids:
                    parent_ids.append(parent_id)
        return parent_ids

    def _has_worldgen_context(self, entity):
        if not isinstance(entity, dict):
            return False
        for field_name in (
            "heightmap_model",
            "hydrology_summary",
            "environment_summary",
            "water_cycle_model",
            "koppen_climate_model",
            "river_model",
            "climate_summary",
            "materials_summary",
            "natural_material_model",
            "material_heatmap_model",
            "regolith_soil_model",
            "ocean_circulation_model",
            "cryosphere_model",
            "surface_evolution_model",
            "true_color_model",
        ):
            if isinstance(entity.get(field_name), dict):
                return True
        if entity.get("natural_materials"):
            return True
        return False

    def _resolve_worldgen_context(self):
        if (not self.biosphere_context and self.biosphere_entity is None) or self.world_model is None:
            return None

        start_ids = []
        if isinstance(self.biosphere_entity, dict):
            for entity_id in self._relation_ids(self.biosphere_entity.get("overlay_location")):
                if entity_id not in start_ids:
                    start_ids.append(entity_id)
        for field_name in ("patch_location_id", "parent_location_id", "root_location_id"):
            entity_id = self.biosphere_context.get(field_name)
            if entity_id and entity_id not in start_ids:
                start_ids.append(entity_id)

        queue = list(start_ids)
        visited = set()
        fallback = None
        while queue:
            entity_id = queue.pop(0)
            if entity_id in visited:
                continue
            visited.add(entity_id)
            entity = self._get_entity(entity_id)
            if not isinstance(entity, dict):
                continue
            if self._has_worldgen_context(entity):
                context = {
                    "source_entity_id": entity_id,
                    "source_name": entity.get("pretty_name") or entity.get("name") or entity_id,
                    "source_entity": entity,
                    "heightmap": entity.get("heightmap_model") if isinstance(entity.get("heightmap_model"), dict) else None,
                    "hydrology": entity.get("hydrology_summary") if isinstance(entity.get("hydrology_summary"), dict) else None,
                    "environment": entity.get("environment_summary") if isinstance(entity.get("environment_summary"), dict) else None,
                    "water_cycle": entity.get("water_cycle_model") if isinstance(entity.get("water_cycle_model"), dict) else None,
                    "koppen_climate": entity.get("koppen_climate_model") if isinstance(entity.get("koppen_climate_model"), dict) else None,
                    "rivers": entity.get("river_model") if isinstance(entity.get("river_model"), dict) else None,
                    "climate_summary": entity.get("climate_summary") if isinstance(entity.get("climate_summary"), dict) else None,
                    "materials": entity.get("natural_material_model") if isinstance(entity.get("natural_material_model"), dict) else None,
                    "materials_summary": entity.get("materials_summary") if isinstance(entity.get("materials_summary"), dict) else None,
                    "material_heatmap": entity.get("material_heatmap_model") if isinstance(entity.get("material_heatmap_model"), dict) else None,
                    "regolith_soil": entity.get("regolith_soil_model") if isinstance(entity.get("regolith_soil_model"), dict) else None,
                    "ocean_circulation": entity.get("ocean_circulation_model") if isinstance(entity.get("ocean_circulation_model"), dict) else None,
                    "cryosphere": entity.get("cryosphere_model") if isinstance(entity.get("cryosphere_model"), dict) else None,
                    "surface_evolution": entity.get("surface_evolution_model") if isinstance(entity.get("surface_evolution_model"), dict) else None,
                    "true_color": entity.get("true_color_model") if isinstance(entity.get("true_color_model"), dict) else None,
                }
                if context["heightmap"] is not None:
                    return context
                if fallback is None:
                    fallback = context
            queue.extend([
                parent_id for parent_id in self._entity_parent_ids(entity)
                if parent_id not in visited and parent_id not in queue
            ])
        return fallback

    def _clamp(self, value, low=0.0, high=1.0):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = low
        return max(low, min(high, numeric))

    def _resolve_biosphere_shape_points(self):
        shape = self.biosphere_context.get("biosphere_shape")
        if not isinstance(shape, dict):
            return []
        points = shape.get("points")
        if not isinstance(points, (list, tuple)):
            return []
        parsed = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                parsed.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        return parsed

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

    def _point_in_biosphere_shape(self, x, y):
        points = self.biosphere_shape_points
        if len(points) < 3:
            return True
        inside = False
        previous_x, previous_y = points[-1]
        for current_x, current_y in points:
            intersects = ((current_y > y) != (previous_y > y))
            if intersects:
                denominator = previous_y - current_y
                if abs(denominator) < 1e-9:
                    denominator = 1e-9
                crossing_x = (previous_x - current_x) * (y - current_y) / denominator + current_x
                if x <= crossing_x:
                    inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside

    def _apply_biosphere_shape_mask(self):
        if not self.biosphere_context or len(self.biosphere_shape_points) < 3:
            return
        for cell in self.grid.iter_cells(include_inactive=True):
            center_x = (cell["min_x"] + cell["max_x"]) * 0.5
            center_y = (cell["min_y"] + cell["max_y"]) * 0.5
            cell["active"] = self._point_in_biosphere_shape(center_x, center_y)

    def _source_bounds_points(self):
        source_bounds = self.biosphere_context.get("source_bounds")
        if not isinstance(source_bounds, dict):
            source_bounds = self.biosphere_context.get("bounds")
        if not isinstance(source_bounds, dict):
            return []
        if source_bounds.get("type") == "bbox":
            return [
                (source_bounds.get("min_x", 0.0), source_bounds.get("min_y", 0.0)),
                (source_bounds.get("max_x", 0.0), source_bounds.get("min_y", 0.0)),
                (source_bounds.get("max_x", 0.0), source_bounds.get("max_y", 0.0)),
                (source_bounds.get("min_x", 0.0), source_bounds.get("max_y", 0.0)),
            ]
        points = source_bounds.get("points")
        if not isinstance(points, (list, tuple)):
            return []
        parsed = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                parsed.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        return parsed

    def _points_bbox(self, points, fallback=None):
        if not points:
            return dict(fallback or {"min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0})
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
        }

    def _source_entity_bbox(self):
        entity = (self.worldgen_context or {}).get("source_entity")
        bounds = entity.get("bounds") if isinstance(entity, dict) else None
        if isinstance(bounds, dict) and bounds.get("type") == "bbox":
            return {
                "min_x": float(bounds.get("min_x", -180.0)),
                "max_x": float(bounds.get("max_x", 180.0)),
                "min_y": float(bounds.get("min_y", -90.0)),
                "max_y": float(bounds.get("max_y", 90.0)),
            }
        if isinstance(bounds, dict) and isinstance(bounds.get("points"), (list, tuple)):
            return self._points_bbox([
                (float(point[0]), float(point[1]))
                for point in bounds.get("points")
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ])
        return {"min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0}

    def _cell_source_point(self, cell, patch_bbox):
        map_u = (cell["min_x"] + cell["max_x"]) * 0.5 / max(0.0001, self.MAP_SIZE_M)
        map_v = (cell["min_y"] + cell["max_y"]) * 0.5 / max(0.0001, self.MAP_SIZE_M)
        span_x = patch_bbox["max_x"] - patch_bbox["min_x"]
        span_y = patch_bbox["max_y"] - patch_bbox["min_y"]
        return (
            patch_bbox["min_x"] + span_x * map_u,
            patch_bbox["min_y"] + span_y * map_v,
        )

    def _normalise_source_point(self, x, y):
        bbox = self._source_entity_bbox()
        span_x = bbox["max_x"] - bbox["min_x"]
        span_y = bbox["max_y"] - bbox["min_y"]
        nx = 0.5 if abs(span_x) < 0.0001 else (x - bbox["min_x"]) / span_x
        ny = 0.5 if abs(span_y) < 0.0001 else (y - bbox["min_y"]) / span_y
        return self._clamp(nx), self._clamp(ny)

    def _heightmap_rows(self, heightmap):
        sample_grid = heightmap.get("sample_grid") if isinstance(heightmap, dict) else None
        rows = sample_grid.get("rows") if isinstance(sample_grid, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
            return []
        return rows

    def _bilinear_sample_rows(self, rows, nx, ny):
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
            return None
        height = len(rows)
        width = min(len(row) for row in rows if isinstance(row, list))
        if width <= 0:
            return None
        nx = self._clamp(nx)
        ny = self._clamp(ny)
        x = nx * max(0, width - 1)
        y = ny * max(0, height - 1)
        x0 = int(x)
        y0 = int(y)
        x1 = min(width - 1, x0 + 1)
        y1 = min(height - 1, y0 + 1)
        fx = x - x0
        fy = y - y0

        def value_at(row, col):
            try:
                return float(rows[row][col])
            except (TypeError, ValueError, IndexError):
                return 0.0

        top = value_at(y0, x0) * (1.0 - fx) + value_at(y0, x1) * fx
        bottom = value_at(y1, x0) * (1.0 - fx) + value_at(y1, x1) * fx
        return top * (1.0 - fy) + bottom * fy

    def _sample_heightmap(self, heightmap, nx, ny):
        return self._bilinear_sample_rows(self._heightmap_rows(heightmap), nx, ny)

    def _sample_koppen_class(self, nx, ny):
        context = self.worldgen_context or {}
        climate_model = context.get("koppen_climate") if isinstance(context.get("koppen_climate"), dict) else {}
        water_cycle = context.get("water_cycle") if isinstance(context.get("water_cycle"), dict) else {}
        grid = climate_model.get("climate_grid") if isinstance(climate_model.get("climate_grid"), dict) else None
        if grid is None:
            grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else None
        rows = []
        if isinstance(grid, dict):
            rows = grid.get("koppen_rows") or grid.get("rows") or []
        if not rows:
            return None
        valid_rows = [row for row in rows if isinstance(row, list) and row]
        if not valid_rows:
            return None
        width = min(len(row) for row in valid_rows)
        if width <= 0:
            return None
        x = int(round(self._clamp(nx) * (width - 1))) % width
        y = int(round(self._clamp(ny) * (len(rows) - 1)))
        y = max(0, min(len(rows) - 1, y))
        row = rows[y]
        if not isinstance(row, list) or x >= len(row):
            return None
        return row[x]

    def _material_ids_for_worldgen_context(self):
        context = self.worldgen_context or {}
        material_ids = []
        materials_summary = context.get("materials_summary") if isinstance(context.get("materials_summary"), dict) else {}
        material_ids.extend(materials_summary.get("dominant_materials") or [])
        materials = context.get("materials") if isinstance(context.get("materials"), dict) else {}
        material_ids.extend(materials.get("dominant_materials") or [])
        for item in materials.get("likely_materials") or []:
            if isinstance(item, dict) and item.get("material_id"):
                material_ids.append(item["material_id"])
        source = context.get("source_entity") if isinstance(context.get("source_entity"), dict) else {}
        material_ids.extend(source.get("natural_materials") or [])
        return [str(material_id).lower() for material_id in material_ids if material_id]

    def _worldgen_bedrock_type(self, material_ids):
        text = " ".join(material_ids)
        if any(token in text for token in ("basalt", "olivine", "pyroxene", "ilmenite", "magnetite")):
            return "basalt"
        if any(token in text for token in ("limestone", "calcite", "carbonate")):
            return "limestone"
        if any(token in text for token in ("shale", "mudstone", "clay")):
            return "shale"
        if any(token in text for token in ("sandstone", "quartz", "regolith", "silica", "sand")):
            return "sandstone"
        if any(token in text for token in ("granite", "feldspar", "mica")):
            return "granite"
        return None

    def _patch_center_normalised_point(self):
        patch_bbox = self._points_bbox(self._source_bounds_points())
        if patch_bbox["min_x"] == patch_bbox["max_x"] or patch_bbox["min_y"] == patch_bbox["max_y"]:
            patch_bbox = self._source_entity_bbox()
        center_x = (patch_bbox["min_x"] + patch_bbox["max_x"]) / 2.0
        center_y = (patch_bbox["min_y"] + patch_bbox["max_y"]) / 2.0
        return self._normalise_source_point(center_x, center_y)

    def _drainage_label(self, relative_permeability):
        if relative_permeability is None:
            return None
        if relative_permeability < 0.3:
            return "poor"
        if relative_permeability < 0.6:
            return "moderate"
        return "well_drained"

    def _generate_area_soil_profile(self):
        """
        First-pass soil profile from the corrected worldgen bridge.

        Biology (organic layer, nutrients, microbial activity, compaction) is
        deliberately left None -- regolith_soils.py self-labels its output
        "biosphere_contribution": "excluded_pending_separate_design", so those
        fields stay visibly unresolved until a later plant/soil co-development
        pass actually generates them, rather than guessing.
        """
        context = self.worldgen_context or {}
        regolith = context.get("regolith_soil") or {}
        grid = regolith.get("grid") if isinstance(regolith.get("grid"), dict) else {}
        nx, ny = self._patch_center_normalised_point()

        soil_depth_m = self._bilinear_sample_rows(grid.get("soil_depth_m_rows"), nx, ny)
        porosity = self._bilinear_sample_rows(grid.get("porosity_rows"), nx, ny)
        permeability = self._bilinear_sample_rows(grid.get("relative_permeability_rows"), nx, ny)
        ph = self._bilinear_sample_rows(grid.get("ph_rows"), nx, ny)
        salinity = self._bilinear_sample_rows(grid.get("salinity_index_rows"), nx, ny)

        surface_evolution = context.get("surface_evolution") or {}
        process_grid = surface_evolution.get("process_grid") if isinstance(surface_evolution.get("process_grid"), dict) else {}
        erosion = self._bilinear_sample_rows(process_grid.get("erosion_intensity_rows"), nx, ny)

        dominant_classes = regolith.get("dominant_soil_classes") if isinstance(regolith.get("dominant_soil_classes"), list) else []
        parent_material = None
        if dominant_classes and isinstance(dominant_classes[0], dict):
            parent_material = dominant_classes[0].get("id")
        if not parent_material:
            parent_material = self._worldgen_bedrock_type(self._material_ids_for_worldgen_context()) or "unresolved_regolith"

        if soil_depth_m is None:
            return {
                "generated_from": "geology_heuristic_fallback",
                "organic_layer": None,
                "topsoil": None,
                "subsoil": None,
                "parent_material": parent_material,
                "moisture_capacity": None,
                "ph": None,
                "salinity": None,
                "nutrients": None,
                "microbial_activity": None,
                "drainage": None,
                "compaction": None,
                "erosion_risk": None,
                "root_depth_constraints": None,
            }

        return {
            "generated_from": "regolith_soil_model",
            "organic_layer": None,
            "topsoil": round(soil_depth_m * 0.3, 3),
            "subsoil": round(soil_depth_m * 0.7, 3),
            "parent_material": parent_material,
            "moisture_capacity": round(porosity, 3) if porosity is not None else None,
            "ph": round(ph, 2) if ph is not None else None,
            "salinity": round(salinity, 3) if salinity is not None else None,
            "nutrients": None,
            "microbial_activity": None,
            "drainage": self._drainage_label(permeability),
            "compaction": None,
            "erosion_risk": round(erosion, 3) if erosion is not None else None,
            "root_depth_constraints": round(min(soil_depth_m, 3.0), 3),
        }

    def _ensure_biosphere_soil_profiles(self):
        """
        Generate area/biosphere soil profiles once and stage the write onto
        the durable entity. Staged only (world_model.set_literal), never
        auto-saved -- durability still requires the user's explicit Save.
        """
        if not isinstance(self.biosphere_entity, dict) or self.world_model is None:
            return
        biosphere_id = self.biosphere_entity.get("id")
        if not biosphere_id:
            return

        area_profile = self.biosphere_entity.get("area_soil_profile")
        if not isinstance(area_profile, dict) or not area_profile:
            area_profile = self._generate_area_soil_profile()
            self.biosphere_entity["area_soil_profile"] = area_profile
            try:
                self.world_model.set_literal(biosphere_id, "area_soil_profile", area_profile, persist=True)
            except AttributeError:
                pass

        biosphere_profile = self.biosphere_entity.get("biosphere_soil_profile")
        if not isinstance(biosphere_profile, dict) or not biosphere_profile:
            biosphere_profile = dict(area_profile)
            biosphere_profile["generated_from"] = "area_soil_profile_baseline"
            self.biosphere_entity["biosphere_soil_profile"] = biosphere_profile
            try:
                self.world_model.set_literal(biosphere_id, "biosphere_soil_profile", biosphere_profile, persist=True)
            except AttributeError:
                pass

    def _worldgen_soil_type(self, material_ids, is_under_water, elevation_norm):
        text = " ".join(material_ids)
        hydrology = (self.worldgen_context or {}).get("hydrology") or {}
        environment = (self.worldgen_context or {}).get("environment") or {}
        tags = " ".join(str(tag).lower() for tag in environment.get("tags", []) if tag)
        liquid_water_possible = hydrology.get("liquid_water_possible")
        water_absent = liquid_water_possible is False or hydrology.get("cycle") == "none"
        if is_under_water or "clay" in text or "wet" in tags:
            return "heavy_clay" if elevation_norm < 0.25 else "clay_loam"
        if "sand" in text or "regolith" in text or "arid" in tags or water_absent:
            return "very_sandy" if elevation_norm > 0.55 else "sandy_loam"
        if elevation_norm < 0.30:
            return "clay_loam"
        if elevation_norm > 0.75:
            return "sandy_loam"
        return "loam"

    def _apply_worldgen_context_to_grid(self):
        if not self.worldgen_context:
            return
        heightmap = self.worldgen_context.get("heightmap")
        material_ids = self._material_ids_for_worldgen_context()
        bedrock_type = self._worldgen_bedrock_type(material_ids)
        patch_bbox = self._points_bbox(self._source_bounds_points())
        if patch_bbox["min_x"] == patch_bbox["max_x"] or patch_bbox["min_y"] == patch_bbox["max_y"]:
            patch_bbox = self._source_entity_bbox()

        min_elevation = None
        max_elevation = None
        sea_level = None
        if isinstance(heightmap, dict):
            rows = self._heightmap_rows(heightmap)
            values = [float(value) for row in rows for value in row if isinstance(value, (int, float))]
            if values:
                min_elevation = float(heightmap.get("min_elevation_m", min(values)))
                max_elevation = float(heightmap.get("max_elevation_m", max(values)))
            try:
                sea_level = float(heightmap.get("sea_level_m"))
            except (TypeError, ValueError):
                sea_level = None

        for cell in self.grid.iter_cells():
            elevation = None
            source_x, source_y = self._cell_source_point(cell, patch_bbox)
            nx, ny = self._normalise_source_point(source_x, source_y)
            if isinstance(heightmap, dict):
                elevation = self._sample_heightmap(heightmap, nx, ny)
            if elevation is not None and min_elevation is not None and max_elevation is not None:
                elevation_norm = self._clamp(
                    (elevation - min_elevation) / max(1.0, max_elevation - min_elevation)
                )
                cell["elevation_m"] = round(elevation, 3)
                cell["altitude"] = elevation_norm
                cell["z"] = elevation_norm
            else:
                elevation_norm = self._clamp(cell.get("altitude", 0.5))

            is_under_water = elevation is not None and sea_level is not None and elevation < sea_level
            koppen_class = self._sample_koppen_class(nx, ny)
            if koppen_class:
                cell["koppen_class"] = koppen_class
                if koppen_class in {"BWh", "BWk", "BSh", "BSk"}:
                    cell["top_moisture"] = self._clamp(cell["top_moisture"] * 0.72)
                    cell["deep_moisture"] = self._clamp(cell["deep_moisture"] * 0.84)
                elif koppen_class in {"Af", "Am", "Cfa", "Cfb", "Cfc", "Cwa", "Cwb", "Cwc", "Dfa", "Dfb", "Dwa", "Dwb"}:
                    cell["top_moisture"] = self._clamp(cell["top_moisture"] + 0.14)
                    cell["deep_moisture"] = self._clamp(cell["deep_moisture"] + 0.10)
                elif koppen_class in {"ET", "EF"}:
                    cell["top_temperature"] = self._clamp(cell.get("top_temperature", 0.5) * 0.82)
            if bedrock_type:
                cell["bedrock_type"] = bedrock_type
            cell["soil_type"] = self._worldgen_soil_type(material_ids, is_under_water, elevation_norm)
            cell["worldgen_source_entity_id"] = self.worldgen_context.get("source_entity_id")

    def _apply_worldgen_water_context_to_grid(self):
        if not self.worldgen_context:
            return
        hydrology = self.worldgen_context.get("hydrology") if isinstance(self.worldgen_context.get("hydrology"), dict) else {}
        environment = self.worldgen_context.get("environment") if isinstance(self.worldgen_context.get("environment"), dict) else {}
        tags = " ".join(str(tag).lower() for tag in environment.get("tags", []) if tag)
        active_water = bool(hydrology.get("liquid_water_possible")) or hydrology.get("cycle") == "active"
        dry_world = (
            "arid" in tags
            or "airless" in tags
            or hydrology.get("cycle") == "none"
            or hydrology.get("liquid_water_possible") is False
        )
        for cell in self.grid.iter_cells():
            elevation = cell.get("elevation_m")
            sea_level = None
            heightmap = self.worldgen_context.get("heightmap")
            if isinstance(heightmap, dict):
                try:
                    sea_level = float(heightmap.get("sea_level_m"))
                except (TypeError, ValueError):
                    sea_level = None
            if elevation is not None and sea_level is not None and elevation < sea_level:
                cell["surface_water"] = max(cell["surface_water"], 0.45)
                cell["top_moisture"] = max(cell["top_moisture"], 0.72)
                cell["deep_moisture"] = max(cell["deep_moisture"], 0.82)
                cell["habitat_type"] = "shallow_water"
            elif active_water and not dry_world:
                wetness = 1.0 - self._clamp(cell.get("altitude", 0.5))
                cell["top_moisture"] = self._clamp(cell["top_moisture"] + wetness * 0.12)
                cell["deep_moisture"] = self._clamp(cell["deep_moisture"] + wetness * 0.10)
            elif dry_world:
                cell["surface_water"] = 0.0
                cell["top_moisture"] = self._clamp(cell["top_moisture"] * 0.45)
                cell["deep_moisture"] = self._clamp(cell["deep_moisture"] * 0.62)

    def _species_label(self, entity, fallback_id):
        if not isinstance(entity, dict):
            return fallback_id
        common = str(entity.get("common_name") or "").strip()
        binomial = str(entity.get("binomial_name") or "").strip()
        if common and binomial and binomial.lower() not in common.lower():
            return f"{common} - {binomial}"
        return common or binomial or entity.get("pretty_name") or entity.get("name") or fallback_id

    def _load_available_species(self):
        if self.world_model is None:
            return [
                {"id": species_id, "label": species_id}
                for species_id in self.STARTER_SPECIES_IDS
            ]

        species_ids = []
        # A durable Biosphere entity carries its own roster buckets directly
        # (see tools/author_biosphere_model.py) -- prefer that over the older
        # ephemeral species-roster collection when both are available.
        roster_source = self.biosphere_entity
        if not isinstance(roster_source, dict):
            roster_source = (
                self.world_model.get_entity(self.species_collection_id)
                if self.species_collection_id
                else None
            )
        if isinstance(roster_source, dict):
            for field_name in self.BIOSPHERE_SPECIES_ROSTER_FIELDS:
                species_ids.extend(self._relation_ids(roster_source.get(field_name)))
            for field_name in self.LEGACY_BIOSPHERE_SPECIES_ROSTER_FIELDS:
                species_ids.extend(self._relation_ids(roster_source.get(field_name)))
            if not species_ids:
                species_ids.extend(self._relation_ids(roster_source.get("includes")))
                species_ids.extend(self._relation_ids(roster_source.get("featured_entries")))

        if not species_ids and not isinstance(roster_source, dict):
            species_ids = list(self.STARTER_SPECIES_IDS)

        entries = []
        seen = set()
        for species_id in species_ids:
            if species_id in seen:
                continue
            seen.add(species_id)
            entity = self.world_model.get_entity(species_id)
            if not isinstance(entity, dict):
                continue
            entries.append({
                "id": species_id,
                "label": self._species_label(entity, species_id),
                "entity": entity,
            })
        return entries

    def get_scope_label(self):
        if self.biosphere_context:
            patch_name = self.biosphere_context.get("patch_name") or "Biosphere Patch"
            return f"{patch_name} | 10 m x 10 m"
        return "Bioregion Test Map | 10 km x 10 km"

    def get_bioregion_hierarchy_breadcrumb(self):
        """Walk parent_biosphere links from the current Biosphere entity upward."""
        if not isinstance(self.biosphere_entity, dict):
            return ""
        names = []
        visited = set()
        current = self.biosphere_entity
        while isinstance(current, dict):
            entity_id = current.get("id")
            if not entity_id or entity_id in visited:
                break
            visited.add(entity_id)
            names.append(current.get("pretty_name") or current.get("name") or entity_id)
            parent_ids = self._relation_ids(current.get("parent_biosphere"))
            current = self._get_entity(parent_ids[0]) if parent_ids else None
        return " > ".join(reversed(names))

    def get_scope_breadcrumb(self):
        if not self.biosphere_context:
            return ""
        root_name = self.biosphere_context.get("root_name") or self.biosphere_context.get("root_location_id")
        patch_name = self.biosphere_context.get("patch_name") or self.biosphere_context.get("patch_location_id")
        source_name = (self.worldgen_context or {}).get("source_name")
        hierarchy = self.get_bioregion_hierarchy_breadcrumb()
        if hierarchy and " > " in hierarchy:
            breadcrumb = hierarchy
        elif root_name and patch_name:
            breadcrumb = f"{root_name} > {patch_name}"
        else:
            breadcrumb = str(patch_name or root_name or "")
        if source_name:
            return f"{breadcrumb} | terrain from {source_name}"
        return breadcrumb

    def get_species_catalog_entries(self):
        selected = set(self.selected_species_ids)
        return [
            {
                "id": entry["id"],
                "label": entry["label"],
                "selected": entry["id"] in selected,
                "suitability": self.species_suitability.get(entry["id"], {}).get("average_suitability"),
            }
            for entry in self.available_species
        ]

    def toggle_species_selection(self, species_id):
        species_id = str(species_id or "")
        if not any(entry.get("id") == species_id for entry in self.available_species):
            return False
        if species_id in self.selected_species_ids:
            self.selected_species_ids = [
                selected_id for selected_id in self.selected_species_ids
                if selected_id != species_id
            ]
        else:
            self.selected_species_ids.append(species_id)
        return True

    def get_selected_species_count(self):
        return len(self.selected_species_ids)

    def _range_score(self, value, tolerance):
        if not isinstance(tolerance, dict):
            return 1.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 1.0
        minimum = tolerance.get("min")
        maximum = tolerance.get("max")
        optimum = tolerance.get("optimum")
        try:
            minimum = float(minimum) if minimum is not None else None
            maximum = float(maximum) if maximum is not None else None
        except (TypeError, ValueError):
            minimum = None
            maximum = None
        if minimum is not None and numeric < minimum:
            span = max(1.0, (maximum if maximum is not None else minimum + 1.0) - minimum)
            return self._clamp(1.0 - ((minimum - numeric) / span))
        if maximum is not None and numeric > maximum:
            span = max(1.0, maximum - (minimum if minimum is not None else maximum - 1.0))
            return self._clamp(1.0 - ((numeric - maximum) / span))
        if optimum is None:
            return 1.0
        try:
            optimum = float(optimum)
        except (TypeError, ValueError):
            return 1.0
        span = max(1.0, (maximum if maximum is not None else optimum + 1.0) - (minimum if minimum is not None else optimum - 1.0))
        return self._clamp(1.0 - abs(numeric - optimum) / span)

    def _list_match_score(self, value, accepted_values):
        if not accepted_values:
            return 1.0
        value = str(value or "").strip().lower()
        accepted = {str(item or "").strip().lower() for item in accepted_values if str(item or "").strip()}
        if not accepted:
            return 1.0
        return 1.0 if value in accepted else 0.35

    def _species_entity_profile(self, entry):
        entity = entry.get("entity") if isinstance(entry, dict) else None
        if not isinstance(entity, dict):
            return {}
        profile = entity.get("worldgen_suitability_profile")
        return profile if isinstance(profile, dict) else {}

    def _cell_disturbance_tags(self, cell):
        tags = set()
        if str(cell.get("soil_type")) in {"very_sandy", "sandy_loam"}:
            tags.add("low_soil_development")
        if cell.get("surface_water", 0.0) > 0.28:
            tags.add("flooding")
        if cell.get("altitude", 0.5) > 0.82:
            tags.add("exposure")
        return tags

    def _score_species_for_cell(self, species_entry, cell):
        profile = self._species_entity_profile(species_entry)
        if not profile:
            return None

        scores = []
        moisture = (cell.get("top_moisture", 0.0) * 0.70) + (cell.get("deep_moisture", 0.0) * 0.30)
        scores.append(self._range_score(moisture, profile.get("moisture")))
        scores.append(self._range_score(cell.get("elevation_m"), profile.get("elevation_m")))
        scores.append(self._list_match_score(cell.get("soil_type"), profile.get("soil_types")))

        if cell.get("surface_water", 0.0) > 0.30 and not profile.get("tolerates_flooding", False):
            scores.append(0.25)
        disturbance_tags = set(profile.get("disturbance_affinities") or [])
        cell_disturbance = self._cell_disturbance_tags(cell)
        if disturbance_tags and cell_disturbance:
            scores.append(1.0 if disturbance_tags & cell_disturbance else 0.78)

        return self._clamp(sum(scores) / max(1, len(scores)))

    def _build_species_suitability_summary(self):
        summary = {}
        for entry in getattr(self, "available_species", []):
            scores = [
                score
                for cell in self.grid.iter_cells()
                for score in [self._score_species_for_cell(entry, cell)]
                if score is not None
            ]
            if not scores:
                continue
            summary[entry["id"]] = {
                "average_suitability": round(sum(scores) / len(scores), 3),
                "best_cell_suitability": round(max(scores), 3),
                "suitable_cell_fraction": round(sum(score >= 0.62 for score in scores) / len(scores), 3),
            }
        return summary

    def update(self, dt):
        self.sim_manager.update(dt)
        self.weather.update(dt)
        self.water_cycle.update_grid(
            grid=self.grid,
            dt=dt,
            rain_input_rate=self.weather.get_rain_input_rate(),
        )
        self.vegetation.update_grid(
            grid=self.grid,
            dt=dt,
        )
        self._log_environment_summary()

    def get_center(self):
        return self.MAP_SIZE_M / 2.0, self.MAP_SIZE_M / 2.0

    def get_height_outline_segments(self):
        """
        Return cached contour-like height outline segments.
        """
        return self.derived_map_layers.get("height_outline_segments", [])

    def _log_environment_summary(self):
        avg_surface = self.get_average_surface_water()
        avg_top = self.get_average_top_moisture()
        avg_deep = self.get_average_deep_moisture()
        avg_biomass = self.get_average_plant_biomass()
        avg_health = self.get_average_plant_health()

        logger.debug(
            f"[BioregionSimulation] Moisture summary | "
            f"rain={self.weather.is_raining} | "
            f"avg_surface={avg_surface:.3f} | "
            f"avg_top={avg_top:.3f} | "
            f"avg_deep={avg_deep:.3f} | "
            f"avg_biomass={avg_biomass:.3f} | "
            f"avg_health={avg_health:.3f}",
            key="bioregion_moisture_summary",
            interval=1.5
        )

    def get_section_count(self):
        return self.SECTIONS_PER_SIDE

    def get_section_size(self):
        return self.SECTION_SIZE_M

    def get_subsection_count_per_section(self):
        return self.SUBSECTIONS_PER_SECTION_SIDE

    def get_subsection_size(self):
        return self.SUBSECTION_SIZE_M

    def get_map_size(self):
        return self.MAP_SIZE_M

    def get_biosphere_shape_points(self):
        return list(self.biosphere_shape_points)

    def get_biosphere_width(self):
        return self.biosphere_width_m

    def get_biosphere_height(self):
        return self.biosphere_height_m

    def get_biosphere_area(self):
        return self.biosphere_area_m2

    def world_to_cell_indices(self, world_x, world_y):
        if world_x < 0.0 or world_y < 0.0:
            return None

        if world_x >= self.bounds["max_x"] or world_y >= self.bounds["max_y"]:
            return None

        if not self._point_in_biosphere_shape(world_x, world_y):
            return None

        section_col = int(world_x // self.SECTION_SIZE_M)
        section_row = int(world_y // self.SECTION_SIZE_M)

        local_x = world_x - (section_col * self.SECTION_SIZE_M)
        local_y = world_y - (section_row * self.SECTION_SIZE_M)

        subsection_col = int(local_x // self.SUBSECTION_SIZE_M)
        subsection_row = int(local_y // self.SUBSECTION_SIZE_M)

        subsection_min_x = (
            section_col * self.SECTION_SIZE_M
            + subsection_col * self.SUBSECTION_SIZE_M
        )
        subsection_min_y = (
            section_row * self.SECTION_SIZE_M
            + subsection_row * self.SUBSECTION_SIZE_M
        )
        subsection_max_x = subsection_min_x + self.SUBSECTION_SIZE_M
        subsection_max_y = subsection_min_y + self.SUBSECTION_SIZE_M

        return {
            "section_col": section_col,
            "section_row": section_row,
            "subsection_col": subsection_col,
            "subsection_row": subsection_row,
            "min_x": subsection_min_x,
            "min_y": subsection_min_y,
            "max_x": subsection_max_x,
            "max_y": subsection_max_y,
            "center_x": (subsection_min_x + subsection_max_x) / 2.0,
            "center_y": (subsection_min_y + subsection_max_y) / 2.0,
        }

    def get_cell_label(self, cell):
        if cell is None:
            return "No cell selected"

        return (
            f"Section ({cell['section_col']}, {cell['section_row']}) | "
            f"Subsection ({cell['subsection_col']}, {cell['subsection_row']})"
        )

    def get_selected_grid_cell(self):
        if self.selected_cell is None:
            return None

        section_col = self.selected_cell["section_col"]
        section_row = self.selected_cell["section_row"]
        subsection_col = self.selected_cell["subsection_col"]
        subsection_row = self.selected_cell["subsection_row"]

        absolute_col = (
            section_col * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_col
        )
        absolute_row = (
            section_row * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_row
        )

        return self.grid.get_cell(absolute_row, absolute_col)

    def get_hover_grid_cell(self):
        if self.hover_cell is None:
            return None

        section_col = self.hover_cell["section_col"]
        section_row = self.hover_cell["section_row"]
        subsection_col = self.hover_cell["subsection_col"]
        subsection_row = self.hover_cell["subsection_row"]

        absolute_col = (
            section_col * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_col
        )
        absolute_row = (
            section_row * self.SUBSECTIONS_PER_SECTION_SIDE + subsection_row
        )

        return self.grid.get_cell(absolute_row, absolute_col)

    def get_average_surface_water(self):
        return self.grid.get_average_surface_water()

    def get_average_top_moisture(self):
        return self.grid.get_average_top_moisture()

    def get_average_deep_moisture(self):
        return self.grid.get_average_deep_moisture()

    def get_average_plant_biomass(self):
        return self.grid.get_average_plant_biomass()

    def get_average_plant_health(self):
        return self.grid.get_average_plant_health()

    @property
    def is_raining(self):
        return self.weather.is_raining

    def handle_pointer_motion(self, event, camera, screen_pos):
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.hover_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        world_x, world_y = camera.screen_to_world(screen_pos)
        self.selected_cell = self.world_to_cell_indices(world_x, world_y)
        self.hover_screen_pos = screen_pos

        selected_grid_cell = self.get_selected_grid_cell()
        if selected_grid_cell is not None:
            logger.debug(
                f"[BioregionSimulation] Selected cell | "
                f"soil={selected_grid_cell['soil_type']} | "
                f"bedrock={selected_grid_cell['bedrock_type']} | "
                f"altitude={selected_grid_cell['altitude']:.3f} | "
                f"surface={selected_grid_cell['surface_water']:.3f} | "
                f"top={selected_grid_cell['top_moisture']:.3f} | "
                f"deep={selected_grid_cell['deep_moisture']:.3f} | "
                f"biomass={selected_grid_cell['plant_biomass']:.3f} | "
                f"health={selected_grid_cell['plant_health']:.3f} | "
                f"habitat={selected_grid_cell['habitat_type']}",
                key="bioregion_cell_selection",
                interval=0.1
            )
