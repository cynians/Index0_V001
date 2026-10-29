"""BioSim consumes edited artwork without changing the grown plant."""
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.species.species_simulation import SpeciesSimulation


@pytest.fixture
def scene():
    pygame.init()
    pygame.display.set_mode((1, 1))
    folder = Path(__file__).resolve().parents[1] / "artifacts" / f"asset_refresh_test_{uuid4().hex}"
    folder.mkdir()
    path = folder / "leaf.png"
    def save(colour):
        leaf = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.polygon(leaf, colour, [(12, 1), (21, 13), (12, 22), (3, 13)])
        pygame.image.save(leaf, str(path))
        # Explicit timestamps avoid clock/filesystem resolution dependence.
        save.revision += 1_000_000_000
        os.utime(path, ns=(save.revision, save.revision))
    save.revision = 1_800_000_000_000_000_000
    save((65, 135, 60))
    body = SpeciesSimulation(species_entity={"id": "asset_fixture", "type": "species",
        "plant_growth_form": "forb", "plant_growth_behaviour": "rosette_basal",
        "mature_height": {"typical_m": .4}, "plant_leaf_module_ref": str(path)}, seed=303)
    body.set_age(body.mature_age_days)
    world = SimpleNamespace(repository_revision=0)
    sim = SimpleNamespace(world_model=world, world_units_to_meters=1.,
        get_representative_species_simulation=lambda _id: body)
    item = dict(species_id=body.species_id, representative_id="test", abundance=1.,
                variant=0, visual_scale=1., growth_form="forb")
    yield body, sim, item, save
    pygame.quit()
    path.unlink()
    folder.rmdir()


def test_edited_module_invalidates_biosim_canonical_and_frame_caches(scene):
    body, sim, item, save = scene
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    camera = SimpleNamespace(zoom=400., sprite_height_cap=84)
    placements = body.render_snapshot.placements
    ecology = body.get_ecological_outcome()
    first, _ = renderer._sprite_surface(sim, item, camera)
    direct, _ = renderer._render_sprite_surface(sim, item, camera)
    save((195, 75, 145))
    # Expire the renderer's filesystem throttle without waiting for wall time.
    renderer.species_renderer._asset_revision_cache.clear()
    second, _ = renderer._sprite_surface(sim, item, camera)
    direct_second, _ = renderer._render_sprite_surface(sim, item, camera)
    assert pygame.image.tobytes(first, "RGBA") != pygame.image.tobytes(second, "RGBA")
    assert pygame.image.tobytes(direct, "RGBA") != pygame.image.tobytes(direct_second, "RGBA")
    assert body.render_snapshot.placements == placements
    assert body.get_ecological_outcome() == ecology


def test_kept_picture_path_changes_when_saved_art_changes(scene):
    body, sim, item, save = scene
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    folder = Path(body.blueprint.module("leaf").asset_ref).parent
    sim.plant_pictures = SimpleNamespace(map_sprite_dir=folder,
        _map_sprite_path=lambda _sid, _variant: folder / "kept.png", body=lambda *_args: body)
    item = dict(item, display_maturity=1.)
    first = renderer._stage_picture_path(sim, item, 84)
    save((195, 75, 145))
    renderer.species_renderer._asset_revision_cache.clear()
    assert renderer._stage_picture_path(sim, item, 84) != first


def test_representatives_use_foliage_preserving_lit_painter(scene, monkeypatch):
    body, sim, item, _save = scene
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    calls = []
    art = pygame.Surface((12, 22), pygame.SRCALPHA)
    monkeypatch.setattr(renderer, "_paint_stage_picture",
        lambda *_args: (calls.append(True) or art, (6., 21.)))
    renderer._sprite_surface(sim, item, SimpleNamespace(zoom=400., sprite_height_cap=84))
    # The kept picture comes from the lit painter; the view wants more than this stand-in picture holds, so
    # the plant is painted again at the view's size by the same painter (``_view_picture``), never enlarged.
    assert calls == [True, True]


def test_art_checks_do_not_regrow_cached_scenery_bodies(scene, monkeypatch):
    body, sim, item, _save = scene
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    sim.get_representative_species_simulation = lambda _id: None
    calls = []
    monkeypatch.setattr(renderer, "_species_case", lambda *_args: calls.append(True) or body)
    first = renderer._instance_art_revision(sim, item)
    assert renderer._instance_art_revision(sim, item) == first
    assert calls == [True]


def test_maple_keeps_leafy_cohort_coverage_at_small_cap():
    from simulations.biosphere.plant_pictures import grow_specimen
    from world.world_model import WorldModel
    import numpy as np
    pygame.init()
    pygame.display.set_mode((1, 1))
    world = WorldModel()
    body = grow_specimen(world, "spec_acer_rubrum", 303, 1.)
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    sim = SimpleNamespace(world_model=world, world_units_to_meters=1.,
        get_representative_species_simulation=lambda _id: body)
    item = dict(species_id=body.species_id, representative_id="maple", abundance=1.,
                variant=0, visual_scale=1., growth_form="tree")
    snapshot = body.render_snapshot
    art, _ = renderer._sprite_surface(sim, item, SimpleNamespace(zoom=400., sprite_height_cap=84))
    rgb, alpha = pygame.surfarray.array3d(art), pygame.surfarray.array_alpha(art)
    # Reducing sparse individual samples previously stripped the leafy crown.
    green = (rgb[:, :, 1] > rgb[:, :, 0].astype(float)*1.2) & (alpha > 0)
    assert np.count_nonzero(green) > np.count_nonzero(alpha)*.6
    assert body.render_snapshot is snapshot
    pygame.quit()
