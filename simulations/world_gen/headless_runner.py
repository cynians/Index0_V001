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
    render_outputs: bool = True
    trace_elements: list = field(default_factory=list)
    replay_contract_path: str = ""
    replay_contract: dict = None


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
            self._save_layer("Elevation", self._render_height_layer(planet, size, include_materials=False), prefix),
            self._save_layer("Surface Materials", self._render_material_layer(planet, size), prefix),
            self._save_layer("Climate and Rivers", self._render_climate_layer(planet, size), prefix),
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
        }

    def run(self, config=None):
        config = config or HeadlessWorldGenConfig()
        if config.render_outputs:
            self._initialize_rendering(config)
        world, sim = self._new_runtime(config)
        stage_history = []
        stage_fingerprints = []
        stage_screenshots = []

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
            if not action():
                raise RuntimeError(sim.commit_status)
            if sim.editor_stage != expected_stage:
                raise RuntimeError(f"Expected stage {expected_stage}, got {sim.editor_stage}: {sim.commit_status}")

        capture("crust")
        advance(sim._save_selected_planet_seed, "atmosphere")
        capture("atmosphere")
        if not sim._save_atmosphere_model():
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
