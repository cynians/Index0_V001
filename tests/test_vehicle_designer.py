import unittest

import pygame

from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.vehicle.vehicle_design import VehicleDesignController
from simulations.vehicle.vehicle_design_simulation import VehicleDesignSimulation
from simulations.vehicle.vehicle_renderer import VehicleRenderer
from ui.ui_manager import UIManager


class VehicleDesignerTests(unittest.TestCase):
    def test_all_six_orthographic_views_use_shared_physical_axes(self):
        controller = VehicleDesignController()
        self.assertEqual({"right", "left", "front", "rear", "top", "bottom"}, set(controller.ORTHOGRAPHIC_VIEWS))
        self.assertEqual(("x", "z"), controller.ORTHOGRAPHIC_VIEWS["right"]["axes"])
        self.assertEqual(("y", "z"), controller.ORTHOGRAPHIC_VIEWS["front"]["axes"])
        self.assertEqual(("x", "y"), controller.ORTHOGRAPHIC_VIEWS["top"]["axes"])

    def test_dimension_change_resizes_affected_pixel_canvases(self):
        controller = VehicleDesignController()
        self.assertEqual(90, len(controller.hull_silhouettes["right"][0]))
        old_right_width = len(controller.hull_silhouettes["right"][0])
        old_front_width = len(controller.hull_silhouettes["front"][0])
        self.assertTrue(controller.set_vehicle_dimension_m("x", 14.0))
        self.assertGreater(len(controller.hull_silhouettes["right"][0]), old_right_width)
        self.assertEqual(old_front_width, len(controller.hull_silhouettes["front"][0]))

    def test_component_first_projection_leaves_only_depth_axis_unresolved(self):
        controller = VehicleDesignController()
        component_id = controller.place_component_in_orthographic_view(
            "comp_engine_inline_compact", "right", 3.0, 1.25,
        )
        component = controller._get_component_by_instance_id(component_id)
        self.assertEqual("y", component["undefined_axis"])
        original = dict(component["position_m"])
        self.assertTrue(controller.move_component_axis(component_id, "y", 0.75))
        self.assertEqual(original["x"], component["position_m"]["x"])
        self.assertEqual(original["z"], component["position_m"]["z"])
        self.assertEqual(0.75, component["position_m"]["y"])

    def test_vehicle_card_offers_designer_operative_sim_and_registry(self):
        entity = {"id": "veh_demo", "type": "vehicle", "_dataset": "vehicles"}
        options = LaunchAffordanceResolver().options_for_entity(entity)
        self.assertEqual(
            ["vehicle_designer", "vehicle_sim", "vehicle_registry"],
            [option["mode"] for option in options],
        )
        self.assertEqual(
            ["Vehicle Designer", "Vehicle Sim", "Vehicle Registry"],
            [option["label"] for option in options],
        )

    def test_projection_layout_matches_physical_directions(self):
        simulation = VehicleDesignSimulation()
        payload = simulation.get_focused_render_payload()
        rects = VehicleRenderer._orthographic_layout(pygame.Surface((1440, 900)), simulation, payload)
        self.assertLess(rects["left"].centerx, rects["front"].centerx)
        self.assertLess(rects["front"].centerx, rects["right"].centerx)
        self.assertLess(rects["right"].centerx, rects["rear"].centerx)
        self.assertLess(rects["top"].centery, rects["front"].centery)
        self.assertLess(rects["front"].centery, rects["bottom"].centery)

    def test_focus_mode_expands_only_the_selected_pixel_canvas(self):
        simulation = VehicleDesignSimulation()
        simulation.set_design_step("hull")
        simulation.selected_hull_view_id = "top"
        simulation.toggle_hull_focus_mode()
        payload = simulation.get_focused_render_payload()
        rects = VehicleRenderer._orthographic_layout(pygame.Surface((1440, 900)), simulation, payload)
        self.assertEqual({"top"}, set(rects))
        self.assertGreater(rects["top"].width, 800)

    def test_detail_paint_is_clipped_to_structural_silhouette(self):
        controller = VehicleDesignController()
        controller.paint_hull_cell("right", 4, 3, True)
        self.assertTrue(controller.paint_color_cell("details", "right", 4, 3, "#d7dde8"))
        self.assertEqual("#d7dde8", controller.detail_layers["right"][3][4])
        self.assertFalse(controller.paint_color_cell("details", "right", 5, 3, "#d7dde8"))
        self.assertIsNone(controller.detail_layers["right"][3][5])

    def test_livery_copy_paste_creates_selectable_independent_design(self):
        controller = VehicleDesignController()
        copied = controller.copy_active_livery()
        pasted_id = controller.paste_livery(copied)
        self.assertEqual(2, len(controller.liveries))
        self.assertEqual(pasted_id, controller.active_livery_id)
        self.assertTrue(controller.select_livery("livery_001"))
        self.assertEqual("livery_001", controller.active_livery_id)

    def test_livery_uses_independent_high_resolution_silhouette_mask(self):
        controller = VehicleDesignController()
        hull = controller.hull_silhouettes["right"]
        hull[len(hull) // 2][len(hull[0]) // 2] = True
        livery = controller.get_paint_layer("liveries", "right")
        self.assertEqual(len(hull) * 4, len(livery))
        self.assertEqual(len(hull[0]) * 4, len(livery[0]))
        center_y, center_x = len(livery) // 2, len(livery[0]) // 2
        self.assertTrue(controller.paint_color_cell("liveries", "right", center_x, center_y, "#ff0000"))
        self.assertFalse(controller.paint_color_cell("liveries", "right", 0, 0, "#ff0000"))
        self.assertIsNone(livery[0][0])

    def test_paint_screen_returns_to_component_layout(self):
        simulation = VehicleDesignSimulation()
        self.assertTrue(simulation.enter_paint_screen("details"))
        self.assertEqual("details", simulation.design_step)
        self.assertTrue(simulation.is_vehicle_pixel_editor_active())
        self.assertEqual("vehicle_orthographic", simulation.pixel_art_editor["setup_mode"])
        self.assertEqual(
            {"right", "left", "front", "rear", "top", "bottom"},
            set(simulation.pixel_art_editor["views"]),
        )
        self.assertTrue(simulation.finish_paint_screen())
        self.assertEqual("components", simulation.design_step)
        self.assertFalse(simulation.is_vehicle_pixel_editor_active())

    def test_embedded_pixel_studio_enforces_vehicle_mask_and_writes_back(self):
        simulation = VehicleDesignSimulation()
        grid = simulation.design.hull_silhouettes["right"]
        x, y = len(grid[0]) // 2, len(grid) // 2
        grid[y][x] = True
        simulation.selected_hull_view_id = "right"
        self.assertTrue(simulation.enter_paint_screen("details"))
        editor = simulation.pixel_art_editor
        editor["canvas_rect"] = pygame.Rect(0, 0, editor["canvas_width"], editor["canvas_height"])
        editor["color"] = (12, 34, 56)

        simulation.pixel_art_editor_ui.paint_at((0, 0))
        self.assertIsNone(editor["layers"][0]["pixels"][0][0])
        simulation.pixel_art_editor_ui.paint_at((x, y))
        self.assertEqual((12, 34, 56), editor["layers"][0]["pixels"][y][x])

        self.assertTrue(simulation.pixel_art_editor_ui.save())
        self.assertEqual("#0c2238", simulation.design.detail_layers["right"][y][x])
        self.assertIsNone(simulation.design.detail_layers["right"][0][0])

    def test_vehicle_pixel_studio_replaces_the_normal_simulation_overlay(self):
        pygame.font.init()
        pygame.display.init()
        pygame.display.set_mode((1, 1), flags=pygame.HIDDEN)
        simulation = VehicleDesignSimulation()
        simulation.design.hull_silhouettes["right"][4][8] = True
        self.assertTrue(simulation.enter_paint_screen("liveries"))
        manager = UIManager()
        manager.rebuild_for_state(simulation, 1280, 800)
        self.assertIs(simulation.pixel_art_editor_ui, manager.vehicle_pixel_editor_ui)

        surface = pygame.Surface((1280, 800))
        font = pygame.font.SysFont("consolas", 16)
        manager.draw(surface, font)
        self.assertIsNotNone(simulation.pixel_art_editor.get("canvas_rect"))
        self.assertEqual("vehicle_orthographic", simulation.pixel_art_editor.get("setup_mode"))

    def test_design_view_suppresses_shared_top_left_chrome(self):
        pygame.font.init()
        simulation = VehicleDesignSimulation()
        manager = UIManager()

        manager.rebuild_for_state(simulation, 1280, 800)
        self.assertEqual("design", simulation.active_view_mode)
        self.assertEqual([], manager.time_lines)
        self.assertEqual(0.0, manager.timeline_fraction)
        self.assertIsNone(manager.mouse_world_label)
        self.assertIsNone(manager.scope_label)
        self.assertIsNone(manager.breadcrumb_label)
        self.assertEqual([], manager.vehicle_requirement_lines)

        simulation.set_view_mode("operational")
        manager.rebuild_for_state(simulation, 1280, 800)
        self.assertIsNotNone(manager.scope_label)
        self.assertTrue(manager.time_lines)

    def test_sparse_specification_rows_can_be_authored_and_removed(self):
        controller = VehicleDesignController(vehicle_entity={"id": "veh_sparse", "name": "Sparse Brief"})
        self.assertEqual([], controller.vehicle_specifications)
        row_id = controller.add_specification_row("characteristic")
        self.assertTrue(controller.update_specification_value("characteristic", row_id, "label", "Cruise speed"))
        self.assertTrue(controller.update_specification_value("characteristic", row_id, "value", ""))
        payload = controller.get_specification_payload()
        self.assertEqual("Cruise speed", payload["characteristics"][0]["label"])
        self.assertEqual("", payload["characteristics"][0]["value"])
        self.assertTrue(controller.remove_specification_row("characteristic", row_id))
        self.assertEqual([], controller.vehicle_specifications)

    def test_structural_feature_satisfies_airframe_requirement_without_becoming_component(self):
        controller = VehicleDesignController(vehicle_entity={
            "id": "veh_delta",
            "vehicle_class": "aircraft",
            "installed_components": [],
            "structural_features": [
                {"id": "delta_planform", "label": "Integral delta wing", "satisfies_categories": ["structure", "flight_surfaces"]},
            ],
        })
        status = {entry["category"]: entry for entry in controller.get_requirement_status_list()}
        self.assertTrue(status["structure"]["is_satisfied"])
        self.assertTrue(status["flight_surfaces"]["is_satisfied"])
        self.assertEqual([], controller.get_placed_components())

    def test_component_footprint_is_clamped_inside_every_vehicle_axis(self):
        controller = VehicleDesignController()
        component_id = controller.place_component_in_orthographic_view(
            "comp_engine_inline_compact", "right", 0.0, 0.0,
        )
        component = controller._get_component_by_instance_id(component_id)
        dimensions = controller._component_dimensions(component)
        for axis in ("x", "y", "z"):
            self.assertGreaterEqual(component["position_m"][axis], dimensions[axis] / 2.0)
            controller.move_component_axis(component_id, axis, 10_000.0)
            self.assertLessEqual(
                component["position_m"][axis] + dimensions[axis] / 2.0,
                controller.vehicle_dimensions_m[axis] + 1e-9,
            )

    def test_specification_screen_accepts_keyboard_text_and_advances_to_hull(self):
        simulation = VehicleDesignSimulation()
        row_id = simulation.design.add_specification_row("characteristic")
        simulation.specification_active_cell = ("characteristic", row_id, "label")
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, unicode="R", mod=0)
        self.assertTrue(simulation.handle_specification_key(event))
        self.assertEqual("R", simulation.design.vehicle_specifications[0]["label"])
        self.assertTrue(simulation.finish_specifications())
        self.assertEqual("hull", simulation.design_step)

    def test_long_specification_lists_can_page_independently(self):
        simulation = VehicleDesignSimulation()
        for _index in range(7):
            simulation.add_specification_row("characteristic")
        self.assertGreater(simulation.specification_page_offsets["characteristic"], 0)
        requirement_offset = simulation.specification_page_offsets["requirement"]
        self.assertTrue(simulation.page_specification_rows("characteristic", -1))
        self.assertEqual(requirement_offset, simulation.specification_page_offsets["requirement"])

    def test_default_catalog_entries_carry_inferred_ports(self):
        controller = VehicleDesignController()
        engine = controller.get_component_catalog_entry("comp_engine_inline_compact")
        self.assertEqual([{"port_id": "port_0_fuel", "resource_type": "fuel", "label": "Fuel"}], engine["inputs"])
        self.assertEqual(
            [{"port_id": "port_0_mechanical_power", "resource_type": "mechanical_power", "label": "Shaft Power"}],
            engine["outputs"],
        )
        fuel_tank = controller.get_component_catalog_entry("comp_fuel_tank_standard")
        self.assertEqual([], fuel_tank["inputs"])
        self.assertEqual(
            [{"port_id": "port_0_fuel", "resource_type": "fuel", "label": "Fuel"}], fuel_tank["outputs"],
        )

    @staticmethod
    def _empty_ground_vehicle_controller():
        # An explicit `installed_components` key (even empty) skips the
        # controller's own "bootstrap a default first component" behavior,
        # so these tests start from a genuinely empty layout.
        entity = {"vehicle_class": "ground_vehicle", "installed_components": []}
        return VehicleDesignController(vehicle_entity=entity)

    def test_engine_and_fuel_tank_auto_wire_by_resource_type(self):
        controller = self._empty_ground_vehicle_controller()
        engine_id = controller.place_component_in_orthographic_view("comp_engine_inline_compact", "right", 1.0, 1.0)
        tank_id = controller.place_component_in_orthographic_view("comp_fuel_tank_standard", "right", 5.0, 1.0)
        edges = controller.compute_system_wiring()
        self.assertEqual(1, len(edges))
        self.assertEqual(tank_id, edges[0]["from_slot_id"])
        self.assertEqual(engine_id, edges[0]["to_slot_id"])
        self.assertEqual("fuel", edges[0]["resource_type"])
        wiring_status = controller.get_component_wiring_status()
        self.assertTrue(wiring_status[engine_id]["fully_wired"])
        self.assertTrue(wiring_status[tank_id]["fully_wired"])

    def test_engine_without_fuel_tank_is_installed_but_unwired(self):
        controller = self._empty_ground_vehicle_controller()
        engine_id = controller.place_component_in_orthographic_view("comp_engine_inline_compact", "right", 1.0, 1.0)
        wiring_status = controller.get_component_wiring_status()
        self.assertFalse(wiring_status[engine_id]["fully_wired"])
        requirement = next(r for r in controller.get_requirement_status_list() if r["category"] == "propulsion_road")
        self.assertEqual("installed_unwired", requirement["state"])
        self.assertTrue(requirement["is_satisfied"])

    def test_uninstalling_a_component_leaves_a_reserved_empty_slot(self):
        controller = self._empty_ground_vehicle_controller()
        engine_id = controller.place_component_in_orthographic_view("comp_engine_inline_compact", "right", 1.0, 1.0)
        self.assertTrue(controller.uninstall_component_from_slot(engine_id))
        slot = controller._get_component_by_instance_id(engine_id)
        self.assertIsNone(slot["catalog_id"])
        self.assertEqual("propulsion_road", slot["slot_category"])
        requirement = next(r for r in controller.get_requirement_status_list() if r["category"] == "propulsion_road")
        self.assertEqual("reserved", requirement["state"])
        self.assertFalse(requirement["is_satisfied"])

        compatible_ids = {entry["id"] for entry in controller.get_compatible_catalog_entries_for_slot(engine_id)}
        self.assertIn("comp_engine_vblock_heavy", compatible_ids)
        self.assertNotIn("comp_fuel_tank_standard", compatible_ids)

        original_rect = dict(slot["local_rect_m"])
        self.assertTrue(controller.install_component_in_slot(engine_id, "comp_engine_vblock_heavy"))
        self.assertEqual("comp_engine_vblock_heavy", slot["catalog_id"])
        self.assertEqual(original_rect, slot["local_rect_m"])

    def test_manual_route_cycling_overrides_then_reverts_to_auto(self):
        controller = self._empty_ground_vehicle_controller()
        engine_id = controller.place_component_in_orthographic_view("comp_engine_inline_compact", "right", 1.0, 1.0)
        first_tank_id = controller.place_component_in_orthographic_view("comp_fuel_tank_standard", "right", 5.0, 1.0)
        second_tank_id = controller.place_component_in_orthographic_view("comp_fuel_tank_standard", "right", 8.0, 1.0)
        tank_ids = {first_tank_id, second_tank_id}

        self.assertTrue(controller.cycle_input_port_route(engine_id, "port_0_fuel"))
        first_route = dict(controller.manual_routes[0])
        self.assertTrue(controller.cycle_input_port_route(engine_id, "port_0_fuel"))
        second_route = controller.manual_routes[0] if controller.manual_routes else None
        self.assertNotEqual(first_route, second_route)

        # Cycle until the override clears (reverts to automatic wiring).
        for _ in range(4):
            if not controller.manual_routes:
                break
            controller.cycle_input_port_route(engine_id, "port_0_fuel")
        self.assertEqual([], controller.manual_routes)
        edges = controller.compute_system_wiring()
        self.assertEqual(1, len(edges))
        self.assertIn(edges[0]["from_slot_id"], tank_ids)


if __name__ == "__main__":
    unittest.main()
