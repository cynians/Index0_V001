import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation, normalise_climbing_supports
from simulations.species.surface_growth import SurfaceChart, surface_activity, normalise_surface_profile, surface_outline_factor
from simulations.species.solid_structures import SolidStructureField
from simulations.species.plant_nutrition import resolve_plant_nutrient_response
from tools.author_plant_species import prepare_update, AuthoringError


def entity():
    # Synthetic unrelated taxon: no production species ID controls behavior.
    return {"id":"fixture_surface_organism","plant_growth_form":"lichen",
            "plant_growth_behaviour":"surface_covering","plant_lifespan":"perennial",
            "plant_reproductive_structure":"apothecium",
            "surface_growth_profile":{"thallus_form":"placodioid_crustose",
                "hydration_response":"pulse_overhydration_depression",
                "colony_diameter":{"max_m":.10},
                "marginal_lobe_width":{"min_m":.0005,"max_m":.002}}}


def wall():
    rows=["#"*16 for _ in range(16)]
    for j in range(5,9): rows[j]=rows[j][:8]+".."+rows[j][10:]
    return {"id":"wall","kind":"wall","position_m":[0,0,0],"rotation_deg":27,
            "pixel_size_m":.01,"extrusion_depth_m":.02,"mask_rows":rows}


def environment():
    return {"solid_structures":[wall()],"surface_attachment":{"support_id":"wall","uv_m":[-.01,.08]}}


def mature(e=None, env=None, lod=2):
    sim=SpeciesSimulation(species_entity=e or entity(),environment=env or environment(),seed=303)
    sim.set_lod(lod); sim.set_age(sim.mature_age_days)
    return sim


def test_surface_snapshot_is_portable_deterministic_bounded_and_without_plant_organs():
    first=mature(); second=mature()
    assert first.render_snapshot.to_dict()==second.render_snapshot.to_dict()
    snapshot=PlantGrowthSnapshot.from_dict(json.loads(json.dumps(first.render_snapshot.to_dict())))
    assert snapshot.to_dict()==first.render_snapshot.to_dict()
    assert {p[0] for p in snapshot.placements}=={"thallus","apothecium"}
    assert len(snapshot.placements)<10000
    for i,p in enumerate(snapshot.placements):
        assert -1<=p[1]<i
        assert all(math.isfinite(float(v)) for v in p[2:])
        assert str(i) in snapshot.placement_paths
    assert first.get_ecological_outcome()["root_depth_source"]=="not_applicable"
    assert first.get_ecological_outcome()["estimated_leaf_count"]==0
    assert {m.id for m in first.blueprint.modules}=={"thallus","apothecium"}


def test_wall_face_attachment_and_hole_exclusion_are_in_model_space():
    sim=mature(); field=SolidStructureField.from_environment(sim.environment);solid=field.structures[0]
    for polygon in sim.render_snapshot.placement_paths.values():
        for point in polygon:
            local=field._world_to_local(solid,point)
            assert -.013<local[1]<-.01
            # Query occupied_cell with a world point on the face's interior.
            assert field.occupied_cell(solid,field._local_to_world(solid,(local[0],0,local[2]))) is not None


def test_connected_front_cannot_jump_a_gap_to_another_wall_island():
    e=environment();s=e["solid_structures"][0]
    s["mask_rows"]=["####....########"]*16
    e["surface_attachment"]["uv_m"]=[-.06,.08]
    sim=mature(env=e);solid=SolidStructureField.from_environment(e).structures[0]
    for p in sim.render_snapshot.placements:
        assert SolidStructureField._world_to_local(solid,p[2:5])[0]<-.04


def test_missing_support_and_zero_growth_produce_no_cover():
    assert not mature(env={"surface_attachment":{"support_id":"absent"}}).render_snapshot.placements
    sim=mature(env={**environment(),"surface_growth_years":0})
    assert sim.render_snapshot.stats["surface_coverage_m2"]==0
    assert sim.get_ecological_outcome()["resource_demand"]==0


