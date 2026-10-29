"""Author Woods Rose modules through the shared Pixel Studio controller."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.entity_loader import EntityLoader


SPECIES_ID = "spec_rosa_woodsii"
LEAF_ID = "illust_rosa_woodsii_leaf_module"
STEM_ID = "illust_rosa_woodsii_stem_module"
BRANCH_ID = "illust_rosa_woodsii_branch_module"
FLOWER_ID = "illust_rosa_woodsii_flower_module"
FRUIT_ID = "illust_rosa_woodsii_hip_module"


class PixelEditorHost:
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
        return self.canvas_size_override or (64, 80)

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


def upsert(loader, entity):
    current = loader.entities.get(entity["id"])
    if isinstance(current, dict):
        current.update(entity)
        entity = current
    if not loader.persist_entity(entity):
        raise RuntimeError(f"Could not persist {entity['id']}")
    return entity


def stroke(editor, points, color, brush_size=1):
    editor.set_color_rgb(color)
    editor.set_brush_size(brush_size)
    editor.handle_click(points[0])
    for point in points[1:]:
        editor.handle_motion(point)
    editor.finish_stroke()


def paint_leaf(editor):
    """Paint one pinnately compound leaf, never a stem section."""
    width = int(editor.state.get("canvas_width") or 64)
    height = int(editor.state.get("canvas_height") or 80)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    rachis = (width // 2, height - 8)
    tip = (width // 2 + 2, 9)
    stroke(editor, [rachis, (width // 2, 50), (width // 2 + 1, 30), tip], (43, 93, 45), 3)
    # Paired lanceolate leaflets make the silhouette read as one compound
    # leaf. The central rachis is part of this leaf asset, not a stem asset.
    for index, (y, spread) in enumerate(((59, 11), (49, 14), (39, 14), (29, 11), (20, 7))):
        for side in (-1, 1):
            base_x = width // 2
            tip_x = base_x + side * spread
            tip_y = y - 8
            mid_x = base_x + side * round(spread * 0.58)
            mid_y = y - 3
            stroke(editor, [(base_x, y), (mid_x, mid_y), (tip_x, tip_y)], (52, 122, 54), 5)
            stroke(editor, [(base_x, y - 1), (mid_x, mid_y - 1), (tip_x, tip_y)], (113, 177, 76), 2)
    stroke(editor, [(width // 2, 17), (width // 2 + 2, 9)], (52, 122, 54), 3)


def paint_stem(editor):
    """Paint one narrow reddish-brown cane section."""
    width = int(editor.state.get("canvas_width") or 24)
    height = int(editor.state.get("canvas_height") or 48)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    center = width // 2
    stroke(editor, [(center, height - 4), (center - 1, 30), (center + 1, 16), (center, 4)], (102, 66, 47), 5)
    stroke(editor, [(center - 1, height - 5), (center, 31), (center + 1, 17), (center + 1, 5)], (166, 100, 60), 2)
    for y in (14, 28, 41):
        stroke(editor, [(center - 3, y), (center + 3, y + 1)], (73, 51, 42), 1)


def paint_branch(editor):
    """Paint one slightly curved, fine woody branch section."""
    width = int(editor.state.get("canvas_width") or 32)
    height = int(editor.state.get("canvas_height") or 44)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    stroke(editor, [(width // 2, height - 4), (width // 2 + 2, 31), (width // 2 - 2, 18), (width // 2 + 3, 4)], (101, 66, 47), 4)
    stroke(editor, [(width // 2 + 1, height - 5), (width // 2 + 3, 31), (width // 2 - 1, 18), (width // 2 + 3, 5)], (163, 97, 59), 1)


def paint_flower(editor):
    """Paint one simple five-petaled rose flower module."""
    width = int(editor.state.get("canvas_width") or 50)
    height = int(editor.state.get("canvas_height") or 50)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    center = (width // 2, height // 2)
    petals = ((0, -7), (7, -1), (4, 7), (-4, 7), (-7, -1))
    for dx, dy in petals:
        stroke(editor, [(center[0] + dx // 2, center[1] + dy // 2), (center[0] + dx, center[1] + dy)], (196, 104, 128), 5)
    stroke(editor, [(center[0] - 2, center[1]), (center[0] + 2, center[1])], (224, 181, 72), 3)


def paint_hip(editor):
    """Paint one persistent red-orange rose hip module."""
    width = int(editor.state.get("canvas_width") or 40)
    height = int(editor.state.get("canvas_height") or 40)
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    center = (width // 2, height // 2 + 3)
    stroke(editor, [(center[0], center[1] - 8), (center[0], center[1] - 13)], (66, 108, 46), 2)
    for offset in range(-7, 8, 2):
        stroke(editor, [(center[0] - 7, center[1] + offset // 2), (center[0] + 7, center[1] + offset // 2)], (184, 67, 45), 2)
    stroke(editor, [(center[0] - 4, center[1] - 6), (center[0] + 4, center[1] + 6)], (226, 112, 54), 1)


def author_module(host, illustration_id, metric_size, canvas_size, painter, anchor):
    controller = PixelArtEditorUI(host)
    if not controller.open(illustration_id):
        raise RuntimeError(f"Could not open Pixel Studio entry {illustration_id}")
    controller.state["metric_size_buffer"] = str(metric_size)
    controller.state["illustration"]["pixel_document_path"] = ""
    controller.state["illustration"]["media_path"] = ""
    host.canvas_size_override = canvas_size
    if not controller.begin_canvas():
        raise RuntimeError(f"Could not create canvas for {illustration_id}")
    host.canvas_size_override = None
    painter(controller)
    controller.set_anchor_mode("attachment")
    controller.set_attachment_point(anchor)
    controller.set_anchor_mode("axis")
    controller.set_growth_axis((anchor[0], max(1, anchor[1] - 30)))
    if not controller.save():
        raise RuntimeError(f"Could not save {illustration_id}: {controller.state.get('status')}")
    return host.loader.entities[illustration_id]


def main():
    pygame.init()
    pygame.font.init()
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    species = loader.entities.get(SPECIES_ID)
    if not isinstance(species, dict):
        raise RuntimeError(f"Missing existing plant card: {SPECIES_ID}")

    species.update(
        {
            "leaf_structure": "pinnately_compound",
            "leaf_arrangement": "alternate",
            "leaf_attachment_pattern": "along_stem",
            "leaf_clustering": "distributed",
            "leaf_phenology": "deciduous",
            "plant_woodiness": "woody",
            "plant_leaf_distribution": "along_shoot",
            "plant_leaf_spacing_bias": 0.58,
            "plant_leaf_cluster_density": 0.46,
            "plant_fine_twig_density": 0.52,
        }
    )
    upsert(loader, species)

    for entity_id, name, role, kind, size in (
        (LEAF_ID, "Woods Rose Leaf Module", "leaf", "leaf", 0.18),
        (STEM_ID, "Woods Rose Stem Module", "stem", "stem_section", 0.45),
        (BRANCH_ID, "Woods Rose Branch Module", "branch", "branch_section", 0.30),
        (FLOWER_ID, "Woods Rose Flower Module", "flower", "flower", 0.12),
        (FRUIT_ID, "Woods Rose Rose Hip Module", "fruit", "fruit", 0.10),
    ):
        upsert(loader, {
            "id": entity_id,
            "_dataset": "ideas",
            "type": "idea",
            "idea_class": "illustration",
            "name": name,
            "pretty_name": name,
            "parents": [SPECIES_ID],
            "plant_asset_role": role,
            "plant_asset_kind": kind,
            "plant_asset_target_field": f"plant_{role}_module_ref",
            "depicted_size_m": size,
            "media_path": "",
        })

    host = PixelEditorHost(loader)
    leaf = author_module(host, LEAF_ID, 0.18, (64, 80), paint_leaf, (32, 72))
    stem = author_module(host, STEM_ID, 0.45, (24, 48), paint_stem, (12, 43))
    branch = author_module(host, BRANCH_ID, 0.30, (32, 44), paint_branch, (16, 39))
    flower = author_module(host, FLOWER_ID, 0.12, (50, 50), paint_flower, (25, 40))
    hip = author_module(host, FRUIT_ID, 0.10, (40, 40), paint_hip, (20, 34))
    species["plant_leaf_module_ref"] = leaf["media_path"]
    species["plant_stem_module_ref"] = stem["media_path"]
    species["plant_branch_module_ref"] = branch["media_path"]
    species["plant_flower_module_ref"] = flower["media_path"]
    species["plant_fruit_module_ref"] = hip["media_path"]
    species["plant_module_anchors"] = {
        "leaf": leaf.get("pixel_module_anchor"),
        "stem": stem.get("pixel_module_anchor"),
        "branch": branch.get("pixel_module_anchor"),
        "flower": flower.get("pixel_module_anchor"),
        "fruit": hip.get("pixel_module_anchor"),
    }
    upsert(loader, species)
    print(json.dumps({
        "species_id": SPECIES_ID,
        "leaf_structure": species["leaf_structure"],
        "leaf_asset": leaf["media_path"],
        "stem_asset": stem["media_path"],
        "branch_asset": branch["media_path"],
        "flower_asset": flower["media_path"],
        "fruit_asset": hip["media_path"],
    }, indent=2))


if __name__ == "__main__":
    main()
