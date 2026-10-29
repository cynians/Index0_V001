"""Stress the ground-water systems on real and awkward ground, without touching the store.

What is stressed: the fine hydrology's water table, run-on and floods, the
soil's water figures, the Biosphere's water balance, the "what grows here"
solver and a Biosphere opened on the ground's flora
(``docs/biosphere_worldgen_hookup_v001.md`` sections 3.3 and 3.7).

Everything runs look-only.  Maps are refined in memory with the generator as
it is now and kept as files under ``artifacts/stress_ground_water`` (a cache:
delete it at will); nothing is written to the ontology.  One subcommand is one
short burst.

    make NAME --parent ID_OR_NAME [--share CX CY W H | --where river|coast|centre --size-m W H]
    make NAME --rebuild STORED_ID          the same footprint, by the generator as it is now
    check NAME [NAME ...]                  invariants, and a child against its parent
    climates NAME                          eight climates laid over one map's ground
    play NAME [--years N]                  a Biosphere opened at telling points, played with its residents
    extremes                               the arithmetic on ground no map would hand over

``NAME`` is a case made here; a stored map's id works wherever a name does.
"""

from __future__ import annotations

import argparse
import math
import os
import pickle
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np  # noqa: E402

STATE = PROJECT_ROOT / "artifacts" / "stress_ground_water"
ROOTING_DEPTHS_M = (0.35, 1.0, 2.0)
WETNESS_CLASSES = ((0.14, "very dry"), (0.31, "dry"), (0.50001, "mesic"), (0.68, "moist"), (0.85, "wet"), (9.0, "sodden"))
# Climates to lay over a map's ground: rain and demand in mm, the driest and wettest month, the share of rain
# that falls in summer, the coldest and warmest month in degrees, and the zone they would be called.
CLIMATES = (
    ("hyper-arid", 40, 2600, 0, 12, 0.5, 18, 36, "BWh", "Hot Desert"),
    ("steppe", 320, 1200, 12, 45, 0.6, -6, 24, "BSk", "Cold Steppe"),
    ("mediterranean", 520, 1150, 4, 95, 0.15, 8, 26, "Csa", "Mediterranean"),
    ("temperate", 750, 700, 48, 78, 0.5, 2, 18, "Cfb", "Temperate Oceanic"),
    ("oceanic wet", 2400, 700, 150, 260, 0.4, 5, 15, "Cfb", "Temperate Oceanic"),
    ("monsoon", 1800, 1700, 5, 420, 0.9, 20, 30, "Am", "Tropical Monsoon"),
    ("boreal", 450, 380, 22, 60, 0.6, -22, 15, "Dfc", "Subarctic"),
    ("tundra", 250, 250, 10, 35, 0.6, -28, 7, "ET", "Tundra"),
)


# ----------------------------------------------------------------------------------------------------
# A world nothing is written from, and the cases kept beside it
# ----------------------------------------------------------------------------------------------------
def open_world():
    from world.world_model import WorldModel

    world = WorldModel()
    world.loader.use_ontology = False
    world.loader.save_changed_dataset_files = lambda *args, **kwargs: None
    # Cases made here stand before what the store holds under the same id (a map made again in place).
    cases, hidden, stored = {}, set(), world.get_entity
    world.get_entity = lambda entity_id: None if entity_id in hidden else (cases.get(entity_id) or stored(entity_id))
    world.stress_cases, world.stress_hidden = cases, hidden
    return world


def case_path(name):
    return STATE / "cases" / f"{name}.pickle"


def entity_of(world, name, _seen=None):
    """A stored map or a case made here, known to ``world`` (in memory) with the cases it was refined from."""
    path = case_path(name)
    if not path.exists():
        entity = world.get_entity(name)
        if entity is None:
            raise SystemExit(f"{name}: neither a stored map nor a case under {path.parent}")
        return entity
    with open(path, "rb") as handle:
        case = pickle.load(handle)
    parent = case.get("parent")
    if parent and case_path(parent).exists() and parent not in (_seen or ()):
        entity_of(world, parent, (_seen or ()) + (name,))
    world.loader.persist_entity(case["entity"])
    world.stress_cases[case["entity"]["id"]] = case["entity"]
    return case["entity"]


def rows_of(entity):
    rows = ((entity.get("heightmap_model") or {}).get("sample_grid") or {}).get("rows") or []
    return np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)


def size_m(entity):
    from simulations.world_gen.regional_refinement import map_physical_dimensions_m

    return map_physical_dimensions_m(entity)


def substrate_of(entity):
    from simulations.biosphere import terrain_site
    from simulations.map.worldgen_substrate import WorldgenSubstrate

    return WorldgenSubstrate(entity, terrain_site.frame_bounds_m(entity))


def lattice(entity, cells=96):
    from simulations.biosphere import terrain_site

    frame = terrain_site.frame_bounds_m(entity)
    width, height = frame["max_x"] - frame["min_x"], frame["max_y"] - frame["min_y"]
    columns = max(2, round(cells * width / max(width, height)))
    rows = max(2, round(cells * height / max(width, height)))
    return np.meshgrid(frame["min_x"] + (np.arange(columns) + 0.5) * width / columns,
                       frame["min_y"] + (np.arange(rows) + 0.5) * height / rows), frame


# ----------------------------------------------------------------------------------------------------
# make
# ----------------------------------------------------------------------------------------------------
def _window_shares(parent, where, size):
    """Centre and size of a footprint on ``parent`` as shares of its extent, placed by what it should hold."""
    width_m, height_m = size_m(parent)
    share_w, share_h = min(0.9, size[0] / width_m), min(0.9, size[1] / height_m)
    if where == "centre":
        return 0.5, 0.5, share_w, share_h
    elevation = rows_of(parent)
    water = parent.get("water_cycle_model") or {}
    presence = np.asarray((water.get("surface_water_grid") or {}).get("water_presence_rows") or np.zeros(elevation.shape), dtype=bool)
    if presence.shape != elevation.shape:
        # An older map keeps its water on a lattice of its own.
        rows = np.clip(np.rint(np.linspace(0, presence.shape[0] - 1, elevation.shape[0])).astype(int), 0, presence.shape[0] - 1)
        columns = np.clip(np.rint(np.linspace(0, presence.shape[1] - 1, elevation.shape[1])).astype(int), 0, presence.shape[1] - 1)
        presence = presence[np.ix_(rows, columns)]
    sea = (parent.get("heightmap_model") or {}).get("sea_level_m")
    sea_cells = elevation <= float(sea) if sea is not None else np.zeros(elevation.shape, dtype=bool)
    best = None
    for cy in np.linspace(0.5 * share_h + 0.06, 1.0 - 0.5 * share_h - 0.06, 14):
        for cx in np.linspace(0.5 * share_w + 0.06, 1.0 - 0.5 * share_w - 0.06, 22):
            r0, r1 = int((cy - share_h / 2) * elevation.shape[0]), int((cy + share_h / 2) * elevation.shape[0]) + 1
            c0, c1 = int((cx - share_w / 2) * elevation.shape[1]), int((cx + share_w / 2) * elevation.shape[1]) + 1
            sea_share = float(sea_cells[r0:r1, c0:c1].mean())
            wet_share = float((presence[r0:r1, c0:c1] & ~sea_cells[r0:r1, c0:c1]).mean())
            # A coast: about a third sea.  A river: fresh water in it, as little sea as may be.
            score = -abs(sea_share - 0.35) if where == "coast" else min(wet_share, 0.2) - sea_share
            if best is None or score > best[0]:
                best = (score, float(cx), float(cy))
    return best[1], best[2], share_w, share_h


