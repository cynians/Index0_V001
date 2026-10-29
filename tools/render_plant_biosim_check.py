"""Inspect saved plant organs at production BioSim and map sizes."""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('SDL_VIDEODRIVER','dummy')
import pygame
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.plant_pictures import top_view, map_sprite_at
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from tools.render_species_views import stage_ages, configure_stage
from world.world_model import WorldModel


def sprite(renderer, sim, cap):
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,
        get_representative_species_simulation=lambda _rid:sim)
    instance={'species_id':sim.species_id,'representative_id':'inspection','abundance':1.,'visual_scale':1.,'variant':0}
    return BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(
        scene,instance,SimpleNamespace(zoom=400.,sprite_height_cap=cap))


def render(species_id, output_dir):
    pygame.init();pygame.display.set_mode((1,1))
    sim=SpeciesSimulation(world_model=WorldModel(),species_id=species_id,seed=303)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    stages=stage_ages(sim)
    sheet=pygame.Surface((1540,130+320*len(stages)+130));sheet.fill((18,23,20))
    font=pygame.font.SysFont('consolas',19);small=pygame.font.SysFont('consolas',15)
    def label(s,x,y):sheet.blit(font.render(s,True,(220,230,211)),(x,y))
    label(sim.blueprint.display_name+' | BioSim consumer check',20,16)
    label('Production grounded sprites and map pictures, shown at native pixel size | seed 303',20,48)
    label('220px-cap sprite                  84px-cap sprite              Top/map picture               40px map',20,86)
    records=[]
    for row,(name,age) in enumerate(stages):
        y=130+row*320;configure_stage(sim,name,age)
        label(f'{name} | model day {age:.0f}',20,y)
        samples=[]
        for cap,x in ((220,260),(84,650)):
            art,anchor=sprite(renderer,sim,cap)
            sheet.blit(art,(round(x-anchor[0]),round(y+260-anchor[1])))
            samples.append({'cap_px':cap,'size_px':list(art.get_size()),'ground_anchor_px':list(anchor),
                            'painted_bbox_px':list(art.get_bounding_rect())})
        pygame.draw.line(sheet,(105,97,70),(20,y+260),(790,y+260))
        picture=top_view(sim)
        if picture is not None:
            sheet.blit(picture,(925,y+44));sheet.blit(map_sprite_at(picture,40),(1390,y+120))
        records.append({'label':name,'age_model_days':age,'sprites':samples,
            'top_size_px':list(picture.get_size()) if picture is not None else None,
            'bounds_m':sim.render_snapshot.bounds_m})
    y=130+320*len(stages)
    moss = bool(sim.blueprint.growth.get('moss_turf_version'))
    label(('Repeated wet mats' if moss else 'Repeated mature stand')+' | native 84px sprites | seeds 11, 42, 303, 777, 901',20,y)
    adult_name,adult_age=next(((name,age) for name,age in stages if name==('Wet mat' if moss else 'Flowering')),stages[-1])
    for i,seed in enumerate((11,42,303,777,901)):
        case=SpeciesSimulation(species_entity=sim.species_entity,seed=seed);configure_stage(case,adult_name,adult_age)
        art,anchor=sprite(renderer,case,84)
        sheet.blit(art,(round(500+i*110-anchor[0]),round(y+115-anchor[1])))
    pygame.draw.line(sheet,(105,97,70),(450,y+115),(1080,y+115))
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'detail.png')
    (output_dir/'biosim_check.json').write_text(json.dumps({'species_id':species_id,
        'blueprint_fingerprint':sim.blueprint.fingerprint(),'seed':303,'stages':records,
        'source':'Production BioSim grounded-sprite and plant-picture adapters; no live scene navigation'},indent=2),encoding='utf-8')
    pygame.quit()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--species',required=True);parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    render(args.species,args.output_dir or Path('artifacts')/args.species)
