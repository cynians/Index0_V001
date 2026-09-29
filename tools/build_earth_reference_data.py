"""Build the compact, authored Earth world-generation reference bundle.

Inputs are intentionally kept outside version control; the generated gzip JSON
contains the runtime data and provenance. Relief is NOAA ETOPO5 and vectors are
Natural Earth 1:50m physical layers.
"""

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import shapefile

from simulations.world_gen.water_cycle import derive_water_cycle_model


CACHE = ROOT / ".cache"
OUTPUT = ROOT / "world" / "reference_data" / "earth_worldgen_reference.json.gz"
GRID_WIDTH = 257
GRID_HEIGHT = 129


def _parts(shape):
    stops = list(shape.parts) + [len(shape.points)]
    for index in range(len(stops) - 1):
        points = shape.points[stops[index]:stops[index + 1]]
        if len(points) >= 2:
            yield points


def _rounded_map_ring(points):
    return [[round(float(lon), 4), round(-float(lat), 4)] for lon, lat in points]


def _rounded_uv_line(points):
    return [
        {"x": round((float(lon) + 180.0) / 360.0, 6), "y": round((90.0 - float(lat)) / 180.0, 6)}
        for lon, lat in points
    ]


def _read_relief():
    raw = np.memmap(CACHE / "ETOPO5.DOS", dtype="<i2", mode="r", shape=(2160, 4320))
    target_lats = np.linspace(90.0, -90.0, GRID_HEIGHT)
    target_lons = np.linspace(-180.0, 180.0, GRID_WIDTH)
    rows = []
    for latitude in target_lats:
        source_y = np.clip((90.0 - latitude) / 180.0 * 2159.0, 0.0, 2159.0)
        y0 = int(np.floor(source_y))
        y1 = min(2159, y0 + 1)
        fy = source_y - y0
        row = []
        for longitude in target_lons:
            source_lon = longitude % 360.0
            source_x = source_lon / 360.0 * 4320.0
            x0 = int(np.floor(source_x)) % 4320
            x1 = (x0 + 1) % 4320
            fx = source_x - np.floor(source_x)
            value = (
                (1.0 - fy) * ((1.0 - fx) * float(raw[y0, x0]) + fx * float(raw[y0, x1]))
                + fy * ((1.0 - fx) * float(raw[y1, x0]) + fx * float(raw[y1, x1]))
            )
            row.append(int(round(value)))
        rows.append(row)
    return rows


def _land_polygons():
    reader = shapefile.Reader(str(CACHE / "ne_50m_land" / "ne_50m_land.shp"))
    return [_rounded_map_ring(part) for shape in reader.shapes() for part in _parts(shape) if len(part) >= 3]


def _glacier_polygons():
    reader = shapefile.Reader(str(CACHE / "ne_50m_glaciated" / "ne_50m_glaciated_areas.shp"))
    return [_rounded_map_ring(part) for shape in reader.shapes() for part in _parts(shape) if len(part) >= 3]


def _rank(record):
    value = record.as_dict().get("scalerank", 99)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99


def _rivers():
    reader = shapefile.Reader(str(CACHE / "ne_50m_rivers" / "ne_50m_rivers_lake_centerlines.shp"))
    rivers = []
    for item in reader.iterShapeRecords():
        rank = _rank(item.record)
        if rank > 6:
            continue
        fields = item.record.as_dict()
        for part_index, part in enumerate(_parts(item.shape)):
            if len(part) < 2:
                continue
            rivers.append({
                "id": f"earth_river_{len(rivers)}",
                "name": fields.get("name") or fields.get("name_en") or "River",
                "source": "Natural Earth 1:50m rivers",
                "scalerank": rank,
                "stream_order": max(1, 7 - rank),
                "network_role": "mainstem" if rank <= 2 else "tributary" if rank <= 4 else "feeder",
                "flow": round(max(0.16, 1.0 - rank * 0.12), 3),
                "display_points": _rounded_uv_line(part),
            })
    return rivers


