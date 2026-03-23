class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI).

    This version loads the orbital system from world entries instead of
    hardcoding Sun / Earth / Moon directly in the simulation.
    """

    def __init__(self, world_model=None, root_system_id="system_sol", year=2400):
        from engine.clock import Clock
        from simulations.space.system import CelestialSystem
        from engine.simulation_manager import SimulationManager
        from world.world_model import WorldModel

        self.render_mode = "space"

        self.year = year
        self.root_system_id = root_system_id

        self.world_model = world_model if world_model is not None else WorldModel()

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1e-13
        self.max_zoom = 1e-6
        self.preferred_zoom = 1.0e-10

        self.selected_space_object = None
        self.selected_system_entity_id = None
        self.hover_space_object = None
        self.hover_system_entity_id = None
        self.hover_screen_pos = None

        self.system.populate_from_world_model(
            world_model=self.world_model,
            year=self.year,
            root_system_id=self.root_system_id
        )

    def get_center(self):
        return 0.0, 0.0

    def update(self, dt):
        self.sim_manager.update(dt)

    def get_entity(self, space_object, world_model=None):
        """
        Resolve world entity from a space object.

        If no world_model is provided, use the simulation's own world model.
        """
        if space_object.entity_id is None:
            return None

        model = world_model if world_model is not None else self.world_model
        entity = model.get_entity(space_object.entity_id)
        space_object.entity = entity
        return entity

    def get_selected_body_entity(self):
        """
        Return the source systems.yaml entity for the currently selected body.
        """
        if self.selected_space_object is None:
            return None
        return self.system.get_source_entity_for_space_object(self.selected_space_object)

    def _pick_space_object(self, camera, screen_pos):
        """
        Pick the nearest visible body under the cursor using a screen-space radius.
        """
        sx, sy = screen_pos
        best_obj = None
        best_dist_sq = None

        for entry in self.system.get_entries():
            obj = entry["object"]
            bx, by = obj.get_position()

            center = camera.world_to_screen((bx, by))
            if center is None:
                continue

            layer_stack = entry["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            max_pixel_radius = 0
            for layer in layers:
                pixel_size = max(1, int(layer["size"] * camera.zoom))
                max_pixel_radius = max(max_pixel_radius, pixel_size // 2)

            pick_radius = max(8, max_pixel_radius + 6)

            dx = sx - center[0]
            dy = sy - center[1]
            dist_sq = dx * dx + dy * dy

            if dist_sq > pick_radius * pick_radius:
                continue

            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_obj = obj
                best_dist_sq = dist_sq

        return best_obj

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Update hover state from pointer motion.
        """
        picked_obj = self._pick_space_object(camera, screen_pos)

        self.hover_space_object = picked_obj
        self.hover_screen_pos = screen_pos

        if picked_obj is None:
            self.hover_system_entity_id = None
            return

        source_entity = self.system.get_source_entity_for_space_object(picked_obj)
        self.hover_system_entity_id = source_entity.get("id") if source_entity else None

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Handle pointer input for the space simulation.
        """
        picked_obj = self._pick_space_object(camera, screen_pos)

        self.hover_space_object = picked_obj
        self.hover_screen_pos = screen_pos

        if picked_obj is None:
            self.selected_space_object = None
            self.selected_system_entity_id = None
            self.hover_system_entity_id = None
            return

        self.selected_space_object = picked_obj

        source_entity = self.system.get_source_entity_for_space_object(picked_obj)
        self.selected_system_entity_id = source_entity.get("id") if source_entity else None
        self.hover_system_entity_id = self.selected_system_entity_id