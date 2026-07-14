import unittest

from simulations.map.map_simulation import MapSimulation


class FailingScreenCamera:
    zoom = 1.0

    def world_to_screen(self, pos):
        raise AssertionError("polygon picking should stay in world space")


class MapPickingTests(unittest.TestCase):
    def test_polygon_pick_with_screen_pos_uses_world_space_hit_test(self):
        layer = {
            "shape": "polygon",
            "entity_id": "loc_square",
            "points": [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
            "_world_bounds": (-10.0, 10.0, -10.0, 10.0),
        }
        sim = MapSimulation.__new__(MapSimulation)
        sim.get_layers = lambda: [layer]

        picked = sim._pick_layer_at_world(
            world_x=0.0,
            world_y=0.0,
            camera=FailingScreenCamera(),
            screen_pos=(50, 50),
        )

        self.assertIs(layer, picked)


if __name__ == "__main__":
    unittest.main()
