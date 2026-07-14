import gzip
import json
from pathlib import Path


def _earth_reference_land_polygons():
    path = Path(__file__).resolve().parent / "reference_data" / "earth_land_110m.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _earth_reference_region_geometries():
    path = Path(__file__).resolve().parent / "reference_data" / "earth_regions_reference.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _earth_height_rows():
    return [
        [-2200, -1800, -1200, -400, 900, 1300, 600, -900, -2600, -3100, -2800, -1500, 400, 1200, 900, -900, -2400, -2800, -2200, -1400, -800, -600, -1200, -2100, -2600],
        [-3400, -2800, -900, 1100, 1800, 900, -1300, -3300, -3900, -3000, -900, 400, 900, 1700, 2200, 1200, -700, -2600, -3500, -3100, -2200, -1500, -1800, -2900, -3600],
        [-4200, -3500, -1800, 300, 800, 400, -1900, -4200, -3900, -1800, 200, 700, 1100, 2100, 3100, 2400, 600, -1200, -2800, -3800, -4100, -3600, -3200, -3600, -4300],
        [-4700, -3900, -2600, -600, 250, -1200, -3100, -4400, -3200, -1000, 300, 650, 900, 1800, 4200, 3600, 1500, -600, -2100, -3600, -4600, -4900, -4700, -4500, -4800],
        [-5000, -4200, -3200, -800, 350, -900, -3300, -4500, -2700, -900, 450, 780, 620, 900, 2600, 3100, 2200, 300, -1400, -3200, -4500, -5200, -5300, -5100, -5000],
        [-5200, -4600, -3600, -1600, 220, -400, -2700, -4200, -3100, -1400, 200, 420, -300, -900, 600, 1800, 2500, 900, -500, -2500, -4100, -5000, -5400, -5300, -5200],
        [-5000, -4400, -3400, -2100, -600, -1200, -3000, -4700, -4300, -3300, -1500, -500, -1700, -3300, -1600, 200, 900, 120, -1600, -3000, -4200, -4900, -5200, -5200, -5000],
        [-4700, -4000, -3300, -2600, -1800, -2600, -4100, -5200, -5000, -4300, -2900, -1500, -2200, -4200, -3500, -1700, -900, -2200, -3600, -4300, -4700, -4800, -4900, -4900, -4700],
        [-4300, -3800, -3400, -3000, -2800, -3400, -4700, -5600, -5200, -4500, -3400, -2300, -2800, -4800, -5000, -4200, -3300, -3700, -4300, -4600, -4500, -4300, -4200, -4200, -4300],
        [-3600, -3300, -3100, -3000, -3100, -3700, -4800, -5400, -5000, -4300, -3600, -3100, -3400, -4700, -5200, -5000, -4600, -4400, -4100, -3800, -3500, -3200, -3100, -3200, -3600],
        [-2500, -2300, -2200, -2400, -2800, -3400, -4200, -4800, -4600, -4100, -3800, -3600, -3700, -4200, -4700, -4900, -4700, -4300, -3600, -2800, -2100, -1600, -1400, -1700, -2500],
        [900, 1200, 1400, 1300, 900, 300, -1000, -2600, -3400, -3600, -3400, -3100, -3000, -3200, -3400, -3500, -3300, -2900, -2200, -1200, 100, 800, 1200, 1100, 900],
        [2400, 2600, 2700, 2500, 2200, 1800, 900, -800, -2200, -3000, -3300, -3400, -3400, -3300, -3100, -2800, -2400, -1800, -800, 600, 1600, 2300, 2700, 2600, 2400],
    ]


def _earth_ice_rows():
    rows = []
    for row_index in range(12):
        row = []
        for col_index in range(24):
            row.append(row_index == 0 or row_index >= 10 or (row_index == 1 and 11 <= col_index <= 15))
        rows.append(row)
    return rows


