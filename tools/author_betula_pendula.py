"""Author the third researched plant representative: silver birch."""

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
SPECIES_ID = "spec_betula_pendula"
ORDER_ID = "cladis_fagales"
FAMILY_ID = "cladis_betulaceae"
GENUS_ID = "cladis_betula"
LEAF_ID = "idea_betula_pendula_leaf_pixel"
FLOWER_ID = "idea_betula_pendula_catkin_pixel"
BARK_ID = "idea_betula_pendula_bark_texture"


def author_leaf(editor):
    """Paint one simple diamond-shaped birch leaf and its midrib."""

    editor.state["canvas_rect"] = pygame.Rect(0, 0, 48, 64)
    paint_stroke(editor, [(24, 55), (24, 18)], (40, 101, 48), 13)
    paint_stroke(editor, [(24, 18), (24, 10)], (54, 130, 58), 3)
    paint_stroke(editor, [(24, 55), (24, 15)], (164, 199, 92), 1)
    for start, end in [
        ((24, 29), (15, 22)), ((24, 29), (33, 22)),
        ((24, 38), (14, 32)), ((24, 38), (34, 32)),
        ((24, 46), (16, 42)), ((24, 46), (32, 42)),
    ]:
        paint_stroke(editor, [start, end], (103, 169, 70), 1)
    # Small dark edge cuts suggest the toothed margin without turning the
    # reusable organ into a branch or petiole.
    for start, end in [
        ((17, 24), (12, 22)), ((31, 24), (36, 22)),
        ((14, 32), (9, 31)), ((34, 32), (39, 31)),
        ((16, 40), (11, 40)), ((32, 40), (37, 40)),
    ]:
        paint_stroke(editor, [start, end], (26, 77, 39), 1)


def author_catkin(editor):
    """Paint one hanging brown-gold catkin, separate from branch geometry."""

    editor.state["canvas_rect"] = pygame.Rect(0, 0, 48, 64)
    paint_stroke(editor, [(24, 9), (24, 17)], (94, 79, 48), 2)
    paint_stroke(editor, [(24, 17), (24, 53)], (175, 139, 49), 5)
    for y in range(21, 53, 6):
        paint_stroke(editor, [(20, y), (28, y)], (216, 180, 68), 2)


def author_bark_texture(editor):
    """Author a pale birch base tile plus sparse black-bark exceptions."""

    width, height = int(editor.state.get("canvas_width") or 24), int(editor.state.get("canvas_height") or 48)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    layer = editor.state["layers"][0]["pixels"]
    for y in range(height):
        for x in range(width):
            layer[y][x] = (218, 218, 198) if x % 7 else (194, 196, 176)
    for x, y in ((4, 6), (16, 17), (8, 31), (20, 40)):
        layer[y][x] = (52, 47, 40)
        if x + 1 < width:
            layer[y][x + 1] = (93, 79, 61)
    editor.state["texture_base_layers"] = editor._snapshot_layers(editor.state["layers"])
    for cell, marks in {
        (0, 1): ((5, 12), (6, 12), (5, 13)),
        (2, 1): ((17, 25), (18, 25), (18, 26), (19, 26)),
        (1, 2): ((10, 37), (11, 37), (10, 38), (14, 43)),
    }.items():
        editor._texture_load_cell(*cell)
        current = editor.state["layers"][0]["pixels"]
        for x, y in marks:
            current[y][x] = (42, 38, 34)
        editor._texture_store_current()
    editor._texture_load_cell(1, 1)


