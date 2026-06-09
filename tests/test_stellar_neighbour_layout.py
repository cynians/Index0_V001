import math
import unittest
from types import SimpleNamespace

from simulations.space.space_renderer import SpaceRenderer
from simulations.space.stellar import LY_M


class FakeWorldModel:
    def __init__(self, entities):
        self.entities = entities

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


def system_entity(entity_id, name, neighbours=None):
    return {
        "id": entity_id,
        "type": "location",
        "_dataset": "locations",
        "name": name,
        "location_class": "star_system",
        "stellar_neighbours": neighbours or [],
    }


class StellarNeighbourLayoutTests(unittest.TestCase):
    def _layout(self, entities, root_id="system_a"):
        renderer = SpaceRenderer(SimpleNamespace(default_font=None))
        sim = SimpleNamespace(
            world_model=FakeWorldModel(entities),
            root_system_id=root_id,
            root_body_id=None,
        )
        return renderer._stellar_neighbour_layout(sim)

    def _distance_ly(self, layout, left_id, right_id):
        left = layout[left_id]["pos"]
        right = layout[right_id]["pos"]
        return math.hypot(left[0] - right[0], left[1] - right[1]) / LY_M

    def test_chain_neighbourhood_uses_deterministic_colinear_fallback(self):
        layout = self._layout({
            "system_a": system_entity("system_a", "A", [{"system": "system_b", "distance_ly": 1.0}]),
            "system_b": system_entity("system_b", "B", [{"system": "system_c", "distance_ly": 2.0}]),
            "system_c": system_entity("system_c", "C"),
        })

        self.assertAlmostEqual(1.0, self._distance_ly(layout, "system_a", "system_b"), places=6)
        self.assertAlmostEqual(2.0, self._distance_ly(layout, "system_b", "system_c"), places=6)
        self.assertAlmostEqual(3.0, self._distance_ly(layout, "system_a", "system_c"), places=6)
        self.assertAlmostEqual(0.0, layout["system_c"]["pos"][1], delta=1.0)

    def test_triangle_neighbourhood_satisfies_all_three_distances(self):
        layout = self._layout({
            "system_a": system_entity(
                "system_a",
                "A",
                [
                    {"system": "system_b", "distance_ly": 3.0},
                    {"system": "system_c", "distance_ly": 4.0},
                ],
            ),
            "system_b": system_entity(
                "system_b",
                "B",
                [
                    {"system": "system_a", "distance_ly": 3.0},
                    {"system": "system_c", "distance_ly": 5.0},
                ],
            ),
            "system_c": system_entity(
                "system_c",
                "C",
                [
                    {"system": "system_a", "distance_ly": 4.0},
                    {"system": "system_b", "distance_ly": 5.0},
                ],
            ),
        })

        self.assertAlmostEqual(3.0, self._distance_ly(layout, "system_a", "system_b"), places=6)
        self.assertAlmostEqual(4.0, self._distance_ly(layout, "system_a", "system_c"), places=6)
        self.assertAlmostEqual(5.0, self._distance_ly(layout, "system_b", "system_c"), places=6)
        self.assertGreater(layout["system_c"]["pos"][1], 0.0)


if __name__ == "__main__":
    unittest.main()
