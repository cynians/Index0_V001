"""Headless driver for the production world-generation route.

This module does not reimplement planet generation.  It creates an isolated
WorldModel, instantiates the real WorldGenSimulation, invokes the same stage
actions used by the UI, and renders with the real WorldGenRenderer onto
off-screen Pygame surfaces.
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
from simulations.world_gen.material_heatmaps import load_raster_bundle_surface
from simulations.world_gen.regional_refinement import generate_refined_region
from simulations.world_gen.world_gen_renderer import WorldGenRenderer
from simulations.world_gen.world_gen_sim import WorldGenSimulation
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
    render_outputs: bool = True
    trace_elements: list = field(default_factory=list)
    replay_contract_path: str = ""
    replay_contract: dict = None
    attach_moon: bool = False
    moon_semi_major_axis_km: float = 384_400.0
    moon_radius_earth: float = 0.27


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
    regional_materials_path: str
    regional_region_path: str
    regional_layer_images: list
    regional_contact_sheet: str
    input_contract_path: str


@dataclass
class IsolatedHeadlessWorldGenResult:
    retention: str
    planet_id: str
    summary: dict
    stage_fingerprints: list
    bundle_path: str = ""


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
        tectonic_segments = [
            segment
            for segment in ((entity.get("tectonic_model") or {}).get("boundary_segments") or [])
            if str(segment.get("kind") or "") in {"collision", "subduction"}
        ]
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
            score = local_relief / span * 0.64 + prominence / span * 0.16 + altitude / span * 0.14 + tectonic_bonus
            if score > best[0]:
                best = (score, x, y)
        return best[1] / max(1, width - 1), best[2] / max(1, height - 1)

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
        world = WorldModel(entries_directory=self.entries_root, use_ontology=False)
        sim = WorldGenSimulation(
            world_model=world,
            parent_system_id=self.system_id,
            year=int((self._replay_contract or {}).get("registry_year") or 2400),
        )
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
            sim.randomize_seed(
                mode=config.randomize_mode,
                rng=random.Random(config.randomizer_seed),
            )
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

    def _render_material_layer(self, planet, size):
        model = planet.get("material_heatmap_model") or {}
        composite = model.get("composite_layer") or {}
        path = Path(composite.get("bundle_path") or "")
        if path and not path.is_absolute():
            path = self.repository_root / path
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
            action_timings.append({
                "action": getattr(action, "__name__", action.__class__.__name__),
                "expected_stage": expected_stage,
                "seconds": round(time.perf_counter() - started_at, 6),
            })
            if not succeeded:
                raise RuntimeError(sim.commit_status)
            if sim.editor_stage != expected_stage:
                raise RuntimeError(f"Expected stage {expected_stage}, got {sim.editor_stage}: {sim.commit_status}")

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
        refinement_parent = planet
        refinement_depth = (
            0
            if gas_giant_terminal
            else max(0, int(config.regional_refinement_depth or 0))
        )
        for refinement_index in range(refinement_depth):
            parent_bounds = refinement_parent.get("bounds") or {}
            if parent_bounds.get("type") != "bbox":
                break
            width = float(parent_bounds["max_x"]) - float(parent_bounds["min_x"])
            height = float(parent_bounds["max_y"]) - float(parent_bounds["min_y"])
            if str(config.regional_target_mode or "manual") == "mountain":
                center_x_fraction, center_y_fraction = self._mountain_center_fraction(refinement_parent)
                center_x_fraction = max(0.2, min(0.8, center_x_fraction))
                center_y_fraction = max(0.2, min(0.8, center_y_fraction))
            else:
                center_x_fraction = (
                    max(0.2, min(0.8, float(config.regional_center_x)))
                    if refinement_index == 0 else 0.5
                )
                center_y_fraction = (
                    max(0.2, min(0.8, float(config.regional_center_y)))
                    if refinement_index == 0 else 0.5
                )
            center_x = float(parent_bounds["min_x"]) + width * center_x_fraction
            center_y = float(parent_bounds["min_y"]) + height * center_y_fraction
            bounds = {
                "min_x": center_x - width * 0.20,
                "max_x": center_x + width * 0.20,
                "min_y": center_y - height * 0.20,
                "max_y": center_y + height * 0.20,
            }
            refinement_parent = generate_refined_region(
                world,
                refinement_parent,
                bounds,
                seed_suffix="headless-regional-material-validation",
            )
            regional_refinement_ids.append(str(refinement_parent.get("id")))
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
                regional_layers = self._render_layers(
                    refinement_parent,
                    config,
                    prefix=f"regional_lod_{refinement_parent.get('map_detail_level', 1)}",
                )
                regional_contact_sheet = self._build_contact_sheet(
                    regional_layers,
                    config,
                    filename="regional_map_layers_contact_sheet.png",
                )
        summary = self._summary(planet, config, stage_history)
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
            regional_materials_path=regional_materials_path,
            regional_region_path=regional_region_path,
            regional_layer_images=[{"label": item["label"], "path": item["path"]} for item in regional_layers],
            regional_contact_sheet=regional_contact_sheet,
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