def _legacy_earth_reference_payload():
    height_rows = _earth_height_rows()
    return {
        "map_status": "earth_reference_worldgen_baseline",
        "map_projection": "equirectangular",
        "map_canvas_width_px": 2048,
        "map_canvas_height_px": 1024,
        "map_generation_recipe": [
            "reference_earth_canvas",
            "reference_hypsometry",
            "reference_atmosphere",
            "reference_plate_tectonics",
            "reference_hydrology",
        ],
        "derived_planet_physics": {
            "radius_m": 6371000.0,
            "radius_earth": 1.0,
            "mass_kg": 5.9722e24,
            "mass_earth": 1.0,
            "mean_density_kg_m3": 5514.0,
            "surface_gravity_m_s2": 9.80665,
            "surface_gravity_g": 1.0,
            "rotation_period_hours": 23.9345,
            "escape_velocity_m_s": 11186.0,
        },
        "atmosphere_model": {
            "status": "earth_reference_atmosphere",
            "atmosphere_class": "nitrogen_oxygen_temperate",
            "surface_pressure_bar": 1.01325,
            "surface_temperature_k": 288.15,
            "greenhouse_delta_k": 33.0,
            "mean_molecular_weight_g_mol": 28.97,
            "composition": [
                {"molecule": "N2", "name": "Nitrogen", "fraction": 0.78084, "percent": 78.084},
                {"molecule": "O2", "name": "Oxygen", "fraction": 0.20946, "percent": 20.946},
                {"molecule": "Ar", "name": "Argon", "fraction": 0.00934, "percent": 0.934},
                {"molecule": "CO2", "name": "Carbon Dioxide", "fraction": 0.00042, "percent": 0.042},
            ],
            "retention": [
                {"molecule": "N2", "status": "stable"},
                {"molecule": "O2", "status": "stable"},
                {"molecule": "H2O", "status": "stable"},
                {"molecule": "CO2", "status": "stable"},
            ],
        },
        "interior_regime_model": {
            "interior": {
                "differentiated": True,
                "core_radius_fraction": 0.546,
                "mantle_present": True,
                "crust_thickness_km": 35.0,
                "internal_heat_w_m2": 0.087,
                "tectonic_regime": "plate_tectonics",
                "volcanic_activity": "active",
                "crust_type": "mixed_continental_oceanic",
            },
            "surface_processes": {
                "hydrologic_cycle": "active",
                "erosion_processes": ["fluvial", "glacial", "coastal", "aeolian", "chemical_weathering"],
                "crater_retention": "low",
            },
        },
        "terrain_seed_model": {
            "status": "earth_reference_terrain_seed",
            "map_seed": "reference-earth",
            "map_canvas": {
                "projection": "equirectangular",
                "width_px": 2048,
                "height_px": 1024,
                "vertical_datum": "mean_sea_level",
            },
            "heightfield": {
                "resolution": "reference_coarse_global",
                "min_elevation_m": -10984.0,
                "max_elevation_m": 8849.0,
                "sea_level_m": 0.0,
                "target_ocean_fraction": 0.708,
                "primary_topography": "plate_tectonic_hypsometry",
            },
            "tectonics": {
                "enabled": True,
                "regime": "plate_tectonics",
                "plate_count": 15,
                "boundary_style": "subduction_rift_transform",
            },
            "hydrology": {
                "cycle": "active",
                "liquid_water_possible": True,
                "target_ocean_fraction": 0.708,
                "drainage_enabled": True,
            },
        },
        "tectonic_model": {
            "status": "earth_reference_tectonics",
            "age_myr": 4500.0,
            "plate_count": 15,
            "regime": "plate_tectonics",
            "plates": [
                {"id": "pacific", "name": "Pacific Plate", "kind": "oceanic"},
                {"id": "north_american", "name": "North American Plate", "kind": "mixed"},
                {"id": "eurasian", "name": "Eurasian Plate", "kind": "mixed"},
                {"id": "african", "name": "African Plate", "kind": "mixed"},
                {"id": "antarctic", "name": "Antarctic Plate", "kind": "mixed"},
                {"id": "indo_australian", "name": "Indo-Australian Plate", "kind": "mixed"},
                {"id": "south_american", "name": "South American Plate", "kind": "mixed"},
                {"id": "nazca", "name": "Nazca Plate", "kind": "oceanic"},
            ],
            "surface_effects": {
                "mountain_building": "active",
                "trench_formation": "active",
                "rift_spreading": "active",
                "continental_drift": "active",
            },
        },
        "heightmap_model": {
            "status": "earth_reference_heightmap",
            "projection": "equirectangular",
            "wrap_x": True,
            "min_elevation_m": -10984.0,
            "max_elevation_m": 8849.0,
            "sea_level_m": 0.0,
            "land_fraction": 0.292,
            "ocean_fraction": 0.708,
            "sample_grid": {
                "width": len(height_rows[0]),
                "height": len(height_rows),
                "rows": height_rows,
            },
            "surface_masks": {
                "ice_rows": _earth_ice_rows(),
            },
            "notes": [
                "Coarse reference grid for UI/world-gen validation, not a navigation-grade elevation dataset.",
            ],
        },
        "reference_land_polygons": _earth_reference_land_polygons(),
        "water_cycle_model": {
            "status": "earth_reference_water_cycle",
            "ocean_fraction": 0.708,
            "mean_precipitation_mm_yr": 990.0,
            "mean_evaporation_mm_yr": 990.0,
            "runoff_km3_yr": 47000.0,
            "ice_sheet_fraction": 0.021,
            "cycle": "active",
        },
        "environment_summary": {
            "habitability_class": "biosphere-bearing temperate terrestrial",
            "surface_water": "stable_liquid_oceans",
            "atmosphere": "nitrogen_oxygen",
            "tectonics": "active_plate_tectonics",
            "biosphere": "global",
        },
        "geology_summary": {
            "crust": "mixed_oceanic_continental",
            "tectonic_regime": "plate_tectonics",
            "highest_point_m": 8849.0,
            "lowest_point_m": -10984.0,
        },
        "hydrology_summary": {
            "ocean_fraction": 0.708,
            "liquid_water": True,
            "cryosphere": "polar_and_mountain_ice",
        },
        "ecology_summary": {
            "biosphere_status": "confirmed",
            "primary_energy": "solar_photosynthesis",
            "dominant_surface_biomes": ["marine", "forest", "grassland", "desert", "tundra"],
        },
    }


