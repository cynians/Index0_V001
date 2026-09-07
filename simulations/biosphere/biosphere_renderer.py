"""Render SpeciesSim plant snapshots as grounded sprites on a BioSim map."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer, diagnostic_cell_bounds
from simulations.species.species_simulation import SpeciesSimulation


class BiosphereBuilderRenderer:
    """Isometric scene adapter for continuous ecology and SpeciesSim plants."""

    def __init__(self, app_view, species_renderer=None):
        self.app_view = app_view
        self.species_renderer = species_renderer or SpeciesRenderer(app_view)
        self._simulation_cache = {}
        self._surface_cache = {}

    def _species_case(self, biosphere_sim, instance):
        representative_id = instance.get("representative_id")
        if representative_id:
            representative_case = getattr(
                biosphere_sim,
                "get_representative_species_simulation",
                lambda _representative_id: None,
            )(representative_id)
            if representative_case is not None:
                return representative_case
        species_id = instance["species_id"]
        age_bucket = int(instance.get("age_bucket", 1))
        variant = int(instance.get("variant", 0))
        entity = biosphere_sim.world_model.get_entity(species_id) or {"id": species_id, "type": "species"}
        revision = getattr(biosphere_sim.world_model, "repository_revision", 0)
        key = species_id, age_bucket, variant, revision
        cached = self._simulation_cache.get(key)
        if cached is not None:
            return cached
        case = SpeciesSimulation(
            world_model=biosphere_sim.world_model,
            species_id=species_id,
            species_entity=entity,
            seed=1709 + variant * 101,
        )
        case.lod = 1
        maturity = (0.18, 0.38, 0.62, 0.88)[max(0, min(3, age_bucket))]
        case.set_age(case.mature_age_days * maturity)
        self._simulation_cache[key] = case
        if len(self._simulation_cache) > 96:
            self._simulation_cache.pop(next(iter(self._simulation_cache)))
        return case

    @staticmethod
    def _target_height_px(case, instance, camera, world_units_to_meters):
        above_ground_m = max(0.08, float(case.render_snapshot.bounds_m[5] or 0.0))
        pixels_per_metre = float(getattr(camera, "zoom", 1.0) or 1.0) / max(1e-9, float(world_units_to_meters or 1.0))
        physical_height = above_ground_m * pixels_per_metre
        form = str(instance.get("growth_form") or "forb")
        semantic_floor = {"tree": 30, "shrub": 24, "graminoid": 18, "forb": 20, "aquatic": 22, "succulent": 22}.get(form, 20)
        abundance = max(0.0, min(1.0, float(instance.get("abundance", 0.0) or 0.0)))
        height_cap = max(84, int(getattr(camera, "sprite_height_cap", 84) or 84))
        return max(semantic_floor, min(height_cap, round(max(physical_height, semantic_floor) * (0.72 + abundance * 0.38))))

    def _sprite_surface(self, biosphere_sim, instance, camera):
        case = self._species_case(biosphere_sim, instance)
        target_height = self._target_height_px(case, instance, camera, biosphere_sim.world_units_to_meters)
        bounds = diagnostic_cell_bounds(case.render_snapshot)
        model_width = max(0.08, bounds[1] - bounds[0])
        model_height = max(0.08, bounds[3] - bounds[2])
        target_width = max(10, min(96, round(target_height * model_width / model_height)))
        cache_key = (
            instance["species_id"], instance.get("age_bucket"), instance.get("variant"),
            target_width, target_height, case.blueprint.fingerprint(),
            round(float(case.render_snapshot.age_days), 3),
        )
        cached = self._surface_cache.get(cache_key)
        if cached is not None:
            return cached

        panel = pygame.Surface((target_width + 12, target_height + 12), pygame.SRCALPHA)
        sprite_camera = DiagnosticCamera(panel.get_width(), panel.get_height(), bounds)
        sprite_camera.scale = min(
            target_width / model_width,
            target_height / model_height,
        )
        root_x, root_y = sprite_camera.world_to_screen((0.0, 0.0))
        sprite_camera.bottom += panel.get_height() - 5 - root_y
        self.species_renderer._draw_individual(
            panel,
            case,
            camera=sprite_camera,
            clear=False,
            cache=True,
            draw_ground_line=False,
            foliage_sample_cap=3,
        )
        root_x, root_y = sprite_camera.world_to_screen((0.0, 0.0))
        if root_y + 1 < panel.get_height():
            panel.fill((0, 0, 0, 0), (0, root_y + 1, panel.get_width(), panel.get_height() - root_y - 1))
        bounds_rect = panel.get_bounding_rect(min_alpha=1)
        if bounds_rect.width > 0 and bounds_rect.height > 0:
            cropped = panel.subsurface(bounds_rect).copy()
            anchor = (root_x - bounds_rect.x, root_y - bounds_rect.y)
        else:
            cropped = panel
            anchor = (panel.get_width() * 0.5, panel.get_height() - 1)
        result = cropped, anchor
        self._surface_cache[cache_key] = result
        if len(self._surface_cache) > 128:
            self._surface_cache.pop(next(iter(self._surface_cache)))
        return result

    @staticmethod
    def _projection(screen, biosphere_sim):
        bounds = biosphere_sim.bounds
        width = max(0.1, bounds["max_x"] - bounds["min_x"])
        height = max(0.1, bounds["max_y"] - bounds["min_y"])
        if getattr(biosphere_sim, "isometric_fullscreen_preview", False):
            scene = pygame.Rect(22, 22, screen.get_width() - 44, screen.get_height() - 44)
        else:
            left_margin = min(318, max(228, round(screen.get_width() * 0.245)))
            scene = pygame.Rect(left_margin, 104, max(120, screen.get_width() - left_margin - 18), max(120, screen.get_height() - 222))
        scale = min(scene.width / (width + height + 1.0), scene.height / ((width + height) * 0.5 + 2.0))
        scale = max(8.0, scale) * max(0.25, float(getattr(biosphere_sim, "isometric_view_zoom", 1.0) or 1.0))
        view_center = getattr(biosphere_sim, "isometric_view_center", None)
        center_x = float(view_center[0]) if isinstance(view_center, (tuple, list)) and len(view_center) >= 2 else (bounds["min_x"] + bounds["max_x"]) * 0.5
        center_y = float(view_center[1]) if isinstance(view_center, (tuple, list)) and len(view_center) >= 2 else (bounds["min_y"] + bounds["max_y"]) * 0.5
        state = {
            "scale": scale,
            "center_x": center_x,
            "center_y": center_y,
            "origin_x": float(scene.centerx),
            "origin_y": float(scene.centery + scene.height * 0.08),
            "scene_rect": scene,
        }
        biosphere_sim._isometric_projection_state = state
        return state

    @staticmethod
    def _iso(state, x, y):
        dx = float(x) - state["center_x"]
        dy = float(y) - state["center_y"]
        return (
            state["origin_x"] + (dx - dy) * state["scale"],
            state["origin_y"] + (dx + dy) * state["scale"] * 0.5,
        )

    def _draw_ground(self, screen, biosphere_sim, state):
        screen.fill((15, 20, 18))
        bounds = biosphere_sim.bounds
        corners = [
            self._iso(state, bounds["min_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["max_y"]),
            self._iso(state, bounds["min_x"], bounds["max_y"]),
        ]
        lower = [(x, y + 13) for x, y in corners]
        pygame.draw.polygon(screen, (32, 38, 30), [corners[0], corners[1], lower[1], lower[0]])
        pygame.draw.polygon(screen, (25, 31, 26), [corners[1], corners[2], lower[2], lower[1]])
        pygame.draw.polygon(screen, (67, 75, 57), corners)

        # Broad continuous habitat bands make moisture legible without cells.
        band = []
        for index in range(25):
            ny = index / 24.0
            x = bounds["min_x"] + (0.23 + 0.18 * ny) * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + ny * (bounds["max_y"] - bounds["min_y"])
            band.append(self._iso(state, x, y))
        if len(band) > 1:
            pygame.draw.lines(screen, (77, 105, 88), False, band, max(2, round(state["scale"] * 0.10)))
            pygame.draw.lines(screen, (93, 121, 101), False, band, 1)

        # Sparse world-coordinate flecks provide scale without introducing a grid.
        for index in range(58):
            fx = ((index * 0.61803398875 + 0.17) % 1.0)
            fy = ((index * 0.41421356237 + 0.31) % 1.0)
            x = bounds["min_x"] + fx * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + fy * (bounds["max_y"] - bounds["min_y"])
            sx, sy = self._iso(state, x, y)
            color = (89, 94, 69) if index % 3 else (57, 68, 53)
            pygame.draw.circle(screen, color, (round(sx), round(sy)), 1)
        pygame.draw.polygon(screen, (112, 122, 91), corners, 2)

    def _draw_population_patches(self, screen, biosphere_sim, state):
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        patches = sorted(biosphere_sim.ecology.population_footprints(), key=lambda item: item["x"] + item["y"])
        for patch in patches:
            points = []
            for index in range(24):
                angle = math.tau * index / 24.0
                wobble = 1.0 + 0.08 * math.sin(index * 2.17 + len(patch["patch_id"]))
                points.append(self._iso(
                    state,
                    patch["x"] + math.cos(angle) * patch["radius_m"] * wobble,
                    patch["y"] + math.sin(angle) * patch["radius_m"] * wobble,
                ))
            abundance = max(0.0, min(1.0, patch["abundance"]))
            color = patch["color"]
            pygame.draw.polygon(overlay, (*color, round(40 + abundance * 78)), points)
            pygame.draw.lines(overlay, (*tuple(min(255, channel + 30) for channel in color), 120), True, points, 1)
        screen.blit(overlay, (0, 0))

    def draw(self, screen, biosphere_sim):
        if getattr(biosphere_sim, "simulation_mode", None) != "biosphere_builder":
            return
        state = self._projection(screen, biosphere_sim)
        self._draw_ground(screen, biosphere_sim, state)
        self._draw_population_patches(screen, biosphere_sim, state)
        sprite_camera = SimpleNamespace(
            zoom=state["scale"],
            sprite_height_cap=getattr(biosphere_sim, "isometric_sprite_height_cap", 84),
        )
        instances = list(getattr(biosphere_sim, "get_species_sprite_instances", lambda: [])() or [])
        instances.sort(key=lambda item: (item["x"] + item["y"], item["y"], item["x"]))
        hitboxes = []
        for instance in instances:
            anchor_screen = self._iso(state, instance["x"], instance["y"])
            sprite, root_anchor = self._sprite_surface(biosphere_sim, instance, sprite_camera)
            x = round(anchor_screen[0] - root_anchor[0])
            y = round(anchor_screen[1] - root_anchor[1])
            if x > screen.get_width() or y > screen.get_height() or x + sprite.get_width() < 0 or y + sprite.get_height() < 0:
                continue
            abundance = max(0.0, min(1.0, float(instance.get("abundance", 0.0) or 0.0)))
            shadow_w = max(5, round(sprite.get_width() * (0.34 + abundance * 0.18)))
            pygame.draw.ellipse(
                screen,
                (31, 38, 27),
                (round(anchor_screen[0] - shadow_w / 2), round(anchor_screen[1] - 2), shadow_w, 5),
            )
            screen.blit(sprite, (x, y))
            sprite_rect = pygame.Rect(x, y, sprite.get_width(), sprite.get_height())
            representative_id = instance.get("representative_id")
            if representative_id:
                hitboxes.append((representative_id, sprite_rect.inflate(8, 8)))
            if instance.get("selected"):
                pygame.draw.rect(screen, (255, 224, 112), sprite_rect.inflate(6, 6), 2, border_radius=4)
        biosphere_sim._representative_screen_hitboxes = hitboxes
