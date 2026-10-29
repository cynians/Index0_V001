"""Founding a Biosphere at a point on generated terrain.

World generation refines a planet into ``generated_region`` maps whose
``bounds`` live in their parent map's coordinates.  The Biosphere simulates in
metres.  Like a city (``simulations/city/city_site.py``), a Biosphere site is
therefore its own parentless ``site_meters`` location laid over one refined
region:

* its ``bounds`` are the region's physical footprint, ``0..width_m`` by
  ``0..height_m``, so a city and a Biosphere over the same region share one
  frame;
* ``terrain_source_map_id`` names the region; elevation, water, climate and
  abiotic soil are read through that link, never copied;
* ``biosphere_founding_point_local_m`` is where life starts.  The simulated
  domain begins as a small square around it and grows with the populations.

A Site-level region resolves the ground every few metres, which is too coarse
for a domain that starts ten metres wide.  ``TerrainDetail`` therefore lays a
fixed lattice of chunks over the region and refines one more level, chunk by
chunk, only where the living domain reaches.  Chunks are ordinary persisted
worldgen products; a city founded on the same region reads them too.

See ``docs/biosphere_worldgen_hookup_v001.md``.
"""

from __future__ import annotations

import math

from simulations.city.city_site import TERRAIN_SOURCE_FIELD, refined_patches, terrain_source_region
from simulations.map.worldgen_substrate import LayeredSubstrate, WorldgenSubstrate
from simulations.world_gen.regional_refinement import (
    MAX_DETAIL_LEVEL, MIN_REFINEMENT_STEP, generate_refined_region, map_physical_dimensions_m,
)


BIOSPHERE_SITE_CLASS = "biosphere_patch"
BIOSPHERE_SITE_ROLE = "biosphere_terrain_site"

INITIAL_EXTENT_M = 10.0
# The widest living area one site simulates.  A Site region is a few
# kilometres across; the soil field coarsens to fit rather than refuse.
MAX_DOMAIN_EXTENT_M = 4000.0

# A region must already resolve the ground about this finely before a single
# further refinement step can reach plant scale.  This is the Site level.
MAX_ANCHOR_SPACING_M = 12.0
# Chunks stop refining once the ground is resolved this finely.
TARGET_SPACING_M = 1.0
CHUNK_SIZE_M = 128.0
CHUNK_SAMPLES = 129


def _grid_rows(entity):
    grid = ((entity or {}).get("heightmap_model") or {}).get("sample_grid") or {}
    rows = grid.get("rows")
    return rows if isinstance(rows, list) and len(rows) >= 2 and len(rows[0]) >= 2 else None


def _sample_spacing_m(region):
    rows = _grid_rows(region)
    if rows is None:
        return math.inf
    width_m, height_m = map_physical_dimensions_m(region)
    return max(width_m / max(1, len(rows[0]) - 1), height_m / max(1, len(rows) - 1))


def anchor_region(world_model, entity):
    """The refined region ``entity`` stands on: itself, or its terrain source."""

    if not isinstance(entity, dict):
        return None
    if entity.get(TERRAIN_SOURCE_FIELD):
        return terrain_source_region(world_model, entity)
    if entity.get("location_class") == "generated_region" and _grid_rows(entity) is not None:
        return entity
    return None


def founding_report(world_model, entity):
    """Return ``(can_found, reason)`` for starting a Biosphere on ``entity``'s map."""

    # Reasons are shown on a sidebar button: keep them to a few words.
    if not isinstance(entity, dict):
        return False, "no map open"
    region = anchor_region(world_model, entity)
    if region is None:
        return False, "needs generated terrain"
    width_m, height_m = map_physical_dimensions_m(region)
    if min(width_m, height_m) < INITIAL_EXTENT_M:
        return False, "region too small"
    if _sample_spacing_m(region) > MAX_ANCHOR_SPACING_M:
        return False, "refine to Site first"
    return True, ""