def _lakes():
    reader = shapefile.Reader(str(CACHE / "ne_50m_lakes" / "ne_50m_lakes.shp"))
    lakes = []
    for item in reader.iterShapeRecords():
        rank = _rank(item.record)
        if rank > 5:
            continue
        fields = item.record.as_dict()
        for part in _parts(item.shape):
            if len(part) >= 3:
                lakes.append({
                    "name": fields.get("name") or fields.get("name_en") or "Lake",
                    "scalerank": rank,
                    "points": _rounded_uv_line(part),
                })
    return lakes


def _climate(relief):
    zones = [
        {"id": "polar", "name": "Polar", "color": [205, 226, 235]},
        {"id": "alpine", "name": "Alpine", "color": [180, 190, 184]},
        {"id": "cold", "name": "Cold continental", "color": [99, 151, 125]},
        {"id": "temperate", "name": "Temperate", "color": [77, 145, 82]},
        {"id": "dry", "name": "Dry subtropical", "color": [194, 165, 88]},
        {"id": "tropical", "name": "Tropical", "color": [42, 126, 68]},
        {"id": "ocean", "name": "Ocean", "color": [33, 85, 128]},
    ]
    rows, temperatures, precipitation = [], [], []
    for iy, elevation_row in enumerate(relief):
        latitude = 90.0 - iy / (GRID_HEIGHT - 1) * 180.0
        climate_row, temperature_row, precipitation_row = [], [], []
        for elevation in elevation_row:
            temperature = 301.0 - abs(latitude) * 0.62 - max(0, elevation) * 0.006
            if elevation <= 0:
                zone = "ocean"
                precipitation_mm = 1050
            elif abs(latitude) >= 66 or temperature < 263:
                zone = "polar"
                precipitation_mm = 260
            elif elevation >= 2400:
                zone = "alpine"
                precipitation_mm = 620
            elif abs(latitude) >= 47:
                zone = "cold"
                precipitation_mm = 720
            elif 18 <= abs(latitude) <= 35:
                zone = "dry"
                precipitation_mm = 410
            elif abs(latitude) < 23.5:
                zone = "tropical"
                precipitation_mm = 1650
            else:
                zone = "temperate"
                precipitation_mm = 900
            climate_row.append(zone)
            temperature_row.append(round(temperature, 1))
            precipitation_row.append(precipitation_mm)
        rows.append(climate_row)
        temperatures.append(temperature_row)
        precipitation.append(precipitation_row)
    return zones, rows, temperatures, precipitation


