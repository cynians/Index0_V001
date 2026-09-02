"""
Ontology-backed local site population simulation.

Architecture invariant: locations, pops, institutions, cultures, and durable
people are authored in the ontology.  The resolver below only constructs a
deterministic runtime presence cache from those facts; lightweight people are
promoted to fuller runtime records when encountered.
"""

import hashlib
import math

from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.person.person_simulation import PersonSimulation
from simulations.vehicle.vehicle_simulation import VehicleSimulation

# Ids of the workers who handle incoming cargo. Hardcoded to the two
# authored lumber laborers rather than a person_class filter, matching the
# pattern already used for the Elda/Tomas proprietor decision below --
# every authored worker currently shares person_class "worker".
LUMBER_UNLOAD_WORKER_IDS = ("person_lumber_laborer_nia", "person_lumber_laborer_elias")
DEFAULT_LOGISTICS_ARRIVAL_POINT = (56.0, 15.0)
DEFAULT_LOGISTICS_SCHEDULE_INTERVAL_S = 90.0
DEFAULT_LOGISTICS_CARGO_ITEM = "item_raw_lumber"
DEFAULT_LOGISTICS_CARGO_QUANTITY = 20


class RuntimeWorldOverlay:
    """Read-through world view for provisional people generated from pops."""

    def __init__(self, world_model, entities=None):
        self.base = world_model
        self.entities = dict(entities or {})
        self.loader = getattr(world_model, "loader", None)

    @property
    def repository_revision(self):
        return getattr(self.base, "repository_revision", 0)

    def get_entity(self, entity_id):
        return self.entities.get(entity_id) or self.base.get_entity(entity_id)

    def get_dataset(self, dataset_name):
        base = list(getattr(self.base, "get_dataset", lambda _name: [])(dataset_name) or [])
        base.extend(
            entity for entity in self.entities.values()
            if entity.get("_dataset") == dataset_name
        )
        return base

    def get_active_entities(self, *args, **kwargs):
        base = list(getattr(self.base, "get_active_entities", lambda *_a, **_k: [])(*args, **kwargs) or [])
        dataset_name = kwargs.get("dataset_name")
        entity_type = kwargs.get("entity_type")
        for entity in self.entities.values():
            if dataset_name and entity.get("_dataset") != dataset_name:
                continue
            if entity_type and entity.get("type") != entity_type:
                continue
            base.append(entity)
        return base


