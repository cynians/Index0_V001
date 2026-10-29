"""Screen-space renderer for the Blueprint Designer.

Draws the whole workspace (header, tool panel, canvas, floor-space panel,
pickers, status bar) and hands the resulting hitboxes back to the simulation,
which does all input handling -- the same contract Formation Sim uses.
"""

from __future__ import annotations

import math
import zlib

import pygame
from ui.fonts import get_font

from . import blueprint_model as bm
from .blueprint_views import VIEW_LABELS
from .material_visuals import shade_color


class BlueprintDesignerRenderer:
    BACKGROUND = (11, 14, 19)
    CANVAS = (15, 20, 27)
    PANEL = (19, 25, 33)
    PANEL_ALT = (25, 33, 43)
    BORDER = (70, 86, 102)
    BORDER_ACTIVE = (214, 186, 104)
    TEXT = (228, 233, 237)
    MUTED = (146, 160, 172)
    DIM = (96, 108, 120)
    ACCENT = (214, 186, 104)
    ERROR = (232, 118, 104)
    OK = (132, 200, 150)
    GRID_MINOR = (22, 29, 38)
    GRID_MAJOR = (32, 42, 54)
    WALL = (206, 210, 214)
    WALL_INTERIOR = (160, 166, 172)
    DRAFT = (120, 200, 236)
    SELECT = (240, 206, 110)
    HOVER = (130, 190, 230)

    HEADER_TOP = 52
    HEADER_H = 58
    LEFT_W = 236
    RIGHT_W = 288
    STATUS_H = 30

    def __init__(self, app_view=None):
        self.app_view = app_view
        self._fonts = {}
        self._text_cache = {}
        self._detail_cache = {}

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _font(self, size=14, bold=False):
        key = (size, bold)
        font = self._fonts.get(key)
        if font is None:
            font = get_font(size, bold=bold)
            self._fonts[key] = font
        return font

    def _text(self, value, color=None, size=14, bold=False):
        color = tuple(color or self.TEXT)
        key = (str(value), color, size, bold)
        surface = self._text_cache.get(key)
        if surface is None:
            if len(self._text_cache) > 2500:
                self._text_cache.clear()
            surface = self._font(size, bold).render(str(value), True, color)
            self._text_cache[key] = surface
        return surface

    def _fit(self, value, width, size=14, bold=False):
        text = str(value)
        font = self._font(size, bold)
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text + "…"

    def _label_box(self, screen, text, center, color=None, size=12, background=(10, 13, 18)):
        surface = self._text(text, color or self.TEXT, size=size, bold=True)
        rect = surface.get_rect(center=(int(center[0]), int(center[1])))
        box = rect.inflate(8, 4)
        pygame.draw.rect(screen, background, box, border_radius=3)
        pygame.draw.rect(screen, (60, 72, 86), box, 1, border_radius=3)
        screen.blit(surface, rect)

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------

    def _button(self, screen, hitboxes, key, rect, label, *, active=False, enabled=True, size=13, align="center"):
        rect = pygame.Rect(rect)
        mouse = pygame.mouse.get_pos() if pygame.display.get_init() and pygame.display.get_surface() else (-1, -1)
        hovered = enabled and rect.collidepoint(mouse)
        if active:
            fill, border, color = (58, 54, 36), self.BORDER_ACTIVE, self.TEXT
        elif not enabled:
            fill, border, color = (20, 24, 30), (44, 52, 62), self.DIM
        else:
            fill, border, color = ((34, 44, 57) if hovered else self.PANEL_ALT), self.BORDER, self.TEXT
        pygame.draw.rect(screen, fill, rect, border_radius=4)
        pygame.draw.rect(screen, border, rect, 1, border_radius=4)
        text = self._fit(label, rect.width - 10, size=size, bold=active)
        surface = self._text(text, color, size=size, bold=active)
        if align == "left":
            screen.blit(surface, surface.get_rect(midleft=(rect.x + 8, rect.centery)))
        else:
            screen.blit(surface, surface.get_rect(center=rect.center))
        if enabled:
            hitboxes[key] = rect
        return rect

    def _section(self, screen, x, y, width, title):
        screen.blit(self._text(title, self.MUTED, size=11, bold=True), (x, y))
        pygame.draw.line(screen, (40, 50, 62), (x, y + 16), (x + width, y + 16), 1)
        return y + 22

    def _stepper(self, screen, hitboxes, key, x, y, width, label, value, *, enabled=True):
        screen.blit(self._text(label, self.MUTED, size=12), (x, y + 6))
        right = x + width
        self._button(screen, hitboxes, f"{key}_up", (right - 26, y, 26, 26), "+", enabled=enabled)
        value_rect = pygame.Rect(right - 26 - 74, y, 70, 26)
        pygame.draw.rect(screen, (14, 18, 24), value_rect, border_radius=3)
        surface = self._text(value, self.TEXT, size=12, bold=True)
        screen.blit(surface, surface.get_rect(center=value_rect.center))
        self._button(screen, hitboxes, f"{key}_down", (value_rect.x - 30, y, 26, 26), "−", enabled=enabled)
        return y + 32

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def draw(self, screen, sim):
        width, height = screen.get_size()
        sim.set_viewport(width, height)
        screen.fill(self.BACKGROUND)
        hitboxes = {}
        top = self.HEADER_TOP + self.HEADER_H + 6
        bottom = height - self.STATUS_H - 6
        left = pygame.Rect(10, top, self.LEFT_W, max(120, bottom - top))
        right = pygame.Rect(width - self.RIGHT_W - 10, top, self.RIGHT_W, max(120, bottom - top))
        canvas = pygame.Rect(left.right + 8, top, max(200, right.left - left.right - 16), max(120, bottom - top))

        self._draw_header(screen, sim, width, hitboxes)
        # The canvas rect must be known before the canvas is drawn so view
        # fitting and coordinate transforms use this frame's geometry.
        sim.set_layout(canvas, {})
        self._draw_canvas(screen, sim, canvas)
        self._draw_left_panel(screen, sim, left, hitboxes)
        self._draw_right_panel(screen, sim, right, hitboxes)
        self._draw_status(screen, sim, width, height)
        if sim.picker is not None:
            self._draw_picker(screen, sim, canvas, hitboxes)
        sim.set_layout(canvas, hitboxes)

    # ------------------------------------------------------------------
    # Header / status
    # ------------------------------------------------------------------

    def _draw_header(self, screen, sim, width, hitboxes):
        header = pygame.Rect(0, self.HEADER_TOP, width, self.HEADER_H)
        pygame.draw.rect(screen, (14, 19, 26), header)
        pygame.draw.line(screen, self.BORDER, (10, header.bottom - 1), (width - 10, header.bottom - 1), 1)
        title = self._text("BLUEPRINT DESIGNER", self.TEXT, size=20, bold=True)
        screen.blit(title, (18, header.y + 8))
        released = sim.read_only
        badge = "RELEASED" if released else "DRAFT"
        badge_color = (120, 170, 210) if released else self.ACCENT
        badge_surface = self._text(badge, badge_color, size=12, bold=True)
        badge_rect = badge_surface.get_rect(midleft=(18 + title.get_width() + 18, header.y + 20)).inflate(12, 6)
        pygame.draw.rect(screen, (22, 30, 40), badge_rect, border_radius=3)
        pygame.draw.rect(screen, badge_color, badge_rect, 1, border_radius=3)
        screen.blit(badge_surface, badge_surface.get_rect(center=badge_rect.center))

        buttons = [
            ("new_version", "New Version", 112, True),
            ("place_on_map", "Place on Map", 112, True),
            ("save", "Save", 64, not released or sim.saved_fingerprint is None),
            ("fit", "Fit", 46, True),
            ("redo", "Redo", 56, bool(sim.redo_stack)),
            ("undo", "Undo", 56, bool(sim.undo_stack)),
        ]
        buttons_left = width - 12 - sum(item[2] + 8 for item in buttons)

        name = sim.get_blueprint_name()
        version = sim.get_version_label()
        placed = sim.placed_building_count()
        parts = [name] + ([version] if version else [])
        parts.append(f"{placed} placed" if placed else "not placed yet")
        subtitle = " · ".join(parts)
        subtitle_width = max(80, buttons_left - 30)
        if sim.dirty:
            marker = self._text("● unsaved", self.ERROR, size=13, bold=True)
            screen.blit(marker, (20, header.y + 34))
            screen.blit(self._text(self._fit(subtitle, subtitle_width - marker.get_width() - 10, size=13), self.MUTED, size=13),
                        (20 + marker.get_width() + 10, header.y + 34))
        else:
            screen.blit(self._text(self._fit(subtitle, subtitle_width, size=13), self.MUTED, size=13), (20, header.y + 34))

        x = width - 12
        for key, label, button_w, enabled in buttons:
            x -= button_w
            self._button(screen, hitboxes, key, (x, header.y + 14, button_w, 30), label,
                         enabled=enabled, active=(key == "save" and sim.dirty))
            x -= 8

    def _draw_status(self, screen, sim, width, height):
        bar = pygame.Rect(0, height - self.STATUS_H, width, self.STATUS_H)
        pygame.draw.rect(screen, (13, 17, 23), bar)
        pygame.draw.line(screen, (40, 50, 62), bar.topleft, bar.topright, 1)
        color = self.ERROR if sim.status_is_error else self.TEXT
        screen.blit(self._text(self._fit(sim.status, width - 460, size=13), color, size=13), (14, bar.y + 7))
        parts = []
        if sim.stage == sim.STAGE_GRUNDRISS and sim.cursor_plan is not None:
            x, y = sim.cursor_plan
            parts.append(f"x {x:.2f} m  y {y:.2f} m")
            if sim.cursor_snap:
                parts.append(f"snap: {sim.cursor_snap}")
        grid = sim.blueprint["grid"]["snap_m"]
        parts.append(f"grid {grid:g} m" if sim.snap_enabled else "free placement")
        text = "   ".join(parts)
        surface = self._text(text, self.MUTED, size=12)
        screen.blit(surface, surface.get_rect(midright=(width - 14, bar.centery)))

    # ------------------------------------------------------------------
    # Left panel
    # ------------------------------------------------------------------

    def _draw_left_panel(self, screen, sim, rect, hitboxes):
        pygame.draw.rect(screen, self.PANEL, rect, border_radius=6)
        pygame.draw.rect(screen, (40, 50, 62), rect, 1, border_radius=6)
        x = rect.x + 10
        w = rect.width - 20
        y = rect.y + 10
        half = (w - 6) // 2
        self._button(screen, hitboxes, "stage:grundriss", (x, y, half, 30), "1  Grundriss",
                     active=sim.stage == sim.STAGE_GRUNDRISS)
        self._button(screen, hitboxes, "stage:design", (x + half + 6, y, half, 30), "2  Design",
                     active=sim.stage == sim.STAGE_DESIGN)
        y += 40
        content = pygame.Rect(rect.x + 2, y - 4, rect.width - 4, rect.bottom - y + 2)
        if sim.stage == sim.STAGE_GRUNDRISS:
            draw = lambda top: self._draw_grundriss_panel(screen, sim, x, top, w, hitboxes)
        else:
            draw = lambda top: self._draw_design_panel(screen, sim, x, top, w, hitboxes)
        self._scrolling_panel(screen, sim, "left", content, y, draw, hitboxes)

    def _scrolling_panel(self, screen, sim, side, content, top, draw, hitboxes):
        """Draw panel content clipped to ``content`` with a wheel-scroll offset."""

        scroll = int(sim.panel_scroll.get(side, 0))
        previous_clip = screen.get_clip()
        screen.set_clip(content)
        keys_before = set(hitboxes)
        bottom = draw(top - scroll)
        screen.set_clip(previous_clip)
        for key in set(hitboxes) - keys_before:
            rect = hitboxes[key]
            if not rect.colliderect(content):
                del hitboxes[key]
            elif not content.contains(rect):
                hitboxes[key] = rect.clip(content)
        content_height = (bottom or top) + scroll - top
        max_scroll = max(0, int(content_height - content.height + 12))
        sim.panel_scroll[side] = max(0, min(scroll, max_scroll))
        sim.panel_rects[side] = pygame.Rect(content)
        if max_scroll > 0:
            track = pygame.Rect(content.right - 5, content.y + 4, 3, content.height - 8)
            pygame.draw.rect(screen, (34, 42, 52), track)
            thumb_h = max(18, int(track.height * content.height / max(1, content_height)))
            thumb_y = track.y + int((track.height - thumb_h) * (sim.panel_scroll[side] / max_scroll))
            pygame.draw.rect(screen, (110, 126, 142), (track.x, thumb_y, track.width, thumb_h))

    def _draw_grundriss_panel(self, screen, sim, x, y, w, hitboxes):
        editable = not sim.read_only
        y = self._section(screen, x, y, w, "TOOLS")
        for tool in sim.GRUNDRISS_TOOLS:
            enabled = editable or tool == "select"
            self._button(screen, hitboxes, f"tool:{tool}", (x, y, w, 26), sim.TOOL_LABELS[tool],
                         active=sim.tool == tool, enabled=enabled, align="left")
            y += 30
        if sim.tool == "opening" or (sim.selection or {}).get("kind") == "opening":
            y += 2
            classes = bm.OPENING_CLASS_ORDER
            col_w = (w - 6) // 2
            for index, opening_class in enumerate(classes):
                column, row = index % 2, index // 2
                self._button(
                    screen, hitboxes, f"opening_class:{opening_class}",
                    (x + column * (col_w + 6), y + row * 28, col_w, 24),
                    bm.OPENING_CLASSES[opening_class]["label"],
                    active=sim.opening_class == opening_class, enabled=editable, size=11,
                )
            y += ((len(classes) + 1) // 2) * 28 + 2
        if sim.tool == "fixture":
            label = sim.fixture_label(sim.pending_fixture_ref) if sim.pending_fixture_ref else "Choose item…"
            self._button(screen, hitboxes, "fixture:choose", (x, y, w, 26), label, enabled=editable, size=12)
            y += 32
        y += 6
        y = self._section(screen, x, y, w, "SNAP")
        self._button(screen, hitboxes, "snap:toggle", (x, y, 104, 26),
                     "Grid: on" if sim.snap_enabled else "Grid: off", active=sim.snap_enabled, size=12)
        grid = sim.blueprint["grid"]["snap_m"]
        self._button(screen, hitboxes, "snap:down", (x + 112, y, 26, 26), "−")
        value = pygame.Rect(x + 142, y, w - 142 - 30, 26)
        pygame.draw.rect(screen, (14, 18, 24), value, border_radius=3)
        surface = self._text(f"{grid:g} m", self.TEXT, size=12, bold=True)
        screen.blit(surface, surface.get_rect(center=value.center))
        self._button(screen, hitboxes, "snap:up", (x + w - 26, y, 26, 26), "+")
        y += 30
        screen.blit(self._text("Shift: free · Ctrl: 45° steps", self.DIM, size=11), (x, y))
        y += 22

        y = self._section(screen, x, y, w, "LEVELS")
        for level in reversed(sim.blueprint["levels"]):
            room_count = len(bm.rooms_on_level(sim.blueprint, level["key"]))
            label = f"{level['name']}  ·  {room_count} room{'s' if room_count != 1 else ''}"
            self._button(screen, hitboxes, f"level:select:{level['key']}", (x, y, w, 24), label,
                         active=level["key"] == sim.active_level, size=12, align="left")
            y += 28
        half = (w - 6) // 2
        self._button(screen, hitboxes, "level:add", (x, y, half, 24), "+ Level", enabled=editable, size=12)
        self._button(screen, hitboxes, "level:remove", (x + half + 6, y, half, 24), "− Level",
                     enabled=editable and len(sim.blueprint["levels"]) > 1, size=12)
        y += 30
        level = sim.active_level_record()
        if level is not None:
            y = self._stepper(screen, hitboxes, "level:height", x, y, w, "Height",
                              f"{level['height_m']:.2f} m", enabled=editable)
            if sim.level_below() is not None and not bm.rooms_on_level(sim.blueprint, sim.active_level):
                self._button(screen, hitboxes, "level:copy_below", (x, y, w, 24), "Copy outline from below",
                             enabled=editable, size=12)
                y += 30
        y += 4
        y = self._section(screen, x, y, w, "WALLS")
        classes = sim.blueprint["wall_classes"]
        y = self._stepper(screen, hitboxes, "wall:exterior", x, y, w, "Exterior",
                          f"{classes['exterior']['thickness_m'] * 100:.0f} cm", enabled=editable)
        y = self._stepper(screen, hitboxes, "wall:interior", x, y, w, "Interior",
                          f"{classes['interior']['thickness_m'] * 100:.0f} cm", enabled=editable)
        y += 4
        y = self._section(screen, x, y, w, "ROOF")
        roof = sim.blueprint["roof"]
        self._button(screen, hitboxes, "roof:shape", (x, y, half, 24), f"Shape: {roof['shape']}",
                     enabled=editable, size=12)
        axis_label = "Ridge E–W" if roof["ridge_axis"] == "x" else "Ridge N–S"
        self._button(screen, hitboxes, "roof:axis", (x + half + 6, y, half, 24), axis_label,
                     enabled=editable and roof["shape"] != "flat", size=12)
        y += 30
        if roof["shape"] != "flat":
            y = self._stepper(screen, hitboxes, "roof:pitch", x, y, w, "Pitch", f"{roof['pitch_deg']:.0f}°",
                              enabled=editable)
            y = self._stepper(screen, hitboxes, "roof:overhang", x, y, w, "Overhang",
                              f"{roof['overhang_m']:.2f} m", enabled=editable)
        return y

    def _draw_design_panel(self, screen, sim, x, y, w, hitboxes):
        editable = not sim.read_only
        y = self._section(screen, x, y, w, "VIEW")
        for view_id in sim.DESIGN_VIEWS:
            self._button(screen, hitboxes, f"view:{view_id}", (x, y, w, 26), VIEW_LABELS[view_id],
                         active=sim.design_view_id == view_id, align="left")
            y += 30
        if sim.design_view_id == "top":
            self._button(screen, hitboxes, "top:roof_toggle", (x, y, w, 24),
                         "Showing roofs" if sim.top_show_roof else "Showing floors", size=12)
            y += 30
            if not sim.top_show_roof:
                for level in reversed(sim.blueprint["levels"]):
                    self._button(screen, hitboxes, f"level:select:{level['key']}", (x, y, w, 22), level["name"],
                                 active=level["key"] == sim.active_level, size=11, align="left")
                    y += 26
        y += 4
        y = self._section(screen, x, y, w, "DEFAULT MATERIALS")
        for role in bm.MATERIAL_ROLES:
            material = sim.blueprint["default_materials"].get(role)
            row = pygame.Rect(x, y, w, 34)
            enabled = editable
            pygame.draw.rect(screen, self.PANEL_ALT, row, border_radius=4)
            pygame.draw.rect(screen, self.BORDER, row, 1, border_radius=4)
            swatch = pygame.Rect(row.x + 6, row.y + 6, 22, 22)
            sim.materials.fill_polygon(
                screen, [swatch.topleft, swatch.topright, swatch.bottomright, swatch.bottomleft],
                material, role, meters_to_px=22, anchor=swatch.topleft,
            )
            pygame.draw.rect(screen, (8, 10, 14), swatch, 1)
            screen.blit(self._text(bm.MATERIAL_ROLE_LABELS[role], self.MUTED, size=11), (row.x + 36, row.y + 3))
            name = sim.materials.name(material) if material else "Unassigned"
            screen.blit(self._text(self._fit(name, w - 44, size=12), self.TEXT if material else self.DIM, size=12),
                        (row.x + 36, row.y + 17))
            if enabled:
                hitboxes[f"role:{role}"] = row
            y += 38
        y += 4
        if sim.design_view_id != "top" or sim.top_show_roof:
            y = self._section(screen, x, y, w, "DETAILS")
            has_details = sim.design_view_id in sim.blueprint["view_details"]
            self._button(screen, hitboxes, "details:paint", (x, y, w, 28), "Paint in Pixel Studio",
                         enabled=editable)
            y += 32
            self._button(screen, hitboxes, "details:clear", (x, y, w, 24), "Clear details",
                         enabled=editable and has_details, size=12)
            y += 30
            screen.blit(self._text(f"{bm.PIXELS_PER_METER} px per metre", self.DIM, size=11), (x, y))
            y += 18
        return y

    # ------------------------------------------------------------------
    # Right panel
    # ------------------------------------------------------------------

    def _draw_right_panel(self, screen, sim, rect, hitboxes):
        pygame.draw.rect(screen, self.PANEL, rect, border_radius=6)
        pygame.draw.rect(screen, (40, 50, 62), rect, 1, border_radius=6)
        content = rect.inflate(-4, -4)
        self._scrolling_panel(
            screen, sim, "right", content, rect.y + 10,
            lambda top: self._draw_right_content(screen, sim, rect.x + 12, top, rect.width - 24, hitboxes),
            hitboxes,
        )

    def _draw_right_content(self, screen, sim, x, y, w, hitboxes):
        totals = sim.derived["totals"]
        y = self._section(screen, x, y, w, "FLOOR SPACE")
        rows = [
            ("Footprint", f"{totals['footprint_area_m2']:.1f} m²"),
            ("Gross floor area", f"{totals['gross_floor_area_m2']:.1f} m²"),
            ("Net usable area", f"{totals['net_floor_area_m2']:.1f} m²"),
            ("Outline", f"{totals['footprint_width_m']:.2f} × {totals['footprint_depth_m']:.2f} m"),
            ("Height", f"{totals['building_height_m']:.2f} m"),
            ("Volume", f"{totals['enclosed_volume_m3']:.0f} m³"),
            ("Levels · rooms", f"{totals['level_count']} · {totals['room_count']}"),
            ("Openings · fixed items", f"{totals['opening_count']} · {totals['fixture_count']}"),
        ]
        for label, value in rows:
            screen.blit(self._text(label, self.MUTED, size=12), (x, y))
            surface = self._text(value, self.TEXT, size=12, bold=True)
            screen.blit(surface, surface.get_rect(topright=(x + w, y)))
            y += 19
        level_derived = sim.level_derived()
        if level_derived is not None and len(sim.blueprint["levels"]) > 1:
            screen.blit(self._text(
                f"{level_derived['name']}: {level_derived['gross_area_m2']:.1f} m² gross · "
                f"{level_derived['net_area_m2']:.1f} m² net", self.DIM, size=11), (x, y))
            y += 18
        y += 6
        y = self._section(screen, x, y, w, "ROOMS")
        rooms = bm.rooms_on_level(sim.blueprint, sim.active_level)
        if not rooms:
            screen.blit(self._text("No rooms on this level yet", self.DIM, size=12), (x, y))
            y += 20
        max_rows = 40
        for room in rooms[:max_rows]:
            metrics = sim.derived["rooms"].get(room["key"], {})
            selected = (sim.selection or {}).get("key") == room["key"] or (sim.selection or {}).get("room") == room["key"]
            row = pygame.Rect(x, y, w, 22)
            if selected:
                pygame.draw.rect(screen, (50, 46, 30), row, border_radius=3)
            screen.blit(self._text(self._fit(room["name"], w - 90, size=12), self.TEXT, size=12), (x + 4, y + 4))
            surface = self._text(f"{metrics.get('net_area_m2', 0.0):.1f} m²", self.MUTED, size=12)
            screen.blit(surface, surface.get_rect(topright=(x + w - 4, y + 4)))
            hitboxes[f"room:list:{room['key']}"] = row
            y += 24
        if len(rooms) > max_rows:
            screen.blit(self._text(f"+ {len(rooms) - max_rows} more", self.DIM, size=11), (x, y))
            y += 18
        y += 8
        y = self._section(screen, x, y, w, "SELECTION")
        keys_before = set(hitboxes)
        self._draw_selection(screen, sim, x, y, w, hitboxes)
        new_bottoms = [hitboxes[key].bottom for key in set(hitboxes) - keys_before]
        return max([y + 150] + [bottom + 8 for bottom in new_bottoms])

    def _draw_selection(self, screen, sim, x, y, w, hitboxes):
        selection = sim.selection
        editable = not sim.read_only
        if not selection:
            hint = "Click a surface" if sim.stage == sim.STAGE_DESIGN else "Click a room, wall, opening or item"
            screen.blit(self._text(hint, self.DIM, size=12), (x, y))
            return
        kind = selection.get("kind")

        def line(label, value):
            nonlocal y
            screen.blit(self._text(label, self.MUTED, size=12), (x, y))
            surface = self._text(self._fit(value, w - 110, size=12), self.TEXT, size=12, bold=True)
            screen.blit(surface, surface.get_rect(topright=(x + w, y)))
            y += 19

        half = (w - 6) // 2
        if kind == "room":
            room = sim._room(selection["key"])
            if room is None:
                return
            metrics = sim.derived["rooms"].get(room["key"], {})
            if sim.text_edit is not None:
                box = pygame.Rect(x, y, w, 26)
                pygame.draw.rect(screen, (12, 16, 22), box, border_radius=3)
                pygame.draw.rect(screen, self.ACCENT, box, 1, border_radius=3)
                screen.blit(self._text(sim.text_edit["buffer"] + "▏", self.TEXT, size=13), (box.x + 6, box.y + 5))
                hitboxes["sel:rename_box"] = box
                y += 32
            else:
                screen.blit(self._text(self._fit(room["name"], w, size=15, bold=True), self.TEXT, size=15, bold=True), (x, y))
                y += 24
            line("Gross area", f"{metrics.get('gross_area_m2', 0.0):.2f} m²")
            line("Net usable", f"{metrics.get('net_area_m2', 0.0):.2f} m²")
            line("Perimeter", f"{metrics.get('perimeter_m', 0.0):.2f} m")
            line("Corners", str(len(room["points"])))
            fixtures = metrics.get("fixtures") or []
            line("Fixed items", str(len(fixtures)))
            for fixture_key in fixtures[:4]:
                fixture = sim._fixture(fixture_key)
                if fixture:
                    screen.blit(self._text("· " + self._fit(sim.fixture_label(fixture["ref"]), w - 12, size=11),
                                           self.MUTED, size=11), (x + 4, y))
                    y += 16
            y += 6
            self._button(screen, hitboxes, "sel:rename", (x, y, half, 26), "Rename", enabled=editable, size=12)
            self._button(screen, hitboxes, "sel:delete", (x + half + 6, y, half, 26), "Delete", enabled=editable, size=12)
            return
        if kind == "vertex":
            line("Corner", f"{selection['point'][0]:.2f}, {selection['point'][1]:.2f}")
            screen.blit(self._text("Drag to move · Delete removes", self.DIM, size=11), (x, y))
            y += 20
            self._button(screen, hitboxes, "sel:delete", (x, y, w, 26), "Remove corner", enabled=editable, size=12)
            return
        if kind == "wall":
            wall = next((item for item in sim.derived["walls"] if item["key"] == selection["key"]), None)
            if wall is None:
                return
            line("Wall", "Exterior" if wall["kind"] == "exterior" else "Interior")
            line("Length", f"{wall['length_m']:.2f} m")
            line("Thickness", f"{wall['thickness_m'] * 100:.0f} cm")
            line("Height", f"{wall['top_z'] - wall['base_z']:.2f} m")
            if wall["facing"]:
                line("Faces", wall["facing"])
            line("Openings", str(len(wall["openings"])))
            names = [sim._room(key)["name"] for key in wall["rooms"] if sim._room(key)]
            line("Rooms", ", ".join(names))
            return
        if kind == "opening":
            opening = sim._opening(selection["key"])
            if opening is None:
                return
            derived = next((o for wall in sim.derived["walls"] for o in wall["openings"] if o["key"] == opening["key"]), None)
            line("Opening", bm.OPENING_CLASSES[opening["opening_class"]]["label"])
            line("Walkable", "yes" if bm.OPENING_CLASSES[opening["opening_class"]]["passable"] else "no")
            if derived is None:
                screen.blit(self._text("Not on a wall — move it onto one", self.ERROR, size=11), (x, y))
                y += 18
            y = self._stepper(screen, hitboxes, "sel:width", x, y, w, "Width", f"{opening['width_m']:.2f} m", enabled=editable)
            y = self._stepper(screen, hitboxes, "sel:sill", x, y, w, "Sill", f"{opening['sill_m']:.2f} m", enabled=editable)
            y = self._stepper(screen, hitboxes, "sel:head", x, y, w, "Head", f"{opening['head_m']:.2f} m", enabled=editable)
            self._button(screen, hitboxes, "sel:delete", (x, y, w, 26), "Remove opening", enabled=editable, size=12)
            return
        if kind == "fixture":
            fixture = sim._fixture(selection["key"])
            if fixture is None:
                return
            screen.blit(self._text(self._fit(sim.fixture_label(fixture["ref"]), w, size=14, bold=True), self.TEXT, size=14, bold=True), (x, y))
            y += 22
            line("Reference", fixture["ref"])
            line("Size", f"{fixture['size_m'][0]:.2f} × {fixture['size_m'][1]:.2f} m")
            line("Rotation", f"{fixture['rotation_deg']:.0f}°")
            room_key = next((k for k, m in sim.derived["rooms"].items() if fixture["key"] in m.get("fixtures", [])), None)
            room = sim._room(room_key) if room_key else None
            line("Room", room["name"] if room else "—")
            y += 4
            self._button(screen, hitboxes, "sel:rotate", (x, y, half, 26), "Rotate 90°", enabled=editable, size=12)
            self._button(screen, hitboxes, "sel:delete", (x + half + 6, y, half, 26), "Remove", enabled=editable, size=12)
            return
        if kind == "stair":
            feature = sim._feature(selection["key"])
            if feature is None:
                return
            to_level = bm.level_by_key(sim.blueprint, feature["to_level"])
            line("Stair", "")
            line("To", to_level["name"] if to_level else "—")
            self._button(screen, hitboxes, "sel:delete", (x, y + 6, w, 26), "Remove stair", enabled=editable, size=12)
            return
        if kind == "surface":
            key = selection["key"]
            role = selection.get("role")
            line("Surface", bm.MATERIAL_ROLE_LABELS.get(role, role or "—"))
            screen.blit(self._text(self._fit(key, w, size=11), self.DIM, size=11), (x, y))
            y += 18
            override = sim.blueprint["surface_materials"].get(key)
            material = sim.material_for(key, role)
            line("Material", sim.materials.name(material) if material else "Unassigned")
            line("Source", "this surface" if override else "default")
            y += 4
            if not key.startswith("opening:"):
                self._button(screen, hitboxes, "surface:set", (x, y, w, 26), "Set surface material",
                             enabled=editable, size=12)
                y += 30
            if override:
                self._button(screen, hitboxes, "surface:clear", (x, y, w, 26), "Use default", enabled=editable, size=12)
                y += 30
            if selection.get("room"):
                self._button(screen, hitboxes, "surface:room_walls", (x, y, w, 26), "Room wall finish…",
                             enabled=editable, size=12)

    # ------------------------------------------------------------------
    # Canvas
    # ------------------------------------------------------------------

    def _draw_canvas(self, screen, sim, rect):
        pygame.draw.rect(screen, self.CANVAS, rect)
        previous_clip = screen.get_clip()
        screen.set_clip(rect)
        if sim.stage == sim.STAGE_GRUNDRISS:
            self._draw_plan(screen, sim, rect)
        elif sim.design_view_id == "top":
            self._draw_top_design(screen, sim, rect)
        else:
            self._draw_elevation(screen, sim, rect)
        screen.set_clip(previous_clip)
        pygame.draw.rect(screen, (40, 50, 62), rect, 1)

    def _draw_grid(self, screen, sim, rect, view_id):
        zoom = sim._view(view_id)["zoom"]
        step = sim.blueprint["grid"]["snap_m"]
        while step * zoom < 7:
            step *= 2
        top_left = sim.screen_to_world(rect.topleft, view_id)
        bottom_right = sim.screen_to_world(rect.bottomright, view_id)
        min_x, max_x = sorted((top_left[0], bottom_right[0]))
        min_y, max_y = sorted((top_left[1], bottom_right[1]))
        x = math.floor(min_x / step) * step
        count = 0
        while x <= max_x and count < 800:
            major = abs(x / 5.0 - round(x / 5.0)) < 1e-6
            sx = sim.world_to_screen((x, 0), view_id)[0]
            pygame.draw.line(screen, self.GRID_MAJOR if major else self.GRID_MINOR, (sx, rect.top), (sx, rect.bottom), 1)
            x += step
            count += 1
        y = math.floor(min_y / step) * step
        count = 0
        while y <= max_y and count < 800:
            major = abs(y / 5.0 - round(y / 5.0)) < 1e-6
            sy = sim.world_to_screen((0, y), view_id)[1]
            pygame.draw.line(screen, self.GRID_MAJOR if major else self.GRID_MINOR, (rect.left, sy), (rect.right, sy), 1)
            y += step
            count += 1

    @staticmethod
    def _room_color(key):
        value = zlib.crc32(str(key).encode("utf-8"))
        hue = (value % 360) / 360.0
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue, 0.28, 0.34)
        return int(r * 255), int(g * 255), int(b * 255)

    def _wall_polygon(self, sim, start, end, thickness, view_id="plan"):
        length = math.dist(start, end) or 1.0
        nx, ny = -(end[1] - start[1]) / length, (end[0] - start[0]) / length
        half = thickness / 2.0
        corners = [
            (start[0] + nx * half, start[1] + ny * half),
            (end[0] + nx * half, end[1] + ny * half),
            (end[0] - nx * half, end[1] - ny * half),
            (start[0] - nx * half, start[1] - ny * half),
        ]
        return [sim.world_to_screen(p, view_id) for p in corners]

    def _draw_walls(self, screen, sim, level_derived, *, color=None, interior_color=None):
        for wall in level_derived["walls"]:
            start, end = wall["start"], wall["end"]
            length = wall["length_m"] or 1.0
            cursor = 0.0
            pieces = []
            for opening in wall["openings"]:
                low = opening["offset_m"] - opening["width_m"] / 2.0
                high = opening["offset_m"] + opening["width_m"] / 2.0
                if low > cursor:
                    pieces.append((cursor, low))
                cursor = max(cursor, high)
            if cursor < length:
                pieces.append((cursor, length))
            fill = (color or self.WALL) if wall["kind"] == "exterior" else (interior_color or self.WALL_INTERIOR)
            selected = (sim.selection or {}).get("key") == wall["key"]
            hovered = (sim.hover or {}).get("key") == wall["key"]
            for low, high in pieces:
                a = (start[0] + (end[0] - start[0]) * low / length, start[1] + (end[1] - start[1]) * low / length)
                b = (start[0] + (end[0] - start[0]) * high / length, start[1] + (end[1] - start[1]) * high / length)
                polygon = self._wall_polygon(sim, a, b, wall["thickness_m"])
                pygame.draw.polygon(screen, self.SELECT if selected else (self.HOVER if hovered else fill), polygon)
            for opening in wall["openings"]:
                self._draw_opening_symbol(screen, sim, wall, opening,
                                          selected=(sim.selection or {}).get("key") == opening["key"])

    def _draw_opening_symbol(self, screen, sim, wall, opening, selected=False, ghost=False):
        start = sim.world_to_screen(opening["start"], "plan")
        end = sim.world_to_screen(opening["end"], "plan")
        color = self.SELECT if selected else ((120, 200, 236) if ghost else (190, 196, 202))
        opening_class = opening.get("opening_class", "door")
        zoom = sim._view("plan")["zoom"]
        thickness_px = max(2, int(wall["thickness_m"] * zoom))
        if opening_class == "window":
            length = math.dist(start, end) or 1.0
            nx, ny = -(end[1] - start[1]) / length, (end[0] - start[0]) / length
            offset = thickness_px / 2.0
            for sign in (-1, 1):
                pygame.draw.line(screen, color, (start[0] + nx * offset * sign * 0.6, start[1] + ny * offset * sign * 0.6),
                                 (end[0] + nx * offset * sign * 0.6, end[1] + ny * offset * sign * 0.6), 1)
            pygame.draw.line(screen, color, start, end, 1)
        elif opening_class in {"door", "double_door"}:
            width_px = math.dist(start, end)
            nx, ny = wall.get("outward_normal") or (0.0, 0.0)
            # Swing into the building (or to one side of an interior wall).
            length = math.dist(opening["start"], opening["end"]) or 1.0
            dx, dy = (opening["end"][0] - opening["start"][0]) / length, (opening["end"][1] - opening["start"][1]) / length
            if not nx and not ny:
                nx, ny = -dy, dx
            inward = (-nx, -ny)
            leaves = [(opening["start"], 1.0)] if opening_class == "door" else [(opening["start"], 0.5), (opening["end"], -0.5)]
            for hinge, share in leaves:
                leaf = width_px * abs(share)
                hinge_screen = sim.world_to_screen(hinge, "plan")
                direction = (dx * math.copysign(1, share), dy * math.copysign(1, share))
                tip = (hinge[0] + inward[0] * length * abs(share), hinge[1] + inward[1] * length * abs(share))
                pygame.draw.line(screen, color, hinge_screen, sim.world_to_screen(tip, "plan"), 2)
                steps = 10
                arc = []
                for i in range(steps + 1):
                    angle = (math.pi / 2.0) * i / steps
                    px = hinge[0] + (direction[0] * math.cos(angle) + inward[0] * math.sin(angle)) * length * abs(share)
                    py = hinge[1] + (direction[1] * math.cos(angle) + inward[1] * math.sin(angle)) * length * abs(share)
                    arc.append(sim.world_to_screen((px, py), "plan"))
                if len(arc) > 1 and leaf > 4:
                    pygame.draw.lines(screen, shade_color(color, 0.7), False, arc, 1)
        elif opening_class == "loading_door":
            steps = max(2, int(math.dist(start, end) // 8))
            for i in range(steps):
                if i % 2 == 0:
                    t0, t1 = i / steps, (i + 1) / steps
                    pygame.draw.line(screen, color, (start[0] + (end[0] - start[0]) * t0, start[1] + (end[1] - start[1]) * t0),
                                     (start[0] + (end[0] - start[0]) * t1, start[1] + (end[1] - start[1]) * t1), 2)
        else:
            # Open doorway: short jamb ticks across the wall at both ends.
            length = math.dist(start, end) or 1.0
            nx, ny = -(end[1] - start[1]) / length, (end[0] - start[0]) / length
            half = thickness_px / 2.0 + 2
            for point in (start, end):
                pygame.draw.line(screen, color, (point[0] - nx * half, point[1] - ny * half),
                                 (point[0] + nx * half, point[1] + ny * half), 2)
        if selected or ghost:
            pygame.draw.circle(screen, color, (int(start[0]), int(start[1])), 3)
            pygame.draw.circle(screen, color, (int(end[0]), int(end[1])), 3)

    def _dashed_polygon(self, screen, points, color, dash=6):
        for index in range(len(points)):
            a = points[index]
            b = points[(index + 1) % len(points)]
            length = math.dist(a, b)
            if length < 1:
                continue
            steps = max(1, int(length // dash))
            for i in range(0, steps, 2):
                t0, t1 = i / steps, min(1.0, (i + 1) / steps)
                pygame.draw.line(screen, color, (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                                 (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1), 1)

    def _length_label(self, screen, sim, a, b, color=None, offset_px=14):
        length = math.dist(a, b)
        if length < 0.05:
            return
        sa, sb = sim.world_to_screen(a, "plan"), sim.world_to_screen(b, "plan")
        mid = ((sa[0] + sb[0]) / 2.0, (sa[1] + sb[1]) / 2.0)
        span = math.dist(sa, sb) or 1.0
        nx, ny = -(sb[1] - sa[1]) / span, (sb[0] - sa[0]) / span
        self._label_box(screen, f"{length:.2f} m", (mid[0] + nx * offset_px, mid[1] + ny * offset_px), color=color)

    def _draw_plan(self, screen, sim, rect):
        self._draw_grid(screen, sim, rect, "plan")
        origin = sim.world_to_screen((0.0, 0.0), "plan")
        pygame.draw.line(screen, (52, 64, 78), (origin[0] - 10, origin[1]), (origin[0] + 10, origin[1]), 1)
        pygame.draw.line(screen, (52, 64, 78), (origin[0], origin[1] - 10), (origin[0], origin[1] + 10), 1)

        below = sim.level_below()
        if below is not None:
            for room in bm.rooms_on_level(sim.blueprint, below["key"]):
                self._dashed_polygon(screen, [sim.world_to_screen(p, "plan") for p in room["points"]], (74, 90, 108))

        level_derived = sim.level_derived()
        rooms = bm.rooms_on_level(sim.blueprint, sim.active_level)
        selection = sim.selection or {}
        hover = sim.hover or {}
        for room in rooms:
            points = [sim.world_to_screen(p, "plan") for p in room["points"]]
            color = self._room_color(room["key"])
            if selection.get("kind") == "room" and selection.get("key") == room["key"]:
                color = shade_color(color, 1.45)
            elif hover.get("kind") == "room" and hover.get("key") == room["key"]:
                color = shade_color(color, 1.2)
            pygame.draw.polygon(screen, color, points)
        for feature in sim.blueprint["vertical_features"]:
            if sim.active_level not in {feature["from_level"], feature["to_level"]}:
                continue
            self._draw_stair(screen, sim, feature, upper=feature["to_level"] == sim.active_level,
                             selected=selection.get("key") == feature["key"])
        if level_derived is not None:
            self._draw_walls(screen, sim, level_derived)
            for wall in level_derived["walls"]:
                if wall["key"] in {hover.get("key"), selection.get("key")}:
                    self._length_label(screen, sim, tuple(wall["start"]), tuple(wall["end"]), color=self.SELECT, offset_px=18)
        for fixture in sim.blueprint["fixtures"]:
            if fixture["level"] != sim.active_level:
                continue
            self._draw_fixture(screen, sim, fixture, selected=selection.get("key") == fixture["key"],
                               hovered=hover.get("key") == fixture["key"])
        zoom = sim._view("plan")["zoom"]
        for room in rooms:
            metrics = sim.derived["rooms"].get(room["key"], {})
            center = sim.world_to_screen(metrics.get("centroid") or room["points"][0], "plan")
            name_surface = self._text(room["name"], self.TEXT, size=13 if zoom > 14 else 11, bold=True)
            area_surface = self._text(f"{metrics.get('net_area_m2', 0.0):.1f} m²", self.MUTED, size=12 if zoom > 14 else 10)
            screen.blit(name_surface, name_surface.get_rect(center=(center[0], center[1] - 8)))
            screen.blit(area_surface, area_surface.get_rect(center=(center[0], center[1] + 8)))
        if selection.get("kind") == "room":
            room = sim._room(selection["key"])
            if room is not None:
                points = [tuple(p) for p in room["points"]]
                for index in range(len(points)):
                    self._length_label(screen, sim, points[index], points[(index + 1) % len(points)],
                                       color=self.SELECT, offset_px=-16 if bm.polygon_signed_area(points) > 0 else 16)
        # Room corner handles in select mode.
        if sim.tool == "select" and not sim.read_only:
            for room in rooms:
                for point in room["points"]:
                    screen_point = sim.world_to_screen(point, "plan")
                    pygame.draw.circle(screen, (30, 36, 44), (int(screen_point[0]), int(screen_point[1])), 4)
                    pygame.draw.circle(screen, (150, 160, 170), (int(screen_point[0]), int(screen_point[1])), 4, 1)
            if selection.get("kind") == "vertex":
                point = sim.world_to_screen(selection["point"], "plan")
                pygame.draw.circle(screen, self.SELECT, (int(point[0]), int(point[1])), 6, 2)
            if hover.get("kind") == "vertex":
                point = sim.world_to_screen(hover["point"], "plan")
                pygame.draw.circle(screen, self.HOVER, (int(point[0]), int(point[1])), 6, 2)

        self._draw_drafts(screen, sim)
        self._draw_compass(screen, rect)
        self._draw_scale_bar(screen, sim, rect, "plan")
        if sim.read_only:
            self._label_box(screen, "Released · read-only · New Version to edit", (rect.centerx, rect.y + 18),
                            color=(150, 196, 230))

    def _draw_stair(self, screen, sim, feature, upper=False, selected=False):
        points = [tuple(p) for p in feature["points"]]
        screen_points = [sim.world_to_screen(p, "plan") for p in points]
        color = self.SELECT if selected else ((110, 124, 140) if upper else (176, 184, 192))
        if upper:
            self._dashed_polygon(screen, screen_points, color)
            return
        pygame.draw.polygon(screen, (40, 48, 58), screen_points)
        pygame.draw.polygon(screen, color, screen_points, 1)
        bbox = bm.polygon_bbox(points)
        long_x = (bbox[2] - bbox[0]) >= (bbox[3] - bbox[1])
        treads = 12
        for i in range(1, treads):
            t = i / treads
            if long_x:
                x = bbox[0] + (bbox[2] - bbox[0]) * t
                a, b = (x, bbox[1]), (x, bbox[3])
            else:
                y = bbox[1] + (bbox[3] - bbox[1]) * t
                a, b = (bbox[0], y), (bbox[2], y)
            pygame.draw.line(screen, shade_color(color, 0.7), sim.world_to_screen(a, "plan"), sim.world_to_screen(b, "plan"), 1)
        center = sim.world_to_screen(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2), "plan")
        self._label_box(screen, "UP", center, color=color, size=11)

    def _draw_fixture(self, screen, sim, fixture, selected=False, hovered=False, ghost=False):
        points = bm.rectangle_points(fixture["position"], fixture["size_m"], fixture["rotation_deg"])
        screen_points = [sim.world_to_screen(p, "plan") for p in points]
        fill = (46, 70, 84) if not ghost else (40, 86, 104)
        border = self.SELECT if selected else (self.HOVER if hovered or ghost else (126, 170, 190))
        pygame.draw.polygon(screen, fill, screen_points)
        pygame.draw.polygon(screen, border, screen_points, 2 if selected else 1)
        # Front edge marker (the local "south" side).
        front = [screen_points[2], screen_points[3]]
        pygame.draw.line(screen, border, front[0], front[1], 3)
        zoom = sim._view("plan")["zoom"]
        if zoom > 18 and (selected or hovered or ghost or zoom > 40):
            center = sim.world_to_screen(fixture["position"], "plan")
            label = self._fit(sim.fixture_label(fixture["ref"]), 160, size=10)
            self._label_box(screen, label, (center[0], center[1] - fixture["size_m"][1] * zoom / 2 - 12),
                            color=(200, 222, 232), size=10)

    def _draw_drafts(self, screen, sim):
        cursor = sim.cursor_plan
        if sim.tool == "room" and sim.draft_points:
            points = list(sim.draft_points)
            screen_points = [sim.world_to_screen(p, "plan") for p in points]
            if len(screen_points) >= 2:
                pygame.draw.lines(screen, self.DRAFT, False, screen_points, 2)
            for index in range(len(points) - 1):
                self._length_label(screen, sim, points[index], points[index + 1], color=self.DRAFT)
            if cursor is not None:
                last = screen_points[-1]
                cursor_screen = sim.world_to_screen(cursor, "plan")
                pygame.draw.line(screen, self.DRAFT, last, cursor_screen, 1)
                self._length_label(screen, sim, points[-1], cursor, color=(255, 236, 160))
                if len(points) >= 2:
                    self._dashed_polygon(screen, [cursor_screen, screen_points[0]], (80, 130, 160))
                    candidate = points + [cursor]
                    if len(candidate) >= 3:
                        area = bm.polygon_area(candidate)
                        centroid = bm.polygon_centroid(candidate)
                        self._label_box(screen, f"{area:.2f} m²", sim.world_to_screen(centroid, "plan"),
                                        color=(255, 236, 160), size=13)
            for index, point in enumerate(screen_points):
                radius = 6 if index == 0 and len(points) >= 3 else 4
                pygame.draw.circle(screen, self.DRAFT, (int(point[0]), int(point[1])), radius, 0 if index else 2)
        if sim.tool in {"rect", "stair"} and sim.rect_anchor is not None and cursor is not None:
            anchor = sim.rect_anchor
            corners = [anchor, (cursor[0], anchor[1]), cursor, (anchor[0], cursor[1])]
            screen_points = [sim.world_to_screen(p, "plan") for p in corners]
            pygame.draw.polygon(screen, self.DRAFT, screen_points, 2)
            self._length_label(screen, sim, corners[0], corners[1], color=(255, 236, 160), offset_px=-14 if cursor[1] > anchor[1] else 14)
            self._length_label(screen, sim, corners[1], corners[2], color=(255, 236, 160), offset_px=-14 if cursor[0] < anchor[0] else 14)
            area = abs((cursor[0] - anchor[0]) * (cursor[1] - anchor[1]))
            self._label_box(screen, f"{area:.2f} m²", sim.world_to_screen(((anchor[0] + cursor[0]) / 2, (anchor[1] + cursor[1]) / 2), "plan"),
                            color=(255, 236, 160), size=13)
        if sim.tool == "opening":
            preview = sim.opening_preview()
            if preview is not None:
                self._draw_opening_symbol(screen, sim, preview["wall"], {**preview, "opening_class": sim.opening_class}, ghost=True)
                wall = preview["wall"]
                self._length_label(screen, sim, wall["start"], preview["start"], color=(170, 220, 240), offset_px=18)
                self._length_label(screen, sim, preview["end"], wall["end"], color=(170, 220, 240), offset_px=18)
                self._length_label(screen, sim, preview["start"], preview["end"], color=(255, 236, 160), offset_px=-18)
        if sim.tool == "fixture":
            preview = sim.fixture_preview()
            if preview is not None:
                self._draw_fixture(screen, sim, {**preview, "key": "__preview__"}, ghost=True)
        if sim.length_entry and cursor is not None:
            point = sim.world_to_screen(cursor, "plan")
            hint = "W x D" if sim.tool in {"rect", "stair"} else "length"
            self._label_box(screen, f"{sim.length_entry}▏ m   ({hint} · Enter)", (point[0] + 70, point[1] + 22),
                            color=(255, 236, 160), size=13)
        if cursor is not None and sim.tool != "select" and sim.canvas_rect.collidepoint(sim.cursor_screen or (-1, -1)):
            point = sim.world_to_screen(cursor, "plan")
            color = {
                "vertex": (255, 214, 102),
                "edge": (140, 220, 170),
                "grid": (130, 190, 230),
                "angle": (220, 160, 240),
            }.get(sim.cursor_snap, (200, 200, 200))
            px, py = int(point[0]), int(point[1])
            pygame.draw.line(screen, color, (px - 8, py), (px + 8, py), 1)
            pygame.draw.line(screen, color, (px, py - 8), (px, py + 8), 1)
            if sim.cursor_snap == "vertex":
                pygame.draw.rect(screen, color, (px - 5, py - 5, 10, 10), 1)
            elif sim.cursor_snap == "edge":
                pygame.draw.polygon(screen, color, [(px, py - 6), (px + 6, py), (px, py + 6), (px - 6, py)], 1)

    def _draw_compass(self, screen, rect):
        center = (rect.right - 28, rect.y + 30)
        pygame.draw.polygon(screen, (170, 180, 190), [(center[0], center[1] - 14), (center[0] - 6, center[1] + 4), (center[0] + 6, center[1] + 4)])
        surface = self._text("N", (170, 180, 190), size=11, bold=True)
        screen.blit(surface, surface.get_rect(center=(center[0], center[1] + 14)))

    def _draw_scale_bar(self, screen, sim, rect, view_id):
        zoom = sim._view(view_id)["zoom"]
        target = 120 / max(zoom, 1e-6)
        magnitude = 10 ** math.floor(math.log10(target))
        length = magnitude
        for candidate in (1, 2, 5, 10):
            if candidate * magnitude <= target:
                length = candidate * magnitude
        px = length * zoom
        x0, y0 = rect.x + 16, rect.bottom - 18
        pygame.draw.line(screen, (170, 180, 190), (x0, y0), (x0 + px, y0), 2)
        pygame.draw.line(screen, (170, 180, 190), (x0, y0 - 4), (x0, y0 + 4), 1)
        pygame.draw.line(screen, (170, 180, 190), (x0 + px, y0 - 4), (x0 + px, y0 + 4), 1)
        screen.blit(self._text(f"{length:g} m", (170, 180, 190), size=11), (x0 + px + 6, y0 - 7))

    # ------------------------------------------------------------------
    # Design views
    # ------------------------------------------------------------------

    def _draw_primitives(self, screen, sim, primitives, view_id):
        zoom = sim._view(view_id)["zoom"]
        anchor = sim.world_to_screen((0.0, 0.0), view_id)
        selection = sim.selection or {}
        hover = sim.hover or {}
        for primitive in primitives:
            points = [sim.world_to_screen(p, view_id) for p in primitive["polygon"]]
            if len(points) < 3:
                continue
            if primitive["kind"] == "opening" and not primitive.get("role"):
                # An open doorway shows the dark interior behind it.
                pygame.draw.polygon(screen, (24, 26, 30), points)
            else:
                material = sim.material_for(primitive["surface_key"], primitive.get("role"))
                sim.materials.fill_polygon(screen, points, material, primitive.get("role"), meters_to_px=zoom,
                                           anchor=anchor, shade=primitive.get("shade", 1.0),
                                           seed_key=primitive["surface_key"])
            # Walls of neighbouring rooms form one continuous facade, so only
            # openings, gables, and roof planes get an outline.
            if primitive["kind"] != "wall" and primitive["kind"] != "floor":
                pygame.draw.polygon(screen, (20, 24, 30), points, 1)
        for primitive in primitives:
            key = primitive["surface_key"]
            if key == selection.get("key") or key == hover.get("key"):
                points = [sim.world_to_screen(p, view_id) for p in primitive["polygon"]]
                if len(points) >= 3:
                    pygame.draw.polygon(screen, self.SELECT if key == selection.get("key") else self.HOVER, points, 2)

    def _draw_details(self, screen, sim, view_id):
        detail = sim.blueprint["view_details"].get(view_id)
        if not isinstance(detail, dict) or not detail.get("frame_m"):
            return
        width, height = int(detail.get("width") or 0), int(detail.get("height") or 0)
        if width <= 0 or height <= 0:
            return
        cache_key = (view_id, id(detail), width, height)
        surface = self._detail_cache.get(cache_key)
        if surface is None:
            surface = pygame.Surface((width, height), pygame.SRCALPHA)
            surface.fill((0, 0, 0, 0))
            for layer in detail.get("layers") or []:
                if not isinstance(layer, dict) or not layer.get("visible", True):
                    continue
                for y, row in enumerate((layer.get("pixels") or [])[:height]):
                    for x, color in enumerate((row or [])[:width]):
                        if color is not None:
                            surface.set_at((x, y), (int(color[0]), int(color[1]), int(color[2]), 255))
            if len(self._detail_cache) > 16:
                self._detail_cache.clear()
            self._detail_cache[cache_key] = surface
        u0, v0, u1, v1 = detail["frame_m"]
        if view_id == "top":
            top_left = sim.world_to_screen((u0, v0), view_id)
        else:
            top_left = sim.world_to_screen((u0, v1), view_id)
        zoom = sim._view(view_id)["zoom"]
        target = (max(1, int(round(width / bm.PIXELS_PER_METER * zoom))), max(1, int(round(height / bm.PIXELS_PER_METER * zoom))))
        if target[0] > 6000 or target[1] > 6000:
            return
        screen.blit(pygame.transform.scale(surface, target), (int(top_left[0]), int(top_left[1])))

    def _draw_top_design(self, screen, sim, rect):
        self._draw_grid(screen, sim, rect, "top")
        primitives = sim.design_primitives("top")
        self._draw_primitives(screen, sim, primitives, "top")
        if sim.top_show_roof:
            self._draw_details(screen, sim, "top")
        else:
            level_derived = sim.level_derived()
            if level_derived is not None:
                for wall in level_derived["walls"]:
                    polygon = [sim.world_to_screen(p, "top") for p in self._wall_corners(wall)]
                    pygame.draw.polygon(screen, (34, 38, 44), polygon)
            for fixture in sim.blueprint["fixtures"]:
                if fixture["level"] == sim.active_level:
                    points = [sim.world_to_screen(p, "top") for p in
                              bm.rectangle_points(fixture["position"], fixture["size_m"], fixture["rotation_deg"])]
                    pygame.draw.polygon(screen, (126, 170, 190), points, 1)
        self._draw_compass(screen, rect)
        self._draw_scale_bar(screen, sim, rect, "top")
        if not primitives:
            self._label_box(screen, "Nothing to show yet — draw rooms in the Grundriss stage", rect.center, color=self.MUTED)

    @staticmethod
    def _wall_corners(wall):
        start, end = wall["start"], wall["end"]
        length = math.dist(start, end) or 1.0
        nx, ny = -(end[1] - start[1]) / length, (end[0] - start[0]) / length
        half = wall["thickness_m"] / 2.0
        return [
            (start[0] + nx * half, start[1] + ny * half),
            (end[0] + nx * half, end[1] + ny * half),
            (end[0] - nx * half, end[1] - ny * half),
            (start[0] - nx * half, start[1] - ny * half),
        ]

    def _draw_elevation(self, screen, sim, rect):
        view_id = sim.design_view_id
        self._draw_grid(screen, sim, rect, view_id)
        ground_y = sim.world_to_screen((0.0, 0.0), view_id)[1]
        pygame.draw.rect(screen, (24, 28, 24), (rect.left, ground_y, rect.width, max(0, rect.bottom - ground_y)))
        pygame.draw.line(screen, (120, 128, 110), (rect.left, ground_y), (rect.right, ground_y), 2)
        primitives = sim.design_primitives(view_id)
        self._draw_primitives(screen, sim, primitives, view_id)
        self._draw_details(screen, sim, view_id)
        if primitives:
            roof = sim.derived.get("roof") or {}
            eave = roof.get("eave_z") or sim.derived["totals"]["wall_height_m"]
            right = max(p[0] for primitive in primitives for p in primitive["polygon"])
            for z, label in ((eave, "eave"), (eave + (roof.get("rise_m") or 0.0), "ridge")):
                if label == "ridge" and not roof.get("rise_m"):
                    continue
                sx, sy = sim.world_to_screen((right, z), view_id)
                text = self._text(f"{label} {z:.2f} m", self.MUTED, size=11)
                label_x = min(sx + 34, rect.right - text.get_width() - 8)
                pygame.draw.line(screen, (90, 104, 118), (sx + 6, sy), (max(sx + 6, label_x - 4), sy), 1)
                screen.blit(text, (label_x, sy - 16 if label_x < sx + 34 else sy - 7))
        else:
            self._label_box(screen, "Nothing to show yet — draw rooms in the Grundriss stage", rect.center, color=self.MUTED)
        title = self._text(VIEW_LABELS.get(view_id, view_id).upper(), self.MUTED, size=12, bold=True)
        screen.blit(title, (rect.x + 12, rect.y + 10))
        self._draw_scale_bar(screen, sim, rect, view_id)

    # ------------------------------------------------------------------
    # Picker
    # ------------------------------------------------------------------

    def _draw_picker(self, screen, sim, canvas, hitboxes):
        picker = sim.picker
        panel = pygame.Rect(0, 0, min(460, canvas.width - 40), min(520, canvas.height - 40))
        panel.center = canvas.center
        shade = pygame.Surface(canvas.size, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 120))
        screen.blit(shade, canvas.topleft)
        pygame.draw.rect(screen, self.PANEL, panel, border_radius=8)
        pygame.draw.rect(screen, self.BORDER, panel, 1, border_radius=8)
        hitboxes["picker:panel"] = panel
        titles = {
            "material": "Choose material",
            "fixture": "Choose a fixed item",
            "parent": "Place on which site?",
        }
        x = panel.x + 14
        y = panel.y + 12
        screen.blit(self._text(titles.get(picker["kind"], "Choose"), self.TEXT, size=16, bold=True), (x, y))
        self._button(screen, hitboxes, "picker:close", (panel.right - 40, panel.y + 10, 28, 26), "×")
        y += 32
        box = pygame.Rect(x, y, panel.width - 28, 28)
        pygame.draw.rect(screen, (12, 16, 22), box, border_radius=4)
        pygame.draw.rect(screen, self.BORDER, box, 1, border_radius=4)
        query = picker.get("query") or ""
        screen.blit(self._text((query or "Type to filter") + ("▏" if query else ""),
                               self.TEXT if query else self.DIM, size=13), (box.x + 8, box.y + 6))
        y += 36
        if picker["kind"] in {"material", "fixture"}:
            self._button(screen, hitboxes, "picker:all", (x, y, 150, 24),
                         "Showing all" if picker.get("show_all") else "Show all", size=12,
                         active=bool(picker.get("show_all")))
            y += 30
        options = sim.picker_options()
        row_h = 28
        visible = max(1, (panel.bottom - 14 - y) // row_h)
        scroll = max(0, min(int(picker.get("scroll", 0)), max(0, len(options) - visible)))
        picker["scroll"] = scroll
        if not options:
            screen.blit(self._text("No matches", self.DIM, size=13), (x, y + 4))
        for option in options[scroll:scroll + visible]:
            row = pygame.Rect(x, y, panel.width - 28, row_h - 3)
            mouse = pygame.mouse.get_pos() if pygame.display.get_init() and pygame.display.get_surface() else (-1, -1)
            pygame.draw.rect(screen, (34, 44, 57) if row.collidepoint(mouse) else self.PANEL_ALT, row, border_radius=3)
            text_x = row.x + 8
            if option.get("color") is not None:
                pygame.draw.rect(screen, option["color"], (row.x + 6, row.y + 4, 16, row.height - 8))
                text_x += 22
            screen.blit(self._text(self._fit(option["label"], row.width - 170, size=13), self.TEXT, size=13), (text_x, row.y + 5))
            detail = self._text(self._fit(str(option.get("detail") or ""), 140, size=11), self.MUTED, size=11)
            screen.blit(detail, detail.get_rect(midright=(row.right - 8, row.centery)))
            hitboxes[f"picker:item:{option['id']}"] = row
            y += row_h
        if len(options) > visible:
            screen.blit(self._text(f"{scroll + 1}–{min(len(options), scroll + visible)} of {len(options)} · scroll",
                                   self.DIM, size=11), (x, panel.bottom - 16))
