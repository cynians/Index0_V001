import unittest
from types import SimpleNamespace

from simulations.collection.collections import Context, members, rule_matches, view


def world_with(*entities):
    by_id = {entity["id"]: entity for entity in entities}
    return SimpleNamespace(
        get_entity=by_id.get,
        get_entities_by_dataset=lambda name: [entity for entity in by_id.values() if entity.get("_dataset") == name],
    )


def vehicle(entity_id, vehicle_class="system_spacecraft", tags=(), **fields):
    return {"id": entity_id, "_dataset": "vehicles", "type": "vehicle", "vehicle_class": vehicle_class,
            "tags": list(tags), **fields}


def collection(entity_id, **fields):
    return {"id": entity_id, "_dataset": "collections", "type": "collections", **fields}


TEST_CRAFT_RULE = {
    "datasets": ["vehicles"],
    "field_values": {"vehicle_class": ["orbital_spacecraft", "system_spacecraft"]},
    "tags_all": ["test craft"],
}


class RuleTests(unittest.TestCase):
    def test_each_part_of_a_rule_filters(self):
        craft = vehicle("veh_a", tags=["Test Craft", "spacecraft"], manufacturer_name="X")
        self.assertTrue(rule_matches(craft, TEST_CRAFT_RULE))
        self.assertFalse(rule_matches(vehicle("veh_b", tags=["spacecraft"]), TEST_CRAFT_RULE))
        self.assertFalse(rule_matches(vehicle("veh_c", "aircraft", tags=["test craft"]), TEST_CRAFT_RULE))
        self.assertFalse(rule_matches(dict(craft, _dataset="components"), TEST_CRAFT_RULE))
        self.assertTrue(rule_matches(craft, {"tags_any": ["nope", "spacecraft"], "fields_present": ["manufacturer_name"]}))
        self.assertFalse(rule_matches(craft, {"fields_present": ["dimension_length_m"]}))


class MemberTests(unittest.TestCase):
    def test_listed_rule_and_nested_members_each_once_with_weights(self):
        world = world_with(
            vehicle("veh_tug", "orbital_spacecraft", tags=["test craft"]),
            vehicle("veh_pathfinder", tags=["test craft"]),
            vehicle("veh_liner", tags=["passenger"]),
            vehicle("veh_freighter", tags=["cargo"]),
            collection("coll_freight", includes=["veh_freighter"], member_weights=[{"member": "veh_freighter", "weight": 0.3}]),
            collection("coll_debug", includes=["veh_liner", "veh_pathfinder", "coll_freight"],
                       membership_rule=TEST_CRAFT_RULE,
                       member_weights=[{"member": "veh_tug", "weight": 2.5}]),
        )
        found = {member.entity_id: member for member in members(world.get_entity("coll_debug"), world)}
        self.assertEqual({"veh_liner", "veh_pathfinder", "veh_freighter", "veh_tug"}, set(found))
        self.assertEqual(("listed", 1.0), (found["veh_pathfinder"].source, found["veh_pathfinder"].weight))
        self.assertEqual(("coll_freight", 0.3), (found["veh_freighter"].source, found["veh_freighter"].weight))
        self.assertEqual(("rule", 2.5), (found["veh_tug"].source, found["veh_tug"].weight))

    def test_a_collection_that_lists_itself_through_another_ends(self):
        world = world_with(
            vehicle("veh_a"),
            collection("coll_one", includes=["coll_two", "veh_a"]),
            collection("coll_two", includes=["coll_one"]),
        )
        self.assertEqual(["veh_a"], [member.entity_id for member in members(world.get_entity("coll_one"), world)])

    def test_plant_collections_read_through_the_same_api(self):
        plants = {"id": "biosphere_collection_test", "_dataset": "biospheres", "collection_role": "plant_collection",
                  "plant_records": [{"species": "spec_a", "rarity": "dominant"}, {"species": "spec_b", "rarity": "rare"}]}
        weights = {member.entity_id: member.weight for member in members(plants, world_with())}
        self.assertEqual({"spec_a": 1.0, "spec_b": 0.05}, weights)


class ViewTests(unittest.TestCase):
    def test_the_context_narrows_by_year_and_judges_each_member(self):
        world = world_with(
            vehicle("veh_old", tags=["test craft"], start_year=2100, end_year=2300),
            vehicle("veh_new", tags=["test craft"], start_year=2350),
            vehicle("veh_undated", tags=["test craft"]),
            collection("coll_debug", includes=["veh_missing"], membership_rule=TEST_CRAFT_RULE),
        )
        seen = view(world.get_entity("coll_debug"), world,
                    Context(year=2400, check=lambda entity: entity["id"].upper()))
        self.assertEqual({"veh_new": "VEH_NEW", "veh_undated": "VEH_UNDATED"},
                         {item.entity["id"]: item.verdict for item in seen})


if __name__ == "__main__":
    unittest.main()
