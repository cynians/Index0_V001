"""Author the first researched modular plant representative.

This uses the same PixelArtEditorUI controller as the desktop flow, but drives
it headlessly so a remote session can still create real illustration assets.
The ontology remains the authority for the clade, species, and illustration
entities; PNGs and layer documents are stored in the normal asset locations.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from ui.pixel_art_editor_ui import PixelArtEditorUI
from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIES_ID = "spec_lolium_perenne"
GENUS_ID = "cladis_lolium"
LEAF_ID = "idea_lolium_perenne_leaf_pixel"
FLOWER_ID = "idea_lolium_perenne_inflorescence_pixel"


class PixelEditorHost:
    """Small host adapter exposing the real pixel editor persistence flow."""

    LINE_HEIGHT = 18

    def __init__(self, loader):
        self.loader = loader
        self.world_model = SimpleNamespace(
            loader=loader,
            get_entity=lambda entity_id: loader.entities.get(entity_id),
        )
        self.PROJECT_ROOT = PROJECT_ROOT
        self.pixel_art_editor = None
        self.pixel_art_painting = False
        self.layout = {}
        self.canvas_size_override = None

    @staticmethod
    def _sanitize_entity_id(entity_id):
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", str(entity_id or "")).strip("._-")

    def _ellipsize_text(self, text, font, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        while text and font.size(text + "...")[0] > max_width:
            text = text[:-1]
        return text + "..."

    def _pixel_canvas_size_for_entity(self, _entity, _metric_size_m):
        return self.canvas_size_override or (50, 50)

    def _parent_entity_for_illustration(self, illustration):
        for parent_id in illustration.get("parents") or []:
            parent = self.loader.entities.get(parent_id)
            if isinstance(parent, dict):
                return parent
        return None

    def assign_illustration_image(self, illustration_id, image_path):
        illustration = self.loader.entities.get(illustration_id)
        if not isinstance(illustration, dict):
            return False
        illustration["media_path"] = image_path
        return self.loader.persist_entity(illustration)


def upsert(loader, candidate):
    entity_id = candidate["id"]
    entity = loader.entities.get(entity_id)
    if isinstance(entity, dict):
        entity.update(candidate)
    else:
        entity = dict(candidate)
    if not loader.persist_entity(entity):
        raise RuntimeError(f"Could not persist {entity_id}")
    return entity


def paint_stroke(editor, points, color, brush_size=1):
    editor.set_color_rgb(color)
    editor.set_brush_size(brush_size)
    editor.handle_click(points[0])
    for point in points[1:]:
        editor.handle_motion(point)
    editor.finish_stroke()


def paint_filled_triangle(editor, start, end, color):
    """Use the editor's filled shape tool for a clean pointed silhouette."""

    editor.set_color_rgb(color)
    editor.set_tool("triangle")
    editor.state["shape_filled"] = True
    editor.handle_click(start)
    editor.handle_motion(end)
    editor.finish_stroke()
    editor.state["shape_filled"] = False
    editor.set_tool("brush")