def test_cylinder_chart_preserves_metric_attachment_on_sampled_trunk():
    env={"climbing_supports":[{"id":"trunk","kind":"tree","radius_m":.025,
         "center_m":[0,0],"height_m":.2,"axis_points_m":[[0,0,0],[.01,.003,.1],[.006,0,.2]]}],
         "surface_attachment":{"support_id":"trunk","uv_m":[0,.1]}}
    sim=mature(env=env);chart=SurfaceChart(env,SolidStructureField([]),normalise_climbing_supports(env),.1)
    for att in sim.render_snapshot.attachment_points:
        expected=chart.point(*att["uv_m"],sim.blueprint.growth["surface_growth_profile"]["thickness_m"])
        assert att["position_m"]==pytest.approx(expected,abs=1e-6)
    assert sim.render_snapshot.stats["surface_support_kind"]=="cylindrical_trunk"
    assert max(p[2] for p in sim.render_snapshot.placements)-min(p[2] for p in sim.render_snapshot.placements)>.03


def test_canonical_ecology_bounds_and_counts_do_not_depend_on_lod():
    sims=[mature(lod=lod) for lod in range(3)]
    assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
    assert sims[0].render_snapshot.bounds_m==sims[2].render_snapshot.bounds_m
    assert sims[0].render_snapshot.stats["canonical_apothecium_count"]==sims[2].render_snapshot.stats["canonical_apothecium_count"]


def test_hydration_activates_then_depresses_without_destroying_dormant_cover():
    sim=mature();wet=sim.get_ecological_outcome({"thallus_hydration":.45})
    dry=sim.get_ecological_outcome({"thallus_hydration":0})
    saturated=sim.get_ecological_outcome({"thallus_hydration":1})
    assert dry["growth_rate"]<saturated["growth_rate"]<wet["growth_rate"]
    assert dry["surface_coverage_m2"]==wet["surface_coverage_m2"]
    assert dry["mortality_risk"]==wet["mortality_risk"]==0
    assert sim.get_ecological_outcome({"soil_moisture":0})==sim.get_ecological_outcome({"soil_moisture":1})
    assert sim.get_ecological_outcome()["surface_hydration_status"]=="unresolved_neutral"
    sim.environment["thallus_hydration"]=0
    assert sim.get_ecological_outcome()["growth_rate"]==dry["growth_rate"]


def test_annual_radial_increment_is_explicit_and_never_inferred_from_colony_size():
    a=mature(env={**environment(),"surface_growth_years":5})
    b=mature(env={**environment(),"surface_growth_years":10})
    assert a.render_snapshot.stats["surface_radius_m"]==pytest.approx(.01)
    assert b.render_snapshot.stats["surface_radius_m"]==pytest.approx(.02)
    assert a.render_snapshot.stats["surface_coverage_m2"]<b.render_snapshot.stats["surface_coverage_m2"]
    assert "not_calendar_age" in mature().render_snapshot.stats["surface_radius_source"]


def test_moss_reuses_surface_attachment_with_a_distinct_patch_body():
    e=entity();e["plant_growth_form"]="moss";e["surface_growth_profile"]={"thallus_form":"moss_mat"}
    sim=mature(e=e)
    assert {p[0] for p in sim.render_snapshot.placements}=={"moss_patch"}
    assert sim.render_snapshot.stats["canonical_apothecium_count"]==0
    assert sim.render_snapshot.stats["surface_coverage_m2"]>0
    assert "Roots" not in {t["label"] for t in sim.get_simulation_panel_tabs()}
    from simulations.species.surface_supports import rock_fixture
    rock=mature(e=e,env=rock_fixture())
    assert {p[0] for p in rock.render_snapshot.placements}=={"moss_patch"}
    assert rock.render_snapshot.stats["surface_support_kind"]=="analytic_rounded_rock"