def frame_bounds_m(region):
    """The site's frame: the region's physical footprint in metres."""

    width_m, height_m = map_physical_dimensions_m(region)
    return {
        "type": "bbox",
        "min_x": 0.0, "max_x": round(float(width_m), 3),
        "min_y": 0.0, "max_y": round(float(height_m), 3),
    }


def map_point_to_frame_m(entity, region, map_point):
    """A point picked on ``entity``'s map, in the region's metre frame.

    A terrain-linked map (a city) is already in that frame; a region map is in
    its parent's coordinates and is scaled by its physical size.
    """

    frame = frame_bounds_m(region)
    x, y = float(map_point[0]), float(map_point[1])
    if entity.get(TERRAIN_SOURCE_FIELD):
        point = (x, y)
    else:
        bounds = region.get("bounds") or {}
        span_x = float(bounds["max_x"]) - float(bounds["min_x"])
        span_y = float(bounds["max_y"]) - float(bounds["min_y"])
        point = (
            (x - float(bounds["min_x"])) / span_x * frame["max_x"],
            (y - float(bounds["min_y"])) / span_y * frame["max_y"],
        )
    return (
        max(frame["min_x"], min(frame["max_x"], point[0])),
        max(frame["min_y"], min(frame["max_y"], point[1])),
    )


def sites_on_region(world_model, region_id):
    """Biosphere sites already founded over ``region_id``."""

    loader = getattr(world_model, "loader", None)
    return [
        entity for entity in (getattr(loader, "entities", {}) or {}).values()
        if isinstance(entity, dict)
        and entity.get(TERRAIN_SOURCE_FIELD) == region_id
        and entity.get("location_role") == BIOSPHERE_SITE_ROLE
    ]


def is_terrain_site(entity):
    return (
        isinstance(entity, dict)
        and bool(entity.get(TERRAIN_SOURCE_FIELD))
        and entity.get("location_role") == BIOSPHERE_SITE_ROLE
    )


def _allocate_site_id(world_model, region):
    loader = getattr(world_model, "loader", None)
    existing = set(getattr(loader, "entities", {}) or {})
    base = "".join(ch if ch.isalnum() else "_" for ch in str(region.get("id") or "region")).strip("_")
    index = 1
    while f"biosite_{base}_{index:02d}" in existing:
        index += 1
    return f"biosite_{base}_{index:02d}", index


def _founding_footprint(region, frame, point_m, extent_m=INITIAL_EXTENT_M):
    """The founding square in the region's own map coordinates."""

    source = region.get("bounds") or {}
    span_x = float(source["max_x"]) - float(source["min_x"])
    span_y = float(source["max_y"]) - float(source["min_y"])
    half = extent_m * 0.5
    return {
        "type": "bbox",
        "min_x": float(source["min_x"]) + max(0.0, point_m[0] - half) / frame["max_x"] * span_x,
        "max_x": float(source["min_x"]) + min(frame["max_x"], point_m[0] + half) / frame["max_x"] * span_x,
        "min_y": float(source["min_y"]) + max(0.0, point_m[1] - half) / frame["max_y"] * span_y,
        "max_y": float(source["min_y"]) + min(frame["max_y"], point_m[1] + half) / frame["max_y"] * span_y,
    }


