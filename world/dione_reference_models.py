"""Cassini-derived reference topography for Saturn's moon Dione."""

import json
from pathlib import Path


REFERENCE_RADIUS_M = 561_400.0


def _dione_height_grid():
    path = Path(__file__).resolve().parent / "reference_data" / "dione_heightmap_reference.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_dione_entity(entities):
    if hasattr(entities, "entities"):
        entities = getattr(entities, "entities", {})
    if isinstance(entities, dict):
        direct = entities.get("body_dione")
        if isinstance(direct, dict):
            return direct
    return None


def _heightmap_payload(grid):
    rows = grid["rows"]
    width = int(grid["width"])
    height = int(grid["height"])
    values = [value for row in rows for value in row[:-1]]
    sample_count = max(1, len(values))
    plain_fraction = sum(-2000 <= value <= 2000 for value in values) / sample_count
    mountain_fraction = sum(value > 2000 for value in values) / sample_count
    basin_fraction = sum(value < -2000 for value in values) / sample_count
    source = dict(grid.get("source") or {})
    source["archive_url"] = (
        "https://sbnarchive.psi.edu/pds4/cassini/"
        "satellite-dione.cassini.shape-models-maps/data/global/"
    )

    return {
        "status": "dione_cassini_spc_reference_heightmap",
        "body_id": "body_dione",
        "projection": "equirectangular",
        "spherical_body": True,
        "wrap_x": True,
        "wrap_y": False,
        "edge_policy": "longitude_wrap_latitude_clamp",
        "width_px": 2048,
        "height_px": 1024,
        "coverage": "full_moon",
        "radius_m": REFERENCE_RADIUS_M,
        "vertical_datum": grid.get("vertical_datum", "mean_radius_561400m"),
        "elevation_unit": "m",
        "min_elevation_m": grid["min_elevation_m"],
        "max_elevation_m": grid["max_elevation_m"],
        "sea_level_m": None,
        "sample_grid": {
            "width": width,
            "height": height,
            "wrap_x": True,
            "wrap_y": False,
            "spacing_x_px": round(2048 / max(1, width - 1), 4),
            "spacing_y_px": round(1024 / max(1, height - 1), 4),
            "rows": rows,
        },
        "surface_masks": {
            "ice_rows": [[True] * width for _ in range(height)],
            "ice_source": "water_ice_surface",
            "target_ice_fraction": 1.0,
        },
        "hypsometry_summary": {
            "broad_plain_fraction": round(plain_fraction, 3),
            "mountain_fraction_above_2000m": round(mountain_fraction, 3),
            "deep_basin_fraction_below_minus_2000m": round(basin_fraction, 3),
            "land_fraction": 1.0,
            "ocean_fraction": 0.0,
            "ice_fraction": 1.0,
        },
        "geology_model": {
            "model_version": "dione-cassini-reference-v1",
            "surface": "water_ice_and_impact_regolith",
            "dominant_landforms": ["impact_craters", "chasmata", "tectonic_fractures", "smooth_plains"],
            "tectonic_style": "extensional_ice_tectonics",
        },
        "source_models": {
            "topography": source,
            "resampling": "bilinear_merge_of_equatorial_and_polar_radius_geotiffs",
        },
        "storage": {
            "kind": "reference_resampled_heightfield",
            "source_resolution_m_per_pixel": source.get("source_resolution_m_per_pixel"),
        },
        "notes": [
            "Elevations are radius offsets from Dione's 561.4 km reference sphere.",
            "The runtime grid is a compact resampling of the Cassini SPC products; features below the source resolution are not invented.",
        ],
    }


def _dione_reference_payload(grid):
    return {
        "map_status": "dione_cassini_reference",
        "map_projection": "equirectangular",
        "map_canvas_width_px": 2048,
        "map_canvas_height_px": 1024,
        "map_generation_recipe": [
            "cassini_spc_global_shape",
            "equatorial_and_polar_geotiff_merge",
            "compact_equirectangular_resample",
        ],
        "surface_palette": {
            "surface_color": [178, 190, 199],
            "palette": [[91, 103, 115], [166, 180, 190], [222, 231, 235], [118, 128, 139]],
        },
        "terrain_seed_model": {
            "status": "dione_cassini_reference_terrain",
            "map_seed": "reference-dione-cassini-spc",
            "map_canvas": {
                "projection": "equirectangular",
                "width_px": 2048,
                "height_px": 1024,
                "vertical_datum": "mean_radius_561400m",
            },
            "heightfield": {
                "resolution": "cassini_spc_compact_global",
                "min_elevation_m": grid["min_elevation_m"],
                "max_elevation_m": grid["max_elevation_m"],
                "sea_level_m": None,
                "primary_topography": "cassini_stereophotoclinometry",
            },
        },
        "heightmap_model": _heightmap_payload(grid),
        "geology_summary": {
            "surface": "water_ice_and_impact_regolith",
            "dominant_features": ["craters", "chasmata", "bright_ice_cliffs", "tectonic_fractures"],
            "topography_source": "Cassini stereophotoclinometry",
        },
    }


def apply_dione_reference_models(target):
    dione = _find_dione_entity(target)
    if not isinstance(dione, dict):
        return False
    grid = _dione_height_grid()
    if not grid.get("rows"):
        return False

    changed = False
    for key, value in _dione_reference_payload(grid).items():
        if dione.get(key) in (None, "", [], {}):
            dione[key] = value
            changed = True

    tags = dione.get("tags")
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    elif isinstance(tags, list):
        tags = list(tags)
    else:
        tags = []
    if "dione_cassini_reference_heightmap" not in tags:
        tags.append("dione_cassini_reference_heightmap")
        dione["tags"] = tags
        changed = True
    return changed
