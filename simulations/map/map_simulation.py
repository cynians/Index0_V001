from engine.logger import logger


class MapSimulation:
    """
    Pure map simulation (entity-driven).

    In map mode, planets are rendered as 2D surface containers rather than
    physical spheres. Child regions are expected to use projected map-space
    coordinates inside that container.

    Selection ownership also lives here:
    * click handling is map-specific
    * picking is done in world/map coordinates
    * selected entity state is stored on the simulation
    * hover state is stored on the simulation
    """

    MAP_PLANET_WIDTH = 4000
    MAP_PLANET_HEIGHT = 2000

    def __init__(self, simulation_context):
        from engine.clock import Clock
        from engine.simulation_manager import SimulationManager

        self.render_mode = "map"

        self.context = simulation_context
        self.world_model = simulation_context.world_model

        self.sim_clock = Clock(base_dt=1.0)

        class _DummySystem:
            def update(self, dt):
                pass

        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 0.02
        self.max_zoom = 10.0
        self.preferred_zoom = 0.22

        self._layer_cache = None
        self._cache_year = None

        self.selected_entity_id = None
        self.hover_entity_id = None
        self.hover_screen_pos = None

    @property
    def year(self):
        return getattr(self.context, "year", 0)

    def get_root_entity(self):
        return self.world_model.get_entity(self.context.root_entity_id)

    def get_root_name(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return self.context.root_entity_id
        return root_entity.get("name", self.context.root_entity_id)

    def get_parent_root_entity_id(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None
        return root_entity.get("parent_location")

    def get_scope_breadcrumb(self):
        """
        Return a root breadcrumb from top ancestor down to the current root.
        """
        breadcrumb = []
        visited = set()
        current_entity = self.get_root_entity()

        while current_entity:
            entity_id = current_entity.get("id")
            if entity_id in visited:
                break

            visited.add(entity_id)
            breadcrumb.append(current_entity.get("name", entity_id))

            parent_id = current_entity.get("parent_location")
            if not parent_id:
                break

            current_entity = self.world_model.get_entity(parent_id)

        breadcrumb.reverse()
        return breadcrumb

    def _color_for_entity(self, entity):
        location_class = entity.get("location_class")

        if location_class == "planet":
            return (70, 90, 120)

        if location_class == "continent":
            return (120, 140, 170)

        if location_class == "country":
            return (155, 170, 195)

        if location_class == "region":
            return (180, 190, 205)

        if location_class == "city":
            return (220, 220, 220)

        return (200, 200, 200)

    def _build_layers(self, year):
        """
        Build render layers from active entities.

        Supported map geometry:
        * planet       -> map_rect surface container
        * bbox region  -> rect
        * point place  -> marker
        """
        layers = []

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entity_id = entity.get("id")

            coords = entity.get("coords") or {}
            bounds = entity.get("bounds") or {}

            x = None
            y = None

            if coords.get("type") == "point":
                x = coords.get("x", 0)
                y = coords.get("y", 0)

            location_class = entity.get("location_class")
            color = self._color_for_entity(entity)

            if location_class == "planet":
                if x is None or y is None:
                    x = 0
                    y = 0

                layers.append({
                    "shape": "map_rect",
                    "x": x,
                    "y": y,
                    "width_world": self.MAP_PLANET_WIDTH,
                    "height_world": self.MAP_PLANET_HEIGHT,
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                })
                continue

            if bounds.get("type") == "bbox":
                min_x = bounds.get("min_x", 0)
                max_x = bounds.get("max_x", 0)
                min_y = bounds.get("min_y", 0)
                max_y = bounds.get("max_y", 0)

                width_world = max_x - min_x
                height_world = max_y - min_y

                if x is None or y is None:
                    x = (min_x + max_x) / 2
                    y = (min_y + max_y) / 2

                layers.append({
                    "shape": "rect",
                    "x": x,
                    "y": y,
                    "width_world": width_world,
                    "height_world": height_world,
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                })
                continue

            if x is None or y is None:
                continue

            layers.append({
                "shape": "marker",
                "x": x,
                "y": y,
                "min_screen_size": 8,
                "name": entity.get("name"),
                "entity_id": entity_id,
                "color": color,
            })

        return layers

    def get_layers(self):
        year = self.year

        if self._layer_cache is None or self._cache_year != year:
            logger.debug(
                f"[MapSimulation] Rebuilding layer cache for year {year}",
                key="map_layers_build",
                interval=0.5
            )
            self._layer_cache = self._build_layers(year)
            self._cache_year = year

        return self._layer_cache

    def get_entries(self):
        entries = []

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entries.append({
                "entity": entity,
                "name": entity.get("name"),
                "entity_id": entity.get("id"),
            })

        return entries

    def _screen_to_world(self, camera, screen_pos):
        sx, sy = screen_pos

        world_x = (sx - camera.width / 2) / camera.zoom + camera.x
        world_y = (sy - camera.height / 2) / camera.zoom + camera.y

        return world_x, world_y

    def _point_in_rect_layer(self, world_x, world_y, layer):
        half_w = layer.get("width_world", 0) / 2
        half_h = layer.get("height_world", 0) / 2

        min_x = layer["x"] - half_w
        max_x = layer["x"] + half_w
        min_y = layer["y"] - half_h
        max_y = layer["y"] + half_h

        return min_x <= world_x <= max_x and min_y <= world_y <= max_y

    def _point_in_marker_layer(self, world_x, world_y, layer, camera):
        pick_radius_world = max(12.0 / max(camera.zoom, 1e-9), 8.0)

        dx = world_x - layer["x"]
        dy = world_y - layer["y"]

        return (dx * dx + dy * dy) <= (pick_radius_world * pick_radius_world)

    def _pick_layer_at_world(self, world_x, world_y, camera):
        """
        Pick from topmost to bottommost.

        Reverse iteration matters so that:
        * Berlin beats Germany
        * Germany beats Europe
        * Europe beats Earth
        """
        layers = self.get_layers()

        for layer in reversed(layers):
            shape = layer.get("shape", "marker")

            if shape in ("map_rect", "rect"):
                if self._point_in_rect_layer(world_x, world_y, layer):
                    return layer

            elif shape == "marker":
                if self._point_in_marker_layer(world_x, world_y, layer, camera):
                    return layer

        return None

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Update hover state from pointer motion.
        """
        world_x, world_y = self._screen_to_world(camera, screen_pos)
        picked_layer = self._pick_layer_at_world(world_x, world_y, camera)

        if picked_layer is None:
            self.hover_entity_id = None
            self.hover_screen_pos = None
            return

        self.hover_entity_id = picked_layer.get("entity_id")
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Handle pointer input for the map simulation.

        This method receives screen coordinates from the app and performs
        picking in world/map coordinates.
        """
        world_x, world_y = self._screen_to_world(camera, screen_pos)
        picked_layer = self._pick_layer_at_world(world_x, world_y, camera)

        self.hover_screen_pos = screen_pos
        self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None

        if picked_layer is None:
            self.selected_entity_id = None
            return

        self.selected_entity_id = picked_layer.get("entity_id")

        logger.debug(
            f"[MapSimulation] Selected entity: {self.selected_entity_id}",
            key="map_selection",
            interval=0.1
        )

    def get_center(self):
        return 0.0, 0.0

    def update(self, dt):
        self.sim_manager.update(dt)