def _earth_worldgen_reference_bundle():
    path = Path(__file__).resolve().parent / "reference_data" / "earth_worldgen_reference.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _earth_reference_payload():
    payload = _legacy_earth_reference_payload()
    bundle = _earth_worldgen_reference_bundle()
    for key in (
        "data_sources", "heightmap_model", "reference_land_polygons",
        "reference_glacier_polygons", "water_cycle_model", "cryosphere_model",
        "natural_material_model", "surface_palette",
    ):
        if key in bundle:
            payload[key] = bundle[key]
    if bundle:
        payload["map_status"] = "earth_authored_worldgen_reference"
        payload["map_canvas_width_px"] = 4096
        payload["map_canvas_height_px"] = 2048
        payload["map_generation_recipe"] = [
            "authored_noaa_global_relief",
            "authored_natural_earth_physical_vectors",
            "worldgen_climate_hydrology_contract",
            "shared_movable_spherical_projection",
        ]
    return payload


def _find_earth_entity(entities):
    if hasattr(entities, "entities"):
        entities = getattr(entities, "entities", {})
    if isinstance(entities, dict):
        direct = entities.get("planet_earth") or entities.get("body_earth")
        if isinstance(direct, dict):
            return direct
        iterable = entities.values()
    else:
        iterable = entities or []

    for entity in iterable:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or entity.get("pretty_name") or "").strip().lower()
        if name == "earth" and entity.get("location_class") == "planet":
            return entity
    return None


def _runtime_entity_store(target):
    if hasattr(target, "entities"):
        entities = getattr(target, "entities", {})
        datasets = getattr(target, "datasets", {}) or {}
        return entities, datasets
    return target, {}


def _bbox(min_x, max_x, min_y, max_y):
    return {
        "type": "bbox",
        "coordinate_space": "map_world",
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
    }


def _poly(points):
    return {
        "type": "polygon",
        "coordinate_space": "map_world",
        "points": points,
    }


