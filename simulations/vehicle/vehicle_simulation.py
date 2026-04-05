from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.vehicle.vehicle_design import VehicleDesignController
import pygame

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
    * physical vehicle dimensions and catalog loaded from repository entities
    * 100 m x 100 m prototype vehicle map for scale testing
    * basic design-window catalog selection and component placement
    """

    VIEW_DESIGN = "design"
    VIEW_INTERIOR = "interior"
    VIEW_OPERATIONAL = "operational"

    TEST_MAP_SIZE_X_M = 100.0
    TEST_MAP_SIZE_Y_M = 100.0

    def __init__(self, world_model=None, vehicle_entity_id="veh_test_rig_01"):
        class _DummySystem:
            def update(self, dt):
                pass

        self.world_model = world_model
        self.vehicle_entity_id = vehicle_entity_id

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

        self.vehicle = self._build_vehicle_state_from_entity()
        self.design = VehicleDesignController(
            world_model=self.world_model,
            vehicle_entity=self.vehicle.get("_entity"),
        )

        self.hover_part_id = None
        self.selected_part_id = None
        self.hover_screen_pos = None

    def _get_vehicle_entity(self):
        if self.world_model is None:
            return None
        return self.world_model.get_entity(self.vehicle_entity_id)

    def _build_vehicle_state_from_entity(self):
        entity = self._get_vehicle_entity()

        if entity is None:
            return {
                "id": self.vehicle_entity_id,
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
                "_entity": None,
            }

        return {
            "id": entity.get("id", self.vehicle_entity_id),
            "name": entity.get("name", self.vehicle_entity_id),
            "vehicle_class": entity.get("vehicle_class", "vehicle"),
            "manufacturer": entity.get("manufacturer_name", entity.get("manufacturer", "Unknown")),
            "position": {
                "x": self.TEST_MAP_SIZE_X_M / 2.0,
                "y": self.TEST_MAP_SIZE_Y_M / 2.0,
            },
            "interior_layout": entity.get("interior_layout", []),
            "operational_state": entity.get(
                "operational_state",
                {
                    "speed_kph": 38,
                    "heading_deg": 90,
                    "power_state": "nominal",
                    "crew_state": "ready",
                    "task_state": "idle test state",
                    "range_km": 420,
                },
            ),
            "_entity": entity,
        }

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

    def begin_design_catalog_drag(self, catalog_id):
        """
        Start dragging a catalog component from the vehicle design UI catalog.
        """
        if self.active_view_mode != self.VIEW_DESIGN:
            return False

        started = self.design.begin_catalog_drag(catalog_id)
        if not started:
            return False

        self.selected_part_id = None
        self.design.set_selected_component(None)
        self.hover_screen_pos = None
        return True

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
        payload["drag_preview_block"] = design_payload["drag_preview_block"]
        payload["component_catalog"] = design_payload["component_catalog"]
        payload["grouped_component_catalog"] = design_payload["grouped_component_catalog"]
        payload["catalog_panel_rect"] = design_payload["catalog_panel_rect"]
        payload["catalog_entry_rects"] = design_payload["catalog_entry_rects"]
        payload["active_catalog_component_id"] = design_payload["active_catalog_component_id"]
        payload["hover_catalog_component_id"] = design_payload["hover_catalog_component_id"]
        payload["dragging_component_id"] = design_payload["dragging_component_id"]
        payload["dragging_catalog_component_id"] = design_payload["dragging_catalog_component_id"]
        payload["requirement_status"] = design_payload["requirement_status"]
        return payload

    def _build_interior_payload(self, payload):
        payload["base_rect"] = self.get_mode_base_rect()
        payload["blocks"] = self.get_mode_blocks()
        return payload

    def _infer_operational_group(self, component):
        text = " ".join(
            str(component.get(key, ""))
            for key in ("component_type", "label", "catalog_id")
        ).lower()

        if any(token in text for token in ("engine", "motor", "reactor", "battery", "power", "fuel")):
            return "Powertrain"

        if any(token in text for token in ("cockpit", "driver", "crew", "control", "avionics", "bridge")):
            return "Crew & Control"

        if any(token in text for token in ("cargo", "bay", "storage", "hold", "luggage")):
            return "Cargo"

        if any(token in text for token in ("wheel", "track", "landing", "gear", "suspension", "drive")):
            return "Mobility"

        if any(token in text for token in ("sensor", "radar", "antenna", "comm", "target")):
            return "Sensors & Comms"

        if any(token in text for token in ("gun", "missile", "weapon", "turret", "cannon")):
            return "Weapons"

        return "General Systems"

    def _operational_status_text_for_group(self, group_name, operational_state):
        if group_name == "Powertrain":
            return f"power: {operational_state.get('power_state', 'unknown')}"

        if group_name == "Crew & Control":
            return f"crew: {operational_state.get('crew_state', 'unknown')}"

        if group_name == "Cargo":
            return f"task: {operational_state.get('task_state', 'unknown')}"

        if group_name == "Mobility":
            speed = operational_state.get("speed_kph", "?")
            return f"speed: {speed} kph"

        if group_name == "Sensors & Comms":
            heading = operational_state.get("heading_deg", "?")
            return f"heading: {heading} deg"

        if group_name == "Weapons":
            return f"task: {operational_state.get('task_state', 'unknown')}"

        return f"power: {operational_state.get('power_state', 'unknown')}"

    def _build_operational_modules(self):
        base_rect = self.get_mode_base_rect()
        system_summary = self.design.get_operational_system_summary()

        modules = []
        if not system_summary:
            return modules

        hull_width = max(1.0, base_rect["width"])
        hull_height = max(1.0, base_rect["height"])

        padding_x = max(0.15, hull_width * 0.04)
        padding_y = max(0.08, hull_height * 0.08)
        gap_y = max(0.04, hull_height * 0.04)

        usable_width = max(0.2, hull_width - padding_x * 2.0)
        start_x = base_rect["x"] + padding_x
        start_y = base_rect["y"] + padding_y

        row_unit = max(0.18, hull_height * 0.09)
        module_heights = []
        for summary in system_summary:
            child_count = max(1, len(summary.get("children", [])))
            module_heights.append(row_unit * (2 + child_count))

        total_height = sum(module_heights) + gap_y * max(0, len(module_heights) - 1)
        if total_height > max(0.2, hull_height - padding_y * 2.0):
            scale = max(0.25, (hull_height - padding_y * 2.0) / total_height)
            module_heights = [max(0.14, value * scale) for value in module_heights]
            gap_y = max(0.02, gap_y * scale)

        current_y = start_y

        for summary, module_height in zip(system_summary, module_heights):
            status = summary.get("status", "missing")
            component_labels = list(summary.get("component_labels", []))

            if component_labels:
                component_text = ", ".join(component_labels[:3])
                if len(component_labels) > 3:
                    component_text += " ..."
            else:
                component_text = "no installed components"

            modules.append(
                {
                    "id": f"operational_{summary.get('group', 'system').lower().replace(' ', '_').replace('&', 'and')}",
                    "label": f"{summary.get('group', 'System')} Module",
                    "group": summary.get("group", "General Systems"),
                    "component_label": component_text,
                    "component_type": "operational_group",
                    "catalog_id": None,
                    "status": status,
                    "status_text": status,
                    "children": summary.get("children", []),
                    "x": start_x,
                    "y": current_y,
                    "width": usable_width,
                    "height": module_height,
                }
            )

            current_y += module_height + gap_y

        return modules

    def _operational_module_at_world_position(self, world_x, world_y):
        for module in reversed(self._build_operational_modules()):
            module_min_x = module["x"]
            module_max_x = module["x"] + module["width"]
            module_min_y = module["y"]
            module_max_y = module["y"] + module["height"]

            if module_min_x <= world_x <= module_max_x and module_min_y <= world_y <= module_max_y:
                return module

        return None

    def _build_operational_payload(self, payload):
        payload["base_rect"] = self.get_mode_base_rect()
        payload["operational_state"] = self.vehicle.get("operational_state", {})
        payload["operational_modules"] = self._build_operational_modules()
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
                    "role_summary": self.vehicle.get("vehicle_class", "vehicle"),
                }
            )
            return base_payload

        if consumer_type == "producer":
            base_payload.update(
                {
                    "manufacturer": self.vehicle.get("manufacturer"),
                    "design_component_count": len(self.design.get_placed_components()),
                    "interior_block_count": len(self.vehicle.get("interior_layout", [])),
                    "production_summary": "repository-backed prototype shell",
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
            catalog_id = self.design.get_catalog_entry_at_screen_position(screen_pos)
            self.design.set_hover_catalog_component(catalog_id)

            world_x, world_y = camera.screen_to_world(screen_pos)

            self.design.update_drag(
                self.vehicle.get("position", {}),
                world_x,
                world_y,
            )

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
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                catalog_id = self.design.get_catalog_entry_at_screen_position(screen_pos)
                if catalog_id:
                    self.design.begin_catalog_drag(catalog_id)
                    self.selected_part_id = None
                    self.design.set_selected_component(None)
                    self.hover_screen_pos = screen_pos
                    return

                world_x, world_y = camera.screen_to_world(screen_pos)
                clicked_block = self._design_block_at_world_position(world_x, world_y)
                if clicked_block:
                    clicked_id = clicked_block.get("id")
                    self.selected_part_id = clicked_id
                    self.design.set_selected_component(clicked_id)
                    self.design.begin_component_drag(
                        self.vehicle.get("position", {}),
                        clicked_id,
                        world_x,
                        world_y,
                    )
                    self.hover_screen_pos = screen_pos
                    return

                self.selected_part_id = None
                self.design.set_selected_component(None)
                self.design.cancel_drag()
                self.hover_screen_pos = None
                return

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                world_x, world_y = camera.screen_to_world(screen_pos)
                ended_id = self.design.end_drag(
                    self.vehicle.get("position", {}),
                    world_x,
                    world_y,
                )
                self.selected_part_id = ended_id
                self.design.set_selected_component(ended_id)
                self.hover_screen_pos = screen_pos if ended_id else None
                return

            return

        world_x, world_y = camera.screen_to_world(screen_pos)
        clicked_block = self._interior_block_at_world_position(world_x, world_y)
        clicked_id = clicked_block.get("id") if clicked_block else None

        self.selected_part_id = clicked_id
        self.hover_screen_pos = screen_pos if clicked_block else None