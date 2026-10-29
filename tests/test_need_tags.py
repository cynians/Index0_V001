import unittest

import pygame

from ui.card import EntityCard
from world.need_tags import explain, need_links, need_summary, need_tag_index, own_need_links


class FakeWorld:
    repository_revision = 1

    def __init__(self, *entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


def tag(tag_id, name, *, need=None, parents=(), tag_class="need"):
    entity = {"id": tag_id, "_dataset": "tags", "type": "tag", "name": name, "tag_class": tag_class}
    if need:
        entity["serves_need"] = need
    if parents:
        entity["parents"] = list(parents)
    return entity


def world():
    return FakeWorld(
        tag("tag_need_food", "Food", need="food"),
        tag("tag_need_snack", "Snack", parents=["tag_need_food"]),
        tag("tag_need_fish", "Fish", parents=["tag_need_food"]),
        tag("tag_need_berries", "Berries", parents=["tag_need_food"]),
        tag("tag_world_gen_complete", "world_gen_complete", tag_class="operational"),
        {"id": "cat_foodstuff", "_dataset": "categories", "pretty_name": "Foodstuff", "tags": ["Food"]},
        {"id": "cat_food_ingredient", "_dataset": "categories", "pretty_name": "Food Ingredient",
         "parents": ["cat_foodstuff"]},
        {"id": "item_chips_bag", "_dataset": "items", "pretty_name": "Chips Bag", "tags": ["Snack"],
         "food_satiation": 15},
        {"id": "item_flour", "_dataset": "items", "pretty_name": "Flour", "categories": ["cat_food_ingredient"]},
        {"id": "item_ration", "_dataset": "items", "pretty_name": "Ration", "food_satiation": 30},
        {"id": "item_smoked_fish", "_dataset": "items", "pretty_name": "Smoked Fish", "tags": ["fish"]},
        {"id": "item_lingonberries", "_dataset": "items", "pretty_name": "Lingonberries", "tags": ["Berries"]},
        {"id": "item_vending_machine", "_dataset": "items", "pretty_name": "Vending Machine",
         "dispenses_items": ["item_chips_bag"]},
        {"id": "job_fishmonger", "_dataset": "jobs", "pretty_name": "Fishmonger",
         "hands_out_items": ["item_smoked_fish"]},
        {"id": "person_fishmonger", "_dataset": "people", "pretty_name": "Ivo Brann",
         "is_employed_as": "job_fishmonger"},
        {"id": "person_hiker", "_dataset": "people", "pretty_name": "Hiker",
         "inventory_items": [{"item": "item_chips_bag", "quantity": 2}]},
        {"id": "spec_lingonberry", "_dataset": "species", "pretty_name": "Lingonberry",
         "harvest_yields": ["item_lingonberries"]},
    )


class NeedTagIndexTests(unittest.TestCase):
    def test_child_tag_inherits_its_parents_need(self):
        index = need_tag_index(world())

        self.assertEqual("food", index["snack"].need)
        self.assertEqual(("Snack", "Food"), index["snack"].chain)
        self.assertIs(index["snack"], index["tag_need_snack"])

    def test_tags_of_another_class_are_not_need_tags(self):
        self.assertNotIn("world_gen_complete", need_tag_index(world()))

    def test_a_parent_cycle_without_a_need_resolves_to_nothing(self):
        cyclic = FakeWorld(
            tag("tag_a", "A", parents=["tag_b"]),
            tag("tag_b", "B", parents=["tag_a"]),
        )

        self.assertEqual({}, need_tag_index(cyclic))


class OwnNeedLinkTests(unittest.TestCase):
    def test_local_tag(self):
        model = world()
        [link] = own_need_links(model.get_entity("item_chips_bag"), model)

        self.assertEqual(("food", "local", "Snack"), (link.need, link.provenance, link.tag))
        self.assertEqual("food: tagged Snack (Snack > Food)", explain(link, model))

    def test_tag_inherited_from_a_category_ancestor(self):
        model = world()
        [link] = own_need_links(model.get_entity("item_flour"), model)

        self.assertEqual(("inherited", "cat_foodstuff"), (link.provenance, link.source))
        self.assertEqual("food: category Foodstuff tagged Food", explain(link, model))

    def test_food_satiation_infers_food_only_without_a_food_tag(self):
        model = world()
        [ration] = own_need_links(model.get_entity("item_ration"), model)

        self.assertEqual(("food", "inferred"), (ration.need, ration.provenance))
        self.assertEqual(["local"], [link.provenance for link in own_need_links(model.get_entity("item_chips_bag"), model)])

    def test_rest_quality_infers_rest_and_any_person_is_company(self):
        model = world()
        model.entities["item_bench"] = {"id": "item_bench", "_dataset": "items", "rest_quality": 0.35}
        [bench] = own_need_links(model.get_entity("item_bench"), model)
        person_links = own_need_links(model.get_entity("person_hiker"), model)

        self.assertEqual(("rest", "inferred"), (bench.need, bench.provenance))
        self.assertEqual(["belonging: is a person"], [explain(link, model) for link in person_links])


class HolderNeedLinkTests(unittest.TestCase):
    def links(self, entity_id):
        model = world()
        return model, need_links(model.get_entity(entity_id), model, need="food")

    def test_machine_dispenses(self):
        model, [link] = self.links("item_vending_machine")

        self.assertEqual(("dispenses", "operate", "item_chips_bag"), (link.relation, link.action, link.thing))
        self.assertEqual("food: dispenses Chips Bag, tagged Snack (Snack > Food)", explain(link, model))

    def test_person_gives_through_their_job(self):
        model, [link] = self.links("person_fishmonger")

        self.assertEqual(("gives", "ask"), (link.relation, link.action))
        self.assertEqual(("person_fishmonger", "job_fishmonger", "item_smoked_fish"), link.path)
        self.assertEqual("food: gives Smoked Fish as Fishmonger, tagged Fish (Fish > Food)", explain(link, model))

    def test_species_bears(self):
        _model, [link] = self.links("spec_lingonberry")

        self.assertEqual(("bears", "harvest", "item_lingonberries"), (link.relation, link.action, link.thing))

    def test_inventory_carries(self):
        _model, [link] = self.links("person_hiker")

        self.assertEqual(("carries", "take", "item_chips_bag"), (link.relation, link.action, link.thing))

    def test_summary_names_the_most_direct_reason(self):
        model = world()
        model.entities["item_vending_machine"]["tags"] = ["Snack"]

        self.assertEqual([("food", "Snack")], need_summary(model.get_entity("item_vending_machine"), model))
        self.assertEqual(
            [("food", "gives Smoked Fish"), ("belonging", "company")],
            need_summary(model.get_entity("person_fishmonger"), model),
        )


class CardNeedChipTests(unittest.TestCase):
    def test_tags_tab_draws_a_serves_row_for_an_untagged_holder(self):
        pygame.font.init()
        model = world()
        card_view = EntityCard.__new__(EntityCard)
        card_view.entity = model.get_entity("spec_lingonberry")
        card_view.world_model = model
        card_view._resolve_schema = lambda: {}
        card = {}

        card_view._layout_tag_rows(card, 0, 0, 420, [])
        card_view._draw_tag_rows(pygame.Surface((420, 120)), pygame.font.Font(None, 16), card)

        self.assertEqual(["General", "Serves"], [layout["row"].label for layout in card["tag_row_layouts"]])
        self.assertEqual(["food"], [chip["need"] for chip in card["need_chip_hitboxes"]])
        self.assertEqual([], card["tag_chip_hitboxes"])


if __name__ == "__main__":
    unittest.main()
