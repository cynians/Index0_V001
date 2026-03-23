from simulations.bioregion.bioregion_renderer import BioregionRenderer
from simulations.map.map_renderer import MapRenderer
from simulations.space.space_renderer import SpaceRenderer


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

        self.bioregion_renderer = BioregionRenderer(simulation)
        self.map_renderer = MapRenderer(simulation)
        self.space_renderer = SpaceRenderer(simulation)

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

        if render_mode == "bioregion":
            self.bioregion_renderer.draw(self.screen, sim)
            return

        if render_mode == "map":
            self.map_renderer.draw(self.screen, sim)
            return

        if render_mode == "space":
            self.space_renderer.draw(self.screen, sim)
            return

        if hasattr(sim, "system"):
            self.space_renderer.draw(self.screen, sim)
            return

        if hasattr(sim, "get_layers"):
            self.map_renderer.draw(self.screen, sim)
            return

    # --------------------------------------------------
    # UI DRAW
    # --------------------------------------------------

    def draw_ui(self):
        """
        App/UI chrome now lives in UIManager.
        Renderer no longer draws tab/time/status overlays.
        """
        return