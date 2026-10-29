import unittest

from tools.author_lumber_logistics_model import build_changes


class AuthorLumberLogisticsModelTests(unittest.TestCase):
    def test_authors_vehicle_design_item_and_two_routes(self):
        datasets = {
            "schemas": [
                {"id": "schema_logistics", "schema": "logistics", "fields": {"associated_locations": {"type": "entity_list"}}},
                {"id": "schema_locations", "schema": "locations", "fields": {"existing": {"type": "string"}}},
            ],
            "locations": [
                {
                    "id": "location_lumber_test_site", "_dataset": "locations", "type": "location",
                    "name": "Lumber Processing Test Site",
                    "bounds": {"type": "bbox", "min_x": -70, "max_x": 75, "min_y": -90, "max_y": 55},
                    "resident_people": ["person_lumber_overseer_tomas"],
                },
            ],
        }

        changes = build_changes(datasets)
        by_id = {entity["id"]: entity for entity in changes}

        self.assertIn("route_class", by_id["schema_logistics"]["fields"])
        self.assertIn("cargo_quantity_per_trip", by_id["schema_logistics"]["fields"])
        self.assertIn("assigned_vehicle_design", by_id["schema_logistics"]["fields"])
        self.assertIn("inbound_logistics_routes", by_id["schema_locations"]["fields"])
        self.assertIn("outbound_logistics_routes", by_id["schema_locations"]["fields"])
        self.assertIn("logistics_arrival_point", by_id["schema_locations"]["fields"])

        design = by_id["veh_design_lumber_hauler_cart"]
        self.assertEqual("horse-drawn logistics cart", design["vehicle_class"])

        item = by_id["item_raw_lumber"]
        self.assertFalse(item["consumable"])
        self.assertIn("ownership_lumber_storage_stock", item["ownership_records"])

        inbound = by_id["log_lumber_inbound_delivery"]
        self.assertEqual("active", inbound["status"])
        self.assertEqual("item_raw_lumber", inbound["cargo_item"])
        self.assertEqual(20, inbound["cargo_quantity_per_trip"])
        self.assertEqual("veh_design_lumber_hauler_cart", inbound["assigned_vehicle_design"])
        self.assertEqual("location_lumber_test_site", inbound["destination_location"])

        outbound = by_id["log_lumber_outbound_planks"]
        self.assertEqual("active", outbound["status"])
        self.assertEqual("location_lumber_test_site", outbound["origin_location"])

        site = by_id["location_lumber_test_site"]
        self.assertEqual(["log_lumber_inbound_delivery"], site["inbound_logistics_routes"])
        self.assertEqual(["log_lumber_outbound_planks"], site["outbound_logistics_routes"])
        self.assertEqual([56.0, 15.0], site["logistics_arrival_point"])
        # apply_changes fully replaces an entity's stored properties, so the
        # site's pre-existing fields must survive being carried through here
        # rather than getting dropped by a bare partial patch.
        self.assertEqual("Lumber Processing Test Site", site["name"])
        self.assertEqual(["person_lumber_overseer_tomas"], site["resident_people"])

        ownership = by_id["ownership_lumber_storage_stock"]
        self.assertEqual(["institution_person_sim_lab"], ownership["owner_entities"])
        self.assertEqual(["item_raw_lumber"], ownership["owned_assets"])


if __name__ == "__main__":
    unittest.main()