def build():
    relief = _read_relief()
    ice_rows = [
        [abs(90.0 - iy / (GRID_HEIGHT - 1) * 180.0) >= 70.0 or elevation >= 5000 for elevation in row]
        for iy, row in enumerate(relief)
    ]
    land_cells = sum(elevation > 0 for row in relief for elevation in row)
    total_cells = GRID_WIDTH * GRID_HEIGHT
    land_fraction = land_cells / total_cells
    rivers = _rivers()
    lakes = _lakes()
    heightmap_model = {
        "status": "heightmap_authored_reference",
        "model_version": "earth-reference-v1",
        "projection": "equirectangular",
        "coverage": "full_planet",
        "wrap_x": True,
        "wrap_y": False,
        "edge_policy": "longitude_wrap_latitude_clamp",
        "vertical_datum": "mean_sea_level",
        "elevation_unit": "meters",
        "min_elevation_m": min(map(min, relief)),
        "max_elevation_m": max(map(max, relief)),
        "sea_level_m": 0.0,
        "land_fraction": round(land_fraction, 4),
        "ocean_fraction": round(1.0 - land_fraction, 4),
        "sample_grid": {"width": GRID_WIDTH, "height": GRID_HEIGHT, "rows": relief},
        "surface_masks": {"ice_rows": ice_rows},
        "source": "NOAA/NCEI ETOPO5",
        "storage": {"kind": "authored_global_reference_grid", "sample_format": "integer_meters"},
    }
    water_cycle = derive_water_cycle_model(
        terrain={
            "map_seed": "earth_reference_2026",
            "hydrology": {
                "target_ocean_fraction": 1.0 - land_fraction,
                "liquid_water_possible": True,
                # Natural Earth remains the visual river reference; this pass
                # specifically evaluates the generated climate model.
                "drainage_enabled": False,
            },
        },
        heightmap=heightmap_model,
        atmosphere={
            "estimated_surface_temperature_k": 288.0,
            "surface_pressure_bar": 1.01325,
        },
        seed={
            "map_seed": "earth_reference_2026",
            "rotation_hours": 23.934,
            "axial_tilt_deg": 23.44,
            "climate_mode": "latitudinal_seasonal",
        },
        planet_id="planet_earth",
    )
    water_cycle.update({
        "status": "earth_reference_simulated_climate",
        "source": "Index0 coupled climate model driven by NOAA/NCEI ETOPO5 relief; Natural Earth supplies reference hydrography.",
        "rivers": rivers,
        "river_count": len(rivers),
        "reference_lakes": lakes,
        "lake_count": len(lakes),
    })
    payload = {
        "schema_version": 1,
        "generated_utc": "2026-07-14",
        "data_sources": [
            {
                "name": "NOAA/NCEI ETOPO5 global relief",
                "url": "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO5/TOPO/ETOPO5/",
                "role": "authored terrestrial and bathymetric elevation",
                "note": "Legacy 5 arc-minute relief; ETOPO2022 is the preferred future high-resolution replacement.",
            },
            {
                "name": "Natural Earth 1:50m physical vectors",
                "url": "https://www.naturalearthdata.com/downloads/50m-physical-vectors/",
                "role": "land, rivers, lakes, and glaciated areas",
                "license": "public domain",
            },
        ],
        "heightmap_model": heightmap_model,
        "reference_land_polygons": {
            "source": "Natural Earth 1:50m land polygons, public domain",
            "source_url": "https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-land/",
            "coordinate_space": "map_world", "projection": "equirectangular",
            "y_axis": "negative_latitude", "polygons": _land_polygons(),
        },
        "reference_glacier_polygons": {
            "source": "Natural Earth 1:50m glaciated areas, public domain",
            "coordinate_space": "map_world", "projection": "equirectangular",
            "y_axis": "negative_latitude", "polygons": _glacier_polygons(),
        },
        "water_cycle_model": water_cycle,
        "cryosphere_model": {
            "status": "cryosphere_authored_reference",
            "reference_glacier_polygons_key": "reference_glacier_polygons",
            "source": "Natural Earth 1:50m glaciated areas",
        },
        "natural_material_model": {
            "status": "materials_authored_earth_reference",
            "model_version": "earth-reference-v1",
            "dominant_materials": [
                "mat_basalt", "mat_granite", "mat_quartz", "mat_plagioclase_feldspar",
                "mat_clay_rich_regolith", "mat_calcite", "mat_water_ice",
            ],
            "likely_materials": [
                {"material_id": "mat_basalt", "name": "Basalt", "occurrence": "common", "confidence": 0.98},
                {"material_id": "mat_granite", "name": "Granite", "occurrence": "common", "confidence": 0.98},
                {"material_id": "mat_quartz", "name": "Quartz", "occurrence": "common", "confidence": 0.98},
                {"material_id": "mat_plagioclase_feldspar", "name": "Plagioclase Feldspar", "occurrence": "common", "confidence": 0.98},
                {"material_id": "mat_clay_rich_regolith", "name": "Clay-Rich Regolith", "occurrence": "common", "confidence": 0.95},
                {"material_id": "mat_calcite", "name": "Calcite", "occurrence": "common", "confidence": 0.94},
                {"material_id": "mat_water_ice", "name": "Water Ice", "occurrence": "regional", "confidence": 1.0},
            ],
            "source": "authored Earth crust and surface mineral reference",
        },
        "surface_palette": {
            "surface_color": [92, 108, 91],
            "palette": [[36, 70, 102], [83, 105, 84], [148, 142, 112], [211, 220, 220]],
            "evidence": [
                {"source": "NOAA ETOPO5", "role": "elevation shading"},
                {"source": "Natural Earth", "role": "land, water, and ice masks"},
            ],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
    return payload


if __name__ == "__main__":
    result = build()
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    print(f"Relief: {GRID_WIDTH}x{GRID_HEIGHT}; rivers: {len(result['water_cycle_model']['rivers'])}; lakes: {len(result['water_cycle_model']['reference_lakes'])}")
