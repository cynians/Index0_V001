"""Author the second researched plant representative: European white water lily.

The pixels are made through the same editor controller used by the desktop
authoring flow.  The species deliberately exercises a different blueprint
grammar from ryegrass: a submerged rhizome, floating leaves on petioles, and
one surface flower.
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.entity_loader import EntityLoader
from tools.author_lolium_perenne import PixelEditorHost, paint_stroke, upsert


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIES_ID = "spec_nymphaea_alba"
GENUS_ID = "cladis_water_lilies_nymphaea"
LEAF_ID = "idea_nymphaea_alba_leaf_pixel"
FLOWER_ID = "idea_nymphaea_alba_flower_pixel"


def paint_filled_circle(editor, start, end, color):
    editor.set_color_rgb(color)
    editor.set_tool("circle")
    editor.state["shape_filled"] = True
    editor.handle_click(start)
    editor.handle_motion(end)
    editor.finish_stroke()
    editor.state["shape_filled"] = False
    editor.set_tool("brush")


def author_leaf(editor):
    """Paint one broad, notched floating leaf without a petiole."""

    editor.state["canvas_rect"] = pygame.Rect(0, 0, 80, 80)
    paint_filled_circle(editor, (8, 8), (72, 72), (32, 91, 54))
    paint_filled_circle(editor, (12, 12), (68, 68), (58, 145, 82))
    # A water-lily leaf has a deep radial notch.  The petiole will be drawn by
    # the species grammar, so this eraser stroke only defines the blade shape.
    editor.set_tool("eraser")
    editor.set_brush_size(7)
    editor.handle_click((40, 70))
    for point in ((40, 63), (40, 56), (40, 49)):
        editor.handle_motion(point)
    editor.finish_stroke()
    editor.set_tool("brush")
    paint_stroke(editor, [(40, 49), (40, 34), (40, 20)], (144, 202, 113), 1)
    paint_stroke(editor, [(40, 49), (26, 37), (17, 25)], (125, 190, 101), 1)
    paint_stroke(editor, [(40, 49), (54, 37), (63, 25)], (125, 190, 101), 1)


def author_flower(editor):
    """Paint a single white radial flower with a yellow centre."""

    editor.state["canvas_rect"] = pygame.Rect(0, 0, 80, 80)
    center = (40, 39)
    for end in ((40, 13), (55, 18), (66, 31), (63, 47), (52, 58), (40, 64), (28, 58), (17, 47), (14, 31), (25, 18)):
        paint_stroke(editor, [center, end], (234, 242, 224), 6)
    paint_filled_circle(editor, (32, 31), (48, 47), (226, 190, 66))
    paint_filled_circle(editor, (36, 35), (44, 43), (158, 112, 35))


def author_illustration(host, illustration_id, metric_size, painter):
    controller = PixelArtEditorUI(host)
    if not controller.open(illustration_id):
        raise RuntimeError(f"Could not open pixel editor for {illustration_id}")
    controller.state["metric_size_buffer"] = str(metric_size)
    controller.state["illustration"]["pixel_document_path"] = ""
    controller.state["illustration"]["media_path"] = ""
    host.canvas_size_override = (80, 80)
    if not controller.begin_canvas():
        raise RuntimeError(f"Could not create pixel canvas for {illustration_id}")
    host.canvas_size_override = None
    painter(controller)
    # These two marks are the same editor actions a human would use: first the
    # socket where the petiole/peduncle connects, then the authored growth axis.
    controller.set_anchor_mode("attachment")
    controller.set_attachment_point((40, 68 if illustration_id == LEAF_ID else 67))
    controller.set_anchor_mode("axis")
    controller.set_growth_axis((40, 18))
    if not controller.save():
        raise RuntimeError(f"Could not save pixel art for {illustration_id}: {controller.state.get('status')}")
    return host.loader.entities[illustration_id]


def main():
    pygame.init()
    pygame.font.init()
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )

    species = upsert(loader, {
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "European White Water Lily - Nymphaea alba",
        "pretty_name": "European White Water Lily - Nymphaea alba",
        "binomial_name": "Nymphaea alba",
        "species_class": "natural_plant",
        "parents": [GENUS_ID],
        "plant_growth_form": "aquatic",
        "plant_growth_behaviour": "determinate_sympodial",
        "plant_lifespan": "perennial",
        "plant_life_form": "hydrophyte",
        "plant_woodiness": "herbaceous",
        "mature_height": {"min_m": 0.05, "max_m": 0.35},
        "mature_height_class": "low",
        "growth_rate": "moderate",
        "maturity_rate": "moderate",
        "longevity_class": "long",
        "leaf_phenology": "deciduous",
        "leaf_size_class": "very_large",
        "leaf_arrangement": "spiral",
        "leaf_attachment_pattern": "basal_rosette",
        "leaf_clustering": "rosette",
        "photosynthesis_pathway": "c3",
        "root_architecture": "adventitious",
        "root_depth_class": "shallow",
        "reproductive_mode": "both",
        "seed_size_class": "small",
        "clonal_spread": "high",
        "regeneration_strategy": "vegetative_recruitment",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "none",
        "shade_tolerance": "low",
        "moisture_preference": "aquatic",
        "waterlogging_tolerance": "high",
        "salinity_tolerance": "low",
        "wiki_entry": (
            "# European white water lily\n\n"
            "*Nymphaea alba* is a deciduous aquatic perennial. A horizontal "
            "rhizome is rooted in mud while long petioles carry rounded, deeply "
            "notched leaves at the water surface; bowl-shaped white flowers are "
            "held at or just above the surface.\n\n"
            "Research: [RHS species profile](https://www.rhs.org.uk/plants/11623/nymphaea-alba-%28h%29/details), "
            "[NParks profile](https://www.nparks.gov.sg/florafaunaweb/flora/2/2/2271), "
            "[NZ Flora taxon profile](https://www.nzflora.info/factsheet/Taxon/Nymphaea-alba.html), "
            "[Kew POWO genus account](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A330032-2/general-information)."
        ),
    })
    upsert(loader, {
        "id": LEAF_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "European White Water Lily Leaf Module",
        "pretty_name": "European White Water Lily Leaf Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.42,
        "plant_module_kind": "leaf",
    })
    upsert(loader, {
        "id": FLOWER_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "European White Water Lily Flower Module",
        "pretty_name": "European White Water Lily Flower Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.28,
        "plant_module_kind": "flower",
    })

    host = PixelEditorHost(loader)
    leaf = author_illustration(host, LEAF_ID, 0.42, author_leaf)
    flower = author_illustration(host, FLOWER_ID, 0.28, author_flower)
    species["plant_leaf_module_ref"] = leaf["media_path"]
    species["plant_flower_module_ref"] = flower["media_path"]
    species["plant_module_anchors"] = {
        "leaf": leaf.get("pixel_module_anchor"),
        "flower": flower.get("pixel_module_anchor"),
    }
    upsert(loader, species)

    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    blueprint = PlantBlueprint.from_species_entity(species, SPECIES_ID)
    simulation = SpeciesSimulation(species_entity=species, seed=202, asset_store=asset_store, blueprint=blueprint)
    simulation.set_age(0)
    environment = {
        "water_available": 0.96,
        "light": 0.78,
        "temperature": 0.72,
        "substrate": "mud",
    }
    telemetry = simulation.simulate_days(5, environment=environment, sample_every_days=1)
    blueprint_path = simulation.bake_snapshot(asset_store)
    telemetry_path = PROJECT_ROOT / "assets" / "plants" / "telemetry" / f"{SPECIES_ID}_5day.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(json.dumps({
        "species_id": SPECIES_ID,
        "simulation": "species",
        "seed": simulation.seed,
        "days": 5,
        "environment": environment,
        "samples": telemetry,
    }, indent=2) + "\n", encoding="utf-8")
    print({
        "species_id": SPECIES_ID,
        "parent_genus": GENUS_ID,
        "leaf_asset": leaf["media_path"],
        "flower_asset": flower["media_path"],
        "blueprint": blueprint_path,
        "telemetry": telemetry,
    })


if __name__ == "__main__":
    main()
