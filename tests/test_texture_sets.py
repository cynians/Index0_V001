import unittest

from world.texture_sets import TextureSet, cell_key, parse_cell_key


class TextureSetTests(unittest.TestCase):
    def test_sparse_variants_round_trip_and_deterministic_shuffle(self):
        base = [{"name": "Bark", "visible": True, "opacity": 1.0, "pixels": [[(180, 180, 180)]]}]
        texture = TextureSet(1, 1, base_layers=base, texture_id="silver_birch_bark", seed=21)
        texture.add_variant(0, 1, base)
        texture.add_variant(2, 1, base)

        self.assertEqual("0,1", cell_key(0, 1))
        self.assertEqual((2, 1), parse_cell_key("2,1"))
        self.assertEqual(("0,1", "2,1"), tuple(texture.shuffled_variant_keys(2)))
        self.assertNotEqual(texture.shuffled_variant_keys(12)[0:2], ["0,1", "0,1"])

        restored = TextureSet.from_dict(texture.to_dict())
        self.assertIsNotNone(restored)
        self.assertEqual({"0,1", "2,1"}, set(restored.variants))
        self.assertEqual("silver_birch_bark", restored.texture_id)


if __name__ == "__main__":
    unittest.main()
