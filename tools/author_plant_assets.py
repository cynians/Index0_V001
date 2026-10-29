"""Preview and author plant Pixel Studio modules from one reusable manifest.

The command has two modes:

* default: validate the manifest and write a preview-only review package under
  ``artifacts/<species_id>_asset_preview``;
* ``--apply``: persist the inspected modules through Pixel Studio and wire the
  owning species.

Species-specific visual decisions live in JSON manifests, not Python scripts.
The same declarative pixel operations therefore produce the reviewed preview
and the production Pixel Studio document without a hand-redraw.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import textwrap
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.species.species_renderer import (
    DiagnosticCamera,
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    top_down_diagnostic_bounds,
    canopy_visible_indices,
)
from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION, SpeciesSimulation
from ui.knowledge_browser_ui import KnowledgeBrowserUI
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.entity_loader import EntityLoader
from world.world_model import WorldModel


from world.fungal_traits import FUNGAL_ASSET_FIELDS
ROLES = {"leaf", "stem", "branch", "root", "flower", "calyx", "fruit", "strobilus", *FUNGAL_ASSET_FIELDS}
STRUCTURAL_ROLES = {"stem", "branch", "root"}
OP_TYPES = {"line", "polygon", "circle", "radial_lines", "scale_bands", "ligulate_rays"}


def asset_field(role):
    return FUNGAL_ASSET_FIELDS.get(role, f"plant_{role}_module_ref")


def anchor_field(role):
    return "fungal_module_anchors" if role in FUNGAL_ASSET_FIELDS else "plant_module_anchors"


def _wire_module(entity, anchors, module, path, payload):
    """Wire a base unit or one named fungal view without replacing its base."""
    role = module["role"]
    variant = module.get("variant_key")
    if variant:
        anchors.setdefault(role, {}).setdefault("variants", {})[variant] = {**payload, "asset_ref": path}
    else:
        entity[asset_field(role)] = path
        if role not in STRUCTURAL_ROLES:
            variants = deepcopy((anchors.get(role) or {}).get("variants"))
            anchors[role] = payload
            if variants:
                anchors[role]["variants"] = variants


class ManifestError(ValueError):
    """Raised when a plant-asset manifest cannot be authored safely."""


class PixelEditorHost:
    """Small headless host implementing PixelArtEditorUI's save contract."""

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

    def _pixel_canvas_size_for_entity(self, entity, metric_size_m):
        return self.canvas_size_override or KnowledgeBrowserUI._pixel_canvas_size_for_entity(
            None, entity, float(metric_size_m)
        )

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


def _upsert(loader, entity):
    current = loader.entities.get(entity["id"])
    if isinstance(current, dict):
        current.update(entity)
        entity = current
    if not loader.persist_entity(entity):
        raise RuntimeError(f"Could not persist {entity['id']}")
    return entity


def canvas_size(metric_size_m: float) -> tuple[int, int]:
    """Use the live app formula; manifests never choose production canvases."""

    return KnowledgeBrowserUI._pixel_canvas_size_for_entity(
        None, {"type": "idea"}, float(metric_size_m)
    )


def load_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Could not read {path}: {exc}") from exc
    validate_manifest(payload)
    payload["_manifest_path"] = str(path.resolve())
    return payload


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ManifestError(f"{label} must be a finite number")
    if positive and float(value) <= 0:
        raise ManifestError(f"{label} must be greater than zero")
    return float(value)


