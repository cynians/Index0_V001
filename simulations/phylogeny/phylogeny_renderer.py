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
            if clade_id == payload.get("selected_id"):
                fill = (66, 76, 48)
                border = (230, 212, 136)
            elif clade_id == payload.get("hover_id"):
                fill = (48, 66, 78)
                border = (154, 210, 236)
            elif clade_id == payload.get("focus_id"):
                fill = (56, 70, 92)
                border = (180, 204, 244)
            elif rect_data.get("species"):
                fill = (38, 42, 50)
                border = (118, 132, 156)
            else:
                fill = (34, 40, 52)
                border = (112, 128, 152)
            pygame.draw.rect(screen, fill, node_rect)
            pygame.draw.rect(screen, border, node_rect, 1)
            if node_rect.width >= 48 and node_rect.height >= 16:
                label = self._label_for_width(rect_data.get("label", clade_id), font, node_rect.width - 12)
                surface = font.render(label, True, (236, 240, 246))
                screen.blit(surface, surface.get_rect(center=node_rect.center))
