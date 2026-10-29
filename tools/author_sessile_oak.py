"""Author a closely related oak and import generated artwork into Pixel Studio."""
import argparse
import copy
import json
from pathlib import Path
import pygame
from world.entity_loader import EntityLoader
from tools.author_woods_rose_assets import PixelEditorHost, author_module, upsert, stroke

SPECIES_ID = "spec_quercus_petraea"
GREEN = [(36,73,32),(56,102,40),(83,132,49),(131,166,70)]
BROWN = [(62,53,42),(92,79,62),(126,112,91),(162,147,122)]


def import_painter(source, palette, opaque=False):
    image=pygame.transform.scale(pygame.image.load(str(source)),(32,32))
    def paint(editor):
        editor.state['canvas_rect']=pygame.Rect(0,0,32,32)
        for y in range(32):
            for x in range(32):
                pixel=image.get_at((x,y))
                if not opaque and pixel.a < 180:
                    continue
                color=min(palette,key=lambda c:sum((c[j]-pixel[j])**2 for j in range(3)))
                stroke(editor,[(x,y)],color,1)
    return paint


def main(leaf_source,bark_source,branch_source):
    pygame.init()
    loader=EntityLoader()
    if not loader.plant_catalogue.is_species('spec_quercus_robur'):
        raise RuntimeError('Oak ancestry is unavailable')
    output=Path('artifacts/sessile_oak')
    output.mkdir(parents=True,exist_ok=True)
    backup=output/'before.json'
    if not backup.exists():
        backup.write_text(json.dumps(loader.entities.get(SPECIES_ID),indent=2),encoding='utf-8')
    # Explicitly remove identity, relationships and asset references when using
    # the closely related authored oak as a starting point.
    species={k:copy.deepcopy(v) for k,v in loader.entities['spec_quercus_robur'].items()
             if k not in {'id','offspring','employed_people','plant_module_anchors'}
             and not k.endswith('_ref')}
    species.update(id=SPECIES_ID,common_name='Sessile Oak - Quercus petraea',
        pretty_name='Sessile Oak - Quercus petraea',binomial_name='Quercus petraea',
        parents=['cladis_quercus'],plant_leaf_spacing_bias=.60,plant_branch_droop=.20,
        plant_crown_openness=.48,plant_fine_twig_density=.86,plant_leaf_cluster_density=.80,
        waterlogging_tolerance='low',shade_tolerance='medium',leaf_size_class='small',
        wiki_entry='# Sessile oak\n\nQuercus petraea has stalked, regularly lobed simple leaves. '
        'This representative shares oak height, life history and medium shade tolerance. '
        'The modest crown openness, droop, spacing and twig-density differences are authored '
        'visual modelling choices, not measured species constants. Root and life-history '
        'parameters inherit the existing oak approximation.\n\n'
        'Sources: https://landscapeplants.oregonstate.edu/plants/quercus-petraea ; '
        'https://www.forestresearch.gov.uk/tools-and-resources/tree-species-database/131560-sessile-oak-sok/ '
        '\n\nAssets: native 32 x 32 leaf, bark and twig. Reproductive assets are not yet authored.')
    species=upsert(loader,species)
    host=PixelEditorHost(loader)
    records={}
    for role,source,size,palette in [('leaf',leaf_source,.1,GREEN),('bark',bark_source,.2,BROWN),('branch',branch_source,.2,BROWN)]:
        eid=f'illust_quercus_petraea_{role}_32_v001'
        entity={'id':eid,'_dataset':'ideas','type':'idea','idea_class':'illustration',
                'name':f'Sessile Oak {role.title()} 32px','pretty_name':f'Sessile Oak {role.title()} 32px',
                'parents':[SPECIES_ID],'depicted_size_m':size,
                'plant_asset_role':role,'plant_asset_kind':role}
        if role=='bark':
            entity['pixel_editor_mode']='texture'
        upsert(loader,entity)
        result=author_module(host,eid,size,(32,32),import_painter(source,palette,role=='bark'),(16,29))
        records[role]={'media_path':result['media_path'],'pixel_document_path':result['pixel_document_path'],
                       'anchor':result['pixel_module_anchor'],'source':str(source)}
    species['plant_leaf_module_ref']=records['leaf']['media_path']
    species['plant_branch_module_ref']=records['branch']['media_path']
    species['plant_bark_texture_set_ref']=records['bark']['pixel_document_path']
    species['plant_module_anchors']={'leaf':records['leaf']['anchor'],'branch':records['branch']['anchor']}
    upsert(loader,species)
    assert loader.plant_catalogue.is_species(SPECIES_ID)
    (output/'authored.json').write_text(json.dumps({'species':species,'assets':records},indent=2),encoding='utf-8')
    print(json.dumps(records,indent=2))
    pygame.quit()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for role in ('leaf','bark','branch'):
        parser.add_argument(role,type=Path)
    args=parser.parse_args()
    main(args.leaf,args.bark,args.branch)
