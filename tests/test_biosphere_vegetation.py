from copy import deepcopy
from types import SimpleNamespace

import pygame

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.vegetation import VegetationSampler


def fixture(species_id="spec_lolium_perenne", abundance=0.8):
    sim = BiosphereSimulation.reference_site()
    sim.ecology.introduce(species_id, 5, 5, 4.5, abundance)
    sim.representatives.sync_from_population(sim.ecology)
    return sim


def test_visuals_fill_population_without_mutating_ecology_or_representatives():
    sim = fixture()
    before = deepcopy(sim.ecology.summary())
    reps = sim.get_species_sprite_instances()
    samples = VegetationSampler().sample(sim.ecology, reps)
    assert len(samples) > 400
    assert all(i["display_only"] and not i.get("representative_id") for i in samples)
    assert all(sim.ecology.contains(i["x"], i["y"]) for i in samples)
    assert all(sim.ecology.abundance_at(i["species_id"], i["x"], i["y"]) > 0 for i in samples)
    assert sim.ecology.summary() == before
    assert sim.get_species_sprite_instances() == reps
    assert samples == VegetationSampler().sample(sim.ecology, reps)


def test_density_is_monotonic_and_cache_observes_abundance_and_sources():
    sim = fixture(abundance=0.15)
    sampler = VegetationSampler()
    reps = sim.get_species_sprite_instances()
    sparse = sampler.sample(sim.ecology, reps)
    sim.ecology.patches[0].abundance = 0.85
    dense = sampler.sample(sim.ecology, reps)
    positions = lambda items: {(i["x"], i["y"]) for i in items}
    assert positions(sparse) < positions(dense)
    assert dense == sampler.sample(sim.ecology, reps)
    for rep in reps:
        rep["age_bucket"] = 3
    assert all(i["age_bucket"] == 3 for i in sampler.sample(sim.ecology, reps))
    sim.ecology.patches.clear()
    assert sampler.sample(sim.ecology, reps) == []


def test_large_overlapping_populations_remain_bounded_and_deduplicated():
    sim = fixture()
    sim.ecology.bounds = dict(min_x=-500, max_x=500, min_y=-500, max_y=500)
    for index in range(12):
        sim.ecology.introduce("spec_lolium_perenne", index, 0, 450, 0.9)
    samples = VegetationSampler().sample(sim.ecology, sim.get_species_sprite_instances())
    assert 0 < len(samples) <= VegetationSampler.MAX_INSTANCES
    assert len({(i["x"], i["y"]) for i in samples}) == len(samples)


def test_a_sward_is_sampled_from_its_own_organisms_and_trees_are_shown_as_recorded():
    sim = fixture()
    sim.ecology.introduce("spec_betula_pendula", 5, 5, 4.5, 0.8)
    sim.representatives.sync_from_population(sim.ecology)
    reps = sim.get_species_sprite_instances()
    sources = {r["representative_id"]: r["species_id"] for r in reps}
    samples = VegetationSampler().sample(sim.ecology, reps)
    assert {s["growth_form"] for s in samples} == {"tree", "graminoid"}
    sward = [s for s in samples if s["growth_form"] == "graminoid"]
    trees = [s for s in samples if s["growth_form"] == "tree"]
    assert all(sources[s["visual_source_id"]] == s["species_id"] for s in sward)
    # A tree in view is a recorded plant: it has an identity, and looks like one of the planet's kept individuals.
    recorded = set(sim.ecology.species_individuals("spec_betula_pendula")["uid"].tolist())
    assert trees and {s["individual_uid"] for s in trees} <= recorded
    assert all(0 <= s["variant"] < sim.plant_pictures.count("spec_betula_pendula") for s in trees)
    # The trees simulated in depth are drawn from their own bodies, not a second time as display plants.
    followed = {rep.individual_uid for rep in sim.representatives.items("spec_betula_pendula", alive_only=True)}
    assert followed and not followed & {s["individual_uid"] for s in trees}


def test_large_domain_projection_fits_overview_instead_of_forcing_closeup():
    sim = fixture()
    sim.bounds = dict(min_x=0, min_y=0, max_x=1000, max_y=1000)
    sim.isometric_fullscreen_preview = True
    surface = pygame.Surface((1000, 700))
    state = BiosphereBuilderRenderer._projection(surface, sim)
    points = [BiosphereBuilderRenderer._iso(state, x, y) for x, y in
              ((0, 0), (1000, 0), (1000, 1000), (0, 1000))]
    assert all(surface.get_rect().collidepoint(p) for p in points)


