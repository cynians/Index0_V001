from copy import deepcopy
from dataclasses import replace
from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.vegetation import VegetationSampler
from simulations.species.forest_ecology import shade_profile


def fixture(tolerance="low", canopy_light=True, birch=(5, 5, 4.5)):
    tree = profile_from_entity(dict(id="oak", plant_growth_form="tree", mature_height={"max_m": 20},
                                   plant_crown_openness={"typical": .43}, shade_tolerance="medium"))
    seedling = profile_from_entity(dict(id="birch", plant_growth_form="tree", shade_tolerance=tolerance))
    ecology = BiosphereEcology(dict(min_x=0, max_x=10, min_y=0, max_y=10), [tree, seedling])
    for x, y in ((4.15, 4.65), (5.85, 5.35)):
        ecology.introduce("oak", x, y, 2.65, .85)
        ecology.patches[-1].development_days = tree.maturity_days
    ecology.canopy_light_enabled = canopy_light
    ecology.introduce("birch", *birch, .72)
    return ecology


def birches(ecology):
    return ecology.species_individuals("birch")


def test_authored_shade_trait_uses_shared_threshold_and_explicit_zero_takes_priority():
    for value in ("low", "medium", "high"):
        profile = profile_from_entity(dict(id="plant", shade_tolerance=value))
        assert profile.light_minimum == shade_profile(value)["minimum_light"]
        assert profile.light_requirement_source == "shade_tolerance qualitative default"
    profile = profile_from_entity(dict(id="plant", shade_tolerance="low", biosphere_growth_profile={"light_minimum": 0}))
    assert profile.light_minimum == 0
    assert profile.light_requirement_source == "authored biosphere light_minimum"
    unknown = profile_from_entity(dict(id="plant", plant_growth_form="tree", shade_tolerance="other_unknown"))
    assert unknown.light_minimum == .22
    bad = profile_from_entity(dict(id="plant", shade_tolerance="low", biosphere_growth_profile={"light_minimum": float("nan")}))
    assert bad.light_minimum == .55
    assert bad.light_requirement_source == "shade_tolerance qualitative default"


def test_seedlings_favour_edges_and_open_gaps_without_moving_existing_canopies():
    ecology = fixture()
    original = deepcopy(ecology.canopy_footprints())
    assert ecology.recruitment_at("birch", 5, 5) == 0
    assert ecology.recruitment_at("birch", 1, 5) == 1
    assert ecology.abundance_at("birch", 5, 5) == 0
    assert ecology.abundance_at("birch", 1, 5) > 0
    for p in ecology.species_patches("oak"):
        p.abundance = 0
    assert ecology.recruitment_at("birch", 5, 5) == 1
    assert [(p["x"], p["y"]) for p in original] == [(p["x"], p["y"]) for p in ecology.canopy_footprints()]


def test_higher_shade_tolerance_accepts_more_sites_not_different_neighbour_geometry():
    counts = []
    footprints = []
    for tolerance in ("low", "medium", "high"):
        ecology = fixture(tolerance)
        counts.append(sum(ecology.recruitment_at("birch", (x+.5)/4, (y+.5)/4) >= .99
                          for x in range(40) for y in range(40)))
        footprints.append(ecology.canopy_footprints())
    assert counts[0] < counts[1] < counts[2]
    assert footprints[0] == footprints[1] == footprints[2]


def test_seedlings_root_where_the_light_lets_them_and_are_not_moved_by_it_afterwards():
    shaded = fixture()
    plants = birches(shaded)
    # Sown under two oaks, birch takes only at their edge and in the open.
    assert len(plants["x"]) > 0
    assert all(shaded.recruitment_at("birch", x, y) > 0 for x, y in zip(plants["x"].tolist(), plants["y"].tolist()))
    assert len(birches(fixture(canopy_light=False))["x"]) > len(plants["x"])
    # The plants are recorded, not a picture of the light: switching it off shows the same ones.
    sampler = VegetationSampler()
    shown = sampler.sample(shaded, [])
    shaded.canopy_light_enabled = False
    assert shaded.recruitment_at("birch", 5, 5) == 1
    assert sampler.sample(shaded, []) == shown
    assert sum(plant["species_id"] == "birch" for plant in shown) == len(plants["x"])
    shaded.canopy_light_enabled = True
    shaded.profiles["birch"] = replace(shaded.profiles["birch"], light_minimum=0)
    assert shaded.recruitment_at("birch", 5, 5) == 1


def test_bright_seedbed_margins_survive_dark_centre_and_failed_cohorts_do_not_mature():
    ecology = fixture()
    birch = ecology.species_patches("birch")[0]
    support, _ = ecology._cohort_support(birch)
    assert .2 < support < .9
    ecology.advance(1)
    assert 1 < birch.development_days < 1 + ecology.DAYS_PER_SEASON
    # Sown wholly in the dark between the two crowns, nothing takes and the stand is gone with the season.
    blocked = fixture(birch=(5, 5, .2))
    assert blocked.recruitment_at("birch", 5, 5) == 0
    assert len(birches(blocked)["x"]) == 0
    blocked.advance(1)
    assert blocked.species_patches("birch") == []


def test_representative_sites_reach_bright_margins_and_never_place_in_rejected_holes():
    ecology = fixture()
    sites = ecology.representative_sites("birch", count=32)
    assert len(sites) >= 4
    assert all(ecology.recruitment_at("birch", x, y) > 0 and value > .003 for value, x, y in sites)


def test_new_adults_retain_their_establishment_holes():
    ecology = fixture()
    birch = ecology.species_patches("birch")[0]
    # The seedbed stage ends long before a tree is full-grown: it is the short
    # establishment span, not the years to mature size.
    birch.development_days = ecology.establishment_days(ecology.profiles["birch"]) - .01
    assert ecology.establishment_days(ecology.profiles["birch"]) < ecology.profiles["birch"].maturity_days
    ecology.advance(1)
    assert birch.establishment_canopies is not None
    assert ecology.abundance_at("birch", 5, 5) == 0
    assert ecology.abundance_at("birch", 1, 5) > 0


def test_light_is_bounded_order_independent_and_not_tied_to_display_budget():
    a, b = fixture(), fixture()
    b.patches.reverse()
    for x, y in ((5, 5), (1, 5), (5, 9)):
        assert .0 <= a.ground_light_at(x, y) <= 1
        assert a.ground_light_at(x, y) == b.ground_light_at(x, y)
    a.advance(3)
    b.advance(3)
    assert a.summary() == b.summary()
    before = a.ground_light_at(5, 5)
    sampler = VegetationSampler()
    sampler.MAX_INSTANCES = 5
    sampler.sample(a, [])
    assert a.ground_light_at(5, 5) == before


def test_canopy_openness_zero_and_development_changes_invalidate_cache():
    ecology = fixture()
    shade = ecology.ground_light_at(5, 5)
    ecology.profiles["oak"] = replace(ecology.profiles["oak"], crown_openness=0)
    assert ecology.ground_light_at(5, 5) < shade
    for p in ecology.species_patches("oak"):
        p.development_days = 0
    assert ecology.ground_light_at(5, 5) > shade
