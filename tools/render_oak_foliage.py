"""Whole-crown, branch and shoot comparisons using the live oak entity."""
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
import pygame
from world.persistent_ontology_store import PersistentOntologyStore
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds, branch_diagnostic_selection, branch_diagnostic_bounds


def descendants(placements,root):
    selected={root}
    for i,p in enumerate(placements):
        if p[1] in selected:
            selected.add(i)
    return selected


def bounds_for(sim,selected):
    points=[p[2:5] for i,p in enumerate(sim.render_snapshot.placements) if i in selected]
    xs=[p[0]+1.8*p[1] for p in points]
    zs=[p[2] for p in points]
    margin=sim.blueprint.module("leaf").length_m*.7
    return min(xs)-margin,max(xs)+margin,min(zs)-margin,max(zs)+margin


def render(output):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1,1))
    species=next(s for s in PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()["species"] if s["id"]=="spec_quercus_robur")
    sim=SpeciesSimulation(species_entity=species,seed=303)
    sim.set_age(sim.mature_age_days)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    ps=sim.render_snapshot.placements
    # A complete secondary limb and one terminal shoot from the same plant.
    selected,shoot=branch_diagnostic_selection(sim)
    sheet=pygame.Surface((1440,1040))
    sheet.fill((18,23,20))
    font=pygame.font.SysFont("consolas",18)
    heading=pygame.font.SysFont("consolas",24)
    sheet.blit(heading.render("English Oak | leaf distribution and branching",True,(230,237,222)),(20,15))
    sheet.blit(font.render("Same plant and seed. Individual leaves use a native 32 x 32 sprite.",True,(173,191,167)),(20,51))
    for col,(label,indices) in enumerate((("Whole crown",None),("Secondary branch",selected),("Current shoot",shoot))):
        bounds=diagnostic_cell_bounds(sim.render_snapshot) if indices is None else branch_diagnostic_bounds(sim,indices)
        for row,skeleton in enumerate((False,True)):
            panel=pygame.Surface((460,420))
            camera=DiagnosticCamera(460,420,bounds)
            camera.bottom=210+(bounds[3]-bounds[2])*camera.scale*.5
            renderer._draw_individual(panel,sim,camera=camera,visible_indices=indices,skeleton=skeleton)
            bar=10**math.floor(math.log10(90/camera.scale))
            pygame.draw.line(panel,(205,216,182),(20,396),(20+round(bar*camera.scale),396),2)
            panel.blit(font.render(f"{bar:g} m",True,(205,216,182)),(20,367))
            sheet.blit(panel,(col*480+10,126+row*450))
            sheet.blit(font.render(label+(" | structure" if skeleton else " | foliage"),True,(225,233,215)),(col*480+20,98+row*450))
    pygame.image.save(sheet,output/"oak_foliage_comparison.png")
    sim.set_active_simulation_panel_tab("branches")
    branch_view=pygame.Surface((1400,850))
    renderer.draw(branch_view,sim)
    pygame.image.save(branch_view,output/"oak_branches_view.png")
    variants=pygame.Surface((1440,680))
    variants.fill((18,23,20))
    variant_records=[]
    for col,distribution in enumerate(("along_shoot","terminal_cluster","mixed_long_short_shoots")):
        case=SpeciesSimulation(species_entity={**species,"plant_leaf_distribution":distribution},seed=303)
        case.set_age(case.mature_age_days)
        selected,current=branch_diagnostic_selection(case)
        bounds=branch_diagnostic_bounds(case,current)
        panel=pygame.Surface((460,500))
        camera=DiagnosticCamera(460,500,bounds)
        camera.bottom=250+(bounds[3]-bounds[2])*camera.scale*.5
        renderer._draw_individual(panel,case,camera=camera,visible_indices=current)
        variants.blit(panel,(col*480+10,95))
        variants.blit(font.render(distribution.replace("_"," "),True,(219,230,207)),(col*480+18,66))
        variant_records.append({"distribution":distribution,"stats":case.get_growth_summary()})
    variants.blit(heading.render("Leaf Distribution | same oak traits and seed",True,(226,234,219)),(20,20))
    variants.blit(font.render("Individual shoot views enlarged independently. Current-shoot node spacing changes with distribution.",True,(169,185,162)),(20,636))
    pygame.image.save(variants,output/"oak_distribution_variants.png")
    (output/"variants.json").write_text(json.dumps(variant_records,indent=2))
    (output/"snapshot.json").write_text(json.dumps(sim.render_snapshot.to_dict()),encoding="utf-8")
    (output/"summary.json").write_text(json.dumps(sim.get_growth_summary(),indent=2),encoding="utf-8")
    print(sim.get_growth_summary())
    pygame.quit()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("artifacts/oak_foliage_final"))
    render(parser.parse_args().output)
