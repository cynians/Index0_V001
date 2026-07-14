"""Build the runtime Earth country-reference payload from Natural Earth GeoJSON.

The source is Natural Earth's Admin 0 Countries layer.  The generated file is
deliberately compact: it retains only identity, label placement, and geometry
needed by the map runtime.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".cache" / "natural_earth" / "ne_110m_admin_0_countries_current.geojson"
OUTPUT = ROOT / "world" / "reference_data" / "earth_countries_reference.json"


def _ring(coordinates):
    return [
        [round(float(point[0]), 4), round(-float(point[1]), 4)]
        for point in coordinates
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]


def _rings(geometry):
    geometry = geometry if isinstance(geometry, dict) else {}
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    source_rings = []
    if geometry_type == "Polygon":
        source_rings = coordinates
    elif geometry_type == "MultiPolygon":
        source_rings = [ring for polygon in coordinates for ring in polygon]
    return [ring for ring in (_ring(points) for points in source_rings) if len(ring) >= 3]


def _country_id(properties):
    code = str(properties.get("ADM0_A3") or properties.get("ISO_A3") or "").strip().lower()
    code = "".join(character for character in code if character.isalnum())
    if not code:
        raise ValueError("Country feature is missing an Admin-0 identifier")
    return f"loc_country_{code}"


def build():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    countries = []
    for feature in source.get("features") or []:
        properties = feature.get("properties") or {}
        polygons = _rings(feature.get("geometry"))
        if not polygons:
            continue
        name = str(properties.get("ADMIN") or properties.get("NAME_EN") or properties.get("NAME") or "").strip()
        if not name:
            continue
        countries.append({
            "id": _country_id(properties),
            "name": name,
            "formal_name": str(properties.get("FORMAL_EN") or "").strip() or None,
            "iso_a2": str(properties.get("ISO_A2") or "").strip() or None,
            "iso_a3": str(properties.get("ADM0_A3") or properties.get("ISO_A3") or "").strip() or None,
            "continent": str(properties.get("CONTINENT") or "").strip() or None,
            "subregion": str(properties.get("SUBREGION") or "").strip() or None,
            "coords": {
                "type": "point",
                "x": round(float(properties.get("LABEL_X", 0.0)), 4),
                "y": round(-float(properties.get("LABEL_Y", 0.0)), 4),
            },
            "bounds": {
                "type": "multipolygon",
                "coordinate_space": "map_world",
                "polygons": polygons,
            },
        })
    countries.sort(key=lambda item: item["name"])
    payload = {
        "schema_version": 1,
        "source": "Natural Earth Admin 0 Countries 1:110m, version 5.1.1",
        "source_url": "https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/",
        "boundary_policy": "Natural Earth de facto boundaries",
        "coordinate_space": "map_world",
        "y_axis": "negative_latitude",
        "countries": countries,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build()
    print(f"Wrote {OUTPUT} ({len(result['countries'])} countries)")