def cmd_make(args):
    from simulations.world_gen.regional_refinement import generate_refined_region

    world = open_world()
    if args.rebuild:
        stored = world.get_entity(args.rebuild)
        parent = world.get_entity(stored["refinement_parent_map_id"])
        bounds, parent_name = dict(stored["bounds"]), parent["id"]
        # With nothing written, the refinement would hand back the stored map's own models under its id.
        world.stress_hidden.add(args.rebuild)
    else:
        parent, parent_name = entity_of(world, args.parent), args.parent
        cx, cy, share_w, share_h = args.share if args.share else _window_shares(parent, args.where, args.size_m)
        b = parent["bounds"]
        width, height = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
        bounds = {"type": "bbox", "min_x": b["min_x"] + (cx - share_w / 2) * width, "max_x": b["min_x"] + (cx + share_w / 2) * width,
                  "min_y": b["min_y"] + (cy - share_h / 2) * height, "max_y": b["min_y"] + (cy + share_h / 2) * height}
        print(f"footprint on {parent_name}: centre {cx:.3f}, {cy:.3f} of its extent, {share_w:.3f} x {share_h:.3f}")
    (STATE / "rasters").mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    region = generate_refined_region(world, parent, bounds, allow_intermediate=False, storage_root=str(STATE / "rasters"))
    elapsed = time.perf_counter() - started
    case_path(args.name).parent.mkdir(parents=True, exist_ok=True)
    with open(case_path(args.name), "wb") as handle:
        pickle.dump({"entity": dict(region), "parent": parent_name, "seconds": elapsed}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    width_m, height_m = size_m(region)
    grid = rows_of(region)
    print(f"made {args.name} = {region['id']} (level {region.get('map_detail_level')}) in {elapsed:.0f} s: "
          f"{width_m:.0f} x {height_m:.0f} m, {grid.shape[1]} x {grid.shape[0]} cells of {width_m / max(1, grid.shape[1] - 1):.2f} m, "
          f"relief {np.ptp(grid):.1f} m; kept in {case_path(args.name).stat().st_size / 1e6:.0f} MB")


# ----------------------------------------------------------------------------------------------------
# check
# ----------------------------------------------------------------------------------------------------
class Findings:
    def __init__(self, name):
        self.name, self.failed = name, []

    def expect(self, holds, text):
        if not holds:
            self.failed.append(text)
            print(f"   !! {text}")


def _raster(grid, name):
    values = (grid or {}).get(name)
    try:
        return None if not values else np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError):
        return None


def _shares(values, mask):
    classes, low = [], -1.0
    for high, label in WETNESS_CLASSES:
        classes.append(f"{label} {float(((values >= low) & (values < high))[mask].mean()):.2f}")
        low = high
    return ", ".join(classes)


def _test_floras(world, biomes):
    """The planet-independent flora of the stress runs: Biosim World's woodland and wetland lists on every biome."""
    from simulations.biosphere.flora import BiomeFlora, planet_floras

    source = planet_floras(world, "planet_biosim_world")
    dry, wet = source.get("Cfb") or source.get("Cfa/montane"), source.get("Cfb/wetland") or source.get("Cfa/wetland/montane")
    floras = {}
    for biome in biomes:
        flora = BiomeFlora("planet_stress", biome)
        for species_id in (wet if biome.water else dry).species():
            flora.record(species_id, (wet if biome.water else dry).rarity(species_id))
        floras[biome.key] = flora
    return floras


def wetness_at(substrate, x, y):
    """Wetness for roots of each of ``ROOTING_DEPTHS_M`` at points of a substrate, or ``None`` where it tells no demand."""
    from simulations.biosphere import water_balance as wb
    from simulations.map.worldgen_substrate import WATER_BALANCE_FIELDS

    sampled = {key: np.asarray(substrate.sample_array(key, x, y, np.nan), dtype=np.float64) for key in WATER_BALANCE_FIELDS}
    demand = sampled["annual_potential_evaporation_mm"]
    if not np.isfinite(demand).any():
        return None

    def read(key, default=np.nan):
        return np.asarray(substrate.sample_array(key, x, y, default), dtype=np.float64)

    def filled(key, default):
        return np.nan_to_num(sampled[key], nan=default)

    ground = {
        "rain": wb.monthly_rain(read("annual_precipitation_mm", 0.0), sampled["driest_month_precipitation_mm"],
                                sampled["wettest_month_precipitation_mm"], sampled["summer_precipitation_fraction"]),
        "demand": wb.monthly_demand(np.nan_to_num(demand), read("coldest_month_temperature_k"), read("warmest_month_temperature_k"),
                                    np.nan_to_num(read("surface_solar_exposure", 1.0), nan=1.0)),
        "available_water_mm_per_m": filled("available_water_mm_per_m", wb.DEFAULT_AVAILABLE_WATER_MM_PER_M),
        "rootable_depth_m": np.where(np.isfinite(sampled["rootable_depth_m"]), sampled["rootable_depth_m"], read("soil_depth_m")),
        "lateral_mm": filled("lateral_water_mm", 0.0), "capillary_rise_m": filled("capillary_rise_m", wb.DEFAULT_CAPILLARY_RISE_M),
        "water_table_depth_m": sampled["water_table_depth_m"],
    }
    if substrate.fields.get("drainage_mm_per_day") is not None:
        ground["drainage_mm_per_day"] = filled("drainage_mm_per_day", np.inf)
    return {depth_m: wb.plant_wetness(ground, depth_m) for depth_m in ROOTING_DEPTHS_M}


