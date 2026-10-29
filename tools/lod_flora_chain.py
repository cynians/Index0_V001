"""The same ground at every level a Biosphere can run on: does it carry the same vegetation?

A Biosphere can be founded from Site scale down (``terrain_site.founding_report``:
ground resolved to 12 m or finer), and below a Site lie the Parcel, the Plot
and the Survey.  ``check`` takes such a chain of maps, coarsest first, and for
every map under the first reads the ground it covers twice, once from the map
itself and once from each map above it, and compares what a collection puts
there: the biome's word, the cover of every layer and species, where each
species' patches lie, and the single plants set out.  Looking closer may
sharpen where things grow; it may not move the woods.

Every biome is given the collection of its Koppen zone
(``tools/author_zone_collections.py``), in memory; nothing is written.  Maps
are stored regions or the cases of ``tools/stress_ground_water.py``:

    py tools/lod_flora_chain.py check refined_lod4_29a30fb2ae wet_parcel wet_plot wet_survey
    py tools/lod_flora_chain.py check refined_lod4_4ef0f98c8b dry_parcel dry_plot dry_survey --sheet dry_chain.png

Two tests are pictures, painted as a city's map paints its ground (each plant
its species' own picture from above):

    py tools/lod_flora_chain.py zoom refined_lod4_29a30fb2ae wet_parcel wet_plot wet_survey
        the ground of every map of the chain, painted from the map above it and from itself
    py tools/lod_flora_chain.py zones refined_lod4_29a30fb2ae
        one map's ground under twelve climates, each with the collection of its zone
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import numpy as np

import stress_ground_water as stress

CELLS = 96
LEVEL_NAMES = {4: "Site", 5: "Parcel", 6: "Plot", 7: "Survey"}
# The planet whose kept plant pictures the paintings use.
PICTURE_PLANET = "planet_biosim_world"
# Climates laid over one map's ground for ``zones``: zone, rain and the air's demand (mm), driest and wettest
# month (mm), share of the rain that falls in summer, coldest and warmest month (degrees C).
ZONE_CLIMATES = (
    ("Af", 2600, 1500, 150, 300, 0.50, 24, 27), ("Aw", 1100, 1800, 3, 250, 0.85, 20, 30),
    ("BWh", 60, 2600, 0, 15, 0.50, 14, 36), ("BSh", 420, 1900, 4, 110, 0.80, 14, 31),
    ("BSk", 320, 1200, 12, 45, 0.60, -6, 24), ("Csa", 520, 1150, 4, 95, 0.15, 8, 26),
    ("Cwa", 1200, 1300, 12, 260, 0.85, 10, 27), ("Cfa", 1300, 1200, 80, 150, 0.55, 6, 27),
    ("Cfb", 900, 700, 55, 95, 0.50, 3, 18), ("Dfb", 700, 600, 35, 90, 0.60, -9, 19),
    ("Dfc", 450, 380, 22, 60, 0.60, -22, 15), ("ET", 250, 250, 10, 35, 0.60, -28, 7),
)


def seed_of(entity):
    """The seed of a map's planet: the vegetation is the planet's, not a map's."""
    from simulations.biosphere.potential_vegetation import planet_seed

    return planet_seed(entity.get("refinement_root_planet_id") or entity.get("terrain_root_planet_id") or PICTURE_PLANET)


def level_name(entity):
    return LEVEL_NAMES.get(int(entity.get("map_detail_level") or 0), f"level {entity.get('map_detail_level')}")


def _uv_bounds(entity):
    return entity["heightmap_model"]["source_uv_bounds"]


def to_uv(entity, x, y):
    """Points of a map's metre frame as planet map coordinates."""
    from simulations.biosphere import terrain_site

    frame, uv = terrain_site.frame_bounds_m(entity), _uv_bounds(entity)
    return (uv["min_u"] + (np.asarray(x) - frame["min_x"]) / (frame["max_x"] - frame["min_x"]) * (uv["max_u"] - uv["min_u"]),
            uv["min_v"] + (np.asarray(y) - frame["min_y"]) / (frame["max_y"] - frame["min_y"]) * (uv["max_v"] - uv["min_v"]))


