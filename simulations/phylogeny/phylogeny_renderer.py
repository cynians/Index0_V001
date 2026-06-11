import pygame


class PhylogenyRenderer:
    """
    Draws phylogeny trees in world space so the normal camera can pan/zoom.
    """

    def __init__(self, app_view):
        self.app_view = app_view

    def _world_rect_to_screen(self, camera, rect_data):
        top_left = camera.world_to_screen((rect_data["x"], rect_data["y"]))
        bottom_right = camera.world_to_screen(
            (rect_data["x"] + rect_data["width"], rect_data["y"] + rect_data["height"])
        )
        if top_left is None or bottom_right is None:
            return None
        left = min(top_left[0], bottom_right[0])
        right = max(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        bottom = max(top_left[1], bottom_right[1])
        return pygame.Rect(left, top, right - left, bottom - top)

    def _label_for_width(self, label, font, width):
        text = str(label or "")
        if font.size(text)[0] <= width:
            return text
        ellipsis = "..."
        while text and font.size(text + ellipsis)[0] > width:
            text = text[:-1]
        return text + ellipsis if text else ellipsis

    def _coerce_hex_color(self, value, fallback=None):
        text = str(value or "").strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (
                    int(text[1:3], 16),
                    int(text[3:5], 16),
                    int(text[5:7], 16),
                )
            except ValueError:
                return fallback
        return fallback

    def _coerce_color_value(self, value, fallback=None):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in value[:3])
            except (TypeError, ValueError):
                return fallback
        return self._coerce_hex_color(value, fallback=fallback)

    def _mix_color(self, color, target, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        return tuple(
            max(0, min(255, int(round(color[index] * (1.0 - ratio) + target[index] * ratio))))
            for index in range(3)
        )

    def _node_colors(self, clade_id, rect_data, payload):
        base = self._coerce_color_value(rect_data.get("card_color"), fallback=None)
        if base is not None:
            fill = self._mix_color(base, (18, 22, 30), 0.60)
            header = self._coerce_color_value(rect_data.get("card_header_color"), fallback=None)
            border_source = header if header is not None else base
            border = self._mix_color(border_source, (234, 240, 250), 0.26)
            if clade_id == payload.get("selected_id"):
                fill = self._mix_color(base, (66, 76, 48), 0.32)
                border = self._mix_color(border_source, (246, 232, 166), 0.12)
            elif clade_id == payload.get("hover_id"):
                fill = self._mix_color(base, (48, 66, 78), 0.32)
                border = self._mix_color(border_source, (184, 232, 250), 0.18)
            elif clade_id == payload.get("focus_id"):
                fill = self._mix_color(base, (56, 70, 92), 0.32)
                border = self._mix_color(border_source, (220, 232, 252), 0.18)
            return fill, border

        if clade_id == payload.get("selected_id"):
            return (66, 76, 48), (230, 212, 136)
        if clade_id == payload.get("hover_id"):
            return (48, 66, 78), (154, 210, 236)
        if clade_id == payload.get("focus_id"):
            return (56, 70, 92), (180, 204, 244)
        if rect_data.get("species"):
            return (38, 42, 50), (118, 132, 156)
        return (34, 40, 52), (112, 128, 152)

    def _node_band_color(self, rect_data):
        colors = rect_data.get("wiki_field_colors")
        if isinstance(colors, dict):
            value = colors.get("default")
            if not value:
                for candidate in colors.values():
                    if candidate:
                        value = candidate
                        break
            band = self._coerce_color_value(value, fallback=None)
            if band is not None:
                return band
        return self._coerce_color_value(rect_data.get("card_header_color"), fallback=None)

    def draw(self, screen, sim):
        camera = self.app_view.camera
        font = self.app_view.default_font
        payload = sim.get_render_payload()
        bounds = sim.bounds

        background_tl = camera.world_to_screen((bounds["min_x"], bounds["min_y"]))
        background_br = camera.world_to_screen((bounds["max_x"], bounds["max_y"]))
        if background_tl is not None and background_br is not None:
            background = pygame.Rect(
                min(background_tl[0], background_br[0]),
                min(background_tl[1], background_br[1]),
                abs(background_br[0] - background_tl[0]),
                abs(background_br[1] - background_tl[1]),
            )
            pygame.draw.rect(screen, (15, 18, 22), background)

        nodes = payload.get("nodes", {})
        for parent_id, child_id in payload.get("edges", []):
            parent = nodes.get(parent_id)
            child = nodes.get(child_id)
            if not parent or not child:
                continue
            parent_mid = camera.world_to_screen((parent["x"] + parent["width"], parent["y"] + parent["height"] / 2.0))
            child_mid = camera.world_to_screen((child["x"], child["y"] + child["height"] / 2.0))
            if parent_mid is None or child_mid is None:
                continue
            elbow_x = (parent_mid[0] + child_mid[0]) // 2
            pygame.draw.line(screen, (104, 122, 150), parent_mid, (elbow_x, parent_mid[1]), 2)
            pygame.draw.line(screen, (104, 122, 150), (elbow_x, parent_mid[1]), (elbow_x, child_mid[1]), 2)
            pygame.draw.line(screen, (104, 122, 150), (elbow_x, child_mid[1]), child_mid, 2)

        for clade_id, rect_data in nodes.items():
            node_rect = self._world_rect_to_screen(camera, rect_data)
            if node_rect is None or node_rect.width < 3 or node_rect.height < 3:
                continue
            fill, border = self._node_colors(clade_id, rect_data, payload)
            pygame.draw.rect(screen, fill, node_rect)
            band = self._node_band_color(rect_data)
            if band is not None:
                pygame.draw.rect(screen, band, pygame.Rect(node_rect.x, node_rect.y, min(6, node_rect.width), node_rect.height))
            pygame.draw.rect(screen, border, node_rect, 1)
            if node_rect.width >= 48 and node_rect.height >= 16:
                band_offset = 6 if band is not None else 0
                label = self._label_for_width(rect_data.get("label", clade_id), font, node_rect.width - 12 - band_offset)
                surface = font.render(label, True, (236, 240, 246))
                label_rect = node_rect.move(band_offset // 2, 0)
                screen.blit(surface, surface.get_rect(center=label_rect.center))
