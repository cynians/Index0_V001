import unittest

from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.clothing.clothing_design import (
    DEFAULT_BODY_SHAPE,
    body_landmarks,
    default_garment_pixels,
    human_reference_pixels,
    is_clothing_item,
    warp_clothing_pixels,
)
from simulations.clothing.clothing_simulation import ClothingSimulation


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


def _bounds(pixels):
    occupied = [(x, y) for y, row in enumerate(pixels) for x, value in enumerate(row) if value is not None]
    return min(x for x, _ in occupied), min(y for _, y in occupied), max(x for x, _ in occupied), max(y for _, y in occupied)


class ClothingEditorTests(unittest.TestCase):
    def setUp(self):
        self.clothing = {"id": "cat_clothing", "type": "category", "parents": ["cat_manufactured_good"]}
        self.formal = {"id": "cat_formalwear", "type": "category", "parents": ["cat_clothing"]}
        self.suit = {
            "id": "item_formal_suit", "type": "item", "_dataset": "items",
            "name": "Formal Suit", "categories": ["cat_formalwear"],
            "appearance_profile": {"silhouette": "suit"},
        }
        self.world = _World([self.clothing, self.formal, self.suit])

    def test_clothing_descendants_inherit_editor_launch_affordance(self):
        self.assertTrue(is_clothing_item(self.suit, self.world))
        options = LaunchAffordanceResolver().options_for_entity(self.suit, world_model=self.world)
        self.assertEqual(["clothing_editor"], [option["mode"] for option in options])

    def test_unrelated_item_does_not_gain_clothing_editor(self):
        item = {"id": "item_hammer", "type": "item", "_dataset": "items", "categories": ["cat_tools"]}
        self.assertFalse(is_clothing_item(item, self.world))
        self.assertEqual([], LaunchAffordanceResolver().options_for_entity(item, world_model=self.world))

    def test_category_cycles_are_safe(self):
        self.formal["parents"] = ["cat_loop"]
        self.world.entities["cat_loop"] = {"id": "cat_loop", "type": "category", "parents": ["cat_formalwear"]}
        self.assertFalse(is_clothing_item(self.suit, self.world))

    def test_editor_has_editable_garment_and_locked_human_reference(self):
        sim = ClothingSimulation(self.world, self.suit["id"])
        reference = sim.pixel_art_editor["views"]["reference"]
        garment, guide = reference["layers"]
        self.assertFalse(garment.get("locked", False))
        self.assertTrue(guide["locked"])
        self.assertTrue(guide["reference_only"])
        self.assertTrue(any(value is not None for row in guide["pixels"] for value in row))
        for view_id in ("small", "large"):
            self.assertTrue(sim.pixel_art_editor["views"][view_id]["layers"][0]["locked"])

    def test_arm_leg_and_torso_metrics_move_their_landmarks(self):
        short = dict(DEFAULT_BODY_SHAPE, arm_length=0.0, leg_length=0.0, torso_width=0.0)
        long = dict(DEFAULT_BODY_SHAPE, arm_length=1.0, leg_length=1.0, torso_width=1.0)
        short_marks, long_marks = body_landmarks(short), body_landmarks(long)
        self.assertGreater(long_marks["wrist_y"], short_marks["wrist_y"])
        self.assertLess(long_marks["hip_y"], short_marks["hip_y"])
        self.assertGreater(long_marks["torso_half"], short_marks["torso_half"])

    def test_one_reference_design_derives_visibly_different_sizes(self):
        source = default_garment_pixels("suit")
        small = warp_clothing_pixels(source, DEFAULT_BODY_SHAPE, {key: 0.1 for key in DEFAULT_BODY_SHAPE})
        large = warp_clothing_pixels(source, DEFAULT_BODY_SHAPE, {key: 0.9 for key in DEFAULT_BODY_SHAPE})
        small_bounds, large_bounds = _bounds(small), _bounds(large)
        self.assertLess(small_bounds[2] - small_bounds[0], large_bounds[2] - large_bounds[0])
        self.assertNotEqual(small, large)

    def test_reference_human_remains_long_and_spindly(self):
        pixels = human_reference_pixels()
        left, top, right, bottom = _bounds(pixels)
        self.assertGreater(bottom - top, (right - left) * 3)


if __name__ == "__main__":
    unittest.main()
