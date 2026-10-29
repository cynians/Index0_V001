"""What a collection of plants makes of a piece of ground: who grows where, and why there.

Look-only.  Lays the climate of a Koppen zone over a Site's ground, gives it
the plant collection of that zone (both in memory, as ``lod_flora_chain``
does) and reads the ground with the solver that plants maps and Biosphere
sites (``potential_vegetation.resident_vegetation``).  Then it asks of the
result what a natural vegetation would show:

* does every species grow somewhere, and what keeps out those that do not;
* is a species where it is because of the ground (water, depth of soil,
  shade, floods) or only because its patches happen to lie there;
* how many species share a piece of ground, and does the community change
  from dry ground to wet;
* which species answer the ground alike, so that only their rarity and
  their patches tell them apart;
* which of the traits the solver reads are authored and which are defaults.

    python tools/flora_distribution_audit.py --site refined_lod4_29a30fb2ae --zone BSk
    python tools/flora_distribution_audit.py --site <id> --zone Dfb --shots artifacts/flora_audit --at 0.62 0.36
    python tools/flora_distribution_audit.py --site <id> --all

``--all`` goes through every climate there is and gives one line each: the
yardstick a change to the solver or to a collection is measured by.

``--shots`` also opens a Biosphere on that ground at ``--at`` and saves the
isometric view from near and from far.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

GRADIENTS = (("water table", "water_table_depth_m"), ("wetness", "soil_moisture"), ("soil depth", "rootable_depth_m"),
             ("sun", "surface_solar_exposure"))
# A species whose ground differs from the land's by less than this many standard deviations on every
# gradient is where it is by its patches alone.
HABITAT_SIGNAL = 0.3
PRESENT = 0.02
# Under trees that cover this much of a cell the ground is a wood's floor.
CLOSED_CANOPY = 0.6
# What a vegetation is made of.  A collection without one of these cannot make the ground it belongs on.
ROLES = ("tree", "tree of wet ground", "shrub", "shrub of the shade", "grass", "grass of dry ground", "herb",
         "herb of the shade", "water plant", "crust")
BRIEF_HEAD = ("zone  species grow  a cell  wood  on its floor  bare  wet/dry  by ground/patches  "
              "roles no species has | roles whose species do not grow")
_WORLD = []


def roles_of(profile):
    """The parts a species can play, from what the solver reads of it."""
    if profile.surface_growth_profile:
        return {"crust"}
    if profile.growth_form == "aquatic":
        return {"water plant"}
    shade = float(profile.light_minimum) <= 0.18  # what the classes of shade tolerance call tolerant
    if profile.growth_form == "tree":
        return {"tree"} | ({"tree of wet ground"} if profile.waterlogging_tolerance in ("medium", "high") else set())
    if profile.growth_form in ("shrub", "subshrub"):
        return {"shrub"} | ({"shrub of the shade"} if shade else set())
    if profile.growth_form == "graminoid":
        return {"grass"} | ({"grass of dry ground"} if float(profile.moisture_optimum) <= 0.45 else set())
    return {"herb"} | ({"herb of the shade"} if shade else set())


def shift(values, cover, land):
    """How far the ground a species covers lies from the land's average, in the land's standard deviations."""
    ok = land & np.isfinite(values)
    spread = float(values[ok].std()) if ok.any() else 0.0
    weight = np.where(ok, cover, 0.0)
    if spread <= 1e-9 or weight.sum() <= 1e-9:
        return 0.0
    return float(((values * weight)[ok].sum() / weight.sum() - values[ok].mean()) / spread)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", required=True, help="a stored Site or a case of tools/stress_ground_water.py")
    parser.add_argument("--zone", help="the Koppen zone whose climate and collection are laid over it")
    parser.add_argument("--all", action="store_true", help="every climate, a line each")
    parser.add_argument("--stored", action="store_true",
                        help="the Site as it is: its own climate and the floras its planet has (what play established)")
    parser.add_argument("--brief", action="store_true", help="one line for the zone")
    parser.add_argument("--shots", help="folder for isometric pictures of a Biosphere opened on that ground")
    parser.add_argument("--at", nargs=2, type=float, default=(0.5, 0.5), metavar=("EAST", "SOUTH"))
    args = parser.parse_args(argv)
    if args.all:
        from tools.lod_flora_chain import ZONE_CLIMATES as every

        print(BRIEF_HEAD)
        for entry in every:
            main(["--site", args.site, "--zone", entry[0], "--brief"])
        return
    if args.stored:
        args.zone = "own"
    if not args.zone:
        parser.error("--zone, --all or --stored")
    say = (lambda *_told, **_how: None) if args.brief else print

    from simulations.biosphere.biomes import biome_grid
    from simulations.biosphere.ecology import moisture_response, rooting_depth_m, rooting_response, thermal_response_array
    from simulations.biosphere.potential_vegetation import LAYERS, MAP_CELLS, planet_seed, resident_vegetation
    from simulations.city.city_vegetation import _profiles
    from tools import stress_ground_water as stress
    from tools.lod_flora_chain import ZONE_CLIMATES, zone_floras

    climate = next((entry for entry in ZONE_CLIMATES if entry[0] == args.zone), None)
    say()
    if climate is None and not args.stored:
        raise SystemExit(f"no climate for {args.zone}; there are {', '.join(entry[0] for entry in ZONE_CLIMATES)}")
    if not _WORLD:
        _WORLD.append(stress.open_world())
    world = _WORLD[0]
    entity = stress.entity_of(world, args.site)
    if not args.stored:
        entity = stress.under_climate(entity, tuple(climate) + (args.zone, args.zone))
    world.stress_cases[entity["id"]] = entity
    substrate = stress.substrate_of(entity)
    width, height = stress.size_m(entity)
    bounds = {"min_x": 0.0, "min_y": 0.0, "max_x": float(width), "max_y": float(height)}
    columns, rows = MAP_CELLS, max(2, round(MAP_CELLS * height / width))
    x, y = np.meshgrid((np.arange(columns) + 0.5) * width / columns, (np.arange(rows) + 0.5) * height / rows)
    _index, biomes = biome_grid(substrate, x, y)
    planet_id = entity.get("refinement_root_planet_id")
    if args.stored:
        from simulations.biosphere.flora import planet_floras

        floras = {key: flora for key, flora in planet_floras(world, planet_id).items() if flora.records}
        if not floras:
            raise SystemExit(f"nothing is established on {planet_id}")
    else:
        floras = zone_floras(biomes)
    profiles = _profiles(world, floras)
    vegetation = resident_vegetation(substrate, bounds, profiles, floras, cells=MAP_CELLS, seed=planet_seed(planet_id))
    x, y = vegetation.x, vegetation.y
    land = ~np.asarray(substrate.open_water_array(x, y), dtype=bool)
    ground = {name: np.asarray(substrate.sample_array(key, x, y, np.nan), dtype=np.float64) for name, key in GRADIENTS}
    canopy = vegetation.layer_cover("canopy")
    if vegetation.stand_age is not None:
        ground["years since fire"] = vegetation.stand_age
    told = "its own climate" if climate is None else (
        f"rain {climate[1]} mm against {climate[2]} mm of demand, {climate[6]} to {climate[7]} C")
    say(f"{args.site} under {args.zone}: {width:.0f} x {height:.0f} m, {land.mean():.0%} land; {told}; biomes {sorted(floras)}")
    say(f"water table on land: median {np.nanmedian(ground['water table'][land]):.1f} m "
          f"(10th to 90th: {np.nanpercentile(ground['water table'][land], 10):.1f} to {np.nanpercentile(ground['water table'][land], 90):.1f})")

    say("fire: " + (f"every {vegetation.fire_return_years:.0f} years on average" if vegetation.fire_return_years
                    else "none under this climate"))
    # -- species by species --------------------------------------------------------------------------
    rarity = {}
    for flora in floras.values():
        for species_id in flora.species():
            rarity.setdefault(species_id, flora.rarity(species_id))
    order = [name for name, _least in LAYERS] + ["climber"]
    warmest = np.asarray(substrate.sample_array("warmest_month_temperature_k", x, y, np.nan), dtype=np.float64)
    coldest = np.asarray(substrate.sample_array("coldest_month_temperature_k", x, y, np.nan), dtype=np.float64)
    say("\nspecies            layer        m   rarity     land  present  placed by (shift in sd)")
    by_ground, by_chance, absent = [], [], []
    for species_id in sorted(profiles, key=lambda item: (order.index(vegetation.layers.get(item, "ground")) if item in vegetation.layers
                                                         else 9, -float(np.mean(vegetation.cover.get(item, 0.0))))):
        profile = profiles[species_id]
        cover = vegetation.cover.get(species_id)
        name = species_id[5:23]
        if cover is not None and float(cover[land].max(initial=0.0)) < PRESENT <= float(cover.max()):
            say(f"{name:18s} {vegetation.layers.get(species_id, ''):11s} {profile.mature_height_m:4.1f}  {rarity.get(species_id, ''):9s} "
                  f"    -        -  in the water only: {float(cover[~land].mean()):.0%} of it")
            continue
        if cover is None or float(cover[land].max(initial=0.0)) < PRESENT:
            # What keeps it out: the limit that is lowest over the land.
            wet = vegetation.wetness_by_rooting.get(rooting_depth_m(profile))
            limits = {"temperature": float(np.nanmean(thermal_response_array(profile, warmest, coldest, 0.0)[land])),
                      "rooting depth": float(np.nanmean(rooting_response(profile, ground["soil depth"])[land]))}
            if wet is not None:
                limits["water"] = float(np.nanmean(moisture_response(profile, wet)[land]))
            worst = min(limits, key=limits.get)
            potential = vegetation.potential.get(species_id)
            reach = "" if potential is None else f"; could cover {float(potential[land].max()):.0%} at best"
            absent.append(species_id)
            say(f"{name:18s} {'-':11s} {profile.mature_height_m:4.1f}  {rarity.get(species_id, ''):9s}    -        -  "
                  f"ABSENT: {worst} {limits[worst]:.2f}{reach}")
            continue
        shifts = {label: shift(values, cover, land) for label, values in ground.items()}
        if vegetation.layers.get(species_id) != "canopy":
            shifts["under trees"] = shift(canopy, cover, land)
        strongest = max(shifts, key=lambda label: abs(shifts[label]))
        placed = f"{strongest} {shifts[strongest]:+.1f}" if abs(shifts[strongest]) >= HABITAT_SIGNAL else "its patches alone"
        (by_ground if abs(shifts[strongest]) >= HABITAT_SIGNAL else by_chance).append(species_id)
        say(f"{name:18s} {vegetation.layers.get(species_id, ''):11s} {profile.mature_height_m:4.1f}  {rarity.get(species_id, ''):9s} "
              f"{float(cover[land].mean()):6.1%}  {float((cover[land] >= PRESENT).mean()):6.0%}  {placed}")

    # -- the community -------------------------------------------------------------------------------
    present = [species_id for species_id in vegetation.cover if species_id not in absent]
    stack = np.stack([vegetation.cover[species_id] for species_id in present]) if present else np.zeros((1,) + x.shape)
    richness = (stack >= PRESENT).sum(axis=0)[land]
    total = stack.sum(axis=0)[land]
    say(f"\n{len(present)} of {len(profiles)} species grow; placed by the ground {len(by_ground)}, by patches alone {len(by_chance)}, absent {len(absent)}")
    say(f"species sharing a cell of land: mean {richness.mean():.1f} (10th to 90th: {np.percentile(richness, 10):.0f} to "
          f"{np.percentile(richness, 90):.0f}); bare land (cover under 5 %): {float((total < 0.05).mean()):.0%}")
    table = ground["water table"]
    edges = np.nanpercentile(table[land], [33.3, 66.7])
    bands = (("wet third", land & (table <= edges[0])), ("middle", land & (table > edges[0]) & (table <= edges[1])),
             ("dry third", land & (table > edges[1])))
    makeup = []
    for label, band in bands:
        means = np.array([float(vegetation.cover[species_id][band].mean()) for species_id in present])
        makeup.append(means)
        top = ", ".join(f"{present[number][5:20]} {means[number]:.0%}" for number in np.argsort(-means)[:4] if means[number] > 0.005)
        say(f"  {label:10s} (table {np.nanmean(table[band]):4.1f} m): {int((means >= PRESENT).sum())} species; {top}")
    wet, dry = makeup[0], makeup[-1]
    say(f"  wet third against dry third: {float(np.abs(wet - dry).sum() / max(1e-9, (wet + dry).sum())):.2f} apart "
          "(0 the same community, 1 nothing in common)")
    # -- a wood's floor, the layers, and the parts no species plays ------------------------------------------
    closed = land & (canopy >= CLOSED_CANOPY)
    below = [species_id for species_id in present if vegetation.layers.get(species_id) != "canopy"]
    floor_species = floor_cover = float("nan")
    if closed.any() and below:
        under = np.stack([vegetation.cover[species_id] for species_id in below])[:, closed]
        floor_species, floor_cover = float((under >= PRESENT).sum(axis=0).mean()), float(under.sum(axis=0).mean())
    say(f"closed wood on {float(closed[land].mean()):.0%} of the land; on its floor {floor_species:.1f} species to a cell, "
        f"covering {floor_cover:.0%}")
    say("cover by layer: " + ", ".join(f"{name} {float(vegetation.layer_cover(name)[land].mean()):.0%}" for name, _least in LAYERS))
    played = {role: [species_id for species_id, profile in profiles.items() if role in roles_of(profile)] for role in ROLES}
    missing = [role for role in ROLES if not played[role]]
    idle = [role for role in ROLES if played[role] and not any(species_id in present for species_id in played[role])]
    say(f"roles no species of the collection has: {', '.join(missing) or 'none'}")
    say(f"roles whose species do not grow here: {', '.join(idle) or 'none'}")
    # -- species that answer the ground alike ------------------------------------------------------------
    alike = []
    for first in range(len(present)):
        for second in range(first + 1, len(present)):
            a, b = (vegetation.potential[present[number]][land] for number in (first, second))
            if a.std() > 1e-9 and b.std() > 1e-9 and float(np.corrcoef(a, b)[0, 1]) > 0.98:
                alike.append(f"{present[first][5:20]} = {present[second][5:20]}")
    say(f"pairs that answer the ground alike (only rarity and patches tell them apart): {len(alike)}"
          + (": " + "; ".join(alike[:8]) + (" ..." if len(alike) > 8 else "") if alike else ""))
    # -- where the solver's figures come from -----------------------------------------------------------
    sources = ("moisture_source", "waterlogging_source", "salinity_source", "thermal_source", "light_requirement_source",
               "succession_source")

    def kind(told):
        told = str(told).lower()
        if "qualitative" in told:
            return "a class"       # authored as a word (dry, shade-tolerant ...), which stands for one figure
        if any(word in told for word in ("growth_form", "growth form", "unauthored", "shared by all", "preference default")):
            return "nothing"       # not authored: the figure of its growth form, or of all plants
        return "a figure"

    say("where the figures the solver reads come from (species authored with a figure / with a class / with nothing):")
    for name in sources:
        kinds = [kind(getattr(profile, name, "")) for profile in profiles.values()]
        bare = [species_id[5:] for species_id, profile in profiles.items() if kind(getattr(profile, name, "")) == "nothing"]
        say(f"  {name[:-7]:18s} {kinds.count('a figure'):2d} / {kinds.count('a class'):2d} / {kinds.count('nothing'):2d}"
              + (f"   nothing: {', '.join(bare[:6])}{' ...' if len(bare) > 6 else ''}" if bare else ""))
    optima = sorted({round(float(profile.moisture_optimum), 2) for profile in profiles.values()})
    lights = sorted({round(float(profile.light_minimum), 2) for profile in profiles.values()})
    say(f"  different moisture optima among the {len(profiles)}: {optima}; different light minima: {lights}")

    if args.brief:
        print(f"{args.zone:5s} {len(profiles):5d} {len(present):5d}  {richness.mean():5.1f}  {float(closed[land].mean()):4.0%}  "
              f"{floor_species:5.1f} sp {floor_cover:4.0%}  {float((total < 0.05).mean()):4.0%}  "
              f"{float(np.abs(wet - dry).sum() / max(1e-9, (wet + dry).sum())):6.2f}  {len(by_ground):9d}/{len(by_chance):<6d}  "
              f"{', '.join(missing) or '-'} | {', '.join(idle) or '-'}")
    if not args.shots:
        return
    # -- a Biosphere on that ground -----------------------------------------------------------------------
    import pygame

    from simulations.biosphere import resident_start, terrain_site
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.biosphere_simulation import BiosphereSimulation
    from simulations.biosphere.plant_pictures import MAP_SPRITE_DIR

    pygame.init()
    pygame.display.set_mode((16, 16))
    resident_start.planet_floras = lambda _world, _planet: floras  # the zone's collection, in memory
    region = entity["bounds"]
    site = terrain_site.found_biosphere_site(world, entity["id"], (
        region["min_x"] + (region["max_x"] - region["min_x"]) * args.at[0],
        region["min_y"] + (region["max_y"] - region["min_y"]) * args.at[1]), year=2400)
    sim = BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})
    if sim.surroundings is None:
        raise SystemExit("the Biosphere opened there has no surroundings")
    sim.plant_pictures.map_sprite_dir = MAP_SPRITE_DIR  # kept between runs; a cache, not the ontology
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    renderer.GROUND_SETTLE_SECONDS = 0.0
    sim.isometric_fullscreen_preview = True
    out = Path(args.shots)
    out.mkdir(parents=True, exist_ok=True)
    screen = pygame.Surface((1600, 900))
    for zoom in (0.3, 0.06):
        sim.isometric_view_zoom = zoom
        for _frame in range(2):
            renderer.draw(screen, sim)
        path = out / f"{args.site}_{args.zone}_{sim._isometric_projection_state['scale']:.0f}px_per_m.png"
        pygame.image.save(screen, str(path))
        say(f"{path}: {sim._surroundings_render_count} plants of the surroundings")


if __name__ == "__main__":
    main()