def ground_report(world, entity, findings, cells=96, quiet=False):
    """Invariants of one map's rasters and what its consumers make of them; returns figures to compare by."""
    from simulations.biosphere import water_balance as wb
    from simulations.biosphere.biomes import biome_grid
    from simulations.biosphere.potential_vegetation import resident_vegetation
    from simulations.city.city_vegetation import _profiles
    from simulations.map.worldgen_substrate import FLOOD_FIELDS, WATER_BALANCE_FIELDS

    say = (lambda *_args: None) if quiet else print
    water_model = entity.get("water_cycle_model") or {}
    runoff, surface = water_model.get("runoff_grid") or {}, water_model.get("surface_water_grid") or {}
    soil = (entity.get("regolith_soil_model") or {}).get("grid") or {}
    presence = np.asarray(surface.get("water_presence_rows") or [[False]], dtype=bool)
    land = ~presence
    width_m, height_m = size_m(entity)
    say(f"   level {entity.get('map_detail_level')}, {width_m:.0f} x {height_m:.0f} m, {presence.shape[1]} x {presence.shape[0]} cells, "
        f"open water {float(presence.mean()):.3f}")
    figures = {}

    table, lateral = _raster(runoff, "water_table_depth_m_rows"), _raster(runoff, "lateral_water_rows_mm")
    if table is None:
        say("   no water table on this map (coarser than Site, or made before it was reckoned)")
    else:
        findings.expect(np.isfinite(table).all() and (table >= 0).all() and (table <= 99.0).all(), "water table depth out of range or not finite")
        findings.expect(float(table[presence].max(initial=0.0)) == 0.0, "water table below the surface under open water")
        findings.expect(np.isfinite(lateral).all(), "run-on not finite")
        if land.any():
            findings.expect(abs(float(np.median(lateral[land]))) <= 1.0, f"ordinary ground's run-on is not nought ({np.median(lateral[land]):.1f} mm)")
            say(f"   water table on land p05/50/95: {np.percentile(table[land], [5, 50, 95]).round(2)} m; within 0.3 / 1 / 2 m: "
                f"{[round(float((table[land] <= depth).mean()), 3) for depth in (0.3, 1.0, 2.0)]}; run-on p95 {np.percentile(lateral[land], 95):.0f} mm")
            figures["table_median"] = float(np.median(table[land]))
            figures["wetland_share"] = float((table[land] <= 0.3).mean())
    covered, reworked = _raster(surface, "flood_return_period_rows_years"), _raster(surface, "flood_reworking_return_period_rows_years")
    if covered is None:
        say("   no floods told (no carved channel on it, or made before)")
    else:
        findings.expect(np.isfinite(covered).all() and np.isfinite(reworked).all(), "flood returns not finite")
        findings.expect((reworked >= covered - 1e-9).all(), "ground reworked more often than it is covered")
        findings.expect((covered[land] >= 0.1 - 1e-9).all() and (covered <= 999.0).all(), "flood returns out of range")
        findings.expect(float(covered[presence].max(initial=0.0)) == 0.0, "open water not always covered")
        say(f"   floods: land covered within 2 / 10 / 100 y {[round(float((covered[land] <= years).mean()), 3) for years in (2, 10, 100)]}, "
            f"reworked {[round(float((reworked[land] <= years).mean()), 3) for years in (2, 10, 100)]}")
        figures["covered_10"] = float((covered[land] <= 10).mean())
    for name, low, high in (("available_water_capacity_rows_mm_per_m", 70.0, 190.0), ("capillary_rise_rows_m", 0.1, 2.0),
                            ("drainage_rate_rows_mm_per_day", 0.05, 1000.0)):
        values = _raster(soil, name)
        if values is None:
            say(f"   soil carries no {name}")
            continue
        findings.expect(np.isfinite(values).all() and (values >= low - 1e-6).all() and (values <= high + 1e-6).all(),
                        f"{name} out of {low}..{high}: {np.nanmin(values):.3f}..{np.nanmax(values):.3f}")
    rootable, depth = _raster(soil, "rootable_depth_m_rows"), _raster(soil, "soil_depth_m_rows")
    if rootable is not None and depth is not None:
        findings.expect((rootable >= depth - 1e-3).all(), "ground rootable to less than its soil is deep")

    # What the consumers read.
    (x, y), frame = lattice(entity, cells)
    substrate = substrate_of(entity)
    started = time.perf_counter()
    sampled = {key: np.asarray(substrate.sample_array(key, x, y, np.nan), dtype=np.float64) for key in WATER_BALANCE_FIELDS + FLOOD_FIELDS}
    open_water = np.asarray(substrate.open_water_array(x, y), dtype=bool)
    dry = ~open_water
    for key, values in sampled.items():
        if substrate.fields.get(key) is not None:
            findings.expect(np.isfinite(values).all(), f"substrate hands over {key} with gaps ({int((~np.isfinite(values)).sum())} points)")
    demand = sampled["annual_potential_evaporation_mm"]
    if not np.isfinite(demand).any():
        say("   the map tells no demand of the air: the Biosphere reads its wetness index")
        return figures
    coldest = np.asarray(substrate.sample_array("coldest_month_temperature_k", x, y, np.nan), dtype=np.float64)
    warmest = np.asarray(substrate.sample_array("warmest_month_temperature_k", x, y, np.nan), dtype=np.float64)
    rain = np.asarray(substrate.sample_array("annual_precipitation_mm", x, y, 0.0), dtype=np.float64)

    def filled(key, default):
        return np.nan_to_num(sampled[key], nan=default)

    ground = {
        "rain": wb.monthly_rain(rain, sampled["driest_month_precipitation_mm"], sampled["wettest_month_precipitation_mm"],
                                sampled["summer_precipitation_fraction"]),
        "demand": wb.monthly_demand(np.nan_to_num(demand), coldest, warmest,
                                    np.nan_to_num(np.asarray(substrate.sample_array("surface_solar_exposure", x, y, 1.0), dtype=np.float64), nan=1.0)),
        "available_water_mm_per_m": filled("available_water_mm_per_m", wb.DEFAULT_AVAILABLE_WATER_MM_PER_M),
        "rootable_depth_m": np.where(np.isfinite(sampled["rootable_depth_m"]), sampled["rootable_depth_m"],
                                     np.asarray(substrate.sample_array("soil_depth_m", x, y, np.nan), dtype=np.float64)),
        "lateral_mm": filled("lateral_water_mm", 0.0), "capillary_rise_m": filled("capillary_rise_m", wb.DEFAULT_CAPILLARY_RISE_M),
        "water_table_depth_m": sampled["water_table_depth_m"],
    }
    if substrate.fields.get("drainage_mm_per_day") is not None:
        ground["drainage_mm_per_day"] = filled("drainage_mm_per_day", np.inf)
    wetness = {}
    for depth_m in ROOTING_DEPTHS_M:
        wet = wb.plant_wetness(ground, depth_m)
        findings.expect(np.isfinite(wet).all() and (wet >= 0).all() and (wet <= wb.SODDEN_WETNESS + 1e-9).all(),
                        f"wetness for roots {depth_m} m out of range")
        wetness[depth_m] = wet
    findings.expect((wetness[2.0][dry] >= wetness[0.35][dry] - 0.05).mean() > 0.98 if dry.any() else True,
                    "deeper roots meet drier ground than shallow ones on more than 2 % of the land")
    if dry.any():
        say(f"   rain {np.nanmean(rain):.0f} mm against {np.nanmean(demand):.0f} mm; wetness for a herb: {_shares(wetness[0.35], dry)}")
        say(f"   for a tree: {_shares(wetness[2.0], dry)}")
        figures.update(herb=float(np.median(wetness[0.35][dry])), tree=float(np.median(wetness[2.0][dry])),
                       above_fresh=float((wetness[0.35][dry] > wb.FRESH_WETNESS + 1e-6).mean()))
    index, biomes = biome_grid(substrate, x, y)
    floras = _test_floras(world, biomes)
    profiles = _profiles(world, floras)
    vegetation = resident_vegetation(substrate, frame, profiles, floras, cells=cells, seed=7)
    layers = {}
    for species_id, cover in vegetation.cover.items():
        findings.expect(np.isfinite(cover).all() and (cover >= -1e-9).all() and (cover <= 1.0 + 1e-9).all(), f"cover of {species_id} out of 0..1")
        layers.setdefault(vegetation.layers[species_id], np.zeros(cover.shape))
        layers[vegetation.layers[species_id]] += cover
    for layer, cover in layers.items():
        if layer != "climber":
            findings.expect(float(cover.max()) <= 1.0 + 1e-6, f"the {layer} layer covers more than the ground ({cover.max():.3f})")
    total = sum(layers.values()) if layers else np.zeros(x.shape)
    land_lattice = ~np.asarray(substrate.open_water_array(vegetation.x, vegetation.y), dtype=bool)
    if land_lattice.any():
        top = sorted(vegetation.cover, key=lambda species_id: -float(vegetation.cover[species_id][land_lattice].mean()))[:4]
        say(f"   biomes: {', '.join(f'{biome.key} {float((index == number).mean()):.2f}' for number, biome in enumerate(biomes))}")
        say(f"   solver ({time.perf_counter() - started:.1f} s with sampling): canopy {float(layers.get('canopy', total * 0)[land_lattice].mean()):.2f}, "
            f"field {float(layers.get('field', total * 0)[land_lattice].mean()):.2f}, bare {float((total < 0.05)[land_lattice].mean()):.2f}; "
            + ", ".join(f"{species_id.replace('spec_', '')} {float(vegetation.cover[species_id][land_lattice].mean()):.2f}" for species_id in top))
        figures.update(canopy=float(layers.get("canopy", total * 0)[land_lattice].mean()), bare=float((total < 0.05)[land_lattice].mean()))
    figures["_sampled"] = (x, y, sampled, wetness, open_water)
    return figures