def _point(value, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ManifestError(f"{label} must be [x, y]")
    return [_number(value[0], f"{label}[0]"), _number(value[1], f"{label}[1]")]


def _color(value, label):
    if not isinstance(value, list) or len(value) not in {3, 4}:
        raise ManifestError(f"{label} must be [r, g, b] or [r, g, b, a]")
    result = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise ManifestError(f"{label} channels must be integers from 0 to 255")
        result.append(channel)
    return result


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise ManifestError("Manifest root must be an object")
    if manifest.get("version") != 1:
        raise ManifestError("Manifest version must be 1")
    species_id = str(manifest.get("species_id") or "").strip()
    if not species_id.startswith("spec_"):
        raise ManifestError("species_id must be an existing spec_* ID")
    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ManifestError("modules must be a non-empty list")
    fungal_flags = [m.get("role") in FUNGAL_ASSET_FIELDS for m in modules if isinstance(m,dict)]
    if any(fungal_flags) and not all(fungal_flags):
        raise ManifestError("Fungal and vascular asset roles need separate manifests")
    seen_roles = set()
    seen_ids = set()
    for index, module in enumerate(modules):
        label = f"modules[{index}]"
        if not isinstance(module, dict):
            raise ManifestError(f"{label} must be an object")
        role = str(module.get("role") or "")
        if 'cap_join_fraction' in module:
            join = _number(module['cap_join_fraction'], 'cap_join_fraction')
            if role != 'fruiting_body' or not .05 <= join <= .95:
                raise ManifestError('cap_join_fraction requires a fruiting_body fraction in .05..95')
        if role not in ROLES:
            raise ManifestError(f"{label}.role must be one of {sorted(ROLES)}")
        variant = module.get("variant_key")
        if variant is not None and (role not in {*FUNGAL_ASSET_FIELDS, 'leaf'} or not isinstance(variant, str)
                                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", variant)):
            raise ManifestError("variant_key requires a named fungal or leaf module variant")
        if (role, variant) in seen_roles:
            raise ManifestError(f"Duplicate module role/variant: {role}/{variant}")
        seen_roles.add((role, variant))
        if module.get("visual_unit") not in {None, "pinnule", "leaflet", "spine_cluster"}:
            raise ManifestError(f"{label}.visual_unit must be pinnule, leaflet, spine_cluster or omitted")
        if module.get("visual_unit") and role != "leaf":
            raise ManifestError(f"{label}: compound units are only valid for leaf modules")
        illustration_id = str(module.get("illustration_id") or "")
        if not illustration_id.startswith("illust_") or illustration_id in seen_ids:
            raise ManifestError(f"{label}.illustration_id must be a unique illust_* ID")
        seen_ids.add(illustration_id)
        if not str(module.get("name") or "").strip():
            raise ManifestError(f"{label}.name is required")
        _number(module.get("depicted_size_m"), f"{label}.depicted_size_m", positive=True)
        design_size = module.get("design_size")
        if not isinstance(design_size, list) or len(design_size) != 2:
            raise ManifestError(f"{label}.design_size must be [width, height]")
        for axis, value in zip(("width", "height"), design_size):
            if isinstance(value, bool) or not isinstance(value, int) or value < 8:
                raise ManifestError(f"{label}.design_size {axis} must be an integer >= 8")
        anchor = module.get("anchor")
        if not isinstance(anchor, dict):
            raise ManifestError(f"{label}.anchor is required")
        for key in ("attachment", "tip"):
            point = _point(anchor.get(key), f"{label}.anchor.{key}")
            if any(value < 0 or value > 1 for value in point):
                raise ManifestError(f"{label}.anchor.{key} must use normalized 0..1 coordinates")
        operations = module.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ManifestError(f"{label}.operations must be a non-empty list")
        for op_index, operation in enumerate(operations):
            op_label = f"{label}.operations[{op_index}]"
            if not isinstance(operation, dict) or operation.get("op") not in OP_TYPES:
                raise ManifestError(f"{op_label}.op must be one of {sorted(OP_TYPES)}")
            op_type = operation["op"]
            _color(operation.get("color"), f"{op_label}.color")
            if op_type in {"line", "polygon"}:
                points = operation.get("points")
                minimum = 2 if op_type == "line" else 3
                if not isinstance(points, list) or len(points) < minimum:
                    raise ManifestError(f"{op_label}.points needs at least {minimum} points")
                for point_index, point in enumerate(points):
                    _point(point, f"{op_label}.points[{point_index}]")
            elif op_type == "circle":
                _point(operation.get("center"), f"{op_label}.center")
                _number(operation.get("radius"), f"{op_label}.radius", positive=True)
            elif op_type in {"radial_lines", "ligulate_rays"}:
                _point(operation.get("center"), f"{op_label}.center")
                _number(operation.get("inner_radius"), f"{op_label}.inner_radius", positive=True)
                _number(operation.get("outer_radius"), f"{op_label}.outer_radius", positive=True)
                count = operation.get("count")
                if isinstance(count, bool) or not isinstance(count, int) or count < 2:
                    raise ManifestError(f"{op_label}.count must be an integer >= 2")
                if "accent_color" in operation:
                    _color(operation["accent_color"], f"{op_label}.accent_color")
                if op_type == "ligulate_rays":
                    if not 3 <= count <= 48 or operation["outer_radius"] <= operation["inner_radius"]:
                        raise ManifestError(f"{op_label}: ligulate rays need 3–48 rays and ordered radii")
                    _number(operation.get("ray_width"), f"{op_label}.ray_width", positive=True)
                    if operation["ray_width"] > operation["outer_radius"] or operation["outer_radius"] > max(design_size)*2:
                        raise ManifestError(f"{op_label}: ligulate ray dimensions exceed the design envelope")
            elif op_type == "scale_bands":
                _point(operation.get("center"), f"{op_label}.center")
                radii = operation.get("radii")
                if not isinstance(radii, list) or not 1 <= len(radii) <= 12:
                    raise ManifestError(f"{op_label}.radii must contain 1–12 radii")
                for radius in radii: _number(radius, f"{op_label}.radius", positive=True)
                _number(operation.get("y_scale", 1), f"{op_label}.y_scale", positive=True)
                _number(operation.get("scale_size", 2), f"{op_label}.scale_size", positive=True)
                _number(operation.get("spacing_factor", 3.6), f"{op_label}.spacing_factor", positive=True)
                for key, default in (("start_deg", 0), ("end_deg", 360)):
                    _number(operation.get(key, default), f"{op_label}.{key}")
    for role, variant in seen_roles:
        if role in FUNGAL_ASSET_FIELDS and variant is not None and ((role, None) not in seen_roles or
                                     any((view, variant) not in seen_roles for view in FUNGAL_ASSET_FIELDS)):
            raise ManifestError("Fungal variants require base modules and paired side/top views")
    if len(seen_roles) > 18:
        raise ManifestError("At most eight paired fungal variants plus base views are supported")
    updates = manifest.get("species_field_updates", {})
    if not isinstance(updates, dict):
        raise ManifestError("species_field_updates must be an object")
    config = manifest.get("preview") or {}
    if not isinstance(config, dict):
        raise ManifestError("preview must be an object")
    if "age_days" in config and _number(config["age_days"],"preview age_days") < 0:
        raise ManifestError("Preview age_days must be nonnegative")
    stages = config.get("stages") or []
    if not isinstance(stages,list) or len(stages)>8:
        raise ManifestError("preview.stages must be a list of at most 8 stages")
    for stage in stages:
        if not isinstance(stage,dict) or not str(stage.get("label") or "").strip():
            raise ManifestError("Each preview stage needs a label")
        if _number(stage.get("age_days"),"preview stage age_days") < 0:
            raise ManifestError("Preview stage age_days must be nonnegative")


def _scaled_point(point, source_size, target_size):
    sx = (target_size[0] - 1) / max(1, source_size[0] - 1)
    sy = (target_size[1] - 1) / max(1, source_size[1] - 1)
    return round(float(point[0]) * sx), round(float(point[1]) * sy)


def _scaled_radius(radius, source_size, target_size):
    scale = min(
        (target_size[0] - 1) / max(1, source_size[0] - 1),
        (target_size[1] - 1) / max(1, source_size[1] - 1),
    )
    return max(1, round(float(radius) * scale))


def render_module(module: dict) -> pygame.Surface:
    """Render one validated declarative module at its live canvas size."""

    target_size = canvas_size(module["depicted_size_m"])
    source_size = tuple(module["design_size"])
    surface = pygame.Surface(target_size, pygame.SRCALPHA)
    for operation in module["operations"]:
        op_type = operation["op"]
        color = tuple(operation["color"])
        width = _scaled_radius(operation.get("width", 1), source_size, target_size)
        if op_type == "line":
            points = [_scaled_point(point, source_size, target_size) for point in operation["points"]]
            pygame.draw.lines(surface, color, bool(operation.get("closed")), points, width)
        elif op_type == "polygon":
            points = [_scaled_point(point, source_size, target_size) for point in operation["points"]]
            pygame.draw.polygon(surface, color, points, 0 if operation.get("filled", True) else width)
        elif op_type == "circle":
            center = _scaled_point(operation["center"], source_size, target_size)
            radius = _scaled_radius(operation["radius"], source_size, target_size)
            pygame.draw.circle(surface, color, center, radius, 0 if operation.get("filled", True) else width)
        elif op_type == "ligulate_rays":
            cx, cy = operation["center"]
            inner, outer = operation["inner_radius"], operation["outer_radius"]
            half = operation["ray_width"] * .5
            # Strap-shaped ray florets with five toothed ends, not a daisy's
            # oval petals. Centre/stamens are separate drawing operations.
            unit = [(inner,-half*.14),(outer-3,-half)]
            unit += [(outer-(1.2 if i%2 else 0),-half+2*half*i/8) for i in range(9)]
            unit += [(outer-3,half),(inner,half*.14)]
            for ray in range(operation["count"]):
                theta = ray*math.tau/operation["count"] - math.pi*.5
                cs, sn = math.cos(theta), math.sin(theta)
                points = [(cx+x*cs-y*sn, cy+x*sn+y*cs) for x,y in unit]
                tone = operation.get("accent_color",operation["color"]) if ray%3==0 else operation["color"]
                pygame.draw.polygon(surface, tuple(tone), [_scaled_point(p,source_size,target_size) for p in points])
                a=(cx+(inner+3)*cs, cy+(inner+3)*sn)
                b=(cx+(outer-4)*cs, cy+(outer-4)*sn)
                vein=tuple(max(0,c-14) for c in tone[:3])
                pygame.draw.line(surface,vein,_scaled_point(a,source_size,target_size),_scaled_point(b,source_size,target_size),1)
        elif op_type == "radial_lines":
            center = _scaled_point(operation["center"], source_size, target_size)
            inner = _scaled_radius(operation["inner_radius"], source_size, target_size)
            outer = _scaled_radius(operation["outer_radius"], source_size, target_size)
            count = operation["count"]
            accent_every = max(0, int(operation.get("accent_every", 0)))
            accent = tuple(operation.get("accent_color", operation["color"]))
            for ray in range(count):
                angle = math.tau * ray / count
                start = (round(center[0] + inner * math.cos(angle)), round(center[1] + inner * math.sin(angle)))
                end = (round(center[0] + outer * math.cos(angle)), round(center[1] + outer * math.sin(angle)))
                ray_color = accent if accent_every and ray % accent_every == 0 else color
                pygame.draw.line(surface, ray_color, start, end, width)
        elif op_type == "scale_bands":
            layer = pygame.Surface(target_size, pygame.SRCALPHA)
            cx, cy = operation["center"]
            ys = float(operation.get("y_scale", 1))
            begin, end = (math.radians(float(operation.get(k, default))) for k, default in (("start_deg", 0), ("end_deg", 360)))
            for band, radius in enumerate(operation["radii"]):
                count = max(3, min(96, round(float(radius) * abs(end-begin) / max(2, float(operation.get("scale_size", 2))*float(operation.get("spacing_factor",3.6))))))
                for i in range(count):
                    theta = begin + (end-begin)*(i+.5*(band%2))/count
                    jitter=.45*math.sin(i*2.3+band*1.7)
                    x, y = cx+(radius+jitter)*math.cos(theta), cy+(radius+jitter)*ys*math.sin(theta)
                    unit = float(operation.get("scale_size", 2))
                    points = [(x-unit,y-unit*.35),(x+unit,y-unit*.35),(x+unit*.45,y+unit*.7),(x-unit*.45,y+unit*.7)]
                    pygame.draw.polygon(layer, color, [_scaled_point(p,source_size,target_size) for p in points])
            # Textural marks stay inside the already painted silhouette.
            mask = pygame.mask.from_surface(surface).to_surface(setcolor=(255,255,255,255),unsetcolor=(0,0,0,0))
            layer.blit(mask,(0,0),special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(layer,(0,0))
    return surface


def _anchor_pixels(module, size):
    attachment = module["anchor"]["attachment"]
    tip = module["anchor"]["tip"]
    return (
        (round(attachment[0] * (size[0] - 1)), round(attachment[1] * (size[1] - 1))),
        (round(tip[0] * (size[0] - 1)), round(tip[1] * (size[1] - 1))),
    )


def _anchor_payload(module):
    attachment = [round(float(value), 4) for value in module["anchor"]["attachment"]]
    tip = module["anchor"]["tip"]
    dx, dy = float(tip[0]) - attachment[0], float(tip[1]) - attachment[1]
    length = max(1e-9, math.hypot(dx, dy))
    vector = [round(dx / length, 4), round(dy / length, 4)]
    return {
        "attachment_point": attachment,
        "growth_axis": vector,
        "growth_vector": vector,
        "depicted_size_m": float(module["depicted_size_m"]),
        **({'cap_join_fraction': module['cap_join_fraction']} if 'cap_join_fraction' in module else {}),
        **({"visual_unit": module["visual_unit"]} if module.get("visual_unit") else {}),
    }


def _text(surface, font, value, position, color=(220, 232, 214)):
    surface.blit(font.render(str(value), True, color), position)


def _preview_directory(manifest, override=None):
    if override:
        return override.resolve()
    configured = manifest.get("preview", {}).get("output_dir")
    if configured:
        return (PROJECT_ROOT / configured).resolve()
    return PROJECT_ROOT / "artifacts" / f"{manifest['species_id']}_asset_preview"


def _render_design_board(manifest, rendered, output_dir, *, preview_only=True):
    columns = min(2, len(rendered))
    rows = math.ceil(len(rendered) / columns)
    panel_width, panel_height = 820, 580
    board = pygame.Surface((columns * panel_width + 40, rows * panel_height + 110))
    board.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 25)
    body = pygame.font.SysFont("consolas", 17)
    small = pygame.font.SysFont("consolas", 14)
    status = "PREVIEW ONLY" if preview_only else "SAVED PIXEL STUDIO ASSETS"
    _text(board, title, f"{status} | {manifest.get('display_name', manifest['species_id'])}", (20, 18))
    _text(board, body, "live canvas formula | manifest-driven | " + ("no ontology writes" if preview_only else "verified production pixels"), (20, 53), (165, 190, 156))
    for index, (module, sprite, _path) in enumerate(rendered):
        row, column = divmod(index, columns)
        x, y = 20 + column * panel_width, 90 + row * panel_height
        pygame.draw.rect(board, (29, 43, 35), (x, y, panel_width - 24, panel_height - 20), border_radius=5)
        pygame.draw.rect(board, (79, 107, 80), (x, y, panel_width - 24, panel_height - 20), 1, border_radius=5)
        _text(board, title, module["role"].upper(), (x + 18, y + 15))
        board.blit(sprite, (x + 25, y + 78))
        zoom_size = min(360, panel_height - 150)
        zoomed = pygame.transform.scale(sprite, (zoom_size, zoom_size))
        board.blit(zoomed, (x + 175, y + 65))
        _text(board, small, f"native {sprite.get_width()}x{sprite.get_height()}", (x + 20, y + 166), (155, 180, 150))
        _text(board, body, f"depicted size: {module['depicted_size_m']:.3f} m", (x + 20, y + 440))
        description_lines = textwrap.wrap(str(module.get("description", module["name"])), width=82)[:2]
        for line_index, line in enumerate(description_lines):
            _text(board, small, line, (x + 20, y + 469 + line_index * 18))
        credit = str(module.get("credit") or "reference credit recorded in manifest")
        _text(board, small, credit[:92], (x + 20, y + 516), (155, 180, 150))
    path = output_dir / ("design_board.png" if preview_only else "detail.png")
    pygame.image.save(board, path)
    return path


def _shoot_bounds(simulations):
    points = []
    for simulation in simulations:
        snapshot = simulation.render_snapshot
        if simulation.blueprint.growth.get("fungal_grammar_version"):
            a,b,c,d,e,f = snapshot.bounds_m
            points.extend(((a+c*SCREEN_DEPTH_PROJECTION,e),(b+d*SCREEN_DEPTH_PROJECTION,f)))
            continue
        orientations = getattr(snapshot, "placement_orientations", {}) or {}
        leaf_module = simulation.blueprint.module("leaf")
        leaf_length = max(0.0, float(getattr(leaf_module, "length_m", 0.0) or 0.0))
        for index, placement in enumerate(snapshot.placements):
            if placement[0] in {"root", "root_section", "root_support"}:
                continue
            points.append((placement[2] + placement[3] * SCREEN_DEPTH_PROJECTION, placement[4]))
            if placement[0] != "leaf" or leaf_length <= 0.0:
                continue
            path = (snapshot.placement_paths or {}).get(str(index)) or []
            if path:
                points.extend((p[0] + p[1] * SCREEN_DEPTH_PROJECTION, p[2]) for p in path)
                blade_half = float((leaf_module.visual or {}).get("frond_blade_width_m", 0)) * .5 * max(.025, float(placement[6]))
                if blade_half:
                    stipe = float((leaf_module.visual or {}).get("frond_stipe_fraction", .36))
                    for n, p in enumerate(path):
                        if n / max(1, len(path) - 1) < stipe:
                            continue
                        x = p[0] + p[1] * SCREEN_DEPTH_PROJECTION
                        points.extend(((x - blade_half, max(0, p[2] - blade_half)),
                                       (x + blade_half, p[2] + blade_half)))
                continue
            forward = (orientations.get(str(index)) or {}).get("forward") or []
            if len(forward) < 3:
                continue
            extent = leaf_length * max(0.55, float(placement[6])) * 1.35
            endpoint = (
                float(placement[2]) + float(forward[0]) * extent,
                float(placement[3]) + float(forward[1]) * extent,
                float(placement[4]) + float(forward[2]) * extent,
            )
            points.append((endpoint[0] + endpoint[1] * SCREEN_DEPTH_PROJECTION, endpoint[2]))
    return (
        min(point[0] for point in points), max(point[0] for point in points),
        min(0.0, min(point[1] for point in points)), max(point[1] for point in points),
    )


def _render_mockup(manifest, rendered, output_dir):
    live = WorldModel().resolved_species_entity(manifest["species_id"])
    measured = deepcopy(live)
    measured.update(deepcopy(manifest.get("species_field_updates") or {}))
    preview = deepcopy(measured)
    anchor_key = anchor_field(manifest["modules"][0]["role"])
    anchors = deepcopy(preview.get(anchor_key) or {})
    for module, _sprite, path in rendered:
        _wire_module(preview, anchors, module, path.relative_to(PROJECT_ROOT).as_posix(), _anchor_payload(module))
    preview[anchor_key] = anchors
    config = manifest.get("preview") or {}
    seed = int(config.get("seed", 303))
    original_control = config.get("control_mode") == "original"
    simulations = [
        SpeciesSimulation(species_entity=live if original_control else measured, seed=seed),
        SpeciesSimulation(species_entity=preview, seed=seed),
    ]
    age_offset = float(config.get("reproductive_age_offset_days", 5.0))
    for simulation in simulations:
        age = config.get("age_days", simulation.blueprint.growth["life_history"]["reproductive_start_days"] + age_offset)
        simulation.set_age(age)
    bounds = _shoot_bounds(simulations)
    panel_height = max(180,min(700,round(700*(bounds[3]-bounds[2])/max(0.01,bounds[1]-bounds[0])+50)))
    sheet = pygame.Surface((1440, panel_height+120))
    sheet.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 24)
    small = pygame.font.SysFont("consolas", 17)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    _text(sheet, title, f"PREVIEW ONLY | fixed seed {seed} | reproductive age | matched scale", (22, 18))
    roles = " + ".join(module["role"] for module, _sprite, _path in rendered)
    labels = ("BEFORE: current live plant" if original_control else "CONTROL: updated traits + existing assets",
              f"PREVIEW: proposed {roles} assets")
    for index, (simulation, label) in enumerate(zip(simulations, labels)):
        panel = pygame.Surface((700, panel_height))
        visible = {
            placement_index
            for placement_index, placement in enumerate(simulation.render_snapshot.placements)
            if placement[0] not in {"root", "root_section", "root_support"}
        }
        renderer._draw_individual(
            panel,
            simulation,
            snapshot=simulation.render_snapshot,
            camera=DiagnosticCamera(700, panel_height, bounds),
            visible_indices=visible,
        )
        x = 10 + index * 715
        sheet.blit(panel, (x, 82))
        _text(sheet, small, label, (x + 12, 58))
    path = output_dir / "fixed_seed_mockup.png"
    pygame.image.save(sheet, path)
    return path


def _render_top_mockup(manifest, rendered, output_dir):
    """Render the preview from above so rosette overlap and size vary visibly."""

    live = WorldModel().resolved_species_entity(manifest["species_id"])
    measured = deepcopy(live)
    measured.update(deepcopy(manifest.get("species_field_updates") or {}))
    preview = deepcopy(measured)
    anchor_key = anchor_field(manifest["modules"][0]["role"])
    anchors = deepcopy(preview.get(anchor_key) or {})
    for module, _sprite, path in rendered:
        _wire_module(preview, anchors, module, path.relative_to(PROJECT_ROOT).as_posix(), _anchor_payload(module))
    preview[anchor_key] = anchors
    config = manifest.get("preview") or {}
    seed = int(config.get("seed", 303))
    simulations = (
        SpeciesSimulation(species_entity=measured, seed=seed),
        SpeciesSimulation(species_entity=preview, seed=seed),
    )
    age_offset = float(config.get("reproductive_age_offset_days", 5.0))
    for simulation in simulations:
        age = config.get("age_days", simulation.blueprint.growth["life_history"]["reproductive_start_days"] + age_offset)
        simulation.set_age(age)
    separate_bounds = [top_down_diagnostic_bounds(simulation) for simulation in simulations]
    bounds = (
        min(item[0] for item in separate_bounds),
        max(item[1] for item in separate_bounds),
        min(item[2] for item in separate_bounds),
        max(item[3] for item in separate_bounds),
    )
    sheet = pygame.Surface((1440, 820))
    sheet.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 24)
    small = pygame.font.SysFont("consolas", 17)
    _text(sheet, title, f"PREVIEW ONLY | top view | fixed seed {seed} | matched scale", (22, 18))
    roles = " + ".join(module["role"] for module, _sprite, _path in rendered)
    labels = ("CONTROL: updated traits + existing assets", f"PREVIEW: proposed {roles} assets")
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    for index, (simulation, label) in enumerate(zip(simulations, labels)):
        panel = pygame.Surface((700, 700))
        renderer._draw_individual(
            panel,
            simulation,
            snapshot=simulation.render_snapshot,
            camera=TopDownDiagnosticCamera(700, 700, bounds),
            visible_indices=canopy_visible_indices(simulation,simulation.render_snapshot),
        )
        x = 10 + index * 715
        sheet.blit(panel, (x, 82))
        _text(sheet, small, label, (x + 12, 58))
    path = output_dir / "fixed_seed_top_mockup.png"
    pygame.image.save(sheet, path)
    return path


