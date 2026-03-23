class CelestialSystem:
    """
    Space-system container.

    Responsibilities:
    * store instantiated space objects
    * expose renderer-safe entries
    * update all objects
    * populate itself from the 'systems' dataset in WorldModel
    """

    def __init__(self):
        self._entries = []
        self.objects_by_id = {}

    def add(self, obj, name=None, layers=None, source_entity=None):
        """
        Register a space object in the system.
        """
        entry = {
            "object": obj,
            "name": name or obj.name,
            "layers": layers,
            "entity_id": getattr(obj, "entity_id", None),
            "source_entity": source_entity,
        }

        self._entries.append(entry)

        if source_entity is not None:
            source_entity_id = source_entity.get("id")
            if source_entity_id:
                self.objects_by_id[source_entity_id] = obj

    def get_entries(self):
        """
        Return all system entries with minimal, renderer-safe structure.
        """
        entries = []

        for entry in self._entries:
            obj = entry["object"]

            entries.append({
                "object": obj,
                "name": entry["name"],
                "layers": entry["layers"],
                "entity_id": getattr(obj, "entity_id", None)
            })

        return entries

    def _iter_active_entities(self, world_model, year):
        """
        Yield active entities from the world model.

        This keeps the loader resilient to small API differences.
        """
        if hasattr(world_model, "get_active_entities"):
            for entity in world_model.get_active_entities(year):
                yield entity
            return

        if hasattr(world_model, "entities_active") and hasattr(world_model, "get_entity"):
            for entity_id in world_model.entities_active(year):
                entity = world_model.get_entity(entity_id)
                if entity:
                    yield entity
            return

        raise AttributeError("WorldModel has no supported active-entity API.")

    def _get_active_system_entities(self, world_model, year, root_system_id):
        """
        Return active orbital-body entries for the selected star system.
        """
        active_entities = list(self._iter_active_entities(world_model, year))

        return [
            entity for entity in active_entities
            if entity.get("_dataset") == "systems"
            and entity.get("type") == "system"
            and entity.get("system_role") == "orbital_body"
            and entity.get("star_system") == root_system_id
        ]

    def _coerce_color(self, value, fallback=(180, 180, 180)):
        """
        Convert entry display_color data into an RGB tuple.
        """
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return fallback

        try:
            return (
                int(value[0]),
                int(value[1]),
                int(value[2]),
            )
        except (TypeError, ValueError):
            return fallback

    def _create_layers_for_entity(self, entity):
        """
        Create a minimal MapLayerStack from physical body size and display color.
        """
        from simulations.map.map_layers import MapLayerStack

        radius_m = float(entity.get("radius_m", 1.0) or 1.0)
        diameter_m = max(radius_m * 2.0, 1.0)
        color = self._coerce_color(entity.get("display_color"))

        stack = MapLayerStack(radius_m * 2.2)
        stack.add_layer({
            "name": "surface",
            "color": color,
            "x": 0.0,
            "y": 0.0,
            "size": diameter_m,
        })

        return stack

    def _create_root_object(self, entity):
        """
        Create a root body with no orbital parent.
        """
        from simulations.space.object import SpaceObject

        entity_id = entity.get("location_entity")

        return SpaceObject(
            name=entity.get("name", entity.get("id")),
            mass=float(entity.get("mass_kg", 0.0) or 0.0),
            position=(0.0, 0.0),
            entity_id=entity_id
        )

    def _create_orbiting_object(self, entity, parent_obj):
        """
        Create a body orbiting an already-instantiated parent body.
        """
        from simulations.space.object import SpaceObject
        from simulations.space.orbit import KeplerOrbit

        entity_id = entity.get("location_entity")

        orbit = KeplerOrbit(
            parent=parent_obj,
            a=float(entity.get("semi_major_axis_m", 0.0) or 0.0),
            e=float(entity.get("eccentricity", 0.0) or 0.0),
            M0=float(entity.get("mean_anomaly_deg_at_epoch", 0.0) or 0.0),
        )

        return SpaceObject(
            name=entity.get("name", entity.get("id")),
            mass=float(entity.get("mass_kg", 0.0) or 0.0),
            orbit=orbit,
            entity_id=entity_id
        )

    def populate_from_world_model(self, world_model, year, root_system_id):
        """
        Populate the celestial system from active entries in the 'systems' dataset.

        Expected entry shape:
        * type: system
        * system_role: orbital_body
        * star_system: <root system id>
        """
        self._entries = []
        self.objects_by_id = {}

        bodies = self._get_active_system_entities(world_model, year, root_system_id)

        if not bodies:
            return

        pending = {entity["id"]: entity for entity in bodies}
        stalled_last_round = False

        while pending:
            created_any = False

            for entity_id in list(pending.keys()):
                entity = pending[entity_id]
                parent_body_id = entity.get("parent_body")

                if not parent_body_id:
                    obj = self._create_root_object(entity)
                    layers = self._create_layers_for_entity(entity)
                    self.add(
                        obj,
                        name=entity.get("name"),
                        layers=layers,
                        source_entity=entity
                    )
                    del pending[entity_id]
                    created_any = True
                    continue

                parent_obj = self.objects_by_id.get(parent_body_id)
                if parent_obj is None:
                    continue

                obj = self._create_orbiting_object(entity, parent_obj)
                layers = self._create_layers_for_entity(entity)
                self.add(
                    obj,
                    name=entity.get("name"),
                    layers=layers,
                    source_entity=entity
                )
                del pending[entity_id]
                created_any = True

            if created_any:
                stalled_last_round = False
                continue

            if stalled_last_round:
                unresolved_ids = ", ".join(sorted(pending.keys()))
                raise ValueError(
                    f"Could not resolve orbital parents in systems dataset: {unresolved_ids}"
                )

            stalled_last_round = True

    def update(self, dt):
        """
        Update all space objects.
        """
        objects = [entry["object"] for entry in self._entries]

        for obj in objects:
            obj.update(dt, attractors=objects)