def build_site_entity(world_model, region, point_m, name=None, year=None):
    """The Biosphere site location for ``region``, not yet persisted."""

    site_id, index = _allocate_site_id(world_model, region)
    bounds = frame_bounds_m(region)
    name = str(name or "").strip() or f"Biosphere {index}"
    heightmap = region.get("heightmap_model") or {}
    region_label = region.get("pretty_name") or region.get("name") or region.get("id")
    site = {
        "id": site_id,
        "_dataset": "locations",
        "type": "location",
        "name": name,
        "pretty_name": name,
        "location_class": BIOSPHERE_SITE_CLASS,
        "location_role": BIOSPHERE_SITE_ROLE,
        "map_coordinate_space": "site_meters",
        "map_detail_level": int(region.get("map_detail_level", 0) or 0),
        "map_status": "biosphere founded on generated terrain",
        "bounds": bounds,
        TERRAIN_SOURCE_FIELD: region["id"],
        "terrain_source_fingerprint": str(
            heightmap.get("source_heightfield_fingerprint") or heightmap.get("input_fingerprint") or ""
        ),
        # Parent maps draw this: where on the region life started, not the
        # whole region (a city founded on it already outlines that).
        "geographic_source_bounds": _founding_footprint(region, bounds, point_m),
        "biosphere_founding_point_local_m": [round(float(point_m[0]), 3), round(float(point_m[1]), 3)],
        "biosphere_initial_extent_m": INITIAL_EXTENT_M,
        "biosphere_width_m": bounds["max_x"],
        "biosphere_height_m": bounds["max_y"],
        "entry_status": "draft",
        "wiki_entry": (
            f"Founded on {region_label} at {point_m[0]:.0f} m east, {point_m[1]:.0f} m south "
            "of its north-west corner. The ground, water and climate are that region's "
            "generated terrain."
        ),
    }
    root_planet_id = region.get("refinement_root_planet_id")
    if root_planet_id:
        site["terrain_root_planet_id"] = root_planet_id
    if region.get("display_color") is not None:
        site["display_color"] = list(region["display_color"])
    if year is not None:
        site["start_year"] = year
    return site


def found_biosphere_site(world_model, entity_id, map_point, name=None, year=None):
    """Create and persist a Biosphere site at ``map_point`` of ``entity_id``'s map."""

    entity = world_model.get_entity(entity_id) if world_model is not None else None
    can_found, _reason = founding_report(world_model, entity)
    if not can_found:
        return None
    loader = getattr(world_model, "loader", None)
    if loader is None or not hasattr(loader, "persist_entity"):
        return None
    region = anchor_region(world_model, entity)
    point_m = map_point_to_frame_m(entity, region, map_point)
    site = build_site_entity(world_model, region, point_m, name=name, year=year)
    if not loader.persist_entity(site):
        return None
    return site


def founding_domain(site, extent_m=None):
    """The square the simulation starts in, kept inside the site's frame."""

    frame = site["bounds"]
    width = float(frame["max_x"]) - float(frame["min_x"])
    height = float(frame["max_y"]) - float(frame["min_y"])
    extent = min(float(extent_m or site.get("biosphere_initial_extent_m") or INITIAL_EXTENT_M), width, height)
    point = site.get("biosphere_founding_point_local_m") or (
        (frame["min_x"] + frame["max_x"]) * 0.5, (frame["min_y"] + frame["max_y"]) * 0.5,
    )
    min_x = max(float(frame["min_x"]), min(float(frame["max_x"]) - extent, float(point[0]) - extent * 0.5))
    min_y = max(float(frame["min_y"]), min(float(frame["max_y"]) - extent, float(point[1]) - extent * 0.5))
    return {"min_x": min_x, "max_x": min_x + extent, "min_y": min_y, "max_y": min_y + extent}


def clamp_to_frame(bounds, frame):
    return {
        "min_x": max(float(frame["min_x"]), float(bounds["min_x"])),
        "max_x": min(float(frame["max_x"]), float(bounds["max_x"])),
        "min_y": max(float(frame["min_y"]), float(bounds["min_y"])),
        "max_y": min(float(frame["max_y"]), float(bounds["max_y"])),
    }


def site_substrate(world_model, site):
    """Physical sampler for a site in its metre frame, or ``None``."""

    region = terrain_source_region(world_model, site)
    bounds = (site or {}).get("bounds") or {}
    if region is None or bounds.get("type") != "bbox":
        return None
    # Chunks appear where the player looks closely.  The region stays the
    # climate and the water budget, so looking does not change what grows.
    return LayeredSubstrate(
        WorldgenSubstrate(region, bounds),
        [(patch_bounds, WorldgenSubstrate(patch, patch_bounds))
         for patch, patch_bounds in refined_patches(world_model, site)],
        climate_from_base=True,
        conserved_fields=("soil_moisture",),
    )


