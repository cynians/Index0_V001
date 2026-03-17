import pygame

from scripts.sim_core.space.orbit_visualizer import draw_orbit


class Renderer:
    """
    Handles all rendering.

    Responsibilities:
    * draw world objects
    * draw UI overlays
    """

    def __init__(self, simulation):

        self.sim = simulation      # App (view)
        self.simulation = None     # active simulation (logic)

    # --------------------------------------------------
    # MAIN ENTRY
    # --------------------------------------------------

    def draw(self, screen):

        if self.simulation is None:
            return

        self.screen = screen

        self.draw_world()
        self.draw_ui()

    # --------------------------------------------------
    # WORLD DRAW
    # --------------------------------------------------

    def draw_world(self):

        view = self.sim
        sim = self.simulation

        # ---- orbit paths ----
        for body in sim.system.get_entries():

            obj = body["object"]
            orbit = getattr(obj, "orbit", None)

            if orbit is None:
                continue

            draw_orbit(self.screen, view.camera, orbit)

        # ---- bodies ----
        for body in sim.system.get_entries():

            obj = body["object"]
            bx, by = obj.get_position()

            layer_stack = body["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            for layer in layers:

                x = layer["x"] + bx
                y = layer["y"] + by
                size = layer["size"]

                tl = view.camera.world_to_screen((x, y))
                br = view.camera.world_to_screen((x + size, y + size))

                if tl is None or br is None:
                    continue

                rect = pygame.Rect(
                    tl[0],
                    tl[1],
                    br[0] - tl[0],
                    br[1] - tl[1]
                )

                pygame.draw.rect(self.screen, layer["color"], rect)
                pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

                if view.camera.zoom > 0.8:
                    text = view.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )
                    self.screen.blit(text, (rect.x + 6, rect.y + 6))

    # --------------------------------------------------
    # UI DRAW
    # --------------------------------------------------

    def draw_ui(self):

        view = self.sim
        sim = self.simulation

        # --------------------------------------------------
        # TAB BAR
        # --------------------------------------------------

        tab_manager = view.tab_manager

        x_offset = 20
        y_offset = 5
        padding = 10

        for i, tab in enumerate(tab_manager.tabs):

            label = tab.name

            text_surface = view.default_font.render(
                label,
                True,
                (255, 255, 255)
            )

            text_rect = text_surface.get_rect()

            rect = pygame.Rect(
                x_offset,
                y_offset,
                text_rect.width + padding * 2,
                text_rect.height + padding
            )

            # highlight active tab
            if i == tab_manager.active_index:
                pygame.draw.rect(self.screen, (80, 80, 120), rect)
            else:
                pygame.draw.rect(self.screen, (40, 40, 40), rect)

            pygame.draw.rect(self.screen, (200, 200, 200), rect, 1)

            self.screen.blit(
                text_surface,
                (rect.x + padding, rect.y + padding // 2)
            )

            x_offset += rect.width + 5

        label = view.default_font.render(
            f"Y {sim.year} | TICK {sim.sim_clock.tick}",
            True,
            (220, 220, 220)
        )
        self.screen.blit(label, (20, 20))

        time_label = view.default_font.render(
            f"TIME SCALE x{sim.sim_clock.time_scale:.2f}",
            True,
            (180, 180, 180)
        )
        self.screen.blit(time_label, (20, 50))

        mouse = pygame.mouse.get_pos()

        wx = int((mouse[0] - view.width / 2) / view.camera.zoom + view.camera.x)
        wy = int((mouse[1] - view.height / 2) / view.camera.zoom + view.camera.y)

        mouse_text = view.default_font.render(
            f"mouse world: {wx} , {wy}",
            True,
            (150, 150, 150)
        )

        self.screen.blit(mouse_text, (20, 80))