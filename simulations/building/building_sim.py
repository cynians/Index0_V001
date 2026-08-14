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
        return (
            root is not None
            and root.get("location_class") in self.STRUCTURE_LOCATION_CLASSES
        )

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
