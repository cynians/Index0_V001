import heapq
import math

import pygame

from engine.clock import Clock
from engine.logger import logger
from engine.simulation_manager import SimulationManager
from simulations.person.person_assets import (
    assess_person_readiness,
    character_creation_prompt_lines,
    placeable_asset_catalog,
)
from world.ownership_resolver import OwnershipResolver
from world.year_utils import parse_year


class PersonRuntimeSystem:
    """Transient embodied state; durable consequences are persisted separately."""

    def __init__(self, simulation):
        self.simulation = simulation

    def update(self, dt):
        self.simulation._update_runtime(dt)


class PersonSimulation:
    """
    Person dossier plus the first embodied task-queue simulation slice.

    Ontology entities remain the durable semantic source. Position, current
    needs, movement orders, and the live task queue are deliberately transient
    runtime state until an action creates a consequence worth persisting.
    """

    REFERENCE_FIELDS = (
        "affiliated_factions",
        "affiliated_institutions",
        "associated_locations",
        "participated_events",
        "parents",
        "related",
        "offspring",
    )

    TEMPORAL_KEYS = (
        "birth_year",
        "year",
        "year_number",
        "active_year",
        "start_year",
        "effective_year",
        "death_year",
        "end_year",
    )

    CONTROL_AUTONOMOUS = "autonomous"
    CONTROL_DIRECT = "direct"
    VALID_CONTROL_MODES = {CONTROL_AUTONOMOUS, CONTROL_DIRECT}

    BIG_FIVE_AXES = (
        {
            "id": "openness",
            "label": "Openness",
            "low_label": "Conventional",
            "high_label": "Open",
        },
        {
            "id": "conscientiousness",
            "label": "Conscientiousness",
            "low_label": "Flexible",
            "high_label": "Conscientious",
        },
        {
            "id": "extraversion",
            "label": "Extraversion",
            "low_label": "Reserved",
            "high_label": "Extraverted",
        },
        {
            "id": "agreeableness",
            "label": "Agreeableness",
            "low_label": "Competitive",
            "high_label": "Agreeable",
        },
        {
            "id": "neuroticism",
            "label": "Neuroticism",
            "low_label": "Emotionally stable",
            "high_label": "Reactive",
        },
    )

    TEST_MAP_BOUNDS = {
        "min_x": -18.0,
        "max_x": 18.0,
        "min_y": -11.0,
        "max_y": 11.0,
    }

    # No world-gen linkage exists yet to place a site-less person anywhere
    # meaningful. Rather than defaulting them into the lumber test site's
    # geometry (see docs/person_simulation_concept_v001.md Cycle 2), they
    # spawn in an open, structureless void sized well past camera clamping
    # so nothing suggests a bounded room.
    VOID_MAP_BOUNDS = {
        "min_x": -200.0,
        "max_x": 200.0,
        "min_y": -200.0,
        "max_y": 200.0,
    }

    TEST_POINT_DEFINITIONS = (
        {
            "id": "bed",
            "label": "Bed",
            "position": (-12.0, -6.0),
            "color": (102, 145, 196),
            "need": "rest",
            "maslow_tier": "physiological",
            "duration": 5.0,
            "tags": ("Rest",),
        },
        {
            "id": "food",
            "label": "Ingredients",
            "position": (-12.0, 6.0),
            "color": (196, 153, 79),
            "need": "food",
            "maslow_tier": "physiological",
            "duration": 1.5,
            "asset_id": "location_person_test_pantry",
            "tags": ("Eating Comfort",),
        },
        {
            "id": "kitchen",
            "label": "Kitchen",
            "position": (-4.0, 6.0),
            "color": (118, 161, 172),
            "need": "food",
            "maslow_tier": "physiological",
            "duration": 5.0,
            "asset_id": "location_person_test_kitchen",
            "producer_id": "producer_person_test_kitchen",
            "recipe_id": "recipe_simple_cooked_meal",
            "tags": ("Eating Comfort",),
        },
        {
            "id": "job",
            "label": "Job",
            "position": (8.0, -5.0),
            "color": (112, 170, 126),
            "need": "esteem",
            "maslow_tier": "esteem",
            "duration": 6.0,
            "tags": ("Livelihood",),
        },
        {
            "id": "target",
            "label": "Target",
            "position": (10.0, 6.0),
            "color": (184, 104, 100),
            "need": "leisure",
            "maslow_tier": "self-actualization",
            "duration": 4.0,
            "tags": ("Social Place",),
        },
        {
            # Duty-only: reached exclusively through assign_external_task
            # (see SiteSimulation._handle_vehicle_arrival). Deliberately
            # carries no `tags` -- a wish must never drive job-assigned
            # logistics work, only a person's own internally formed tasks.
            # See docs/conceptual_layer_overview_v006.txt section 22.
            "id": "lumber_dropoff",
            "label": "Lumber Yard Drop-off",
            "position": (6.0, 15.0),
            "color": (149, 111, 66),
            "need": "esteem",
            "maslow_tier": "esteem",
            "duration": 1.0,
            "asset_id": "location_lumber_test_storage",
        },
        {
            # Duty-only, same as lumber_dropoff above.
            "id": "lumber_pickup",
            "label": "Lumber Yard Pickup",
            "position": (4.0, 15.0),
            "color": (111, 149, 66),
            "need": "esteem",
            "maslow_tier": "esteem",
            "duration": 1.0,
            "asset_id": "location_lumber_test_storage",
        },
    )

    def __init__(self, world_model=None, person_entity_id=None, year=2400):
        self.world_model = world_model
        self.person_entity_id = person_entity_id
        self.render_mode = "person"
        self.world_units_to_meters = 1.0
        self.year = int(year) if year is not None else 2400

        self.sim_clock = Clock(base_dt=1.0)
        self.system = PersonRuntimeSystem(self)
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.bounds = dict(self.VOID_MAP_BOUNDS)
        self.min_zoom = 12.0
        self.max_zoom = 80.0
        self.preferred_zoom = 28.0
        self.free_camera_pan = False

        self._pending_inspector_target = None
        self._pending_floating_card_target = None
        self.ownership = OwnershipResolver(world_model)
        self.site_entity_id = None
        self.in_void = True
        self.site_entity = {}
        self.site_structures = []
        self.site_people = []
        self.wall_segments = []
        self.openings = []
        self.navigation_path = []
        self.navigation_destination = None
        self.navigation_destination_entity_id = None
        self.navigation_mode = "idle"
        self.navigation_heading = None
        self.navigation_ask_person_id = None
        self.navigation_people_asked = set()
        self.navigation_history = []

        # Placeholder for habit formation (repeated performance of a task in
        # a particular way should eventually crystallize into a durable
        # habit that biases future task scoring). Deliberately inert for
        # now: no formation heuristic is wired up, and nothing reads this
        # yet. Left as a documented stub rather than guessed at.
        self.habits = []

        self.control_mode = self.CONTROL_AUTONOMOUS
        self.position = [0.0, 0.0]
        self.move_speed_m_per_second = 3.2
        self.arrival_radius_m = 0.18
        self.needs = {
            "food": 52.0,
            "rest": 72.0,
            "safety": 100.0,
            "belonging": 64.0,
            "esteem": 46.0,
            "leisure": 42.0,
        }
        self.work_due = 78.0
        self.completed_jobs = 0
        self.task_queue = []
        self.external_task_allocations = []
        self.internal_task_allocations = []
        self.active_task = None
        self.active_task_elapsed = 0.0
        self.runtime_inventory = {}
        self.container_inventories = {}
        self.inventory_history = []
        self.decision_history = []
        self.last_task_comparison = []
        self._task_serial = 0
        self.direct_target = None
        self.hover_point_id = None
        self.last_status = "Autonomous queue initialized"
        self.test_points = {
            definition["id"]: dict(definition)
            for definition in self.TEST_POINT_DEFINITIONS
        }
        self.asset_palette = placeable_asset_catalog(self.TEST_POINT_DEFINITIONS)
        self.placement_mode = False
        self.placement_selected_asset_id = None
        self._load_site_model()
        self._load_authored_inventories()
        self._refresh_job_point_label()
        self._load_authored_task_allocations()
        self._fill_autonomous_queue()
        self._assess_character_readiness()

    def get_center(self):
        return 0.0, 0.0

    def get_initial_camera_zoom(self, screen_w, screen_h):
        map_width = self.bounds["max_x"] - self.bounds["min_x"]
        map_height = self.bounds["max_y"] - self.bounds["min_y"]
        return max(
            self.min_zoom,
            min(self.max_zoom, min(screen_w / map_width, screen_h / map_height) * 0.82),
        )

    @staticmethod
    def _point_pair(value, fallback=(0.0, 0.0)):
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                pass
        return tuple(fallback)

    @staticmethod
    def _bbox(value):
        if not isinstance(value, dict):
            return None
        try:
            return {
                "min_x": float(value["min_x"]),
                "max_x": float(value["max_x"]),
                "min_y": float(value["min_y"]),
                "max_y": float(value["max_y"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _split_wall(start, end, intervals):
        horizontal = abs(start[1] - end[1]) < 1e-8
        low = start[0] if horizontal else start[1]
        high = end[0] if horizontal else end[1]
        if low > high:
            low, high = high, low
        cursor = low
        segments = []
        for opening_low, opening_high in sorted(intervals):
            opening_low = max(low, min(high, opening_low))
            opening_high = max(low, min(high, opening_high))
            if opening_low > cursor + 1e-6:
                if horizontal:
                    segments.append(((cursor, start[1]), (opening_low, start[1])))
                else:
                    segments.append(((start[0], cursor), (start[0], opening_low)))
            cursor = max(cursor, opening_high)
        if cursor < high - 1e-6:
            if horizontal:
                segments.append(((cursor, start[1]), (high, start[1])))
            else:
                segments.append(((start[0], cursor), (start[0], high)))
        return segments

    def _structure_walls(self, bounds, openings):
        side_specs = {
            "north": ((bounds["min_x"], bounds["min_y"]), (bounds["max_x"], bounds["min_y"]), True),
            "south": ((bounds["min_x"], bounds["max_y"]), (bounds["max_x"], bounds["max_y"]), True),
            "west": ((bounds["min_x"], bounds["min_y"]), (bounds["min_x"], bounds["max_y"]), False),
            "east": ((bounds["max_x"], bounds["min_y"]), (bounds["max_x"], bounds["max_y"]), False),
        }
        walls = []
        for side, (start, end, _horizontal) in side_specs.items():
            intervals = []
            for opening in openings:
                if str(opening.get("side") or "").casefold() != side:
                    continue
                try:
                    center = float(opening.get("center"))
                    width = max(0.8, float(opening.get("width", 2.0)))
                except (TypeError, ValueError):
                    continue
                intervals.append((center - width / 2.0, center + width / 2.0))
            walls.extend(self._split_wall(start, end, intervals))
        return walls

    def _load_site_model(self):
        person = self.get_person() or {}
        requested_site = str(person.get("simulation_site") or "").strip()
        if not requested_site:
            for location_id in self._relation_ids(person.get("associated_locations")):
                location = self.get_person(location_id) or {}
                if location.get("simulation_points"):
                    requested_site = location_id
                    break
        if requested_site:
            self.site_entity_id = requested_site
        self.in_void = not bool(self.site_entity_id)
        self.site_entity = (self.get_person(self.site_entity_id) or {}) if self.site_entity_id else {}
        site_bounds = self._bbox(self.site_entity.get("bounds"))
        if site_bounds:
            self.bounds = site_bounds

        raw_points = self.site_entity.get("simulation_points") or []
        if isinstance(raw_points, dict):
            raw_points = [raw_points]
        for raw in raw_points if isinstance(raw_points, (list, tuple)) else []:
            if not isinstance(raw, dict):
                continue
            point_id = str(raw.get("id") or "").strip()
            if point_id not in self.test_points:
                continue
            point = self.test_points[point_id]
            point.update({key: value for key, value in raw.items() if value is not None})
            point["position"] = self._point_pair(raw.get("position"), point.get("position"))

        structure_ids = self._relation_ids(
            self.site_entity.get("layout_structures") or self.site_entity.get("constituents")
        )
        for structure_id in structure_ids:
            entity = self.get_person(structure_id) or {}
            bounds = self._bbox(entity.get("bounds"))
            if not bounds:
                continue
            openings = entity.get("openings") or []
            if isinstance(openings, dict):
                openings = [openings]
            openings = [dict(item) for item in openings if isinstance(item, dict)]
            structure = {
                "entity_id": structure_id,
                "label": entity.get("pretty_name") or entity.get("name") or structure_id,
                "structure_class": entity.get("building_class") or entity.get("site_class") or "building",
                "bounds": bounds,
                "openings": openings,
                "color": entity.get("map_color"),
            }
            self.site_structures.append(structure)
            self.wall_segments.extend(self._structure_walls(bounds, openings))
            for opening in openings:
                self.openings.append({**opening, "structure_id": structure_id})

        for person_id in self._relation_ids(self.site_entity.get("resident_people")):
            resident = self.get_person(person_id) or {}
            resident_position = self._point_pair(resident.get("site_position"))
            self.site_people.append({
                "entity_id": person_id,
                "label": resident.get("pretty_name") or resident.get("name") or person_id,
                "sex": resident.get("sex"),
                "position": resident_position,
                "controlled": person_id == self.person_entity_id,
            })
            if person_id == self.person_entity_id and resident.get("site_position") is not None:
                self.position[:] = [resident_position[0], resident_position[1]]

    def _assess_character_readiness(self):
        person = self.get_person() or {}
        self.character_readiness = assess_person_readiness(person, self.world_model)
        self.needs_character_creation = self.character_readiness["tier"] != "authored"

    def _asset_palette_entry(self, asset_id):
        return next((entry for entry in self.asset_palette if entry["id"] == asset_id), None)

    def select_asset_for_placement(self, asset_id):
        """Rudimentary asset placer: enter placement mode for a palette entry.

        Scoped to the void test area for now -- authored sites keep their
        careful hand-placed geometry untouched until wall-aware placement
        is worth building.
        """
        if not self.in_void:
            self.last_status = "Asset placement is only available in the void test area for now"
            return False
        entry = self._asset_palette_entry(asset_id)
        if entry is None:
            return False
        self.placement_mode = True
        self.placement_selected_asset_id = asset_id
        self.last_status = f"Placement mode: click the map to place {entry.get('label', asset_id)}"
        return True

    def cancel_asset_placement(self):
        self.placement_mode = False
        self.placement_selected_asset_id = None

    def place_selected_asset(self, position):
        if not self.placement_mode or not self.placement_selected_asset_id:
            return False
        template = self._asset_palette_entry(self.placement_selected_asset_id)
        if template is None:
            return False
        point_id = template["id"]
        point = self.test_points.setdefault(point_id, dict(template))
        point.update({key: value for key, value in template.items() if key != "position"})
        point["position"] = (float(position[0]), float(position[1]))
        point["placed"] = True
        self.last_status = f"Placed {point.get('label', point_id)}"
        self.placement_mode = False
        self.placement_selected_asset_id = None
        return True

    _PLACEMENT_DIGIT_KEYS = (
        pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
        pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9,
    )

    def consumes_global_keydown(self):
        return self.in_void

    def handle_event(self, event):
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            if self.placement_mode:
                self.cancel_asset_placement()
            return
        if event.key in self._PLACEMENT_DIGIT_KEYS:
            index = self._PLACEMENT_DIGIT_KEYS.index(event.key)
            if index < len(self.asset_palette):
                self.select_asset_for_placement(self.asset_palette[index]["id"])

    def update(self, dt):
        self.sim_manager.update(dt)

    def _update_runtime(self, dt):
        try:
            dt = max(0.0, min(10.0, float(dt)))
        except (TypeError, ValueError):
            return
        if dt <= 0.0:
            return

        self._decay_needs(dt)
        if self.control_mode == self.CONTROL_DIRECT:
            self._update_direct_control(dt)
        else:
            self._update_autonomous_control(dt)

    def _decay_needs(self, dt):
        decay = {
            "food": 0.030,
            "rest": 0.016,
            "belonging": 0.004,
            "esteem": 0.006,
            "leisure": 0.020,
        }
        for need, rate in decay.items():
            self.needs[need] = max(0.0, self.needs.get(need, 0.0) - rate * dt)
        self.work_due = min(100.0, self.work_due + 0.012 * dt)

    @staticmethod
    def _inventory_entries(entity):
        raw_entries = (entity or {}).get("inventory_items") or []
        if isinstance(raw_entries, dict):
            raw_entries = [raw_entries]
        entries = []
        for raw in raw_entries if isinstance(raw_entries, (list, tuple)) else []:
            if isinstance(raw, str):
                raw = {"item": raw, "quantity": 1}
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("item") or raw.get("item_id") or "").strip()
            if not item_id:
                continue
            try:
                quantity = max(0.0, float(raw.get("quantity", 1) or 0.0))
            except (TypeError, ValueError):
                quantity = 0.0
            if quantity > 0.0:
                entries.append((item_id, quantity))
        return entries

    def _load_authored_inventories(self):
        person = self.get_person() or {}
        self.runtime_inventory = {
            item_id: quantity
            for item_id, quantity in self._inventory_entries(person)
        }
        for point_id, point in self.test_points.items():
            holder = self.get_person(point.get("asset_id")) or {}
            entries = self._inventory_entries(holder)
            if entries:
                self.container_inventories[point_id] = {
                    item_id: quantity for item_id, quantity in entries
                }

    @staticmethod
    def _clean_quantity(value):
        value = float(value or 0.0)
        return int(value) if value.is_integer() else round(value, 3)

    def _item_quantity(self, item_id, inventory=None):
        inventory = self.runtime_inventory if inventory is None else inventory
        return max(0.0, float(inventory.get(item_id, 0.0) or 0.0))

    def _change_inventory(self, item_id, delta, reason, *, source=None, destination=None):
        old_quantity = self._item_quantity(item_id)
        new_quantity = max(0.0, old_quantity + float(delta))
        self.runtime_inventory[item_id] = new_quantity
        item = self.get_person(item_id) or {}
        self.inventory_history.insert(0, {
            "item_id": item_id,
            "label": item.get("pretty_name") or item.get("name") or item_id,
            "delta": self._clean_quantity(delta),
            "quantity": self._clean_quantity(new_quantity),
            "reason": str(reason or "inventory changed"),
            "source": source,
            "destination": destination,
        })
        del self.inventory_history[20:]
        return new_quantity

    @staticmethod
    def _recipe_amounts(recipe, structured_field, relation_field):
        raw = (recipe or {}).get(structured_field) or []
        if isinstance(raw, dict):
            raw = [raw]
        amounts = []
        for entry in raw if isinstance(raw, (list, tuple)) else []:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item") or entry.get("item_id") or "").strip()
            if not item_id:
                continue
            try:
                quantity = max(0.0, float(entry.get("quantity", 1) or 0.0))
            except (TypeError, ValueError):
                quantity = 0.0
            if quantity > 0.0:
                amounts.append((item_id, quantity))
        if amounts:
            return amounts
        relations = (recipe or {}).get(relation_field) or []
        if isinstance(relations, str):
            relations = [relations]
        return [(item_id, 1.0) for item_id in relations if isinstance(item_id, str) and item_id]

    def _task_for_point(self, point_id, source="autonomous", priority=0.0, **metadata):
        point = self.test_points.get(point_id)
        if point is None:
            return None
        task = {
            "id": metadata.pop("id", f"{source}:{point_id}"),
            "point_id": point_id,
            "label": point["label"],
            "target": tuple(point["position"]),
            "duration": float(point.get("duration", 0.0) or 0.0),
            "maslow_tier": point.get("maslow_tier", "assigned"),
            "source": source,
            "priority": float(priority),
            "base_priority": float(priority),
            "phase": "moving",
            "lifecycle_state": "proposed",
            "elapsed": 0.0,
        }
        task.update(metadata)
        if point_id == "food":
            recipe_id = self.test_points["kitchen"].get("recipe_id")
            recipe = self.get_person(recipe_id) or {}
            recipe_inputs = self._recipe_amounts(recipe, "input_requirements", "input_items")
            recipe_outputs = self._recipe_amounts(recipe, "output_yields", "output_items")
            ingredient_id, ingredient_quantity = recipe_inputs[0] if recipe_inputs else ("item_food_ingredients", 1.0)
            meal_id, _meal_quantity = recipe_outputs[0] if recipe_outputs else ("item_cooked_meal", 1.0)
            task["label"] = "Prepare and eat a meal"
            task["steps"] = [
                {
                    "id": "collect_ingredients",
                    "label": "Collect ingredients",
                    "point_id": "food",
                    "duration": 1.5,
                    "asset_id": self.test_points["food"].get("asset_id"),
                    "item_id": ingredient_id,
                    "quantity": ingredient_quantity,
                },
                {
                    "id": "cook_meal",
                    "label": "Cook meal",
                    "point_id": "kitchen",
                    "duration": 5.0,
                    "asset_id": self.test_points["kitchen"].get("asset_id"),
                    "producer_id": self.test_points["kitchen"].get("producer_id"),
                    "recipe_id": recipe_id,
                },
                {
                    "id": "eat_meal",
                    "label": "Eat cooked meal",
                    "point_id": "kitchen",
                    "duration": 2.0,
                    "asset_id": meal_id,
                    "item_id": meal_id,
                },
            ]
            task["step_index"] = 0
            self._set_task_step(task, 0, selected=False)
        elif point_id == "lumber_dropoff":
            point = self.test_points["lumber_dropoff"]
            cargo_item_id = point.get("cargo_item_id") or "item_raw_lumber"
            remaining_quantity = float(point.get("remaining_quantity", 0.0) or 0.0)
            task["label"] = "Unload delivery cart"
            task["steps"] = [
                {
                    "id": "walk_to_dropoff",
                    "label": "Walk to delivery cart",
                    "point_id": "lumber_dropoff",
                    "duration": 1.0,
                    "asset_id": point.get("asset_id"),
                },
                {
                    "id": "transfer_lumber",
                    "label": "Unload lumber into storage",
                    "point_id": "lumber_dropoff",
                    "duration": 3.0,
                    "asset_id": point.get("asset_id"),
                    "item_id": cargo_item_id,
                    "quantity": remaining_quantity,
                },
            ]
            task["step_index"] = 0
            self._set_task_step(task, 0, selected=False)
        return task

    def _set_task_step(self, task, step_index, *, selected=True):
        steps = list(task.get("steps") or [])
        if not steps or step_index < 0 or step_index >= len(steps):
            return False
        step = steps[step_index]
        point = self.test_points.get(step.get("point_id"))
        if point is None:
            return False
        task["step_index"] = step_index
        task["interaction_point_id"] = step.get("point_id")
        task["action_label"] = step.get("label") or task.get("label")
        task["target"] = tuple(point["position"])
        task["duration"] = float(step.get("duration", point.get("duration", 0.0)) or 0.0)
        task["phase"] = "moving"
        if selected:
            # Candidate tasks are assembled while the task panel is open.  Only
            # selecting a real next step may replace the person's live route.
            self._clear_navigation()
            task["lifecycle_state"] = "travelling"
        return True

    def _current_task_step(self, task):
        steps = list((task or {}).get("steps") or [])
        index = int((task or {}).get("step_index", 0) or 0)
        return steps[index] if 0 <= index < len(steps) else None

    def _knows_entity(self, entity_id):
        return any(record.get("entity_id") == entity_id for record in self._knowledge_records())

    def _kitchen_recipe_report(self, recipe_id, producer_id):
        recipe = self.get_person(recipe_id) or {}
        producer = self.get_person(producer_id) or {}
        if not recipe:
            return False, "recipe is unavailable"
        if not self._knows_entity(recipe_id):
            return False, "recipe is not known"
        required_technologies = set(self._relation_ids(recipe.get("required_technologies")))
        required_components = set(self._relation_ids(recipe.get("required_components")))
        producer_technologies = set(self._relation_ids(producer.get("production_technologies")))
        producer_components = set(self._relation_ids(producer.get("assigned_components")))
        matching_line = None
        for line in producer.get("production_lines") or []:
            if not isinstance(line, dict):
                continue
            if recipe_id not in self._relation_ids(line.get("recipe_ids") or line.get("recipes")):
                continue
            matching_line = line
            producer_technologies.update(self._relation_ids(line.get("employed_technology_ids")))
            producer_components.update(self._relation_ids(line.get("assigned_component_ids")))
            break
        if matching_line is None:
            return False, "kitchen has no production line for the recipe"
        recipe_outputs = {
            item_id
            for item_id, _quantity in self._recipe_amounts(recipe, "output_yields", "output_items")
        }
        line_product = str(matching_line.get("product_id") or "").strip()
        if recipe_outputs and line_product not in recipe_outputs:
            return False, "kitchen production line does not produce the recipe output"
        missing_technologies = required_technologies - producer_technologies
        if missing_technologies:
            return False, "missing cooking technology: " + ", ".join(sorted(missing_technologies))
        missing_components = required_components - producer_components
        if missing_components:
            return False, "missing kitchen component: " + ", ".join(sorted(missing_components))
        return True, "recipe and kitchen requirements satisfied"

    def _task_step_access_report(self, task):
        step = self._current_task_step(task)
        if not step:
            return {"allowed": True, "reason": "no owned asset required"}
        asset_id = step.get("asset_id")
        if step.get("id") == "eat_meal":
            item_id = step.get("item_id") or asset_id
            return {
                "allowed": self._item_quantity(item_id) > 0,
                "reason": "cooked meal held by person" if self._item_quantity(item_id) > 0 else "cooked meal is not in inventory",
            }
        if asset_id:
            report = self.ownership.access_report(self.person_entity_id, asset_id)
            if not report["allowed"]:
                return report
        if step.get("id") == "cook_meal":
            allowed, reason = self._kitchen_recipe_report(step.get("recipe_id"), step.get("producer_id"))
            return {"allowed": allowed, "reason": reason, "asset_id": asset_id}
        return {"allowed": True, "reason": "ownership permits use", "asset_id": asset_id}

    def _complete_multi_step_action(self, step):
        """Apply the concrete consequence of one step of a multi-step task.

        Dispatches on step id rather than task/point id because every
        multi-step task (food preparation, lumber unloading, ...) shares this
        single completion hook from _advance_active_task.
        """
        step_id = (step or {}).get("id")
        if step_id == "collect_ingredients":
            item_id = step.get("item_id") or "item_food_ingredients"
            quantity = float(step.get("quantity", 1.0) or 1.0)
            container = self.container_inventories.setdefault("food", {})
            available = self._item_quantity(item_id, container)
            if available < quantity:
                return False, f"ingredient store has only {self._clean_quantity(available)} available"
            container[item_id] = available - quantity
            self._change_inventory(
                item_id,
                quantity,
                "collected for recipe",
                source=self.test_points["food"].get("asset_id"),
                destination=self.person_entity_id,
            )
        elif step_id == "cook_meal":
            recipe_id = step.get("recipe_id")
            recipe = self.get_person(recipe_id) or {}
            inputs = self._recipe_amounts(recipe, "input_requirements", "input_items")
            outputs = self._recipe_amounts(recipe, "output_yields", "output_items")
            missing = [
                (item_id, quantity - self._item_quantity(item_id))
                for item_id, quantity in inputs
                if self._item_quantity(item_id) < quantity
            ]
            if missing:
                return False, "missing recipe item: " + ", ".join(
                    f"{item_id} x{self._clean_quantity(quantity)}" for item_id, quantity in missing
                )
            for item_id, quantity in inputs:
                self._change_inventory(
                    item_id,
                    -quantity,
                    "consumed by recipe",
                    source=self.person_entity_id,
                    destination=step.get("producer_id"),
                )
            for item_id, quantity in outputs:
                self._change_inventory(
                    item_id,
                    quantity,
                    "produced by recipe",
                    source=step.get("producer_id"),
                    destination=self.person_entity_id,
                )
        elif step_id == "eat_meal":
            item_id = step.get("item_id") or "item_cooked_meal"
            item = self.get_person(item_id) or {}
            if self._item_quantity(item_id) <= 0:
                return False, "no cooked meal held"
            if item.get("consumable") is False:
                return False, "held item is not consumable"
            try:
                satiation = max(0.0, float(item.get("food_satiation", 0.0) or 0.0))
            except (TypeError, ValueError):
                satiation = 0.0
            if satiation <= 0.0:
                return False, "food item has no satiation value"
            self._change_inventory(
                item_id,
                -1,
                "consumed as food",
                source=self.person_entity_id,
                destination="consumed",
            )
            self.needs["food"] = min(100.0, self.needs["food"] + satiation)
        elif step_id == "transfer_lumber":
            item_id = step.get("item_id") or "item_raw_lumber"
            quantity = float(step.get("quantity", 0.0) or 0.0)
            if quantity <= 0.0:
                return False, "no cargo remaining to unload"
            storage = self.container_inventories.setdefault("lumber_dropoff", {})
            storage[item_id] = self._item_quantity(item_id, storage) + quantity
            point = self.test_points.get("lumber_dropoff")
            if point is not None:
                point["remaining_quantity"] = 0.0
        return True, ""

    def _personality_scores(self):
        return {
            axis["id"]: float(axis.get("value", 0.5))
            for axis in self.get_personality_panel_model().get("axes", [])
        }

    @staticmethod
    def _urgency(fulfillment, exponent=1.75):
        lack = 1.0 - max(0.0, min(100.0, float(fulfillment or 0.0))) / 100.0
        return lack ** exponent

    def _authored_wish_entities(self, person, *field_names):
        """Resolve wishes/dreams/goals list entries that are real references
        into the `wishes` dataset (an authored wish_type is the marker) --
        as opposed to legacy free-text notes, which display fine via
        _authored_list/_display_entity_value but carry no wish_type to
        match on."""
        entities = []
        if self.world_model is None:
            return entities
        for field_name in field_names:
            raw = person.get(field_name)
            if raw in (None, ""):
                continue
            values = raw if isinstance(raw, (list, tuple, set)) else [raw]
            for value in values:
                if not isinstance(value, str):
                    continue
                entity = self.world_model.get_entity(value)
                if isinstance(entity, dict) and entity.get("wish_type"):
                    entities.append(entity)
        return entities

    def _authored_motive_boost(self, point_id):
        point_tags = set((self.test_points.get(point_id) or {}).get("tags") or ())
        if not point_tags:
            return 0.0, []
        person = self.get_person() or {}
        boost = 0.0
        reasons = []
        for field_name, weight in (("wishes", 18.0), ("dreams", 22.0), ("goals", 25.0)):
            for wish in self._authored_wish_entities(person, field_name, f"personal_{field_name}"):
                if str(wish.get("wish_type")) not in point_tags:
                    continue
                boost += weight
                motive_label = {"wishes": "Wish", "dreams": "Dream", "goals": "Goal"}.get(
                    field_name,
                    field_name.title(),
                )
                label = wish.get("pretty_name") or wish.get("name") or wish.get("id")
                reasons.append(f"{motive_label}: {label}")
        return boost, reasons

    def _goal_tags(self):
        """Wish types implied by this person's authored wishes/dreams/goals."""
        person = self.get_person() or {}
        tags = set()
        for field_name in ("wishes", "dreams", "goals"):
            for wish in self._authored_wish_entities(person, field_name, f"personal_{field_name}"):
                tags.add(str(wish.get("wish_type")))
        return tags

    def _goal_driven_internal_tasks(self):
        """Queue a self-initiated task for any accessible tagged point that
        matches an unmet goal/wish/dream and isn't already pending.

        Points reached only through job/employment duty (e.g.
        lumber_dropoff/lumber_pickup) carry no `tags` and are therefore
        never reachable here -- wishes drive a person's own tasks, never
        externally assigned work (see docs/conceptual_layer_overview_v006.txt
        section 22). A given point is only re-queued once its previous
        goal-driven task has resolved (removed from internal_task_allocations
        / no longer active), not every tick.
        """
        goal_tags = self._goal_tags()
        if not goal_tags:
            return
        pending_point_ids = {
            task.get("point_id")
            for task in self.internal_task_allocations
            if task.get("motive") == "goal"
        }
        if isinstance(self.active_task, dict) and self.active_task.get("motive") == "goal":
            pending_point_ids.add(self.active_task.get("point_id"))
        for point_id, point in self.test_points.items():
            if point_id in {"food", "bed", "job", "target"} or point_id in pending_point_ids:
                continue
            point_tags = set(point.get("tags") or ())
            if not (point_tags & goal_tags):
                continue
            asset_id = point.get("asset_id")
            if asset_id and not self.ownership.can_use(self.person_entity_id, asset_id):
                continue
            self._build_internal_task(
                point_id,
                label=f"Pursue goal at {point.get('label', point_id)}",
                motive="goal",
                weight=0.4,
            )

    def _conviction_effects(self, task):
        action_tags = {str(tag).casefold() for tag in task.get("action_tags", []) if tag}
        if not action_tags:
            return 0.0, [], []
        penalty = 0.0
        reasons = []
        alternatives = []
        for record in self._knowledge_records():
            rules = record.get("behavioral_rules") or {}
            if not isinstance(rules, dict):
                continue
            forbidden = {str(tag).casefold() for tag in rules.get("forbids", []) if tag}
            conflicts = sorted(action_tags & forbidden)
            if not conflicts:
                continue
            strength = self._bounded_score(record.get("conviction"), default=0.5)
            value = 310.0 * (strength ** 1.55)
            penalty -= value
            reasons.append(
                f"{record.get('label', 'Conviction')} forbids {', '.join(conflicts)} "
                f"({strength * 100:.0f}% held)"
            )
            rule_alternatives = rules.get("alternatives") or {}
            if isinstance(rule_alternatives, dict):
                for conflict in conflicts:
                    alternative = rule_alternatives.get(conflict)
                    if alternative:
                        alternatives.append(str(alternative))
        return penalty, reasons, alternatives

    def _score_task(self, task):
        task = dict(task)
        personality = self._personality_scores()
        point_id = task.get("point_id")
        source = task.get("source", "internal")
        breakdown = []
        score = float(task.get("base_priority", task.get("priority", 0.0)) or 0.0)
        if score:
            breakdown.append({"label": "Base pressure", "value": score})

        if point_id == "food":
            value = 270.0 * self._urgency(self.needs.get("food", 0.0), 1.72)
            score += value
            breakdown.append({"label": "Hunger", "value": value})
        elif point_id == "bed":
            value = 235.0 * self._urgency(self.needs.get("rest", 0.0), 1.8)
            score += value
            breakdown.append({"label": "Fatigue", "value": value})
        elif point_id == "target":
            value = 105.0 * self._urgency(self.needs.get("leisure", 0.0), 1.55)
            score += value
            breakdown.append({"label": "Leisure deprivation", "value": value})
        elif point_id == "job":
            conscientiousness = personality.get("conscientiousness", 0.5)
            value = self.work_due * 0.72 * (0.55 + conscientiousness * 0.75)
            score += value
            breakdown.append({"label": "Work due + conscientiousness", "value": value})

        motive_boost, motive_reasons = self._authored_motive_boost(point_id)
        if motive_boost:
            score += motive_boost
            breakdown.append({"label": "; ".join(motive_reasons), "value": motive_boost})

        if source in {"external", "player"}:
            duty_weight = self._bounded_score(task.get("duty_weight"), default=0.7)
            compliance = (
                personality.get("conscientiousness", 0.5) * 0.62
                + personality.get("agreeableness", 0.5) * 0.38
            )
            duty_value = 118.0 * duty_weight * (0.55 + compliance)
            score += duty_value
            breakdown.append({"label": "Assigned duty", "value": duty_value})
            coercion = self._bounded_score(task.get("coercion"), default=0.0)
            if coercion:
                coercion_value = 58.0 * coercion * (
                    0.55 + personality.get("neuroticism", 0.5) * 0.45
                )
                score += coercion_value
                breakdown.append({"label": "Coercion / feared consequence", "value": coercion_value})

        conviction_value, conviction_reasons, alternatives = self._conviction_effects(task)
        if conviction_value:
            score += conviction_value
            breakdown.append({"label": "; ".join(conviction_reasons), "value": conviction_value})

        task["decision_score"] = round(score, 3)
        task["priority"] = task["decision_score"]
        task["score_breakdown"] = breakdown
        task["conviction_conflicts"] = conviction_reasons
        task["suggested_alternatives"] = alternatives
        positive = sorted(
            (item for item in breakdown if item["value"] > 0),
            key=lambda item: item["value"],
            reverse=True,
        )
        negative = sorted(
            (item for item in breakdown if item["value"] < 0),
            key=lambda item: item["value"],
        )
        explanation = [
            f"Decision pressure {task['decision_score']:.0f}.",
            *(f"For: {item['label']} ({item['value']:+.0f})." for item in positive[:3]),
            *(f"Against: {item['label']} ({item['value']:+.0f})." for item in negative[:2]),
        ]
        task["decision_explanation"] = " ".join(explanation)
        return task

    def _autonomous_candidates(self):
        candidates = []
        if self.needs.get("food", 0.0) < 72.0:
            candidates.append(self._task_for_point("food", source="autonomous", priority=22.0, allocation_kind="need"))
        if self.needs.get("rest", 0.0) < 58.0:
            candidates.append(self._task_for_point("bed", source="autonomous", priority=20.0, allocation_kind="need"))
        if self.work_due > 32.0:
            candidates.append(self._task_for_point("job", source="autonomous", priority=18.0, allocation_kind="job"))
        if self.needs.get("leisure", 0.0) < 65.0:
            candidates.append(self._task_for_point("target", source="autonomous", priority=16.0, allocation_kind="wish"))
        candidates.extend(dict(task) for task in self.internal_task_allocations)
        candidates.extend(dict(task) for task in self.external_task_allocations)
        return [self._score_task(task) for task in candidates if task]

    def _fill_autonomous_queue(self):
        self._goal_driven_internal_tasks()
        retained = [
            self._score_task(task)
            for task in self.task_queue
            if task.get("source") == "player"
        ]
        candidates = retained + self._autonomous_candidates()
        active_id = (self.active_task or {}).get("id")
        unique = {}
        for task in candidates:
            if task.get("id") == active_id:
                continue
            key = str(task.get("id") or f"{task.get('source')}:{task.get('point_id')}")
            if key not in unique or task.get("decision_score", 0.0) > unique[key].get("decision_score", 0.0):
                unique[key] = task
        self.task_queue = sorted(
            unique.values(),
            key=lambda task: (-task.get("decision_score", 0.0), task.get("label", "")),
        )[:8]
        self.last_task_comparison = [dict(task) for task in self.task_queue[:6]]

    def assign_player_task(self, point_id):
        task = self._task_for_point(
            point_id,
            source="player",
            priority=48.0,
            duty_weight=0.95,
            issuer_label="Player",
        )
        if task is None:
            return False
        task = self._score_task(task)

        self.task_queue = [
            queued
            for queued in self.task_queue
            if not (
                queued.get("source") == "player"
                and queued.get("point_id") == point_id
            )
        ]
        self.task_queue.insert(0, task)

        if self.control_mode == self.CONTROL_AUTONOMOUS and isinstance(self.active_task, dict):
            if self.active_task.get("source") != "player":
                self.active_task["phase"] = "moving"
                self.task_queue.insert(1, self.active_task)
                self.active_task = None
                self.active_task_elapsed = 0.0

        self.last_status = f"Player queued: {task['label']}"
        return True

    def assign_external_task(
        self,
        point_id,
        *,
        label=None,
        issuer_id=None,
        issuer_label=None,
        duty_weight=0.75,
        coercion=0.0,
        action_tags=None,
        alternative_point_id=None,
        repeating=False,
    ):
        """Allocate a duty from another person, faction, or institution."""
        self._task_serial += 1
        task = self._task_for_point(
            point_id,
            source="external",
            priority=24.0,
            id=f"external:{self._task_serial}:{point_id}",
            issuer_id=issuer_id,
            issuer_label=issuer_label or self._display_entity_value(issuer_id) or "External authority",
            duty_weight=self._bounded_score(duty_weight, 0.75),
            coercion=self._bounded_score(coercion, 0.0),
            action_tags=list(action_tags or []),
            alternative_point_id=alternative_point_id,
            repeating=bool(repeating),
        )
        if task is None:
            return False
        if label:
            task["label"] = str(label)
        task = self._score_task(task)
        self.external_task_allocations.append(task)
        conviction_penalty = -sum(
            min(0.0, float(item.get("value", 0.0)))
            for item in task.get("score_breakdown", [])
        )
        if (
            conviction_penalty >= 100.0
            and alternative_point_id in self.test_points
            and task.get("suggested_alternatives")
        ):
            alternative_label = task["suggested_alternatives"][0]
            alternative = self._task_for_point(
                alternative_point_id,
                source="internal",
                priority=58.0,
                id=f"response:{task['id']}",
                motive="conviction",
                responding_to=task["id"],
            )
            alternative["label"] = f"Request reassignment: {alternative_label}"
            self.internal_task_allocations.append(alternative)
        self._fill_autonomous_queue()
        self.last_status = f"Duty assigned by {task['issuer_label']}: {task['label']}"
        return task["id"]

    def _build_internal_task(self, point_id, *, label=None, motive="goal", weight=0.5):
        """Construct and record a self-formed intention, without refilling
        the queue -- callers that already sit inside _fill_autonomous_queue
        (e.g. _goal_driven_internal_tasks) must use this directly to avoid
        recursing back into it via assign_internal_task."""
        self._task_serial += 1
        task = self._task_for_point(
            point_id,
            source="internal",
            priority=15.0 + self._bounded_score(weight, 0.5) * 45.0,
            id=f"internal:{self._task_serial}:{point_id}",
            motive=str(motive or "goal"),
        )
        if task is None:
            return None
        if label:
            task["label"] = str(label)
        self.internal_task_allocations.append(task)
        return task["id"]

    def assign_internal_task(self, point_id, *, label=None, motive="goal", weight=0.5):
        """Add a conscious intention formed by the person themself."""
        task_id = self._build_internal_task(point_id, label=label, motive=motive, weight=weight)
        if task_id is None:
            return False
        self._fill_autonomous_queue()
        return task_id

    def _record_decision(self, event, task, displaced=None):
        entry = {
            "event": str(event),
            "task_id": task.get("id"),
            "label": task.get("label", "Task"),
            "source": task.get("source", "internal"),
            "score": round(float(task.get("decision_score", 0.0)), 1),
            "explanation": task.get("decision_explanation", ""),
            "conviction_conflicts": list(task.get("conviction_conflicts") or []),
            "suggested_alternatives": list(task.get("suggested_alternatives") or []),
            "lifecycle_state": task.get("lifecycle_state", "proposed"),
            "action": task.get("action_label") or task.get("label", "Task"),
        }
        if displaced:
            entry["displaced"] = displaced.get("label")
        if task.get("failure_reason"):
            entry["failure_reason"] = task["failure_reason"]
            entry["explanation"] = f"Failed because {task['failure_reason']}. {entry['explanation']}"
        self.decision_history.insert(0, entry)
        del self.decision_history[20:]

    def _reconsider_active_task(self):
        if not isinstance(self.active_task, dict) or self.active_task.get("source") == "direct":
            return False
        self.active_task = self._score_task(self.active_task)
        self._fill_autonomous_queue()
        if not self.task_queue:
            return False
        challenger = self.task_queue[0]
        if challenger.get("decision_score", 0.0) <= self.active_task.get("decision_score", 0.0) + 14.0:
            return False
        displaced = self.active_task
        displaced["phase"] = "moving"
        displaced["lifecycle_state"] = "interrupted"
        displaced["elapsed"] = self.active_task_elapsed
        self.active_task = self.task_queue.pop(0)
        self.active_task["lifecycle_state"] = "travelling"
        self.active_task_elapsed = float(self.active_task.get("elapsed", 0.0) or 0.0)
        self._clear_navigation()
        self.last_status = f"Changed priority: {self.active_task['label']} over {displaced['label']}"
        self._record_decision("preempted", self.active_task, displaced=displaced)
        return True

    def _begin_next_queued_task(self):
        if self.active_task is not None:
            return
        self._fill_autonomous_queue()
        if self.task_queue:
            self.active_task = self.task_queue.pop(0)
            self.active_task["lifecycle_state"] = "accepted"
            self.active_task["phase"] = "moving"
            self.active_task["lifecycle_state"] = "travelling"
            self.active_task_elapsed = float(self.active_task.get("elapsed", 0.0) or 0.0)
            self._clear_navigation()
            self.last_status = f"Going to {self.active_task['label']}"
            self._record_decision("selected", self.active_task)

    @staticmethod
    def _segments_intersect(a, b, c, d):
        def orientation(p, q, r):
            value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
            if abs(value) < 1e-8:
                return 0
            return 1 if value > 0 else 2

        def on_segment(p, q, r):
            return (
                min(p[0], r[0]) - 1e-8 <= q[0] <= max(p[0], r[0]) + 1e-8
                and min(p[1], r[1]) - 1e-8 <= q[1] <= max(p[1], r[1]) + 1e-8
            )

        o1 = orientation(a, b, c)
        o2 = orientation(a, b, d)
        o3 = orientation(c, d, a)
        o4 = orientation(c, d, b)
        if o1 != o2 and o3 != o4:
            return True
        return (
            (o1 == 0 and on_segment(a, c, b))
            or (o2 == 0 and on_segment(a, d, b))
            or (o3 == 0 and on_segment(c, a, d))
            or (o4 == 0 and on_segment(c, b, d))
        )

    def _segment_blocked(self, start, end):
        if math.dist(start, end) < 1e-8:
            return False
        return any(
            self._segments_intersect(start, end, wall_start, wall_end)
            for wall_start, wall_end in self.wall_segments
        )

    def _nav_node_valid(self, node):
        x, y = node
        if not (
            self.bounds["min_x"] + 0.25 <= x <= self.bounds["max_x"] - 0.25
            and self.bounds["min_y"] + 0.25 <= y <= self.bounds["max_y"] - 0.25
        ):
            return False
        return not any(
            abs((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) < 1e-8
            and min(a[0], b[0]) - 1e-8 <= x <= max(a[0], b[0]) + 1e-8
            and min(a[1], b[1]) - 1e-8 <= y <= max(a[1], b[1]) + 1e-8
            for a, b in self.wall_segments
        )

    def _nearest_nav_node(self, point):
        base = (int(round(point[0])), int(round(point[1])))
        candidates = []
        for radius in range(0, 4):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    node = (base[0] + dx, base[1] + dy)
                    if self._nav_node_valid(node) and not self._segment_blocked(point, node):
                        candidates.append((math.dist(point, node), node))
            if candidates:
                return min(candidates)[1]
        return base

    def _plan_route(self, start, target):
        start = self._point_pair(start)
        target = self._point_pair(target)
        if not self.wall_segments or not self._segment_blocked(start, target):
            return [target]

        start_node = self._nearest_nav_node(start)
        target_node = self._nearest_nav_node(target)
        frontier = [(0.0, start_node)]
        came_from = {start_node: None}
        cost_so_far = {start_node: 0.0}
        while frontier:
            _priority, current = heapq.heappop(frontier)
            if current == target_node:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (current[0] + dx, current[1] + dy)
                if not self._nav_node_valid(neighbor) or self._segment_blocked(current, neighbor):
                    continue
                new_cost = cost_so_far[current] + 1.0
                if new_cost >= cost_so_far.get(neighbor, math.inf):
                    continue
                cost_so_far[neighbor] = new_cost
                heuristic = abs(target_node[0] - neighbor[0]) + abs(target_node[1] - neighbor[1])
                heapq.heappush(frontier, (new_cost + heuristic, neighbor))
                came_from[neighbor] = current

        if target_node not in came_from:
            return []
        nodes = []
        current = target_node
        while current is not None:
            nodes.append((float(current[0]), float(current[1])))
            current = came_from[current]
        nodes.reverse()
        route = nodes[1:] + [target]

        smoothed = []
        anchor = start
        index = 0
        while index < len(route):
            furthest = index
            for candidate_index in range(index, len(route)):
                if self._segment_blocked(anchor, route[candidate_index]):
                    break
                furthest = candidate_index
            waypoint = route[furthest]
            smoothed.append(waypoint)
            anchor = waypoint
            index = furthest + 1
        return smoothed

    def _record_navigation(self, event, reason, **details):
        entry = {
            "event": str(event or "navigation"),
            "reason": str(reason or ""),
            "mode": self.navigation_mode,
            "destination_entity_id": self.navigation_destination_entity_id,
            **details,
        }
        if self.navigation_history and all(
            self.navigation_history[0].get(key) == entry.get(key)
            for key in ("event", "reason", "mode", "destination_entity_id")
        ):
            return
        self.navigation_history.insert(0, entry)
        del self.navigation_history[30:]

    def _raw_navigation_knowledge(self, person_id, destination_entity_id):
        if not destination_entity_id:
            return None
        person = self.get_person(person_id) or {}
        raw_records = person.get("knowledge_records") or person.get("knowledge") or []
        if isinstance(raw_records, dict):
            raw_records = [raw_records]
        for raw in raw_records if isinstance(raw_records, (list, tuple)) else []:
            if isinstance(raw, str):
                raw = {"entity": raw}
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity") or raw.get("subject") or raw.get("entity_id") or "").strip()
            if entity_id == destination_entity_id:
                return dict(raw)
        return None

    @staticmethod
    def _navigation_knowledge_kind(record):
        if not isinstance(record, dict):
            return "unknown"
        declared = str(
            record.get("navigation_knowledge")
            or record.get("wayfinding_knowledge")
            or ""
        ).strip().casefold()
        if record.get("route_waypoints") or declared in {"route", "known route", "way"}:
            return "route"
        if record.get("direction_hint") or declared in {"direction", "direction only", "heading"}:
            return "direction"
        return "unknown"

    def _task_navigation_destination_entity_id(self, task):
        step = self._current_task_step(task)
        candidates = []
        if isinstance(step, dict):
            candidates.extend((step.get("destination_entity_id"), step.get("asset_id")))
            point = self.test_points.get(step.get("point_id")) or {}
            candidates.append(point.get("asset_id"))
        point = self.test_points.get((task or {}).get("point_id")) or {}
        candidates.extend(((task or {}).get("destination_entity_id"), point.get("asset_id")))
        for candidate in candidates:
            entity_id = str(candidate or "").strip()
            entity = self.get_person(entity_id) or {}
            if entity_id and (entity.get("type") == "location" or entity.get("_dataset") == "locations"):
                return entity_id
        return ""

    def _known_waypoint_path(self, start, target, record):
        raw_waypoints = (record or {}).get("route_waypoints") or []
        waypoints = []
        for value in raw_waypoints:
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                continue
            try:
                waypoints.append((float(value[0]), float(value[1])))
            except (TypeError, ValueError):
                continue
        if not waypoints:
            return self._plan_route(start, target)
        if math.hypot(waypoints[-1][0] - target[0], waypoints[-1][1] - target[1]) > self.arrival_radius_m:
            waypoints.append(target)

        reachable = [
            (math.hypot(point[0] - start[0], point[1] - start[1]), index)
            for index, point in enumerate(waypoints)
            if not self._segment_blocked(start, point)
        ]
        if not reachable:
            return []
        _distance, first_index = min(reachable)
        route = waypoints[first_index:]
        cursor = start
        for waypoint in route:
            if self._segment_blocked(cursor, waypoint):
                return []
            cursor = waypoint
        return route

    @staticmethod
    def _unit_vector(vector, fallback=(1.0, 0.0)):
        try:
            dx, dy = float(vector[0]), float(vector[1])
        except (TypeError, ValueError, IndexError):
            dx, dy = fallback
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            dx, dy = fallback
            length = max(1e-8, math.hypot(dx, dy))
        return dx / length, dy / length

    def _direction_probe_path(self, target, heading=None):
        start = tuple(self.position)
        if heading is None:
            heading = (target[0] - start[0], target[1] - start[1])
        heading = self._unit_vector(heading, fallback=(target[0] - start[0], target[1] - start[1]))
        self.navigation_heading = heading
        distance_to_target = math.hypot(target[0] - start[0], target[1] - start[1])
        probe_distance = min(8.0, distance_to_target)
        probe = (
            max(self.bounds["min_x"], min(self.bounds["max_x"], start[0] + heading[0] * probe_distance)),
            max(self.bounds["min_y"], min(self.bounds["max_y"], start[1] + heading[1] * probe_distance)),
        )
        if math.hypot(probe[0] - start[0], probe[1] - start[1]) <= self.arrival_radius_m:
            return []
        return self._plan_route(start, probe)

    def _should_ask_for_directions(self):
        personality = self._personality_scores()
        sociability = (personality.get("extraversion", 0.5) + personality.get("agreeableness", 0.5)) / 2.0
        available = [
            resident for resident in self.site_people
            if not resident.get("controlled") and resident.get("entity_id") not in self.navigation_people_asked
        ]
        return bool(available) and sociability >= 0.5

    def _start_asking_for_directions(self, target):
        candidates = []
        for resident in self.site_people:
            person_id = resident.get("entity_id")
            if resident.get("controlled") or not person_id or person_id in self.navigation_people_asked:
                continue
            position = self._point_pair(resident.get("position"))
            distance = math.hypot(position[0] - self.position[0], position[1] - self.position[1])
            candidates.append((distance, str(person_id), position, resident.get("label") or person_id))
        if not candidates:
            return False
        _distance, person_id, position, label = min(candidates)
        route = self._plan_route(tuple(self.position), position)
        if not route and math.hypot(position[0] - self.position[0], position[1] - self.position[1]) > self.arrival_radius_m:
            self.navigation_people_asked.add(person_id)
            return self._start_asking_for_directions(target)
        self.navigation_mode = "asking"
        self.navigation_ask_person_id = person_id
        self.navigation_path = route
        self.last_status = f"Asking {label} for directions"
        self._record_navigation("ask", f"No known route; asking {label}", person_id=person_id, person_label=label)
        return True

    def _adopt_navigation_knowledge(self, record, target, *, source_label=None):
        kind = self._navigation_knowledge_kind(record)
        if kind == "route":
            route = self._known_waypoint_path(tuple(self.position), target, record)
            if route:
                self.navigation_mode = "known_route"
                self.navigation_path = route
                reason = "Following a known route" if not source_label else f"Following directions from {source_label}"
                self.last_status = reason
                self._record_navigation("route", reason, source=source_label or "own knowledge")
                return True
            self._record_navigation("route_blocked", "The known route no longer appears passable")
            return False
        if kind == "direction":
            self.navigation_mode = "direction"
            self.navigation_path = self._direction_probe_path(target, record.get("direction_hint"))
            if self.navigation_path:
                reason = "Starting in the known direction" if not source_label else f"Starting in the direction given by {source_label}"
                self.last_status = reason
                self._record_navigation("direction", reason, source=source_label or "own knowledge")
                return True
        return False

    def _resolve_asked_directions(self, target):
        person_id = self.navigation_ask_person_id
        resident = self.get_person(person_id) or {}
        label = resident.get("pretty_name") or resident.get("name") or person_id or "resident"
        if person_id:
            self.navigation_people_asked.add(person_id)
        record = self._raw_navigation_knowledge(person_id, self.navigation_destination_entity_id)
        self.navigation_ask_person_id = None
        if self._adopt_navigation_knowledge(record, target, source_label=label):
            return True
        self._record_navigation("no_answer", f"{label} does not know the way", person_id=person_id)
        if self._start_asking_for_directions(target):
            return True
        self.navigation_mode = "direction"
        self.navigation_path = self._direction_probe_path(target, self.navigation_heading)
        self.last_status = f"No one knows the way; continuing toward {self.navigation_destination_entity_id or 'the destination'}"
        return bool(self.navigation_path)

    def _begin_knowledge_navigation(self, target, destination_entity_id, *, guided=False):
        self.navigation_destination = target
        self.navigation_destination_entity_id = destination_entity_id or None
        if guided:
            self.navigation_mode = "guided"
            self.navigation_path = self._plan_route(tuple(self.position), target)
            self._record_navigation("guided", "Following the player's direct guidance")
            return bool(self.navigation_path)

        record = self._raw_navigation_knowledge(self.person_entity_id, destination_entity_id)
        if self._adopt_navigation_knowledge(record, target):
            return True
        if not self._segment_blocked(tuple(self.position), target):
            self.navigation_mode = "visible"
            self.navigation_path = [target]
            self.last_status = "Destination is visible; going directly"
            self._record_navigation("visible", "Destination is directly visible")
            return True
        if self._should_ask_for_directions() and self._start_asking_for_directions(target):
            return True
        self.navigation_mode = "direction"
        self.navigation_path = self._direction_probe_path(target)
        self.last_status = "Route unknown; continuing in the destination's direction"
        self._record_navigation("continue", self.last_status)
        return bool(self.navigation_path)

    def _continue_uncertain_navigation(self, target):
        if self.navigation_mode == "asking":
            return self._resolve_asked_directions(target)
        if self._should_ask_for_directions() and self._start_asking_for_directions(target):
            return True
        self.navigation_mode = "direction"
        self.navigation_path = self._direction_probe_path(target, self.navigation_heading)
        if self.navigation_path:
            self.last_status = "Still uncertain; continuing in the same direction"
            self._record_navigation("continue", self.last_status)
            return True
        self.last_status = "Unable to find a way forward"
        self._record_navigation("stuck", self.last_status)
        return False

    def _clear_navigation(self):
        self.navigation_path = []
        self.navigation_destination = None
        self.navigation_destination_entity_id = None
        self.navigation_mode = "idle"
        self.navigation_heading = None
        self.navigation_ask_person_id = None
        self.navigation_people_asked = set()

    def _advance_toward(self, target, dt, *, destination_entity_id="", guided=False):
        target = self._point_pair(target)
        if self.navigation_destination != target:
            if not self._begin_knowledge_navigation(target, destination_entity_id, guided=guided):
                self.last_status = "No route through available openings"
                return False

        remaining_travel = self.move_speed_m_per_second * dt
        while self.navigation_path and remaining_travel > 0.0:
            waypoint = self.navigation_path[0]
            dx = waypoint[0] - self.position[0]
            dy = waypoint[1] - self.position[1]
            distance = math.hypot(dx, dy)
            if distance <= self.arrival_radius_m:
                self.position[:] = [waypoint[0], waypoint[1]]
                self.navigation_path.pop(0)
                continue
            travel = min(distance, remaining_travel)
            self.position[0] += dx / distance * travel
            self.position[1] += dy / distance * travel
            remaining_travel -= travel
            if travel >= distance - self.arrival_radius_m:
                self.position[:] = [waypoint[0], waypoint[1]]
                self.navigation_path.pop(0)
        if not self.navigation_path:
            if math.hypot(target[0] - self.position[0], target[1] - self.position[1]) <= self.arrival_radius_m:
                self.position[:] = [target[0], target[1]]
                self._clear_navigation()
                return True
            self._continue_uncertain_navigation(target)
        return False

    def _advance_active_task(self, dt):
        task = self.active_task
        if not isinstance(task, dict):
            return False

        if task.get("phase") == "moving":
            if not self._advance_toward(
                task["target"],
                dt,
                destination_entity_id=self._task_navigation_destination_entity_id(task),
                guided=task.get("source") == "direct",
            ):
                return False
            access = self._task_step_access_report(task)
            if not access.get("allowed", False):
                self._fail_task(task, access.get("reason") or "interaction unavailable")
                return True
            task["phase"] = "using"
            task["lifecycle_state"] = "executing"
            self.active_task_elapsed = 0.0
            task["elapsed"] = 0.0
            self.last_status = f"{task.get('action_label') or 'Using ' + task['label']}"
            return False

        self.active_task_elapsed += dt
        task["elapsed"] = self.active_task_elapsed
        if self.active_task_elapsed < task.get("duration", 0.0):
            return False

        step = self._current_task_step(task)
        if step is not None:
            succeeded, reason = self._complete_multi_step_action(step)
            if not succeeded:
                self._fail_task(task, reason)
                return True
            next_index = int(task.get("step_index", 0) or 0) + 1
            if next_index < len(task.get("steps") or []):
                self.active_task_elapsed = 0.0
                task["elapsed"] = 0.0
                self._set_task_step(task, next_index)
                self.last_status = f"Next: {task.get('action_label', task.get('label', 'task'))}"
                self._record_decision("advanced", task)
                return False

        self._complete_task(task)
        self.active_task = None
        self.active_task_elapsed = 0.0
        return True

    def _complete_task(self, task):
        point_id = task.get("point_id")
        if point_id == "bed":
            self.needs["rest"] = min(100.0, self.needs["rest"] + 62.0)
            self.needs["safety"] = min(100.0, self.needs["safety"] + 4.0)
        elif point_id == "job":
            self.work_due = max(0.0, self.work_due - 64.0)
            self.needs["esteem"] = min(100.0, self.needs["esteem"] + 12.0)
            self.completed_jobs += 1
        elif point_id == "target":
            self.needs["leisure"] = min(100.0, self.needs["leisure"] + 54.0)
            self.needs["esteem"] = min(100.0, self.needs["esteem"] + 4.0)
        task["lifecycle_state"] = "completed"
        task["elapsed"] = 0.0
        self.last_status = f"Completed {task.get('label', point_id or 'task')}"
        if not task.get("repeating"):
            task_id = task.get("id")
            self.external_task_allocations = [
                item for item in self.external_task_allocations if item.get("id") != task_id
            ]
            self.internal_task_allocations = [
                item for item in self.internal_task_allocations if item.get("id") != task_id
            ]
        self._record_decision("completed", task)
        self._clear_navigation()

    def _fail_task(self, task, reason):
        task["lifecycle_state"] = "failed"
        task["failure_reason"] = str(reason or "interaction failed")
        task["elapsed"] = self.active_task_elapsed
        self.last_status = f"Could not {task.get('action_label', task.get('label', 'complete task'))}: {task['failure_reason']}"
        self._record_decision("failed", task)
        task_id = task.get("id")
        self.external_task_allocations = [
            item for item in self.external_task_allocations if item.get("id") != task_id
        ]
        self.internal_task_allocations = [
            item for item in self.internal_task_allocations if item.get("id") != task_id
        ]
        if self.active_task is task:
            self.active_task = None
            self.active_task_elapsed = 0.0
        self._clear_navigation()

    def _update_autonomous_control(self, dt):
        self._reconsider_active_task()
        self._begin_next_queued_task()
        if self._advance_active_task(dt):
            self._fill_autonomous_queue()

    def _update_direct_control(self, dt):
        if isinstance(self.active_task, dict) and self.active_task.get("source") == "direct":
            self._advance_active_task(dt)
            return
        if self.direct_target is not None and self._advance_toward(self.direct_target, dt, guided=True):
            self.direct_target = None
            self.last_status = "Direct destination reached"

    def set_control_mode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in self.VALID_CONTROL_MODES:
            return False
        if mode == self.control_mode:
            return True

        if isinstance(self.active_task, dict):
            source = self.active_task.get("source")
            if mode == self.CONTROL_DIRECT and source != "direct":
                self.active_task["phase"] = "moving"
                self.active_task["lifecycle_state"] = "interrupted"
                self.active_task["elapsed"] = self.active_task_elapsed
                self.task_queue.insert(0, self.active_task)
            self.active_task = None
            self.active_task_elapsed = 0.0

        self.direct_target = None
        self._clear_navigation()
        self.control_mode = mode
        if mode == self.CONTROL_AUTONOMOUS:
            self._fill_autonomous_queue()
            self.last_status = "Autonomous task selection resumed"
        else:
            self.last_status = "Direct control: click a destination"
        return True

    def command_direct_move(self, target, point_id=None):
        if self.control_mode != self.CONTROL_DIRECT:
            return False
        x = max(self.bounds["min_x"], min(self.bounds["max_x"], float(target[0])))
        y = max(self.bounds["min_y"], min(self.bounds["max_y"], float(target[1])))
        self.direct_target = None
        self.active_task = None
        self.active_task_elapsed = 0.0
        self._clear_navigation()

        if point_id in self.test_points:
            self.active_task = self._score_task(
                self._task_for_point(point_id, source="direct", priority=1000.0)
            )
            self.active_task["lifecycle_state"] = "travelling"
            self.last_status = f"Direct order: use {self.active_task['label']}"
        else:
            self.direct_target = (x, y)
            self.last_status = "Direct movement order"
        return True

    def cancel_direct_order(self):
        if self.control_mode != self.CONTROL_DIRECT:
            return False
        self.direct_target = None
        self._clear_navigation()
        if isinstance(self.active_task, dict) and self.active_task.get("source") == "direct":
            self.active_task["lifecycle_state"] = "interrupted"
            self.active_task = None
            self.active_task_elapsed = 0.0
        self.last_status = "Direct order cancelled"
        return True

    def get_test_points(self):
        return [dict(point) for point in self.test_points.values()]

    def get_person_render_payload(self):
        destination = self.direct_target
        if isinstance(self.active_task, dict):
            destination = self.active_task.get("target")
        return {
            "bounds": dict(self.bounds),
            "site_id": self.site_entity_id,
            "in_void": self.in_void,
            "site_label": (
                self.site_entity.get("pretty_name")
                or self.site_entity.get("name")
                or ("Unbound void -- no site authored yet" if self.in_void else "Person Test Site")
            ),
            "terrain_zones": list(self.site_entity.get("terrain_zones") or []),
            "structures": list(self.site_structures),
            "site_people": list(self.site_people),
            "wall_segments": list(self.wall_segments),
            "openings": list(self.openings),
            "position": tuple(self.position),
            "points": self.get_test_points(),
            "control_mode": self.control_mode,
            "destination": destination,
            "route_points": list(self.navigation_path),
            "navigation_mode": self.navigation_mode,
            "navigation_destination_entity_id": self.navigation_destination_entity_id,
            "navigation_history": list(self.navigation_history[:5]),
            "hover_point_id": self.hover_point_id,
            "active_point_id": (self.active_task or {}).get("interaction_point_id") or (self.active_task or {}).get("point_id"),
            "active_phase": (self.active_task or {}).get("phase"),
            "needs_character_creation": self.needs_character_creation,
            "character_readiness_tier": self.character_readiness["tier"],
            "character_readiness_missing": list(self.character_readiness["missing"]),
            "asset_palette": list(self.asset_palette),
            "placement_mode": self.placement_mode,
            "placement_selected_asset_id": self.placement_selected_asset_id,
        }

    def _point_at_world_position(self, world_x, world_y):
        closest = None
        closest_distance = math.inf
        for point in self.test_points.values():
            px, py = point["position"]
            distance = math.hypot(float(world_x) - px, float(world_y) - py)
            if distance <= 1.55 and distance < closest_distance:
                closest = point
                closest_distance = distance
        return closest

    def handle_pointer_motion(self, event, camera, screen_pos):
        world_x, world_y = camera.screen_to_world(screen_pos)
        point = self._point_at_world_position(world_x, world_y)
        self.hover_point_id = point.get("id") if point else None

    def handle_pointer_event(self, event, camera, screen_pos):
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        if self.placement_mode:
            if event.button == 1:
                world_x, world_y = camera.screen_to_world(screen_pos)
                self.place_selected_asset((world_x, world_y))
            else:
                self.cancel_asset_placement()
            return
        if event.button == 3:
            if not self.cancel_direct_order():
                world_x, world_y = camera.screen_to_world(screen_pos)
                point = self._point_at_world_position(world_x, world_y)
                asset_id = point.get("asset_id") if point else None
                if asset_id:
                    self.open_entity_card(asset_id, mode="inspect", familiarity=self._familiarity_for(asset_id))
            return
        if event.button != 1:
            return

        world_x, world_y = camera.screen_to_world(screen_pos)
        point = self._point_at_world_position(world_x, world_y)
        if self.control_mode == self.CONTROL_DIRECT:
            self.command_direct_move(
                (world_x, world_y),
                point_id=point.get("id") if point else None,
            )
        elif point is not None:
            self.assign_player_task(point.get("id"))

    def _relation_ids(self, value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple, set)):
            return [item for item in value if isinstance(item, str) and item]
        return []

    def _refresh_job_point_label(self):
        person = self.get_person() or {}
        label = "Test Job"
        job_ids = self._relation_ids(person.get("is_employed_as"))
        if job_ids:
            job = self.get_person(job_ids[0]) or {}
            label = job.get("pretty_name") or job.get("name") or job_ids[0]
        self.test_points["job"]["label"] = label

    def _load_authored_task_allocations(self):
        person = self.get_person() or {}
        for task_id in self._relation_ids(person.get("assigned_tasks")):
            authored = self.get_person(task_id) or {}
            action_tags = authored.get("action_tags") or []
            if isinstance(action_tags, str):
                action_tags = [action_tags]
            point_id = str(
                authored.get("person_test_point")
                or authored.get("point_id")
                or "job"
            )
            if point_id not in self.test_points:
                continue
            self._task_serial += 1
            task = self._task_for_point(
                point_id,
                source="external",
                priority=float(authored.get("base_priority", 24.0) or 24.0),
                id=f"authored:{task_id}",
                issuer_id=authored.get("issuer") or authored.get("assigned_by"),
                issuer_label=self._display_entity_value(authored.get("issuer") or authored.get("assigned_by")) or "Assigned duty",
                duty_weight=self._bounded_score(authored.get("duty_weight"), 0.7),
                coercion=self._bounded_score(authored.get("coercion"), 0.0),
                action_tags=list(action_tags),
                repeating=bool(authored.get("repeating", False)),
            )
            if task is not None:
                task["label"] = str(authored.get("pretty_name") or authored.get("name") or task["label"])
                self.external_task_allocations.append(task)

    def get_person(self, person_entity_id=None):
        if self.world_model is None:
            return None
        return self.world_model.get_entity(person_entity_id or self.person_entity_id)

    def get_person_name(self):
        person = self.get_person() or {}
        return (
            person.get("pretty_name")
            or person.get("name")
            or self.person_entity_id
            or "Person"
        )

    def get_person_class(self):
        person = self.get_person() or {}
        return person.get("person_class") or person.get("type") or "person"

    def get_history_timeline_title(self):
        return "Person History"

    def get_year_context_label(self):
        return f"Year {int(self.year)}"

    def set_year(self, year):
        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        if year == self.year:
            return False

        self.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0
        logger.info(f"[PersonSimulation] Selected history year {year}")
        return True

    def open_entity_card(self, entity_id, *, mode="edit", familiarity=None):
        """Request a floating card for entity_id -- drained by UIManager each frame.

        mode="edit" opens the real entity, fully editable, identical to the
        repository browser. mode="inspect" opens a familiarity-redacted,
        read-only view (see ui/ui_manager.py's floating-card handling).
        """
        if not entity_id:
            return False
        self._pending_floating_card_target = {
            "id": entity_id,
            "mode": mode,
            "familiarity": familiarity,
        }
        return True

    def consume_pending_floating_card_target(self):
        target = self._pending_floating_card_target
        self._pending_floating_card_target = None
        return target

    def _familiarity_for(self, entity_id):
        """How much the controlled person currently knows about entity_id, 0.0-1.0."""
        if not entity_id:
            return 0.0
        for record in self._knowledge_records():
            if record.get("entity_id") == entity_id:
                return float(record.get("familiarity", 0.35))
        return 0.0

    def open_person_inspector(self):
        if self.get_person() is None:
            return False

        self._pending_inspector_target = {
            "kind": "person",
            "id": self.person_entity_id,
        }
        return True

    def open_character_editor(self):
        """Open the full generic entity editor on this person, in edit mode.

        Unlike open_person_inspector (name/notes only, see
        save_selection_inspector_updates), this reuses the same
        schema-driven floating-card editor the toolbelt's "Character
        Editor" tool jumps within -- it already exposes every authored
        field, including personality/knowledge/wishes, so no bespoke
        field-editing UI needs to exist yet.
        """
        return self.open_entity_card(self.person_entity_id, mode="edit")

    def consume_pending_inspector_target(self):
        target = self._pending_inspector_target
        self._pending_inspector_target = None
        return target

    def get_dossier_panel_lines(self):
        person = self.get_person() or {}
        lines = [
            f"Class: {self.get_person_class()}",
            f"Anchor: {self._anchor_year_label(person)}",
        ]

        for label, key in (
            ("Factions", "affiliated_factions"),
            ("Institutions", "affiliated_institutions"),
            ("Locations", "associated_locations"),
            ("Events", "participated_events"),
        ):
            values = person.get(key) or []
            if isinstance(values, str):
                values = [values]
            if values:
                lines.append(f"{label}: {', '.join(str(value) for value in values[:3])}")

        notes = str(person.get("wiki_entry") or person.get("notes") or person.get("description") or "").strip()
        if notes:
            short_notes = notes.replace("\n", " ")
            if len(short_notes) > 96:
                short_notes = short_notes[:93].rstrip() + "..."
            lines.append(f"Notes: {short_notes}")

        active = self.active_task or {}
        queue_labels = [
            f"{'!' if task.get('source') == 'player' else ''}{task.get('label', 'Task')}"
            for task in self.task_queue[:4]
        ]
        lines.extend([
            f"Mode: {'Autonomous' if self.control_mode == self.CONTROL_AUTONOMOUS else 'Direct control'}",
            (
                f"Needs: food {self.needs['food']:.0f} | rest {self.needs['rest']:.0f} | "
                f"leisure {self.needs['leisure']:.0f}"
            ),
            f"Work due: {self.work_due:.0f} | jobs completed: {self.completed_jobs}",
            (
                f"Active: {active.get('label', 'none')} "
                f"({active.get('lifecycle_state', active.get('phase', 'idle'))})"
            ),
            f"Queue: {' > '.join(queue_labels) if queue_labels else 'empty'}",
            self.last_status,
        ])

        return lines

    def get_dossier_panel_model(self):
        """Compact, presentation-ready identity and current-state summary."""
        person = self.get_person() or {}

        affiliations = []
        for label, key in (
            ("Faction", "affiliated_factions"),
            ("Institution", "affiliated_institutions"),
            ("Place", "associated_locations"),
        ):
            values = person.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values[:2]:
                display = self._display_entity_value(value)
                entity = self.get_person(value) if isinstance(value, str) else None
                if entity:
                    display = self._display_entity_value(entity) or display
                if display:
                    affiliations.append({"kind": label, "label": display})

        active = self.active_task or {}
        return {
            "name": self.get_person_name(),
            "person_class": self.get_person_class(),
            "anchor": self._anchor_year_label(person),
            "mode": "Autonomous" if self.control_mode == self.CONTROL_AUTONOMOUS else "Direct",
            "affiliations": affiliations[:4],
            "needs": [
                {"id": "food", "label": "Food", "value": float(self.needs.get("food", 0.0))},
                {"id": "rest", "label": "Rest", "value": float(self.needs.get("rest", 0.0))},
                {"id": "leisure", "label": "Ease", "value": float(self.needs.get("leisure", 0.0))},
            ],
            "active_task": active.get("label") or "No active task",
            "active_phase": active.get("lifecycle_state") or active.get("phase") or "idle",
            "active_action": active.get("action_label") or active.get("label") or "No action",
            "queue_count": len(self.task_queue),
            "status": self.last_status,
        }

    def get_character_creation_panel_model(self):
        """Readiness tier plus what character creation would still need to fill."""
        readiness = self.character_readiness
        return {
            **readiness,
            "needs_character_creation": self.needs_character_creation,
            "prompt_lines": character_creation_prompt_lines(readiness, self.get_person_name()),
        }

    @staticmethod
    def _bounded_score(value, default=0.5):
        try:
            score = float(value)
        except (TypeError, ValueError):
            return float(default)
        if score > 1.0 and score <= 100.0:
            score /= 100.0
        return max(0.0, min(1.0, score))

    def _display_entity_value(self, value):
        if isinstance(value, dict):
            return str(
                value.get("pretty_name")
                or value.get("name")
                or value.get("label")
                or value.get("id")
                or ""
            ).strip()
        if isinstance(value, str):
            entity = self.get_person(value)
            if isinstance(entity, dict):
                return str(
                    entity.get("pretty_name")
                    or entity.get("name")
                    or entity.get("id")
                    or value
                ).strip()
            return value.strip()
        return str(value).strip() if value is not None else ""

    def _authored_list(self, person, *field_names):
        items = []
        for field_name in field_names:
            raw = person.get(field_name)
            if raw in (None, ""):
                continue
            values = raw if isinstance(raw, (list, tuple, set)) else [raw]
            for value in values:
                label = self._display_entity_value(value)
                if label and label not in items:
                    items.append(label)
        return items

    @staticmethod
    def _knowledge_category(entity, fallback="Other"):
        entity_type = str((entity or {}).get("type") or (entity or {}).get("_dataset") or "").casefold()
        if entity_type in {"person", "people", "pop", "species"}:
            return "People"
        if entity_type in {"location", "locations", "city", "cities", "building"}:
            return "Places"
        if entity_type in {"producer", "producers", "institution", "institutions", "faction", "factions", "employment", "job"}:
            return "Work & organizations"
        if entity_type in {"idea", "ideas", "culture", "cultural_aspect", "religion", "ideology", "worldview"}:
            return "Worldviews & ideas"
        if entity_type in {"technology", "technologies", "item", "component", "vehicle", "recipe", "recipes"}:
            return "Things & techniques"
        if entity_type in {"event", "events", "period", "conflict"}:
            return "Events & history"
        return fallback

    def _knowledge_records(self):
        """Normalize authored knowledge while accepting references to any card type."""
        person = self.get_person() or {}
        records = []
        raw_records = person.get("knowledge_records") or person.get("knowledge") or []
        if not isinstance(raw_records, (list, tuple, set)):
            raw_records = [raw_records]
        for raw in raw_records:
            if isinstance(raw, str):
                raw = {"entity": raw}
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            entity_id = str(
                record.get("entity")
                or record.get("subject")
                or record.get("entity_id")
                or ""
            ).strip()
            entity = self.get_person(entity_id) if entity_id else None
            if not isinstance(entity, dict):
                entity = {}
            label = str(
                record.get("label")
                or entity.get("pretty_name")
                or entity.get("name")
                or entity_id
                or "Unspecified knowledge"
            )
            record.update({
                "entity_id": entity_id,
                "label": label,
                "category": record.get("category") or self._knowledge_category(entity),
                "interest": self._bounded_score(record.get("interest"), default=0.5),
                "familiarity": self._bounded_score(record.get("familiarity"), default=0.35),
                "conviction": self._bounded_score(record.get("conviction"), default=0.0),
                "entity_type": entity.get("type") or entity.get("_dataset") or "unknown",
            })
            if not record.get("behavioral_rules") and isinstance(entity.get("behavioral_rules"), dict):
                record["behavioral_rules"] = dict(entity["behavioral_rules"])
            records.append(record)

        automatic_fields = (
            ("related", "People", 0.72),
            ("parents", "People", 0.76),
            ("offspring", "People", 0.84),
            ("associated_locations", "Places", 0.68),
            ("affiliated_institutions", "Work & organizations", 0.72),
            ("affiliated_factions", "Work & organizations", 0.72),
            ("is_employed_by", "Work & organizations", 0.82),
            ("is_employed_as", "Work & organizations", 0.8),
            ("is_employed_at", "Work & organizations", 0.78),
            ("worldviews", "Worldviews & ideas", 0.8),
            ("beliefs", "Worldviews & ideas", 0.82),
            ("cultural_aspects", "Worldviews & ideas", 0.74),
            ("known_entities", "Other", 0.5),
        )
        existing_ids = {record.get("entity_id") for record in records if record.get("entity_id")}
        for field_name, category, interest in automatic_fields:
            for entity_id in self._relation_ids(person.get(field_name)):
                if entity_id in existing_ids:
                    continue
                entity = self.get_person(entity_id) or {}
                records.append({
                    "entity_id": entity_id,
                    "label": self._display_entity_value(entity_id) or entity_id,
                    "category": self._knowledge_category(entity, category) if category == "Other" else category,
                    "interest": interest,
                    "familiarity": 0.6,
                    "conviction": 0.0,
                    "entity_type": entity.get("type") or entity.get("_dataset") or "unknown",
                    "source": field_name.replace("_", " "),
                    "behavioral_rules": entity.get("behavioral_rules") or {},
                })
                existing_ids.add(entity_id)
        return records

    def get_knowledge_panel_model(self):
        category_order = (
            "People",
            "Places",
            "Work & organizations",
            "Worldviews & ideas",
            "Things & techniques",
            "Events & history",
            "Other",
        )
        grouped = {category: [] for category in category_order}
        for record in self._knowledge_records():
            category = record.get("category") or "Other"
            grouped.setdefault(category, []).append(record)
        categories = []
        for category in category_order + tuple(key for key in grouped if key not in category_order):
            entries = grouped.get(category) or []
            if not entries:
                continue
            entries.sort(key=lambda entry: (-entry.get("interest", 0.0), entry.get("label", "")))
            categories.append({"id": category.casefold().replace(" ", "_"), "label": category, "entries": entries})
        return {
            "person_name": self.get_person_name(),
            "categories": categories,
            "entry_count": sum(len(category["entries"]) for category in categories),
        }

    def _inventory_item_model(self, item_id, quantity, *, holder=None):
        item = self.get_person(item_id) or {}
        return {
            "item_id": item_id,
            "label": item.get("pretty_name") or item.get("name") or item_id,
            "item_class": item.get("item_class") or "item",
            "quantity": self._clean_quantity(quantity),
            "unit": item.get("inventory_unit") or "unit",
            "stackable": bool(item.get("stackable", True)),
            "consumable": bool(item.get("consumable", False)),
            "food_satiation": item.get("food_satiation"),
            "holder": holder,
        }

    def get_inventory_panel_model(self):
        held = [
            self._inventory_item_model(item_id, quantity, holder=self.person_entity_id)
            for item_id, quantity in sorted(self.runtime_inventory.items())
            if float(quantity or 0.0) > 0.0
        ]
        nearby = []
        for point_id, inventory in self.container_inventories.items():
            holder_id = (self.test_points.get(point_id) or {}).get("asset_id")
            holder = self.get_person(holder_id) or {}
            holder_label = holder.get("pretty_name") or holder.get("name") or holder_id or point_id
            for item_id, quantity in sorted(inventory.items()):
                if float(quantity or 0.0) <= 0.0:
                    continue
                entry = self._inventory_item_model(item_id, quantity, holder=holder_id)
                entry["holder_label"] = holder_label
                nearby.append(entry)
        return {
            "person_name": self.get_person_name(),
            "held_items": held,
            "nearby_items": nearby,
            "history": list(self.inventory_history[:8]),
            "held_stack_count": len(held),
            "held_unit_count": self._clean_quantity(sum(float(item["quantity"]) for item in held)),
        }

    def get_task_panel_model(self):
        if self.control_mode == self.CONTROL_AUTONOMOUS:
            self._fill_autonomous_queue()
        active = self._score_task(self.active_task) if isinstance(self.active_task, dict) else None
        if active is not None:
            self.active_task = active
        comparisons = [dict(task) for task in ([active] if active else []) + list(self.task_queue[:7])]
        comparisons.sort(key=lambda task: -task.get("decision_score", 0.0))
        personality = self._personality_scores()
        for task in comparisons:
            conflicts = task.get("conviction_conflicts") or []
            if not conflicts:
                task["likely_response"] = "Proceed normally"
            elif task.get("suggested_alternatives"):
                task["likely_response"] = "Seek reassignment: " + ", ".join(task["suggested_alternatives"][:2])
            elif personality.get("agreeableness", 0.5) < 0.45:
                task["likely_response"] = "Likely refusal or deliberate non-compliance"
            elif personality.get("conscientiousness", 0.5) > 0.72:
                task["likely_response"] = "Distressed compliance or hesitation"
            else:
                task["likely_response"] = "Hesitation or partial compliance"
        displayed_comparisons = comparisons[:5]
        conflicted = [task for task in comparisons if task.get("conviction_conflicts")]
        if conflicted and conflicted[0] not in displayed_comparisons:
            if displayed_comparisons:
                displayed_comparisons[-1] = conflicted[0]
            else:
                displayed_comparisons = [conflicted[0]]
        return {
            "person_name": self.get_person_name(),
            "active": active,
            "queue": list(self.task_queue[:7]),
            "comparisons": displayed_comparisons,
            "history": list(self.decision_history[:5]),
            "external_count": len(self.external_task_allocations),
            "internal_count": len(self.internal_task_allocations),
            "status": self.last_status,
            "navigation": {
                "mode": self.navigation_mode,
                "destination_entity_id": self.navigation_destination_entity_id,
                "heading": self.navigation_heading,
                "asking_person_id": self.navigation_ask_person_id,
                "history": list(self.navigation_history[:5]),
            },
        }

    def employment_pressure(self):
        """Base (duty_weight, coercion) derived from this person's job
        criticality (is_employed_as) and employer discipline
        (is_employed_by) -- the raw "how seriously is this job normally
        taken, how strict is the employer" input. This combines with
        personality in _score_task (assign_external_task's duty_weight/
        coercion params); it is not a substitute for that -- a lazy child
        watching an orchard and a heavily indoctrinated soldier can share
        the same job_criticality/employer_discipline_level and still land
        very differently once conscientiousness/agreeableness/neuroticism
        are applied. Falls back to a moderate default when no employment
        (or no criticality/discipline data) is authored.
        """
        person = self.get_person() or {}
        job_ids = self._relation_ids(person.get("is_employed_as"))
        job = self.get_person(job_ids[0]) if job_ids else None
        # 0.75 matches assign_external_task's own default duty_weight, so a
        # person with no authored job_criticality behaves the same as if no
        # employment-derived weight were being passed at all.
        duty_weight = self._bounded_score((job or {}).get("job_criticality"), default=0.75)

        coercion = 0.0
        discipline_levels = []
        for employer_id in self._relation_ids(person.get("is_employed_by")):
            employer = self.get_person(employer_id) or {}
            level = employer.get("employer_discipline_level")
            if level is not None:
                discipline_levels.append(self._bounded_score(level, default=0.0))
        if discipline_levels:
            coercion = max(discipline_levels)
        return duty_weight, coercion

    def _assigned_job_labels(self, person):
        labels = []
        for job_id in self._relation_ids(person.get("is_employed_as")):
            label = self._display_entity_value(job_id)
            if label and label not in labels:
                labels.append(label)
        return labels

    def get_needs_panel_model(self):
        """Return current need pressure plus durable wishes and goals for the UI."""
        person = self.get_person() or {}
        physiological = (self.needs.get("food", 0.0) + self.needs.get("rest", 0.0)) / 2.0
        tiers = [
            {
                "id": "physiological",
                "label": "Physiological",
                "score": physiological / 100.0,
                "components": (
                    f"Food {self.needs.get('food', 0.0):.0f}  |  "
                    f"Rest {self.needs.get('rest', 0.0):.0f}"
                ),
            },
            {
                "id": "safety",
                "label": "Safety",
                "score": self.needs.get("safety", 0.0) / 100.0,
                "components": f"Safety {self.needs.get('safety', 0.0):.0f}",
            },
            {
                "id": "belonging",
                "label": "Love & belonging",
                "score": self.needs.get("belonging", 0.0) / 100.0,
                "components": f"Belonging {self.needs.get('belonging', 0.0):.0f}",
            },
            {
                "id": "esteem",
                "label": "Esteem",
                "score": self.needs.get("esteem", 0.0) / 100.0,
                "components": f"Esteem {self.needs.get('esteem', 0.0):.0f}",
            },
            {
                "id": "self_actualization",
                "label": "Self-actualization",
                "score": self.needs.get("leisure", 0.0) / 100.0,
                "components": f"Prototype leisure driver {self.needs.get('leisure', 0.0):.0f}",
            },
        ]

        authored_wishes = self._authored_list(
            person,
            "wishes",
            "personal_wishes",
            "desires",
            "preferred_leisure",
        )
        current_wishes = []
        if self.needs.get("food", 100.0) < 60.0:
            current_wishes.append("Eat something")
        if self.needs.get("rest", 100.0) < 60.0:
            current_wishes.append("Get some rest")
        if self.needs.get("leisure", 100.0) < 60.0:
            current_wishes.append("Spend leisure time at Target")

        authored_goals = self._authored_list(
            person,
            "goals",
            "personal_goals",
            "long_term_goals",
        )
        authored_dreams = self._authored_list(person, "dreams", "personal_dreams")
        assigned_jobs = self._assigned_job_labels(person)
        queued_goals = []
        for task in ([self.active_task] if self.active_task else []) + list(self.task_queue):
            if not isinstance(task, dict):
                continue
            label = str(task.get("label") or "").strip()
            if label and label not in queued_goals:
                queued_goals.append(label)

        wishes = [
            {"label": label, "source": "person record"}
            for label in authored_wishes
        ] + [
            {"label": label, "source": "current need"}
            for label in current_wishes
            if label not in authored_wishes
        ]
        goals = [
            {"label": label, "source": "person record"}
            for label in authored_goals
        ] + [
            {"label": label, "source": "dream"}
            for label in authored_dreams
            if label not in authored_goals
        ] + [
            {"label": label, "source": "assigned job"}
            for label in assigned_jobs
            if label not in authored_goals
        ] + [
            {"label": label, "source": "task queue"}
            for label in queued_goals[:4]
            if label not in authored_goals and label not in assigned_jobs
        ]
        return {
            "person_name": self.get_person_name(),
            "tiers": tiers,
            "wishes": wishes,
            "goals": goals,
            "active_task": (self.active_task or {}).get("label") or "None",
        }

    def get_personality_panel_model(self):
        """Project ontology-authored Big Five fields without inventing durable facts."""
        person = self.get_person() or {}
        nested = person.get("big_five") or person.get("personality_big_five") or {}
        if not isinstance(nested, dict):
            nested = {}

        axes = []
        for definition in self.BIG_FIVE_AXES:
            axis_id = definition["id"]
            field_names = (
                f"big_five_{axis_id}",
                f"personality_{axis_id}",
                axis_id,
            )
            authored = axis_id in nested and nested.get(axis_id) not in (None, "")
            raw_value = nested.get(axis_id)
            if not authored:
                for field_name in field_names:
                    if field_name in person and person.get(field_name) not in (None, ""):
                        raw_value = person.get(field_name)
                        authored = True
                        break
            axis = dict(definition)
            axis["value"] = self._bounded_score(raw_value, default=0.5)
            axis["authored"] = authored
            axes.append(axis)

        markers = self._authored_list(
            person,
            "personality_adjectives",
            "personality_markers",
            "personality_traits",
        )
        return {
            "person_name": self.get_person_name(),
            "axes": axes,
            "all_authored": all(axis["authored"] for axis in axes),
            "adjective_markers": markers,
        }

    def _anchor_year_label(self, person):
        for key in self.TEMPORAL_KEYS:
            year = self._normalize_year_value(person.get(key))
            if year is not None:
                return f"{key} {year}"
        return "not set"

    def get_history_timeline_items(self):
        if self.world_model is None or not hasattr(self.world_model, "get_timeline_items"):
            return []

        person = self.get_person() or {}
        reference_ids = self._person_reference_ids(person)

        items = []
        for item in self.world_model.get_timeline_items():
            if item.get("timeline_kind") == "major_period":
                items.append(item)
                continue

            entity_id = item.get("entity_id")
            entity = self.world_model.get_entity(entity_id)
            if entity_id == self.person_entity_id:
                items.append(item)
            elif entity_id in reference_ids:
                items.append(item)
            elif self._entity_references_person(entity):
                items.append(item)

        return items

    def _person_reference_ids(self, person):
        references = set()
        for key in self.REFERENCE_FIELDS:
            value = person.get(key)
            if isinstance(value, str) and value:
                references.add(value)
            elif isinstance(value, (list, tuple, set)):
                references.update(item for item in value if isinstance(item, str) and item)
        return references

    def _entity_references_person(self, entity):
        if not isinstance(entity, dict) or not self.person_entity_id:
            return False

        for value in entity.values():
            if value == self.person_entity_id:
                return True
            if isinstance(value, (list, tuple, set)) and self.person_entity_id in value:
                return True
        return False

    def _normalize_year_value(self, value):
        yearer = getattr(self.world_model, "yearer", None)
        if yearer is not None and hasattr(yearer, "normalize_year"):
            normalized = yearer.normalize_year(value)
            if normalized is not None:
                return normalized

        return parse_year(value)

    def save_selection_inspector_updates(self, target_kind, target_id, updates):
        if target_kind != "person" or target_id != self.person_entity_id:
            return False

        person = self.get_person()
        if not isinstance(person, dict):
            return False

        name = str(updates.get("name", "")).strip() or str(target_id)
        notes = str(updates.get("wiki_entry", updates.get("notes", ""))).strip()
        if not self._persist_person_updates(person, {"pretty_name": name, "name": name, "wiki_entry": notes}):
            return False

        self._refresh_world_model()
        logger.info(f"[PersonSimulation] Updated dossier fields {target_id}")
        return True

    def reanchor_selection_time(self, target_kind, target_id, year):
        if target_kind != "person" or target_id != self.person_entity_id:
            return False

        person = self.get_person()
        if not isinstance(person, dict):
            return False

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        updates = self._build_time_reanchor_updates(person, year)
        if not self._persist_person_updates(person, updates):
            return False

        self._refresh_world_model()
        self.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0
        self._pending_inspector_target = {
            "kind": "person",
            "id": self.person_entity_id,
        }

        logger.info(f"[PersonSimulation] Reanchored person:{target_id} to year {year}")
        return True

    def _build_time_reanchor_updates(self, person, year):
        old_start_year = self._normalize_year_value(person.get("start_year"))
        old_end_year = self._normalize_year_value(person.get("end_year"))
        old_birth_year = self._normalize_year_value(person.get("birth_year"))
        old_death_year = self._normalize_year_value(person.get("death_year"))
        updates = {}

        if "birth_year" in person:
            old_anchor_year = old_birth_year
            updates["birth_year"] = year
            if old_birth_year is not None and old_death_year is not None:
                updates["death_year"] = old_death_year + (year - old_birth_year)
        elif "year" in person:
            old_anchor_year = self._normalize_year_value(person.get("year"))
            updates["year"] = year
        elif "year_number" in person:
            old_anchor_year = self._normalize_year_value(person.get("year_number"))
            updates["year_number"] = year
        elif "active_year" in person:
            old_anchor_year = self._normalize_year_value(person.get("active_year"))
            updates["active_year"] = year
        elif "start_year" in person:
            old_anchor_year = old_start_year
            updates["start_year"] = year
            if old_start_year is not None and old_end_year is not None:
                if old_end_year >= old_start_year and old_end_year != old_start_year:
                    updates["end_year"] = old_end_year + (year - old_start_year)
                elif old_end_year == old_start_year:
                    updates["end_year"] = year
        elif "effective_year" in person:
            old_anchor_year = self._normalize_year_value(person.get("effective_year"))
            updates["effective_year"] = year
        elif "death_year" in person:
            old_anchor_year = old_death_year
            updates["death_year"] = year
        elif "end_year" in person:
            old_anchor_year = old_end_year
            updates["end_year"] = year
        else:
            old_anchor_year = None
            updates["start_year"] = year

        if "effective_year" in person:
            old_effective_year = self._normalize_year_value(person.get("effective_year"))
            if old_effective_year is None or old_effective_year == old_anchor_year:
                updates["effective_year"] = year

        return updates

    def _refresh_world_model(self):
        if self.world_model is not None and hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

    def _persist_person_updates(self, person, updates):
        entity_id = person.get("id")
        if not entity_id:
            return False

        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is None or not hasattr(loader, "persist_entity"):
            logger.error("[PersonSimulation] No repository loader available for person persistence")
            return False

        person.update(updates)
        if not person.get("_dataset"):
            person["_dataset"] = "people"
        return loader.persist_entity(person)
