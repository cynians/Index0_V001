"""Headless driver for the production world-generation route.

This module does not reimplement planet generation.  It creates an isolated
WorldModel, instantiates the real WorldGenSimulation, invokes the same stage
actions used by the UI, and renders with the real WorldGenRenderer onto
off-screen Pygame surfaces.

Architecture invariants: ontology data is the only durable entity/semantic
authority and runtime mappings are caches. Generated planets are disposable at
this development stage; old worldgen products need not remain compatible.
"""

import json
import hashlib
import math
import os
import random
import re
import secrets
import copy
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pygame

from engine.camera import Camera
from simulations.world_gen.crust import TRACE_RESERVE_PERCENT, element_name
from simulations.world_gen.generation_contract import (
    contract_fingerprint,
    validate_generation_input_contract,
)
from simulations.world_gen.heightmap import _clamp
from simulations.world_gen.material_heatmaps import load_raster_bundle_surface
from simulations.world_gen.regional_refinement import map_physical_dimensions_m
from simulations.world_gen.world_gen_renderer import WorldGenRenderer
from simulations.world_gen.world_gen_sim import WorldGenSimulation
from simulations.world_gen.worldgen_diagnostics import derive_causal_feature_diagnostics
from world.world_model import WorldModel


@dataclass
class HeadlessWorldGenConfig:
    name: str = "Headless Player Default"
    template_id: str = "silicate_terrestrial"
    map_seed: str = "auto"
    periapsis_au: float = 1.0
    apoapsis_au: float = 1.0
    radius_earth: float = 1.0
    core_radius_fraction: float = 0.55
    crust_thickness_km: float = 35.0
    angular_velocity_deg_per_hour: float = 15.0
    water_fraction: float = 0.5
    volatile_inventory: str = "earthlike"
    tectonics_mode: str = "unknown"
    screen_size: tuple = (1600, 900)
    layer_size: tuple = (640, 320)
    finish_worldgen: bool = False
    randomize_mode: str = ""
    randomizer_seed: int = None
    regional_refinement_depth: int = 0
    regional_center_x: float = 0.5
    regional_center_y: float = 0.5
    regional_target_mode: str = "manual"
    # Optional physical footprint for the first refinement.  The ordinary
    # runner keeps its historical fractional crop when these are zero; the
    # representative-world scenario can additionally provide an explicit
    # per-LOD footprint schedule.
    regional_width_km: float = 0.0
    regional_height_km: float = 0.0
    regional_center_seed: int = None
    regional_center_latitude: float = None
    regional_center_longitude: float = None
    # Optional per-level physical footprints.  This lets the representative
    # fixture exercise the documented 500-2000 km LOD1 macroregion followed by
    # a 100 km LOD2 region, while ordinary callers retain fractional zoom.
    regional_footprint_schedule_km: tuple = None
    force_plate_tectonics: bool = False
    earthlike_constraints: bool = False
    render_outputs: bool = True
    trace_elements: list = field(default_factory=list)
    replay_contract_path: str = ""
    replay_contract: dict = None
    attach_moon: bool = False
    moon_semi_major_axis_km: float = 384_400.0
    moon_radius_earth: float = 0.27
    # Optional scientific-grid and feedback budgets for representative runs.
    # These are normal world-generation parameters: the production stage
    # actions and models remain unchanged, while a bounded scenario can use a
    # coarser canonical support and fewer climate/landscape feedback passes.
    scientific_sample_dimensions: tuple = None
    regional_sample_dimensions: tuple = None
    worldgen_feedback_iterations: int = 2


@dataclass
class HeadlessWorldGenResult:
    output_root: str
    repository_root: str
    planet_id: str
    stage_history: list
    stage_screenshots: list
    layer_images: list
    contact_sheet: str
    summary_path: str
    planet_path: str
    runtime_classes: dict
    regional_refinement_ids: list
    regional_refinement_manifest: list
    regional_materials_path: str
    regional_region_path: str
    regional_layer_images: list
    regional_contact_sheet: str
    regional_level_diagnostics: list
    regional_lod_overview: str
    regional_level_snapshot_paths: list
    input_contract_path: str


@dataclass
class IsolatedHeadlessWorldGenResult:
    retention: str
    planet_id: str
    summary: dict
    stage_fingerprints: list
    bundle_path: str = ""


PRODUCTION_WORLDGEN_STAGE_ACTIONS = (
    "_save_selected_planet_seed",
    "_save_atmosphere_model",
    "_save_interior_regime_model",
    "_save_terrain_seed_model",
    "_handle_heightmap_primary_action",
)


def verify_production_pipeline(
    simulation,
    action_sequence,
    *,
    tectonic_pass_used=False,
    gas_giant_terminal=False,
    regional_selection_diagnostics=None,
):
    """Return evidence that headless generation used production stage methods.

    The representative scenario is intentionally an isolated execution, but
    isolation must not mean a second generator.  This check records both the
    actual action sequence and the bound method modules so a future test
    runner cannot quietly replace a production action with a fixture helper.
    """
    expected = list(PRODUCTION_WORLDGEN_STAGE_ACTIONS[:2]) if gas_giant_terminal else [
        *PRODUCTION_WORLDGEN_STAGE_ACTIONS[:4],
        *([PRODUCTION_WORLDGEN_STAGE_ACTIONS[4]] if tectonic_pass_used else []),
        PRODUCTION_WORLDGEN_STAGE_ACTIONS[4],
    ]
    actual = [str(name) for name in action_sequence]
    bindings = {}
    bound_methods_verified = True
    for name in dict.fromkeys(expected):
        method = getattr(simulation, name, None)
        function = getattr(method, "__func__", method)
        bound_to_simulation = getattr(method, "__self__", None) is simulation
        module = getattr(function, "__module__", None)
        bindings[name] = {
            "bound_to_simulation": bound_to_simulation,
            "module": module,
            "qualname": getattr(function, "__qualname__", None),
        }
        bound_methods_verified = bound_methods_verified and (
            bound_to_simulation
            and module == "simulations.world_gen.world_gen_sim"
        )

    diagnostics = regional_selection_diagnostics or []
    regional_route_verified = all(
        item.get("route") == "MapSimulation.regenerate_visible_region"
        for item in diagnostics
    )
    return {
        "verified": bool(
            simulation.__class__ is WorldGenSimulation
            and actual == expected
            and bound_methods_verified
            and regional_route_verified
        ),
        "simulation_class": f"{simulation.__class__.__module__}.{simulation.__class__.__name__}",
        "stage_action_sequence": actual,
        "expected_stage_action_sequence": expected,
        "stage_action_bindings": bindings,
        "regional_route": (
            "MapSimulation.regenerate_visible_region"
            if diagnostics
            else None
        ),
        "regional_route_verified": regional_route_verified,
        "isolation_scope": "isolated_world_model_and_run_local_storage",
        "generator_scope": "production_worldgen_simulation_and_stage_handlers",
    }


