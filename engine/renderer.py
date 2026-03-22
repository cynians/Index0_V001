import pygame

from simulations.space.orbit_visualizer import draw_orbit


class Renderer:
    """
    Handles all rendering.

    Responsibilities:
    * dispatch rendering by simulation render mode
    * draw world objects
    * draw UI overlays
    """

    def __init__(self, simulation):
        self.sim = simulation
        self.simulation = None
        self.screen = None

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
        sim = self.simulation
        render_mode = getattr(sim, "render_mode", None)

        if render_mode == "map":
            self.draw_map_simulation(sim)
            return

        if render_mode == "space":
            self.draw_space_simulation(sim)
            return

        # fallback for legacy objects
        if hasattr(sim, "system"):
            self.draw_space_simulation(sim)
            return

        if hasattr(sim, "get_layers"):
            self.draw_map_simulation(sim)
            return

    def draw_map_simulation(self, sim):
        view = self.sim

        for layer in sim.get_layers():
            center = view.camera.world_to_screen((layer["x"], layer["y"]))

            if center is None:
                continue

            pixel_size = max(1, int(layer["size"] * view.camera.zoom))

            rect = pygame.Rect(
                int(center[0] - pixel_size / 2),
                int(center[1] - pixel_size / 2),
                pixel_size,
                pixel_size,
            )

            if (
                rect.right < 0
                or rect.left > view.width
                or rect.bottom < 0
                or rect.top > view.height
            ):
                continue

            pygame.draw.rect(self.screen, layer["color"], rect)
            pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

            if rect.width >= 60 and rect.height >= 24:
                text = view.default_font.render(
                    layer.get("name", "layer"),
                    True,
                    (240, 240, 240)
                )
                self.screen.blit(text, (rect.x + 6, rect.y + 6))

    def draw_space_simulation(self, sim):
        view = self.sim

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

                center = view.camera.world_to_screen((x, y))

                if center is None:
                    continue

                pixel_size = max(1, int(size * view.camera.zoom))

                rect = pygame.Rect(
                    int(center[0] - pixel_size / 2),
                    int(center[1] - pixel_size / 2),
                    pixel_size,
                    pixel_size,
                )

                if (
                    rect.right < 0
                    or rect.left > view.width
                    or rect.bottom < 0
                    or rect.top > view.height
                ):
                    continue

                pygame.draw.rect(self.screen, layer["color"], rect)
                pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

                if rect.width >= 60 and rect.height >= 24:
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
        self.screen.blit(label, (20, 40))

        time_label = view.default_font.render(
            f"TIME SCALE x{sim.sim_clock.time_scale:.2f}",
            True,
            (180, 180, 180)
        )
        self.screen.blit(time_label, (20, 60))

        mouse = pygame.mouse.get_pos()

        wx = int((mouse[0] - view.width / 2) / view.camera.zoom + view.camera.x)
        wy = int((mouse[1] - view.height / 2) / view.camera.zoom + view.camera.y)

        mouse_text = view.default_font.render(
            f"mouse world: {wx} , {wy}",
            True,
            (150, 150, 150)
        )
        self.screen.blit(mouse_text, (20, 80))