"""State helpers for the visual Species Editor."""

from __future__ import annotations

import copy
import os
import random

import pygame

from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.plant_growth_catalog import (
    PLANT_GROWTH_BEHAVIOUR_CHOICES,
    PLANT_GROWTH_FORM_CHOICES,
    PLANT_LIFE_CYCLE_CHOICES,
)
from world.plant_traits import (
    PLANT_ARCHITECTURE_RANGE_FIELDS,
    PLANT_TRAIT_BEHAVIOR_PATHS,
    PLANT_TRAIT_CHOICES,
    PLANT_TRAIT_SCHEMA_FIELDS,
    normalised_plant_trait_range,
)


SPECIAL_CHOICES = {
    "plant_growth_form": PLANT_GROWTH_FORM_CHOICES,
    "plant_growth_behaviour": PLANT_GROWTH_BEHAVIOUR_CHOICES,
    "plant_lifespan": PLANT_LIFE_CYCLE_CHOICES,
}

RANGE_DEFAULTS = {
    "plant_apical_control": .60,
    "plant_leaf_spacing_bias": .50,
    "plant_branch_droop": .35,
    "plant_branch_angle_gradient": .45,
    "plant_crown_openness": .50,
    "plant_leaf_depth_gradient": .45,
    "plant_fine_twig_density": .55,
    "plant_leaf_cluster_density": .55,
}

FIELD_GROUPS = ("All", "Crown", "Branches", "Shoots", "Leaves", "Reproduction")
PREVIEW_MODES = ("minimum", "typical", "maximum", "variation")
PREVIEW_AFFECTING_FIELDS = PLANT_ARCHITECTURE_RANGE_FIELDS | {
    "plant_growth_form", "plant_growth_behaviour", "plant_lifespan",
    "mature_height", "mature_height_class", "growth_rate", "maturity_rate",
    "plant_axis_continuity", "plant_branching_rhythm", "plant_branching_timing",
    "plant_lateral_axis_orientation", "plant_flowering_position",
    "plant_shoot_dimorphism", "plant_leaf_distribution", "plant_woodiness",
    "leaf_phenology", "leaf_size_class", "leaf_structure", "leaf_arrangement",
    "leaf_attachment_pattern", "leaf_clustering", "root_architecture",
    "reproductive_mode", "clonal_spread", "seed_size_class",
}


def field_group(field_name):
    name = str(field_name).lower()
    if any(token in name for token in ("flower", "fruit", "seed", "reproduct", "pollin", "dispers", "clonal")):
        return "Reproduction"
    if any(token in name for token in ("leaf", "photosynth")):
        return "Crown" if any(token in name for token in ("depth", "cluster", "distribution")) else "Leaves"
    if any(token in name for token in ("crown", "height", "openness")):
        return "Crown"
    if any(token in name for token in ("branch", "lateral", "twig")):
        return "Branches"
    return "Shoots"


def calibration_badge(value):
    value = value if isinstance(value, dict) else {}
    status = str(value.get("status") or "").lower()
    source = str(value.get("source") or "").lower()
    if "measured" in status or "measurement" in source:
        return "MEASURED", (104, 179, 208)
    if "literature" in status or "literature" in source:
        return "LITERATURE", (143, 181, 116)
    if "visual" in status or "visual" in source:
        return "VISUAL FIT", (218, 178, 93)
    if status in {"runtime_default", "legacy_point_value"} or "guess" in source:
        return "GUESSED", (190, 139, 104)
    return "UNVERIFIED", (157, 139, 130)


def editor_choices(field_name):
    return tuple(SPECIAL_CHOICES.get(field_name) or PLANT_TRAIT_CHOICES.get(field_name) or ())


def field_label(field_name):
    path = PLANT_TRAIT_BEHAVIOR_PATHS.get(field_name)
    if path:
        return path[-1]
    return field_name.removeprefix("plant_").replace("_", " ").title()


def editable_field_rows(entity, query="", group="All", preview_only=False):
    query = str(query or "").strip().lower()
    rows = []
    for field_name in PLANT_TRAIT_SCHEMA_FIELDS:
        if field_name.endswith("_ref") or field_name in {"plant_module_anchors"}:
            continue
        label = field_label(field_name)
        if query and query not in label.lower() and query not in field_name.lower():
            continue
        row_group = field_group(field_name)
        affects_preview = field_name in PREVIEW_AFFECTING_FIELDS
        if group != "All" and row_group != group:
            continue
        if preview_only and not affects_preview:
            continue
        if field_name in PLANT_ARCHITECTURE_RANGE_FIELDS:
            kind = "range"
        elif editor_choices(field_name):
            kind = "choice"
        else:
            kind = "card"
        rows.append({
            "field": field_name,
            "label": label,
            "kind": kind,
            "value": entity.get(field_name),
            "group": row_group,
            "affects_preview": affects_preview,
        })
    return rows


