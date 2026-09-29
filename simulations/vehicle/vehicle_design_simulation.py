from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.vehicle.vehicle_design import VehicleDesignController
from ui.pixel_art_editor_ui import PixelArtEditorUI
import copy
import pygame

class VehicleDesignSimulation:
    """
    Prototype vehicle design simulation.

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

    This is the design/catalog/prototype workspace for a vehicle entity, not a
    runtime individual vehicle. See simulations/vehicle/vehicle_simulation.py
    for the embedded runtime VehicleSimulation used by SiteSimulation.
    """

    VIEW_DESIGN = "design"
    VIEW_INTERIOR = "interior"
    VIEW_OPERATIONAL = "operational"

    DESIGN_STEP_SPECIFICATIONS = "specifications"
    DESIGN_STEP_HULL = "hull"
    DESIGN_STEP_COMPONENTS = "components"
    DESIGN_STEP_DETAILS = "details"
    DESIGN_STEP_LIVERIES = "liveries"

    SYSTEMS_VIEW_LAYOUT = "layout"
    SYSTEMS_VIEW_DIAGRAM = "diagram"

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
        self.design_step = self.DESIGN_STEP_SPECIFICATIONS
        self.systems_view_mode = self.SYSTEMS_VIEW_LAYOUT
        self._diagram_node_rects = {}
        self._diagram_port_rects = {}
        self.hull_tool = "draw"
        self.hull_brush_radius = 0
        self.selected_hull_view_id = "right"
        self.hull_focus_mode = False
        self.pixel_tool = "draw"
        self.pixel_color = "#d7dde8"
        self.pixel_brush_radius = 0
        self.show_paint_components = True
        self.livery_clipboard = None
        self._livery_list_hitboxes = []
        self._specification_hitboxes = []
        self.specification_active_cell = None
        self.specification_selected_row = None
        self.specification_page_offsets = {"characteristic": 0, "requirement": 0}
        self._orthographic_view_rects = {}
        self._hull_painting = False
        self._active_orthographic_drag = None

        # Pixel Studio can be embedded by simulations as well as by the
        # repository's Illustration cards. The controller deliberately keeps
        # its state on the host so both entry points use the identical editor.
        self.pixel_art_editor = None
        self.pixel_art_painting = False
        self.pixel_art_editor_ui = PixelArtEditorUI(self)
        self.layout = None
        self.LINE_HEIGHT = 20

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

    @staticmethod
    def _ellipsize_text(text, font, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        suffix = "…"
        while text and font.size(text + suffix)[0] > max_width:
            text = text[:-1]
        return text + suffix

    @staticmethod
    def _pixel_color(value):
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            return tuple(max(0, min(255, int(channel))) for channel in value[:3])
        text = str(value or "").strip()
        if len(text) == 7 and text.startswith("#"):
            try:
                return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))
            except ValueError:
                return None
        return None

    def _component_reference_pixels(self, view_id, width, height):
        pixels = [[None for _ in range(width)] for _ in range(height)]
        view = self.design.ORTHOGRAPHIC_VIEWS[view_id]
        axis_u, axis_v = view["axes"]
        dims = self.design.vehicle_dimensions_m
        for block in self.design.get_orthographic_component_blocks(view_id):
            u = float(block.get("u", 0.0)) / max(0.01, float(dims.get(axis_u, 1.0)))
            v = float(block.get("v", 0.0)) / max(0.01, float(dims.get(axis_v, 1.0)))
            half_w = float(block.get("width", 1.0)) / max(0.01, float(dims.get(axis_u, 1.0))) / 2.0
            half_h = float(block.get("height", 1.0)) / max(0.01, float(dims.get(axis_v, 1.0))) / 2.0
            if view.get("flip_x"):
                u = 1.0 - u
            x1 = max(0, min(width - 1, round((u - half_w) * (width - 1))))
            x2 = max(0, min(width - 1, round((u + half_w) * (width - 1))))
            y1 = max(0, min(height - 1, round((1.0 - v - half_h) * (height - 1))))
            y2 = max(0, min(height - 1, round((1.0 - v + half_h) * (height - 1))))
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            color = (105, 196, 221)
            for x in range(x1, x2 + 1):
                pixels[y1][x] = color
                pixels[y2][x] = color
            for y in range(y1, y2 + 1):
                pixels[y][x1] = color
                pixels[y][x2] = color
        return pixels

    def _opposite_reference_pixels(self, step, view_id, width, height):
        opposite_id = self.design.ORTHOGRAPHIC_VIEWS[view_id]["opposite"]
        source = self.design.get_paint_layer(step, opposite_id)
        source_height = len(source)
        source_width = len(source[0]) if source_height else 0
        pixels = [[None for _ in range(width)] for _ in range(height)]
        if not source_width or not source_height:
            return pixels
        for y in range(height):
            source_y = min(source_height - 1, int(y * source_height / height))
            for x in range(width):
                source_x = min(source_width - 1, int((width - 1 - x) * source_width / width))
                pixels[y][x] = self._pixel_color(source[source_y][source_x])
        return pixels

    def _pixel_studio_views(self, step):
        views = {}
        masks = {}
        for view_id in ("left", "right", "front", "rear", "top", "bottom"):
            definition = self.design.ORTHOGRAPHIC_VIEWS[view_id]
            source = self.design.get_paint_layer(step, view_id)
            height = len(source)
            width = len(source[0]) if height else 1
            artwork = [
                [self._pixel_color(value) for value in row]
                for row in source
            ]
            views[view_id] = {
                "name": definition.get("label", view_id.title()),
                "width": width,
                "height": max(1, height),
                "active_layer": 0,
                "layers": [
                    {"name": "Structural details" if step == "details" else "Livery paint", "visible": True, "opacity": 1.0, "pixels": artwork},
                    {"name": "Opposite-side guide", "visible": True, "opacity": 0.22, "reference_only": True, "locked": True,
                     "pixels": self._opposite_reference_pixels(step, view_id, width, max(1, height))},
                    {"name": "Components guide", "visible": bool(self.show_paint_components), "opacity": 0.18, "reference_only": True, "locked": True,
                     "pixels": self._component_reference_pixels(view_id, width, max(1, height))},
                ],
            }
            masks[view_id] = self.design.get_paint_mask(step, view_id)
        return views, masks

    def _apply_pixel_studio_views(self, step, views, masks):
        target_by_view = self.design.detail_layers if step == "details" else next(
            (item.get("layers") for item in self.design.liveries if item.get("id") == self.design.active_livery_id),
            None,
        )
        if not isinstance(target_by_view, dict):
            return False
        for view_id, view in views.items():
            width, height = int(view.get("width") or 0), int(view.get("height") or 0)
            mask = masks.get(view_id) or []
            output = [[None for _ in range(width)] for _ in range(height)]
            for layer in view.get("layers") or []:
                if not layer.get("visible", True) or layer.get("reference_only"):
                    continue
                opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0))))
                for y, row in enumerate((layer.get("pixels") or [])[:height]):
                    for x, value in enumerate(row[:width]):
                        if not (y < len(mask) and x < len(mask[y]) and mask[y][x]):
                            continue
                        color = self._pixel_color(value)
                        if color is None:
                            continue
                        previous = self._pixel_color(output[y][x])
                        if previous is not None and opacity < 1.0:
                            color = tuple(round(previous[i] * (1.0 - opacity) + color[i] * opacity) for i in range(3))
                        output[y][x] = "#{:02x}{:02x}{:02x}".format(*color)
            target_by_view[view_id] = output
        self.design.paint_revision += 1
        self._persist_design_state()
        return True

    def _open_pixel_studio(self, step):
        views, masks = self._pixel_studio_views(step)
        title = f"{self.get_vehicle_name()} · {'Structural Details' if step == 'details' else 'Liveries'}"

        def apply_views(updated_views, updated_masks):
            return self._apply_pixel_studio_views(step, updated_views, updated_masks)

        def return_to_components(_saved):
            self.design_step = self.DESIGN_STEP_COMPONENTS
            self.design.cancel_drag()
            self._active_orthographic_drag = None

        return self.pixel_art_editor_ui.open_embedded(
            title=title,
            views=views,
            active_view=self.selected_hull_view_id,
            masks=masks,
            on_save=apply_views,
            on_close=return_to_components,
            finish_on_save=True,
        )

    def is_vehicle_pixel_editor_active(self):
        return isinstance(self.pixel_art_editor, dict) and bool(self.pixel_art_editor.get("embedded"))

    def consumes_global_keydown(self):
        return self.is_vehicle_pixel_editor_active()

    def handle_event(self, event):
        if self.is_vehicle_pixel_editor_active() and event.type == pygame.KEYDOWN:
            return self.pixel_art_editor_ui.handle_keydown(event)
        return False

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

    def _is_space_station(self):
        entity = self.vehicle.get("_entity")
        return bool(
            isinstance(entity, dict)
            and entity.get("location_class") in {"space_station", "station"}
        )

    def get_vehicle_dimensions_m(self):
        return self.design.get_vehicle_dimensions_m()

    def _persist_design_state(self):
        entity = self._get_vehicle_entity()
        if not isinstance(entity, dict):
            return False
        installed_components = self.design.get_placed_components()
        if self.world_model is not None and hasattr(self.world_model, "set_literal"):
            changed = False
            for field_name, field_value in (
                *tuple(self.design.specification_metadata.items()),
                ("dimension_length_m", self.design.vehicle_dimensions_m["x"]),
                ("dimension_width_m", self.design.vehicle_dimensions_m["y"]),
                ("dimension_height_m", self.design.vehicle_dimensions_m["z"]),
                ("hull_silhouettes", self.design.get_hull_silhouettes()),
                ("vehicle_detail_layers", self.design.detail_layers),
                ("vehicle_liveries", self.design.liveries),
                ("vehicle_specifications", self.design.vehicle_specifications),
                ("design_requirements", self.design.design_requirements),
                ("structural_features", self.design.structural_features),
                ("manual_routes", self.design.manual_routes),
            ):
                changed = bool(self.world_model.set_literal(self.vehicle_entity_id, field_name, field_value)) or changed
            changed = bool(self.world_model.set_literal(
                self.vehicle_entity_id,
                "installed_components",
                installed_components,
            )) or changed
            return bool(changed)
        entity["installed_components"] = installed_components
        entity["dimension_length_m"] = self.design.vehicle_dimensions_m["x"]
        entity["dimension_width_m"] = self.design.vehicle_dimensions_m["y"]
        entity["dimension_height_m"] = self.design.vehicle_dimensions_m["z"]
        entity["hull_silhouettes"] = self.design.get_hull_silhouettes()
        entity["vehicle_detail_layers"] = self.design.detail_layers
        entity["vehicle_liveries"] = self.design.liveries
        entity.update(self.design.specification_metadata)
        entity["vehicle_specifications"] = copy.deepcopy(self.design.vehicle_specifications)
        entity["design_requirements"] = copy.deepcopy(self.design.design_requirements)
        entity["structural_features"] = copy.deepcopy(self.design.structural_features)
        entity["manual_routes"] = copy.deepcopy(self.design.manual_routes)
        if self.world_model is not None and hasattr(self.world_model, "mark_repository_changed"):
            self.world_model.mark_repository_changed()
        return True

    def get_active_mode_label(self):
        mode_labels = {
            self.VIEW_DESIGN: "Station Design" if self._is_space_station() else "Vehicle Design",
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
        payload["system_diagram"] = design_payload["system_diagram"]
        payload["orthographic_views"] = design_payload["orthographic_views"]
        payload["design_step"] = self.design_step
        payload["systems_view_mode"] = self.systems_view_mode
        payload["hull_tool"] = self.hull_tool
        payload["selected_hull_view_id"] = self.selected_hull_view_id
        payload["hull_focus_mode"] = self.hull_focus_mode
        payload["pixel_tool"] = self.pixel_tool
        payload["pixel_color"] = self.pixel_color
        payload["pixel_brush_radius"] = self.pixel_brush_radius
        payload["show_paint_components"] = self.show_paint_components
        payload["detail_layers"] = self.design.detail_layers
        payload["liveries"] = self.design.get_livery_summaries()
        payload["active_livery_id"] = self.design.active_livery_id
        payload["active_livery_layers"] = {
            view_id: self.design.get_paint_layer("liveries", view_id)
            for view_id in self.design.ORTHOGRAPHIC_VIEWS
        }
        payload["paint_revision"] = self.design.paint_revision
        payload["livery_resolution"] = {
            view_id: self.design._paint_grid_size("liveries", view_id)
            for view_id in self.design.ORTHOGRAPHIC_VIEWS
        }
        payload["specifications"] = self.design.get_specification_payload()
        payload["specification_active_cell"] = self.specification_active_cell
        payload["specification_selected_row"] = self.specification_selected_row
        payload["specification_page_offsets"] = dict(self.specification_page_offsets)
        return payload

    def set_orthographic_view_rects(self, rects):
        self._orthographic_view_rects = dict(rects or {})

    def set_systems_view_mode(self, mode):
        if mode not in {self.SYSTEMS_VIEW_LAYOUT, self.SYSTEMS_VIEW_DIAGRAM}:
            return False
        if self.design_step != self.DESIGN_STEP_COMPONENTS:
            return False
        self.systems_view_mode = mode
        self.selected_part_id = None
        self.design.set_selected_component(None)
        return True

    def toggle_systems_view_mode(self):
        target = (
            self.SYSTEMS_VIEW_DIAGRAM if self.systems_view_mode == self.SYSTEMS_VIEW_LAYOUT
            else self.SYSTEMS_VIEW_LAYOUT
        )
        return self.set_systems_view_mode(target)

    def set_diagram_node_rects(self, rects):
        self._diagram_node_rects = dict(rects or {})

    def set_diagram_port_rects(self, rects):
        self._diagram_port_rects = dict(rects or {})

    def _diagram_node_at_screen_position(self, screen_pos):
        for node_id, rect in self._diagram_node_rects.items():
            if rect.collidepoint(screen_pos):
                return node_id
        return None

    def _diagram_port_at_screen_position(self, screen_pos):
        for key, rect in self._diagram_port_rects.items():
            if rect.collidepoint(screen_pos):
                return key
        return None

    def _handle_diagram_pointer_event(self, event, screen_pos):
        if event.type != pygame.MOUSEBUTTONDOWN:
            return

        if event.button == 1:
            port_key = self._diagram_port_at_screen_position(screen_pos)
            if port_key is not None:
                direction, instance_id, port_id = port_key
                if direction == "input":
                    self.design.cycle_input_port_route(instance_id, port_id)
                    self._persist_design_state()
                return

            node_id = self._diagram_node_at_screen_position(screen_pos)
            if node_id is not None:
                if self.selected_part_id and self.selected_part_id != node_id:
                    catalog_id = self.design.get_catalog_entry_at_screen_position(screen_pos)
                    if catalog_id:
                        if self.design.install_component_in_slot(self.selected_part_id, catalog_id):
                            self._persist_design_state()
                        return
                self.selected_part_id = node_id
                self.design.set_selected_component(node_id)
                return

            catalog_id = self.design.get_catalog_entry_at_screen_position(screen_pos)
            if catalog_id and self.selected_part_id:
                if self.design.install_component_in_slot(self.selected_part_id, catalog_id):
                    self._persist_design_state()
                return

            self.selected_part_id = None
            self.design.set_selected_component(None)
            return

        if event.button == 3:
            node_id = self._diagram_node_at_screen_position(screen_pos)
            if node_id is not None and self.design.uninstall_component_from_slot(node_id):
                self._persist_design_state()

    def set_livery_list_hitboxes(self, hitboxes):
        self._livery_list_hitboxes = list(hitboxes or [])

    def set_specification_hitboxes(self, hitboxes):
        self._specification_hitboxes = list(hitboxes or [])

    def add_specification_row(self, row_kind):
        row_id = self.design.add_specification_row(row_kind)
        if row_id is None:
            return False
        self.specification_selected_row = (row_kind, row_id)
        self.specification_active_cell = (row_kind, row_id, "label")
        rows = self.design.vehicle_specifications if row_kind == "characteristic" else self.design.design_requirements
        self.specification_page_offsets[row_kind] = max(0, len(rows) - 5)
        return True

    def page_specification_rows(self, row_kind, delta):
        if row_kind not in self.specification_page_offsets:
            return False
        rows = self.design.vehicle_specifications if row_kind == "characteristic" else self.design.design_requirements
        current = self.specification_page_offsets[row_kind]
        updated = max(0, min(max(0, len(rows) - 1), current + int(delta) * 5))
        if updated == current:
            return False
        self.specification_page_offsets[row_kind] = updated
        self.specification_active_cell = None
        return True

    def remove_selected_specification_row(self):
        if not self.specification_selected_row:
            return False
        row_kind, row_id = self.specification_selected_row
        changed = self.design.remove_specification_row(row_kind, row_id)
        if changed:
            self.specification_selected_row = None
            self.specification_active_cell = None
            self._persist_design_state()
        return changed

    def finish_specifications(self):
        self._persist_design_state()
        return self.set_design_step(self.DESIGN_STEP_HULL)

    def handle_specification_key(self, event):
        if self.active_view_mode != self.VIEW_DESIGN or self.design_step != self.DESIGN_STEP_SPECIFICATIONS:
            return False
        if event.type != pygame.KEYDOWN or not self.specification_active_cell:
            return False
        row_kind, row_id, field_name = self.specification_active_cell
        payload = self.design.get_specification_payload()
        if row_kind == "metadata":
            current = payload["metadata"].get(field_name, "")
        else:
            collection = payload["characteristics" if row_kind == "characteristic" else "requirements"]
            row = next((item for item in collection if item.get("id") == row_id), None)
            if row is None:
                return True
            current = row.get(field_name, "")
        if event.key == pygame.K_ESCAPE:
            self.specification_active_cell = None
            return True
        if event.key in {pygame.K_RETURN, pygame.K_KP_ENTER}:
            self._persist_design_state()
            self.specification_active_cell = None
            return True
        if event.key == pygame.K_TAB:
            cells = [(kind, item_id, field) for kind, item_id, field, _rect in self._specification_hitboxes]
            if cells:
                try:
                    index = cells.index(self.specification_active_cell)
                except ValueError:
                    index = -1
                direction = -1 if event.mod & pygame.KMOD_SHIFT else 1
                self.specification_active_cell = cells[(index + direction) % len(cells)]
            return True
        if event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
            updated = ""
        elif event.key == pygame.K_BACKSPACE:
            updated = current[:-1]
        elif event.key == pygame.K_DELETE:
            updated = ""
        elif event.unicode and event.unicode.isprintable():
            updated = current + event.unicode
        else:
            return True
        self.design.update_specification_value(row_kind, row_id, field_name, updated)
        if row_kind == "metadata":
            if isinstance(self.design.vehicle_entity, dict):
                self.design.vehicle_entity[field_name] = updated
            if field_name == "name":
                self.vehicle["name"] = updated
            elif field_name == "vehicle_class":
                self.vehicle["vehicle_class"] = updated
            elif field_name == "manufacturer_name":
                self.vehicle["manufacturer"] = updated
        return True

    def set_design_step(self, step):
        if step not in {
            self.DESIGN_STEP_SPECIFICATIONS,
            self.DESIGN_STEP_HULL,
            self.DESIGN_STEP_COMPONENTS,
            self.DESIGN_STEP_DETAILS,
            self.DESIGN_STEP_LIVERIES,
        }:
            return False
        if self.design_step == self.DESIGN_STEP_SPECIFICATIONS and step != self.DESIGN_STEP_SPECIFICATIONS:
            self._persist_design_state()
        self.design_step = step
        self.design.cancel_drag()
        self._active_orthographic_drag = None
        self._hull_painting = False
        if step != self.DESIGN_STEP_HULL:
            self.hull_focus_mode = False
        return True

    def enter_paint_screen(self, step):
        if step not in {self.DESIGN_STEP_DETAILS, self.DESIGN_STEP_LIVERIES}:
            return False
        self.design_step = step
        self.hull_focus_mode = False
        self._hull_painting = False
        return self._open_pixel_studio(step)

    def finish_paint_screen(self):
        if self.is_vehicle_pixel_editor_active():
            return self.pixel_art_editor_ui.save()
        if self.design_step not in {self.DESIGN_STEP_DETAILS, self.DESIGN_STEP_LIVERIES}:
            return False
        self._persist_design_state()
        return self.set_design_step(self.DESIGN_STEP_COMPONENTS)

    def select_paint_view(self, view_id):
        if view_id not in self.design.ORTHOGRAPHIC_VIEWS:
            return False
        self.selected_hull_view_id = view_id
        return True

    def set_pixel_tool(self, tool):
        if tool not in {"draw", "erase", "pick"}:
            return False
        self.pixel_tool = tool
        return True

    def set_pixel_color(self, color):
        color = str(color or "").strip().lower()
        if len(color) != 7 or not color.startswith("#"):
            return False
        try:
            int(color[1:], 16)
        except ValueError:
            return False
        self.pixel_color = color
        self.pixel_tool = "draw"
        return True

    def adjust_pixel_brush(self, delta):
        maximum = 15 if self.design_step == self.DESIGN_STEP_LIVERIES else 4
        self.pixel_brush_radius = max(0, min(maximum, self.pixel_brush_radius + int(delta)))
        return True

    def toggle_paint_components(self):
        self.show_paint_components = not self.show_paint_components
        return True

    def copy_active_livery(self):
        copied = self.design.copy_active_livery()
        if copied is None:
            return False
        self.livery_clipboard = copied
        return True

    def paste_livery(self):
        pasted_id = self.design.paste_livery(self.livery_clipboard)
        if pasted_id:
            self._persist_design_state()
        return bool(pasted_id)

    def select_livery(self, livery_id):
        return self.design.select_livery(livery_id)

    def toggle_hull_focus_mode(self):
        if self.design_step != self.DESIGN_STEP_HULL:
            return False
        if self.selected_hull_view_id not in self.design.ORTHOGRAPHIC_VIEWS:
            self.selected_hull_view_id = "right"
        self.hull_focus_mode = not self.hull_focus_mode
        self._hull_painting = False
        return True

    def adjust_vehicle_dimension(self, axis, delta):
        current = self.design.vehicle_dimensions_m.get(axis)
        if current is None:
            return False
        changed = self.design.set_vehicle_dimension_m(axis, current + float(delta))
        if changed:
            self._persist_design_state()
        return changed

    def set_hull_tool(self, tool):
        if tool not in {"draw", "erase"}:
            return False
        self.hull_tool = tool
        return True

    def clear_hull(self):
        self.design.clear_hull_silhouettes()
        self._persist_design_state()
        return True

    def _orthographic_hit(self, screen_pos):
        for view_id, rect in self._orthographic_view_rects.items():
            if rect.collidepoint(screen_pos):
                view = self.design.ORTHOGRAPHIC_VIEWS[view_id]
                inner = rect.inflate(-12, -28)
                if inner.width <= 0 or inner.height <= 0:
                    return None
                rel_x = max(0.0, min(1.0, (screen_pos[0] - inner.x) / max(1, inner.width)))
                rel_y = max(0.0, min(1.0, (screen_pos[1] - inner.y) / max(1, inner.height)))
                if view.get("flip_x"):
                    rel_x = 1.0 - rel_x
                axis_u, axis_v = view["axes"]
                return {
                    "view_id": view_id,
                    "rect": rect,
                    "inner": inner,
                    "u_fraction": rel_x,
                    "v_fraction": 1.0 - rel_y,
                    "u": rel_x * self.design.vehicle_dimensions_m[axis_u],
                    "v": (1.0 - rel_y) * self.design.vehicle_dimensions_m[axis_v],
                    "axes": view["axes"],
                }
        return None

    def _paint_hull_at_screen(self, screen_pos):
        hit = self._orthographic_hit(screen_pos)
        if hit is None:
            return False
        grid = self.design.hull_silhouettes.get(hit["view_id"], [])
        if not grid:
            return False
        column = min(len(grid[0]) - 1, int(hit["u_fraction"] * len(grid[0])))
        row = min(len(grid) - 1, int((1.0 - hit["v_fraction"]) * len(grid)))
        return self.design.paint_hull_cell(
            hit["view_id"], column, row,
            filled=self.hull_tool == "draw",
            brush_radius=self.hull_brush_radius,
        )

    def _paint_color_at_screen(self, screen_pos):
        hit = self._orthographic_hit(screen_pos)
        if hit is None:
            return False
        layer_kind = self.design_step
        layer = self.design.get_paint_layer(layer_kind, hit["view_id"])
        if not layer:
            return False
        column = min(len(layer[0]) - 1, int(hit["u_fraction"] * len(layer[0])))
        row = min(len(layer) - 1, int((1.0 - hit["v_fraction"]) * len(layer)))
        if self.pixel_tool == "pick":
            value = layer[row][column]
            if value:
                self.pixel_color = str(value)
                self.pixel_tool = "draw"
                return True
            return False
        color = None if self.pixel_tool == "erase" else self.pixel_color
        return self.design.paint_color_cell(
            layer_kind, hit["view_id"], column, row, color,
            brush_radius=self.pixel_brush_radius,
        )

    def _component_at_orthographic_hit(self, hit):
        blocks = self.design.get_orthographic_component_blocks(hit["view_id"])
        for block in reversed(blocks):
            if (abs(hit["u"] - block["u"]) <= max(0.35, block["width"] / 2.0)
                    and abs(hit["v"] - block["v"]) <= max(0.35, block["height"] / 2.0)):
                return block
        return None

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
            if self.design_step in {self.DESIGN_STEP_DETAILS, self.DESIGN_STEP_LIVERIES}:
                if self._hull_painting:
                    self._paint_color_at_screen(screen_pos)
                return
            if self.design_step == self.DESIGN_STEP_HULL:
                if self._hull_painting:
                    self._paint_hull_at_screen(screen_pos)
                return

            hit = self._orthographic_hit(screen_pos)
            if self._active_orthographic_drag and hit is not None:
                axis = self._active_orthographic_drag["axis"]
                if axis in hit["axes"]:
                    axis_index = hit["axes"].index(axis)
                    self.design.move_component_axis(
                        self._active_orthographic_drag["component_id"],
                        axis,
                        hit["u"] if axis_index == 0 else hit["v"],
                    )
                return
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
            if self.design_step == self.DESIGN_STEP_SPECIFICATIONS:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for row_kind, row_id, field_name, rect in self._specification_hitboxes:
                        if rect.collidepoint(screen_pos):
                            self.specification_active_cell = (row_kind, row_id, field_name)
                            self.specification_selected_row = None if row_kind == "metadata" else (row_kind, row_id)
                            return
                    if self.specification_active_cell is not None:
                        self._persist_design_state()
                    self.specification_active_cell = None
                return
            if self.design_step == self.DESIGN_STEP_COMPONENTS and self.systems_view_mode == self.SYSTEMS_VIEW_DIAGRAM:
                self._handle_diagram_pointer_event(event, screen_pos)
                return
            if self.design_step in {self.DESIGN_STEP_DETAILS, self.DESIGN_STEP_LIVERIES}:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.design_step == self.DESIGN_STEP_LIVERIES:
                        for livery_id, rect in self._livery_list_hitboxes:
                            if rect.collidepoint(screen_pos):
                                self.design.select_livery(livery_id)
                                return
                    hit = self._orthographic_hit(screen_pos)
                    if hit is not None:
                        self.selected_hull_view_id = hit["view_id"]
                        self._hull_painting = True
                        self._paint_color_at_screen(screen_pos)
                    return
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    self.pixel_tool = "erase"
                    self._hull_painting = self._orthographic_hit(screen_pos) is not None
                    if self._hull_painting:
                        self._paint_color_at_screen(screen_pos)
                    return
                if event.type == pygame.MOUSEBUTTONUP and event.button in {1, 3}:
                    if self._hull_painting:
                        self._persist_design_state()
                    self._hull_painting = False
                    return
                return
            if self.design_step == self.DESIGN_STEP_HULL:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button in {1, 3}:
                    hit = self._orthographic_hit(screen_pos)
                    if hit is not None:
                        self.selected_hull_view_id = hit["view_id"]
                    if event.button == 1 and int(getattr(event, "clicks", 1) or 1) >= 2 and hit is not None:
                        self.toggle_hull_focus_mode()
                        return
                    self.hull_tool = "draw" if event.button == 1 else "erase"
                    self._hull_painting = hit is not None
                    if self._hull_painting:
                        self._paint_hull_at_screen(screen_pos)
                    return
                if event.type == pygame.MOUSEBUTTONUP and event.button in {1, 3}:
                    if self._hull_painting:
                        self._persist_design_state()
                    self._hull_painting = False
                    return
                return

            hit = self._orthographic_hit(screen_pos)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and hit is not None:
                clicked = self._component_at_orthographic_hit(hit)
                if clicked:
                    component_id = clicked["id"]
                    component = self.design._get_component_by_instance_id(component_id)
                    missing_axis = component.get("undefined_axis") if component else None
                    movable_axis = missing_axis if missing_axis in hit["axes"] else None
                    if movable_axis is None:
                        movable_axis = hit["axes"][0]
                    self.selected_part_id = component_id
                    self.design.set_selected_component(component_id)
                    self._active_orthographic_drag = {"component_id": component_id, "axis": movable_axis}
                    return

                catalog_id = self.design.dragging_catalog_component_id or self.design.active_catalog_component_id
                if catalog_id:
                    created_id = self.design.place_component_in_orthographic_view(
                        catalog_id, hit["view_id"], hit["u"], hit["v"],
                    )
                    self.design.cancel_drag()
                    self.selected_part_id = created_id
                    self.design.set_selected_component(created_id)
                    if created_id:
                        self._persist_design_state()
                    return

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if hit is not None and self.design.dragging_catalog_component_id:
                    created_id = self.design.place_component_in_orthographic_view(
                        self.design.dragging_catalog_component_id,
                        hit["view_id"], hit["u"], hit["v"],
                    )
                    self.design.cancel_drag()
                    self.selected_part_id = created_id
                    self.design.set_selected_component(created_id)
                    if created_id:
                        self._persist_design_state()
                    return
                if self._active_orthographic_drag:
                    component = self.design._get_component_by_instance_id(
                        self._active_orthographic_drag["component_id"]
                    )
                    if component:
                        component["undefined_axis"] = None
                    self._persist_design_state()
                self._active_orthographic_drag = None
                self.design.cancel_drag()
                return

            if hit is not None:
                return
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
                if ended_id:
                    self._persist_design_state()
                return

            return

        world_x, world_y = camera.screen_to_world(screen_pos)
        clicked_block = self._interior_block_at_world_position(world_x, world_y)
        clicked_id = clicked_block.get("id") if clicked_block else None

        self.selected_part_id = clicked_id
        self.hover_screen_pos = screen_pos if clicked_block else None
