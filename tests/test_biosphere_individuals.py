"""Stands kept as individuals: recorded plants, the few simulated in depth, and the planet's kept pictures."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.individuals import IndividualRegister
from simulations.biosphere.plant_pictures import FOUNDERS, STAGES, planet_plant_pictures, stage_of
from simulations.biosphere.vegetation import VegetationSampler


SHRUB = dict(id="shrub", plant_growth_form="shrub")
GRASS = dict(id="grass", plant_growth_form="graminoid")
CRUST = dict(id="crust", plant_growth_form="lichen")
BAMBOO = dict(id="bamboo", plant_growth_form="graminoid", mature_height={"max_m": 12})
BIRCH = "spec_betula_pendula"


def ecology_of(*entities, side=60):
    return BiosphereEcology(dict(min_x=0, max_x=side, min_y=0, max_y=side), [profile_from_entity(e) for e in entities])


def members_of(ecology, species_id):
    return ecology.individuals.members(ecology.species_patches(species_id)[0].patch_id)


def birch_site(grown=None):
    """A sown birch stand; ``grown`` puts its plants at that share of full size before any is followed."""
    sim = BiosphereSimulation.reference_site()
    sim.ecology.introduce(BIRCH, 5, 5, 4.5, 0.8)
    if grown is not None:
        sim.ecology.patches[0].development_days = sim.ecology.profiles[BIRCH].maturity_days * grown
    sim.representatives.sync_from_population(sim.ecology)
    return sim


# ----------------------------------------------------------------------
# What is recorded
# ----------------------------------------------------------------------
def test_plants_drawn_as_bodies_are_recorded_one_by_one_and_cover_is_not():
    ecology = ecology_of(SHRUB, GRASS, CRUST, BAMBOO)
    keeps = {species_id: ecology.keeps_individuals(profile) for species_id, profile in ecology.profiles.items()}
    assert keeps == {"shrub": True, "grass": False, "crust": False, "bamboo": True}  # a tall grass is plants, a sward is not
    for index, species_id in enumerate(keeps):
        ecology.introduce(species_id, 15 + 10 * index, 30, 4.0, 0.5)
    summary = {item["species_id"]: item for item in ecology.summary()["species"]}
    assert summary["grass"]["individuals"] is None and summary["crust"]["individuals"] is None
    assert members_of(ecology, "grass") is None

    stand = ecology.species_patches("shrub")[0]
    plants = members_of(ecology, "shrub")
    spacing = ecology.spacing_m(ecology.profiles["shrub"])
    # Half the room of the disc was sown: that many plants, one to a place, all inside it.
    assert len(plants) == summary["shrub"]["individuals"] == round(0.5 * np.pi * 4.0 ** 2 / spacing ** 2)
    assert np.hypot(plants.x - stand.x, plants.y - stand.y).max() <= stand.radius_m
    places = set(zip(np.floor(plants.x / spacing).tolist(), np.floor(plants.y / spacing).tolist()))
    assert len(places) == len(plants)
    assert abs(stand.abundance - 0.5) < 0.02  # the stand's cover is its plants over its room


def test_a_single_plant_set_by_hand_stands_where_it_was_set_on_ground_of_its_own():
    ecology = ecology_of(dict(id="oak", plant_growth_form="tree", mature_height={"max_m": 40}))
    ecology.introduce("oak", 30, 30, 1.5, 0.3)
    stand, plants = ecology.species_patches("oak")[0], members_of(ecology, "oak")
    assert (plants.x.tolist(), plants.y.tolist()) == ([30.0], [30.0])
    # Less than a plant cannot be sown, and a stand is never less than the ground its plants take.
    assert np.pi * stand.radius_m ** 2 >= ecology.spacing_m(ecology.profiles["oak"]) ** 2 * 0.999


# ----------------------------------------------------------------------
# How a stand of plants fares
# ----------------------------------------------------------------------
def test_a_stand_fills_to_the_cover_the_kernel_expects_and_then_keeps_its_plants():
    ecology = ecology_of(SHRUB)
    ecology.introduce("shrub", 30, 30, 9.0, 0.1)
    stand = ecology.species_patches("shrub")[0]
    profile = ecology.profiles["shrub"]
    sown = len(members_of(ecology, "shrub"))
    ecology.advance(120)
    stand = max(ecology.species_patches("shrub"), key=lambda patch: patch.radius_m)
    suitability = ecology._suitability(profile, ecology.environment_at(stand.x, stand.y, 0.5, stand.patch_id))
    plants = ecology.individuals.members(stand.patch_id)
    assert len(plants) > 3 * sown
    assert abs(stand.abundance - ecology.expected_cover(profile, suitability)) < 0.2
    # At its balance the stand is the same plants from one year to the next, not a churn of places.
    before = set(plants.uid.tolist())
    ecology.advance(4)
    after = set(ecology.individuals.members(stand.patch_id).uid.tolist())
    assert len(before & after) > 0.9 * len(before)


def test_where_the_ground_does_not_carry_the_species_its_plants_go():
    ecology = ecology_of(SHRUB)
    ecology.profiles["shrub"] = replace(ecology.profiles["shrub"], moisture_optimum=0.99, moisture_tolerance=0.08)
    ecology.introduce("shrub", 40, 12, 6.0, 0.6)
    sown = len(members_of(ecology, "shrub"))
    ecology.advance(12)
    assert sum(len(ecology.individuals.members(p.patch_id)) for p in ecology.species_patches("shrub")) < sown
    ecology.advance(200)
    assert ecology.species_patches("shrub") == [] and ecology.individuals.stands == {}


def test_neighbours_take_after_the_simulated_plant_nearest_to_them_at_half_to_one_and_a_half_strength():
    ecology = ecology_of(SHRUB)
    assert ecology.NEIGHBOUR_EFFECT == (0.5, 1.5)
    x, y = np.array([1.0, 2.0, 48.0, 49.0]), np.zeros(4)
    thriving, failing = (0.0, 0.0, 1.4, 0.004), (50.0, 0.0, 0.7, 0.016)
    feedback = {"simulated": [thriving, failing]}
    for strength in (0.5, 1.0, 1.5):
        growth, mortality = ecology._neighbour_effect("shrub", x, y, np.full(4, strength), feedback)
        np.testing.assert_allclose(growth, [1 + 0.4 * strength] * 2 + [1 - 0.3 * strength] * 2)
        np.testing.assert_allclose(mortality, [0.004 * strength] * 2 + [0.016 * strength] * 2)
    # Before any plant of the species is simulated, the species' own figures stand in.
    growth, mortality = ecology._neighbour_effect("shrub", x, y, np.ones(4), {"growth_multiplier": 1.2})
    assert growth.tolist() == [1.2] * 4 and mortality.tolist() == [0.0] * 4


def test_plants_beside_a_thriving_simulated_neighbour_outgrow_those_beside_a_failing_one_each_in_its_own_measure():
    ecology = ecology_of(SHRUB, side=120)
    ecology.introduce("shrub", 30, 60, 8.0, 0.3)
    ecology.introduce("shrub", 90, 60, 8.0, 0.3)
    near_thriving, near_failing = (ecology.individuals.members(patch.patch_id) for patch in ecology.species_patches("shrub"))
    founders = (len(near_thriving), len(near_failing))
    feedback = {"shrub": {"simulated": [(30.0, 60.0, 1.6, 0.0), (90.0, 60.0, 0.4, 0.0)]}}
    ecology.advance(6, representative_feedback=feedback)
    # ``lag_days`` is how far a plant is behind its stand's founding cohort: ahead of it beside the one, behind beside the other.
    ahead, behind = near_thriving.lag_days[:founders[0]], near_failing.lag_days[:founders[1]]
    assert ahead.max() < 0.0 < behind.min()
    assert ahead.std() > 1.0 and behind.std() > 1.0  # no two plants take after their neighbour alike


def test_a_species_too_many_to_record_is_kept_as_records_that_each_stand_for_several_plants():
    register = IndividualRegister()
    register.add("stand", "herb", np.arange(1000.0), np.zeros(1000), 0.0, 0, 0)
    followed = int(register.members("stand").uid[7])
    register.simulated.add(followed)
    register.coarsen("herb", np.random.default_rng(3))
    members = register.members("stand")
    assert register.unit_of("herb") == 2 and 350 < len(members) < 650
    assert abs(members.plants() - 1000.0) < 1e-3  # no plant is lost by it
    assert followed in members.uid.tolist()        # and a plant followed in depth is never the one to go
    register.add("stand", "herb", [5000.0], [0.0], 0.0, 1, 0)
    assert register.members("stand").count[-1] == 2.0  # a new record stands for as many as the others


# ----------------------------------------------------------------------
# The planet's kept pictures
# ----------------------------------------------------------------------
def test_a_planet_keeps_ten_individuals_of_a_species_from_where_it_first_settled():
    sim = BiosphereSimulation.reference_site()
    pictures = sim.plant_pictures
    assert pictures is planet_plant_pictures(sim.world_model, pictures.planet_id)
    assert not pictures.settled(BIRCH)
    sim.ecology.introduce(BIRCH, 5, 5, 4.5, 0.8)
    assert pictures.settled(BIRCH) and pictures.count(BIRCH) == FOUNDERS == 10
    founders = pictures.individuals[BIRCH]
    assert len({individual.seed for individual in founders}) == FOUNDERS
    assert all(individual.origin == "founder" and "ground_light" in individual.conditions for individual in founders)
    sim.ecology.introduce(BIRCH, 2, 8, 1.0, 0.8)  # a second sowing finds them there
    assert pictures.individuals[BIRCH] is founders and pictures.count(BIRCH) == FOUNDERS
    # Every recorded plant looks like one of them.
    variants = sim.ecology.species_individuals(BIRCH)["variant"]
    assert len(set(variants.tolist())) > 3 and variants.min() >= 0 and variants.max() < FOUNDERS


def test_a_kept_individual_has_one_body_per_stage_and_a_display_plant_is_drawn_from_it():
    sim = birch_site()
    pictures = sim.plant_pictures
    assert [stage_of(share) for share in (0.0, 0.2, 0.5, 0.9, 1.0)] == [0.06, 0.16, 0.48, 0.85, 1.0]
    young, grown = pictures.body(BIRCH, 3, 0.16), pictures.body(BIRCH, 3, 1.0)
    assert pictures.body(BIRCH, 3, 0.2) is young and pictures.body(BIRCH, 3, 1.0) is grown  # grown once, kept
    assert young.seed == grown.seed == pictures.seed(BIRCH, 3) != pictures.seed(BIRCH, 4)
    assert young.render_snapshot.bounds_m[5] < grown.render_snapshot.bounds_m[5]
    assert len(STAGES) == 7
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    plant = VegetationSampler().sample(sim.ecology, sim.get_species_sprite_instances())[0]
    assert renderer._species_case(sim, plant) is pictures.body(BIRCH, plant["variant"], plant["display_maturity"])


# ----------------------------------------------------------------------
# The plants simulated in depth
# ----------------------------------------------------------------------
def test_the_plants_simulated_in_depth_are_a_few_of_the_recorded_plants_spread_over_the_stand():
    sim = birch_site(grown=0.5)
    organisms = sim.representatives.items(BIRCH, alive_only=True)
    plants = sim.ecology.species_individuals(BIRCH)
    assert len(organisms) == sim.representatives.SIMULATED_PER_STAND == 3 < len(plants["uid"])
    place = {int(uid): (float(x), float(y)) for uid, x, y in zip(plants["uid"], plants["x"], plants["y"])}
    assert all(place[organism.individual_uid] == (organism.x, organism.y) for organism in organisms)
    assert sim.ecology.individuals.simulated == {organism.individual_uid for organism in organisms}
    # Not three neighbours: each stands for a part of the stand.
    apart = [np.hypot(a.x - b.x, a.y - b.y) for a in organisms for b in organisms if a is not b]
    assert min(apart) > 2.0
    # A plant followed from the age it had keeps the look of the kept individual it was drawn as.
    variant = {int(uid): int(v) for uid, v in zip(plants["uid"], plants["variant"])}
    assert all(organism.seed == sim.plant_pictures.seed(BIRCH, variant[organism.individual_uid]) for organism in organisms)


def test_when_a_simulated_plant_dies_another_plant_is_picked_and_followed_from_the_age_it_has():
    sim = birch_site(grown=0.5)
    before = sim.representatives.items(BIRCH, alive_only=True)
    old, failed = before[0], before[1]
    old.age_days = 1e9        # dies of old age this season
    failed.health = -10.0     # and this one of its condition
    sim.advance_seasons(1)
    assert (old.alive, old.death_cause) == (False, "old age")
    assert (failed.alive, failed.death_cause) == (False, "poor condition")
    after = sim.representatives.items(BIRCH, alive_only=True)
    assert len(after) == 3 and before[2] in after
    picked = [organism for organism in after if organism not in before]
    assert len(picked) == 2 and not {o.individual_uid for o in picked} & {old.individual_uid, failed.individual_uid}
    # Each is followed from the age its plant had, not from seed.
    assert all(organism.age_days > 0.3 * sim.ecology.profiles[BIRCH].maturity_days for organism in picked)
    plants = sim.ecology.species_individuals(BIRCH)
    share = {int(uid): float(s) for uid, s in zip(plants["uid"], plants["share"])}
    # The old plant left its place to a seedling of its own; the failed one left a gap.
    assert share[old.individual_uid] < 0.03 and failed.individual_uid not in share
    assert sim.ecology.individuals.simulated == {organism.individual_uid for organism in after}


def test_a_simulated_seedling_that_comes_of_age_joins_the_planets_kept_pictures():
    sim = birch_site()  # freshly sown: the plants picked are seedlings, each a plant of its own
    organism = sim.representatives.items(BIRCH, alive_only=True)[0]
    pictures = sim.plant_pictures
    assert not organism.in_pictures and pictures.variant_of(BIRCH, organism.seed) is None
    organism.health = 1.0
    sim.representatives.grow_body(organism, sim.representatives.life_timing(organism).maturity_days)
    sim.advance_seasons(1)
    assert organism.alive and organism.in_pictures
    joined = pictures.variant_of(BIRCH, organism.seed)
    assert joined == FOUNDERS and pictures.individuals[BIRCH][joined].origin == "grown"
    plants = sim.ecology.species_individuals(BIRCH)
    assert int(plants["variant"][plants["uid"].tolist().index(organism.individual_uid)]) == joined  # it is that individual now
    sim.advance_seasons(1)
    assert pictures.count(BIRCH) == FOUNDERS + 1  # once, not every season


# ----------------------------------------------------------------------
# What a view shows
# ----------------------------------------------------------------------
def test_a_view_shows_the_recorded_plants_within_its_budget_and_puts_back_what_a_record_stands_for():
    ecology = ecology_of(SHRUB)
    ecology.introduce("shrub", 30, 30, 9.0, 0.6)
    plants = ecology.species_individuals("shrub")
    sampler = VegetationSampler()
    everything = sampler.sample(ecology, [])
    assert sorted(plant["individual_uid"] for plant in everything) == sorted(plants["uid"].tolist())
    assert all(plant["display_only"] and plant["display_maturity"] in STAGES for plant in everything)
    # A window shows what stands in it.
    half = sampler.sample(ecology, [], window=(-100.0, 0.0, 0.0, 200.0))
    assert 0 < len(half) < len(everything) and all(plant["x"] - plant["y"] <= 0.0 for plant in half)
    # More plants than the budget: some are left out, the same ones each time.
    thrifty = VegetationSampler()
    thrifty.MAX_INSTANCES = 40
    few = thrifty.sample(ecology, [])
    assert 0 < len(few) < 80 and {plant["individual_uid"] for plant in few} <= set(plants["uid"].tolist())
    again = VegetationSampler()
    again.MAX_INSTANCES = 40
    assert again.sample(ecology, []) == few
    # A record that stands for four plants is drawn as four where there is budget for it.
    members = members_of(ecology, "shrub")
    members.count[:] = 4.0
    ecology.individuals.revision += 1
    expanded = sampler.sample(ecology, [])
    assert len(expanded) == 4 * len(everything)
    assert sum(plant["individual_uid"] is not None for plant in expanded) == len(everything)
