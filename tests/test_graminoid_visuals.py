import math
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from simulations.species.graminoid_visuals import blade_ribbon, compound_panicle_surface
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation


@pytest.fixture(autouse=True)
def pygame_display():
    pygame.init()
    pygame.display.set_mode((1, 1))


def test_blade_keeps_socket_tip_and_tapers_without_unbounded_geometry():
    points = [(10, 90), (35, 50), (75, 45), (110, 70)]
    center, left, right = blade_ribbon(points, 8)
    assert center[0] == points[0] and center[-1] == points[-1]
    assert left[-1] == right[-1] == points[-1]
    assert 10 < len(center) <= 121
    widths = [math.dist(a, b) for a, b in zip(left, right)]
    assert max(widths) > widths[0] > widths[-1]
    assert max(widths) <= 16.00001
    assert all(math.isfinite(c) for path in (center, left, right) for p in path for c in p)
    long_center = blade_ribbon([(i, 0) for i in range(1000)], 1e9)[0]
    assert len(long_center) <= 121
    assert long_center[-1] == (999, 0)


@pytest.mark.parametrize("points,width", [
    ([], 1), ([(0, 0), (0, 0)], 1), ([(0, 0), (1, 1)], 0),
    ([(0, 0), (1, 1)], -1), ([(0, 0), (1, 1)], math.nan),
    ([(0, 0), (math.inf, 1)], 1),
])
def test_blade_missing_zero_and_nonfinite_values_are_neutral(points, width):
    assert blade_ribbon(points, width) == ([], [], [])


def test_connected_blades_scale_with_camera_and_module_width_without_mutating_snapshot():
    sim = SpeciesSimulation(species_entity={
        "id": "synthetic_connected_graminoid", "plant_growth_form": "graminoid",
        "leaf_attachment_pattern": "along_stem", "leaf_size_class": "large",
        "mature_height": {"max_m": 1.},
    }, seed=303)
    sim.set_age(200)
    snapshot = sim.render_snapshot
    before = snapshot.to_dict()
    leaf_index = next(i for i, p in enumerate(snapshot.placements)
                      if p[0] == "leaf" and snapshot.placement_paths.get(str(i)))
    original = sim.blueprint.module("leaf")
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))

    def coverage(radius, zoom):
        sim.blueprint.modules = [replace(m, radius_m=radius) if m.id == "leaf" else m
                                 for m in sim.blueprint.modules]
        surface = pygame.Surface((900, 900), pygame.SRCALPHA)
        camera = DiagnosticCamera(900, 900, (-1., 1., -.5, 1.5))
        camera.scale *= zoom
        renderer._draw_individual(surface, sim, camera=camera, clear=False,
                                  visible_indices={leaf_index}, snapshot=snapshot,
                                  draw_ground_line=False, draw_environment=False, cache=False)
        return pygame.mask.from_surface(surface).count()

    thin, broad = coverage(.003, 1.), coverage(.015, 1.)
    assert broad > thin * 2
    assert coverage(.015, 2.) > broad * 2.5
    assert coverage(0., 1.) == 0
    assert snapshot.to_dict() == before
    sim.blueprint.modules = [original if m.id == "leaf" else m for m in sim.blueprint.modules]


def test_compound_panicles_are_deterministic_varied_and_bounded():
    a = compound_panicle_surface(100, (132, 128, 70), 303)
    b = compound_panicle_surface(100, (132, 128, 70), 303)
    c = compound_panicle_surface(100, (132, 128, 70), 304)
    assert pygame.image.tobytes(a, "RGBA") == pygame.image.tobytes(b, "RGBA")
    assert pygame.image.tobytes(a, "RGBA") != pygame.image.tobytes(c, "RGBA")
    bounds = a.get_bounding_rect()
    assert bounds.width > bounds.height * 1.1
    assert pygame.mask.from_surface(a).count() > 800
    assert bounds.left > 0 and bounds.right < a.get_width()
    assert bounds.top > 0 and bounds.bottom < a.get_height()
    assert compound_panicle_surface(10**9, (132, 128, 70)).get_height() <= 320


def test_graminoid_panicle_scales_in_close_views_and_attaches_at_its_base():
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sim = SimpleNamespace(blueprint=SimpleNamespace(
        growth={"growth_form": "graminoid", "reproductive_structure": "panicle"},
        module=lambda _: SimpleNamespace(length_m=.22, visual={}),
    ))

    def render(ppm, rotation=0.):
        surface = pygame.Surface((650, 650), pygame.SRCALPHA)
        renderer._draw_reproductive_fallback(surface, sim, SimpleNamespace(scale=ppm),
            "flower", (325, 400), rotation, 1., (132, 128, 70), variant_seed=303)
        return surface.get_bounding_rect()

    normal, close = render(300), render(600)
    assert close.height > normal.height * 1.8
    assert abs(close.bottom-400) < 10
    assert close.top < 300
    turned = render(600, 90.)
    assert turned.right <= 335 and turned.left < 250