def _earth_reference_surface_regions():
    return [
        {
            "id": "loc_africa",
            "name": "Africa",
            "location_class": "continent",
            "card_color": "#8f7744",
            "coords": {"type": "point", "x": 20.0, "y": 1.0},
            "bounds": _poly([
                [-17.5, -34.5],
                [-7.0, -35.5],
                [6.5, -36.2],
                [18.5, -34.0],
                [31.0, -31.0],
                [34.5, -23.0],
                [43.5, -12.5],
                [51.5, -11.0],
                [44.0, -1.0],
                [42.0, 11.0],
                [35.0, 24.0],
                [26.0, 32.0],
                [17.0, 34.5],
                [7.0, 36.0],
                [-5.5, 34.5],
                [-13.0, 29.0],
                [-17.0, 18.0],
                [-9.0, 5.0],
                [-13.0, -6.0],
                [-17.5, -20.0],
                [-17.5, -34.5],
            ]),
        },
        {
            "id": "loc_antarctica",
            "name": "Antarctica",
            "location_class": "continent",
            "card_color": "#d2e0e7",
            "coords": {"type": "point", "x": 0.0, "y": 82.0},
            "bounds": _poly([
                [-180.0, 67.0],
                [-140.0, 65.0],
                [-100.0, 68.0],
                [-65.0, 64.0],
                [-25.0, 70.0],
                [20.0, 66.0],
                [60.0, 68.5],
                [105.0, 64.5],
                [145.0, 66.5],
                [180.0, 67.0],
                [180.0, 90.0],
                [-180.0, 90.0],
                [-180.0, 67.0],
            ]),
        },
        {
            "id": "loc_pacific_ocean",
            "name": "Pacific Ocean",
            "location_class": "ocean",
            "card_color": "#1c5a8c",
            "coords": {"type": "point", "x": -150.0, "y": 0.0},
            "bounds": _poly([
                [-180.0, -64.0],
                [-120.0, -62.0],
                [-95.0, -44.0],
                [-78.0, -8.0],
                [-72.0, 8.0],
                [-80.0, 32.0],
                [-110.0, 54.0],
                [-150.0, 62.0],
                [-180.0, 60.0],
                [-180.0, -64.0],
            ]),
        },
        {
            "id": "loc_indian_ocean",
            "name": "Indian Ocean",
            "location_class": "ocean",
            "card_color": "#2a6f8d",
            "coords": {"type": "point", "x": 76.0, "y": 23.0},
            "bounds": _poly([
                [21.0, -31.0],
                [58.0, -30.0],
                [98.0, -22.0],
                [120.0, -8.0],
                [118.0, 30.0],
                [104.0, 48.0],
                [80.0, 57.0],
                [48.0, 60.0],
                [35.0, 45.0],
                [29.0, 20.0],
                [21.0, 8.0],
                [21.0, -31.0],
            ]),
        },
        {
            "id": "loc_arctic_ocean",
            "name": "Arctic Ocean",
            "location_class": "ocean",
            "card_color": "#9db9ca",
            "coords": {"type": "point", "x": 0.0, "y": -82.0},
            "bounds": _bbox(-180.0, 180.0, -90.0, -66.0),
        },
        {
            "id": "loc_southern_ocean",
            "name": "Southern Ocean",
            "location_class": "ocean",
            "card_color": "#688fa5",
            "coords": {"type": "point", "x": 0.0, "y": 58.0},
            "bounds": _bbox(-180.0, 180.0, 45.0, 66.0),
        },
    ]


