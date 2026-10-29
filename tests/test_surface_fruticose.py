import copy
import json
import math

import pytest

from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.surface_supports import rock_fixture, rock_lifecycle_treatments


def entity():
    return {"id":"unrelated_fungal_fixture", "plant_growth_form":"lichen",
            "plant_growth_behaviour":"surface_covering", "plant_reproductive_structure":"apothecium",
            "surface_growth_profile":{"thallus_form":"fruticose",
              "tuft_height":{"typical_m":.025}, "joint_symbiont_dispersal":"terminal_soredia",
              "cyanobiont":"synthetic_association", "visual_calibration":{"colony_diameter_m":.07}}}


def specimen(env=None,lod=2,e=None):
    sim=SpeciesSimulation(species_entity=e or entity(),environment=env or rock_fixture(),seed=303)
    sim.set_lod(lod);sim.set_age(sim.mature_age_days)
    return sim


def test_fruticose_structure_is_bounded_portable_deterministic_and_has_no_vascular_organs():
    sim=specimen(); snapshot=sim.render_snapshot
    assert snapshot.to_dict()==specimen().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))).to_dict()==snapshot.to_dict()
    assert 0<snapshot.stats["pseudopodetium_count"]<=288
    assert 0<snapshot.stats["phyllocladium_count"]<=5000
    assert len(snapshot.placements)<16000
    assert snapshot.stats["root_segment_count"]==snapshot.stats["leaf_count"]==snapshot.stats["stem_count"]==0
    assert {p[0] for p in snapshot.placements}>={"thallus","pseudopodetium","phyllocladium"}
    for i,p in enumerate(snapshot.placements):
        assert -1<=p[1]<i
        assert all(math.isfinite(float(x)) for x in p[2:])
    assert sim.get_ecological_outcome()["photosynthetic_surface_area_m2"]>0


def test_fixed_surface_anchors_do_not_shift_when_neighbouring_cells_are_damaged():
    intact=specimen(); damaged=specimen({**rock_fixture(),"surface_tissue_loss":.45})
    def axes(sim):
        return {tuple(tuple(p) for p in sim.render_snapshot.placement_paths[str(i)])
                for i,placement in enumerate(sim.render_snapshot.placements) if placement[0]=="pseudopodetium"}
    assert axes(damaged)<axes(intact)
    assert damaged.render_snapshot.stats["surface_coverage_m2"]<intact.render_snapshot.stats["surface_coverage_m2"]
    assert not specimen({**rock_fixture(),"surface_tissue_loss":1}).render_snapshot.placements


def test_preview_growth_dry_rewet_and_canonical_ecology_across_lod():
    profile=specimen().blueprint.growth["surface_growth_profile"]
    cases=[specimen(env) for _,env in rock_lifecycle_treatments(rock_fixture(),profile)]
    assert cases[0].render_snapshot.stats["surface_coverage_m2"]<cases[1].render_snapshot.stats["surface_coverage_m2"]<cases[2].render_snapshot.stats["surface_coverage_m2"]
    assert cases[3].render_snapshot.placements==cases[4].render_snapshot.placements
    assert cases[3].get_ecological_outcome()["photosynthetic_surface_area_m2"]==0
    assert cases[4].get_ecological_outcome()["photosynthetic_surface_area_m2"]>0
    assert specimen(lod=0).get_ecological_outcome()==specimen(lod=2).get_ecological_outcome()
    assert not specimen({"surface_attachment":{"support_id":"missing"}}).render_snapshot.placements


def test_profile_controls_change_geometry_and_blueprint_fingerprint():
    first=entity();other=copy.deepcopy(first)
    other["surface_growth_profile"]["tuft_height"]["typical_m"]*=2
    a,b=specimen(e=first),specimen(e=other)
    assert a.blueprint.fingerprint()!=b.blueprint.fingerprint()
    assert a.render_snapshot.placement_paths!=b.render_snapshot.placement_paths
    assert a.render_snapshot.stats["surface_coverage_m2"]==b.render_snapshot.stats["surface_coverage_m2"]
    assert PlantBlueprint.from_dict(a.blueprint.to_dict()).fingerprint()==a.blueprint.fingerprint()


def test_unsupported_lichen_preview_uses_upright_tufts_and_spacing_controls_density():
    sparse=entity();dense=copy.deepcopy(sparse)
    sparse['surface_growth_profile']['visual_calibration']['tuft_spacing_m']=.008
    dense['surface_growth_profile']['visual_calibration']['tuft_spacing_m']=.005
    a=specimen(env={'thallus_hydration':.45},e=sparse)
    b=specimen(env={'thallus_hydration':.45},e=dense)
    assert a.render_snapshot.stats['surface_support_kind']=='illustrative_specimen_plane'
    assert b.render_snapshot.stats['pseudopodetium_count']>a.render_snapshot.stats['pseudopodetium_count']
    for sim in (a,b):
        snap=sim.render_snapshot
        axes=[snap.placement_paths[str(i)] for i,p in enumerate(snap.placements)
              if p[0]=='pseudopodetium']
        assert axes and all(path[-1][2]>path[0][2] for path in axes)
        assert snap.stats['root_segment_count']==snap.stats['leaf_count']==0


def test_live_fungal_record_preserves_identity_and_passes_traits_through_blueprint():
    from world.persistent_ontology_store import PersistentOntologyStore
    from world.world_model import WorldModel
    from pathlib import Path
    datasets=PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    row=next(r for r in datasets["species"] if r.get("id")=="spec_stereocaulon_vesuvianum")
    assert row["parents"]==["cladis_rock_foam_lichens_stereocaulon"]
    assert row["nitrogen_fixation"]=="associated"
    resolved=WorldModel().resolved_species_entity(row["id"])
    blueprint=PlantBlueprint.from_species_entity(resolved)
    assert blueprint.growth["surface_growth_profile"]["thallus_form"]=="fruticose"
    assert blueprint.growth["surface_growth_profile"]["radial_rate_source"]=="runtime_default"
    assert blueprint.growth["max_height_m"]==pytest.approx(.025)
