"""Fixed-seed oak experiments; does not mutate the live ontology."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import pygame
from world.persistent_ontology_store import PersistentOntologyStore
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer


def render(output):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1,1))
    oak=next(s for s in PersistentOntologyStore(Path('ontology/index0.owl')).load_datasets()['species'] if s['id']=='spec_quercus_robur')
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    sim=SpeciesSimulation(species_entity=oak,seed=303)
    sim.diagnostic_view='forest'
    records=[]
    sheet=pygame.Surface((2400,1200))
    for row,spacing in enumerate(('dense','open')):
        for col,tolerance in enumerate(('low','medium','high')):
            sim.set_forest_settings(spacing,tolerance)
            panel=pygame.Surface((1200,900))
            renderer._draw_forest(panel,sim)
            name=f'{spacing}_{tolerance}'
            pygame.image.save(panel,output/f'{name}.png')
            sheet.blit(pygame.transform.scale(panel,(800,600)),(col*800,row*600))
            plan,cases=sim.get_forest_experiment()
            record={**plan,'cohorts':[len(c.render_snapshot.leaf_clusters) for c in cases]}
            records.append(record)
            print(name,plan['established_count'],round(plan['mean_ground_light'],3),record['cohorts'][4])
    pygame.image.save(sheet,output/'forest_comparison.png')
    (output/'results.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    sim.set_forest_settings('medium',None)
    panel=pygame.Surface((1400,950))
    renderer._draw_forest(panel,sim)
    pygame.image.save(panel,output/'forest_view.png')
    pygame.quit()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('artifacts/forest_shade_final'))
    render(parser.parse_args().output)
