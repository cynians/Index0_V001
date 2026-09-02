import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from simulations.formation.formation_renderer import FormationRenderer
from simulations.formation.formation_simulation import FormationSimulation


class FormationSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def _simulation(self):
        root = {
            "id": "form_test",
            "type": "formation",
            "_dataset": "formations",
            "name": "Test Formation",
        }
        faction = {
            "id": "fac_test",
            "type": "faction",
            "_dataset": "factions",
            "name": "Test Faction",
        }
        world = SimpleNamespace(
            get_entity=lambda entity_id: root if entity_id == "form_test" else faction if entity_id == "fac_test" else None,
            get_dataset=lambda name: [root] if name == "formations" else [faction] if name == "factions" else [],
        )
        return FormationSimulation(world_model=world, formation_id="form_test")

    def test_empty_records_do_not_invent_subdivision_names(self):
        sim = self._simulation()
        self.assertEqual([], sim.structure["children"])

    def test_renderer_exposes_tree_and_scale_controls(self):
        sim = self._simulation()
        screen = pygame.Surface((1200, 800))
        view = SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))

        FormationRenderer(view).draw(screen, sim)

        self.assertIn("tree:form_test", sim.hitboxes)
        self.assertIn("scale:personnel", sim.hitboxes)
        self.assertIn("create", sim.hitboxes)

    def test_clicking_child_requests_formation_navigation(self):
        sim = self._simulation()
        screen = pygame.Surface((1200, 800))
        view = SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))
        FormationRenderer(view).draw(screen, sim)

        handled = sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            camera=None,
            screen_pos=sim.hitboxes["tree:form_test"].center,
        )

        self.assertTrue(handled)
        self.assertEqual("form_test", sim.selected_node_id)
        self.assertEqual("aggregate", sim.display_scale)
        self.assertIsNone(sim.consume_pending_navigation_action())

    def test_legacy_formation_section_nests_named_formations(self):
        entities = {
            "form_root": {
                "id": "form_root",
                "type": "formation",
                "_dataset": "formations",
                "name": "Teutonian Kaiserheer",
                "wiki_entry": (
                    "! Formations\n!! [[Heeresgruppe 1]]\n"
                    "[[1. Infanterie, Heeresgruppe 1]]\n"
                    "[[2. Infanterie, Heeresgruppe 1]]\n"
                    "[[1. Läuferbrigade, Heeresgruppe 1]]\n"
                ),
            },
            "form_group": {
                "id": "form_group",
                "type": "formation",
                "_dataset": "formations",
                "name": "Heeresgruppe 1",
            },
            "form_first": {
                "id": "form_first",
                "type": "formation",
                "_dataset": "formations",
                "name": "1. Infanterie, Heeresgruppe 1",
            },
        }
        world = SimpleNamespace(get_entity=entities.get, get_dataset=lambda name: list(entities.values()))
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        group = sim.structure["children"][0]

        self.assertEqual("Heeresgruppe 1", group["label"])
        self.assertEqual(
            [
                "1. Infanterie, Heeresgruppe 1",
                "2. Infanterie, Heeresgruppe 1",
                "1. Läuferbrigade, Heeresgruppe 1",
            ],
            [child["label"] for child in group["children"]],
        )
        self.assertFalse(group["children"][0].get("is_unlinked"))
        self.assertTrue(group["children"][1].get("is_unlinked"))

    def test_opening_empty_child_card_recovers_children_from_parent_outline(self):
        entities = {
            "form_root": {
                "id": "form_root",
                "type": "formation",
                "_dataset": "formations",
                "name": "Teutonian Kaiserheer",
                "wiki_entry": (
                    "! Formations\n!! [[Heeresgruppe 1]]\n"
                    "[[1. Infanterie, Heeresgruppe 1]]\n"
                    "[[2. Infanterie, Heeresgruppe 1]]\n"
                ),
            },
            "form_group": {
                "id": "form_group",
                "type": "formation",
                "_dataset": "formations",
                "name": "Heeresgruppe 1",
            },
        }
        world = SimpleNamespace(get_entity=entities.get, get_dataset=lambda name: list(entities.values()))
        sim = FormationSimulation(world_model=world, formation_id="form_group")

        self.assertEqual(
            ["1. Infanterie, Heeresgruppe 1", "2. Infanterie, Heeresgruppe 1"],
            [child["label"] for child in sim.structure["children"]],
        )

    def test_creation_adds_an_arbitrary_named_child(self):
        sim = self._simulation()
        self.assertTrue(sim.begin_creation())
        sim.creation_faction_id = "fac_test"
        for character in "Landing Force":
            sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": 0, "unicode": character}))
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN, "unicode": ""}))

        self.assertEqual("Landing Force", sim.structure["children"][0]["label"])
        self.assertTrue(sim.structure["children"][0].get("is_draft"))

    def test_clicking_unlinked_reference_starts_creation_with_its_name(self):
        entities = {
            "form_root": {
                "id": "form_root",
                "type": "formation",
                "_dataset": "formations",
                "name": "Root",
                "wiki_entry": "! Formations\n!! [[Missing Formation]]\n",
            }
        }
        world = SimpleNamespace(get_entity=entities.get, get_dataset=lambda name: list(entities.values()))
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)

        unlinked_pos = sim.hitboxes["tree:unlinked:form_root:1"].center
        for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            sim.handle_pointer_event(
                pygame.event.Event(event_type, {"button": 1}),
                camera=None,
                screen_pos=unlinked_pos,
            )

        self.assertTrue(sim.creation_active)
        self.assertEqual("Missing Formation", sim.creation_buffer)

    def test_attached_vehicles_expose_profiles_and_grouped_crew(self):
        entities = {
            "form_root": {
                "id": "form_root",
                "type": "formation",
                "_dataset": "formations",
                "name": "Vehicle Test Formation",
                "vehicles": ["veh_jeep", "veh_spacecraft"],
            },
            "veh_jeep": {
                "id": "veh_jeep",
                "type": "vehicle",
                "_dataset": "vehicles",
                "name": "Test Army Jeep",
                "vehicle_class": "ground_vehicle",
                "formation_display_profile": "jeep",
                "crew_complement": 2,
                "crew_roles": [{"role": "Driver", "count": 1}, {"role": "Gunner", "count": 1}],
            },
            "veh_spacecraft": {
                "id": "veh_spacecraft",
                "type": "vehicle",
                "_dataset": "vehicles",
                "name": "Test Spacecraft",
                "vehicle_class": "interstellar_spacecraft",
                "formation_display_profile": "spacecraft",
                "crew_complement": 1000,
                "crew_roles": [{"role": "Engineering", "count": 1000}],
            },
        }
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")

        self.assertEqual(["Test Army Jeep", "Test Spacecraft"], [vehicle["label"] for vehicle in sim.structure["vehicles"]])
        self.assertEqual("jeep", sim.structure["vehicles"][0]["profile"])
        self.assertEqual(
            [{"role": "Engineering", "count": 1000}],
            sim.structure["vehicles"][1]["crew_roles"],
        )

        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)

    def test_unassigned_vehicle_is_not_displayed(self):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations", "name": "Root",
            },
            "veh_catalog_only": {
                "id": "veh_catalog_only", "type": "vehicle", "_dataset": "vehicles",
                "name": "Catalog Vehicle", "vehicle_class": "ground_vehicle", "crew_complement": 1,
            },
        }
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")

        self.assertEqual([], sim.structure["vehicles"])

    def test_formation_blueprint_exposes_temporal_equipment(self):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations", "name": "Root",
                "blueprints": ["form_blueprint"],
            },
            "form_blueprint": {
                "id": "form_blueprint", "type": "formation", "_dataset": "formations",
                "name": "Infantry Group", "formation_kind": "blueprint",
                "blueprint_items": ["item_rifle", "item_future_rifle"],
            },
            "item_rifle": {
                "id": "item_rifle", "type": "item", "_dataset": "items", "name": "Test Assault Rifle",
                "start_year": 2300,
            },
            "item_future_rifle": {
                "id": "item_future_rifle", "type": "item", "_dataset": "items", "name": "Test New Assault Rifle",
                "start_year": 2401,
            },
        }
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")

        blueprint = sim.structure["blueprints"][0]
        self.assertEqual(2400, sim.year)
        self.assertEqual("blueprint", blueprint["formation_kind"])
        self.assertTrue(blueprint["items"][0]["is_available"])
        self.assertFalse(blueprint["items"][1]["is_available"])

        sim.set_year(2401)
        self.assertTrue(sim.structure["blueprints"][0]["items"][1]["is_available"])

        blueprint_sim = FormationSimulation(world_model=world, formation_id="form_blueprint")
        self.assertEqual(
            ["Test Assault Rifle", "Test New Assault Rifle"],
            [item["label"] for item in blueprint_sim.structure["blueprint_items"]],
        )

    def test_renderer_exposes_blueprint_navigation_and_year_controls(self):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations", "name": "Root",
                "blueprints": ["form_blueprint"],
            },
            "form_blueprint": {
                "id": "form_blueprint", "type": "formation", "_dataset": "formations", "name": "Infantry Group",
                "formation_kind": "blueprint", "blueprint_items": [],
            },
        }
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)

        self.assertIn("blueprint:form_blueprint", sim.hitboxes)
        self.assertIn("year:previous", sim.hitboxes)
        self.assertIn("year:next", sim.hitboxes)
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            camera=None,
            screen_pos=sim.hitboxes["year:next"].center,
        )
        self.assertEqual(2401, sim.year)
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            camera=None,
            screen_pos=sim.hitboxes["blueprint:form_blueprint"].center,
        )
        self.assertEqual("form_blueprint", sim.consume_pending_navigation_action()["entity_id"])

    def test_year_can_be_typed_without_creating_intermediate_years(self):
        sim = self._simulation()
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            None,
            sim.hitboxes["year:current"].center,
        )
        for character in "2412":
            sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": 0, "unicode": character}))
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN, "unicode": ""}))

        self.assertEqual(2412, sim.year)
        self.assertEqual([], sim.structure.get("formation_snapshots", []))

    def test_creation_name_field_can_insert_text_at_clicked_position(self):
        sim = self._simulation()
        self.assertTrue(sim.begin_creation())
        sim.creation_buffer = "Battalion"
        sim.creation_cursor = len(sim.creation_buffer)
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)
        name_field = sim.hitboxes["creation:name"]
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            None,
            (name_field.x + 10, name_field.centery),
        )
        for character in "1st ":
            sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": 0, "unicode": character}))

        self.assertEqual("1st Battalion", sim.creation_buffer)
        self.assertEqual(4, sim.creation_cursor)

    def test_blueprint_editor_records_only_actual_changes_by_year(self):
        entities = {
            "form_blueprint": {
                "id": "form_blueprint", "type": "formation", "_dataset": "formations",
                "name": "Infantry Group", "formation_kind": "blueprint", "blueprint_items": [],
            },
            "item_rifle": {
                "id": "item_rifle", "type": "item", "_dataset": "items", "name": "Rifle",
            },
        }

        def set_literal(entity_id, field, value, persist=True):
            entities[entity_id][field] = value

        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
            set_literal=set_literal,
        )
        sim = FormationSimulation(world_model=world, formation_id="form_blueprint")

        self.assertFalse(sim._update_blueprint_fields({"personnel": 0}))
        self.assertTrue(sim._update_blueprint_fields({"personnel": 100}))
        self.assertTrue(sim._update_blueprint_fields({"personnel": 200}))
        self.assertEqual(1, len(entities["form_blueprint"]["formation_snapshots"]))
        self.assertEqual(2400, entities["form_blueprint"]["formation_snapshots"][0]["start_year"])

        sim.set_year(2401)
        self.assertTrue(sim._update_blueprint_fields({"personnel": 300}))
        self.assertEqual(
            [2400, 2401],
            [entry["start_year"] for entry in entities["form_blueprint"]["formation_snapshots"]],
        )

    def test_creation_menu_supports_new_blueprint_and_from_blueprint(self):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations", "name": "Root",
                "blueprints": ["form_blueprint"],
            },
            "form_blueprint": {
                "id": "form_blueprint", "type": "formation", "_dataset": "formations", "name": "Infantry Group",
                "formation_kind": "blueprint", "blueprint_items": [], "personnel": 100,
            },
            "fac_a": {
                "id": "fac_a", "type": "faction", "_dataset": "factions", "name": "Faction A",
            },
        }

        class Loader:
            def persist_entity(self, entity):
                entities[entity["id"]] = entity
                return True

        def set_literal(entity_id, field, value, persist=True):
            entities[entity_id][field] = value

        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [entity for entity in entities.values() if entity.get("_dataset") == name],
            set_literal=set_literal,
            loader=Loader(),
            mark_repository_changed=lambda: None,
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        self.assertTrue(sim.open_creation_menu())
        self.assertTrue(sim.choose_creation_mode("new_blueprint"))
        self.assertTrue(sim.faction_selection_active)
        self.assertTrue(sim.choose_faction("fac_a"))
        sim.creation_buffer = "Armored Group"
        self.assertTrue(sim.commit_creation())
        new_blueprint = entities["form_armored_group"]
        self.assertEqual("blueprint", new_blueprint["formation_kind"])
        self.assertIn("form_armored_group", entities["form_root"]["blueprints"])

        sim.structure = sim._build_structure()
        sim.selected_node_id = "form_root"
        self.assertTrue(sim.open_creation_menu())
        self.assertTrue(sim.choose_creation_mode("from_blueprint"))
        self.assertTrue(sim.choose_blueprint("form_blueprint"))
        self.assertTrue(sim.faction_selection_active)
        self.assertTrue(sim.choose_faction("fac_a"))
        sim.creation_buffer = "Infantry Group Realization"
        self.assertTrue(sim.commit_creation())
        realization = entities["form_infantry_group_realization"]
        self.assertEqual("realization", realization["formation_kind"])
        self.assertEqual("form_blueprint", realization["blueprint"])

    def test_new_formation_requires_searchable_faction_distinct_from_structural_parent(self):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations", "name": "Root",
                "faction": "fac_a",
            },
            "fac_a": {
                "id": "fac_a", "type": "faction", "_dataset": "factions", "name": "Faction A",
            },
            "fac_b": {
                "id": "fac_b", "type": "faction", "_dataset": "factions", "name": "Test Military Faction B",
            },
        }

        class Loader:
            def persist_entity(self, entity):
                entities[entity["id"]] = entity
                return True

        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [
                entity for entity in entities.values() if entity.get("_dataset") == name
            ],
            loader=Loader(),
            mark_repository_changed=lambda: None,
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        self.assertTrue(sim.open_creation_menu())
        self.assertTrue(sim.choose_creation_mode("new_formation"))
        self.assertTrue(sim.faction_selection_active)

        for character in "military faction b":
            sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": 0, "unicode": character}))
        self.assertEqual(["fac_b"], [faction["id"] for faction in sim._filtered_faction_options()])
        self.assertTrue(sim.choose_faction("fac_b"))
        sim.creation_buffer = "Independent Force"
        self.assertTrue(sim.commit_creation())
        self.assertEqual("fac_b", entities["form_independent_force"]["faction"])

    def test_blueprint_organization_manager_exposes_child_navigation_and_add_action(self):
        entities = {
            "form_blueprint": {
                "id": "form_blueprint", "type": "formation", "_dataset": "formations",
                "name": "Parent Blueprint", "formation_kind": "blueprint",
                "faction": "fac_a", "parents": [],
            },
            "form_child_blueprint": {
                "id": "form_child_blueprint", "type": "formation", "_dataset": "formations",
                "name": "Child Blueprint", "formation_kind": "blueprint",
                "faction": "fac_a", "parents": ["form_blueprint"], "blueprint_items": [],
            },
            "fac_a": {
                "id": "fac_a", "type": "faction", "_dataset": "factions", "name": "Faction A",
            },
        }
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [
                entity for entity in entities.values() if entity.get("_dataset") == name
            ],
        )
        sim = FormationSimulation(world_model=world, formation_id="form_blueprint")
        sim.blueprint_editor_section = "organization"
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)

        self.assertIn("blueprint:organization:add", sim.hitboxes)
        self.assertIn("blueprint:organization:form_child_blueprint", sim.hitboxes)
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            None,
            sim.hitboxes["blueprint:organization:form_child_blueprint"].center,
        )
        self.assertEqual(
            "form_child_blueprint",
            sim.consume_pending_navigation_action()["entity_id"],
        )

    def test_parent_button_requests_parent_formation_tab(self):
        entities = {
            "form_parent": {
                "id": "form_parent", "type": "formation", "_dataset": "formations", "name": "Parent"
            },
            "form_child": {
                "id": "form_child", "type": "formation", "_dataset": "formations", "name": "Child",
                "parents": ["form_parent"],
            },
        }
        world = SimpleNamespace(get_entity=entities.get, get_dataset=lambda name: list(entities.values()))
        sim = FormationSimulation(world_model=world, formation_id="form_child")
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)

        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}),
            camera=None,
            screen_pos=sim.hitboxes["parent"].center,
        )

        self.assertEqual(
            {"id": "knowledge_launch_mode", "entity_id": "form_parent", "launch_mode": "formation"},
            sim.consume_pending_navigation_action(),
        )

    def test_dragging_sibling_reorders_and_persists_order_when_supported(self):
        entities = {
            "form_parent": {
                "id": "form_parent", "type": "formation", "_dataset": "formations", "name": "Parent",
            },
            "form_a": {
                "id": "form_a", "type": "formation", "_dataset": "formations", "name": "A",
                "parents": ["form_parent"], "formation_order": 0,
            },
            "form_b": {
                "id": "form_b", "type": "formation", "_dataset": "formations", "name": "B",
                "parents": ["form_parent"], "formation_order": 1,
            },
        }
        order_updates = []
        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: list(entities.values()),
            set_literal=lambda entity_id, field, value, persist=True: order_updates.append((entity_id, field, value)),
        )
        sim = FormationSimulation(world_model=world, formation_id="form_parent")
        screen = pygame.Surface((1200, 800))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)
        a_pos = sim.hitboxes["tree:form_a"].center
        b_pos = sim.hitboxes["tree:form_b"].center

        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, a_pos)
        sim.handle_pointer_motion(
            pygame.event.Event(pygame.MOUSEMOTION, {"buttons": (1, 0, 0)}),
            None,
            (b_pos[0], b_pos[1] + 12),
        )
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1}), None, b_pos)

        self.assertEqual(["B", "A"], [child["label"] for child in sim.structure["children"]])
        self.assertEqual({"form_a", "form_b"}, {update[0] for update in order_updates})

    def test_clicking_ontology_child_requests_its_formation_tab(self):
        entities = {
            "form_root": {
                "id": "form_root",
                "type": "formation",
                "_dataset": "formations",
                "name": "Root Formation",
                "offspring": [{"id": "form_child"}],
            },
            "form_child": {
                "id": "form_child",
                "type": "formation",
                "_dataset": "formations",
                "name": "1st Battalion",
            },
        }

        world = SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: list(entities.values()),
        )
        sim = FormationSimulation(world_model=world, formation_id="form_root")
        screen = pygame.Surface((1200, 800))
        view = SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))
        FormationRenderer(view).draw(screen, sim)

        child_pos = sim.hitboxes["tree:form_child"].center
        for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            sim.handle_pointer_event(
                pygame.event.Event(event_type, {"button": 1}),
                camera=None,
                screen_pos=child_pos,
            )

        self.assertEqual(
            {
                "id": "knowledge_launch_mode",
                "entity_id": "form_child",
                "launch_mode": "formation",
            },
            sim.consume_pending_navigation_action(),
        )


if __name__ == "__main__":
    unittest.main()
