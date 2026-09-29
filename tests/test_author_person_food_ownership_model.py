import unittest

from tools.author_person_food_ownership_model import build_changes


class AuthorPersonFoodOwnershipModelTests(unittest.TestCase):
    def test_authors_recipe_ownership_and_kitchen_semantics(self):
        schema_names = (
            "vehicle", "location", "person", "pop", "faction",
            "institution", "producer", "technology",
        )
        datasets = {
            "schemas": [
                {"id": f"schema_{name}", "schema": name, "fields": {"existing": {"type": "string"}}}
                for name in schema_names
            ]
        }

        changes = build_changes(datasets)
        by_id = {entity["id"]: entity for entity in changes}

        self.assertIn("schema_recipe", by_id)
        self.assertIn("schema_ownership", by_id)
        self.assertIn("ownership_records", by_id["schema_vehicle"]["fields"])
        self.assertIn("inventory_items", by_id["schema_vehicle"]["fields"])
        # schema_item is owned in full by tools/author_item_component_model.py
        self.assertNotIn("schema_item", by_id)
        self.assertIn("ownership_records", by_id["schema_location"]["fields"])
        self.assertIn("openings", by_id["schema_location"]["fields"])
        self.assertIn("resident_people", by_id["schema_location"]["fields"])
        self.assertIn("present_pops", by_id["schema_location"]["fields"])
        self.assertIn("visitor_scenarios", by_id["schema_location"]["fields"])
        self.assertIn("inventory_items", by_id["schema_person"]["fields"])
        self.assertIn("simulation_site", by_id["schema_person"]["fields"])

        recipe = by_id["recipe_simple_cooked_meal"]
        self.assertEqual(["item_food_ingredients"], recipe["input_items"])
        self.assertEqual(["item_cooked_meal"], recipe["output_items"])
        self.assertEqual(1, recipe["input_requirements"][0]["quantity"])
        self.assertEqual("item_cooked_meal", recipe["output_yields"][0]["item"])
        self.assertCountEqual(
            ["component_kitchen_sink", "component_electric_oven"],
            recipe["required_components"],
        )

        person = by_id["person_lab_worker"]
        self.assertEqual("recipe_simple_cooked_meal", person["knowledge_records"][0]["entity"])
        self.assertIn("institution_person_sim_lab", person["affiliated_institutions"])

        pantry = by_id["location_person_test_pantry"]
        self.assertEqual(6, pantry["inventory_items"][0]["quantity"])
        self.assertIn("ownership_person_test_ingredients", pantry["ownership_records"])

        kitchen = by_id["producer_person_test_kitchen"]
        line = kitchen["production_lines"][0]
        self.assertEqual([recipe["id"]], line["recipe_ids"])
        self.assertIn("tech_electric_oven", line["employed_technology_ids"])
        self.assertCountEqual(recipe["required_components"], kitchen["assigned_components"])

        site = by_id["location_lumber_test_site"]
        self.assertEqual(4, len(site["resident_people"]))
        self.assertCountEqual(
            [
                "location_lumber_test_barracks", "location_person_test_kitchen",
                "location_lumber_test_storage", "location_lumber_test_factory",
            ],
            site["layout_structures"],
        )
        sexes = [by_id[person_id]["sex"] for person_id in site["resident_people"]]
        self.assertEqual(2, sexes.count("female"))
        self.assertEqual(2, sexes.count("male"))
        # Employment is a plain relationship field on the person (is_employed_by/
        # is_employed_as/is_employed_at) rather than a mediating employment
        # entity -- see docs/conceptual_layer_overview_v006.txt section 22.
        self.assertEqual("job_lumber_site_cook", by_id["person_lab_worker"]["is_employed_as"])
        self.assertEqual(["producer_person_test_kitchen"], by_id["person_lab_worker"]["is_employed_by"])
        self.assertEqual("job_lumber_site_laborer", by_id["person_lumber_laborer_elias"]["is_employed_as"])
        self.assertEqual("job_lumber_site_laborer", by_id["person_lumber_laborer_nia"]["is_employed_as"])
        self.assertEqual("job_lumber_site_overseer", by_id["person_lumber_overseer_tomas"]["is_employed_as"])
        self.assertEqual(["producer_lumber_test_factory"], by_id["person_lumber_overseer_tomas"]["is_employed_by"])
        for structure_id in site["layout_structures"]:
            self.assertTrue(by_id[structure_id]["openings"])
        self.assertEqual("site_meters", site["map_coordinate_space"])
        self.assertEqual("bbox", site["bounds"]["type"])
        self.assertIn("location_lumber_east_road", site["constituents"])
        self.assertIn("location_lumber_neighbor_village", site["constituents"])
        self.assertEqual(["pop_lumber_neighbor_village"], site["present_pops"])
        self.assertEqual(30, by_id["pop_lumber_neighbor_village"]["population_count"])
        self.assertEqual(3, by_id["pop_lumber_neighbor_village"]["representative_count"])
        self.assertEqual(
            ["institution_test_city_council"],
            by_id["ownership_lumber_neighbor_village"]["owner_entities"],
        )


if __name__ == "__main__":
    unittest.main()