def author_leaf(editor):
    """Paint one flat, pointed ryegrass blade—no stem, branch, or paired leaf."""

    width = int(editor.state.get("canvas_width") or 20)
    height = int(editor.state.get("canvas_height") or 80)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    # Broad sheath end at the attachment point, tapering to a single tip.
    base = (width // 2, height - 8)
    tip = (width // 2 - 1, 7)
    paint_filled_triangle(editor, (width // 2 - 3, tip[1]), (width // 2 + 3, base[1]), (35, 91, 46))
    paint_filled_triangle(editor, (width // 2 - 2, tip[1] + 1), (width // 2 + 2, base[1] - 1), (67, 143, 63))
    # One offset sheen gives the blade a flat, slightly folded surface without
    # introducing a second stalk-like line through its center.
    paint_stroke(editor, [(width // 2 + 1, height - 15), (width // 2, height - 28), (width // 2, height - 41), (width // 2 - 1, height - 54)], (143, 196, 84), 1)


def author_inflorescence(editor):
    """Paint a ryegrass culm with an alternating compact spike."""

    editor.state["canvas_rect"] = pygame.Rect(0, 0, 50, 50)
    paint_stroke(editor, [(25, 45), (25, 9)], (39, 96, 46), 2)
    for index, y in enumerate(range(12, 34, 4)):
        side = -1 if index % 2 == 0 else 1
        x = 25 + side * 4
        paint_stroke(editor, [(25, y), (x, y - 1)], (171, 139, 48), 2)
        paint_stroke(editor, [(x, y - 2), (x + side * 2, y), (x, y + 2)], (216, 185, 76), 2)
    paint_stroke(editor, [(25, 8), (25, 5)], (178, 145, 51), 1)


def author_illustration(host, illustration_id, metric_size, painter, canvas_size=None):
    controller = PixelArtEditorUI(host)
    if not controller.open(illustration_id):
        raise RuntimeError(f"Could not open pixel editor for {illustration_id}")
    controller.state["metric_size_buffer"] = str(metric_size)
    if canvas_size:
        # Re-author this module at its new long-sprite aspect instead of
        # restoring the previous square document.
        controller.state["illustration"]["pixel_document_path"] = ""
        controller.state["illustration"]["media_path"] = ""
    host.canvas_size_override = canvas_size
    if not controller.begin_canvas():
        raise RuntimeError(f"Could not create pixel canvas for {illustration_id}")
    host.canvas_size_override = None
    painter(controller)
    # The attachment is authored as a point on the reusable module, not baked
    # into the pixels. This is the same action exposed by the Anchor tool.
    controller.set_anchor_mode("attachment")
    base = (int(controller.state.get("canvas_width") or 1) // 2, int(controller.state.get("canvas_height") or 1) - 8)
    controller.set_attachment_point(base)
    controller.set_anchor_mode("axis")
    tip = (base[0] - 1, 7)
    controller.set_growth_axis(tip)
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
        "id": GENUS_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Lolium",
        "pretty_name": "Lolium",
        "parents": ["cladis_true_grasses_poaceae"],
    })
    species = upsert(loader, {
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "Perennial Ryegrass - Lolium perenne",
        "pretty_name": "Perennial Ryegrass - Lolium perenne",
        "binomial_name": "Lolium perenne",
        "species_class": "natural_plant",
        "parents": [GENUS_ID],
        "plant_growth_form": "graminoid",
        "plant_growth_behaviour": "tussock_tillering",
        "plant_lifespan": "short_lived_perennial",
        "plant_life_form": "hemicryptophyte",
        "plant_woodiness": "herbaceous",
        "mature_height": {"min_m": 0.25, "max_m": 0.9},
        "mature_height_class": "low",
        "growth_rate": "fast",
        "maturity_rate": "fast",
        "longevity_class": "short",
        "leaf_phenology": "evergreen",
        "leaf_size_class": "small",
        "leaf_arrangement": "distichous",
        "leaf_attachment_pattern": "basal",
        "leaf_clustering": "tufted",
        "photosynthesis_pathway": "c3",
        "root_architecture": "fibrous",
        "root_depth_class": "shallow",
        "reproductive_mode": "sexual",
        "seed_size_class": "tiny",
        "clonal_spread": "low",
        "regeneration_strategy": "mixed",
        "resprouting": "strong",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "arbuscular",
        "shade_tolerance": "low",
        "moisture_preference": "moist",
        "waterlogging_tolerance": "medium",
        "salinity_tolerance": "low",
        "wiki_entry": (
            "# Perennial ryegrass\\n\\n"
            "*Lolium perenne* is a cool-season grass of Poaceae. It forms a "
            "bunchy tuft of narrow basal leaves with erect, nearly naked culms "
            "and a compact spike inflorescence. The species is generally "
            "short-lived as a perennial, so this representative uses repeated "
            "tillering with a finite adult lifespan.\\n\\n"
            "Research: [Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A407493-1), "
            "[USDA plant fact sheet](https://plants.usda.gov/DocumentLibrary/factsheet/pdf/fs_lope.pdf), "
            "[USDA Forest Service FEIS](https://research.fs.usda.gov/feis/species-reviews/lolperp)."
        ),
    })
    upsert(loader, {
        "id": LEAF_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "Perennial Ryegrass Leaf Module",
        "pretty_name": "Perennial Ryegrass Leaf Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.35,
        "plant_module_kind": "leaf",
    })
    upsert(loader, {
        "id": FLOWER_ID,
        "_dataset": "ideas",
        "type": "idea",
        "idea_class": "illustration",
        "name": "Perennial Ryegrass Inflorescence Module",
        "pretty_name": "Perennial Ryegrass Inflorescence Module",
        "parents": [SPECIES_ID],
        "depicted_size_m": 0.22,
        "plant_module_kind": "flower",
    })

    host = PixelEditorHost(loader)
    leaf = author_illustration(host, LEAF_ID, 0.35, author_leaf, canvas_size=(20, 80))
    flower = author_illustration(host, FLOWER_ID, 0.22, author_inflorescence)
    species["plant_leaf_module_ref"] = leaf["media_path"]
    species["plant_flower_module_ref"] = flower["media_path"]
    species["plant_module_anchors"] = {
        "leaf": leaf.get("pixel_module_anchor") or {"attachment_point": [0.5, 0.9], "growth_axis": [0.0, -1.0]},
        "flower": flower.get("pixel_module_anchor") or {"attachment_point": [0.5, 0.9], "growth_axis": [0.0, -1.0]},
    }
    upsert(loader, species)
    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    # Rebuild from the freshly authored ontology row so this authoring pass
    # cannot reuse a stale pre-anchor blueprint cache.
    blueprint = PlantBlueprint.from_species_entity(species, SPECIES_ID)
    simulation = SpeciesSimulation(
        species_entity=species,
        seed=101,
        asset_store=asset_store,
        blueprint=blueprint,
    )
    simulation.set_age(0)
    telemetry = simulation.simulate_days(5, sample_every_days=1)
    blueprint_path = simulation.bake_snapshot(asset_store)
    telemetry_path = PROJECT_ROOT / "assets" / "plants" / "telemetry" / f"{SPECIES_ID}_5day.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(
        json.dumps(
            {
                "species_id": SPECIES_ID,
                "simulation": "species",
                "seed": simulation.seed,
                "days": 5,
                "environment": {},
                "samples": telemetry,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print({
        "species_id": SPECIES_ID,
        "genus_id": GENUS_ID,
        "leaf_asset": leaf["media_path"],
        "flower_asset": flower["media_path"],
        "leaf_document": leaf["pixel_document_path"],
        "flower_document": flower["pixel_document_path"],
        "blueprint": blueprint_path,
        "telemetry": telemetry,
    })


if __name__ == "__main__":
    main()