def against_parent(world, child, parent, findings):
    """The child's ground read at the child's lattice from both maps: what a level adds may not move its parent's mean."""
    from simulations.biosphere import terrain_site

    child_frame, parent_frame = terrain_site.frame_bounds_m(child), terrain_site.frame_bounds_m(parent)
    cb, pb = child["bounds"], parent["bounds"]
    (x, y), _frame = lattice(child, 64)
    # The same points in the parent's metre frame, through the map coordinates both are refined in.
    u = cb["min_x"] + (x - child_frame["min_x"]) / (child_frame["max_x"] - child_frame["min_x"]) * (cb["max_x"] - cb["min_x"])
    v = cb["min_y"] + (y - child_frame["min_y"]) / (child_frame["max_y"] - child_frame["min_y"]) * (cb["max_y"] - cb["min_y"])
    px = parent_frame["min_x"] + (u - pb["min_x"]) / (pb["max_x"] - pb["min_x"]) * (parent_frame["max_x"] - parent_frame["min_x"])
    py = parent_frame["min_y"] + (v - pb["min_y"]) / (pb["max_y"] - pb["min_y"]) * (parent_frame["max_y"] - parent_frame["min_y"])
    own, above = substrate_of(child), substrate_of(parent)
    land = ~np.asarray(own.open_water_array(x, y), dtype=bool) & ~np.asarray(above.open_water_array(px, py), dtype=bool)
    if not land.any():
        return
    print(f"   against its parent {parent['id']} at the same {int(land.sum())} points of land:")
    for key, tolerance, unit in (("elevation_m", 0.5, "m"), ("water_table_depth_m", 0.5, "m"), ("available_water_mm_per_m", 15.0, "mm/m"),
                                 ("capillary_rise_m", 0.15, "m"), ("drainage_mm_per_day", None, "mm/day"), ("rootable_depth_m", 0.5, "m"),
                                 ("lateral_water_mm", None, "mm"), ("flood_return_period_years", None, "y"),
                                 ("flood_reworking_return_period_years", None, "y")):
        if own.fields.get(key) is None or above.fields.get(key) is None:
            print(f"      {key}: {'child has none' if own.fields.get(key) is None else 'parent has none'}")
            continue
        mine = np.asarray(own.sample_array(key, x, y, np.nan), dtype=np.float64)[land]
        theirs = np.asarray(above.sample_array(key, px, py, np.nan), dtype=np.float64)[land]
        if key.startswith("flood_"):
            agree = float(((mine <= 10.0) == (theirs <= 10.0)).mean())
            print(f"      {key}: within ten years on {float((mine <= 10).mean()):.3f} of it here, {float((theirs <= 10).mean()):.3f} by the parent; "
                  f"the two agree on {agree:.3f}")
            findings.expect(agree >= 0.9, f"{key}: child and parent disagree on a tenth of the ground or more ({agree:.2f})")
            continue
        if key == "drainage_mm_per_day":
            mine, theirs, unit = np.log10(mine), np.log10(theirs), "decades"
        difference = mine - theirs
        print(f"      {key}: mean {np.mean(mine):.2f} here, {np.mean(theirs):.2f} by the parent ({unit}); "
              f"difference mean {np.mean(difference):+.2f}, p05 {np.percentile(difference, 5):+.2f}, p95 {np.percentile(difference, 95):+.2f}")
        if tolerance is not None:
            findings.expect(abs(float(np.mean(difference))) <= tolerance,
                            f"{key}: the child's mean is {np.mean(difference):+.2f} {unit} off its parent's over the same ground")
    # What it comes to for a plant: looking closer may sharpen where things grow, not change how wet the ground is.
    mine, theirs = wetness_at(own, x, y), wetness_at(above, px, py)
    if mine is None or theirs is None:
        return
    edges = [high for high, _label in WETNESS_CLASSES]
    for depth_m in (ROOTING_DEPTHS_M[0], ROOTING_DEPTHS_M[-1]):
        here, there = mine[depth_m][land], theirs[depth_m][land]
        same = float((np.digitize(here, edges) == np.digitize(there, edges)).mean())
        print(f"      wetness for roots {depth_m} m: mean {np.mean(here):.3f} here, {np.mean(there):.3f} by the parent; "
              f"above fresh on {float((here > 0.5001).mean()):.3f} against {float((there > 0.5001).mean()):.3f}; same class on {same:.2f}")
        findings.expect(abs(float(np.mean(here) - np.mean(there))) <= 0.03,
                        f"wetness for roots {depth_m} m: the child's mean is {np.mean(here) - np.mean(there):+.3f} off its parent's")