def from_uv(entity, u, v):
    """Planet map coordinates as points of a map's metre frame."""
    from simulations.biosphere import terrain_site

    frame, uv = terrain_site.frame_bounds_m(entity), _uv_bounds(entity)
    return (frame["min_x"] + (np.asarray(u) - uv["min_u"]) / (uv["max_u"] - uv["min_u"]) * (frame["max_x"] - frame["min_x"]),
            frame["min_y"] + (np.asarray(v) - uv["min_v"]) / (uv["max_v"] - uv["min_v"]) * (frame["max_y"] - frame["min_y"]))


def footprint_on(above, below):
    """The frame of ``below`` as a window of ``above``'s frame."""
    from simulations.biosphere import terrain_site

    frame = terrain_site.frame_bounds_m(below)
    x, y = from_uv(above, *to_uv(below, np.array([frame["min_x"], frame["max_x"]]), np.array([frame["min_y"], frame["max_y"]])))
    return {"min_x": float(x[0]), "max_x": float(x[1]), "min_y": float(y[0]), "max_y": float(y[1])}


def zone_floras(biomes):
    """A flora for every biome, set by the collection of its Koppen zone (in memory)."""
    from simulations.biosphere.flora import BiomeFlora, plant_collection
    from tools.author_zone_collections import ZONE_COLLECTIONS, collection_id, rarities_of

    floras = {}
    for biome in biomes:
        if biome.climate not in ZONE_COLLECTIONS or biome.key in floras:
            continue
        flora = BiomeFlora("planet_chain", biome)
        flora.assign_collection(plant_collection(collection_id(biome.climate), biome.climate, rarities_of(biome.climate)))
        floras[biome.key] = flora
    return floras


def spacing_of(profile):
    """Ground between two plants of a species, for setting single plants out: the same at every level."""
    return max(0.5, 0.2 * float(profile.mature_height_m))


def read(world, entity, bounds, floras_for=None):
    """The vegetation of a window of a map: ``(vegetation, profiles, biomes on its lattice)``."""
    from simulations.biosphere.biomes import biome_grid
    from simulations.biosphere.potential_vegetation import resident_vegetation
    from simulations.city.city_vegetation import _profiles

    substrate = stress.substrate_of(entity)
    width, height = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
    columns = max(2, round(CELLS * width / max(width, height)))
    rows = max(2, round(CELLS * height / max(width, height)))
    x, y = np.meshgrid(bounds["min_x"] + (np.arange(columns) + 0.5) * width / columns,
                       bounds["min_y"] + (np.arange(rows) + 0.5) * height / rows)
    index, biomes = biome_grid(substrate, x, y)
    floras = zone_floras(biomes if floras_for is None else floras_for)
    profiles = _profiles(world, floras)
    vegetation = resident_vegetation(substrate, bounds, profiles, floras, cells=CELLS, seed=seed_of(entity))
    words = np.array([biome.key for biome in biomes])[index]
    return vegetation, profiles, words, substrate


def _layers(vegetation, shape):
    layers = {}
    for species_id, cover in vegetation.cover.items():
        layers.setdefault(vegetation.layers[species_id], np.zeros(shape))
        layers[vegetation.layers[species_id]] += cover
    return layers


