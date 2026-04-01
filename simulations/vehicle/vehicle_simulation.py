from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.vehicle.vehicle_design import VehicleDesignController


class VehicleSimulation:
    """
    Prototype vehicle simulation.

    Current slice:
    * dedicated render mode
    * dedicated vehicle tab root
    * focused vehicle view modes:
      - design
      - interior
      - operational
    * vehicle design logic split into VehicleDesignController
    * physical vehicle dimensions stored in SI units
    * display geometry derived from those SI dimensions
    * 100 m x 100 m prototype vehicle map for scale testing
    * basic design-window catalog selection and component placement
    * placeholder exported render payload variants for other simulation consumers
    """

    VIEW_DESIGN = "design"
    VIEW_INTERIOR = "interior"
    VIEW_OPERATIONAL = "operational"

    TEST_MAP_SIZE_X_M = 100.0
    TEST_MAP_SIZE_Y_M = 100.0

    def __init__(self):
        class _DummySystem:
            def update(self, dt):
                pass

        self.render_mode = "vehicle"
        self.world_units_to_meters = 1.0

        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.available_view_modes = [
            self.VIEW_DESIGN,
            self.VIEW_INTERIOR,
            self.VIEW_OPERATIONAL,
        ]
        self.active_view_mode = self.VIEW_DESIGN

        self.design_panel_tabs = [
            {"id": "catalog", "label": "Catalog"},
            {"id": "selection", "label": "Selection"},
            {"id": "layout", "label": "Layout"},
        ]
        self.active_design_panel_tab_id = "catalog"

        self.min_zoom = 1.0
        self.max_zoom = 20.0
        self.preferred_zoom = 7.0

        self.bounds = {
            "min_x": 0.0,
            "max_x": self.TEST_MAP_SIZE_X_M,
            "min_y": 0.0,
            "max_y": self.TEST_MAP_SIZE_Y_M,
        }

        self.design = VehicleDesignController()

        self.vehicle = {
            "id": "vehicle_test_rig_01",
            "name": "Vehicle Test Rig 01",
            "vehicle_class": "prototype utility vehicle",
            "manufacturer": "Index Test Works",
            "position": {
                "x": self.TEST_MAP_SIZE_X_M / 2.0,
                "y": self.TEST_MAP_SIZE_Y_M / 2.0,
            },
            "interior_layout": [
                {
                    "id": "driver_station",
                    "label": "Driver",
                    "x_fraction": 0.00,
                    "y_fraction": 0.0,
                    "width_fraction": 0.20,
                    "height_fraction": 1.0,
                },
                {
                    "id": "crew_space",
                    "label": "Crew",
                    "x_fraction": 0.20,
                    "y_fraction": 0.0,
                    "width_fraction": 0.25,
                    "height_fraction": 1.0,
                },
                {
                    "id": "cargo_bay",
                    "label": "Cargo",
                    "x_fraction": 0.45,
                    "y_fraction": 0.0,
                    "width_fraction": 0.55,
                    "height_fraction": 1.0,
                },
            ],
            "operational_state": {
                "speed_kph": 38,
                "heading_deg": 90,
                "power_state": "nominal",
                "crew_state": "ready",
                "task_state": "idle test state",
                "range_km": 420,
            },
        }

        self.hover_part_id = None
        self.selected_part_id = None
        self.hover_screen_pos = None

    @property
    def year(self):
        return 2400

    def update(self, dt):
        self.sim_manager.update(dt)

    def get_center(self):
        return self.TEST_MAP_SIZE_X_M / 2.0, self.TEST_MAP_SIZE_Y_M / 2.0

    def _clear_interaction_state(self):
        self.hover_part_id = None
        self.selected_part_id = None
        self.hover_screen_pos = None
        self.design.set_hover_component(None)
        self.design.set_selected_component(None)

    def _reset_design_panel_state(self):
        self.active_design_panel_tab_id = "catalog"

    def set_view_mode(self, mode):
        if mode not in self.available_view_modes:
            return False

        self.active_view_mode = mode
        self._clear_interaction_state()

        if mode == self.VIEW_DESIGN:
            self._reset_design_panel_state()

        return True

    def get_vehicle_name(self):
        return self.vehicle.get("name", self.vehicle.get("id", "vehicle"))

    def get_vehicle_class(self):
        return self.vehicle.get("vehicle_class", "vehicle")

    def get_vehicle_dimensions_m(self):
        return self.design.get_vehicle_dimensions_m()

    def get_active_mode_label(self):
        mode_labels = {
            self.VIEW_DESIGN: "Vehicle Design",
            self.VIEW_INTERIOR: "Interior",
            self.VIEW_OPERATIONAL: "Operational",
        }
        return mode_labels.get(self.active_view_mode, self.active_view_mode)

    def get_mode_base_rect(self):
        return self.design.get_world_base_rect(self.vehicle.get("position", {}))

    def select_design_catalog_component(self, catalog_id):
        """
        Select the active design catalog component for placement.
        """
        if self.active_view_mode != self.VIEW_DESIGN:
            return False

        if self.design.get_component_catalog_entry(catalog_id) is None:
            return False

        self.design.set_active_catalog_component(catalog_id)
        self.selected_part_id = None
        self.design.set_selected_component(None)
        self.hover_screen_pos = None
        return True

    def get_simulation_panel_tabs(self):
        if self.active_view_mode == self.VIEW_DESIGN:
            return list(self.design_panel_tabs)
        return []

    def get_active_simulation_panel_tab_id(self):
        if self.active_view_mode == self.VIEW_DESIGN:
            return self.active_design_panel_tab_id
        return None

    def set_active_simulation_panel_tab(self, tab_id):
        if self.active_view_mode != self.VIEW_DESIGN:
            return False

        valid_ids = {tab["id"] for tab in self.design_panel_tabs}
        if tab_id not in valid_ids:
            return False

        self.active_design_panel_tab_id = tab_id
        return True

    def _layout_to_world_blocks(self, layout_entries):
        base_rect = self.get_mode_base_rect()
        base_x = base_rect["x"]
        base_y = base_rect["y"]
        base_w = base_rect["width"]
        base_h = base_rect["height"]

        world_blocks = []
        for entry in layout_entries:
            world_blocks.append(
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "x": base_x + entry["x_fraction"] * base_w,
                    "y": base_y + entry["y_fraction"] * base_h,
                    "width": entry["width_fraction"] * base_w,
                    "height": entry["height_fraction"] * base_h,
                }
            )

        return world_blocks

    def get_mode_blocks(self):
        if self.active_view_mode == self.VIEW_DESIGN:
            return self.design.get_world_design_blocks(self.vehicle.get("position", {}))

        if self.active_view_mode == self.VIEW_INTERIOR:
            return self._layout_to_world_blocks(self.vehicle.get("interior_layout", []))

        return []

    def _build_design_payload(self, payload):
        design_payload = self.design.get_design_payload(self.vehicle.get("position", {}))
        payload["base_rect"] = design_payload["base_rect"]
        payload["blocks"] = design_payload["blocks"]
        payload["component_catalog"] = design_payload["component_catalog"]
        payload["catalog_panel_rect"] = design_payload["catalog_panel_rect"]
        payload["catalog_entry_rects"] = design_payload["catalog_entry_rects"]
        payload["active_catalog_component_id"] = design_payload["active_catalog_component_id"]
        payload["hover_catalog_component_id"] = design_payload["hover_catalog_component_id"]
        return payload

    def _build_interior_payload(self, payload):
        payload["base_rect"] = self.get_mode_base_rect()
        payload["blocks"] = self.get_mode_blocks()
        return payload

    def _build_operational_payload(self, payload):
        payload["base_rect"] = self.get_mode_base_rect()
        payload["operational_state"] = self.vehicle.get("operational_state", {})
        payload["operational_modules"] = []
        payload["installed_components"] = self.design.get_placed_components()
        return payload

    def get_focused_render_payload(self):
        dimensions = self.get_vehicle_dimensions_m()

        payload = {
            "vehicle_id": self.vehicle.get("id"),
            "vehicle_name": self.get_vehicle_name(),
            "vehicle_class": self.get_vehicle_class(),
            "vehicle_dimensions_m": dimensions,
            "mode": self.active_view_mode,
            "mode_label": self.get_active_mode_label(),
            "selected_part_id": self.selected_part_id,
            "hover_part_id": self.hover_part_id,
            "map_bounds_m": {
                "x": self.TEST_MAP_SIZE_X_M,
                "y": self.TEST_MAP_SIZE_Y_M,
            },
        }

        if self.active_view_mode == self.VIEW_DESIGN:
            return self._build_design_payload(payload)

        if self.active_view_mode == self.VIEW_INTERIOR:
            return self._build_interior_payload(payload)

        return self._build_operational_payload(payload)

    def get_export_render_payload(self, consumer_type="generic"):
        operational_state = self.vehicle.get("operational_state", {})
        dimensions = self.get_vehicle_dimensions_m()

        base_payload = {
            "vehicle_id": self.vehicle.get("id"),
            "vehicle_name": self.get_vehicle_name(),
            "vehicle_class": self.get_vehicle_class(),
            "vehicle_dimensions_m": dimensions,
            "consumer_type": consumer_type,
        }

        if consumer_type == "person":
            base_payload.update(
                {
                    "visible_controls": ["drive", "power", "cargo access"],
                    "crew_state": operational_state.get("crew_state"),
                    "power_state": operational_state.get("power_state"),
                    "task_state": operational_state.get("task_state"),
                }
            )
            return base_payload

        if consumer_type == "faction":
            base_payload.update(
                {
                    "readiness": operational_state.get("crew_state"),
                    "power_state": operational_state.get("power_state"),
                    "range_km": operational_state.get("range_km"),
                    "role_summary": "prototype utility platform",
                }
            )
            return base_payload

        if consumer_type == "producer":
            base_payload.update(
                {
                    "manufacturer": self.vehicle.get("manufacturer"),
                    "design_component_count": len(self.design.get_placed_components()),
                    "interior_block_count": len(self.vehicle.get("interior_layout", [])),
                    "production_summary": "prototype shell for later production-detail integration",
                }
            )
            return base_payload

        base_payload.update(
            {
                "power_state": operational_state.get("power_state"),
                "task_state": operational_state.get("task_state"),
            }
        )
        return base_payload

    def _design_block_at_world_position(self, world_x, world_y):
        return self.design.component_at_world_position(
            self.vehicle.get("position", {}),
            world_x,
            world_y,
        )

    def _interior_block_at_world_position(self, world_x, world_y):
        for block in reversed(self.get_mode_blocks()):
            block_min_x = block["x"]
            block_max_x = block["x"] + block["width"]
            block_min_y = block["y"]
            block_max_y = block["y"] + block["height"]

            if block_min_x <= world_x <= block_max_x and block_min_y <= world_y <= block_max_y:
                return block

        return None

    def handle_pointer_motion(self, event, camera, screen_pos):
        if self.active_view_mode == self.VIEW_DESIGN:
            world_x, world_y = camera.screen_to_world(screen_pos)

            hovered_block = self._design_block_at_world_position(world_x, world_y)
            hovered_id = hovered_block.get("id") if hovered_block else None

            self.hover_part_id = hovered_id
            self.hover_screen_pos = screen_pos if hovered_block else None
            self.design.set_hover_component(hovered_id)
            return

        world_x, world_y = camera.screen_to_world(screen_pos)
        hovered_block = self._interior_block_at_world_position(world_x, world_y)
        hovered_id = hovered_block.get("id") if hovered_block else None

        self.hover_part_id = hovered_id
        self.hover_screen_pos = screen_pos if hovered_block else None

    def handle_pointer_event(self, event, camera, screen_pos):
        if self.active_view_mode == self.VIEW_DESIGN:
            world_x, world_y = camera.screen_to_world(screen_pos)

            clicked_block = self._design_block_at_world_position(world_x, world_y)
            if clicked_block:
                clicked_id = clicked_block.get("id")
                self.selected_part_id = clicked_id
                self.design.set_selected_component(clicked_id)
                self.hover_screen_pos = screen_pos
                return

            placed_id = self.design.place_active_catalog_component_at_world_position(
                self.vehicle.get("position", {}),
                world_x,
                world_y,
            )
            if placed_id:
                self.selected_part_id = placed_id
                self.design.set_selected_component(placed_id)
                self.hover_screen_pos = screen_pos
                return

            moved = self.design.move_selected_component_to_world_position(
                self.vehicle.get("position", {}),
                world_x,
                world_y,
            )
            if moved:
                self.hover_screen_pos = screen_pos
                return

            return

        world_x, world_y = camera.screen_to_world(screen_pos)
        clicked_block = self._interior_block_at_world_position(world_x, world_y)
        clicked_id = clicked_block.get("id") if clicked_block else None

        self.selected_part_id = clicked_id
        self.hover_screen_pos = screen_pos if clicked_block else None