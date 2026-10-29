"""Play primary succession through on a generated site and print what a player meets.

A pacing and playability probe for the Biosphere builder, not a test: it founds
a Biosphere at a point of a refined region, plants the bootstrap organism, and
each time the soil unlocks a succession tier plants the best-suited species of
that tier on the richest soil.  Per year it prints soil stage, biomass, living
area, nutrients and season cost, followed by the simulation's own field notes.

    python tools/biosphere_terraforming_playthrough.py --years 40
    python tools/biosphere_terraforming_playthrough.py --climate temperate --shots artifacts/terraforming

The world is opened look-only: nothing is stored in the ontology and refined
chunks go to a temp folder.  ``--climate temperate`` replaces the region's
climate grids in memory with a mild wet climate on the same ground, to see what
the loop does where climate is not the limit.

See ``docs/biosphere_worldgen_hookup_v001.md``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_driver import Driver  # noqa: E402  (must precede every other pygame import)

import pygame  # noqa: E402

from simulations.biosphere import terrain_site  # noqa: E402
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer  # noqa: E402
from simulations.biosphere.biosphere_simulation import BiosphereSimulation  # noqa: E402
from simulations.world_gen.regional_refinement import map_physical_dimensions_m  # noqa: E402


DEFAULT_REGION = "refined_lod4_e7fa59b8b3"
SHOT_YEARS = (0, 2, 5, 10, 20, 40, 60, 100)


def _fill(rows, value):
    for row in rows:
        for index in range(len(row)):
            row[index] = value(row[index]) if callable(value) else value


def apply_temperate_climate(region):
    """A mild, wet climate on the same ground.  In memory only."""
    water = region["water_cycle_model"]
    climate = water["climate_grid"]
    _fill(climate["temperature_rows_k"], 283.65)
    _fill(climate["seasonal_min_temperature_rows_k"], 275.15)
    _fill(climate["seasonal_max_temperature_rows_k"], 292.15)
    _fill(climate["annual_precipitation_rows_mm"], 900.0)
    # What the water balance reads: the air asks for less than the rain brings, in every season.
    for name, value in (("annual_potential_evaporation_rows_mm", 650.0), ("driest_month_precipitation_rows_mm", 60.0),
                        ("wettest_month_precipitation_rows_mm", 90.0), ("summer_precipitation_fraction_rows", 0.5)):
        if climate.get(name):
            _fill(climate[name], value)
    _fill(water["runoff_grid"]["wetness_index_rows"], lambda value: min(1.0, 0.42 + float(value)))
    # The zone label must follow the numbers, or every screenshot says "Hot Steppe".
    if climate.get("koppen_rows"):
        _fill(climate["koppen_rows"], "Cfb")
        classes = [item for item in (water.get("koppen_classes") or []) if item.get("id") != "Cfb"]
        water["koppen_classes"] = classes + [{"id": "Cfb", "label": "Temperate Oceanic"}]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--region", default=DEFAULT_REGION, help="id of a Site-level refined region")
    parser.add_argument("--point", nargs=2, type=float, metavar=("EAST_M", "SOUTH_M"),
                        help="founding point in metres from the region's north-west corner (default: 62 %% east, 36 %% south)")
    parser.add_argument("--years", type=int, default=40)
    parser.add_argument("--climate", choices=("site", "temperate"), default="site")
    parser.add_argument("--brush", type=float, default=None, metavar="RADIUS_M",
                        help="sow every introduction over a disc of this radius instead of by hand")
    parser.add_argument("--shots", help="folder for isometric screenshots at set years")
    parser.add_argument("--residents", action="store_true",
                        help="open on what the biome's flora has growing there, not on bare ground")
    parser.add_argument("--city", help="id of a city of the same planet: after the run its map is drawn with what "
                                       "the run entered in the biome's flora (hookup document, section 3.7)")
    args = parser.parse_args(argv)

    driver = Driver("terraforming", read_only=True)
    driver.frame(2)
    world = driver.app.world_model
    region = world.get_entity(args.region)
    can_found, reason = terrain_site.founding_report(world, region)
    if not can_found:
        print(f"Cannot found a Biosphere on {args.region}: {reason}")
        return 1
    if args.climate == "temperate":
        apply_temperate_climate(region)
    width_m, height_m = map_physical_dimensions_m(region)
    east_m, south_m = args.point or (width_m * 0.62, height_m * 0.36)
    bounds = region["bounds"]
    map_point = (
        bounds["min_x"] + (bounds["max_x"] - bounds["min_x"]) * east_m / width_m,
        bounds["min_y"] + (bounds["max_y"] - bounds["min_y"]) * south_m / height_m,
    )
    site = terrain_site.found_biosphere_site(world, region["id"], map_point, year=2400)
    # Primary succession is played from bare ground; ``--residents`` opens the site as a player finds it.
    sim = BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400, "start_bare": not args.residents})
    if args.climate == "temperate":
        # Chunks would re-derive their climate from worldgen; stay on the overridden region.
        sim.terrain.missing = lambda _bounds: []
        sim._refresh_terrain_pending()
    else:
        started = time.perf_counter()
        sim.resolve_terrain()
        print(f"ground refined in {time.perf_counter() - started:.1f} s")
    status = sim.get_terrain_status()
    print(status["label"], "|", status["climate_label"])

    founding_x, founding_y = sim.founding_point()
    print("\nSPECIES ON THIS SITE (tier, growth form, verdict)")
    counts = {}
    for item in sim.get_species_catalog_items():
        fit = item.get("site_fit") or {}
        counts[(item["succession_tier"], fit.get("verdict"))] = counts.get((item["succession_tier"], fit.get("verdict")), 0) + 1
        print(f"  T{item['succession_tier']} {item['growth_form']:<13} {item['label'][:40]:<40} {fit.get('label', '')}")
    print("per tier:", {tier: {verdict: count for (t, verdict), count in sorted(counts.items(), key=str) if t == tier}
                        for tier in sorted({tier for tier, _verdict in counts})})

    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    renderer.GROUND_SETTLE_SECONDS = 0.0
    screen = pygame.Surface((1600, 900))
    sim.isometric_fullscreen_preview = True
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def shot(year):
        if shots is None:
            return
        renderer.draw(screen, sim)
        renderer.draw(screen, sim)
        pygame.image.save(screen, str(shots / f"{args.climate}_year_{year:03d}.png"))

    def richest_cell():
        soil = sim.soil
        value, column, row = max(
            (soil.organic_matter_rows[row][column], column, row)
            for row in range(soil.rows) for column in range(soil.columns)
        )
        return soil.cell_center(column, row), value

    def best_species(tier, x, y):
        candidates = [
            profile for profile in sim.species_profiles
            if profile.succession_tier == tier and profile.growth_form != "aquatic"
            and sim.is_species_unlocked(profile.species_id)
        ]
        return sorted(((sim.diagnose(profile.species_id, x, y)["suitability"], profile) for profile in candidates),
                      key=lambda item: -item[0])[:3]

    shot(0)
    sim.seeding_brush_m = args.brush
    sim.select_species(sim.BIOMASSER_ID)
    sim.place_selected_species(founding_x, founding_y)
    planted_tiers = {0}
    print()
    for year in range(1, args.years + 1):
        started = time.perf_counter()
        sim.advance_seasons(4)
        season_ms = (time.perf_counter() - started) / 4 * 1000
        summary = sim.ecology.summary()
        soil = summary["soil"]
        representatives = sim.representatives.summary()
        tier = soil["supported_succession_tier"]
        print(
            f"y{year:03d} {soil['soil_stage']:<26} tier {tier} | SOM mean {soil['mean_soil_organic_matter_kg_m2']:.3f}"
            f" max {soil['max_soil_organic_matter_kg_m2']:.3f} | biomass {summary['living_biomass_kg']:8.1f} kg"
            f" | species {len(summary['species'])} | living area"
            f" {sim.bounds['max_x'] - sim.bounds['min_x']:.0f}x{sim.bounds['max_y'] - sim.bounds['min_y']:.0f} m"
            f" | N {soil['mean_available_nitrogen_g_m2']:.2f} P {soil['mean_available_phosphorus_g_m2']:.2f}"
            f" | reps {representatives['alive']}/{representatives['total']} | {season_ms:.0f} ms/season"
        )
        for new_tier in range(1, tier + 1):
            if new_tier in planted_tiers:
                continue
            (x, y), organic = richest_cell()
            options = best_species(new_tier, x, y)
            print(f"   tier {new_tier} unlocked (richest soil {organic:.3f} kg/m²); best: "
                  + "; ".join(f"{profile.label[:26]} {score:.0%}" for score, profile in options))
            if options and sim.ecology.sustains(options[0][1], options[0][0]):
                sim.select_species(options[0][1].species_id)
                sim.place_selected_species(x, y)
                planted_tiers.add(new_tier)
        if sim.pending_terrain_chunks():
            sim.resolve_terrain()
        if year in SHOT_YEARS or year == args.years:
            shot(year)

    print("\nFIELD NOTES")
    for note in sim.field_notes:
        print(f"  {note['when']:<12} {note['kind']:<8} {note['text']}")
    print("\nLIVING AT THE END")
    for item in sim.ecology.summary()["species"]:
        print(f"  {sim.ecology.profiles[item['species_id']].label}: {item['biomass_kg']:.1f} kg in {item['population_patches']} patches")
    if args.city:
        from simulations.biosphere.flora import planet_floras
        from render_city_resident_vegetation import shoot_city

        print("\nTHE PLANET'S FLORAS AFTER THE RUN (in this session only: nothing is stored)")
        for _key, flora in sorted(planet_floras(world, sim.planet_id).items()):
            print(f"  {flora.biome.label}")
            for species_id in flora.species():
                record = flora.records[species_id]
                held = "" if record.cover_share is None else f", held {record.cover_share:.1%} of the living area"
                since = "" if record.established_year is None else f", established {record.established_year}"
                print(f"    {record.rarity:10s} {species_id:34s} by {record.rarity_source}{since}{held}")
        if args.shots:
            driver.shots_dir = Path(args.shots)
            driver.shots_dir.mkdir(parents=True, exist_ok=True)
        driver.prefix, driver.step = "city_after_run", 1
        print()
        shoot_city(driver, args.city, widths=(0.0, 500.0, 120.0))
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
