"""Founding a city on generated terrain.

World generation refines a planet into ``generated_region`` maps whose
``bounds`` live in their parent map's coordinates; their physical size is a
separate fact on the heightmap.  Buildings are placed in metres.  A city is
therefore its own ``site_meters`` location laid over one refined region:

* its ``bounds`` are ``0..width_m`` by ``0..height_m`` of that region;
* ``terrain_source_map_id`` names the region, and every terrain, water,
  climate, soil and material model is read through that link, never copied;
* like the other metre-frame sites it has no structural parent, because a
  parent map would draw its metre bounds in the wrong frame.

The region stays an ordinary worldgen product.  Regenerating it changes the
ground under the city, which ``terrain_is_stale`` reports from the heightfield
fingerprint stored at founding.

See ``docs/city_simulation_concept_v001.md``.
"""

from __future__ import annotations

from simulations.map.worldgen_substrate import LayeredSubstrate, WorldgenSubstrate
from simulations.world_gen.regional_refinement import map_physical_dimensions_m


CITY_LOCATION_CLASS = "city"
CITY_LOCATION_ROLE = "city_simulation_site"
TERRAIN_SOURCE_FIELD = "terrain_source_map_id"

# A town footprint.  LOD4 "Site" regions (0.5-5 km) are the intended ground;
# the limits only reject regions that cannot be walked as one settlement.
MIN_CITY_EXTENT_M = 100.0
MAX_CITY_EXTENT_M = 30_000.0


def _grid_rows(entity):
    grid = ((entity or {}).get("heightmap_model") or {}).get("sample_grid") or {}
    rows = grid.get("rows")
    return rows if isinstance(rows, list) and len(rows) >= 2 and len(rows[0]) >= 2 else None


def _terrain_fingerprint(region):
    heightmap = (region or {}).get("heightmap_model") or {}
    return str(
        heightmap.get("source_heightfield_fingerprint")
        or heightmap.get("input_fingerprint")
        or ""
    )


def founding_report(region):
    """Return ``(can_found, reason)`` for founding a city on ``region``."""

    # Reasons are shown on a sidebar button: keep them to a few words.
    if not isinstance(region, dict):
        return False, "no map open"
    if region.get(TERRAIN_SOURCE_FIELD):
        return False, "already a city"
    if region.get("location_class") != "generated_region":
        return False, "needs a refined region"
    if _grid_rows(region) is None:
        return False, "no generated terrain"
    width_m, height_m = map_physical_dimensions_m(region)
    extent_m = max(width_m, height_m)
    if min(width_m, height_m) < MIN_CITY_EXTENT_M:
        return False, f"region under {MIN_CITY_EXTENT_M:.0f} m"
    if extent_m > MAX_CITY_EXTENT_M:
        return False, f"refine below {MAX_CITY_EXTENT_M / 1000.0:.0f} km"
    return True, ""


def city_bounds_m(region):
    """The city's own frame: the region's physical footprint in metres."""

    width_m, height_m = map_physical_dimensions_m(region)
    return {
        "type": "bbox",
        "min_x": 0.0,
        "max_x": round(float(width_m), 3),
        "min_y": 0.0,
        "max_y": round(float(height_m), 3),
    }


def cities_on_region(world_model, region_id):
    """Cities already founded over ``region_id``."""

    loader = getattr(world_model, "loader", None)
    entities = getattr(loader, "entities", {}) or {}
    return [
        entity for entity in entities.values()
        if isinstance(entity, dict)
        and entity.get(TERRAIN_SOURCE_FIELD) == region_id
        and entity.get("location_class") == CITY_LOCATION_CLASS
    ]


def _allocate_city_id(world_model, region):
    loader = getattr(world_model, "loader", None)
    existing = set(getattr(loader, "entities", {}) or {})
    base = "".join(ch if ch.isalnum() else "_" for ch in str(region.get("id") or "region")).strip("_")
    index = 1
    while f"city_{base}_{index:02d}" in existing:
        index += 1
    return f"city_{base}_{index:02d}", index


def build_city_entity(world_model, region, name=None, year=None):
    """The city location for ``region``, not yet persisted."""

    city_id, index = _allocate_city_id(world_model, region)
    bounds = city_bounds_m(region)
    name = str(name or "").strip() or f"Settlement {index}"
    region_label = region.get("pretty_name") or region.get("name") or region.get("id")
    city = {
        "id": city_id,
        "_dataset": "locations",
        "type": "location",
        "name": name,
        "pretty_name": name,
        "location_class": CITY_LOCATION_CLASS,
        "location_role": CITY_LOCATION_ROLE,
        "map_coordinate_space": "site_meters",
        "map_detail_level": int(region.get("map_detail_level", 0) or 0),
        "map_status": "city founded on generated terrain",
        "bounds": bounds,
        TERRAIN_SOURCE_FIELD: region["id"],
        "terrain_source_fingerprint": _terrain_fingerprint(region),
        "geographic_source_bounds": dict(region.get("bounds") or {}),
        "entry_status": "draft",
        "wiki_entry": (
            f"Founded on {region_label}. The ground is that region's generated "
            f"terrain, {bounds['max_x']:.0f} m by {bounds['max_y']:.0f} m."
        ),
    }
    root_planet_id = region.get("refinement_root_planet_id")
    if root_planet_id:
        city["terrain_root_planet_id"] = root_planet_id
    if region.get("display_color") is not None:
        city["display_color"] = list(region["display_color"])
    if year is not None:
        city["start_year"] = year
    return city


