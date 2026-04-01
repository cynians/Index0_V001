class VehicleDesignController:
    """
    Stores vehicle design-state and design-specific interaction logic.

    Current slice:
    * stores physical vehicle dimensions in SI units
    * stores a simple component catalog
    * stores placed design components in local vehicle-space meters
    * exposes design render payloads
    * handles design-window catalog selection
    * supports basic placement and repositioning inside the hull
    * can bootstrap its state from repository entities
    """

    CATALOG_PANEL_X = 18
    CATALOG_PANEL_Y = 18
    CATALOG_PANEL_W = 320
    CATALOG_ENTRY_H = 28
    CATALOG_HEADER_H = 28
    CATALOG_PADDING = 10

    def __init__(self, world_model=None, vehicle_entity=None):
        self.world_model = world_model
        self.vehicle_entity = vehicle_entity

        self.vehicle_dimensions_m = self._load_vehicle_dimensions_m(vehicle_entity)
        self.component_catalog = self._load_component_catalog(world_model, vehicle_entity)
        self.placed_components = self._load_placed_components(world_model, vehicle_entity)

        if not self.placed_components and self.component_catalog:
            first_entry = self.component_catalog[0]
            self.placed_components = [
                {
                    "instance_id": "placed_component_001",
                    "catalog_id": first_entry["id"],
                    "label": first_entry["label"],
                    "component_type": first_entry["component_type"],
                    "local_rect_m": {
                        "x": 0.8,
                        "y": 1.4,
                        "width": first_entry["dimensions_m"]["x"],
                        "height": first_entry["dimensions_m"]["y"],
                    },
                }
            ]

        self.next_component_index = self._infer_next_component_index()

        self.hover_component_id = None
        self.selected_component_id = None
        self.active_catalog_component_id = None
        self.hover_catalog_component_id = None

    def _load_vehicle_dimensions_m(self, vehicle_entity):
        if vehicle_entity:
            return {
                "x": float(vehicle_entity.get("dimension_x_m", 10.0)),
                "y": float(vehicle_entity.get("dimension_y_m", 4.0)),
                "z": float(vehicle_entity.get("dimension_z_m", 3.0)),
            }

        return {
            "x": 10.0,
            "y": 4.0,
            "z": 3.0,
        }

    def _build_catalog_entry_from_component_entity(self, entity):
        return {
            "id": entity.get("id"),
            "label": entity.get("pretty_name", entity.get("name", entity.get("id", "component"))),
            "component_type": entity.get("component_class", "component"),
            "dimensions_m": {
                "x": float(entity.get("dimension_x_m", 1.0)),
                "y": float(entity.get("dimension_y_m", 1.0)),
                "z": float(entity.get("dimension_z_m", 1.0)),
            },
            "mass_kg": float(entity.get("mass_kg", 0.0)),
            "power_kw": float(entity.get("power_kw", 0.0)),
        }

    def _default_component_catalog(self):
        return [
            {
                "id": "comp_engine_inline_compact",
                "label": "Inline Engine",
                "component_type": "engine_component",
                "dimensions_m": {"x": 2.2, "y": 1.2, "z": 1.4},
                "mass_kg": 680.0,
                "power_kw": 180.0,
            },
            {
                "id": "comp_engine_vblock_heavy",
                "label": "V-Block Engine",
                "component_type": "engine_component",
                "dimensions_m": {"x": 2.8, "y": 1.5, "z": 1.6},
                "mass_kg": 980.0,
                "power_kw": 320.0,
            },
        ]

    def _load_component_catalog(self, world_model, vehicle_entity):
        if world_model is None or vehicle_entity is None:
            return self._default_component_catalog()

        component_ids = vehicle_entity.get("design_catalog_components", [])
        catalog = []

        for component_id in component_ids:
            entity = world_model.get_entity(component_id)
            if entity is None:
                continue
            catalog.append(self._build_catalog_entry_from_component_entity(entity))

        return catalog or self._default_component_catalog()

    def _load_placed_components(self, world_model, vehicle_entity):
        placed = []

        if vehicle_entity is None:
            return placed

        design_placed_components = vehicle_entity.get("design_placed_components", [])
        for entry in design_placed_components:
            if not isinstance(entry, dict):
                continue

            component_id = entry.get("component_id")
            component_entity = world_model.get_entity(component_id) if (world_model and component_id) else None

            if component_entity is not None:
                label = component_entity.get("pretty_name", component_entity.get("name", component_id))
                component_type = component_entity.get("component_class", "component")
                width = float(entry.get("width_m", component_entity.get("dimension_x_m", 1.0)))
                height = float(entry.get("height_m", component_entity.get("dimension_y_m", 1.0)))
            else:
                label = entry.get("label", component_id or "component")
                component_type = entry.get("component_type", "component")
                width = float(entry.get("width_m", 1.0))
                height = float(entry.get("height_m", 1.0))

            placed.append(
                {
                    "instance_id": entry.get("instance_id", "placed_component_001"),
                    "catalog_id": component_id,
                    "label": label,
                    "component_type": component_type,
                    "local_rect_m": {
                        "x": float(entry.get("local_x_m", 0.0)),
                        "y": float(entry.get("local_y_m", 0.0)),
                        "width": width,
                        "height": height,
                    },
                }
            )

        return placed

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

    def get_component_catalog_entry(self, catalog_id):
        for entry in self.component_catalog:
            if entry.get("id") == catalog_id:
                return entry
        return None

    def get_catalog_panel_rect(self):
        height = (
            self.CATALOG_HEADER_H
            + self.CATALOG_PADDING
            + len(self.component_catalog) * self.CATALOG_ENTRY_H
            + self.CATALOG_PADDING
        )
        return {
            "x": self.CATALOG_PANEL_X,
            "y": self.CATALOG_PANEL_Y,
            "width": self.CATALOG_PANEL_W,
            "height": height,
        }

    def get_catalog_entry_rects(self):
        rects = []
        panel = self.get_catalog_panel_rect()
        entry_x = panel["x"] + self.CATALOG_PADDING
        entry_y = panel["y"] + self.CATALOG_HEADER_H + self.CATALOG_PADDING
        entry_w = panel["width"] - 2 * self.CATALOG_PADDING

        for index, entry in enumerate(self.component_catalog):
            rects.append(
                {
                    "catalog_id": entry["id"],
                    "x": entry_x,
                    "y": entry_y + index * self.CATALOG_ENTRY_H,
                    "width": entry_w,
                    "height": self.CATALOG_ENTRY_H - 4,
                }
            )

        return rects

    def get_catalog_entry_at_screen_position(self, screen_pos):
        sx, sy = screen_pos
        for rect in self.get_catalog_entry_rects():
            if (
                rect["x"] <= sx <= rect["x"] + rect["width"]
                and rect["y"] <= sy <= rect["y"] + rect["height"]
            ):
                return rect["catalog_id"]
        return None

    def get_placed_components(self):
        return list(self.placed_components)

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
                    "x": base_rect["x"] + local_rect.get("x", 0.0),
                    "y": base_rect["y"] + local_rect.get("y", 0.0),
                    "width": local_rect.get("width", 1.0),
                    "height": local_rect.get("height", 1.0),
                }
            )

        return world_blocks

    def get_design_payload(self, vehicle_position):
        return {
            "base_rect": self.get_world_base_rect(vehicle_position),
            "blocks": self.get_world_design_blocks(vehicle_position),
            "component_catalog": self.get_component_catalog(),
            "catalog_panel_rect": self.get_catalog_panel_rect(),
            "catalog_entry_rects": self.get_catalog_entry_rects(),
            "selected_component_id": self.selected_component_id,
            "hover_component_id": self.hover_component_id,
            "active_catalog_component_id": self.active_catalog_component_id,
            "hover_catalog_component_id": self.hover_catalog_component_id,
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
            "local_rect_m": self._clamp_local_rect_to_hull(local_rect),
        }

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

        target_component = None
        for component in self.placed_components:
            if component.get("instance_id") == self.selected_component_id:
                target_component = component
                break

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