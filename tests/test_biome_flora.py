"""A planet's flora by biome: naming biomes, recording what a Biosphere establishes, and what a city then finds growing."""

import math
import os
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from simulations.biosphere import terrain_site
from simulations.biosphere.biomes import Biome, biome_at, biome_grid, classify
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import (
    mineral_soil_index, rooting_depth_m, rooting_response,
    BiosphereEcology, expected_cover_array, mature_wetness, moisture_retention_bonus, potential_suitability,
    profile_from_entity, thermal_response, thermal_response_array,
)
from simulations.biosphere.flora import (
    BiomeFlora, RARITY_GROUND_SHARE, biome_flora, planet_floras, plant_collection, rarity_from_share, save_flora,
)
from simulations.biosphere.potential_vegetation import (
    aggregation,
    AQUATIC_DEPTH_M, CLIMBER_SUPPORT_SHARE, _patch_noise, _ranked, layer_of, resident_vegetation,
)
from simulations.city import city_site
from simulations.world_gen.solar_exposure import surface_solar_exposure, with_surface_solar_exposure
from simulations.biosphere.plant_pictures import MAP_SPRITE_PX, map_sprite_at, planet_plant_pictures
from simulations.city.city_vegetation import PlantField, TILE_PX, city_plant_cover, city_vegetation, pixel_px
from simulations.map.map_simulation import MapSimulation
from tests.test_biosphere_terrain_site import COLUMNS, REGION_ID, ROWS, _grid, _region_point, _world
from world.simulation_context import SimulationContext


PLANET = "planet_fixture"
GRASS = "spec_lolium_perenne"
OAK = {"id": "spec_test_oak", "_dataset": "species", "type": "species", "pretty_name": "English Oak",
       "plant_growth_form": "tree", "moisture_preference": "mesic", "shade_tolerance": "medium",
       "mature_height": {"max_m": 30}}
HEATH = {"id": "spec_test_heath", "_dataset": "species", "type": "species", "pretty_name": "Heath",
         "plant_growth_form": "shrub", "moisture_preference": "dry", "shade_tolerance": "low"}
SEDGE = {"id": "spec_test_sedge", "_dataset": "species", "type": "species", "pretty_name": "Sedge",
         "plant_growth_form": "forb", "moisture_preference": "wet", "shade_tolerance": "low"}
IVY = {"id": "spec_test_ivy", "_dataset": "species", "type": "species", "pretty_name": "Ivy",
       "plant_growth_form": "vine", "moisture_preference": "mesic", "shade_tolerance": "high",
       "mature_height": {"max_m": 20}}
CFB = Biome("Cfb", "Temperate Oceanic")


def site(world):
    """A Biosphere site on the fixture region, and its ground."""
    root = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0), year=2400)
    return root, terrain_site.site_substrate(world, root)


# ----------------------------------------------------------------------
# Biomes
# ----------------------------------------------------------------------
def test_a_biome_is_its_climate_zone_split_by_water_and_height_only_where_there_is_a_word():
    plain = classify("Cfb", "Temperate Oceanic", wetness=0.3, height_m=400.0)
    assert (plain.key, plain.label) == ("Cfb", "Temperate Oceanic")
    assert classify("Cfb", "Temperate Oceanic", wetness=0.05).key == "Cfb"       # dry ground has no word of its own
    assert classify("Cfb", "Temperate Oceanic", height_m=600.0).key == "Cfb"     # nor has a hill
    wet = classify("Cfb", "Temperate Oceanic", wetness=0.8)
    assert (wet.key, wet.label) == ("Cfb/wetland", "Temperate Oceanic wetland")
    assert classify("Cfb", "Temperate Oceanic", channel=True).label == "Temperate Oceanic riverside"
    assert classify("Cfb", "Temperate Oceanic", open_water=True, wetness=0.9).key == "Cfb/open_water"
    high = classify("Cfb", "Temperate Oceanic", height_m=1400.0, warmest_c=16.0)
    assert (high.key, high.label) == ("Cfb/montane", "Montane Temperate Oceanic")
    assert classify("ET", "Tundra", height_m=2600.0, warmest_c=6.0).label == "Alpine Tundra"
    both = classify("Cfb", "Temperate Oceanic", wetness=0.9, height_m=1200.0, warmest_c=15.0)
    assert (both.key, both.label) == ("Cfb/wetland/montane", "Montane Temperate Oceanic wetland")
    assert Biome("", "").label == "Unclassified ground"


def test_the_ground_of_a_generated_site_names_its_biomes_point_by_point_and_all_at_once():
    world = _world()
    region = world.get_entity(REGION_ID)
    # East of 400 m the ground is soaked: a wetland within the same climate.
    region["water_cycle_model"]["runoff_grid"]["wetness_index_rows"] = _grid(
        lambda column, _row: 0.9 if column >= 50 else 0.3)
    _root, ground = site(world)
    assert biome_at(ground, 200.0, 64.0) == CFB
    assert biome_at(ground, 8.0, 64.0).label == "Temperate Oceanic open water"
    assert biome_at(ground, 480.0, 64.0).key == "Cfb/wetland"
    x, y = np.meshgrid(np.array([8.0, 200.0, 480.0]), np.array([32.0, 200.0]))
    index, biomes = biome_grid(ground, x, y)
    assert [[biomes[i].key for i in row] for row in index.tolist()] == [["Cfb/open_water", "Cfb", "Cfb/wetland"]] * 2


