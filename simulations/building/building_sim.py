from simulations.map.map_simulation import MapSimulation


class BuildingSimulation(MapSimulation):
    """
    Building-level map workspace.

    Buildings and rooms are still normal location entries. This simulation
    narrows the map polygon drafting workflow so authored polygons become
    child room locations under the active building.
    """

    ROOM_LAYER_KIND = "rooms"
    DEFAULT_BUILDING_WORLD_WIDTH = 48.0
    DEFAULT_BUILDING_WORLD_HEIGHT = 32.0
    STRUCTURE_LOCATION_CLASSES = {"building", "space_station", "station"}

    def __init__(self, simulation_context):
        super().__init__(simulation_context)
        # Building interiors are authored in metres (the default frame is
        # 48 x 32 world units), not planetary map degrees.
        self.world_units_to_meters = 1.0
        self.preferred_zoom = 8.0
        self.max_zoom = 160.0
        self.active_layer_kind = self.LOCATION_LAYER_KIND

    def _resolve_root_bounds(self):
        root = self.get_root_entity()
        if root is not None:
            bounds = root.get("bounds") or {}
            if bounds.get("type") in {"bbox", "polygon"}:
                return super()._resolve_root_bounds()

            if root.get("location_class") in {"space_station", "station"}:
                half_w = max(1.0, float(root.get("dimension_length_m", 100.0))) / 2.0
                half_h = max(1.0, float(root.get("dimension_width_m", 40.0))) / 2.0
                return {
                    "min_x": -half_w,
                    "max_x": half_w,
                    "min_y": -half_h,
                    "max_y": half_h,
                }

        half_w = self.DEFAULT_BUILDING_WORLD_WIDTH / 2.0
        half_h = self.DEFAULT_BUILDING_WORLD_HEIGHT / 2.0
        return {
            "min_x": -half_w,
            "max_x": half_w,
            "min_y": -half_h,
            "max_y": half_h,
        }

    def get_available_layer_kinds(self):
        return [self.LOCATION_LAYER_KIND]

    def can_create_map_square_draft(self):
        return False

    def can_create_spatial_feature_draft(self):
        root = self.get_root_entity()
        if root is not None and root.get("building_blueprint"):
            # Rooms of a placed building come from its blueprint version.
            return False
        return (
            root is not None
            and root.get("location_class") in self.STRUCTURE_LOCATION_CLASSES
        )

    # ------------------------------------------------------------------
    # Buildings placed from a blueprint
    # ------------------------------------------------------------------

    def _placed_blueprint_geometry(self):
        root = self.get_root_entity()
        if not isinstance(root, dict) or not root.get("building_blueprint"):
            return None
        revision = getattr(self.world_model, "repository_revision", 0)
        cached = getattr(self, "_placed_blueprint_cache", None)
        if cached is not None and cached[0] == revision:
            return cached[1]
        from .blueprint_placement import placed_blueprint_geometry

        geometry = placed_blueprint_geometry(self.world_model, root)
        self._placed_blueprint_cache = (revision, geometry)
        return geometry

    def blueprint_room_entity_id(self, room_key):
        """Id a blueprint room gets once it is materialised as an entity."""
        return f"{self.context.root_entity_id}__room_{self._sanitize_identifier_part(room_key)}"

    def _materialised_room_keys(self):
        loader = self._repository_loader()
        root_id = self.context.root_entity_id
        return {
            entity.get("blueprint_room_key")
            for entity in (getattr(loader, "entities", {}) or {}).values()
            if isinstance(entity, dict)
            and entity.get("parent_location") == root_id
            and entity.get("blueprint_room_key")
        }

    def _blueprint_room_layers(self):
        geometry = self._placed_blueprint_geometry()
        if geometry is None:
            return []
        from . import blueprint_model

        materialised = self._materialised_room_keys()
        layers = []
        for room in blueprint_model.placed_rooms(
            geometry["blueprint"], geometry["position"], geometry["rotation_deg"]
        ):
            if room["key"] in materialised:
                continue  # its own location layer is already drawn
            points = [tuple(point) for point in room["points"]]
            centroid_x, centroid_y = self._polygon_centroid(points)
            layers.append({
                "shape": "polygon",
                "x": centroid_x,
                "y": centroid_y,
                "points": points,
                "name": room["name"],
                "entity_id": self.blueprint_room_entity_id(room["key"]),
                "color": "#4c5866",
                "area_world": self._polygon_area(points),
                "draw_order": -1000,
                "is_blueprint_room": True,
                "blueprint_room_key": room["key"],
            })
        return layers

    def materialize_blueprint_room(self, room_key):
        """Create the ontology entity for one blueprint room, on demand.

        Rooms normally stay inside the blueprint (``<building>#room:<key>``);
        an entity is only created once something needs to refer to it.
        """
        entity_id = self.blueprint_room_entity_id(room_key)
        loader = self._repository_loader()
        if entity_id in (getattr(loader, "entities", {}) or {}):
            return entity_id
        geometry = self._placed_blueprint_geometry()
        if geometry is None:
            return None
        from . import blueprint_model

        room = next(
            (item for item in blueprint_model.placed_rooms(
                geometry["blueprint"], geometry["position"], geometry["rotation_deg"]
            ) if item["key"] == room_key),
            None,
        )
        if room is None:
            return None
        root = self.get_root_entity() or {}
        root_id = self.context.root_entity_id
        root_name = root.get("pretty_name") or root.get("name") or root_id
        points = [[round(x, 4), round(y, 4)] for x, y in room["points"]]
        record = {
            "id": entity_id,
            "type": "location",
            "location_class": "room",
            "location_role": "indoor_room",
            "room_class": "room",
            "name": f"{root_name} · {room['name']}",
            "pretty_name": f"{root_name} · {room['name']}",
            "parent_location": root_id,
            "parent_entity": root_id,
            "parents": [root_id],
            "blueprint_room_key": room_key,
            "geometry": {"type": "polygon", "coordinate_space": "map_world", "points": points},
            "bounds": {"type": "polygon", "coordinate_space": "map_world", "points": points},
            "entry_status": "draft",
            "wiki_entry": f"Room {room['name']} of {root_name}, defined by blueprint {root.get('building_blueprint')}.",
        }
        try:
            self._append_location_record(record)
            self._append_offspring_reference_to_location(root_id, entity_id)
        except OSError:
            return None
        self._notify_incremental_repository_change()
        self._invalidate_layer_cache()
        return entity_id

    def open_entity_card(self, entity_id, *, mode="edit", familiarity=None):
        prefix = f"{self.context.root_entity_id}__room_"
        loader = self._repository_loader()
        if (
            entity_id
            and str(entity_id).startswith(prefix)
            and entity_id not in (getattr(loader, "entities", {}) or {})
        ):
            layer = next(
                (item for item in self._blueprint_room_layers() if item["entity_id"] == entity_id),
                None,
            )
            if layer is None or not self.materialize_blueprint_room(layer["blueprint_room_key"]):
                return False
        return super().open_entity_card(entity_id, mode=mode, familiarity=familiarity)

    def get_spatial_feature_draft_button_label(self):
        return "New Room"

    def _build_default_floor_layer(self):
        root = self.get_root_entity()
        if root is None:
            return None

        points = self._root_bounds_as_polygon()
        centroid_x, centroid_y = self._polygon_centroid(points)
        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": root.get("name") or root.get("pretty_name") or self.context.root_entity_id,
            "entity_id": self.context.root_entity_id,
            "color": self._color_for_entity(root),
            "area_world": self._polygon_area(points),
            "draw_order": -2000,
            "is_virtual_building_floor": True,
        }

    def _build_layers(self, year):
        layers = super()._build_layers(year)
        layers = layers + self._blueprint_room_layers()
        root_id = self.context.root_entity_id
        if any(layer.get("entity_id") == root_id for layer in layers):
            return layers

        floor_layer = self._build_default_floor_layer()
        if floor_layer is not None:
            return [floor_layer] + layers
        return layers

    def _allocate_spatial_feature_draft_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)

        index = 1
        while True:
            room_id = f"loc_room_{root_id}_{index:03d}"
            if room_id not in existing_ids:
                return room_id, index
            index += 1

    def _build_draft_spatial_feature_record(self):
        room_id, index = self._allocate_spatial_feature_draft_id()
        root_name = self.get_root_name()
        name = f"Draft Room {index:03d}"
        notes = f"Draft room polygon created inside {root_name}."

        points = list(self.draft_spatial_feature_points)
        return {
            "id": room_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "room",
            "location_role": "indoor_room",
            "room_class": "room",
            "layer_kind": self.ROOM_LAYER_KIND,
            "wiki_entry": notes,
            "parent_location": self.context.root_entity_id,
            "parent_entity": self.context.root_entity_id,
            "parents": [self.context.root_entity_id],
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": points,
            },
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": points,
            },
            "start_year": self.year,
            "entry_status": "draft",
        }

    def finish_spatial_feature_draft(self):
        if not self.can_finish_spatial_feature_draft():
            return False

        room = self._build_draft_spatial_feature_record()

        try:
            self._append_location_record(room)
            self._append_offspring_reference_to_location(
                self.context.root_entity_id,
                room["id"],
            )
        except OSError:
            return False

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_location_id = room["id"]
        self.selected_entity_id = room["id"]
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()
        return True
