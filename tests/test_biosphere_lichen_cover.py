from copy import deepcopy
from types import SimpleNamespace

import pygame

from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.vegetation import VegetationSampler
from world.world_model import WorldModel


def test_surface_fungi_are_available_without_becoming_plants():
    world=WorldModel()
    sim=BiosphereSimulation.reference_site(world)
    for sid in ("spec_stereocaulon_vesuvianum","spec_lecanora_muralis","spec_rusavskia_elegans"):
        assert not world.is_plant_species(sid)
        assert sid in sim.ecology.profiles
        assert sim.ecology.profiles[sid].surface_growth_profile
        assert sim.is_species_unlocked(sid)
    # A fungal stub with no opted-in recipe is still excluded.
    fungi=world.get_dataset("species")
    for e in fungi:
        if not world.is_plant_species(e["id"]) and not e.get("plant_growth_form") and not e.get("species_simulation_enabled") and not e.get("biosphere_bootstrap_species"):
            assert e["id"] not in sim.ecology.profiles
            break


def test_groundcover_profile_changes_habit_without_ecological_mutation():
    world=WorldModel();sim=BiosphereSimulation.reference_site(world)
    sid="spec_stereocaulon_vesuvianum"
    sim.ecology.introduce(sid,5,5,4,.8)
    sim.ecology.patches[0].development_days=sim.ecology.profiles[sid].maturity_days
    sim.representatives.sync_from_population(sim.ecology)
    before=deepcopy(sim.ecology.summary())
    reps=deepcopy(sim.get_species_sprite_instances())
    renderer=BiosphereBuilderRenderer(SimpleNamespace())
    screen=pygame.Surface((1000,700))
    renderer.draw(screen,sim)
    first=pygame.image.tobytes(screen,"RGB")
    renderer.draw(screen,sim)
    assert first==pygame.image.tobytes(screen,"RGB")
    assert sim.ecology.summary()==before
    assert sim.get_species_sprite_instances()==reps
    assert sim._vegetation_render_count>100
    assert len(sim._representative_screen_hitboxes)==4
    assert VegetationSampler().sample(sim.ecology,reps)==VegetationSampler().sample(sim.ecology,reps)


def test_population_symbol_is_bounded_and_distinguishes_crust_from_tuft():
    instance={"species_id":"unrelated_surface_fixture","growth_form":"lichen",
              "x":2.,"y":3.,"display_maturity":1.}
    images=[]
    for form in ("fruticose","placodioid_crustose","foliose"):
        surface=pygame.Surface((100,100));surface.fill((0,0,0))
        rect=BiosphereBuilderRenderer._draw_groundcover(surface,instance,(50,50),1000,(20,250,20),
                                                       {"thallus_form":form,"tuft_height_m":.025})
        assert surface.get_rect().contains(rect)
        assert rect.width<=32 and rect.height<=42
        images.append(pygame.image.tobytes(surface,"RGB"))
    assert images[0]!=images[1]
    assert images[1]!=images[2]
