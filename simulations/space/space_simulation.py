class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI).

    This version loads the orbital system from world entries instead of
    hardcoding Sun / Earth / Moon directly in the simulation.
    """

    def __init__(self, world_model=None, root_system_id="system_sol", year=2400, root_body_id=None):
        from engine.clock import Clock
        from simulations.space.system import CelestialSystem
        from engine.simulation_manager import SimulationManager
        from world.world_model import WorldModel

        self.render_mode = "space"

        self.year = year
        self.root_system_id = root_system_id
        self.root_body_id = root_body_id

        self.world_model = world_model if world_model is not None else WorldModel()

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1e-17
        self.max_zoom = 1e-6
        self.preferred_zoom = 1.0e-10
        if self.root_body_id is not None:
            self.min_zoom = 1e-10
            self.max_zoom = 2e-5
            self.preferred_zoom = 2.0e-9

        self.selected_space_object = None
        self.selected_system_entity_id = None
        self.hover_space_object = None
        self.hover_system_entity_id = None
        self.hover_screen_pos = None
        self.body_label_hitboxes = []

        self.system.populate_from_world_model(
            world_model=self.world_model,
            year=self.year,
            root_system_id=self.root_system_id,
            root_body_id=self.root_body_id,
        )
        self._loaded_repository_revision = getattr(self.world_model, "repository_revision", 0)

    def get_center(self):
        return 0.0, 0.0

    def get_scope_label(self):
        if self.root_body_id is None:
            root = self.world_model.get_entity(self.root_system_id)
            return root.get("name", self.root_system_id) if root else self.root_system_id

        body = self.world_model.get_entity(self.root_body_id)
        return body.get("name", self.root_body_id) if body else self.root_body_id

    def get_scope_breadcrumb(self):
        if self.root_body_id is None:
            return "Full star system"
        return "Local planetary space"

    def update(self, dt):
        repository_revision = getattr(self.world_model, "repository_revision", 0)
        if repository_revision != self._loaded_repository_revision:
            self.system.populate_from_world_model(
                world_model=self.world_model,
                year=self.year,
                root_system_id=self.root_system_id,
                root_body_id=self.root_body_id,
            )
            self._loaded_repository_revision = repository_revision
            self.selected_space_object = None
            self.selected_system_entity_id = None
            self.hover_space_object = None
            self.hover_system_entity_id = None
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
        Return the source orbital entity for the currently selected body.
        """
        if self.selected_space_object is None:
            return None
        return self.system.get_source_entity_for_space_object(self.selected_space_object)

    def get_selection_inspector_payload(self):
        entity = self.get_selected_body_entity()
        if not entity:
            return None

        entity_id = entity.get("id")
        body_class = (
            entity.get("body_class")
            or entity.get("location_class")
            or entity.get("type", "body")
        )
        details = [
            f"Class: {body_class}",
            f"Repository ID: {entity_id}",
        ]
        start_year = entity.get("start_year")
        end_year = entity.get("end_year")
        if start_year not in (None, "") or end_year not in (None, ""):
            active_start = start_year if start_year not in (None, "") else "?"
            active_end = end_year if end_year not in (None, "") else "present"
            details.append(f"Active: {active_start} to {active_end}")

        return {
            "entity_id": entity_id,
            "title": entity.get("pretty_name") or entity.get("name") or entity_id,
            "kind": "Space body",
            "details": details,
            "actions": [
                {"id": "open_selection_wiki", "label": "Open Wiki Entry"},
            ] if entity_id else [],
        }

    def clear_body_label_hitboxes(self):
        self.body_label_hitboxes = []

    def register_body_label_hitbox(self, source_entity_id, rect):
        if not source_entity_id or rect is None:
            return
        for entry in self.system.get_entries():
            obj = entry["object"]
            source = self.system.get_source_entity_for_space_object(obj)
            if isinstance(source, dict) and source.get("id") == source_entity_id:
                self.body_label_hitboxes.append(
                    {
                        "entity_id": source_entity_id,
                        "object": obj,
                        "rect": rect.copy(),
                    }
                )
                return

    def _pick_labelled_space_object(self, screen_pos):
        for hitbox in reversed(self.body_label_hitboxes):
            rect = hitbox.get("rect")
            if rect is not None and rect.collidepoint(screen_pos):
                return hitbox.get("object")
        return None

    def _pick_space_object(self, camera, screen_pos):
        """
        Pick the nearest visible body under the cursor using a screen-space radius.
        """
        labelled_obj = self._pick_labelled_space_object(screen_pos)
        if labelled_obj is not None:
            return labelled_obj

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
