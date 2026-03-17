import os
import sys
import random
import pygame

from scripts.sim_core.space.orbit_visualizer import draw_orbit
from scripts.sim_core.locations.map_layers import MapLayerStack
from scripts.sim_core.space.system import CelestialSystem

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

from scripts.sim_core.window import SimWindow
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

        # --------------------------------------------------
        # Camera (solar scale)
        # --------------------------------------------------

        self.camera.zoom = 1e-9

        # --------------------------------------------------
        # Celestial system
        # --------------------------------------------------

        self.system = CelestialSystem()

        # --------------------------
        # Sun
        # --------------------------

        self.sun_object = SpaceObject(
            name="sun",
            mass=1.989e30,
            position=(0.0, 0.0)
        )

        self.system.add(
            self.sun_object,
            name="sun",
            layers=None
        )

        # --------------------------
        # Earth
        # --------------------------

        earth_size = 22_585_000

        self.earth_layers = MapLayerStack(earth_size)

        self.earth_object = SpaceObject(
            name="earth",
            mass=5.972e24,
            orbit=KeplerOrbit(
                parent=self.sun_object,
                a=149_600_000_000,
                e=0.0167
            )
        )

        self.system.add(
            self.earth_object,
            name="earth",
            layers=self.earth_layers
        )

        # --------------------------
        # Moon
        # --------------------------

        moon_size = 6_159_000

        self.moon_layers = MapLayerStack(moon_size)

        self.moon_object = SpaceObject(
            name="moon",
            mass=7.342e22,
            orbit=KeplerOrbit(
                parent=self.earth_object,
                a=384_400_000,
                e=0.0549
            )
        )

        self.system.add(
            self.moon_object,
            name="moon",
            layers=self.moon_layers
        )

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    def update(self, dt):

        self.sim_clock.update(dt)

        while self.sim_clock.should_step():
            sim_dt = self.sim_clock.consume_step()

            # hierarchical update handled by system order
            self.system.update(sim_dt)

    # --------------------------------------------------
    # Input
    # --------------------------------------------------

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

    # --------------------------------------------------
    # Time formatting
    # --------------------------------------------------

    def format_sim_time(self):

        total_seconds = int(self.sim_clock.time)

        seconds = total_seconds % 60
        minutes = (total_seconds // 60) % 60
        hours = (total_seconds // 3600) % 24
        days = (total_seconds // 86400) % 365

        years = self.year + (total_seconds // (86400 * 365))

        return f"Y {years} | D {days:03} | {hours:02}:{minutes:02}:{seconds:02}"

    # --------------------------------------------------
    # WORLD DRAW
    # --------------------------------------------------

    def draw_world(self):

        # ---- orbit paths ----

        for body in self.system.get_entries():

            obj = body["object"]
            orbit = getattr(obj, "orbit", None)

            if orbit is None:
                continue

            draw_orbit(self.screen, self.camera, orbit)

        # ---- bodies ----

        for body in self.system.get_entries():

            obj = body["object"]
            bx, by = obj.get_position()

            layer_stack = body["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            for layer in layers:

                x = layer["x"] + bx
                y = layer["y"] + by
                size = layer["size"]

                tl = self.camera.world_to_screen((x, y))
                br = self.camera.world_to_screen((x + size, y + size))

                rect = pygame.Rect(tl[0], tl[1], br[0] - tl[0], br[1] - tl[1])

                pygame.draw.rect(self.screen, layer["color"], rect)
                pygame.draw.rect(self.screen, (220, 220, 220), rect, 2)

                if self.camera.zoom > 0.8:
                    text = self.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )
                    self.screen.blit(text, (rect.x + 6, rect.y + 6))

        # ---- entities ----

        for entity_id, entity in self.entities.items():

            pos = self.entity_positions.get(entity_id)
            if pos is None:
                continue

            t = entity.get("type", "unknown")

            color = (
                (80, 160, 255) if t == "culture"
                else (180, 80, 255) if t == "cultural_aspect"
                else (200, 200, 200)
            )

            sp = self.camera.world_to_screen(pos)
            radius = max(3, int(6 * self.camera.zoom))

            pygame.draw.circle(self.screen, color, sp, radius)

            if self.camera.zoom > 1.8:
                text = self.default_font.render(
                    entity.get("name", entity_id),
                    True,
                    (200, 200, 200)
                )
                self.screen.blit(text, (sp[0] + 8, sp[1] - 8))

    # --------------------------------------------------
    # UI DRAW
    # --------------------------------------------------

    def draw_ui(self):

        super().draw_ui()

        label = self.default_font.render(
            f"{self.format_sim_time()} | TICK {self.sim_clock.tick}",
            True,
            (220, 220, 220)
        )
        self.screen.blit(label, (20, 20))

        entity_label = self.default_font.render(
            f"ACTIVE ENTITIES {len(self.entities)}",
            True,
            (160, 160, 160)
        )
        self.screen.blit(entity_label, (20, 50))

        time_label = self.default_font.render(
            f"TIME SCALE x{self.sim_clock.time_scale:.2f}",
            True,
            (180, 180, 180)
        )
        self.screen.blit(time_label, (20, 80))

        mouse = pygame.mouse.get_pos()

        wx = int((mouse[0] - self.width / 2) / self.camera.zoom + self.camera.x)
        wy = int((mouse[1] - self.height / 2) / self.camera.zoom + self.camera.y)

        mouse_text = self.default_font.render(
            f"mouse world: {wx} , {wy}",
            True,
            (150, 150, 150)
        )

        self.screen.blit(mouse_text, (20, 110))


def main():

    sim = TestSimulation()
    sim.run()


if __name__ == "__main__":
    main()