def compare(world, above, below, findings, sheet=None):
    """The ground of ``below`` read from ``above`` and from itself; prints, and returns the panels of a sheet."""
    from simulations.biosphere import terrain_site

    window = footprint_on(above, below)
    own_frame = terrain_site.frame_bounds_m(below)
    started = time.perf_counter()
    theirs, profiles_above, words_above, ground_above = read(world, above, window)
    mine, profiles_own, words_own, ground_own = read(world, below, own_frame)
    shape = mine.x.shape
    if theirs.x.shape != shape:
        findings.expect(False, f"{level_name(below)} against {level_name(above)}: the two lattices differ ({theirs.x.shape} and {shape})")
        return None
    water = (np.asarray(ground_own.open_water_array(mine.x, mine.y), dtype=bool)
             | np.asarray(ground_above.open_water_array(theirs.x, theirs.y), dtype=bool))
    land = ~water
    print(f"-- the {level_name(below)}'s ground ({own_frame['max_x']:.0f} x {own_frame['max_y']:.0f} m) read from the "
          f"{level_name(above)} and from itself ({time.perf_counter() - started:.1f} s; {int(land.sum())} of {land.size} points are land on both)")
    same_word = float((words_above == words_own)[land].mean()) if land.any() else 1.0
    told = {}
    for word in sorted(set(words_above[land]) | set(words_own[land])):
        told[word] = (float((words_above[land] == word).mean()), float((words_own[land] == word).mean()))
    print(f"   biome: the same word on {same_word:.2f} of the land; shares above/here: "
          + ", ".join(f"{word} {a:.2f}/{b:.2f}" for word, (a, b) in told.items()))
    findings.expect(same_word >= 0.85, f"{level_name(below)} against {level_name(above)}: another biome on {1 - same_word:.2f} of the land")
    layers_above, layers_own = _layers(theirs, shape), _layers(mine, shape)
    for layer in ("canopy", "understorey", "field", "ground"):
        a, b = layers_above.get(layer, np.zeros(shape)), layers_own.get(layer, np.zeros(shape))
        if not (a.any() or b.any()):
            continue
        difference = float(np.abs(a - b)[land].mean()) if land.any() else 0.0
        print(f"   {layer:11s} cover {a[land].mean():.3f} above, {b[land].mean():.3f} here; the two differ by {difference:.3f} a point")
        findings.expect(difference <= 0.15, f"{level_name(below)} against {level_name(above)}: {layer} cover differs by {difference:.2f} a point")
    species = sorted(set(theirs.cover) | set(mine.cover),
                     key=lambda item: -max(float(theirs.cover.get(item, np.zeros(shape))[land].mean()),
                                           float(mine.cover.get(item, np.zeros(shape))[land].mean())))
    worst = []
    for species_id in species:
        a, b = theirs.cover.get(species_id, np.zeros(shape)), mine.cover.get(species_id, np.zeros(shape))
        stands_a, stands_b = (a > 0.02) & land, (b > 0.02) & land
        union = int((stands_a | stands_b).sum())
        overlap = float((stands_a & stands_b).sum()) / union if union else 1.0
        if max(a[land].mean(), b[land].mean()) >= 0.01:
            worst.append((overlap, species_id, float(a[land].mean()), float(b[land].mean())))
    for overlap, species_id, a, b in sorted(worst)[:6]:
        print(f"   {species_id[5:30]:26s} cover {a:.3f} above, {b:.3f} here; stands on the same ground: {overlap:.2f}")
    if worst:
        # By how much of the ground each holds: a herb on a hundredth of it, met on threads only the finer map
        # resolves, does not speak for the woods.
        weights = np.array([max(row[2], row[3]) for row in worst])
        mean_overlap = float(np.average([row[0] for row in worst], weights=weights))
        print(f"   over {len(worst)} species: on the same ground {mean_overlap:.2f} by cover "
              f"({np.mean([row[0] for row in worst]):.2f} species for species), {min(row[0] for row in worst):.2f} at worst")
        findings.expect(mean_overlap >= 0.6, f"{level_name(below)} against {level_name(above)}: species stand on the same ground "
                                             f"on {mean_overlap:.2f} of it only")
    # The single plants: a tree seen from the map above is the tree seen here.  A plant stands where the cover
    # at its place takes it, so one set out from above is missing here only where this map gives its species
    # less cover at that spot (the ground read more closely).  Where it gives as much or more, it has to stand.
    matched, counted, owed, kept = 0, 0, 0, 0
    for species_id in species:
        profile = profiles_own.get(species_id) or profiles_above.get(species_id)
        if profile is None or profile.mature_height_m < 2.0 or species_id not in theirs.cover or species_id not in mine.cover:
            continue
        ax, ay, _grown = theirs.plants(species_id, spacing_of(profile), seed=seed_of(above))
        bx, by, _grown = mine.plants(species_id, spacing_of(profile), seed=seed_of(below))
        if not len(ax):
            continue
        # The plants of the map above, in this map's frame.
        px, py = from_uv(below, *to_uv(above, ax, ay))
        tolerance = 0.25 * spacing_of(profile)
        found = np.zeros(len(px), dtype=bool)
        if len(bx):
            order = np.argsort(bx)
            low, high = np.searchsorted(bx[order], px - tolerance), np.searchsorted(bx[order], px + tolerance)
            for number in range(len(px)):
                near = order[low[number]:high[number]]
                found[number] = bool(len(near) and np.any(np.hypot(bx[near] - px[number], by[near] - py[number]) <= tolerance))
        inside = (px >= own_frame["min_x"]) & (px <= own_frame["max_x"]) & (py >= own_frame["min_y"]) & (py <= own_frame["max_y"])
        must = inside & (mine.cover_at(species_id, px, py) >= theirs.cover_at(species_id, ax, ay) - 1e-9)
        matched += int(found[inside].sum())
        counted += int(inside.sum())
        owed += int(must.sum())
        kept += int((found & must).sum())
    if counted:
        print(f"   single plants from 2 m up: {matched} of the {counted} set out from above stand here too ({matched / counted:.2f}); "
              f"of the {owed} whose spot has as much cover here, {kept} do")
        findings.expect(owed == 0 or kept / owed >= 0.98,
                        f"{level_name(below)} against {level_name(above)}: {owed - kept} of {owed} plants whose spot keeps its cover "
                        "do not stand at the same place here")
    if sheet is not None:
        sheet.append((level_name(above), level_name(below), layers_above.get("canopy", np.zeros(shape)), layers_own.get("canopy", np.zeros(shape)),
                      layers_above.get("field", np.zeros(shape)), layers_own.get("field", np.zeros(shape)), water))
    return True