def cmd_check(args):
    world = open_world()
    failed = 0
    for name in args.names:
        entity = entity_of(world, name)
        findings = Findings(name)
        print(f"== {name} ({entity['id']})")
        ground_report(world, entity, findings)
        parent = world.get_entity(entity.get("refinement_parent_map_id") or "")
        if parent is not None and int(parent.get("map_detail_level") or 0) >= 4:
            against_parent(world, entity, parent, findings)
        print(f"   {'no finding' if not findings.failed else str(len(findings.failed)) + ' finding(s)'}")
        failed += len(findings.failed)
    return 1 if failed else 0


# ----------------------------------------------------------------------------------------------------
# climates
# ----------------------------------------------------------------------------------------------------
def _budyko_surplus(rain, demand):
    """What a year's rain leaves over (Budyko 1974): for the runoff and recharge of a climate laid over a map."""
    dryness = demand / max(rain, 1e-6)
    used = math.sqrt(dryness * math.tanh(1.0 / max(dryness, 1e-6)) * (1.0 - math.exp(-dryness)))
    return rain * (1.0 - min(1.0, used))


def under_climate(entity, climate):
    """A copy of a map with a climate laid over its ground and its fine hydrology read again (in memory)."""
    from simulations.world_gen.fine_hydrology import refine_surface_hydrology

    _name, rain, demand, driest, wettest, summer, coldest, warmest, zone, label = climate
    water = dict(entity["water_cycle_model"])
    grid = dict(water["climate_grid"])
    shape = np.asarray(grid["annual_precipitation_rows_mm"], dtype=np.float64).shape
    surplus = _budyko_surplus(rain, demand)

    def flat(value):
        return np.full(shape, value).tolist()

    grid.update(
        annual_precipitation_rows_mm=flat(rain), annual_potential_evaporation_rows_mm=flat(demand),
        annual_evapotranspiration_rows_mm=flat(rain - surplus), annual_runoff_rows_mm=flat(0.65 * surplus),
        annual_groundwater_recharge_rows_mm=flat(0.35 * surplus), driest_month_precipitation_rows_mm=flat(driest),
        wettest_month_precipitation_rows_mm=flat(wettest), summer_precipitation_fraction_rows=flat(summer),
        temperature_rows_k=flat(273.15 + 0.5 * (coldest + warmest)), seasonal_min_temperature_rows_k=flat(273.15 + coldest),
        seasonal_max_temperature_rows_k=flat(273.15 + warmest), koppen_rows=[[zone] * shape[1] for _row in range(shape[0])],
    )
    water["climate_grid"] = grid
    water["koppen_classes"] = [{"id": zone, "label": label}]
    return dict(entity, water_cycle_model=refine_surface_hydrology(entity["heightmap_model"], water))


def cmd_climates(args):
    world = open_world()
    entity = entity_of(world, args.name)
    print(f"== {args.name} ({entity['id']}): eight climates over the same ground")
    print(f"   {'climate':14s} {'rain':>5s} {'demand':>6s} {'recharge':>8s} | {'table':>6s} {'<0.3m':>6s} | {'herb':>5s} {'tree':>5s} {'>fresh':>6s} | "
          f"{'canopy':>6s} {'bare':>5s} | seconds")
    failed, rows = 0, []
    for climate in CLIMATES:
        findings = Findings(climate[0])
        started = time.perf_counter()
        figures = ground_report(world, under_climate(entity, climate), findings, cells=72, quiet=True)
        recharge = 0.35 * _budyko_surplus(climate[1], climate[2])
        rows.append((climate, figures))
        print(f"   {climate[0]:14s} {climate[1]:5.0f} {climate[2]:6.0f} {recharge:8.0f} | {figures.get('table_median', float('nan')):6.2f} "
              f"{figures.get('wetland_share', float('nan')):6.3f} | {figures.get('herb', float('nan')):5.2f} {figures.get('tree', float('nan')):5.2f} "
              f"{figures.get('above_fresh', float('nan')):6.3f} | {figures.get('canopy', float('nan')):6.2f} {figures.get('bare', float('nan')):5.2f} | "
              f"{time.perf_counter() - started:.1f}" + ("" if not findings.failed else f"   !! {'; '.join(findings.failed)}"))
        failed += len(findings.failed)
    # More recharge may not sink the water table; and among climates whose rain is spread over the year, more
    # rain against demand may not dry the ground (a monsoon's dry season is another matter).
    by_recharge = sorted(rows, key=lambda row: _budyko_surplus(row[0][1], row[0][2]))
    for (less, a), (more, b) in zip(by_recharge, by_recharge[1:]):
        for key, sign in (("table_median", -1.0), ("wetland_share", 1.0)):
            if key in a and key in b and sign * (b[key] - a[key]) < -0.03:
                print(f"   !! {key}: {more[0]} ({b[key]:.2f}) against {less[0]} with less recharge ({a[key]:.2f})")
                failed += 1
    steady = sorted((row for row in rows if row[0][4] <= 6.0 * max(row[0][3], 1.0)), key=lambda row: row[0][1] / row[0][2])
    for (drier, a), (wetter, b) in zip(steady, steady[1:]):
        if "herb" in a and "herb" in b and b["herb"] - a["herb"] < -0.03:
            print(f"   !! herb: {wetter[0]} ({b['herb']:.2f}) against the drier {drier[0]} ({a['herb']:.2f})")
            failed += 1
    print(f"   {'no finding' if not failed else str(failed) + ' finding(s)'}")
    return 1 if failed else 0