# ----------------------------------------------------------------------
# Floras and collections
# ----------------------------------------------------------------------
def test_a_flora_takes_its_rarities_from_play_until_a_collection_sets_them():
    assert [rarity_from_share(share) for share in (0.7, 0.5, 0.2, 0.05, 0.001)] == [
        "dominant", "dominant", "common", "occasional", "rare"]
    flora = BiomeFlora(PLANET, CFB)
    assert flora.record(GRASS, "rare", year=2410, cover_share=0.01, site_id="site_1") == "entered"
    assert flora.record(GRASS, "rare", year=2411, cover_share=0.02) is None
    assert flora.record(GRASS, "common", year=2420, cover_share=0.2) == "changed"
    assert (flora.rarity(GRASS), flora.records[GRASS].established_year, flora.records[GRASS].site_id) == ("common", 2410, "site_1")
    flora.record("spec_test_oak", "dominant")
    assert flora.species() == ["spec_test_oak", GRASS]  # the commonest first

    collection = plant_collection("biosphere_collection_meadow", "Meadow", {GRASS: "dominant", "spec_test_sedge": "rare"})
    flora.assign_collection(collection)
    assert flora.collection_id == "biosphere_collection_meadow"
    assert (flora.rarity(GRASS), flora.rarity("spec_test_sedge"), flora.rarity("spec_test_oak")) == ("dominant", "rare", "dominant")
    # What the collection set is not undone by a poor season; what play entered still follows play.
    assert flora.record(GRASS, "rare", cover_share=0.001) is None and flora.rarity(GRASS) == "dominant"
    assert flora.record("spec_test_oak", "occasional") == "changed"
    # Another collection in its place: what only the first one put there goes, what play established stays as play left it.
    flora.assign_collection(plant_collection("biosphere_collection_heath", "Heath", {"spec_test_heath": "common"}))
    assert flora.species() == ["spec_test_heath", "spec_test_oak", GRASS]
    assert (flora.rarity(GRASS), flora.records[GRASS].rarity_source) == ("rare", "gameplay")
    flora.assign_collection(None)
    assert flora.collection_id is None and "spec_test_heath" not in flora.records


def test_a_flora_is_kept_as_a_biosphere_entity_over_its_planet_and_read_back_whole():
    world = _world()
    flora = biome_flora(world, PLANET, Biome("Cfb", "Temperate Oceanic", "wetland"))
    assert biome_flora(world, PLANET, Biome("Cfb", "Temperate Oceanic", "wetland")) is flora
    flora.record(GRASS, "common", year=2412, cover_share=0.21, site_id="site_1")
    entity = flora.to_entity({"id": flora.entity_id, "notes": "kept"}, planet_name="Fixture")
    assert entity["id"] == "biosphere_flora_fixture_cfb_wetland" and entity["_dataset"] == "biospheres"
    assert (entity["overlay_location"], entity["biome_key"], entity["sessile_life_species"]) == (PLANET, "Cfb/wetland", [GRASS])
    assert entity["name"] == "Temperate Oceanic wetland flora of Fixture" and entity["notes"] == "kept"
    again = BiomeFlora.from_entity(entity)
    assert (again.planet_id, again.biome, again.records) == (flora.planet_id, flora.biome, flora.records)
    # Where the session may write, it is written; and the next session finds it under its planet.
    assert save_flora(world, flora) and world.get_entity(flora.entity_id)["plant_records"][0]["rarity"] == "common"
    world.__dict__.pop("_planet_floras")
    assert planet_floras(world, PLANET)["Cfb/wetland"].rarity(GRASS) == "common"
    assert planet_floras(world, "planet_elsewhere") == {}


# ----------------------------------------------------------------------
# The kernel's arithmetic over arrays
# ----------------------------------------------------------------------
def test_the_array_arithmetic_is_the_kernels_own():
    oak = profile_from_entity(dict(OAK, frost_tolerance={"min_c": -12.0}))
    wetness, rain = np.array([0.05, 0.3, 0.44, 0.6, 0.9]), np.array([200.0, 650.0, 1000.0, 1500.0, 800.0])
    np.testing.assert_allclose(mature_wetness(wetness, rain), [
        min(1.0, w + moisture_retention_bonus(w, 1e12, r)) for w, r in zip(wetness.tolist(), rain.tolist())], atol=1e-9)
    warmest, coldest = np.array([277.0, 284.0, 295.0, 314.0, 290.0]), np.array([250.0, 262.0, 275.0, 290.0, 258.0])
    for shade in (0.0, 0.7):
        np.testing.assert_allclose(thermal_response_array(oak, warmest, coldest, shade), [
            thermal_response(oak, {"warmest_month_temperature_k": w, "coldest_month_temperature_k": c, "canopy_shade": shade})[0]
            for w, c in zip(warmest.tolist(), coldest.tolist())], atol=1e-12)
    assert thermal_response_array(oak, np.array([np.nan]), np.array([270.0])).tolist() == [1.0]  # no normals: unjudged
    ecology = BiosphereEcology(dict(min_x=0, max_x=10, min_y=0, max_y=10), [oak])
    suitability = np.array([0.0, 0.2, 0.5, 0.8, 1.0])
    np.testing.assert_allclose(expected_cover_array(oak, suitability),
                               [ecology.expected_cover(oak, s) for s in suitability.tolist()], atol=1e-12)
    # On built ground in the open, with nothing else short: the lower of the kernel's water and temperature limits.
    environment = {"soil_moisture": 0.3, "annual_precipitation_mm": 650.0,
                   "warmest_month_temperature_k": 295.0, "coldest_month_temperature_k": 275.0}
    potential = ecology.site_potential(oak, environment)["open"]
    assert abs(float(potential_suitability(oak, mature_wetness(0.3, 650.0), 295.0, 275.0)) - potential) < 1e-9


