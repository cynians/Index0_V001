"""Import a generated oak leaf into the native 32x32 Pixel Studio grid."""
from pathlib import Path
import json
import argparse
import pygame
from PIL import Image
from tools.author_woods_rose_assets import PixelEditorHost, author_module, upsert, stroke
from world.entity_loader import EntityLoader
from world.persistent_ontology_store import PersistentOntologyStore


def main(source):
    pygame.init()
    loader=EntityLoader()
    species=loader.entities["spec_quercus_robur"]
    output=Path("artifacts/oak_foliage")
    output.mkdir(parents=True,exist_ok=True)
    fields=("plant_leaf_module_ref","plant_module_anchors","leaf_size_class")
    backup=output/"oak_leaf_fields_before.json"
    if not backup.exists():
        backup.write_text(json.dumps({k:species.get(k) for k in fields},indent=2))
    # Import into the user's requested native grid. Binary alpha and four
    # discrete paint colours remove texture from the generated source.
    image=Image.open(source).convert("RGBA").resize((32,32),Image.Resampling.NEAREST)
    palette=((36,73,32),(56,102,40),(83,132,49),(131,166,70))
    def paint(editor):
        editor.state["canvas_rect"]=pygame.Rect(0,0,32,32)
        for y in range(32):
            for x in range(32):
                r,g,b,a=image.getpixel((x,y))
                if a<180 or g<65:
                    continue
                color=palette[min(3,max(0,int((g-65)/48)))]
                stroke(editor,[(x,y)],color,1)
    entity_id="illust_quercus_robur_leaf_32"
    upsert(loader,{"id":entity_id,"_dataset":"ideas","type":"idea","idea_class":"illustration",
                  "name":"English Oak Leaf 32px","pretty_name":"English Oak Leaf 32px",
                  "parents":[species["id"]],"plant_asset_role":"leaf","plant_asset_kind":"leaf",
                  "plant_asset_target_field":"plant_leaf_module_ref","depicted_size_m":.10})
    leaf=author_module(PixelEditorHost(loader),entity_id,.10,(32,32),paint,(16,29))
    species["plant_leaf_module_ref"]=leaf["media_path"]
    species["plant_module_anchors"]={**(species.get("plant_module_anchors") or {}),"leaf":leaf["pixel_module_anchor"]}
    species["leaf_size_class"]="small"
    PersistentOntologyStore(Path("ontology/index0.owl")).persist_entity_fields(species,fields)
    print(json.dumps({"asset":leaf["media_path"],"document":leaf.get("pixel_document_path"),"anchor":leaf["pixel_module_anchor"]}))
    pygame.quit()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    main(parser.parse_args().source)