# ----------------------------------------------------------------------------------------------------
# play
# ----------------------------------------------------------------------------------------------------
def _telling_points(entity):
    """Points of a map that put the kernel on different ground: sodden, moist, drained, and the river's bars."""
    (x, y), _frame = lattice(entity, 96)
    substrate = substrate_of(entity)
    water = np.asarray(substrate.open_water_array(x, y), dtype=bool)
    table = np.asarray(substrate.sample_array("water_table_depth_m", x, y, np.nan), dtype=np.float64)
    reworked = np.asarray(substrate.sample_array("flood_reworking_return_period_years", x, y, 999.0), dtype=np.float64)
    inner = np.zeros(x.shape, dtype=bool)
    inner[8:-8, 8:-8] = True
    kinds = (("sodden", (table <= 0.15)), ("moist", (table > 0.5) & (table < 0.9)), ("drained", (table > 2.5)),
             ("bar", (reworked <= 5.0)), ("anywhere", np.ones(x.shape, dtype=bool)))
    points = []
    for label, mask in kinds:
        choice = np.argwhere(mask & ~water & inner)
        if len(choice) and (label != "anywhere" or not points):
            row, column = choice[len(choice) // 2]
            points.append((label, float(x[row, column]), float(y[row, column])))
    return points


def cmd_play(args):
    from simulations.biosphere import terrain_site
    from simulations.biosphere.biosphere_simulation import BiosphereSimulation
    from simulations.biosphere.flora import biome_flora
    from simulations.biosphere.biomes import biome_at

    world = open_world()
    entity = entity_of(world, args.name)
    frame, b = terrain_site.frame_bounds_m(entity), entity["bounds"]
    can_found, reason = terrain_site.founding_report(world, entity)
    print(f"== {args.name} ({entity['id']}, level {entity.get('map_detail_level')}): "
          + ("a Biosphere at its telling points" if can_found else f"no Biosphere can be founded here: {reason}"))
    if not can_found:
        return 0
    planet_id = entity.get("refinement_root_planet_id")
    failed = 0
    for label, x, y in _telling_points(entity):
        map_point = (b["min_x"] + (x - frame["min_x"]) / (frame["max_x"] - frame["min_x"]) * (b["max_x"] - b["min_x"]),
                     b["min_y"] + (y - frame["min_y"]) / (frame["max_y"] - frame["min_y"]) * (b["max_y"] - b["min_y"]))
        substrate = substrate_of(entity)
        # A flora for whatever biome the point lies in, so that every map opens on residents.
        biome = biome_at(substrate, x, y)
        flora = biome_flora(world, planet_id, biome)
        if not flora.records:
            for species_id, rarity in _test_floras(world, [biome])[biome.key].records.items():
                flora.record(species_id, rarity.rarity)
        started = time.perf_counter()
        try:
            site = terrain_site.found_biosphere_site(world, entity["id"], map_point, year=2400)
            sim = BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400, **({"initial_extent_m": args.extent} if args.extent else {})})
            opened = time.perf_counter() - started
            environment = sim.ecology.environment_at(*sim.founding_point())
            residents = sorted(sim.resident_flora.species) if sim.resident_flora else []
            plants = sum(len(sim.ecology.individuals.members(patch.patch_id) or ()) for patch in sim.ecology.patches)
            print(f"   {label:8s} at {x:7.0f}, {y:6.0f}: {biome.label}; table {environment.get('water_table_depth_m', float('nan')):.2f} m, "
                  f"wetness {environment['soil_moisture']:.2f}, reworked every {environment.get('flood_reworking_return_period_years', 999):.0f} y; "
                  f"opened in {opened:.1f} s with {len(residents)} residents, {plants} plants")
            seasons, slowest, start = [], 0.0, {patch.species_id for patch in sim.ecology.patches}
            introduced = None
            for year in range(1, args.years + 1):
                if year == 3:
                    # Something the flora does not hold, where the ground suits it best.
                    fits = [(sim.diagnose(profile.species_id, *sim.founding_point())["suitability"], profile.species_id)
                            for profile in sim.species_profiles
                            if profile.species_id not in start and profile.growth_form in ("tree", "shrub") and sim.is_species_unlocked(profile.species_id)]
                    if fits and max(fits)[0] > 0.0:
                        introduced = max(fits)[1]
                        sim.select_species(introduced)
                        sim.place_selected_species(*sim.founding_point())
                for _season in range(4):
                    tick = time.perf_counter()
                    sim.advance_seasons(1)
                    seasons.append(time.perf_counter() - tick)
            living = {patch.species_id for patch in sim.ecology.patches}
            for patch in sim.ecology.patches:
                if not (0.0 <= patch.abundance <= 0.98 + 1e-9 and math.isfinite(patch.radius_m)):
                    print(f"   !! {patch.species_id}: stand out of range (cover {patch.abundance}, radius {patch.radius_m})")
                    failed += 1
            floods = [note["text"] for note in sim.field_notes if note["kind"] == "flood"]
            print(f"            after {args.years} y: {len(living & start)} of {len(start)} residents stand, "
                  f"{'brought in ' + sim.short_label(introduced) + (' (stands)' if introduced in living else ' (gone)') if introduced else 'nothing to bring in'}; "
                  f"living area {sim.ecology.width:.0f} x {sim.ecology.height:.0f} m; seasons median {np.median(seasons) * 1000:.0f} ms, "
                  f"slowest {max(seasons) * 1000:.0f} ms; {len(floods)} flood(s)")
            for note in [note for note in sim.field_notes if note["kind"] in ("failure", "flood")][:4]:
                print(f"            {note['when']}: {note['text']}")
        except Exception as error:  # a stress run reports what broke and goes on to the next point
            import traceback

            failed += 1
            print(f"   !! {label} at {x:.0f}, {y:.0f}: {type(error).__name__}: {error}")
            print("      " + traceback.format_exc().strip().splitlines()[-3].strip())
    print(f"   {'no finding' if not failed else str(failed) + ' finding(s)'}")
    return 1 if failed else 0


