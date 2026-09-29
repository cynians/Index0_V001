"""Paired live oak species previews with fixed seed and shared physical scales."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import pygame
from world.persistent_ontology_store import PersistentOntologyStore
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds, branch_diagnostic_selection, branch_diagnostic_bounds


def shared_bounds(bounds):
    return (min(b[0] for b in bounds),max(b[1] for b in bounds),min(b[2] for b in bounds),max(b[3] for b in bounds))


def render(output,forest=True):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1,1))
    rows=PersistentOntologyStore(Path('ontology/index0.owl')).load_datasets()['species']
    sims=[SpeciesSimulation(species_entity=next(e for e in rows if e['id']==eid),seed=303)
          for eid in ('spec_quercus_robur','spec_quercus_petraea')]
    for sim in sims: sim.set_age(sim.mature_age_days)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    sheet=pygame.Surface((1500,1180))
    sheet.fill((18,23,20))
    font=pygame.font.SysFont('consolas',18)
    small=pygame.font.SysFont('consolas',15)
    for col,sim in enumerate(sims):
        sheet.blit(font.render(sim.blueprint.display_name,True,(225,234,213)),(20+col*750,18))
        sheet.blit(small.render('Same seed 303 | mature stage | shared scale in each row',True,(168,190,165)),(20+col*750,50))
    # Secondary branch / current shoot columns need authentic per-leaf
    # geometry, which the default (coarse) snapshot no longer carries.
    detailed=[sim.get_detailed_snapshot() for sim in sims]
    selections=[branch_diagnostic_selection(sim,snapshot=snap) for sim,snap in zip(sims,detailed)]
    for row,(caption,top,height) in enumerate((('Whole tree',104,390),('Secondary branch',535,270),('Current shoot',856,245))):
        indices=[None if row==0 else selections[i][row-1] for i in range(2)]
        bounds=shared_bounds([diagnostic_cell_bounds(s.render_snapshot) if idx is None else branch_diagnostic_bounds(s,idx,snapshot=snap) for s,snap,idx in zip(sims,detailed,indices)])
        for col,(sim,snap,idx) in enumerate(zip(sims,detailed,indices)):
            panel=pygame.Surface((730,height))
            camera=DiagnosticCamera(730,height,bounds)
            camera.bottom=height/2+(bounds[3]-bounds[2])*camera.scale/2
            renderer._draw_individual(panel,sim,camera=camera,visible_indices=idx,snapshot=snap if idx is not None else None)
            sheet.blit(panel,(10+col*750,top))
            sheet.blit(small.render(caption,True,(204,215,191)),(20+col*750,top-23))
    sheet.blit(small.render('Sessile oak: slightly less droop, more open crown; differences are authored model settings.',True,(169,189,162)),(20,1137))
    pygame.image.save(sheet,output/'oak_species_comparison.png')
    assets=pygame.Surface((960,330)); assets.fill((22,28,23))
    paths=[('English oak leaf',sims[0].species_entity['plant_leaf_module_ref'])]
    paths += [('Sessile '+role,f'assets/illustrations/illust_quercus_petraea_{role}_32_v001_pixel.png') for role in ('leaf','bark','branch')]
    for i,(name,path) in enumerate(paths):
        sprite=pygame.image.load(path)
        assets.blit(pygame.transform.scale(sprite,(224,224)),(i*240+8,45))
        assets.blit(small.render(name,True,(219,230,203)),(i*240+8,15))
    assets.blit(small.render('Native 32 x 32 assets shown at 7x nearest-neighbour scale',True,(174,193,165)),(15,298))
    pygame.image.save(assets,output/'pixel_assets.png')
    records={'species':[{'id':s.species_id,'growth':s.blueprint.growth,'stats':s.get_growth_summary()} for s in sims],'forests':[]}
    if forest:
        contact=pygame.Surface((1600,1200))
        for row,spacing in enumerate(('dense','open')):
            for col,sim in enumerate(sims):
                sim.set_forest_settings(spacing,None)
                panel=pygame.Surface((1200,900))
                renderer._draw_forest(panel,sim)
                pygame.image.save(panel,output/f'{sim.species_id}_{spacing}.png')
                contact.blit(pygame.transform.scale(panel,(800,600)),(col*800,row*600))
                plan,cases=sim.get_forest_experiment()
                records['forests'].append({'species':sim.species_id,'spacing':spacing,'established':plan['established_count'],
                    'mean_light':plan['mean_ground_light'],'centre_cohorts':len(cases[4].render_snapshot.leaf_clusters)})
        pygame.image.save(contact,output/'forest_species_comparison.png')
    (output/'results.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(json.dumps(records['forests']))
    pygame.quit()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('artifacts/sessile_oak_final'))
    parser.add_argument('--no-forest',action='store_true')
    args=parser.parse_args()
    render(args.output,not args.no_forest)
