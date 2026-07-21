import unittest

import pygame

from engine.camera import Camera
from engine.camera_controller import CameraController
from engine.input_controller import InputController


class _Simulation:
    min_zoom = 0.02
    max_zoom = 80.0
    free_camera_pan = True

    def __init__(self):
        self.received_wheel_y = []

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            self.received_wheel_y.append(event.y)


class CameraZoomSafetyTests(unittest.TestCase):
    def test_map_zoom_is_clamped_to_simulation_contract(self):
        camera = Camera(1920, 1080)
        controller = CameraController(camera, 1920, 1080)
        simulation = _Simulation()

        camera.zoom = 1.0e12
        controller.apply_constraints(simulation)
        self.assertEqual(80.0, camera.zoom)

        camera.zoom = 1.0e-30
        controller.apply_constraints(simulation)
        self.assertEqual(0.02, camera.zoom)

    def test_wheel_burst_is_coalesced_and_bounded_per_frame(self):
        camera = Camera(1920, 1080)
        simulation = _Simulation()
        input_controller = InputController(camera, simulation)
        events = [pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": 1}) for _ in range(100)]

        input_controller.process(events)

        self.assertEqual([6.0], simulation.received_wheel_y)
        self.assertLess(camera.zoom, 0.003)

    def test_large_negative_wheel_step_remains_finite_and_positive(self):
        camera = Camera(1920, 1080)
        camera.zoom = 1.0

        camera.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": -100}))

        self.assertGreater(camera.zoom, 0.0)
        self.assertLess(camera.zoom, 1.0)


if __name__ == "__main__":
    unittest.main()