def _organ_detail_snapshot(simulation):
    """Expand represented tree foliage so the close-up can fit a real socket."""
    snapshot = simulation.render_snapshot
    if snapshot.leaf_clusters and not any(p[0] == "leaf" for p in snapshot.placements):
        return simulation.get_detailed_snapshot()
    return snapshot


def _render_detail_mockup(manifest, rendered, output_dir):
    """Render one real leaf socket at an independently fitted physical scale."""

    live = WorldModel().resolved_species_entity(manifest["species_id"])
    measured = deepcopy(live)
    measured.update(deepcopy(manifest.get("species_field_updates") or {}))
    preview = deepcopy(measured)
    anchor_key = anchor_field(manifest["modules"][0]["role"])
    anchors = deepcopy(preview.get(anchor_key) or {})
    for module, _sprite, path in rendered:
        _wire_module(preview, anchors, module, path.relative_to(PROJECT_ROOT).as_posix(), _anchor_payload(module))
    preview[anchor_key] = anchors
    config = manifest.get("preview") or {}
    seed = int(config.get("seed", 303))
    simulations = (
        SpeciesSimulation(species_entity=measured, seed=seed),
        SpeciesSimulation(species_entity=preview, seed=seed),
    )
    age_offset = float(config.get("reproductive_age_offset_days", 5.0))
    for simulation in simulations:
        age = config.get("age_days", simulation.blueprint.growth["life_history"]["reproductive_start_days"] + age_offset)
        simulation.set_age(age)

    snapshots = [_organ_detail_snapshot(simulation) for simulation in simulations]
    snapshot = snapshots[1]
    # Prefer an outer fertile shoot over the densely overlapped basal crown.
    fruits = [(i,p) for i,p in enumerate(snapshot.placements) if p[0] == "fruit"]
    focal_parent = max(fruits,key=lambda item: math.hypot(item[1][2],item[1][3]))[1][1] if fruits else None
    leaf_index = next((i for i,p in enumerate(snapshot.placements)
                       if p[0] == "leaf" and (focal_parent is None or p[1] == focal_parent)),None)
    detail_bar_m = 0.01
    frond_detail = False
    fungal_index = None
    fungal_bodies = [b for b in snapshot.stats.get('fungal_bodies', []) if b['placement_index'] is not None]
    if fungal_bodies:
        body = max(fungal_bodies, key=lambda b: b['cap_width_m'])
        fungal_index = body['placement_index']
        x, y, z = body['cap_socket_m']; cx = x+y*SCREEN_DEPTH_PROJECTION
        width = body['cap_width_m']
        bounds = (cx-width*1.15, cx+width*1.15, z-width*.55, z+width*.55)
        detail_bar_m = .01
    elif leaf_index is None:
        bounds = _shoot_bounds(simulations)
    else:
        leaf = snapshot.placements[leaf_index]
        point = (
            float(leaf[2]) + float(leaf[3]) * SCREEN_DEPTH_PROJECTION,
            float(leaf[4]),
        )
        module = simulations[1].blueprint.module("leaf")
        frond_detail = (getattr(module,"visual",{}) or {}).get('visual_unit') == 'pinnule'
        leaf_size = max(
            0.001,
            float((getattr(module, "visual", {}) or {}).get("depicted_size_m") or 0.0),
            float(getattr(module, "length_m", 0.0) or 0.0),
        )
        span = max(0.015, leaf_size * 6.0)
        center_x, center_z = point
        detail_bar_m = leaf_size
        bounds = (
            center_x - span / 2.0,
            center_x + span / 2.0,
            center_z - span / 2.0,
            center_z + span / 2.0,
        )
        if frond_detail:
            # A botanical frond is already one leaf placement. Fit its real
            # rachis and blade instead of zooming out six whole-frond lengths
            # and displaying the surrounding stand as an alleged organ detail.
            projected=[]
            for detail in snapshots:
                for p in detail.placement_paths.get(str(leaf_index),[]):
                    projected.append((p[0]+p[1]*SCREEN_DEPTH_PROJECTION,p[2]))
            if projected:
                pad=max(.04,float(module.visual.get('frond_blade_width_m',leaf_size*.6))*.6)
                bounds=(min(p[0] for p in projected)-pad,max(p[0] for p in projected)+pad,
                        min(p[1] for p in projected)-pad,max(p[1] for p in projected)+pad)

    sheet = pygame.Surface((1440, 820))
    sheet.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 24)
    small = pygame.font.SysFont("consolas", 17)
    organ_name = 'bracket' if fungal_index is not None else 'leaf'
    _text(sheet, title, f"PREVIEW ONLY | fitted {organ_name} detail | fixed seed {seed}", (22, 18))
    _text(sheet, small, "Independent close-up; compare shape here, whole-plant scale in the matched overview.", (22, 51), (165, 190, 156))
    labels = (f"CONTROL: existing {organ_name} asset or fallback", f"PREVIEW: proposed {organ_name} asset")
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    for index, (simulation, label, detail_snapshot) in enumerate(zip(simulations, labels, snapshots)):
        panel = pygame.Surface((700, 700))
        visible = {
            placement_index
            for placement_index, placement in enumerate(detail_snapshot.placements)
            if placement[0] not in {"root", "root_section", "root_support"}
        }
        if frond_detail:
            visible={leaf_index}
        if fungal_index is not None:
            visible={fungal_index}
        camera = DiagnosticCamera(700, 700, bounds, minimum_span_m=0.001)
        renderer._draw_individual(
            panel,
            simulation,
            snapshot=detail_snapshot,
            camera=camera,
            visible_indices=visible,
            draw_environment=fungal_index is None,
        )
        try:
            scale_bar_px = abs(camera.world_to_screen((detail_bar_m, 0.0))[0] - camera.world_to_screen((0.0, 0.0))[0])
        except (TypeError, IndexError):
            scale_bar_px = 60
        bar_left, bar_y = 28, 665
        pygame.draw.line(panel, (224, 207, 126), (bar_left, bar_y), (bar_left + round(scale_bar_px), bar_y), 3)
        pygame.draw.line(panel, (224, 207, 126), (bar_left, bar_y - 5), (bar_left, bar_y + 5), 2)
        pygame.draw.line(panel, (224, 207, 126), (bar_left + round(scale_bar_px), bar_y - 5), (bar_left + round(scale_bar_px), bar_y + 5), 2)
        bar_label = f"{detail_bar_m * 1000.0:g} mm" if detail_bar_m < 1.0 else f"{detail_bar_m:g} m"
        _text(panel, small, bar_label, (bar_left, bar_y - 28), (224, 207, 126))
        x = 10 + index * 715
        sheet.blit(panel, (x, 82))
        _text(sheet, small, label, (x + 12, 78))
    path = output_dir / "detail_mockup.png"
    pygame.image.save(sheet, path)
    return path