def _apply_missing_earth_surface_regions(target, earth):
    entities, datasets = _runtime_entity_store(target)
    if not isinstance(entities, dict) or not isinstance(earth, dict):
        return False

    changed = False
    location_dataset = datasets.setdefault("locations", []) if isinstance(datasets, dict) else []
    earth_constituents = earth.get("constituents")
    if isinstance(earth_constituents, str):
        earth_constituents = [earth_constituents] if earth_constituents else []
    elif isinstance(earth_constituents, list):
        earth_constituents = list(earth_constituents)
    else:
        earth_constituents = []

    existing_dataset_ids = {
        entity.get("id")
        for entity in location_dataset
        if isinstance(entity, dict)
    }

    for region in _earth_reference_surface_regions():
        region_id = region["id"]
        if region_id not in entities:
            entity = {
                "id": region_id,
                "pretty_name": region["name"],
                "name": region["name"],
                "type": "location",
                "_dataset": "locations",
                "location_class": region["location_class"],
                "parent_location": "planet_earth",
                "parents": ["planet_earth"],
                "coords": region["coords"],
                "bounds": region["bounds"],
                "card_color": region["card_color"],
                "wiki_entry": f"Runtime Earth reference {region['location_class']} used as a broad map layer.",
                "map_reference_generated": True,
            }
            entities[region_id] = entity
            if region_id not in existing_dataset_ids:
                location_dataset.append(entity)
                existing_dataset_ids.add(region_id)
            changed = True
        elif isinstance(entities.get(region_id), dict) and entities[region_id].get("map_reference_generated"):
            entity = entities[region_id]
            for field in ("coords", "bounds", "card_color", "location_class"):
                if entity.get(field) != region[field]:
                    entity[field] = region[field]
                    changed = True

        if region_id not in earth_constituents:
            earth_constituents.append(region_id)
            changed = True

    if earth.get("constituents") != earth_constituents:
        earth["constituents"] = earth_constituents

    return changed


def _apply_earth_reference_region_geometries(target, earth):
    entities, _datasets = _runtime_entity_store(target)
    if not isinstance(entities, dict) or not isinstance(earth, dict):
        return False

    payload = _earth_reference_region_geometries()
    regions = payload.get("regions") if isinstance(payload.get("regions"), dict) else {}
    if not regions:
        return False

    changed = False
    for entity_id, reference in regions.items():
        entity = entities.get(entity_id)
        if not isinstance(entity, dict):
            continue
        bounds = reference.get("bounds")
        coords = reference.get("coords")
        if isinstance(bounds, dict) and entity.get("bounds") != bounds:
            entity["bounds"] = bounds
            entity["bounds_source"] = "natural_earth_reference"
            entity["map_reference_geometry"] = True
            changed = True
        if isinstance(coords, dict) and entity.get("coords") != coords:
            entity["coords"] = coords
            changed = True
    return changed


def apply_earth_reference_models(target):
    entities, _ = _runtime_entity_store(target)
    earth = _find_earth_entity(entities)
    if not isinstance(earth, dict):
        return False

    changed = False
    canonical_keys = {
        "data_sources", "heightmap_model", "reference_land_polygons",
        "reference_glacier_polygons", "water_cycle_model", "cryosphere_model",
        "natural_material_model", "surface_palette",
        "map_status", "map_canvas_width_px", "map_canvas_height_px", "map_generation_recipe",
    }
    for key, value in _earth_reference_payload().items():
        existing = earth.get(key)
        existing_status = existing.get("status", "") if isinstance(existing, dict) else ""
        legacy_reference = (
            str(existing_status).startswith("earth_reference_")
            or (key == "reference_land_polygons" and isinstance(existing, dict) and "110m" in str(existing.get("source", "")))
            or (key == "map_status" and str(existing).startswith("earth_reference_"))
            or (key == "map_canvas_width_px" and existing == 2048)
            or (key == "map_canvas_height_px" and existing == 1024)
            or (key == "map_generation_recipe" and isinstance(existing, list) and "reference_earth_canvas" in existing)
        )
        if existing in (None, "", [], {}) or (key in canonical_keys and legacy_reference):
            earth[key] = value
            changed = True

    tags = earth.get("tags")
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    elif isinstance(tags, list):
        tags = list(tags)
    else:
        tags = []
    if "earth_reference_worldgen" not in tags:
        tags.append("earth_reference_worldgen")
        earth["tags"] = tags
        changed = True

    changed = _apply_missing_earth_surface_regions(target, earth) or changed
    changed = _apply_earth_reference_region_geometries(target, earth) or changed
    return changed