def draw(sheet, path):
    import pygame

    pygame.init()
    font = pygame.font.SysFont("arial", 14)
    bare, wood, sward, blue = np.array((200, 176, 132.0)), np.array((28, 92, 40.0)), np.array((96, 160, 62.0)), np.array((40, 70, 120))

    def panel(cover, water, tone, title):
        rgb = bare * (1.0 - np.clip(cover, 0, 1)[..., None]) + tone * np.clip(cover, 0, 1)[..., None]
        rgb = np.where(water[..., None], blue, rgb).astype(np.uint8)
        scale = max(1, 300 // rgb.shape[1])
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
        surface = pygame.Surface((rgb.shape[1], rgb.shape[0] + 20))
        surface.fill((24, 24, 28))
        surface.blit(pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2))), (0, 20))
        surface.blit(font.render(title, True, (232, 232, 232)), (4, 2))
        return surface

    rows = []
    for above, below, canopy_a, canopy_b, field_a, field_b, water in sheet:
        rows.append([panel(canopy_a, water, wood, f"trees on the {below}'s ground, from the {above}"),
                     panel(canopy_b, water, wood, f"trees, from the {below} itself"),
                     panel(field_a, water, sward, f"field layer, from the {above}"),
                     panel(field_b, water, sward, f"field layer, from the {below} itself")])
    width = max(sum(s.get_width() for s in row) + 8 * (len(row) - 1) for row in rows)
    height = sum(max(s.get_height() for s in row) + 8 for row in rows)
    image = pygame.Surface((width, height))
    image.fill((24, 24, 28))
    top = 0
    for row in rows:
        left = 0
        for surface in row:
            image.blit(surface, (left, top))
            left += surface.get_width() + 8
        top += max(s.get_height() for s in row) + 8
    pygame.image.save(image, str(path))
    print("sheet:", path, image.get_size())