# ----------------------------------------------------------------------
# What grows where
# ----------------------------------------------------------------------
def floras_of(**rarities):
    flora = BiomeFlora(PLANET, CFB)
    for species_id, rarity in rarities.items():
        flora.record(species_id, rarity)
    return {flora.biome.key: flora}


def test_a_flora_sorts_itself_along_the_ground_and_under_its_own_canopy():
    world = _world(OAK, HEATH, SEDGE)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    profiles = {entity["id"]: profile_from_entity(entity) for entity in (OAK, HEATH, SEDGE)}
    profiles[HEATH["id"]] = replace(profiles[HEATH["id"]], moisture_optimum=0.36, moisture_tolerance=0.12)
    profiles[SEDGE["id"]] = replace(profiles[SEDGE["id"]], moisture_optimum=0.70, moisture_tolerance=0.14)
    assert [layer_of(profiles[e["id"]]) for e in (OAK, HEATH, SEDGE)] == ["canopy", "understorey", "field"]
    # The oak is common, not everywhere: it stands in woods with open ground between them.
    rarities = {OAK["id"]: "common", HEATH["id"]: "dominant", SEDGE["id"]: "dominant"}
    vegetation = resident_vegetation(ground, bounds, profiles, floras_of(**rarities), cells=64)
    heath, sedge = vegetation.cover[HEATH["id"]], vegetation.cover[SEDGE["id"]]
    west, east = vegetation.x < 150.0, vegetation.x > 400.0
    # The fixture's ground is drier in the west and wetter in the east.  The sedge holds the wet end and wants
    # for water elsewhere; the heath holds what drains, and none of the ground whose water stands in its roots.
    assert sedge[east].mean() > 5 * sedge[west].mean()
    drained, sodden = (vegetation.x > 200.0) & (vegetation.x < 340.0), vegetation.x > 500.0
    # (Where no oaks stand: under them a light-hungry shrub holds next to nothing, and where the woods lie is the
    # planet's to say, not this window's.)
    clear = vegetation.cover[OAK["id"]] < 0.05
    assert heath[drained & clear].mean() > 0.3 and heath[sodden].max() == 0.0
    assert heath[west & clear].mean() < heath[drained & clear].mean()
    # Nothing that roots in soil stands in the open water along the west edge.
    water = np.asarray(ground.open_water_array(vegetation.x, vegetation.y), dtype=bool)
    assert water.any() and all(float(cover[water].max()) == 0.0 for cover in vegetation.cover.values())
    # With oaks over part of the ground a light-hungry shrub holds less of it than it would without them.
    oak = vegetation.cover[OAK["id"]]
    assert oak.max() > 0.3 and (oak[~water] == 0).any()
    open_ground = resident_vegetation(ground, bounds, profiles, floras_of(**{HEATH["id"]: "dominant"}), cells=64)
    assert heath.sum() < open_ground.cover[HEATH["id"]].sum()
    under = oak > 0.3
    without = open_ground.cover[HEATH["id"]]
    assert (heath[under] <= without[under]).all() and (heath[under] < without[under]).any()
    # A species outside the biome's flora does not grow there at all.
    assert set(open_ground.cover) == {HEATH["id"]}