def test_schema_transport_fingerprint_and_fungal_authoring_are_explicit():
    e=entity();bp=PlantBlueprint.from_species_entity(e)
    assert PlantBlueprint.from_dict(json.loads(json.dumps(bp.to_dict()))).fingerprint()==bp.fingerprint()
    changed=copy.deepcopy(e);changed["surface_growth_profile"]["colony_diameter"]["max_m"]=.08
    assert bp.fingerprint()!=PlantBlueprint.from_species_entity(changed).fingerprint()
    datasets={"species":[{"id":e["id"],"type":"species","parents":["cladis_fungi"]}],
              "cladistics":[{"id":"cladis_fungi","type":"cladistics","parents":[]}]}
    updates={k:v for k,v in e.items() if k!="id"}
    authored,_,_=prepare_update(datasets,e["id"],updates)
    assert authored["parents"]==["cladis_fungi"]
    with pytest.raises(AuthoringError): prepare_update(datasets,e["id"],{"growth_rate":"slow"})
    datasets["species"][0]["parents"]=["cladis_animalia"]
    with pytest.raises(AuthoringError): prepare_update(datasets,e["id"],updates)


def test_natural_and_engineered_siblings_do_not_supply_each_others_traits():
    from world.species_inheritance import resolve_species_field, SPECIES_INHERITABLE_FIELDS
    parent={"id":"genus","plant_reproductive_structure":"apothecium",
            "growth_rate":"very_fast_engineered","inferred_field_sources":{
                "plant_reproductive_structure":{"kind":"offspring_consensus","source_ids":["natural"]},
                "growth_rate":{"kind":"offspring_consensus","source_ids":["engineered"]}}}
    natural={"id":"natural","parents":["genus"]}
    engineered={"id":"engineered","parents":["genus"],"origin_type":"bioengineered"}
    loader=SimpleNamespace(entities={"genus":parent,"natural":natural,"engineered":engineered})
    assert resolve_species_field(loader,engineered,"plant_reproductive_structure")["value"] is None
    assert resolve_species_field(loader,natural,"growth_rate")["value"] is None
    assert resolve_species_field(loader,natural,"plant_reproductive_structure")["value"]=="apothecium"
    assert "surface_growth_profile" not in SPECIES_INHERITABLE_FIELDS


def test_nonfinite_inputs_are_bounded_and_soil_nutrients_do_not_create_roots():
    env={**environment(),"surface_growth_years":float('inf'),"thallus_hydration":float('nan')}
    sim=mature(env=env)
    assert all(math.isfinite(x) for x in sim.render_snapshot.bounds_m)
    profile=normalise_surface_profile({"colony_diameter":{"max_m":float('inf')},"radial_expansion_rate":"unknown"})
    assert math.isfinite(profile["diameter_m"])
    nutrient=resolve_plant_nutrient_response(sim.blueprint.growth,{"available_nitrogen_g_m2":100,"available_phosphorus_g_m2":100})
    assert nutrient["phosphorus_root_access_multiplier"]==nutrient["nitrogen_access_multiplier"]==0


def test_biosphere_consumes_same_hydration_and_does_not_use_soil_root_access():
    from simulations.biosphere.ecology import profile_from_entity,BiosphereEcology
    e=entity();profile=profile_from_entity(e);eco=BiosphereEcology({"min_x":0,"max_x":1,"min_y":0,"max_y":1},[profile])
    env=eco.environment_at(.5,.5)
    dry=eco.suitability_factors(profile,{**env,"thallus_hydration":0})
    wet=eco.suitability_factors(profile,{**env,"thallus_hydration":.45})
    assert dry["suitability"]==0
    assert wet["suitability"]>0


def test_live_wall_lichen_retains_fungi_and_researched_unknowns():
    from world.world_model import WorldModel
    from world.plant_catalogue import PlantCatalogue
    w=WorldModel();sid="spec_lecanora_muralis";raw=w.loader.get(sid)
    assert not w.is_plant(sid)
    assert PlantCatalogue.build(w.loader.entities,root_id="cladis_fungi").is_species(sid)
    assert raw["parents"]==["cladis_rim_lichens_lecanora"]
    assert raw["growth_rate"]=="slow" and raw["maturity_rate"]=="other_unknown"
    assert raw["surface_growth_profile"]["substrates"]["bark"]=="documented_uncommon"
    assert w.resolved_species_entity(sid)["clonal_spread"]=="none"