def test_dense_render_keeps_only_real_representatives_pickable_and_ecology_unchanged():
    sim = fixture()
    before = sim.ecology.summary()
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    surface = pygame.Surface((1000, 700))
    renderer.draw(surface, sim)
    assert sim._vegetation_render_count > 400
    assert len(sim._representative_screen_hitboxes) == 4
    assert sim.ecology.summary() == before
    pixels = pygame.image.tobytes(surface, "RGB")
    renderer.draw(surface, sim)
    assert pygame.image.tobytes(surface, "RGB") == pixels
    sim.isometric_view_zoom = 2
    renderer.draw(surface, sim)
    assert sim.ecology.summary() == before


def test_recorded_plants_keep_their_place_while_they_grow_and_are_joined_by_younger_ones():
    sim = fixture("spec_betula_pendula", abundance=0.3)
    patch = sim.ecology.patches[0]
    profile = sim.ecology.profiles[patch.species_id]
    sampler = VegetationSampler()
    reps = sim.get_species_sprite_instances()
    patch.development_days = profile.maturity_days * 0.1
    young = sampler.sample(sim.ecology, reps)
    patch.development_days = profile.maturity_days
    grown = sampler.sample(sim.ecology, reps)
    # The same plants stand where they stood; only their stage has moved on.
    assert young and [(i["individual_uid"], i["x"], i["y"]) for i in young] == [(i["individual_uid"], i["x"], i["y"]) for i in grown]
    assert all(i["display_maturity"] <= 0.16 for i in young) and all(i["display_maturity"] == 1.0 for i in grown)
    assert grown == VegetationSampler().sample(sim.ecology, reps)


def test_a_stand_on_ground_that_carries_it_becomes_plants_of_several_ages():
    ecology = BiosphereEcology(dict(min_x=0, max_x=40, min_y=0, max_y=40),
                               [profile_from_entity(dict(id="shrub", plant_growth_form="shrub"))])
    ecology.introduce("shrub", 20, 20, 8, 0.2)
    founders = set(ecology.species_individuals("shrub")["uid"].tolist())
    ecology.advance(24)
    plants = ecology.species_individuals("shrub")
    # Seedlings have rooted among the founders, and the founders are still there.
    assert set(plants["uid"].tolist()) - founders and founders <= set(plants["uid"].tolist())
    assert plants["share"].min() < plants["share"].max()


def test_display_prototypes_grow_without_mutating_real_representatives():
    sim = fixture("spec_betula_pendula")
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    rep = sim.representatives.items(alive_only=True)[0]
    instance = sim.get_species_sprite_instances()[0]
    before = rep.simulation.render_snapshot
    young = renderer._species_case(sim, dict(instance, representative_id=None,
                                            visual_source_id=rep.representative_id, display_maturity=.16))
    older = renderer._species_case(sim, dict(instance, representative_id=None,
                                            visual_source_id=rep.representative_id, display_maturity=.85))
    assert young is not older and young is not rep.simulation and older is not rep.simulation
    assert young.render_snapshot.age_days < older.render_snapshot.age_days
    assert young.render_snapshot.stats["leaf_area_m2"] < older.render_snapshot.stats["leaf_area_m2"]
    camera = SimpleNamespace(zoom=40, sprite_height_cap=84)
    assert renderer._target_height_px(young, dict(instance, display_maturity=.16), camera, 1) < renderer._target_height_px(older, dict(instance, display_maturity=.85), camera, 1)
    assert renderer._species_case(sim, instance) is rep.simulation
    assert rep.simulation.render_snapshot is before


def test_a_plant_picture_is_sized_by_what_stands_above_ground():
    # Roots reach deeper and wider than the shoot; the picture is cut off at the ground.
    snapshot = SimpleNamespace(placements=[
        ["stem", -1, 0.0, 0.0, 0.0, 0.0, 1.0, 0], ["leaf", 0, 0.4, 0.0, 1.0, 0.0, 1.0, 2],
        ["leaf", 0, -0.4, 0.0, 1.0, 0.0, 1.0, 2], ["root", 0, 3.0, 0.0, -2.0, 0.0, 1.0, 1],
        ["root", 0, -3.0, 0.0, -2.0, 0.0, 1.0, 1],
    ])
    assert BiosphereBuilderRenderer._shown_extent(snapshot, (-3.0, 3.0, -2.0, 1.0)) == (0.8, 1.0)
    # Without placements to go by, the whole width stands in.
    assert BiosphereBuilderRenderer._shown_extent(SimpleNamespace(), (-3.0, 3.0, -2.0, 1.0)) == (6.0, 1.0)


def test_a_flat_plant_is_enlarged_until_its_width_reads_not_its_height():
    height = BiosphereBuilderRenderer._flat_plant_height
    assert height(22, 0.5, 0.5) == 22   # upright and tiny: enlarged to the legible height
    assert height(22, 30.0, 20.0) == 22  # large enough as it is
    assert height(22, 0.5, 20.0) == 1    # a floating leaf: 22 px wide is legible, 22 px tall would be 440 px wide
    assert height(22, 4.0, 2.0) == 11