def test_what_stands_under_and_beside_others_is_what_the_kernel_keeps():
    world = _world(OAK, HEATH)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    profiles = {entity["id"]: profile_from_entity(entity) for entity in (OAK, HEATH)}
    profiles[HEATH["id"]] = replace(profiles[HEATH["id"]], moisture_optimum=0.45, moisture_tolerance=0.6,
                                    waterlogging_tolerance="high")  # at home anywhere here
    oak_profile, heath_profile = profiles[OAK["id"]], profiles[HEATH["id"]]
    kernel = BiosphereEcology
    # The kernel's own figures: a tree counts nearly in full against a shrub far below it and stands over it,
    # the shrub counts little against the tree and does not.
    assert kernel.competition_weight(heath_profile.mature_height_m, oak_profile.mature_height_m) == 0.75
    assert kernel.competition_weight(oak_profile.mature_height_m, heath_profile.mature_height_m) == 0.15
    assert kernel.overtops(oak_profile.mature_height_m, heath_profile.mature_height_m)
    assert not kernel.overtops(heath_profile.mature_height_m, oak_profile.mature_height_m)
    # The balance of a stand with neighbours: they take room from its growth and add to what it loses.
    alone = float(expected_cover_array(heath_profile, 0.8))
    assert alone == pytest.approx(kernel.expected_cover(kernel, heath_profile, 0.8))
    pressed = float(expected_cover_array(heath_profile, 0.8, 0.6, 0.0))
    assert pressed == pytest.approx(alone - 0.6 * kernel.COMPETITION_SHARE)
    overtopped = float(expected_cover_array(heath_profile, 0.8, 0.6, 0.8))
    assert overtopped == pytest.approx(pressed - 0.8 * kernel.OVERTOPPED_STRESS_PER_SEASON / (heath_profile.growth_rate * 0.8))
    assert float(expected_cover_array(heath_profile, 0.3, 1.0, 1.0)) == 0.0

    open_ground = resident_vegetation(ground, bounds, profiles, floras_of(**{HEATH["id"]: "dominant"}), cells=64)
    oaks_only = resident_vegetation(ground, bounds, profiles, floras_of(**{OAK["id"]: "dominant"}), cells=64)
    wood = resident_vegetation(ground, bounds, profiles, floras_of(**{OAK["id"]: "dominant", HEATH["id"]: "dominant"}), cells=64)
    oak, heath = wood.cover[OAK["id"]], wood.cover.get(HEATH["id"], np.zeros(wood.x.shape))
    closed = oak > 0.8
    assert closed.any()
    # Under closed oaks the shrub holds a small part of what the same ground gives it in the open ...
    assert heath[closed].mean() < 0.35 * open_ground.cover[HEATH["id"]][closed].mean()
    # ... and the oaks give way a little to what stands under them, by no more than the kernel's figure.
    alone = oaks_only.cover[OAK["id"]]
    assert (oak <= alone + 1e-12).all()
    assert (oak >= alone - heath * kernel.UNDERSTOREY_COMPETITION * kernel.COMPETITION_SHARE - 0.03).all()


def test_a_climber_stands_only_in_the_crowns_of_what_carries_it():
    world = _world(OAK, IVY)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    profiles = {entity["id"]: profile_from_entity(entity) for entity in (OAK, IVY)}
    assert layer_of(profiles[IVY["id"]]) == "climber"  # twenty metres long, and still no tree
    alone = resident_vegetation(ground, bounds, profiles, floras_of(**{IVY["id"]: "dominant"}), cells=64)
    assert alone.cover == {}
    wood = resident_vegetation(ground, bounds, profiles, floras_of(**{IVY["id"]: "dominant", OAK["id"]: "common"}), cells=64)
    oak, ivy = wood.cover[OAK["id"]], wood.cover[IVY["id"]]
    assert ivy.max() > 0.0 and ivy[oak == 0].max() == 0.0
    assert (ivy <= oak * CLIMBER_SUPPORT_SHARE + 1e-12).all()


class RiverGround:
    """A straight river down the middle of 400 m of ground, deep in mid-channel and shallow at its edges.

    The ground the generator would hand over: wet along the banks, drier
    with distance; soil a hand deep on the west side and metres deep on the
    east; the east side also turned away from the sun.
    """

    def _depth(self, x):
        return np.clip(8.0 - np.abs(np.asarray(x, dtype=np.float64) - 200.0) * 0.16, 0.0, None)  # 50 m to either side

    def sample_array(self, key, x, y, default=0.0):
        x = np.asarray(x, dtype=np.float64)
        away = np.clip(np.abs(x - 200.0) - 50.0, 0.0, None)
        if key == "water_depth_m":
            return self._depth(x)
        if key == "elevation_m":
            return 100.0 - self._depth(x) + away * 0.02
        if key == "soil_moisture":
            return np.where(away < 30.0, 0.40 - away * 0.01, 0.10)
        if key == "annual_precipitation_mm":
            return np.full(x.shape, 1000.0)
        if key == "soil_depth_m":
            return np.where(x < 200.0, 0.12, 3.0)
        if key == "surface_solar_exposure":
            return np.where(x < 300.0, 1.0, 0.55)
        return np.full(x.shape, default, dtype=np.float64)

    def open_water_array(self, x, y):
        return self._depth(x) > 0.05

    def koppen_at(self, _x, _y):
        return ("Cfb", "Temperate Oceanic")


