import unittest

from simulations.person.person_simulation import PersonSimulation


class FakeLoader:
    def __init__(self, world):
        self.world = world

    def persist_entity(self, entity):
        self.world.entities[entity["id"]] = entity
        return True


class FakeWorld:
    def __init__(self, *entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.loader = FakeLoader(self)

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


def tag(tag_id, name, **fields):
    return {"id": tag_id, "_dataset": "tags", "type": "tag", "name": name, "tag_class": "need", **fields}


def item(item_id, name, satiation=None, **fields):
    entity = {"id": item_id, "_dataset": "items", "type": "item", "pretty_name": name, **fields}
    if satiation is not None:
        entity.update({"consumable": True, "food_satiation": satiation})
    return entity


def story_world():
    """The owner's example: chips in hand, a vending machine, a fishmonger, a crowberry shrub."""
    return FakeWorld(
        tag("tag_need_food", "Food", serves_need="food"),
        tag("tag_need_snack", "Snack", parents=["tag_need_food"]),
        tag("tag_need_fish", "Fish", parents=["tag_need_food"]),
        tag("tag_need_berries", "Berries", parents=["tag_need_food"]),
        item("item_chips_bag", "Chips Bag", 15, tags=["Snack"]),
        item("item_smoked_fish", "Smoked Fish", 45, tags=["Fish"]),
        item("item_crowberries", "Crowberries", 6, tags=["Berries"]),
        item("item_vending_machine", "Vending Machine", dispenses_items=["item_chips_bag"]),
        {"id": "job_fishmonger", "_dataset": "jobs", "type": "job", "pretty_name": "Fishmonger",
         "hands_out_items": ["item_smoked_fish"]},
        {"id": "person_fishmonger", "_dataset": "people", "type": "person", "pretty_name": "Ivo Brann",
         "is_employed_as": "job_fishmonger"},
        {"id": "spec_crowberry", "_dataset": "species", "type": "species", "common_name": "Black Crowberry",
         "harvest_yields": ["item_crowberries"]},
        {"id": "person_hungry", "_dataset": "people", "type": "person", "pretty_name": "Hungry Walker",
         "knowledge_collection": "coll_knowledge_hungry",
         "inventory_items": [{"item": "item_chips_bag", "quantity": 1}]},
        {"id": "coll_knowledge_hungry", "_dataset": "collections", "type": "collection",
         "pretty_name": "Knowledge of Hungry Walker", "collection_class": "personal_knowledge",
         "includes": ["item_vending_machine", "person_fishmonger", "spec_crowberry"],
         "member_records": [
             {"member": "item_vending_machine", "familiarity": 0.7},
             {"member": "person_fishmonger", "familiarity": 0.7},
             {"member": "spec_crowberry", "familiarity": 0.5},
         ]},
    )


def run_story():
    world = story_world()
    sim = PersonSimulation(world, "person_hungry", year=2400)
    sim.needs.update({"food": 20.0, "rest": 100.0, "leisure": 100.0})
    sim.work_due = 0.0
    sim.place_thing("item_vending_machine", (8, 0), stock={})
    sim.place_thing("person_fishmonger", (60, 0), stock={"item_smoked_fish": 1})
    sim.place_thing("spec_crowberry", (40, -30), stock={"item_crowberries": 12})
    stolen = False
    for _ in range(400):
        sim._update_runtime(0.5)
        if not stolen and sim._item_quantity("item_smoked_fish") > 0:
            stolen = bool(sim.lose_item("item_smoked_fish", reason="stolen"))
    return world, sim


class NeedLoopStoryTests(unittest.TestCase):
    def test_hungry_person_works_through_what_they_know_until_fed(self):
        _world, sim = run_story()

        outcomes = [
            (entry["event"], entry["label"])
            for entry in reversed(sim.decision_history)
            if entry["event"] in {"completed", "failed"}
        ]
        self.assertEqual(
            [
                ("completed", "Eat Chips Bag"),
                ("failed", "Get Chips Bag from Vending Machine"),
                ("failed", "Ask Ivo Brann for Smoked Fish"),
                ("completed", "Harvest Crowberries from Black Crowberry"),
            ],
            outcomes[:4],
        )
        self.assertGreaterEqual(sim.needs["food"], 72.0)

    def test_failures_say_why_and_become_beliefs(self):
        _world, sim = run_story()
        failures = [entry["failure_reason"] for entry in reversed(sim.decision_history) if entry["event"] == "failed"]

        self.assertEqual(["Vending Machine has no Chips Bag left", "no Smoked Fish held"], failures)
        self.assertEqual("empty", sim.learned_beliefs["item_vending_machine"]["believed_state"])
        self.assertEqual("empty", sim.learned_beliefs["person_fishmonger"]["believed_state"])
        self.assertEqual({"food": 15.0}, sim.learned_beliefs["item_chips_bag"]["experienced"])

    def test_task_panel_groups_attempts_under_their_goal(self):
        world = story_world()
        sim = PersonSimulation(world, "person_hungry", year=2400)
        sim.needs.update({"food": 20.0, "rest": 100.0, "leisure": 100.0})
        sim.work_due = 0.0
        sim.place_thing("item_vending_machine", (8, 0), stock={})
        sim.place_thing("person_fishmonger", (60, 0), stock={"item_smoked_fish": 1})
        for _ in range(40):
            sim._update_runtime(0.5)

        [goal] = sim.get_task_panel_model()["goals"]["current"]

        self.assertEqual("Find food", goal["title"])
        self.assertEqual(
            [("completed", "Eat Chips Bag", "food 20 to 35"),
             ("failed", "Get Chips Bag from Vending Machine", "Vending Machine has no Chips Bag left")],
            [(attempt["state"], attempt["label"], attempt["detail"]) for attempt in goal["attempts"]],
        )
        self.assertEqual("Ask Ivo Brann for Smoked Fish", goal["current"]["label"])
        self.assertEqual(["Eat Smoked Fish"], goal["next"])

    def test_save_writes_learned_beliefs_into_the_knowledge_collection(self):
        world, sim = run_story()

        self.assertTrue(sim.has_unsaved_knowledge())
        self.assertTrue(sim.save_learned_knowledge())

        collection = world.entities["coll_knowledge_hungry"]
        rows = {row["member"]: row for row in collection["member_records"]}
        self.assertEqual("empty", rows["item_vending_machine"]["believed_state"])
        self.assertEqual(0.7, rows["item_vending_machine"]["familiarity"])
        self.assertIn("item_chips_bag", collection["includes"])
        self.assertFalse(sim.has_unsaved_knowledge())
        food_sources = next(
            category["entries"] for category in sim.get_knowledge_panel_model()["categories"]
            if category["label"] == "Food sources"
        )
        machine = next(entry for entry in food_sources if entry["entity_id"] == "item_vending_machine")
        self.assertIn("empty", machine["stance"])


def outcomes(sim):
    return [
        (entry["event"], entry["label"])
        for entry in reversed(sim.decision_history)
        if entry["event"] in {"completed", "failed"}
    ]


class RestAndCompanyTests(unittest.TestCase):
    def settle(self, sim, seconds=60):
        for _ in range(seconds * 2):
            sim._update_runtime(0.5)

    def test_tired_person_prefers_the_bed_over_a_nearer_bench(self):
        world = FakeWorld(
            {"id": "item_bed", "_dataset": "items", "type": "item", "pretty_name": "Bed", "rest_quality": 1.0},
            {"id": "item_bench", "_dataset": "items", "type": "item", "pretty_name": "Bench", "rest_quality": 0.35},
            {"id": "person_tired", "_dataset": "people", "type": "person", "pretty_name": "Tired Walker",
             "knowledge_collection": "coll_knowledge_tired"},
            {"id": "coll_knowledge_tired", "_dataset": "collections", "collection_class": "personal_knowledge",
             "includes": ["item_bench"], "member_records": [{"member": "item_bench", "familiarity": 0.7}]},
        )
        sim = PersonSimulation(world, "person_tired", year=2400)
        sim.needs.update({"food": 100.0, "rest": 20.0, "leisure": 100.0})
        sim.work_due = 0.0
        sim.place_thing("item_bench", (2, 0))

        self.settle(sim)

        # The void's own bed is 13 m away, the bench 2 m: a full rest beats a quick sit.
        self.assertEqual([("completed", "Rest at Bed")], outcomes(sim))
        self.assertAlmostEqual(82.0, sim.needs["rest"], delta=1.0)
        self.assertEqual({"rest": 62.0}, sim.learned_beliefs["item_bed"]["experienced"])

    def test_lonely_person_walks_to_a_friend_rather_than_a_nearer_stranger(self):
        world = FakeWorld(
            {"id": "loc_camp", "_dataset": "locations", "type": "location",
             "bounds": {"min_x": -30, "max_x": 30, "min_y": -30, "max_y": 30},
             "resident_people": ["person_lonely", "person_friend", "person_stranger"]},
            {"id": "person_lonely", "_dataset": "people", "type": "person", "pretty_name": "Lonely Walker",
             "simulation_site": "loc_camp", "site_position": [0, 0], "knowledge_collection": "coll_knowledge_lonely"},
            {"id": "coll_knowledge_lonely", "_dataset": "collections", "collection_class": "personal_knowledge",
             "includes": ["person_friend"],
             "member_records": [{"member": "person_friend", "familiarity": 0.9, "interest": 0.9}]},
            {"id": "person_friend", "_dataset": "people", "type": "person", "pretty_name": "Old Friend",
             "site_position": [20, 0]},
            {"id": "person_stranger", "_dataset": "people", "type": "person", "pretty_name": "New Neighbour",
             "site_position": [3, 0]},
        )
        sim = PersonSimulation(world, "person_lonely", year=2400)
        sim.needs.update({"food": 100.0, "rest": 100.0, "leisure": 100.0, "belonging": 20.0})
        sim.work_due = 0.0

        self.settle(sim, seconds=30)

        self.assertEqual(("completed", "Spend time with Old Friend"), outcomes(sim)[0])
        self.assertAlmostEqual(56.0, sim.needs["belonging"], delta=1.0)
        self.assertEqual("lives here", sim._need_candidates()["person_stranger"]["source"])


if __name__ == "__main__":
    unittest.main()
