import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from simulations.formation.formation_renderer import FormationRenderer
from simulations.formation.formation_simulation import FormationSimulation
from tools.author_unit_card_model import EXAMPLE_CARD, build_transaction


def _key(key, text=""):
    return pygame.event.Event(pygame.KEYDOWN, {"key": key, "unicode": text, "mod": 0})


class DeckBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    def _sim(self, extra=None):
        entities = {
            "form_bn": {
                "id": "form_bn", "type": "formation", "_dataset": "formations",
                "name": "1st Landing Battalion", "faction": "fac_sol", "formation_kind": "realization",
                "location": "loc_base",
            },
            "pop_sol": {"id": "pop_sol", "type": "pop", "_dataset": "pops", "name": "Sol Marines",
                        "pop_type": "service", "faction": "fac_sol", "population_count": 1000},
            "loc_base": {"id": "loc_base", "type": "location", "_dataset": "locations", "name": "Base"},
            "depot_sol": {"id": "depot_sol", "type": "location", "_dataset": "locations", "name": "Sol Depot",
                          "site_class": "depot", "controlling_factions": ["fac_sol"],
                          "vehicle_stock": [{"vehicle": "veh_tank", "quantity": 100}],
                          "inventory_items": [{"item": "item_rifle", "quantity": 100}]},
            "form_co": {
                "id": "form_co", "type": "formation", "_dataset": "formations",
                "name": "1st Company", "faction": "fac_sol", "parents": ["form_bn"],
                "deck_cards": [{"card": "card_rifles", "count": 2}],
            },
            "fac_sol": {"id": "fac_sol", "type": "faction", "_dataset": "factions", "name": "Sol Marines"},
            "fac_other": {"id": "fac_other", "type": "faction", "_dataset": "factions", "name": "Other"},
            "veh_tank": {
                "id": "veh_tank", "type": "vehicle", "_dataset": "vehicles", "name": "Test Tank",
                "formation_display_profile": "tank",
                "crew_roles": [{"role": "Driver", "count": 1}, {"role": "Gunner", "count": 1},
                               {"role": "Loader", "count": 1}, {"role": "Commander", "count": 1}],
            },
            "veh_old": {"id": "veh_old", "type": "vehicle", "_dataset": "vehicles", "name": "Old Tank",
                        "start_year": 1900, "end_year": 1950},
            "cat_small_arm": {"id": "cat_small_arm", "type": "category", "_dataset": "categories",
                              "name": "Small Arm"},
            "item_rifle": {"id": "item_rifle", "type": "item", "_dataset": "items", "name": "Assault Rifle",
                           "categories": ["cat_small_arm"]},
            "card_tanks": {
                "id": "card_tanks", "type": "unit_card", "_dataset": "unit_cards",
                "name": "Tank Platoon", "faction": "fac_sol", "card_category": "Armor",
                "card_equipment": [{"id": "eq_1", "kind": "vehicle", "vehicle": "veh_tank", "count": 3}],
            },
            "card_rifles": {
                "id": "card_rifles", "type": "unit_card", "_dataset": "unit_cards",
                "name": "Rifle Section", "card_category": "Infantry",
                "card_manpower": [{"id": "man_1", "role": "Sergeant", "count": 1, "is_command": True},
                                  {"id": "man_2", "role": "Rifleman", "count": 7}],
                "card_equipment": [{"id": "eq_1", "kind": "item", "item": "item_rifle", "count": 7}],
            },
            "card_foreign": {
                "id": "card_foreign", "type": "unit_card", "_dataset": "unit_cards",
                "name": "Foreign Card", "faction": "fac_other", "card_category": "Armor",
            },
        }
        entities.update(extra or {})
        changed = []

        def set_literal(entity_id, field, value, persist=True):
            entities[entity_id][field] = value

        def persist_entity(entity, **_kwargs):
            entities[entity["id"]] = entity
            return True

        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [e for e in entities.values() if e.get("_dataset") == name],
            set_literal=set_literal,
            loader=SimpleNamespace(persist_entity=persist_entity),
            mark_repository_changed=lambda ids=None: changed.append(ids),
        )
        sim = FormationSimulation(world_model=world, formation_id="form_bn")
        return sim, entities

    def _render(self, sim):
        screen = pygame.Surface((1600, 1000))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)
        return sim.hitboxes

    def _click(self, sim, key):
        rect = sim.hitboxes[key]
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, rect.center)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1}), None, rect.center)

    def test_card_counts_vehicle_crew_and_items_and_lists_what_it_draws(self):
        sim, entities = self._sim()
        tanks = sim.deck.card_totals(entities["card_tanks"])
        self.assertEqual((3, 12, 0, 12, 0), (tanks["vehicles"], tanks["crew"], tanks["personnel"],
                                             tanks["people"], tanks["items"]))
        rifles = sim.deck.card_totals(entities["card_rifles"])
        self.assertEqual((8, 7, 0), (rifles["people"], rifles["items"], rifles["vehicles"]))
        draw = sim.deck.card_draw(entities["card_tanks"])
        self.assertEqual({"Driver": 3, "Gunner": 3, "Loader": 3, "Commander": 3}, draw["people"])
        self.assertEqual({("vehicle", "veh_tank"): 3}, draw["equipment"])

    def test_catalog_offers_own_and_unowned_cards_only(self):
        sim, _ = self._sim()
        sim.set_workspace_mode("deck")
        self.assertEqual(["card_rifles", "card_tanks"], sorted(option["id"] for option in sim.deck.catalog()))
        self.assertEqual(["Infantry", "Armor"], sim.deck.catalog_categories())

    def test_deck_has_no_copy_limit_and_rolls_up_subordinates(self):
        sim, entities = self._sim()
        sim.set_workspace_mode("deck")
        for _ in range(3):
            self.assertTrue(sim.deck.change_card_count("card_tanks", 1))
        self.assertEqual([{"card": "card_tanks", "count": 3}], entities["form_bn"]["deck_cards"])
        totals = sim.deck.deck_summary()["totals"]
        self.assertEqual((3, 9, 36, 0), (totals["cards"], totals["vehicles"], totals["people"], totals["items"]))
        below = sim.deck.subordinate_totals()
        self.assertEqual((2, 16, 14), (below["cards"], below["people"], below["items"]))
        for _ in range(3):
            sim.deck.change_card_count("card_tanks", -1)
        self.assertEqual([], entities["form_bn"]["deck_cards"])

    def test_new_card_takes_manpower_vehicles_and_items_and_joins_the_deck(self):
        sim, entities = self._sim()
        sim.set_workspace_mode("deck")
        self.assertTrue(sim.deck.new_card())
        self.assertTrue(sim.consumes_global_keydown())
        for character in "Mech Section":
            sim.handle_event(_key(ord(character.lower()) if character != " " else pygame.K_SPACE, character))
        sim.handle_event(_key(pygame.K_TAB))
        sim.deck.set_category("Infantry")
        sim.deck.open_picker("vehicle")
        self.assertEqual(["veh_tank"], [option["id"] for option in sim.deck.picker_options()])
        sim.deck.add_equipment_entry("vehicle", "veh_tank")
        sim.deck.open_picker("item")
        self.assertEqual([("item_rifle", "Small Arm")],
                         [(option["id"], option["detail"]) for option in sim.deck.picker_options()])
        sim.deck.add_equipment_entry("item", "item_rifle")
        rifle_entry = sim.deck.editor["draft"]["card_equipment"][1]["id"]
        sim.deck.adjust_entry(rifle_entry, 5)
        sim.deck.add_personnel_entry()
        sim.deck.editor["buffer"] = "Rifleman"
        sim.deck.commit_field()
        sim.deck.adjust_entry(sim.deck.editor["draft"]["card_manpower"][0]["id"], 5)
        card_id = sim.deck.save_card()
        self.assertEqual("card_mech_section", card_id)
        card = entities[card_id]
        self.assertEqual(("unit_cards", "fac_sol", "Infantry"), (card["_dataset"], card["faction"], card["card_category"]))
        self.assertEqual([("vehicle", "veh_tank", 1), ("item", "item_rifle", 6)],
                         [(entry["kind"], entry[entry["kind"]], entry["count"]) for entry in card["card_equipment"]])
        self.assertEqual([("Rifleman", 6)], [(entry["role"], entry["count"]) for entry in card["card_manpower"]])
        self.assertFalse({"card_contents", "card_cost", "max_per_deck"} & set(card))
        self.assertEqual(10, sim.deck.card_totals(card)["people"])
        self.assertEqual(1, sim.deck.deck_count(card_id))
        self.assertIsNone(sim.deck.editor)

    def test_editor_refuses_an_empty_or_unnamed_card(self):
        sim, entities = self._sim()
        sim.set_workspace_mode("deck")
        sim.deck.new_card()
        self.assertIsNone(sim.deck.save_card())
        self.assertIn("name", sim.deck.editor["status"])
        sim.deck.editor["buffer"] = "Empty"
        self.assertIsNone(sim.deck.save_card())
        self.assertIn("people or equipment", sim.deck.editor["status"])
        self.assertNotIn("card_empty", entities)

    def test_clicks_add_cards_and_put_an_item_on_a_card(self):
        sim, entities = self._sim()
        self._render(sim)
        self._click(sim, "workspace:deck")
        self.assertEqual("deck", sim.workspace_mode)
        hitboxes = self._render(sim)
        self.assertNotIn("deck:budget", hitboxes)
        self._click(sim, "deck:catalog:card:card_rifles")
        self.assertEqual([{"card": "card_rifles", "count": 1}], entities["form_bn"]["deck_cards"])
        hitboxes = self._render(sim)
        self.assertIn("deck:card:plus:card_rifles", hitboxes)
        self._click(sim, "deck:catalog:edit:card_tanks")
        self.assertEqual("card_tanks", sim.deck.editor["draft"]["id"])
        hitboxes = self._render(sim)
        self.assertNotIn("deck:catalog:card:card_rifles", hitboxes)
        self.assertNotIn("deck:editor:field:card_cost", hitboxes)
        self._click(sim, "deck:editor:add_item")
        self._render(sim)
        self._click(sim, "deck:editor:picker:pick:item_rifle")
        self._render(sim)
        self._click(sim, "deck:editor:save")
        self.assertEqual(["vehicle", "item"], [entry["kind"] for entry in entities["card_tanks"]["card_equipment"]])

    def test_tree_click_in_deck_mode_retargets_without_navigating(self):
        sim, _ = self._sim()
        sim.set_workspace_mode("deck")
        self._render(sim)
        self._click(sim, "tree:form_co")
        self.assertEqual("form_co", sim.deck.target_formation_id())
        self.assertIsNone(sim.consume_pending_navigation_action())
        self.assertEqual(2, sim.deck.deck_summary()["totals"]["cards"])

    def test_blueprint_deck_is_snapshotted_and_draws_nothing(self):
        sim, entities = self._sim()
        entities["form_bn"]["formation_kind"] = "blueprint"
        sim.set_workspace_mode("deck")
        sim.deck.change_card_count("card_rifles", 1)
        snapshot = entities["form_bn"]["formation_snapshots"][-1]
        self.assertEqual([{"card": "card_rifles", "count": 1}], snapshot["state"]["deck_cards"])
        self.assertEqual(100, sim.deck.fielding.stock("depot_sol", "item", "item_rifle"))
        self.assertEqual([], [e for e in entities.values() if e.get("_dataset") == "logistics"])

    def test_fielding_draws_people_and_stock_requests_delivery_and_goes_understrength(self):
        sim, entities = self._sim()
        entities["pop_sol"]["population_count"] = 36
        entities["depot_sol"]["vehicle_stock"] = [{"vehicle": "veh_tank", "quantity": 4}]
        fielding = sim.deck.fielding
        sim.set_workspace_mode("deck")
        self.assertEqual(("pop_sol", ["depot_sol"], "loc_base"),
                         (fielding.manpower_pop_id("form_co"), fielding.depot_ids("form_co"),
                          fielding.destination_id("form_bn")))
        self.assertEqual(20, fielding.pop_free("pop_sol"))  # the company's two rifle sections hold 16

        sim.deck.change_card_count("card_tanks", 1)
        self.assertEqual((8, 1), (fielding.pop_free("pop_sol"), fielding.stock("depot_sol", "vehicle", "veh_tank")))
        demand_id = fielding.demand_id("form_bn", "depot_sol")
        demand = entities[demand_id]
        self.assertEqual(("formation supply", "requested", "depot_sol", "loc_base", "form_bn"),
                         (demand["route_class"], demand["status"], demand["origin_location"],
                          demand["destination_location"], demand["requested_by"]))
        self.assertEqual([{"kind": "vehicle", "vehicle": "veh_tank", "quantity": 3}], demand["cargo_manifest"])
        self.assertEqual([demand_id], entities["depot_sol"]["outbound_logistics_routes"])
        self.assertIn("3 Test Tank requested from Sol Depot", sim.deck.notice)

        sim.deck.change_card_count("card_tanks", 1)
        self.assertEqual([{"card": "card_tanks", "count": 2, "short": {"people": 4, "vehicle:veh_tank": 2}}],
                         entities["form_bn"]["deck_cards"])
        self.assertIn("understrength", sim.deck.notice)
        self.assertEqual((0, 0), (fielding.pop_free("pop_sol"), fielding.stock("depot_sol", "vehicle", "veh_tank")))
        self.assertEqual(4, entities[demand_id]["cargo_manifest"][0]["quantity"])

        sim.deck.change_card_count("card_tanks", -1)  # the understrength copy goes first
        self.assertEqual([{"card": "card_tanks", "count": 1}], entities["form_bn"]["deck_cards"])
        self.assertEqual((8, 1), (fielding.pop_free("pop_sol"), fielding.stock("depot_sol", "vehicle", "veh_tank")))
        sim.deck.remove_card("card_tanks")
        self.assertEqual((20, 4), (fielding.pop_free("pop_sol"), fielding.stock("depot_sol", "vehicle", "veh_tank")))
        self.assertEqual(("cancelled", []), (entities[demand_id]["status"], entities[demand_id]["cargo_manifest"]))

    def test_formation_without_pool_or_depot_is_fielded_short_and_says_why(self):
        sim, entities = self._sim()
        entities["fac_sol"]["name"] = "Sol"
        del entities["pop_sol"], entities["depot_sol"]
        sim.set_workspace_mode("deck")
        sim.deck.change_card_count("card_tanks", 1)
        self.assertEqual({"people": 12, "vehicle:veh_tank": 3}, entities["form_bn"]["deck_cards"][0]["short"])
        self.assertIn("no manpower pool", sim.deck.notice)
        hitboxes = self._render(sim)
        self.assertIn("deck:card:minus:card_tanks", hitboxes)

    def test_people_panel_shows_representatives_and_saves_one_as_a_person(self):
        sim, entities = self._sim()
        sim.set_workspace_mode("deck")
        sim.deck.change_card_count("card_rifles", 2)
        roster = sim.deck.people.roster("form_bn")
        self.assertEqual([("Sergeant", 2, 2, 0), ("Rifleman", 14, 3, 11)],
                         [(row["role"], row["held"], len(row["representatives"]), row["crowd"]) for row in roster])
        first = roster[1]["representatives"][0]
        again = sim.deck.people.roster("form_bn")[1]["representatives"][0]
        self.assertEqual(first, again)  # the same person comes back every time
        self.assertEqual(("form_bn", "Rifleman", "pop_sol", ["fac_sol"]),
                         (first["serves_in"], first["service_role"], first["source_pop"],
                          first["affiliated_factions"]))

        self._render(sim)
        self._click(sim, f"deck:people:pick:{first['id']}")
        self.assertEqual(first["id"], sim.deck.people_selected)
        self._render(sim)
        self._click(sim, f"deck:people:save:{first['id']}")
        saved_id = sim.deck.people_selected
        person = entities[saved_id]
        self.assertTrue(saved_id.startswith("person_"))
        self.assertEqual((first["name"], first["birth_seed"], "form_bn", "Rifleman", "draft"),
                         (person["name"], person["birth_seed"], person["serves_in"], person["service_role"],
                          person["entry_status"]))
        self.assertTrue(person["genetic_dna"])
        rifles = sim.deck.people.roster("form_bn")[1]
        # A saved person is one of the 14, and the representatives move on to the next seed.
        self.assertEqual((14, [saved_id], 3, 10), (rifles["held"], [p["id"] for p in rifles["saved"]],
                                                   len(rifles["representatives"]), rifles["crowd"]))
        self.assertNotIn(first["birth_seed"], [rep["birth_seed"] for rep in rifles["representatives"]])

        self._render(sim)
        self._click(sim, f"deck:people:open:{saved_id}")
        self.assertEqual({"id": "knowledge_launch_mode", "entity_id": saved_id, "launch_mode": "person"},
                         sim.consume_pending_navigation_action())

    def test_people_short_comes_off_the_ranks_before_command_and_a_plan_holds_nobody(self):
        sim, entities = self._sim()
        entities["pop_sol"]["population_count"] = 26  # the company already holds 16
        sim.set_workspace_mode("deck")
        sim.deck.change_card_count("card_rifles", 2)
        roster = sim.deck.people.roster("form_bn")
        self.assertEqual([("Sergeant", 2, 0), ("Rifleman", 8, 6)],
                         [(row["role"], row["held"], row["short"]) for row in roster])
        entities["form_bn"]["formation_kind"] = "blueprint"
        self.assertEqual([0, 0], [row["held"] for row in sim.deck.people.roster("form_bn")])
        self.assertEqual([[], []], [row["representatives"] for row in sim.deck.people.roster("form_bn")])

    def test_author_tool_writes_schema_example_and_reshapes_first_shape_cards_once(self):
        datasets = {
            "schemas": [{"id": "schema_formation", "_dataset": "schemas", "schema": "formation",
                         "fields": {"doctrine": {"type": "string"}, "deck_budget": {"type": "number"}}},
                        {"id": "schema_logistics", "_dataset": "schemas", "schema": "logistics",
                         "fields": {"route_class": {"type": "string"}}},
                        {"id": "schema_person", "_dataset": "schemas", "schema": "person",
                         "fields": {"sex": {"type": "string"}}}],
            "vehicles": [{"id": "veh_test_tank"}],
            "factions": [{"id": EXAMPLE_CARD["faction"]}],
            "formations": [{"id": "form_x", "_dataset": "formations", "deck_budget": 60}],
            "unit_cards": [{"id": "card_old", "_dataset": "unit_cards", "card_cost": 5, "max_per_deck": 2,
                            "card_contents": [{"kind": "vehicle", "vehicle_id": "veh_test_tank", "count": 2},
                                              {"kind": "personnel", "role": "Rifleman", "count": 4}]}],
        }
        upserts = {entity["id"]: entity for entity in build_transaction(datasets)}
        # The depot, the US Army pop and the era cards wait for the entities they refer to.
        self.assertEqual({"schema_unit_card", "schema_formation", "schema_logistics", "schema_person",
                          "card_old", "form_x",
                          EXAMPLE_CARD["id"], "pop_ggo_sol_marine_service_members", "pop_usaf_airmen",
                          "pop_usn_sailors"}, set(upserts))
        fields = upserts["schema_formation"]["fields"]
        self.assertEqual({"doctrine", "deck_cards", "manpower_pop", "supply_depot"}, set(fields))
        self.assertIn("cargo_manifest", upserts["schema_logistics"]["fields"])
        self.assertEqual({"sex", "serves_in", "service_role", "service_rank", "source_pop"},
                         set(upserts["schema_person"]["fields"]))
        self.assertNotIn("deck_budget", upserts["form_x"])
        old = upserts["card_old"]
        self.assertFalse({"card_contents", "card_cost", "max_per_deck"} & set(old))
        self.assertEqual([("vehicle", "veh_test_tank", 2)],
                         [(entry["kind"], entry["vehicle"], entry["count"]) for entry in old["card_equipment"]])
        self.assertEqual([("Rifleman", 4)], [(entry["role"], entry["count"]) for entry in old["card_manpower"]])
        datasets["schemas"] = [upserts[schema_id] for schema_id in upserts if schema_id.startswith("schema_")]
        datasets["formations"] = [upserts["form_x"]]
        datasets["unit_cards"] = [old, upserts[EXAMPLE_CARD["id"]]]
        datasets["pops"] = [upserts[pop_id] for pop_id in upserts if pop_id.startswith("pop_")]
        self.assertEqual([], build_transaction(datasets))


if __name__ == "__main__":
    unittest.main()
