import math

import pygame

from simulations.world_gen.heightmap import (
    contour_levels_for_heightmap,
    display_contour_interval_m,
    height_marker_interval_m,
)


class WorldGenRenderer:
    """
    Renderer for the empty-start planetary world generation workspace.
    """

    AU_M = 149_597_870_700.0

    def __init__(self, app_view):
        self.app_view = app_view

    def _coerce_rgb(self, value, fallback=(122, 176, 232)):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(value[index]))) for index in range(3))
            except (TypeError, ValueError):
                return fallback
        return fallback

    def _mix_rgb(self, color_a, color_b, weight_b):
        weight_b = max(0.0, min(1.0, float(weight_b or 0.0)))
        weight_a = 1.0 - weight_b
        return tuple(
            max(0, min(255, int(color_a[index] * weight_a + color_b[index] * weight_b)))
            for index in range(3)
        )

    def _surface_palette_colors(self, entity=None, material_model=None):
        if isinstance(material_model, dict):
            palette = material_model.get("surface_palette")
        else:
            palette = None
        if not isinstance(palette, dict) and isinstance(entity, dict):
            palette = entity.get("surface_palette")
        if not isinstance(palette, dict):
            palette = {}

        palette_colors = palette.get("palette") if isinstance(palette.get("palette"), list) else []
        colors = [self._coerce_rgb(color, fallback=(80, 78, 72)) for color in palette_colors[:4]]
        if len(colors) >= 4:
            return colors

        fallback_source = palette.get("surface_color") if palette else None
        if fallback_source is None and isinstance(entity, dict):
            fallback_source = entity.get("display_color")
        base = self._coerce_rgb(fallback_source, fallback=(82, 78, 70))
        return [
            self._mix_rgb(base, (12, 14, 14), 0.36),
            base,
            self._mix_rgb(base, (218, 214, 198), 0.34),
            self._mix_rgb(base, (46, 48, 44), 0.18),
        ]

    def _world_point_for_au(self, au_x, au_y):
        return au_x * self.AU_M, au_y * self.AU_M

    def _screen_points_for_orbit(self, camera, semi_major_au, eccentricity, count=180):
        if semi_major_au is None or eccentricity is None:
            return []

        points = []
        b_au = semi_major_au * math.sqrt(max(0.0, 1.0 - eccentricity * eccentricity))
        for index in range(count):
            angle = (index / count) * math.tau
            x_au = semi_major_au * (math.cos(angle) - eccentricity)
            y_au = b_au * math.sin(angle)
            screen_point = camera.world_to_screen(self._world_point_for_au(x_au, y_au))
            if screen_point is not None:
                points.append((int(screen_point[0]), int(screen_point[1])))
        return points

    def _draw_circle_au(self, screen, camera, radius_au, color, width=1):
        if radius_au is None or radius_au <= 0:
            return

        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        pixel_radius = int(radius_au * self.AU_M * camera.zoom)
        if pixel_radius <= 1:
            return

        pygame.draw.circle(
            screen,
            color,
            (int(center[0]), int(center[1])),
            pixel_radius,
            width,
        )

    def _draw_habitable_zone(self, screen, camera, model):
        inner_au = model.get("habitable_zone_inner_au")
        outer_au = model.get("habitable_zone_outer_au")
        if inner_au is None or outer_au is None or outer_au <= inner_au:
            return

        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        inner_px = int(inner_au * self.AU_M * camera.zoom)
        outer_px = int(outer_au * self.AU_M * camera.zoom)
        if outer_px <= 1:
            return

        zone_bounds = pygame.Rect(
            int(center[0] - outer_px - 3),
            int(center[1] - outer_px - 3),
            outer_px * 2 + 6,
            outer_px * 2 + 6,
        ).clip(screen.get_rect())
        if zone_bounds.width <= 0 or zone_bounds.height <= 0:
            return

        local_center = (
            int(center[0] - zone_bounds.x),
            int(center[1] - zone_bounds.y),
        )
        zone_surface = pygame.Surface(zone_bounds.size, pygame.SRCALPHA)
        pygame.draw.circle(zone_surface, (92, 128, 92, 42), local_center, outer_px)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (0, 0, 0, 0), local_center, inner_px)
        pygame.draw.circle(zone_surface, (150, 196, 138, 130), local_center, outer_px, 2)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (150, 196, 138, 120), local_center, inner_px, 2)
        screen.blit(zone_surface, zone_bounds.topleft)

    def _body_position_screen(self, camera, semi_major_au, eccentricity):
        if semi_major_au is None or eccentricity is None:
            return None
        x_au = semi_major_au * (1.0 - eccentricity)
        return camera.world_to_screen(self._world_point_for_au(x_au, 0.0))

    def _draw_reference_bodies(self, screen, camera, sim, payload):
        bodies = payload.get("system_bodies", [])
        selected_id = payload.get("selected_world_gen_planet_id")
        planet_hitboxes = []

        for body in bodies:
            semi_major_m = body.get("semi_major_axis_m")
            eccentricity = body.get("eccentricity", 0.0)
            if not semi_major_m:
                continue

            try:
                semi_major_au = float(semi_major_m) / self.AU_M
                eccentricity_value = float(eccentricity or 0.0)
            except (TypeError, ValueError):
                continue

            orbit_points = self._screen_points_for_orbit(camera, semi_major_au, eccentricity_value, count=120)
            if len(orbit_points) > 2:
                pygame.draw.lines(screen, (76, 84, 98), True, orbit_points, 1)

            class_key = str(body.get("location_class") or body.get("body_class") or "").lower()
            if class_key != "planet":
                continue

            point = self._body_position_screen(camera, semi_major_au, eccentricity_value)
            if point is None:
                continue

            entity_id = body.get("id")
            selected = entity_id == selected_id
            color = self._coerce_rgb(body.get("display_color"), fallback=(122, 176, 232))
            if selected:
                color = tuple(min(255, int(channel * 1.18 + 28)) for channel in color)
            radius = 5 if not selected else 7
            pygame.draw.circle(screen, color, (int(point[0]), int(point[1])), radius)
            pygame.draw.circle(screen, (214, 236, 255), (int(point[0]), int(point[1])), radius + 2, 1)
            label = self.app_view.default_font.render(body.get("name", entity_id), True, color)
            screen.blit(label, (int(point[0]) + 9, int(point[1]) + 7))
            planet_hitboxes.append((entity_id, pygame.Rect(int(point[0]) - 12, int(point[1]) - 12, 24, 24)))

        sim.set_planet_hitboxes(planet_hitboxes)

    def _draw_star(self, screen, camera, payload):
        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        pygame.draw.circle(screen, (244, 208, 106), (int(center[0]), int(center[1])), 9)
        pygame.draw.circle(screen, (255, 236, 172), (int(center[0]), int(center[1])), 13, 1)
        star = payload.get("star") or {}
        label = star.get("name") or "Primary Star"
        text = self.app_view.default_font.render(label, True, (244, 226, 172))
        screen.blit(text, (int(center[0]) + 14, int(center[1]) - 8))

    def _draw_candidate_orbit(self, screen, camera, model):
        if not model.get("orbit_valid"):
            return

        points = self._screen_points_for_orbit(
            camera,
            model.get("semi_major_axis_au"),
            model.get("eccentricity"),
            count=180,
        )
        if len(points) <= 2:
            return

        pygame.draw.lines(screen, (116, 184, 244), True, points, 2)
        periapsis = points[0]
        pygame.draw.circle(screen, (176, 220, 255), periapsis, 5)
        label = self.app_view.default_font.render("candidate planet", True, (176, 220, 255))
        screen.blit(label, (periapsis[0] + 8, periapsis[1] + 8))

    def _draw_input_panel(self, screen, sim, payload, camera):
        font = self.app_view.default_font
        selected_planet = payload.get("selected_planet")
        if selected_planet:
            if payload.get("editor_stage") == "tectonics":
                self._draw_tectonics_panel(screen, sim, payload)
                return
            if payload.get("editor_stage") == "heightmap":
                self._draw_heightmap_panel(screen, sim, payload, camera)
                return
            if payload.get("editor_stage") == "water_cycle":
                self._draw_water_cycle_panel(screen, sim, payload)
                return
            if payload.get("editor_stage") == "terrain":
                self._draw_terrain_panel(screen, sim, payload)
                return
            if payload.get("editor_stage") == "regime":
                self._draw_regime_panel(screen, sim, payload)
                return
            if payload.get("editor_stage") == "atmosphere":
                self._draw_atmosphere_panel(screen, sim, payload)
                return
            self._draw_crust_composition_panel(screen, sim, payload)
            return

        panel_w = 430
        panel_h = 270
        panel = pygame.Rect(20, screen.get_height() - panel_h - 24, panel_w, panel_h)
        pygame.draw.rect(screen, (22, 25, 34), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        title = font.render("World Generation: Orbit Draft", True, (244, 244, 244))
        screen.blit(title, (panel.x + 12, panel.y + 10))

        field_rects = {}
        y = panel.y + 46
        for field in payload.get("fields", []):
            label = font.render(field["label"], True, (190, 200, 216))
            screen.blit(label, (panel.x + 12, y))
            input_rect = pygame.Rect(panel.x + 216, y - 4, 150, 24)
            field_rects[field["id"]] = input_rect
            fill = (38, 48, 68) if field.get("active") else (30, 34, 44)
            border = (188, 212, 244) if field.get("active") else (92, 102, 122)
            pygame.draw.rect(screen, fill, input_rect)
            pygame.draw.rect(screen, border, input_rect, 1)
            value = field.get("text") or ""
            value_surface = font.render(value or "AU", True, (238, 238, 238) if value else (128, 138, 154))
            screen.blit(value_surface, (input_rect.x + 6, input_rect.y + 4))
            y += 34

        sim.set_input_field_rects(field_rects)
        sim.set_control_panel_rect(panel)

        y += 6
        for line in payload.get("summary_lines", []):
            surface = font.render(line, True, (220, 226, 236))
            screen.blit(surface, (panel.x + 12, y))
            y += 22

        formation_rect = pygame.Rect(panel.x + 12, panel.bottom - 66, 172, 30)
        self._draw_panel_button(screen, font, formation_rect, "Formation Theory", primary=True)
        space_rect = self._draw_space_jump_button(screen, font, panel)
        if hasattr(sim, "set_formation_theory_button_rect"):
            sim.set_formation_theory_button_rect(formation_rect)
        if hasattr(sim, "set_world_gen_space_button_rect"):
            sim.set_world_gen_space_button_rect(space_rect)

        status = payload.get("commit_status") or ""
        if status:
            status_surface = font.render(status, True, (178, 210, 244))
            screen.blit(status_surface, (formation_rect.right + 14, panel.bottom - 59))

        if payload.get("planet_name_prompt_active"):
            hint_text = "Type planet name. Enter creates planet. Esc cancels."
        elif payload.get("orbit_pick_stage") == "second":
            hint_text = "Second click sets ellipse. Click elsewhere to start a new circular draft."
        else:
            hint_text = "Click orbit, then Enter to name and create the planet."
        hint = font.render(hint_text, True, (142, 152, 170))
        max_hint_w = panel.width - 24
        if hint.get_width() > max_hint_w:
            hint_text = "Click once: circular. Second click: ellipse. Tab edits fields."
            hint = font.render(hint_text, True, (142, 152, 170))
        screen.blit(hint, (panel.x + 12, panel.bottom - 26))

        if payload.get("planet_name_prompt_active"):
            prompt_w = 360
            prompt_h = 112
            prompt = pygame.Rect(
                (screen.get_width() - prompt_w) // 2,
                86,
                prompt_w,
                prompt_h,
            )
            input_rect = pygame.Rect(prompt.x + 18, prompt.y + 56, prompt.width - 36, 28)
            pygame.draw.rect(screen, (24, 28, 38), prompt)
            pygame.draw.rect(screen, (188, 196, 212), prompt, 1)
            title = font.render("Name Planet", True, (244, 244, 244))
            screen.blit(title, (prompt.x + 14, prompt.y + 12))
            pygame.draw.rect(screen, (38, 48, 68), input_rect)
            pygame.draw.rect(screen, (188, 212, 244), input_rect, 1)
            text = payload.get("planet_name_buffer") or ""
            surface = font.render(text or "Planet name", True, (238, 238, 238) if text else (128, 138, 154))
            screen.blit(surface, (input_rect.x + 8, input_rect.y + 5))

    def _draw_panel_button(self, screen, font, rect, label, primary=False):
        fill = (74, 92, 132) if primary else (40, 46, 60)
        border = (178, 196, 228) if primary else (118, 130, 154)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)
        surface = font.render(label, True, (238, 242, 248))
        screen.blit(surface, surface.get_rect(center=rect.center))

    def _draw_space_jump_button(self, screen, font, panel):
        rect = pygame.Rect(panel.right - 142, panel.bottom - 48, 126, 30)
        self._draw_panel_button(screen, font, rect, "Space Sim")
        return rect

    def _wrap_text(self, text, font, max_width):
        words = str(text or "").split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _format_temp_k_c(self, value):
        try:
            kelvin = float(value or 0.0)
        except (TypeError, ValueError):
            kelvin = 0.0
        return f"{kelvin:.1f} K / {kelvin - 273.15:.1f} C"

    def _draw_crust_composition_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (20, 23, 32), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        planet_class = str(payload.get("planet_class") or "").lower()
        is_envelope_body = planet_class in {"gas_giant", "ice_giant", "hot_gas_giant"}
        panel_label = "Envelope / Bulk Composition" if is_envelope_body else "Crust Composition"
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} {panel_label}"
        title_surface = font.render(title, True, (244, 244, 244))
        screen.blit(title_surface, (panel.x + 16, panel.y + 12))

        if is_envelope_body:
            subtitle = "Gas and ice giants use envelope/bulk elemental inventory; refractory crust sliders are not assumed."
        else:
            subtitle = "Major crust elements must total 99%; trace elements are implicit unless promoted."
        subtitle_surface = font.render(subtitle, True, (158, 170, 190))
        screen.blit(subtitle_surface, (panel.x + 16, panel.y + 34))

        composition = payload.get("crust_composition") or {}
        elements = sorted(
            list(composition.get("major_elements") or []),
            key=lambda item: -float(item.get("abundance_percent", 0.0) or 0.0),
        )
        slider_rects = {}
        y = panel.y + 70
        label_w = 180
        percent_w = 78
        slider_x = panel.x + label_w + 32
        slider_w = max(220, panel.width - label_w - percent_w - 300)
        row_h = 34
        target = float(payload.get("crust_target_percent") or 99.0)

        for element in elements:
            symbol = element.get("symbol", "")
            name = element.get("name") or symbol
            try:
                abundance = float(element.get("abundance_percent", 0.0))
            except (TypeError, ValueError):
                abundance = 0.0

            row_rect = pygame.Rect(panel.x + 14, y - 6, panel.width - 320, 28)
            pygame.draw.rect(screen, (29, 33, 44), row_rect)
            label = font.render(f"{name} ({symbol})", True, (216, 224, 238))
            screen.blit(label, (panel.x + 22, y))

            slider_rect = pygame.Rect(slider_x, y + 3, slider_w, 8)
            slider_rects[symbol] = slider_rect
            pygame.draw.rect(screen, (55, 61, 76), slider_rect)
            fill_w = int(slider_rect.width * max(0.0, min(1.0, abundance / target)))
            if fill_w > 0:
                pygame.draw.rect(screen, (122, 168, 218), pygame.Rect(slider_rect.x, slider_rect.y, fill_w, slider_rect.height))
            knob_x = slider_rect.x + fill_w
            pygame.draw.circle(screen, (220, 232, 248), (knob_x, slider_rect.centery), 7)
            percent = font.render(f"{abundance:5.2f}%", True, (232, 238, 246))
            screen.blit(percent, (slider_rect.right + 18, y - 2))
            y += row_h

        summary_x = panel.right - 280
        summary = pygame.Rect(summary_x, panel.y + 70, 250, 418)
        pygame.draw.rect(screen, (25, 29, 40), summary)
        pygame.draw.rect(screen, (96, 108, 132), summary, 1)
        physics = payload.get("derived_planet_physics") or {}
        trace_rows = sorted(
            list(composition.get("trace_elements") or []),
            key=lambda item: -float(item.get("abundance_percent", 0.0) or 0.0),
        )
        summary_lines = [
            f"Template: {payload.get('planet_template_label', 'unknown')}",
            f"Explicit total: {payload.get('crust_major_total_percent', 0.0):.2f}%",
            f"Trace reserve: {payload.get('trace_reserve_percent', 1.0):.2f}%",
            f"Type: {payload.get('planet_class') or payload.get('crust_type', 'unknown')}",
            f"Density proxy: {payload.get('crust_density_kg_m3', 0.0):.0f} kg/m3",
            f"Mass: {physics.get('mass_earth', 0.0):.3f} Earth",
            f"Mean density: {physics.get('mean_density_kg_m3', 0.0):.0f} kg/m3",
            f"Gravity: {physics.get('surface_gravity_g', 0.0):.2f} g",
            f"Day length: {physics.get('rotation_period_hours', 0.0):.2f} h",
            f"Core radius: {physics.get('core_radius_fraction', 0.0) * 100.0:.1f}%",
            f"Mantle: {physics.get('mantle_radius_fraction', 0.0) * 100.0:.1f}%",
            f"Crust: {physics.get('crust_radius_fraction', 0.0) * 100.0:.2f}%",
        ]
        sy = summary.y + 12
        for line in summary_lines:
            surface = font.render(line, True, (196, 210, 228))
            screen.blit(surface, (summary.x + 12, sy))
            sy += 22

        if trace_rows:
            sy += 4
            screen.blit(font.render("Trace Inventory", True, (232, 238, 246)), (summary.x + 12, sy))
            sy += 24
            for trace in trace_rows[:4]:
                line = (
                    f"{trace.get('symbol')} "
                    f"{float(trace.get('abundance_percent', 0.0) or 0.0):.3f}% "
                    f"{trace.get('rarity', '')}"
                )
                screen.blit(font.render(line, True, (176, 188, 208)), (summary.x + 12, sy))
                sy += 20

        seed_field_rects = {}
        sy += 10
        seed_title = font.render("Physical Inputs", True, (232, 238, 246))
        screen.blit(seed_title, (summary.x + 12, sy))
        sy += 26
        for field in payload.get("seed_fields", []):
            field_id = field.get("id")
            if field_id in {"volatile_inventory", "tectonics_mode"}:
                continue
            label_text = str(field.get("label", field_id))
            if len(label_text) > 19:
                label_text = label_text[:18]
            label = font.render(label_text, True, (176, 188, 208))
            screen.blit(label, (summary.x + 12, sy + 4))
            input_rect = pygame.Rect(summary.x + 142, sy, 92, 24)
            seed_field_rects[field_id] = input_rect
            fill = (38, 48, 68) if field.get("active") else (30, 34, 44)
            border = (188, 212, 244) if field.get("active") else (92, 102, 122)
            pygame.draw.rect(screen, fill, input_rect)
            pygame.draw.rect(screen, border, input_rect, 1)
            value = str(field.get("text") or "")
            value_surface = font.render(value or "value", True, (238, 238, 238) if value else (128, 138, 154))
            screen.blit(value_surface, (input_rect.x + 6, input_rect.y + 4))
            sy += 30

        material_top = max(y + 12, panel.y + 346)
        material_bottom = panel.bottom - 94
        material_rect = pygame.Rect(
            panel.x + 16,
            material_top,
            max(260, summary.x - panel.x - 34),
            max(80, material_bottom - material_top),
        )
        self._draw_crust_material_candidates(screen, font, material_rect, payload)

        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 84, 92, 26)
        self._draw_panel_button(screen, font, back_rect, "Back")
        generic_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 132, 30)
        eccentric_rect = pygame.Rect(generic_rect.right + 8, panel.bottom - 48, 148, 30)
        gas_rect = pygame.Rect(eccentric_rect.right + 8, panel.bottom - 48, 132, 30)
        add_rect = pygame.Rect(gas_rect.right + 8, panel.bottom - 48, 184, 30)
        save_rect = pygame.Rect(add_rect.right + 10, panel.bottom - 48, 154, 30)
        self._draw_panel_button(screen, font, generic_rect, "Generate Generic")
        self._draw_panel_button(screen, font, eccentric_rect, "Generate Eccentric")
        self._draw_panel_button(screen, font, gas_rect, "Gas / Ice Giant")
        self._draw_panel_button(screen, font, add_rect, "Add Abundant Trace Element")
        self._draw_panel_button(screen, font, save_rect, "Save Composition", primary=True)
        space_rect = self._draw_space_jump_button(screen, font, panel)

        status = payload.get("commit_status") or ""
        if status:
            status_surface = font.render(status, True, (178, 210, 244))
            screen.blit(status_surface, (save_rect.right + 18, panel.bottom - 41))

        hint = font.render("Drag sliders. Enter saves. Esc exits selected planet. Click empty space to draft another orbit.", True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        periodic_rect, element_rects = self._draw_periodic_table_popup(screen, font, payload, elements)
        sim.set_crust_ui_rects(
            slider_rects=slider_rects,
            add_trace_rect=add_rect,
            save_rect=save_rect,
            periodic_rect=periodic_rect,
            element_rects=element_rects,
            random_generic_rect=generic_rect,
            random_eccentric_rect=eccentric_rect,
            random_gas_giant_rect=gas_rect,
            back_rect=back_rect,
            space_rect=space_rect,
        )
        sim.set_seed_field_rects(seed_field_rects)
        sim.set_control_panel_rect(panel)

    def _draw_crust_material_candidates(self, screen, font, rect, payload):
        pygame.draw.rect(screen, (18, 21, 30), rect)
        pygame.draw.rect(screen, (76, 86, 106), rect, 1)
        screen.blit(font.render("Possible Materials", True, (232, 238, 246)), (rect.x + 12, rect.y + 10))

        model = payload.get("natural_material_model") if isinstance(payload.get("natural_material_model"), dict) else {}
        candidates = model.get("likely_materials") if isinstance(model.get("likely_materials"), list) else []
        if not candidates:
            message = "No material candidates yet; adjust the elemental inventory or save composition."
            screen.blit(font.render(message, True, (154, 166, 188)), (rect.x + 12, rect.y + 38))
            return

        groups = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            subclass = str(candidate.get("material_subclass") or "material").replace("_", " ").title()
            groups.setdefault(subclass, []).append(candidate)

        sorted_groups = sorted(
            groups.items(),
            key=lambda item: -max(float(candidate.get("confidence", 0.0) or 0.0) for candidate in item[1]),
        )
        columns = 2 if rect.width >= 760 else 1
        column_gap = 18
        column_w = int((rect.width - 24 - column_gap * (columns - 1)) / columns)
        x_positions = [rect.x + 12 + index * (column_w + column_gap) for index in range(columns)]
        y_positions = [rect.y + 38 for _ in range(columns)]
        bottom = rect.bottom - 10

        group_index = 0
        for subclass, items in sorted_groups:
            column = group_index % columns
            x = x_positions[column]
            y = y_positions[column]
            if y + 46 > bottom:
                group_index += 1
                continue
            screen.blit(font.render(subclass, True, (192, 204, 224)), (x, y))
            y += 22
            for item in sorted(items, key=lambda candidate: -float(candidate.get("confidence", 0.0) or 0.0))[:5]:
                if y + 22 > bottom:
                    break
                swatch = pygame.Rect(x, y + 4, 12, 12)
                color = self._coerce_rgb(item.get("display_color"), fallback=(142, 136, 122))
                pygame.draw.rect(screen, color, swatch)
                pygame.draw.rect(screen, (42, 46, 58), swatch, 1)
                name = str(item.get("name") or item.get("material_id") or "material")
                formula = str(item.get("chemical_formula") or "")
                occurrence = str(item.get("occurrence") or "possible")
                confidence = float(item.get("confidence", 0.0) or 0.0)
                label = f"{name} | {occurrence} {confidence * 100:.0f}%"
                if formula:
                    label = f"{label} | {formula}"
                clipped = label
                while font.size(clipped)[0] > column_w - 20 and len(clipped) > 12:
                    clipped = clipped[:-2]
                if clipped != label:
                    clipped = f"{clipped}."
                screen.blit(font.render(clipped, True, (206, 216, 230)), (x + 18, y))
                y += 20
            y_positions[column] = y + 10
            group_index += 1

    def _draw_periodic_table_popup(self, screen, font, payload, current_elements):
        if not payload.get("periodic_table_open"):
            return None, {}

        rows = payload.get("periodic_table_rows") or []
        cell_w = 42
        cell_h = 32
        gap = 4
        popup_w = 18 * cell_w + 19 * gap
        popup_h = len(rows) * cell_h + (len(rows) + 1) * gap + 58
        popup = pygame.Rect(
            (screen.get_width() - popup_w) // 2,
            (screen.get_height() - popup_h) // 2,
            popup_w,
            popup_h,
        )

        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, (24, 28, 38), popup)
        pygame.draw.rect(screen, (190, 200, 220), popup, 1)
        title = font.render("Select Trace Element To Promote", True, (244, 244, 244))
        screen.blit(title, (popup.x + 14, popup.y + 12))
        note = font.render("Elements already explicit are dimmed. Esc closes.", True, (154, 166, 188))
        screen.blit(note, (popup.x + 14, popup.y + 34))

        explicit_symbols = {element.get("symbol") for element in current_elements}
        element_rects = {}
        grid_y = popup.y + 60
        for row_index, row in enumerate(rows):
            for col_index, symbol in enumerate(row):
                if not symbol:
                    continue
                rect = pygame.Rect(
                    popup.x + gap + col_index * (cell_w + gap),
                    grid_y + gap + row_index * (cell_h + gap),
                    cell_w,
                    cell_h,
                )
                disabled = symbol in explicit_symbols
                fill = (36, 42, 54) if not disabled else (30, 31, 36)
                border = (118, 146, 184) if not disabled else (70, 74, 86)
                text_color = (222, 234, 248) if not disabled else (102, 108, 124)
                pygame.draw.rect(screen, fill, rect)
                pygame.draw.rect(screen, border, rect, 1)
                surface = font.render(symbol, True, text_color)
                screen.blit(surface, surface.get_rect(center=rect.center))
                if not disabled:
                    element_rects[symbol] = rect

        return popup, element_rects

    def _draw_atmosphere_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (20, 23, 32), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        atmosphere = payload.get("atmosphere_model") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Atmosphere"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "Atmosphere is constrained by stellar flux, gravity, molecule mass, volatile inventory, and condensation."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        left = pygame.Rect(panel.x + 16, panel.y + 70, (panel.width - 58) // 2, panel.height - 150)
        right = pygame.Rect(left.right + 26, left.y, panel.right - left.right - 42, left.height)
        pygame.draw.rect(screen, (25, 29, 40), left)
        pygame.draw.rect(screen, (96, 108, 132), left, 1)
        pygame.draw.rect(screen, (25, 29, 40), right)
        pygame.draw.rect(screen, (96, 108, 132), right, 1)

        lines = [
            f"Atmosphere class: {atmosphere.get('atmosphere_class', 'unknown')}",
            f"Solid surface: {'yes' if atmosphere.get('has_solid_surface', True) else 'no'}",
            f"Equilibrium temp: {self._format_temp_k_c(atmosphere.get('equilibrium_temperature_k', 0.0))}",
            f"Surface temp est.: {self._format_temp_k_c(atmosphere.get('estimated_surface_temperature_k', 0.0))}",
            f"Greenhouse delta: {atmosphere.get('greenhouse_delta_k', 0.0):.1f} K",
            f"Volatile supply: {atmosphere.get('volatile_supply_bar', 0.0):.2f} bar",
            f"Retained column: {atmosphere.get('retained_column_fraction', 0.0) * 100.0:.1f}%",
            f"Pressure estimate: {atmosphere.get('surface_pressure_bar', 0.0):.3f} bar",
            f"Escape velocity: {atmosphere.get('escape_velocity_m_s', 0.0):.0f} m/s",
            f"Exobase temp: {self._format_temp_k_c(atmosphere.get('exobase_temperature_k', 0.0))}",
        ]
        y = left.y + 14
        screen.blit(font.render("Thermal / Retention Model", True, (232, 238, 246)), (left.x + 12, y))
        y += 30
        for line in lines:
            screen.blit(font.render(line, True, (196, 210, 228)), (left.x + 12, y))
            y += 24

        y += 12
        screen.blit(font.render("Molecule Retention", True, (232, 238, 246)), (left.x + 12, y))
        y += 26
        for row in atmosphere.get("retention", [])[:13]:
            molecule = row.get("molecule")
            status = row.get("status")
            ratio = row.get("escape_speed_ratio", 0.0)
            text = f"{molecule:<4} {status:<6} escape/rms {ratio:.1f}"
            color = (188, 220, 188) if status == "stable" else ((228, 202, 142) if status == "leaky" else (220, 150, 150))
            screen.blit(font.render(text, True, color), (left.x + 12, y))
            y += 22

        y = right.y + 14
        screen.blit(font.render("Estimated Composition", True, (232, 238, 246)), (right.x + 12, y))
        y += 30
        bar_x = right.x + 118
        bar_w = max(160, right.width - 210)
        for item in atmosphere.get("composition", [])[:12]:
            molecule = item.get("molecule")
            percent = float(item.get("percent", 0.0))
            screen.blit(font.render(molecule, True, (216, 224, 238)), (right.x + 12, y))
            bar = pygame.Rect(bar_x, y + 5, bar_w, 8)
            pygame.draw.rect(screen, (55, 61, 76), bar)
            fill_w = int(bar.width * max(0.0, min(1.0, percent / 100.0)))
            if fill_w:
                pygame.draw.rect(screen, (122, 168, 218), pygame.Rect(bar.x, bar.y, fill_w, bar.height))
            screen.blit(font.render(f"{percent:5.2f}%", True, (232, 238, 246)), (bar.right + 12, y - 1))
            y += 30

        y += 14
        for note in atmosphere.get("notes", [])[:4]:
            for wrapped in self._wrap_text(note, font, right.width - 24):
                screen.blit(font.render(wrapped, True, (154, 166, 188)), (right.x + 12, y))
                y += 20
                if y > right.bottom - 28:
                    break
            if y > right.bottom - 28:
                break

        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 164, 30)
        can_complete = bool(getattr(sim, "_world_gen_can_finish", lambda: False)())
        complete_rect = pygame.Rect(save_rect.right + 12, panel.bottom - 48, 204, 30) if can_complete else None
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, "Save Atmosphere", primary=True)
        if complete_rect is not None:
            self._draw_panel_button(screen, font, complete_rect, "Complete Worldgen")
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            status_x = (complete_rect.right + 18) if complete_rect is not None else (save_rect.right + 18)
            screen.blit(font.render(status, True, (178, 210, 244)), (status_x, panel.bottom - 41))
        hint_text = (
            "Save atmosphere, then complete worldgen for gas giants. Esc exits selected planet."
            if can_complete else
            "Enter saves atmosphere. Esc exits selected planet. Later: atmospheric chemistry and climate iteration."
        )
        hint = font.render(hint_text, True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, complete_rect=complete_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)

    def _draw_status_row(self, screen, font, rect, label, value, color=(196, 210, 228)):
        screen.blit(font.render(str(label), True, (154, 166, 188)), (rect.x, rect.y))
        value_text = self._wrap_text(str(value), font, rect.width - 190)
        y = rect.y
        for line in value_text[:2]:
            screen.blit(font.render(line, True, color), (rect.x + 190, y))
            y += 20
        return max(rect.y + 24, y + 2)

    def _draw_regime_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (20, 23, 32), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        regime = payload.get("interior_regime_model") or {}
        interior = regime.get("interior") or {}
        surface = regime.get("surface_processes") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Interior / Surface Regime"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "This determines which terrain, erosion, hydrology, and crater processes the map generator may use."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        left = pygame.Rect(panel.x + 16, panel.y + 70, (panel.width - 58) // 2, panel.height - 150)
        right = pygame.Rect(left.right + 26, left.y, panel.right - left.right - 42, left.height)
        for box in (left, right):
            pygame.draw.rect(screen, (25, 29, 40), box)
            pygame.draw.rect(screen, (96, 108, 132), box, 1)

        y = left.y + 14
        screen.blit(font.render("Interior Engine", True, (232, 238, 246)), (left.x + 12, y))
        y += 32
        interior_rows = [
            ("Differentiated", "yes" if interior.get("differentiated") else "no"),
            ("Mantle present", "yes" if interior.get("mantle_present") else "no"),
            ("Core radius", f"{float(interior.get('core_radius_fraction', 0.0)) * 100.0:.1f}%"),
            ("Mantle radius", f"{float(interior.get('mantle_radius_fraction', 0.0)) * 100.0:.1f}%"),
            ("Crust", f"{float(interior.get('crust_thickness_km', 0.0)):.1f} km | {interior.get('crust_type', 'unknown')}"),
            ("Internal heat", f"{float(interior.get('internal_heat_w_m2', 0.0)):.3f} W/m2"),
            ("Tectonics", interior.get("tectonic_regime", "unknown")),
            ("Volcanism", interior.get("volcanic_activity", "unknown")),
        ]
        for label, value in interior_rows:
            row_rect = pygame.Rect(left.x + 12, y, left.width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y = right.y + 14
        screen.blit(font.render("Surface Process Permissions", True, (232, 238, 246)), (right.x + 12, y))
        y += 32
        process_rows = [
            ("Pressure", f"{float(surface.get('surface_pressure_bar', 0.0)):.3f} bar"),
            ("Temperature", self._format_temp_k_c(surface.get("surface_temperature_k", 0.0))),
            ("Liquid water", "possible" if surface.get("liquid_water_possible") else "not stable"),
            ("Hydrology", surface.get("hydrologic_cycle", "unknown")),
            ("Wind erosion", surface.get("aeolian_activity", "unknown")),
            ("Crater retention", surface.get("crater_retention", "unknown")),
            ("Topography seed", surface.get("primary_topography", "unknown")),
        ]
        for label, value in process_rows:
            row_rect = pygame.Rect(right.x + 12, y, right.width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y += 8
        erosion = ", ".join(surface.get("erosion_processes") or [])
        for wrapped in self._wrap_text(f"Erosion: {erosion or 'none'}", font, right.width - 24):
            screen.blit(font.render(wrapped, True, (196, 210, 228)), (right.x + 12, y))
            y += 20

        y += 8
        screen.blit(font.render("Next Map Recipe", True, (232, 238, 246)), (right.x + 12, y))
        y += 24
        for step in (regime.get("map_recipe") or [])[:7]:
            text = step.replace("_", " ")
            screen.blit(font.render(f"- {text}", True, (154, 166, 188)), (right.x + 18, y))
            y += 20
            if y > right.bottom - 24:
                break

        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 188, 30)
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, "Save Regime", primary=True)
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            screen.blit(font.render(status, True, (178, 210, 244)), (save_rect.right + 18, panel.bottom - 41))
        hint = font.render("Enter saves regime. Esc exits selected planet. Next: generate first heightfield/map layers.", True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)

    def _draw_terrain_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (20, 23, 32), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        terrain = payload.get("terrain_seed_model") or {}
        natural_materials = payload.get("natural_material_model") or {}
        heightfield = terrain.get("heightfield") or {}
        tectonics = terrain.get("tectonics") or {}
        cratering = terrain.get("cratering") or {}
        erosion = terrain.get("erosion") or {}
        hydrology = terrain.get("hydrology") or {}
        canvas = terrain.get("map_canvas") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Terrain Seed"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "This creates the first global map scaffold: elevation bounds, water mask, tectonic/crater layers, and erosion masks."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        col_gap = 24
        col_w = (panel.width - 48 - col_gap * 2) // 3
        columns = [
            pygame.Rect(panel.x + 16, panel.y + 70, col_w, panel.height - 150),
            pygame.Rect(panel.x + 16 + col_w + col_gap, panel.y + 70, col_w, panel.height - 150),
            pygame.Rect(panel.x + 16 + (col_w + col_gap) * 2, panel.y + 70, col_w, panel.height - 150),
        ]
        for box in columns:
            pygame.draw.rect(screen, (25, 29, 40), box)
            pygame.draw.rect(screen, (96, 108, 132), box, 1)

        y = columns[0].y + 14
        screen.blit(font.render("Heightfield Canvas", True, (232, 238, 246)), (columns[0].x + 12, y))
        y += 32
        height_rows = [
            ("Projection", canvas.get("projection", "unknown")),
            ("Canvas", f"{canvas.get('width_px', 0)} x {canvas.get('height_px', 0)}"),
            ("Relief driver", heightfield.get("relief_driver", "unknown")),
            ("Topography", heightfield.get("primary_topography", "unknown")),
            ("Min elevation", f"{float(heightfield.get('min_elevation_m', 0.0)):.0f} m"),
            ("Max elevation", f"{float(heightfield.get('max_elevation_m', 0.0)):.0f} m"),
            ("Roughness", f"{float(heightfield.get('roughness', 0.0)):.2f}"),
            ("Ocean target", f"{float(heightfield.get('target_ocean_fraction', 0.0)) * 100.0:.1f}%"),
            ("Ice target", f"{float(hydrology.get('target_ice_fraction', 0.0)) * 100.0:.1f}%"),
        ]
        for label, value in height_rows:
            row_rect = pygame.Rect(columns[0].x + 12, y, columns[0].width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y = columns[1].y + 14
        screen.blit(font.render("Surface Drivers", True, (232, 238, 246)), (columns[1].x + 12, y))
        y += 32
        driver_rows = [
            ("Tectonics", "enabled" if tectonics.get("enabled") else "disabled"),
            ("Regime", tectonics.get("regime", "unknown")),
            ("Plate count", tectonics.get("plate_count", 0)),
            ("Boundary style", tectonics.get("boundary_style", "unknown")),
            ("Cratering", f"{cratering.get('retention', 'unknown')} | {float(cratering.get('density', 0.0)):.2f}"),
            ("Max crater", f"{float(cratering.get('max_crater_diameter_km', 0.0)):.1f} km"),
            ("Hydrology", hydrology.get("cycle", "unknown")),
            ("Frozen water", "possible" if hydrology.get("frozen_water_possible") else "not stable"),
            ("Drainage", "enabled" if hydrology.get("drainage_enabled") else "disabled"),
        ]
        for label, value in driver_rows:
            row_rect = pygame.Rect(columns[1].x + 12, y, columns[1].width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y += 8
        erosion_text = ", ".join(erosion.get("processes") or [])
        for wrapped in self._wrap_text(f"Erosion: {erosion_text or 'none'}", font, columns[1].width - 24):
            screen.blit(font.render(wrapped, True, (196, 210, 228)), (columns[1].x + 12, y))
            y += 20

        y = columns[2].y + 14
        screen.blit(font.render("Map Layers", True, (232, 238, 246)), (columns[2].x + 12, y))
        y += 30
        for layer in (terrain.get("map_layers") or [])[:6]:
            label = f"{layer.get('id', 'layer')} | {layer.get('kind', 'layer')}"
            for wrapped in self._wrap_text(label, font, columns[2].width - 30):
                screen.blit(font.render(wrapped, True, (196, 210, 228)), (columns[2].x + 18, y))
                y += 19
            if y > columns[2].bottom - 138:
                break

        y += 8
        screen.blit(font.render("Natural Materials", True, (232, 238, 246)), (columns[2].x + 12, y))
        y += 24
        for item in (natural_materials.get("likely_materials") or [])[:5]:
            swatch = self._coerce_rgb(item.get("display_color"), fallback=(134, 134, 126))
            swatch_rect = pygame.Rect(columns[2].x + 18, y + 3, 12, 12)
            pygame.draw.rect(screen, swatch, swatch_rect)
            pygame.draw.rect(screen, (86, 92, 104), swatch_rect, 1)
            text = f"{item.get('name', 'material')} | {item.get('occurrence', 'possible')} {float(item.get('confidence', 0.0)):.2f}"
            for wrapped in self._wrap_text(text, font, columns[2].width - 46):
                screen.blit(font.render(wrapped, True, (154, 166, 188)), (columns[2].x + 36, y))
                y += 19
            if y > columns[2].bottom - 20:
                break

        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 180, 30)
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, "Save Terrain", primary=True)
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            screen.blit(font.render(status, True, (178, 210, 244)), (save_rect.right + 18, panel.bottom - 41))
        hint = font.render("Enter saves terrain seed. Esc exits selected planet. Next: preview/render map layers.", True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)

    def _plate_color(self, index, plate_type):
        palette = [
            (66, 102, 132),
            (78, 122, 96),
            (128, 106, 72),
            (112, 82, 126),
            (118, 118, 76),
            (72, 118, 126),
            (128, 84, 84),
            (90, 104, 146),
        ]
        base = palette[index % len(palette)]
        if plate_type == "oceanic":
            return (max(26, base[0] - 28), max(40, base[1] - 10), min(170, base[2] + 26))
        if plate_type == "continental":
            return (min(160, base[0] + 32), min(155, base[1] + 24), max(54, base[2] - 6))
        return base

    def _draw_arrow(self, screen, start, vector, color, scale=1.0, width=1):
        sx, sy = start
        vx, vy = vector
        ex = sx + vx * scale
        ey = sy + vy * scale
        pygame.draw.line(screen, color, (int(sx), int(sy)), (int(ex), int(ey)), width)
        angle = math.atan2(ey - sy, ex - sx)
        head = 6
        left = (ex - math.cos(angle - 0.55) * head, ey - math.sin(angle - 0.55) * head)
        right = (ex - math.cos(angle + 0.55) * head, ey - math.sin(angle + 0.55) * head)
        pygame.draw.line(screen, color, (int(ex), int(ey)), (int(left[0]), int(left[1])), width)
        pygame.draw.line(screen, color, (int(ex), int(ey)), (int(right[0]), int(right[1])), width)

    def _draw_tectonic_map(self, screen, font, rect, tectonic_model):
        grid = tectonic_model.get("sample_grid") if isinstance(tectonic_model.get("sample_grid"), dict) else {}
        owners = grid.get("owners") if isinstance(grid.get("owners"), list) else []
        plates = list(tectonic_model.get("plates") or [])
        sample_h = int(grid.get("height", len(owners)) or len(owners))
        sample_w = int(grid.get("width", len(owners[0]) if owners else 0) or 0)
        if sample_w < 2 or sample_h < 2 or not plates:
            return

        previous_clip = screen.get_clip()
        screen.set_clip(rect)
        try:
            cell_w = rect.width / max(1, sample_w)
            cell_h = rect.height / max(1, sample_h)
            for row_index, owner_row in enumerate(owners[:sample_h]):
                for col_index, owner in enumerate(owner_row[:sample_w]):
                    plate = plates[int(owner) % len(plates)]
                    color = self._plate_color(int(owner), plate.get("plate_type"))
                    cell = pygame.Rect(
                        int(rect.x + col_index * cell_w),
                        int(rect.y + row_index * cell_h),
                        max(1, int(math.ceil(cell_w))),
                        max(1, int(math.ceil(cell_h))),
                    )
                    pygame.draw.rect(screen, color, cell)

            for segment in tectonic_model.get("boundary_segments") or []:
                x1 = rect.x + float(segment.get("x1", 0.0)) * rect.width
                y1 = rect.y + float(segment.get("y1", 0.0)) * rect.height
                x2 = rect.x + float(segment.get("x2", 0.0)) * rect.width
                y2 = rect.y + float(segment.get("y2", 0.0)) * rect.height
                pygame.draw.line(screen, (220, 228, 236), (int(x1), int(y1)), (int(x2), int(y2)), 1)

            # Draw current arrows separately so they read above plate ownership.
            for current in tectonic_model.get("mantle_currents") or []:
                x = rect.x + float(current.get("pos_x", 0.0)) * rect.width
                y = rect.y + float(current.get("pos_y", 0.0)) * rect.height
                self._draw_arrow(
                    screen,
                    (x, y),
                    (float(current.get("dir_x", 0.0)), float(current.get("dir_y", 0.0))),
                    (118, 206, 220),
                    scale=22,
                    width=2,
                )

            for index, plate in enumerate(plates):
                x = rect.x + float(plate.get("center_x", 0.0)) * rect.width
                y = rect.y + float(plate.get("center_y", 0.0)) * rect.height
                pygame.draw.circle(screen, (16, 18, 24), (int(x), int(y)), 5)
                pygame.draw.circle(screen, (236, 238, 244), (int(x), int(y)), 5, 1)
                self._draw_arrow(
                    screen,
                    (x, y),
                    (float(plate.get("velocity_x_cm_year", 0.0)), float(plate.get("velocity_y_cm_year", 0.0))),
                    (246, 218, 126),
                    scale=4,
                    width=1,
                )
        finally:
            screen.set_clip(previous_clip)

    def _draw_tectonics_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (18, 21, 28), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        tectonic_model = payload.get("tectonic_model") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Tectonics"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "Mantle currents drive plate motion. Advancing turns boundaries into mountains, trenches, basins, and erosion state."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        sidebar_w = 330
        preview = pygame.Rect(panel.x + 16, panel.y + 70, panel.width - sidebar_w - 48, panel.height - 150)
        sidebar = pygame.Rect(preview.right + 24, preview.y, sidebar_w, preview.height)
        pygame.draw.rect(screen, (7, 10, 14), preview)
        pygame.draw.rect(screen, (104, 116, 138), preview, 1)
        self._draw_tectonic_map(screen, font, preview, tectonic_model)
        pygame.draw.rect(screen, (25, 29, 40), sidebar)
        pygame.draw.rect(screen, (96, 108, 132), sidebar, 1)

        y = sidebar.y + 14
        screen.blit(font.render("Plate State", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 32
        boundary_counts = {}
        for boundary in tectonic_model.get("boundaries") or []:
            kind = boundary.get("kind", "passive")
            boundary_counts[kind] = boundary_counts.get(kind, 0) + 1
        rows = [
            ("Status", tectonic_model.get("status", "unknown")),
            ("Age", f"{float(tectonic_model.get('age_myr', 0.0)):.1f} Myr"),
            ("Plates", tectonic_model.get("plate_count", 0)),
            ("Convergent", boundary_counts.get("collision", 0) + boundary_counts.get("subduction", 0)),
            ("Divergent", boundary_counts.get("divergent", 0)),
            ("Transform", boundary_counts.get("transform", 0)),
            ("Passive", boundary_counts.get("passive", 0)),
        ]
        for label, value in rows:
            row_rect = pygame.Rect(sidebar.x + 12, y, sidebar.width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y += 14
        screen.blit(font.render("Legend", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 26
        for text, color in [
            ("plate areas", (126, 156, 116)),
            ("white boundaries", (220, 228, 236)),
            ("cyan mantle currents", (118, 206, 220)),
            ("gold plate vectors", (246, 218, 126)),
        ]:
            pygame.draw.rect(screen, color, pygame.Rect(sidebar.x + 12, y + 5, 18, 8))
            screen.blit(font.render(text, True, (176, 188, 208)), (sidebar.x + 38, y))
            y += 22

        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 188, 30)
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, "Advance Tectonics", primary=True)
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            screen.blit(font.render(status, True, (178, 210, 244)), (save_rect.right + 18, panel.bottom - 41))
        hint = font.render("Enter advances 25 Myr. Esc exits selected planet. Next: heightmap from uplift, basins, and erosion.", True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)

    def _heightmap_contour_segments(self, heightmap, level):
        grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        sample_h = int(grid.get("height", len(rows)) or len(rows))
        sample_w = int(grid.get("width", len(rows[0]) if rows else 0) or 0)
        if sample_w < 2 or sample_h < 2 or len(rows) < sample_h:
            return []

        def edge_point(edge, col, row, v_a, v_b):
            denom = v_b - v_a
            t = 0.5 if abs(denom) < 1e-9 else (level - v_a) / denom
            t = max(0.0, min(1.0, t))
            if edge == "top":
                return col + t, row
            if edge == "right":
                return col + 1, row + t
            if edge == "bottom":
                return col + t, row + 1
            return col, row + t

        segments = []
        for row in range(sample_h - 1):
            if row + 1 >= len(rows):
                break
            for col in range(sample_w - 1):
                try:
                    v00 = float(rows[row][col])
                    v10 = float(rows[row][col + 1])
                    v01 = float(rows[row + 1][col])
                    v11 = float(rows[row + 1][col + 1])
                except (IndexError, TypeError, ValueError):
                    continue

                points = []
                if (v00 <= level <= v10) or (v10 <= level <= v00):
                    if v00 != v10:
                        points.append(edge_point("top", col, row, v00, v10))
                if (v10 <= level <= v11) or (v11 <= level <= v10):
                    if v10 != v11:
                        points.append(edge_point("right", col, row, v10, v11))
                if (v01 <= level <= v11) or (v11 <= level <= v01):
                    if v01 != v11:
                        points.append(edge_point("bottom", col, row, v01, v11))
                if (v00 <= level <= v01) or (v01 <= level <= v00):
                    if v00 != v01:
                        points.append(edge_point("left", col, row, v00, v01))

                if len(points) == 2:
                    segments.append((points[0], points[1], level))
                elif len(points) == 4:
                    segments.append((points[0], points[1], level))
                    segments.append((points[2], points[3], level))
        return segments

    def _draw_heightmap_contours(self, screen, font, map_rect, clip_rect, heightmap, interval_m):
        grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        sample_w = int(grid.get("width", 0) or 0)
        sample_h = int(grid.get("height", 0) or 0)
        if sample_w < 2 or sample_h < 2:
            return

        levels = contour_levels_for_heightmap(heightmap, interval_m, max_levels=18)
        scale_x = map_rect.width / max(1, sample_w - 1)
        scale_y = map_rect.height / max(1, sample_h - 1)
        previous_clip = screen.get_clip()
        screen.set_clip(clip_rect)
        try:
            for level in levels:
                is_zero = abs(level) < interval_m * 0.45
                is_major = level % max(interval_m * 5, 1) == 0
                if is_zero:
                    color = (128, 190, 240)
                    width = 2
                elif is_major:
                    color = (178, 190, 206)
                    width = 1
                elif level < 0:
                    color = (72, 92, 116)
                    width = 1
                else:
                    color = (118, 128, 142)
                    width = 1
                for p1, p2, _ in self._heightmap_contour_segments(heightmap, level):
                    screen_p1 = (int(map_rect.x + p1[0] * scale_x), int(map_rect.y + p1[1] * scale_y))
                    screen_p2 = (int(map_rect.x + p2[0] * scale_x), int(map_rect.y + p2[1] * scale_y))
                    pygame.draw.line(screen, color, screen_p1, screen_p2, width)
        finally:
            screen.set_clip(previous_clip)

        sea_level = heightmap.get("sea_level_m")
        label = "0 m datum" if sea_level is None else f"{float(sea_level):.0f} m sea level"
        label_surface = font.render(label, True, (164, 204, 238))
        screen.blit(label_surface, (clip_rect.x + 10, clip_rect.y + 10))

    def _draw_heightmap_land_ocean(self, screen, map_rect, clip_rect, heightmap, selected_planet=None, material_model=None):
        grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        sample_h = int(grid.get("height", len(rows)) or len(rows))
        sample_w = int(grid.get("width", len(rows[0]) if rows else 0) or 0)
        if sample_w < 2 or sample_h < 2:
            return
        masks = heightmap.get("surface_masks") if isinstance(heightmap.get("surface_masks"), dict) else {}
        ice_rows = masks.get("ice_rows") if isinstance(masks.get("ice_rows"), list) else []
        land_dark, land_mid, land_high, land_shadow = self._surface_palette_colors(selected_planet, material_model)
        ice_low = self._mix_rgb((182, 204, 216), land_mid, 0.14)
        ice_high = self._mix_rgb((232, 242, 246), land_high, 0.10)
        ocean_deep = self._mix_rgb((8, 26, 48), land_shadow, 0.10)
        ocean_shallow = self._mix_rgb((28, 78, 124), land_mid, 0.08)

        sea_level_value = heightmap.get("sea_level_m")
        has_ocean = sea_level_value is not None
        sea_level = 0.0 if sea_level_value is None else float(sea_level_value)
        min_elevation = float(heightmap.get("min_elevation_m", -4000.0) or -4000.0)
        max_elevation = float(heightmap.get("max_elevation_m", 4000.0) or 4000.0)
        land_span = max(1.0, max_elevation - sea_level)
        ocean_span = max(1.0, sea_level - min_elevation)
        cell_cols = max(1, sample_w - 1)
        cell_rows = max(1, sample_h - 1)
        x_edges = [map_rect.x + int(col_index * map_rect.width / cell_cols) for col_index in range(cell_cols + 1)]
        y_edges = [map_rect.y + int(row_index * map_rect.height / cell_rows) for row_index in range(cell_rows + 1)]

        previous_clip = screen.get_clip()
        screen.set_clip(clip_rect)
        try:
            for row_index, row in enumerate(rows[:sample_h - 1]):
                y0 = y_edges[row_index]
                y1 = y_edges[row_index + 1]
                for col_index, value in enumerate(row[:sample_w - 1]):
                    try:
                        elevation = float(value)
                    except (TypeError, ValueError):
                        continue
                    has_ice = (
                        row_index < len(ice_rows)
                        and isinstance(ice_rows[row_index], list)
                        and col_index < len(ice_rows[row_index])
                        and bool(ice_rows[row_index][col_index])
                    )
                    if has_ice:
                        height = min(1.0, (elevation - min_elevation) / max(1.0, max_elevation - min_elevation))
                        color = self._mix_rgb(ice_low, ice_high, height)
                    elif has_ocean and elevation < sea_level:
                        depth = min(1.0, (sea_level - elevation) / ocean_span)
                        color = self._mix_rgb(ocean_shallow, ocean_deep, depth)
                    else:
                        height = min(1.0, (elevation - sea_level) / land_span)
                        if height < 0.45:
                            color = self._mix_rgb(land_dark, land_mid, height / 0.45)
                        elif height < 0.82:
                            color = self._mix_rgb(land_mid, land_high, (height - 0.45) / 0.37)
                        else:
                            color = self._mix_rgb(land_high, (214, 212, 196), (height - 0.82) / 0.18)
                    x0 = x_edges[col_index]
                    x1 = x_edges[col_index + 1]
                    rect = pygame.Rect(
                        x0,
                        y0,
                        max(1, x1 - x0),
                        max(1, y1 - y0),
                    )
                    pygame.draw.rect(screen, color, rect)
        finally:
            screen.set_clip(previous_clip)

    def _climate_zone_colors(self, water_cycle):
        colors = {
            "polar_ice": (202, 224, 232),
            "cold_steppe": (146, 158, 132),
            "temperate_wet": (82, 142, 104),
            "temperate_dry": (172, 156, 104),
            "tropical_wet": (48, 130, 88),
            "tropical_dry": (184, 146, 78),
            "arid": (196, 176, 118),
            "highland": (138, 128, 118),
            "ocean": (50, 92, 132),
        }
        for zone in water_cycle.get("climate_zones") or []:
            if isinstance(zone, dict) and zone.get("id"):
                colors[str(zone["id"])] = self._coerce_rgb(
                    zone.get("color"),
                    fallback=colors.get(str(zone["id"]), (150, 150, 150)),
                )
        return colors

    def _draw_water_cycle_preview(self, screen, rect, water_cycle):
        climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle, dict) else {}
        rows = climate_grid.get("rows") if isinstance(climate_grid.get("rows"), list) else []
        pygame.draw.rect(screen, (8, 10, 14), rect)
        if not rows:
            pygame.draw.rect(screen, (96, 108, 132), rect, 1)
            return

        colors = self._climate_zone_colors(water_cycle)
        row_count = len(rows)
        col_count = min(len(row) for row in rows if row)
        x_edges = [rect.x + round(index * rect.width / max(1, col_count)) for index in range(col_count + 1)]
        y_edges = [rect.y + round(index * rect.height / max(1, row_count)) for index in range(row_count + 1)]
        previous_clip = screen.get_clip()
        screen.set_clip(rect)
        try:
            for row_index, row in enumerate(rows):
                y0 = y_edges[row_index]
                y1 = y_edges[row_index + 1]
                for col_index, zone_id in enumerate(row[:col_count]):
                    x0 = x_edges[col_index]
                    x1 = x_edges[col_index + 1]
                    pygame.draw.rect(
                        screen,
                        colors.get(str(zone_id), (126, 128, 126)),
                        pygame.Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0)),
                    )
            for river in water_cycle.get("rivers") or []:
                if not isinstance(river, dict):
                    continue
                points = []
                for point in river.get("points") or []:
                    if not isinstance(point, dict):
                        continue
                    px = rect.x + float(point.get("x", 0.0) or 0.0) * rect.width
                    py = rect.y + float(point.get("y", 0.0) or 0.0) * rect.height
                    points.append((int(px), int(py)))
                if len(points) >= 2:
                    line_width = 2 + int(float(river.get("flow", 0.1) or 0.1) * 3)
                    pygame.draw.lines(screen, (82, 172, 238), False, points, line_width)
                    pygame.draw.circle(screen, (178, 226, 255), points[0], 3)
        finally:
            screen.set_clip(previous_clip)
        pygame.draw.rect(screen, (118, 132, 158), rect, 1)

    def _draw_water_cycle_panel(self, screen, sim, payload):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (18, 21, 28), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        water_cycle = payload.get("water_cycle_model") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Water Cycle"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "Climate zones and rivers are derived from heightmap, sea level, pressure, temperature, and map seed."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        sidebar_w = 360
        preview = pygame.Rect(panel.x + 16, panel.y + 70, panel.width - sidebar_w - 48, panel.height - 150)
        sidebar = pygame.Rect(preview.right + 24, preview.y, sidebar_w, preview.height)
        pygame.draw.rect(screen, (25, 29, 40), sidebar)
        pygame.draw.rect(screen, (96, 108, 132), sidebar, 1)
        self._draw_water_cycle_preview(screen, preview, water_cycle)

        y = sidebar.y + 14
        screen.blit(font.render("Hydrology", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 30
        runoff = water_cycle.get("runoff_summary") if isinstance(water_cycle.get("runoff_summary"), dict) else {}
        rows = [
            ("Cycle", "active" if water_cycle.get("hydrology_enabled") else "inactive"),
            ("Liquid water", "possible" if water_cycle.get("liquid_water_possible") else "not stable"),
            ("Pressure", f"{float(runoff.get('surface_pressure_bar', 0.0)):.3f} bar"),
            ("Mean temp", f"{float(runoff.get('mean_temperature_k', 0.0)):.1f} K"),
            ("Rivers", str(int(water_cycle.get("river_count", 0) or 0))),
        ]
        for label, value in rows:
            row_rect = pygame.Rect(sidebar.x + 12, y, sidebar.width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y += 10
        screen.blit(font.render("Climate Coverage", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 28
        for zone in (water_cycle.get("climate_zones") or [])[:8]:
            if not isinstance(zone, dict):
                continue
            color = self._coerce_rgb(zone.get("color"), fallback=(154, 166, 188))
            fraction = max(0.0, min(1.0, float(zone.get("fraction", 0.0) or 0.0)))
            row = pygame.Rect(sidebar.x + 12, y, sidebar.width - 24, 20)
            pygame.draw.rect(screen, color, pygame.Rect(row.x, row.y + 3, 14, 14))
            bar_x = row.x + 122
            bar_w = max(1, row.width - 172)
            pygame.draw.rect(screen, (42, 48, 60), pygame.Rect(bar_x, row.y + 5, bar_w, 10))
            pygame.draw.rect(screen, color, pygame.Rect(bar_x, row.y + 5, int(bar_w * fraction), 10))
            label = str(zone.get("label") or zone.get("id") or "Climate")
            screen.blit(font.render(label[:16], True, (196, 210, 228)), (row.x + 22, row.y))
            screen.blit(font.render(f"{fraction * 100.0:.0f}%", True, (154, 166, 188)), (row.right - 42, row.y))
            y += 24
            if y > sidebar.bottom - 84:
                break

        y += 8
        if water_cycle.get("river_count"):
            screen.blit(font.render("River Sources", True, (232, 238, 246)), (sidebar.x + 12, y))
            y += 26
            for river in (water_cycle.get("rivers") or [])[:4]:
                if not isinstance(river, dict):
                    continue
                text = f"{river.get('id', 'river')} | {float(river.get('source_elevation_m', 0.0)):.0f} m | {river.get('mouth', 'basin')}"
                screen.blit(font.render(text, True, (154, 202, 238)), (sidebar.x + 18, y))
                y += 20
                if y > sidebar.bottom - 42:
                    break

        can_complete = bool(getattr(sim, "_world_gen_can_finish", lambda: False)())
        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 178, 30)
        complete_rect = pygame.Rect(save_rect.right + 12, panel.bottom - 48, 204, 30) if can_complete else None
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, "Regenerate Cycle", primary=True)
        if complete_rect is not None:
            self._draw_panel_button(screen, font, complete_rect, "Complete Worldgen")
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            status_x = (complete_rect.right + 18) if complete_rect is not None else (save_rect.right + 18)
            screen.blit(font.render(status, True, (178, 210, 244)), (status_x, panel.bottom - 41))
        hint = font.render("Enter regenerates this water cycle. Complete Worldgen finalizes the planet for map and biosphere work.", True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, complete_rect=complete_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)

    def _draw_heightmap_panel(self, screen, sim, payload, camera):
        font = self.app_view.default_font
        panel = pygame.Rect(34, 74, screen.get_width() - 68, screen.get_height() - 130)
        pygame.draw.rect(screen, (18, 21, 28), panel)
        pygame.draw.rect(screen, (188, 196, 212), panel, 1)

        selected_planet = payload.get("selected_planet") or {}
        heightmap = payload.get("heightmap_model") or {}
        terrain = payload.get("terrain_seed_model") or {}
        title = f"World Generation: {selected_planet.get('name', selected_planet.get('id', 'Planet'))} Heightmap"
        screen.blit(font.render(title, True, (244, 244, 244)), (panel.x + 16, panel.y + 12))
        subtitle = "Height markers are contour lines from the saved heightfield seed; marker interval tightens as zoom increases."
        screen.blit(font.render(subtitle, True, (158, 170, 190)), (panel.x + 16, panel.y + 34))

        sidebar_w = 330
        preview = pygame.Rect(panel.x + 16, panel.y + 70, panel.width - sidebar_w - 48, panel.height - 150)
        sidebar = pygame.Rect(preview.right + 24, preview.y, sidebar_w, preview.height)
        pygame.draw.rect(screen, (6, 8, 12), preview)
        pygame.draw.rect(screen, (104, 116, 138), preview, 1)
        pygame.draw.rect(screen, (25, 29, 40), sidebar)
        pygame.draw.rect(screen, (96, 108, 132), sidebar, 1)

        canvas_w = max(1, int(heightmap.get("width_px", 2048) or 2048))
        canvas_h = max(1, int(heightmap.get("height_px", 1024) or 1024))
        preview_scale = min(preview.width / canvas_w, preview.height / canvas_h)
        preview_zoom = max(1.0, float(getattr(sim, "heightmap_preview_zoom", 1.0) or 1.0))
        requested_interval = height_marker_interval_m(preview_scale * preview_zoom)
        interval = display_contour_interval_m(heightmap, requested_interval, max_levels=18)

        map_w = int(canvas_w * preview_scale * preview_zoom)
        map_h = int(canvas_h * preview_scale * preview_zoom)
        map_rect = pygame.Rect(0, 0, map_w, map_h)
        map_rect.center = preview.center
        previous_clip = screen.get_clip()
        screen.set_clip(preview)
        pygame.draw.rect(screen, (10, 13, 18), map_rect)
        screen.set_clip(previous_clip)
        material_model = payload.get("natural_material_model") if isinstance(payload.get("natural_material_model"), dict) else None
        self._draw_heightmap_land_ocean(
            screen,
            map_rect,
            preview,
            heightmap,
            selected_planet=selected_planet,
            material_model=material_model,
        )
        previous_clip = screen.get_clip()
        screen.set_clip(preview)
        pygame.draw.rect(screen, (74, 86, 106), map_rect, 1)
        screen.set_clip(previous_clip)
        self._draw_heightmap_contours(screen, font, map_rect, preview, heightmap, interval)

        y = sidebar.y + 14
        screen.blit(font.render("Heightfield Storage", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 32
        storage = heightmap.get("storage") if isinstance(heightmap.get("storage"), dict) else {}
        sample = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
        hypsometry = heightmap.get("hypsometry_summary") if isinstance(heightmap.get("hypsometry_summary"), dict) else {}
        tectonic_model = selected_planet.get("tectonic_model") if isinstance(selected_planet.get("tectonic_model"), dict) else {}
        simulated_age = (
            heightmap.get("simulated_age_myr")
            or selected_planet.get("simulated_geology_age_myr")
            or tectonic_model.get("age_myr")
            or 0.0
        )
        rows = [
            ("Projection", heightmap.get("projection", "unknown")),
            ("Canvas", f"{canvas_w} x {canvas_h} px"),
            ("Samples", f"{sample.get('width', 0)} x {sample.get('height', 0)}"),
            ("Chunks", f"{storage.get('chunk_cols', 0)} x {storage.get('chunk_rows', 0)}"),
            ("Chunk size", f"{storage.get('chunk_width_px', 0)} x {storage.get('chunk_height_px', 0)} px"),
            ("Simulated age", f"{float(simulated_age or 0.0):.1f} Myr"),
            ("Elevation", f"{float(heightmap.get('min_elevation_m', 0.0)):.0f} to {float(heightmap.get('max_elevation_m', 0.0)):.0f} m"),
            ("Land", f"{float(hypsometry.get('land_fraction', 0.0)) * 100.0:.0f}%"),
            ("Ocean", f"{float(hypsometry.get('ocean_fraction', 0.0)) * 100.0:.0f}%"),
            ("Ice", f"{float(hypsometry.get('ice_fraction', 0.0)) * 100.0:.0f}%"),
            ("Broad plains", f"{float(hypsometry.get('broad_plain_fraction', 0.0)) * 100.0:.0f}%"),
            ("Mountains", f"{float(hypsometry.get('mountain_fraction_above_2000m', 0.0)) * 100.0:.0f}% >2km"),
            ("Preview zoom", f"x{preview_zoom:.2f}"),
            ("Marker interval", f"{interval} m"),
            ("Requested", f"{requested_interval} m"),
        ]
        for label, value in rows:
            row_rect = pygame.Rect(sidebar.x + 12, y, sidebar.width - 24, 24)
            y = self._draw_status_row(screen, font, row_rect, label, value)

        y += 12
        heatmap_model = payload.get("material_heatmap_model") if isinstance(payload.get("material_heatmap_model"), dict) else {}
        heatmap_layers = heatmap_model.get("layers") if isinstance(heatmap_model.get("layers"), list) else []
        if heatmap_layers:
            screen.blit(font.render("Material Provinces", True, (232, 238, 246)), (sidebar.x + 12, y))
            y += 28
            for layer in heatmap_layers[:4]:
                color = self._coerce_rgb(layer.get("display_color"), fallback=(154, 166, 188))
                coverage = max(0.0, min(1.0, float(layer.get("coverage_fraction", layer.get("mean_intensity", 0.0)) or 0.0)))
                row = pygame.Rect(sidebar.x + 12, y, sidebar.width - 24, 18)
                pygame.draw.rect(screen, color, pygame.Rect(row.x, row.y + 2, 14, 14))
                bar_x = row.x + 132
                bar_w = max(1, row.width - 170)
                pygame.draw.rect(screen, (42, 48, 60), pygame.Rect(bar_x, row.y + 5, bar_w, 8))
                pygame.draw.rect(screen, color, pygame.Rect(bar_x, row.y + 5, int(bar_w * coverage), 8))
                label = str(layer.get("name") or layer.get("material_id") or "Material")
                screen.blit(font.render(label[:17], True, (196, 210, 228)), (row.x + 22, row.y))
                y += 21
            y += 4

        y += 8
        screen.blit(font.render("Reuse Contract", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 28
        contract = storage.get("consumer_contract", "chunks are addressed by projection pixel bbox")
        for wrapped in self._wrap_text(contract, font, sidebar.width - 24):
            screen.blit(font.render(wrapped, True, (154, 166, 188)), (sidebar.x + 12, y))
            y += 20

        y += 12
        recipe = terrain.get("map_recipe") if isinstance(terrain.get("map_recipe"), list) else []
        screen.blit(font.render("Next", True, (232, 238, 246)), (sidebar.x + 12, y))
        y += 26
        for step in recipe[-4:]:
            for wrapped in self._wrap_text(f"- {str(step).replace('_', ' ')}", font, sidebar.width - 30):
                screen.blit(font.render(wrapped, True, (154, 166, 188)), (sidebar.x + 18, y))
                y += 19

        can_finish = bool(getattr(sim, "_world_gen_can_finish", lambda: False)())
        can_advance_tectonics = bool(getattr(sim, "_heightmap_can_advance_tectonics", lambda: False)())
        can_complete = can_finish and not can_advance_tectonics
        button_label = "Advance Tectonics" if can_advance_tectonics else "Generate Water Cycle"
        back_rect = pygame.Rect(panel.x + 16, panel.bottom - 48, 92, 30)
        save_rect = pygame.Rect(back_rect.right + 12, panel.bottom - 48, 188, 30)
        complete_rect = pygame.Rect(save_rect.right + 12, panel.bottom - 48, 204, 30) if can_complete else None
        self._draw_panel_button(screen, font, back_rect, "Back")
        self._draw_panel_button(screen, font, save_rect, button_label, primary=True)
        if complete_rect is not None:
            self._draw_panel_button(screen, font, complete_rect, "Complete Worldgen")
        space_rect = self._draw_space_jump_button(screen, font, panel)
        status = payload.get("commit_status") or ""
        if status:
            status_x = (complete_rect.right + 18) if complete_rect is not None else (save_rect.right + 18)
            screen.blit(font.render(status, True, (178, 210, 244)), (status_x, panel.bottom - 41))
        if can_advance_tectonics:
            hint_text = "Enter advances tectonics 25 Myr. Mouse wheel over preview zooms heightmap. Esc exits selected planet."
        elif can_complete:
            hint_text = "Advance Heightmap simulates 25 Myr. Complete Worldgen finalizes this planet. Esc exits selected planet."
        else:
            hint_text = "Enter generates rivers and climate zones from this heightmap. Mouse wheel over preview zooms."
        hint = font.render(hint_text, True, (142, 152, 170))
        screen.blit(hint, (panel.x + 16, panel.bottom - 76))

        sim.set_crust_ui_rects(save_rect=save_rect, complete_rect=complete_rect, back_rect=back_rect, space_rect=space_rect)
        sim.set_seed_field_rects({})
        sim.set_control_panel_rect(panel)
        sim.set_heightmap_preview_rect(preview)

    def _draw_seed_panel_fields(self, screen, sim, payload, panel):
        font = self.app_view.default_font
        field_rects = {}
        y = panel.y + 46
        for field in payload.get("seed_fields", []):
            label = font.render(field["label"], True, (190, 200, 216))
            screen.blit(label, (panel.x + 12, y))
            input_rect = pygame.Rect(panel.x + 196, y - 4, 170, 24)
            field_rects[field["id"]] = input_rect
            fill = (38, 48, 68) if field.get("active") else (30, 34, 44)
            border = (188, 212, 244) if field.get("active") else (92, 102, 122)
            pygame.draw.rect(screen, fill, input_rect)
            pygame.draw.rect(screen, border, input_rect, 1)
            value = field.get("text") or ""
            placeholder = "value"
            value_surface = font.render(value or placeholder, True, (238, 238, 238) if value else (128, 138, 154))
            screen.blit(value_surface, (input_rect.x + 6, input_rect.y + 4))
            y += 32

        sim.set_seed_field_rects(field_rects)
        sim.set_control_panel_rect(panel)

        selected_planet = payload.get("selected_planet") or {}
        orbit_bits = []
        if selected_planet.get("periapsis_au") is not None:
            orbit_bits.append(f"peri {float(selected_planet.get('periapsis_au')):.3f} AU")
        if selected_planet.get("apoapsis_au") is not None:
            orbit_bits.append(f"apo {float(selected_planet.get('apoapsis_au')):.3f} AU")
        orbit_text = " | ".join(orbit_bits) if orbit_bits else "Orbit locked"
        orbit_surface = font.render(orbit_text, True, (196, 210, 226))
        screen.blit(orbit_surface, (panel.x + 12, panel.bottom - 84))

        status = payload.get("commit_status") or ""
        if status:
            status_surface = font.render(status, True, (178, 210, 244))
            screen.blit(status_surface, (panel.x + 12, panel.bottom - 58))

        hint_text = "Enter saves seed. Esc returns to orbit draft. Click empty space to place another planet."
        hint = font.render(hint_text, True, (142, 152, 170))
        max_hint_w = panel.width - 24
        if hint.get_width() > max_hint_w:
            hint_text = "Enter saves seed. Esc returns. Click empty space for another planet."
            hint = font.render(hint_text, True, (142, 152, 170))
        screen.blit(hint, (panel.x + 12, panel.bottom - 28))

    def draw(self, screen, sim):
        payload = sim.get_preview_payload()
        model = payload.get("model", {})
        camera = self.app_view.camera

        self._draw_habitable_zone(screen, camera, model)
        self._draw_reference_bodies(screen, camera, sim, payload)
        self._draw_candidate_orbit(screen, camera, model)
        self._draw_star(screen, camera, payload)
        self._draw_input_panel(screen, sim, payload, camera)