def test_live_card_opens_growth_tools_without_exposing_plant_asset_tools():
    from world.world_model import WorldModel
    from ui.card import EntityCard
    from simulations.species.plant_assets import is_surface_species_entity
    w=WorldModel();card=EntityCard.__new__(EntityCard);card.entity=w.loader.get("spec_lecanora_muralis")
    card.dataset_name="species";card.world_model=w
    tools={t["id"] for t in card._toolbelt_items()}
    assert {"species_visual_editor","species_sim_lab"}<=tools
    assert "plant_asset_leaf" not in tools
    assert is_surface_species_entity(card.entity,w.loader.entities)
    assert not is_surface_species_entity({**card.entity,"id":"fake_animal"},w.loader.entities)


def test_production_surface_panel_and_raster_are_repeatable():
    from simulations.species.species_renderer import SpeciesRenderer
    pygame.init();pygame.display.set_mode((1,1))
    sim=mature();renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    first=pygame.Surface((1000,650));second=pygame.Surface((1000,650))
    assert sim.diagnostic_view=="surface"
    renderer.draw(first,sim);renderer.draw(second,sim)
    assert pygame.image.tobytes(first,"RGB")==pygame.image.tobytes(second,"RGB")
    pixels=pygame.surfarray.array3d(first)
    assert ((pixels[:,:,1]>pixels[:,:,0]) & (pixels[:,:,0]>100)).sum()>1000
    sim.set_active_simulation_panel_tab("editor")
    renderer.draw(first,sim)
    assert sim.get_species_editor_preview().blueprint.growth["growth_behaviour"]=="surface_covering"
    pygame.quit()


def test_irregular_outline_is_seed_stable_and_expansion_retains_patch_positions():
    factors=[surface_outline_factor(i*math.tau/180,303,.65) for i in range(180)]
    assert max(factors)-min(factors)>.15
    assert .7<min(factors)<max(factors)<=1
    assert factors != [surface_outline_factor(i*math.tau/180,404,.65) for i in range(180)]
    assert all(surface_outline_factor(i,303,0)==1 for i in range(12))
    base={"surface_weathering_progress":0,"surface_reproductive_progress":0}
    first=mature(env={**base,"surface_growth_years":5})
    second=mature(env={**base,"surface_growth_years":10})
    def patches(sim):
        return {tuple(a["uv_m"]):a["position_m"] for a in sim.render_snapshot.attachment_points}
    a,b=patches(first),patches(second)
    assert a and a.keys()<b.keys()
    assert all(b[key]==value for key,value in a.items())


def test_analytic_rock_is_portable_bounded_and_offsets_follow_surface_normals():
    from tools.render_surface_growth import rock_fixture
    from simulations.species.surface_supports import rock_chart_direction, rock_point, rock_normal, rock_bounds
    env=rock_fixture();sim=mature(env=env)
    chart=SurfaceChart(env,SolidStructureField([]),[],.1)
    assert sim.render_snapshot.stats["surface_support_kind"]=="analytic_rounded_rock"
    assert sim.render_snapshot.stats["surface_support_id"]=="rock_test_asset"
    thickness=sim.blueprint.growth["surface_growth_profile"]["thickness_m"]
    for att in sim.render_snapshot.attachment_points[::47]:
        u,v=att["uv_m"]
        direction=rock_chart_direction(chart.rock,u,v,chart.longitude,chart.latitude)
        point=rock_point(chart.rock,direction);normal=rock_normal(chart.rock,direction)
        expected=[point[i]+normal[i]*thickness for i in range(3)]
        assert att["position_m"]==pytest.approx(expected,abs=1e-6)
    assert max(p[3] for p in sim.render_snapshot.placements)-min(p[3] for p in sim.render_snapshot.placements)>.01
    assert PlantGrowthSnapshot.from_dict(json.loads(json.dumps(sim.render_snapshot.to_dict()))).to_dict()==sim.render_snapshot.to_dict()
    assert sim.render_snapshot.bounds_m==mature(env=env,lod=0).render_snapshot.bounds_m
    rock=chart.rock;b=rock_bounds(rock)
    assert all(b[2*i]<=rock_point(rock,(1,0,0))[i]<=b[2*i+1] for i in range(3))