def found_city(world_model, region_id, name=None, year=None):
    """Create and persist a city over ``region_id``.  Returns it or ``None``."""

    region = world_model.get_entity(region_id) if world_model is not None else None
    can_found, _reason = founding_report(region)
    if not can_found:
        return None
    loader = getattr(world_model, "loader", None)
    if loader is None or not hasattr(loader, "persist_entity"):
        return None
    city = build_city_entity(world_model, region, name=name, year=year)
    if not loader.persist_entity(city):
        return None
    return city


def terrain_source_region(world_model, city):
    """The region a city stands on, or ``None`` when it has no usable terrain."""

    if not isinstance(city, dict) or not city.get(TERRAIN_SOURCE_FIELD) or world_model is None:
        return None
    region = world_model.get_entity(city[TERRAIN_SOURCE_FIELD])
    return region if _grid_rows(region) is not None else None


def terrain_is_stale(world_model, city):
    """True when the region was regenerated after the city was founded."""

    region = terrain_source_region(world_model, city)
    if region is None:
        return True
    founded_on = str(city.get("terrain_source_fingerprint") or "")
    return bool(founded_on) and founded_on != _terrain_fingerprint(region)


def refined_patches(world_model, city):
    """Regions refined from the city's ground, coarsest first.

    Returns ``[(region, bounds_m)]`` where ``bounds_m`` is the patch's
    footprint in the city's metres.  These are the finer-LOD patches the Map
    sim composites into the city map; the substrate reads them the same way.
    """

    source = terrain_source_region(world_model, city)
    city_bounds = (city or {}).get("bounds") or {}
    source_bounds = (source or {}).get("bounds") or {}
    if source is None or city_bounds.get("type") != "bbox" or source_bounds.get("type") != "bbox":
        return []
    source_id = source["id"]
    span_x = float(source_bounds["max_x"]) - float(source_bounds["min_x"])
    span_y = float(source_bounds["max_y"]) - float(source_bounds["min_y"])
    if span_x <= 0.0 or span_y <= 0.0:
        return []
    width_m = float(city_bounds["max_x"]) - float(city_bounds["min_x"])
    height_m = float(city_bounds["max_y"]) - float(city_bounds["min_y"])

    def refined_from_source(region):
        visited = set()
        parent_id = region.get("refinement_parent_map_id")
        while parent_id and parent_id not in visited:
            if parent_id == source_id:
                return True
            visited.add(parent_id)
            parent_id = (world_model.get_entity(parent_id) or {}).get("refinement_parent_map_id")
        return False

    patches = []
    loader = getattr(world_model, "loader", None)
    for region in (getattr(loader, "entities", {}) or {}).values():
        if not isinstance(region, dict) or region.get("location_class") != "generated_region":
            continue
        bounds = region.get("bounds") or {}
        if bounds.get("type") != "bbox" or not refined_from_source(region) or _grid_rows(region) is None:
            continue
        patches.append((region, {
            "type": "bbox",
            "min_x": float(city_bounds["min_x"]) + (float(bounds["min_x"]) - float(source_bounds["min_x"])) / span_x * width_m,
            "max_x": float(city_bounds["min_x"]) + (float(bounds["max_x"]) - float(source_bounds["min_x"])) / span_x * width_m,
            "min_y": float(city_bounds["min_y"]) + (float(bounds["min_y"]) - float(source_bounds["min_y"])) / span_y * height_m,
            "max_y": float(city_bounds["min_y"]) + (float(bounds["max_y"]) - float(source_bounds["min_y"])) / span_y * height_m,
        }))
    patches.sort(key=lambda item: (
        int(item[0].get("map_detail_level", 0) or 0),
        int(item[0].get("refinement_revision", 0) or 0),
    ))
    return patches


class CitySubstrate(LayeredSubstrate):
    """The city's ground: the source region, overridden by finer patches where they exist."""


def city_substrate(world_model, city):
    """Physical sampler for a city in its own metre frame, or ``None``."""

    region = terrain_source_region(world_model, city)
    bounds = (city or {}).get("bounds") or {}
    if region is None or bounds.get("type") != "bbox":
        return None
    return CitySubstrate(
        WorldgenSubstrate(region, bounds),
        [(patch_bounds, WorldgenSubstrate(patch, patch_bounds))
         for patch, patch_bounds in refined_patches(world_model, city)],
    )