def test_the_ground_decides_where_things_grow_water_depth_of_soil_and_sun():
    lily = {"id": "spec_test_lily", "_dataset": "species", "type": "species", "pretty_name": "Lily",
            "plant_growth_form": "aquatic", "moisture_preference": "aquatic", "shade_tolerance": "low"}
    profiles = {entity["id"]: profile_from_entity(entity) for entity in (OAK, HEATH, SEDGE, lily)}
    profiles[SEDGE["id"]] = replace(profiles[SEDGE["id"]], moisture_optimum=0.74, moisture_tolerance=0.2)
    profiles[HEATH["id"]] = replace(profiles[HEATH["id"]], moisture_optimum=0.45, moisture_tolerance=0.3,
                                    root_depth_class="shallow")
    profiles[OAK["id"]] = replace(profiles[OAK["id"]], moisture_optimum=0.45, moisture_tolerance=0.3, root_depth_class="deep")
    assert (rooting_depth_m(profiles[OAK["id"]]), rooting_depth_m(profiles[HEATH["id"]])) == (2.0, 0.35)
    assert rooting_depth_m(replace(profiles[OAK["id"]], root_depth_class="other_unknown")) == 1.5  # a tree's, by its form
    assert rooting_depth_m(replace(profiles[OAK["id"]], max_root_depth={"max_m": 4.0})) == 4.0
    np.testing.assert_allclose(rooting_response(profiles[OAK["id"]], np.array([0.1, 0.2, 0.5, 0.8, 5.0, np.nan])),
                               [0.0, 0.0, 0.5, 1.0, 1.0, 1.0])
    bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)
    floras = {}
    for biome in (CFB, Biome("Cfb", "Temperate Oceanic", "open_water")):
        floras[biome.key] = BiomeFlora(PLANET, biome)
        for entity in (OAK, HEATH, SEDGE, lily):
            floras[biome.key].record(entity["id"], "dominant")
    vegetation = resident_vegetation(RiverGround(), bounds, profiles, floras, cells=80)
    x, depth = vegetation.x, RiverGround()._depth(vegetation.x)
    lilies, sedge = vegetation.cover[lily["id"]], vegetation.cover[SEDGE["id"]]
    oak, heath = vegetation.cover[OAK["id"]], vegetation.cover[HEATH["id"]]
    land = depth == 0
    # Water: the lily holds the shallows along both edges and none of the deep channel.
    assert lilies[depth > AQUATIC_DEPTH_M[1]].max() == 0.0 < lilies[(depth > 0.1) & (depth < AQUATIC_DEPTH_M[0])].min()
    # Wetness: under a built soil the bank is still the wetter ground, so the sedge of wet ground holds it and
    # nothing further off, although the same rain falls on both.
    bank, beyond = land & (np.abs(x - 200.0) < 62.0), np.abs(x - 200.0) > 130.0
    assert sedge[bank].max() > 0.3 and sedge[beyond].max() == 0.0 and sedge[~land].max() == 0.0
    # Depth of soil: the oak stands on the deep ground east of the river and not on a hand of soil west of it;
    # the shallow-rooted heath takes the west bank.
    west, east = land & (x < 140.0), land & (x > 285.0) & (x < 300.0)  # east: beyond the bank, too wet for an oak
    assert oak[west].max() == 0.0 < oak[east].min()
    # (nearest the bank it gives way to the sedge, which stands as tall as a quarter of it and takes its room)
    assert np.median(heath[west]) > 0.5 and heath[west].min() > 0.05
    # Sun: on the slope turned away from it the same oak, on the same soil, holds less ground.
    shaded = land & (x > 310.0)
    assert 0.0 < oak[shaded].max() < oak[east].min()


def test_a_rare_plant_is_met_on_a_small_share_of_the_ground_that_suits_it_in_patches():
    world = _world(HEATH)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    # At home anywhere here, and spreading by runners: a plant that holds beds of its own.
    profile = replace(profile_from_entity(HEATH), moisture_optimum=0.45, moisture_tolerance=0.6,
                      waterlogging_tolerance="high", clonal_spread="high")
    held = {}
    for rarity in ("dominant", "common", "occasional", "rare"):
        vegetation = resident_vegetation(ground, bounds, {HEATH["id"]: profile}, floras_of(**{HEATH["id"]: rarity}), cells=96)
        land = ~np.asarray(ground.open_water_array(vegetation.x, vegetation.y), dtype=bool)
        cover = vegetation.cover[HEATH["id"]]
        held[rarity] = float((cover[land] > 0).mean())
        if rarity == "rare":
            # Where it grows it grows as well as anywhere; and its cells keep company, they are not salt and pepper.
            assert cover.max() > 0.5
            occupied = cover > 0
            neighbours = (np.roll(occupied, 1, 0) | np.roll(occupied, -1, 0) | np.roll(occupied, 1, 1) | np.roll(occupied, -1, 1))
            assert (occupied & neighbours).sum() > 0.8 * occupied.sum()
            x, y, share = vegetation.plants(HEATH["id"], 1.0, seed=3)
            assert len(x) > 0 and share.min() >= 0.15 and share.max() <= 1.0
            # A piece of the ground asked for alone holds the same plants as the whole does there.
            piece = (float(x[0]) - 40.0, float(y[0]) - 30.0, float(x[0]) + 40.0, float(y[0]) + 30.0)
            px, py, _share = vegetation.plants(HEATH["id"], 1.0, seed=3, window=piece)
            within = (x >= piece[0]) & (x < piece[2]) & (y >= piece[1]) & (y < piece[3])
            inside = (px >= piece[0]) & (px < piece[2]) & (py >= piece[1]) & (py < piece[3])
            assert within.any() and sorted(zip(x[within].tolist(), y[within].tolist())) == sorted(zip(px[inside].tolist(), py[inside].tolist()))
            # Single plants stand as often as the cover says, and end where the patch does, not where a cell does.
            assert abs(len(x) - cover.sum() * vegetation.cell_area_m2) < 0.15 * len(x)
            assert vegetation.stands_at(HEATH["id"], x, y).all()
            np.testing.assert_array_equal(vegetation.cover_at(HEATH["id"], vegetation.x, vegetation.y) > 0, occupied)
    # A rarity is a share of the planet's ground, in patches; a window holds more of them or fewer.  The patches
    # of one species are nested, the rarer inside the commoner.
    assert held["dominant"] > 0.97 and held["dominant"] >= held["common"] >= held["occasional"] >= held["rare"] > 0.0
    wide = np.random.default_rng(5).uniform(-2.0e6, 2.0e6, (3, 120_000))
    ranks = _ranked(_patch_noise(HEATH["id"], wide, 200.0, 0))
    for rarity, expected in RARITY_GROUND_SHARE.items():
        assert abs(float((ranks < expected).mean()) - expected) < 0.01, rarity
    # The same plant come from seed is met on more of the ground and stands thinner there, scattered through
    # the others; the cover it holds in all is the same.
    beds = resident_vegetation(ground, bounds, {HEATH["id"]: profile}, floras_of(**{HEATH["id"]: "occasional"}), cells=96)
    seeded = replace(profile, clonal_spread="none")
    scattered = resident_vegetation(ground, bounds, {HEATH["id"]: seeded}, floras_of(**{HEATH["id"]: "occasional"}), cells=96)
    assert (aggregation(profile), aggregation(seeded)) == (1.0, 0.5)
    land = ~np.asarray(ground.open_water_array(beds.x, beds.y), dtype=bool)
    in_beds, thinly = beds.cover[HEATH["id"]][land], scattered.cover[HEATH["id"]][land]
    assert (thinly > 0).mean() > 1.5 * (in_beds > 0).mean()
    assert thinly.max() < 0.6 * in_beds.max()
    assert 0.5 < thinly.sum() / in_beds.sum() < 2.0   # the patches of a window are a few: the sums differ by which it holds