def test_explicit_lifecycle_preserves_dry_cover_rewetting_and_accounts_for_damage():
    from tools.render_surface_growth import rock_fixture, rock_lifecycle_treatments
    sims=[mature(env=env) for _,env in rock_lifecycle_treatments(rock_fixture())]
    young,expanding,established,dry,rewet,damaged=sims
    areas=[s.render_snapshot.stats["surface_coverage_m2"] for s in sims]
    assert 0<areas[0]<areas[1]<areas[2]
    assert areas[2]==areas[3]==areas[4]
    assert 0<areas[5]<areas[2]*.65
    assert dry.render_snapshot.placements==rewet.render_snapshot.placements==established.render_snapshot.placements
    assert dry.render_snapshot.placement_paths==rewet.render_snapshot.placement_paths
    assert dry.get_ecological_outcome()["surface_activity"]==0
    assert rewet.get_ecological_outcome()["surface_activity"]==1
    assert dry.get_ecological_outcome()["mortality_risk"]==0
    assert young.render_snapshot.stats["canonical_apothecium_count"]==0
    assert expanding.render_snapshot.stats["canonical_apothecium_count"]==0
    assert established.render_snapshot.stats["canonical_apothecium_count"]>0
    assert dry.render_snapshot.stats["surface_effective_growth_years"]==25
    assert dry.render_snapshot.stats["surface_lifecycle_state"]=="dormant"
    assert damaged.render_snapshot.stats["surface_lifecycle_state"]=="damaged"
    removed=mature(env={**rock_fixture(),"surface_tissue_loss":1})
    assert not removed.render_snapshot.placements
    assert removed.get_ecological_outcome()["resource_demand"]==0
    assert removed.get_ecological_outcome()["fecundity"]==0


def test_supplied_history_integrates_active_time_and_invalid_rocks_remain_finite():
    from simulations.species.surface_supports import normalise_surface_supports,rock_chart_direction,rock_point,rock_normal
    history=[{"years":5,"thallus_hydration":.45},{"years":10,"thallus_hydration":0}]
    sim=mature(env={"surface_history":history})
    assert sim.render_snapshot.stats["surface_radius_m"]==pytest.approx(.01)
    dry=mature(env={"surface_history":[{"years":10,"thallus_hydration":0}]})
    assert not dry.render_snapshot.placements
    rock=normalise_surface_supports({"surface_supports":[{"kind":"rounded_rock",
           "radii_m":[float('nan'),0,float('inf')],"center_m":"bad","roughness":float('inf')}]})[0]
    direction=rock_chart_direction(rock,0,0)
    assert all(math.isfinite(x) for x in (*rock_point(rock,direction),*rock_normal(rock,direction)))
    assert normalise_surface_supports({"surface_supports":"bad"})==[]


def test_rock_renderer_hides_far_side_colony_and_shows_front_side():
    from tools.render_surface_growth import rock_fixture
    from simulations.species.species_renderer import SpeciesRenderer, SurfaceElevationCamera
    pygame.init();pygame.display.set_mode((1,1))
    e=entity();e["surface_growth_profile"]["colony_diameter"]={"max_m":.02}
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    env=rock_fixture();env["surface_attachment"]["latitude_deg"]=0
    frames=[]
    for longitude in (-90,90):
        env["surface_attachment"]["longitude_deg"]=longitude
        sim=mature(e=e,env=copy.deepcopy(env));image=pygame.Surface((550,450))
        renderer._draw_individual(image,sim,camera=SurfaceElevationCamera(550,450,[-.09,.09,-.06,.06,0,.14]),
                                  draw_ground_line=False,show_height_reference=False,cache=False)
        frames.append(pygame.surfarray.array3d(image))
    def green_count(pixels):
        return ((pixels[:,:,1]>pixels[:,:,0])&(pixels[:,:,0]>85)).sum()
    assert green_count(frames[0])>100
    assert green_count(frames[1])==0
    assert ((frames[1][:,:,0]>60)&(frames[1][:,:,0]>frames[1][:,:,1])).sum()>10000
    pygame.quit()


