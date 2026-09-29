"""Render SpeciesSim plant snapshots as grounded sprites on a BioSim map."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer, diagnostic_cell_bounds
from simulations.species.species_simulation import SpeciesSimulation
from simulations.biosphere.vegetation import VegetationSampler


class BiosphereBuilderRenderer:
    """Isometric scene adapter for continuous ecology and SpeciesSim plants."""

    def __init__(self, app_view, species_renderer=None):
        self.app_view = app_view
        self.species_renderer = species_renderer or SpeciesRenderer(app_view)
        self._simulation_cache = {}
        self._surface_cache = {}
        self._frame_surfaces = {}
        self._frame_surface_context = None
        self._vegetation_sampler = VegetationSampler()
        self._terrain_surface_cache = {}

    def _species_case(self, biosphere_sim, instance):
        representative_id = instance.get("representative_id")
        if "display_maturity" not in instance:
            representative_id = representative_id or instance.get("visual_source_id")
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
        display_maturity = instance.get("display_maturity")
        key = id(biosphere_sim.world_model), species_id, age_bucket, variant, revision, display_maturity
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
        maturity = display_maturity if display_maturity is not None else (0.18, 0.38, 0.62, 0.88)[max(0, min(3, age_bucket))]
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
        abundance = round(max(0.0, min(1.0, float(instance.get("abundance", 0.0) or 0.0))) * 5) / 5
        height_cap = max(84, int(getattr(camera, "sprite_height_cap", 84) or 84))
        if "display_maturity" in instance:
            # Tall species hit the map height cap even while young; retain a
            # visible stage difference instead of making every crown equally tall.
            stage = max(0.0, min(1.0, instance["display_maturity"]))
            height_cap = max(6, round(height_cap * stage ** 0.65))
            semantic_floor = min(semantic_floor, height_cap)
        height = max(semantic_floor, min(height_cap, round(max(physical_height, semantic_floor) * (0.72 + abundance * 0.38))))
        return max(5 if "display_maturity" in instance else 8, round(height * instance.get("visual_scale", 1.0)))

    def _sprite_surface(self, biosphere_sim, instance, camera):
        frame_key = (instance["species_id"], instance.get("representative_id") or instance.get("visual_source_id"),
                     instance.get("age_bucket"), instance.get("variant"), instance.get("visual_scale", 1.0),
                     round(float(instance.get("abundance", 0.0)) * 5), instance.get("display_maturity"))
        frame_cached = getattr(self, "_frame_surfaces", {}).get(frame_key)
        if frame_cached is not None:
            return frame_cached
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
            case.seed, getattr(biosphere_sim.world_model, "repository_revision", 0),
        )
        cached = self._surface_cache.get(cache_key)
        if cached is not None:
            self._frame_surfaces[frame_key] = cached
            if len(self._frame_surfaces) > 1024:
                self._frame_surfaces.pop(next(iter(self._frame_surfaces)))
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
        self._frame_surfaces[frame_key] = result
        if len(self._frame_surfaces) > 1024:
            self._frame_surfaces.pop(next(iter(self._frame_surfaces)))
        if len(self._surface_cache) > 128:
            self._surface_cache.pop(next(iter(self._surface_cache)))
        return result

    @staticmethod
    def _draw_groundcover(screen, instance, anchor_screen, scale, color):
        """Map-scale grass/lichen symbols; individual organ models remain in SpeciesSim."""
        sx, sy = map(round, anchor_screen)
        stage = max(0.0, min(1.0, instance.get("display_maturity", .88)))
        size = max(1, min(13, round(scale * 0.16 * max(.10, stage) ** .65 * instance.get("visual_scale", 1.0))))
        shade = tuple(max(0, round(c * 0.48)) for c in color)
        pygame.draw.ellipse(screen, shade, (sx - size, sy - size // 3, size * 2, max(2, size)))
        if instance.get("growth_form") == "lichen":
            pygame.draw.ellipse(screen, color, (sx - size, sy - size // 2, size * 2, max(2, size)))
        else:
            blades = 2 if stage < .2 else 3 if stage < .45 else 5 if stage < .7 else 7
            for index in range(blades):
                offset = index - (blades-1)/2
                tip = (sx + round(offset * size * 0.65), sy - size - (index % 2) * size // 2)
                blade_color = tuple(min(255, round(c * (0.70 + index * 0.25 / max(1, blades-1)))) for c in color)
                pygame.draw.line(screen, blade_color, (sx + offset, sy), tip, max(1, size // 3))
        return pygame.Rect(sx - size, sy - size * 2, size * 2, size * 3)

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
        scale = max(0.05, scale) * max(0.25, float(getattr(biosphere_sim, "isometric_view_zoom", 1.0) or 1.0))
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
            "substrate": getattr(biosphere_sim, "substrate", None),
        }
        biosphere_sim._isometric_projection_state = state
        return state

    @staticmethod
    def _iso(state, x, y):
        dx = float(x) - state["center_x"]
        dy = float(y) - state["center_y"]
        substrate = state.get("substrate")
        z = substrate.elevation(x, y, True) if substrate is not None else 0.0
        return (
            state["origin_x"] + (dx - dy) * state["scale"],
            state["origin_y"] + (dx + dy) * state["scale"] * 0.5 - z * state["scale"],
        )

    def _draw_imported_ground(self, screen, substrate, state):
        key = (substrate.fingerprint, screen.get_size(), tuple(state[k] for k in
               ("scale", "center_x", "center_y", "origin_x", "origin_y")))
        surface = self._terrain_surface_cache.get(key)
        if surface is None:
            surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            b = dict(substrate.bounds)
            grid = substrate.heightmap["sample_grid"]
            # Tessellate the visible window, not all 36km² when zoomed to a river bank.
            if substrate.native is not None:
                rect, scale = state["scene_rect"], state["scale"]
                lo,hi=substrate.heightmap["min_elevation_m"],substrate.heightmap["max_elevation_m"]
                corners=[]
                for sx,sy in (rect.topleft,rect.topright,rect.bottomleft,rect.bottomright):
                    a=(sx-state["origin_x"])/scale
                    c=(sy-state["origin_y"])/(scale*.5)
                    corners.append((state["center_x"]+(a+c)*.5,state["center_y"]+(c-a)*.5))
                b.update(min_x=max(b["min_x"],min(p[0] for p in corners)+lo-2),
                         max_x=min(b["max_x"],max(p[0] for p in corners)+hi+2),
                         min_y=max(b["min_y"],min(p[1] for p in corners)+lo-2),
                         max_y=min(b["max_y"],max(p[1] for p in corners)+hi+2))
                if b["max_x"]<=b["min_x"] or b["max_y"]<=b["min_y"]:
                    return
            step=max(1.,3./state["scale"]) if substrate.native is not None else 0.
            nx,ny=(max(1,min(400,math.ceil((b["max_x"]-b["min_x"])/step))),
                   max(1,min(400,math.ceil((b["max_y"]-b["min_y"])/step)))) if step else (min(200,grid["width"]-1),min(200,grid["height"]-1))
            dx, dy = (b["max_x"]-b["min_x"])/nx, (b["max_y"]-b["min_y"])/ny
            points = [[self._iso(state, b["min_x"]+i*dx, b["min_y"]+j*dy)
                       for i in range(nx+1)] for j in range(ny+1)]
            for _, j, i in sorted((i+j, j, i) for j in range(ny) for i in range(nx)):
                x, y = b["min_x"]+(i+.5)*dx, b["min_y"]+(j+.5)*dy
                wet = substrate.open_water_at(x,y)
                color = substrate.sample("abiotic_rgb", x, y, (115, 105, 81))
                if wet:
                    shade = .99 + .01 * math.sin(x * .8 + y * 3)
                    if substrate.fields.get("abiotic_rgb") is None:
                        color = (57, 109, 121)
                else:
                    sx = (substrate.elevation(x+dx*.5, y)-substrate.elevation(x-dx*.5, y))/dx
                    sy = (substrate.elevation(x, y+dy*.5)-substrate.elevation(x, y-dy*.5))/dy
                    shade = max(.55, min(1.2, (1 + .45*sx - .55*sy) / math.sqrt(1+sx*sx+sy*sy)))
                rgb = tuple(max(0, min(255, round(c*shade))) for c in color)
                pygame.draw.polygon(surface, rgb, [points[j][i], points[j][i+1], points[j+1][i+1], points[j+1][i]])
            if len(self._terrain_surface_cache) >= 4:
                self._terrain_surface_cache.pop(next(iter(self._terrain_surface_cache)))
            self._terrain_surface_cache[key] = surface
        screen.blit(surface, (0, 0))

    def _draw_ground(self, screen, biosphere_sim, state):
        screen.fill((15, 20, 18))
        if getattr(biosphere_sim, "substrate", None) is not None:
            self._draw_imported_ground(screen, biosphere_sim.substrate, state)
            return
        bounds = biosphere_sim.bounds
        corners = [
            self._iso(state, bounds["min_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["max_y"]),
            self._iso(state, bounds["min_x"], bounds["max_y"]),
        ]
        lower = [(x, y + 13) for x, y in corners]
        pygame.draw.polygon(screen, (49, 41, 31), [corners[0], corners[1], lower[1], lower[0]])
        pygame.draw.polygon(screen, (39, 34, 28), [corners[1], corners[2], lower[2], lower[1]])
        pygame.draw.polygon(screen, (103, 91, 68), corners)

        # Broad continuous habitat bands make moisture legible without cells.
        band = []
        for index in range(25):
            ny = index / 24.0
            x = bounds["min_x"] + (0.23 + 0.18 * ny) * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + ny * (bounds["max_y"] - bounds["min_y"])
            band.append(self._iso(state, x, y))
        if len(band) > 1:
            pygame.draw.lines(screen, (77, 103, 96), False, band, max(2, round(state["scale"] * 0.10)))
            pygame.draw.lines(screen, (103, 126, 113), False, band, 1)

        # Sparse world-coordinate flecks provide scale without introducing a grid.
        for index in range(58):
            fx = ((index * 0.61803398875 + 0.17) % 1.0)
            fy = ((index * 0.41421356237 + 0.31) % 1.0)
            x = bounds["min_x"] + fx * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + fy * (bounds["max_y"] - bounds["min_y"])
            sx, sy = self._iso(state, x, y)
            color = (126, 111, 82) if index % 3 else (78, 70, 57)
            pygame.draw.circle(screen, color, (round(sx), round(sy)), 1)
        pygame.draw.polygon(screen, (149, 132, 91), corners, 2)

    def _draw_organic_soil(self, screen, biosphere_sim, state):
        """Tint soil state without changing the authoritative mineral ground."""
        soil = getattr(biosphere_sim, "soil", None)
        mode = getattr(biosphere_sim, "soil_diagnostic_mode", "organic")
        if soil is None or (mode == "organic" and soil.summary()["max_soil_organic_matter_kg_m2"] <= 0.0001):
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        for row in range(soil.rows):
            for column in range(soil.columns):
                organic = soil.organic_matter_rows[row][column]
                litter = soil.litter_rows[row][column]
                if mode == "nitrogen":
                    value = soil.available_nitrogen_rows[row][column]
                    strength = max(0.0, min(1.0, value / 0.35))
                    color = (44, round(80 + strength * 95), 112, round(38 + strength * 145))
                elif mode == "phosphorus":
                    value = soil.available_phosphorus_rows[row][column]
                    strength = max(0.0, min(1.0, value / 0.12))
                    color = (round(105 + strength * 115), 72, round(120 + strength * 90), round(38 + strength * 145))
                else:
                    strength = max(0.0, min(1.0, (organic + litter * 0.22) / 0.45))
                    mature = max(0.0, min(1.0, organic / 0.30))
                    color = (
                        round(77 - mature * 22),
                        round(61 + mature * 20),
                        round(42 + mature * 4),
                        round(35 + strength * 112),
                    )
                if strength <= 0.002:
                    continue
                x0, x1, y0, y1 = soil.cell_bounds(column, row)
                points = [
                    self._iso(state, x0, y0), self._iso(state, x1, y0),
                    self._iso(state, x1, y1), self._iso(state, x0, y1),
                ]
                pygame.draw.polygon(overlay, color, points)
        screen.blit(overlay, (0, 0))

    def _draw_population_patches(self, screen, biosphere_sim, state):
        if getattr(biosphere_sim, "substrate", None) is not None and not getattr(biosphere_sim, "show_population_footprints", False):
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        patches = sorted(biosphere_sim.ecology.population_footprints(), key=lambda item: item["x"] + item["y"])
        for patch in patches:
            points = []
            for index in range(24):
                angle = math.tau * index / 24.0
                wobble = 1.0 + 0.08 * math.sin(index * 2.17 + len(patch["patch_id"]))
                points.append(self._iso(
                    state,
                    max(biosphere_sim.bounds["min_x"], min(biosphere_sim.bounds["max_x"], patch["x"] + math.cos(angle) * patch["radius_m"] * wobble)),
                    max(biosphere_sim.bounds["min_y"], min(biosphere_sim.bounds["max_y"], patch["y"] + math.sin(angle) * patch["radius_m"] * wobble)),
                ))
            abundance = max(0.0, min(1.0, patch["abundance"]))
            color = patch["color"]
            pygame.draw.polygon(overlay, (*color, round(40 + abundance * 78)), points)
        screen.blit(overlay, (0, 0))

    def draw(self, screen, biosphere_sim):
        if getattr(biosphere_sim, "simulation_mode", None) != "biosphere_builder":
            return
        state = self._projection(screen, biosphere_sim)
        # Reuse unchanged scene sprites across frames, not only within one frame.
        # Deep representative snapshots/repository revision invalidate real growth.
        representatives = getattr(biosphere_sim, "representatives", None)
        rep_key = tuple((r.representative_id, id(r.simulation.render_snapshot), r.simulation.seed)
                        for r in representatives.items(alive_only=True)) if representatives is not None else ()
        context = (id(biosphere_sim.world_model), getattr(biosphere_sim.world_model, "repository_revision", 0),
                   state["scale"], getattr(biosphere_sim, "isometric_sprite_height_cap", 84),
                   biosphere_sim.world_units_to_meters, rep_key)
        if context != self._frame_surface_context:
            self._frame_surfaces = {}
            self._frame_surface_context = context
        self._draw_ground(screen, biosphere_sim, state)
        self._draw_organic_soil(screen, biosphere_sim, state)
        show_vegetation = bool(getattr(biosphere_sim, "show_vegetation", True))
        if show_vegetation:
            self._draw_population_patches(screen, biosphere_sim, state)
        sprite_camera = SimpleNamespace(
            zoom=state["scale"],
            sprite_height_cap=getattr(biosphere_sim, "isometric_sprite_height_cap", 84),
        )
        instances = list(getattr(biosphere_sim, "get_species_sprite_instances", lambda: [])() or []) if show_vegetation else []
        vegetation = self._vegetation_sampler.sample(biosphere_sim.ecology, instances) if show_vegetation else []
        biosphere_sim._vegetation_render_count = len(vegetation)
        instances.extend(vegetation)
        instances.sort(key=lambda item: (item["x"] + item["y"], item["y"], item["x"]))
        hitboxes = []
        for instance in instances:
            anchor_screen = self._iso(state, instance["x"], instance["y"])
            if instance.get("growth_form") in {"graminoid", "lichen"}:
                if not screen.get_rect().inflate(30, 30).collidepoint(anchor_screen):
                    continue
                rect = self._draw_groundcover(screen, instance, anchor_screen, state["scale"],
                                              biosphere_sim.ecology.profiles[instance["species_id"]].color)
                if instance.get("representative_id"):
                    hitboxes.append((instance["representative_id"], rect.inflate(8, 8)))
                if instance.get("selected"):
                    pygame.draw.rect(screen, (255, 224, 112), rect.inflate(6, 6), 2)
                continue
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
