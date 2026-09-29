import pygame


class PersonRenderer:
    """Draw the first embodied person-control test room."""

    BACKGROUND = (10, 13, 18)
    FLOOR = (29, 34, 41)
    FLOOR_BORDER = (108, 121, 139)
    GRID = (42, 49, 59)
    TEXT = (226, 232, 239)

    def __init__(self, app_view):
        self.app_view = app_view
        self._text_cache = {}

    def _text(self, value, color=None):
        color = tuple(color or self.TEXT)
        key = (str(value), color)
        surface = self._text_cache.get(key)
        if surface is None:
            surface = self.app_view.default_font.render(str(value), True, color)
            self._text_cache[key] = surface
            if len(self._text_cache) > 256:
                self._text_cache.pop(next(iter(self._text_cache)))
        return surface

    def _world_rect(self, camera, min_x, min_y, max_x, max_y):
        top_left = camera.world_to_screen((min_x, min_y))
        bottom_right = camera.world_to_screen((max_x, max_y))
        if top_left is None or bottom_right is None:
            return None
        return pygame.Rect(
            min(top_left[0], bottom_right[0]),
            min(top_left[1], bottom_right[1]),
            abs(bottom_right[0] - top_left[0]),
            abs(bottom_right[1] - top_left[1]),
        )

    @staticmethod
    def _spindly_geometry(ground_center, height_px, body_shape=None):
        """Canonical long, narrow human proportions shared by every person view."""
        x, ground_y = ground_center
        shape = body_shape if isinstance(body_shape, dict) else {}
        def value(key):
            try:
                return max(0.0, min(1.0, float(shape.get(key, 0.5))))
            except (TypeError, ValueError):
                return 0.5
        height = max(24, int(height_px * (0.90 + 0.20 * value("stature"))))
        unit = height / 360.0
        top = ground_y - height
        head_scale = 0.82 + 0.36 * value("head_size")
        head_w = 36 * unit * head_scale
        head_h = 48 * unit * head_scale
        head = pygame.Rect(
            round(x - head_w / 2), round(top),
            max(4, round(head_w)), max(6, round(head_h)),
        )
        shoulder_y = round(head.bottom + 13 * unit)
        hip_y = round(top + height * (0.56 - 0.14 * value("leg_length")))
        shoulder_half = (18 + 10 * value("shoulder_width")) * unit
        torso_top_half = (10 + 11 * value("torso_width")) * unit
        torso_bottom_half = (7 + 7 * value("torso_width")) * unit
        arm_end_y = round(shoulder_y + height * (0.22 + 0.14 * value("arm_length")))
        return {
            "height": height,
            "unit": unit,
            "head": head,
            "neck": ((round(x), head.bottom - max(1, round(2 * unit))), (round(x), shoulder_y)),
            "shoulders": ((round(x - shoulder_half), shoulder_y), (round(x + shoulder_half), shoulder_y)),
            "torso": (
                (round(x - torso_top_half), shoulder_y),
                (round(x + torso_top_half), shoulder_y),
                (round(x + torso_bottom_half), hip_y),
                (round(x - torso_bottom_half), hip_y),
            ),
            "left_arm": ((round(x - shoulder_half * .92), shoulder_y), (round(x - shoulder_half * 1.04), arm_end_y)),
            "right_arm": ((round(x + shoulder_half * .92), shoulder_y), (round(x + shoulder_half * 1.06), arm_end_y)),
            "left_leg": ((round(x - 6 * unit), hip_y), (round(x - 11 * unit), ground_y)),
            "right_leg": ((round(x + 6 * unit), hip_y), (round(x + 17 * unit), ground_y - max(1, round(7 * unit)))),
            "hip_y": hip_y,
        }

    @classmethod
    def _draw_spindly_figure(cls, screen, ground_center, height_px, skin_color, body_shape=None, clothing=None, face=False):
        geometry = cls._spindly_geometry(ground_center, height_px, body_shape)
        unit = geometry["unit"]
        outline = (7, 9, 13)
        limb_outline = max(3, round(10 * unit))
        limb_width = max(1, round(5 * unit))
        skin_width = max(1, round(4 * unit))

        profile = (clothing or {}).get("appearance_profile") or {}
        silhouette = str(profile.get("silhouette") or "").casefold()
        primary = cls._color(profile.get("primary_color"), (50, 64, 80))
        accent = cls._color(profile.get("accent_color"), (218, 216, 205))
        leg_color = primary if silhouette == "suit" else skin_color
        for key in ("left_leg", "right_leg"):
            pygame.draw.line(screen, outline, *geometry[key], limb_outline)
            pygame.draw.line(screen, leg_color, *geometry[key], limb_width)
        for key in ("left_arm", "right_arm"):
            pygame.draw.line(screen, outline, *geometry[key], limb_outline)
            pygame.draw.line(screen, skin_color, *geometry[key], skin_width)

        pygame.draw.polygon(screen, outline, geometry["torso"])
        inset = max(1, round(3 * unit))
        torso = geometry["torso"]
        pygame.draw.polygon(screen, skin_color, (
            (torso[0][0] + inset, torso[0][1] + inset),
            (torso[1][0] - inset, torso[1][1] + inset),
            (torso[2][0] - inset, torso[2][1] - inset),
            (torso[3][0] + inset, torso[3][1] - inset),
        ))

        if silhouette == "toga":
            torso = geometry["torso"]
            skirt_y = round(geometry["hip_y"] + (ground_center[1] - geometry["hip_y"]) * .34)
            pygame.draw.polygon(screen, outline, (
                torso[0], torso[1], (torso[2][0] + round(18 * unit), skirt_y),
                (torso[3][0] - round(18 * unit), skirt_y),
            ))
            pygame.draw.polygon(screen, primary, (
                (torso[0][0] + inset, torso[0][1] + inset), torso[1],
                (torso[2][0] + round(14 * unit), skirt_y - inset),
                (torso[3][0] - round(14 * unit), skirt_y - inset),
            ))
            pygame.draw.line(screen, accent, torso[0], torso[2], max(1, round(4 * unit)))
        elif silhouette == "suit":
            pygame.draw.polygon(screen, primary, geometry["torso"])
            x = geometry["head"].centerx
            pygame.draw.polygon(screen, accent, (
                (x - round(5 * unit), geometry["torso"][0][1] + inset),
                (x + round(5 * unit), geometry["torso"][0][1] + inset),
                (x, geometry["hip_y"] - round(10 * unit)),
            ))
            for key in ("left_arm", "right_arm"):
                start, end = geometry[key]
                sleeve_end = (round(start[0] + (end[0] - start[0]) * .82), round(start[1] + (end[1] - start[1]) * .82))
                pygame.draw.line(screen, outline, start, sleeve_end, limb_outline)
                pygame.draw.line(screen, primary, start, sleeve_end, limb_width)
        pygame.draw.line(screen, outline, *geometry["neck"], limb_outline)
        pygame.draw.line(screen, skin_color, *geometry["neck"], skin_width)
        pygame.draw.ellipse(screen, outline, geometry["head"])
        head_inner = geometry["head"].inflate(-max(2, round(6 * unit)), -max(2, round(6 * unit)))
        pygame.draw.ellipse(screen, skin_color, head_inner)

        if face and geometry["head"].width >= 18:
            eye_y = geometry["head"].y + round(20 * unit)
            eye_dx = max(3, round(7 * unit))
            eye_radius = max(1, round(2.5 * unit))
            pygame.draw.circle(screen, (32, 25, 22), (geometry["head"].centerx - eye_dx, eye_y), eye_radius)
            pygame.draw.circle(screen, (32, 25, 22), (geometry["head"].centerx + eye_dx, eye_y), eye_radius)
        return geometry

    @staticmethod
    def _color(value, fallback):
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) == 6:
                try:
                    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
                except ValueError:
                    pass
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(channel))) for channel in value[:3])
            except (TypeError, ValueError):
                pass
        return tuple(fallback)

    def _draw_floor(self, screen, camera, bounds):
        floor = self._world_rect(
            camera,
            bounds["min_x"],
            bounds["min_y"],
            bounds["max_x"],
            bounds["max_y"],
        )
        if floor is None:
            return
        pygame.draw.rect(screen, self.FLOOR, floor)
        pygame.draw.rect(screen, self.FLOOR_BORDER, floor, 2)

        for world_x in range(int(bounds["min_x"]) + 2, int(bounds["max_x"]), 2):
            start = camera.world_to_screen((world_x, bounds["min_y"]))
            end = camera.world_to_screen((world_x, bounds["max_y"]))
            if start is not None and end is not None:
                pygame.draw.line(screen, self.GRID, start, end, 1)
        for world_y in range(int(bounds["min_y"]) + 1, int(bounds["max_y"]), 2):
            start = camera.world_to_screen((bounds["min_x"], world_y))
            end = camera.world_to_screen((bounds["max_x"], world_y))
            if start is not None and end is not None:
                pygame.draw.line(screen, self.GRID, start, end, 1)

    def _draw_site_layout(self, screen, camera, payload):
        for zone in payload.get("terrain_zones", []):
            if not isinstance(zone, dict):
                continue
            bounds = zone.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            color = self._color(zone.get("color"), (43, 64, 52))
            pygame.draw.rect(screen, color, rect)
            label = self._text(zone.get("label") or zone.get("terrain_class") or "terrain", (159, 177, 160))
            screen.blit(label, (rect.x + 10, rect.y + 8))

        for landmark in payload.get("site_landmarks", []):
            if not isinstance(landmark, dict):
                continue
            bounds = landmark.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            landmark_class = str(landmark.get("landmark_class") or "").casefold()
            color = self._color(landmark.get("color"), (82, 78, 68))
            pygame.draw.rect(screen, color, rect, border_radius=3)
            if landmark_class == "road":
                pygame.draw.line(screen, (176, 166, 139), rect.midtop, rect.midbottom, max(2, rect.width // 5))
                pygame.draw.line(screen, (218, 204, 163), rect.midtop, rect.midbottom, 1)
            label = self._text(landmark.get("label") or landmark_class or "landmark", (215, 209, 190))
            screen.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 5)))

        for structure in payload.get("structures", []):
            bounds = structure.get("bounds") or {}
            rect = self._world_rect(
                camera,
                bounds.get("min_x", 0),
                bounds.get("min_y", 0),
                bounds.get("max_x", 0),
                bounds.get("max_y", 0),
            )
            if rect is None:
                continue
            color = self._color(structure.get("color"), (59, 64, 70))
            footprint = [camera.world_to_screen(tuple(point)) for point in structure.get("footprint") or []]
            if len(footprint) >= 3 and all(point is not None for point in footprint):
                # Blueprint buildings: real outline, rooms slightly lighter.
                pygame.draw.polygon(screen, color, footprint)
                room_color = tuple(min(255, channel + 12) for channel in color[:3])
                for room in structure.get("rooms") or []:
                    room_points = [camera.world_to_screen(tuple(point)) for point in room.get("points") or []]
                    if len(room_points) >= 3 and all(point is not None for point in room_points):
                        pygame.draw.polygon(screen, room_color, room_points)
            else:
                pygame.draw.rect(screen, color, rect)
            label = self._text(structure.get("label") or "Building", (205, 211, 216))
            screen.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 8)))

        for start, end in payload.get("wall_segments", []):
            screen_start = camera.world_to_screen(start)
            screen_end = camera.world_to_screen(end)
            if screen_start is None or screen_end is None:
                continue
            pygame.draw.line(screen, (12, 15, 19), screen_start, screen_end, 8)
            pygame.draw.line(screen, (156, 163, 168), screen_start, screen_end, 3)

    def _draw_site_people(self, screen, camera, payload):
        for resident in payload.get("site_people", []):
            if resident.get("controlled"):
                continue
            center = camera.world_to_screen(resident.get("position") or (0, 0))
            if center is None:
                continue
            sex = str(resident.get("sex") or "").casefold()
            detail = str(resident.get("simulation_detail") or "full").casefold()
            presence_kind = str(resident.get("presence_kind") or "authored").casefold()
            if presence_kind == "vehicle":
                self._draw_vehicle_presence(screen, camera, resident, center, payload)
                continue
            if detail == "aggregate":
                color = (144, 132, 101)
                radius = 12
            elif detail == "lightweight":
                color = (180, 154, 98)
                radius = 6
            elif "representative" in presence_kind:
                color = (116, 180, 145)
                radius = 7
            elif "visitor" in presence_kind:
                color = (194, 151, 103)
                radius = 7
            else:
                color = tuple((resident.get("appearance") or {}).get("skin_color") or (
                    (194, 126, 151) if sex == "female" else (112, 157, 201) if sex == "male" else (157, 151, 121)
                ))
                radius = 7
            selected = resident.get("entity_id") == payload.get("selected_presence_id")
            hovered = resident.get("entity_id") == payload.get("hover_presence_id")
            if selected or hovered:
                pygame.draw.ellipse(
                    screen,
                    (238, 209, 111) if selected else (112, 201, 230),
                    (center[0] - radius - 5, center[1] - radius * 5, radius * 2 + 10, radius * 5 + 8),
                    2,
                )
            self._draw_spindly_figure(
                screen, center, radius * 5, color,
                body_shape=(resident.get("appearance") or {}).get("body_shape"),
                clothing=resident.get("clothing"),
            )
            if detail == "lightweight":
                pygame.draw.circle(screen, (233, 218, 168), center, 2, 1)
            label = self._text(resident.get("label") or "Worker", (194, 202, 211))
            screen.blit(label, label.get_rect(midtop=(center[0], center[1] + 5)))

    def _draw_vehicle_presence(self, screen, camera, resident, center, payload):
        x, y = center
        selected = resident.get("entity_id") == payload.get("selected_presence_id")
        hovered = resident.get("entity_id") == payload.get("hover_presence_id")
        if selected or hovered:
            pygame.draw.rect(
                screen, (238, 209, 111) if selected else (112, 201, 230),
                (x - 16, y - 10, 32, 20), 2, border_radius=3,
            )
        pygame.draw.rect(screen, (10, 13, 18), (x - 14, y - 8, 28, 16), border_radius=3)
        pygame.draw.rect(screen, (149, 111, 66), (x - 12, y - 7, 24, 14), border_radius=2)
        pygame.draw.circle(screen, (30, 33, 38), (x - 7, y + 7), 3)
        pygame.draw.circle(screen, (30, 33, 38), (x + 7, y + 7), 3)
        label = self._text(resident.get("label") or "Vehicle", (194, 202, 211))
        screen.blit(label, label.get_rect(midtop=(x, y + 14)))

    def _draw_bed_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 22, y - 10, 44, 21), border_radius=3)
        pygame.draw.rect(screen, (225, 231, 238), (x - 18, y - 7, 12, 8), border_radius=2)
        pygame.draw.line(screen, (22, 25, 31), (x - 22, y + 12), (x - 22, y + 17), 3)
        pygame.draw.line(screen, (22, 25, 31), (x + 22, y + 12), (x + 22, y + 17), 3)

    def _draw_food_icon(self, screen, center, color):
        x, y = center
        pygame.draw.circle(screen, color, center, 18)
        pygame.draw.arc(screen, (236, 231, 212), (x - 13, y - 8, 26, 19), 0, 3.14, 3)
        pygame.draw.line(screen, (236, 231, 212), (x - 10, y + 7), (x + 10, y + 7), 3)

    def _draw_job_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 19, y - 16, 38, 32), border_radius=3)
        pygame.draw.rect(screen, (32, 38, 43), (x - 8, y - 22, 16, 10), 3, border_radius=3)
        pygame.draw.line(screen, (225, 231, 225), (x - 12, y), (x + 12, y), 3)

    def _draw_kitchen_icon(self, screen, center, color):
        x, y = center
        pygame.draw.rect(screen, color, (x - 23, y - 17, 46, 34), border_radius=4)
        pygame.draw.rect(screen, (31, 39, 45), (x - 17, y - 11, 20, 11), border_radius=2)
        pygame.draw.circle(screen, (220, 231, 231), (x - 7, y - 6), 3, 1)
        pygame.draw.rect(screen, (42, 48, 54), (x + 7, y - 11, 11, 22), border_radius=2)
        pygame.draw.circle(screen, (229, 216, 166), (x + 12, y - 5), 2)
        pygame.draw.line(screen, (226, 235, 235), (x - 18, y + 7), (x - 3, y + 7), 2)

    def _draw_target_icon(self, screen, center, color):
        pygame.draw.circle(screen, color, center, 20)
        pygame.draw.circle(screen, (234, 224, 210), center, 13, 3)
        pygame.draw.circle(screen, color, center, 6)

    def _draw_point(self, screen, camera, point, payload):
        center = camera.world_to_screen(point["position"])
        if center is None:
            return
        point_id = point["id"]
        color = tuple(point.get("color") or (160, 160, 160))

        if point_id == "bed":
            self._draw_bed_icon(screen, center, color)
        elif point_id == "food":
            self._draw_food_icon(screen, center, color)
        elif point_id == "job":
            self._draw_job_icon(screen, center, color)
        elif point_id == "kitchen":
            self._draw_kitchen_icon(screen, center, color)
        else:
            self._draw_target_icon(screen, center, color)

        if point_id == payload.get("active_point_id"):
            pygame.draw.circle(screen, (245, 214, 108), center, 29, 3)
        elif point_id == payload.get("hover_point_id"):
            pygame.draw.circle(screen, (122, 214, 239), center, 27, 2)

        label = self._text(point.get("label") or point_id)
        screen.blit(label, label.get_rect(midtop=(center[0], center[1] + 28)))
        tier = self._text(point.get("maslow_tier", ""), (145, 157, 172))
        screen.blit(tier, tier.get_rect(midtop=(center[0], center[1] + 46)))

    def _draw_route(self, screen, camera, payload):
        destination = payload.get("destination")
        if destination is None:
            return
        points = [payload["position"], *(payload.get("route_points") or []), destination]
        screen_points = [camera.world_to_screen(point) for point in points]
        screen_points = [point for point in screen_points if point is not None]
        if len(screen_points) < 2:
            return
        route_color = (
            (104, 190, 232)
            if payload.get("control_mode") == "direct"
            else (220, 196, 108)
        )
        pygame.draw.lines(screen, (18, 21, 26), False, screen_points, 6)
        pygame.draw.lines(screen, route_color, False, screen_points, 2)
        pygame.draw.circle(screen, route_color, screen_points[-1], 5, 2)

    def _draw_person(self, screen, camera, payload):
        center = camera.world_to_screen(payload["position"])
        if center is None:
            return
        color = tuple((payload.get("appearance") or {}).get("skin_color") or (174, 119, 82))
        height_px = round(max(32, min(68, 1.75 * float(getattr(camera, "zoom", 28.0)))))
        self._draw_spindly_figure(
            screen, center, height_px, color,
            body_shape=(payload.get("appearance") or {}).get("body_shape"),
            clothing=payload.get("clothing"),
        )
        if payload.get("control_mode") == "direct":
            pygame.draw.ellipse(screen, (112, 201, 230), (center[0] - 13, center[1] - 5, 26, 10), 2)

    def _draw_editor_mannequin(self, screen, center, skin_color, body_shape, clothing):
        self._draw_spindly_figure(
            screen, center, 390, skin_color,
            body_shape=body_shape, clothing=clothing, face=True,
        )

    def _draw_person_editor(self, screen, sim):
        from simulations.person.person_editor import editor_appearance
        from simulations.person.person_genetics import BODY_TRAITS, SKIN_TONES

        state = sim._ensure_person_editor()
        decoded = editor_appearance(state)
        tone = decoded["skin_tone"]
        width, height = screen.get_size()
        screen.fill((11, 15, 21))
        font = self.app_view.default_font
        title_font = pygame.font.SysFont("consolas", 24, bold=True)
        small = pygame.font.SysFont("consolas", 13)
        tiny = pygame.font.SysFont("consolas", 11)
        screen.blit(title_font.render(f"Person Editor | {sim.get_person_name()}", True, (232, 238, 246)), (22, 20))
        screen.blit(small.render(
            "Body proportions and skin tone decode from one DNA string; ordinary clothing items layer over the naked body.",
            True, (157, 176, 198)), (22, 54))

        workspace = pygame.Rect(20, 84, max(560, width - 270), max(430, height - 188))
        pygame.draw.rect(screen, (17, 23, 32), workspace, border_radius=8)
        pygame.draw.rect(screen, (58, 76, 99), workspace, 1, border_radius=8)
        split_x = workspace.x + int(workspace.width * .56)
        pygame.draw.line(screen, (48, 62, 80), (split_x, workspace.y + 16), (split_x, workspace.bottom - 16), 1)

        mannequin_center = (workspace.x + int(workspace.width * .28), workspace.bottom - 56)
        clothing = sim.get_person_editor_clothing()
        self._draw_editor_mannequin(
            screen, mannequin_center, tuple(tone["color"]), decoded["body_shape"], clothing,
        )
        clothing_label = (clothing or {}).get("pretty_name") or (clothing or {}).get("name") or "Naked"
        label = font.render(f"{tone['label']} skin | {clothing_label}", True, (225, 229, 235))
        screen.blit(label, label.get_rect(center=(mannequin_center[0], workspace.bottom - 34)))

        right_x = split_x + 24
        screen.blit(font.render("GENETIC TRAITS", True, (220, 226, 236)), (right_x, workspace.y + 24))
        hitboxes = []
        screen.blit(tiny.render("Skin tone", True, (151, 170, 194)), (right_x, workspace.y + 51))
        card_w = max(104, min(150, (workspace.right - right_x - 22) // 3 - 8))
        for index, option in enumerate(SKIN_TONES):
            rect = pygame.Rect(right_x + index * (card_w + 10), workspace.y + 68, card_w, 50)
            active = option["id"] == tone["id"]
            pygame.draw.rect(screen, (38, 51, 68) if active else (24, 31, 42), rect, border_radius=5)
            pygame.draw.rect(screen, (231, 199, 105) if active else (75, 92, 114), rect, 2 if active else 1, border_radius=5)
            pygame.draw.circle(screen, option["color"], (rect.x + 22, rect.centery), 11)
            text = small.render(option["label"], True, (230, 234, 240))
            screen.blit(text, text.get_rect(midleft=(rect.x + 40, rect.centery)))
            hitboxes.append({"kind": "skin_tone", "tone_id": option["id"], "rect": rect})

        shape_y = workspace.y + 136
        screen.blit(tiny.render("Body shape loci", True, (151, 170, 194)), (right_x, shape_y))
        for index, trait in enumerate(BODY_TRAITS):
            row_y = shape_y + 20 + index * 27
            value = decoded["body_shape"][trait["id"]]
            screen.blit(tiny.render(trait["label"], True, (210, 219, 231)), (right_x, row_y + 5))
            minus = pygame.Rect(right_x + 118, row_y, 24, 22)
            track = pygame.Rect(minus.right + 6, row_y + 9, max(60, workspace.right - minus.right - 70), 5)
            plus = pygame.Rect(track.right + 7, row_y, 24, 22)
            for rect, text_value, delta in ((minus, "−", -.05), (plus, "+", .05)):
                pygame.draw.rect(screen, (35, 47, 62), rect, border_radius=3)
                pygame.draw.rect(screen, (77, 99, 125), rect, 1, border_radius=3)
                screen.blit(small.render(text_value, True, (229, 234, 241)), small.render(text_value, True, (229, 234, 241)).get_rect(center=rect.center))
                hitboxes.append({"kind": "body_trait", "trait_id": trait["id"], "delta": delta, "rect": rect})
            pygame.draw.line(screen, (66, 79, 96), track.midleft, track.midright, 3)
            knob_x = round(track.x + value * track.width)
            pygame.draw.circle(screen, (224, 194, 102), (knob_x, track.centery), 5)

        clothing_y = shape_y + 190
        screen.blit(tiny.render("Clothing items (not DNA)", True, (151, 170, 194)), (right_x, clothing_y))
        clothing_options = [(None, "Naked")]
        for clothing_id in ("item_test_toga", "item_test_suit"):
            entity = sim.get_person(clothing_id) or {}
            clothing_options.append((clothing_id, entity.get("pretty_name") or entity.get("name") or clothing_id))
        clothing_w = max(92, (workspace.right - right_x - 22) // 3 - 6)
        for index, (clothing_id, clothing_name) in enumerate(clothing_options):
            rect = pygame.Rect(right_x + index * (clothing_w + 8), clothing_y + 19, clothing_w, 38)
            active = state.get("working_clothing_id") == clothing_id
            pygame.draw.rect(screen, (49, 61, 78) if active else (25, 32, 43), rect, border_radius=4)
            pygame.draw.rect(screen, (231, 199, 105) if active else (75, 92, 114), rect, 2 if active else 1, border_radius=4)
            rendered = tiny.render(str(clothing_name), True, (231, 235, 241))
            screen.blit(rendered, rendered.get_rect(center=rect.center))
            hitboxes.append({"kind": "clothing", "clothing_id": clothing_id, "rect": rect})

        dna_y = workspace.y + 409
        screen.blit(font.render("DNA STRING", True, (220, 226, 236)), (right_x, dna_y))
        dna_rect = pygame.Rect(right_x, dna_y + 27, workspace.right - right_x - 22, 57)
        pygame.draw.rect(screen, (8, 12, 18), dna_rect, border_radius=4)
        pygame.draw.rect(screen, (62, 80, 104), dna_rect, 1, border_radius=4)
        dna = state.get("working_dna", "")
        midpoint = (len(dna) + 1) // 2
        screen.blit(tiny.render(dna[:midpoint], True, (155, 213, 190)), (dna_rect.x + 10, dna_rect.y + 9))
        screen.blit(tiny.render(dna[midpoint:], True, (155, 213, 190)), (dna_rect.x + 10, dna_rect.y + 31))

        button_y = workspace.bottom - 48
        save_rect = pygame.Rect(right_x, button_y, 116, 34)
        revert_rect = pygame.Rect(save_rect.right + 10, button_y, 116, 34)
        sim_rect = pygame.Rect(revert_rect.right + 10, button_y, 138, 34)
        for rect, label_text, kind, active in (
            (save_rect, "Save", "save", state.get("dirty")),
            (revert_rect, "Revert", "revert", True),
            (sim_rect, "Person Sim", "simulation", True),
        ):
            pygame.draw.rect(screen, (72, 91, 116) if active else (37, 43, 52), rect, border_radius=4)
            pygame.draw.rect(screen, (123, 157, 195) if active else (65, 72, 82), rect, 1, border_radius=4)
            rendered = small.render(label_text, True, (235, 239, 245) if active else (128, 135, 145))
            screen.blit(rendered, rendered.get_rect(center=rect.center))
            if active:
                hitboxes.append({"kind": kind, "rect": rect})

        status = str(state.get("status") or "")
        screen.blit(small.render(status, True, (191, 204, 220)), (22, workspace.bottom + 16))
        screen.blit(tiny.render(
            "DNA shapes the naked body. Clothing remains an equipped item and never rewrites genetic loci.",
            True, (139, 153, 171)), (22, workspace.bottom + 40))
        sim.set_person_editor_hitboxes(hitboxes)

    def _draw_character_creation_banner(self, screen, payload):
        if not payload.get("needs_character_creation") or payload.get("site_simulation"):
            return
        tier = str(payload.get("character_readiness_tier") or "sparse").upper()
        missing = payload.get("character_readiness_missing") or []
        message = f"CHARACTER CREATION NEEDED -- {tier} -- missing: {', '.join(missing) if missing else 'unknown'}"
        text = self._text(message, (30, 20, 14))
        bar = pygame.Rect(0, 0, screen.get_width(), text.get_height() + 14)
        pygame.draw.rect(screen, (214, 168, 74), bar)
        screen.blit(text, text.get_rect(center=bar.center))

    def _draw_asset_palette(self, screen, payload):
        palette = payload.get("asset_palette") or []
        if not palette:
            return
        x, y = 16, 112
        header = self._text("ASSET PLACER", (200, 205, 214))
        screen.blit(header, (x, y))
        y += header.get_height() + 4
        selected_id = payload.get("placement_selected_asset_id")
        for index, entry in enumerate(palette, start=1):
            highlighted = entry["id"] == selected_id
            color = (245, 214, 108) if highlighted else self._color(entry.get("color"), (160, 160, 160))
            label = self._text(f"[{index}] {entry.get('label', entry['id'])}", color)
            screen.blit(label, (x, y))
            y += label.get_height() + 2
        if payload.get("placement_mode"):
            hint = self._text("Click the map to place -- Esc to cancel", (238, 209, 111))
            screen.blit(hint, (x, y + 4))

    def draw(self, screen, sim):
        if getattr(sim, "is_person_editor_active", lambda: False)():
            self._draw_person_editor(screen, sim)
            return
        screen.fill(self.BACKGROUND)
        camera = self.app_view.camera
        payload = sim.get_person_render_payload()
        if not payload.get("in_void"):
            self._draw_floor(screen, camera, payload["bounds"])
            self._draw_site_layout(screen, camera, payload)
        self._draw_route(screen, camera, payload)
        for point in payload.get("points", []):
            self._draw_point(screen, camera, point, payload)
        self._draw_site_people(screen, camera, payload)
        if payload.get("draw_controlled_person", True):
            self._draw_person(screen, camera, payload)

        if payload.get("site_simulation"):
            mode = "SITE POPULATION SIMULATION"
        else:
            mode = "AUTONOMOUS QUEUE" if payload.get("control_mode") == "autonomous" else "DIRECT CONTROL"
        mode_surface = self._text(mode, (226, 214, 142) if mode.startswith("AUTO") else (126, 205, 235))
        screen.blit(mode_surface, mode_surface.get_rect(midtop=(screen.get_width() // 2, 48)))
        if payload.get("site_simulation"):
            hint = "Click a named person to inspect or fully generate a lightweight encounter"
        else:
            hint = (
                "Click a point to assign it; urgent needs or convictions may override"
                if payload.get("control_mode") == "autonomous"
                else "Click to move; click a point to move and use; right-click to cancel"
            )
        hint_surface = self._text(hint, (160, 172, 187))
        screen.blit(hint_surface, hint_surface.get_rect(midtop=(screen.get_width() // 2, 68)))
        if payload.get("in_void") and not payload.get("site_simulation"):
            void_surface = self._text(payload.get("site_label"), (120, 128, 142))
            screen.blit(void_surface, void_surface.get_rect(midtop=(screen.get_width() // 2, 90)))
            self._draw_asset_palette(screen, payload)
        self._draw_character_creation_banner(screen, payload)
