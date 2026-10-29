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
                "doctrine": "Rough Terrain Reconnaissance",
                "roster_slots": [{"id": "rifle", "kind": "personnel", "role": "Rifleman", "count": 5}],
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
        self.assertEqual("Rough Terrain Reconnaissance", realization["doctrine"])
        self.assertEqual(5, realization["roster_slots"][0]["count"])

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


class SquadDesignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    def _world(self, entities):
        def set_literal(entity_id, field, value, persist=True):
            entities[entity_id][field] = value

        def persist_entity(entity, **_kwargs):
            entities[entity["id"]] = entity
            return True

        return SimpleNamespace(
            get_entity=entities.get,
            get_dataset=lambda name: [
                e for e in entities.values() if e.get("_dataset") == name
            ],
            set_literal=set_literal,
            loader=SimpleNamespace(persist_entity=persist_entity),
            mark_repository_changed=lambda: None,
        )

    def _sim(self, extra=None):
        entities = {
            "form_root": {
                "id": "form_root", "type": "formation", "_dataset": "formations",
                "name": "GGO Sol Marines", "faction": "fac_x", "formation_kind": "realization",
            },
            "fac_x": {"id": "fac_x", "type": "faction", "_dataset": "factions", "name": "Faction X"},
        }
        entities.update(extra or {})
        sim = FormationSimulation(world_model=self._world(entities), formation_id="form_root")
        sim.set_workspace_mode("design")
        return sim, entities

    def _render(self, sim):
        screen = pygame.Surface((1400, 900))
        FormationRenderer(SimpleNamespace(default_font=pygame.font.SysFont("consolas", 16))).draw(screen, sim)
        return sim.hitboxes

    def test_spawns_personnel_and_vehicle_roster_slots(self):
        sim, entities = self._sim()
        p = sim.add_roster_slot("personnel", role="Rifleman")
        v = sim.add_roster_slot("vehicle", role="Landing APC")
        self.assertIsNotNone(p)
        slots = entities["form_root"]["roster_slots"]
        self.assertEqual([s["kind"] for s in slots], ["personnel", "vehicle"])
        self.assertEqual(sim.get_design_model()["slots"][1]["role"], "Landing APC")

    def test_marquee_selects_slots_within_the_container(self):
        sim, _ = self._sim()
        sim.add_roster_slot("personnel")
        sim.add_roster_slot("personnel")
        hitboxes = self._render(sim)
        slot_rects = [r for k, r in hitboxes.items() if k.startswith("slot:")]
        canvas = hitboxes["design:canvas"]
        origin = (canvas.x + 2, canvas.y + 2)
        far = (max(r.right for r in slot_rects) + 5, max(r.bottom for r in slot_rects) + 5)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, origin)
        sim.handle_pointer_motion(pygame.event.Event(pygame.MOUSEMOTION, {"buttons": (1, 0, 0)}), None, far)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1}), None, far)
        self.assertEqual(len(sim.canvas_selection), 2)

    def test_shift_click_toggles_slot_selection(self):
        sim, _ = self._sim()
        sim.add_roster_slot("personnel")
        hitboxes = self._render(sim)
        key = next(k for k in hitboxes if k.startswith("slot:"))
        sim.toggle_canvas_selection(key, additive=True)
        self.assertIn(key, sim.canvas_selection)
        sim.toggle_canvas_selection(key, additive=True)
        self.assertNotIn(key, sim.canvas_selection)

    def test_group_selection_creates_child_and_moves_selected_slots(self):
        sim, entities = self._sim()
        s1 = sim.add_roster_slot("personnel", role="Team Leader")
        sim.add_roster_slot("personnel", role="Rifleman")
        sim.canvas_selection = {f"slot:form_root:{s1}"}
        new_id = sim.group_selection("1st Fire Team")
        self.assertIsNotNone(new_id)
        child = entities[new_id]
        self.assertEqual(child["parents"], ["form_root"])
        self.assertEqual([s["role"] for s in child["roster_slots"]], ["Team Leader"])
        self.assertEqual([s["role"] for s in entities["form_root"]["roster_slots"]], ["Rifleman"])

    def test_dragging_a_group_box_onto_another_nests_it(self):
        extra = {
            "form_a": {"id": "form_a", "type": "formation", "_dataset": "formations",
                       "name": "Alpha", "parents": ["form_root"]},
            "form_b": {"id": "form_b", "type": "formation", "_dataset": "formations",
                       "name": "Bravo", "parents": ["form_root"]},
        }
        sim, entities = self._sim(extra)
        hitboxes = self._render(sim)
        a = hitboxes["group:form_a"].center
        b = hitboxes["group:form_b"].center
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, a)
        sim.handle_pointer_motion(pygame.event.Event(pygame.MOUSEMOTION, {"buttons": (1, 0, 0)}),
                                  None, (b[0] + 20, b[1] + 20))
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1}), None, b)
        self.assertEqual(entities["form_a"]["parents"], ["form_b"])

    def test_doctrine_cycle_writes_the_doctrine_string(self):
        sim, entities = self._sim()
        sim.cycle_group_doctrine("form_root")
        self.assertEqual(entities["form_root"]["doctrine"], "assault")
        sim.cycle_group_doctrine("form_root")
        self.assertEqual(entities["form_root"]["doctrine"], "defensive")

    def test_design_output_has_no_positional_fields(self):
        sim, entities = self._sim()
        s1 = sim.add_roster_slot("personnel")
        sim.canvas_selection = {f"slot:form_root:{s1}"}
        new_id = sim.group_selection("Squad")
        for entity in entities.values():
            for banned in ("x", "y", "canvas_x", "canvas_y", "position", "layout"):
                self.assertNotIn(banned, entity)
        # the durable child carries only structure
        self.assertLessEqual(
            set(entities[new_id]) - {
                "id", "type", "_dataset", "name", "pretty_name", "entry_status",
                "formation_kind", "parents", "faction", "roster_slots", "start_year",
            },
            set(),
        )

    def test_double_click_group_descends_into_it(self):
        extra = {
            "form_a": {"id": "form_a", "type": "formation", "_dataset": "formations",
                       "name": "Alpha", "parents": ["form_root"]},
        }
        sim, _ = self._sim(extra)
        hitboxes = self._render(sim)
        pos = hitboxes["group:form_a"].center
        for _ in range(2):
            sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, pos)
            sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1}), None, pos)
        self.assertEqual(sim.get_design_model()["container_id"], "form_a")

    def test_vehicle_assignment_tracks_catalog_crew_and_custom_override(self):
        sim, entities = self._sim({
            "heli": {"id": "heli", "type": "vehicle", "_dataset": "vehicles",
                     "name": "Mountain Helicopter", "crew_roles": [
                         {"role": "Pilot", "count": 1},
                         {"role": "Copilot", "count": 1},
                         {"role": "Crew", "count": 4},
                     ]},
        })
        self.assertTrue(sim.open_design_catalog("form_root", "vehicle"))
        self.assertTrue(sim.choose_design_catalog_item("heli"))
        slot = entities["form_root"]["roster_slots"][0]
        self.assertEqual("heli", slot["vehicle_id"])
        self.assertNotIn("crew_roles", slot)
        self.assertTrue(sim.start_design_edit("form_root", "count", slot["id"]))
        sim.design_edit_buffer = "2"
        self.assertTrue(sim.commit_design_edit())
        self.assertEqual((0, 2, 12), sim.design_direct_totals(sim.structure))
        self.assertEqual(2, sim.design_crew_coverage(sim.structure)[0]["required"])
        self.assertEqual(2, sim.design_crew_coverage(sim.structure)[0]["missing"])
        sim.add_roster_slot("personnel", role="Pilot", count=2)
        self.assertEqual(0, sim.design_crew_coverage(sim.structure)[0]["missing"])
        entities["heli"]["crew_roles"][0]["count"] = 2
        self.assertEqual((2, 2, 14), sim.design_direct_totals(sim.structure))
        self.assertTrue(sim.start_design_edit("form_root", "crew_roles", slot["id"]))
        sim.design_edit_buffer = "Pilot:1, Copilot:1, Crew:4"
        self.assertTrue(sim.commit_design_edit())
        self.assertEqual((2, 2, 12), sim.design_direct_totals(sim.structure))

    def test_parent_and_child_assignments_and_doctrine_are_independent(self):
        sim, entities = self._sim({
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Mountain Platoon", "parents": ["form_root"]},
            "item_rope": {"id": "item_rope", "type": "item", "_dataset": "items", "name": "Climbing Rope"},
        })
        sim.add_roster_slot("personnel", role="Maintenance", container_id="form_root")
        sim.add_roster_slot("personnel", role="Mountaineer", count=15, container_id="form_child")
        self.assertEqual((15, 0, 0), sim.design_direct_totals(sim._find_node("form_child")))
        self.assertEqual("GGO Sol Marines", sim.design_parent_support("form_child")[0])
        self.assertTrue(sim.start_design_edit("form_child", "doctrine"))
        sim.design_edit_buffer = "Rough Terrain Reconnaissance"
        self.assertTrue(sim.commit_design_edit())
        self.assertEqual("Rough Terrain Reconnaissance", entities["form_child"]["doctrine"])
        self.assertFalse(entities["form_root"].get("doctrine"))
        self.assertTrue(sim.open_design_catalog("form_child", "equipment"))
        self.assertTrue(sim.choose_design_catalog_item("item_rope"))
        self.assertEqual(["item_rope"], entities["form_child"]["equipment_items"])
        self.assertNotIn("equipment_items", entities["form_root"])

    def test_expanded_child_has_direct_design_controls_and_can_collapse(self):
        sim, _entities = self._sim({
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Child", "parents": ["form_root"],
                           "roster_slots": [{"id": "scout", "kind": "personnel", "role": "Scout", "count": 2}]},
        })
        hitboxes = self._render(sim)
        self.assertIn("design:add:role:form_child", hitboxes)
        self.assertIn("design:add:vehicle:form_child", hitboxes)
        self.assertIn("design:add:equipment:form_child", hitboxes)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None,
                                 hitboxes["design:collapse:form_child"].center)
        self.assertIn("form_child", sim.design_collapsed)
        hitboxes = self._render(sim)
        self.assertNotIn("slot:form_child:scout", hitboxes)
        self.assertIn("design:add:role:form_child", hitboxes)
        self.assertIn("design:collapse:form_child", hitboxes)

    def test_blueprint_role_and_doctrine_edits_record_view_year(self):
        sim, entities = self._sim({
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Child Blueprint", "formation_kind": "blueprint",
                           "parents": ["form_root"]},
        })
        slot_id = sim.add_roster_slot("personnel", role="Scout", container_id="form_child")
        self.assertIsNotNone(slot_id)
        self.assertTrue(sim.start_design_edit("form_child", "doctrine"))
        sim.design_edit_buffer = "Mountain reconnaissance"
        self.assertTrue(sim.commit_design_edit())
        snapshots = entities["form_child"]["formation_snapshots"]
        self.assertEqual(1, len(snapshots))
        self.assertEqual(2400, snapshots[0]["start_year"])
        self.assertEqual("Mountain reconnaissance", snapshots[0]["state"]["doctrine"])
        self.assertEqual("Scout", snapshots[0]["state"]["roster_slots"][0]["role"])

    def test_parent_support_is_visible_when_child_is_opened_as_root(self):
        entities = {
            "form_parent": {"id": "form_parent", "type": "formation", "_dataset": "formations",
                            "name": "Regiment", "roster_slots": [
                                {"id": "maint", "kind": "personnel", "role": "Maintenance", "count": 6}]},
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Platoon", "parents": ["form_parent"]},
        }
        sim = FormationSimulation(world_model=self._world(entities), formation_id="form_child")
        self.assertEqual(("Regiment", ["Maintenance"]), sim.design_parent_support("form_child"))

    def test_visual_symbol_selects_and_count_badge_edits_its_slot(self):
        sim, entities = self._sim()
        slot_id = sim.add_roster_slot("personnel", role="Scout", count=3)
        hitboxes = self._render(sim)
        key = f"slot:form_root:{slot_id}"
        card = hitboxes[key]
        middle = (card.centerx, card.centery)
        sim.handle_pointer_motion(pygame.event.Event(pygame.MOUSEMOTION, {"buttons": (0, 0, 0)}),
                                  None, middle)
        self.assertEqual(key, sim.design_hover_key)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, middle)
        self.assertIn(key, sim.canvas_selection)
        count = hitboxes[f"design:edit:form_root:count:{slot_id}"].center
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, count)
        self.assertEqual(("form_root", "count", slot_id), sim.design_edit)
        sim.design_edit_buffer = "5"
        self.assertTrue(sim.commit_design_edit())
        self.assertEqual(5, entities["form_root"]["roster_slots"][0]["count"])

    def test_clickable_subordinate_creation_inherits_owner_and_keeps_generic_label(self):
        sim, entities = self._sim()
        self.assertTrue(sim.begin_structure_child("form_root"))
        self.assertTrue(sim.creation_active)
        self.assertEqual("fac_x", sim.creation_faction_id)
        sim.creation_buffer = "Outer Trade Flotilla"
        self.assertTrue(sim.commit_creation())
        child = entities["form_outer_trade_flotilla"]
        self.assertEqual("Outer Trade Flotilla", child["name"])
        self.assertEqual(["form_root"], child["parents"])
        self.assertEqual("fac_x", child["faction"])

    def test_group_command_uses_selected_child_roster_as_its_source(self):
        sim, entities = self._sim({
            "form_convoy": {"id": "form_convoy", "type": "formation", "_dataset": "formations",
                            "name": "Convoy", "parents": ["form_root"], "faction": "fac_x",
                            "roster_slots": [
                                {"id": "master", "kind": "personnel", "role": "Ship Master", "count": 1},
                                {"id": "ship", "kind": "vehicle", "role": "Merchant Vessel", "count": 3},
                            ]},
        })
        sim.canvas_selection = {"slot:form_convoy:master", "slot:form_convoy:ship"}
        self.assertTrue(sim.begin_group_naming())
        sim.design_group_name = "Escort Section"
        sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN, "unicode": ""}))
        self.assertFalse(sim.design_group_naming)
        self.assertEqual(["form_convoy"], entities["form_escort_section"]["parents"])
        self.assertEqual(2, len(entities["form_escort_section"]["roster_slots"]))
        self.assertEqual([], entities["form_convoy"]["roster_slots"])

    def test_place_selected_moves_slots_and_command_groups_without_changing_owner(self):
        sim, entities = self._sim({
            "form_a": {"id": "form_a", "type": "formation", "_dataset": "formations",
                       "name": "A", "parents": ["form_root"], "faction": "fac_x",
                       "roster_slots": [{"id": "freighter", "kind": "vehicle", "role": "Freighter",
                                         "vehicle_id": "veh_freighter", "count": 2}]},
            "form_b": {"id": "form_b", "type": "formation", "_dataset": "formations",
                       "name": "B", "parents": ["form_root"], "faction": "fac_x"},
            "form_c": {"id": "form_c", "type": "formation", "_dataset": "formations",
                       "name": "C", "parents": ["form_a"], "faction": "fac_x"},
        })
        sim.canvas_selection = {"slot:form_a:freighter", "group:form_c"}
        self.assertTrue(sim.move_selection_to("form_b"))
        self.assertEqual([], entities["form_a"]["roster_slots"])
        self.assertEqual("veh_freighter", entities["form_b"]["roster_slots"][0]["vehicle_id"])
        self.assertEqual(["form_b"], entities["form_c"]["parents"])
        self.assertEqual("fac_x", entities["form_c"]["faction"])
        self.assertEqual("fac_x", entities["form_b"]["faction"])

    def test_parent_picker_searches_ancestry_and_rejects_cycle(self):
        sim, entities = self._sim({
            "form_trade": {"id": "form_trade", "type": "formation", "_dataset": "formations",
                           "name": "Trade Fleet", "parents": ["form_root"], "faction": "fac_x"},
            "form_convoy": {"id": "form_convoy", "type": "formation", "_dataset": "formations",
                            "name": "Convoy", "parents": ["form_trade"], "faction": "fac_x"},
            "form_other": {"id": "form_other", "type": "formation", "_dataset": "formations",
                           "name": "Other", "parents": ["form_root"], "faction": "fac_x"},
        })
        self.assertTrue(sim.open_target_picker("move_group", "form_trade"))
        self.assertNotIn("form_convoy", {option["id"] for option in sim.design_target_options()})
        self.assertFalse(sim.choose_design_target("form_convoy"))
        sim.design_target_query = "Convoy"
        self.assertEqual([], sim.design_target_options())
        self.assertTrue(sim.open_target_picker("move_group", "form_other"))
        sim.design_target_query = "Trade Fleet"
        self.assertEqual({"form_trade", "form_convoy"},
                         {option["id"] for option in sim.design_target_options()})
        self.assertTrue(sim.choose_design_target("form_convoy"))
        self.assertEqual(["form_convoy"], entities["form_other"]["parents"])
        self.assertEqual("fac_x", entities["form_other"]["faction"])

    def test_structure_menu_clicks_rename_and_owner_change_without_reparenting(self):
        sim, entities = self._sim({
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Child", "parents": ["form_root"], "faction": "fac_x"},
            "fac_y": {"id": "fac_y", "type": "faction", "_dataset": "factions", "name": "Merchant Guild"},
        })
        self.assertTrue(sim.open_structure_menu("form_child"))
        hitboxes = self._render(sim)
        self.assertIn("design:structure:action:rename:form_child", hitboxes)
        point = hitboxes["design:structure:action:rename:form_child"].center
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None, point)
        self.assertEqual(("form_child", "name", None), sim.design_edit)
        sim.design_edit_buffer = "North Atlantic Convoy"
        self.assertTrue(sim.commit_design_edit())
        self.assertEqual("North Atlantic Convoy", entities["form_child"]["pretty_name"])
        self.assertEqual(["form_root"], entities["form_child"]["parents"])
        self.assertTrue(sim.open_design_owner_picker("form_child"))
        sim.design_owner_query = "merchant"
        self.assertEqual(["fac_y"], [option["id"] for option in sim.design_owner_options()])
        self.assertTrue(sim.choose_design_owner("fac_y"))
        self.assertEqual("fac_y", entities["form_child"]["faction"])
        self.assertEqual("fac_x", entities["form_root"]["faction"])
        self.assertEqual(["form_root"], entities["form_child"]["parents"])

    def test_reorder_and_fold_commands_keep_large_structure_navigable(self):
        children = {
            f"form_unit_{index}": {
                "id": f"form_unit_{index}", "type": "formation", "_dataset": "formations",
                "name": f"Unit {index}", "parents": ["form_root"], "faction": "fac_x",
                "formation_order": index,
            }
            for index in range(120)
        }
        sim, entities = self._sim(children)
        self._render(sim)
        canvas = sim.hitboxes["design:canvas"]
        self.assertGreater(sim.design_content_height, canvas.height)
        self.assertLess(len([key for key in sim.hitboxes if key.startswith("design:collapse:")]), 15)
        self.assertTrue(sim.fold_descendants("form_root"))
        self.assertEqual(120, len(sim.design_collapsed))
        self.assertTrue(sim.fold_descendants("form_root", collapsed=False))
        self.assertFalse(sim.design_collapsed)
        self.assertTrue(sim.shift_group_order("form_unit_1", -1))
        self.assertEqual("form_unit_1", sim.structure["children"][0]["id"])
        self.assertEqual(0, entities["form_unit_1"]["formation_order"])

    def test_command_restructure_updates_blueprint_organization_snapshot(self):
        sim, entities = self._sim({
            "form_blue": {"id": "form_blue", "type": "formation", "_dataset": "formations",
                          "name": "Fleet Blueprint", "parents": ["form_root"], "faction": "fac_x",
                          "formation_kind": "blueprint"},
            "form_a": {"id": "form_a", "type": "formation", "_dataset": "formations",
                       "name": "A", "parents": ["form_blue"], "faction": "fac_x",
                       "formation_kind": "blueprint", "formation_order": 0},
            "form_b": {"id": "form_b", "type": "formation", "_dataset": "formations",
                       "name": "B", "parents": ["form_blue"], "faction": "fac_x",
                       "formation_kind": "blueprint", "formation_order": 1},
        })
        self.assertTrue(sim.shift_group_order("form_b", -1))
        self.assertEqual(["form_b", "form_a"],
                         entities["form_blue"]["formation_snapshots"][0]["state"]["organization"])
        self.assertTrue(sim.nest_group("form_a", "form_b"))
        self.assertEqual(["form_b"],
                         entities["form_blue"]["formation_snapshots"][0]["state"]["organization"])
        self.assertEqual(["form_a"],
                         entities["form_b"]["formation_snapshots"][0]["state"]["organization"])

    def test_top_add_commands_follow_the_selected_formation(self):
        sim, entities = self._sim({
            "form_child": {"id": "form_child", "type": "formation", "_dataset": "formations",
                           "name": "Child", "parents": ["form_root"], "faction": "fac_x"},
        })
        hitboxes = self._render(sim)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None,
                                 hitboxes["group:form_child"].center)
        self.assertEqual("form_child", sim.get_design_action_target_id())
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None,
                                 hitboxes["design:add_personnel"].center)
        self.assertEqual("form_child", sim.design_edit[0])
        self.assertEqual("New role", entities["form_child"]["roster_slots"][0]["role"])
        self.assertNotIn("roster_slots", entities["form_root"])

    def test_attach_existing_formation_assembles_cross_root_tree_without_owner_change(self):
        sim, entities = self._sim({
            "fac_y": {"id": "fac_y", "type": "faction", "_dataset": "factions", "name": "Traders"},
            "form_external": {"id": "form_external", "type": "formation", "_dataset": "formations",
                              "name": "Independent Convoy", "faction": "fac_y"},
            "form_escort": {"id": "form_escort", "type": "formation", "_dataset": "formations",
                            "name": "Escort", "parents": ["form_external"], "faction": "fac_y"},
        })
        self.assertTrue(sim.open_design_attach_picker("form_root"))
        sim.design_attach_query = "Independent"
        self.assertEqual(["form_external"], [option["id"] for option in sim.design_attach_options()])
        hitboxes = self._render(sim)
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1}), None,
                                 hitboxes["design:attach:item:form_external"].center)
        self.assertEqual(["form_root"], entities["form_external"]["parents"])
        self.assertEqual("fac_y", entities["form_external"]["faction"])
        self.assertIsNotNone(sim._find_node("form_escort"))
        self.assertTrue(sim.open_design_attach_picker("form_escort"))
        self.assertNotIn("form_root", {option["id"] for option in sim.design_attach_options()})
        self.assertNotIn("form_external", {option["id"] for option in sim.design_attach_options()})
        self.assertFalse(sim.choose_design_attach("form_root"))


if __name__ == "__main__":
    unittest.main()