def new_editor_state(entity):
    working = copy.deepcopy(entity if isinstance(entity, dict) else {})
    return {
        "original_entity": copy.deepcopy(working),
        "working_entity": working,
        "reference_surface": None,
        "reference_label": "Temporary reference — not saved",
        "query": "",
        "scroll": 0,
        "selected_field": None,
        "active_range": None,
        "field_group": "All",
        "preview_only": True,
        "preview_mode": "typical",
        "variation_count": 4,
        "preview_deferred": False,
        "undo_stack": [],
        "redo_stack": [],
        "reference_overlay": False,
        "reference_silhouette": False,
        "reference_opacity": .35,
        "reference_scale": 1.0,
        "reference_offset": [0.0, 0.0],
        "reference_silhouette_surface": None,
        "dirty": False,
        "status": "Paste a reference image, then tune the preview.",
    }


def range_value(state, field_name):
    entity = state.get("working_entity") or {}
    return normalised_plant_trait_range(
        entity.get(field_name),
        RANGE_DEFAULTS.get(field_name, .5),
        default_span=.10,
    )


def record_history(state):
    state.setdefault("undo_stack", []).append(copy.deepcopy(state.get("working_entity") or {}))
    del state["undo_stack"][:-30]
    state["redo_stack"] = []


def undo(state):
    stack = state.setdefault("undo_stack", [])
    if not stack:
        state["status"] = "Nothing to undo."
        return False
    state.setdefault("redo_stack", []).append(copy.deepcopy(state["working_entity"]))
    state["working_entity"] = stack.pop()
    state["dirty"] = state["working_entity"] != state["original_entity"]
    state["status"] = "Undid the last field change."
    return True


def redo(state):
    stack = state.setdefault("redo_stack", [])
    if not stack:
        state["status"] = "Nothing to redo."
        return False
    state.setdefault("undo_stack", []).append(copy.deepcopy(state["working_entity"]))
    state["working_entity"] = stack.pop()
    state["dirty"] = state["working_entity"] != state["original_entity"]
    state["status"] = "Redid the field change."
    return True


def set_range_handle(state, field_name, handle, value, record=True):
    if record:
        record_history(state)
    value = max(0., min(1., float(value)))
    current = range_value(state, field_name)
    if handle == "min":
        current["min"] = min(value, current["typical"])
    elif handle == "max":
        current["max"] = max(value, current["typical"])
    else:
        current["typical"] = value
        current["min"] = min(current["min"], value)
        current["max"] = max(current["max"], value)
    current["status"] = "provisional_visual_calibration"
    current["source"] = "species_editor_visual_fit"
    state["working_entity"][field_name] = current
    state["selected_field"] = field_name
    state["dirty"] = True
    state["status"] = f"Previewing {field_label(field_name)}"
    return True


def cycle_choice(state, field_name, direction=1):
    choices = editor_choices(field_name)
    if not choices:
        state["selected_field"] = field_name
        state["status"] = "This value uses the full Species Card editor."
        return False
    record_history(state)
    values = [str(choice.get("value") or "") for choice in choices]
    current = str((state.get("working_entity") or {}).get(field_name) or "")
    try:
        index = values.index(current)
    except ValueError:
        index = -1 if direction > 0 else 0
    value = values[(index + direction) % len(values)]
    state["working_entity"][field_name] = value
    state["selected_field"] = field_name
    state["dirty"] = True
    state["status"] = f"{field_label(field_name)}: {value.replace('_', ' ')}"
    return True


def load_reference_from_clipboard(state):
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
    except pygame.error:
        state["status"] = "Clipboard image support is unavailable."
        return True

    surface = None
    try:
        data = pygame.scrap.get(getattr(pygame, "SCRAP_BMP", "image/bmp"))
    except pygame.error:
        data = None
    surface = PixelArtEditorUI.surface_from_image_bytes(data)
    if surface is None:
        try:
            text_data = pygame.scrap.get(getattr(pygame, "SCRAP_TEXT", "text/plain"))
        except pygame.error:
            text_data = None
        if text_data:
            text = text_data.decode("utf-8", errors="ignore").strip().strip("\x00").strip('"')
            if text and os.path.exists(text):
                try:
                    surface = pygame.image.load(text).convert_alpha()
                except (pygame.error, OSError):
                    surface = None
    if surface is None:
        state["status"] = "Ctrl+V found no image or local image path."
        return True
    state["reference_surface"] = surface
    state["reference_silhouette_surface"] = None
    state["reference_overlay"] = True
    state["reference_label"] = f"Temporary reference • {surface.get_width()} × {surface.get_height()} px"
    state["status"] = "Reference loaded locally; it will not be saved."
    return True


def preview_entity(state, mode="typical", sample_index=0):
    """Resolve one reproducible organism from the authored range envelopes."""
    entity = copy.deepcopy(state.get("working_entity") or {})
    rng = random.Random(303_000 + int(sample_index))
    for field_name in PLANT_ARCHITECTURE_RANGE_FIELDS:
        envelope = normalised_plant_trait_range(
            entity.get(field_name), RANGE_DEFAULTS.get(field_name, .5), default_span=.10,
        )
        if mode == "minimum":
            chosen = envelope["min"]
        elif mode == "maximum":
            chosen = envelope["max"]
        elif mode == "variation":
            chosen = rng.uniform(envelope["min"], envelope["max"])
        else:
            chosen = envelope["typical"]
        envelope["typical"] = round(chosen, 4)
        entity[field_name] = envelope
    return entity
