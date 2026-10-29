import unittest

from tools.author_lumber_placeholder_heightmap import build_changes, SITE_ID, SURROUNDS_ID
from simulations.world_gen.local_placeholder_heightmap import PLACEHOLDER_HEIGHTMAP_STATUS


class AuthorLumberPlaceholderHeightmapTests(unittest.TestCase):
    def test_authors_site_and_surrounds_heightmaps_from_one_consistent_field(self):
        datasets = {
            "locations": [
                {
                    "id": SITE_ID, "_dataset": "locations", "type": "location",
                    "name": "Lumber Processing Test Site",
                    "bounds": {"type": "bbox", "min_x": -70, "max_x": 75, "min_y": -90, "max_y": 55},
                    "resident_people": ["person_lumber_overseer_tomas"],
                },
            ],
        }

        changes = build_changes(datasets)
        by_id = {entity["id"]: entity for entity in changes}

        site = by_id[SITE_ID]
        surrounds = by_id[SURROUNDS_ID]

        # Pre-existing site fields must survive (same _replace_entity trap as
        # the logistics authoring script).
        self.assertEqual("Lumber Processing Test Site", site["name"])
        self.assertEqual(["person_lumber_overseer_tomas"], site["resident_people"])

        for entity in (site, surrounds):
            heightmap = entity["heightmap_model"]
            self.assertEqual(PLACEHOLDER_HEIGHTMAP_STATUS, heightmap["status"])
            rows = heightmap["sample_grid"]["rows"]
            self.assertGreaterEqual(len(rows), 2)
            self.assertGreaterEqual(len(rows[0]), 2)

        # Same seed/field: a site-bounds sample should closely match what the
        # (denser) surrounds heightmap reports for its overlapping origin
        # corner, since both sample the same continuous noise field.
        site_corner = site["heightmap_model"]["sample_grid"]["rows"][0][0]
        surrounds_min = surrounds["heightmap_model"]["min_elevation_m"]
        surrounds_max = surrounds["heightmap_model"]["max_elevation_m"]
        self.assertGreaterEqual(site_corner, surrounds_min - 1e-6)
        self.assertLessEqual(site_corner, surrounds_max + 1e-6)


if __name__ == "__main__":
    unittest.main()
