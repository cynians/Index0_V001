from simulations.bioregion.bioregion_renderer import BioregionRenderer
from simulations.map.map_renderer import MapRenderer
from simulations.space.space_renderer import SpaceRenderer
from simulations.vehicle.vehicle_renderer import VehicleRenderer
from simulations.world_gen.world_gen_renderer import WorldGenRenderer
from simulations.phylogeny.phylogeny_renderer import PhylogenyRenderer
from simulations.person.person_renderer import PersonRenderer
from simulations.formation.formation_renderer import FormationRenderer


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
        self.vehicle_renderer = VehicleRenderer(simulation)
        self.world_gen_renderer = WorldGenRenderer(simulation)
        self.phylogeny_renderer = PhylogenyRenderer(simulation)
        self.person_renderer = PersonRenderer(simulation)
        self.formation_renderer = FormationRenderer(simulation)

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

        if render_mode == "world_gen":
            self.world_gen_renderer.draw(self.screen, sim)
            return

        if render_mode == "vehicle":
            self.vehicle_renderer.draw(self.screen, sim)
            return

        if render_mode in {"person", "site_people"}:
            self.person_renderer.draw(self.screen, sim)
            return

        if render_mode == "formation":
            self.formation_renderer.draw(self.screen, sim)
            return

        if render_mode == "phylogeny":
            self.phylogeny_renderer.draw(self.screen, sim)
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