def test_what_a_run_measured_of_a_plant_is_how_common_the_solver_makes_it():
    from simulations.biosphere.flora import ground_share_of

    # The rarities are steps on one line; a measured share is read off the line between them.
    for rarity, least in (("dominant", 0.50), ("common", 0.15), ("occasional", 0.03)):
        assert abs(ground_share_of(least) - RARITY_GROUND_SHARE[rarity]) < 1e-9 and rarity_from_share(least) == rarity
    assert ground_share_of(0.0) == RARITY_GROUND_SHARE["rare"] and ground_share_of(0.9) == 1.0
    assert RARITY_GROUND_SHARE["occasional"] < ground_share_of(0.05) < ground_share_of(0.12) < RARITY_GROUND_SHARE["common"]
    world = _world(HEATH)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    profile = replace(profile_from_entity(HEATH), moisture_optimum=0.45, moisture_tolerance=0.6, waterlogging_tolerance="high")
    held = []
    for measured in (0.05, 0.12):   # both "occasional"
        flora = BiomeFlora(PLANET, CFB)
        assert flora.record(HEATH["id"], rarity_from_share(measured), cover_share=measured) == "entered"
        assert flora.rarity(HEATH["id"]) == "occasional" and flora.ground_share(HEATH["id"]) == ground_share_of(measured)
        vegetation = resident_vegetation(ground, bounds, {HEATH["id"]: profile}, {CFB.key: flora}, cells=96)
        held.append(float(vegetation.cover[HEATH["id"]].sum()))
    assert held[1] > 1.3 * held[0]
    # One a collection set keeps what its letter stands for, whatever a plot measured of it since.
    flora = BiomeFlora(PLANET, CFB)
    flora.assign_collection(plant_collection("biosphere_collection_test", "Test", {HEATH["id"]: "common"}))
    flora.record(HEATH["id"], "rare", cover_share=0.01)
    assert (flora.rarity(HEATH["id"]), flora.ground_share(HEATH["id"])) == ("common", RARITY_GROUND_SHARE["common"])
    assert BiomeFlora(PLANET, CFB).ground_share(HEATH["id"]) is None