class SitePresenceResolver:
    """Project authored residents, pop representatives, and visitors."""

    DEFAULT_NAMES = (
        "Alda Rill", "Bren Tarrow", "Cera Venn", "Dain Orro", "Esme Harl",
        "Fenn Alder", "Gara Pell", "Hollis Wren", "Iven Marr", "Jora Senn",
    )

    def __init__(self, world_model, site_entity, year=2400):
        self.world_model = world_model
        self.site = site_entity or {}
        self.year = int(year or 2400)

    @staticmethod
    def _ids(value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, dict):
            value = value.get("entity") or value.get("id") or value.get("entity_id")
            return [value] if value else []
        if isinstance(value, (list, tuple, set)):
            result = []
            for item in value:
                for entity_id in SitePresenceResolver._ids(item):
                    if entity_id not in result:
                        result.append(entity_id)
            return result
        return []

    @staticmethod
    def _point(value, fallback=(0.0, 0.0)):
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            return tuple(fallback)

    def _fraction(self, key):
        digest = hashlib.sha256(f"{self.site.get('id')}|{self.year}|{key}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2 ** 64 - 1)

    def _personality(self, key):
        return {
            f"big_five_{axis}": round(0.18 + self._fraction(f"{key}:{axis}") * 0.68, 3)
            for axis in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
        }

    def _runtime_person(self, *, entity_id, name, position, source_pop=None, person_class="visitor", detail="full", **extra):
        entity = {
            "id": entity_id,
            "_dataset": "people",
            "type": "person",
            "name": name,
            "pretty_name": name,
            "person_class": person_class,
            "simulation_site": self.site.get("id"),
            "site_position": list(position),
            "source_pop": source_pop,
            **self._personality(entity_id),
        }
        entity.update({key: value for key, value in extra.items() if value is not None})
        return {
            "id": entity_id,
            "label": name,
            "position": tuple(position),
            "presence_kind": extra.get("presence_kind", "projected"),
            "simulation_detail": detail,
            "source_pop": source_pop,
            "purpose": extra.get("visit_purpose"),
            "ontology_status": extra.get("ontology_status", "runtime projection"),
            "entity": entity,
        }

    def resolve(self):
        presences = []
        for person_id in self._ids(self.site.get("resident_people")):
            person = self.world_model.get_entity(person_id) or {}
            presences.append({
                "id": person_id,
                "label": person.get("pretty_name") or person.get("name") or person_id,
                "position": self._point(person.get("site_position")),
                "presence_kind": "authored",
                "simulation_detail": "full",
                "source_pop": None,
                "purpose": "resident work and life",
                "ontology_status": "durable ontology person",
                "entity": person,
            })

        village_anchor = self._point(self.site.get("population_anchor"), (25.0, -65.0))
        for pop_id in self._ids(self.site.get("present_pops")):
            pop = self.world_model.get_entity(pop_id) or {}
            count = max(0, int(pop.get("population_count", pop.get("size", 0)) or 0))
            representative_count = max(0, min(count, int(pop.get("representative_count", 3) or 3)))
            names = list(pop.get("representative_names") or self.DEFAULT_NAMES)
            for index in range(representative_count):
                angle = (index / max(1, representative_count)) * math.tau - math.pi / 2.0
                radius = 8.0 + index * 2.5
                position = (village_anchor[0] + math.cos(angle) * radius, village_anchor[1] + math.sin(angle) * radius)
                name = names[index % len(names)]
                presences.append(self._runtime_person(
                    entity_id=f"runtime_{pop_id}_representative_{index + 1}",
                    name=name,
                    position=position,
                    source_pop=pop_id,
                    person_class="representative villager",
                    detail="full",
                    presence_kind="pop representative",
                    ontology_status="stable runtime representative",
                    associated_locations=self._ids(pop.get("home_location")),
                ))
            generic_count = max(0, count - representative_count)
            if generic_count:
                presences.append({
                    "id": f"aggregate_{pop_id}_generic",
                    "label": f"Generic Villagers ×{generic_count}",
                    "position": (village_anchor[0] + 13.0, village_anchor[1] - 12.0),
                    "presence_kind": "pop aggregate",
                    "simulation_detail": "aggregate",
                    "source_pop": pop_id,
                    "purpose": "ordinary village activity",
                    "ontology_status": "aggregate pop projection",
                    "count": generic_count,
                    "entity": None,
                })

        for person_id in self._ids(self.site.get("authored_visitors")):
            person = self.world_model.get_entity(person_id) or {}
            presences.append({
                "id": person_id,
                "label": person.get("pretty_name") or person.get("name") or person_id,
                "position": self._point(person.get("site_position"), (47.0, 2.0)),
                "presence_kind": "authored visitor",
                "simulation_detail": "full",
                "source_pop": person.get("source_pop"),
                "purpose": person.get("visit_purpose") or "visit",
                "ontology_status": "durable ontology person",
                "entity": person,
            })

        scenarios = self.site.get("visitor_scenarios") or []
        if isinstance(scenarios, dict):
            scenarios = [scenarios]
        for index, raw in enumerate(scenarios):
            if not isinstance(raw, dict):
                continue
            count = max(1, int(raw.get("count", 1) or 1))
            names = list(raw.get("names") or [raw.get("name") or self.DEFAULT_NAMES[index % len(self.DEFAULT_NAMES)]])
            anchor = self._point(raw.get("position"), (55.0, 12.0 + index * 8.0))
            for occurrence in range(count):
                name = names[occurrence % len(names)]
                detail = str(raw.get("simulation_detail") or "lightweight")
                presences.append(self._runtime_person(
                    entity_id=f"runtime_{self.site.get('id')}_{raw.get('id', 'visitor')}_{occurrence + 1}",
                    name=name,
                    position=(anchor[0], anchor[1] + occurrence * 5.0),
                    source_pop=raw.get("source_pop"),
                    person_class=raw.get("person_class") or "traveller",
                    detail=detail,
                    presence_kind=raw.get("presence_kind") or "provisional visitor",
                    ontology_status=(
                        "materialized on site entry"
                        if raw.get("materialize_on_entry")
                        else "named lightweight encounter"
                    ),
                    visit_purpose=raw.get("purpose"),
                    affiliated_institutions=self._ids(raw.get("institution")),
                ))
        return presences


class _SiteRuntimeSystem:
    def __init__(self, simulation):
        self.simulation = simulation

    def update(self, dt):
        self.simulation._update_site_runtime(dt)


class SiteSimulation(PersonSimulation):
    """Person-scale site context with scale-aware population projection."""

    _encounter_memory = {}

    def __init__(self, world_model, site_entity_id, year=2400):
        site = world_model.get_entity(site_entity_id) or {}
        resident_ids = SitePresenceResolver._ids(site.get("resident_people"))
        overlay_entities = {}
        if resident_ids:
            anchor_person_id = resident_ids[0]
        else:
            anchor_person_id = f"runtime_{site_entity_id}_observer"
            overlay_entities[anchor_person_id] = {
                "id": anchor_person_id, "_dataset": "people", "type": "person",
                "name": "Site Observer", "pretty_name": "Site Observer",
                "person_class": "site observer", "simulation_site": site_entity_id,
                "site_position": [0, 0],
            }
        self.base_world_model = world_model
        self.site_root_id = site_entity_id
        self.runtime_world = RuntimeWorldOverlay(world_model, overlay_entities)
        super().__init__(self.runtime_world, anchor_person_id, year=year)
        self.render_mode = "site_people"
        self.free_camera_pan = True
        self.min_zoom = 2.0
        self.preferred_zoom = 7.0
        self.selected_presence_id = None
        self.hover_presence_id = None
        self.presences = SitePresenceResolver(world_model, site, year=year).resolve()
        for index, presence in enumerate(self.presences):
            remembered = self._encounter_memory.get((site_entity_id, presence.get("id")))
            if remembered:
                self.presences[index] = {**presence, **remembered}
        for presence in self.presences:
            entity = presence.get("entity")
            if isinstance(entity, dict) and not world_model.get_entity(entity.get("id")):
                self.runtime_world.entities[entity["id"]] = entity
        self.agent_simulations = {}
        self._build_full_agent_simulations()
        self.site_decisions = self._build_site_decisions()
        self._assign_site_decisions()
        self.vehicle_agents = {}
        self._logistics_state = {}
        self._logistics_vehicle_serial = 0
        self._vehicle_directions = {}
        self.sim_clock = Clock(base_dt=1.0)
        self.system = _SiteRuntimeSystem(self)
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

    def _build_full_agent_simulations(self):
        runtime_people = [
            presence for presence in self.presences
            if presence.get("simulation_detail") == "full" and isinstance(presence.get("entity"), dict)
        ]
        shared_people = [
            {
                "entity_id": presence["id"],
                "label": presence["label"],
                "sex": (presence.get("entity") or {}).get("sex"),
                "position": presence["position"],
                "controlled": False,
            }
            for presence in runtime_people
        ]
        for presence in runtime_people:
            person_id = presence["id"]
            agent = self.agent_simulations.get(person_id)
            if agent is None:
                if person_id == self.person_entity_id:
                    agent = self
                else:
                    agent = PersonSimulation(self.runtime_world, person_id, year=self.year)
                    agent.min_zoom = self.min_zoom
                agent.position[:] = list(presence["position"])
                self.agent_simulations[person_id] = agent
        for agent in self.agent_simulations.values():
            agent.site_people = [dict(item) for item in shared_people]

    def _build_site_decisions(self):
        requester = next(
            (item for item in self.presences if item.get("id") == "person_neighbor_elda_woodbuyer"),
            None,
        )
        responsible = self.agent_simulations.get("person_lumber_overseer_tomas")
        if requester is None or responsible is None:
            return []
        return [{
            "id": "decision_sell_lumber_to_elda",
            "label": "Decide whether to sell lumber to Elda Marr",
            "requester_person_id": requester["id"],
            "responsible_person_id": "person_lumber_overseer_tomas",
            "status": "pending",
            "options": ["Sell requested lumber", "Refuse the sale"],
            "reason": requester.get("purpose") or "wood for house repairs",
        }]

    def _assign_site_decisions(self):
        for decision in self.site_decisions:
            agent = self.agent_simulations.get(decision["responsible_person_id"])
            if agent is None:
                continue
            agent.assign_external_task(
                "job",
                label=decision["label"],
                issuer_label="Elda Marr",
                duty_weight=0.45,
                action_tags=["commercial_decision", "visitor_request"],
            )

    def _update_site_runtime(self, dt):
        for person_id, agent in self.agent_simulations.items():
            if agent is self:
                PersonSimulation._update_runtime(self, dt)
            else:
                agent._update_runtime(dt)
            presence = next((item for item in self.presences if item.get("id") == person_id), None)
            if presence is not None:
                presence["position"] = tuple(agent.position)
        self._maybe_actuate_logistics(dt)
        self._update_vehicle_agents(dt)

    def _load_active_logistics_routes(self, field_name):
        route_ids = SitePresenceResolver._ids(self.site_entity.get(field_name))
        routes = []
        for route_id in route_ids:
            route = self.base_world_model.get_entity(route_id) or {}
            if route.get("id") and route.get("status") == "active":
                routes.append(route)
        return routes

    def _lumber_stock(self, item_id):
        """Sum of item_id already unloaded into site storage across the
        laborers who handle lumber_dropoff -- the only stock ledger that
        exists today (see PersonSimulation._advance_active_task's
        transfer_lumber step, which fills container_inventories["lumber_dropoff"]).
        v1 slice: a single running count, not the per-batch property/
        provenance holding-tank model described for the future storage
        subsystem."""
        total = 0.0
        for worker_id in LUMBER_UNLOAD_WORKER_IDS:
            agent = self.agent_simulations.get(worker_id)
            if agent is None:
                continue
            storage = agent.container_inventories.get("lumber_dropoff") or {}
            total += float(storage.get(item_id, 0.0) or 0.0)
        return total

    def _consume_lumber_stock(self, item_id, quantity):
        remaining = float(quantity)
        for worker_id in LUMBER_UNLOAD_WORKER_IDS:
            if remaining <= 0.0:
                break
            agent = self.agent_simulations.get(worker_id)
            if agent is None:
                continue
            storage = agent.container_inventories.get("lumber_dropoff") or {}
            have = float(storage.get(item_id, 0.0) or 0.0)
            take = min(have, remaining)
            if take > 0.0:
                storage[item_id] = have - take
                remaining -= take
        return float(quantity) - remaining

    def _maybe_actuate_logistics(self, dt):
        for route in self._load_active_logistics_routes("inbound_logistics_routes"):
            self._maybe_actuate_route(route, dt, direction="inbound")
        for route in self._load_active_logistics_routes("outbound_logistics_routes"):
            self._maybe_actuate_route(route, dt, direction="outbound")

    def _maybe_actuate_route(self, route, dt, direction):
        route_id = route.get("id")
        state = self._logistics_state.setdefault(route_id, {"elapsed": 0.0, "active_vehicle_id": None})
        if state.get("active_vehicle_id"):
            return
        state["elapsed"] += dt
        interval = float(route.get("schedule_interval_s") or DEFAULT_LOGISTICS_SCHEDULE_INTERVAL_S)
        if state["elapsed"] < interval:
            return
        if direction == "outbound":
            cargo_item = route.get("cargo_item") or DEFAULT_LOGISTICS_CARGO_ITEM
            if self._lumber_stock(cargo_item) <= 0.0:
                # Nothing to ship this cycle -- retry on the next interval
                # rather than spamming a stock check every tick.
                state["elapsed"] = 0.0
                return
        state["elapsed"] = 0.0
        self._spawn_logistics_vehicle(route, direction)

    def _spawn_logistics_vehicle(self, route, direction="inbound"):
        arrival_point = SitePresenceResolver._point(
            self.site_entity.get("logistics_arrival_point"), DEFAULT_LOGISTICS_ARRIVAL_POINT,
        )
        cargo_item = route.get("cargo_item") or DEFAULT_LOGISTICS_CARGO_ITEM
        try:
            requested_quantity = int(route.get("cargo_quantity_per_trip") or DEFAULT_LOGISTICS_CARGO_QUANTITY)
        except (TypeError, ValueError):
            requested_quantity = DEFAULT_LOGISTICS_CARGO_QUANTITY

        self._logistics_vehicle_serial += 1
        vehicle_id = f"runtime_vehicle_{route.get('id')}_{self._logistics_vehicle_serial}"

        if direction == "outbound":
            pickup_point = tuple(self.test_points["lumber_pickup"]["position"])
            # Stock-bounded: can't ship more than what's actually in storage.
            quantity = self._consume_lumber_stock(cargo_item, requested_quantity)
            vehicle = VehicleSimulation(
                self.base_world_model,
                vehicle_id,
                route_waypoints=[pickup_point, arrival_point],
                cargo={cargo_item: quantity},
                design_entity_id=route.get("assigned_vehicle_design"),
                label="Lumber Outbound Cart",
            )
        else:
            dropoff_point = tuple(self.test_points["lumber_dropoff"]["position"])
            vehicle = VehicleSimulation(
                self.base_world_model,
                vehicle_id,
                route_waypoints=[arrival_point, dropoff_point],
                cargo={cargo_item: requested_quantity},
                design_entity_id=route.get("assigned_vehicle_design"),
                label="Lumber Delivery Cart",
            )
        self.vehicle_agents[vehicle_id] = vehicle
        self._vehicle_directions[vehicle_id] = direction
        self._logistics_state[route.get("id")]["active_vehicle_id"] = vehicle_id
        self.presences.append(vehicle.get_presence_payload())

    def _handle_vehicle_arrival(self, vehicle):
        item_id = next(iter(vehicle.cargo), DEFAULT_LOGISTICS_CARGO_ITEM)
        quantity = float(vehicle.cargo.get(item_id, 0.0) or 0.0)
        for worker_id in LUMBER_UNLOAD_WORKER_IDS:
            agent = self.agent_simulations.get(worker_id)
            if agent is None:
                continue
            # Each agent owns an independent test_points dict (built fresh
            # per PersonSimulation instance), so the delivery quantity must
            # be written onto the specific worker's copy that will actually
            # read it when it builds the unload task.
            point = agent.test_points.get("lumber_dropoff")
            if point is None:
                continue
            point["remaining_quantity"] = quantity
            point["cargo_item_id"] = item_id
            vehicle.begin_unloading()
            vehicle.assigned_worker_id = worker_id
            duty_weight, coercion = agent.employment_pressure()
            agent.assign_external_task(
                "lumber_dropoff",
                label="Unload lumber delivery cart",
                issuer_label="Site Overseer",
                duty_weight=duty_weight,
                coercion=coercion,
                action_tags=["unload_cargo"],
            )
            return

    def _update_vehicle_agents(self, dt):
        finished_ids = []
        for vehicle_id, vehicle in self.vehicle_agents.items():
            was_arrived = vehicle.state == VehicleSimulation.STATE_ARRIVED
            vehicle._update_runtime(dt)
            if vehicle.state == VehicleSimulation.STATE_ARRIVED and not was_arrived:
                if self._vehicle_directions.get(vehicle_id) == "outbound":
                    # Outbound cargo was already loaded from site stock at
                    # spawn time; reaching the exit waypoint just means it
                    # has left -- no worker unload step, straight to leaving.
                    vehicle.cargo = {}
                    vehicle.state = VehicleSimulation.STATE_DEPARTING
                else:
                    self._handle_vehicle_arrival(vehicle)
            if vehicle.state == VehicleSimulation.STATE_UNLOADING:
                worker = self.agent_simulations.get(vehicle.assigned_worker_id)
                point = worker.test_points.get("lumber_dropoff") if worker is not None else None
                if point is not None and float(point.get("remaining_quantity", 0.0) or 0.0) <= 0.0:
                    vehicle.cargo = {}
            if vehicle.state == VehicleSimulation.STATE_DONE:
                finished_ids.append(vehicle_id)
                continue
            presence = vehicle.get_presence_payload()
            for index, existing in enumerate(self.presences):
                if existing.get("id") == vehicle_id:
                    self.presences[index] = presence
                    break
            else:
                self.presences.append(presence)

        for vehicle_id in finished_ids:
            del self.vehicle_agents[vehicle_id]
            self._vehicle_directions.pop(vehicle_id, None)
            self.presences = [item for item in self.presences if item.get("id") != vehicle_id]
            for route_state in self._logistics_state.values():
                if route_state.get("active_vehicle_id") == vehicle_id:
                    route_state["active_vehicle_id"] = None

    def get_center(self):
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) * 0.5,
            (self.bounds["min_y"] + self.bounds["max_y"]) * 0.5,
        )

    def get_initial_camera_zoom(self, screen_w, screen_h):
        width = max(1.0, self.bounds["max_x"] - self.bounds["min_x"])
        height = max(1.0, self.bounds["max_y"] - self.bounds["min_y"])
        return max(self.min_zoom, min(self.max_zoom, min(screen_w / width, screen_h / height) * 0.78))

    def get_dossier_panel_model(self):
        """Show whichever presence is selected or hovered, not just the anchor person.

        The base PersonSimulation dossier always describes self (the anchor
        resident), which is why clicking or hovering another person or a
        delivery vehicle in Site Simulation previously showed nothing new.
        """
        target_id = self.selected_presence_id or self.hover_presence_id
        if target_id is None:
            return None

        vehicle = self.vehicle_agents.get(target_id)
        if vehicle is not None:
            return self._vehicle_dossier_model(vehicle)

        agent = self.agent_simulations.get(target_id)
        if agent is not None:
            # agent_simulations[self.person_entity_id] is self -- call the
            # base implementation directly there to avoid recursing back
            # into this override.
            if agent is self:
                return PersonSimulation.get_dossier_panel_model(self)
            return agent.get_dossier_panel_model()

        presence = next((item for item in self.presences if item.get("id") == target_id), None)
        if presence is not None:
            return self._presence_dossier_model(presence)
        return None

    def _vehicle_dossier_model(self, vehicle):
        remaining = vehicle._cargo_total()
        initial = max(1, vehicle.initial_cargo_total)
        item_id = next(iter(vehicle.cargo), None) or vehicle.assigned_worker_id
        cargo_label = str(item_id or "cargo").removeprefix("item_").replace("_", " ").title()
        state_label = str(vehicle.state).replace("_", " ").title()
        status = (
            f"{remaining} of {initial} {cargo_label} remaining"
            if remaining
            else "Unloaded, departing"
        )
        return {
            "name": vehicle.label,
            "person_class": "logistics vehicle",
            "anchor": "",
            "mode": state_label,
            "affiliations": [],
            "needs": [{"id": "cargo", "label": cargo_label, "value": 100.0 * remaining / initial}],
            "active_task": status,
            "active_phase": vehicle.state,
            "active_action": status,
            "queue_count": 0,
            "status": f"State: {state_label}",
        }

    def _presence_dossier_model(self, presence):
        detail = str(presence.get("simulation_detail") or "")
        count = presence.get("count")
        name = presence.get("label") or "Unknown"
        if count:
            name = f"{name}"
        return {
            "name": name,
            "person_class": presence.get("presence_kind", "presence"),
            "anchor": presence.get("ontology_status", ""),
            "mode": detail.title(),
            "affiliations": [],
            "needs": [],
            "active_task": presence.get("purpose") or "No task info available",
            "active_phase": detail,
            "active_action": presence.get("purpose") or "",
            "queue_count": 0,
            "status": (
                "Click to materialize into a full, task-tracked person"
                if detail not in ("full", "aggregate")
                else ""
            ),
        }

    def materialize_presence(self, presence_id):
        presence = next((item for item in self.presences if item.get("id") == presence_id), None)
        if not presence or presence.get("simulation_detail") == "aggregate":
            return False
        if presence.get("simulation_detail") != "full":
            presence["simulation_detail"] = "full"
            presence["ontology_status"] = "encountered; queued for durable authoring"
            self._encounter_memory[(self.site_root_id, presence_id)] = dict(presence)
            self._build_full_agent_simulations()
        self.selected_presence_id = presence_id
        return True

    def _nearest_presence(self, world_pos, radius=2.5):
        choices = []
        for presence in self.presences:
            px, py = presence.get("position") or (0, 0)
            distance = math.hypot(float(px) - world_pos[0], float(py) - world_pos[1])
            if distance <= radius:
                choices.append((distance, presence.get("id")))
        return min(choices)[1] if choices else None

    def handle_pointer_motion(self, event, camera, screen_pos):
        world_pos = camera.screen_to_world(screen_pos)
        self.hover_presence_id = self._nearest_presence(world_pos) if world_pos else None

    def handle_pointer_event(self, event, camera, screen_pos):
        if getattr(event, "type", 1025) != 1025:
            return False
        button = getattr(event, "button", None)
        world_pos = camera.screen_to_world(screen_pos)
        presence_id = self._nearest_presence(world_pos) if world_pos else None

        if button == 3:
            if presence_id:
                return self._open_card_for_presence(presence_id)
            return False

        if button != 1:
            return False
        if presence_id:
            return self.materialize_presence(presence_id)
        self.selected_presence_id = None
        return False

    def _open_card_for_presence(self, presence_id):
        """Open an editable, authorial-view card for a site presence.

        Site Simulation is the overview/overseer vantage point, not any one
        embodied character, so right-click here opens the full card
        (mode="edit") rather than a familiarity-gated inspect view -- see
        PersonSimulation.handle_pointer_event for the embodied-person case.
        """
        presence = next((item for item in self.presences if item.get("id") == presence_id), None)
        if presence is None:
            return False

        entity = presence.get("entity")
        entity_id = entity.get("id") if isinstance(entity, dict) else None
        if entity_id and self.base_world_model.get_entity(entity_id) is not None:
            return self.open_entity_card(entity_id, mode="edit")

        source_pop = presence.get("source_pop")
        if source_pop and self.base_world_model.get_entity(source_pop) is not None:
            return self.open_entity_card(source_pop, mode="edit")

        design_entity_id = entity.get("design_entity_id") if isinstance(entity, dict) else None
        if design_entity_id and self.base_world_model.get_entity(design_entity_id) is not None:
            return self.open_entity_card(design_entity_id, mode="edit")

        return False

    def get_site_summary_lines(self):
        full = sum(1 for item in self.presences if item.get("simulation_detail") == "full")
        lightweight = sum(1 for item in self.presences if item.get("simulation_detail") == "lightweight")
        aggregate = sum(int(item.get("count", 0) or 0) for item in self.presences if item.get("simulation_detail") == "aggregate")
        pending = sum(1 for item in self.site_decisions if item.get("status") == "pending")
        return [
            f"Site Simulation: {self.site_entity.get('pretty_name') or self.site_entity.get('name') or self.site_root_id}",
            f"Full people: {full} | Named lightweight: {lightweight}",
            f"Aggregate population represented: {aggregate}",
            f"Pending proprietor decisions: {pending}",
            "Click a named lightweight person to fully generate the encounter.",
        ]

    def get_person_render_payload(self):
        payload = PersonSimulation.get_person_render_payload(self)
        payload["site_simulation"] = True
        payload["draw_controlled_person"] = False
        # The shared site overview uses the same authored geometry but does not
        # expose the controlled person's private test points or active route.
        payload["points"] = []
        payload["destination"] = None
        payload["route_points"] = []
        payload["active_point_id"] = None
        payload["hover_point_id"] = None
        payload["selected_presence_id"] = self.selected_presence_id
        payload["hover_presence_id"] = self.hover_presence_id
        payload["site_landmarks"] = list(self.site_entity.get("site_landmarks") or [])
        payload["site_people"] = [
            {
                "entity_id": item.get("id"),
                "label": item.get("label"),
                "position": item.get("position"),
                "sex": (item.get("entity") or {}).get("sex"),
                "presence_kind": item.get("presence_kind"),
                "simulation_detail": item.get("simulation_detail"),
                "purpose": item.get("purpose"),
                "ontology_status": item.get("ontology_status"),
                "count": item.get("count"),
                "controlled": False,
            }
            for item in self.presences
        ]
        return payload