def preview(manifest, output_dir=None):
    """Create the review package without touching live entities or assets."""

    output_dir = _preview_directory(manifest, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for module in manifest["modules"]:
        sprite = render_module(module)
        suffix = "_" + module["variant_key"] if module.get("variant_key") else ""
        path = output_dir / f"{module['role']}{suffix}_preview.png"
        pygame.image.save(sprite, path)
        rendered.append((module, sprite, path))
    board = _render_design_board(manifest, rendered, output_dir)
    mockup = _render_mockup(manifest, rendered, output_dir)
    top_mockup = _render_top_mockup(manifest, rendered, output_dir)
    detail_mockup = _render_detail_mockup(manifest, rendered, output_dir)
    life_stages = _render_life_stages(manifest, rendered, output_dir)
    return {
        "mode": "preview",
        "species_id": manifest["species_id"],
        "manifest": manifest["_manifest_path"],
        "design_board": str(board.resolve()),
        "fixed_seed_mockup": str(mockup.resolve()),
        "fixed_seed_top_mockup": str(top_mockup.resolve()),
        "detail_mockup": str(detail_mockup.resolve()),
        "life_stages": str(life_stages.resolve()) if life_stages else None,
        "modules": [
            {
                "role": module["role"],
                "depicted_size_m": module["depicted_size_m"],
                "canvas_size": list(sprite.get_size()),
                "preview_path": str(path.resolve()),
            }
            for module, sprite, path in rendered
        ],
        "live_writes": False,
    }


def _render_life_stages(manifest, rendered, output_dir):
    """Optional manifest-selected stages, using the actual portable renderer."""
    stages = (manifest.get("preview") or {}).get("stages") or []
    if not stages:
        return None
    entity = deepcopy(WorldModel().resolved_species_entity(manifest["species_id"]))
    entity.update(deepcopy(manifest.get("species_field_updates") or {}))
    anchor_key = anchor_field(manifest["modules"][0]["role"])
    anchors = deepcopy(entity.get(anchor_key) or {})
    for module,_sprite,path in rendered:
        _wire_module(entity, anchors, module, path.relative_to(PROJECT_ROOT).as_posix(), _anchor_payload(module))
    entity[anchor_key] = anchors
    simulations = []
    for stage in stages[:8]:
        simulation = SpeciesSimulation(species_entity=entity,seed=int((manifest.get("preview") or {}).get("seed",303)))
        simulation.set_lod(2)
        simulation.set_age(float(stage["age_days"]))
        simulations.append(simulation)
    bounds = _shoot_bounds(simulations)
    width,height = 400,330
    sheet = pygame.Surface((width*4,90+height*math.ceil(len(simulations)/4)))
    sheet.fill((13,20,17))
    title = pygame.font.SysFont("consolas",23)
    font = pygame.font.SysFont("consolas",15)
    display = manifest.get("display_name") or manifest["species_id"]
    seed = int((manifest.get("preview") or {}).get("seed",303))
    _text(sheet,title,f"PREVIEW ONLY | {display} | life stages | seed {seed} | LOD 2",(18,16))
    _text(sheet,font,"Shared overview scale; organ insets enlarged separately. Ages are MODEL DAYS, not measured years.",(18,50))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    records = []
    for index,(stage,simulation) in enumerate(zip(stages,simulations)):
        snapshot = simulation.render_snapshot
        cell = pygame.Surface((width,height));cell.fill((18,26,20))
        shoot_indices = {i for i,p in enumerate(snapshot.placements) if p[0] not in {"root","root_section","root_support"}}
        overview = pygame.Surface((width,125))
        renderer._draw_individual(overview,simulation,snapshot=snapshot,
                                  camera=DiagnosticCamera(width,125,bounds),visible_indices=shoot_indices)
        cell.blit(overview,(0,65))
        # One connected shoot/socket detail, not every overlapping branch at
        # the same projected position. This makes the actual organ legible.
        fungal = bool(simulation.blueprint.growth.get("fungal_grammar_version"))
        fertile = [(i,p) for i,p in enumerate(snapshot.placements) if p[0] in {"flower","fruit","fruiting_body"}]
        focal = max(fertile,key=lambda item: math.hypot(item[1][2],item[1][3])) if fertile else next(
            ((i,p) for i,p in enumerate(snapshot.placements) if p[0] == "leaf"),None)
        if focal:
            host = int(focal[1][1])
            selected = {host,int(snapshot.placements[host][1])}
            selected |= {i for i,p in enumerate(snapshot.placements) if p[1] == host and p[0] in {"leaf","flower","fruit"}}
            x,y,z = focal[1][2:5];cx = x+y*SCREEN_DEPTH_PROJECTION
            focal_module = simulation.blueprint.module(focal[1][0])
            span = max(0.018,float(getattr(focal_module,"length_m",.1))*5)
            if fungal:
                selected = {focal[0]}
                span = max(.018, float(getattr(focal_module, 'length_m', .1))*2.4)
            detail = pygame.Surface((160,130))
            renderer._draw_individual(detail,simulation,snapshot=snapshot,
                camera=DiagnosticCamera(160,130,(cx-span/2,cx+span/2,z-span/2,z+span/2),minimum_span_m=0.001),
                visible_indices=selected, draw_environment=not fungal)
            cell.blit(detail,(12,190))
        state = simulation.life_state()
        _text(cell,font,str(stage["label"]),(12,12))
        _text(cell,font,f"Model day {simulation.age_days:g}",(12,34),(160,178,151))
        _text(cell,font,"Bracket detail" if fungal else "Shoot detail",(184,218),(160,178,151))
        if fungal:
            _text(cell,font,f"Brackets {snapshot.stats['estimated_fruiting_body_count']}",(184,244))
            _text(cell,font,"Colony persists",(184,266))
        else:
            _text(cell,font,f"Flowers {sum(p[0] == 'flower' for p in snapshot.placements)}",(184,244))
            _text(cell,font,f"Fruit {sum(p[0] == 'fruit' for p in snapshot.placements)}",(184,266))
        pygame.draw.rect(cell,(67,89,60),cell.get_rect(),1)
        sheet.blit(cell,((index%4)*width,90+(index//4)*height))
        records.append({"label":stage["label"],"age_days":simulation.age_days,"life_state":state,
                        "fingerprint":simulation.blueprint.fingerprint(),"bounds_m":snapshot.bounds_m,"stats":snapshot.stats})
    path = output_dir/"life_stages.png"
    pygame.image.save(sheet,path)
    (output_dir/"life_stages.json").write_text(json.dumps(records,indent=2)+"\n",encoding="utf-8")
    return path


def _copy_surface_to_editor(editor, surface):
    width = int(editor.state.get("canvas_width") or 0)
    height = int(editor.state.get("canvas_height") or 0)
    if surface.get_size() != (width, height):
        raise RuntimeError(f"Rendered surface {surface.get_size()} != Pixel Studio canvas {(width, height)}")
    editor.state["canvas_rect"] = pygame.Rect(0, 0, width, height)
    layer = editor._active_layer()
    pixels = layer.get("pixels") if isinstance(layer, dict) else None
    if not isinstance(pixels, list):
        raise RuntimeError("Pixel Studio active layer is unavailable")
    for y in range(height):
        for x in range(width):
            color = surface.get_at((x, y))
            pixels[y][x] = (color.r, color.g, color.b) if color.a else None
    editor._mark_dirty()


def _author_module(host, module, surface):
    controller = PixelArtEditorUI(host)
    illustration_id = module["illustration_id"]
    if not controller.open(illustration_id):
        raise RuntimeError(f"Could not open Pixel Studio entry {illustration_id}")
    controller.state["metric_size_buffer"] = str(module["depicted_size_m"])
    controller.state["illustration"]["pixel_document_path"] = ""
    controller.state["illustration"]["media_path"] = ""
    host.canvas_size_override = surface.get_size()
    if not controller.begin_canvas():
        raise RuntimeError(f"Could not create canvas for {illustration_id}")
    host.canvas_size_override = None
    _copy_surface_to_editor(controller, surface)
    attachment, tip = _anchor_pixels(module, surface.get_size())
    controller.set_anchor_mode("attachment")
    controller.set_attachment_point(attachment)
    controller.set_anchor_mode("axis")
    controller.set_growth_axis(tip)
    if not controller.save():
        raise RuntimeError(f"Could not save {illustration_id}: {controller.state.get('status')}")
    return host.loader.entities[illustration_id]


def apply_manifest(manifest):
    """Persist an inspected manifest through the Pixel Studio path."""

    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    species = loader.entities.get(manifest["species_id"])
    if not isinstance(species, dict):
        raise RuntimeError(f"Missing existing plant card: {manifest['species_id']}")
    if manifest["modules"][0]["role"] in FUNGAL_ASSET_FIELDS:
        from simulations.species.plant_assets import is_fungal_growth_species_entity
        proposed = {**species, **manifest.get("species_field_updates", {})}
        if not is_fungal_growth_species_entity(proposed, loader.entities):
            raise ManifestError("Fungal assets require a verified Fungi species with a valid body recipe")
    rendered = [(module, render_module(module)) for module in manifest["modules"]]
    for module, _surface in rendered:
        _upsert(loader, {
            "id": module["illustration_id"],
            "_dataset": "ideas",
            "type": "idea",
            "idea_class": "illustration",
            "name": module["name"],
            "pretty_name": module["name"],
            "parents": [manifest["species_id"]],
            "plant_asset_role": module["role"],
            "plant_asset_kind": module.get("kind", module["role"]),
            "plant_asset_target_field": asset_field(module["role"]),
            "plant_asset_variant": module.get("variant_key", ""),
            "depicted_size_m": float(module["depicted_size_m"]),
            "asset_reference_urls": list(module.get("reference_urls") or []),
            "asset_reference_credit": str(module.get("credit") or ""),
            "asset_design_status": "approved_pixel_studio_module",
            "asset_manifest_path": Path(manifest["_manifest_path"]).relative_to(PROJECT_ROOT).as_posix(),
            "media_path": "",
        })
    host = PixelEditorHost(loader)
    authored = []
    anchor_key = anchor_field(manifest["modules"][0]["role"])
    anchors = deepcopy(species.get(anchor_key) or {})
    for module, surface in rendered:
        illustration = _author_module(host, module, surface)
        media_path = illustration.get("media_path")
        document_path = illustration.get("pixel_document_path")
        if not media_path or not (PROJECT_ROOT / media_path).is_file():
            raise RuntimeError(f"Missing authored PNG for {module['role']}: {media_path}")
        if not document_path or not (PROJECT_ROOT / document_path).is_file():
            raise RuntimeError(f"Missing editable document for {module['role']}: {document_path}")
        payload = dict(illustration.get("pixel_module_anchor") or {})
        payload["depicted_size_m"] = float(module["depicted_size_m"])
        if 'cap_join_fraction' in module:
            payload['cap_join_fraction'] = module['cap_join_fraction']
        if module.get("visual_unit"):
            payload["visual_unit"] = module["visual_unit"]
        _wire_module(species, anchors, module, media_path, payload)
        authored.append({
            "role": module["role"],
            "illustration_id": module["illustration_id"],
            "media_path": media_path,
            "pixel_document_path": document_path,
            "canvas_size": list(surface.get_size()),
        })
    species.update(deepcopy(manifest.get("species_field_updates") or {}))
    species[anchor_key] = anchors
    _upsert(loader, species)
    fields = {anchor_key, *manifest.get("species_field_updates", {}).keys()}
    fields.update(asset_field(module["role"]) for module in manifest["modules"])
    if not loader.persist_entity_fields(species, fields):
        raise RuntimeError(f"Could not persist asset fields for {manifest['species_id']}")
    return {
        "mode": "apply",
        "species_id": manifest["species_id"],
        "manifest": manifest["_manifest_path"],
        "modules": authored,
        "persisted_fields": sorted(fields),
    }


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Version-1 plant asset JSON manifest")
    parser.add_argument("--apply", action="store_true", help="Persist approved assets and wire the species")
    parser.add_argument("--validate-only", action="store_true", help="Validate and print the resolved authoring plan")
    parser.add_argument("--output-dir", type=Path, help="Override the preview artifact directory")
    args = parser.parse_args(argv)
    if args.apply and args.validate_only:
        parser.error("--apply and --validate-only are mutually exclusive")
    if args.apply and args.output_dir:
        parser.error("--output-dir only applies to preview mode")
    return args


def main(argv=None):
    args = _parse_args(argv)
    manifest = load_manifest(args.manifest.resolve())
    if args.validate_only:
        result = {
            "mode": "validate",
            "species_id": manifest["species_id"],
            "modules": [
                {
                    "role": module["role"],
                    "depicted_size_m": module["depicted_size_m"],
                    "canvas_size": list(canvas_size(module["depicted_size_m"])),
                }
                for module in manifest["modules"]
            ],
            "live_writes": False,
        }
    else:
        pygame.init()
        pygame.font.init()
        if not args.apply:
            pygame.display.set_mode((1, 1))
        try:
            result = apply_manifest(manifest) if args.apply else preview(manifest, args.output_dir)
        finally:
            pygame.quit()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
