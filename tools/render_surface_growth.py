"""Production renderer evidence for a surface organism on a wall and trunk.

Fixtures are transient scene geometry, never ontology habitat facts. Every
species uses the same seed/cameras; no species-specific renderer branch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import SpeciesRenderer, SurfaceElevationCamera, IsometricDiagnosticCamera
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel
from simulations.species.surface_supports import ROCK_TEST_ASSET, rock_fixture, rock_lifecycle_treatments


def wall_fixture():
    rows=["#"*36 for _ in range(20)]
    for i in range(6,11):
        rows[i]=rows[i][:16]+"."*4+rows[i][20:]
    return {"solid_structures":[{"id":"lichen_wall","kind":"wall","position_m":[0,0,0],
        "rotation_deg":0,"pixel_size_m":.01,"extrusion_depth_m":.02,"mask_rows":rows,
        "palette":{"fill":[93,89,80],"edge":[120,112,100]}}],
        "surface_attachment":{"support_id":"lichen_wall","uv_m":[-.035,.115]}}


def trunk_fixture():
    return {"climbing_supports":[{"id":"curved_trunk","kind":"tree","radius_m":.025,
        "center_m":[0,0],"height_m":.15,"crown_radius_m":.025,
        "axis_points_m":[[0,0,0],[.008,.004,.075],[.004,.001,.15]]}],
        "surface_attachment":{"support_id":"curved_trunk","uv_m":[0,.08]}}


def render(species_id, output, seed=303, rock_test_asset=None, overrides=None, lifecycle_growth_years=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    world=WorldModel();entity=world.resolved_species_entity(species_id)
    if entity is None:
        raise ValueError(f"Unknown species {species_id}")
    entity={**entity,**(overrides or {})}
    def specimen(env,fraction=1.):
        sim=SpeciesSimulation(world_model=None if overrides else world,species_id=species_id,
                              species_entity=entity,seed=seed,environment=env)
        if sim.blueprint.growth.get("growth_behaviour")!="surface_covering":
            raise ValueError("The species needs an authored surface-covering recipe")
        sim.set_lod(2);sim.set_age(sim.mature_age_days*fraction)
        return sim
    wall=specimen(wall_fixture());trunk=specimen(trunk_fixture())
    pygame.init();pygame.display.set_mode((1,1))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None));font=pygame.font.SysFont("consolas",18)
    def panel(sim,size,camera):
        image=pygame.Surface(size)
        renderer._draw_individual(image,sim,camera=camera,show_height_reference=False,
                                 draw_ground_line=False,cache=False)
        return image
    def title(canvas,text,position):
        canvas.blit(font.render(text,True,(226,233,214)),position)
    bounds=[-.20,.20,-.025,.025,-.01,.21]
    sheet=pygame.Surface((1600,720));sheet.fill((18,23,20))
    for i,cls in enumerate((SurfaceElevationCamera,IsometricDiagnosticCamera)):
        sheet.blit(panel(wall,(780,630),cls(780,630,bounds)),(10+800*i,60))
        title(sheet,"SURFACE COLONY | "+("FRONT" if i==0 else "ISOMETRIC")+" | same 3D state",(15+800*i,20))
    pygame.image.save(sheet,output/"after.png")
    detail=pygame.Surface((1600,1080));detail.fill((18,23,20))
    detail.blit(panel(wall,(770,600),SurfaceElevationCamera(770,600,[-.1,.025,-.023,-.008,.054,.175])),(10,55))
    title(detail,"WALL DETAIL | same colony, independently enlarged",(15,20))
    detail.blit(panel(trunk,(770,600),IsometricDiagnosticCamera(770,600,trunk.render_snapshot.bounds_m)),(810,55))
    title(detail,"CURVED TRUNK | transient support geometry test",(810,20))
    stages=[]
    for i,fraction in enumerate((.25,.55,1.)):
        sim=specimen({},fraction)
        detail.blit(panel(sim,(510,350),SurfaceElevationCamera(510,350,[-.055,.055,-.003,0,-.055,.055])),(10+530*i,690))
        title(detail,f"Preview progress {fraction} | same scale",(15+530*i,660))
        stages.append({"preview_fraction":fraction,"coverage_m2":sim.render_snapshot.stats["surface_coverage_m2"],
                       "radius_m":sim.render_snapshot.stats["surface_radius_m"]})
    title(detail,"Growth stages use a developmental preview clock; they are not calendar ages.",(15,1044))
    rock_metrics=[]
    rock_presentation=[]
    if rock_test_asset is not None:
        asset=rock_fixture(rock_test_asset)
        fruticose=wall.blueprint.growth["surface_growth_profile"]["thallus_form"]=="fruticose"
        enlarged=wall.blueprint.growth["surface_growth_profile"]["thallus_form"] in {"fruticose","foliose","placodioid_crustose"}
        detail=pygame.Surface((1600,1530 if enlarged else 1080));detail.fill((18,23,20))
        title(detail,("UNSAVED DESIGN | " if overrides else "")+"ROCK_TEST_ASSET | same seed, surface attachment, camera and physical scale",(15,15))
        rock_bounds=[-.085,.085,-.060,.060,0,.135]
        profile=wall.blueprint.growth["surface_growth_profile"]
        for i,(label,env) in enumerate(rock_lifecycle_treatments(asset,profile,lifecycle_growth_years)):
            sim=specimen(env);x=10+(i%3)*530;y=65+(i//3)*475
            title(detail,label,(x,y))
            detail.blit(panel(sim,(510,395),IsometricDiagnosticCamera(510,395,rock_bounds)),(x,y+25))
            stats=sim.render_snapshot.stats;eco=sim.get_ecological_outcome()
            title(detail,f"Cover {stats['surface_coverage_m2']*10000:.1f} cm2 | activity {eco['surface_activity']:.2f}",(x,y+421))
            rock_metrics.append({"label":label,"environment":env,"stats":stats,"ecological_outcome":eco})
        title(detail,"Size stages and lifecycle controls are qualitative previews; rates and ages require species-specific evidence.",(15,1032))
        title(detail,"Drying preserves cover; rewetting restores activity. No maximum lifespan or new spore recruits are invented.",(15,1058))
        if enlarged:
            close_env=rock_lifecycle_treatments(asset,profile,lifecycle_growth_years)[2][1]
            # Display-only finer shared sprite grid exposes millimetre scales.
            close_env["surface_supports"][0]["render_pixel_size_m"]=.0005 if fruticose else .00025
            close=specimen(close_env)
            points=[p for i,path in close.render_snapshot.placement_paths.items()
                    if not fruticose or close.render_snapshot.placements[int(i)][0]!="thallus" for p in path]
            close_bounds=[v for axis in range(3) for v in
                          (min(p[axis] for p in points)-.005,max(p[axis] for p in points)+.005)]
            for i,cls in enumerate((SurfaceElevationCamera,IsometricDiagnosticCamera)):
                camera=(cls(780,390,close_bounds,surface_rotation_deg=float(asset["surface_attachment"].get("longitude_deg",-90))+90)
                        if i==0 else cls(780,390,close_bounds))
                detail.blit(panel(close,(780,390),camera),(10+800*i,1115))
                title(detail,"ENLARGED THALLUS DETAIL | finer display grid | "+("2D" if i==0 else "ISOMETRIC"),(15+800*i,1090))
        # Show both established presentation conventions, with and without
        # the covering. Lifecycle evidence retains the paired six-case layout.
        sheet=pygame.Surface((1600,940));sheet.fill((18,23,20))
        for row,(name,years) in enumerate((("BARE ROCK",0),("ESTABLISHED COVER",25))):
            env={**asset,"surface_growth_years":years,"surface_reproductive_progress":1,
                 "surface_weathering_progress":1,"thallus_hydration":.45}
            if profile["radial_rate_source"] == "runtime_default":
                env["surface_growth_years"]=0
                env["surface_initial_radius_m"]=profile["diameter_m"]/2 if years else 0
            sim=specimen(env)
            cameras=[SurfaceElevationCamera(780,405,rock_bounds,
                         surface_rotation_deg=float(asset["surface_attachment"].get("longitude_deg",-90))+90),
                     IsometricDiagnosticCamera(780,405,rock_bounds)]
            shared_scale=min(camera.scale for camera in cameras)
            cameras[0].scale=shared_scale
            cameras[0].offset_x=390-(cameras[0].min_u+cameras[0].max_u)*.5*shared_scale
            cameras[0].bottom=202.5+(cameras[0].min_z+cameras[0].max_z)*.5*shared_scale
            for column,cls in enumerate((SurfaceElevationCamera,IsometricDiagnosticCamera)):
                size=(780,405);x=10+800*column;y=45+465*row
                sheet.blit(panel(sim,size,cameras[column]),(x,y))
                title(sheet,name+" | "+("PIXEL 2D" if column==0 else "ISOMETRIC"),(x+5,y-28))
            rock_presentation.append({"label":name,"stats":sim.render_snapshot.stats,
                                      "camera_bounds_m":rock_bounds,"pixels_per_metre":shared_scale,
                                      "elevation_rotation_deg":cameras[0].surface_rotation_deg})
        title(sheet,("UNSAVED DESIGN PREVIEW | " if overrides else "")+"Shared pixel grid, attachment geometry and coverage for both views.",(15,917))
        pygame.image.save(sheet,output/"after.png")
    pygame.image.save(detail,output/"detail.png");pygame.quit()
    metrics={"seed":seed,"lod":2,"experimental_overrides":bool(overrides),"wall_camera_bounds_m":bounds,
             "fingerprint":wall.blueprint.fingerprint(),"age_days":wall.age_days,
             "stats":wall.render_snapshot.stats,"ecological_outcome":wall.get_ecological_outcome(wall.environment),
             "trunk_stats":trunk.render_snapshot.stats,"growth_stages":stages,
             "hydration_contrasts":{str(h):wall.get_ecological_outcome({"thallus_hydration":h}) for h in (0,.45,1)},
             "rock_test_asset":str(rock_test_asset) if rock_test_asset else None,
             "rock_presentation":rock_presentation,
             "rock_lifecycle":rock_metrics}
    (output/"after_metrics.json").write_text(json.dumps(metrics,indent=2)+"\n",encoding="utf-8")
    (output/"wall_fixture.json").write_text(json.dumps(wall.environment,indent=2)+"\n",encoding="utf-8")
    return {"species_id":species_id,"coverage_m2":metrics["stats"]["surface_coverage_m2"],
            "after":str(output/"after.png"),"detail":str(output/"detail.png")}


def render_atmospheric_inspection(species_id, output, seed=303):
    """Shared-scale mineral-rock colonization under explicit air histories."""
    from copy import deepcopy
    from simulations.species.surface_atmosphere import atmosphere_treatments
    world = WorldModel()
    entity = world.resolved_species_entity(species_id)
    profile = (entity or {}).get('surface_growth_profile') or {}
    if not profile.get('atmospheric_tolerance'):
        raise ValueError('Atmospheric inspection requires an authored surface atmosphere envelope')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    pygame.init(); pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1600, 950)); sheet.fill((18, 23, 20))
    font = pygame.font.SysFont('consolas', 17)
    def label(text, x, y):
        sheet.blit(font.render(text, True, (226, 233, 214)), (x, y))
    label(f'{entity.get("pretty_name", species_id)} | authored atmospheric envelope | production renderer', 16, 12)
    label('Same rock, seed 303, LOD 2, camera and one-year exposure | coefficients are design assumptions', 16, 38)
    fixture = rock_fixture()
    controls = [('BARE ROCK | initial control', {})] + atmosphere_treatments()
    records = []
    for i, (name, exposure) in enumerate(controls):
        env = {**deepcopy(fixture), **exposure, 'surface_reproductive_progress': 1.,
               'surface_weathering_progress': 1., 'surface_initial_radius_m': .015 if i >= 4 else .005,
               'surface_history': [{'years': 1., **exposure}]}
        if i == 0:
            env.update(surface_initial_radius_m=0., surface_history=[])
        sim = SpeciesSimulation(world_model=world, species_id=species_id, seed=seed, environment=env)
        sim.set_lod(2); sim.set_age(sim.mature_age_days)
        x = 10+(i%3)*530; y = 88+(i//3)*410
        label(name, x+5, y)
        camera = IsometricDiagnosticCamera(510, 320, [-.085, .085, -.060, .060, 0., .135])
        panel = pygame.Surface((510, 320))
        renderer._draw_individual(panel, sim, camera=camera, cache=False,
                                 show_height_reference=False, draw_ground_line=False)
        pygame.draw.line(panel, (220, 204, 135), (18, 296), (18+round(.02*camera.scale), 296), 3)
        panel.blit(font.render('2 cm', True, (220, 204, 135)), (18, 275))
        sheet.blit(panel, (x, y+26))
        stats = sim.render_snapshot.stats; outcome = sim.get_ecological_outcome()
        activity = outcome['surface_activity'] if stats['surface_coverage_m2'] > 0 else 0.
        label(f'Cover {stats["surface_coverage_m2"]*10000:.1f} cm2 | activity {activity:.2f}', x+5, y+353)
        label(f'Standing mass {outcome["standing_biomass_kg"]*1000:.2f} g | roots 0', x+5, y+376)
        records.append({'label': name, 'environment': env, 'stats': stats, 'ecology': outcome})
    label('Dry and vacuum controls begin with 1.5 cm established radius: activity stops, retained cover remains.', 16, 916)
    pygame.image.save(sheet, output/'after.png'); pygame.quit()
    (output/'atmospheric_metrics.json').write_text(json.dumps({
        'species_id': species_id, 'seed': seed, 'lod': 2,
        'blueprint_fingerprint': sim.blueprint.fingerprint(), 'cases': records,
        'interpretation': 'One-year supplied exposure history, bounded chart; not survival or planetary terraforming proof'}, indent=2), encoding='utf-8')
    return {'sheet': str(output/'after.png'), 'cases': len(records)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=303)
    parser.add_argument('--atmosphere-inspection', action='store_true', help='Six shared-scale atmospheric history and dormancy cases')
    parser.add_argument('--lifecycle-growth-years', nargs=3, type=float, help='Explicit effective growth-year controls for young, expanding, established detail panels')
    parser.add_argument("--rock-test-asset",type=Path,nargs="?",const=ROCK_TEST_ASSET,
                        help="Replace the detail sheet with six lifecycle treatments on an analytic rock")
    args=parser.parse_args()
    result = (render_atmospheric_inspection(args.species, args.output, args.seed) if args.atmosphere_inspection
              else render(args.species,args.output,args.seed,args.rock_test_asset,lifecycle_growth_years=args.lifecycle_growth_years))
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