class HeadlessWorldGenRunner:
    SYSTEM_ID = "system_headless_test"
    STAR_ID = "star_headless_test"

    def __init__(self, output_root):
        self.output_root = Path(output_root).resolve()
        self.repository_root = self.output_root / "repository"
        self.entries_root = self.repository_root / "entries"
        self.images_root = self.output_root / "images"
        self.stages_root = self.images_root / "stages"
        self.layers_root = self.images_root / "layers"
        self._renderer = None
        self._app_view = None
        self.system_id = self.SYSTEM_ID
        self.star_id = self.STAR_ID
        self._replay_contract = None

    @staticmethod
    def _slug(value):
        text = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "planet")).strip("_").lower()
        return text or "planet"

    @staticmethod
    def _mountain_center_fraction(entity):
        """Locate a high-relief land window using the saved heightfield."""
        heightmap = entity.get("heightmap_model") if isinstance(entity, dict) else {}
        rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
        if len(rows) < 5 or not isinstance(rows[0], list):
            return 0.5, 0.5
        height = len(rows)
        width = min(len(row) for row in rows if isinstance(row, list))
        sea = heightmap.get("sea_level_m")
        minimum = float(heightmap.get("min_elevation_m", min(min(row[:width]) for row in rows)) or 0.0)
        maximum = float(heightmap.get("max_elevation_m", max(max(row[:width]) for row in rows)) or 0.0)
        land_floor = float(sea) if sea is not None else minimum
        span = max(1.0, maximum - land_floor)
        radius = max(2, min(8, width // 32))
        regional_craters = ((heightmap.get("regional_crater_model") or {}).get("craters") or [])
        global_crater_model = entity.get("crater_model") or {}
        global_craters = global_crater_model.get("craters") or []
        planet_radius_m = max(
            1.0,
            float(global_crater_model.get("radius_m", entity.get("radius_m", 1.0)) or 1.0),
        )
        tectonic_model = entity.get("tectonic_model") or {}
        all_boundary_segments = [
            segment for segment in (tectonic_model.get("boundary_segments") or [])
            if isinstance(segment, dict)
        ]
        segments_by_id = {
            str(segment.get("id")): segment
            for segment in all_boundary_segments
            if segment.get("id")
        }
        orogen_model = tectonic_model.get("orogen_system_model") or {}
        mountain_systems = []
        for system in (orogen_model.get("systems") or []):
            if not isinstance(system, dict):
                continue
            mechanism = str(system.get("mechanism") or "")
            if mechanism not in {
                "continental_collision",
                "ocean_continent_subduction",
                "island_arc_subduction",
                "transpressional_strike_slip",
            }:
                continue
            segments = [
                segments_by_id[str(segment_id)]
                for segment_id in (system.get("source_segment_ids") or [])
                if str(segment_id) in segments_by_id
            ]
            if segments:
                mountain_systems.append((system, segments))
        tectonic_segments = [
            segment
            for _system, segments in mountain_systems
            for segment in segments
        ]
        if not tectonic_segments:
            tectonic_segments = [
                segment for segment in all_boundary_segments
                if str(segment.get("kind") or "") in {"collision", "subduction"}
            ]

        def segment_distance(u, v, segment):
            x1 = float(segment.get("x1", 0.5) or 0.5)
            x2 = x1 + ((float(segment.get("x2", x1) or x1) - x1 + 0.5) % 1.0 - 0.5)
            y1 = float(segment.get("y1", 0.5) or 0.5)
            y2 = float(segment.get("y2", y1) or y1)
            px = float(u)
            if px - x1 > 0.5:
                px -= 1.0
            elif px - x1 < -0.5:
                px += 1.0
            dx, dy = x2 - x1, y2 - y1
            length_sq = dx * dx + dy * dy
            t = 0.0 if length_sq <= 1e-12 else ((px - x1) * dx + (float(v) - y1) * dy) / length_sq
            t = max(0.0, min(1.0, t))
            return math.hypot(px - (x1 + dx * t), float(v) - (y1 + dy * t))
        candidate_pixels = [
            (x, y)
            for y in range(max(radius, int(height * 0.16)), min(height - radius, int(height * 0.84) + 1))
            for x in range(max(radius, int(width * 0.12)), min(width - radius, int(width * 0.88) + 1))
        ]
        best = (float("-inf"), width // 2, height // 2)
        for x, y in candidate_pixels:
            u, v = x / max(1, width - 1), y / max(1, height - 1)
            tectonic_bonus = 0.0
            for segment in tectonic_segments:
                su = (float(segment.get("x1", 0.5)) + float(segment.get("x2", 0.5))) * 0.5
                sv = (float(segment.get("y1", 0.5)) + float(segment.get("y2", 0.5))) * 0.5
                du = abs(u - su)
                du = min(du, 1.0 - du)
                distance = math.hypot(du * 2.0, v - sv)
                tectonic_bonus = max(tectonic_bonus, 0.12 * max(0.0, 1.0 - distance / 0.10))
            connected_orogen_bonus = 0.0
            for system, segments in mountain_systems:
                mean_width = float(
                    ((system.get("geometry") or {}).get("mean_influence_width", 0.025))
                    or 0.025
                )
                distance = min(segment_distance(u, v, segment) for segment in segments)
                corridor = max(0.018, mean_width * 3.2)
                if distance <= corridor:
                    geometry = system.get("geometry") or {}
                    length_prior = _clamp(
                        float(geometry.get("length_km", 0.0) or 0.0) / 5000.0,
                        0.0,
                        1.0,
                    )
                    activity_prior = _clamp(
                        float((system.get("kinematics") or {}).get("activity", 0.0) or 0.0),
                        0.0,
                        1.0,
                    )
                    connected_orogen_bonus = max(
                        connected_orogen_bonus,
                        (0.09 + length_prior * 0.08 + activity_prior * 0.07)
                        * max(0.0, 1.0 - distance / corridor),
                    )
            inside_crater = False
            for crater in regional_craters:
                cu, cv = float(crater.get("center_u", -10.0)), float(crater.get("center_v", -10.0))
                ru = max(1e-6, float(crater.get("radius_fraction_u", 0.0) or 0.0))
                rv = max(1e-6, float(crater.get("radius_fraction_v", 0.0) or 0.0))
                if ((u - cu) / (ru * 1.7)) ** 2 + ((v - cv) / (rv * 1.7)) ** 2 <= 1.0:
                    inside_crater = True
                    break
            if not inside_crater:
                for crater in global_craters:
                    cu = float(crater.get("x", -10.0) or -10.0)
                    cv = float(crater.get("y", -10.0) or -10.0)
                    angular_radius = (
                        max(0.0, float(crater.get("diameter_km", 0.0) or 0.0))
                        * 500.0
                        / planet_radius_m
                    )
                    radius_u = max(1e-6, angular_radius / math.tau)
                    radius_v = max(1e-6, angular_radius / math.pi)
                    wrapped_u = abs(u - cu)
                    wrapped_u = min(wrapped_u, 1.0 - wrapped_u)
                    if (
                        (wrapped_u / (radius_u * 4.0)) ** 2
                        + ((v - cv) / (radius_v * 4.0)) ** 2
                        <= 1.0
                    ):
                        inside_crater = True
                        break
            if inside_crater:
                continue
            center = float(rows[y][x])
            if sea is not None and center <= float(sea) + span * 0.015:
                continue
            samples = [
                float(rows[y - radius][x]), float(rows[y + radius][x]),
                float(rows[y][x - radius]), float(rows[y][x + radius]),
                float(rows[y - radius][x - radius]), float(rows[y + radius][x + radius]),
            ]
            local_relief = max([center, *samples]) - min([center, *samples])
            prominence = max(0.0, center - sum(samples) / len(samples))
            altitude = max(0.0, center - land_floor)
            score = (
                local_relief / span * 0.58
                + prominence / span * 0.14
                + altitude / span * 0.12
                + tectonic_bonus
                + connected_orogen_bonus
            )
            if score > best[0]:
                best = (score, x, y)
        return best[1] / max(1, width - 1), best[2] / max(1, height - 1)

    @staticmethod
    def _configured_refinement_footprint(config, refinement_index):
        schedule = getattr(config, "regional_footprint_schedule_km", None)
        if isinstance(schedule, (list, tuple)) and refinement_index < len(schedule):
            item = schedule[refinement_index]
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    width_km, height_km = float(item[0]), float(item[1])
                except (TypeError, ValueError):
                    return None
            else:
                try:
                    width_km = height_km = float(item)
                except (TypeError, ValueError):
                    return None
            if width_km > 0.0 and height_km > 0.0:
                return width_km, height_km
        if refinement_index == 0:
            width_km = max(0.0, float(config.regional_width_km or 0.0))
            height_km = max(0.0, float(config.regional_height_km or 0.0))
            if width_km > 0.0 and height_km > 0.0:
                return width_km, height_km
        return None

    @staticmethod
    def _representative_region_bounds(parent_entity, config, footprint_km=None):
        """Resolve one deterministic geographic window on the root planet.

        Worldgen's planetary rectangle is an equirectangular longitude /
        latitude domain, and regional refinement converts that domain back to
        physical metres.  Resolving the requested footprint against the
        parent's saved physical dimensions keeps the test window at the
        requested scale while preserving the production refinement path.
        """
        parent_bounds = parent_entity.get("bounds") or {}
        if parent_bounds.get("type") != "bbox":
            return None, None
        if footprint_km is None:
            footprint_km = (
                float(config.regional_width_km or 0.0),
                float(config.regional_height_km or 0.0),
            )
        width_km = max(0.0, float(footprint_km[0] or 0.0))
        height_km = max(0.0, float(footprint_km[1] or 0.0))
        if width_km <= 0.0 or height_km <= 0.0:
            return None, None

        domain_width = float(parent_bounds["max_x"]) - float(parent_bounds["min_x"])
        domain_height = float(parent_bounds["max_y"]) - float(parent_bounds["min_y"])
        physical_width_m, physical_height_m = map_physical_dimensions_m(parent_entity)
        if physical_width_m <= 0.0 or physical_height_m <= 0.0:
            return None, None
        width = domain_width * (width_km * 1000.0) / physical_width_m
        height = domain_height * (height_km * 1000.0) / physical_height_m
        width = min(domain_width, max(1e-6, width))
        height = min(domain_height, max(1e-6, height))

        half_width = width * 0.5
        half_height = height * 0.5
        min_x = float(parent_bounds["min_x"]) + half_width
        max_x = float(parent_bounds["max_x"]) - half_width
        min_y = float(parent_bounds["min_y"]) + half_height
        max_y = float(parent_bounds["max_y"]) - half_height
        center_seed = config.regional_center_seed
        if center_seed is None:
            center_seed = config.randomizer_seed
        if center_seed is None:
            center_seed = str(config.map_seed or config.name)
        seed_bytes = str(center_seed).encode("utf-8")
        center_rng = random.Random(int.from_bytes(hashlib.sha256(seed_bytes).digest()[:8], "big"))

        center_longitude = config.regional_center_longitude
        center_latitude = config.regional_center_latitude
        if (
            center_longitude is None
            and center_latitude is None
            and str(config.regional_target_mode or "manual") == "mountain"
        ):
            # A uniformly random globe point can land in deep ocean, producing
            # a technically valid but diagnostically empty tile. Use the
            # saved production heightfield to select a seeded high-relief land
            # focus instead; explicit coordinates still override this for
            # ocean/coast/desert test cases.
            focus_u, focus_v = HeadlessWorldGenRunner._mountain_center_fraction(parent_entity)
            center_longitude = float(parent_bounds["min_x"]) + focus_u * domain_width
            center_map_y = float(parent_bounds["min_y"]) + focus_v * domain_height
            center_latitude = -center_map_y
        if center_longitude is None:
            center_longitude = center_rng.uniform(min_x, max_x)
        # The map stores Y positive downward, while the representative
        # scenario's public coordinate is geographic latitude. Keep that
        # distinction explicit so the simulated globe focus and the stored
        # diagnostic agree with the user's selected latitude.
        if center_latitude is None:
            center_latitude = center_rng.uniform(-70.0, 70.0)
        center_longitude = max(min_x, min(max_x, float(center_longitude)))
        center_latitude = max(-90.0, min(90.0, float(center_latitude)))
        center_map_y = -center_latitude
        center_map_y = max(min_y, min(max_y, center_map_y))
        center_latitude = -center_map_y
        bounds = {
            "min_x": center_longitude - half_width,
            "max_x": center_longitude + half_width,
            "min_y": center_map_y - half_height,
            "max_y": center_map_y + half_height,
        }
        metadata = {
            "center_latitude": round(center_latitude, 6),
            "center_longitude": round(center_longitude, 6),
            "requested_width_km": width_km,
            "requested_height_km": height_km,
            "resolved_domain_width_degrees": round(width, 8),
            "resolved_domain_height_degrees": round(height, 8),
            "center_seed": str(center_seed),
            "coordinate_system": "equirectangular_longitude_latitude",
        }
        return bounds, metadata

    def _map_ui_region_selection(self, world, parent_entity, config, refinement_index):
        """Simulate the map UI's zoomed selection and visible-region action.

        This deliberately delegates final bounds resolution to
        ``MapSimulation.regenerate_visible_region``.  The headless fixture
        only chooses the camera focus/zoom and a map content viewport, just as
        the interactive map does before the user presses Regenerate Region.
        """
        from simulations.map.map_simulation import MapSimulation

        screen_width, screen_height = (
            int(config.screen_size[0]),
            int(config.screen_size[1]),
        )
        context = SimpleNamespace(
            year=2400,
            root_entity_id=parent_entity.get("id"),
            world_model=world,
            regional_sample_dimensions=config.regional_sample_dimensions,
            regional_feedback_iterations=config.worldgen_feedback_iterations,
            worldgen_storage_root=self.repository_root,
        )
        map_simulation = MapSimulation(context)
        root = map_simulation.get_root_entity() or parent_entity
        parent_bounds = map_simulation._entity_map_bounds(root)
        if not isinstance(parent_bounds, dict):
            raise RuntimeError("Map UI could not resolve the selected parent bounds")

        parent_width = max(1e-9, float(parent_bounds["max_x"]) - float(parent_bounds["min_x"]))
        parent_height = max(1e-9, float(parent_bounds["max_y"]) - float(parent_bounds["min_y"]))
        parent_width_m, parent_height_m = map_physical_dimensions_m(root)
        if parent_width_m <= 0.0 or parent_height_m <= 0.0:
            raise RuntimeError("Map UI could not resolve the selected parent physical dimensions")

        selection_mode = "nested_visible_fraction"
        focus_longitude = None
        focus_latitude = None
        configured_footprint = self._configured_refinement_footprint(
            config, refinement_index,
        )
        if refinement_index == 0 and configured_footprint is not None:
            _unused_bounds, focus = self._representative_region_bounds(
                root, config, configured_footprint,
            )
            focus_longitude = float(focus["center_longitude"])
            focus_latitude = float(focus["center_latitude"])
            target_width_world = parent_width * (configured_footprint[0] * 1000.0) / parent_width_m
            target_height_world = parent_height * (configured_footprint[1] * 1000.0) / parent_height_m
            selection_mode = (
                "seeded_high_relief_land_focus_and_physical_zoom"
                if str(config.regional_target_mode or "manual") == "mountain"
                and config.regional_center_latitude is None
                and config.regional_center_longitude is None
                else "random_geographic_focus_and_physical_zoom"
            )
        else:
            if str(config.regional_target_mode or "manual") == "mountain":
                center_x_fraction, center_y_fraction = self._mountain_center_fraction(root)
                center_x_fraction = max(0.2, min(0.8, center_x_fraction))
                center_y_fraction = max(0.2, min(0.8, center_y_fraction))
            else:
                center_x_fraction = max(0.2, min(0.8, float(config.regional_center_x))) if refinement_index == 0 else 0.5
                center_y_fraction = max(0.2, min(0.8, float(config.regional_center_y))) if refinement_index == 0 else 0.5
            if root.get("location_class") in {"planet", "moon"}:
                focus_longitude = (float(parent_bounds["min_x"]) + parent_width * center_x_fraction)
                focus_latitude = -(float(parent_bounds["min_y"]) + parent_height * center_y_fraction)
            if configured_footprint is not None:
                target_width_world = parent_width * (configured_footprint[0] * 1000.0) / parent_width_m
                target_height_world = parent_height * (configured_footprint[1] * 1000.0) / parent_height_m
            else:
                target_width_world = parent_width * 0.4
                target_height_world = parent_height * 0.4

        camera = Camera(screen_width, screen_height)
        camera.x = (float(parent_bounds["min_x"]) + float(parent_bounds["max_x"])) * 0.5
        camera.y = (float(parent_bounds["min_y"]) + float(parent_bounds["max_y"])) * 0.5

        if root.get("location_class") in {"planet", "moon"}:
            # A focused globe is locally compressed in longitude by cos(lat).
            # Compensate the simulated zoom so a requested geographic window
            # remains representative at random latitudes.
            focus_latitude = max(-89.0, min(89.0, float(focus_latitude or 0.0)))
            map_simulation.map_projection_focus_x = (float(focus_longitude or 0.0) / 360.0) % 1.0
            map_simulation.map_projection_focus_y = max(-0.5, min(0.5, -focus_latitude / 180.0))
            longitude_scale = max(0.12, abs(math.cos(math.radians(focus_latitude))))
        else:
            longitude_scale = 1.0

        usable_height = max(240.0, float(screen_height) * 0.94)
        usable_width = max(240.0, float(screen_width) * 0.94)
        camera.zoom = min(
            usable_height / max(1e-9, target_height_world),
            usable_width / max(1e-9, target_width_world * longitude_scale),
        )
        camera.zoom = max(1e-6, min(float(map_simulation.max_zoom), camera.zoom))

        # The production UI passes its map content rectangle to the action.
        # Keep the simulated content centered in the configured screen while
        # matching the selected footprint's projected aspect ratio.
        viewport_height = min(usable_height, max(240.0, camera.zoom * target_height_world))
        viewport_width = min(usable_width, max(240.0, camera.zoom * target_width_world * longitude_scale))
        viewport_left = (float(screen_width) - viewport_width) * 0.5
        viewport_top = (float(screen_height) - viewport_height) * 0.5
        viewport_rect = SimpleNamespace(
            left=viewport_left,
            right=viewport_left + viewport_width,
            top=viewport_top,
            bottom=viewport_top + viewport_height,
        )
        selected_bounds = map_simulation._visible_refinement_bounds(
            camera,
            screen_width,
            screen_height,
            {"type": "bbox", **{key: float(parent_bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}},
            root,
            viewport_rect=viewport_rect,
        )
        region = map_simulation.regenerate_visible_region(
            camera,
            screen_width,
            screen_height,
            viewport_rect=viewport_rect,
        )
        if not isinstance(region, dict) or not region.get("id"):
            raise RuntimeError(
                f"Map UI regeneration returned no region for level {refinement_index + 1}"
            )
        region_bounds = region.get("bounds") or {}
        return region, {
            "route": "MapSimulation.regenerate_visible_region",
            "selection_mode": selection_mode,
            "focus_longitude": focus_longitude,
            "focus_latitude": focus_latitude,
            "camera_zoom": round(float(camera.zoom), 8),
            "viewport_px": {
                "width": round(float(viewport_width), 3),
                "height": round(float(viewport_height), 3),
            },
            "visible_bounds_before_regeneration": copy.deepcopy(selected_bounds or {}),
            "regenerated_bounds": copy.deepcopy(region_bounds),
        }

    def _resolve_replay_contract(self, config):
        contract = config.replay_contract
        if not isinstance(contract, dict) and config.replay_contract_path:
            contract = json.loads(Path(config.replay_contract_path).read_text(encoding="utf-8"))
        if isinstance(contract, dict):
            self._replay_contract = validate_generation_input_contract(copy.deepcopy(contract))
        return self._replay_contract

    def _prepare_output(self, config):
        for path in (self.entries_root / "locations", self.stages_root, self.layers_root):
            path.mkdir(parents=True, exist_ok=True)
        contract = self._resolve_replay_contract(config)
        system_context = copy.deepcopy((contract or {}).get("system_context") or {})
        star_context = copy.deepcopy((contract or {}).get("star_context") or {})
        self.system_id = str(system_context.get("id") or self.SYSTEM_ID)
        self.star_id = str(star_context.get("id") or self.STAR_ID)
        system_context.update({
                "id": self.system_id,
                "name": system_context.get("name") or "Headless Test System",
                "pretty_name": system_context.get("pretty_name") or system_context.get("name") or "Headless Test System",
                "type": "location",
                "location_class": "star_system",
                "location_role": "star_system",
                "system_role": "star_system",
                "constituents": [self.star_id],
                "wiki_entry": "! Planets\n",
                "tags": ["headless_worldgen_test", "player_contract_replay"] if contract else ["headless_worldgen_test"],
            })
        star_context.update({
                "id": self.star_id,
                "name": star_context.get("name") or "Headless Sol",
                "pretty_name": star_context.get("pretty_name") or star_context.get("name") or "Headless Sol",
                "type": "location",
                "location_class": "star",
                "location_role": "orbital_body",
                "system_role": "orbital_body",
                "star_system": self.system_id,
                "parent_location": self.system_id,
                "tags": ["headless_worldgen_test", "player_contract_replay"] if contract else ["headless_worldgen_test", "solar_analogue"],
            })
        star_context.setdefault("star_class", "main_sequence")
        star_context.setdefault("spectral_class", "G2V")
        star_context.setdefault("mass_kg", 1.98847e30)
        star_context.setdefault("radius_m", 696_340_000.0)
        star_context.setdefault("luminosity_solar", 1.0)
        system_context.setdefault("system_age_gyr", 4.6)
        bootstrap = [system_context, star_context]
        bootstrap_path = self.entries_root / "locations" / "bootstrap.json"
        bootstrap_path.write_text(
            json.dumps(bootstrap, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _initialize_rendering(self, config):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        pygame.font.init()
        width, height = (int(config.screen_size[0]), int(config.screen_size[1]))
        # Some production renderer paths call Surface.convert_alpha(), which
        # requires an initialized display even when all output is off-screen.
        # The dummy driver keeps this headless and avoids opening a window.
        pygame.display.set_mode((width, height))
        camera = Camera(width, height)
        camera.zoom = min(width, height) / (3.4 * WorldGenSimulation.AU_M)
        self._app_view = SimpleNamespace(
            default_font=pygame.font.SysFont("consolas", 15),
            camera=camera,
            storage_root=self.repository_root,
        )
        self._renderer = WorldGenRenderer(self._app_view)

    def _attach_moon(self, sim, config):
        """Attach a moon to the just-committed primary planet.

        Satellites are already a fully supported concept in the interactive
        sim (WorldGenSimulation._begin_moon_orbit_draft /
        _commit_named_planet already write a `location_class: "moon"` entity
        with `parent_body` set) -- this reuses that exact path headlessly
        rather than hand-building a satellite entity. Committing alone
        leaves mass_kg/radius_m unset ("physical model pending"), so one
        extra _save_selected_planet_seed() call is needed for the moon to
        carry the mass/radius that _tidal_regime's satellite loop reads;
        full crust/atmosphere/terrain generation is not needed for a body
        that only needs to exist as a tidal contributor.
        """
        primary_planet_id = sim.selected_world_gen_planet_id
        primary_planet_entity = sim.planet_entity
        primary_stage = sim.editor_stage
        primary_template = sim.active_planet_template
        primary_seed_buffers = dict(sim.seed_input_buffers)
        primary_crust_composition = copy.deepcopy(sim.crust_composition)

        if not sim._begin_moon_orbit_draft(sim.planet_entity):
            raise RuntimeError(sim.commit_status)
        moon_au = max(1e-6, (float(config.moon_semi_major_axis_km) * 1000.0) / WorldGenSimulation.AU_M)
        sim._set_orbit_distances(moon_au, moon_au)
        if config.moon_radius_earth:
            sim.seed_input_buffers["radius_earth"] = sim._format_seed_input(config.moon_radius_earth)
        sim.planet_name_buffer = f"{config.name} Moon"
        if not sim._commit_named_planet():
            raise RuntimeError(sim.commit_status)
        if not sim._save_selected_planet_seed():
            raise RuntimeError(sim.commit_status)

        sim.selected_world_gen_planet_id = primary_planet_id
        sim.planet_entity = primary_planet_entity
        sim.editor_stage = primary_stage
        sim.active_planet_template = primary_template
        sim.seed_input_buffers = primary_seed_buffers
        sim.crust_composition = primary_crust_composition

    def _new_runtime(self, config):
        self._prepare_output(config)
        world = WorldModel()
        sim = WorldGenSimulation(
            world_model=world,
            parent_system_id=self.system_id,
            year=int((self._replay_contract or {}).get("registry_year") or 2400),
            worldgen_storage_root=self.repository_root,
        )
        sim.scientific_sample_dimensions = config.scientific_sample_dimensions
        sim.worldgen_feedback_iterations = int(config.worldgen_feedback_iterations or 2)
        if self._replay_contract:
            first_screen = self._replay_contract["first_screen"]
            identity = self._replay_contract.get("planet_identity") or {}
            orbit = self._replay_contract.get("orbit") or {}
            template_id = str(first_screen.get("planet_template") or "silicate_terrestrial")
            if template_id not in sim.PLANET_TEMPLATES:
                raise ValueError(f"Unknown replay planet template: {template_id}")
            sim.active_planet_template = template_id
            sim._set_orbit_distances(
                float(orbit.get("periapsis_au") or 1.0),
                float(orbit.get("apoapsis_au") or orbit.get("periapsis_au") or 1.0),
            )
            sim.planet_name_buffer = str(identity.get("name") or config.name)
            if not sim._commit_named_planet():
                raise RuntimeError(sim.commit_status)
            for field_id, default_value in sim.DEFAULT_SEED.items():
                value = first_screen.get(field_id, default_value)
                sim.seed_input_buffers[field_id] = sim._format_seed_input(value) if isinstance(value, (int, float)) else str(value)
            sim.crust_composition = copy.deepcopy(first_screen.get("crust_composition") or sim.crust_composition)
            return world, sim
        if config.template_id not in sim.PLANET_TEMPLATES:
            raise ValueError(f"Unknown planet template: {config.template_id}")
        sim.active_planet_template = config.template_id
        sim._set_orbit_distances(float(config.periapsis_au), float(config.apoapsis_au))
        sim.planet_name_buffer = str(config.name)
        if not sim._commit_named_planet():
            raise RuntimeError(sim.commit_status)

        if config.randomize_mode:
            if config.randomize_mode not in {"generic", "eccentric", "gas_giant"}:
                raise ValueError(f"Unknown randomizer mode: {config.randomize_mode}")
            if config.randomizer_seed is None:
                config.randomizer_seed = secrets.randbits(64)
            randomizer_rng = random.Random(config.randomizer_seed)
            sim.randomize_seed(
                mode=config.randomize_mode,
                rng=randomizer_rng,
            )
            if config.earthlike_constraints:
                # Preserve randomized body size, composition, spin, and map
                # seed while keeping this diagnostic fixture in the intended
                # temperate, water-bearing Earth-like family.
                sim.seed_input_buffers["water_fraction"] = sim._format_seed_input(
                    round(randomizer_rng.uniform(0.35, 0.65), 4)
                )
                sim.seed_input_buffers["volatile_inventory"] = "earthlike"
            if config.force_plate_tectonics:
                # Keep every generic randomized physical input, but constrain
                # this benchmark to the plate-tectonic branch so runs remain
                # comparable across seeds.
                sim.seed_input_buffers["tectonics_mode"] = "mobile_lid"
            return world, sim

        template = sim.PLANET_TEMPLATES[config.template_id]
        sim.active_planet_template = config.template_id
        sim.seed_input_buffers.update({
            "radius_earth": sim._format_seed_input(config.radius_earth),
            "core_radius_fraction": sim._format_seed_input(config.core_radius_fraction),
            "crust_thickness_km": sim._format_seed_input(config.crust_thickness_km),
            "angular_velocity_deg_per_hour": sim._format_seed_input(config.angular_velocity_deg_per_hour),
            "water_fraction": sim._format_seed_input(config.water_fraction),
            "volatile_inventory": str(config.volatile_inventory),
            "tectonics_mode": str(config.tectonics_mode),
            "map_seed": str(config.map_seed),
        })
        major_elements = template.get("major_elements") or []
        sim.crust_composition = {
            "major_elements": [
                {
                    "symbol": symbol,
                    "name": element_name(symbol),
                    "abundance_percent": float(abundance),
                }
                for symbol, abundance in major_elements
            ],
            "trace_reserve_percent": TRACE_RESERVE_PERCENT,
            "trace_elements": [
                {
                    "symbol": str(item["symbol"]),
                    "name": element_name(item["symbol"]),
                    "abundance_percent": float(item["abundance_percent"]),
                    "rarity": str(item.get("rarity") or "uncommon"),
                }
                for item in config.trace_elements
            ],
        }
        return world, sim

    def _render_stage(self, sim, index, label):
        width, height = self._app_view.camera.width, self._app_view.camera.height
        surface = pygame.Surface((width, height))
        surface.fill((5, 8, 10))
        self._renderer.draw(surface, sim)
        path = self.stages_root / f"{index:02d}_{self._slug(label)}.png"
        pygame.image.save(surface, str(path))
        return str(path)

    @staticmethod
    def _scalar_color(value, minimum, maximum, palette):
        if value is None:
            return 20, 22, 28
        span = max(1e-9, float(maximum) - float(minimum))
        t = max(0.0, min(1.0, (float(value) - float(minimum)) / span))
        scaled = t * (len(palette) - 1)
        low = min(len(palette) - 1, int(math.floor(scaled)))
        high = min(len(palette) - 1, low + 1)
        blend = scaled - low
        return tuple(
            int(palette[low][channel] * (1.0 - blend) + palette[high][channel] * blend)
            for channel in range(3)
        )

    def _render_scalar_layer(self, rows, size, palette, fixed_range=None):
        rows = rows if isinstance(rows, list) else []
        valid_rows = [row for row in rows if isinstance(row, list) and row]
        if not valid_rows:
            surface = pygame.Surface(size)
            surface.fill((20, 22, 28))
            return surface
        height = len(valid_rows)
        width = min(len(row) for row in valid_rows)
        values = [
            float(value)
            for row in valid_rows
            for value in row[:width]
            if isinstance(value, (int, float))
        ]
        minimum, maximum = fixed_range or (
            (min(values), max(values)) if values else (0.0, 1.0)
        )
        source = pygame.Surface((width, height))
        for y, row in enumerate(valid_rows):
            for x, value in enumerate(row[:width]):
                source.set_at((x, y), self._scalar_color(value, minimum, maximum, palette))
        return pygame.transform.smoothscale(source, size)

    def _render_height_layer(self, planet, size, include_materials=False):
        surface = pygame.Surface(size)
        surface.fill((8, 10, 14))
        rect = surface.get_rect()
        self._renderer._draw_heightmap_land_ocean(
            surface,
            rect,
            rect,
            planet.get("heightmap_model") or {},
            selected_planet=planet,
            material_model=planet.get("natural_material_model"),
            material_heatmap_model=planet.get("material_heatmap_model") if include_materials else None,
        )
        return surface

    def _render_heightmap_hillshade(self, planet, size):
        """Render the stored physical heightfield as a morphology diagnostic.

        True color is intentionally material-driven and can hide relief on a
        uniform lithologic province.  This layer is a diagnostic view of the
        actual child heightfield: the broad form is inherited from the parent
        and the hillshade reveals only the residual relief resolved at this
        level.  It is not a second terrain representation.
        """
        heightmap = planet.get("heightmap_model") or {}
        grid = heightmap.get("sample_grid") or {}
        rows = grid.get("rows") or []
        if not rows or not rows[0]:
            surface = pygame.Surface(size)
            surface.fill((22, 26, 34))
            return surface
        grid_height = len(rows)
        grid_width = len(rows[0])
        sea_level = heightmap.get("sea_level_m")
        all_values = [
            float(value)
            for row in rows
            for value in row[:grid_width]
            if isinstance(value, (int, float))
        ]
        minimum = min(all_values) if all_values else -1.0
        maximum = max(all_values) if all_values else 1.0
        # Separate land relief from bathymetry for readability.  Otherwise a
        # deep ocean basin compresses a several-kilometre mountain range into
        # a narrow fraction of the diagnostic's tonal range.
        land_values = [
            float(value)
            for y, row in enumerate(rows)
            for x, value in enumerate(row[:grid_width])
            if sea_level is None or float(value) > float(sea_level)
        ]
        land_minimum = min(land_values) if land_values else minimum
        land_maximum = max(land_values) if land_values else maximum
        land_span = max(1.0, land_maximum - land_minimum)
        span = max(1.0, maximum - minimum)
        source = pygame.Surface((grid_width, grid_height))
        light_x, light_y, light_z = -0.62, -0.48, 0.62
        light_length = max(1e-6, math.sqrt(light_x ** 2 + light_y ** 2 + light_z ** 2))
        light_x /= light_length
        light_y /= light_length
        light_z /= light_length
        for y, row in enumerate(rows):
            north_row = rows[max(0, y - 1)]
            south_row = rows[min(grid_height - 1, y + 1)]
            for x, value in enumerate(row[:grid_width]):
                west_x = max(0, x - 1)
                east_x = min(grid_width - 1, x + 1)
                dx = (float(row[east_x]) - float(row[west_x])) * 0.5
                dy = (float(south_row[x]) - float(north_row[x])) * 0.5
                # The physical samples are intentionally not stretched into
                # an exaggerated mountain renderer.  A modest vertical gain
                # keeps basin/ridge topology visible at both regional levels.
                nx = -dx / max(1.0, span * 0.018)
                ny = -dy / max(1.0, span * 0.018)
                nz = 1.0
                normal_length = max(1e-6, math.sqrt(nx ** 2 + ny ** 2 + nz ** 2))
                shade = max(
                    0.0,
                    min(
                        1.0,
                        (nx * light_x + ny * light_y + nz * light_z)
                        / normal_length,
                    ),
                )
                if sea_level is not None and float(value) <= float(sea_level):
                    base = (22, 52, 78)
                    relief_t = max(0.0, min(1.0, (float(value) - minimum) / span))
                    color = tuple(
                        max(0, min(255, int(channel * (0.55 + shade * 0.65))))
                        for channel in base
                    )
                else:
                    relief_t = max(
                        0.0,
                        min(1.0, (float(value) - land_minimum) / land_span),
                    )
                    # Neutral earth tones prevent the diagnostic from being
                    # confused with a material or climate layer.
                    base = (
                        int(74 + relief_t * 102),
                        int(78 + relief_t * 86),
                        int(72 + relief_t * 62),
                    )
                    color = tuple(
                        max(0, min(255, int(channel * (0.55 + shade * 0.70))))
                        for channel in base
                    )
                source.set_at((x, y), color)
        # Planetary maps are 2:1 in equirectangular space, while regional
        # patches carry their own physical width/height and are commonly
        # square.  Preserve that physical aspect in the diagnostic canvas;
        # stretching a square child to 2:1 makes inherited ridge directions
        # and border behavior impossible to judge visually.
        physical_width_m, physical_height_m = map_physical_dimensions_m(planet)
        source_aspect = (
            physical_width_m / physical_height_m
            if physical_width_m > 0.0 and physical_height_m > 0.0
            else source.get_width() / max(1, source.get_height())
        )
        canvas_width, canvas_height = int(size[0]), int(size[1])
        canvas_aspect = canvas_width / max(1, canvas_height)
        if source_aspect > canvas_aspect:
            draw_width = canvas_width
            draw_height = max(1, int(round(canvas_width / source_aspect)))
        else:
            draw_height = canvas_height
            draw_width = max(1, int(round(canvas_height * source_aspect)))
        rendered = pygame.Surface((canvas_width, canvas_height))
        rendered.fill((8, 10, 14))
        scaled = pygame.transform.smoothscale(source, (draw_width, draw_height))
        rendered.blit(
            scaled,
            ((canvas_width - draw_width) // 2, (canvas_height - draw_height) // 2),
        )
        return rendered

    def _render_material_layer(self, planet, size):
        model = planet.get("material_heatmap_model") or {}
        composite = model.get("composite_layer") or {}
        path = Path(composite.get("bundle_path") or "")
        if path and not path.is_absolute():
            candidates = (
                self.output_root / path,
                self.repository_root / path,
                Path(__file__).resolve().parents[2] / path,
            )
            path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        source = load_raster_bundle_surface(
            path,
            composite.get("bundle_layer_id") or "composite",
        ) if path else None
        if source is None:
            source = pygame.Surface(size, pygame.SRCALPHA)
            source.fill((20, 22, 28, 255))
        background = self._render_height_layer(planet, size, include_materials=False)
        overlay = pygame.transform.smoothscale(source, size)
        background.blit(overlay, (0, 0))
        return background

    def _render_climate_layer(self, planet, size):
        surface = pygame.Surface(size)
        self._renderer._draw_water_cycle_preview(
            surface,
            surface.get_rect(),
            planet.get("water_cycle_model") or {},
        )
        return surface

    def _render_coastal_layer(self, planet, size, show_legend=True):
        width, height = int(size[0]), int(size[1])
        surface = self._render_height_layer(
            planet,
            (width, height),
            include_materials=False,
        )
        shade = pygame.Surface((width, height), pygame.SRCALPHA)
        shade.fill((7, 15, 24, 82))
        surface.blit(shade, (0, 0))
        model = planet.get("coastal_geomorphology_model") or {}
        segments = model.get("segments") or []

        def uv_to_pixel(point):
            return (
                int(round(float(point[0]) * (width - 1))),
                int(round(float(point[1]) * (height - 1))),
            )

        def draw_arrow(start, end, color, line_width=2):
            pygame.draw.aaline(surface, color, start, end)
            dx = float(end[0] - start[0])
            dy = float(end[1] - start[1])
            length = math.hypot(dx, dy)
            if length < 2.0:
                return
            ux, uy = dx / length, dy / length
            head = max(4.0, min(8.0, length * 0.55))
            left = (
                int(round(end[0] - ux * head - uy * head * 0.55)),
                int(round(end[1] - uy * head + ux * head * 0.55)),
            )
            right = (
                int(round(end[0] - ux * head + uy * head * 0.55)),
                int(round(end[1] - uy * head - ux * head * 0.55)),
            )
            pygame.draw.polygon(surface, color, [end, left, right])

        counts = {}
        colors = {}
        for segment in segments:
            assemblage = str(segment.get("morphology_assemblage") or segment.get("primary_assemblage") or "unclassified")
            counts[assemblage] = counts.get(assemblage, 0) + 1
            colors[assemblage] = tuple(segment.get("display_color") or [220, 196, 116])

        for segment in segments:
            color = tuple(segment.get("display_color") or [220, 196, 116])
            run = []
            for point in ((segment.get("geometry") or {}).get("points") or []):
                candidate = uv_to_pixel(point)
                if run and abs(candidate[0] - run[-1][0]) > width * 0.5:
                    if len(run) >= 2:
                        pygame.draw.lines(surface, (8, 12, 18), False, run, 5)
                        pygame.draw.lines(surface, color, False, run, 3)
                        pygame.draw.aalines(surface, color, False, run)
                    run = []
                run.append(candidate)
            if len(run) >= 2:
                pygame.draw.lines(surface, (8, 12, 18), False, run, 5)
                pygame.draw.lines(surface, color, False, run, 3)
                pygame.draw.aalines(surface, color, False, run)

            points = ((segment.get("geometry") or {}).get("points") or [])
            if not points:
                continue
            measurements = segment.get("measurements") or {}
            centroid = measurements.get("centroid_uv") or points[len(points) // 2]
            center = uv_to_pixel(centroid)
            normal = measurements.get("seaward_normal_uv") or [0.0, 1.0]
            normal_length = max(1e-9, math.hypot(float(normal[0]), float(normal[1])))
            nx = float(normal[0]) / normal_length
            ny = float(normal[1]) / normal_length

            exposure = float((segment.get("wave_climate") or {}).get("exposure_index", 0.0) or 0.0)
            wave_length = max(5.0, width * 0.008 * (0.35 + exposure * 0.65))
            wave_end = (
                int(round(center[0] + nx * wave_length)),
                int(round(center[1] + ny * wave_length)),
            )
            pygame.draw.aaline(surface, (82, 188, 236), center, wave_end)

            tidal_range = float((segment.get("tidal_regime") or {}).get("estimated_range_m", 0.0) or 0.0)
            tide_length = max(3.0, width * 0.004 * (0.35 + min(1.0, tidal_range / 5.0) * 0.65))
            tide_end = (
                int(round(center[0] - nx * tide_length)),
                int(round(center[1] - ny * tide_length)),
            )
            pygame.draw.aaline(surface, (112, 232, 218), center, tide_end)

            orientation = float(measurements.get("orientation_rad", 0.0) or 0.0)
            direction = -1.0 if (segment.get("wave_climate") or {}).get("longshore_transport_direction") == "chain_reverse" else 1.0
            transport = float((segment.get("wave_climate") or {}).get("transport_capacity_index", 0.0) or 0.0)
            transport_length = max(6.0, width * 0.010 * (0.4 + transport * 0.6))
            transport_end = (
                int(round(center[0] + math.cos(orientation) * direction * transport_length)),
                int(round(center[1] + math.sin(orientation) * direction * transport_length)),
            )
            draw_arrow(center, transport_end, (244, 174, 76))

        if segments and show_legend:
            font_size = max(12, int(round(min(width / 85.0, height / 28.0))))
            font = pygame.font.SysFont("consolas", font_size)
            legend_rows = sorted(counts, key=lambda key: (-counts[key], key))[:6]
            line_height = font.get_linesize() + 3
            panel_width = min(width - 24, max(280, int(width * 0.28)))
            panel_height = 16 + line_height * (len(legend_rows) + 4)
            panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
            panel.fill((8, 14, 22, 218))
            title = font.render("COASTAL GEOMORPHOLOGY", True, (240, 244, 248))
            panel.blit(title, (12, 8))
            y = 8 + line_height
            for assemblage in legend_rows:
                color = colors.get(assemblage, (220, 196, 116))
                pygame.draw.line(panel, color, (12, y + font_size // 2), (36, y + font_size // 2), 4)
                label = f"{assemblage.replace('_', ' ')} ({counts[assemblage]})"
                panel.blit(font.render(label, True, (222, 228, 236)), (44, y))
                y += line_height
            for color, label in (
                ((82, 188, 236), "wave exposure"),
                ((112, 232, 218), "tidal range"),
                ((244, 174, 76), "longshore transport"),
            ):
                pygame.draw.line(panel, color, (12, y + font_size // 2), (36, y + font_size // 2), 2)
                panel.blit(font.render(label, True, (200, 210, 222)), (44, y))
                y += line_height
            surface.blit(panel, (12, 12))
        return surface

    def _save_layer(self, label, surface, prefix=""):
        filename = f"{self._slug(prefix)}_{self._slug(label)}.png" if prefix else f"{self._slug(label)}.png"
        path = self.layers_root / filename
        pygame.image.save(surface, str(path))
        return {"label": label, "path": str(path), "surface": surface}

    def _render_layers(self, planet, config, prefix=""):
        size = (int(config.layer_size[0]), int(config.layer_size[1]))
        water = planet.get("water_cycle_model") or {}
        climate = water.get("climate_grid") or {}
        evolution = planet.get("surface_evolution_model") or {}
        process = evolution.get("process_grid") or {}
        layers = [
            self._save_layer(
                "Heightmap Hillshade",
                self._render_heightmap_hillshade(planet, size),
                prefix,
            ),
            self._save_layer("True Color", self._render_height_layer(planet, size, include_materials=True), prefix),
            self._save_layer("Surface Materials", self._render_material_layer(planet, size), prefix),
            self._save_layer("Climate and Rivers", self._render_climate_layer(planet, size), prefix),
            self._save_layer("Coastal Geomorphology", self._render_coastal_layer(planet, size), prefix),
            self._save_layer(
                "Surface Temperature",
                self._render_scalar_layer(
                    climate.get("temperature_rows_k"),
                    size,
                    [(20, 38, 90), (62, 126, 184), (82, 160, 112), (220, 190, 92), (184, 72, 52)],
                    fixed_range=(220.0, 330.0),
                ),
                prefix,
            ),
            self._save_layer(
                "Annual Precipitation",
                self._render_scalar_layer(
                    climate.get("annual_precipitation_rows_mm"),
                    size,
                    [(104, 78, 50), (196, 164, 92), (94, 160, 128), (48, 120, 180), (220, 236, 244)],
                    fixed_range=(0.0, 4200.0),
                ),
                prefix,
            ),
            self._save_layer(
                "Chemical Weathering",
                self._render_scalar_layer(
                    process.get("chemical_weathering_rows"),
                    size,
                    [(30, 30, 34), (104, 84, 58), (170, 116, 66), (214, 174, 104), (238, 222, 166)],
                    fixed_range=(0.0, 1.0),
                ),
                prefix,
            ),
        ]
        return layers

    def _build_contact_sheet(self, layers, config, filename="map_layers_contact_sheet.png"):
        tile_w, tile_h = int(config.layer_size[0]), int(config.layer_size[1])
        columns = 2
        rows = int(math.ceil(len(layers) / columns))
        header_h = 38
        gap = 14
        sheet = pygame.Surface((
            columns * tile_w + (columns + 1) * gap,
            rows * (tile_h + header_h) + (rows + 1) * gap,
        ))
        sheet.fill((16, 19, 26))
        font = pygame.font.SysFont("consolas", 18)
        for index, layer in enumerate(layers):
            col = index % columns
            row = index // columns
            x = gap + col * (tile_w + gap)
            y = gap + row * (tile_h + header_h)
            label_surface = font.render(layer["label"], True, (232, 236, 244))
            sheet.blit(label_surface, (x + 8, y + 8))
            tile_rect = pygame.Rect(x, y + header_h, tile_w, tile_h)
            sheet.blit(layer["surface"], tile_rect.topleft)
            pygame.draw.rect(sheet, (112, 124, 148), tile_rect, 1)
        path = self.images_root / filename
        pygame.image.save(sheet, str(path))
        return str(path)

    def _build_lod_overview(self, level_renderings, config, filename="regional_lod_overview.png"):
        """Build a compact cross-level comparison from already-rendered layers."""
        if not level_renderings:
            return ""
        representative_labels = (
            "True Color",
            "Surface Materials",
            "Climate and Rivers",
            "Annual Precipitation",
        )
        tile_w = max(220, min(360, int(config.layer_size[0] * 0.55)))
        tile_h = max(120, min(200, int(config.layer_size[1] * 0.55)))
        columns = len(representative_labels)
        header_h = 56
        gap = 12
        row_h = tile_h + 28
        sheet = pygame.Surface((columns * tile_w + (columns + 1) * gap, header_h + len(level_renderings) * (row_h + gap) + gap))
        sheet.fill((12, 16, 23))
        font = pygame.font.SysFont("consolas", max(12, min(18, tile_w // 18)))
        small_font = pygame.font.SysFont("consolas", max(10, min(14, tile_w // 22)))
        for column, label in enumerate(representative_labels):
            x = gap + column * (tile_w + gap)
            title = font.render(label, True, (236, 240, 248))
            sheet.blit(title, (x + 6, 10))
        for row, rendering in enumerate(level_renderings):
            y = header_h + gap + row * (row_h + gap)
            level = rendering.get("detail_level")
            level_id = str(rendering.get("detail_level_id") or "lod")
            footprint = rendering.get("physical_footprint_m") or {}
            spacing = rendering.get("sample_spacing_m") or {}
            label = (
                f"LOD {level} {level_id} | "
                f"{float(footprint.get('width', 0.0) or 0.0) / 1000.0:.2f} x "
                f"{float(footprint.get('height', 0.0) or 0.0) / 1000.0:.2f} km | "
                f"{float(spacing.get('x', 0.0) or 0.0):.2f} m/px"
            )
            sheet.blit(small_font.render(label, True, (178, 190, 208)), (gap, y - 19))
            level_layers = {str(item.get("label")): item for item in rendering.get("layers") or []}
            for column, layer_label in enumerate(representative_labels):
                x = gap + column * (tile_w + gap)
                tile_rect = pygame.Rect(x, y, tile_w, tile_h)
                layer = level_layers.get(layer_label)
                if layer and layer.get("surface") is not None:
                    surface = pygame.transform.smoothscale(layer["surface"], (tile_w, tile_h))
                    sheet.blit(surface, tile_rect.topleft)
                else:
                    sheet.fill((24, 28, 36), tile_rect)
                pygame.draw.rect(sheet, (104, 118, 142), tile_rect, 1)
        path = self.images_root / filename
        pygame.image.save(sheet, str(path))
        return str(path)

    @staticmethod
    def _summary(planet, config, stage_history):
        atmosphere = planet.get("atmosphere_model") or {}
        regime = planet.get("interior_regime_model") or {}
        interior = regime.get("interior") or {}
        thermal = regime.get("thermal_evolution") or {}
        heightmap = planet.get("heightmap_model") or {}
        water = planet.get("water_cycle_model") or {}
        coastal = planet.get("coastal_geomorphology_model") or {}
        hypsometry = heightmap.get("hypsometry_summary") or {}
        seed = planet.get("world_gen_seed") or {}
        physics = seed.get("derived_planet_physics") or {}
        return {
            "config": asdict(config),
            "planet_id": planet.get("id"),
            "planet_name": planet.get("name"),
            "stage_history": stage_history,
            "generated_seed": {
                field: seed.get(field)
                for field in (
                    "planet_template",
                    "planet_template_label",
                    "radius_earth",
                    "core_radius_fraction",
                    "crust_thickness_km",
                    "angular_velocity_deg_per_hour",
                    "water_fraction",
                    "volatile_inventory",
                    "tectonics_mode",
                    "map_seed",
                )
            } | {
                "rotation_period_hours": physics.get(
                    "rotation_period_hours",
                    planet.get("rotation_period_hours"),
                ),
            },
            "atmosphere_class": atmosphere.get("atmosphere_class"),
            "outgassing_redox_state": atmosphere.get("outgassing_redox_state"),
            "dominant_gases": [
                {
                    "molecule": row.get("molecule"),
                    "percent": row.get("percent"),
                }
                for row in (atmosphere.get("composition") or [])[:5]
            ],
            "surface_pressure_bar": atmosphere.get("surface_pressure_bar"),
            "surface_temperature_k": atmosphere.get("estimated_surface_temperature_k"),
            "tectonic_regime": interior.get("tectonic_regime"),
            "heat_pipe_support": thermal.get("heat_pipe_support"),
            "regional_material_candidate_count": len(
                (planet.get("natural_material_model") or {}).get(
                    "regional_material_candidates"
                )
                or []
            ),
            "elevation_range_m": [
                heightmap.get("min_elevation_m"),
                heightmap.get("max_elevation_m"),
            ],
            "land_fraction": hypsometry.get("land_fraction"),
            "ocean_fraction": hypsometry.get("ocean_fraction"),
            "ice_fraction": hypsometry.get("ice_fraction"),
            "river_count": water.get("river_count"),
            "coastal_geomorphology": copy.deepcopy(coastal.get("summary") or {}),
            "mean_land_precipitation_mm": (water.get("runoff_summary") or {}).get("mean_land_precipitation_mm"),
            "material_layers": [
                {
                    "material_id": layer.get("material_id"),
                    "name": layer.get("name"),
                    "coverage_fraction": layer.get("coverage_fraction"),
                    "affinity_profile": layer.get("affinity_profile"),
                }
                for layer in (planet.get("material_heatmap_model") or {}).get("layers") or []
            ],
            "mineralization_potential": (
                (planet.get("mineralization_potential_model") or {}).get("summary")
            ),
            "desert_surface_morphology": (
                (planet.get("desert_surface_morphology_model") or {}).get("summary")
            ),
            "duricrust_weathering": (
                (planet.get("duricrust_weathering_model") or {}).get("summary")
            ),
            "karst_dissolution": (
                (planet.get("karst_dissolution_model") or {}).get("summary")
            ),
            "periglacial_patterned_ground": (
                (planet.get("periglacial_patterned_ground_model") or {}).get("summary")
            ),
            "playa_evaporite_basins": (
                (planet.get("playa_evaporite_basins_model") or {}).get("summary")
            ),
            "causal_feature_diagnostics": derive_causal_feature_diagnostics(planet),
            "climate_field_diagnostics": copy.deepcopy(
                (water.get("climate_field_diagnostics") or {})
            ),
        }

    def run(self, config=None):
        run_started_at = time.perf_counter()
        config = config or HeadlessWorldGenConfig()
        if config.render_outputs:
            self._initialize_rendering(config)
        world, sim = self._new_runtime(config)
        if config.attach_moon:
            self._attach_moon(sim, config)
        stage_history = []
        stage_fingerprints = []
        stage_screenshots = []
        action_timings = []
        pipeline_action_sequence = []
        tectonic_pass_used = False

        def capture(label):
            stage_history.append(sim.editor_stage)
            planet_snapshot = sim._selected_planet_entity() or {}
            encoded = json.dumps(
                planet_snapshot,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            stage_fingerprints.append({
                "label": label,
                "stage": sim.editor_stage,
                "planet_state_sha256": hashlib.sha256(encoded).hexdigest(),
            })
            if config.render_outputs:
                stage_screenshots.append(self._render_stage(sim, len(stage_screenshots) + 1, label))

        def advance(action, expected_stage):
            started_at = time.perf_counter()
            succeeded = action()
            action_name = getattr(action, "__name__", action.__class__.__name__)
            action_timings.append({
                "action": action_name,
                "expected_stage": expected_stage,
                "seconds": round(time.perf_counter() - started_at, 6),
            })
            if not succeeded:
                raise RuntimeError(sim.commit_status)
            if sim.editor_stage != expected_stage:
                raise RuntimeError(f"Expected stage {expected_stage}, got {sim.editor_stage}: {sim.commit_status}")
            pipeline_action_sequence.append(action_name)

        capture("crust")
        advance(sim._save_selected_planet_seed, "atmosphere")
        capture("atmosphere")
        atmosphere_started_at = time.perf_counter()
        atmosphere_succeeded = sim._save_atmosphere_model()
        action_timings.append({
            "action": "_save_atmosphere_model",
            "expected_stage": "regime_or_gas_giant_terminal",
            "seconds": round(time.perf_counter() - atmosphere_started_at, 6),
        })
        if not atmosphere_succeeded:
            raise RuntimeError(sim.commit_status)
        pipeline_action_sequence.append("_save_atmosphere_model")
        atmosphere_planet = sim._selected_planet_entity()
        gas_giant_terminal = (
            sim.editor_stage == "atmosphere"
            and isinstance(atmosphere_planet, dict)
            and sim._planet_has_gas_giant_markers(atmosphere_planet)
        )
        if gas_giant_terminal:
            capture("gas_giant_complete")
        else:
            if sim.editor_stage != "regime":
                raise RuntimeError(
                    f"Expected stage regime, got {sim.editor_stage}: {sim.commit_status}"
                )
            capture("regime")
            advance(sim._save_interior_regime_model, "terrain")
            capture("terrain")
            advance(sim._save_terrain_seed_model, "heightmap")
            capture("heightmap")
            if sim._heightmap_can_advance_tectonics():
                tectonic_pass_used = True
                advance(sim._handle_heightmap_primary_action, "heightmap")
                capture("heightmap_after_tectonics")
            advance(sim._handle_heightmap_primary_action, "water_cycle")
            capture("water_cycle")

        planet = sim._selected_planet_entity()
        if not isinstance(planet, dict):
            raise RuntimeError("World generation lost the selected planet")

        regional_refinement_ids = []
        regional_materials_path = ""
        regional_region_path = ""
        regional_layers = []
        regional_contact_sheet = ""
        regional_level_diagnostics = []
        regional_lod_overview = ""
        diagnostic_level_renderings = []
        regional_level_snapshot_paths = []
        refinement_parent = planet
        regional_refinement_manifest = []
        regional_selection_diagnostics = []
        representative_region = None
        refinement_depth = (
            0
            if gas_giant_terminal
            else max(0, int(config.regional_refinement_depth or 0))
        )
        for refinement_index in range(refinement_depth):
            configured_footprint = self._configured_refinement_footprint(
                config, refinement_index,
            )
            if refinement_index == 0 and configured_footprint is not None:
                _unused_bounds, representative_region = self._representative_region_bounds(
                    refinement_parent, config, configured_footprint,
                )
            refinement_parent, selection_diagnostic = self._map_ui_region_selection(
                world,
                refinement_parent,
                config,
                refinement_index,
            )
            regional_selection_diagnostics.append(selection_diagnostic)
            regional_refinement_ids.append(str(refinement_parent.get("id")))
            regional_heightmap = refinement_parent.get("heightmap_model") or {}
            regional_refinement_manifest.append({
                "id": refinement_parent.get("id"),
                "detail_level": refinement_parent.get("map_detail_level"),
                "detail_level_id": (regional_heightmap.get("detail_level_spec") or {}).get("id"),
                "bounds": copy.deepcopy(refinement_parent.get("bounds") or {}),
                "center": copy.deepcopy(refinement_parent.get("coords") or {}),
                "physical_footprint_m": {
                    "width": regional_heightmap.get("region_width_m"),
                    "height": regional_heightmap.get("region_height_m"),
                },
                "sample_grid": {
                    key: (regional_heightmap.get("sample_grid") or {}).get(key)
                    for key in ("width", "height", "wrap_x", "wrap_y")
                },
                "sample_spacing_m": {
                    "x": regional_heightmap.get("sample_spacing_x_m"),
                    "y": regional_heightmap.get("sample_spacing_y_m"),
                },
                "source_uv_bounds": copy.deepcopy(regional_heightmap.get("source_uv_bounds") or {}),
                "parent_lineage": copy.deepcopy(
                    (regional_heightmap.get("generated_truth_lineage") or {})
                ),
                "map_selection": copy.deepcopy(selection_diagnostic),
                "production_tectonic_response": copy.deepcopy(
                    regional_heightmap.get("production_tectonic_response") or {}
                ),
                "regional_tectonic_model": {
                    "status": (refinement_parent.get("tectonic_model") or {}).get("status"),
                    "source_status": (refinement_parent.get("tectonic_model") or {}).get("source_status"),
                    "plate_count": len((refinement_parent.get("tectonic_model") or {}).get("plates") or []),
                    "boundary_segment_count": len((refinement_parent.get("tectonic_model") or {}).get("boundary_segments") or []),
                },
            })
            # Retain every intermediate child entity, including its actual
            # sample rows and parent lineage. The final child alone is not
            # enough to prove that LOD N was derived from LOD N-1.
            snapshot_detail_level = int(refinement_parent.get("map_detail_level", 0) or 0)
            snapshot_detail_level_id = str(
                (regional_heightmap.get("detail_level_spec") or {}).get("id") or "lod"
            )
            snapshot_root = self.output_root / "regional"
            snapshot_root.mkdir(parents=True, exist_ok=True)
            snapshot_path = snapshot_root / (
                f"lod_{snapshot_detail_level:02d}_{self._slug(snapshot_detail_level_id)}.json"
            )
            snapshot_path.write_text(
                json.dumps(refinement_parent, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            regional_level_snapshot_paths.append(str(snapshot_path))
            if config.render_outputs:
                detail_level = snapshot_detail_level
                detail_level_id = snapshot_detail_level_id
                level_layers = self._render_layers(
                    refinement_parent,
                    config,
                    prefix=f"regional_lod_{detail_level:02d}_{detail_level_id}",
                )
                level_contact_sheet = self._build_contact_sheet(
                    level_layers,
                    config,
                    filename=f"regional_lod_{detail_level:02d}_{detail_level_id}_layers_contact_sheet.png",
                )
                diagnostic_level_renderings.append({
                    "detail_level": detail_level,
                    "detail_level_id": detail_level_id,
                    "physical_footprint_m": copy.deepcopy(
                        regional_refinement_manifest[-1]["physical_footprint_m"]
                    ),
                    "sample_spacing_m": copy.deepcopy(
                        regional_refinement_manifest[-1]["sample_spacing_m"]
                    ),
                    "snapshot_path": str(snapshot_path),
                    "layers": level_layers,
                    "contact_sheet": level_contact_sheet,
                })
        if regional_refinement_ids:
            regional_region_path_obj = self.output_root / "regional_region.json"
            regional_region_path_obj.write_text(
                json.dumps(refinement_parent, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            regional_region_path = str(regional_region_path_obj)
            regional_materials_path_obj = self.output_root / "regional_materials.json"
            regional_materials_path_obj.write_text(
                json.dumps(
                    refinement_parent.get("regional_material_model") or {},
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            regional_materials_path = str(regional_materials_path_obj)

        if not config.render_outputs:
            layers = []
            contact_sheet = ""
        elif gas_giant_terminal:
            stage_surface = pygame.image.load(stage_screenshots[-1])
            layers = [{
                "label": "Gas Giant Atmosphere",
                "path": stage_screenshots[-1],
                "surface": pygame.transform.smoothscale(
                    stage_surface,
                    (int(config.layer_size[0]), int(config.layer_size[1])),
                ),
            }]
        else:
            layers = self._render_layers(planet, config)
        if config.render_outputs:
            contact_sheet = self._build_contact_sheet(layers, config)
            if regional_refinement_ids:
                if diagnostic_level_renderings:
                    final_rendering = diagnostic_level_renderings[-1]
                    regional_layers = final_rendering["layers"]
                    regional_contact_sheet = final_rendering["contact_sheet"]
                    regional_lod_overview = self._build_lod_overview(
                        diagnostic_level_renderings,
                        config,
                    )
                    regional_level_diagnostics = [
                        {
                            "detail_level": rendering["detail_level"],
                            "detail_level_id": rendering["detail_level_id"],
                            "physical_footprint_m": rendering["physical_footprint_m"],
                            "sample_spacing_m": rendering["sample_spacing_m"],
                            "snapshot_path": rendering.get("snapshot_path"),
                            "layer_images": [
                                {"label": item["label"], "path": item["path"]}
                                for item in rendering["layers"]
                            ],
                            "contact_sheet": rendering["contact_sheet"],
                        }
                        for rendering in diagnostic_level_renderings
                    ]
        summary = self._summary(planet, config, stage_history)
        summary["representative_region"] = representative_region
        summary["regional_refinement_manifest"] = regional_refinement_manifest
        summary["regional_selection_diagnostics"] = regional_selection_diagnostics
        summary["regional_level_snapshot_paths"] = list(regional_level_snapshot_paths)
        summary["render_diagnostics"] = {
            "stage_screenshots": list(stage_screenshots),
            "planetary_layer_images": [
                {"label": item["label"], "path": item["path"]}
                for item in layers
            ],
            "planetary_contact_sheet": contact_sheet,
            "regional_levels": copy.deepcopy(regional_level_diagnostics),
            "regional_lod_overview": regional_lod_overview,
        }
        summary["timings"] = {
            "actions": action_timings,
            "generation_and_render_seconds": round(time.perf_counter() - run_started_at, 6),
        }
        summary["parity"] = {
            "mode": "player_contract_replay" if self._replay_contract else "headless_authored_inputs",
            "input_contract_fingerprint": contract_fingerprint(self._replay_contract) if self._replay_contract else (planet.get("world_gen_input_contract") or {}).get("fingerprint_sha256"),
            "stage_sequence": list(stage_history),
            "stage_fingerprints": stage_fingerprints,
            "ordinary_stage_renderer": "simulations.world_gen.world_gen_renderer.WorldGenRenderer",
        }
        summary["pipeline_parity"] = verify_production_pipeline(
            sim,
            pipeline_action_sequence,
            tectonic_pass_used=tectonic_pass_used,
            gas_giant_terminal=gas_giant_terminal,
            regional_selection_diagnostics=regional_selection_diagnostics,
        )

        input_contract = planet.get("world_gen_input_contract") or self._replay_contract or {}
        input_contract_path = self.output_root / "input_contract.json"
        input_contract_path.write_text(
            json.dumps(input_contract, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

        planet_path = self.output_root / "planet.json"
        planet_path.write_text(
            json.dumps(planet, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        summary_path = self.output_root / "summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

        if config.finish_worldgen and not sim._finish_world_gen():
            raise RuntimeError(sim.commit_status)

        result = HeadlessWorldGenResult(
            output_root=str(self.output_root),
            repository_root=str(self.repository_root),
            planet_id=str(planet.get("id")),
            stage_history=stage_history,
            stage_screenshots=stage_screenshots,
            layer_images=[{"label": item["label"], "path": item["path"]} for item in layers],
            contact_sheet=contact_sheet,
            summary_path=str(summary_path),
            planet_path=str(planet_path),
            runtime_classes={
                "simulation": f"{sim.__class__.__module__}.{sim.__class__.__name__}",
                "renderer": "simulations.world_gen.world_gen_renderer.WorldGenRenderer",
                "world_model": f"{world.__class__.__module__}.{world.__class__.__name__}",
            },
            regional_refinement_ids=regional_refinement_ids,
            regional_refinement_manifest=regional_refinement_manifest,
            regional_materials_path=regional_materials_path,
            regional_region_path=regional_region_path,
            regional_layer_images=[{"label": item["label"], "path": item["path"]} for item in regional_layers],
            regional_contact_sheet=regional_contact_sheet,
            regional_level_diagnostics=regional_level_diagnostics,
            regional_lod_overview=regional_lod_overview,
            regional_level_snapshot_paths=regional_level_snapshot_paths,
            input_contract_path=str(input_contract_path),
        )
        result_path = self.output_root / "result.json"
        result_path.write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result


def run_isolated_headless_worldgen(config=None, *, bundle_path=None, retention="temporary", include_images=False, project_root=None):
    """Run in disposable storage and optionally publish one validated bundle."""
    from simulations.world_gen.storage_policy import (
        RETENTION_PINNED,
        RETENTION_RETAINED,
        WorldGenStoragePolicy,
    )
    from simulations.world_gen.worldgen_bundle import write_worldgen_bundle

    config = config or HeadlessWorldGenConfig()
    policy = WorldGenStoragePolicy.for_project(project_root)
    run_root = policy.temporary_run_directory(prefix=config.map_seed or "run")
    try:
        result = HeadlessWorldGenRunner(run_root).run(config)
        summary = json.loads(Path(result.summary_path).read_text(encoding="utf-8"))
        destination = ""
        if retention in {RETENTION_RETAINED, RETENTION_PINNED}:
            destination_path = Path(bundle_path).resolve() if bundle_path else policy.retained_bundle(
                f"{result.planet_id}-{config.map_seed}",
                pinned=retention == RETENTION_PINNED,
            )
            destination = str(write_worldgen_bundle(
                destination_path,
                result=result,
                retention=retention,
                include_images=include_images,
            ))
        return IsolatedHeadlessWorldGenResult(
            retention=retention,
            planet_id=result.planet_id,
            summary=summary,
            stage_fingerprints=list((summary.get("parity") or {}).get("stage_fingerprints") or []),
            bundle_path=destination,
        )
    finally:
        policy.remove_temporary_tree(run_root)