# ----------------------------------------------------------------------------------------------------
# pictures
# ----------------------------------------------------------------------------------------------------
def paint(world, entity, bounds, size, pictures):
    """A window of a map's ground as a city's map paints it: water, the low layers as a tint, every tall plant
    its species' own picture from above.  Returns ``(surface, vegetation, profiles)``."""
    import pygame

    from simulations.biosphere.ecology import BiosphereEcology
    from simulations.city.city_vegetation import LOW_LAYERS, PlantField, ground_cover_picture, plant_colour

    vegetation, profiles, _words, substrate = read(world, entity, bounds)
    ecology = BiosphereEcology(bounds, profiles.values())
    ecology.pictures = pictures
    spacing = {species_id: ecology.spacing_m(profiles[species_id]) for species_id in vegetation.cover}
    width, height = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
    px_per_m = size[0] / width
    # The bare ground under it: lit from the north-west, water as water.
    columns, rows = max(2, size[0] // 2), max(2, size[1] // 2)
    x, y = np.meshgrid(bounds["min_x"] + (np.arange(columns) + 0.5) * width / columns,
                       bounds["min_y"] + (np.arange(rows) + 0.5) * height / rows)
    ground = np.asarray(substrate.sample_array("elevation_m", x, y, 0.0), dtype=np.float64)
    fall_y, fall_x = np.gradient(ground, height / rows, width / columns)
    light = np.clip(1.0 - 2.5 * (fall_x + fall_y), 0.72, 1.18)[..., None]
    rgb = np.clip(np.array((176.0, 160.0, 124.0)) * light, 0, 255)
    rgb = np.where(np.asarray(substrate.open_water_array(x, y), dtype=bool)[..., None], np.array((46.0, 84.0, 132.0)), rgb)
    small = pygame.surfarray.make_surface(np.transpose(rgb.astype(np.uint8), (1, 0, 2)))
    surface = pygame.transform.smoothscale(small.convert_alpha(), size)
    colours = {species_id: plant_colour(pictures, species_id, profiles[species_id])
               for species_id, layer in vegetation.layers.items() if layer in LOW_LAYERS}
    low = ground_cover_picture(vegetation, colours, long_side_px=max(size)) if vegetation.cover else None
    if low is not None:
        surface.blit(pygame.transform.smoothscale(low, size), (0, 0))
    if vegetation.cover:
        field = PlantField(vegetation, profiles, spacing, pictures, seed_of(entity), overview_long_side_px=32)
        tall = field.paint(bounds["min_x"], bounds["min_y"], px_per_m, size) if field else None
        if tall is not None:
            surface.blit(tall, (0, 0))
    return surface, vegetation, profiles


def _pictures(world):
    import pygame

    from simulations.biosphere.plant_pictures import MAP_SPRITE_DIR, planet_plant_pictures

    pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((16, 16))
    pictures = planet_plant_pictures(world, PICTURE_PLANET)
    # Pictures from above are kept on disk between sessions (a cache; nothing of the ontology).
    pictures.map_sprite_dir = MAP_SPRITE_DIR
    return pictures


def _sheet(panels, columns, path):
    import pygame

    font = pygame.font.SysFont("arial", 15)
    cells = []
    for title, surface in panels:
        cell = pygame.Surface((surface.get_width(), surface.get_height() + 22))
        cell.fill((24, 24, 28))
        cell.blit(surface, (0, 22))
        cell.blit(font.render(title, True, (234, 234, 234)), (4, 3))
        cells.append(cell)
    rows = [cells[start:start + columns] for start in range(0, len(cells), columns)]
    width = max(sum(cell.get_width() for cell in row) + 8 * (len(row) - 1) for row in rows)
    height = sum(max(cell.get_height() for cell in row) + 8 for row in rows) - 8
    image = pygame.Surface((width, height))
    image.fill((24, 24, 28))
    top = 0
    for row in rows:
        left = 0
        for cell in row:
            image.blit(cell, (left, top))
            left += cell.get_width() + 8
        top += max(cell.get_height() for cell in row) + 8
    path = Path(path)
    path = path if path.is_absolute() else stress.STATE / path
    pygame.image.save(image, str(path))
    print("picture:", path, image.get_size())


def cmd_zoom(args):
    from simulations.biosphere import terrain_site

    world = stress.open_world()
    chain = [stress.entity_of(world, name) for name in args.names]
    pictures = _pictures(world)
    panels = []
    for position in range(1, len(chain)):
        above, below = chain[position - 1], chain[position]
        frame = terrain_site.frame_bounds_m(below)
        size = (args.width, max(2, round(args.width * (frame["max_y"] - frame["min_y"]) / (frame["max_x"] - frame["min_x"]))))
        started = time.perf_counter()
        from_above, _vegetation, _profiles = paint(world, above, footprint_on(above, below), size, pictures)
        from_itself, vegetation, profiles = paint(world, below, frame, size, pictures)
        told = f"{frame['max_x']:.0f} x {frame['max_y']:.0f} m"
        panels.append((f"the {level_name(below)}'s ground ({told}), painted from the {level_name(above)}", from_above))
        panels.append((f"the same ground, painted from the {level_name(below)} itself", from_itself))
        tall = sorted((species_id for species_id in vegetation.cover if profiles[species_id].mature_height_m >= 2.0),
                      key=lambda species_id: -float(vegetation.cover[species_id].mean()))
        print(f"{level_name(below)} ({told}) painted twice in {time.perf_counter() - started:.1f} s; tall plants there: "
              + ", ".join(f"{species_id[5:]} {float(vegetation.cover[species_id].mean()):.2f}" for species_id in tall[:6]))
    _sheet(panels, 2, args.out)
    return 0


def cmd_zones(args):
    from simulations.biosphere import terrain_site
    from simulations.world_gen.water_cycle import KOPPEN_CLASSES

    world = stress.open_world()
    entity = stress.entity_of(world, args.name)
    pictures = _pictures(world)
    frame = terrain_site.frame_bounds_m(entity)
    size = (args.width, max(2, round(args.width * (frame["max_y"] - frame["min_y"]) / (frame["max_x"] - frame["min_x"]))))
    wanted = [climate for climate in ZONE_CLIMATES if not args.only or climate[0] in args.only]
    panels = []
    for zone, rain, demand, driest, wettest, summer, coldest, warmest in wanted:
        label = KOPPEN_CLASSES[zone]["label"]
        started = time.perf_counter()
        under = stress.under_climate(entity, (zone, rain, demand, driest, wettest, summer, coldest, warmest, zone, label))
        surface, vegetation, _profiles = paint(world, under, frame, size, pictures)
        shape = vegetation.x.shape
        land = ~np.asarray(stress.substrate_of(under).open_water_array(vegetation.x, vegetation.y), dtype=bool)
        layers = _layers(vegetation, shape)
        total = sum(layers.values()) if layers else np.zeros(shape)
        covers = sorted(((float(cover[land].mean()), species_id) for species_id, cover in vegetation.cover.items()), reverse=True)
        print(f"{zone:4s} {label:28s} rain {rain:5d} mm, demand {demand:5d}, {coldest:4d} to {warmest:3d} C: "
              f"trees {float(layers.get('canopy', np.zeros(shape))[land].mean()):.2f}, "
              f"field {float(layers.get('field', np.zeros(shape))[land].mean()):.2f}, bare {float((total < 0.05)[land].mean()):.2f}; "
              + ", ".join(f"{species_id[5:]} {share:.2f}" for share, species_id in covers[:4])
              + f"  ({time.perf_counter() - started:.1f} s)")
        panels.append((f"{zone}  {label}: {rain} mm of rain, {coldest} to {warmest} C", surface))
    _sheet(panels, args.columns, args.out)
    return 0


def cmd_check(args):
    world = stress.open_world()
    chain = [stress.entity_of(world, name) for name in args.names]
    findings = stress.Findings("chain")
    sheet = [] if args.sheet else None
    print("chain: " + " > ".join(f"{level_name(entity)} {entity['id']}" for entity in chain))
    for position in range(1, len(chain)):
        tops = chain[:position] if args.all_pairs else [chain[position - 1]]
        for above in tops:
            compare(world, above, chain[position], findings, sheet)
    print("no finding" if not findings.failed else f"{len(findings.failed)} finding(s)")
    if sheet:
        out = Path(args.sheet)
        draw(sheet, out if out.is_absolute() else stress.STATE / out)
    return 1 if findings.failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="every map of a chain against the maps above it, over the same ground")
    check.add_argument("names", nargs="+", help="stored regions or stress cases, coarsest first")
    check.add_argument("--all-pairs", action="store_true", help="each map against every map above it, not only its parent")
    check.add_argument("--sheet", help="save a picture of tree and field cover from both readings (under the stress cache)")
    check.set_defaults(run=cmd_check)
    zoom = commands.add_parser("zoom", help="paint the ground of every map of a chain from the map above it and from itself")
    zoom.add_argument("names", nargs="+", help="stored regions or stress cases, coarsest first")
    zoom.add_argument("--width", type=int, default=620, help="width of one painting in pixels")
    zoom.add_argument("--out", default="chain_zoom.png", help="where to save the sheet (under the stress cache unless absolute)")
    zoom.set_defaults(run=cmd_zoom)
    zones = commands.add_parser("zones", help="paint one map's ground under twelve climates, each with its zone's collection")
    zones.add_argument("name", help="a stored region or stress case")
    zones.add_argument("--only", nargs="*", help="only these zones")
    zones.add_argument("--width", type=int, default=560, help="width of one painting in pixels")
    zones.add_argument("--columns", type=int, default=3)
    zones.add_argument("--out", default="zone_gallery.png", help="where to save the sheet (under the stress cache unless absolute)")
    zones.set_defaults(run=cmd_zones)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
