import unittest

from simulations.person.person_assets import (
    assess_person_readiness,
    character_creation_prompt_lines,
    placeable_asset_catalog,
)


class PersonReadinessTests(unittest.TestCase):
    def test_empty_person_is_empty_tier(self):
        readiness = assess_person_readiness({"id": "person_blank", "type": "person"})
        self.assertEqual("empty", readiness["tier"])
        self.assertEqual(0.0, readiness["score"])
        self.assertEqual([], readiness["present"])

    def test_none_person_is_empty_tier(self):
        readiness = assess_person_readiness(None)
        self.assertEqual("empty", readiness["tier"])

    def test_partially_authored_person_is_sparse_tier(self):
        person = {
            "id": "person_test",
            "pretty_name": "Test Person",
            "affiliated_institutions": ["institution_test_lab"],
            "knowledge_records": [{"entity": "recipe_simple_cooked_meal", "interest": 0.8}],
        }
        readiness = assess_person_readiness(person)
        self.assertEqual("sparse", readiness["tier"])
        self.assertIn("identity", readiness["present"])
        self.assertIn("social", readiness["present"])
        self.assertIn("knowledge", readiness["present"])
        self.assertIn("personality", readiness["missing"])
        self.assertIn("motivation", readiness["missing"])
        self.assertIn("site", readiness["missing"])

    def test_fully_authored_person_is_authored_tier(self):
        person = {
            "id": "person_full",
            "pretty_name": "Mara Voss",
            "big_five_openness": 0.6,
            "big_five_conscientiousness": 0.7,
            "big_five_extraversion": 0.5,
            "big_five_agreeableness": 0.8,
            "big_five_neuroticism": 0.3,
            "wishes": ["wish_eat_with_friends"],
            "knowledge_records": [{"entity": "recipe_simple_cooked_meal", "interest": 0.8}],
            "affiliated_institutions": ["institution_test_lab"],
            "simulation_site": "location_lumber_test_site",
        }
        readiness = assess_person_readiness(person)
        self.assertEqual("authored", readiness["tier"])
        self.assertEqual(1.0, readiness["score"])

    def test_site_present_via_associated_location_with_world_model(self):
        class _WorldStub:
            def __init__(self, entities):
                self.entities = entities

            def get_entity(self, entity_id):
                return self.entities.get(entity_id)

        world = _WorldStub({
            "location_authored_site": {"id": "location_authored_site", "simulation_points": [{"id": "bed"}]},
        })
        person = {"id": "person_test", "associated_locations": ["location_authored_site"]}
        readiness = assess_person_readiness(person, world)
        self.assertIn("site", readiness["present"])

        readiness_without_world = assess_person_readiness(person)
        self.assertIn("site", readiness_without_world["missing"])

    def test_prompt_lines_mention_missing_categories(self):
        readiness = assess_person_readiness({"id": "person_blank"})
        lines = character_creation_prompt_lines(readiness, "Unnamed Person")
        self.assertIn("Unnamed Person lacks enough authored data to simulate credibly.", lines)
        self.assertTrue(any("Missing:" in line for line in lines))

    def test_prompt_lines_for_authored_person_are_affirmative(self):
        readiness = {"tier": "authored", "score": 1.0, "present": [], "missing": []}
        lines = character_creation_prompt_lines(readiness, "Mara Voss")
        self.assertEqual(["Mara Voss has enough authored data to simulate credibly."], lines)


class PlaceableAssetCatalogTests(unittest.TestCase):
    def test_duty_only_points_are_excluded_and_position_is_dropped(self):
        definitions = (
            {"id": "bed", "label": "Bed", "position": (1.0, 2.0), "tags": ("Rest",)},
            {"id": "lumber_dropoff", "label": "Lumber Yard Drop-off", "position": (6.0, 15.0)},
        )
        catalog = placeable_asset_catalog(definitions)
        self.assertEqual(["bed"], [entry["id"] for entry in catalog])
        self.assertNotIn("position", catalog[0])
        self.assertEqual("Bed", catalog[0]["label"])


if __name__ == "__main__":
    unittest.main()
