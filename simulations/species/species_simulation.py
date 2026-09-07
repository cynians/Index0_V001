"""Standalone species-level plant growth simulation.

This simulation owns individual module placements. Map and scenery modes only
consume a reference to a blueprint/snapshot, so they never simulate leaves.
"""

from __future__ import annotations

import math
import random
from simulations.species.root_growth import root_profile, build_root_graph
from typing import Any

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
        self.forest_spacing = "medium"
        self.forest_tolerance = None
        self.forest_view_style = "isometric"
        self._forest_cache = None
        self.diagnostic_view = "individual"
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
        elif phase == "senescent":
            if age_limit is None:
                decline_window = max(365.0, float(profile.get("cycle_days", 365.0)))
                senescence_factor = min(1.0, (age_days - senescence_start) / decline_window)
            else:
                decline_window = max(1.0, float(age_limit) - senescence_start)
                senescence_factor = min(1.0, (age_days - senescence_start) / decline_window)
            reproductive_factor = max(0.0, 1.0 - senescence_factor)
        else:
            reproductive_factor = 0.0
            senescence_factor = 0.0
        return {
            "phase": phase,
            "reproductive_factor": round(reproductive_factor, 4),
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
        if lod >= 1 or self.blueprint.growth.get("shoot_distribution_grammar"):
            module_ids.add("branch_section")
        if lod >= 1:
            module_ids.update({"leaf", "flower", "fruit"})
        modules = {
            module.id: module.to_dict()
            for module in self.blueprint.modules
            if module.id in module_ids
        }
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
    def _add_leaf_cluster(leaf_clusters, host_placement, x, y, z, estimated_count, leaf_area_m2, branch_order, visual_density=1.0):
        """Record a calculative leaf cohort without expanding every leaf."""

        if leaf_clusters is None:
            return None
        cluster_id = f"leaf_cluster_{len(leaf_clusters) + 1:04d}"
        leaf_clusters.append({
            "id": cluster_id,
            "host_placement_index": int(host_placement),
            "position_m": [round(float(x), 4), round(float(y), 4), round(float(z), 4)],
            "estimated_leaf_count": max(1, int(round(estimated_count))),
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

    def _grow_rosette(self, placements, maturity, lod):
        root = self._growth_origin(placements)
        count = max(3, int(round(5 + maturity * 7)))
        if lod == 0:
            count = min(count, 3)
        for index in range(count):
            angle = index * 360.0 / count + 137.5 * maturity
            radius = 0.06 + 0.20 * maturity
            self._add(
                placements,
                "leaf" if lod >= 1 else "stem_section",
                root,
                math.cos(math.radians(angle)) * radius,
                math.sin(math.radians(angle)) * radius,
                0.08 + 0.12 * maturity,
                angle,
                0.65 + 0.35 * maturity,
                1,
            )
        return

    def _grow_fern(self, placements, maturity, lod, attachment_points=None):
        """Grow several arching fronds with leaflets distributed on each rachis."""

        growth = self.blueprint.growth
        max_height = max(0.18, float(growth.get("max_height_m", 1.25) or 1.25))
        frond_count = max(3, int(round(4 + maturity * 5)))
        if lod == 0:
            frond_count = min(frond_count, 3)
        segments = min(10, max(3, int(round(4 + maturity * 6))))
        root = self._growth_origin(placements)
        for frond_index in range(frond_count):
            angle = frond_index * 360.0 / frond_count + 17.0
            radians = math.radians(angle)
            parent = root
            for segment in range(segments):
                fraction = (segment + 1) / segments
                radius = 0.05 + 0.32 * maturity * fraction
                arch = math.sin(math.pi * fraction)
                x = math.cos(radians) * radius
                y = math.sin(radians) * radius
                z = 0.06 + max_height * maturity * (0.28 + 0.62 * arch)
                rachis = self._add(
                    placements,
                    "stem_section",
                    parent,
                    x,
                    y,
                    z,
                    angle,
                    0.58 + 0.42 * maturity,
                    1,
                )
                if lod >= 1 and segment > 0:
                    side = -1.0 if (segment + frond_index) % 2 == 0 else 1.0
                    leaflet_angle = angle + side * (54.0 + 10.0 * fraction)
                    leaflet_radius = 0.045 + 0.02 * maturity
                    leaf_x = x + math.cos(math.radians(leaflet_angle)) * leaflet_radius
                    leaf_y = y + math.sin(math.radians(leaflet_angle)) * leaflet_radius
                    leaf_z = z + 0.012
                    if attachment_points is not None:
                        attachment_points.append({
                            "stem_placement_index": rachis,
                            "socket": "leaf",
                            "position_m": [round(leaf_x, 4), round(leaf_y, 4), round(leaf_z, 4)],
                            "side": "left" if side < 0 else "right",
                            "rotation_deg": round(leaflet_angle % 360.0, 3),
                        })
                    self._add(
                        placements,
                        "leaf",
                        rachis,
                        leaf_x,
                        leaf_y,
                        leaf_z,
                        leaflet_angle,
                        0.48 + 0.42 * maturity,
                        2,
                    )
                parent = rachis

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
        if lod == 0:
            count = min(count, 3)
        radius = 0.08 + 0.46 * maturity
        for index in range(count):
            angle = index * 360.0 / count + 18.0
            radians = math.radians(angle)
            x = math.cos(radians) * radius
            y = math.sin(radians) * radius
            target_x, target_y, target_z = x * 0.62, y * 0.62, -0.015
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
            if lod >= 1:
                if attachment_points is not None:
                    attachment_points.append({
                        "stem_placement_index": petiole,
                        "socket": "leaf",
                        "position_m": [round(x, 4), round(y, 4), 0.0],
                        "side": "surface",
                        "rotation_deg": round(angle, 3),
                    })
                self._add(
                    placements,
                    "leaf",
                    petiole,
                    x,
                    y,
                    0.0,
                    angle,
                    0.65 + 0.35 * maturity,
                    2,
                )

        # Flowers occupy alternating positions in the rhizome's spiral. A
        # mature cycle can carry two visible blooms, rather than forcing one
        # flower into the centre of an otherwise generic rosette.
        if lod >= 2 and flowering_factor > 0.0:
            flower_count = 2 if maturity >= 0.75 else 1
            for flower_index in range(flower_count):
                flower_angle = 112.0 + flower_index * 48.0
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
                        flower_x * 0.55 * fraction + perpendicular[0] * bend,
                        flower_y * 0.55 * fraction + perpendicular[1] * bend,
                        -0.22 + (target_z + 0.22) * fraction + 0.04 * math.sin(math.pi * fraction),
                    ))
                peduncle = self._add(
                    placements,
                    "stem_section",
                    root,
                    flower_x * 0.55,
                    flower_y * 0.55,
                    target_z,
                    flower_angle,
                    0.7 + 0.3 * maturity,
                    1,
                    placement_paths=placement_paths,
                    path=peduncle_path,
                )
                self._add(
                    placements,
                    "flower",
                    peduncle,
                    flower_x,
                    flower_y,
                    0.06,
                    0.0,
                    0.7 + 0.3 * flowering_factor,
                    2,
                )

    def _grow_sympodial(self, placements, maturity, lod, rng):
        """Grow a determinate axis whose continuation shifts laterally."""

        growth = self.blueprint.growth
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        generations = min(14, max(1, int(round((max_height / internode) * maturity))))
        leaves_per_node = 0 if lod == 0 else max(1, int(growth.get("leaves_per_node", 1) or 1))
        branch_angle = float(growth.get("branch_angle_deg", 28.0) or 28.0)
        phyllotaxis = float(growth.get("phyllotaxis_deg", 137.5) or 137.5)

        root = self._growth_origin(placements)
        parent, x, y = root, 0.0, 0.0
        for generation in range(generations):
            fraction = (generation + 1) / max(1, generations)
            z = min(max_height * maturity, internode * (generation + 1))
            continuation_angle = phyllotaxis * generation + (branch_angle if generation % 2 else -branch_angle)
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
            x += math.cos(math.radians(continuation_angle)) * 0.045
            y += math.sin(math.radians(continuation_angle)) * 0.045
            parent = stem

    def _grow_creeping(self, placements, maturity, lod, rng):
        """Grow a low horizontal axis with leaves at contact/internode nodes."""

        growth = self.blueprint.growth
        length = max(0.3, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.04, float(growth.get("internode_length_m", 0.2) or 0.2))
        nodes = min(18, max(2, int(round((length / internode) * maturity))))
        leaves_per_node = 0 if lod == 0 else 1
        root = self._growth_origin(placements)
        parent, x, y = root, 0.0, 0.0
        for index in range(nodes):
            angle = 12.0 * math.sin(index * 0.8)
            stem = self._add(placements, "stem_section", parent, x, y, 0.06, angle, 0.65 + 0.35 * maturity, 1)
            if leaves_per_node:
                for side in (-1.0, 1.0):
                    leaf_angle = angle + side * 90.0
                    self._add(placements, "leaf", stem, x, y + side * 0.07, 0.09, leaf_angle, 0.55 + 0.45 * maturity, 2)
            x += internode * 0.9 * maturity
            y += math.sin(math.radians(angle)) * 0.08
            parent = stem

    def _grow_tussock(self, placements, maturity, lod, rng, flowering_factor=0.0, attachment_points=None):
        """Independent basal tillers; spread controls footprint, not shoot count.

        Radius/drift factors are bounded qualitative defaults, not measured rates.
        Unknown spread preserves the historical low-spread geometry.
        """
        growth = self.blueprint.growth
        max_height = max(0.1, float(growth.get("max_height_m", 1.0) or 1.0))
        internode = max(0.03, float(growth.get("internode_length_m", 0.2) or 0.2))
        generations = min(10, max(1, int(round((max_height / internode) * maturity))))
        shoot_count = max(3, int(round(4 + 5 * maturity)))
        spread = {"none": .12, "low": 1., "moderate": 1.6, "high": 2.4}.get(growth.get("clonal_spread"), 1.)
        drift = 0. if growth.get("clonal_spread") == "none" else .01 * spread
        root = self._growth_origin(placements)
        size_factor = max(.025, math.sqrt(maturity))
        phase = rng.uniform(0., math.tau)
        for shoot in range(shoot_count):
            angle = phase + shoot * math.tau / shoot_count + rng.uniform(-.12, .12)
            height_factor = rng.uniform(.74, 1.)
            x, y = math.cos(angle)*.04*spread*size_factor, math.sin(angle)*.04*spread*size_factor
            parent = root
            for generation in range(generations):
                z = max_height * maturity * height_factor * (generation+1)/generations
                stem = self._add(placements, "stem_section", parent, x, y, z, 0., .65+.35*maturity, 1)
                # Keep upper flowering culms relatively bare; leaves emerge at nodes.
                if lod >= 1 and maturity > 0 and generation < min(3, generations):
                    leaf_angle = (300. if math.cos(angle) < 0 else 60.) + (generation%2)*12.
                    leaf = self._add(placements, "leaf", stem, x, y, z, leaf_angle, size_factor, 2)
                    if attachment_points is not None:
                        attachment_points.append({"stem_placement_index": stem, "leaf_placement_index": leaf,
                                                  "socket": "leaf", "position_m": [round(x,4), round(y,4), round(z,4)]})
                if generation == generations-1 and lod >= 1 and flowering_factor > 0.:
                    # The painted spike is an organ attached exactly at the culm tip.
                    self._add(placements, "flower", stem, x, y, z, 0., .65+.35*flowering_factor, 3)
                parent = stem
                x += math.cos(angle)*drift*size_factor
                y += math.sin(angle)*drift*size_factor

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

    def _grow_tree(self, placements, maturity, lod, flowering_factor=0.0, attachment_points=None, placement_paths=None, leaf_clusters=None, rng=None, detail=False):
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
            return grow_tree_shoots(self, placements, maturity, lod, leaf_clusters, attachment_points, placement_paths, flowering_factor, detail=detail)
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


    def _grow_clonal(self, placements, maturity, lod, rng):
        """Grow a parent plant plus repeated ramets connected by clone axes."""

        growth = self.blueprint.growth
        behaviour = str(growth.get("growth_behaviour") or "")
        ramet_count = max(2, int(round(2 + 5 * maturity)))
        if lod == 0:
            ramet_count = min(ramet_count, 2)
        root = self._growth_origin(placements)
        for index in range(ramet_count):
            angle = index * 360.0 / ramet_count
            radius = 0.12 + 0.34 * maturity
            x = math.cos(math.radians(angle)) * radius
            y = math.sin(math.radians(angle)) * radius
            connector_z = -0.05 if behaviour == "rhizomatous_clonal" else 0.08
            connector = self._add(placements, "branch_section", root, x * 0.55, y * 0.55, connector_z, angle, 0.7, 1)
            ramet = self._add(placements, "stem_section", connector, x, y, 0.16 + 0.25 * maturity, angle, 0.65 + 0.35 * maturity, 2)
            if lod >= 1:
                self._add(placements, "leaf", ramet, x, y, 0.24 + 0.2 * maturity, angle + 90.0, 0.55 + 0.45 * maturity, 3)

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
        maturity = self._maturity(age_days)
        life_state = self.life_state(age_days)
        rng = random.Random(self.seed)
        placements = []
        self._placement_orientation_hints = {}
        attachment_points = []
        leaf_clusters = []
        placement_paths = {}
        structural_axis_length_m = None
        shape = str(self.blueprint.growth.get("shape") or "herb")
        behaviour = str(self.blueprint.growth.get("growth_behaviour") or "iterative_indeterminate")
        if shape == "aquatic":
            self._grow_aquatic_rosette(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
                placement_paths=placement_paths,
            )
        elif behaviour == "rosette_short_internode" or shape == "rosette":
            self._grow_rosette(placements, maturity, lod)
        elif behaviour == "unbranched_single_axis":
            self._grow_single_axis(
                placements,
                maturity,
                lod,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
            )
        elif behaviour == "fern_fronding" or shape == "fern":
            self._grow_fern(
                placements,
                maturity,
                lod,
                attachment_points=attachment_points,
            )
        elif behaviour == "basal_succulent_rosette" or shape == "succulent":
            self._grow_succulent(
                placements,
                maturity,
                lod,
                attachment_points=attachment_points,
            )
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
                attachment_points=attachment_points,
                placement_paths=placement_paths,
                leaf_clusters=leaf_clusters,
                rng=rng,
                detail=detail,
            )
            if isinstance(growth_result, dict):
                structural_axis_length_m = growth_result.get("structural_axis_length_m")
        elif behaviour == "determinate_sympodial":
            self._grow_sympodial(placements, maturity, lod, rng)
        elif behaviour == "creeping_prostrate":
            self._grow_creeping(placements, maturity, lod, rng)
        elif behaviour == "tussock_tillering":
            self._grow_tussock(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                attachment_points=attachment_points,
            )
        elif behaviour in {"rhizomatous_clonal", "stoloniferous_clonal", "suckering_clonal"}:
            self._grow_clonal(placements, maturity, lod, rng)
        else:
            self._grow_branching(
                placements,
                maturity,
                lod,
                rng,
                flowering_factor=life_state["reproductive_factor"],
                placement_paths=placement_paths,
            )

        profile = self.blueprint.growth.get("root_profile") or root_profile(self.blueprint.growth)
        root_nodes, root_stats = build_root_graph(profile, maturity, self.seed)
        crown = next((i for i, p in enumerate(placements) if p[0] == "root" and p[1] < 0), None)
        renewal_organ = next((i for i, p in enumerate(placements) if p[0] == "renewal_organ"), None)
        root_growth_origin = renewal_organ if renewal_organ is not None else crown
        root_indices = {}
        if root_growth_origin is not None:
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
                    leaf_area * float(placement[6]),
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
            # Socket positions are not sufficient bounds for long organs
            # such as succulent blades. Include their oriented model-space
            # extent without creating another simulation object.
            if placement[0] in {"leaf", "flower", "fruit"}:
                module = self.blueprint.module(placement[0])
                length_m = max(0.0, float(getattr(module, "length_m", 0.0) or 0.0)) if module is not None else 0.0
                orientation = placement_orientations.get(str(index), {})
                forward = orientation.get("forward") or [0.0, 0.0, 0.0]
                extent = length_m * max(0.0, float(placement[6]))
                if len(forward) >= 3 and extent > 0.0:
                    points.append((
                        float(placement[2]) + float(forward[0]) * extent,
                        float(placement[3]) + float(forward[1]) * extent,
                        float(placement[4]) + float(forward[2]) * extent,
                    ))
        if not points:
            points = [(0.0, 0.0, 0.0)]
        bounds = [
            min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points),
            min(point[2] for point in points), max(point[2] for point in points),
        ]
        modules = self._module_table(lod)
        tussock_stats = {}
        if behaviour == "tussock_tillering":
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
        return "Species Sim | modular plant growth"

    def get_simulation_panel_tabs(self):
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
        environment = environment if isinstance(environment, dict) else {}

        def clamp(value):
            return max(0.0, min(1.0, float(value)))

        disturbance = clamp(environment.get("disturbance", 0.0))
        resprouting = self.blueprint.growth.get("resprouting", "other_unknown")
        disturbance_factor = {"absent": 1., "weak": .8, "moderate": .55, "strong": .3}.get(resprouting, 1.)
        stress_values = [
            clamp(environment.get("temperature_stress", 0.0)),
            clamp(environment.get("water_stress", 0.0)),
            clamp(environment.get("light_stress", 0.0)),
            disturbance * disturbance_factor,
            clamp(environment.get("competition", 0.0)),
            clamp(environment.get("disease_pressure", 0.0)),
        ]
        stress = sum(stress_values) / len(stress_values)
        maturity = float(self.render_snapshot.stats.get("maturity", 0.0) or 0.0)
        life_state = self.life_state(self.render_snapshot.age_days)
        growth_bias = clamp(self.blueprint.growth.get("growth_rate_bias", 0.55))
        vitality = clamp(
            maturity
            * (0.55 + growth_bias * 0.45)
            * life_state["active_factor"]
            * (1.0 - stress * 0.78)
        )
        leaf_count = int(self.render_snapshot.stats.get("estimated_leaf_count", 0) or 0)
        leaf_area = float(self.render_snapshot.stats.get("leaf_area_m2", 0.0) or 0.0)
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
            "growth_rate": round(vitality * growth_bias, 4),
            "fecundity": round(vitality * life_state["reproductive_factor"], 4),
            "mortality_risk": round(1.0 if life_state["phase"] == "dead" else clamp(1.0 - vitality), 4),
            "resource_demand": round((leaf_count * 0.012) + (stem_structural_term * 0.02), 4),
            "leaf_area_proxy": round(leaf_area * vitality, 4),
            "estimated_leaf_count": leaf_count,
            "leaf_cluster_count": int(self.render_snapshot.stats.get("leaf_cluster_count", 0) or 0),
            "structural_biomass_proxy": round(stem_structural_term * 0.08 * vitality, 4),
            "root_depth_m": self.render_snapshot.stats.get("root_depth_m", 0.0),
            "root_spread_m": self.render_snapshot.stats.get("root_spread_m", 0.0),
            "root_length_m": self.render_snapshot.stats.get("root_length_m", 0.0),
            "root_depth_source": self.render_snapshot.stats.get("root_depth_source", "runtime_default"),
            "root_model_status": self.render_snapshot.stats.get("root_model_status", "unresolved"),
            "disturbance_input": disturbance,
            "disturbance_penalty": round(disturbance * disturbance_factor, 4),
            "resprouting": resprouting,
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
