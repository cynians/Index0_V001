"""Standalone species-level plant growth simulation.

This simulation owns individual module placements. Map and scenery modes only
consume a reference to a blueprint/snapshot, so they never simulate leaves.
"""

from __future__ import annotations

import math
import random
import json
from simulations.species.root_growth import (
    build_distributed_adventitious_roots,
    build_root_graph,
    build_mixed_contact_roots,
    root_profile,
)
from simulations.species.solid_structures import SolidStructureField
from typing import Any

from engine import asset_files
from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.species.plant_assets import (
    PlantAssetStore,
    PlantBlueprint,
    PlantGrowthSnapshot,
    PlantModule,
    PLANT_MODEL_SPACE,
    plant_life_history_profile,
)


# One shared orthographic convention for the species renderer and all of its
# diagnostic cameras. Positive depth projects consistently to screen-right.
SCREEN_DEPTH_PROJECTION = 1.8


def normalise_neighbour_root_zones(environment):
    """Return bounded planar root-influence zones from runtime context.

    These zones represent occupied neighbouring-root space at the clonal
    connector depth.  They are deliberately not a soil model and are not
    persisted as intrinsic species traits.
    """

    environment = environment if isinstance(environment, dict) else {}
    values = environment.get("neighbour_root_zones")
    if values is None:
        values = environment.get("neighbor_root_zones")
    if not isinstance(values, list):
        return []
    zones = []
    for index, value in enumerate(values[:24]):
        if not isinstance(value, dict):
            continue
        center = value.get("center_m") or value.get("position_m")
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            continue
        try:
            x, y = float(center[0]), float(center[1])
            radius = float(value.get("radius_m", 0.0) or 0.0)
            influence = float(value.get("influence", 1.0))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (x, y, radius, influence)) or radius <= 0.0:
            continue
        zones.append({
            "id": str(value.get("id") or f"neighbour_root_{index + 1}"),
            "center_m": [round(max(-1000.0, min(1000.0, x)), 4),
                         round(max(-1000.0, min(1000.0, y)), 4)],
            "radius_m": round(max(0.02, min(25.0, radius)), 4),
            "influence": round(max(0.0, min(1.0, influence)), 4),
        })
    return [zone for zone in zones if zone["influence"] > 0.0]


