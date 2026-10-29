"""Floating blades keep physical scale, surface contacts and canonical metrics."""
import math
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.floating_leaves import draw_floating_leaf
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, TopDownDiagnosticCamera, IsometricDiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation


def aquatic(seed=303, diameter=.3):
    data = {"id":"synthetic_floating_rosette", "plant_growth_form":"aquatic",
            "plant_growth_behaviour":"determinate_sympodial", "plant_lifespan":"perennial",
            "root_architecture":"adventitious", "leaf_length":{"max_m":diameter}}
    sim = SpeciesSimulation(species_entity=data, seed=seed)
    sim.set_age(180)
    return sim


def test_surface_contacts_and_horizontal_frames_are_exact():
    sim = aquatic(); snap = sim.render_snapshot
    for index, p in enumerate(snap.placements):
        if p[0] not in {"leaf","flower"}: continue
        assert snap.placements[p[1]][2:5] == p[2:5]
        assert snap.placement_paths[str(p[1])][-1] == pytest.approx(p[2:5])
        if p[0] == "leaf":
            assert p[4] == 0
            assert snap.placement_orientations[str(index)]["forward"][2] == 0
            assert snap.placement_orientations[str(index)]["normal"] == [0,0,1]
    assert len({round(math.hypot(p[2],p[3]),3) for p in snap.placements if p[0]=="leaf"}) > 3


def test_canonical_leaf_area_and_ecology_do_not_depend_on_lod():
    sim = aquatic(); results = []
    for lod in range(3):
        sim.set_lod(lod)
        results.append(sim.get_ecological_outcome())
        assert sim.render_snapshot.stats["leaf_area_m2"] > .4
        assert sim.render_snapshot.stats["estimated_leaf_count"] == 9
    assert results[0] == results[1] == results[2]
    assert aquatic().render_snapshot.to_dict() == aquatic().render_snapshot.to_dict()
    assert aquatic(404).render_snapshot.placements != aquatic().render_snapshot.placements


def test_metric_diameter_affects_area_and_portable_snapshot():
    small, large = aquatic(diameter=.15), aquatic(diameter=.3)
    assert large.render_snapshot.stats["leaf_area_m2"] == pytest.approx(small.render_snapshot.stats["leaf_area_m2"]*4, abs=1e-5)
    assert large.blueprint.fingerprint() != small.blueprint.fingerprint()
    assert PlantBlueprint.from_dict(large.blueprint.to_dict()).fingerprint() == large.blueprint.fingerprint()
    snap = large.render_snapshot
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    for p in snap.placements:
        assert all(math.isfinite(v) for v in p[2:7])
        assert -1 <= p[1] < len(snap.placements)


def test_young_blades_expand_and_flowering_has_a_real_stage_gate():
    sim = aquatic(); sim.set_age(30)
    young = sim.render_snapshot.stats["leaf_area_m2"]
    assert not any(p[0] == "flower" for p in sim.render_snapshot.placements)
    sim.set_age(180)
    assert sim.render_snapshot.stats["leaf_area_m2"] > young
    assert sum(p[0] == "flower" for p in sim.render_snapshot.placements) == 2


@pytest.fixture
def pixels():
    pygame.init(); pygame.display.set_mode((1,1))
    blade = pygame.Surface((75,75),pygame.SRCALPHA)
    pygame.draw.circle(blade,(50,110,60),(37,37),30)
    pygame.draw.polygon(blade,(0,0,0,0),[(37,40),(28,74),(46,74)])
    yield blade
    pygame.quit()


def test_projection_keeps_diameter_and_side_view_collapses_to_a_rim(pixels):
    for kind in (DiagnosticCamera,TopDownDiagnosticCamera,IsometricDiagnosticCamera):
        camera = kind(500,500,(-1,1,-1,1,0,1) if kind is IsometricDiagnosticCamera else (-1,1,-1,1))
        canvas = pygame.Surface((500,500),pygame.SRCALPHA)
        draw_floating_leaf(canvas,pixels,camera,[0,0,0],[0,1,0],.3,(.5,.52))
        rect = canvas.get_bounding_rect()
        assert rect.width > 10
        if kind is DiagnosticCamera: assert rect.height <= 2
        elif kind is TopDownDiagnosticCamera:
            assert rect.width == pytest.approx(.3*camera.scale,abs=3)
            assert rect.height == pytest.approx(.3*camera.scale,abs=3)
        else: assert rect.height > 10 and rect.height < rect.width


def test_projection_clips_extreme_zoom_and_renderer_accepts_all_views(pixels):
    camera = TopDownDiagnosticCamera(50,50,(-.05,.05,-.05,.05))
    canvas = pygame.Surface((50,50),pygame.SRCALPHA)
    draw_floating_leaf(canvas,pixels,camera,[0,0,0],[0,1,0],1000,(.5,.52))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None)); sim = aquatic()
    for lod in range(3):
        sim.set_lod(lod)
        for cls,bounds in ((DiagnosticCamera,(-1,1,-.65,.3)),
                           (TopDownDiagnosticCamera,(-1,1,-1,1)),
                           (IsometricDiagnosticCamera,[-1,1,-1,1,-.65,.3])):
            renderer._draw_individual(pygame.Surface((500,500)),sim,camera=cls(500,500,bounds),cache=False)
    renderer.draw(pygame.Surface((500,500)),sim)


def test_invalid_or_empty_projection_does_not_paint(pixels):
    camera = TopDownDiagnosticCamera(100,100,(-1,1,-1,1))
    canvas = pygame.Surface((100,100),pygame.SRCALPHA)
    for size in (0.,float("nan"),float("inf")):
        draw_floating_leaf(canvas,pixels,camera,[0,0,0],[0,1,0],size,(.5,.52))
    draw_floating_leaf(canvas,pixels,camera,[0,0,0],[0,0,0],.3,(.5,.52))
    assert canvas.get_bounding_rect().width == 0

def test_authored_width_changes_only_transverse_metric_extent(pixels):
    from simulations.species.floating_leaves import draw_planar_leaf
    camera=TopDownDiagnosticCamera(500,500,(-1,1,-1,1))
    boxes=[]
    for width in (.08,.24):
        canvas=pygame.Surface((500,500),pygame.SRCALPHA)
        draw_planar_leaf(canvas,pixels,camera,[0,0,0],[0,1,0],[0,0,1],.3,(.5,.9),width_m=width)
        boxes.append(canvas.get_bounding_rect())
    assert boxes[1].width==pytest.approx(boxes[0].width*3,abs=3)
    assert boxes[1].height==boxes[0].height
