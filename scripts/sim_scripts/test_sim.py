import os
import sys
import random
import pygame

# --------------------------------------------------
# Import path setup
# --------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
SCRIPTS_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))

if SCRIPTS_DIR not in sys.path:
    sys.path.append(SCRIPTS_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from scripts.sim_core.window  import SimWindow
from scripts.sim_core.clock import Clock
from scripts.sim_core.space.object import SpaceObject
from scripts.sim_core.space.orbit import KeplerOrbit

# optional knowledge-layer attach
try:
    from tools.world_model import WorldModel
    WORLD_AVAILABLE = True
except Exception:
    WORLD_AVAILABLE = False


class TestSimulation(SimWindow):

    def __init__(self):

        super().__init__(
            width=1200,
            height=800,
            title="Index_0 Test Simulation"
        )

        random.seed(1)

        self.year = 2400

        self.world = None
        self.entities = {}
        self.entity_positions = {}

        # --------------------------------------------------
        # World attach
        # --------------------------------------------------

        if WORLD_AVAILABLE:
            try:

                self.world = WorldModel()
                self.entities = self.world.entities_active(self.year)

                print(
                    f"[SIM] World attached: {len(self.entities)} active entities at year {self.year}"
                )

                for entity_id in self.entities:

                    x = random.randint(-2000, 2000)
                    y = random.randint(-2000, 2000)

                    self.entity_positions[entity_id] = (x, y)

            except Exception as exc:

                print(f"[SIM] World attach failed: {exc}")
                self.world = None
                self.entities = {}

        # --------------------------------------------------
        # Simulation clock
        # --------------------------------------------------

        self.sim_clock = Clock(base_dt=4.8)

        # ------------------------------------------
        # Simulation tick limiter (5 Hz)
        # ------------------------------------------

        self._sim_accumulator = 0.0
        self._sim_tick_interval = 0.2  # 5 ticks per second

        # --------------------------------------------------
        # Create planetary bodies
        # --------------------------------------------------

        self.bodies = []

        # Earth
        earth_layers = self.generate_layers()

        self.earth_object = SpaceObject(
            name="earth",
            mass=5.972e24,
            position=(0.0, 0.0)
        )

        earth = {
            "name": "earth",
            "object": self.earth_object,
            "pos": self.earth_object.get_position(),
            "layers": earth_layers
        }

        self.bodies.append(earth)

        # Moon
        moon_layers = self.generate_layers()

        self.moon_object = SpaceObject(
            name="moon",
            mass=7.342e22,
            orbit=KeplerOrbit(
                parent=self.earth_object,
                a=6_000_000,
                e=0.0
            )
        )

        moon = {
            "name": "moon",
            "object": self.moon_object,
            "pos": self.moon_object.get_position(),
            "layers": moon_layers
        }

        self.bodies.append(moon)

    # --------------------------------------------------
    # Layer generator
    # --------------------------------------------------

    def generate_layers(self):

        layers = []

        sizes = [
            ("planet", 2_000_000),
            ("continent", 600_000),
            ("region", 150_000),
            ("city", 40_000),
            ("production_site", 8_000),
            ("building", 1200)
        ]

        shades = [
            (60, 60, 60),
            (75, 75, 75),
            (90, 90, 90),
            (110, 110, 110),
            (130, 130, 130),
            (160, 160, 160)
        ]

        parent_x = -sizes[0][1] / 2
        parent_y = -sizes[0][1] / 2
        parent_size = sizes[0][1]

        for i, (name, size) in enumerate(sizes):

            if i == 0:

                x = parent_x
                y = parent_y

            else:

                margin = parent_size - size

                x = parent_x + random.uniform(0, margin)
                y = parent_y + random.uniform(0, margin)

            layer = {
                "name": name,
                "x": x,
                "y": y,
                "size": size,
                "color": shades[i]
            }

            layers.append(layer)

            parent_x = x
            parent_y = y
            parent_size = size

        return layers

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    def update(self, dt):

        # update clock (real time)
        self.sim_clock.update(dt)

        # run simulation steps if needed
        while self.sim_clock.should_step():
            sim_dt = self.sim_clock.consume_step()

            self.earth_object.update(sim_dt)
            self.moon_object.update(sim_dt)

            # sync positions
            self.bodies[0]["pos"] = self.earth_object.get_position()
            self.bodies[1]["pos"] = self.moon_object.get_position()

    def handle_event(self, event):

        if event.type == pygame.KEYDOWN:

            if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.sim_clock.set_time_scale(self.sim_clock.time_scale + 0.25)

            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.sim_clock.set_time_scale(self.sim_clock.time_scale - 0.25)

            elif event.key == pygame.K_0:
                self.sim_clock.set_time_scale(1.0)

            elif event.key == pygame.K_SPACE:
                self.sim_clock.toggle_pause()

    def format_sim_time(self):

        total_seconds = int(self.sim_clock.time)

        seconds = total_seconds % 60
        minutes = (total_seconds // 60) % 60
        hours = (total_seconds // 3600) % 24
        days = (total_seconds // 86400) % 365

        years = self.year + (total_seconds // (86400 * 365))

        return f"Y {years} | D {days:03} | {hours:02}:{minutes:02}:{seconds:02}"
    # --------------------------------------------------
    # Draw
    # --------------------------------------------------

    def draw(self):

        super().draw()

        # --------------------------------------------------
        # UI text
        # --------------------------------------------------

        label = self.default_font.render(
            f"{self.format_sim_time()} | TICK {self.sim_clock.tick}",
            True,
            (220, 220, 220)
        )
        self.screen.blit(label, (20, 20))

        time_label = self.default_font.render(
            f"TIME SCALE x{self.sim_clock.time_scale:.2f}",
            True,
            (180, 180, 180)
        )
        self.screen.blit(time_label, (20, 110))

        entity_label = self.default_font.render(
            f"ACTIVE ENTITIES {len(self.entities)}",
            True,
            (160, 160, 160)
        )
        self.screen.blit(entity_label, (20, 50))

        # --------------------------------------------------
        # Draw planetary bodies
        # --------------------------------------------------

        for body in self.bodies:

            bx, by = body["pos"]

            for layer in body["layers"]:

                x = layer["x"] + bx
                y = layer["y"] + by
                size = layer["size"]

                top_left = self.camera.world_to_screen((x, y))
                bottom_right = self.camera.world_to_screen((x + size, y + size))

                width = bottom_right[0] - top_left[0]
                height = bottom_right[1] - top_left[1]

                rect = pygame.Rect(
                    top_left[0],
                    top_left[1],
                    width,
                    height
                )

                pygame.draw.rect(
                    self.screen,
                    layer["color"],
                    rect
                )

                pygame.draw.rect(
                    self.screen,
                    (220, 220, 220),
                    rect,
                    2
                )

                if self.camera.zoom > 0.8:

                    text = self.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )

                    self.screen.blit(
                        text,
                        (rect.x + 6, rect.y + 6)
                    )

        # --------------------------------------------------
        # Draw entities
        # --------------------------------------------------

        for entity_id, entity in self.entities.items():

            pos = self.entity_positions.get(entity_id)

            if pos is None:
                continue

            entity_type = entity.get("type", "unknown")

            if entity_type == "culture":
                color = (80, 160, 255)

            elif entity_type == "cultural_aspect":
                color = (180, 80, 255)

            else:
                color = (200, 200, 200)

            screen_pos = self.camera.world_to_screen(pos)

            radius = max(3, int(6 * self.camera.zoom))

            pygame.draw.circle(
                self.screen,
                color,
                screen_pos,
                radius
            )

            if self.camera.zoom > 1.8:

                name = entity.get("name", entity_id)

                text = self.default_font.render(
                    name,
                    True,
                    (200, 200, 200)
                )

                self.screen.blit(
                    text,
                    (screen_pos[0] + 8, screen_pos[1] - 8)
                )

        # --------------------------------------------------
        # Mouse world position debug
        # --------------------------------------------------

        mouse = pygame.mouse.get_pos()

        world_x = int((mouse[0] - self.width / 2) / self.camera.zoom + self.camera.x)
        world_y = int((mouse[1] - self.height / 2) / self.camera.zoom + self.camera.y)

        mouse_text = self.default_font.render(
            f"mouse world: {world_x} , {world_y}",
            True,
            (150, 150, 150)
        )

        self.screen.blit(mouse_text, (20, 80))


def main():

    sim = TestSimulation()
    sim.run()


if __name__ == "__main__":
    main()