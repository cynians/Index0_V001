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

    def test_chain_neighbourhood_uses_deterministic_metro_branch(self):
        layout = self._layout({
            "system_a": system_entity("system_a", "A", [{"system": "system_b", "distance_ly": 1.0}]),
            "system_b": system_entity("system_b", "B", [{"system": "system_c", "distance_ly": 2.0}]),
            "system_c": system_entity("system_c", "C"),
        })

        self.assertGreater(self._distance_ly(layout, "system_a", "system_b"), 0.0)
        self.assertGreater(self._distance_ly(layout, "system_b", "system_c"), 0.0)
        self.assertAlmostEqual(0.0, layout["system_c"]["pos"][1], delta=1.0)
        self.assertEqual(1.0, layout["system_b"]["distance_ly"])
        self.assertEqual(2.0, layout["system_c"]["distance_ly"])

    def test_triangle_neighbourhood_closes_in_schematic_geometry(self):
        entities = {
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
        }
        renderer = SpaceRenderer(SimpleNamespace(default_font=None))
        sim = SimpleNamespace(
            world_model=FakeWorldModel(entities),
            root_system_id="system_a",
            root_body_id=None,
        )
        graph = renderer._stellar_neighbour_graph(sim)
        layout = renderer._stellar_neighbour_layout(sim, graph)
        diagnostics = renderer._stellar_edge_diagnostics(graph, layout)

        self.assertTrue(all(row["valid"] for row in diagnostics.values()))
        self.assertNotAlmostEqual(layout["system_b"]["pos"][1], layout["system_c"]["pos"][1])

    def test_impossible_declared_triangle_marks_longest_edge_invalid(self):
        entities = {
            "system_a": system_entity(
                "system_a", "A", [
                    {"system": "system_b", "distance_ly": 2.0},
                    {"system": "system_c", "distance_ly": 9.0},
                ],
            ),
            "system_b": system_entity(
                "system_b", "B", [
                    {"system": "system_a", "distance_ly": 2.0},
                    {"system": "system_c", "distance_ly": 3.0},
                ],
            ),
            "system_c": system_entity("system_c", "C"),
        }
        renderer = SpaceRenderer(SimpleNamespace(default_font=None))
        sim = SimpleNamespace(
            world_model=FakeWorldModel(entities),
            root_system_id="system_a",
            root_body_id=None,
        )
        graph = renderer._stellar_neighbour_graph(sim)
        layout = renderer._stellar_neighbour_layout(sim, graph)
        diagnostics = renderer._stellar_edge_diagnostics(graph, layout)

        invalid = diagnostics[renderer._edge_key("system_a", "system_c")]
        self.assertFalse(invalid["valid"])
        self.assertEqual("declared_distances_cannot_form_triangle", invalid["reason"])

    def test_root_neighbours_are_distributed_across_metro_branches(self):
        neighbours = [
            {"system": f"system_{letter}", "distance_ly": index + 1.0}
            for index, letter in enumerate("bcdef")
        ]
        entities = {"system_a": system_entity("system_a", "A", neighbours)}
        entities.update({
            f"system_{letter}": system_entity(f"system_{letter}", letter.upper())
            for letter in "bcdef"
        })
        layout = self._layout(entities)

        angles = {
            round((layout[system_id]["branch_angle"] % math.tau) / (math.pi / 4.0))
            for system_id in entities
            if system_id != "system_a"
        }
        self.assertEqual(5, len(angles))


if __name__ == "__main__":
    unittest.main()
