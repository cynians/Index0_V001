import copy
import json
import math
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, SurfaceElevationCamera
from simulations.species.surface_growth import surface_palette
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer


def entity():
    return {"id": "unrelated_foliose_fixture", "plant_growth_form": "lichen",
            "plant_growth_behaviour": "surface_covering", "plant_reproductive_structure": "apothecium",
            "surface_growth_profile": {"thallus_form": "foliose", "colony_diameter": {"max_m": .06},
                "marginal_lobe_width": {"min_m": .0004, "max_m": .0013},
                "visual_calibration": {"discrete_lobe_fraction": .5, "lobe_spacing_factor": 3.3,
                    "thallus_palette": [[150,60,20],[180,80,20],[220,110,30],[240,150,40]]}}}


def specimen(e=None, env=None, lod=2):
    sim=SpeciesSimulation(species_entity=e or entity(), environment=env or {}, seed=303)
    sim.set_lod(lod);sim.set_age(sim.mature_age_days)
    return sim


def test_foliose_surface_is_deterministic_portable_bounded_and_nonvascular():
    sim=specimen();s=sim.render_snapshot
    assert s.to_dict()==specimen().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(json.loads(json.dumps(s.to_dict()))).to_dict()==s.to_dict()
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint()==sim.blueprint.fingerprint()
    assert 0<len(s.placements)<10000
    assert {p[0] for p in s.placements}=={"thallus","apothecium"}
    assert s.stats["leaf_count"]==s.stats["root_segment_count"]==s.stats["stem_count"]==0
    for i,p in enumerate(s.placements):
        assert -1<=p[1]<i
        assert all(math.isfinite(x) for point in s.placement_paths[str(i)] for x in point)
    assert all(a["socket"]=="surface" for a in s.attachment_points)


def test_discrete_lobes_reduce_cover_and_palette_changes_only_appearance():
    continuous=entity();continuous["surface_growth_profile"]["visual_calibration"]["discrete_lobe_fraction"]=0
    discrete=specimen();solid=specimen(continuous)
    assert discrete.render_snapshot.stats["surface_coverage_m2"]<solid.render_snapshot.stats["surface_coverage_m2"]
    changed=entity();changed["surface_growth_profile"]["visual_calibration"]["thallus_palette"]=[[30,90,30]]*4
    other=specimen(changed)
    assert discrete.blueprint.fingerprint()!=other.blueprint.fingerprint()
    assert discrete.render_snapshot.placements==other.render_snapshot.placements
    assert discrete.render_snapshot.placement_paths==other.render_snapshot.placement_paths
    pygame.init();renderer=SpeciesRenderer(SimpleNamespace(camera=None));images=[]
    for sim in (discrete,other):
        screen=pygame.Surface((400,400))
        renderer._draw_individual(screen,sim,camera=SurfaceElevationCamera(400,400,[-.04,.04,-.002,.002,-.04,.04]),
                                  show_height_reference=False,draw_ground_line=False,cache=False)
        images.append(pygame.image.tobytes(screen,"RGB"))
    assert images[0]!=images[1]


def test_lifecycle_activity_and_canonical_ecology_are_independent_of_display_detail():
    dry=specimen(env={"thallus_hydration":0});wet=specimen(env={"thallus_hydration":.8})
    assert dry.render_snapshot.placement_paths==wet.render_snapshot.placement_paths
    assert dry.get_ecological_outcome()["photosynthetic_surface_area_m2"]==0
    assert wet.get_ecological_outcome()["photosynthetic_surface_area_m2"]>0
    assert specimen(lod=0).get_ecological_outcome()==specimen(lod=2).get_ecological_outcome()
    assert not specimen(env={"surface_tissue_loss":1}).render_snapshot.placements
    assert not specimen(env={"surface_growth_years":0}).render_snapshot.placements
    assert not specimen(env={"surface_attachment":{"support_id":"unavailable"}}).render_snapshot.placements


def test_expansion_preserves_established_cells_and_damage_preserves_surviving_anchors():
    def body(sim):
        return {tuple(p[2:5]) for p in sim.render_snapshot.placements if p[0]=="thallus"}
    small=specimen(env={"surface_growth_years":0,"surface_initial_radius_m":.014})
    large=specimen(env={"surface_growth_years":0,"surface_initial_radius_m":.03})
    damaged=specimen(env={"surface_tissue_loss":.45})
    assert body(small)<body(large)
    assert body(damaged)<body(large)
    # Discs may only remain over surviving tissue.
    for i,p in enumerate(damaged.render_snapshot.placements):
        if p[0]=="apothecium":
            assert damaged.render_snapshot.placements[p[1]][0]=="thallus"


def test_authored_palette_reaches_biosphere_and_malformed_palettes_are_neutral():
    instance={"species_id":"unrelated_foliose_fixture","growth_form":"lichen","x":1.,"y":2.,"display_maturity":1.}
    profile=specimen().blueprint.growth["surface_growth_profile"]
    before=copy.deepcopy(profile);screen=pygame.Surface((100,100));screen.fill((0,0,0))
    BiosphereBuilderRenderer._draw_groundcover(screen,instance,(50,50),200,(20,250,20),profile)
    assert profile==before
    assert screen.get_at((50,50))[:3]!=(20,250,20)
    assert any(screen.get_at((x,y))[:3] in surface_palette(profile,()) for x in range(30,70) for y in range(30,70))
    fallback=((1,2,3),)*4
    assert surface_palette({"visual_calibration":{"thallus_palette":[[2,3]]}},fallback)==fallback
    assert surface_palette({"visual_calibration":None},fallback)==fallback


def test_saved_sunburst_reaches_fungi_and_transports_only_its_authored_recipe():
    from pathlib import Path
    from world.persistent_ontology_store import PersistentOntologyStore
    from world.plant_catalogue import PlantCatalogue
    from world.world_model import WorldModel
    rows=PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    entities={r["id"]:r for dataset in rows.values() if isinstance(dataset,list)
              for r in dataset if isinstance(r,dict) and r.get("id")}
    sid="spec_rusavskia_elegans";row=entities[sid]
    assert row["parents"]==["cladis_rusavskia"]
    assert entities["cladis_teloschistales"]["parents"]==["cladis_lecanoromycetidae"]
    assert PlantCatalogue.build(entities,root_id="cladis_fungi").is_species(sid)
    assert not PlantCatalogue.build(entities).is_species(sid)
    resolved=WorldModel().resolved_species_entity(sid)
    assert resolved["surface_growth_profile"]==row["surface_growth_profile"]
    blueprint=PlantBlueprint.from_species_entity(resolved,sid)
    assert blueprint.growth["surface_growth_profile"]["thallus_form"]=="foliose"
    assert blueprint.growth["surface_growth_profile"]["radial_rate_source"]=="runtime_default"
    assert blueprint.growth["max_height_m"]==pytest.approx(.0006)
    assert not resolved.get("maturity_age") and not resolved.get("longevity")
    assert row["nitrogen_fixation"]=="none"