# ----------------------------------------------------------------------
# From a Biosphere run to a city
# ----------------------------------------------------------------------
def test_a_plant_established_in_a_biosphere_is_found_growing_by_a_city_of_the_same_biome():
    pygame.init()
    world = _world()
    region = world.get_entity(REGION_ID)

    # A city founded before anything is established has bare ground.
    city = city_site.found_city(world, REGION_ID, year=2400)
    city_ground = city_site.city_substrate(world, city)
    assert city_vegetation(world, city, city_ground) is None
    city_map = MapSimulation(SimulationContext(year=2400, root_entity_id=city["id"], world_model=world))
    assert city_map._resident_vegetation_layers() == []

    # A Biosphere on the same planet: ryegrass sown wide on built soil takes, and is entered in the biome's flora.
    root, _ground = site(world)
    sim = BiosphereSimulation(world, {"patch_location_id": root["id"], "year": 2400})
    sim._set_domain({"min_x": 340.0, "max_x": 460.0, "min_y": 10.0, "max_y": 118.0})
    sim.soil.organic_matter_rows = [[4.0] * sim.soil.columns for _ in range(sim.soil.rows)]
    sim.soil.revision += 1
    sim.ecology.introduce(GRASS, 400.0, 64.0, 30.0, 0.5)
    sim.advance_seasons(12)
    flora = planet_floras(world, PLANET)["Cfb"]
    assert flora.species() == [GRASS] and flora.records[GRASS].established_year >= 2401
    assert flora.rarity(GRASS) == rarity_from_share(flora.records[GRASS].cover_share)
    assert any("is now part of the Temperate Oceanic flora" in note["text"] for note in sim.field_notes)
    assert world.get_entity(flora.entity_id)["sessile_life_species"] == [GRASS]  # and written where the session may

    # The city of the same biome now carries it, where its ground suits it and not on the water.
    vegetation, profiles, spacing = city_vegetation(world, city, city_ground)
    assert set(vegetation.cover) == {GRASS} and vegetation.share(GRASS) > 0.0
    cover = city_plant_cover(world, city, city_ground)
    alpha = pygame.surfarray.array_alpha(cover.ground)
    assert alpha.max() > 60 and alpha[2, alpha.shape[1] // 2] == 0  # grass on the land, none on the west edge's water
    assert not cover.field  # and no shrub or tree, for none is established
    layers = city_map._resident_vegetation_layers()
    assert [(layer["shape"], layer["name"]) for layer in layers] == [("image_rect", "Resident ground cover")]
    assert any(item.get("name") == "Resident ground cover" for item in city_map._build_layers(2400))

    # A collection named on the flora's entity sets what is common there, sown or not: from the next look on.
    world.loader.persist_entity(dict(OAK))
    world.loader.persist_entity(plant_collection("biosphere_collection_oakwood", "Oakwood", {"spec_test_oak": "dominant"}))
    stored = world.get_entity(flora.entity_id)
    world.loader.persist_entity({**stored, "plant_collection": "biosphere_collection_oakwood"})
    flora = planet_floras(world, PLANET)["Cfb"]
    assert (flora.rarity("spec_test_oak"), flora.records["spec_test_oak"].rarity_source) == ("dominant", "collection")
    assert world.get_entity(flora.entity_id)["sessile_life_species"] == ["spec_test_oak", GRASS]
    assert set(city_vegetation(world, city, city_ground)[0].cover) == {GRASS, "spec_test_oak"}
    # And it follows the collection: a species added to it is in the flora too.
    world.loader.persist_entity(dict(HEATH))
    world.loader.persist_entity(plant_collection("biosphere_collection_oakwood", "Oakwood",
                                                 {"spec_test_oak": "dominant", HEATH["id"]: "rare"}))
    assert planet_floras(world, PLANET)["Cfb"].rarity(HEATH["id"]) == "rare"
    wooded = city_map._resident_vegetation_layers()
    assert [layer["shape"] for layer in wooded] == ["image_rect", "image_rect", "plant_field"]
    # The whole city at once is one picture of its crowns; from a set scale on, the plants themselves.
    assert wooded[1]["max_zoom"] == wooded[2]["min_zoom"] and "spec_test_oak" in wooded[2]["_plant_field"].species
    assert region["refinement_root_planet_id"] == PLANET


def test_the_plants_of_a_city_are_their_species_own_pictures_from_above_coarser_the_further_out():
    pygame.init()
    world = _world(OAK, HEATH)
    _root, ground = site(world)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    profiles = {entity["id"]: profile_from_entity(entity) for entity in (OAK, HEATH)}
    vegetation = resident_vegetation(ground, bounds, profiles, floras_of(**{OAK["id"]: "common", HEATH["id"]: "common"}), cells=64)

    # The planet keeps each species from above: its own individuals, full-grown, as Species Sim draws them.
    pictures = planet_plant_pictures(world, PLANET)
    from_above = pictures.map_sprite(OAK["id"], 0)
    assert 0.6 * MAP_SPRITE_PX <= max(from_above.get_size()) <= MAP_SPRITE_PX + 8
    assert pictures.map_sprite(OAK["id"], 0) is from_above and pictures.map_sprite(OAK["id"], 1) is not from_above
    # A coarser picture is made from it: a few pixels, each of them plant or not.
    coarse = map_sprite_at(from_above, 12)
    assert max(coarse.get_size()) == 12
    assert sorted(set(pygame.surfarray.array_alpha(coarse).ravel().tolist())) == [0, 255]
    assert map_sprite_at(from_above, max(from_above.get_size())) is from_above

    field = PlantField(vegetation, profiles, {OAK["id"]: 9.0, HEATH["id"]: 0.6}, pictures, seed=5, overview_long_side_px=512)
    kind, plant_x, plant_y, radius_m = field.plants_in((0.0, 0.0, 512.0, 256.0))
    oaks = kind == field.species.index(OAK["id"])
    assert oaks.any() and (~oaks).any() and field.species == [HEATH["id"], OAK["id"]]  # the lower is drawn first
    assert radius_m[oaks].max() <= 9.0 * 0.62 and (np.diff(kind) >= 0).all()
    # The whole ground at once: an oak is a small picture of an oak, a heath bush too small for one, a tint.
    assert field.overview.get_size() == (512, 256) and pygame.surfarray.array_alpha(field.overview).max() == 255

    # Close in a painted pixel is a screen pixel, and the oak lies where the tree stands.
    grown = oaks & (radius_m > 4.0)
    x, y = float(plant_x[grown][0]), float(plant_y[grown][0])
    window = (x - 20.0, y - 20.0, x + 20.0, y + 20.0)
    assert pixel_px(16.0) == 1.0 and PlantField._level(16.0) == 8
    close = field.tiles(window, 16.0, budget_ms=1e9)
    picture, start, end = next(item for item in close if item[1][0] <= x < item[2][0] and item[1][1] <= y < item[2][1])
    around = pygame.Rect(int((x - start[0]) * 16.0) - 40, int((y - start[1]) * 16.0) - 40, 80, 80).clip(picture.get_rect())
    assert pygame.surfarray.array_alpha(picture.subsurface(around)).max() == 255
    # The pictures of a view meet edge to edge: where one ends the next begins.
    starts = {item[1] for item in close}
    assert any((item[2][0], item[1][1]) in starts for item in close)
    assert all(picture.get_width() == math.ceil((end[0] - start[0]) * 16.0) for picture, start, end in close)

    # Further out a painted pixel takes two screen pixels, then three: the same ground in fewer, larger pixels.
    assert pixel_px(4.0) == 2.0 and pixel_px(0.5) == 3.0
    assert 2.0 ** (PlantField._level(4.0) / 2.0) == 2.0 and 2.0 ** (PlantField._level(1.0) / 2.0) < 0.36
    further = field.tiles(window, 4.0, budget_ms=1e9)
    assert all(picture.get_width() == math.ceil((end[0] - start[0]) * 4.0) for picture, start, end in further)
    # A tile not painted yet shows its piece of the overview until its turn comes.
    level = PlantField._level(8.0)
    wide = field.tiles((0.0, 0.0, 512.0, 256.0), 8.0, budget_ms=0.0)
    assert len(wide) > 1 and len([key for key in field._tiles if key[0] == level]) == 1


# ----------------------------------------------------------------------
# What the ground gives the played kernel
# ----------------------------------------------------------------------
def test_a_built_soil_keeps_the_wetter_ground_wetter_and_reads_the_soils_chemistry():
    world = _world()
    root, _ground = site(world)
    sim = BiosphereSimulation(world, {"patch_location_id": root["id"], "year": 2400})
    sim._set_domain({"min_x": 60.0, "max_x": 460.0, "min_y": 10.0, "max_y": 118.0})
    dry, wet = sim.ecology.abiotic_environment_at(80.0, 64.0), sim.ecology.abiotic_environment_at(440.0, 64.0)
    assert wet["soil_moisture"] - dry["soil_moisture"] > 0.2
    assert dry["typical_soil_moisture"] == wet["typical_soil_moisture"]  # one figure for the whole site
    sim.soil.organic_matter_rows = [[4.0] * sim.soil.columns for _ in range(sim.soil.rows)]
    sim.soil.revision += 1
    built_dry, built_wet = sim.ecology.environment_at(80.0, 64.0), sim.ecology.environment_at(440.0, 64.0)
    # The soil adds the same to both: what the terrain made wetter stays as much wetter.
    assert built_dry["moisture_retention_bonus"] == built_wet["moisture_retention_bonus"]
    assert abs((built_wet["soil_moisture"] - built_dry["soil_moisture"])
               - (wet["soil_moisture"] - dry["soil_moisture"])) < 1e-9
    assert mature_wetness(0.1, 1000.0, 0.3) - mature_wetness(0.05, 1000.0, 0.3) == pytest.approx(0.05)
    assert mature_wetness(0.1, 1000.0) == pytest.approx(mature_wetness(0.05, 1000.0))  # each lifted on its own: levelled
    # The generator gives no fertility; what life built counts as far as the soil's reaction and salt allow.
    assert (mineral_soil_index(6.5), mineral_soil_index(4.5), mineral_soil_index(8.5), mineral_soil_index(10.0)) == (1.0, 0.5, 0.5, 0.0)
    assert mineral_soil_index(6.5, 0.25) == 0.75
    assert built_dry["mineral_soil_index"] == mineral_soil_index(built_dry["soil_ph"], built_dry["soil_salinity_index"])
    assert "reaction and salt" in built_dry["soil_fertility_source"]


def test_a_slope_turned_from_the_sun_gets_less_of_it_and_generated_ground_carries_that():
    y = np.arange(60)[:, None] * 10.0
    ridge = np.where(y < 300.0, y, 600.0 - y) * 0.36 * np.ones((60, 40))  # west to east, twenty degrees either side
    north = surface_solar_exposure(ridge, 10.0, 10.0, 45.0)
    south = surface_solar_exposure(ridge, 10.0, 10.0, -45.0)
    assert surface_solar_exposure(np.zeros((8, 8)), 10.0, 10.0, 45.0).min() == 1.0  # level ground is the measure
    assert north[50, 5] == 1.0 and 0.7 < north[10, 5] < 0.85  # in the north the face to the south has the sun
    assert south[10, 5] == 1.0 and south[50, 5] == pytest.approx(north[10, 5])
    assert surface_solar_exposure(ridge, 10.0, 10.0, 0.0)[10, 5] == pytest.approx(surface_solar_exposure(ridge, 10.0, 10.0, 0.0)[50, 5])
    heightmap = {"sample_grid": {"rows": ridge.tolist()}, "sample_spacing_x_m": 10.0, "sample_spacing_y_m": 10.0,
                 "source_uv_bounds": {"min_u": 0.2, "max_u": 0.21, "min_v": 0.245, "max_v": 0.255}}
    carried = with_surface_solar_exposure(heightmap, {"status": "water_cycle_seeded"}, 23.44)["insolation_grid"]
    assert (carried["width"], carried["height"], carried["latitude_deg"]) == (40, 60, 45.0)
    assert carried["surface_solar_exposure_rows"][10][5] == round(float(north[10, 5]), 3)
    assert with_surface_solar_exposure({"sample_grid": {"rows": []}}, {"a": 1}) == {"a": 1}