def author_illustration(host, illustration_id, metric_size, painter, canvas_size=(48, 64)):
    controller = PixelArtEditorUI(host)
    if not controller.open(illustration_id):
        raise RuntimeError(f"Could not open pixel editor for {illustration_id}")
    controller.state["metric_size_buffer"] = str(metric_size)
    controller.state["illustration"]["pixel_document_path"] = ""
    controller.state["illustration"]["media_path"] = ""
    host.canvas_size_override = canvas_size
    if not controller.begin_canvas():
        raise RuntimeError(f"Could not create pixel canvas for {illustration_id}")
    host.canvas_size_override = None
    painter(controller)
    controller.set_anchor_mode("attachment")
    controller.set_attachment_point((24, 55 if illustration_id == LEAF_ID else 9))
    controller.set_anchor_mode("axis")
    controller.set_growth_axis((24, 15 if illustration_id == LEAF_ID else 53))
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

    upsert(loader, {
        "id": ORDER_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Fagales",
        "pretty_name": "Fagales",
        "parents": ["cladis_fabids"],
    })
    upsert(loader, {
        "id": FAMILY_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Betulaceae",
        "pretty_name": "Betulaceae",
        "parents": [ORDER_ID],
    })
    upsert(loader, {
        "id": GENUS_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Betula",
        "pretty_name": "Betula",
        "parents": [FAMILY_ID],
    })
    species = upsert(loader, {
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "Silver Birch - Betula pendula",
        "pretty_name": "Silver Birch - Betula pendula",
        "binomial_name": "Betula pendula",
        "species_class": "natural_plant",
        "parents": [GENUS_ID],
        "plant_growth_form": "tree",
        "plant_growth_behaviour": "branched_woody",
        "plant_lifespan": "perennial",
        "plant_life_form": "phanerophyte",
        "plant_woodiness": "woody",
        "mature_height": {"min_m": 15.0, "max_m": 30.0},
        "mature_height_class": "tall",
        "growth_rate": "fast",
        "maturity_rate": "slow",
        "longevity_class": "moderate",
        "leaf_phenology": "deciduous",
        "leaf_size_class": "medium",
        "leaf_arrangement": "alternate",
        "leaf_attachment_pattern": "along_stem",
        "leaf_clustering": "distributed",
        "plant_shoot_dimorphism": "long_and_short_shoots",
        "plant_leaf_distribution": "mixed_long_short_shoots",
        # Calibrated 0..1 architectural proxies from the literature and
        # reference images; intermediate values remain valid for other taxa.
        "plant_leaf_spacing_bias": 0.72,
        "plant_branch_droop": 0.78,
        "plant_branch_angle_gradient": 0.66,
        "plant_crown_openness": 0.80,
        "plant_leaf_depth_gradient": 0.56,
        "plant_fine_twig_density": 0.82,
        "plant_leaf_cluster_density": 0.68,
        "photosynthesis_pathway": "c3",
        "root_architecture": "mixed",
        "root_depth_class": "intermediate",
        "reproductive_mode": "sexual",
        "seed_size_class": "tiny",
        "clonal_spread": "none",
        "regeneration_strategy": "gap_recruitment",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "ectomycorrhizal",
        "shade_tolerance": "low",
        "moisture_preference": "moist",
        "waterlogging_tolerance": "medium",
        "salinity_tolerance": "low",
        "wiki_entry": (
            "# Silver birch\n\n"
            "*Betula pendula* is a deciduous, light-demanding tree with a tall "
            "slender trunk, pale bark, pendulous young twigs, alternate toothed "
            "leaves, and wind-pollinated catkins. This representative uses a "
            "branched woody grammar with curved axes and a light, open crown.\n\n"
            "Research: [Kew plant profile](https://www.kew.org/plants/silver-birch), "
            "[Kew POWO species account](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A295174-1/general-information), "
            "[World Flora Online](https://www.worldfloraonline.org/taxon/wfo-0000335449)."
        ),
    })
    upsert(loader, {
        "id": LEAF_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "Silver Birch Leaf Module",
        "pretty_name": "Silver Birch Leaf Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.07,
        "plant_module_kind": "leaf",
    })
    upsert(loader, {
        "id": FLOWER_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "Silver Birch Catkin Module",
        "pretty_name": "Silver Birch Catkin Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.09,
        "plant_module_kind": "flower",
    })
    upsert(loader, {
        "id": BARK_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "Silver Birch Bark Texture Set",
        "pretty_name": "Silver Birch Bark Texture Set",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.06,
        "pixel_editor_mode": "texture",
        "plant_module_kind": "bark_texture",
    })

    host = PixelEditorHost(loader)
    leaf = author_illustration(host, LEAF_ID, 0.07, author_leaf)
    flower = author_illustration(host, FLOWER_ID, 0.09, author_catkin)
    bark = author_illustration(host, BARK_ID, 0.06, author_bark_texture, canvas_size=(24, 48))
    species["plant_leaf_module_ref"] = leaf["media_path"]
    species["plant_flower_module_ref"] = flower["media_path"]
    species["plant_bark_texture_set_ref"] = bark["pixel_document_path"]
    species["plant_module_anchors"] = {
        "leaf": leaf.get("pixel_module_anchor"),
        "flower": flower.get("pixel_module_anchor"),
    }
    upsert(loader, species)

    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    blueprint = PlantBlueprint.from_species_entity(species, SPECIES_ID)
    simulation = SpeciesSimulation(species_entity=species, seed=303, asset_store=asset_store, blueprint=blueprint)
    simulation.set_age(0)
    environment = {"light": 0.94, "temperature": 0.62, "water_available": 0.72, "competition": 0.1}
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
        "bark_texture": bark["pixel_document_path"],
        "blueprint": blueprint_path,
        "telemetry": telemetry,
    })


if __name__ == "__main__":
    main()