# ----------------------------------------------------------------------------------------------------
# extremes
# ----------------------------------------------------------------------------------------------------
def cmd_extremes(_args):
    from simulations.biosphere import water_balance as wb
    from simulations.biosphere.ecology import flood_standing_share, moisture_response, profile_from_entity
    from simulations.world_gen import fine_hydrology as fh
    from simulations.world_gen import river_floods as rf
    from simulations.world_gen.regolith_soils import soil_drainage_rate, soil_water_properties

    findings = Findings("extremes")
    print("== the arithmetic on ground no map would hand over")
    # The balance: nothing, floods of rain, no demand, frozen air, missing figures.
    cases = 0
    for rain in (0.0, 1.0, 400.0, 20000.0):
        for demand in (0.0, 1.0, 900.0, 9000.0):
            for store in (0.0, 0.001, 150.0, 5000.0):
                for table in (None, 0.0, 0.4, 50.0, float("nan")):
                    for drainage in (None, 1e-9, 1.0, 1e9):
                        for lateral in (-1e6, 0.0, 1e6):
                            ground = wb.point_ground(rain, demand, coldest_month_k=200.0, warmest_month_k=330.0, exposure=float("nan"),
                                                     available_water_mm_per_m=store, rootable_depth_m=float("nan"), lateral_mm=lateral,
                                                     capillary_rise_m=0.0, water_table_depth_m=table, drainage_mm_per_day=drainage)
                            for depth in (0.0, 0.4, 30.0):
                                for development in (-1.0, 0.0, 2.0):
                                    wet = wb.point_wetness(ground, depth, development)
                                    cases += 1
                                    if not (math.isfinite(wet) and 0.0 <= wet <= wb.SODDEN_WETNESS + 1e-9):
                                        findings.expect(False, f"point wetness {wet} for rain {rain}, demand {demand}, store {store}, table {table}, "
                                                               f"drainage {drainage}, run-on {lateral}, roots {depth}, soil {development}")
    print(f"   balance at single places: {cases} cases")
    rng = np.random.default_rng(11)
    shape = (40, 60)
    extreme = {
        "rain": wb.monthly_rain(rng.choice([0.0, 5.0, 900.0, 30000.0], shape), rng.choice([0.0, 400.0], shape), rng.choice([0.0, 9000.0], shape),
                                rng.choice([0.0, 1.0, np.nan], shape)),
        "demand": wb.monthly_demand(rng.choice([0.0, 3.0, 1500.0, 12000.0], shape), rng.choice([150.0, 280.0, np.nan], shape),
                                    rng.choice([150.0, 320.0, np.nan], shape), rng.choice([0.0, 1.0, 7.0, np.nan], shape)),
        "available_water_mm_per_m": rng.choice([0.0, 70.0, 190.0, 1e6], shape), "rootable_depth_m": rng.choice([0.0, 0.01, 3.0, np.nan], shape),
        "lateral_mm": rng.choice([-1e6, -50.0, 0.0, 800.0, 1e7], shape), "capillary_rise_m": rng.choice([0.0, 0.1, 2.0, 50.0], shape),
        "water_table_depth_m": rng.choice([0.0, 0.2, 3.0, 99.0, np.nan], shape), "drainage_mm_per_day": rng.choice([0.0, 0.05, 30.0, np.inf], shape),
    }
    for depth in (0.0, 0.35, 2.0, 40.0):
        with np.errstate(all="ignore"):
            wet = wb.plant_wetness(extreme, depth)
        findings.expect(np.isfinite(wet).all() and (wet >= 0).all() and (wet <= wb.SODDEN_WETNESS + 1e-9).all(),
                        f"array wetness for roots {depth} m: {int((~np.isfinite(wet)).sum())} not finite, range {np.nanmin(wet):.3f}..{np.nanmax(wet):.3f}")
    print("   balance over arrays of extremes: done")

    # Plants.
    for preference in ("very_dry", "dry", "mesic", "moist", "wet", "aquatic", "", "nonsense"):
        for tolerance in ("low", "medium", "high", "", "other_unknown"):
            profile = profile_from_entity({"id": "spec_stress", "plant_growth_form": "forb", "moisture_preference": preference,
                                           "waterlogging_tolerance": tolerance})
            response = moisture_response(profile, np.array([-1.0, 0.0, 0.2, 0.5, 0.9, 1.0, 5.0, np.nan]))
            findings.expect(np.isfinite(response[:-1]).all() and (response[:-1] >= 0).all() and (response[:-1] <= 1).all(),
                            f"moisture response of a {preference!r} plant of {tolerance!r} tolerance: {response}")
            standing = flood_standing_share(profile, np.array([0.0, 1e-9, 0.1, 5.0, 999.0, 1e12, np.nan, -3.0]))
            findings.expect(np.isfinite(standing).all() and (standing >= 0).all() and (standing <= 1).all(), f"standing share: {standing}")
    print("   plants: moisture response and standing share over every class and nonsense")

    # Soil figures and flood arithmetic.
    clay = np.array([-1.0, 0.0, 0.3, 1.0, 7.0, np.nan])
    with np.errstate(all="ignore"):
        available, rise = soil_water_properties(clay)
        rate = soil_drainage_rate(clay)
    findings.expect(np.isfinite(available[:5]).all() and np.isfinite(rise[:5]).all() and np.isfinite(rate[:5]).all() and (rate[:5] > 0).all(),
                    "soil water figures for clay shares outside 0..1")
    for section, mean, plain in ((1e-9, 1e-9, 1.0), (0.05, 0.03, 1.0), (3.0, 2.0, 10.0), (60.0, 40.0, 5000.0)):
        for growth in (1e-9, 0.4, 1.5, 50.0):
            heights = np.array([-1e6, -section, -0.5 * section, 0.0, 0.5 * mean, 5.0 * mean, 1e6])
            with np.errstate(all="ignore"):
                years = rf.return_period_years(rf.discharge_for_stage(heights, section, mean, plain), growth)
            findings.expect(np.isfinite(years).all() and (years >= rf.SHORTEST_RETURN_YEARS).all() and (years <= rf.NEVER_YEARS).all()
                            and (np.diff(years) >= -1e-9).all(), f"flood returns for a section {section} m deep, growth {growth}: {years}")
    print("   soil figures and flood returns: done")

    # The fine hydrology on tiles at the edge of what a tile can be.
    def tile(elevation, level=5, spacing=1.0, sea=None):
        return {"map_detail_level": level, "sample_grid": {"rows": np.asarray(elevation, dtype=float).tolist()},
                "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing, "sea_level_m": sea}

    def cycle(rain=900.0, demand=1000.0, runoff=300.0, recharge=100.0):
        flat = lambda value: [[value] * 4 for _ in range(4)]  # noqa: E731
        return {"status": "water_cycle_seeded", "climate_grid": {
            "annual_runoff_rows_mm": flat(runoff), "annual_precipitation_rows_mm": flat(rain),
            "annual_potential_evaporation_rows_mm": flat(demand), "annual_groundwater_recharge_rows_mm": flat(recharge)},
            "drainage_network_model": {"rivers": [], "ephemeral_channels": [], "grid_width": 4, "grid_height": 4},
            "runoff_grid": {}, "surface_water_grid": {}, "rivers": [], "lakes": []}

    yy, xx = np.mgrid[0:65, 0:65].astype(float)
    tiles = {
        "dead flat": (tile(np.full((65, 65), 100.0)), cycle()),
        "a wall (45 degrees)": (tile(100.0 + xx), cycle()),
        "three by three cells": (tile(100.0 + xx[:3, :3]), cycle()),
        "all under the sea": (tile(np.full((65, 65), -5.0), sea=0.0), cycle()),
        "half sea, a metre of shore": (tile(xx / 32.0 - 1.0, sea=0.0), cycle()),
        "no rain at all": (tile(100.0 - 0.05 * yy + 0.002 * (xx - 32) ** 2), cycle(0.0, 3000.0, 0.0, 0.0)),
        "a deluge": (tile(100.0 - 0.05 * yy + 0.002 * (xx - 32) ** 2), cycle(20000.0, 300.0, 15000.0, 4000.0)),
        "a pit": (tile(100.0 - 8.0 * np.exp(-((xx - 32) ** 2 + (yy - 32) ** 2) / 60.0)), cycle()),
        "centimetre roughness on a plain": (tile(100.0 + 0.01 * rng.standard_normal((65, 65)), spacing=0.1, level=6), cycle()),
        "kilometre cells called a Site": (tile(100.0 - 0.05 * yy, spacing=1000.0, level=4), cycle()),
    }
    for label, (heightmap, water) in tiles.items():
        started = time.perf_counter()
        try:
            with np.errstate(all="ignore"):
                refined = fh.refine_surface_hydrology(heightmap, water)
        except Exception as error:
            findings.expect(False, f"fine hydrology on {label}: {type(error).__name__}: {error}")
            continue
        runoff = refined.get("runoff_grid") or {}
        table, lateral = _raster(runoff, "water_table_depth_m_rows"), _raster(runoff, "lateral_water_rows_mm")
        if table is None:
            print(f"   {label}: left as it came (no fine hydrology)")
            continue
        presence = np.asarray(refined["surface_water_grid"]["water_presence_rows"], dtype=bool)
        findings.expect(np.isfinite(table).all() and (table >= 0).all() and (table <= 99.0).all() and np.isfinite(lateral).all(),
                        f"fine hydrology on {label}: table or run-on out of range")
        findings.expect(float(table[presence].max(initial=0.0)) == 0.0, f"fine hydrology on {label}: a water table under open water")
        land = ~presence
        print(f"   {label}: water {float(presence.mean()):.2f}, table median {np.median(table[land]) if land.any() else float('nan'):.2f} m, "
              f"run-on {np.min(lateral):.0f}..{np.max(lateral):.0f} mm ({(time.perf_counter() - started) * 1000:.0f} ms)")
    # A large tile: how long the table takes.
    big = 100.0 - 0.01 * np.mgrid[0:1025, 0:1025][0] + 0.5 * np.sin(np.mgrid[0:1025, 0:1025][1] / 40.0)
    water = np.zeros(big.shape, dtype=bool)
    water[-6:, :] = True
    started = time.perf_counter()
    head = fh.regional_water_table(water, np.where(water, big, 0.0), big, 300.0, 2.0, 2.0)
    findings.expect(np.isfinite(head).all() and (head <= big + 1e-9).all(), "the table of a 1025 x 1025 tile is above its ground or not finite")
    print(f"   the table of a 1025 x 1025 tile: {time.perf_counter() - started:.1f} s")
    print(f"   {'no finding' if not findings.failed else str(len(findings.failed)) + ' finding(s)'}")
    return 1 if findings.failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("make", help="refine a map in memory and keep it as a case")
    make.add_argument("name")
    make.add_argument("--parent", help="stored id or case name of the map to refine")
    make.add_argument("--rebuild", help="stored id of a map to make again over the same footprint")
    make.add_argument("--share", nargs=4, type=float, metavar=("CX", "CY", "W", "H"), help="footprint as shares of the parent's extent")
    make.add_argument("--where", choices=("river", "coast", "centre"), default="river")
    make.add_argument("--size-m", nargs=2, type=float, default=(3000.0, 1700.0), metavar=("W", "H"))
    make.set_defaults(run=cmd_make)
    check = commands.add_parser("check", help="invariants of a map's rasters and what reads them")
    check.add_argument("names", nargs="+")
    check.set_defaults(run=cmd_check)
    climates = commands.add_parser("climates", help="eight climates over one map's ground")
    climates.add_argument("name")
    climates.set_defaults(run=cmd_climates)
    play = commands.add_parser("play", help="a Biosphere opened on the ground's flora at telling points")
    play.add_argument("name")
    play.add_argument("--years", type=int, default=8)
    play.add_argument("--extent", type=float, help="side of the living area it opens with, in metres")
    play.set_defaults(run=cmd_play)
    extremes = commands.add_parser("extremes", help="the arithmetic on ground no map would hand over")
    extremes.set_defaults(run=cmd_extremes)
    args = parser.parse_args(argv)
    if args.command == "make" and not (args.parent or args.rebuild):
        parser.error("make needs --parent or --rebuild")
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
