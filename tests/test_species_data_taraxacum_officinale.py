"""The dandelion card exercises the shared basal scape and fruit-head route."""

from copy import deepcopy
from types import SimpleNamespace

import pygame

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.plant_pictures import map_sprite_at, top_view
from simulations.species.scape_rosettes import scape_rosette_profile
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


def _entity():
    return WorldModel().resolved_species_entity("spec_taraxacum_officinale")


def test_scape_profile_rejects_missing_and_unbounded_controls():
    valid = {"form": "scape_rosette", "scape_count": 6,
             "scape_radius_m": 0.0022, "scape_spread_m": 0.075}
    assert scape_rosette_profile(valid)["version"] == 1
    for patch in ({"scape_count": 0}, {"scape_count": 13},
                  {"scape_radius_m": 0}, {"scape_spread_m": float("nan")},
                  {"scape_spread_m": 0.3}):
        assert scape_rosette_profile({**valid, **patch}) is None


def test_saved_card_makes_leafless_scapes_and_reuses_them_for_pappus():
    entity = _entity()
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    growth = sim.blueprint.growth
    assert growth["scape_rosette_version"] == 1
    assert growth["max_height_m"] == 0.4
    assert sim.blueprint.module("stem_section").radius_m == 0.0022
    flower = sim.generate_snapshot(170, 2)
    fruit = sim.generate_snapshot(285, 2)
    for snapshot in (flower, fruit):
        assert snapshot.stats["scape_count"] == 6
        assert sum(p[0] == "stem_section" for p in snapshot.placements) == 6
        assert all(0 <= p[1] < len(snapshot.placements) for p in snapshot.placements if p[0] in {"flower", "fruit"})
        assert all(p[4] < 0.05 for p in snapshot.placements if p[0] == "leaf")
    assert flower.stats["scape_flower_head_count"] == 6
    assert fruit.stats["scape_fruit_head_count"] == 6
    assert fruit.stats["scape_flower_head_count"] == 0


def test_same_profile_reuses_path_without_species_identity_and_lod_preserves_area():
    entity = deepcopy(_entity())
    entity["id"] = "spec_synthetic_scape_rosette"
    first = SpeciesSimulation(species_entity=entity, seed=303)
    second = SpeciesSimulation(species_entity=entity, seed=303)
    assert first.blueprint.growth["scape_rosette_version"] == 1
    assert first.generate_snapshot(285, 2).to_dict() == second.generate_snapshot(285, 2).to_dict()
    areas = [first.generate_snapshot(170, lod).stats["leaf_area_m2"] for lod in (0, 1, 2)]
    assert areas[0] == areas[1] == areas[2]
    entity["plant_shoot_profile"] = {"form": "scape_rosette", "scape_count": -1}
    assert "scape_rosette_version" not in SpeciesSimulation(species_entity=entity, seed=303).blueprint.growth


def test_saved_modules_survive_biosim_billboard_and_map_reduction():
    pygame.init()
    pygame.display.set_mode((1, 1))
    try:
        sim = SpeciesSimulation(species_entity=_entity(), seed=303)
        sim.set_lod(2)
        species_renderer = SpeciesRenderer(SimpleNamespace(camera=None))
        bio = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=species_renderer)
        scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),
                                world_units_to_meters=1.,
                                get_representative_species_simulation=lambda _rid: sim)
        item = {"species_id": sim.species_id, "representative_id": "test",
                "abundance": 1., "visual_scale": 1., "variant": 0}
        for day in (170, 285):
            sim.set_age(day)
            sprite, anchor = bio._render_sprite_surface(
                scene, item, SimpleNamespace(zoom=400., sprite_height_cap=84))
            assert 0 < sprite.get_width() <= 96 and 0 < sprite.get_height() <= 84
            assert 0 <= anchor[0] <= sprite.get_width()
            assert 0 <= anchor[1] <= sprite.get_height()
            picture = top_view(sim)
            assert picture is not None and max(picture.get_size()) <= 192
            coarse = map_sprite_at(picture, 40)
            assert max(coarse.get_size()) <= 40
            assert coarse.get_bounding_rect(min_alpha=1).width > 0
    finally:
        pygame.quit()
