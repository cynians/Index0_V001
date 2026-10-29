import unittest

from simulations.person.person_knowledge import knowledge_records, known_entities
from simulations.person.person_simulation import PersonSimulation


class FakeWorld:
    def __init__(self, *entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


def collection(collection_id, name, records, nested=(), collection_class="personal_knowledge"):
    return {
        "id": collection_id, "_dataset": "collections", "pretty_name": name,
        "collection_class": collection_class,
        "includes": list(nested) + [record["member"] for record in records],
        "member_records": [dict(record) for record in records],
    }


def world():
    return FakeWorld(
        {"id": "person_mara", "_dataset": "people", "type": "person", "pretty_name": "Mara",
         "knowledge_collection": "coll_mara"},
        collection("coll_mara", "Knowledge of Mara", [
            {"member": "loc_woodlot", "navigation_knowledge": "route", "familiarity": 0.9},
            {"member": "loc_pantry", "familiarity": 0.8},
        ], nested=["coll_camp_lore"]),
        collection("coll_camp_lore", "Camp Lore", [
            {"member": "loc_woodlot", "navigation_knowledge": "direction", "direction_hint": [-1, 0],
             "familiarity": 0.3},
            {"member": "spec_crowberry", "familiarity": 0.5, "believed_location": "loc_woodlot"},
        ], collection_class="shared_knowledge"),
        {"id": "loc_woodlot", "_dataset": "locations", "type": "location", "pretty_name": "Wood Lot"},
        {"id": "loc_pantry", "_dataset": "locations", "type": "location", "pretty_name": "Pantry"},
        {"id": "spec_crowberry", "_dataset": "species", "type": "species", "common_name": "Crowberry",
         "plant_life_form": "chamaephyte", "harvest_yields": ["item_crowberries"]},
        {"id": "item_crowberries", "_dataset": "items", "type": "item", "pretty_name": "Crowberries",
         "tags": ["Berries"]},
        {"id": "tag_need_food", "_dataset": "tags", "name": "Food", "tag_class": "need", "serves_need": "food"},
        {"id": "tag_need_berries", "_dataset": "tags", "name": "Berries", "tag_class": "need",
         "parents": ["tag_need_food"]},
    )


class KnownEntityTests(unittest.TestCase):
    def test_shared_collection_adds_what_the_person_was_not_told(self):
        model = world()
        known = {entry.entity_id: entry for entry in known_entities(model.get_entity("person_mara"), model)}

        self.assertEqual({"loc_woodlot", "loc_pantry", "spec_crowberry"}, set(known))
        self.assertEqual(("coll_camp_lore",), known["spec_crowberry"].sources)

    def test_own_belief_wins_field_by_field_over_the_shared_one(self):
        model = world()
        woodlot = next(
            entry for entry in known_entities(model.get_entity("person_mara"), model)
            if entry.entity_id == "loc_woodlot"
        )

        self.assertEqual("route", woodlot.record["navigation_knowledge"])
        self.assertEqual(0.9, woodlot.record["familiarity"])
        self.assertEqual([-1, 0], woodlot.record["direction_hint"])
        self.assertEqual(("coll_mara", "coll_camp_lore"), woodlot.sources)

    def test_records_name_the_shared_collection_as_their_source(self):
        model = world()
        records = {record["entity"]: record for record in knowledge_records(model.get_entity("person_mara"), model)}

        self.assertEqual("Camp Lore", records["spec_crowberry"]["source"])
        self.assertNotIn("source", records["loc_pantry"])

    def test_collections_that_include_each_other_are_read_once(self):
        model = world()
        model.entities["coll_camp_lore"]["includes"].append("coll_mara")

        self.assertEqual(3, len(known_entities(model.get_entity("person_mara"), model)))

    def test_a_person_without_a_knowledge_collection_knows_nothing(self):
        model = world()

        self.assertEqual([], known_entities({"id": "person_blank"}, model))


class KnowledgePanelFoodSourceTests(unittest.TestCase):
    def test_knowledge_panel_lists_food_known_through_shared_lore(self):
        model = world()
        sim = PersonSimulation(model, "person_mara", year=2400)

        categories = {category["label"]: category["entries"] for category in sim.get_knowledge_panel_model()["categories"]}
        [row] = categories["Food sources"]

        self.assertEqual("Crowberry", row["label"])
        self.assertEqual("bears Crowberries at Wood Lot · Camp Lore", row["stance"])
        self.assertEqual(("bears", "harvest"), (row["relation"], row["action"]))
        self.assertIn("Crowberry", [entry["label"] for entry in categories["Nature"]])


if __name__ == "__main__":
    unittest.main()
