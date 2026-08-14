import math

import pygame

from engine.clock import Clock
from engine.logger import logger
from engine.simulation_manager import SimulationManager
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

    TEST_POINT_DEFINITIONS = (
        {
            "id": "bed",
            "label": "Bed",
            "position": (-12.0, -6.0),
            "color": (102, 145, 196),
            "need": "rest",
            "maslow_tier": "physiological",
            "duration": 5.0,
        },
        {
            "id": "food",
            "label": "Food",
            "position": (-12.0, 6.0),
            "color": (196, 153, 79),
            "need": "food",
            "maslow_tier": "physiological",
            "duration": 3.0,
        },
        {
            "id": "job",
            "label": "Job",
            "position": (8.0, -5.0),
            "color": (112, 170, 126),
            "need": "esteem",
            "maslow_tier": "esteem",
            "duration": 6.0,
        },
        {
            "id": "target",
            "label": "Target",
            "position": (10.0, 6.0),
            "color": (184, 104, 100),
            "need": "leisure",
            "maslow_tier": "self-actualization",
            "duration": 4.0,
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

        self.bounds = dict(self.TEST_MAP_BOUNDS)
        self.min_zoom = 12.0
        self.max_zoom = 80.0
        self.preferred_zoom = 28.0
        self.free_camera_pan = False

        self._pending_inspector_target = None

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
        self.active_task = None
        self.active_task_elapsed = 0.0
        self.direct_target = None
        self.hover_point_id = None
        self.last_status = "Autonomous queue initialized"
        self.test_points = {
            definition["id"]: dict(definition)
            for definition in self.TEST_POINT_DEFINITIONS
        }
        self._refresh_job_point_label()
        self._fill_autonomous_queue()

    def get_center(self):
        return 0.0, 0.0

    def get_initial_camera_zoom(self, screen_w, screen_h):
        map_width = self.bounds["max_x"] - self.bounds["min_x"]
        map_height = self.bounds["max_y"] - self.bounds["min_y"]
        return max(
            self.min_zoom,
            min(self.max_zoom, min(screen_w / map_width, screen_h / map_height) * 0.82),
        )

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

    def _task_for_point(self, point_id, source="autonomous", priority=0.0):
        point = self.test_points.get(point_id)
        if point is None:
            return None
        return {
            "id": f"{source}:{point_id}",
            "point_id": point_id,
            "label": point["label"],
            "target": tuple(point["position"]),
            "duration": float(point.get("duration", 0.0) or 0.0),
            "maslow_tier": point.get("maslow_tier", "assigned"),
            "source": source,
            "priority": float(priority),
            "phase": "moving",
        }

    def _autonomous_candidates(self):
        candidates = []
        food = self.needs.get("food", 0.0)
        rest = self.needs.get("rest", 0.0)
        leisure = self.needs.get("leisure", 0.0)

        if food < 72.0:
            candidates.append(("food", 145.0 - food))
        if rest < 58.0:
            candidates.append(("bed", 135.0 - rest))
        if self.work_due > 32.0:
            candidates.append(("job", 25.0 + self.work_due * 0.82))
        if leisure < 65.0:
            candidates.append(("target", 88.0 - leisure))
        return sorted(candidates, key=lambda item: (-item[1], item[0]))

    def _fill_autonomous_queue(self):
        represented = {
            task.get("point_id")
            for task in self.task_queue
            if isinstance(task, dict)
        }
        if isinstance(self.active_task, dict):
            represented.add(self.active_task.get("point_id"))

        for point_id, priority in self._autonomous_candidates():
            if point_id in represented:
                continue
            task = self._task_for_point(point_id, source="autonomous", priority=priority)
            if task is not None:
                self.task_queue.append(task)
                represented.add(point_id)
            if len(self.task_queue) >= 4:
                break

        forced = [task for task in self.task_queue if task.get("source") == "player"]
        autonomous = [task for task in self.task_queue if task.get("source") != "player"]
        autonomous.sort(key=lambda task: (-task.get("priority", 0.0), task.get("label", "")))
        self.task_queue = forced + autonomous

    def assign_player_task(self, point_id):
        task = self._task_for_point(point_id, source="player", priority=1000.0)
        if task is None:
            return False

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

    def _begin_next_queued_task(self):
        if self.active_task is not None:
            return
        self._fill_autonomous_queue()
        if self.task_queue:
            self.active_task = self.task_queue.pop(0)
            self.active_task_elapsed = 0.0
            self.last_status = f"Going to {self.active_task['label']}"

    def _advance_toward(self, target, dt):
        dx = float(target[0]) - self.position[0]
        dy = float(target[1]) - self.position[1]
        distance = math.hypot(dx, dy)
        if distance <= self.arrival_radius_m:
            self.position[0] = float(target[0])
            self.position[1] = float(target[1])
            return True

        travel = min(distance, self.move_speed_m_per_second * dt)
        if distance > 0.0:
            self.position[0] += dx / distance * travel
            self.position[1] += dy / distance * travel
        return travel >= distance - self.arrival_radius_m

    def _advance_active_task(self, dt):
        task = self.active_task
        if not isinstance(task, dict):
            return False

        if task.get("phase") == "moving":
            if not self._advance_toward(task["target"], dt):
                return False
            task["phase"] = "using"
            self.active_task_elapsed = 0.0
            self.last_status = f"Using {task['label']}"
            return False

        self.active_task_elapsed += dt
        if self.active_task_elapsed < task.get("duration", 0.0):
            return False

        self._complete_task(task)
        self.active_task = None
        self.active_task_elapsed = 0.0
        return True

    def _complete_task(self, task):
        point_id = task.get("point_id")
        if point_id == "food":
            self.needs["food"] = min(100.0, self.needs["food"] + 58.0)
        elif point_id == "bed":
            self.needs["rest"] = min(100.0, self.needs["rest"] + 62.0)
            self.needs["safety"] = min(100.0, self.needs["safety"] + 4.0)
        elif point_id == "job":
            self.work_due = max(0.0, self.work_due - 64.0)
            self.needs["esteem"] = min(100.0, self.needs["esteem"] + 12.0)
            self.completed_jobs += 1
        elif point_id == "target":
            self.needs["leisure"] = min(100.0, self.needs["leisure"] + 54.0)
            self.needs["esteem"] = min(100.0, self.needs["esteem"] + 4.0)
        self.last_status = f"Completed {task.get('label', point_id or 'task')}"

    def _update_autonomous_control(self, dt):
        self._begin_next_queued_task()
        if self._advance_active_task(dt):
            self._fill_autonomous_queue()

    def _update_direct_control(self, dt):
        if isinstance(self.active_task, dict) and self.active_task.get("source") == "direct":
            self._advance_active_task(dt)
            return
        if self.direct_target is not None and self._advance_toward(self.direct_target, dt):
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
                self.task_queue.insert(0, self.active_task)
            self.active_task = None
            self.active_task_elapsed = 0.0

        self.direct_target = None
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

        if point_id in self.test_points:
            self.active_task = self._task_for_point(point_id, source="direct", priority=1000.0)
            self.last_status = f"Direct order: use {self.active_task['label']}"
        else:
            self.direct_target = (x, y)
            self.last_status = "Direct movement order"
        return True

    def cancel_direct_order(self):
        if self.control_mode != self.CONTROL_DIRECT:
            return False
        self.direct_target = None
        if isinstance(self.active_task, dict) and self.active_task.get("source") == "direct":
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
            "position": tuple(self.position),
            "points": self.get_test_points(),
            "control_mode": self.control_mode,
            "destination": destination,
            "hover_point_id": self.hover_point_id,
            "active_point_id": (self.active_task or {}).get("point_id"),
            "active_phase": (self.active_task or {}).get("phase"),
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
        if event.button == 3:
            self.cancel_direct_order()
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
        for employment_id in self._relation_ids(person.get("employment_assignments")):
            employment = self.get_person(employment_id) or {}
            job_ids = self._relation_ids(employment.get("job"))
            if not job_ids:
                continue
            job = self.get_person(job_ids[0]) or {}
            label = job.get("pretty_name") or job.get("name") or job_ids[0]
            break
        self.test_points["job"]["label"] = label

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

    def open_person_inspector(self):
        if self.get_person() is None:
            return False

        self._pending_inspector_target = {
            "kind": "person",
            "id": self.person_entity_id,
        }
        return True

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
            f"Active: {active.get('label', 'none')} ({active.get('phase', 'idle')})",
            f"Queue: {' > '.join(queue_labels) if queue_labels else 'empty'}",
            self.last_status,
        ])

        return lines

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

    def _assigned_job_labels(self, person):
        labels = []
        for employment_id in self._relation_ids(person.get("employment_assignments")):
            employment = self.get_person(employment_id) or {}
            for job_id in self._relation_ids(employment.get("job")):
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
