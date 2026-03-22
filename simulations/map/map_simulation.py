class MapSimulation:
    """
    Map simulation driven by SimulationContext.
    """

    def __init__(self, context):
        from engine.clock import Clock
        from simulations.map.map_layers import MapLayerStack

        self.render_mode = "map"

        self.context = context
        self.year = context.year

        self.sim_clock = Clock(base_dt=4.8)

        self.map_size = 50_000_000
        self.map_layers = MapLayerStack(self.map_size)
        self.origin = (0, 0)

        half = self.map_size // 2
        self.bounds = {
            "min_x": -half,
            "max_x": half,
            "min_y": -half,
            "max_y": half,
        }

        self.min_zoom = 1e-8
        self.max_zoom = 1e-3
        self.preferred_zoom = min(1200 / self.map_size, 800 / self.map_size) * 0.9

        self.entities_by_id = {}
        self.root_entities = []

        self.reload_from_context()

    # --------------------------------------------------
    # Context loading
    # --------------------------------------------------

    def reload_from_context(self):
        location_entities = self.context.get_active_locations()
        self.build_entity_graph(location_entities)
        self.build_layers_from_entities()

    # --------------------------------------------------
    # Runtime
    # --------------------------------------------------

    def update(self, dt):
        self.sim_clock.update(dt)

        while self.sim_clock.should_step():
            self.sim_clock.consume_step()

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def get_layers(self):
        layers = []

        for layer in self.map_layers.get_layers():
            layers.append({
                "x": self.origin[0] + layer["x"],
                "y": self.origin[1] + layer["y"],
                "size": layer["size"],
                "color": layer["color"],
                "name": layer["name"],
            })

        return layers

    def get_center(self):
        return self.origin

    def get_entity(self, entity_id):
        return self.entities_by_id.get(entity_id)

    # --------------------------------------------------
    # Graph
    # --------------------------------------------------

    def build_entity_graph(self, entities):
        self.entities_by_id = {}
        self.root_entities = []

        local_entities = {}

        for entity in entities:
            entity_copy = dict(entity)
            entity_copy["children"] = []
            entity_copy["parent_ref"] = None
            local_entities[entity_copy["id"]] = entity_copy

        self.entities_by_id = local_entities

        for entity in self.entities_by_id.values():
            parent_id = entity.get("parent_location") or entity.get("parent")

            if parent_id and parent_id in self.entities_by_id:
                parent = self.entities_by_id[parent_id]
                parent["children"].append(entity)
                entity["parent_ref"] = parent
            else:
                self.root_entities.append(entity)

    # --------------------------------------------------
    # Layers
    # --------------------------------------------------

    def build_layers_from_entities(self):
        self.map_layers.clear()

        for entity in self.entities_by_id.values():
            layer = self.build_layer_for_entity(entity)

            if layer is not None:
                self.map_layers.add_layer(layer)

    def build_layer_for_entity(self, entity):
        bounds = entity.get("bounds")

        if not bounds:
            return None

        bounds_type = bounds.get("type")
        name = entity.get("name") or entity.get("id")

        if bounds_type == "radius":
            center = self.resolve_entity_center(entity)
            radius = bounds.get("value")

            return {
                "x": center["x"],
                "y": center["y"],
                "size": radius * 2,
                "color": (90, 90, 90),
                "name": name,
            }

        if bounds_type == "bbox":
            cx = (bounds["min_x"] + bounds["max_x"]) / 2
            cy = (bounds["min_y"] + bounds["max_y"]) / 2
            anchor = self.get_inherited_coords(entity) or {"x": 0, "y": 0}

            return {
                "x": anchor["x"] + cx,
                "y": anchor["y"] + cy,
                "size": max(
                    bounds["max_x"] - bounds["min_x"],
                    bounds["max_y"] - bounds["min_y"],
                ),
                "color": (120, 120, 120),
                "name": name,
            }

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def get_inherited_coords(self, entity):
        current = entity

        while current is not None:
            coords = current.get("coords")

            if isinstance(coords, dict):
                return coords

            current = current.get("parent_ref")

        return None

    def resolve_entity_center(self, entity):
        coords = self.get_inherited_coords(entity)
        return coords or {"x": 0, "y": 0}