import copy


class VehicleDesignController:
    """
    Stores vehicle design-state and design-specific interaction logic.

    Current slice:
    * stores physical vehicle dimensions in SI units
    * stores a simple component catalog
    * stores placed design components in local vehicle-space meters
    * exposes design render payloads
    * supports true drag-and-drop placement and repositioning inside the hull
    * can bootstrap its state from repository entities
    * resolves hierarchical functional requirements by vehicle class
    * evaluates which requirements are satisfied by currently placed components
    * prefers repository-defined vehicle/component metadata before fallback maps
    """

    CATALOG_PANEL_X = 18
    CATALOG_PANEL_Y = 18
    CATALOG_PANEL_W = 320
    CATALOG_ENTRY_H = 28
    CATALOG_HEADER_H = 28
    CATALOG_PADDING = 10

    ORTHOGRAPHIC_VIEWS = {
        "right": {"label": "RIGHT SIDE", "axes": ("x", "z"), "opposite": "left", "flip_x": False},
        "left": {"label": "LEFT SIDE", "axes": ("x", "z"), "opposite": "right", "flip_x": True},
        "front": {"label": "FRONT", "axes": ("y", "z"), "opposite": "rear", "flip_x": True},
        "rear": {"label": "REAR", "axes": ("y", "z"), "opposite": "front", "flip_x": False},
        "top": {"label": "TOP", "axes": ("x", "y"), "opposite": "bottom", "flip_x": False},
        "bottom": {"label": "BOTTOM", "axes": ("x", "y"), "opposite": "top", "flip_x": False},
    }
    # 50% more linear detail than the original six-cell prototype. Persisted
    # silhouettes are resampled on load, preserving their overall form.
    HULL_PIXELS_PER_METER = 9
    # Liveries are authored on a separate micro-pixel raster. Four times the
    # linear hull resolution yields sixteen times the paint detail while the
    # hull remains a light-weight geometric mask.
    LIVERY_PIXELS_PER_METER = 36
    MAX_PAINT_AXIS_PIXELS = 1024

    VEHICLE_CLASS_PARENTS = {
        "vehicle": [],
        "ground_vehicle": ["vehicle"],
        "aircraft": ["vehicle"],
        "naval_vessel": ["vehicle"],
        "orbital_spacecraft": ["vehicle"],
        "planetary_spacecraft": ["vehicle"],
        "system_spacecraft": ["vehicle"],
        "interstellar_spacecraft": ["vehicle"],
    }

    VEHICLE_CLASS_REQUIREMENTS = {
        "vehicle": [
            "structure",
            "control",
        ],
        "ground_vehicle": [
            "locomotion_ground",
            "wheels",
            "propulsion_road",
        ],
        "aircraft": [
            "propulsion_air",
            "flight_surfaces",
            "landing_system",
        ],
        "naval_vessel": [
            "hull",
            "propulsion_marine",
        ],
        "orbital_spacecraft": [
            "spaceframe",
            "propulsion_space",
        ],
        "planetary_spacecraft": [
            "spaceframe",
            "propulsion_space",
            "landing_system",
        ],
        "system_spacecraft": [
            "spaceframe",
            "propulsion_space",
        ],
        "interstellar_spacecraft": [
            "spaceframe",
            "propulsion_space",
        ],
    }

    COMPONENT_CATEGORY_HINTS = {
        "engine_component": {"propulsion_road", "powertrain"},
        "motor_component": {"propulsion_road", "powertrain"},
        "wheel_component": {"locomotion_ground", "wheels"},
        "performance_wheel_component": {"locomotion_ground", "wheels", "performance_wheels"},
        "track_component": {"locomotion_ground", "tracks"},
        "control_component": {"control"},
        "cockpit_component": {"control"},
        "body_component": {"structure", "body"},
        "vehicle_body_component": {"structure", "body"},
        "frame_component": {"structure", "spaceframe"},
        "hull_component": {"structure", "hull"},
        "roof_system_component": {"body"},
        "landing_gear_component": {"landing_system"},
        "cargo_component": {"cargo_handling"},
        "comm_component": {"communications_system"},
        "weapon_component": {"weapon_system"},
        "carriage_component": {"carriage"},
        "aero_surface_component": {"flight_surfaces"},
        "thruster_component": {"propulsion_space"},
        "reactor_component": {"propulsion_space", "powertrain"},
        "marine_drive_component": {"propulsion_marine"},
        "jet_engine_component": {"propulsion_air", "powertrain"},
        "drive_system_component": {"propulsion_road", "powertrain"},
        "fuel_tank_component": {"fuel_storage"},
        "battery_component": {"electrical_storage"},
    }

    # Small controlled vocabulary of resource types a component port can carry.
    RESOURCE_TYPES = {
        "mechanical_power", "electrical_power", "fuel", "coolant",
        "thrust", "lift", "control_signal", "cargo_mass", "crew_capacity",
    }

    # Default input/output ports by component_type, used when a catalog entry
    # (real ontology entity or embedded fixture literal) does not declare its
    # own `inputs`/`outputs`. Purely structural component types (body, hull,
    # frame, landing gear, ...) carry no ports -- they aren't part of a
    # resource-flow graph.
    COMPONENT_TYPE_DEFAULT_PORTS = {
        "engine_component": {
            "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
            "outputs": [{"resource_type": "mechanical_power", "label": "Shaft Power"}],
        },
        "motor_component": {
            "inputs": [{"resource_type": "electrical_power", "label": "Electric Supply"}],
            "outputs": [{"resource_type": "mechanical_power", "label": "Shaft Power"}],
        },
        "drive_system_component": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "wheel_component": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "performance_wheel_component": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "track_component": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "marine_drive_component": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "jet_engine_component": {
            "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "thruster_component": {
            "inputs": [{"resource_type": "fuel", "label": "Propellant"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "reactor_component": {
            "outputs": [
                {"resource_type": "electrical_power", "label": "Electric Power"},
                {"resource_type": "mechanical_power", "label": "Shaft Power"},
            ],
        },
        "aero_surface_component": {
            "inputs": [{"resource_type": "control_signal", "label": "Control Input"}],
            "outputs": [{"resource_type": "lift", "label": "Lift"}],
        },
        "control_component": {
            "outputs": [{"resource_type": "control_signal", "label": "Control Signal"}],
        },
        "cockpit_component": {
            "outputs": [{"resource_type": "control_signal", "label": "Control Signal"}],
        },
        "fuel_tank_component": {
            "outputs": [{"resource_type": "fuel", "label": "Fuel"}],
        },
        "battery_component": {
            "outputs": [{"resource_type": "electrical_power", "label": "Electric Power"}],
        },
        "cargo_component": {
            "outputs": [{"resource_type": "cargo_mass", "label": "Cargo Capacity"}],
        },
    }

    # Real ontology-authored component entities carry a generic `type`
    # ("component"/"assembly") rather than the fine-grained component_type
    # strings above -- fall back to their declared `satisfies_categories`
    # when COMPONENT_TYPE_DEFAULT_PORTS has no entry for the entity's type.
    CATEGORY_DEFAULT_PORTS = {
        "propulsion_road": {
            "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
            "outputs": [{"resource_type": "mechanical_power", "label": "Shaft Power"}],
        },
        "propulsion_air": {
            "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "propulsion_marine": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "propulsion_space": {
            "inputs": [{"resource_type": "fuel", "label": "Propellant"}],
            "outputs": [{"resource_type": "thrust", "label": "Thrust"}],
        },
        "wheels": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "tracks": {
            "inputs": [{"resource_type": "mechanical_power", "label": "Drive Power"}],
            "outputs": [{"resource_type": "thrust", "label": "Traction"}],
        },
        "flight_surfaces": {
            "inputs": [{"resource_type": "control_signal", "label": "Control Input"}],
            "outputs": [{"resource_type": "lift", "label": "Lift"}],
        },
        "control": {
            "outputs": [{"resource_type": "control_signal", "label": "Control Signal"}],
        },
        "fuel_storage": {
            "outputs": [{"resource_type": "fuel", "label": "Fuel"}],
        },
        "electrical_storage": {
            "outputs": [{"resource_type": "electrical_power", "label": "Electric Power"}],
        },
        "cargo_handling": {
            "outputs": [{"resource_type": "cargo_mass", "label": "Cargo Capacity"}],
        },
    }

    REQUIREMENT_TO_OPERATIONAL_GROUP = {
        "structure": "Structure",
        "body": "Structure",
        "spaceframe": "Structure",
        "hull": "Structure",
        "control": "Crew & Control",
        "locomotion_ground": "Mobility",
        "wheels": "Mobility",
        "performance_wheels": "Mobility",
        "tracks": "Mobility",
        "carriage": "Mobility",
        "propulsion_road": "Powertrain",
        "propulsion_space": "Powertrain",
        "propulsion_marine": "Powertrain",
        "propulsion_air": "Powertrain",
        "powertrain": "Powertrain",
        "landing_system": "Mobility",
        "cargo_handling": "Cargo",
        "communications_system": "Sensors & Comms",
        "weapon_system": "Weapons",
        "flight_surfaces": "Control Surfaces",
    }

    REQUIREMENT_TO_SUBSYSTEM = {
        "structure": "core structure",
        "body": "body",
        "spaceframe": "spaceframe",
        "hull": "hull",
        "fuselage": "fuselage",
        "wings": "wings",
        "tail": "tail",
        "control": "control linkages",
        "cockpit": "cockpit",
        "avionics": "avionics",
        "locomotion_ground": "ground locomotion",
        "wheels": "wheels",
        "performance_wheels": "performance wheels",
        "tracks": "tracks",
        "carriage": "carriage",
        "landing_system": "landing system",
        "propulsion_road": "road propulsion",
        "propulsion_space": "space propulsion",
        "propulsion_marine": "marine propulsion",
        "propulsion_air": "air propulsion",
        "powertrain": "powertrain core",
        "cargo_handling": "cargo handling",
        "communications_system": "communications",
        "weapon_system": "weapon system",
        "flight_surfaces": "flight surfaces",
    }

    def __init__(self, world_model=None, vehicle_entity=None):
        self.world_model = world_model
        self.vehicle_entity = vehicle_entity

        self.vehicle_dimensions_m = self._load_vehicle_dimensions_m(vehicle_entity)
        self.specification_metadata = self._load_specification_metadata(vehicle_entity)
        self.vehicle_specifications = self._load_specification_rows(
            vehicle_entity.get("vehicle_specifications", []) if isinstance(vehicle_entity, dict) else [],
            "characteristic",
        )
        self.design_requirements = self._load_specification_rows(
            vehicle_entity.get("design_requirements", []) if isinstance(vehicle_entity, dict) else [],
            "requirement",
        )
        self.structural_features = copy.deepcopy(
            vehicle_entity.get("structural_features", []) if isinstance(vehicle_entity, dict) else []
        )
        self.hull_silhouettes = self._load_hull_silhouettes(vehicle_entity)
        self.detail_layers = self._load_color_layers(
            vehicle_entity.get("vehicle_detail_layers", {}) if isinstance(vehicle_entity, dict) else {}
        )
        self.liveries = self._load_liveries(vehicle_entity)
        self.active_livery_id = self.liveries[0]["id"]
        self.paint_revision = 0
        self.paint_dirty_regions = {}
        self.component_catalog = self._load_component_catalog(world_model, vehicle_entity)
        self.placed_components = self._load_placed_components(world_model, vehicle_entity)

        has_authored_component_layout = (
            isinstance(vehicle_entity, dict)
            and "installed_components" in vehicle_entity
        )
        if not self.placed_components and self.component_catalog and not has_authored_component_layout:
            first_entry = self.component_catalog[0]
            self.placed_components = [
                {
                    "instance_id": "placed_component_001",
                    "catalog_id": first_entry["id"],
                    "label": first_entry["label"],
                    "component_type": first_entry["component_type"],
                    "satisfies_categories": list(first_entry.get("satisfies_categories", [])),
                    "operational_groups": list(first_entry.get("operational_groups", [])),
                    "subsystem_labels": list(first_entry.get("subsystem_labels", [])),
                    "slot_category": (first_entry.get("satisfies_categories") or [None])[0],
                    "local_rect_m": {
                        "x": 0.8,
                        "y": 1.4,
                        "width": first_entry["dimensions_m"]["x"],
                        "height": first_entry["dimensions_m"]["y"],
                    },
                }
            ]

        self.manual_routes = self._load_manual_routes(vehicle_entity)
        self.next_component_index = self._infer_next_component_index()

        self.hover_component_id = None
        self.selected_component_id = None
        self.active_catalog_component_id = None
        self.hover_catalog_component_id = None

        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

        self.component_axis_drag = None

    @staticmethod
    def _load_specification_metadata(vehicle_entity):
        entity = vehicle_entity if isinstance(vehicle_entity, dict) else {}
        return {
            "name": str(entity.get("name", "")),
            "vehicle_class": str(entity.get("vehicle_class", "")),
            "manufacturer_name": str(entity.get("manufacturer_name", entity.get("manufacturer", ""))),
            "description": str(entity.get("description", "")),
        }

    @staticmethod
    def _load_specification_rows(raw_rows, row_kind):
        rows = []
        if not isinstance(raw_rows, list):
            return rows
        defaults = (
            {"label": "", "value": "", "unit": "", "category": ""}
            if row_kind == "characteristic"
            else {"label": "", "target": "", "unit": "", "priority": "", "notes": ""}
        )
        used_ids = set()
        for index, raw in enumerate(raw_rows, 1):
            if not isinstance(raw, dict):
                continue
            row = {key: str(raw.get(key, "")) for key in defaults}
            candidate = str(raw.get("id") or f"{row_kind}_{index:03d}")
            while candidate in used_ids:
                candidate = f"{row_kind}_{index:03d}_{len(used_ids) + 1}"
            row["id"] = candidate
            used_ids.add(candidate)
            rows.append(row)
        return rows

    def get_specification_payload(self):
        return {
            "metadata": dict(self.specification_metadata),
            "characteristics": copy.deepcopy(self.vehicle_specifications),
            "requirements": copy.deepcopy(self.design_requirements),
        }

    def _next_specification_row_id(self, row_kind):
        rows = self.vehicle_specifications if row_kind == "characteristic" else self.design_requirements
        existing = {row.get("id") for row in rows}
        index = 1
        while f"{row_kind}_{index:03d}" in existing:
            index += 1
        return f"{row_kind}_{index:03d}"

    def add_specification_row(self, row_kind):
        if row_kind == "characteristic":
            row = {"id": self._next_specification_row_id(row_kind), "label": "", "value": "", "unit": "", "category": ""}
            self.vehicle_specifications.append(row)
        elif row_kind == "requirement":
            row = {"id": self._next_specification_row_id(row_kind), "label": "", "target": "", "unit": "", "priority": "", "notes": ""}
            self.design_requirements.append(row)
        else:
            return None
        return row["id"]

    def remove_specification_row(self, row_kind, row_id):
        if row_kind == "characteristic":
            rows = self.vehicle_specifications
        elif row_kind == "requirement":
            rows = self.design_requirements
        else:
            return False
        for index, row in enumerate(rows):
            if row.get("id") == row_id:
                del rows[index]
                return True
        return False

    def update_specification_value(self, row_kind, row_id, field_name, value):
        value = str(value)
        if row_kind == "metadata":
            if field_name not in self.specification_metadata:
                return False
            self.specification_metadata[field_name] = value
            return True
        if row_kind == "characteristic":
            rows = self.vehicle_specifications
            allowed = {"label", "value", "unit", "category"}
        elif row_kind == "requirement":
            rows = self.design_requirements
            allowed = {"label", "target", "unit", "priority", "notes"}
        else:
            return False
        if field_name not in allowed:
            return False
        for row in rows:
            if row.get("id") == row_id:
                row[field_name] = value
                return True
        return False

    def _view_grid_size(self, view_id):
        view = self.ORTHOGRAPHIC_VIEWS[view_id]
        horizontal_axis, vertical_axis = view["axes"]
        return (
            max(4, int(round(self.vehicle_dimensions_m[horizontal_axis] * self.HULL_PIXELS_PER_METER))),
            max(4, int(round(self.vehicle_dimensions_m[vertical_axis] * self.HULL_PIXELS_PER_METER))),
        )

    def _empty_hull_grid(self, view_id):
        width, height = self._view_grid_size(view_id)
        return [[False for _ in range(width)] for _ in range(height)]

    def _empty_color_grid(self, view_id):
        width, height = self._view_grid_size(view_id)
        return [[None for _ in range(width)] for _ in range(height)]

    def _paint_grid_size(self, layer_kind, view_id):
        if layer_kind != "liveries":
            return self._view_grid_size(view_id)
        horizontal_axis, vertical_axis = self.ORTHOGRAPHIC_VIEWS[view_id]["axes"]
        return (
            max(4, min(self.MAX_PAINT_AXIS_PIXELS, int(round(self.vehicle_dimensions_m[horizontal_axis] * self.LIVERY_PIXELS_PER_METER)))),
            max(4, min(self.MAX_PAINT_AXIS_PIXELS, int(round(self.vehicle_dimensions_m[vertical_axis] * self.LIVERY_PIXELS_PER_METER)))),
        )

    @staticmethod
    def _resample_value_grid(source, target_width, target_height, default=None):
        source_height = len(source) if isinstance(source, list) else 0
        source_width = max((len(row) for row in source if isinstance(row, list)), default=0) if source_height else 0
        if source_width <= 0 or source_height <= 0:
            return [[default for _ in range(target_width)] for _ in range(target_height)]
        result = []
        for target_y in range(target_height):
            source_y = min(source_height - 1, int(target_y * source_height / target_height))
            source_row = source[source_y] if isinstance(source[source_y], list) else []
            row = []
            for target_x in range(target_width):
                source_x = min(source_width - 1, int(target_x * source_width / target_width))
                row.append(copy.deepcopy(source_row[source_x]) if source_x < len(source_row) else default)
            result.append(row)
        return result

    def _load_color_layers(self, raw_layers, layer_kind="details"):
        layers = {}
        for view_id in self.ORTHOGRAPHIC_VIEWS:
            width, height = self._paint_grid_size(layer_kind, view_id)
            source = raw_layers.get(view_id, []) if isinstance(raw_layers, dict) else []
            layers[view_id] = self._resample_value_grid(source, width, height)
        return layers

    def _load_liveries(self, vehicle_entity):
        raw_liveries = vehicle_entity.get("vehicle_liveries", []) if isinstance(vehicle_entity, dict) else []
        liveries = []
        if isinstance(raw_liveries, list):
            for index, raw in enumerate(raw_liveries):
                if not isinstance(raw, dict):
                    continue
                livery_id = str(raw.get("id") or f"livery_{index + 1:03d}")
                liveries.append({
                    "id": livery_id,
                    "name": str(raw.get("name") or f"Livery {index + 1}"),
                    "layers": self._load_color_layers(raw.get("layers", {}), "liveries"),
                })
        if not liveries:
            liveries.append({
                "id": "livery_001",
                "name": "Base Livery",
                "layers": self._load_color_layers({}, "liveries"),
            })
        return liveries

    def _load_hull_silhouettes(self, vehicle_entity):
        raw = vehicle_entity.get("hull_silhouettes", {}) if isinstance(vehicle_entity, dict) else {}
        result = {}
        for view_id in self.ORTHOGRAPHIC_VIEWS:
            width, height = self._view_grid_size(view_id)
            source = raw.get(view_id) if isinstance(raw, dict) else None
            if not isinstance(source, list) or not source:
                result[view_id] = [[False for _ in range(width)] for _ in range(height)]
                continue
            result[view_id] = self._resample_boolean_grid(source, width, height)
        return result

    @staticmethod
    def _resample_boolean_grid(source, target_width, target_height):
        source_height = len(source)
        source_width = max((len(row) for row in source if isinstance(row, list)), default=0)
        if source_width <= 0 or source_height <= 0:
            return [[False for _ in range(target_width)] for _ in range(target_height)]
        result = []
        for target_y in range(target_height):
            source_y = min(source_height - 1, int(target_y * source_height / target_height))
            source_row = source[source_y] if isinstance(source[source_y], list) else []
            row = []
            for target_x in range(target_width):
                source_x = min(source_width - 1, int(target_x * source_width / target_width))
                row.append(bool(source_row[source_x]) if source_x < len(source_row) else False)
            result.append(row)
        return result

    def set_vehicle_dimension_m(self, axis, value):
        if axis not in {"x", "y", "z"}:
            return False
        value = max(0.5, min(200.0, round(float(value), 2)))
        if self.vehicle_dimensions_m.get(axis) == value:
            return False
        self.vehicle_dimensions_m[axis] = value
        for view_id in self.ORTHOGRAPHIC_VIEWS:
            width, height = self._view_grid_size(view_id)
            self.hull_silhouettes[view_id] = self._resample_boolean_grid(
                self.hull_silhouettes.get(view_id, []), width, height,
            )
            self.detail_layers[view_id] = self._resample_value_grid(
                self.detail_layers.get(view_id, []), width, height,
            )
            for livery in self.liveries:
                livery_width, livery_height = self._paint_grid_size("liveries", view_id)
                livery["layers"][view_id] = self._resample_value_grid(
                    livery.get("layers", {}).get(view_id, []), livery_width, livery_height,
                )
        self.paint_revision += 1
        for component in self.placed_components:
            position = self._ensure_component_position(component)
            position[axis] = self._clamp_component_axis_position(component, axis, position.get(axis, value / 2.0))
        return True

    def _component_dimensions(self, component):
        catalog = self.get_component_catalog_entry(component.get("catalog_id")) or {}
        dimensions = dict(catalog.get("dimensions_m", {}))
        rect = component.get("local_rect_m", {})
        dimensions.setdefault("x", rect.get("width", 1.0))
        dimensions.setdefault("y", rect.get("height", 1.0))
        dimensions.setdefault("z", 1.0)
        return {axis: max(0.0, float(dimensions.get(axis, 0.0))) for axis in ("x", "y", "z")}

    def _clamp_component_axis_position(self, component, axis, value):
        hull_extent = float(self.vehicle_dimensions_m[axis])
        half_extent = min(hull_extent / 2.0, self._component_dimensions(component)[axis] / 2.0)
        return max(half_extent, min(hull_extent - half_extent, float(value)))

    def get_hull_silhouettes(self):
        return {view_id: [list(row) for row in grid] for view_id, grid in self.hull_silhouettes.items()}

    def paint_hull_cell(self, view_id, column, row, filled=True, brush_radius=0):
        grid = self.hull_silhouettes.get(view_id)
        if grid is None or not grid:
            return False
        changed = False
        radius = max(0, int(brush_radius))
        for grid_y in range(max(0, row - radius), min(len(grid), row + radius + 1)):
            for grid_x in range(max(0, column - radius), min(len(grid[grid_y]), column + radius + 1)):
                if (grid_x - column) ** 2 + (grid_y - row) ** 2 > radius ** 2:
                    continue
                if grid[grid_y][grid_x] != bool(filled):
                    grid[grid_y][grid_x] = bool(filled)
                    changed = True
        return changed

    def clear_hull_silhouettes(self):
        self.hull_silhouettes = {
            view_id: self._empty_hull_grid(view_id)
            for view_id in self.ORTHOGRAPHIC_VIEWS
        }

    def get_effective_hull_grid(self, view_id):
        grid = self.hull_silhouettes.get(view_id, [])
        if grid and any(any(row) for row in grid):
            return grid
        opposite_id = self.ORTHOGRAPHIC_VIEWS[view_id]["opposite"]
        opposite = self.hull_silhouettes.get(opposite_id, [])
        if not opposite:
            return grid
        return [list(reversed(row)) for row in opposite]

    def get_paint_layer(self, layer_kind, view_id):
        if layer_kind == "details":
            return self.detail_layers.get(view_id, [])
        if layer_kind == "liveries":
            for livery in self.liveries:
                if livery.get("id") == self.active_livery_id:
                    return livery.get("layers", {}).get(view_id, [])
        return []

    def get_paint_mask(self, layer_kind, view_id):
        hull_mask = self.get_effective_hull_grid(view_id)
        target_width, target_height = self._paint_grid_size(layer_kind, view_id)
        if not hull_mask:
            return [[False for _ in range(target_width)] for _ in range(target_height)]
        if len(hull_mask) == target_height and len(hull_mask[0]) == target_width:
            return hull_mask
        return self._resample_boolean_grid(hull_mask, target_width, target_height)

    def paint_color_cell(self, layer_kind, view_id, column, row, color, brush_radius=0):
        layer = self.get_paint_layer(layer_kind, view_id)
        mask = self.get_paint_mask(layer_kind, view_id)
        if not layer or not mask:
            return False
        changed = False
        radius = max(0, int(brush_radius))
        for grid_y in range(max(0, row - radius), min(len(layer), row + radius + 1)):
            for grid_x in range(max(0, column - radius), min(len(layer[grid_y]), column + radius + 1)):
                if (grid_x - column) ** 2 + (grid_y - row) ** 2 > radius ** 2:
                    continue
                if grid_y >= len(mask) or grid_x >= len(mask[grid_y]) or not mask[grid_y][grid_x]:
                    continue
                value = None if color is None else str(color)
                if layer[grid_y][grid_x] != value:
                    layer[grid_y][grid_x] = value
                    changed = True
        if changed:
            self.paint_revision += 1
            region = (
                max(0, column - radius), max(0, row - radius),
                min(len(layer[0]) - 1, column + radius), min(len(layer) - 1, row + radius),
            )
            self._mark_paint_dirty(layer_kind, view_id, region)
            opposite_id = self.ORTHOGRAPHIC_VIEWS[view_id]["opposite"]
            opposite_layer = self.get_paint_layer(layer_kind, opposite_id)
            if opposite_layer and opposite_layer[0]:
                opposite_width = len(opposite_layer[0])
                mirrored = (
                    max(0, opposite_width - 1 - region[2]), region[1],
                    min(opposite_width - 1, opposite_width - 1 - region[0]), region[3],
                )
                self._mark_paint_dirty(layer_kind, opposite_id, mirrored)
        return changed

    def _mark_paint_dirty(self, layer_kind, view_id, region):
        key = (layer_kind, view_id, self.active_livery_id if layer_kind == "liveries" else None)
        existing = self.paint_dirty_regions.get(key)
        if existing is None:
            self.paint_dirty_regions[key] = tuple(region)
        else:
            self.paint_dirty_regions[key] = (
                min(existing[0], region[0]), min(existing[1], region[1]),
                max(existing[2], region[2]), max(existing[3], region[3]),
            )

    def consume_paint_dirty_region(self, layer_kind, view_id):
        key = (layer_kind, view_id, self.active_livery_id if layer_kind == "liveries" else None)
        return self.paint_dirty_regions.pop(key, None)

    def get_livery_summaries(self):
        return [{"id": item["id"], "name": item["name"]} for item in self.liveries]

    def select_livery(self, livery_id):
        if not any(item.get("id") == livery_id for item in self.liveries):
            return False
        self.active_livery_id = livery_id
        return True

    def copy_active_livery(self):
        for item in self.liveries:
            if item.get("id") == self.active_livery_id:
                return copy.deepcopy(item)
        return None

    def paste_livery(self, copied_livery):
        if not isinstance(copied_livery, dict):
            return None
        existing_ids = {item.get("id") for item in self.liveries}
        index = 1
        while f"livery_{index:03d}" in existing_ids:
            index += 1
        pasted = copy.deepcopy(copied_livery)
        pasted["id"] = f"livery_{index:03d}"
        pasted["name"] = f"{copied_livery.get('name', 'Livery')} Copy"
        pasted["layers"] = self._load_color_layers(pasted.get("layers", {}), "liveries")
        self.liveries.append(pasted)
        self.active_livery_id = pasted["id"]
        self.paint_revision += 1
        return pasted["id"]

    def _ensure_component_position(self, component):
        position = component.get("position_m")
        if not isinstance(position, dict):
            rect = component.get("local_rect_m", {})
            dims = self.get_vehicle_dimensions_m()
            position = {
                "x": float(rect.get("x", 0.0)) + float(rect.get("width", 1.0)) / 2.0,
                "y": float(rect.get("y", 0.0)) + float(rect.get("height", 1.0)) / 2.0,
                "z": dims["z"] / 2.0,
            }
            component["position_m"] = position
        return position

    def get_component_position_m(self, component):
        return dict(self._ensure_component_position(component))

    def get_orthographic_component_blocks(self, view_id):
        view = self.ORTHOGRAPHIC_VIEWS[view_id]
        horizontal_axis, vertical_axis = view["axes"]
        blocks = []
        for component in self.placed_components:
            position = self._ensure_component_position(component)
            catalog = self.get_component_catalog_entry(component.get("catalog_id")) or {}
            component_dims = catalog.get("dimensions_m", {})
            if not component_dims:
                rect = component.get("local_rect_m", {})
                component_dims = {"x": rect.get("width", 1.0), "y": rect.get("height", 1.0), "z": 1.0}
            blocks.append({
                "id": component.get("instance_id"),
                "label": component.get("label", "component"),
                "catalog_id": component.get("catalog_id"),
                "position_m": dict(position),
                "undefined_axis": component.get("undefined_axis"),
                "u": float(position.get(horizontal_axis, 0.0)),
                "v": float(position.get(vertical_axis, 0.0)),
                "width": float(component_dims.get(horizontal_axis, 1.0)),
                "height": float(component_dims.get(vertical_axis, 1.0)),
            })
        return blocks

    def place_component_in_orthographic_view(self, catalog_id, view_id, u, v):
        catalog = self.get_component_catalog_entry(catalog_id)
        if catalog is None or view_id not in self.ORTHOGRAPHIC_VIEWS:
            return None
        axes = self.ORTHOGRAPHIC_VIEWS[view_id]["axes"]
        missing_axis = next(axis for axis in ("x", "y", "z") if axis not in axes)
        position = {axis: self.vehicle_dimensions_m[axis] / 2.0 for axis in ("x", "y", "z")}
        position[axes[0]] = max(0.0, min(self.vehicle_dimensions_m[axes[0]], float(u)))
        position[axes[1]] = max(0.0, min(self.vehicle_dimensions_m[axes[1]], float(v)))
        dims = catalog.get("dimensions_m", {})
        local_rect = {
            "x": position["x"] - float(dims.get("x", 1.0)) / 2.0,
            "y": position["y"] - float(dims.get("y", 1.0)) / 2.0,
            "width": float(dims.get("x", 1.0)),
            "height": float(dims.get("y", 1.0)),
        }
        component = self._make_component_instance(catalog, local_rect)
        component["position_m"] = {
            axis: self._clamp_component_axis_position(component, axis, position[axis])
            for axis in ("x", "y", "z")
        }
        component["undefined_axis"] = missing_axis
        self.placed_components.append(component)
        self.selected_component_id = component["instance_id"]
        return component["instance_id"]

    def move_component_axis(self, component_id, axis, value):
        component = self._get_component_by_instance_id(component_id)
        if component is None or axis not in {"x", "y", "z"}:
            return False
        position = self._ensure_component_position(component)
        position[axis] = self._clamp_component_axis_position(component, axis, value)
        rect = component.get("local_rect_m", {})
        if axis == "x":
            rect["x"] = position["x"] - float(rect.get("width", 1.0)) / 2.0
        elif axis == "y":
            rect["y"] = position["y"] - float(rect.get("height", 1.0)) / 2.0
        return True

    def _load_vehicle_dimensions_m(self, vehicle_entity):
        if vehicle_entity:
            return {
                "x": float(vehicle_entity.get("dimension_length_m", 10.0)),
                "y": float(vehicle_entity.get("dimension_width_m", 4.0)),
                "z": float(vehicle_entity.get("dimension_height_m", 3.0)),
            }

        return {
            "x": 10.0,
            "y": 4.0,
            "z": 3.0,
        }

    def _infer_satisfies_categories_from_entity(self, entity):
        categories = set()

        for field_name in ("functional_roles", "tags", "satisfies_categories"):
            values = entity.get(field_name, [])
            if isinstance(values, list):
                for value in values:
                    text = str(value).strip().lower()
                    if text:
                        categories.add(text)

        label_text = " ".join(
            str(entity.get(key, ""))
            for key in ("pretty_name", "name")
        ).lower()

        if "wheel" in label_text:
            categories.update({"locomotion_ground", "wheels"})
        if "track" in label_text:
            categories.update({"locomotion_ground", "tracks"})
        if "engine" in label_text or "motor" in label_text:
            categories.update({"powertrain"})
        if "performance" in label_text and "wheel" in label_text:
            categories.update({"performance_wheels"})
        if "control" in label_text or "cockpit" in label_text:
            categories.update({"control"})
        if "body" in label_text or "chassis" in label_text:
            categories.update({"structure", "body"})
        if "hull" in label_text:
            categories.update({"hull", "structure"})
        if "landing" in label_text and "gear" in label_text:
            categories.update({"landing_system"})
        if "cargo" in label_text:
            categories.update({"cargo_handling"})
        if "comm" in label_text or "antenna" in label_text or "relay" in label_text:
            categories.update({"communications_system"})
        if "weapon" in label_text or "gun" in label_text or "cannon" in label_text:
            categories.update({"weapon_system"})
        if "thruster" in label_text or "rocket" in label_text:
            categories.update({"propulsion_space"})
        if "marine" in label_text or "propeller" in label_text:
            categories.update({"propulsion_marine"})
        if "jet" in label_text or "turbofan" in label_text:
            categories.update({"propulsion_air", "powertrain"})
        if "roof" in label_text:
            categories.update({"body"})

        return sorted(categories)

    @staticmethod
    def _normalize_ports(raw_ports):
        ports = []
        for index, raw in enumerate(raw_ports or []):
            if not isinstance(raw, dict):
                continue
            resource_type = str(raw.get("resource_type") or "").strip().lower()
            if not resource_type:
                continue
            ports.append({
                "port_id": str(raw.get("port_id") or f"port_{index}_{resource_type}"),
                "resource_type": resource_type,
                "label": str(raw.get("label") or resource_type.replace("_", " ").title()),
            })
        return ports

    def _resolve_ports(self, raw_inputs, raw_outputs, component_type, categories=None):
        inputs = self._normalize_ports(raw_inputs)
        outputs = self._normalize_ports(raw_outputs)
        if inputs or outputs:
            return inputs, outputs
        defaults = self.COMPONENT_TYPE_DEFAULT_PORTS.get(component_type)
        if not defaults:
            for category in categories or []:
                defaults = self.CATEGORY_DEFAULT_PORTS.get(str(category).strip().lower())
                if defaults:
                    break
        defaults = defaults or {}
        return self._normalize_ports(defaults.get("inputs")), self._normalize_ports(defaults.get("outputs"))

    def _ensure_catalog_entry_ports(self, entry):
        if not isinstance(entry, dict):
            return entry
        inputs, outputs = self._resolve_ports(
            entry.get("inputs"), entry.get("outputs"), entry.get("component_type", "component"),
            categories=entry.get("satisfies_categories"),
        )
        entry = dict(entry)
        entry["inputs"] = inputs
        entry["outputs"] = outputs
        return entry

    def _build_catalog_entry_from_component_entity(self, entity):
        raw_operational_groups = entity.get("operational_groups", [])
        operational_groups = [str(v).strip() for v in raw_operational_groups if str(v).strip()]

        raw_subsystem_labels = entity.get("subsystem_labels", [])
        subsystem_labels = [str(v).strip() for v in raw_subsystem_labels if str(v).strip()]

        component_type = entity.get("type", "component")
        satisfies_categories = self._infer_satisfies_categories_from_entity(entity)
        inputs, outputs = self._resolve_ports(
            entity.get("inputs"), entity.get("outputs"), component_type, categories=satisfies_categories,
        )

        return {
            "id": entity.get("id"),
            "label": entity.get("pretty_name", entity.get("name", entity.get("id", "component"))),
            "component_type": component_type,
            "entry_type": entity.get("type", "component"),
            "dimensions_m": {
                "x": float(entity.get("dimension_length_m", 1.0)),
                "y": float(entity.get("dimension_width_m", 1.0)),
                "z": float(entity.get("dimension_height_m", 1.0)),
            },
            "mass_kg": float(entity.get("mass_kg", 0.0)),
            "power_kw": float(entity.get("power_kw", 0.0)),
            "satisfies_categories": satisfies_categories,
            "operational_groups": operational_groups,
            "subsystem_labels": subsystem_labels,
            "inputs": inputs,
            "outputs": outputs,
        }

    def _default_component_catalog(self):
        return [
            {
                "id": "comp_engine_inline_compact",
                "label": "Inline Engine",
                "component_type": "engine_component",
                "entry_type": "component",
                "dimensions_m": {"x": 2.2, "y": 1.2, "z": 1.4},
                "mass_kg": 680.0,
                "power_kw": 180.0,
                "satisfies_categories": ["propulsion_road", "powertrain"],
                "operational_groups": ["Powertrain"],
                "subsystem_labels": ["road propulsion"],
            },
            {
                "id": "comp_engine_vblock_heavy",
                "label": "V-Block Engine",
                "component_type": "engine_component",
                "entry_type": "component",
                "dimensions_m": {"x": 2.8, "y": 1.5, "z": 1.6},
                "mass_kg": 980.0,
                "power_kw": 320.0,
                "satisfies_categories": ["propulsion_road", "powertrain"],
                "operational_groups": ["Powertrain"],
                "subsystem_labels": ["road propulsion"],
            },
            {
                "id": "comp_fuel_tank_standard",
                "label": "Fuel Tank",
                "component_type": "fuel_tank_component",
                "entry_type": "component",
                "dimensions_m": {"x": 1.0, "y": 0.8, "z": 0.6},
                "mass_kg": 60.0,
                "power_kw": 0.0,
                "satisfies_categories": ["fuel_storage"],
                "operational_groups": ["Powertrain"],
                "subsystem_labels": ["fuel storage"],
            },
        ]

    def _load_component_catalog(self, world_model, vehicle_entity):
        if isinstance(vehicle_entity, dict) and "component_catalog" in vehicle_entity:
            catalog = []
            for raw_entry in vehicle_entity.get("component_catalog") or []:
                if isinstance(raw_entry, str):
                    component_entity = (
                        world_model.get_entity(raw_entry)
                        if world_model is not None and hasattr(world_model, "get_entity")
                        else None
                    )
                    if isinstance(component_entity, dict):
                        catalog.append(self._build_catalog_entry_from_component_entity(component_entity))
                    continue
                if not isinstance(raw_entry, dict):
                    continue
                component_id = raw_entry.get("id") or raw_entry.get("entity_id")
                component_entity = (
                    world_model.get_entity(component_id)
                    if component_id and world_model is not None and hasattr(world_model, "get_entity")
                    else None
                )
                if isinstance(component_entity, dict):
                    catalog.append(self._build_catalog_entry_from_component_entity(component_entity))
                elif raw_entry.get("dimensions_m"):
                    catalog.append(self._ensure_catalog_entry_ports(raw_entry))
            return catalog
        return [self._ensure_catalog_entry_ports(entry) for entry in self._default_component_catalog()]

    def _load_placed_components(self, world_model, vehicle_entity):
        if not isinstance(vehicle_entity, dict):
            return []
        placed = []
        for raw_component in vehicle_entity.get("installed_components") or []:
            if not isinstance(raw_component, dict):
                continue
            component = copy.deepcopy(raw_component)
            instance_id = str(component.get("instance_id") or "").strip()
            local_rect = component.get("local_rect_m")
            if not instance_id or not isinstance(local_rect, dict):
                continue
            component.setdefault("label", component.get("catalog_id") or instance_id)
            component.setdefault("component_type", "component")
            component.setdefault("satisfies_categories", [])
            component.setdefault("operational_groups", [])
            component.setdefault("subsystem_labels", [])
            if not component.get("slot_category"):
                categories = component.get("satisfies_categories") or []
                component["slot_category"] = categories[0] if categories else None
            placed.append(component)
        return placed

    def _load_manual_routes(self, vehicle_entity):
        raw_routes = vehicle_entity.get("manual_routes", []) if isinstance(vehicle_entity, dict) else []
        routes = []
        if not isinstance(raw_routes, list):
            return routes
        for raw in raw_routes:
            if not isinstance(raw, dict):
                continue
            required = ("from_slot_id", "from_port_id", "to_slot_id", "to_port_id")
            if not all(raw.get(key) for key in required):
                continue
            routes.append({key: str(raw[key]) for key in required})
        return routes

    def _infer_next_component_index(self):
        max_index = 0
        for component in self.placed_components:
            instance_id = component.get("instance_id", "")
            if not instance_id.startswith("placed_component_"):
                continue
            try:
                index_value = int(instance_id.split("_")[-1])
                max_index = max(max_index, index_value)
            except ValueError:
                continue
        return max_index + 1 if max_index > 0 else 1

    def get_vehicle_dimensions_m(self):
        return dict(self.vehicle_dimensions_m)

    def get_component_catalog(self):
        return list(self.component_catalog)

    def get_grouped_component_catalog(self):
        grouped = {}

        def entry_type_rank(entry):
            entry_type = str(entry.get("entry_type", "component")).strip().lower()
            return 0 if entry_type == "assembly" else 1

        sorted_entries = sorted(
            self.component_catalog,
            key=lambda entry: (
                entry_type_rank(entry),
                str(entry.get("entry_type", "component")).strip().lower(),
                (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                str(entry.get("label", "")),
            ),
        )

        for entry in sorted_entries:
            entry_type = str(entry.get("entry_type", "component")).strip().lower() or "component"
            group_name = (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems")
            group_name = str(group_name).strip() or "General Systems"

            section_title = f"{entry_type.title()}s / {group_name}"
            bucket = grouped.setdefault(
                section_title,
                {
                    "title": section_title,
                    "entry_type": entry_type,
                    "group_name": group_name,
                    "entries": [],
                },
            )
            bucket["entries"].append(entry)

        sections = list(grouped.values())
        sections.sort(
            key=lambda section: (
                0 if section["entry_type"] == "assembly" else 1,
                section["group_name"],
                section["title"],
            )
        )
        return sections



    def get_component_catalog_entry(self, catalog_id):
        for entry in self.component_catalog:
            if entry.get("id") == catalog_id:
                return entry
        return None

    def get_catalog_panel_rect(self):
        grouped_catalog = self.get_grouped_component_catalog()
        row_height = self.CATALOG_ENTRY_H
        section_gap = 8

        total_rows = 0
        for section in grouped_catalog:
            total_rows += 1
            total_rows += len(section.get("entries", []))

        height = (
            self.CATALOG_HEADER_H
            + self.CATALOG_PADDING
            + total_rows * row_height
            + max(0, len(grouped_catalog) - 1) * section_gap
            + self.CATALOG_PADDING
        )

        return {
            "x": self.CATALOG_PANEL_X,
            "y": self.CATALOG_PANEL_Y,
            "width": self.CATALOG_PANEL_W,
            "height": max(height, self.CATALOG_HEADER_H + self.CATALOG_PADDING * 2),
            "section_gap": section_gap,
        }

    def get_catalog_entry_rects(self):
        rects = []
        panel = self.get_catalog_panel_rect()
        grouped_catalog = self.get_grouped_component_catalog()

        entry_x = panel["x"] + self.CATALOG_PADDING
        entry_y = panel["y"] + self.CATALOG_HEADER_H + self.CATALOG_PADDING
        entry_w = panel["width"] - 2 * self.CATALOG_PADDING
        row_height = self.CATALOG_ENTRY_H
        section_gap = panel.get("section_gap", 8)

        for section in grouped_catalog:
            rects.append(
                {
                    "kind": "section",
                    "section_title": section["title"],
                    "catalog_id": None,
                    "label": section["title"],
                    "x": entry_x,
                    "y": entry_y,
                    "width": entry_w,
                    "height": row_height - 6,
                }
            )
            entry_y += row_height

            for entry in section.get("entries", []):
                rects.append(
                    {
                        "kind": "entry",
                        "section_title": section["title"],
                        "catalog_id": entry["id"],
                        "label": entry.get("label", entry["id"]),
                        "entry_type": entry.get("entry_type", "component"),
                        "group_name": (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                        "x": entry_x + 12,
                        "y": entry_y,
                        "width": entry_w - 12,
                        "height": row_height - 4,
                    }
                )
                entry_y += row_height

            entry_y += section_gap

        return rects

    def get_catalog_entry_at_screen_position(self, screen_pos):
        sx, sy = screen_pos
        for rect in self.get_catalog_entry_rects():
            if rect.get("kind") != "entry":
                continue
            if (
                rect["x"] <= sx <= rect["x"] + rect["width"]
                and rect["y"] <= sy <= rect["y"] + rect["height"]
            ):
                return rect["catalog_id"]
        return None

    def get_placed_components(self):
        return list(self.placed_components)

    def _resolve_vehicle_class_chain(self, vehicle_class):
        normalized = str(vehicle_class or "vehicle").strip().lower() or "vehicle"
        ordered = []
        visited = set()

        def visit(class_name):
            if class_name in visited:
                return
            visited.add(class_name)

            for parent in self.VEHICLE_CLASS_PARENTS.get(class_name, []):
                visit(parent)

            ordered.append(class_name)

        visit(normalized)
        if "vehicle" not in visited:
            visit("vehicle")
        return ordered

    def get_resolved_class_requirements(self):
        vehicle_class = ""
        if self.vehicle_entity is not None:
            vehicle_class = self.vehicle_entity.get("vehicle_class", "vehicle")

        class_chain = self._resolve_vehicle_class_chain(vehicle_class)
        resolved = []
        seen = set()

        for class_name in class_chain:
            for requirement in self.VEHICLE_CLASS_REQUIREMENTS.get(class_name, []):
                if requirement in seen:
                    continue
                seen.add(requirement)
                resolved.append(
                    {
                        "category": requirement,
                        "source_class": class_name,
                    }
                )

        return resolved

    def _get_component_satisfaction_categories(self, component):
        categories = set()

        for value in component.get("satisfies_categories", []):
            text = str(value).strip().lower()
            if text:
                categories.add(text)

        component_type = str(component.get("component_type", "")).strip().lower()
        categories.update(self.COMPONENT_CATEGORY_HINTS.get(component_type, set()))

        label_text = " ".join(
            str(component.get(key, ""))
            for key in ("label", "catalog_id", "component_type")
        ).lower()

        if "wheel" in label_text:
            categories.update({"locomotion_ground", "wheels"})
        if "performance" in label_text and "wheel" in label_text:
            categories.update({"performance_wheels"})
        if "track" in label_text:
            categories.update({"locomotion_ground", "tracks"})
        if "engine" in label_text or "motor" in label_text:
            categories.update({"powertrain"})
        if "control" in label_text or "cockpit" in label_text:
            categories.update({"control"})
        if "body" in label_text or "chassis" in label_text:
            categories.update({"structure", "body"})
        if "hull" in label_text:
            categories.update({"hull", "structure"})
        if "landing" in label_text and "gear" in label_text:
            categories.update({"landing_system"})
        if "cargo" in label_text:
            categories.update({"cargo_handling"})
        if "comm" in label_text or "antenna" in label_text or "relay" in label_text:
            categories.update({"communications_system"})
        if "weapon" in label_text or "gun" in label_text or "cannon" in label_text:
            categories.update({"weapon_system"})
        if "roof" in label_text:
            categories.update({"body"})

        return categories

    def get_requirement_status_list(self):
        required = self.get_resolved_class_requirements()
        placed = self.get_placed_components()
        wiring_status = self.get_component_wiring_status()

        placed_category_map = {}
        reserved_category_map = {}
        for component in placed:
            if component.get("catalog_id"):
                categories = self._get_component_satisfaction_categories(component)
                for category in categories:
                    placed_category_map.setdefault(category, []).append(component)
            else:
                slot_category = str(component.get("slot_category") or "").strip().lower()
                if slot_category:
                    reserved_category_map.setdefault(slot_category, []).append(component)

        structural_category_map = {}
        for feature in self.structural_features:
            if not isinstance(feature, dict):
                continue
            for raw_category in feature.get("satisfies_categories", []):
                category = str(raw_category).strip().lower()
                if category:
                    structural_category_map.setdefault(category, []).append(feature)

        results = []
        for requirement in required:
            category = requirement["category"]
            matching_components = placed_category_map.get(category, [])
            matching_structures = structural_category_map.get(category, [])
            reserved_slots = reserved_category_map.get(category, [])
            is_satisfied = bool(matching_components or matching_structures)
            matching_component_ids = [c.get("instance_id") for c in matching_components]
            fully_wired = all(
                wiring_status.get(instance_id, {"fully_wired": True})["fully_wired"]
                for instance_id in matching_component_ids
            )
            if is_satisfied:
                state = "installed" if fully_wired else "installed_unwired"
            elif reserved_slots:
                state = "reserved"
            else:
                state = "missing"
            results.append(
                {
                    "category": category,
                    "source_class": requirement["source_class"],
                    "is_satisfied": is_satisfied,
                    "state": state,
                    "is_wired": fully_wired,
                    "reserved_slot_ids": [c.get("instance_id") for c in reserved_slots],
                    "matching_component_ids": matching_component_ids,
                    "matching_component_labels": [c.get("label", c.get("instance_id", "component")) for c in matching_components],
                    "matching_structure_ids": [item.get("id") for item in matching_structures],
                    "matching_structure_labels": [item.get("label", item.get("id", "structure")) for item in matching_structures],
                }
            )

        return results

    def get_operational_system_summary(self):
        """
        Group hierarchical requirement status into operational system buckets
        with child subsystems. Prefer repository-defined operational_groups and
        subsystem_labels when available.
        """
        requirement_status = self.get_requirement_status_list()
        grouped = {}

        for entry in requirement_status:
            category = entry.get("category", "requirement")
            group_name = self.REQUIREMENT_TO_OPERATIONAL_GROUP.get(category, "General Systems")
            subsystem_name = self.REQUIREMENT_TO_SUBSYSTEM.get(category, category.replace("_", " "))

            bucket = grouped.setdefault(
                group_name,
                {
                    "group": group_name,
                    "children": [],
                    "component_labels": [],
                    "all_satisfied": True,
                    "any_satisfied": False,
                },
            )

            is_satisfied = bool(entry.get("is_satisfied"))
            matching_component_labels = list(entry.get("matching_component_labels", []))
            state = entry.get("state", "active" if is_satisfied else "missing")
            child_status = {
                "installed": "active",
                "installed_unwired": "unwired",
                "reserved": "reserved",
                "missing": "missing",
            }.get(state, "active" if is_satisfied else "missing")

            bucket["children"].append(
                {
                    "category": category,
                    "label": subsystem_name,
                    "source_class": entry.get("source_class", "vehicle"),
                    "status": child_status,
                    "matching_component_labels": matching_component_labels,
                }
            )

            if is_satisfied:
                bucket["any_satisfied"] = True
            else:
                bucket["all_satisfied"] = False

            for label in matching_component_labels:
                if label not in bucket["component_labels"]:
                    bucket["component_labels"].append(label)

        for component in self.get_placed_components():
            component_labels = [component.get("label", component.get("instance_id", "component"))]

            raw_groups = component.get("operational_groups", [])
            raw_subsystems = component.get("subsystem_labels", [])

            if raw_groups:
                for index, group_name in enumerate(raw_groups):
                    group_name = str(group_name).strip() or "General Systems"
                    subsystem_name = None

                    if index < len(raw_subsystems):
                        subsystem_name = str(raw_subsystems[index]).strip() or None
                    if subsystem_name is None and raw_subsystems:
                        subsystem_name = str(raw_subsystems[0]).strip() or None
                    if subsystem_name is None:
                        subsystem_name = component.get("label", component.get("instance_id", "component"))

                    bucket = grouped.setdefault(
                        group_name,
                        {
                            "group": group_name,
                            "children": [],
                            "component_labels": [],
                            "all_satisfied": True,
                            "any_satisfied": False,
                        },
                    )

                    existing_child = None
                    for child in bucket["children"]:
                        if child.get("label") == subsystem_name:
                            existing_child = child
                            break

                    if existing_child is None:
                        bucket["children"].append(
                            {
                                "category": None,
                                "label": subsystem_name,
                                "source_class": "component_subsystem_labels",
                                "status": "active",
                                "matching_component_labels": list(component_labels),
                            }
                        )
                    else:
                        for label in component_labels:
                            if label not in existing_child["matching_component_labels"]:
                                existing_child["matching_component_labels"].append(label)
                        existing_child["status"] = "active"

                    for label in component_labels:
                        if label not in bucket["component_labels"]:
                            bucket["component_labels"].append(label)

                    bucket["any_satisfied"] = True

        summary = []
        for group_name, bucket in grouped.items():
            if bucket["all_satisfied"]:
                status = "active"
            elif bucket["any_satisfied"]:
                status = "incomplete"
            else:
                status = "missing"

            summary.append(
                {
                    "group": group_name,
                    "status": status,
                    "children": bucket["children"],
                    "component_labels": bucket["component_labels"],
                }
            )

        desired_order = {
            "Structure": 0,
            "Crew & Control": 1,
            "Powertrain": 2,
            "Mobility": 3,
            "Cargo": 4,
            "Sensors & Comms": 5,
            "Weapons": 6,
            "Control Surfaces": 7,
            "General Systems": 8,
        }

        summary.sort(key=lambda item: (desired_order.get(item["group"], 99), item["group"]))
        return summary

    def get_world_base_rect(self, vehicle_position):
        dims = self.get_vehicle_dimensions_m()
        return {
            "x": vehicle_position.get("x", 0.0) - dims["x"] / 2.0,
            "y": vehicle_position.get("y", 0.0) - dims["y"] / 2.0,
            "width": dims["x"],
            "height": dims["y"],
        }

    def _clamp_local_rect_to_hull(self, local_rect):
        dims = self.get_vehicle_dimensions_m()

        width = max(0.1, min(local_rect.get("width", 1.0), dims["x"]))
        height = max(0.1, min(local_rect.get("height", 1.0), dims["y"]))

        max_x = max(0.0, dims["x"] - width)
        max_y = max(0.0, dims["y"] - height)

        x = min(max(0.0, local_rect.get("x", 0.0)), max_x)
        y = min(max(0.0, local_rect.get("y", 0.0)), max_y)

        return {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

    def _world_to_local_xy(self, vehicle_position, world_x, world_y):
        base_rect = self.get_world_base_rect(vehicle_position)
        return world_x - base_rect["x"], world_y - base_rect["y"]

    def _hull_contains_world_position(self, vehicle_position, world_x, world_y):
        base_rect = self.get_world_base_rect(vehicle_position)
        return (
            base_rect["x"] <= world_x <= base_rect["x"] + base_rect["width"]
            and base_rect["y"] <= world_y <= base_rect["y"] + base_rect["height"]
        )

    def get_world_design_blocks(self, vehicle_position):
        base_rect = self.get_world_base_rect(vehicle_position)
        world_blocks = []

        for component in self.placed_components:
            local_rect = component.get("local_rect_m", {})
            world_blocks.append(
                {
                    "id": component.get("instance_id"),
                    "label": component.get("label", component.get("instance_id", "component")),
                    "component_type": component.get("component_type", "component"),
                    "catalog_id": component.get("catalog_id"),
                    "entry_type": component.get("entry_type", "component"),
                    "satisfies_categories": list(component.get("satisfies_categories", [])),
                    "operational_groups": list(component.get("operational_groups", [])),
                    "subsystem_labels": list(component.get("subsystem_labels", [])),
                    "x": base_rect["x"] + local_rect.get("x", 0.0),
                    "y": base_rect["y"] + local_rect.get("y", 0.0),
                    "width": local_rect.get("width", 1.0),
                    "height": local_rect.get("height", 1.0),
                }
            )

        return world_blocks

    def get_drag_preview_block(self, vehicle_position):
        if not self.dragging_catalog_component_id or not self.drag_preview_local_rect_m:
            return None

        catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
        if catalog_entry is None:
            return None

        base_rect = self.get_world_base_rect(vehicle_position)
        local_rect = self.drag_preview_local_rect_m

        return {
            "id": "__drag_preview__",
            "label": catalog_entry.get("label", "component"),
            "component_type": catalog_entry.get("component_type", "component"),
            "catalog_id": catalog_entry.get("id"),
            "entry_type": catalog_entry.get("entry_type", "component"),
            "satisfies_categories": list(catalog_entry.get("satisfies_categories", [])),
            "operational_groups": list(catalog_entry.get("operational_groups", [])),
            "subsystem_labels": list(catalog_entry.get("subsystem_labels", [])),
            "x": base_rect["x"] + local_rect.get("x", 0.0),
            "y": base_rect["y"] + local_rect.get("y", 0.0),
            "width": local_rect.get("width", 1.0),
            "height": local_rect.get("height", 1.0),
        }

    # A component's diagram column is its primary operational group, ordered
    # the same way the operational status view already orders its groups.
    DIAGRAM_GROUP_ORDER = {
        "Structure": 0,
        "Crew & Control": 1,
        "Powertrain": 2,
        "Mobility": 3,
        "Cargo": 4,
        "Sensors & Comms": 5,
        "Weapons": 6,
        "Control Surfaces": 7,
        "General Systems": 8,
    }

    def get_system_diagram_payload(self):
        """
        Lay out every slot (installed or reserved-but-empty) as a node in an
        abstract grid -- columns by operational group, independent of the
        slot's physical position in the hull -- with edges from
        ``compute_system_wiring`` connecting matched output/input ports.
        """
        columns = {}
        for component in self.placed_components:
            raw_groups = component.get("operational_groups") or []
            group_name = str(raw_groups[0]).strip() if raw_groups else "General Systems"
            columns.setdefault(group_name, []).append(component)

        group_order = sorted(columns.keys(), key=lambda name: (self.DIAGRAM_GROUP_ORDER.get(name, 99), name))

        wiring_status = self.get_component_wiring_status()
        column_width, row_height, node_gap = 1.0, 1.0, 0.25
        nodes = []
        for column_index, group_name in enumerate(group_order):
            for row_index, component in enumerate(columns[group_name]):
                instance_id = component.get("instance_id")
                nodes.append({
                    "id": instance_id,
                    "label": component.get("label", instance_id or "slot"),
                    "group": group_name,
                    "slot_category": component.get("slot_category"),
                    "installed": bool(component.get("catalog_id")),
                    "fully_wired": wiring_status.get(instance_id, {"fully_wired": True})["fully_wired"],
                    "x": column_index * (column_width + node_gap),
                    "y": row_index * (row_height + node_gap),
                    "width": column_width,
                    "height": row_height,
                    "inputs": self._instance_ports(component, "inputs"),
                    "outputs": self._instance_ports(component, "outputs"),
                })

        return {
            "nodes": nodes,
            "group_order": group_order,
            "edges": self.compute_system_wiring(),
            "wiring_status": wiring_status,
        }

    def get_design_payload(self, vehicle_position):
        return {
            "base_rect": self.get_world_base_rect(vehicle_position),
            "blocks": self.get_world_design_blocks(vehicle_position),
            "drag_preview_block": self.get_drag_preview_block(vehicle_position),
            "component_catalog": self.get_component_catalog(),
            "grouped_component_catalog": self.get_grouped_component_catalog(),
            "catalog_panel_rect": self.get_catalog_panel_rect(),
            "catalog_entry_rects": self.get_catalog_entry_rects(),
            "selected_component_id": self.selected_component_id,
            "hover_component_id": self.hover_component_id,
            "active_catalog_component_id": self.active_catalog_component_id,
            "hover_catalog_component_id": self.hover_catalog_component_id,
            "dragging_component_id": self.dragging_component_id,
            "dragging_catalog_component_id": self.dragging_catalog_component_id,
            "requirement_status": self.get_requirement_status_list(),
            "system_diagram": self.get_system_diagram_payload(),
            "orthographic_views": {
                view_id: {
                    **dict(view),
                    "grid": [list(row) for row in self.hull_silhouettes.get(view_id, [])],
                    "components": self.get_orthographic_component_blocks(view_id),
                }
                for view_id, view in self.ORTHOGRAPHIC_VIEWS.items()
            },
        }

    def component_at_world_position(self, vehicle_position, world_x, world_y):
        for block in reversed(self.get_world_design_blocks(vehicle_position)):
            block_min_x = block["x"]
            block_max_x = block["x"] + block["width"]
            block_min_y = block["y"]
            block_max_y = block["y"] + block["height"]

            if block_min_x <= world_x <= block_max_x and block_min_y <= world_y <= block_max_y:
                return block

        return None

    def set_hover_component(self, component_id):
        self.hover_component_id = component_id

    def set_selected_component(self, component_id):
        self.selected_component_id = component_id

    def set_active_catalog_component(self, catalog_id):
        self.active_catalog_component_id = catalog_id

    def set_hover_catalog_component(self, catalog_id):
        self.hover_catalog_component_id = catalog_id

    def _make_component_instance(self, catalog_entry, local_rect):
        instance_id = f"placed_component_{self.next_component_index:03d}"
        self.next_component_index += 1

        return {
            "instance_id": instance_id,
            "catalog_id": catalog_entry["id"],
            "label": catalog_entry["label"],
            "component_type": catalog_entry["component_type"],
            "entry_type": catalog_entry.get("entry_type", "component"),
            "satisfies_categories": list(catalog_entry.get("satisfies_categories", [])),
            "operational_groups": list(catalog_entry.get("operational_groups", [])),
            "subsystem_labels": list(catalog_entry.get("subsystem_labels", [])),
            "slot_category": (catalog_entry.get("satisfies_categories") or [None])[0],
            "local_rect_m": self._clamp_local_rect_to_hull(local_rect),
        }

    def _get_component_by_instance_id(self, instance_id):
        for component in self.placed_components:
            if component.get("instance_id") == instance_id:
                return component
        return None

    # ------------------------------------------------------------------
    # Slot / installed-part split: a slot is a reserved rect + declared
    # category that a catalog part can be installed into and swapped out
    # of, independent of the rect itself moving or resizing.
    # ------------------------------------------------------------------

    def get_compatible_catalog_entries_for_slot(self, instance_id):
        slot = self._get_component_by_instance_id(instance_id)
        if slot is None:
            return []
        slot_category = slot.get("slot_category")
        if not slot_category:
            return list(self.component_catalog)
        return [
            entry for entry in self.component_catalog
            if slot_category in (entry.get("satisfies_categories") or [])
        ]

    def install_component_in_slot(self, instance_id, catalog_id):
        slot = self._get_component_by_instance_id(instance_id)
        catalog_entry = self.get_component_catalog_entry(catalog_id)
        if slot is None or catalog_entry is None:
            return False
        slot["catalog_id"] = catalog_entry["id"]
        slot["label"] = catalog_entry["label"]
        slot["component_type"] = catalog_entry["component_type"]
        slot["entry_type"] = catalog_entry.get("entry_type", "component")
        slot["satisfies_categories"] = list(catalog_entry.get("satisfies_categories", []))
        slot["operational_groups"] = list(catalog_entry.get("operational_groups", []))
        slot["subsystem_labels"] = list(catalog_entry.get("subsystem_labels", []))
        if not slot.get("slot_category"):
            slot["slot_category"] = (catalog_entry.get("satisfies_categories") or [None])[0]
        return True

    def uninstall_component_from_slot(self, instance_id):
        slot = self._get_component_by_instance_id(instance_id)
        if slot is None or not slot.get("catalog_id"):
            return False
        slot["catalog_id"] = None
        slot["label"] = f"Empty {slot.get('slot_category') or 'slot'}"
        slot["component_type"] = "empty_slot"
        slot["entry_type"] = "empty_slot"
        slot["satisfies_categories"] = []
        slot["operational_groups"] = []
        slot["subsystem_labels"] = []
        return True

    # ------------------------------------------------------------------
    # System diagram: auto-wire installed components' ports by resource
    # type, with manual overrides recorded in ``manual_routes``.
    # ------------------------------------------------------------------

    def _installed_components(self):
        return [component for component in self.placed_components if component.get("catalog_id")]

    def _instance_ports(self, component, direction):
        catalog = self.get_component_catalog_entry(component.get("catalog_id")) or {}
        return catalog.get(direction, [])

    def compute_system_wiring(self):
        installed = self._installed_components()
        output_ports = []
        input_ports = []
        for component in installed:
            instance_id = component.get("instance_id")
            for port in self._instance_ports(component, "outputs"):
                output_ports.append((instance_id, port))
            for port in self._instance_ports(component, "inputs"):
                input_ports.append((instance_id, port))

        edges = []
        claimed_outputs = set()
        manual_targets = set()
        for route in self.manual_routes:
            source_key = (route["from_slot_id"], route["from_port_id"])
            target_key = (route["to_slot_id"], route["to_port_id"])
            source_port = next((p for iid, p in output_ports if (iid, p["port_id"]) == source_key), None)
            target_exists = any((iid, p["port_id"]) == target_key for iid, p in input_ports)
            if source_port is None or not target_exists:
                continue
            edges.append({**route, "resource_type": source_port["resource_type"], "manual": True})
            claimed_outputs.add(source_key)
            manual_targets.add(target_key)

        component_by_id = {component["instance_id"]: component for component in installed}
        for target_instance_id, port in input_ports:
            target_key = (target_instance_id, port["port_id"])
            if target_key in manual_targets:
                continue
            candidates = [
                (source_instance_id, source_port)
                for source_instance_id, source_port in output_ports
                if source_port["resource_type"] == port["resource_type"]
                and (source_instance_id, source_port["port_id"]) not in claimed_outputs
                and source_instance_id != target_instance_id
            ]
            if not candidates:
                continue

            target_groups = set(component_by_id.get(target_instance_id, {}).get("operational_groups", []))

            def _score(candidate, target_groups=target_groups):
                source_instance_id, _source_port = candidate
                source_groups = set(component_by_id.get(source_instance_id, {}).get("operational_groups", []))
                return 0 if source_groups & target_groups else 1

            best_source_instance_id, best_source_port = min(candidates, key=_score)
            claimed_outputs.add((best_source_instance_id, best_source_port["port_id"]))
            edges.append({
                "from_slot_id": best_source_instance_id,
                "from_port_id": best_source_port["port_id"],
                "to_slot_id": target_instance_id,
                "to_port_id": port["port_id"],
                "resource_type": port["resource_type"],
                "manual": False,
            })
        return edges

    def get_component_wiring_status(self):
        edges = self.compute_system_wiring()
        wired_targets = {(edge["to_slot_id"], edge["to_port_id"]) for edge in edges}
        status = {}
        for component in self._installed_components():
            instance_id = component.get("instance_id")
            required_inputs = self._instance_ports(component, "inputs")
            missing = [port for port in required_inputs if (instance_id, port["port_id"]) not in wired_targets]
            status[instance_id] = {"fully_wired": not missing, "missing_inputs": missing}
        return status

    def cycle_input_port_route(self, instance_id, port_id):
        """
        Manually override which output port feeds a given input port,
        cycling through compatible candidates plus a final "auto" option
        that clears the override and reverts to type-matched auto-wiring.
        """
        target_component = self._get_component_by_instance_id(instance_id)
        if target_component is None:
            return False
        target_port = next(
            (port for port in self._instance_ports(target_component, "inputs") if port["port_id"] == port_id),
            None,
        )
        if target_port is None:
            return False

        candidates = []
        for component in self._installed_components():
            if component.get("instance_id") == instance_id:
                continue
            for port in self._instance_ports(component, "outputs"):
                if port["resource_type"] == target_port["resource_type"]:
                    candidates.append((component["instance_id"], port["port_id"]))
        if not candidates:
            return False

        existing_index = next(
            (
                index for index, route in enumerate(self.manual_routes)
                if route["to_slot_id"] == instance_id and route["to_port_id"] == port_id
            ),
            None,
        )
        current = None
        if existing_index is not None:
            existing = self.manual_routes[existing_index]
            current = (existing["from_slot_id"], existing["from_port_id"])

        options = candidates + [None]
        next_index = (options.index(current) + 1) % len(options) if current in options else 0
        chosen = options[next_index]

        if existing_index is not None:
            del self.manual_routes[existing_index]
        if chosen is not None:
            self.manual_routes.append({
                "from_slot_id": chosen[0],
                "from_port_id": chosen[1],
                "to_slot_id": instance_id,
                "to_port_id": port_id,
            })
        return True

    def _build_local_rect_from_pointer(self, width, height, local_x, local_y, pointer_offset):
        offset_x = 0.0
        offset_y = 0.0
        if pointer_offset:
            offset_x = pointer_offset.get("x", 0.0)
            offset_y = pointer_offset.get("y", 0.0)

        return self._clamp_local_rect_to_hull(
            {
                "x": local_x - offset_x,
                "y": local_y - offset_y,
                "width": width,
                "height": height,
            }
        )

    def begin_catalog_drag(self, catalog_id):
        catalog_entry = self.get_component_catalog_entry(catalog_id)
        if catalog_entry is None:
            return False

        dims = catalog_entry.get("dimensions_m", {})
        self.dragging_catalog_component_id = catalog_id
        self.dragging_component_id = None
        self.drag_pointer_offset_local_m = {
            "x": dims.get("x", 1.0) / 2.0,
            "y": dims.get("y", 1.0) / 2.0,
        }
        self.drag_preview_local_rect_m = None
        self.active_catalog_component_id = catalog_id
        return True

    def begin_component_drag(self, vehicle_position, component_id, world_x, world_y):
        component = self._get_component_by_instance_id(component_id)
        if component is None:
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        rect = component.get("local_rect_m", {})

        self.dragging_component_id = component_id
        self.dragging_catalog_component_id = None
        self.drag_preview_local_rect_m = None
        self.drag_pointer_offset_local_m = {
            "x": local_x - rect.get("x", 0.0),
            "y": local_y - rect.get("y", 0.0),
        }
        self.selected_component_id = component_id
        return True

    def update_drag(self, vehicle_position, world_x, world_y):
        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            if self.dragging_catalog_component_id:
                self.drag_preview_local_rect_m = None
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)

        if self.dragging_component_id:
            component = self._get_component_by_instance_id(self.dragging_component_id)
            if component is None:
                return False

            rect = component.get("local_rect_m", {})
            component["local_rect_m"] = self._build_local_rect_from_pointer(
                rect.get("width", 1.0),
                rect.get("height", 1.0),
                local_x,
                local_y,
                self.drag_pointer_offset_local_m,
            )
            return True

        if self.dragging_catalog_component_id:
            catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
            if catalog_entry is None:
                return False

            dims = catalog_entry.get("dimensions_m", {})
            self.drag_preview_local_rect_m = self._build_local_rect_from_pointer(
                dims.get("x", 1.0),
                dims.get("y", 1.0),
                local_x,
                local_y,
                self.drag_pointer_offset_local_m,
            )
            return True

        return False

    def end_drag(self, vehicle_position, world_x, world_y):
        created_id = None

        if self.dragging_catalog_component_id and self.drag_preview_local_rect_m:
            catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
            if catalog_entry is not None and self._hull_contains_world_position(vehicle_position, world_x, world_y):
                new_component = self._make_component_instance(catalog_entry, self.drag_preview_local_rect_m)
                self.placed_components.append(new_component)
                self.selected_component_id = new_component["instance_id"]
                created_id = new_component["instance_id"]

        ended_component_id = self.dragging_component_id

        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

        if created_id:
            return created_id

        if ended_component_id:
            return ended_component_id

        return None

    def cancel_drag(self):
        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

    def place_active_catalog_component_at_world_position(self, vehicle_position, world_x, world_y):
        if not self.active_catalog_component_id:
            return None

        catalog_entry = self.get_component_catalog_entry(self.active_catalog_component_id)
        if not catalog_entry:
            return None

        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            return None

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        dims = catalog_entry.get("dimensions_m", {})

        local_rect = {
            "x": local_x - dims.get("x", 1.0) / 2.0,
            "y": local_y - dims.get("y", 1.0) / 2.0,
            "width": dims.get("x", 1.0),
            "height": dims.get("y", 1.0),
        }

        new_component = self._make_component_instance(catalog_entry, local_rect)
        self.placed_components.append(new_component)
        self.selected_component_id = new_component["instance_id"]
        return new_component["instance_id"]

    def move_selected_component_to_world_position(self, vehicle_position, world_x, world_y):
        if not self.selected_component_id:
            return False

        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            return False

        target_component = self._get_component_by_instance_id(self.selected_component_id)
        if target_component is None:
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        current_rect = target_component.get("local_rect_m", {})

        new_local_rect = {
            "x": local_x - current_rect.get("width", 1.0) / 2.0,
            "y": local_y - current_rect.get("height", 1.0) / 2.0,
            "width": current_rect.get("width", 1.0),
            "height": current_rect.get("height", 1.0),
        }
        target_component["local_rect_m"] = self._clamp_local_rect_to_hull(new_local_rect)
        return True
