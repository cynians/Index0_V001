"""Compose a saved fungus with a saved host tree at physical scale."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.fungal_tree_support import wood_from_tree_snapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds
from world.world_model import WorldModel


def build_scene(world,host_id,fungus_id,*,material="living_hardwood",seed=303,interval=(.7,3.2),age=90):
    host=SpeciesSimulation(world_model=world,species_id=host_id,seed=seed)
    host.set_lod(2);host.set_age(host.mature_age_days)
    wood=wood_from_tree_snapshot(host.render_snapshot,host.blueprint,material=material,interval_m=interval)
    environment={"fungal_substrates":[wood] if wood else [],
                 "substrate_context_source":"actual_generated_host_tree_wound_window"}
    fungus=SpeciesSimulation(world_model=world,species_id=fungus_id,seed=seed,environment=environment)
    fungus.set_lod(2);fungus.set_age(age)
    return host,fungus,wood


def draw_scene(renderer,host,fungus,size,bounds,*,cutaway=False,centered=False):
    panel=pygame.Surface(size)
    camera=DiagnosticCamera(*size,bounds)
    if centered:
        camera.bottom=size[1]*.5+(bounds[3]-bounds[2])*camera.scale*.5
    renderer._draw_individual(panel,host,camera=camera,cache=False,show_height_reference=False)
    fungus.diagnostic_view="mycelium" if cutaway else "individual"
    renderer._draw_individual(panel,fungus,camera=camera,clear=False,cache=False,draw_environment=False,draw_ground_line=False)
    return panel


def render(host_id,fungus_id,output,status):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init();pygame.display.set_mode((1,1));world=WorldModel()
    host,fungus,wood=build_scene(world,host_id,fungus_id)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    bodies=fungus.render_snapshot.stats.get("fungal_bodies",[])
    if not bodies:
        raise RuntimeError("No fungal bodies for this host/material scenario")
    width=1600;height=1050;sheet=pygame.Surface((width,height));sheet.fill((13,20,17))
    title=pygame.font.SysFont("consolas",23);font=pygame.font.SysFont("consolas",17)
    sheet.blit(title.render(f"{fungus.blueprint.display_name} on {host.blueprint.display_name}",True,(228,236,216)),(20,15))
    sheet.blit(font.render("Actual generated host trunk | metre scale | independent fungal model clock | renderer preview",True,(168,188,161)),(20,47))
    bounds=diagnostic_cell_bounds(host.render_snapshot)
    panel=draw_scene(renderer,host,fungus,(700,870),bounds,centered=True)
    marker_camera=DiagnosticCamera(700,870,bounds)
    marker_camera.bottom=435+(bounds[3]-bounds[2])*marker_camera.scale*.5
    sockets=[marker_camera.world_to_screen_3d(b["socket_m"]) for b in bodies]
    marker=(round(sum(p[0] for p in sockets)/len(sockets)),round(sum(p[1] for p in sockets)/len(sockets)))
    pygame.draw.circle(panel,(216,195,113),marker,18,1)
    panel.blit(font.render("Bracket cluster",True,(216,195,113)),(marker[0]+24,marker[1]-8))
    sheet.blit(panel,(10,95))
    sheet.blit(font.render("Whole mature host | brackets retain their real cap size",True,(219,221,192)),(20,78))
    sheet.blit(font.render("The host's growth and leaf area are unchanged.",True,(168,188,161)),(20,122))
    centers=[b["socket_m"] for b in fungus.render_snapshot.stats["fungal_bodies"]]
    if not centers:raise RuntimeError("No fungal bodies for this host/material scenario")
    xs=[p[0]+p[1]*1.8 for p in centers];zs=[p[2] for p in centers]
    close=(min(xs)-.8,max(xs)+.8,min(zs)-.3,max(zs)+.35)
    sheet.blit(draw_scene(renderer,host,fungus,(860,565),close),(730,105))
    sheet.blit(font.render("Enlarged trunk view | same metre-sized caps, closer camera",True,(219,221,192)),(740,78))
    # A physical scale bar for the enlarged view.
    camera=DiagnosticCamera(860,565,close);pixels=abs(camera.world_to_screen((.2,0))[0]-camera.world_to_screen((0,0))[0])
    pygame.draw.line(sheet,(230,202,123),(755,640),(755+pixels,640),3)
    sheet.blit(font.render("20 cm",True,(230,202,123)),(755,614))
    records=[]
    for i,(caption,age) in enumerate((("Emerging",35),("Between flushes",130),("Next flush",210))):
        fungus.set_age(age)
        cell=draw_scene(renderer,host,fungus,(280,270),close,cutaway=True)
        x=735+i*285;sheet.blit(cell,(x,735))
        sheet.blit(font.render(caption,True,(219,221,192)),(x+6,699))
        sheet.blit(font.render(f"Model day {age}",True,(168,188,161)),(x+6,719))
        sheet.blit(font.render(f"Brackets {fungus.render_snapshot.stats['estimated_fruiting_body_count']}",True,(166,190,157)),(x+6,1008))
        records.append({"caption":caption,"age_days":age,"snapshot":fungus.render_snapshot.to_dict(),"ecology":fungus.get_ecological_outcome()})
    sheet.blit(font.render("Cutaway: the fungal colony persists inside the host wood",True,(168,188,161)),(740,674))
    pygame.image.save(sheet,output/("before.png" if status=="before" else "after.png"))
    (output/f"{status}.json").write_text(json.dumps({"seed":303,"host_blueprint":host.blueprint.to_dict(),
        "host_snapshot":host.render_snapshot.to_dict(),"host_ecology":host.get_ecological_outcome(),
        "substrate":wood,"close_bounds_m":close,"stages":records,"source":"live resolved host and fungus; scene inputs not persisted"},indent=2))
    pygame.quit()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host",default="spec_acer_rubrum")
    parser.add_argument("--fungus",default="spec_cerioporus_squamosus")
    parser.add_argument("--output-dir",type=Path,default=Path("artifacts/fungal_tree_interaction"))
    parser.add_argument("--status",choices=("before","after"),default="after")
    args=parser.parse_args();render(args.host,args.fungus,args.output_dir,args.status)