def normalise_rod_structures(environment):
    """Return bounded vertical rods supplied as transient scene geometry."""

    environment = environment if isinstance(environment, dict) else {}
    values = environment.get("rod_structures")
    if not isinstance(values, list):
        return []

    def colour(value, fallback):
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return list(fallback)
        try:
            return [max(0, min(255, round(float(value[index])))) for index in range(3)]
        except (TypeError, ValueError):
            return list(fallback)

    rods = []
    for index, value in enumerate(values[:12]):
        if not isinstance(value, dict):
            continue
        position = value.get("position_m") or value.get("base_position_m")
        if not isinstance(position, (list, tuple)) or len(position) < 3:
            continue
        try:
            x, y, z = (float(position[axis]) for axis in range(3))
            radius = float(value.get("radius_m", 0.0) or 0.0)
            height = float(value.get("height_m", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (x, y, z, radius, height)):
            continue
        if radius <= 0.0 or height <= 0.0:
            continue
        x, y, z = (max(-1000.0, min(1000.0, item)) for item in (x, y, z))
        radius = max(0.005, min(5.0, radius))
        height = max(0.05, min(150.0, height))
        palette = value.get("palette") if isinstance(value.get("palette"), dict) else {}
        rods.append({
            "id": str(value.get("id") or f"rod_structure_{index + 1}"),
            "kind": "rod",
            "position_m": [round(x, 4), round(y, 4), round(z, 4)],
            "center_m": [round(x, 4), round(y, 4)],
            "radius_m": round(radius, 4),
            "height_m": round(height, 4),
            "base_z_m": round(z, 4),
            "top_z_m": round(z + height, 4),
            "axis_points_m": [
                [round(x, 4), round(y, 4), round(z, 4)],
                [round(x, 4), round(y, 4), round(z + height, 4)],
            ],
            "crown_radius_m": round(radius, 4),
            "support_model": "cylindrical_rod_helix",
            "palette": {
                "fill": colour(palette.get("fill"), (100, 111, 116)),
                "highlight": colour(palette.get("highlight"), (190, 205, 208)),
            },
        })
    return rods


def normalise_climbing_supports(environment):
    """Return bounded vertical or sampled-axis supports from the local scene.

    Supports are environmental interaction geometry, never intrinsic vine
    traits. A neighbouring tree/scenery system can provide either a simple
    trunk centre/radius/height or a sampled 3D trunk axis extracted from its
    generated plant snapshot.
    """

    environment = environment if isinstance(environment, dict) else {}
    values = environment.get("climbing_supports")
    values = list(values) if isinstance(values, list) else []
    values.extend(normalise_rod_structures(environment))
    supports = []
    for index, value in enumerate(values[:12]):
        if not isinstance(value, dict):
            continue
        axis_points = []
        raw_axis = value.get("axis_points_m")
        if isinstance(raw_axis, list):
            for point in raw_axis[:48]:
                if not isinstance(point, (list, tuple)) or len(point) < 3:
                    continue
                try:
                    sample = tuple(float(point[axis]) for axis in range(3))
                except (TypeError, ValueError):
                    continue
                if not all(math.isfinite(item) for item in sample):
                    continue
                axis_points.append((
                    max(-1000.0, min(1000.0, sample[0])),
                    max(-1000.0, min(1000.0, sample[1])),
                    max(-1000.0, min(1000.0, sample[2])),
                ))
        axis_points.sort(key=lambda point: point[2])
        monotonic_axis = []
        for point in axis_points:
            if monotonic_axis and point[2] <= monotonic_axis[-1][2] + 1e-6:
                continue
            monotonic_axis.append(point)
        axis_points = monotonic_axis if len(monotonic_axis) >= 2 else []

        center = value.get("center_m") or value.get("position_m")
        if (not isinstance(center, (list, tuple)) or len(center) < 2) and axis_points:
            center = axis_points[0]
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            continue
        try:
            x, y = float(center[0]), float(center[1])
            radius = float(value.get("radius_m", value.get("trunk_radius_m", 0.0)) or 0.0)
            default_height = axis_points[-1][2] - axis_points[0][2] if axis_points else 0.0
            height = float(value.get("height_m", default_height) or default_height)
            crown_radius = float(value.get("crown_radius_m", radius * 4.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (x, y, radius, height, crown_radius)):
            continue
        if radius <= 0.0 or height <= 0.0:
            continue
        support = {
            "id": str(value.get("id") or f"climbing_support_{index + 1}"),
            "kind": str(value.get("kind") or "support").lower(),
            "center_m": [
                round(max(-1000.0, min(1000.0, x)), 4),
                round(max(-1000.0, min(1000.0, y)), 4),
            ],
            "radius_m": round(max(0.01, min(5.0, radius)), 4),
            "height_m": round(max(0.05, min(150.0, height)), 4),
            "crown_radius_m": round(max(0.0, min(30.0, crown_radius)), 4),
            "support_model": (
                "cylindrical_rod_helix"
                if str(value.get("kind") or "").lower() == "rod"
                else "sampled_trunk_axis" if axis_points else "cylindrical_helix"
            ),
        }
        if axis_points:
            support["axis_points_m"] = [
                [round(point[0], 4), round(point[1], 4), round(point[2], 4)]
                for point in axis_points
            ]
            support["base_z_m"] = round(axis_points[0][2], 4)
            support["top_z_m"] = round(axis_points[-1][2], 4)
        if value.get("source_species_id") is not None:
            support["source_species_id"] = str(value["source_species_id"])
        if str(value.get("kind") or "").lower() == "rod":
            support["position_m"] = list(value.get("position_m") or [x, y, axis_points[0][2] if axis_points else 0.0])
            support["palette"] = dict(value.get("palette") or {})
        supports.append(support)
    return supports


def climbing_support_axis_at_z(support, z):
    """Interpolate the horizontal centre of a support at an absolute height."""

    points = support.get("axis_points_m") or []
    if len(points) < 2:
        center = support.get("center_m") or (0.0, 0.0)
        return float(center[0]), float(center[1])
    height = float(z)
    if height <= float(points[0][2]):
        return float(points[0][0]), float(points[0][1])
    if height >= float(points[-1][2]):
        return float(points[-1][0]), float(points[-1][1])
    for start, end in zip(points, points[1:]):
        start_z, end_z = float(start[2]), float(end[2])
        if start_z <= height <= end_z:
            fraction = (height - start_z) / max(1e-9, end_z - start_z)
            return (
                float(start[0]) + (float(end[0]) - float(start[0])) * fraction,
                float(start[1]) + (float(end[1]) - float(start[1])) * fraction,
            )
    return float(points[-1][0]), float(points[-1][1])


def climbing_support_from_tree_snapshot(snapshot, support_id="generated_tree_trunk", position_m=(0.0, 0.0, 0.0)):
    """Extract a bounded climbing axis from a generated tree's trunk chain."""

    try:
        offset = tuple(float(position_m[index]) for index in range(3))
    except (TypeError, ValueError, IndexError):
        offset = (0.0, 0.0, 0.0)
    placements = list(getattr(snapshot, "placements", []) or [])
    trunk_indices = [
        index for index, placement in enumerate(placements)
        if len(placement) >= 8 and placement[0] == "stem_section" and int(placement[7]) == 1
    ]
    if not trunk_indices:
        return None
    trunk_indices.sort(key=lambda index: float(placements[index][4]))
    first = placements[trunk_indices[0]]
    parent_index = int(first[1])
    if 0 <= parent_index < len(placements):
        parent = placements[parent_index]
        points = [[float(parent[2]), float(parent[3]), float(parent[4])]]
    else:
        points = [[float(first[2]), float(first[3]), 0.0]]
    for index in trunk_indices:
        for point in (getattr(snapshot, "placement_paths", {}) or {}).get(str(index), []):
            if len(point) >= 3 and float(point[2]) > points[-1][2] + 1e-6:
                points.append([float(point[0]), float(point[1]), float(point[2])])
        placement = placements[index]
        endpoint = [float(placement[2]), float(placement[3]), float(placement[4])]
        if endpoint[2] > points[-1][2] + 1e-6:
            points.append(endpoint)
    if len(points) < 2:
        return None
    shifted = [
        [point[0] + offset[0], point[1] + offset[1], point[2] + offset[2]]
        for point in points
    ]
    stem_module = (getattr(snapshot, "modules", {}) or {}).get("stem_section", {})
    radius = max(0.01, float(stem_module.get("radius_m", 0.035) or 0.035))
    bounds = list(getattr(snapshot, "bounds_m", []) or [0.0] * 6)
    crown_radius = radius * 4.0
    if len(bounds) >= 4:
        crown_radius = max(radius, (max(float(bounds[1]) - float(bounds[0]), float(bounds[3]) - float(bounds[2]))) * 0.5)
    return {
        "id": str(support_id),
        "kind": "tree",
        "source_species_id": str(getattr(snapshot, "species_id", "unknown_species")),
        "center_m": [round(shifted[0][0], 4), round(shifted[0][1], 4)],
        "radius_m": round(radius, 4),
        "height_m": round(shifted[-1][2] - shifted[0][2], 4),
        "crown_radius_m": round(crown_radius, 4),
        "axis_points_m": [[round(value, 4) for value in point] for point in shifted],
    }


def neighbour_root_segment_clearance(start, end, zone):
    """Signed 2D clearance from a segment to one effective influence disc."""

    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    cx, cy = zone["center_m"]
    dx, dy = ex - sx, ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        nearest_x, nearest_y = sx, sy
    else:
        fraction = max(0.0, min(1.0, ((cx - sx) * dx + (cy - sy) * dy) / length_squared))
        nearest_x, nearest_y = sx + dx * fraction, sy + dy * fraction
    effective_radius = float(zone["radius_m"]) * float(zone["influence"])
    return math.hypot(nearest_x - cx, nearest_y - cy) - effective_radius


def steer_clonal_segment(previous, radius, desired_angle, zones):
    """Choose the smallest bounded angular detour that clears root zones."""

    def endpoint(angle):
        radians = math.radians(angle)
        return (math.cos(radians) * radius, math.sin(radians) * radius, float(previous[2]))

    nominal = endpoint(desired_angle)
    if not zones:
        return desired_angle, nominal, 0.0

    def clearance(candidate):
        return min(neighbour_root_segment_clearance(previous, candidate, zone) for zone in zones)

    nominal_clearance = clearance(nominal)
    if nominal_clearance >= 0.0:
        return desired_angle, nominal, 0.0

    candidates = []
    for offset in range(10, 81, 10):
        for signed_offset in (-offset, offset):
            angle = desired_angle + signed_offset
            candidate = endpoint(angle)
            candidates.append((signed_offset, angle, candidate, clearance(candidate)))
    clear = [item for item in candidates if item[3] >= 0.0]
    if clear:
        chosen = min(clear, key=lambda item: (abs(item[0]), -item[3], item[0]))
    else:
        chosen = max(candidates, key=lambda item: (item[3], -abs(item[0]), -item[0]))
    return chosen[1], chosen[2], float(chosen[0])


class SpeciesSimulation:
    """Deterministic plant-growth lab for one ontology species."""

    render_mode = "species"
    min_zoom = 0.15
    # Was 8.0 pixels/metre, which caps a ~20-30m tree at a couple hundred
    # pixels tall with no way to zoom in on canopy/branch detail from the
    # main viewport. Whole-tree draws are now cached (SpeciesRenderer's
    # per-frame draw cache) and foliage is cluster-based rather than
    # per-leaf, so a much closer zoom no longer costs proportionally more.
    max_zoom = 128.0
    preferred_zoom = 1.15
    HUMAN_REFERENCE_HEIGHT_M = 1.75

    def __init__(self, world_model=None, species_id=None, species_entity=None, seed=1, blueprint=None, asset_store=None, environment=None):
        class _DummySystem:
            def update(self, dt):
                pass

        self.world_model = world_model
        self.species_id = str(species_id or (species_entity or {}).get("id") or "species_preview")
        if species_entity is None and world_model is not None:
            species_entity = world_model.get_entity(self.species_id)
        self.species_entity = species_entity if isinstance(species_entity, dict) else {"id": self.species_id}
        if world_model is not None and hasattr(world_model, "resolved_species_entity"):
            self.species_entity = world_model.resolved_species_entity(self.species_id) or self.species_entity
        self.asset_store = asset_store or PlantAssetStore()
        # A live ontology entity is the source of truth for an interactive
        # Species Sim. Cached blueprints are products for scenery/export and
        # may lag behind newly authored fields or sprites. Callers that need a
        # frozen product can still pass ``blueprint`` explicitly.
        self.blueprint = blueprint or (
            PlantBlueprint.from_species_entity(self.species_entity, self.species_id)
            if species_entity is not None or world_model is not None
            else self.asset_store.load_blueprint(self.species_id)
        ) or PlantBlueprint.from_species_entity(self.species_entity, self.species_id)
        self.seed = int(seed)
        self.environment = dict(environment or {})
        if self.blueprint.growth.get("ground_fungal_version") and "fungal_ground_substrate" not in self.environment:
            self.environment.update(fungal_ground_substrate="soil_humus",
                                    substrate_context_source="representative_ground_lab_fixture")
        if self.blueprint.growth.get("fungal_grammar_version") and not self.blueprint.growth.get("ground_fungal_version") and "fungal_substrates" not in self.environment:
            from simulations.species.fungal_growth import wood_test_fixture
            substrates = self.blueprint.growth["fungal_growth_profile"].get("substrates") or []
            material = next((item for item in substrates if item.startswith("dead_")),
                            substrates[0] if substrates else "dead_hardwood")
            self.environment.update(wood_test_fixture(material=material))
        self.forest_spacing = "medium"
        self.forest_tolerance = None
        self.forest_view_style = "isometric"
        self._forest_cache = None
        self.diagnostic_view = ("surface" if self.blueprint.growth.get("growth_behaviour") == "surface_covering" else "individual")
        self.comparison_subject = "individual"
        self.root_comparison_page = 0
        self.root_comparison_common_scale = False
        self._root_comparison_cases = None
        self._tree_architecture_cases = None
        self._diagnostic_cases = None
        self.species_editor = None
        self._species_editor_preview = {}
        self._species_editor_last_previews = None
        self._species_editor_hitboxes = []
        self.pending_navigation_action = None
        self.age_days = min(90.0, max(1.0, self.max_age_days * 0.5))
        self.lod = 2
        self.render_snapshot = self.generate_snapshot(self.age_days, self.lod)
        self.bounds = self._bounds_for_camera(self.render_snapshot.bounds_m)
        self.world_units_to_meters = 1.0
        self.sim_clock = Clock(base_dt=1.0)
        self.sim_manager = SimulationManager(self.sim_clock, _DummySystem())

    @property
    def year(self):
        return 2400

    def set_forest_settings(self, spacing=None, tolerance="unchanged"):
        if spacing is not None:
            if spacing not in {"dense", "medium", "open"}:
                raise ValueError("Unknown forest spacing")
            self.forest_spacing = spacing
        if tolerance != "unchanged":
            if tolerance not in {None, "low", "medium", "high"}:
                raise ValueError("Unknown shade tolerance")
            self.forest_tolerance = tolerance
        self._forest_cache = None

    def get_forest_experiment(self):
        from simulations.species.forest_ecology import build_forest_plan
        key = (self.seed, self.blueprint.fingerprint(), self.forest_spacing, self.forest_tolerance)
        if self._forest_cache and self._forest_cache[0] == key:
            return self._forest_cache[1:]
        plan = build_forest_plan(self.blueprint.growth, self.seed, self.forest_spacing, self.forest_tolerance)
        cases = []
        for tree in plan["trees"]:
            case = SpeciesSimulation(species_entity=self.species_entity, blueprint=self.blueprint,
                                     seed=tree["seed"], environment=tree["environment"])
            case.lod = 1
            case.set_age(case.mature_age_days*tree["maturity"])
            cases.append(case)
        self._forest_cache = (key, plan, cases)
        return plan, cases

    def handle_comparison_key(self, event):
        import pygame
        if self.diagnostic_view != "compare" or event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_r:
            self.comparison_subject = "individual" if self.comparison_subject == "roots" else "roots"
        elif self.comparison_subject == "roots" and event.key == pygame.K_s:
            self.root_comparison_common_scale = not self.root_comparison_common_scale
        elif self.comparison_subject == "roots" and event.key in (pygame.K_LEFT, pygame.K_RIGHT):
            self.root_comparison_page += 1 if event.key == pygame.K_RIGHT else -1
        else:
            return False
        return True

    def get_root_comparison_cases(self):
        if self._root_comparison_cases is None:
            from simulations.species.root_comparison import build_root_comparison
            self._root_comparison_cases = build_root_comparison()
        return self._root_comparison_cases

    def get_tree_architecture_cases(self):
        if self._tree_architecture_cases is None:
            from simulations.species.species_diagnostics import build_tree_architecture_comparison

            self._tree_architecture_cases = build_tree_architecture_comparison(
                self.world_model,
                asset_store=self.asset_store,
                seed=303,
            )
        return list(self._tree_architecture_cases)

    def _ensure_species_editor(self):
        if self.species_editor is None:
            from simulations.species.species_editor import new_editor_state
            self.species_editor = new_editor_state(self.species_entity)
        return self.species_editor

    def set_species_editor_hitboxes(self, hitboxes):
        self._species_editor_hitboxes = list(hitboxes or [])

    def _sync_species_editor_asset_refs(self):
        """Pull freshly saved Pixel Studio references into the open preview."""
        if self.world_model is None:
            return False
        live = self.world_model.get_entity(self.species_id)
        if not isinstance(live, dict):
            return False
        state = self._ensure_species_editor()
        changed = False
        for field_name in (
            "plant_root_module_ref",
            "plant_stem_module_ref",
            "plant_branch_module_ref",
            "plant_leaf_module_ref",
            "plant_flower_module_ref",
            "plant_calyx_module_ref",
            "plant_fruit_module_ref",
        ):
            if live.get(field_name) == state["working_entity"].get(field_name):
                continue
            state["working_entity"][field_name] = live.get(field_name)
            state["original_entity"][field_name] = live.get(field_name)
            changed = True
        if changed:
            self._invalidate_species_editor_preview()
            state["status"] = "Pixel module updated in the mature preview."
        return changed

    def get_species_editor_previews(self):
        import json
        from simulations.species.species_editor import preview_entity
        state = self._ensure_species_editor()
        self._sync_species_editor_asset_refs()
        if state.get("preview_deferred") and self._species_editor_last_previews:
            return list(self._species_editor_last_previews)
        signature = json.dumps(state["working_entity"], sort_keys=True, default=str)
        mode = state.get("preview_mode", "typical")
        count = int(state.get("variation_count", 4)) if mode == "variation" else 1
        previews = []
        for index in range(count):
            key = (signature, mode, index)
            preview = self._species_editor_preview.get(key)
            if preview is None:
                preview = SpeciesSimulation(
                    species_entity=preview_entity(state, mode, index),
                    species_id=self.species_id,
                    seed=303 + index,
                    asset_store=self.asset_store,
                )
                # Build the requested mature preview once. Calling set_lod()
                # and then set_age() would regenerate this large tree twice.
                preview.lod = 1 if mode == "variation" else 2
                preview.age_days = preview.mature_age_days
                preview.render_snapshot = preview.generate_snapshot(preview.age_days, preview.lod)
                preview.bounds = preview._bounds_for_camera(preview.render_snapshot.bounds_m)
                self._species_editor_preview[key] = preview
            previews.append(preview)
        if len(self._species_editor_preview) > 20:
            self._species_editor_preview = {key: self._species_editor_preview[key] for key in list(self._species_editor_preview)[-12:]}
        self._species_editor_last_previews = list(previews)
        return previews

    def get_species_editor_preview(self):
        return self.get_species_editor_previews()[0]

    def _invalidate_species_editor_preview(self):
        self._species_editor_preview = {}
        self._species_editor_last_previews = None

    def save_species_editor(self):
        import copy
        state = self._ensure_species_editor()
        entity = copy.deepcopy(state["working_entity"])
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is not None and not loader.persist_entity(entity):
            state["status"] = "Could not save the species to the ontology."
            return False
        if self.world_model is not None and hasattr(self.world_model, "mark_repository_changed"):
            self.world_model.mark_repository_changed()
        self.species_entity = entity
        self.blueprint = PlantBlueprint.from_species_entity(entity, self.species_id)
        self.age_days = self.mature_age_days
        self.render_snapshot = self.generate_snapshot(self.age_days, self.lod)
        self.bounds = self._bounds_for_camera(self.render_snapshot.bounds_m)
        state["original_entity"] = copy.deepcopy(entity)
        state["working_entity"] = copy.deepcopy(entity)
        state["dirty"] = False
        state["undo_stack"] = []
        state["redo_stack"] = []
        state["status"] = "Saved to the live species record."
        self._invalidate_species_editor_preview()
        return True

    def revert_species_editor(self):
        import copy
        from simulations.species.species_editor import record_history
        state = self._ensure_species_editor()
        record_history(state)
        state["working_entity"] = copy.deepcopy(state["original_entity"])
        state["dirty"] = False
        state["active_range"] = None
        state["status"] = "Unsaved field changes reverted; the reference image is still local."
        self._invalidate_species_editor_preview()
        return True

    def consume_pending_navigation_action(self):
        action = self.pending_navigation_action
        self.pending_navigation_action = None
        return action

    def consumes_global_keydown(self):
        return self.diagnostic_view == "editor"

    def handle_event(self, event):
        import pygame
        from simulations.species.species_editor import load_reference_from_clipboard, redo, undo
        if self.diagnostic_view != "editor":
            return False
        state = self._ensure_species_editor()
        if event.type == pygame.KEYDOWN:
            modifiers = getattr(event, "mod", 0)
            if event.key == pygame.K_v and modifiers & pygame.KMOD_CTRL:
                return load_reference_from_clipboard(state)
            if event.key == pygame.K_s and modifiers & pygame.KMOD_CTRL:
                return self.save_species_editor()
            if event.key == pygame.K_z and modifiers & pygame.KMOD_CTRL:
                changed = redo(state) if modifiers & pygame.KMOD_SHIFT else undo(state)
                if changed:
                    self._invalidate_species_editor_preview()
                return True
            if event.key == pygame.K_y and modifiers & pygame.KMOD_CTRL:
                changed = redo(state)
                if changed:
                    self._invalidate_species_editor_preview()
                return True
            if event.key == pygame.K_ESCAPE:
                return self.set_active_simulation_panel_tab("individual")
            if event.key == pygame.K_BACKSPACE:
                state["query"] = state.get("query", "")[:-1]
                state["scroll"] = 0
                return True
            text = str(getattr(event, "unicode", "") or "")
            if text.isprintable() and not modifiers & (pygame.KMOD_CTRL | pygame.KMOD_ALT):
                state["query"] = (state.get("query", "") + text)[:48]
                state["scroll"] = 0
                return True
        if event.type == pygame.MOUSEWHEEL:
            state["scroll"] = max(0, int(state.get("scroll", 0)) - int(event.y) * 2)
            return True
        return False

    def _editor_hitbox_at(self, screen_pos):
        for hitbox in reversed(self._species_editor_hitboxes):
            rect = hitbox.get("rect")
            if rect is not None and rect.collidepoint(screen_pos):
                return hitbox
        return None

    def _set_editor_range_from_pointer(self, active, mouse_x):
        from simulations.species.species_editor import set_range_handle
        rect = active["rect"]
        value = (float(mouse_x) - rect.x) / max(1, rect.width)
        state = self._ensure_species_editor()
        changed = set_range_handle(state, active["field"], active["handle"], value, record=False)
        if changed and not state.get("preview_deferred"):
            self._invalidate_species_editor_preview()
        return changed

    def handle_pointer_motion(self, event, camera, screen_pos):
        if self.diagnostic_view != "editor":
            return False
        state = self._ensure_species_editor()
        active = state.get("active_range")
        if active and getattr(event, "buttons", (False,))[0]:
            return self._set_editor_range_from_pointer(active, screen_pos[0])
        return False

    def handle_pointer_event(self, event, camera, screen_pos):
        import pygame
        from simulations.species.species_editor import (
            cycle_choice, load_reference_from_clipboard, range_value, record_history, redo, undo,
        )
        if self.diagnostic_view != "editor" or event.button not in (1, 3):
            return False
        state = self._ensure_species_editor()
        if event.type == pygame.MOUSEBUTTONUP:
            if state.get("active_range"):
                state["preview_deferred"] = False
                self._invalidate_species_editor_preview()
            state["active_range"] = None
            return True
        if event.type != pygame.MOUSEBUTTONDOWN:
            return False
        hitbox = self._editor_hitbox_at(screen_pos)
        if hitbox is None:
            return False
        kind = hitbox.get("kind")
        if kind == "paste":
            return load_reference_from_clipboard(state)
        if kind == "save":
            return self.save_species_editor()
        if kind == "revert":
            return self.revert_species_editor()
        if kind in {"undo", "redo"}:
            changed = undo(state) if kind == "undo" else redo(state)
            if changed:
                self._invalidate_species_editor_preview()
            return True
        if kind == "preview_mode":
            state["preview_mode"] = hitbox["mode"]
            state["status"] = f"Preview mode: {hitbox['mode']}."
            self._species_editor_last_previews = None
            return True
        if kind == "field_group":
            state["field_group"] = hitbox["group"]
            state["scroll"] = 0
            return True
        if kind == "preview_only":
            state["preview_only"] = not state.get("preview_only", True)
            state["scroll"] = 0
            return True
        if kind == "reference_control":
            control = hitbox.get("control")
            if control == "overlay":
                state["reference_overlay"] = not state.get("reference_overlay", False)
            elif control == "silhouette":
                state["reference_silhouette"] = not state.get("reference_silhouette", False)
            elif control == "opacity":
                state["reference_opacity"] = max(.1, min(.9, state.get("reference_opacity", .35) + hitbox.get("delta", 0)))
            elif control == "scale":
                state["reference_scale"] = max(.35, min(2.5, state.get("reference_scale", 1.) + hitbox.get("delta", 0)))
            elif control == "move":
                offset = state.setdefault("reference_offset", [0., 0.])
                if hitbox.get("center"):
                    offset[:] = [0., 0.]
                else:
                    offset[0] = max(-.8, min(.8, offset[0] + hitbox.get("dx", 0)))
                    offset[1] = max(-.8, min(.8, offset[1] + hitbox.get("dy", 0)))
            return True
        if kind == "asset":
            self.pending_navigation_action = {
                "id": "open_species_asset_editor",
                "entity_id": self.species_id,
                "asset_role": hitbox.get("role"),
            }
            return True
        if kind == "card":
            state["selected_field"] = hitbox.get("field")
            state["status"] = "This field uses the full Species Card editor."
            return True
        if kind == "choice":
            changed = cycle_choice(state, hitbox["field"], -1 if event.button == 3 else 1)
            if changed:
                self._invalidate_species_editor_preview()
            return True
        if kind == "range":
            record_history(state)
            current = range_value(state, hitbox["field"])
            rect = hitbox["rect"]
            value = (screen_pos[0] - rect.x) / max(1, rect.width)
            handle = min(("min", "typical", "max"), key=lambda name: abs(float(current[name]) - value))
            active = {"field": hitbox["field"], "handle": handle, "rect": rect}
            state["active_range"] = active
            state["preview_deferred"] = True
            return self._set_editor_range_from_pointer(active, screen_pos[0])
        return False

    def handle_forest_key(self, event):
        import pygame
        if self.diagnostic_view != "forest" or event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_s:
            values = ["dense", "medium", "open"]
            self.set_forest_settings(spacing=values[(values.index(self.forest_spacing)+1)%3])
        elif event.key == pygame.K_t:
            values = [None, "low", "medium", "high"]
            self.set_forest_settings(tolerance=values[(values.index(self.forest_tolerance)+1)%4])
        elif event.key == pygame.K_v:
            values = ["light_map", "isometric"]
            self.forest_view_style = values[(values.index(self.forest_view_style)+1)%2]
        else:
            return False
        return True

    @property
    def suppress_global_overlays(self):
        # Diagnostic canvases reserve their own header and footer. The global
        # scale/FPS overlays would otherwise sit on top of gallery cells.
        return self.diagnostic_view != "individual"

    def update(self, dt):
        self.sim_manager.update(dt)
        if self.diagnostic_view in {"forest", "architecture", "editor"}:
            # Forest experiments use fixed ages for paired comparisons.
            return
        # A preview advances slowly enough that a user can watch branches form.
        elapsed = max(0.0, float(dt)) * 0.5
        if self.blueprint.growth.get("shoot_distribution_grammar"):
            # Detailed crowns need not rebuild for every rendered frame.
            self._pending_growth_days = getattr(self, "_pending_growth_days", 0.0) + elapsed
            if self._pending_growth_days < 0.5:
                return
            elapsed = self._pending_growth_days
            self._pending_growth_days = 0.0
        self.set_age(self.age_days + elapsed)

    def set_age(self, age_days):
        self._pending_growth_days = 0.0
        self.age_days = max(0.0, min(float(age_days), self.max_age_days))
        self.render_snapshot = self.generate_snapshot(self.age_days, self.lod)
        self.bounds = self._bounds_for_camera(self.render_snapshot.bounds_m)

    def adjust_age(self, delta_days):
        self.set_age(self.age_days + float(delta_days))
        return True

    def simulate_days(self, days, environment=None, sample_every_days=1.0):
        """Advance a representative plant and return compact telemetry rows."""

        days = max(0.0, float(days))
        sample_every_days = max(0.1, float(sample_every_days))
        environment = environment if isinstance(environment, dict) else {}
        start_age = self.age_days
        samples = []
        elapsed = 0.0
        while elapsed <= days + 1e-9:
            self.set_age(start_age + elapsed)
            summary = self.get_growth_summary()
            outcome = self.get_ecological_outcome(environment)
            samples.append({
                "elapsed_days": round(elapsed, 3),
                "age_days": round(self.age_days, 3),
                "life_phase": summary.get("life_phase"),
                "maturity": summary.get("maturity", 0.0),
                "placement_count": summary.get("placement_count", 0),
                "leaf_count": summary.get("leaf_count", 0),
                "leaf_cluster_count": summary.get("leaf_cluster_count", 0),
                "estimated_leaf_count": summary.get("estimated_leaf_count", 0),
                "stem_count": summary.get("stem_count", 0),
                "vitality": outcome.get("vitality", 0.0),
                "fecundity": outcome.get("fecundity", 0.0),
                "mortality_risk": outcome.get("mortality_risk", 0.0),
            })
            elapsed = round(elapsed + sample_every_days, 6)
        self.set_age(start_age + days)
        return samples

    def set_lod(self, lod):
        self.lod = max(0, min(2, int(lod)))
        self._diagnostic_cases = None
        self.render_snapshot = self.generate_snapshot(self.age_days, self.lod)
        return True

    @property
    def mature_age_days(self):
        return max(1.0, float(self.blueprint.growth.get("maturity_days", 90.0) or 90.0))

    @property
    def life_history_profile(self):
        profile = self.blueprint.growth.get("life_history")
        if isinstance(profile, dict) and profile.get("class"):
            return dict(profile)
        return plant_life_history_profile(
            self.species_entity.get("plant_lifespan"),
            self.mature_age_days,
        )

    @property
    def max_age_days(self):
        profile = self.life_history_profile
        configured_limit = profile.get("age_limit_days")
        if configured_limit is None:
            # Perennials have no hard terminal age in this prototype, but the
            # interactive preview still needs a bounded exploration window.
            return max(
                self.mature_age_days * 1.5,
                float(profile.get("senescence_start_days", self.mature_age_days)) + 3650.0,
            )
        return max(self.mature_age_days, float(configured_limit))

    def life_state(self, age_days=None):
        """Return the transient life phase used by growth and outcome code."""

        age_days = self.age_days if age_days is None else max(0.0, float(age_days))
        if self.blueprint.growth.get("fungal_grammar_version"):
            from simulations.species.fungal_growth import fungal_life_state
            return fungal_life_state(self.blueprint.growth, age_days)
        from simulations.species.plant_reproduction import seasonal_reproductive_state
        seasonal = seasonal_reproductive_state(self.blueprint.growth, age_days, self.mature_age_days)
        if seasonal is not None:
            return seasonal
        profile = self.life_history_profile
        maturity_days = self.mature_age_days
        reproductive_start = max(
            maturity_days,
            float(profile.get("reproductive_start_days", maturity_days)),
        )
        senescence_start = max(
            reproductive_start,
            float(profile.get("senescence_start_days", reproductive_start)),
        )
        age_limit = profile.get("age_limit_days")
        if profile.get("terminal_reproduction") and age_limit is not None and age_days >= float(age_limit):
            return {
                "phase": "dead",
                "reproductive_factor": 0.0,
                "fruiting_factor": 0.0,
                "senescence_factor": 1.0,
                "active_factor": 0.0,
            }
        if age_days < maturity_days:
            phase = "juvenile"
        elif age_days < reproductive_start:
            phase = "mature_vegetative"
        elif age_days < senescence_start:
            phase = "reproductive"
        else:
            phase = "senescent"

        if phase == "reproductive":
            reproductive_factor = 1.0
            senescence_factor = 0.0
            # Fruit/seed cones take time to develop after flowering starts
            # -- a plant that has *just* reached reproductive age has
            # flowers but nothing has set fruit yet, so this ramps from 0
            # across the reproductive phase rather than snapping to 1.0
            # alongside reproductive_factor.
            phase_span = max(1.0, senescence_start - reproductive_start)
            fruiting_factor = min(1.0, (age_days - reproductive_start) / phase_span)
        elif phase == "senescent":
            if age_limit is None:
                decline_window = max(365.0, float(profile.get("cycle_days", 365.0)))
                senescence_factor = min(1.0, (age_days - senescence_start) / decline_window)
            else:
                decline_window = max(1.0, float(age_limit) - senescence_start)
                senescence_factor = min(1.0, (age_days - senescence_start) / decline_window)
            reproductive_factor = max(0.0, 1.0 - senescence_factor)
            # Mature fruit/cones linger after flowering declines (a real
            # aging conifer still carries old woody cones) rather than
            # disappearing in lockstep with reproductive_factor.
            fruiting_factor = max(0.0, 1.0 - senescence_factor * 0.4)
        else:
            reproductive_factor = 0.0
            senescence_factor = 0.0
            fruiting_factor = 0.0
        return {
            "phase": phase,
            "reproductive_factor": round(reproductive_factor, 4),
            "fruiting_factor": round(fruiting_factor, 4),
            "senescence_factor": round(senescence_factor, 4),
            "active_factor": round(max(0.0, 1.0 - senescence_factor * 0.55), 4),
        }

    def _maturity(self, age_days):
        return max(0.0, min(1.0, float(age_days) / self.mature_age_days))

    def _bounds_for_camera(self, bounds):
        min_x, max_x, min_y, max_y, min_z, max_z = bounds
        projected_min_x = min_x + min_y * SCREEN_DEPTH_PROJECTION
        projected_max_x = max_x + max_y * SCREEN_DEPTH_PROJECTION
        min_x, max_x = min(projected_min_x, projected_max_x), max(projected_min_x, projected_max_x)
        if (self.blueprint.growth.get("growth_behaviour") == "surface_covering"
                or self.blueprint.growth.get("fungal_grammar_version")):
            margin=max(.005,(max_x-min_x)*.1,(max_z-min_z)*.1)
            return {"min_x":min_x-margin,"max_x":max_x+margin,
                    "min_y":-(max_z+margin),"max_y":-(min_z-margin)}
        plant_width = max(0.1, max_x - min_x)
        self.height_reference_x = max_x + max(0.55, plant_width * 0.18)
        reference_half_width = 0.14
        min_x = min(min_x, self.height_reference_x - reference_half_width)
        max_x = max(max_x, self.height_reference_x + reference_half_width)
        max_z = max(max_z, self.HUMAN_REFERENCE_HEIGHT_M)
        margin = max(0.2, (max_x - min_x) * 0.16, (max_z - min_z) * 0.16)
        return {
            "min_x": min_x - margin,
            "max_x": max_x + margin,
            # The application camera uses screen-down world y, while plant
            # model space is z-up. Store camera-space bounds with that axis
            # flipped; diagnostic cameras use snapshot model bounds directly.
            "min_y": -(max_z + margin),
            "max_y": -(min_z - margin),
        }

    def _module_table(self, lod):
        module_ids = {self.blueprint.root_module_id, "stem_section", "root_section", "root_support"}
        if self.blueprint.growth.get("plant_life_form") == "geophyte":
            module_ids.update({"renewal_organ", "renewal_bud"})
        if (lod >= 1 or self.blueprint.growth.get("shoot_distribution_grammar")
                or self.blueprint.growth.get("shrub_cane_grammar_version")):
            module_ids.add("branch_section")
        if lod >= 1 or self.blueprint.growth.get("emergent_rosette_version") or self.blueprint.growth.get('sympodial_herb_version'):
            module_ids.update({"leaf", "flower", "fruit"})
        if self.blueprint.growth.get('sympodial_herb_version') or self.blueprint.growth.get('paniculate_rosette_version') or self.blueprint.growth.get('tufted_sedge_version'):
            module_ids.add('branch_section')
            module_ids.update({'leaf','flower','fruit'})
        if self.blueprint.growth.get('branched_vine_version'):
            module_ids.add('branch_section')
        if self.blueprint.growth.get('cyme_herb_version'):
            module_ids.update({'branch_section','leaf','flower','fruit'})
        modules = {
            module.id: module.to_dict()
            for module in self.blueprint.modules
            if module.id in module_ids
        }
        if self.blueprint.growth.get('columnar_version'):
            modules.update({module.id:module.to_dict() for module in self.blueprint.modules
                            if module.id in {'branch_section','flower','fruit','leaf'}})
        if self.blueprint.growth.get("woody_spur_version"):
            module_ids.update({"leaf", "flower", "fruit", "calyx"})
            modules.update({m.id:m.to_dict() for m in self.blueprint.modules if m.id in module_ids})
        # Frozen blueprints authored before root growth remain portable when
        # their root traits now generate section placements.
        root_asset = self.blueprint.module("root")
        modules.setdefault("root_section", PlantModule(
            "root_section", "root_section", length_m=0.1, radius_m=0.01,
            asset_ref=getattr(root_asset, "asset_ref", None)).to_dict())
        modules.setdefault("root_support", PlantModule(
            "root_support", "stem_section", length_m=0.1, radius_m=0.02).to_dict())
        return modules

    def _add(self, placements, module_id, parent, x, y, z, rotation, scale, level, placement_paths=None, path=None):
        placements.append([
            module_id,
            int(parent),
            round(float(x), 4),
            round(float(y), 4),
            round(float(z), 4),
            round(float(rotation) % 360.0, 3),
            round(float(scale), 4),
            int(level),
        ])
        placement_index = len(placements) - 1
        if placement_paths is not None and path:
            placement_paths[str(placement_index)] = [
                [round(float(point[0]), 4), round(float(point[1]), 4), round(float(point[2]), 4)]
                for point in path
                if isinstance(point, (list, tuple)) and len(point) >= 3
            ]
        return placement_index

    def _growth_origin(self, placements, root_z=0.0):
        """Create the soil anchor and return the parent for aerial shoots.

        Raunkiaer life form describes renewal-bud position, not a season or an
        organ's storage physiology.  Geophytes therefore gain a below-ground
        renewal origin while other life forms retain the historical surface
        origin.  ``belowground_storage`` may further name the supporting organ
        (for example a corm), but is not inferred from geophytism alone.
        """

        crown = self._add(placements, "root", -1, 0.0, 0.0, root_z, 0.0, 1.0, 0)
        if self.blueprint.growth.get("plant_life_form") != "geophyte":
            return crown

        max_height = max(0.1, float(self.blueprint.growth.get("max_height_m", 1.0) or 1.0))
        # Bud depth is currently a transparent runtime default because the
        # ontology stores the life-form class but no measured renewal depth.
        depth = max(0.025, min(0.12, max_height * 0.08))
        organ_scale = max(0.7, min(1.8, max_height / 0.75))
        organ = self._add(
            placements, "renewal_organ", crown,
            0.0, 0.0, root_z - depth, 0.0, organ_scale, 0,
        )
        return self._add(
            placements, "renewal_bud", organ,
            0.0, 0.0, root_z - depth * 0.62, 0.0, organ_scale, 0,
        )

    @staticmethod
    def _normalise_vector(vector, fallback=(0.0, 0.0, 1.0)):
        length = math.sqrt(sum(float(value) * float(value) for value in vector))
        if length < 1e-9:
            return tuple(float(value) for value in fallback)
        return tuple(float(value) / length for value in vector)

    @classmethod
    def _orientation_frame(cls, forward):
        forward = cls._normalise_vector(forward)

        # Choose a reference that is not parallel to forward, then construct
        # a right-handed orthonormal frame: right x up = forward.
        reference_up = (0.0, 0.0, 1.0)
        if abs(forward[2]) > 0.92:
            reference_up = (0.0, 1.0, 0.0)
        right = cls._normalise_vector((
            reference_up[1] * forward[2] - reference_up[2] * forward[1],
            reference_up[2] * forward[0] - reference_up[0] * forward[2],
            reference_up[0] * forward[1] - reference_up[1] * forward[0],
        ), fallback=(1.0, 0.0, 0.0))
        up = cls._normalise_vector((
            forward[1] * right[2] - forward[2] * right[1],
            forward[2] * right[0] - forward[0] * right[2],
            forward[0] * right[1] - forward[1] * right[0],
        ))
        return {
            "forward": [round(value, 5) for value in forward],
            "right": [round(value, 5) for value in right],
            "up": [round(value, 5) for value in up],
        }

    @classmethod
    def _placement_orientation(cls, placements, index):
        """Return a stable 3D orientation frame for one module placement.

        The procedural grammar still uses a projected azimuth for convenient
        2D sprite placement.  The saved frame is the authoritative model
        orientation, so later renderers can choose a different projection or
        a true 3D view without regenerating the plant.
        """

        placement = placements[index]
        kind, parent = placement[0], int(placement[1])
        x, y, z = (float(placement[2]), float(placement[3]), float(placement[4]))
        if 0 <= parent < len(placements):
            parent_position = placements[parent][2:5]
            forward = (
                x - float(parent_position[0]),
                y - float(parent_position[1]),
                z - float(parent_position[2]),
            )
        elif kind == "root":
            forward = (0.0, 0.0, 1.0)
        else:
            angle = math.radians(float(placement[5]))
            forward = (math.cos(angle), math.sin(angle), 0.0)
        return cls._orientation_frame(forward)

    @staticmethod
    def _add_leaf_cluster(leaf_clusters, host_placement, x, y, z, estimated_count, leaf_area_m2, branch_order, visual_density=1.0, *, allow_empty=False):
        """Record a calculative leaf cohort without expanding every leaf."""

        if leaf_clusters is None:
            return None
        cluster_id = f"leaf_cluster_{len(leaf_clusters) + 1:04d}"
        leaf_clusters.append({
            "id": cluster_id,
            "host_placement_index": int(host_placement),
            "position_m": [round(float(x), 4), round(float(y), 4), round(float(z), 4)],
            "estimated_leaf_count": max(0 if allow_empty else 1, int(round(estimated_count))),
            "leaf_area_m2": round(max(0.0, float(leaf_area_m2)), 6),
            "branch_order": int(branch_order),
            "health": 1.0,
            "phenology_factor": 1.0,
            "visual_density": round(max(0.0, min(1.0, float(visual_density))), 4),
        })
        return cluster_id

    @staticmethod
    def _curved_segment_path(start, end, bend=0.02, direction=1.0):
        """Return a few points for a gently organic segment."""

        start = tuple(float(value) for value in start)
        end = tuple(float(value) for value in end)
        dx, dy = end[0] - start[0], end[1] - start[1]
        horizontal = math.hypot(dx, dy)
        perpendicular = (-dy / horizontal, dx / horizontal) if horizontal > 1e-6 else (1.0, 0.0)
        points = []
        for fraction in (0.38, 0.72, 1.0):
            offset = float(bend) * math.sin(math.pi * fraction) * float(direction)
            points.append((
                start[0] + dx * fraction + perpendicular[0] * offset,
                start[1] + dy * fraction + perpendicular[1] * offset,
                start[2] + (end[2] - start[2]) * fraction,
            ))
        return points

    def _grow_bolting_rosette(self, placements, maturity, lod, age_days,
                             flowering_factor, attachment_points, placement_paths):
        from simulations.species.rosette_shoots import build_rosette_shoots, rosette_bolting_factor

        root = self._growth_origin(placements)
        growth = self.blueprint.growth
        nodes, stats = build_rosette_shoots(
            growth, maturity, rosette_bolting_factor(growth, age_days), flowering_factor, self.seed,
        )
        indices = {}
        leaf = self.blueprint.module("leaf")
        area_per_leaf = max(0.0005, max(0.01, leaf.length_m) * max(0.005, leaf.radius_m) * 1.8)
        stats["leaf_area_m2"] = round(sum(
            round(area_per_leaf * node["scale"], 6) for node in nodes if node["kind"] == "leaf"
        ), 6)
        for ordinal, node in enumerate(nodes):
            if node["min_lod"] > lod:
                continue
            parent = root if node["parent"] < 0 else indices[node["parent"]]
            p = node["position"]
            path = None
            if node["kind"] in {"stem_section", "branch_section"}:
                path = self._curved_segment_path(placements[parent][2:5], p, bend=0.004,
                                                 direction=-1.0 if ordinal % 2 else 1.0)
            index = self._add(placements, node["kind"], parent, *p, node["angle"],
                              node["scale"], node["level"], placement_paths=placement_paths, path=path)
            indices[ordinal] = index
            if node["kind"] == "leaf" and attachment_points is not None:
                attachment_points.append({"stem_placement_index": parent,
                                          "leaf_placement_index": index, "socket": "leaf",
                                          "position_m": list(p), "cohort": node["role"]})
                # Coincident on-axis sockets still need an outward orientation.
                rad = math.radians(node["angle"])
                self._placement_orientation_hints[str(index)] = self._orientation_frame(
                    (math.cos(rad), math.sin(rad), 0.30 if node["role"] == "stem_leaf" else 0.18))
        return stats

    def _grow_rosette(self, placements, maturity, lod, flowering_factor=0.0,
                      fruiting_factor=0.0,
                      age_days=0.0, attachment_points=None, placement_paths=None):
        if self.blueprint.growth.get("rosette_shoot_grammar_version"):
            return self._grow_bolting_rosette(placements, maturity, lod, age_days,
                                             flowering_factor, attachment_points, placement_paths)
        root = self._growth_origin(placements)
        count = max(3, int(round(5 + maturity * 7)))
        canonical_count = count
        leaf_module = self.blueprint.module("leaf")
        area_per_leaf = max(0.0005, max(0.01, leaf_module.length_m)
                            * max(0.005, leaf_module.radius_m) * 1.8)
        canonical_leaf_area = sum(
            area_per_leaf * (0.60 + 0.40 * maturity)
            * (0.52 + 0.56 * index / max(1, canonical_count - 1))
            for index in range(canonical_count)
        )
        if lod == 0:
            count = min(count, 3)
        for index in range(count):
            rank = index / max(1, count - 1)
            angle = index * 137.5 + 19.0 * maturity
            # A rosette leaf is attached at the compact basal crown; its
            # blade extends outward from that socket in the renderer.  The
            # old radius (up to 0.26 m) treated each socket like a leaf tip,
            # leaving an implausible empty ring in every basal rosette and
            # lifting the attachment points far above the soil surface.
            radius = (0.006 + 0.018 * maturity) * (0.55 + 0.45 * rank)
            # A sparse rosette exposes individual leaf cohorts, so give the
            # same authored module a visibly broader juvenile-to-mature size
            # range instead of stamping twelve near-identical copies.
            leaf_scale = (0.60 + 0.40 * maturity) * (0.52 + 0.56 * rank)
            self._add(
                placements,
                "leaf" if lod >= 1 else "stem_section",
                root,
                math.cos(math.radians(angle)) * radius,
                math.sin(math.radians(angle)) * radius,
                0.008 + 0.014 * maturity * (0.65 + 0.35 * rank),
                angle,
                leaf_scale,
                1,
            )

        growth = self.blueprint.growth
        reproductive_mode = str(growth.get("reproductive_mode") or "other_unknown")
        structure = str(growth.get("reproductive_structure") or "other_unknown")
        flowering_position = str(growth.get("flowering_position") or "other_unknown")
        can_flower = reproductive_mode in {"sexual", "both", "apomictic"}
        terminal = flowering_position in {"terminal", "mixed"}
        lateral_single_flowers = flowering_position == "lateral" and structure == "flower"
        raceme_fruit = bool(growth.get("rosette_raceme_profile") and structure == "flower")
        scape_profile = growth.get("scape_rosette_profile")
        scape_fruit = bool(scape_profile and growth.get("reproductive_profile")
                           and structure == "capitulum")
        single_flower_fruit = lateral_single_flowers and can_flower
        can_scape_fruit = raceme_fruit or scape_fruit or single_flower_fruit
        scape_count = 0
        if (lod >= 1 and can_flower and (terminal or lateral_single_flowers)
                and structure != "other_unknown"
                and (flowering_factor > 0.0 or (can_scape_fruit and fruiting_factor > 0.0))):
            max_height = max(0.14, float(growth.get("max_height_m", 0.4) or 0.4))
            scape_count = (max(1, round(scape_profile["scape_count"] * maturity)) if scape_profile
                           else 1 + int(maturity >= 0.75) + int(flowering_factor >= 0.65))
            for scape_index in range(scape_count):
                scape_angle = 52.0 + scape_index * 137.5
                scape_radius = ((0.015 + scape_index * 0.009) if lateral_single_flowers
                                else 0.006 + scape_index * 0.004)
                scape_height = min(
                    max_height,
                    max(0.14, max_height * (0.58 + 0.27 * maturity) *
                        (0.82 + 0.18 * ((scape_index * 7) % max(1, scape_count)) / max(1, scape_count - 1))
                        if scape_profile else
                        max_height * (0.58 + 0.27 * maturity) * (0.94 + 0.03 * scape_index)),
                )
                reach = (scape_profile["scape_spread_m"] * scape_height / max_height
                         if scape_profile else scape_radius)
                x = math.cos(math.radians(scape_angle)) * reach
                y = math.sin(math.radians(scape_angle)) * reach
                scape = self._add(
                    placements,
                    "stem_section",
                    root,
                    x,
                    y,
                    scape_height,
                    scape_angle,
                    0.55 + 0.25 * flowering_factor,
                    1,
                    placement_paths=placement_paths,
                    path=(self._curved_segment_path(placements[root][2:5], (x, y, scape_height),
                                                    bend=0.002, direction=1.0)
                          if scape_profile else None),
                )
                if lod >= 2:
                    fruit_score = ((scape_index + 1) * 0.61803398875) % 1.0
                    kind = ("fruit" if can_scape_fruit and fruiting_factor > 0.35
                            and fruit_score < fruiting_factor else "flower")
                    if kind == "flower" and flowering_factor <= 0.0:
                        continue
                    self._add(
                        placements,
                        kind,
                        scape,
                        x,
                        y,
                        scape_height + 0.001,
                        0.0,
                        0.72 + 0.28 * (fruiting_factor if kind == "fruit" else flowering_factor),
                        2,
                    )
        return {"estimated_leaf_count": canonical_count,
                "leaf_area_m2": round(canonical_leaf_area, 6),
                **({"scape_rosette_version": scape_profile["version"],
                    "scape_count": max(1, round(scape_profile["scape_count"] * maturity)),
                    "scape_flower_head_count": sum(p[0] == "flower" for p in placements),
                    "scape_fruit_head_count": sum(p[0] == "fruit" for p in placements)}
                   if scape_profile else {})}

    def _grow_fern(
        self,
        placements,
        maturity,
        lod,
        rng,
        attachment_points=None,
        placement_paths=None,
        leaf_clusters=None,
        rooting_contacts=None,
    ):
        """Grow botanical fronds from a crown or concealed rhizome sockets.

        A frond is one leaf placement. Its pinnae and pinnules are internal
        morphology rendered from ``leaf_division_order``; they are not extra
        plant leaves or stem nodes. Rhizomatous geophytes distribute those
        solitary fronds along a bounded underground axis, while other ferns
        retain a compact crown.
        """

        growth = self.blueprint.growth
        max_height = max(0.18, float(growth.get("max_height_m", 1.25) or 1.25))
        from simulations.species.fern_fronds import frond_centerline
        leaf_length = max(0.08, float(growth.get("leaf_length_m", max_height * 0.72) or max_height * 0.72))
        division_order = max(1, min(4, int(growth.get("leaf_division_order", 1) or 1)))
        primary_pinnae = max(2, min(200, int(growth.get("leaflet_count", 12) or 12)))
        primary_pinna_arrangement = str(growth.get("frond_pinna_arrangement", growth.get("leaf_arrangement")) or "other_unknown")
        storage = {
            str(item).lower().replace("-", "_").replace(" ", "_")
            for item in (growth.get("belowground_storage") or [])
        }
        spread_class = str(growth.get("clonal_spread") or "other_unknown")
        # Low vegetative propagation does not imply creeping solitary fronds.
        # An explicitly basal tuft still arises from one compact crown.
        compact_tuft = growth.get("leaf_attachment_pattern") == "basal_tuft" or growth.get("leaf_distribution") == "basal_tuft"
        rhizome_distributed = "rhizome" in storage and spread_class != "none" and not compact_tuft
        mature_fronds = {
            "none": 1,
            "low": 3,
            "moderate": 5,
            "high": 8,
            "other_unknown": 5,
        }.get(spread_class, 5) if rhizome_distributed else 9
        if rhizome_distributed and spread_class != "none":
            density_range = growth.get("architecture_ranges", {}).get("leaf_cluster_density", {})
            if density_range.get("status") != "runtime_default":
                density = float(growth.get("leaf_cluster_density", 0.5))
                density = max(0.0, min(1.0, density)) if math.isfinite(density) else 0.5
                # A frond is one leaf cluster on a rhizome socket. Use the
                # authored visual density to vary bounded socket abundance,
                # without treating clonal spread rate as measured stand density.
                mature_fronds = max(1, min(24, round(mature_fronds * (0.25 + 2.0 * density))))
        canonical_fronds = max(1, 1 + int(round((mature_fronds - 1) * maturity)))
        visible_fronds = {
            0: 0,
            1: max(1, math.ceil(canonical_fronds * 0.5)),
            2: canonical_fronds,
        }[lod]
        root = self._growth_origin(placements)
        rhizome_axis_length = 0.0
        sockets = []

        if rhizome_distributed:
            reach_factor = {
                "low": 0.52,
                "moderate": 0.78,
                "high": 1.0,
                "other_unknown": 0.68,
            }.get(spread_class, 0.68)
            reach = min(2.4, max(0.35, max_height * 0.92)) * reach_factor * max(0.12, maturity)
            arm_count = min(6, max(1, math.ceil(canonical_fronds / 3)))
            arm_sizes = [canonical_fronds // arm_count for _ in range(arm_count)]
            for index in range(canonical_fronds % arm_count):
                arm_sizes[index] += 1
            phase = rng.uniform(0.0, 360.0)
            for arm_index, nodes_on_arm in enumerate(arm_sizes):
                parent = root
                previous = (0.0, 0.0, -0.075)
                base_angle = phase + arm_index * 360.0 / arm_count
                for node_index in range(nodes_on_arm):
                    fraction = (node_index + 1) / max(1, nodes_on_arm)
                    angle = base_angle + 8.0 * math.sin(node_index * 1.2 + arm_index)
                    radius = reach * fraction
                    x = math.cos(math.radians(angle)) * radius
                    y = math.sin(math.radians(angle)) * radius
                    endpoint = (x, y, -0.075)
                    rhizome_axis_length += math.dist(previous, endpoint)
                    rhizome = self._add(
                        placements,
                        "branch_section",
                        parent,
                        x,
                        y,
                        -0.075,
                        angle,
                        0.72 + 0.28 * maturity,
                        1,
                        placement_paths=placement_paths,
                        path=self._curved_segment_path(
                            previous,
                            endpoint,
                            bend=0.025 * reach_factor,
                            direction=-1.0 if (node_index + arm_index) % 2 else 1.0,
                        ),
                    )
                    root_tip_z = -0.105
                    root_support = self._add(
                        placements,
                        "root_support",
                        rhizome,
                        x,
                        y,
                        root_tip_z,
                        angle,
                        0.16 + 0.08 * maturity,
                        2,
                    )
                    if rooting_contacts is not None:
                        rooting_contacts.append({
                            "parent_index": root_support,
                            "position": (x, y, root_tip_z),
                        })
                    sockets.append((rhizome, x, y, angle))
                    parent = rhizome
                    previous = endpoint
        else:
            crown_phase = rng.uniform(0.0, 360.0)
            sockets = [
                (root, 0.0, 0.0, crown_phase + index * 137.5)
                for index in range(canonical_fronds)
            ]

        blade_fraction = max(0.15, 1.0 - float(growth.get("frond_stipe_fraction", 0.36) or 0.36))
        blade_width = leaf_length * (0.56 + 0.24 * float(growth.get("crown_openness", 0.5) or 0.5))
        area_per_frond = max(0.001, 0.5 * leaf_length * blade_fraction * blade_width * 0.72)
        visible_socket_indices = set(range(visible_fronds))
        for frond_index, (parent, x, y, angle) in enumerate(sockets):
            leaf = None
            if frond_index in visible_socket_indices:
                azimuth = math.radians(angle + 17.0 * math.sin(frond_index * 1.71))
                elevation = math.radians(58.0 + 14.0 * ((frond_index * 3) % 5) / 4.0)
                # Long fronds may extend sideways without making the fern
                # equally tall. Height classes remain labelled model defaults
                # when no measured height was authored.
                forward = self._normalise_vector((
                    math.cos(azimuth) * math.cos(elevation),
                    math.sin(azimuth) * math.cos(elevation),
                    math.sin(elevation),
                ))
                scale = (0.34 + 0.66 * maturity) * (0.82 + 0.18 * math.sin(frond_index * 2.03 + 0.7))
                frond_path = frond_centerline(
                    (x, y, .025), azimuth, leaf_length * max(.025, scale),
                    growth.get("frond_stipe_fraction", .36), max_height * max(.12, maturity),
                    elevation, tip_elevation=-.45 - .4 * ((frond_index * 3) % 5) / 4,
                )
                rotation = math.degrees(math.atan2(-(forward[0] + forward[1] * 1.8), forward[2]))
                leaf = self._add(
                    placements,
                    "leaf",
                    parent,
                    x,
                    y,
                    0.025,
                    rotation,
                    scale,
                    2,
                    placement_paths=placement_paths,
                    path=frond_path,
                )
                self._placement_orientation_hints[str(leaf)] = self._orientation_frame(forward)
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": parent,
                        "leaf_placement_index": leaf,
                        "socket": "frond",
                        "position_m": [round(x, 4), round(y, 4), 0.025],
                        "side": "solitary" if rhizome_distributed else "radial",
                        "rotation_deg": round(rotation % 360.0, 3),
                    })
            if leaf_clusters is not None:
                cluster_id = self._add_leaf_cluster(
                    leaf_clusters,
                    leaf if leaf is not None else parent,
                    x,
                    y,
                    0.025,
                    1,
                    area_per_frond * maturity,
                    1,
                    visual_density=1.0,
                )
                leaf_clusters[-1].update({
                    "explicit_samples": leaf is not None,
                    "sample_placement_indices": [leaf] if leaf is not None else [],
                    "organ_structure": "frond_like",
                    "leaf_division_order": division_order,
                    "primary_pinna_count": primary_pinnae,
                    "primary_pinna_arrangement": primary_pinna_arrangement,
                    "rhizome_distributed": rhizome_distributed,
                })
                if attachment_points is not None and leaf is not None:
                    attachment_points[-1]["cluster_id"] = cluster_id

        return {
            "hierarchical_frond_grammar": True,
            "rhizome_frond_distribution": "spaced_sockets" if rhizome_distributed else "compact_crown",
            "clonal_spread_class": spread_class,
            "canonical_frond_count": canonical_fronds,
            "visible_frond_count": visible_fronds,
            "frond_division_order": division_order,
            "primary_pinnae_per_frond": primary_pinnae,
            "primary_pinna_arrangement": primary_pinna_arrangement,
            "estimated_primary_pinna_count": canonical_fronds * primary_pinnae,
            "frond_area_per_leaf_m2": round(area_per_frond, 6),
            "rhizome_axis_length_m": round(rhizome_axis_length, 4),
            "rhizome_rooting_node_count": len(sockets) if rhizome_distributed else 0,
        }

    def _grow_succulent(self, placements, maturity, lod, attachment_points=None):
        """Grow a compact, fleshy rosette with leaves rising from one base."""

        growth = self.blueprint.growth
        max_height = max(0.18, float(growth.get("max_height_m", 0.9) or 0.9))
        leaf_count = max(5, int(round(8 + maturity * 6)))
        if lod == 0:
            leaf_count = min(leaf_count, 5)
        root = self._growth_origin(placements)
        for index in range(leaf_count):
            angle = index * 137.5 + 8.0
            radians = math.radians(angle)
            base_radius = 0.045 + 0.025 * (index % 2)
            tip_radius = base_radius + (0.16 + 0.22 * maturity) * (0.72 + 0.28 * ((index % 3) / 2.0))
            base_z = 0.05 + 0.02 * (index % 2)
            tip_z = min(max_height * maturity, 0.16 + max_height * (0.34 + 0.42 * ((index % 4) / 3.0)))
            base_x = math.cos(radians) * base_radius
            base_y = math.sin(radians) * base_radius
            tip_x = math.cos(radians) * tip_radius
            tip_y = math.sin(radians) * tip_radius
            stem = self._add(
                placements,
                "stem_section",
                root,
                base_x,
                base_y,
                base_z,
                angle,
                0.72 + 0.28 * maturity,
                1,
            )
            if attachment_points is not None:
                attachment_points.append({
                    "stem_placement_index": stem,
                    "socket": "leaf",
                    "position_m": [round(base_x, 4), round(base_y, 4), round(base_z, 4)],
                    "side": "rosette",
                    "rotation_deg": round(angle % 360.0, 3),
                })
            leaf_index = self._add(
                placements,
                "leaf",
                stem,
                base_x,
                base_y,
                base_z,
                angle,
                0.62 + 0.38 * maturity,
                2,
            )
            # Keep the sprite socket at the base while retaining the leaf's
            # independent 3D growth direction for projection and later 3D
            # renderers.
            self._placement_orientation_hints[str(leaf_index)] = self._orientation_frame((
                tip_x - base_x,
                tip_y - base_y,
                tip_z - base_z,
            ))

    def _grow_moss(self, placements, maturity, lod, attachment_points=None):
        """Grow a low carpet of short shoots rather than an upright herb."""

        growth = self.blueprint.growth
        spread = 0.20 + 0.42 * maturity
        shoot_count = max(6, int(round(10 + maturity * 14)))
        if lod == 0:
            shoot_count = min(shoot_count, 6)
        root = self._growth_origin(placements)
        for index in range(shoot_count):
            angle = index * 137.5
            radians = math.radians(angle)
            radius = spread * math.sqrt((index + 1) / shoot_count)
            x = math.cos(radians) * radius
            y = math.sin(radians) * radius
            z = 0.025 + 0.035 * ((index * 3) % 4) / 3.0
            shoot = self._add(placements, "stem_section", root, x, y, z, angle, 0.46 + 0.22 * maturity, 1)
            if lod >= 1:
                leaf = self._add(
                    placements,
                    "leaf",
                    shoot,
                    x + math.cos(radians) * 0.025,
                    y + math.sin(radians) * 0.025,
                    z + 0.035,
                    angle,
                    0.34 + 0.24 * maturity,
                    2,
                )
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": shoot,
                        "leaf_placement_index": leaf,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                        "side": "mat",
                        "rotation_deg": round(angle % 360.0, 3),
                    })

    def _grow_emergent_rosette(self, placements, maturity, flowering, fruiting,
                               attachment_points, placement_paths):
        from simulations.species.emergent_rosettes import build_emergent_rosette
        profile = self.blueprint.growth["emergent_rosette_profile"]
        root = self._growth_origin(placements, root_z=-profile["sediment_depth_m"])
        nodes, stats = build_emergent_rosette(self.blueprint.growth, maturity, flowering, fruiting, self.seed)
        indices = {}
        for ordinal, node in enumerate(nodes):
            parent = root if node["parent"] < 0 else indices[node["parent"]]
            index = self._add(placements, node["kind"], parent, *node["position"],
                              node["angle"], node["scale"], 1,
                              placement_paths=placement_paths, path=node["path"])
            indices[ordinal] = index
            if node["frame"]:
                self._placement_orientation_hints[str(index)] = node["frame"]
            if node["kind"] == "leaf":
                attachment_points.append({"stem_placement_index": parent, "leaf_placement_index": index,
                                          "socket": "leaf", "position_m": list(placements[index][2:5]),
                                          "side": "emergent"})
        return stats

    def _grow_aquatic_rosette(
        self,
        placements,
        maturity,
        lod,
        flowering_factor=0.0,
        attachment_points=None,
        placement_paths=None,
    ):
        """Grow a rooted floating rosette with explicit petiole attachments.

        Water lilies are not upright rosettes: the rhizome stays in sediment,
        while long petioles carry each floating leaf to the water surface. The
        detailed species sim keeps those petioles and module sockets, while
        scenery can later consume the resulting compact placement product.
        """

        root = self._growth_origin(placements, root_z=-0.22)
        count = max(3, int(round(4 + maturity * 5)))
        radius = 0.08 + 0.46 * maturity
        for index in range(count):
            rng = random.Random(f"{self.seed}:floating_leaf:{index}")
            angle = index * float(self.blueprint.growth["phyllotaxis_deg"]) + 18.0
            radians = math.radians(angle)
            reach = radius * rng.uniform(.25, 1.0)
            leaf_scale = max(.06, math.sqrt(maturity)) * rng.uniform(.82, 1.0)
            x = math.cos(radians) * reach
            y = math.sin(radians) * reach
            target_x, target_y, target_z = x, y, 0.0
            perpendicular = (-math.sin(radians), math.cos(radians))
            petiole_path = []
            for fraction in (0.33, 0.66, 1.0):
                bend = 0.055 * math.sin(math.pi * fraction) * (-1.0 if index % 2 else 1.0)
                petiole_path.append((
                    target_x * fraction + perpendicular[0] * bend,
                    target_y * fraction + perpendicular[1] * bend,
                    -0.22 + (target_z + 0.22) * fraction + 0.035 * math.sin(math.pi * fraction),
                ))
            petiole = self._add(
                placements,
                "stem_section",
                root,
                target_x,
                target_y,
                target_z,
                angle,
                0.65 + 0.35 * maturity,
                1,
                placement_paths=placement_paths,
                path=petiole_path,
            )
            # Keep canonical organs at every LOD; only drawing is sampled.
            if attachment_points is not None:
                attachment_points.append({
                    "stem_placement_index": petiole,
                    "socket": "leaf",
                    "position_m": [round(x, 4), round(y, 4), 0.0],
                    "side": "surface",
                    "rotation_deg": round(angle, 3),
                })
            leaf = self._add(placements, "leaf", petiole, x, y, 0.0, angle, leaf_scale, 2)
            if attachment_points is not None:
                attachment_points[-1]["leaf_placement_index"] = leaf
            self._placement_orientation_hints[str(leaf)] = {
                "forward": [math.cos(radians), math.sin(radians), 0.0],
                "normal": [0.0, 0.0, 1.0],
                "floating_leaf": True,
                "min_render_lod": 0 if index % 3 == 0 else 1 if index % 2 == 0 else 2,
            }

        # Flowers occupy alternating positions in the rhizome's spiral. A
        # mature cycle can carry two visible blooms, rather than forcing one
        # flower into the centre of an otherwise generic rosette.
        if flowering_factor > 0.0:
            flower_count = 2 if maturity >= 0.75 else 1
            for flower_index in range(flower_count):
                flower_angle = 112.0 + flower_index * 170.0
                flower_radians = math.radians(flower_angle)
                flower_radius = 0.06 + 0.10 * maturity
                flower_x = math.cos(flower_radians) * flower_radius
                flower_y = math.sin(flower_radians) * flower_radius
                target_z = 0.02
                perpendicular = (-math.sin(flower_radians), math.cos(flower_radians))
                peduncle_path = []
                for fraction in (0.33, 0.66, 1.0):
                    bend = 0.035 * math.sin(math.pi * fraction) * (1.0 if flower_index else -1.0)
                    peduncle_path.append((
                        flower_x * fraction + perpendicular[0] * bend,
                        flower_y * fraction + perpendicular[1] * bend,
                        -0.22 + (target_z + 0.22) * fraction + 0.04 * math.sin(math.pi * fraction),
                    ))
                peduncle = self._add(
                    placements,
                    "stem_section",
                    root,
                    flower_x,
                    flower_y,
                    target_z,
                    flower_angle,
                    0.7 + 0.3 * maturity,
                    1,
                    placement_paths=placement_paths,
                    path=peduncle_path,
                )
                flower = self._add(
                    placements,
                    "flower",
                    peduncle,
                    flower_x,
                    flower_y,
                    target_z,
                    0.0,
                    0.7 + 0.3 * flowering_factor,
                    2,
                )
                self._placement_orientation_hints[str(flower)] = {"min_render_lod": 1}

    def _grow_basal_fan(self, placements, maturity, lod, flowering, fruiting,
                        attachment_points, placement_paths):
        from simulations.species.basal_fan_shoots import build_basal_fan_shoots
        growth = self.blueprint.growth
        nodes, stats = build_basal_fan_shoots(growth, maturity, maturity, flowering, fruiting, self.seed)
        root = self._growth_origin(placements)
        indices = {}
        for ordinal, node in enumerate(nodes):
            if node["min_lod"] > lod:
                continue
            parent = root if node["parent"] < 0 else indices[node["parent"]]
            p = node["position"]
            path = None
            if node["kind"] in {"stem_section", "branch_section"}:
                path = self._curved_segment_path(placements[parent][2:5], p,
                    bend=growth["max_height_m"]*.006, direction=-1 if ordinal % 2 else 1)
            index = self._add(placements, node["kind"], parent, *p, node["angle"],
                node["scale"], 2, placement_paths=placement_paths, path=path)
            indices[ordinal] = index
            if node["forward"] is not None:
                self._placement_orientation_hints[str(index)] = self._orientation_frame(node["forward"])
            if node["kind"] == "leaf" and attachment_points is not None:
                attachment_points.append({"stem_placement_index": parent,
                    "leaf_placement_index": index, "socket": "leaf", "position_m": list(p),
                    "cohort": node["role"]})
        # Lamina area follows organ length and width, not the generic 5 cm²
        # floor or the number of samples retained by the render LOD.
        stats["leaf_area_m2"] = round(sum(growth["basal_fan_leaf_length_m"]
            * growth["basal_fan_profile"]["leaf_width_m"]*.65*n["scale"]**2
            for n in nodes if n["kind"] == "leaf"), 6)
        return stats

    def _grow_sympodial(
        self,
        placements,
        maturity,
        lod,
        rng,
        flowering_factor=0.0,
        fruiting_factor=0.0,
        attachment_points=None,
        placement_paths=None,
        leaf_clusters=None,
        leaf_factor=1.0,
    ):
        """Grow bounded determinate units with lateral continuation.

        A sympodial plant is not merely a bent monopodial stem: upper units
        terminate while lateral axes continue growth. Terminal reproductive
        modules therefore sit on the final main-axis unit and on bounded
        lateral tips. The grammar is trait-driven and shared by every species
        authored with ``determinate_sympodial``.
        """

        growth = self.blueprint.growth
        if growth.get('sympodial_herb_version') or growth.get('cyme_herb_version') or growth.get('flower_fork_version'):
            if growth.get('flower_fork_version'):
                from simulations.species.flower_terminated_forks import build_forks as build_herb
            elif growth.get('cyme_herb_version'):
                from simulations.species.cyme_herbs import build_cyme_herb as build_herb
            else:
                from simulations.species.sympodial_herbs import build_sympodial_herb as build_herb
            nodes, stats = build_herb(growth, maturity, flowering_factor, fruiting_factor, self.seed,
                **({'leaf_factor':leaf_factor} if growth.get('cyme_herb_version') or growth.get('flower_fork_version') else {}))
            root = self._growth_origin(placements)
            indices = {}
            for ordinal, node in enumerate(nodes):
                parent = root if node['parent'] < 0 else indices[node['parent']]
                index = self._add(placements, node['kind'], parent, *node['position'], node['angle'],
                                  node['scale'], 2, placement_paths=placement_paths, path=node['path'])
                indices[ordinal] = index
                frame = self._orientation_frame(node['forward']) if node['forward'] else {}
                frame['min_render_lod'] = node['min_lod']
                if growth.get('flower_fork_version'):
                    frame.update(unit_id=node['unit_id'],shoot_role=node['role'])
                if growth.get('cyme_herb_version'):
                    frame.update(leaf_role=node['role'],width_m=node.get('width_m',0.))
                self._placement_orientation_hints[str(index)] = frame
                if node['kind'] == 'leaf':
                    cluster = self._add_leaf_cluster(leaf_clusters,index,*node['position'],1,
                        node['area_m2'] if growth.get('cyme_herb_version') or growth.get('flower_fork_version') else
                        growth['leaf_length_m']*growth['sympodial_herb_profile']['leaf_width_m']*.65*node['scale']**2,
                        0,visual_density=1.)
                    if leaf_clusters is not None:
                        leaf_clusters[-1].update(explicit_samples=True,sample_placement_indices=[index])
                    if attachment_points is not None:
                        attachment_points.append({'stem_placement_index':parent,'leaf_placement_index':index,
                            'socket':'leaf','position_m':list(node['position']),'cohort':node['role'],'cluster_id':cluster})
            if growth.get('flower_fork_version'):
                for unit in stats['sympodial_units']:
                    for key in ('origin_node','terminal_node','terminal_peduncle'):
                        if unit[key] is not None:
                            unit[key]=indices[unit[key]]
            return stats
        if growth.get("basal_fan_profile"):
            return self._grow_basal_fan(placements, maturity, lod, flowering_factor,
                                        fruiting_factor, attachment_points, placement_paths)
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        herbaceous_along_stem = (
            str(growth.get("plant_woodiness") or "") == "herbaceous"
            and str(growth.get("leaf_attachment_pattern") or "") in {"along_stem", "mixed"}
        )
        # Herbaceous sympodial forbs normally carry more, shorter visible
        # units than a woody axis using the same neutral runtime internode.
        # This bounded coefficient is shared by the trait combination and
        # avoids a species-specific density branch.
        effective_internode = internode * (0.68 if herbaceous_along_stem else 1.0)
        generations = min(18, max(1, int(round((max_height / effective_internode) * maturity))))
        leaves_per_node = 0 if lod == 0 else max(1, int(growth.get("leaves_per_node", 1) or 1))
        branch_angle = float(growth.get("branch_angle_deg", 28.0) or 28.0)
        phyllotaxis = float(growth.get("phyllotaxis_deg", 137.5) or 137.5)
        flowering_position = str(growth.get("flowering_position") or "other_unknown")
        reproductive_mode = str(growth.get("reproductive_mode") or "other_unknown")
        terminal_flowers = flowering_position in {"terminal", "mixed"}
        lateral_flowers = flowering_position in {"lateral", "mixed"}

        root = self._growth_origin(placements)
        parent, x, y = root, 0.0, 0.0
        terminal_count = 0
        lateral_axis_count = 0
        flower_count = 0
        fruit_count = 0
        lateral_axis_cap = {0: 0, 1: 3, 2: 6}.get(lod, 6)
        for generation in range(generations):
            fraction = (generation + 1) / max(1, generations)
            z = min(max_height * maturity, internode * (generation + 1))
            continuation_angle = phyllotaxis * generation + (branch_angle if generation % 2 else -branch_angle)
            parent_position = placements[parent][2:5] if parent >= 0 else (0.0, 0.0, 0.0)
            stem_end = (x, y, z)
            stem_path = self._curved_segment_path(
                parent_position,
                stem_end,
                bend=0.006 + internode * 0.025,
                direction=-1.0 if generation % 2 else 1.0,
            )
            stem = self._add(
                placements,
                "stem_section",
                parent,
                x,
                y,
                z,
                continuation_angle,
                0.65 + 0.35 * fraction,
                1,
                placement_paths=placement_paths,
                path=stem_path,
            )
            for leaf_index in range(leaves_per_node):
                angle = continuation_angle + (180.0 if leaf_index else 0.0)
                radius = 0.08
                self._add(
                    placements,
                    "leaf",
                    stem,
                    x + math.cos(math.radians(angle)) * radius,
                    y + math.sin(math.radians(angle)) * radius,
                    z,
                    angle,
                    0.55 + 0.45 * maturity,
                    2,
                )
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": stem,
                        "leaf_placement_index": len(placements) - 1,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                    })

            # Upper determinate units hand continuation to a lateral axis.
            # A bounded set of two-segment side axes expresses the ascending
            # upper inflorescence without exponential branching.
            if (
                lod >= 1
                and generations >= 4
                and generation >= generations // 2
                and lateral_axis_count < lateral_axis_cap
            ):
                side = -1.0 if (generation // 2) % 2 else 1.0
                lateral_angle = continuation_angle + side * (55.0 + branch_angle * 0.35)
                lateral_length = min(max_height * 0.22, internode * (0.85 + 0.12 * generation))
                lateral_rad = math.radians(lateral_angle)
                branch_end = (
                    x + math.cos(lateral_rad) * lateral_length,
                    y + math.sin(lateral_rad) * lateral_length,
                    min(max_height * maturity, z + internode * 1.05),
                )
                branch_path = self._curved_segment_path(
                    stem_end,
                    branch_end,
                    bend=lateral_length * 0.08,
                    direction=side,
                )
                branch = self._add(
                    placements,
                    "branch_section",
                    stem,
                    branch_end[0],
                    branch_end[1],
                    branch_end[2],
                    lateral_angle,
                    0.60 + 0.40 * maturity,
                    2,
                    placement_paths=placement_paths,
                    path=branch_path,
                )
                distal_length = lateral_length * 0.72
                tip_end = (
                    branch_end[0] + math.cos(lateral_rad) * distal_length,
                    branch_end[1] + math.sin(lateral_rad) * distal_length,
                    min(max_height * maturity + internode * 0.55, branch_end[2] + internode * 0.48),
                )
                tip_path = self._curved_segment_path(
                    branch_end,
                    tip_end,
                    bend=distal_length * 0.06,
                    direction=-side,
                )
                branch_tip = self._add(
                    placements,
                    "branch_section",
                    branch,
                    tip_end[0],
                    tip_end[1],
                    tip_end[2],
                    lateral_angle,
                    0.58 + 0.42 * maturity,
                    3,
                    placement_paths=placement_paths,
                    path=tip_path,
                )
                lateral_axis_count += 1
                if lod >= 2:
                    self._add(
                        placements,
                        "leaf",
                        branch,
                        branch_end[0],
                        branch_end[1],
                        branch_end[2],
                        lateral_angle,
                        0.55 + 0.45 * maturity,
                        3,
                    )
                    self._add(
                        placements,
                        "leaf",
                        branch_tip,
                        tip_end[0],
                        tip_end[1],
                        tip_end[2],
                        lateral_angle + phyllotaxis,
                        0.52 + 0.43 * maturity,
                        4,
                    )
                if lod >= 2 and terminal_flowers and flowering_factor > 0.0:
                    self._add(
                        placements,
                        "flower",
                        branch_tip,
                        tip_end[0],
                        tip_end[1],
                        tip_end[2] + 0.012,
                        lateral_angle,
                        0.70 + 0.30 * flowering_factor,
                        4,
                    )
                    terminal_count += 1
                    flower_count += 1
                if (
                    lod >= 2
                    and terminal_flowers
                    and fruiting_factor >= 0.25
                    and reproductive_mode not in {"vegetative", "other_unknown"}
                ):
                    self._add(
                        placements,
                        "fruit",
                        branch_tip,
                        tip_end[0],
                        tip_end[1],
                        tip_end[2] + 0.008,
                        lateral_angle,
                        0.55 + 0.35 * fruiting_factor,
                        4,
                    )
                    fruit_count += 1

            if lod >= 2 and lateral_flowers and flowering_factor > 0.0 and generation >= generations // 2:
                lateral_angle = continuation_angle + 90.0
                lateral_rad = math.radians(lateral_angle)
                self._add(
                    placements,
                    "flower",
                    stem,
                    x + math.cos(lateral_rad) * 0.018,
                    y + math.sin(lateral_rad) * 0.018,
                    z,
                    lateral_angle,
                    0.65 + 0.30 * flowering_factor,
                    2,
                )
                flower_count += 1
            x += math.cos(math.radians(continuation_angle)) * 0.045
            y += math.sin(math.radians(continuation_angle)) * 0.045
            parent = stem

        if lod >= 2 and terminal_flowers and flowering_factor > 0.0 and parent >= 0:
            tip = placements[parent][2:5]
            self._add(
                placements,
                "flower",
                parent,
                tip[0],
                tip[1],
                tip[2] + 0.015,
                0.0,
                0.72 + 0.28 * flowering_factor,
                2,
            )
            terminal_count += 1
            flower_count += 1

        return {
            "sympodial_unit_count": generations,
            "sympodial_lateral_axis_count": lateral_axis_count,
            "sympodial_terminal_count": terminal_count,
            "sympodial_flower_count": flower_count,
            "sympodial_fruit_count": fruit_count,
        }

    def _grow_vine(
        self,
        placements,
        maturity,
        lod,
        rng,
        attachment_points=None,
        placement_paths=None,
        leaf_clusters=None,
        life_state=None,
    ):
        """Grow a support-searching axis, then climb a contacted trunk.

        The vine first spends its finite axis budget on a low, sinuous search
        path.  A supplied vertical support changes the same connected axis to
        a helix only after the contact distance has been reached.  Without a
        reachable support the plant remains prostrate; no invisible support
        or species-name special case is invented.
        """

        growth = self.blueprint.growth
        authored_organs = bool(growth.get("vine_organ_geometry_version"))
        life_state = life_state or {}
        organ_totals = [0, 0, 0]
        node_ordinal = 0
        vine_shoots=growth.get('branched_vine_profile')
        main_hosts=[]

        def authored_node(stem, point, azimuth, side):
            nonlocal node_ordinal
            from simulations.species.vine_organs import add_vine_organs
            node_ordinal += 1
            counts = add_vine_organs(self, placements, stem, point, azimuth, node_ordinal,
                                     maturity, lod, life_state, leaf_clusters, attachment_points, side)
            for i, count in enumerate(counts):
                organ_totals[i] += count
            if vine_shoots and side!='lateral_shoot':main_hosts.append((stem,placements[stem][2:5],azimuth,side))

        axis_budget = max(0.0, float(growth.get("max_height_m", 2.2) or 2.2) * maturity)
        total_axis_budget=axis_budget
        if vine_shoots and vine_shoots['lateral_count']:
            axis_budget*=1-vine_shoots['lateral_budget_fraction']
        internode = max(0.05, float(growth.get("internode_length_m", 0.28) or 0.28))
        if vine_shoots:internode=vine_shoots['node_spacing_m']
        leaves_per_node = max(0, int(growth.get("leaves_per_node", 1) or 1))
        if lod == 0:
            leaves_per_node = 0
        elif lod == 1:
            leaves_per_node = min(1, leaves_per_node)

        root = self._growth_origin(placements)
        rods = normalise_rod_structures(self.environment)
        supports = normalise_climbing_supports(self.environment)
        solid_field = SolidStructureField.from_environment(self.environment)
        max_axis = max(0.1, float(growth.get("max_height_m", 2.2) or 2.2))
        candidates = []
        for support in supports:
            center_x, center_y = climbing_support_axis_at_z(support, 0.045)
            center_distance = math.hypot(center_x, center_y)
            contact_gap = max(0.0, center_distance - float(support["radius_m"]) - 0.03)
            # The shallow search wiggle adds a small, explicit path cost.
            route_length = contact_gap * 1.035
            if route_length <= max_axis + 1e-9:
                candidates.append((route_length, str(support["id"]), support, center_distance))
        solid_contact = solid_field.nearest_ground_contact((0.0, 0.0, 0.045), max_axis)
        if solid_contact is not None:
            structure = solid_contact["structure"]
            contact_distance = float(solid_contact["distance_m"])
            candidates.append((
                contact_distance * 1.035,
                str(structure["id"]),
                {
                    "id": structure["id"],
                    "kind": structure["kind"],
                    "support_model": "pixel_solid_surface",
                    "center_m": structure["position_m"][:2],
                    "height_m": max(0.0, float(solid_contact["top_z_m"]) - float(structure["position_m"][2])),
                    "contact_point_m": list(solid_contact["point_m"]),
                    "top_z_m": float(solid_contact["top_z_m"]),
                    "approach_direction": list(solid_contact["direction"]),
                    "solid_structure": structure,
                },
                math.hypot(*structure["position_m"][:2]),
            ))
        selected = min(candidates, default=None, key=lambda item: (item[0], item[1]))

        if selected is not None:
            contact_route_length, _support_id, support, center_distance = selected
            if support.get("support_model") == "pixel_solid_surface":
                direction = tuple(float(value) for value in support["approach_direction"][:2])
                target = tuple(float(value) for value in support["contact_point_m"][:2])
            else:
                center_x, center_y = climbing_support_axis_at_z(support, 0.045)
                if center_distance > 1e-9:
                    direction = (center_x / center_distance, center_y / center_distance)
                else:
                    direction = (1.0, 0.0)
                contact_radius = float(support["radius_m"]) + 0.03
                target = (
                    center_x - direction[0] * contact_radius,
                    center_y - direction[1] * contact_radius,
                )
            search_angle = math.atan2(direction[1], direction[0])
        else:
            support = None
            contact_route_length = axis_budget
            # With no reachable object the search direction remains
            # deterministic but is not always the same screen-right ray.
            search_angle = math.radians(rng.uniform(-12.0, 12.0))
            target = (math.cos(search_angle) * axis_budget, math.sin(search_angle) * axis_budget)

        ground_budget = min(axis_budget, contact_route_length)
        ground_fraction = (
            min(1.0, ground_budget / contact_route_length)
            if contact_route_length > 1e-9 else 1.0
        )
        ground_segments = min(128 if vine_shoots else 32, max(0, int(math.ceil(ground_budget / internode))))
        parent = root
        previous = (0.0, 0.0, 0.045)
        ground_length = 0.0
        actual_ground_segments = 0
        last_ground = root
        for index in range(ground_segments):
            fraction = ground_fraction * (index + 1) / ground_segments
            # Zero at origin/contact, widest mid-search.  The amplitude is
            # deliberately small enough that total axis length stays bounded.
            wave = 0.075 * math.sin(math.pi * fraction) * math.sin(math.tau * 1.5 * fraction)
            if vine_shoots:
                amplitude=min(vine_shoots['ground_meander_m'],ground_budget*.08)
                wave=amplitude*math.sin(math.pi*fraction)*math.sin(math.tau*ground_budget*fraction/vine_shoots['ground_wavelength_m'])
            perpendicular = (-math.sin(search_angle), math.cos(search_angle))
            x = target[0] * fraction + perpendicular[0] * wave
            y = target[1] * fraction + perpendicular[1] * wave
            z = 0.045 + 0.012 * math.sin(math.pi * fraction)
            point = (x, y, z)
            segment_length = math.dist(previous, point)
            remaining_ground = max(0.0, ground_budget - ground_length)
            clipped = segment_length > remaining_ground + 1e-9
            if clipped and segment_length > 1e-9:
                interpolation = remaining_ground / segment_length
                point = tuple(
                    previous[axis] + (point[axis] - previous[axis]) * interpolation
                    for axis in range(3)
                )
                x, y, z = point
                segment_length = remaining_ground
            if segment_length <= 1e-9:
                break
            ground_length += segment_length
            stem = self._add(
                placements,
                "stem_section",
                parent,
                x,
                y,
                z,
                math.degrees(search_angle),
                0.58 + 0.32 * maturity,
                1,
                placement_paths=placement_paths,
                path=self._curved_segment_path(
                    previous,
                    point,
                    bend=0.014,
                    direction=-1.0 if index % 2 else 1.0,
                ),
            )
            if authored_organs:
                authored_node(stem, point, math.degrees(search_angle) + 90., "ground_search")
            for leaf_index in range(0 if authored_organs else leaves_per_node):
                leaf_angle = math.degrees(search_angle) + 90.0 + leaf_index * 360.0 / leaves_per_node
                leaf = self._add(
                    placements,
                    "leaf",
                    stem,
                    x + math.cos(math.radians(leaf_angle)) * 0.035,
                    y + math.sin(math.radians(leaf_angle)) * 0.035,
                    z + 0.035,
                    leaf_angle,
                    0.55 + 0.40 * maturity,
                    2,
                )
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": stem,
                        "leaf_placement_index": leaf,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                        "side": "ground_search",
                        "rotation_deg": round(leaf_angle % 360.0, 3),
                    })
            parent = stem
            last_ground = stem
            previous = point
            actual_ground_segments += 1
            if clipped:
                break

        contacted = bool(
            support is not None
            and axis_budget + 1e-9 >= contact_route_length
        )
        climbing_length = 0.0
        climbing_height = 0.0
        climb_segments = 0
        turn_count = 0.0
        support_height_limited = False
        surface_pattern = "none"
        surface_pattern_amplitude = 0.0
        surface_pattern_wavelength = 0.0
        surface_pattern_phase = 0.0
        surface_tangent_origin = 0.0
        surface_tangent_values = []
        support_clearance = 0.0
        helix_pitch_m = 0.0
        if contacted and support is not None:
            if attachment_points is not None:
                attachment_points.append({
                    "stem_placement_index": last_ground,
                    "socket": "support_contact",
                    "support_id": support["id"],
                    "position_m": [round(previous[0], 4), round(previous[1], 4), round(previous[2], 4)],
                    "side": "contact_transition",
                })
            available_climb = max(0.0, axis_budget - ground_length)
            pixel_surface = support.get("support_model") == "pixel_solid_surface"
            if pixel_surface:
                support_clearance = 0.03
                structure = support["solid_structure"]
                pixel_size = float(structure["pixel_size_m"])
                local_contact = SolidStructureField._world_to_local(structure, previous)
                angle = math.radians(float(structure["rotation_deg"]))
                world_dx, world_dy = support["approach_direction"][:2]
                local_dx = math.cos(angle) * world_dx + math.sin(angle) * world_dy
                local_dy = -math.sin(angle) * world_dx + math.cos(angle) * world_dy
                surface_front_face = abs(local_dy) > abs(local_dx)
                surface_tangent_origin = local_contact[0] if surface_front_face else local_contact[1]
                if str(support.get("kind") or "") == "wall" and surface_front_face:
                    surface_pattern = "bounded_lateral_meander"
                    surface_pattern_amplitude = min(0.30, max(pixel_size * 1.15, internode * 0.72))
                    surface_pattern_wavelength = max(1.05, internode * 5.2)
                    surface_pattern_phase = math.tau * ((self.seed * 7) % 31) / 31.0
                    maximum_slope = math.tau * surface_pattern_amplitude / surface_pattern_wavelength
                    pattern_length_factor = math.sqrt(1.0 + maximum_slope * maximum_slope * 0.5)
                else:
                    surface_pattern = "mask_boundary_follow"
                    pattern_length_factor = 1.0
                possible_height = available_climb / pattern_length_factor
                available_surface_height = max(0.0, float(support["top_z_m"]) - float(previous[2]))
                climbing_height = min(available_surface_height, possible_height)
                support_height_limited = possible_height > available_surface_height + 1e-9
                climbing_length = 0.0
                pitch = None
                helix_radius = None
                start_angle = search_angle
                winding = 0.0
            else:
                helix_radius = float(support["radius_m"]) + 0.035
                support_clearance = 0.035
                pitch = max(0.55, min(1.2, helix_radius * 4.0))
                helix_pitch_m = pitch
                helix_factor = math.sqrt(1.0 + (math.tau * helix_radius / pitch) ** 2)
                possible_height = available_climb / helix_factor
                support_top_z = float(support.get("top_z_m", support["height_m"]))
                available_support_height = max(0.0, support_top_z - float(previous[2]))
                climbing_height = min(available_support_height, possible_height)
                support_height_limited = possible_height > available_support_height + 1e-9
                climbing_length = climbing_height * helix_factor
                axis_x, axis_y = climbing_support_axis_at_z(support, previous[2])
                start_angle = math.atan2(previous[1] - axis_y, previous[0] - axis_x)
                winding = -1.0 if (self.seed % 2) else 1.0
            segment_basis = climbing_height if pixel_surface else climbing_length
            climb_segments = min(48, max(0, int(math.ceil(segment_basis / internode))))
            climb_start_z = previous[2]
            planned_climb_segments = climb_segments
            actual_climb_segments = 0
            for index in range(planned_climb_segments):
                fraction = (index + 1) / planned_climb_segments
                z = climb_start_z + climbing_height * fraction
                if pixel_surface:
                    radians = search_angle
                    preferred_tangent = surface_tangent_origin
                    if surface_pattern == "bounded_lateral_meander":
                        height_above_contact = z - climb_start_z
                        ramp = min(1.0, height_above_contact / max(0.18, surface_pattern_wavelength * 0.30))
                        preferred_tangent += (
                            surface_pattern_amplitude
                            * ramp
                            * math.sin(math.tau * height_above_contact / surface_pattern_wavelength + surface_pattern_phase)
                        )
                    surface_point = solid_field.surface_point_at_z(
                        support["solid_structure"],
                        support["approach_direction"],
                        z,
                        clearance=0.03,
                        previous_point=previous,
                        preferred_local_tangent_m=preferred_tangent,
                    )
                    x, y = surface_point[:2] if surface_point is not None else target
                else:
                    radians = start_angle + winding * math.tau * (climbing_height * fraction / pitch)
                    axis_x, axis_y = climbing_support_axis_at_z(support, z)
                    x = axis_x + math.cos(radians) * helix_radius
                    y = axis_y + math.sin(radians) * helix_radius
                point = (x, y, z)
                if pixel_surface:
                    segment_length = math.dist(previous, point)
                    remaining_axis = max(0.0, available_climb - climbing_length)
                    clipped_to_budget = segment_length > remaining_axis + 1e-9
                    if clipped_to_budget and segment_length > 1e-9:
                        interpolation = remaining_axis / segment_length
                        point = tuple(
                            previous[axis] + (point[axis] - previous[axis]) * interpolation
                            for axis in range(3)
                        )
                        x, y, z = point
                        segment_length = remaining_axis
                    if segment_length <= 1e-9:
                        break
                    climbing_length += segment_length
                    if surface_pattern == "bounded_lateral_meander":
                        climb_path = [
                            tuple(previous[axis] + (point[axis] - previous[axis]) * path_fraction for axis in range(3))
                            for path_fraction in (0.38, 0.72, 1.0)
                        ]
                    elif math.hypot(x - previous[0], y - previous[1]) > 1e-6:
                        climb_path = [(previous[0], previous[1], z), point]
                    else:
                        climb_path = self._curved_segment_path(previous, point, bend=0.004, direction=1.0)
                    local_point = SolidStructureField._world_to_local(support["solid_structure"], point)
                    surface_tangent_values.append(local_point[0] if surface_front_face else local_point[1])
                else:
                    clipped_to_budget = False
                    if authored_organs:
                        climb_path = []
                        for sample in range(1, 9):
                            sample_fraction = (index + sample/8) / planned_climb_segments
                            sample_z = climb_start_z + climbing_height * sample_fraction
                            sample_angle = start_angle + winding * math.tau * climbing_height * sample_fraction / pitch
                            cx, cy = climbing_support_axis_at_z(support, sample_z)
                            climb_path.append((cx + math.cos(sample_angle)*helix_radius,
                                               cy + math.sin(sample_angle)*helix_radius, sample_z))
                    else:
                        climb_path = self._curved_segment_path(previous, point, bend=0.008, direction=winding)
                stem = self._add(
                    placements,
                    "stem_section",
                    parent,
                    x,
                    y,
                    z,
                    math.degrees(radians + (winding * math.pi * 0.5 if not pixel_surface else 0.0)),
                    0.58 + 0.32 * maturity,
                    1,
                    placement_paths=placement_paths,
                    path=climb_path,
                )
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": stem,
                        "socket": "support_contact",
                        "support_id": support["id"],
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                        "side": "climbing_axis",
                    })
                if authored_organs:
                    azimuth = math.degrees(search_angle + math.pi if pixel_surface else radians)
                    authored_node(stem, point, azimuth, "climbing_axis")
                for leaf_index in range(0 if authored_organs else leaves_per_node):
                    leaf_radians = (
                        search_angle + math.pi
                        if pixel_surface else radians
                    )
                    leaf_angle = math.degrees(leaf_radians) + leaf_index * 360.0 / leaves_per_node
                    leaf = self._add(
                        placements,
                        "leaf",
                        stem,
                        x + math.cos(leaf_radians) * 0.045,
                        y + math.sin(leaf_radians) * 0.045,
                        z + 0.02,
                        leaf_angle,
                        0.55 + 0.40 * maturity,
                        2,
                    )
                    if attachment_points is not None:
                        attachment_points.append({
                            "stem_placement_index": stem,
                            "leaf_placement_index": leaf,
                            "socket": "leaf",
                            "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                            "side": "climbing_axis",
                            "rotation_deg": round(leaf_angle % 360.0, 3),
                        })
                parent = stem
                previous = point
                actual_climb_segments += 1
                if clipped_to_budget:
                    break
            climb_segments = actual_climb_segments
            if pixel_surface:
                climbing_height = max(0.0, previous[2] - climb_start_z)
                support_height_limited = previous[2] >= float(support["top_z_m"]) - 1e-6
            turn_count = 0.0 if pixel_surface else climbing_height / pitch

        lateral_count=lateral_length=0
        if vine_shoots:
            from simulations.species.vine_organs import add_vine_laterals
            lateral_count,lateral_length=add_vine_laterals(self,placements,main_hosts,maturity,
                min(total_axis_budget*vine_shoots['lateral_budget_fraction'],
                    max(0.,total_axis_budget-ground_length-climbing_length)),
                placement_paths,attachment_points,authored_node)
        phase = "climbing" if climbing_height > 1e-6 else "ground_search"
        if axis_budget <= 1e-9:
            phase = "dormant"
        organ_stats = ({"vine_organ_geometry_version": 1, "vine_leaf_socket_count": organ_totals[0],
                        "vine_flower_cyme_count": organ_totals[1], "vine_fruit_sample_count": organ_totals[2],
                        "vine_leaf_factor": life_state.get("leaf_factor", 1.0)} if authored_organs else {})
        return {
            **organ_stats,
            "vine_growth_grammar": "support_search_then_climb",
            "vine_phase": phase,
            **({'branched_vine_version':1,'vine_lateral_axis_count':lateral_count,
                'vine_lateral_axis_length_m':round(lateral_length,4)} if vine_shoots else {}),
            "vine_axis_budget_m": round(total_axis_budget, 4),
            "vine_axis_length_m": round(ground_length + climbing_length+lateral_length, 4),
            "vine_ground_axis_length_m": round(ground_length, 4),
            "vine_climbing_axis_length_m": round(climbing_length, 4),
            "vine_climbing_height_m": round(climbing_height, 4),
            "vine_support_search_radius_m": round(max_axis, 4),
            "vine_support_count": len(supports) + len(solid_field.structures),
            "vine_support_contact_count": 1 if contacted else 0,
            "vine_selected_support_id": str(support["id"]) if support is not None else None,
            "vine_selected_support_kind": str(support["kind"]) if support is not None else None,
            "vine_selected_support_radius_m": round(float(support.get("radius_m", 0.0)), 4) if support is not None else 0.0,
            "vine_support_clearance_m": round(support_clearance, 4),
            "vine_helix_pitch_m": round(helix_pitch_m, 4),
            "vine_support_height_limited": support_height_limited,
            "vine_turn_count": round(turn_count, 4),
            "vine_surface_pattern": surface_pattern,
            "vine_surface_pattern_amplitude_m": round(surface_pattern_amplitude, 4),
            "vine_surface_pattern_wavelength_m": round(surface_pattern_wavelength, 4),
            "vine_surface_lateral_span_m": round(
                max(surface_tangent_values) - min(surface_tangent_values)
                if surface_tangent_values else 0.0,
                4,
            ),
            "vine_attachment_mode": (
                str(support.get("support_model") or "cylindrical_helix")
                if support is not None else "none"
            ),
            "vine_ground_segment_count": actual_ground_segments,
            "vine_climbing_segment_count": climb_segments,
            "climbing_supports": supports,
            "rod_structures": rods,
            "solid_structures": solid_field.structures,
        }

    def _grow_creeping(
        self,
        placements,
        maturity,
        lod,
        rng,
        attachment_points=None,
        placement_paths=None,
        leaf_clusters=None,
        rooting_contacts=None,
        flowering_factor=0.0,
        fruiting_factor=0.0,
        fruit_ripeness=0.0,
    ):
        """Grow bounded low axes whose density follows authored spread traits.

        ``mature_height`` remains the vertical envelope.  Horizontal reach is
        a bounded qualitative coefficient, while ``clonal_spread`` controls
        how many exploration axes leave the crown.  Leaf sockets stay on the
        host stem; the previous fixed 7 cm lateral offset made millimetre-scale
        leaves float far away from a creeping shoot.
        """

        growth = self.blueprint.growth
        if growth.get("creeping_woody_profile"):
            from simulations.species.creeping_woody import grow_creeping_woody
            return grow_creeping_woody(self, placements, maturity, lod, rng,
                attachment_points, placement_paths, leaf_clusters, rooting_contacts,
                flowering_factor, fruiting_factor, fruit_ripeness)
        max_height = max(0.05, float(growth.get("max_height_m", 0.3) or 0.3))
        spread_class = str(growth.get("clonal_spread") or "other_unknown")
        spread_profile = {
            "none": (1, 0.72, 0, 0),
            "low": (2, 0.88, 0, 0),
            "moderate": (4, 1.04, 4, 1),
            "high": (6, 1.22, 3, 2),
            "other_unknown": (1, 0.82, 0, 0),
        }.get(spread_class, (1, 0.82, 0, 0))
        mature_axes, reach_factor, rooting_interval, lateral_axes_per_primary = spread_profile
        herb_profile = growth.get("creeping_herb_profile")
        if herb_profile:
            # Branching is independent of vegetative spread: annual
            # shoots can ramify without rooting at their nodes.
            mature_axes = herb_profile["primary_axes"]
            lateral_axes_per_primary = herb_profile["lateral_axes_per_primary"]
        # Clustering describes local grouping, while this authored continuous
        # trait controls packing along each axis. Missing values keep v001.
        ranges = growth.get("architecture_ranges") or {}
        density_authored = ranges.get("leaf_cluster_density", {}).get("status") != "runtime_default"
        density = float(growth.get("leaf_cluster_density", 0.0)) if density_authored else 0.0
        density = max(0.0, min(1.0, density)) if math.isfinite(density) else 0.0
        twig_authored = ranges.get("fine_twig_density", {}).get("status") != "runtime_default"
        twig_density = float(growth.get("fine_twig_density", 0.0)) if twig_authored else 0.0
        twig_density = max(0.0, min(1.0, twig_density)) if math.isfinite(twig_density) else 0.0
        lateral_axes_per_primary += round(6 * twig_density * maturity)
        axis_count = max(1, 1 + int(round((mature_axes - 1) * maturity)))
        axis_length = min(1.2, max(0.14, max_height * reach_factor)) * max(0.08, maturity)
        if herb_profile:
            axis_length = herb_profile["axis_length_m"] * max(.08, maturity)
        clustering = str(growth.get("leaf_clustering") or "other_unknown")
        mature_nodes = {
            "dense_cluster": 24,
            "tufted": 18,
            "paired": 16,
            "distributed": 12,
            "solitary": 10,
            "other_unknown": 12,
        }.get(clustering, 12)
        mature_nodes += round(64 * density)
        if herb_profile:
            mature_nodes = herb_profile["nodes_per_axis"]
        node_count = max(2, min(88, int(round(2 + (mature_nodes - 2) * maturity))))
        leaves_per_node = {
            "dense_cluster": 3,
            "tufted": 3,
            "paired": 2,
        }.get(clustering, 1)
        woody = str(growth.get("plant_woodiness") or "") == "woody"
        root = self._growth_origin(placements)
        leaf_module = self.blueprint.module("leaf")
        leaf_length = max(0.001, float(getattr(leaf_module, "length_m", 0.01) or 0.01))
        leaf_radius = max(0.00025, float(getattr(leaf_module, "radius_m", 0.001) or 0.001))
        leaf_area = max(1e-7, leaf_length * max(0.0005, leaf_radius * 2.0) * 0.72)
        phase = rng.uniform(0.0, 360.0)
        total_axis_length = 0.0
        max_radius = 0.0
        rooting_count = 0
        leaf_socket_count = 0
        secondary_axis_count = 0
        ascending_axis_count = 0
        reproductive_sockets = []

        def add_leaf_socket(stem, position, stem_angle, axis_index, node_index, branch_order):
            """Attach a compact leaf group to one real stem socket."""

            nonlocal leaf_socket_count, total_axis_length
            x, y, z = position
            # Small axillary organs on lateral leafy shoots, never on a
            # floating generic marker or a root. Deterministic socket ranks
            # are shared by flowers and the fruit that follows them.
            if ((herb_profile and node_index >= 2
                 and node_index % herb_profile["reproductive_node_interval"] == 0)
                    or (not herb_profile and branch_order >= 2 and node_index % 7 == 3)):
                reproductive_sockets.append((stem, position, stem_angle, axis_index, node_index))
            sample_indices = []
            cohort_area = 0.
            for leaf_index in range(leaves_per_node):
                # Dense tiny leaves become a shallow spiral around the shoot,
                # not a repeated pair of identical vertical pickets.
                leaf_angle = (
                    stem_angle
                    + 42.0
                    + leaf_index * (360.0 / leaves_per_node)
                    + 31.0 * ((node_index + 2 * axis_index) % 5)
                )
                if herb_profile and growth.get("leaf_arrangement") == "opposite":
                    leaf_angle = stem_angle + 90 + (node_index % 2)*90 + leaf_index*180
                elif herb_profile and growth.get("leaf_arrangement") == "distichous":
                    # One leaf per successive node, alternating across the
                    # local runner axis rather than spiralling around it.
                    leaf_angle = stem_angle + (90 if node_index % 2 == 0 else -90)
                leaf_parent = stem
                leaf_position = (x, y, z)
                ratio = (herb_profile.get("paired_leaf_size_ratio", 1.)
                         if herb_profile and leaf_index % 2 else 1.)
                leaf_scale = (0.72 + 0.28*maturity)*ratio
                petiole = herb_profile.get("petiole_length_m", 0.) if herb_profile else 0.
                theta = math.radians(leaf_angle)
                forward = (math.cos(theta), math.sin(theta), .22)
                if herb_profile and "leaf_pitch_deg" in herb_profile:
                    pitch = math.radians(herb_profile["leaf_pitch_deg"])
                    forward = (math.cos(theta)*math.cos(pitch), math.sin(theta)*math.cos(pitch), math.sin(pitch))
                if petiole:
                    length = petiole * max(.08, maturity)*ratio
                    leaf_position = tuple(v+direction*length for v,direction in zip((x,y,z),forward))
                    leaf_parent = self._add(placements,"branch_section",stem,*leaf_position,leaf_angle,.45,
                                            branch_order+1,placement_paths=placement_paths,
                                            path=[(x,y,z),leaf_position])
                    total_axis_length += math.dist((x,y,z), leaf_position)
                leaf = self._add(
                    placements,
                    "leaf",
                    leaf_parent,
                    *leaf_position,
                    leaf_angle,
                    leaf_scale,
                    branch_order + 1,
                )
                sample_indices.append(leaf)
                cohort_area += leaf_area*(leaf_scale**2 if herb_profile and herb_profile["version"] >= 2 else 1.)
                if herb_profile:
                    self._placement_orientation_hints[str(leaf)] = self._orientation_frame(
                        forward)
                    if herb_profile.get('planar_leaves'):
                        frame=self._placement_orientation_hints[str(leaf)]
                        frame.update(planar_leaf=True,normal=frame['up'],
                                     width_m=herb_profile['leaf_width_m']*leaf_scale)
                leaf_socket_count += 1
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": leaf_parent,
                        "leaf_placement_index": leaf,
                        "socket": "leaf",
                        "position_m": [round(v,4) for v in leaf_position],
                        "side": "radial",
                        "rotation_deg": round(leaf_angle % 360.0, 3),
                    })
            if leaf_clusters is not None and sample_indices:
                cluster_id = self._add_leaf_cluster(
                    leaf_clusters,
                    stem,
                    x,
                    y,
                    z,
                    leaves_per_node,
                    cohort_area,
                    branch_order,
                    visual_density=1.0 if clustering == "dense_cluster" else 0.72,
                )
                leaf_clusters[-1].update({
                    "explicit_samples": True,
                    "sample_placement_indices": sample_indices,
                    "organ_structure": str(growth.get("leaf_structure") or "other_unknown"),
                    # At whole-plant scale the real millimetre leaves merge
                    # optically into a narrow foliage sleeve around the stem.
                    # This collective cue is rendered at physical leaf scale;
                    # individual close-up placements remain authoritative.
                    "dense_shoot_envelope": clustering == "dense_cluster",
                    "leaf_length_m": round(leaf_length, 6),
                })
                if attachment_points is not None:
                    for attachment in attachment_points[-len(sample_indices):]:
                        attachment["cluster_id"] = cluster_id

        lateral_starts = []
        ascending_starts = []

        for axis_index in range(axis_count):
            # A golden-angle sequence covers the ground without producing the
            # diagrammatic spokes caused by equal angular intervals.
            base_angle = phase + axis_index * 137.507764 + rng.uniform(-18.0, 18.0)
            bend_direction = -1.0 if axis_index % 2 else 1.0
            reach = axis_length * rng.uniform(0.62, 1.0)
            axis_nodes = max(2, round(node_count * reach / max(axis_length, 1e-6)))
            tip_lift = rng.uniform(0.12, 1.0)
            ascending_count = (2 if spread_class in {"moderate", "high"} else 1) + round(8 * twig_density * maturity)
            ascending_targets = {
                max(1, min(axis_nodes - 1, round((axis_nodes - 1) * fraction)))
                for fraction in ((i + 1) / (ascending_count + 1) for i in range(ascending_count))
            }
            parent = root
            previous = (0.0, 0.0, 0.02)
            for node_index in range(axis_nodes):
                fraction = (node_index + 1) / axis_nodes
                angle = base_angle + 13.0 * math.sin(node_index * 0.67 * 24/max(24,node_count) + axis_index * 1.31)
                radians = math.radians(angle)
                radius = reach * fraction
                x = math.cos(radians) * radius
                y = math.sin(radians) * radius
                # Procumbent axes follow the substrate; only some distal tips
                # rise, and they do so by unequal amounts.
                terminal_fraction = max(0.0, (fraction - 0.72) / 0.28)
                z = (
                    0.016
                    + 0.0035 * math.sin(node_index * 0.91 + axis_index)
                    + (herb_profile["tip_lift_m"] if herb_profile else min(max_height * 0.15, 0.06)) * tip_lift * terminal_fraction ** 1.7
                    * (maturity if herb_profile and herb_profile["version"] >= 2 else 1.)
                )
                endpoint = (x, y, z)
                path = self._curved_segment_path(
                    previous,
                    endpoint,
                    bend=min(0.018, reach / max(8.0, node_count * 1.8)),
                    direction=bend_direction,
                )
                kind = "stem_section" if axis_index == 0 else "branch_section"
                stem = self._add(
                    placements,
                    kind,
                    parent,
                    x,
                    y,
                    z,
                    angle,
                    (0.68 if woody else 0.52) + 0.28 * maturity,
                    1,
                    placement_paths=placement_paths,
                    path=path,
                )
                total_axis_length += math.dist(previous, endpoint)
                max_radius = max(max_radius, math.hypot(x, y))
                add_leaf_socket(stem, endpoint, angle, axis_index, node_index, 1)

                for lateral_index in range(lateral_axes_per_primary if maturity >= 0.25 else 0):
                    target_fraction = (0.18 + 0.65*lateral_index/max(1,lateral_axes_per_primary-1)
                                       if twig_density > 0 else 0.38 + lateral_index * 0.27)
                    if abs(fraction - target_fraction) <= 0.5 / axis_nodes:
                        lateral_starts.append((stem, endpoint, angle, axis_index, lateral_index, reach))
                if (
                    str(growth.get("lateral_axis_orientation") or "") == "plagiotropic"
                    and maturity >= 0.15
                    and node_index in ascending_targets
                ):
                    ascending_starts.append((stem, endpoint, angle, axis_index, node_index))

                if rooting_interval and node_index > 0 and node_index % rooting_interval == 0:
                    rooting_count += 1
                    if rooting_contacts is not None:
                        rooting_contacts.append({
                            "parent_index": stem,
                            "position": (x, y, 0.0),
                        })
                parent = stem
                previous = endpoint

        # High-spread clones overlap short lateral shoots with their primary
        # runners.  The two-level grammar reads as a ramifying mat rather than
        # a radial diagram, while remaining tightly bounded and deterministic.
        for parent, start, parent_angle, axis_index, lateral_index, parent_reach in lateral_starts:
            secondary_axis_count += 1
            side = -1.0 if (axis_index + lateral_index) % 2 else 1.0
            base_angle = parent_angle + side * rng.uniform(42.0, 78.0)
            reach = min(axis_length * rng.uniform(0.16, 0.30), parent_reach * 0.34)
            spur_nodes = max(3, round(node_count * reach / max(axis_length, 1e-6)))
            previous = start
            spur_parent = parent
            for node_index in range(spur_nodes):
                fraction = (node_index + 1) / spur_nodes
                angle = base_angle + side * 8.0 * math.sin(node_index * 0.8 + axis_index)
                radians = math.radians(angle)
                x = start[0] + math.cos(radians) * reach * fraction
                y = start[1] + math.sin(radians) * reach * fraction
                z = max(0.012, start[2] + 0.0025 * math.sin(node_index + lateral_index))
                endpoint = (x, y, z)
                path = self._curved_segment_path(
                    previous,
                    endpoint,
                    bend=min(0.012, reach / max(7.0, spur_nodes * 1.8)),
                    direction=side,
                )
                stem = self._add(
                    placements,
                    "branch_section",
                    spur_parent,
                    x,
                    y,
                    z,
                    angle,
                    0.62 + 0.30 * maturity,
                    2,
                    placement_paths=placement_paths,
                    path=path,
                )
                total_axis_length += math.dist(previous, endpoint)
                max_radius = max(max_radius, math.hypot(x, y))
                add_leaf_socket(stem, endpoint, angle, axis_index, node_index, 2)
                if twig_density > 0 and maturity >= 0.25:
                    targets = {max(1, round((spur_nodes-1)*f)) for f in (0.35, 0.65, 0.85)}
                    if node_index in targets:
                        ascending_starts.append((stem, endpoint, angle, axis_index, node_index+lateral_index*11))
                spur_parent = stem
                previous = endpoint

        # Plagiotropic plants commonly carry short ascending shoots on their
        # ground-hugging framework.  These shoots provide the low shrub's
        # visible depth without turning the primary runners upright.
        for parent, start, parent_angle, axis_index, start_node in ascending_starts:
            ascending_axis_count += 1
            base_angle = parent_angle + rng.uniform(-34.0, 34.0)
            horizontal_reach = min(0.085, axis_length * rng.uniform(0.10, 0.19))
            vertical_reach = min(max_height * rng.uniform(0.16, 0.28), 0.105) * max(0.08, maturity)
            shoot_nodes = max(4, min(9, round(node_count * rng.uniform(0.25, 0.38))))
            previous = start
            shoot_parent = parent
            for node_index in range(shoot_nodes):
                fraction = (node_index + 1) / shoot_nodes
                angle = base_angle + 9.0 * math.sin(node_index * 0.83 + axis_index)
                radians = math.radians(angle)
                x = start[0] + math.cos(radians) * horizontal_reach * fraction
                y = start[1] + math.sin(radians) * horizontal_reach * fraction
                z = start[2] + vertical_reach * fraction ** 1.08
                endpoint = (x, y, z)
                path = self._curved_segment_path(
                    previous,
                    endpoint,
                    bend=min(0.008, horizontal_reach / max(8.0, shoot_nodes * 2.0)),
                    direction=-1.0 if (axis_index + start_node) % 2 else 1.0,
                )
                stem = self._add(
                    placements,
                    "branch_section",
                    shoot_parent,
                    x,
                    y,
                    z,
                    angle,
                    0.60 + 0.32 * maturity,
                    2,
                    placement_paths=placement_paths,
                    path=path,
                )
                total_axis_length += math.dist(previous, endpoint)
                max_radius = max(max_radius, math.hypot(x, y))
                add_leaf_socket(stem, endpoint, angle, axis_index, node_index, 2)
                shoot_parent = stem
                previous = endpoint

        can_reproduce = str(growth.get("reproductive_mode") or "") in {"sexual", "both", "apomictic"}
        axillary = str(growth.get("flowering_position") or "") in {"lateral", "mixed"}
        profile = growth.get("reproductive_profile")
        # An explicit organ recipe prevents inventing 16 cm flowers or 10 cm
        # fruit from generic module defaults on millimetre-leaved shrubs.
        flower_count = fruit_count = 0
        if can_reproduce and axillary and profile:
            for stem, (x, y, z), angle, axis_index, node_index in reproductive_sockets:
                if herb_profile:
                    score = (stem*.61803398875+.17)%1
                    kind = ("fruit" if fruiting_factor > .02 and score < fruiting_factor
                            else "flower" if flowering_factor > .05 else None)
                    if kind is None:
                        continue
                    length = herb_profile["pedicel_length_m"]
                    theta = math.radians(angle + (-1 if node_index%4 else 1)*85)
                    dx,dy = math.cos(theta)*length*.75, math.sin(theta)*length*.75
                    drop = herb_profile["fruit_recurve"] if kind == "fruit" else 0.
                    tip_z = max(.004,z+length*(.65-1.4*drop))
                    path = []
                    for j in range(9):
                        t=j/8
                        # Same axil; fruit stalk rises before recurving down.
                        path.append((x+dx*t,y+dy*t,z+(tip_z-z)*t+length*drop*1.4*t*(1-t)))
                    pedicel = self._add(placements,"branch_section",stem,*path[-1],angle,1.,3,
                        placement_paths=placement_paths,path=path)
                    self._add(placements,kind,pedicel,*path[-1],0.,1.,4)
                    flower_count += kind == "flower"
                    fruit_count += kind == "fruit"
                    continue
                side = -1 if (axis_index + node_index) % 2 else 1
                offset = profile["fruit_size_m"] * 0.65
                radians = math.radians(angle + side * 90)
                socket = (x + math.cos(radians)*offset, y + math.sin(radians)*offset, z + offset*0.5)
                if flowering_factor > 0.05:
                    self._add(placements, "flower", stem, *socket, angle, 0.75 + 0.25*flowering_factor, 3)
                    flower_count += 1
                if fruiting_factor > 0.02:
                    self._add(placements, "fruit", stem, *socket, 0.0, 0.4 + 0.6*fruit_ripeness, 3)
                    fruit_count += 1

        return {
            "creeping_axis_grammar": True,
            **({"creeping_herb_profile_version": herb_profile["version"]} if herb_profile else {}),
            "creeping_grammar_version": 2,
            "creeping_flower_count": flower_count,
            "creeping_fruit_count": fruit_count,
            "creeping_reproductive_socket_count": len(reproductive_sockets),
            "creeping_spread_class": spread_class,
            "creeping_axis_count": axis_count,
            "creeping_secondary_axis_count": secondary_axis_count,
            "creeping_ascending_axis_count": ascending_axis_count,
            "creeping_nodes_per_axis": node_count,
            "creeping_leaf_socket_count": leaf_socket_count,
            "creeping_rooting_contact_count": rooting_count,
            "creeping_footprint_radius_m": round(max_radius, 4),
            "creeping_axis_length_m": round(total_axis_length, 4),
            "creeping_leaf_socket_offset_m": 0.0,
        }

    def _grow_graminoid_culm(
        self,
        placements,
        parent,
        x,
        y,
        angle,
        maturity,
        lod,
        height_factor=1.0,
        flowering_factor=0.0,
        attachment_points=None,
        base_level=1,
        placement_paths=None,
        leaf_clusters=None,
    ):
        """Grow one reusable node-bearing graminoid culm.

        Herbaceous graminoids retain the original basal-leaf representation.
        A woody graminoid uses the same culm axis but carries bounded branch
        complements on upper nodes.  This is a body-plan rule, not a bamboo or
        species lookup, and can therefore be mounted at a crown or at a clonal
        ramet socket.
        """

        growth = self.blueprint.growth
        if growth.get("woody_graminoid_grammar_version"):
            from simulations.species.woody_graminoid_shoots import grow_woody_culm
            return grow_woody_culm(
                self, placements, parent, x, y, angle, maturity, lod,
                height_factor=height_factor, flowering_factor=flowering_factor,
                attachment_points=attachment_points, base_level=base_level,
                placement_paths=placement_paths, leaf_clusters=leaf_clusters)
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        generations = min(10, max(1, int(round((max_height / internode) * maturity))))
        woody = str(growth.get("plant_woodiness") or "").lower() == "woody"
        basal_leaves = str(growth.get("leaf_attachment_pattern") or "") in {
            "basal",  # compatibility with older experimental fixtures
            "basal_tuft",
        }
        branch_nodes = set()
        if woody and generations >= 4:
            branch_nodes = {
                min(generations - 1, max(1, int(round(generations * fraction)) - 1))
                for fraction in (0.58, 0.72, 0.86)
            }

        stem_parent = parent
        culm_nodes = 0
        branch_sections = 0
        visible_leaves = 0
        for generation in range(generations):
            z = max_height * maturity * height_factor * (generation + 1) / generations
            stem = self._add(
                placements,
                "stem_section",
                stem_parent,
                x,
                y,
                z,
                0.0,
                0.65 + 0.35 * maturity,
                base_level,
            )
            culm_nodes += 1

            if lod >= 1 and maturity > 0 and not woody and basal_leaves and generation == 0:
                # A basal/tufted graminoid (real tussock grasses like
                # ryegrass) carries its leaf blades from the crown, not
                # spread one-per-node up the flowering culm. Two earlier
                # attempts both looked wrong against reference photos: one
                # short leaf per node up the culm read as rigid horizontal
                # "rungs" on a ladder; clustering several fixed-aspect leaf
                # *sprites* at the base instead (each just a point + a big
                # render scale, no real geometric length) produced a rigid
                # radial starburst, since a single-point "leaf" placement
                # has no connected path for the renderer to draw -- it is
                # only ever a flat sprite stamped at one point, unlike
                # stem/branch/root, which are drawn as a connected,
                # optionally curved line from parent to point (see
                # SpeciesRenderer._draw_structural_asset_path / §6a). Each
                # blade now gets a real 3D tip position and an actual
                # curved path (the same helper trunks use for their own
                # gentle bend), so the renderer can draw it as a genuine
                # arching line the way it already draws a stem or branch --
                # not a stretched pixel asset (a tapered leaf sprite
                # repeated per curve segment would look worse, not better,
                # per §6a's own stretch rule), just the connected-line
                # fallback SpeciesRenderer._draw_individual already falls
                # back to for stem/branch/root when no asset applies.
                blade_reach = max_height * maturity * height_factor
                blade_start_z = 0.01
                for fan_index in range(3):
                    fan_angle = angle + (fan_index - 1) * 26.0
                    blade_length = blade_reach * (0.55 + 0.12 * fan_index)
                    elevation = math.radians(70.0 - 6.0 * fan_index)
                    horizontal = blade_length * math.cos(elevation)
                    vertical = blade_length * math.sin(elevation)
                    fan_rad = math.radians(fan_angle)
                    tip_x = x + math.cos(fan_rad) * horizontal
                    tip_y = y + math.sin(fan_rad) * horizontal
                    tip_z = blade_start_z + vertical
                    blade_path = [(x, y, blade_start_z)]
                    blade_path.extend(self._curved_segment_path(
                        (x, y, blade_start_z), (tip_x, tip_y, tip_z),
                        bend=blade_length * 0.22, direction=1.0,
                    ))
                    leaf = self._add(
                        placements, "leaf", stem, tip_x, tip_y, tip_z, fan_angle,
                        max(0.3, math.sqrt(maturity)), base_level + 1,
                        placement_paths=placement_paths, path=blade_path,
                    )
                    visible_leaves += 1
                    if attachment_points is not None:
                        attachment_points.append({
                            "stem_placement_index": stem,
                            "leaf_placement_index": leaf,
                            "socket": "leaf",
                            "position_m": [round(x, 4), round(y, 4), round(blade_start_z, 4)],
                        })
            elif lod >= 1 and maturity > 0 and not woody and not basal_leaves and generation < min(3, generations):
                # Along-stem graminoids carry real blades, not point sprites.
                # Use the blueprint's leaf-length interpretation and a
                # bounded arching path so every species sharing this trait
                # combination benefits without a species-specific branch.
                leaf_angle = angle + generation * float(growth.get("phyllotaxis_deg", 137.5) or 137.5)
                # Independent socket noise keeps growth/flower RNG streams
                # unchanged and the same blade orientation across ages/LODs.
                socket_seed = (int(self.seed) ^ (round(x * 10000) * 73856093)
                               ^ (round(y * 10000) * 19349663) ^ (generation * 83492791))
                leaf_rng = random.Random(socket_seed)
                leaf_angle += leaf_rng.uniform(-10.0, 10.0)
                pitch = math.radians(leaf_rng.uniform(-15.0, 15.0))
                blade_length = min(
                    max_height * 0.55,
                    max(0.08, float(growth.get("leaf_length_m", 0.15) or 0.15) * 1.35),
                ) * max(0.20, maturity) * height_factor
                leaf_rad = math.radians(leaf_angle)
                horizontal = blade_length * 0.78
                perpendicular = (-math.sin(leaf_rad), math.cos(leaf_rad))
                blade_path = []
                for fraction, height_fraction in ((0.30, 0.22), (0.68, 0.18), (1.0, -0.08)):
                    lateral = blade_length * 0.045 * math.sin(math.pi * fraction)
                    reach = (horizontal * fraction * math.cos(pitch)
                             - blade_length * height_fraction * math.sin(pitch))
                    rise = (horizontal * fraction * math.sin(pitch)
                            + blade_length * height_fraction * math.cos(pitch))
                    blade_path.append((
                        x + math.cos(leaf_rad) * reach + perpendicular[0] * lateral,
                        y + math.sin(leaf_rad) * reach + perpendicular[1] * lateral,
                        max(0.02, z + rise),
                    ))
                tip_x, tip_y, tip_z = blade_path[-1]
                leaf = self._add(
                    placements, "leaf", stem, tip_x, tip_y, tip_z, leaf_angle,
                    max(0.025, math.sqrt(maturity)), base_level + 1,
                    placement_paths=placement_paths, path=blade_path,
                )
                visible_leaves += 1
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": stem,
                        "leaf_placement_index": leaf,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                    })

            # Woody grasses carry foliage on branch complements rather than
            # painting a generic leaf directly on every tall culm segment.
            if lod >= 1 and generation in branch_nodes:
                complement_size = 3
                branch_length = min(1.2, max(0.18, max_height * 0.06)) * maturity
                for branch_index in range(complement_size):
                    branch_angle = angle + (branch_index - 1) * 34.0
                    branch_parent = stem
                    for section in range(2):
                        fraction = (section + 1) / 2.0
                        bx = x + math.cos(math.radians(branch_angle)) * branch_length * fraction
                        by = y + math.sin(math.radians(branch_angle)) * branch_length * fraction
                        bz = z - branch_length * (0.05 + 0.10 * float(growth.get("branch_droop", 0.25) or 0.25)) * fraction
                        branch = self._add(
                            placements,
                            "branch_section",
                            branch_parent,
                            bx,
                            by,
                            bz,
                            branch_angle,
                            0.58 + 0.28 * maturity,
                            base_level + 1,
                        )
                        branch_sections += 1
                        leaf_angle = branch_angle + (-38.0 if section == 0 else 42.0)
                        leaf = self._add(
                            placements,
                            "leaf",
                            branch,
                            bx,
                            by,
                            bz,
                            leaf_angle,
                            0.68 + 0.32 * maturity,
                            base_level + 2,
                        )
                        visible_leaves += 1
                        if attachment_points is not None:
                            attachment_points.append({
                                "stem_placement_index": branch,
                                "leaf_placement_index": leaf,
                                "socket": "leaf",
                                "position_m": [round(bx, 4), round(by, 4), round(bz, 4)],
                                "side": "branch_complement",
                                "rotation_deg": round(leaf_angle % 360.0, 3),
                            })
                        branch_parent = branch

            if generation == generations - 1 and lod >= 1 and flowering_factor > 0.0:
                self._add(
                    placements, "flower", stem, x, y, z, 0.0,
                    0.65 + 0.35 * flowering_factor, base_level + 2,
                )
            stem_parent = stem
            if not woody:
                drift = 0.0 if growth.get("clonal_spread") == "none" else 0.01 * {
                    "low": 1.0, "moderate": 1.6, "high": 2.4,
                }.get(growth.get("clonal_spread"), 1.0)
                size_factor = max(0.025, math.sqrt(maturity))
                x += math.cos(math.radians(angle)) * drift * size_factor
                y += math.sin(math.radians(angle)) * drift * size_factor

        return {
            "culm_nodes": culm_nodes,
            "branch_sections": branch_sections,
            "visible_leaves": visible_leaves,
            "branch_complements": len(branch_nodes),
        }

    def _grow_tussock(self, placements, maturity, lod, rng, flowering_factor=0.0, attachment_points=None, placement_paths=None, leaf_clusters=None):
        """Independent basal tillers; spread controls footprint, not shoot count.

        Radius/drift factors are bounded qualitative defaults, not measured rates.
        Unknown spread preserves the historical low-spread geometry.
        """
        growth = self.blueprint.growth
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        shoot_count = max(3, int(round(4 + 5 * maturity)))
        spread = {"none": .12, "low": 1., "moderate": 1.6, "high": 2.4}.get(growth.get("clonal_spread"), 1.)
        root = self._growth_origin(placements)
        size_factor = max(.025, math.sqrt(maturity))
        phase = rng.uniform(0., math.tau)
        totals = {"culm_nodes": 0, "branch_sections": 0, "visible_leaves": 0, "branch_complements": 0}
        for shoot in range(shoot_count):
            angle = phase + shoot * math.tau / shoot_count + rng.uniform(-.12, .12)
            height_factor = rng.uniform(.74, 1.)
            x, y = math.cos(angle)*.04*spread*size_factor, math.sin(angle)*.04*spread*size_factor
            result = self._grow_graminoid_culm(
                placements,
                root,
                x,
                y,
                math.degrees(angle),
                maturity,
                lod,
                height_factor=height_factor,
                flowering_factor=flowering_factor,
                attachment_points=attachment_points,
                base_level=1,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
            )
            for key in totals:
                totals[key] += result[key]
        return {
            "graminoid_culm_grammar": True,
            "graminoid_culm_count": shoot_count,
            "graminoid_culm_node_count": totals["culm_nodes"],
            "graminoid_branch_complement_count": totals["branch_complements"],
        }

    def _grow_single_axis(self, placements, maturity, lod, flowering_factor=0.0, attachment_points=None):
        """Grow one upright culm with alternating leaves and one terminal flower."""

        growth = self.blueprint.growth
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        segments = min(14, max(1, int(round((max_height / internode) * maturity))))
        root = self._growth_origin(placements)
        parent = root
        x, y = 0.0, 0.0
        for index in range(segments):
            z = min(max_height * maturity, internode * (index + 1))
            stem = self._add(placements, "stem_section", parent, x, y, z, 0.0, 0.65 + 0.35 * maturity, 1)
            if lod >= 1 and index < max(1, segments - 1):
                side = -1.0 if index % 2 == 0 else 1.0
                leaf_angle = 300.0 if side < 0 else 60.0
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": stem,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                        "side": "left" if side < 0 else "right",
                        "rotation_deg": leaf_angle,
                    })
                self._add(
                    placements,
                    "leaf",
                    stem,
                    x,
                    y,
                    z,
                    leaf_angle,
                    0.55 + 0.45 * maturity,
                    2,
                )
            if index == segments - 1 and lod >= 2 and flowering_factor > 0.0:
                self._add(
                    placements,
                    "flower",
                    stem,
                    x,
                    y,
                    z + 0.02,
                    0.0,
                    0.65 + 0.35 * flowering_factor,
                    2,
                )
            parent = stem
            x += 0.006 * math.sin(index * 0.7)

    def _prune_tree_solid_intersections(
        self,
        placements,
        placement_paths,
        attachment_points,
        leaf_clusters,
        solid_field,
    ):
        """Terminate tree axes that enter a solid and remove their descendants."""

        if not solid_field.structures:
            return {
                "solid_structure_response": "not_supplied",
                "solid_structure_collision_count": 0,
                "solid_structure_pruned_placement_count": 0,
                "solid_structure_avoided_ids": [],
            }

        removed = set()
        collided_ids = []
        collision_count = 0
        structural_kinds = {"stem_section", "branch_section"}
        organ_kinds = {"leaf", "flower", "fruit"}
        for index, placement in enumerate(placements):
            parent = int(placement[1])
            if parent in removed:
                removed.add(index)
                continue
            if placement[0] in structural_kinds and 0 <= parent < len(placements):
                parent_point = tuple(float(value) for value in placements[parent][2:5])
                endpoint = tuple(float(value) for value in placement[2:5])
                path = [parent_point]
                path.extend(tuple(float(value) for value in point[:3]) for point in placement_paths.get(str(index), []))
                if not path or math.dist(path[-1], endpoint) > 1e-7:
                    path.append(endpoint)
                hit = solid_field.path_hit(path)
                if hit is not None:
                    removed.add(index)
                    collision_count += 1
                    collided_ids.append(str(hit["structure"]["id"]))
            elif placement[0] in organ_kinds:
                hit = solid_field.contains(placement[2:5])
                if hit is not None:
                    removed.add(index)
                    collided_ids.append(str(hit["structure"]["id"]))

        if not removed:
            return {
                "solid_structure_response": "collision_gated_growth",
                "solid_structure_collision_count": 0,
                "solid_structure_pruned_placement_count": 0,
                "solid_structure_avoided_ids": [],
            }

        index_map = {}
        kept = []
        for old_index, placement in enumerate(placements):
            if old_index in removed:
                continue
            new_placement = list(placement)
            parent = int(new_placement[1])
            new_placement[1] = index_map[parent] if parent >= 0 else -1
            index_map[old_index] = len(kept)
            kept.append(new_placement)
        placements[:] = kept

        remapped_paths = {}
        for key, path in list(placement_paths.items()):
            try:
                old_index = int(key)
            except (TypeError, ValueError):
                continue
            if old_index in index_map:
                remapped_paths[str(index_map[old_index])] = path
        placement_paths.clear()
        placement_paths.update(remapped_paths)

        remapped_hints = {}
        for key, orientation in list((getattr(self, "_placement_orientation_hints", {}) or {}).items()):
            try:
                old_index = int(key)
            except (TypeError, ValueError):
                continue
            if old_index in index_map:
                remapped_hints[str(index_map[old_index])] = orientation
        self._placement_orientation_hints = remapped_hints

        retained_clusters = []
        retained_cluster_ids = set()
        for cluster in leaf_clusters:
            old_host = int(cluster.get("host_placement_index", -1) or -1)
            if old_host not in index_map:
                continue
            updated = dict(cluster)
            updated["host_placement_index"] = index_map[old_host]
            for field_name in ("leader_base_index", "leader_tip_index"):
                if field_name in updated:
                    updated[field_name] = index_map[int(updated[field_name])]
            if "sample_placement_indices" in updated:
                updated["sample_placement_indices"] = [
                    index_map[index]
                    for index in updated.get("sample_placement_indices", [])
                    if index in index_map
                ]
            retained_clusters.append(updated)
            retained_cluster_ids.add(str(updated.get("id")))
        leaf_clusters[:] = retained_clusters

        retained_attachments = []
        for attachment in attachment_points:
            updated = dict(attachment)
            valid = True
            for field_name in ("stem_placement_index", "leaf_placement_index"):
                if field_name not in updated:
                    continue
                old_index = int(updated[field_name])
                if old_index not in index_map:
                    valid = False
                    break
                updated[field_name] = index_map[old_index]
            if updated.get("cluster_id") is not None and str(updated["cluster_id"]) not in retained_cluster_ids:
                valid = False
            if valid:
                retained_attachments.append(updated)
        attachment_points[:] = retained_attachments

        return {
            "solid_structure_response": "collision_gated_growth",
            "solid_structure_collision_count": collision_count,
            "solid_structure_pruned_placement_count": len(removed),
            "solid_structure_avoided_ids": sorted(set(collided_ids)),
        }

    def _grow_tree(self, placements, maturity, lod, flowering_factor=0.0, fruiting_factor=0.0, attachment_points=None, placement_paths=None, leaf_clusters=None, rng=None, detail=False, leaf_factor=1.0):
        """Grow a restrained woody tree from the functional plant fields.

        The trunk is one dominant axis. Primary branches are inserted at
        distinct trunk heights, extend along their own directions, and then
        droop into short terminal twigs. Leaves are terminal-twig organs and
        reproductive modules use the same branch tips. This is intentionally a
        compact architectural graph, not a leaf-by-leaf forest canopy.
        """

        growth = self.blueprint.growth
        if growth.get("shoot_distribution_grammar"):
            from simulations.species.tree_shoots import grow_tree_shoots
            return grow_tree_shoots(self, placements, maturity, lod, leaf_clusters, attachment_points, placement_paths, flowering_factor, fruiting_factor, detail=detail, leaf_factor=leaf_factor)
        rng = rng or random.Random(0)
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        trunk_segments = min(14, max(1, int(round((max_height / internode) * maturity))))
        phyllotaxis = float(growth.get("phyllotaxis_deg", 137.5) or 137.5)
        growth_bias = max(0.0, min(1.0, float(growth.get("growth_rate_bias", 0.55) or 0.55)))
        spread = (0.75 + growth_bias * 0.55) * rng.uniform(0.92, 1.08)
        angle_offset = rng.uniform(-4.0, 4.0)
        clustering = str(growth.get("leaf_clustering") or "distributed").lower()
        leaf_distribution = str(growth.get("leaf_distribution") or "terminal_cluster").lower()
        shoot_dimorphism = str(growth.get("shoot_dimorphism") or "single_shoot_system").lower()
        leaf_spacing_bias = max(0.0, min(1.0, float(growth.get("leaf_spacing_bias", 0.5) or 0.5)))
        branch_droop = max(0.0, min(1.0, float(growth.get("branch_droop", 0.5) or 0.5)))
        branch_angle_gradient = max(0.0, min(1.0, float(growth.get("branch_angle_gradient", 0.5) or 0.5)))
        crown_openness = max(0.0, min(1.0, float(growth.get("crown_openness", 0.5) or 0.5)))
        leaf_depth_gradient = max(0.0, min(1.0, float(growth.get("leaf_depth_gradient", 0.35) or 0.35)))
        fine_twig_density = max(0.0, min(1.0, float(growth.get("fine_twig_density", 0.5) or 0.5)))
        leaf_cluster_density = max(0.0, min(1.0, float(growth.get("leaf_cluster_density", 0.5) or 0.5)))
        leaf_module = self.blueprint.module("leaf")
        leaf_length = max(0.01, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
        leaf_radius = max(0.005, float(getattr(leaf_module, "radius_m", 0.01) or 0.01))
        leaf_area_per_leaf = max(0.0005, leaf_length * leaf_radius * 1.8)
        leaf_count = 3 if self.blueprint.growth.get("shape") == "tree" or clustering in {"dense_cluster", "rosette"} else 2
        reproduction = str(growth.get("reproductive_mode") or "").lower()
        can_flower = reproduction in {"sexual", "both", "apomictic", ""}

        root_z = -0.04 if str(growth.get("root_depth_class") or "") == "shallow" else -0.08
        root = self._growth_origin(placements, root_z=root_z)
        parent = root
        trunk_x, trunk_y = 0.0, 0.0
        trunk_indices = []
        for index in range(trunk_segments):
            z = min(max_height * maturity, internode * (index + 1))
            trunk_x += 0.004 * math.sin(index * 0.65) + angle_offset * 0.00015
            trunk_end = (trunk_x, trunk_y, z)
            parent_position = placements[parent][2:5] if parent >= 0 else (0.0, 0.0, root_z)
            trunk_path = self._curved_segment_path(
                parent_position,
                trunk_end,
                bend=0.004 * (0.8 + growth_bias * 0.5),
                direction=-1.0 if index % 2 else 1.0,
            )
            stem = self._add(
                placements,
                "stem_section",
                parent,
                trunk_end[0],
                trunk_end[1],
                trunk_end[2],
                0.0,
                0.7 + 0.3 * ((index + 1) / max(1, trunk_segments)),
                1,
                placement_paths=placement_paths,
                path=trunk_path,
            )
            trunk_indices.append((stem, trunk_end))
            parent = stem

        if lod == 0 or trunk_segments < 3:
            return

        # Branch insertion follows the trunk rather than spawning recursively.
        # This makes the mature birch airy and keeps its structural budget
        # legible in both the detailed sim and its baked scenery product.
        branch_levels = max(
            1,
            min(
                6,
                int(round(
                    (2 + maturity * 4) * (1.08 - 0.22 * crown_openness)
                    + rng.uniform(-0.45, 0.45)
                )),
            ),
        )
        insertion_indices = [
            min(trunk_segments - 2, max(1, int(round((level + 1) * (trunk_segments - 2) / branch_levels))))
            for level in range(branch_levels)
        ]
        for level, trunk_index in enumerate(insertion_indices):
            trunk_parent, anchor = trunk_indices[trunk_index]
            side_count = 2 if level % 2 == 0 else 1
            crown_fraction = level / max(1, branch_levels - 1)
            for side_index in range(side_count):
                side = -1.0 if side_index == 0 else 1.0
                angle = phyllotaxis * (level + 1) + angle_offset + side * (38.0 + 4.0 * (level % 3))
                branch_parent = trunk_parent
                bx, by, bz = anchor
                bz += rng.uniform(-0.08, 0.08) * internode
                branch_orders = 3 if level < max(1, branch_levels // 2) else 2
                branch_segment_start = (bx, by, bz)
                for order in range(branch_orders):
                    # Branch length must live on the same scale as the
                    # authored tree height. The old fixed 0.10 m step made a
                    # 30 m birch look like a pole with tiny nubs.
                    lateral_step = max(
                        0.24,
                        min(2.4, max_height * 0.045),
                    ) * spread * (1.12 - 0.16 * crown_fraction + 0.10 * order)
                    bx += math.cos(math.radians(angle)) * lateral_step
                    by += math.sin(math.radians(angle)) * lateral_step
                    if order == 0:
                        # Birch limbs rise from the trunk before opening out;
                        # upper limbs rise more while lower limbs stay broad.
                        rise = internode * (
                            0.04
                            + 0.30 * crown_fraction
                            + 0.42 * branch_angle_gradient * crown_fraction
                        )
                        bz = min(max_height * maturity, bz + rise)
                    else:
                        # Terminal branchlets turn down, giving the crown its
                        # characteristic light, pendulous outline. Lower limbs
                        # droop more strongly than the upper crown.
                        droop = internode * (
                            0.04
                            + branch_droop * (0.16 + 0.18 * (1.0 - crown_fraction))
                        )
                        bz = max(0.22, bz - droop)
                    end = (bx, by, bz)
                    parent_position = placements[branch_parent][2:5]
                    branch_path = self._curved_segment_path(
                        parent_position,
                        end,
                        bend=0.006 * spread * (1.0 + 0.1 * level),
                        direction=side,
                    )
                    branch = self._add(
                        placements,
                        "branch_section",
                        branch_parent,
                        end[0],
                        end[1],
                        end[2],
                        angle,
                        (0.7 + 0.3 * maturity)
                        * max(0.60, 1.0 - 0.14 * order - 0.08 * crown_fraction),
                        2 + order,
                        placement_paths=placement_paths,
                        path=branch_path,
                    )
                    branch_parent = branch

                    if lod >= 1:
                        # Long shoots carry leaves along their length. Birch
                        # also has compact short shoots near twig ends, so the
                        # mixed grammar deliberately keeps both patterns.
                        if leaf_distribution in {"along_shoot", "mixed_long_short_shoots"}:
                            is_long_shoot = order == 0 or shoot_dimorphism != "long_and_short_shoots"
                            if is_long_shoot:
                                long_leaf_count = max(1, min(3, int(round(1 + 2 * leaf_spacing_bias))))
                                if long_leaf_count == 1:
                                    leaf_fractions = (0.66,)
                                elif long_leaf_count == 2:
                                    leaf_fractions = (0.38, 0.78)
                                else:
                                    leaf_fractions = (0.28, 0.56, 0.84)
                                for leaf_index, fraction in enumerate(leaf_fractions):
                                    leaf_x = branch_segment_start[0] + (end[0] - branch_segment_start[0]) * fraction
                                    leaf_y = branch_segment_start[1] + (end[1] - branch_segment_start[1]) * fraction
                                    leaf_z = branch_segment_start[2] + (end[2] - branch_segment_start[2]) * fraction
                                    leaf_angle = angle + (180.0 if leaf_index % 2 else 0.0) + phyllotaxis * 0.12 * leaf_index
                                    leaf_radius = 0.028 + 0.010 * leaf_index
                                    leaf_x += math.cos(math.radians(leaf_angle)) * leaf_radius
                                    leaf_y += math.sin(math.radians(leaf_angle)) * leaf_radius
                                    leaf_z = max(0.2, leaf_z + (0.018 if leaf_index % 2 else 0.0))
                                    leaf_scale = (0.72 + 0.28 * maturity) * (
                                        1.0 + leaf_depth_gradient * (1.0 - crown_fraction) * 0.25
                                    )
                                    cluster_leaf_count = (
                                        4
                                        + round(10.0 * leaf_cluster_density)
                                        + round(4.0 * fine_twig_density)
                                        + round(2.0 * (1.0 - crown_fraction))
                                    )
                                    cluster_id = self._add_leaf_cluster(
                                        leaf_clusters,
                                        branch_parent,
                                        leaf_x,
                                        leaf_y,
                                        leaf_z,
                                        cluster_leaf_count * (0.82 + 0.18 * maturity),
                                        cluster_leaf_count * leaf_area_per_leaf * leaf_scale,
                                        order,
                                        visual_density=0.45 + leaf_cluster_density * 0.45,
                                    )
                                    if attachment_points is not None:
                                        attachment_points.append({
                                            "stem_placement_index": branch_parent,
                                            "cluster_id": cluster_id,
                                            "socket": "leaf",
                                            "position_m": [round(leaf_x, 4), round(leaf_y, 4), round(leaf_z, 4)],
                                            "side": "left" if leaf_index % 2 == 0 else "right",
                                            "rotation_deg": round(leaf_angle % 360.0, 3),
                                        })
                                    self._add(placements, "leaf", branch_parent, leaf_x, leaf_y, leaf_z, leaf_angle, leaf_scale, 4)

                        if (
                            leaf_distribution == "mixed_long_short_shoots"
                            and shoot_dimorphism == "long_and_short_shoots"
                            and order == branch_orders - 1
                        ):
                            # Short shoots are compact, with two leaves just
                            # before the twig tip rather than a large cluster.
                            short_cluster_count = max(
                                2,
                                round(2.0 + 4.0 * leaf_cluster_density + 3.0 * fine_twig_density),
                            )
                            short_cluster_id = self._add_leaf_cluster(
                                leaf_clusters,
                                branch_parent,
                                branch_segment_start[0] + (end[0] - branch_segment_start[0]) * 0.84,
                                branch_segment_start[1] + (end[1] - branch_segment_start[1]) * 0.84,
                                branch_segment_start[2] + (end[2] - branch_segment_start[2]) * 0.84,
                                short_cluster_count,
                                short_cluster_count * leaf_area_per_leaf * 0.92,
                                order,
                                visual_density=0.60 + leaf_cluster_density * 0.35,
                            )
                            for leaf_index, fraction in enumerate((0.72, 0.94)):
                                leaf_x = branch_segment_start[0] + (end[0] - branch_segment_start[0]) * fraction
                                leaf_y = branch_segment_start[1] + (end[1] - branch_segment_start[1]) * fraction
                                leaf_z = branch_segment_start[2] + (end[2] - branch_segment_start[2]) * fraction
                                leaf_angle = angle + (180.0 if leaf_index else 0.0) + phyllotaxis * 0.06 * leaf_index
                                leaf_radius = 0.025 + 0.008 * leaf_index
                                leaf_x += math.cos(math.radians(leaf_angle)) * leaf_radius
                                leaf_y += math.sin(math.radians(leaf_angle)) * leaf_radius
                                leaf_z = max(0.2, leaf_z + (0.015 if leaf_index else 0.0))
                                leaf_scale = (0.72 + 0.28 * maturity) * (
                                    1.0 + leaf_depth_gradient * (1.0 - crown_fraction) * 0.25
                                ) * 0.92
                                if attachment_points is not None:
                                    attachment_points.append({
                                        "stem_placement_index": branch_parent,
                                        "cluster_id": short_cluster_id,
                                        "socket": "leaf",
                                        "position_m": [round(leaf_x, 4), round(leaf_y, 4), round(leaf_z, 4)],
                                        "side": "left" if leaf_index == 0 else "right",
                                        "rotation_deg": round(leaf_angle % 360.0, 3),
                                    })
                                self._add(placements, "leaf", branch_parent, leaf_x, leaf_y, leaf_z, leaf_angle, leaf_scale, 4)

                        if leaf_distribution in {"terminal_cluster", "branch_tips"} and order == branch_orders - 1:
                            terminal_cluster_id = self._add_leaf_cluster(
                                leaf_clusters,
                                branch_parent,
                                bx,
                                by,
                                bz,
                                leaf_count,
                                leaf_count * leaf_area_per_leaf,
                                order,
                                visual_density=0.65,
                            )
                            for leaf_index in range(leaf_count):
                                leaf_angle = angle + (180.0 if leaf_index % 2 else 0.0) + phyllotaxis * 0.12 * leaf_index
                                leaf_radius = 0.035 + 0.012 * leaf_index
                                leaf_x = bx + math.cos(math.radians(leaf_angle)) * leaf_radius
                                leaf_y = by + math.sin(math.radians(leaf_angle)) * leaf_radius
                                leaf_z = max(0.2, bz + (0.025 if leaf_index % 2 else 0.0))
                                if attachment_points is not None:
                                    attachment_points.append({
                                        "stem_placement_index": branch_parent,
                                        "cluster_id": terminal_cluster_id,
                                        "socket": "leaf",
                                        "position_m": [round(leaf_x, 4), round(leaf_y, 4), round(leaf_z, 4)],
                                        "side": "left" if leaf_index % 2 == 0 else "right",
                                        "rotation_deg": round(leaf_angle % 360.0, 3),
                                    })
                                self._add(placements, "leaf", branch_parent, leaf_x, leaf_y, leaf_z, leaf_angle, 0.72 + 0.28 * maturity, 4)

                    branch_segment_start = end
                    if flowering_factor > 0.0 and can_flower and lod >= 2 and level >= branch_levels - 2:
                        self._add(
                            placements,
                            "flower",
                            branch_parent,
                            bx,
                            by,
                            bz + 0.035,
                            angle,
                            0.65 + 0.35 * flowering_factor,
                            4,
                        )


    def _grow_clonal(
        self,
        placements,
        maturity,
        lod,
        rng,
        attachment_points=None,
        placement_paths=None,
        rooting_contacts=None,
        leaf_clusters=None,
        root_index=None,
        ramet_height_scale=1.0,
        tree_clonal_mode=False,
        flowering_factor=0.0,
        shoot_age_fraction=None,
        placement_orientations=None,
        fruiting_factor=0.0,
        leaf_factor=1.0,
    ):
        """Grow connected clone axes, rooted nodes and developed daughter shoots.

        ``plant_growth_behaviour`` determines whether the connecting axis is a
        surface stolon, a shallow rhizome, or a concealed suckering axis.
        ``clonal_spread`` changes the number and reach of ramets without being
        mistaken for a measured rate.  The coefficients are bounded qualitative
        defaults shared by every species using these behaviours.
        """

        growth = self.blueprint.growth
        behaviour = str(growth.get("growth_behaviour") or "")
        spread_class = str(growth.get("clonal_spread") or "other_unknown")
        spread_profile = {
            "none": (1, 0.35),
            "low": (3, 0.65),
            "moderate": (5, 1.0),
            "high": (8, 1.45),
            "other_unknown": (4, 0.82),
        }.get(spread_class, (4, 0.82))
        mature_ramets, reach_factor = spread_profile
        ramet_count = max(1, 1 + int(round((mature_ramets - 1) * maturity)))
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        reach = min(2.4, max(0.18, max_height * 1.1)) * reach_factor * max(0.08, maturity)
        shoot_profile = growth.get("clonal_forb_profile")
        if shoot_profile:
            reach = shoot_profile["ramet_reach_m"] * max(.08, maturity)
        connector_z = {
            "rhizomatous_clonal": -0.06,
            "stoloniferous_clonal": 0.025,
            "suckering_clonal": -0.08,
        }.get(behaviour, 0.025)
        visible_connector_z = connector_z if behaviour != "suckering_clonal" else -0.04
        root = self._growth_origin(placements) if root_index is None else int(root_index)
        if ramet_count < 3:
            arm_count = 1
        else:
            # A deterministic seed chooses two to four exploration axes.
            # Equal three-spoke stars were a renderer convenience, not a
            # biological claim; bounded imbalance keeps clone topology varied
            # until substrate constraints can steer individual rhizomes.
            arm_count = rng.randint(2, min(4, max(2, int(math.ceil(ramet_count / 2.0)))))
        arm_sizes = [1 for _ in range(arm_count)]
        for _index in range(max(0, ramet_count - arm_count)):
            arm_sizes[rng.randrange(arm_count)] += 1

        leaf_size = str(growth.get("leaf_size_class") or "").lower()
        leaf_scale = {
            "very_small": 0.08,
            "small": 0.22,
            "medium": 0.42,
            "large": 0.62,
            "very_large": 0.82,
        }.get(leaf_size, 0.34)
        leaves_per_node = max(1, int(growth.get("leaves_per_node", 1) or 1))
        if lod == 1:
            leaves_per_node = 1
        lateral_orientation = str(growth.get("lateral_axis_orientation") or "")
        add_lateral_branches = lateral_orientation in {"mixed", "plagiotropic", "pendent"}
        leaf_distribution = str(growth.get("leaf_distribution") or "")
        leaf_structure = str(growth.get("leaf_structure") or "")
        terminal_frond_crowns = (
            behaviour == "rhizomatous_clonal"
            and leaf_distribution == "terminal_cluster"
            and leaf_structure in {"pinnately_compound", "frond_like"}
        )
        clonal_graminoid = (
            str(growth.get("growth_form") or "") == "graminoid"
            and not terminal_frond_crowns
        )
        authored_crown_size = max(1, min(200, int(growth.get("leaf_cluster_size", 3) or 3)))
        canonical_fronds_per_crown = max(1, round(1 + (authored_crown_size - 1) * maturity))
        leaflet_count = max(0, int(growth.get("leaflet_count", 0) or 0))
        leaflet_length = max(0.001, float(growth.get("leaflet_length_m", 0.1) or 0.1))
        leaflet_width = max(0.0002, float(growth.get("leaflet_width_m", 0.01) or 0.01))
        compound_leaf_area = max(0.0005, leaflet_count * leaflet_length * leaflet_width * 0.72)

        rooting_nodes = 0
        runner_axis_length = 0.0
        max_radius = 0.0
        neighbour_root_zones = normalise_neighbour_root_zones(self.environment)
        neighbour_root_avoidance_count = 0
        neighbour_root_total_turn_deg = 0.0
        neighbour_root_min_clearance = None
        ramet_index = 0
        frond_crown_count = 0
        canonical_frond_count = 0
        visible_frond_count = 0
        graminoid_culm_nodes = 0
        graminoid_branch_complements = 0
        phase = rng.uniform(0.0, 360.0)
        arm_angles = [
            phase
            + arm_index * 360.0 / arm_count
            + rng.uniform(-0.22, 0.22) * (360.0 / arm_count)
            for arm_index in range(arm_count)
        ]
        arm_reach_factors = [rng.uniform(0.78, 1.04) for _ in range(arm_count)]
        for arm_index, nodes_on_arm in enumerate(arm_sizes):
            parent = root
            previous = (0.0, 0.0, 0.0)
            base_angle = arm_angles[arm_index]
            heading_drift = rng.uniform(-8.0, 8.0)
            avoidance_heading_bias = 0.0
            for node_index in range(nodes_on_arm):
                fraction = (node_index + 1) / max(1, nodes_on_arm)
                heading_drift = max(-24.0, min(24.0, heading_drift + rng.uniform(-9.0, 9.0)))
                avoidance_heading_bias *= 0.72
                desired_angle = base_angle + heading_drift + avoidance_heading_bias
                radius = reach * arm_reach_factors[arm_index] * fraction
                angle, candidate_end, avoidance_turn = steer_clonal_segment(
                    previous, radius, desired_angle, neighbour_root_zones,
                )
                x, y = candidate_end[0], candidate_end[1]
                runner_end = (x, y, visible_connector_z)
                if abs(avoidance_turn) > 1e-9:
                    neighbour_root_avoidance_count += 1
                    neighbour_root_total_turn_deg += abs(avoidance_turn)
                    avoidance_heading_bias += avoidance_turn
                runner_axis_length += math.dist(previous, runner_end)
                max_radius = max(max_radius, math.hypot(x, y))
                runner_path = self._curved_segment_path(
                    previous,
                    runner_end,
                    bend=0.018 * reach_factor,
                    direction=-1.0 if (node_index + arm_index) % 2 else 1.0,
                )
                if neighbour_root_zones:
                    path_points = [previous, *runner_path]
                    for path_start, path_end in zip(path_points, path_points[1:]):
                        for zone in neighbour_root_zones:
                            clearance = neighbour_root_segment_clearance(path_start, path_end, zone)
                            neighbour_root_min_clearance = (
                                clearance if neighbour_root_min_clearance is None
                                else min(neighbour_root_min_clearance, clearance)
                            )
                runner = self._add(
                    placements,
                    "branch_section",
                    parent,
                    x,
                    y,
                    visible_connector_z,
                    angle,
                    (
                        max(0.018, min(0.08, max_height * 0.0007))
                        if tree_clonal_mode
                        else 0.58 + 0.22 * maturity
                    ),
                    1,
                    placement_paths=placement_paths,
                    path=runner_path,
                )

                # A surface runner or rhizome establishes a local support at
                # each contact.  Suckers already imply a concealed root/crown
                # connection and therefore do not add a visible contact root.
                if behaviour != "suckering_clonal":
                    root_tip_z = min(-0.015, connector_z - 0.025)
                    root_support = self._add(
                        placements,
                        "root_support",
                        runner,
                        x,
                        y,
                        root_tip_z,
                        angle,
                        0.16 + 0.08 * maturity,
                        2,
                    )
                    if rooting_contacts is not None:
                        rooting_contacts.append({
                            "parent_index": root_support,
                            "position": (x, y, root_tip_z),
                        })
                    rooting_nodes += 1

                if terminal_frond_crowns:
                    crown_z = 0.035
                    crown = self._add(
                        placements,
                        "stem_section",
                        runner,
                        x,
                        y,
                        crown_z,
                        angle,
                        0.72 + 0.28 * maturity,
                        2,
                    )
                    if lod == 0:
                        visible_fronds = 0
                    elif lod == 1:
                        visible_fronds = max(2, math.ceil(canonical_fronds_per_crown * 0.5))
                    else:
                        visible_fronds = canonical_fronds_per_crown
                    crown_leaves = []
                    metric_pinnate = bool(growth.get("pinnate_crown_version"))
                    canonical_points = []
                    sampled_ordinals = {round(i * (canonical_fronds_per_crown - 1) / max(1, visible_fronds - 1))
                                        for i in range(visible_fronds)}
                    crown_phase = math.radians(angle + 21.0 * math.sin(ramet_index + 0.5))
                    for frond_index in range(canonical_fronds_per_crown if metric_pinnate else visible_fronds):
                        fraction = frond_index / max(1, visible_fronds)
                        azimuth = crown_phase + math.tau * fraction
                        # Alternating elevation produces an open fountain while
                        # keeping every leaf rooted in the compressed crown.
                        elevation = math.radians(48.0 + 22.0 * ((frond_index * 5) % 7) / 6.0)
                        forward = self._normalise_vector((
                            math.cos(azimuth) * math.cos(elevation),
                            math.sin(azimuth) * math.cos(elevation),
                            math.sin(elevation),
                        ))
                        frond_scale = (0.68 + 0.32 * maturity) * (0.88 + 0.12 * math.sin(frond_index * 2.1 + 1.4))
                        frond_path = None
                        if metric_pinnate:
                            from simulations.species.pinnate_crowns import crown_frond, frond_leaflets
                            frond_path, forward = crown_frond(
                                (x, y, crown_z), crown_phase, frond_index, canonical_fronds_per_crown,
                                float(growth["leaf_length_m"]) * frond_scale,
                                float(growth["leaf_attachment_angle"]), float(growth["crown_openness"]),
                                float(growth["branch_droop"]), float(growth["frond_stipe_fraction"]))
                            canonical_points.extend(frond_path)
                            for base, tip, _ in frond_leaflets(frond_path, leaflet_count, leaflet_length,
                                                             float(growth["frond_stipe_fraction"]), frond_scale):
                                canonical_points.extend((base, tip))
                            if frond_index not in sampled_ordinals:
                                continue
                        rotation = math.degrees(math.atan2(-(forward[0] + forward[1] * 1.8), forward[2]))
                        leaf = self._add(
                            placements,
                            "leaf",
                            crown,
                            x,
                            y,
                            crown_z,
                            rotation,
                            frond_scale,
                            3,
                            placement_paths=placement_paths,
                            path=frond_path,
                        )
                        self._placement_orientation_hints[str(leaf)] = self._orientation_frame(forward)
                        crown_leaves.append(leaf)
                        if attachment_points is not None:
                            attachment_points.append({
                                "stem_placement_index": crown,
                                "leaf_placement_index": leaf,
                                "socket": "terminal_crown",
                                "position_m": [round(x, 4), round(y, 4), crown_z],
                                "side": "radial",
                                "rotation_deg": round(rotation % 360.0, 3),
                            })
                    if leaf_clusters is not None:
                        cluster_id = self._add_leaf_cluster(
                            leaf_clusters,
                            crown,
                            x,
                            y,
                            crown_z,
                            canonical_fronds_per_crown,
                            canonical_fronds_per_crown * compound_leaf_area * maturity,
                            1,
                            visual_density=max(0.1, min(1.0, float(growth.get("leaf_cluster_density", 0.7) or 0.7))),
                        )
                        leaf_clusters[-1].update({
                            "explicit_samples": bool(crown_leaves),
                            "sample_placement_indices": crown_leaves,
                            "leaf_distribution": "terminal_cluster",
                            "organ_structure": leaf_structure,
                            "leaflet_count_per_leaf": leaflet_count,
                            "crown_leaf_count": canonical_fronds_per_crown,
                        })
                        if canonical_points:
                            leaf_clusters[-1]["organ_bounds_m"] = [
                                value for axis in range(3)
                                for value in (min(p[axis] for p in canonical_points), max(p[axis] for p in canonical_points))]
                        for attachment in (attachment_points or []):
                            if attachment.get("leaf_placement_index") in crown_leaves:
                                attachment["cluster_id"] = cluster_id
                    frond_crown_count += 1
                    canonical_frond_count += canonical_fronds_per_crown
                    visible_frond_count += len(crown_leaves)
                    parent = runner
                    previous = runner_end
                    ramet_index += 1
                    continue

                height_factor = 1.0 if ramet_index == 0 else rng.uniform(0.72, 0.94)
                if clonal_graminoid:
                    culm_result = self._grow_graminoid_culm(
                        placements,
                        runner,
                        x,
                        y,
                        angle,
                        maturity,
                        lod,
                        height_factor=height_factor,
                        flowering_factor=flowering_factor,
                        attachment_points=attachment_points,
                        base_level=2,
                        placement_paths=placement_paths,
                        leaf_clusters=leaf_clusters,
                    )
                    graminoid_culm_nodes += culm_result["culm_nodes"]
                    graminoid_branch_complements += culm_result["branch_complements"]
                    parent = runner
                    previous = runner_end
                    ramet_index += 1
                    continue

                if growth.get("clonal_forb_shoot_grammar_version"):
                    # Compose the existing leafy forb axis with clone topology.
                    # Shoot detail must not consume the clone's layout RNG.
                    shoot_rng = random.Random(self.seed ^ (ramet_index + 1) * 1000003)
                    self._grow_iterative_forb(
                        placements, maturity, lod, shoot_rng,
                        flowering_factor=flowering_factor,
                        attachment_points=attachment_points,
                        placement_paths=placement_paths,
                        root_index=runner,
                        origin_xy=(x, y),
                        height_factor=height_factor,
                        axis_phase=angle,
                        terminal_branch_flowering=True,
                        leaf_clusters=leaf_clusters,
                        shoot_age_fraction=shoot_age_fraction,
                        placement_orientations=placement_orientations,
                        fruiting_factor=fruiting_factor,
                        leaf_factor=leaf_factor,
                    )
                    parent = runner
                    previous = runner_end
                    ramet_index += 1
                    continue

                ramet_height = max_height * maturity * height_factor * max(0.02, float(ramet_height_scale))
                dense_shoot = str(growth.get("leaf_clustering") or "") == "dense_cluster"
                segment_density = 1.8 if dense_shoot else 1.0
                segment_count = max(
                    1,
                    min(9 if dense_shoot else 5, int(math.ceil((ramet_height / internode) * segment_density))),
                )
                if lod == 0:
                    segment_count = 1
                stem_parent = runner
                stem_indices = []
                for segment_index in range(segment_count):
                    segment_fraction = (segment_index + 1) / segment_count
                    z = max(0.035, ramet_height * segment_fraction)
                    stem_scale = (
                        max(0.02, ramet_height * 0.012) * (1.0 - 0.48 * segment_fraction)
                        if tree_clonal_mode
                        else 0.62 + 0.38 * segment_fraction
                    )
                    stem = self._add(
                        placements,
                        "stem_section",
                        stem_parent,
                        x,
                        y,
                        z,
                        angle,
                        stem_scale,
                        2,
                    )
                    stem_indices.append(stem)
                    if lod >= 1:
                        for leaf_index in range(leaves_per_node):
                            leaf_angle = angle + leaf_index * 360.0 / leaves_per_node + segment_index * 137.5
                            leaf = self._add(
                                placements,
                                "leaf",
                                stem,
                                x,
                                y,
                                z,
                                leaf_angle,
                                leaf_scale * (0.72 + 0.28 * maturity),
                                3,
                            )
                            if attachment_points is not None:
                                attachment_points.append({
                                    "stem_placement_index": stem,
                                    "leaf_placement_index": leaf,
                                    "socket": "leaf",
                                    "position_m": [round(x, 4), round(y, 4), round(z, 4)],
                                    "side": "clonal_ramet",
                                    "rotation_deg": round(leaf_angle % 360.0, 3),
                                })
                    stem_parent = stem

                # Species with an authored lateral-axis orientation can express
                # a small reusable branch tier on each ramet.  This lets a
                # clubmoss's dendroid shoots differ from an unbranched runner
                # plant without naming the species in the growth code.
                if lod >= 2 and add_lateral_branches and ramet_height > 0.08:
                    branch_droop = max(0.0, min(1.0, float(growth.get("branch_droop", 0.35) or 0.35)))
                    if tree_clonal_mode:
                        tier_fractions = (0.38, 0.52, 0.66, 0.79, 0.90)
                    else:
                        tier_fractions = (0.48, 0.70, 0.86) if dense_shoot else (0.68,)
                    for tier_index, tier_fraction in enumerate(tier_fractions):
                        stem_slot = min(len(stem_indices) - 1, max(0, int(round(tier_fraction * len(stem_indices))) - 1))
                        branch_parent = stem_indices[stem_slot]
                        branch_origin_z = float(placements[branch_parent][4])
                        for side in (-1.0, 1.0):
                            branch_angle = angle + side * (68.0 + tier_index * 8.0)
                            if tree_clonal_mode:
                                branch_length = min(1.8, max(0.24, max_height * 0.025)) * maturity
                            else:
                                branch_length = min(0.18, max_height * 0.16) * maturity
                            branch_length *= 1.0 - tier_index * 0.13
                            branch_parent_index = branch_parent
                            for branch_segment in range(2):
                                branch_fraction = (branch_segment + 1) / 2.0
                                bx = x + math.cos(math.radians(branch_angle)) * branch_length * branch_fraction
                                by = y + math.sin(math.radians(branch_angle)) * branch_length * branch_fraction
                                bz = branch_origin_z - branch_droop * branch_length * branch_fraction * 0.32
                                branch = self._add(
                                    placements,
                                    "branch_section",
                                    branch_parent_index,
                                    bx,
                                    by,
                                    bz,
                                    branch_angle,
                                    (
                                        max(0.006, stem_scale * (0.30 - 0.08 * branch_segment))
                                        if tree_clonal_mode
                                        else 0.58 + 0.25 * maturity
                                    ),
                                    3,
                                )
                                leaf_angle = branch_angle + side * (28.0 + branch_segment * 22.0)
                                leaf = self._add(
                                    placements,
                                    "leaf",
                                    branch,
                                    bx,
                                    by,
                                    bz,
                                    leaf_angle,
                                    leaf_scale * (0.72 + 0.28 * maturity),
                                    4,
                                )
                                if attachment_points is not None:
                                    attachment_points.append({
                                        "stem_placement_index": branch,
                                        "leaf_placement_index": leaf,
                                        "socket": "leaf",
                                        "position_m": [round(bx, 4), round(by, 4), round(bz, 4)],
                                        "side": "lateral",
                                        "rotation_deg": round(leaf_angle % 360.0, 3),
                                    })
                                branch_parent_index = branch

                parent = runner
                previous = runner_end
                ramet_index += 1

        return {
            "clonal_behaviour": behaviour,
            "clonal_spread_class": spread_class,
            "clonal_ramet_count": ramet_count,
            "clonal_axis_count": arm_count,
            "clonal_rooting_node_count": rooting_nodes,
            "clonal_axis_length_m": round(runner_axis_length, 4),
            "clonal_spread_radius_m": round(max_radius, 4),
            "clonal_connector_depth_m": round(connector_z, 4),
            "neighbour_root_model_status": (
                "planar_influence_proxy" if neighbour_root_zones else "not_supplied"
            ),
            "neighbour_root_zones": neighbour_root_zones,
            "neighbour_root_zone_count": len(neighbour_root_zones),
            "neighbour_root_avoidance_count": neighbour_root_avoidance_count,
            "neighbour_root_total_turn_deg": round(neighbour_root_total_turn_deg, 3),
            "neighbour_root_min_clearance_m": (
                round(neighbour_root_min_clearance, 4)
                if neighbour_root_min_clearance is not None else None
            ),
            "terminal_frond_crown_grammar": bool(terminal_frond_crowns),
            "frond_crown_count": frond_crown_count,
            "fronds_per_crown": canonical_fronds_per_crown if terminal_frond_crowns else 0,
            "estimated_frond_count": canonical_frond_count,
            "visible_frond_count": visible_frond_count,
            "leaflets_per_frond": leaflet_count if terminal_frond_crowns else 0,
            "estimated_leaflet_count": canonical_frond_count * leaflet_count,
            "compound_leaf_area_per_frond_m2": round(compound_leaf_area, 6) if terminal_frond_crowns else 0.0,
            "graminoid_culm_grammar": bool(clonal_graminoid),
            "graminoid_culm_count": ramet_count if clonal_graminoid else 0,
            "graminoid_culm_node_count": graminoid_culm_nodes,
            "graminoid_branch_complement_count": graminoid_branch_complements,
            "composed_growth_grammars": (
                ["graminoid_culms", behaviour] if clonal_graminoid else
                ["iterative_forb_shoots", behaviour] if growth.get("clonal_forb_shoot_grammar_version") else
                [behaviour]
            ),
            "clonal_forb_shoot_count": ramet_count if growth.get("clonal_forb_shoot_grammar_version") else 0,
            "tree_clonal_grammar": bool(tree_clonal_mode),
            "tree_sucker_count": ramet_count if tree_clonal_mode else 0,
            "tree_sucker_height_scale": round(float(ramet_height_scale), 4) if tree_clonal_mode else 0.0,
        }

    def _grow_iterative_forb(
        self,
        placements,
        maturity,
        lod,
        rng,
        flowering_factor=0.0,
        attachment_points=None,
        placement_paths=None,
        root_index=None,
        origin_xy=(0.0, 0.0),
        height_factor=1.0,
        axis_phase=0.0,
        terminal_branch_flowering=False,
        leaf_clusters=None,
        shoot_age_fraction=None,
        placement_orientations=None,
        fruiting_factor=0.0,
        leaf_factor=1.0,
        axis_lean_xy=(0.0, 0.0),
    ):
        """Grow a bounded herbaceous main axis with sparse axillary shoots.

        The generic branching grammar is intentionally permissive for broad
        unresolved forms, but it recursively multiplied lateral buds and put
        every resulting endpoint into the same horizontal generation.  An
        authored iterative herbaceous forb instead keeps a dominant main
        axis, a small bounded set of first-order axillary shoots, and lateral
        reproductive modules at upper nodes when those fields are explicit.
        """

        growth = self.blueprint.growth
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0)) * height_factor
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        # Herbaceous forb axes carry more, shorter visible units than the
        # neutral multi-form branching default. Preserve the authored mature
        # height while resolving enough nodes for an alternate leaf sequence.
        effective_internode = internode * 0.68
        segments = min(14, max(1, int(round((max_height / effective_internode) * maturity))))
        shoot_profile = growth.get("basal_subshrub_profile") or growth.get("basal_herb_profile") or growth.get("clonal_forb_profile")
        if shoot_profile:
            effective_internode = max_height / shoot_profile["nodes_per_shoot"]
            segments = max(1, round(shoot_profile["nodes_per_shoot"] * maturity))
        branch_probability = max(
            0.0,
            min(1.0, float(growth.get("branch_probability", 0.18) or 0.0)),
        )
        branch_angle = float(growth.get("branch_angle_deg", 28.0) or 28.0)
        phyllotaxis = float(growth.get("phyllotaxis_deg", 137.5) or 137.5)
        leaves_per_node = max(1, int(growth.get("leaves_per_node", 1) or 1))
        leaf_distribution = str(growth.get("leaf_distribution") or "").lower()
        attachment_pattern = str(growth.get("leaf_attachment_pattern") or "").lower()
        upper_cluster = (
            leaf_distribution == "terminal_cluster"
            or attachment_pattern == "terminal_cluster"
        )
        leaf_start = min(segments - 1, int(math.floor(segments * (0.30 if upper_cluster else 0.0))))

        # Branch probability controls a bounded count, not recursive
        # exponential growth. Candidate nodes exclude the lowest node and the
        # final apex so the main axis remains visually dominant.
        branch_candidates = list(range(max(1, leaf_start), max(1, segments - 1)))
        if terminal_branch_flowering:
            branch_start = (int(math.ceil(segments * shoot_profile["branching_start_fraction"]))
                            if shoot_profile else segments // 2)
            branch_candidates = [node for node in branch_candidates if node >= branch_start]
        branch_target = min(
            4,
            len(branch_candidates),
            max(0, int(round(branch_probability * len(branch_candidates) * 1.35))),
        )
        branch_nodes = set(rng.sample(branch_candidates, branch_target)) if branch_target else set()

        reproductive_mode = str(growth.get("reproductive_mode") or "other_unknown")
        flowering_position = str(growth.get("flowering_position") or "other_unknown")
        reproductive_structure = str(growth.get("reproductive_structure") or "other_unknown")
        can_flower = (
            flowering_factor > 0.0
            and reproductive_mode in {"sexual", "both", "apomictic"}
            and reproductive_structure != "other_unknown"
        )
        can_fruit = ((growth.get("clonal_forb_reproduction_version") or growth.get("basal_subshrub_version") or growth.get("basal_herb_version"))
                     and growth.get("reproductive_profile") and reproductive_structure in {"capitulum", "flower"}
                     and fruiting_factor > .02
                     and reproductive_mode in {"sexual", "both", "apomictic"})

        def add_terminal_head(host, position, order):
            # Reuse the same terminal sockets through the season. These are
            # display clusters, never a measured fruit or floret yield.
            score = (host * .61803398875 + .17) % 1
            if can_fruit and score < fruiting_factor:
                self._add(placements, "fruit", host, *position, 0., 1., order)
            elif can_flower:
                self._add(placements, "flower", host, *position, 0.,
                          .72 + .28 * flowering_factor, order)
        upper_nodes = list(range(max(leaf_start, segments // 2), segments))
        lateral_flower_nodes = set()
        if (can_flower or can_fruit) and flowering_position in {"lateral", "mixed"} and upper_nodes:
            flower_count = min(3, len(upper_nodes))
            lateral_flower_nodes = set(upper_nodes[-flower_count:])

        leaf_module = self.blueprint.module("leaf")
        leaf_area = max(0.0005, max(0.01, leaf_module.length_m)
                        * max(0.005, leaf_module.radius_m) * 1.8)
        if growth.get("basal_subshrub_profile"):
            leaf_area = leaf_module.length_m * shoot_profile["leaf_width_m"] * .72
        if growth.get("basal_herb_profile"):
            leaf_area = leaf_module.length_m * shoot_profile["leaf_width_m"] * .72
            if growth.get("leaf_structure") == "palmately_compound" and growth.get("leaflet_count", 0) > 0:
                # A single compound-leaf placement owns all its leaflet area.
                leaf_area = growth["leaflet_count"] * growth["leaflet_length_m"] * growth["leaflet_width_m"] * .72
        developing_leaves = bool(growth.get("forb_leaf_development_version"))
        mature_node_count = min(14, max(1, round(max_height / effective_internode)))
        if shoot_profile:
            mature_node_count = shoot_profile["nodes_per_shoot"]
        from simulations.species.leaf_development import forb_leaf_development
        leaf_clock = maturity if shoot_age_fraction is None else shoot_age_fraction
        natural_leaf_placement = bool(growth.get("forb_leaf_placement_version"))
        # An independent socket stream leaves clone layout and branch selection
        # untouched, including when leaf samples are hidden at LOD 0.
        socket_rng = random.Random(self.seed ^ round(axis_phase * 1000) ^ 7919)
        from simulations.species.leaf_development import forb_leaf_direction
        from simulations.species.leaf_development import leaf_attachment_direction, leaf_host_tangent
        attachment_angle = growth.get("leaf_attachment_angle")
        transition_fraction = (shoot_profile or {}).get("leaf_arrangement_transition_fraction")
        upper_arrangement = (shoot_profile or {}).get("upper_leaf_arrangement")
        transition_node = (min(segments, max(0, math.ceil(segments * transition_fraction)))
                           if upper_arrangement in {"alternate", "opposite"} and transition_fraction is not None
                           else None)

        root = self._growth_origin(placements) if root_index is None else root_index
        parent = root
        x, y = origin_xy
        if shoot_profile and shoot_profile.get("basal_leaf_count", 0):
            # Optional foliage at a compact crown supplements cauline leaves.
            # Its cohort is canonical even when LOD hides the blade samples.
            basal_count = round(shoot_profile["basal_leaf_count"]*math.sqrt(maturity)*leaf_factor)
            basal_scale = shoot_profile["basal_leaf_length_scale"]*max(.1, math.sqrt(maturity))
            basal_area = leaf_module.length_m * leaf_module.radius_m*2*.72*basal_scale**2
            for basal_index in range(basal_count):
                angle = axis_phase+basal_index*137.507764
                theta = math.radians(angle)
                position = (origin_xy[0]+math.cos(theta)*.004,
                            origin_xy[1]+math.sin(theta)*.004, .014)
                host = self._add(placements, "stem_section", root, *position, angle, .4, 1,
                                placement_paths=placement_paths, path=[placements[root][2:5], position])
                cid = self._add_leaf_cluster(leaf_clusters, host, *position, 1, basal_area, 0)
                if leaf_clusters is not None:
                    leaf_clusters[-1].update(explicit_samples=True, sample_placement_indices=[], cohort="basal_rosette")
                if lod >= 1:
                    leaf = self._add(placements, "leaf", host, *position, angle, basal_scale, 2)
                    if leaf_clusters is not None:
                        leaf_clusters[-1]["sample_placement_indices"].append(leaf)
                    if placement_orientations is not None:
                        placement_orientations[str(leaf)] = self._orientation_frame((math.cos(theta), math.sin(theta), .22))
                    if attachment_points is not None:
                        attachment_points.append({"stem_placement_index":host, "leaf_placement_index":leaf,
                            "socket":"leaf", "position_m":[round(v,4) for v in position],
                            "cluster_id":cid, "cohort":"basal_rosette"})
        main_nodes = []
        for index in range(segments):
            fraction = (index + 1) / max(1, segments)
            z = min(max_height * maturity, effective_internode * (index + 1))
            x += 0.004 * math.sin(index * 0.83)
            y += 0.002 * math.sin(index * 0.47 + 0.6)
            x += axis_lean_xy[0] / max(1, segments)
            y += axis_lean_xy[1] / max(1, segments)
            axis_angle = axis_phase + index * phyllotaxis
            if transition_node is not None and index >= transition_node:
                upper_turn = 137.5 if upper_arrangement == "alternate" else 180.0
                leaf_axis_angle = axis_phase + transition_node * phyllotaxis + (index-transition_node) * upper_turn
                node_leaves_per_node = 1 if upper_arrangement == "alternate" else 2
            else:
                leaf_axis_angle = axis_angle
                node_leaves_per_node = leaves_per_node
            socket_phase = socket_rng.uniform(-1.0, 1.0)
            parent_position = placements[parent][2:5] if parent >= 0 else (0.0, 0.0, 0.0)
            stem_end = (x, y, z)
            stem = self._add(
                placements,
                "stem_section",
                parent,
                *stem_end,
                axis_angle,
                0.66 + 0.34 * fraction,
                1,
                placement_paths=placement_paths,
                path=self._curved_segment_path(
                    parent_position,
                    stem_end,
                    bend=(effective_internode * .012 if growth.get("basal_subshrub_version") or growth.get("basal_herb_version")
                          else 0.004 + effective_internode * 0.018),
                    direction=-1.0 if index % 2 else 1.0,
                ),
            )
            main_nodes.append(stem)

            if index >= leaf_start:
                leaf_position = stem_end
                if natural_leaf_placement:
                    # Stagger the insertion along its actual curved host
                    # section, rather than lining every ramet up on a grid.
                    socket_fraction = max(.3, min(.9,
                        .5 + .5 * float(growth.get("leaf_spacing_bias", .5))
                        + .15 * socket_phase))
                    host_path = [parent_position, *(placement_paths or {}).get(str(stem), [stem_end])]
                    target_z = parent_position[2] + (z - parent_position[2]) * socket_fraction
                    for start, end in zip(host_path, host_path[1:]):
                        if start[2] <= target_z <= end[2]:
                            along = (target_z - start[2]) / max(1e-9, end[2] - start[2])
                            leaf_position = tuple(start[axis] + (end[axis] - start[axis]) * along
                                                  for axis in range(3))
                            break
                leaf_rank = (index - leaf_start) / max(1, segments - leaf_start - 1)
                # Lower leaves are established, the middle cohort is largest,
                # and the newest apical leaves remain smaller. This stretches
                # one approved asset rather than inventing extra leaf objects.
                cohort_factor = 0.80 + 0.20 * max(0.0, 1.0 - abs(leaf_rank - 0.55) * 1.65)
                if terminal_branch_flowering and leaf_rank > 0.7:
                    # Distal cauline leaves grade into smaller bracts rather
                    # than concealing the terminal reproductive socket.
                    cohort_factor *= max(0.28, 1.0 - (leaf_rank - 0.7) * 2.4)
                leaf_scale = (0.68 + 0.32 * maturity) * cohort_factor
                development = None
                area_scale = leaf_scale
                if growth.get("basal_herb_version"):
                    area_scale = leaf_scale ** 2
                if developing_leaves:
                    development = forb_leaf_development(
                        index * 13 / max(1, mature_node_count-1) if shoot_profile else index,
                        14 if shoot_profile else mature_node_count, leaf_clock,
                        growth.get("forb_leaf_length_upper_scale", 1.45),
                    )
                    if shoot_profile:
                        # The approved whole-blade outline supplies its aspect
                        # ratio. The generic forb width proxy otherwise turns
                        # narrow cauline blades into needle-like strips.
                        development.update(width_scale=1.,
                            area_scale=round(development["length_scale"]**2, 6),
                            model="clonal_forb_uniform_blade_proxy")
                    leaf_scale = development["length_scale"]
                    area_scale = development["area_scale"]
                leafy = leaf_factor >= 1. or (index*.61803398875+.17) % 1 < leaf_factor
                cluster_id = self._add_leaf_cluster(
                    leaf_clusters, stem, *leaf_position, node_leaves_per_node if leafy else 0,
                    leaf_area * area_scale * node_leaves_per_node if leafy else 0., 0, visual_density=1.0, allow_empty=True,
                )
                if leaf_clusters is not None:
                    leaf_clusters[-1].update(explicit_samples=True, sample_placement_indices=[])
                    if development is not None:
                        leaf_clusters[-1]["leaf_development"] = dict(development)
                for leaf_index in range(node_leaves_per_node if lod >= 1 and leafy else 0):
                    leaf_angle = leaf_axis_angle + leaf_index * 360.0 / node_leaves_per_node
                    if attachment_points is not None:
                        attachment_points.append({
                            "stem_placement_index": stem,
                            "socket": "leaf",
                            "position_m": [round(value, 4) for value in leaf_position],
                            "rotation_deg": round(leaf_angle, 3),
                            **({"cluster_id": cluster_id} if cluster_id else {}),
                            **({"leaf_development": dict(development)} if development is not None else {}),
                        })
                    leaf_placement = self._add(
                        placements,
                        "leaf",
                        stem,
                        *leaf_position,
                        leaf_angle,
                        leaf_scale,
                        2,
                    )
                    if attachment_points is not None:
                        attachment_points[-1]["leaf_placement_index"] = leaf_placement
                    if (natural_leaf_placement or attachment_angle is not None) and placement_orientations is not None:
                        forward = forb_leaf_direction(
                            leaf_angle, index / max(1, mature_node_count - 1), socket_phase)
                        if attachment_angle is not None:
                            tangent = leaf_host_tangent(parent_position,
                                (placement_paths or {}).get(str(stem), [stem_end]), leaf_position)
                            forward = leaf_attachment_direction(forward, tangent, attachment_angle, socket_phase)
                        placement_orientations[str(leaf_placement)] = {
                            "forward": forward,
                            "model": "leaf_host_angle_v1" if attachment_angle is not None else "forb_socket_direction_v1",
                        }
                    if leaf_clusters is not None:
                        leaf_clusters[-1]["sample_placement_indices"].append(leaf_placement)

            if index in branch_nodes:
                branch_rotation = axis_angle + (-branch_angle if index % 2 else branch_angle)
                branch_radians = math.radians(branch_rotation)
                branch_length = effective_internode * (0.82 + 0.28 * rng.random())
                umbellifer = bool(growth.get("umbellifer_forb_grammar_version"))
                if terminal_branch_flowering:
                    branch_length *= 1.35 if umbellifer else 2.0
                # Ascending reproductive axes need vertical room near the
                # apex; clipping them to the stem height flattened the rays.
                lateral_spread = 0.42 if umbellifer else 0.78
                branch_end = (
                    x + math.cos(branch_radians) * branch_length * lateral_spread,
                    y + math.sin(branch_radians) * branch_length * lateral_spread,
                    min(max_height * maturity + effective_internode * (0.55 if umbellifer else 0.18),
                        z + branch_length * (0.85 if terminal_branch_flowering else 0.42)),
                )
                from simulations.species.lateral_shoots import lateral_shoot_path, point_on_shoot
                fitted_path = lateral_shoot_path(stem_end, branch_end, max_height*maturity,
                    growth.get("lateral_shoot_length"), growth.get("lateral_shoot_curvature"), socket_phase)
                branch_path = fitted_path if fitted_path is not None else self._curved_segment_path(
                    stem_end, branch_end, bend=0.006, direction=-1.0 if index % 2 else 1.0)
                if fitted_path is not None:
                    branch_end = fitted_path[-1]
                branch = self._add(
                    placements,
                    "branch_section",
                    stem,
                    *branch_end,
                    branch_rotation,
                    0.72 + 0.28 * maturity,
                    2,
                    placement_paths=placement_paths,
                    path=branch_path,
                )
                # Draw the cohort factor even when foliage is hidden so LOD
                # cannot move the later branch endpoints.
                branch_leaf_scale = (0.68 + 0.32 * maturity) * (0.78 + 0.08 * rng.random())
                if terminal_branch_flowering:
                    branch_leaf_scale *= 0.6
                branch_development = None
                branch_area_scale = branch_leaf_scale
                if growth.get("basal_herb_version"):
                    branch_area_scale = branch_leaf_scale ** 2
                if developing_leaves:
                    branch_development = forb_leaf_development(
                        index * 13 / max(1, mature_node_count-1) if shoot_profile else index,
                        14 if shoot_profile else mature_node_count, leaf_clock,
                        growth.get("forb_leaf_length_upper_scale", 1.45), lateral=True,
                    )
                    if shoot_profile:
                        branch_development.update(width_scale=1.,
                            area_scale=round(branch_development["length_scale"]**2, 6),
                            model="clonal_forb_uniform_blade_proxy")
                    branch_leaf_scale = branch_development["length_scale"]
                    branch_area_scale = branch_development["area_scale"]
                branch_leaf_position = (
                    tuple(stem_end[axis] + (branch_end[axis] - stem_end[axis]) * (
                        max(.2, min(.8, .25 + .5 * float(growth.get("leaf_spacing_bias", .5))
                                      + .10 * socket_phase)) if natural_leaf_placement else .6)
                          for axis in range(3))
                    if terminal_branch_flowering else branch_end
                )
                if fitted_path is not None and terminal_branch_flowering:
                    fraction = max(.2, min(.8, .25+.5*float(growth.get("leaf_spacing_bias", .5))
                                                   + .10*socket_phase)) if natural_leaf_placement else .6
                    branch_leaf_position = point_on_shoot(stem_end, branch_path, fraction)
                branch_leafy = leaf_factor >= 1. or (index*.61803398875+.43) % 1 < leaf_factor
                cluster_id = self._add_leaf_cluster(
                    leaf_clusters, branch, *branch_leaf_position, 1 if branch_leafy else 0,
                    leaf_area * branch_area_scale if branch_leafy else 0., 1, visual_density=1.0, allow_empty=True,
                )
                if leaf_clusters is not None:
                    leaf_clusters[-1].update(explicit_samples=True, sample_placement_indices=[])
                    if branch_development is not None:
                        leaf_clusters[-1]["leaf_development"] = dict(branch_development)
                if lod >= 1 and branch_leafy:
                    branch_leaf = self._add(
                        placements,
                        "leaf",
                        branch,
                        *branch_leaf_position,
                        branch_rotation,
                        branch_leaf_scale,
                        3,
                    )
                    if attachment_points is not None:
                        attachment_points.append({
                            "stem_placement_index": branch,
                            "leaf_placement_index": branch_leaf,
                            "socket": "leaf",
                            "position_m": [round(value, 4) for value in branch_leaf_position],
                            "rotation_deg": round(branch_rotation, 3),
                            **({"cluster_id": cluster_id} if cluster_id else {}),
                            **({"leaf_development": dict(branch_development)} if branch_development is not None else {}),
                        })
                    if leaf_clusters is not None:
                        leaf_clusters[-1]["sample_placement_indices"].append(branch_leaf)
                    if (natural_leaf_placement or attachment_angle is not None) and placement_orientations is not None:
                        forward = forb_leaf_direction(
                            branch_rotation + (65 if index % 2 else -65),
                            index / max(1, mature_node_count - 1), socket_phase)
                        if attachment_angle is not None:
                            tangent = leaf_host_tangent(stem_end,
                                (placement_paths or {}).get(str(branch), [branch_end]), branch_leaf_position)
                            forward = leaf_attachment_direction(forward, tangent, attachment_angle, socket_phase)
                        placement_orientations[str(branch_leaf)] = {
                            "forward": forward,
                            "model": "leaf_host_angle_v1" if attachment_angle is not None else "forb_socket_direction_v1",
                        }
                if growth.get("short_lived_subshrub_shoot_version") or growth.get("basal_subshrub_version") or growth.get("basal_herb_version"):
                    # Leafy, ascending laterals retain opposite pairs at bounded
                    # nodes along the shoot, rather than one isolated tip leaf.
                    node_count = min(4, max(1, math.ceil(branch_length / effective_internode)))
                    leaf_phase = branch_rotation + (65 if index % 2 else -65)
                    extra_sockets = [(branch_leaf_position, leaf_phase + side * 360 / leaves_per_node)
                                     for side in range(1, leaves_per_node)]
                    for node in range(1, node_count):
                        position = tuple(stem_end[a] + (branch_end[a]-stem_end[a])
                                         * (.6 * node / node_count) for a in range(3))
                        if fitted_path is not None:
                            position = point_on_shoot(stem_end, branch_path, .6*node/node_count)
                        extra_sockets.extend((position, leaf_phase + side * 360 / leaves_per_node)
                                             for side in range(leaves_per_node))
                    for position, angle in extra_sockets:
                        cluster = self._add_leaf_cluster(leaf_clusters, branch, *position,
                            1, leaf_area * branch_area_scale, 1, visual_density=1.0)
                        if leaf_clusters is not None:
                            leaf_clusters[-1].update(explicit_samples=True, sample_placement_indices=[])
                        if lod >= 1:
                            leaf = self._add(placements, "leaf", branch, *position,
                                             angle, branch_leaf_scale, 3)
                            if leaf_clusters is not None:
                                leaf_clusters[-1]["sample_placement_indices"].append(leaf)
                            if attachment_points is not None:
                                attachment_points.append({"stem_placement_index": branch,
                                    "leaf_placement_index": leaf, "socket": "leaf",
                                    "position_m": [round(v, 4) for v in position],
                                    "rotation_deg": angle, "cluster_id": cluster})
                            if placement_orientations is not None:
                                forward = forb_leaf_direction(angle, .6, socket_phase)
                                if attachment_angle is not None:
                                    tangent = leaf_host_tangent(stem_end,
                                        (placement_paths or {}).get(str(branch), [branch_end]), position)
                                    forward = leaf_attachment_direction(forward, tangent,
                                                                         attachment_angle, socket_phase)
                                placement_orientations[str(leaf)] = {"forward": forward,
                                    "model": "leaf_host_angle_v1" if attachment_angle is not None
                                             else "forb_socket_direction_v1"}
                if (terminal_branch_flowering and lod >= 2 and (can_flower or can_fruit)
                        and flowering_position in {"terminal", "mixed"}):
                    add_terminal_head(branch, branch_end, 3)

            if lod >= 2 and index in lateral_flower_nodes:
                flower_rotation = axis_angle + 32.0
                flower_radians = math.radians(flower_rotation)
                flower_offset = min(0.035, effective_internode * 0.16)
                lateral_fruit = can_fruit and (index * .61803398875 + .31) % 1 < fruiting_factor
                if lateral_fruit or can_flower:
                    self._add(
                        placements,
                        "fruit" if lateral_fruit else "flower",
                        stem,
                        x + math.cos(flower_radians) * flower_offset,
                        y + math.sin(flower_radians) * flower_offset,
                        z + effective_internode * 0.04,
                        flower_rotation,
                        1.0 if lateral_fruit else 0.72 + 0.28 * flowering_factor,
                        2,
                    )

            parent = stem

        if (
            lod >= 2
            and (can_flower or can_fruit)
            and flowering_position in {"terminal", "mixed"}
            and main_nodes
        ):
            apex = placements[main_nodes[-1]]
            add_terminal_head(main_nodes[-1],
                              (float(apex[2]), float(apex[3]),
                               float(apex[4]) + effective_internode * .08), 2)

    def _grow_cane_shrub(self, placements, maturity, lod, rng, life_state,
                         placement_paths, leaf_clusters, attachment_points):
        """Canonical basal canes and short laterals for authored woody shrubs.

        The coefficients are qualitative visual controls. All axes and leaf
        cohorts are constructed independently of LOD; only organ samples vary.
        """
        growth = self.blueprint.growth
        height = max(0.03, min(30.0, float(growth.get("shrub_height_m", growth["max_height_m"])))) * max(0.02, maturity)
        droop = float(growth["branch_droop"])
        openness = float(growth["crown_openness"])
        twigs = float(growth["fine_twig_density"])
        density = float(growth["leaf_cluster_density"])
        orientation = growth["lateral_axis_orientation"]
        cane_count = max(1, round(1 + (4 + 4 * twigs) * maturity))
        node_count = max(2, min(36, round(4 + 24 * maturity * (0.65 + 0.35 * density))))
        crown = self._growth_origin(placements)
        phase = rng.uniform(0, math.tau)
        leaf_ordinal = 0
        fertile_tips = []
        spur_sites = []
        spur_profile = growth.get("woody_spur_profile")
        leaf_module = self.blueprint.module("leaf")
        area = max(0.0005, leaf_module.length_m * leaf_module.radius_m * 1.8)
        if spur_profile:
            area = leaf_module.length_m * spur_profile["leaf_width_m"] * .7
        leaf_factor = life_state.get("leaf_factor", 1.0)
        leaves_per_node = max(1, min(3, int(growth.get("leaves_per_node", 1))))
        fascicled = bool(growth.get("shrub_fascicle_grammar_version"))
        spreading = bool(growth.get("shrub_crown_envelope_version"))
        if fascicled:
            leaves_per_node = max(1, min(12, int(growth.get("fascicle_size", 3))))
            # Tiny broad leaves must not inherit a minimum area larger than
            # the whole blade. This remains an architectural area proxy.
            area = leaf_module.length_m * min(leaf_module.radius_m, leaf_module.length_m*.25) * 1.8

        def add_axis(start_parent, points, kind, order, azimuth, scale):
            nonlocal leaf_ordinal
            parent = start_parent
            hosts = []
            for j, point in enumerate(points):
                start = placements[parent][2:5]
                host = self._add(placements, kind, parent, *point, math.degrees(azimuth),
                                 scale * (1 - 0.38 * j / max(1, len(points)-1)), order,
                                 placement_paths=placement_paths,
                                 path=self._curved_segment_path(start, point, bend=height*0.0015))
                hosts.append(host)
                if spur_profile and order > 0:
                    spur_sites.append((host, azimuth+(1 if j%2 else -1)*1.15))
                # Alternate leaves belong along the shoot, including low
                # lateral branchlets, rather than in a terminal foliage cap.
                leaf_ordinal += 1
                leafy = (leaf_ordinal * 0.61803398875) % 1 < leaf_factor
                if leafy and (order > 0 or j >= max(1, round(len(points) * 0.14))):
                    cluster = self._add_leaf_cluster(leaf_clusters, host, *point, leaves_per_node,
                                                     area * leaves_per_node, order)
                    leaf_clusters[-1]["explicit_samples"] = True
                    if fascicled:
                        cohort = leaf_clusters[-1]
                        cohort.update(leaf_arrangement="fascicled", fascicle_size=leaves_per_node,
                                      fascicle_count=1, sample_placement_indices=[])
                        poses = []
                        for leaf_number in range(leaves_per_node):
                            # A compact fan of independent broad blades shares
                            # one node socket. Do not paint the bundle as one leaf.
                            angle = math.degrees(azimuth) + leaf_number*137.5 + rng.uniform(-9,9)
                            pitch = .25 + .9*(leaf_number+.5)/leaves_per_node + rng.uniform(-.12,.12)
                            size = (.72+.28*maturity)*rng.uniform(.78,1.12)
                            poses.append((angle,pitch,size))
                        cohort["leaf_area_m2"] = round(area*sum(size*size for _,_,size in poses),6)
                        if lod >= 1:
                            for leaf_number,(angle,pitch,size) in enumerate(poses):
                                if lod == 1 and leaf_number % 2:
                                    continue
                                leaf = self._add(placements,"leaf",host,*point,angle,size,order+1)
                                a = math.radians(angle)
                                self._placement_orientation_hints[str(leaf)] = self._orientation_frame(
                                    (math.cos(a),math.sin(a),pitch))
                                cohort["sample_placement_indices"].append(leaf)
                                attachment_points.append({"kind":"leaf","stem_placement_index":host,
                                    "leaf_placement_index":leaf,"cluster_id":cluster,
                                    "position_m":list(placements[leaf][2:5])})
                    elif lod >= 1 and (lod == 2 or leaf_ordinal % 2 == 0):
                        for leaf_number in range(leaves_per_node):
                            angle = (math.degrees(azimuth) + (80 if j % 2 else -95)
                                     + leaf_number * 360 / leaves_per_node + rng.uniform(-18,18))
                            leaf = self._add(placements, "leaf", host, *point, angle,
                                             0.72 + 0.28 * maturity, order+1)
                            a = math.radians(angle)
                            self._placement_orientation_hints[str(leaf)] = self._orientation_frame(
                                (math.cos(a), math.sin(a), 0.24))
                            attachment_points.append({"kind":"leaf", "stem_placement_index":host,
                                                      "leaf_placement_index":leaf, "cluster_id":cluster,
                                                      "position_m":list(point)})
                parent = host
            return hosts

        # Draw canonical random choices from an axis-specific stream. Leaf
        # visibility must not consume the structural random stream.
        for cane in range(cane_count):
            angle = phase + cane * 2.3999632297 + rng.uniform(-0.14,0.14)
            h = height * (0.98 if cane == 0 else rng.uniform(0.55, 0.92))
            reach = h * (0.10 + 0.28 * droop + 0.10 * openness) * (0.25 if cane == 0 else 1.0)
            if spreading:
                reach = h * (.65 + .45*droop + .15*openness) * (.55 if cane == 0 else 1.0)
            if spur_profile:
                reach = h * spur_profile["crown_radius_ratio"] * (.18 if cane == 0 else 1.)
            base_radius = height * 0.045 * (cane > 0)
            base_x, base_y = math.cos(angle)*base_radius, math.sin(angle)*base_radius
            points = []
            for j in range(node_count):
                t = (j+1)/node_count
                radius = reach * t**1.7
                az = angle + 0.12*math.sin(t*math.pi)
                points.append((base_x+math.cos(az)*radius,
                               base_y+math.sin(az)*radius,
                               h*t - h*droop*0.16*t**3))
            # Axis-specific leaf angles are deterministic and LOD neutral.
            leaf_rng = rng
            rng = random.Random(self.seed + cane * 9176 + 131)
            hosts = add_axis(crown,points,"stem_section",0,angle,0.55+0.2*maturity)
            rng = leaf_rng
            lateral_count = max(0, round((3+12*twigs)*(1-0.35*openness)*maturity))
            for lateral in range(lateral_count):
                index = min(node_count-1, max(1, round(node_count*(0.18+0.74*(lateral+0.5)/max(1,lateral_count)))))
                host = hosts[index]; start = placements[host][2:5]
                az = angle + lateral*2.3999632297 + rng.uniform(-0.2,0.2)
                length = height*rng.uniform(0.08,0.18)*(0.7+0.5*(1-openness))
                rise = {"orthotropic":0.85,"plagiotropic":0.10,"mixed":0.45,"pendent":-0.30}[orientation]
                rise += rng.uniform(-0.14,0.14)
                lateral_nodes = (max(3, min(48, round(length / spur_profile["fine_node_spacing_m"])))
                                 if spur_profile else max(3, round(3+4*density)))
                branch_points = []
                for j in range(lateral_nodes):
                    t=(j+1)/lateral_nodes
                    branch_points.append((start[0]+math.cos(az)*length*t,
                                          start[1]+math.sin(az)*length*t,
                                          max(height*0.04,start[2]+length*(rise*t-droop*0.35*t*t))))
                leaf_rng = rng
                rng = random.Random(self.seed + cane*9176 + lateral*97 + 503)
                lateral_hosts = add_axis(host,branch_points,"branch_section",1,az,0.22+0.1*maturity)
                rng = leaf_rng
                fertile_tips.append(lateral_hosts[-1])
                for twig in range(round(3 * twigs * maturity)):
                    twig_host = lateral_hosts[min(lateral_nodes-1, 1+twig*2)]
                    p = placements[twig_host][2:5]
                    twig_az = az + (-1 if twig%2 else 1)*rng.uniform(0.7,1.3)
                    twig_length = length*rng.uniform(0.4,0.65)
                    twig_nodes = (max(3, min(32, round(twig_length / spur_profile["fine_node_spacing_m"])))
                                  if spur_profile else 4)
                    twig_points = [(p[0]+math.cos(twig_az)*twig_length*t,
                                    p[1]+math.sin(twig_az)*twig_length*t,
                                    p[2]+twig_length*(0.45*t-droop*0.3*t*t))
                                   for t in (n / twig_nodes for n in range(1, twig_nodes+1))]
                    leaf_rng = rng
                    rng = random.Random(self.seed+cane*9176+lateral*97+twig*31+903)
                    twig_hosts = add_axis(twig_host,twig_points,"branch_section",2,twig_az,0.14)
                    rng = leaf_rng
                    fertile_tips.append(twig_hosts[-1])
            fertile_tips.append(hosts[-1])
        sexual = growth.get("reproductive_mode") in {"sexual","both","apomictic"}
        terminal = growth.get("flowering_position") in {"terminal","mixed"}
        flower_count = fruit_count = 0
        if spur_profile:
            from simulations.species.woody_spurs import grow_woody_spurs
            stats = grow_woody_spurs(self, placements, spur_sites, maturity, life_state, placement_paths)
            return {"shrub_cane_count":cane_count, "shrub_cane_grammar_version":1,
                    "shrub_leaf_factor":leaf_factor, **stats}
        if lod >= 1 and sexual and terminal:
            for ordinal, host in enumerate(fertile_tips):
                score = (ordinal * 0.61803398875 + 0.17) % 1
                kind = ("flower" if score < life_state["reproductive_factor"] * 0.55 else
                        "fruit" if score < life_state["fruiting_factor"] * 0.55 else None)
                if kind is None:
                    continue
                p = placements[host]
                stalk = min(0.02, height*0.012)
                self._add(placements,kind,host,p[2],p[3],p[4]+stalk,0.0,1.0,2)
                flower_count += kind == "flower"; fruit_count += kind == "fruit"
        return {"shrub_cane_count":cane_count,"shrub_cane_grammar_version":1,
                "shrub_fertile_tip_count":len(fertile_tips),"shrub_flower_count":flower_count,
                "shrub_fruit_count":fruit_count,"shrub_leaf_factor":leaf_factor}

    def _grow_branching(self, placements, maturity, lod, rng, flowering_factor=1.0, placement_paths=None):
        growth = self.blueprint.growth
        shape = str(growth.get("shape") or "herb")
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        generations = max(1, int(round((max_height / internode) * maturity)))
        generations = min(generations, 14)
        branch_probability = max(0.0, min(1.0, float(growth.get("branch_probability", 0.25) or 0.25)))
        branch_angle = float(growth.get("branch_angle_deg", 28.0) or 28.0)
        phyllotaxis = float(growth.get("phyllotaxis_deg", 137.5) or 137.5)
        spread_scale = max(1.0, max_height / 10.0) if shape == "tree" else 1.0
        # A detailed representative may resolve many branches, but an
        # unconstrained branching probability grows exponentially. Keep the
        # graph bounded and deterministic so it remains suitable for cohort
        # simulation and later scenery baking.
        if shape == "tree":
            max_buds = {0: 4, 1: 7, 2: 10}.get(lod, 10)
        else:
            max_buds = {0: 8, 1: 20, 2: 32}.get(lod, 32)
        leaves_per_node = max(0, int(growth.get("leaves_per_node", 1) or 1))
        if lod == 0:
            leaves_per_node = 0
        elif lod == 1:
            leaves_per_node = min(1, leaves_per_node)

        root = self._growth_origin(placements)
        # Each bud carries its horizontal growth direction. The main axis is
        # nearly vertical; lateral buds keep their own outward vector as they
        # extend, which produces a canopy rather than a stack of vertical
        # branchlets.
        buds = [(root, 0.0, 0.0, 0, 0.0)]
        if shape in {"shrub", "subshrub"}:
            # A shared crown supports distinct outward-growing canes.
            cane_count = max(1, round(1 + 4 * maturity))
            phase = rng.uniform(0.0, 360.0)
            buds = [(root, 0.0, 0.0, 0, phase + i * 360.0 / cane_count)
                    for i in range(cane_count)]
        for generation in range(generations):
            next_buds = []
            for parent, x, y, level, axis_angle in buds:
                fraction = (generation + 1) / max(1, generations)
                if shape == "tree" and level > 0:
                    parent_z = float(placements[parent][4]) if parent >= 0 else 0.0
                    if level == 1:
                        # Main limbs rise gently from their trunk insertion.
                        z = min(max_height * maturity, parent_z + internode * 0.20)
                    else:
                        # Birch twigs are characteristically pendulous; later
                        # orders can bend down while extending outward.
                        z = max(0.18, parent_z - internode * 0.06)
                else:
                    branch_height_factor = max(0.45, 1.0 - 0.12 * level) if shape == "tree" else 1.0
                    z = min(max_height * maturity, internode * (generation + 1) * branch_height_factor)
                lean = math.sin(math.radians(generation * phyllotaxis)) * 0.012 * generation * spread_scale
                module_id = "stem_section" if level == 0 else "branch_section"
                if shape in {"shrub", "subshrub"}:
                    parent_z = float(placements[parent][4])
                    droop = float(growth.get("branch_droop", 0.28))
                    rise = internode * max(0.18, 0.88 - 0.16 * level - droop * fraction)
                    lateral_step = internode * (0.30 + 0.12 * level + droop * fraction)
                    lateral_step *= max(0.03, maturity)
                    end = (x + math.cos(math.radians(axis_angle)) * lateral_step,
                           y + math.sin(math.radians(axis_angle)) * lateral_step,
                           min(max_height * max(0.03, maturity), parent_z + rise))
                    z = end[2]
                elif level == 0:
                    end = (x + lean, y, z)
                else:
                    lateral_step = 0.05 * spread_scale * (1.0 + 0.25 * level)
                    end = (
                        x + math.cos(math.radians(axis_angle)) * lateral_step + lean * 0.35,
                        y + math.sin(math.radians(axis_angle)) * lateral_step,
                        z,
                    )
                parent_position = placements[parent][2:5] if parent >= 0 else (0.0, 0.0, 0.0)
                path = self._curved_segment_path(
                    parent_position,
                    end,
                    bend=0.006 * spread_scale * (1.0 + 0.2 * level),
                    direction=-1.0 if generation % 2 else 1.0,
                )
                stem = self._add(
                    placements,
                    module_id,
                    parent,
                    end[0],
                    end[1],
                    end[2],
                    generation * phyllotaxis,
                    0.65 + 0.35 * fraction,
                    level + 1,
                    placement_paths=placement_paths,
                    path=path,
                )
                for leaf_index in range(leaves_per_node):
                    angle = generation * phyllotaxis + leaf_index * 360.0 / leaves_per_node
                    self._add(
                        placements,
                        "leaf",
                        stem,
                        end[0],
                        end[1],
                        z,
                        angle,
                        0.55 + 0.45 * maturity,
                        level + 2,
                    )
                if (
                    generation == generations - 1
                    and lod >= 2
                    and shape in {"tree", "shrub"}
                    and flowering_factor > 0.0
                ):
                    self._add(
                        placements,
                        "flower",
                        stem,
                        end[0],
                        end[1],
                        z,
                        0.0,
                        (0.75 + maturity * 0.25) * flowering_factor,
                        level + 2,
                )
                if generation + 1 < generations:
                    next_buds.append((stem, end[0], end[1], level, axis_angle))
                    probability = branch_probability * (1.0 - 0.45 * float(growth.get("apical_dominance", 0.5) or 0.5))
                    if rng.random() < probability:
                        for direction in (-1.0, 1.0):
                            angle = generation * phyllotaxis + direction * branch_angle
                            branch_step = 0.04 * spread_scale * (1.0 + 0.25 * level)
                            next_buds.append((
                                stem,
                                end[0] + math.cos(math.radians(angle)) * branch_step,
                                end[1] + math.sin(math.radians(angle)) * branch_step,
                                level + 1,
                                angle,
                            ))
            buds = next_buds[:max_buds]

    def generate_snapshot(self, age_days=None, lod=None, detail=False):
        age_days = self.age_days if age_days is None else max(0.0, float(age_days))
        lod = self.lod if lod is None else max(0, min(2, int(lod)))
        if self.blueprint.growth.get("fungal_grammar_version"):
            from simulations.species.fungal_growth import build_fungal_snapshot
            return build_fungal_snapshot(self, age_days, lod)
        maturity = self._maturity(age_days)
        if self.blueprint.growth.get('moss_turf_version'):
            from simulations.species.moss_turfs import build_moss_snapshot
            return build_moss_snapshot(self, age_days, lod, maturity)
        life_state = self.life_state(age_days)
        rng = random.Random(self.seed)
        placements = []
        self._placement_orientation_hints = {}
        attachment_points = []
        leaf_clusters = []
        placement_paths = {}
        structural_axis_length_m = None
        clonal_stats = {}
        graminoid_stats = {}
        vine_stats = {}
        sympodial_stats = {}
        rosette_stats = {}
        rooting_contacts = []
        solid_field = SolidStructureField.from_environment(self.environment)
        if self.blueprint.growth.get("growth_behaviour") == "surface_covering":
            from simulations.species.surface_growth import build_surface_snapshot
            return build_surface_snapshot(self, age_days, lod, maturity, solid_field,
                                          normalise_climbing_supports(self.environment))
        rod_structures = normalise_rod_structures(self.environment)
        solid_stats = {
            "solid_structure_count": len(solid_field.structures),
            "solid_structures": solid_field.structures,
            "solid_structure_status": "available" if solid_field.structures else "not_supplied",
            "rod_structure_count": len(rod_structures),
            "rod_structures": rod_structures,
            "rod_structure_status": "available" if rod_structures else "not_supplied",
        }
        shape = str(self.blueprint.growth.get("shape") or "herb")
        behaviour = str(self.blueprint.growth.get("growth_behaviour") or "iterative_indeterminate")
        if self.blueprint.growth.get('renewing_cane_version'):
            from simulations.species.renewing_canes import grow_renewing_canes
            clonal_stats = grow_renewing_canes(self, placements, maturity, lod, age_days,
                life_state, placement_paths, leaf_clusters, attachment_points)
            structural_axis_length_m = clonal_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('seasonal_rhizome_version'):
            from simulations.species.seasonal_rhizomes import grow_seasonal_rhizome
            clonal_stats = grow_seasonal_rhizome(self, placements, maturity, life_state,
                placement_paths, attachment_points, leaf_clusters, rooting_contacts)
            structural_axis_length_m = clonal_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('creeping_upright_version'):
            from simulations.species.creeping_uprights import grow_creeping_uprights
            clonal_stats = grow_creeping_uprights(self, placements, maturity, placement_paths,
                                                attachment_points, leaf_clusters, rooting_contacts)
            structural_axis_length_m = clonal_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('terminal_rosette_version'):
            from simulations.species.terminal_rosettes import grow_terminal_rosettes
            rosette_stats = grow_terminal_rosettes(self, placements, maturity, life_state,
                                                 attachment_points, placement_paths, leaf_clusters)
            structural_axis_length_m = rosette_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('columnar_version'):
            from simulations.species.columnar_succulents import grow_columns
            rosette_stats = grow_columns(self, placements, maturity, life_state, attachment_points, placement_paths)
            structural_axis_length_m = rosette_stats['structural_axis_length_m']
        elif behaviour == 'columnar_succulent' and shape == 'succulent':
            # An explicit column choice without dimensions is unresolved;
            # a basal leaf rosette would contradict its authored body plan.
            self._add(placements,'root',-1,0,0,0,0,1,0)
            rosette_stats={'columnar_model_status':'unresolved_missing_shoot_profile',
                           'estimated_leaf_count':0,'leaf_area_m2':0.,'leaf_cluster_count':0}
            structural_axis_length_m=0.
        elif self.blueprint.growth.get('rhizome_raceme_version'):
            from simulations.species.rhizome_racemes import grow_rhizome_racemes
            clonal_stats = grow_rhizome_racemes(self,placements,maturity,age_days,life_state,
                placement_paths,attachment_points,leaf_clusters,rooting_contacts)
            structural_axis_length_m = clonal_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('mixed_tiller_version'):
            from simulations.species.mixed_tillers import grow_mixed_tillers
            rosette_stats=grow_mixed_tillers(self,placements,maturity,age_days,life_state,
                attachment_points,placement_paths,leaf_clusters)
            structural_axis_length_m=rosette_stats['structural_axis_length_m']
        elif self.blueprint.growth.get('tufted_sedge_version'):
            from simulations.species.tufted_sedges import grow_tufted_sedge
            rosette_stats = grow_tufted_sedge(self,placements,maturity,life_state,
                                            attachment_points,placement_paths,leaf_clusters)
            structural_axis_length_m = rosette_stats['structural_axis_length_m']
        elif self.blueprint.growth.get("emergent_rosette_version"):
            rosette_stats = self._grow_emergent_rosette(
                placements, maturity, life_state["reproductive_factor"], life_state.get("fruiting_factor", 0.),
                attachment_points, placement_paths)
            structural_axis_length_m = rosette_stats["structural_axis_length_m"]
        elif shape == "aquatic":
            self._grow_aquatic_rosette(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
                placement_paths=placement_paths,
            )
        elif self.blueprint.growth.get('paniculate_rosette_version'):
            from simulations.species.paniculate_rosettes import grow_paniculate_rosette
            rosette_stats=grow_paniculate_rosette(self,placements,maturity,life_state,
                                                attachment_points,placement_paths,leaf_clusters)
            structural_axis_length_m=rosette_stats['structural_axis_length_m']
        elif behaviour == "rosette_short_internode" or shape == "rosette":
            rosette_stats = self._grow_rosette(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                fruiting_factor=life_state.get("fruiting_factor", 0.0),
                age_days=age_days,
                attachment_points=attachment_points,
                placement_paths=placement_paths,
            ) or {}
        elif self.blueprint.growth.get("dimorphic_herb_profile_version"):
            from simulations.species.dimorphic_herbs import grow_dimorphic_herb
            clonal_stats = grow_dimorphic_herb(self, placements, maturity, life_state,
                rng, attachment_points, placement_paths, leaf_clusters)
        elif behaviour == "unbranched_single_axis":
            self._grow_single_axis(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
            )
        elif behaviour == "fern_fronding" or shape == "fern":
            clonal_stats = self._grow_fern(
                placements,
                maturity,
                lod,
                rng,
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
                rooting_contacts=rooting_contacts,
            )
        elif behaviour == "basal_succulent_rosette" or shape == "succulent":
            if self.blueprint.growth.get('offset_rosette_version'):
                from simulations.species.offset_rosettes import grow_offset_rosettes
                rosette_stats=grow_offset_rosettes(self,placements,maturity,age_days,
                    attachment_points,placement_paths,leaf_clusters)
                structural_axis_length_m=rosette_stats['structural_axis_length_m']
            else:
                self._grow_succulent(
                    placements,maturity,lod,attachment_points=attachment_points)
        elif behaviour in {"moss_mat", "lichen_crust_radial"} or shape in {"moss", "lichen"}:
            self._grow_moss(
                placements,
                maturity,
                lod,
                attachment_points=attachment_points,
            )
        elif shape == "tree":
            growth_result = self._grow_tree(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                fruiting_factor=life_state["fruiting_factor"],
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
                rng=rng,
                detail=detail,
                leaf_factor=life_state.get("leaf_factor", 1.0),
            )
            if isinstance(growth_result, dict):
                structural_axis_length_m = growth_result.get("structural_axis_length_m")
                if (self.blueprint.growth.get('pendant_branchlet_version') or self.blueprint.growth.get('planar_spray_version')
                        or growth_result.get('tiered_primary_density_version')):
                    clonal_stats.update({k:v for k,v in growth_result.items() if k != 'structural_axis_length_m'})
            from simulations.species.tree_leader_foliage import add_tree_leader_foliage
            add_tree_leader_foliage(
                self, placements, leaf_clusters, attachment_points, maturity, lod,
                detail=detail, leaf_factor=life_state.get("leaf_factor", 1.0),placement_paths=placement_paths,
            )
            if behaviour in {"rhizomatous_clonal", "stoloniferous_clonal", "suckering_clonal"}:
                clone_start = len(placements)
                crown = next(
                    (index for index, placement in enumerate(placements) if placement[0] == "root"),
                    None,
                )
                clonal_result = self._grow_clonal(
                    placements,
                    maturity,
                    2 if self.blueprint.growth.get('planar_spray_version') else lod,
                    random.Random(self.seed),
                    attachment_points=attachment_points,
                    placement_paths=placement_paths,
                    rooting_contacts=rooting_contacts,
                    leaf_clusters=leaf_clusters,
                    root_index=crown,
                    # A snapshot represents one established parent plus a
                    # current cohort of juvenile clonal trees, not several
                    # co-dominant 100 m trunks born on the same day.
                    ramet_height_scale=0.16,
                    tree_clonal_mode=True,
                    flowering_factor=life_state["reproductive_factor"],
                )
                clonal_stats.update(clonal_result)
                clonal_stats.update({
                    "tree_individual_count": 1 + clonal_stats["tree_sucker_count"],
                    "mature_tree_count": 1,
                    "composed_growth_grammars": ["tree", behaviour],
                })

                # Tree cohorts already own calculative clusters. Add one-unit
                # clusters only for the explicit juvenile leaves appended by
                # the clonal grammar.
                leaf_module = self.blueprint.module("leaf")
                leaf_length = max(0.01, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
                leaf_radius = max(0.005, float(getattr(leaf_module, "radius_m", 0.01) or 0.01))
                leaf_area = max(0.0005, leaf_length * leaf_radius * 1.8)
                for leaf_index in range(clone_start, len(placements)):
                    placement = placements[leaf_index]
                    if placement[0] != "leaf":
                        continue
                    if self.blueprint.growth.get('planar_spray_version'):
                        self._placement_orientation_hints.setdefault(str(leaf_index), {})['min_render_lod'] = 1+leaf_index%2
                    cluster_id = self._add_leaf_cluster(
                        leaf_clusters,
                        leaf_index,
                        placement[2],
                        placement[3],
                        placement[4],
                        1,
                        leaf_area * float(placement[6]),
                        max(0, int(placement[7]) - 2),
                        visual_density=1.0,
                    )
                    for attachment in attachment_points:
                        if attachment.get("leaf_placement_index") == leaf_index:
                            attachment["cluster_id"] = cluster_id
                            break
        elif behaviour == "determinate_sympodial":
            sympodial_stats = self._grow_sympodial(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                fruiting_factor=life_state["fruiting_factor"],
                leaf_factor=life_state.get('leaf_factor',1.),
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
            )
            structural_axis_length_m = sympodial_stats.get('structural_axis_length_m')
        elif behaviour == "climbing_support_dependent" or shape == "climber":
            vine_stats = self._grow_vine(
                placements,
                maturity,
                lod,
                rng,
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
                life_state=life_state,
            )
            if self.blueprint.growth.get('branched_vine_version'):
                structural_axis_length_m=vine_stats['vine_axis_length_m']
        elif behaviour == "creeping_prostrate":
            clonal_stats = self._grow_creeping(
                placements,
                maturity,
                lod,
                rng,
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
                rooting_contacts=rooting_contacts,
                flowering_factor=life_state["reproductive_factor"],
                fruiting_factor=life_state["fruiting_factor"],
                fruit_ripeness=life_state.get("fruit_ripeness", 1.0),
            )
            structural_axis_length_m = clonal_stats.get("structural_axis_length_m")
        elif behaviour == "tussock_tillering":
            graminoid_stats = self._grow_tussock(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
            )
        elif behaviour in {"rhizomatous_clonal", "stoloniferous_clonal", "suckering_clonal"}:
            clonal_stats = self._grow_clonal(
                placements,
                maturity,
                lod,
                rng,
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                rooting_contacts=rooting_contacts,
                leaf_clusters=leaf_clusters,
                flowering_factor=life_state["reproductive_factor"],
                shoot_age_fraction=age_days / max(1.0, self.mature_age_days),
                placement_orientations=self._placement_orientation_hints,
                fruiting_factor=life_state["fruiting_factor"],
                leaf_factor=life_state.get("leaf_factor", 1.0),
            )
        elif self.blueprint.growth.get('cushion_version'):
            from simulations.species.cushion_subshrubs import grow_cushion
            clonal_stats = grow_cushion(self, placements, maturity, life_state,
                                        placement_paths, leaf_clusters, attachment_points)
            structural_axis_length_m = clonal_stats['structural_axis_length_m']
        elif self.blueprint.growth.get("basal_herb_version"):
            from simulations.species.basal_herbs import grow_basal_herb
            clonal_stats = grow_basal_herb(
                self, placements, maturity, lod, life_state, placement_paths, leaf_clusters, attachment_points)
        elif self.blueprint.growth.get("basal_subshrub_version"):
            from simulations.species.basal_subshrubs import grow_basal_subshrub
            clonal_stats = grow_basal_subshrub(
                self, placements, maturity, lod, life_state, placement_paths,
                leaf_clusters, attachment_points,
            )
        elif (
            behaviour == "iterative_indeterminate"
            and ((shape == "forb"
                  and str(self.blueprint.growth.get("plant_woodiness") or "") == "herbaceous")
                 or self.blueprint.growth.get("short_lived_subshrub_shoot_version"))
        ):
            self._grow_iterative_forb(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                terminal_branch_flowering=bool(self.blueprint.growth.get("umbellifer_forb_grammar_version")
                                              or self.blueprint.growth.get("short_lived_subshrub_shoot_version")),
                # Cohorts are biological accounting, even when LOD hides all
                # leaf sprites. Rebuilding them from visible placements made
                # ordinary iterative forbs lose their leaf area at LOD 0.
                leaf_clusters=leaf_clusters,
                shoot_age_fraction=age_days/max(1.0,self.mature_age_days) if self.blueprint.growth.get("umbellifer_forb_grammar_version") else None,
                placement_orientations=self._placement_orientation_hints if (
                    self.blueprint.growth.get("umbellifer_forb_grammar_version")
                    or self.blueprint.growth.get("short_lived_subshrub_shoot_version")
                    or "leaf_attachment_angle" in self.blueprint.growth) else None,
            )
        elif self.blueprint.growth.get("shrub_cane_grammar_version"):
            clonal_stats = self._grow_cane_shrub(
                placements, maturity, lod, rng, life_state,
                placement_paths, leaf_clusters, attachment_points,
            )
        else:
            self._grow_branching(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                placement_paths=placement_paths,
            )

        if shape == "tree":
            solid_stats.update(self._prune_tree_solid_intersections(
                placements,
                placement_paths,
                attachment_points,
                leaf_clusters,
                solid_field,
            ))
        elif solid_field.structures and (behaviour == "climbing_support_dependent" or shape == "climber"):
            solid_stats["solid_structure_response"] = "support_surface_climbing"
        elif solid_field.structures:
            solid_stats["solid_structure_response"] = "not_consumed_by_growth_form"

        profile = self.blueprint.growth.get("root_profile") or root_profile(self.blueprint.growth)
        use_distributed_roots = (
            (
                behaviour in {"rhizomatous_clonal", "stoloniferous_clonal"}
                or (
                    behaviour == "fern_fronding"
                    and clonal_stats.get("rhizome_frond_distribution") == "spaced_sockets"
                )
            )
            and profile.get("architecture") == "adventitious"
            and bool(rooting_contacts)
        )
        mixed_contacts = (behaviour == "creeping_prostrate" and profile.get("architecture") == "mixed"
                          and bool(rooting_contacts) and maturity >= 0.25)
        if mixed_contacts:
            crown_index = next(i for i,p in enumerate(placements) if p[0] == "root" and p[1] < 0)
            crown_contact = {"parent_index": crown_index, "position": placements[crown_index][2:5]}
            # Evenly cover a large clone with a bounded representative sample.
            contact_count = min(16,len(rooting_contacts))
            rooting_contacts = [crown_contact] + [rooting_contacts[round(i*(len(rooting_contacts)-1)/max(1,contact_count-1))]
                                                for i in range(contact_count)]
            root_nodes, root_stats = build_mixed_contact_roots(profile, maturity, self.seed, rooting_contacts)
            use_distributed_roots = True
        elif use_distributed_roots:
            root_nodes, root_stats = build_distributed_adventitious_roots(
                profile,
                maturity,
                self.seed,
                rooting_contacts,
            )
        else:
            root_maturity = rosette_stats.get('columnar_size_fraction', maturity)
            root_nodes, root_stats = build_root_graph(profile, root_maturity, self.seed)
        crown = next((i for i, p in enumerate(placements) if p[0] == "root" and p[1] < 0), None)
        renewal_organ = next((i for i, p in enumerate(placements) if p[0] == "renewal_organ"), None)
        root_growth_origin = renewal_organ if renewal_organ is not None else crown
        root_indices = {}
        if use_distributed_roots:
            for index, node in enumerate(root_nodes):
                if node["order"] > lod:
                    continue
                contact = rooting_contacts[node["contact_index"]]
                parent = contact["parent_index"] if node["parent"] < 0 else root_indices[node["parent"]]
                point = [contact["position"][axis] + node["position"][axis] for axis in range(3)]
                root_indices[index] = self._add(
                    placements,
                    node["kind"],
                    parent,
                    *point,
                    0.0,
                    node["thickness"],
                    node["order"],
                )
        elif root_growth_origin is not None:
            origin = placements[root_growth_origin][2:5]
            for index, node in enumerate(root_nodes):
                if node["order"] > lod:
                    continue
                parent = root_growth_origin if node["parent"] < 0 else root_indices[node["parent"]]
                point = [origin[j] + node["position"][j] for j in range(3)]
                root_indices[index] = self._add(placements, node["kind"], parent, *point,
                                                0.0, node["thickness"], node["order"])
        root_stats["root_visible_segment_count"] = sum(root_nodes[i]["kind"] == "root_section" for i in root_indices)
        root_stats["root_origin_z_m"] = placements[crown][4] if crown is not None else 0.0
        root_stats["root_growth_origin_z_m"] = (
            placements[root_growth_origin][4] if root_growth_origin is not None else 0.0
        )
        renewal_buds = [item for item in placements if item[0] == "renewal_bud"]
        storage = [str(item).lower().replace("-", "_").replace(" ", "_")
                   for item in self.blueprint.growth.get("belowground_storage", [])]
        root_stats.update({
            "plant_life_form": self.blueprint.growth.get("plant_life_form", "other_unknown"),
            "renewal_bud_count": len(renewal_buds),
            "renewal_bud_depth_m": round(
                max(0.0, float(root_stats["root_origin_z_m"]) - min(float(item[4]) for item in renewal_buds)), 4
            ) if renewal_buds else 0.0,
            "renewal_bud_depth_source": "runtime_default" if renewal_buds else "not_applicable",
            "renewal_organ_kind": storage[0] if storage else ("unresolved" if renewal_organ is not None else "none"),
        })

        # Non-tree grammars still expose a uniform cluster interface. Their
        # visible leaves are already sparse enough to remain one calculative
        # unit each; tree grammars above create larger cohorts explicitly.
        if not leaf_clusters:
            leaf_module = self.blueprint.module("leaf")
            leaf_length = max(0.01, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
            leaf_radius = max(0.005, float(getattr(leaf_module, "radius_m", 0.01) or 0.01))
            leaf_area = max(0.0005, leaf_length * leaf_radius * 1.8)
            for index, placement in enumerate(placements):
                if placement[0] != "leaf":
                    continue
                cluster_id = self._add_leaf_cluster(
                    leaf_clusters,
                    index,
                    placement[2],
                    placement[3],
                    placement[4],
                    1,
                    (leaf_length**2 * self.blueprint.growth["emergent_rosette_profile"]["blade_width_ratio"]
                     * .60 * float(placement[6])**2 if self.blueprint.growth.get("emergent_rosette_version") else
                     math.pi * (leaf_length * float(placement[6]) * .5)**2 * .94
                     if self.blueprint.growth.get("aquatic_rosette_version") else
                     self.blueprint.growth["basal_fan_leaf_length_m"]
                     * self.blueprint.growth["basal_fan_profile"]["leaf_width_m"]*.65*float(placement[6])**2
                     if self.blueprint.growth.get("basal_fan_profile") else leaf_area * float(placement[6])),
                    max(0, int(placement[7]) - 2),
                    visual_density=1.0,
                )
                for attachment in attachment_points:
                    if attachment.get("stem_placement_index") == placement[1] and "cluster_id" not in attachment:
                        attachment["cluster_id"] = cluster_id
                        break

        placement_orientations = {
            str(index): self._placement_orientation(placements, index)
            for index in range(len(placements))
        }
        placement_orientations.update(getattr(self, "_placement_orientation_hints", {}) or {})
        points = []
        for index, placement in enumerate(placements):
            points.append((placement[2], placement[3], placement[4]))
            if (self.blueprint.growth.get('renewing_cane_version') or self.blueprint.growth.get('columnar_version') or self.blueprint.growth.get('terminal_rosette_version') or self.blueprint.growth.get('offset_rosette_version')) and placement[0] in {'stem_section','branch_section'}:
                radius=placement[6]
                for p in placement_paths.get(str(index), [placement[2:5]]):
                    points.extend(tuple(p[a]+sign*radius for a in range(3)) for sign in (-1,1))
            # Socket positions are not sufficient bounds for long organs
            # such as succulent blades. Include their oriented model-space
            # extent without creating another simulation object.
            if placement[0] in {"leaf", "flower", "fruit", "strobilus"}:
                module = self.blueprint.module(placement[0])
                if placement_orientations.get(str(index), {}).get('seasonal_planar_blade'):
                    # Full compound blade, including its lateral leaflet spread.
                    radius = module.length_m*placement[6]*1.15
                    points.extend(tuple(placement[2+a]+sign*radius for a in range(3)) for sign in (-1, 1))
                    continue
                if placement[0] == 'strobilus' and module:
                    radius = module.radius_m*placement[6]
                    length = module.length_m*placement[6]
                    for z in (placement[4], placement[4]+length):
                        points.extend((placement[2]+dx*radius, placement[3]+dy*radius, z)
                                      for dx in (-1, 1) for dy in (-1, 1))
                    continue
                if placement_orientations.get(str(index), {}).get('microphyll'):
                    half = placement_orientations[str(index)]['blade_width_m']*.5
                    for point in placement_paths.get(str(index), []):
                        points.extend(tuple(point[a]+sign*half for a in range(3)) for sign in (-1, 1))
                    continue
                if placement_orientations.get(str(index), {}).get('terminal_blade'):
                    half = placement_orientations[str(index)]['blade_width_m']*.5
                    for point in placement_paths.get(str(index), []):
                        points.extend(tuple(point[a]+sign*half for a in range(3)) for sign in (-1, 1))
                    continue
                cluster = self.blueprint.growth.get("inflorescence_profile")
                if (cluster and (cluster.get("head_layout") == "rounded" or cluster.get("form") == "umbellate_head" or self.blueprint.growth.get("basal_subshrub_version"))
                        and (placement[0] == "flower" or (placement[0] == "fruit"
                             and (self.blueprint.growth.get("clonal_forb_reproduction_version")
                                  or self.blueprint.growth.get("umbellate_head_version") or self.blueprint.growth.get("basal_subshrub_version"))))):
                    # Composed billboard heads follow the supporting axis in
                    # each camera. A conservative metric sphere fits that
                    # rotated envelope without assuming a world-space plane.
                    radius = math.hypot(cluster["length_m"], cluster["width_m"]*.5)*placement[6]
                    points.extend(tuple(placement[2+axis]+sign[axis]*radius for axis in range(3))
                                  for sign in ((-1,-1,-1),(1,1,1)))
                from simulations.species.pendant_reproduction import pendant_geometry
                pendant = pendant_geometry(self.blueprint.growth, placement, module)
                if pendant:
                    points.extend(pendant)
                    if (placement[0]=='fruit' and (self.blueprint.growth.get('reproductive_profile') or {}).get('fruit_cluster_display')):
                        from simulations.species.pendant_reproduction import pendant_display_units
                        for unit in pendant_display_units(self.blueprint.growth,placement,module,self.seed):
                            points.extend(unit)
                    if placement[0] == "flower" and self.blueprint.growth.get("inflorescence_profile"):
                        half = self.blueprint.growth["inflorescence_profile"]["width_m"] * max(.55, placement[6]) / 2
                        points.extend((pendant[0][0]+dx*half, pendant[0][1]+dy*half, z)
                                      for dx in (-1, 1) for dy in (-1, 1)
                                      for z in (pendant[0][2], pendant[1][2]))
                    continue
                if placement[0] == "fruit" and self.blueprint.growth.get("persistent_calyx_version"):
                    from simulations.species.persistent_calyces import calyx_extent
                    r = calyx_extent(self.blueprint.growth["reproductive_profile"]["persistent_calyx_display"])*placement[6]*.5
                    points.extend(tuple(placement[2+a]+sign*r for a in range(3)) for sign in (-1,1))
                    continue
                frond_path = placement_paths.get(str(index)) if (
                    placement[0] == "leaf" and ((getattr(module, "visual", {}) or {}).get("leaf_structure") == "frond_like"
                                               or self.blueprint.growth.get("pinnate_crown_version"))
                ) else None
                if frond_path:
                    points.extend(tuple(point) for point in frond_path)
                    continue
                length_m = max(0.0, float(getattr(module, "length_m", 0.0) or 0.0)) if module is not None else 0.0
                orientation = placement_orientations.get(str(index), {})
                if orientation.get("planar_leaf"):
                    if 'width_m' in orientation:
                        from simulations.species.floating_leaves import metric_blade_bounds
                        points.extend(metric_blade_bounds(placement[2:5],orientation,length_m*float(placement[6])))
                        continue
                    from simulations.species.emergent_rosettes import planar_blade_bounds
                    points.extend(planar_blade_bounds(placement[2:5], orientation,
                        length_m * float(placement[6]),
                        self.blueprint.growth["emergent_rosette_profile"]["blade_width_ratio"]))
                    continue
                if orientation.get("floating_leaf"):
                    radius = length_m * float(placement[6]) * .55
                    points.extend((placement[2] + dx * radius, placement[3] + dy * radius, placement[4])
                                  for dx in (-1, 1) for dy in (-1, 1))
                    continue
                forward = orientation.get("forward") or [0.0, 0.0, 0.0]
                extent = length_m * max(0.0, float(placement[6]))
                if len(forward) >= 3 and extent > 0.0:
                    points.append((
                        float(placement[2]) + float(forward[0]) * extent,
                        float(placement[3]) + float(forward[1]) * extent,
                        float(placement[4]) + float(forward[2]) * extent,
                    ))
        for cluster in leaf_clusters:
            organ_bounds = cluster.get("organ_bounds_m")
            if organ_bounds:
                points.extend(((organ_bounds[0], organ_bounds[2], organ_bounds[4]),
                               (organ_bounds[1], organ_bounds[3], organ_bounds[5])))
        for support in vine_stats.get("climbing_supports", []):
            center_x, center_y = support["center_m"]
            radius = max(float(support["radius_m"]), float(support.get("crown_radius_m", 0.0) or 0.0))
            base_z = float(support.get("base_z_m", 0.0) or 0.0)
            top_z = float(support.get("top_z_m", base_z + float(support["height_m"])))
            points.extend((
                (center_x - radius, center_y - radius, base_z),
                (center_x + radius, center_y + radius, top_z),
            ))
        if not vine_stats.get("climbing_supports"):
            for rod in rod_structures:
                x, y, z = rod["position_m"]
                radius = float(rod["radius_m"])
                points.extend(((x - radius, y - radius, z), (x + radius, y + radius, rod["top_z_m"])))
        for structure in solid_field.structures:
            min_x, max_x, min_y, max_y, min_z, max_z = solid_field.bounds_m(structure)
            points.extend(((min_x, min_y, min_z), (max_x, max_y, max_z)))
        if not points:
            points = [(0.0, 0.0, 0.0)]
        bounds = [
            min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points),
            min(point[2] for point in points), max(point[2] for point in points),
        ]
        modules = self._module_table(lod)
        tussock_stats = {}
        if behaviour == "tussock_tillering" and not self.blueprint.growth.get('mixed_tiller_version'):
            count = max(3, int(round(4 + 5*maturity)))
            generations = min(10, max(1, round((float(self.blueprint.growth["max_height_m"])/max(.03, float(self.blueprint.growth["internode_length_m"]))) * maturity)))
            leaf = self.blueprint.module("leaf")
            canonical_leaves = count * min(3, generations) if maturity > 0 else 0
            area = max(.0005, max(.01, leaf.length_m)*max(.005, leaf.radius_m)*1.8)
            stems = [p for p in placements if p[0] == "stem_section"]
            tussock_stats = {"tiller_count": count,
                             "tiller_radius_m": round(max((math.hypot(p[2],p[3]) for p in stems), default=0.), 4),
                             "estimated_leaf_count": canonical_leaves,
                             "leaf_area_m2": round(canonical_leaves*round(area*max(.025, math.sqrt(maturity)),6),6)}
        visible_module_count = len(placements)
        return PlantGrowthSnapshot(
            species_id=self.species_id,
            blueprint_fingerprint=self.blueprint.fingerprint(),
            seed=self.seed,
            age_days=round(age_days, 3),
            lod=lod,
            modules=modules,
            placements=placements,
            bounds_m=[round(value, 4) for value in bounds],
            model_space=dict(self.blueprint.model_space or PLANT_MODEL_SPACE),
            placement_paths=placement_paths,
            placement_orientations=placement_orientations,
            attachment_points=attachment_points,
            stats={
                **root_stats,
                **clonal_stats,
                **graminoid_stats,
                **vine_stats,
                **sympodial_stats,
                **solid_stats,
                "environment": dict(self.environment),
                "maturity": round(maturity, 4),
                "life_history": self.life_history_profile.get("class", "perennial"),
                "life_phase": life_state["phase"],
                "reproductive_factor": life_state["reproductive_factor"],
                "senescence_factor": life_state["senescence_factor"],
                "placement_count": visible_module_count,
                "leaf_count": sum(1 for item in placements if item[0] == "leaf"),
                "leaf_sample_count": sum(1 for item in placements if item[0] == "leaf"),
                "leaf_cluster_count": len(leaf_clusters),
                "estimated_leaf_count": sum(item["estimated_leaf_count"] for item in leaf_clusters),
                "leaf_area_m2": round(sum(item["leaf_area_m2"] for item in leaf_clusters), 6),
                "leaf_fascicle_count": sum(int(item.get("fascicle_count", 0) or 0) for item in leaf_clusters),
                "leaf_fascicle_size": int(self.blueprint.growth.get("fascicle_size", 0) or 0),
                "estimated_fascicled_leaf_count": sum(
                    int(item.get("estimated_leaf_count", 0) or 0)
                    for item in leaf_clusters
                    if item.get("leaf_arrangement") == "fascicled"
                ),
                "stem_count": sum(1 for item in placements if item[0] in {"stem_section", "branch_section"}),
                "branch_count": sum(1 for item in placements if item[0] == "branch_section"),
                "axis_continuity": self.blueprint.growth.get("axis_continuity", "other_unknown"),
                "branching_rhythm": self.blueprint.growth.get("branching_rhythm", "other_unknown"),
                "branching_timing": self.blueprint.growth.get("branching_timing", "other_unknown"),
                "lateral_axis_orientation": self.blueprint.growth.get("lateral_axis_orientation", "other_unknown"),
                "flowering_position": self.blueprint.growth.get("flowering_position", "other_unknown"),
                "apical_control": round(float(self.blueprint.growth.get("apical_control", .72)), 4),
                "structural_axis_length_m": (
                    round(float(structural_axis_length_m), 4) if structural_axis_length_m is not None else None
                ),
                "curved_segment_count": len(placement_paths),
                "model_dimensions": int((self.blueprint.model_space or PLANT_MODEL_SPACE).get("dimensions", 3)),
                "projection": str((self.blueprint.model_space or PLANT_MODEL_SPACE).get("projection", "orthographic")),
                "orientation_count": len(placement_orientations),
                "representation": "module_placements_with_leaf_clusters",
                **tussock_stats,
                **rosette_stats,
                **(sympodial_stats if (self.blueprint.growth.get("basal_fan_profile")
                                      or self.blueprint.growth.get('sympodial_herb_version')
                                      or self.blueprint.growth.get('flower_fork_version')) else {}),
            },
            leaf_clusters=leaf_clusters,
        )

    def get_center(self):
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) * 0.5,
            (self.bounds["min_y"] + self.bounds["max_y"]) * 0.5,
        )

    def get_initial_camera_zoom(self, screen_w, screen_h):
        """Fit one individual prominently in the Species Sim viewport."""
        world_w = max(0.1, self.bounds["max_x"] - self.bounds["min_x"])
        world_h = max(0.1, self.bounds["max_y"] - self.bounds["min_y"])
        usable_w = max(240.0, float(screen_w) - 250.0)
        usable_h = max(260.0, float(screen_h) - 120.0)
        return max(self.min_zoom, min(usable_w / world_w, usable_h / world_h) * 0.88)

    def get_height_reference(self):
        """Return the fixed human comparison figure in projected model space."""

        return {
            "kind": "human_silhouette",
            "height_m": self.HUMAN_REFERENCE_HEIGHT_M,
            "position_m": [round(float(getattr(self, "height_reference_x", 0.0)), 4), 0.0, 0.0],
            "label": "Human 1.75 m",
        }

    def get_title(self):
        return f"Species Sim: {self.blueprint.display_name}"

    def get_scope_label(self):
        return f"{self.blueprint.display_name} | {self.blueprint.growth.get('shape', 'herb')}"

    def get_scope_breadcrumb(self):
        if self.blueprint.growth.get("fungal_grammar_version"):
            return "Species Sim | wood-associated fungus"
        return "Species Sim | modular plant growth"

    def get_simulation_panel_tabs(self):
        if self.blueprint.growth.get("fungal_grammar_version"):
            return [{"id":"individual", "label":"Individual"}, {"id":"top_down", "label":"Top-down"},
                    {"id":"mycelium", "label":"Wood Cutaway"}, {"id":"editor", "label":"Species Editor"},
                    {"id":"gallery", "label":"Growth Stages"}]
        if self.blueprint.growth.get("growth_behaviour") == "surface_covering":
            return [{"id":"individual","label":"Individual"},
                    {"id":"surface","label":"Surface"},
                    {"id":"rock_test","label":"Rock Test"},
                    {"id":"editor","label":"Species Editor"},
                    {"id":"gallery","label":"20 Growth Stages"}]
        return [
            {"id": "individual", "label": "Individual"},
            {"id": "top_down", "label": "Top-down"},
            {"id": "roots", "label": "Roots"},
            {"id": "branches", "label": "Branches"},
            {"id": "architecture", "label": "Tree Patterns"},
            {"id": "editor", "label": "Species Editor"},
            {"id": "gallery", "label": "20 Growth Stages"},
            {"id": "forest", "label": "Forest View"},
            {"id": "compare", "label": "Compare"},
        ]

    def get_active_simulation_panel_tab_id(self):
        return self.diagnostic_view

    def set_active_simulation_panel_tab(self, tab_id):
        valid_ids = {tab["id"] for tab in self.get_simulation_panel_tabs()}
        if tab_id not in valid_ids:
            return False
        if tab_id == "editor":
            self._ensure_species_editor()
        if tab_id == "compare":
            if self.diagnostic_view == "roots":
                self.comparison_subject = "roots"
            self._root_comparison_cases = None
        self.diagnostic_view = tab_id
        return True

    def get_growth_gallery_cases(self):
        if self._diagnostic_cases is None:
            from simulations.species.species_diagnostics import build_growth_gallery

            self._diagnostic_cases = build_growth_gallery(
                self.species_entity,
                species_id=self.species_id,
                asset_store=self.asset_store,
                lod=self.lod,
            )
        return list(self._diagnostic_cases)

    def get_rock_test_cases(self):
        from simulations.species.surface_supports import ROCK_TEST_ASSET, rock_fixture, rock_lifecycle_treatments
        if self.blueprint.growth.get("growth_behaviour") != "surface_covering":
            return []
        key=(self.blueprint.fingerprint(),self.seed,self.lod,asset_files.revision(ROCK_TEST_ASSET))
        cached=getattr(self,"_rock_test_cases",None)
        if cached is None or cached[0] != key:
            cases=[]
            for label,environment in rock_lifecycle_treatments(rock_fixture(),self.blueprint.growth.get("surface_growth_profile")):
                case=SpeciesSimulation(species_id=self.species_id,blueprint=self.blueprint,
                                       asset_store=self.asset_store,seed=self.seed,environment=environment)
                case.set_lod(self.lod);case.set_age(case.mature_age_days)
                cases.append((label,case))
            self._rock_test_cases=(key,cases)
        return list(self._rock_test_cases[1])

    def get_growth_summary(self):
        return dict(self.render_snapshot.stats)

    def get_detailed_snapshot(self):
        """Full per-leaf snapshot for close-up diagnostics.

        The default ``render_snapshot`` represents foliage as calculative
        leaf_clusters so a mature crown stays cheap to simulate and render.
        Close-up views (the Branches diagnostic tab, paired species/shoot
        comparison renders) need authentic per-leaf geometry instead; this
        regenerates it on demand, from the same deterministic generator, and
        caches the result until age/lod/blueprint actually change.
        """
        key = (self.blueprint.fingerprint(), self.seed, round(self.age_days, 3), self.lod)
        if (self.blueprint.growth.get("growth_behaviour") == "surface_covering"
                or self.blueprint.growth.get("fungal_grammar_version")):
            key += (json.dumps(self.environment,sort_keys=True,default=str),)
        cached = getattr(self, "_detailed_snapshot_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        snapshot = self.generate_snapshot(self.age_days, self.lod, detail=True)
        self._detailed_snapshot_cache = (key, snapshot)
        return snapshot

    def get_ecological_outcome(self, environment=None):
        """Return the compact handoff a future BioSim cohort can aggregate.

        The current implementation is intentionally a structural prototype;
        detailed physiology and species interactions will consume the supplied
        environment in the later BioSim pass.
        """
        if self.blueprint.growth.get("fungal_grammar_version"):
            from simulations.species.fungal_growth import fungal_ecological_outcome
            return fungal_ecological_outcome(self, environment)
        if self.blueprint.growth.get('moss_turf_version'):
            from simulations.species.moss_turfs import moss_ecological_outcome
            return moss_ecological_outcome(self, environment)
        if self.blueprint.growth.get("growth_behaviour") == "surface_covering":
            from simulations.species.surface_growth import surface_ecological_outcome
            surface_environment = environment if isinstance(environment, dict) else self.environment
            return {"species_id": self.species_id, "age_days": self.render_snapshot.age_days,
                    **surface_ecological_outcome(self.blueprint.growth, self.render_snapshot.stats, surface_environment)}
        environment = environment if isinstance(environment, dict) else {}

        def clamp(value):
            return max(0.0, min(1.0, float(value)))

        disturbance = clamp(environment.get("disturbance", 0.0))
        resprouting = self.blueprint.growth.get("resprouting", "other_unknown")
        disturbance_factor = {"absent": 1., "weak": .8, "moderate": .55, "strong": .3}.get(resprouting, 1.)
        from simulations.species.plant_nutrition import resolve_plant_nutrient_response

        nutrient = resolve_plant_nutrient_response(
            self.blueprint.growth,
            environment,
            self.render_snapshot.stats,
        )
        from simulations.species.plant_reproduction import resolve_reproductive_assurance
        reproduction = resolve_reproductive_assurance(self.blueprint.growth, environment)
        stress_values = [
            clamp(environment.get("temperature_stress", 0.0)),
            clamp(environment.get("water_stress", 0.0)),
            clamp(environment.get("light_stress", 0.0)),
            clamp(nutrient["nitrogen_stress"]),
            clamp(nutrient["phosphorus_stress"]),
            disturbance * disturbance_factor,
            clamp(environment.get("competition", 0.0)),
            clamp(environment.get("disease_pressure", 0.0)),
        ]
        stress = sum(stress_values) / len(stress_values)
        maturity = float(self.render_snapshot.stats.get("maturity", 0.0) or 0.0)
        life_state = self.life_state(self.render_snapshot.age_days)
        growth_bias = clamp(self.blueprint.growth.get("growth_rate_bias", 0.55))
        seasonal_turnover = (
            self.life_history_profile.get("class") == "perennial"
            and "leaf_factor" in life_state
        )
        # An authored leafless season lowers activity, not perennial health.
        # Keep the same growth response without treating routine dormancy as
        # mortality or losing the standing wood when foliage is shed.
        health_factor = 1.0 if seasonal_turnover else life_state["active_factor"]
        vitality = clamp(
            maturity
            * (0.55 + growth_bias * 0.45)
            * health_factor
            * (1.0 - stress * 0.78)
        )
        leaf_count = int(self.render_snapshot.stats.get("estimated_leaf_count", 0) or 0)
        leaf_area = float(self.render_snapshot.stats.get("leaf_area_m2", 0.0) or 0.0)
        photosynthetic_area = float(self.render_snapshot.stats.get('photosynthetic_area_m2', leaf_area))
        stem_count = int(self.render_snapshot.stats.get("stem_count", 0) or 0)
        # stem_count is a placement count, which for shoot-grammar trees
        # varies with incidental render subdivision (how many segments a
        # shoot's spine happens to be split into), not real structure.
        # structural_axis_length_m sums only the architectural axes (trunk /
        # primary / secondary / twig), so it stays stable regardless of
        # render detail; fall back to stem_count for species that don't
        # report it.
        structural_axis_length_m = self.render_snapshot.stats.get("structural_axis_length_m")
        stem_structural_term = float(structural_axis_length_m) if structural_axis_length_m else float(stem_count)
        return {
            "species_id": self.species_id,
            "age_days": self.render_snapshot.age_days,
            "maturity": round(maturity, 4),
            "vitality": round(vitality, 4),
            "growth_rate": round(vitality * growth_bias * (life_state["active_factor"] if seasonal_turnover else 1.0), 4),
            "fecundity": round(
                vitality
                * life_state["reproductive_factor"]
                * reproduction["reproductive_assurance"],
                4,
            ),
            "mortality_risk": round(1.0 if life_state["phase"] == "dead" else clamp(1.0 - vitality), 4),
            "resource_demand": round((leaf_count * 0.012) + (stem_structural_term * 0.02), 4),
            "leaf_area_proxy": round(leaf_area * vitality, 4),
            **({'photosynthetic_area_proxy':round(photosynthetic_area*vitality,4),
                'photosynthetic_stem_area_m2':photosynthetic_area,
                'photosynthetic_source':'green_stem_surface',
                'stem_storage_volume_m3':self.render_snapshot.stats.get('stem_storage_volume_m3',0.)}
               if self.blueprint.growth.get('columnar_version') else {}),
            "estimated_leaf_count": leaf_count,
            "leaf_cluster_count": int(self.render_snapshot.stats.get("leaf_cluster_count", 0) or 0),
            "structural_biomass_proxy": round(stem_structural_term * 0.08 * vitality, 4),
            "root_depth_m": self.render_snapshot.stats.get("root_depth_m", 0.0),
            "root_spread_m": self.render_snapshot.stats.get("root_spread_m", 0.0),
            "root_length_m": self.render_snapshot.stats.get("root_length_m", 0.0),
            "root_depth_source": self.render_snapshot.stats.get("root_depth_source", "runtime_default"),
            "root_model_status": self.render_snapshot.stats.get("root_model_status", "unresolved"),
            "root_distribution": self.render_snapshot.stats.get("root_distribution", "central_crown"),
            "root_cluster_count": int(self.render_snapshot.stats.get("root_cluster_count", 0) or 0),
            "root_cluster_spread_m": self.render_snapshot.stats.get("root_cluster_spread_m", 0.0),
            "root_system_span_m": self.render_snapshot.stats.get(
                "root_system_span_m",
                self.render_snapshot.stats.get("root_spread_m", 0.0),
            ),
            "disturbance_input": disturbance,
            "disturbance_penalty": round(disturbance * disturbance_factor, 4),
            "resprouting": resprouting,
            **reproduction,
            **nutrient,
            "disturbance_response_status": "qualitative_runtime_default",
            "stress_index": round(stress, 4),
            "life_history": life_state,
            "detail_scope": "structural_and_repeated_organs",
            "aggregation_scope": "representative_organism_to_population",
            "status": "prototype_derived",
        }

    def get_scene_reference(self, snapshot=None, store=None, **kwargs):
        store = store or self.asset_store
        return store.make_scene_reference(self.blueprint, snapshot or self.render_snapshot, **kwargs)

    def bake_snapshot(self, store=None):
        """Persist the reusable recipe and current result, returning a scene ref."""
        store = store or self.asset_store
        store.save_blueprint(self.blueprint)
        store.save_snapshot(self.render_snapshot)
        return self.get_scene_reference(store=store)
