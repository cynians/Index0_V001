import unittest

import pygame

from simulations.person.person_simulation import PersonSimulation


class _WorldStub:
    def __init__(self, entities=None):
        self.entities = dict(entities or {})

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class _IdentityCamera:
    """screen_to_world is the identity function -- pass world coords directly as screen_pos."""

    @staticmethod
    def screen_to_world(screen_pos):
        return float(screen_pos[0]), float(screen_pos[1])


class PersonSimulationTests(unittest.TestCase):
    def setUp(self):
        self.person = {
            "id": "person_test",
            "type": "person",
            "pretty_name": "Test Person",
            "affiliated_institutions": ["institution_test_lab"],
            "knowledge_records": [{"entity": "recipe_simple_cooked_meal", "interest": 0.8}],
        }
        fixtures = {
            self.person["id"]: self.person,
            "institution_test_lab": {"id": "institution_test_lab", "type": "institution"},
            "item_food_ingredients": {
                "id": "item_food_ingredients", "type": "item",
                "pretty_name": "Meal Ingredients",
                "ownership_records": ["ownership_test_ingredients"],
            },
            "item_cooked_meal": {
                "id": "item_cooked_meal", "type": "item",
                "consumable": True, "food_satiation": 58,
            },
            "recipe_simple_cooked_meal": {
                "id": "recipe_simple_cooked_meal", "type": "recipe", "pretty_name": "Simple Meal Recipe",
                "input_requirements": [{"item": "item_food_ingredients", "quantity": 1}],
                "output_yields": [{"item": "item_cooked_meal", "quantity": 1}],
                "input_items": ["item_food_ingredients"], "output_items": ["item_cooked_meal"],
                "required_technologies": ["tech_cooking", "tech_electric_oven"],
                "required_components": ["component_kitchen_sink", "component_electric_oven"],
            },
            "location_person_test_pantry": {
                "id": "location_person_test_pantry", "type": "location",
                "inventory_items": [{"item": "item_food_ingredients", "quantity": 6}],
                "ownership_records": ["ownership_test_ingredients"],
            },
            "location_person_test_kitchen": {
                "id": "location_person_test_kitchen", "type": "location",
                "ownership_records": ["ownership_test_kitchen"],
            },
            "producer_person_test_kitchen": {
                "id": "producer_person_test_kitchen", "type": "producer",
                "production_technologies": ["tech_cooking", "tech_electric_oven"],
                "assigned_components": ["component_kitchen_sink", "component_electric_oven"],
                "production_lines": [{
                    "product_id": "item_cooked_meal",
                    "recipe_ids": ["recipe_simple_cooked_meal"],
                    "employed_technology_ids": ["tech_cooking", "tech_electric_oven"],
                    "assigned_component_ids": ["component_kitchen_sink", "component_electric_oven"],
                }],
            },
            "ownership_test_ingredients": {
                "id": "ownership_test_ingredients", "type": "ownership",
                "owner_entities": ["institution_test_lab"],
                "owned_assets": ["item_food_ingredients", "location_person_test_pantry"],
                "permitted_users": ["institution_test_lab"],
            },
            "ownership_test_kitchen": {
                "id": "ownership_test_kitchen", "type": "ownership",
                "owner_entities": ["institution_test_lab"], "owned_assets": ["location_person_test_kitchen"],
                "permitted_users": ["institution_test_lab"],
            },
        }
        self.world = _WorldStub(fixtures)
        self.sim = PersonSimulation(self.world, self.person["id"], year=2400)

    def test_starts_on_six_point_map_with_autonomous_queue(self):
        self.assertEqual("autonomous", self.sim.control_mode)
        self.assertEqual(
            {"bed", "food", "kitchen", "job", "target", "lumber_dropoff", "lumber_pickup"},
            set(self.sim.test_points),
        )
        self.assertGreaterEqual(len(self.sim.task_queue), 2)
        self.assertEqual("food", self.sim.task_queue[0]["point_id"])

    def test_sparse_stub_person_is_flagged_for_character_creation(self):
        # self.person authors identity, social, and knowledge but no
        # personality/motivation/site data -- readiness should land as
        # "sparse", not silently pass as a fully authored character.
        self.assertEqual("sparse", self.sim.character_readiness["tier"])
        self.assertTrue(self.sim.needs_character_creation)
        payload = self.sim.get_person_render_payload()
        self.assertTrue(payload["needs_character_creation"])
        self.assertEqual("sparse", payload["character_readiness_tier"])

    def test_site_less_person_spawns_in_void_not_the_lumber_test_site(self):
        # self.person has no simulation_site and no associated_locations
        # with simulation_points -- worldgen has nothing to place them in
        # yet, so they must not silently land inside the authored lumber
        # site's geometry.
        self.assertTrue(self.sim.in_void)
        self.assertIsNone(self.sim.site_entity_id)
        self.assertEqual({}, self.sim.site_entity)
        self.assertEqual([], self.sim.site_structures)
        self.assertEqual([], self.sim.wall_segments)
        self.assertEqual([], self.sim.site_people)
        payload = self.sim.get_person_render_payload()
        self.assertTrue(payload["in_void"])
        self.assertEqual([], payload["structures"])
        self.assertEqual([], payload["wall_segments"])

    def test_authored_site_clears_void_state(self):
        self.world.entities["location_authored_site"] = {
            "id": "location_authored_site", "type": "location",
            "bounds": {"min_x": -5, "max_x": 5, "min_y": -5, "max_y": 5},
            "simulation_points": [{"id": "bed", "position": [1.0, 1.0]}],
        }
        self.person["simulation_site"] = "location_authored_site"
        sim = PersonSimulation(self.world, self.person["id"], year=2400)
        self.assertFalse(sim.in_void)
        self.assertEqual("location_authored_site", sim.site_entity_id)

    def test_asset_palette_excludes_duty_only_points(self):
        # lumber_dropoff/lumber_pickup are duty-only (no tags): the rudimentary
        # placer only ever offers the player-facing point kinds.
        self.assertEqual(
            {"bed", "food", "kitchen", "job", "target"},
            {entry["id"] for entry in self.sim.asset_palette},
        )
        for entry in self.sim.asset_palette:
            self.assertNotIn("position", entry)

    def test_placement_mode_requires_void(self):
        self.world.entities["location_authored_site"] = {
            "id": "location_authored_site", "type": "location",
            "bounds": {"min_x": -5, "max_x": 5, "min_y": -5, "max_y": 5},
            "simulation_points": [{"id": "bed", "position": [1.0, 1.0]}],
        }
        self.person["simulation_site"] = "location_authored_site"
        sim = PersonSimulation(self.world, self.person["id"], year=2400)
        self.assertFalse(sim.select_asset_for_placement("bed"))
        self.assertFalse(sim.placement_mode)

    def test_number_key_selects_palette_entry_and_enters_placement_mode(self):
        self.assertTrue(self.sim.in_void)
        key_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1)
        self.sim.handle_event(key_event)
        self.assertTrue(self.sim.placement_mode)
        self.assertEqual(self.sim.asset_palette[0]["id"], self.sim.placement_selected_asset_id)

    def test_escape_cancels_placement_mode(self):
        self.sim.select_asset_for_placement("target")
        self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertFalse(self.sim.placement_mode)
        self.assertIsNone(self.sim.placement_selected_asset_id)

    def test_left_click_while_placing_moves_the_point_there(self):
        self.sim.select_asset_for_placement("target")
        click_position = (33.0, -17.0)
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=click_position)
        self.sim.handle_pointer_event(event, _IdentityCamera(), click_position)
        self.assertFalse(self.sim.placement_mode)
        self.assertEqual(click_position, self.sim.test_points["target"]["position"])
        self.assertTrue(self.sim.test_points["target"]["placed"])

    def test_right_click_while_placing_cancels_instead_of_opening_a_card(self):
        self.sim.select_asset_for_placement("target")
        original_position = tuple(self.sim.test_points["target"]["position"])
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0))
        self.sim.handle_pointer_event(event, _IdentityCamera(), (0, 0))
        self.assertFalse(self.sim.placement_mode)
        self.assertEqual(original_position, self.sim.test_points["target"]["position"])

    def test_authored_wish_tag_queues_matching_internal_task(self):
        # lumber_dropoff/lumber_pickup are duty-only (no tags) -- kitchen is
        # the only personal point outside the default food/bed/job/target
        # candidates, so it's the only point a wish can newly queue here.
        self.world.entities["wish_test_eat_with_friends"] = {
            "id": "wish_test_eat_with_friends", "type": "wish",
            "wish_type": "Eating Comfort", "task_type": "experience",
            "pretty_name": "Eat With Friends",
        }
        self.person["goals"] = ["wish_test_eat_with_friends"]
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        def goal_task_point_ids():
            return {
                task.get("point_id")
                for task in sim.internal_task_allocations
                if task.get("motive") == "goal"
            }

        self.assertEqual({"kitchen"}, goal_task_point_ids())

        # Re-evaluating the queue while the goal task is still pending must
        # not queue a duplicate copy of it.
        sim._fill_autonomous_queue()
        self.assertEqual({"kitchen"}, goal_task_point_ids())
        self.assertEqual(
            1,
            len([t for t in sim.internal_task_allocations if t.get("motive") == "goal"]),
        )

    def test_authored_wish_without_wish_type_does_not_match(self):
        # A legacy free-text wish (no wish_type field) must not resolve to
        # any tag -- it's display-only, never a matching source.
        self.person["goals"] = ["Some free-text note with no registry entry"]
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertEqual(set(), sim._goal_tags())
        self.assertEqual(
            [],
            [t for t in sim.internal_task_allocations if t.get("motive") == "goal"],
        )

    def test_authored_wish_boosts_matching_point_decision_score(self):
        self.world.entities["wish_test_visit_friends"] = {
            "id": "wish_test_visit_friends", "type": "wish",
            "wish_type": "Social Place", "task_type": "experience",
            "pretty_name": "Visit Friends",
        }
        self.person["wishes"] = ["wish_test_visit_friends"]
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        boost, reasons = sim._authored_motive_boost("target")
        self.assertEqual(18.0, boost)
        self.assertEqual(["Wish: Visit Friends"], reasons)

        no_boost, no_reasons = sim._authored_motive_boost("bed")
        self.assertEqual(0.0, no_boost)
        self.assertEqual([], no_reasons)

    def test_player_task_preempts_autonomous_work(self):
        self.sim._begin_next_queued_task()
        self.assertEqual("autonomous", self.sim.active_task["source"])

        self.assertTrue(self.sim.assign_player_task("target"))

        self.assertIsNone(self.sim.active_task)
        self.assertEqual("player", self.sim.task_queue[0]["source"])
        self.assertEqual("target", self.sim.task_queue[0]["point_id"])

    def test_direct_control_moves_to_clicked_destination(self):
        self.assertTrue(self.sim.set_control_mode("direct"))
        self.assertTrue(self.sim.command_direct_move((6.0, 0.0)))

        self.sim._update_runtime(1.0)
        self.assertAlmostEqual(3.2, self.sim.position[0], places=4)
        self.sim._update_runtime(1.0)

        self.assertEqual([6.0, 0.0], self.sim.position)
        self.assertIsNone(self.sim.direct_target)

    def test_direct_point_order_moves_and_uses_point(self):
        self.sim.set_control_mode("direct")
        self.sim.needs["food"] = 10.0
        food_position = self.sim.test_points["food"]["position"]
        self.sim.position = [food_position[0], food_position[1]]

        self.assertTrue(self.sim.command_direct_move(food_position, point_id="food"))
        for _ in range(16):
            self.sim._update_runtime(1.0)

        self.assertIsNone(self.sim.active_task)
        self.assertGreater(self.sim.needs["food"], 60.0)
        self.assertEqual(0, self.sim.runtime_inventory.get("item_cooked_meal", 0))
        self.assertEqual(5, self.sim.container_inventories["food"]["item_food_ingredients"])
        self.assertEqual(
            ["consumed as food", "produced by recipe", "consumed by recipe", "collected for recipe"],
            [entry["reason"] for entry in self.sim.inventory_history[:4]],
        )
        self.assertEqual("completed", self.sim.decision_history[0]["lifecycle_state"])

    def test_inventory_panel_tracks_recipe_items_and_nearby_stock(self):
        self.sim.set_control_mode("direct")
        food_position = self.sim.test_points["food"]["position"]
        self.sim.position = [food_position[0], food_position[1]]
        self.sim.command_direct_move(food_position, point_id="food")
        for _ in range(3):
            self.sim._update_runtime(1.0)

        model = self.sim.get_inventory_panel_model()
        self.assertEqual("Meal Ingredients", model["held_items"][0]["label"])
        self.assertEqual(1, model["held_items"][0]["quantity"])
        self.assertEqual(5, model["nearby_items"][0]["quantity"])

    def test_owned_kitchen_denies_unpermitted_person(self):
        self.person["affiliated_institutions"] = []
        self.sim.set_control_mode("direct")
        food_position = self.sim.test_points["food"]["position"]
        self.sim.position = [food_position[0], food_position[1]]
        self.sim.command_direct_move(food_position, point_id="food")

        for _ in range(12):
            self.sim._update_runtime(1.0)

        self.assertIsNone(self.sim.active_task)
        self.assertLess(self.sim.needs["food"], 52.0)
        self.assertEqual("failed", self.sim.decision_history[0]["event"])
        self.assertIn("owned by another party", self.sim.last_status)

    def test_job_point_uses_assigned_job_name(self):
        job = {
            "id": "job_farmer",
            "type": "job",
            "pretty_name": "Subsistence Farmer",
        }
        self.person["is_employed_as"] = job["id"]
        self.world.entities.update({job["id"]: job})

        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertEqual("Subsistence Farmer", sim.test_points["job"]["label"])

    def test_needs_panel_combines_live_needs_with_authored_wishes_and_goals(self):
        self.person["wishes"] = ["Share a meal"]
        self.person["goals"] = ["Build a secure home"]

        model = self.sim.get_needs_panel_model()

        self.assertEqual(5, len(model["tiers"]))
        self.assertEqual("physiological", model["tiers"][0]["id"])
        self.assertEqual("Share a meal", model["wishes"][0]["label"])
        self.assertEqual("person record", model["wishes"][0]["source"])
        self.assertEqual("Build a secure home", model["goals"][0]["label"])

    def test_personality_panel_reads_authored_big_five_and_marks_missing_axes(self):
        self.person.update({
            "big_five_openness": 72,
            "big_five_conscientiousness": 0.81,
            "big_five_extraversion": 0.34,
            "big_five_agreeableness": 0.63,
        })

        model = self.sim.get_personality_panel_model()
        axes = {axis["id"]: axis for axis in model["axes"]}

        self.assertAlmostEqual(0.72, axes["openness"]["value"])
        self.assertTrue(axes["conscientiousness"]["authored"])
        self.assertFalse(axes["neuroticism"]["authored"])
        self.assertEqual(0.5, axes["neuroticism"]["value"])
        self.assertFalse(model["all_authored"])

    def test_knowledge_panel_groups_any_card_type_and_sorts_by_interest(self):
        known_person = {"id": "person_friend", "type": "person", "pretty_name": "Close Friend"}
        known_place = {"id": "loc_harbor", "type": "location", "pretty_name": "Old Harbor"}
        known_belief = {"id": "idea_pacifism", "type": "idea", "pretty_name": "Pacifism"}
        self.world.entities.update({
            known_person["id"]: known_person,
            known_place["id"]: known_place,
            known_belief["id"]: known_belief,
        })
        self.person["knowledge_records"] = [
            {"entity": "loc_harbor", "interest": 0.42, "familiarity": 0.9},
            {"entity": "person_friend", "interest": 0.91, "familiarity": 0.8},
            {"entity": "idea_pacifism", "interest": 0.76, "conviction": 0.94},
        ]

        model = self.sim.get_knowledge_panel_model()
        grouped = {category["label"]: category["entries"] for category in model["categories"]}

        self.assertEqual("Close Friend", grouped["People"][0]["label"])
        self.assertEqual("Old Harbor", grouped["Places"][0]["label"])
        self.assertEqual("Pacifism", grouped["Worldviews & ideas"][0]["label"])
        self.assertAlmostEqual(0.94, grouped["Worldviews & ideas"][0]["conviction"])

    def test_starvation_can_preempt_strong_external_work_duty(self):
        self.person.update({
            "big_five_conscientiousness": 0.9,
            "big_five_agreeableness": 0.8,
            "big_five_neuroticism": 0.3,
        })
        self.sim.needs["food"] = 75.0
        task_id = self.sim.assign_external_task(
            "job",
            label="Stand at desk",
            issuer_label="Employer",
            duty_weight=0.9,
        )
        self.assertTrue(task_id)
        self.sim._begin_next_queued_task()
        self.assertEqual("Stand at desk", self.sim.active_task["label"])

        self.sim.needs["food"] = 2.0
        self.assertTrue(self.sim._reconsider_active_task())
        self.assertEqual("food", self.sim.active_task["point_id"])
        self.assertEqual("preempted", self.sim.decision_history[0]["event"])
        self.assertIn("Stand at desk", self.sim.decision_history[0]["displaced"])

    def test_strong_conviction_penalizes_conflicting_duty_and_suggests_alternative(self):
        belief = {
            "id": "idea_nonviolence",
            "type": "idea",
            "pretty_name": "Doctrine of Nonviolence",
            "behavioral_rules": {
                "forbids": ["kill"],
                "alternatives": {"kill": "Kitchen duty"},
            },
        }
        self.world.entities[belief["id"]] = belief
        self.person["knowledge_records"] = [{
            "entity": belief["id"],
            "interest": 0.9,
            "conviction": 0.97,
        }]
        task_id = self.sim.assign_external_task(
            "target",
            label="Fire on enemy",
            issuer_label="Conscript army",
            duty_weight=0.9,
            coercion=0.8,
            action_tags=["kill"],
            alternative_point_id="job",
        )

        model = self.sim.get_task_panel_model()
        duty = next(task for task in model["comparisons"] if task.get("id") == task_id)
        self.assertTrue(duty["conviction_conflicts"])
        self.assertIn("Kitchen duty", duty["likely_response"])
        self.assertLess(duty["decision_score"], 0.0)
        self.assertTrue(any(
            task.get("label") == "Request reassignment: Kitchen duty"
            for task in model["queue"]
        ))
        self.assertEqual(1, model["internal_count"])

    def test_site_navigation_routes_through_authored_opening(self):
        self.person.update({
            "simulation_site": "location_route_site",
            "site_position": [-4, 0],
        })
        self.world.entities.update({
            "location_route_site": {
                "id": "location_route_site", "type": "location",
                "bounds": {"min_x": -6, "max_x": 6, "min_y": -5, "max_y": 5},
                "layout_structures": ["location_route_building"],
                "resident_people": [self.person["id"]],
            },
            "location_route_building": {
                "id": "location_route_building", "type": "location",
                "bounds": {"min_x": 0, "max_x": 4, "min_y": -2, "max_y": 2},
                "openings": [{"side": "west", "center": -1, "width": 1.2}],
            },
        })
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        route = sim._plan_route((-4, 0), (2, 0))

        self.assertGreater(len(route), 1)
        cursor = (-4, 0)
        for waypoint in route:
            self.assertFalse(sim._segment_blocked(cursor, waypoint))
            cursor = waypoint
        self.assertEqual((2.0, 0.0), route[-1])

    def test_direct_route_uses_door_gap_when_aligned(self):
        self.person.update({
            "simulation_site": "location_door_site",
            "site_position": [-4, 0],
        })
        self.world.entities.update({
            "location_door_site": {
                "id": "location_door_site", "type": "location",
                "bounds": {"min_x": -6, "max_x": 6, "min_y": -5, "max_y": 5},
                "layout_structures": ["location_door_building"],
            },
            "location_door_building": {
                "id": "location_door_building", "type": "location",
                "bounds": {"min_x": 0, "max_x": 4, "min_y": -2, "max_y": 2},
                "openings": [{"side": "west", "center": 0, "width": 2}],
            },
        })
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertEqual([(2.0, 0.0)], sim._plan_route((-4, 0), (2, 0)))

    def test_autonomous_navigation_uses_authored_route_knowledge(self):
        self.person.update({
            "simulation_site": "location_known_site",
            "site_position": [-4, 0],
            "knowledge_records": [{
                "entity": "location_known_building",
                "navigation_knowledge": "route",
                "familiarity": 0.9,
            }],
        })
        self.world.entities.update({
            "location_known_site": {
                "id": "location_known_site", "type": "location",
                "bounds": {"min_x": -6, "max_x": 6, "min_y": -5, "max_y": 5},
                "layout_structures": ["location_known_building"],
                "resident_people": [self.person["id"]],
            },
            "location_known_building": {
                "id": "location_known_building", "type": "location",
                "bounds": {"min_x": 0, "max_x": 4, "min_y": -2, "max_y": 2},
                "openings": [{"side": "west", "center": -1, "width": 1.2}],
            },
        })
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertTrue(sim._begin_knowledge_navigation((2.0, 0.0), "location_known_building"))
        self.assertEqual("known_route", sim.navigation_mode)
        self.assertEqual("route", sim.navigation_history[0]["event"])
        self.assertGreater(len(sim.navigation_path), 1)

    def test_opening_task_panel_does_not_erase_live_wayfinding(self):
        self.person.update({
            "simulation_site": "location_known_site",
            "site_position": [-4, 0],
            "knowledge_records": [{
                "entity": "location_known_building",
                "navigation_knowledge": "route",
                "familiarity": 0.9,
            }],
        })
        self.world.entities.update({
            "location_known_site": {
                "id": "location_known_site", "type": "location",
                "bounds": {"min_x": -6, "max_x": 6, "min_y": -5, "max_y": 5},
                "layout_structures": ["location_known_building"],
                "resident_people": [self.person["id"]],
            },
            "location_known_building": {
                "id": "location_known_building", "type": "location",
                "bounds": {"min_x": 0, "max_x": 4, "min_y": -2, "max_y": 2},
                "openings": [{"side": "west", "center": -1, "width": 1.2}],
            },
        })
        sim = PersonSimulation(self.world, self.person["id"], year=2400)
        self.assertTrue(sim._begin_knowledge_navigation((2.0, 0.0), "location_known_building"))
        route_before = list(sim.navigation_path)

        model = sim.get_task_panel_model()

        self.assertEqual("known_route", model["navigation"]["mode"])
        self.assertEqual("location_known_building", sim.navigation_destination_entity_id)
        self.assertEqual(route_before, sim.navigation_path)

    def test_direction_only_knowledge_starts_in_heading_then_seeks_advice(self):
        self.person.update({
            "simulation_site": "location_direction_site",
            "site_position": [0, 0],
            "big_five_extraversion": 0.7,
            "big_five_agreeableness": 0.7,
            "knowledge_records": [{
                "entity": "location_direction_goal",
                "navigation_knowledge": "direction",
                "direction_hint": [1, 0],
            }],
        })
        self.world.entities.update({
            "location_direction_site": {
                "id": "location_direction_site", "type": "location",
                "bounds": {"min_x": -10, "max_x": 20, "min_y": -10, "max_y": 10},
                "resident_people": [self.person["id"], "person_guide"],
            },
            "location_direction_goal": {"id": "location_direction_goal", "type": "location"},
            "person_guide": {
                "id": "person_guide", "type": "person", "pretty_name": "Local Guide",
                "site_position": [3, 2],
                "knowledge_records": [{"entity": "location_direction_goal", "navigation_knowledge": "route"}],
            },
        })
        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertTrue(sim._begin_knowledge_navigation((16.0, 0.0), "location_direction_goal"))
        self.assertEqual("direction", sim.navigation_mode)
        self.assertEqual("direction", sim.navigation_history[0]["event"])

        sim.navigation_path = []
        self.assertTrue(sim._continue_uncertain_navigation((16.0, 0.0)))
        self.assertEqual("asking", sim.navigation_mode)
        self.assertEqual("person_guide", sim.navigation_ask_person_id)

        sim.position = [3, 2]
        sim.navigation_path = []
        self.assertTrue(sim._resolve_asked_directions((16.0, 0.0)))
        self.assertEqual("known_route", sim.navigation_mode)
        self.assertEqual("Local Guide", sim.navigation_history[0]["source"])

    def test_right_click_while_idle_opens_inspect_card_for_nearby_point_asset(self):
        food_position = self.sim.test_points["food"]["position"]
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=food_position)

        self.sim.handle_pointer_event(event, _IdentityCamera(), food_position)

        target = self.sim.consume_pending_floating_card_target()
        self.assertIsNotNone(target)
        self.assertEqual("location_person_test_pantry", target["id"])
        self.assertEqual("inspect", target["mode"])

    def test_right_click_with_active_direct_order_cancels_instead_of_opening_a_card(self):
        self.sim.set_control_mode("direct")
        self.sim.command_direct_move((6.0, 0.0))
        self.assertIsNotNone(self.sim.direct_target)

        food_position = self.sim.test_points["food"]["position"]
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=food_position)
        self.sim.handle_pointer_event(event, _IdentityCamera(), food_position)

        self.assertIsNone(self.sim.direct_target)
        self.assertIsNone(self.sim.consume_pending_floating_card_target())

    def test_open_character_editor_requests_the_full_edit_mode_card_on_self(self):
        result = self.sim.open_character_editor()

        self.assertTrue(result)
        target = self.sim.consume_pending_floating_card_target()
        self.assertIsNotNone(target)
        self.assertEqual(self.person["id"], target["id"])
        self.assertEqual("edit", target["mode"])

    def test_right_click_far_from_any_point_does_nothing(self):
        far_pos = (500.0, 500.0)
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=far_pos)

        self.sim.handle_pointer_event(event, _IdentityCamera(), far_pos)

        self.assertIsNone(self.sim.consume_pending_floating_card_target())


if __name__ == "__main__":
    unittest.main()