def test_rock_test_tab_uses_shared_cases_without_changing_the_inspected_specimen():
    from simulations.species.species_renderer import SpeciesRenderer
    sim=mature();before=sim.render_snapshot.to_dict();env=copy.deepcopy(sim.environment)
    assert sim.set_active_simulation_panel_tab("rock_test")
    cases=sim.get_rock_test_cases()
    assert len(cases)==6
    assert sim.get_rock_test_cases()[0][1] is cases[0][1]
    assert sim.render_snapshot.to_dict()==before and sim.environment==env
    assert cases[3][1].render_snapshot.placements==cases[4][1].render_snapshot.placements
    pygame.init();pygame.display.set_mode((1,1))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    first,second=pygame.Surface((1200,850)),pygame.Surface((1200,850))
    renderer.draw(first,sim);renderer.draw(second,sim)
    assert pygame.image.tobytes(first,"RGB")==pygame.image.tobytes(second,"RGB")
    # Each row has visible rock and body pixels, including the dry case.
    for y in (100,400):
        pixels=pygame.surfarray.array3d(first)[:,y:y+150]
        assert ((pixels[:,:,1]>pixels[:,:,0])&(pixels[:,:,0]>85)).sum()>50
    sim.seed+=1
    assert sim.get_rock_test_cases()[0][1] is not cases[0][1]
    assert mature(e={"id":"vascular_control"}).get_rock_test_cases()==[]
    pygame.quit()


def test_detailed_surface_cache_invalidates_after_scene_damage_changes():
    sim=mature();first=sim.get_detailed_snapshot()
    assert sim.get_detailed_snapshot() is first
    sim.environment["surface_tissue_loss"]=1
    lost=sim.get_detailed_snapshot()
    assert lost is not first and not lost.placements
    assert lost.stats["surface_lifecycle_state"]=="lost"
    assert not lost.stats["surface_attached"]


def test_rock_pixel_style_uses_a_flat_palette_and_shared_grid_without_changing_growth():
    from simulations.species.surface_supports import rock_fixture
    from simulations.species.species_renderer import SpeciesRenderer, SurfaceElevationCamera, ROCK_PIXEL_PALETTE
    env={**rock_fixture(),"surface_growth_years":0}
    sim=mature(env=env);renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    pygame.init();pygame.display.set_mode((1,1))
    image=pygame.Surface((520,420));camera=SurfaceElevationCamera(520,420,[-.09,.09,-.06,.06,0,.14])
    renderer._draw_individual(image,sim,camera=camera,draw_ground_line=False,show_height_reference=False,cache=False)
    pixels=pygame.surfarray.array3d(image)
    colors={tuple(color) for color in pixels.reshape(-1,3)}
    assert colors<={*ROCK_PIXEL_PALETTE,(18,23,20)}
    assert len(colors)>=4
    step=max(1,min(12,round(camera.scale*.003)))
    for x in range(0,520-step,step):
        for y in range(0,420-step,step):
            assert (pixels[x:x+step,y:y+step]==pixels[x,y]).all()
    occupied=mature(env=rock_fixture())
    coarse=rock_fixture();coarse["surface_supports"][0]["render_pixel_size_m"]=.006
    other=mature(env=coarse)
    assert occupied.render_snapshot.placements==other.render_snapshot.placements
    assert occupied.render_snapshot.placement_paths==other.render_snapshot.placement_paths
    assert occupied.get_ecological_outcome()==other.get_ecological_outcome()
    pygame.quit()