class TerrainDetail:
    """Refines the site's ground chunk by chunk, where the living domain needs it."""

    def __init__(self, world_model, site, *, chunk_size_m=CHUNK_SIZE_M, samples=CHUNK_SAMPLES,
                 target_spacing_m=TARGET_SPACING_M):
        self.world_model = world_model
        self.site = site
        self.frame = dict(site["bounds"])
        self.samples = int(samples) | 1  # refinement grids are odd-sized
        self.target_spacing_m = float(target_spacing_m)
        width = float(self.frame["max_x"]) - float(self.frame["min_x"])
        height = float(self.frame["max_y"]) - float(self.frame["min_y"])
        # Whole chunks tile the frame exactly, so no sliver is left at an edge.
        self.columns = max(1, round(width / float(chunk_size_m)))
        self.rows = max(1, round(height / float(chunk_size_m)))
        self.chunk_width_m = width / self.columns
        self.chunk_height_m = height / self.rows
        self.generated = 0

    # -- lattice -------------------------------------------------------
    def chunk_bounds_m(self, key):
        column, row = key
        return {
            "min_x": float(self.frame["min_x"]) + column * self.chunk_width_m,
            "max_x": float(self.frame["min_x"]) + (column + 1) * self.chunk_width_m,
            "min_y": float(self.frame["min_y"]) + row * self.chunk_height_m,
            "max_y": float(self.frame["min_y"]) + (row + 1) * self.chunk_height_m,
        }

    def chunk_keys_for(self, bounds):
        """Lattice cells a metre-frame rectangle touches, nearest its centre first."""

        bounds = clamp_to_frame(bounds, self.frame)
        if bounds["max_x"] <= bounds["min_x"] or bounds["max_y"] <= bounds["min_y"]:
            return []
        eps = 1e-6
        first_column = max(0, int((bounds["min_x"] - self.frame["min_x"]) / self.chunk_width_m + eps))
        last_column = min(self.columns - 1, int((bounds["max_x"] - self.frame["min_x"]) / self.chunk_width_m - eps))
        first_row = max(0, int((bounds["min_y"] - self.frame["min_y"]) / self.chunk_height_m + eps))
        last_row = min(self.rows - 1, int((bounds["max_y"] - self.frame["min_y"]) / self.chunk_height_m - eps))
        center_x = (bounds["min_x"] + bounds["max_x"]) * 0.5
        center_y = (bounds["min_y"] + bounds["max_y"]) * 0.5

        def distance(key):
            chunk = self.chunk_bounds_m(key)
            return math.hypot((chunk["min_x"] + chunk["max_x"]) * 0.5 - center_x,
                              (chunk["min_y"] + chunk["max_y"]) * 0.5 - center_y)

        return sorted(
            ((column, row) for row in range(first_row, last_row + 1)
             for column in range(first_column, last_column + 1)),
            key=lambda key: (distance(key), key),
        )

    # -- state ---------------------------------------------------------
    def region(self):
        return terrain_source_region(self.world_model, self.site)

    def needed(self):
        """False when the region itself already resolves the ground finely enough."""

        region = self.region()
        if region is None:
            return False
        if int(region.get("map_detail_level", 0) or 0) >= MAX_DETAIL_LEVEL:
            return False
        # A chunk is a refinement step of its own: a region closer to the
        # target than a step is as fine as the ground gets here.
        return _sample_spacing_m(region) >= self.target_spacing_m * MIN_REFINEMENT_STEP

    def can_generate(self):
        loader = getattr(self.world_model, "loader", None)
        return self.needed() and loader is not None and hasattr(loader, "persist_entity")

    def _fine_patches(self):
        # Listing refined patches walks every entity; the simulation asks each frame.
        entities = getattr(getattr(self.world_model, "loader", None), "entities", None)
        key = (id(entities), len(entities) if entities is not None else 0,
               getattr(self.world_model, "repository_revision", 0), self.generated)
        cached = getattr(self, "_fine_patches_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, [
                patch_bounds for patch, patch_bounds in refined_patches(self.world_model, self.site)
                if _sample_spacing_m(patch) <= self.target_spacing_m * 1.5
            ])
            self._fine_patches_cache = cached
        return cached[1]

    def chunk_key_at(self, x, y):
        """The lattice cell containing a point of the frame, or ``None`` outside it."""
        if not (self.frame["min_x"] <= x <= self.frame["max_x"] and self.frame["min_y"] <= y <= self.frame["max_y"]):
            return None
        return (
            min(self.columns - 1, int((x - self.frame["min_x"]) / self.chunk_width_m)),
            min(self.rows - 1, int((y - self.frame["min_y"]) / self.chunk_height_m)),
        )

    def missing(self, bounds):
        """Chunks under ``bounds`` that no fine patch covers yet."""

        if not self.needed():
            return []
        return [key for key in self.chunk_keys_for(bounds) if not self.covered(key)]

    def covered(self, key):
        """True when a fine patch already resolves the whole chunk."""
        chunk = self.chunk_bounds_m(key)
        tolerance = 0.25
        return any(
            patch["min_x"] <= chunk["min_x"] + tolerance and patch["max_x"] >= chunk["max_x"] - tolerance
            and patch["min_y"] <= chunk["min_y"] + tolerance and patch["max_y"] >= chunk["max_y"] - tolerance
            for patch in self._fine_patches()
        )

    def summary(self, bounds):
        region = self.region() or {}
        level = int(region.get("map_detail_level", 0) or 0)
        keys = self.chunk_keys_for(bounds)
        missing = self.missing(bounds)
        return {
            "region_level": level,
            "region_label": (region.get("map_detail_profile") or {}).get("label") or f"LOD {level}",
            "region_spacing_m": _sample_spacing_m(region) if region else None,
            "chunk_size_m": (self.chunk_width_m, self.chunk_height_m),
            "chunks_in_domain": len(keys),
            "chunks_missing": len(missing),
            "target_spacing_m": self.target_spacing_m,
            "needed": self.needed(),
            "can_generate": self.can_generate(),
        }

    # -- generation ----------------------------------------------------
    def generate(self, key, progress_callback=None, storage_root=None):
        """Refine one chunk from the region and persist it.  Returns the new region."""

        region = self.region()
        if region is None or not self.can_generate():
            return None
        source_bounds = region.get("bounds") or {}
        if source_bounds.get("type") != "bbox":
            return None
        chunk = self.chunk_bounds_m(key)
        frame_width = float(self.frame["max_x"]) - float(self.frame["min_x"])
        frame_height = float(self.frame["max_y"]) - float(self.frame["min_y"])
        scale_x = (float(source_bounds["max_x"]) - float(source_bounds["min_x"])) / frame_width
        scale_y = (float(source_bounds["max_y"]) - float(source_bounds["min_y"])) / frame_height
        child_bounds = {
            "min_x": float(source_bounds["min_x"]) + (chunk["min_x"] - float(self.frame["min_x"])) * scale_x,
            "max_x": float(source_bounds["min_x"]) + (chunk["max_x"] - float(self.frame["min_x"])) * scale_x,
            "min_y": float(source_bounds["min_y"]) + (chunk["min_y"] - float(self.frame["min_y"])) * scale_y,
            "max_y": float(source_bounds["min_y"]) + (chunk["max_y"] - float(self.frame["min_y"])) * scale_y,
        }
        generated = generate_refined_region(
            self.world_model,
            dict(region),
            child_bounds,
            sample_dimensions=(self.samples, self.samples),
            storage_root=storage_root,
            progress_callback=progress_callback,
        )
        if isinstance(generated, dict):
            self.generated += 1
        return generated
