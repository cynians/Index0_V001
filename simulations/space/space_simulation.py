from dataclasses import replace
import math

from simulations.collection.collections import Context as CollectionContext, view as collection_view
from simulations.logistics.capabilities import is_eligible
from simulations.logistics.journey import Journey
from simulations.logistics.links import INTERPLANETARY, ORBITAL, link_from_transfer_window
from simulations.logistics.vehicle_profiles import (
    design_propulsion_state,
    space_profile_from_design,
    spacecraft_design_profiles,
)
from simulations.space.orbit import G, KeplerOrbit
from simulations.space.trajectory import Body as TreeBody, BodyTree, Node
from simulations.space.transfer import TransferBody, find_direct_windows
from world.interplanetary_calendar import (
    CYCLE_SECONDS,
    CYCLES_PER_YEAR,
    date_from_seconds,
    duration_cycles,
    year_start_seconds,
)

# Natural bodies the transfer panel lists; stations and spacecraft are not
# planetary transfer targets.
TRANSFER_TARGET_CLASSES = {"planet", "dwarf_planet", "moon", "asteroid", "comet"}

# The craft the transfer panel checks come from a collection
# (docs/collection_simulation_concept_v001.md); while the logistics simulation
# is being built that is the debug set of test craft.
DEFAULT_TRANSFER_COLLECTION_ID = "coll_debug_test_spacecraft"

# About the longest row the panel shows uncut at its width.
TRANSFER_PANEL_LINE_CHARS = 56


# A new manoeuvre node goes this far ahead of now, so it can be shaped before it comes.
NEW_NODE_LEAD_CYCLES = 10


def _panel_entry(text, action=None, style="text", selected=False):
    """One line of a space panel: plain text, a selectable row, or a button (with its click payload)."""
    return {"text": text, "action": action, "style": style, "selected": selected}


def _panel_buttons(buttons, label=None):
    """A line of side-by-side buttons, [(caption, click payload)], with an optional label before them."""
    captions = " | ".join(caption for caption, _action in buttons)
    return {"text": f"{label} {captions}" if label else captions, "action": None, "style": "buttons",
            "selected": False, "buttons": list(buttons), "label": label}


class SpaceSimulation:
    """
    Pure simulation logic (no window, no pygame, no UI).

    This version loads the orbital system from world entries instead of
    hardcoding Sun / Earth / Moon directly in the simulation.
    """

    def __init__(self, world_model=None, root_system_id="system_sol", year=2400, root_body_id=None):
        from engine.clock import Clock
        from simulations.space.system import CelestialSystem
        from engine.simulation_manager import SimulationManager
        from world.world_model import WorldModel

        self.render_mode = "space"

        self.year = year
        # Interplanetary calendar: the view opens at the start of `year`.
        self.start_seconds = year_start_seconds(year)
        self.root_system_id = root_system_id
        self.root_body_id = root_body_id

        self.world_model = world_model if world_model is not None else WorldModel()

        self.sim_clock = Clock(base_dt=4.8)
        self.system = CelestialSystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1e-17
        self.max_zoom = 1e-6
        self.preferred_zoom = 1.0e-10
        if self.root_body_id is not None:
            self.min_zoom = 1e-10
            self.max_zoom = 2e-5
            self.preferred_zoom = 2.0e-9

        self.selected_space_object = None
        self.selected_system_entity_id = None
        self.hover_space_object = None
        self.hover_system_entity_id = None
        self.hover_screen_pos = None
        self.body_label_hitboxes = []

        # Transfer windows cached per (origin, target, count) and spacecraft
        # design profiles until the repository changes: the panel is read every frame.
        self._transfer_windows = {}
        self._spacecraft_designs = None
        self.transfer_collection_id = DEFAULT_TRANSFER_COLLECTION_ID
        # The window picked in the panel, as (origin id, target id), and the
        # journey under way: a plan kept for this session, not stored.
        self.selected_transfer = None
        self.journey = None
        self.follow_craft = False
        self.selected_node = None
        self._tree = None

        self.system.populate_from_world_model(
            world_model=self.world_model,
            year=self.year,
            root_system_id=self.root_system_id,
            root_body_id=self.root_body_id,
            time_seconds=self.seconds_since_epoch(),
        )
        self._loaded_repository_revision = getattr(self.world_model, "repository_revision", 0)

    def seconds_since_epoch(self):
        return self.start_seconds + self.sim_clock.time

    def get_calendar_date(self):
        return date_from_seconds(self.seconds_since_epoch())

    def get_time_info(self):
        """
        Header time in the interplanetary calendar, in place of the shared
        365-day one.
        """
        date = self.get_calendar_date()
        return {
            "lines": [
                date.long_label(),
                f"{date.short_label()} | Tick {self.sim_clock.tick}",
                f"Time Scale x{self.sim_clock.time_scale:.2f}",
            ],
            # The bar runs through the month, ruled in cycles passed like the short form.
            "timeline_fraction": date.month_fraction,
            "timeline_labels": ["0", "25", "50", "75", "100"],
            "year_fraction": date.year_fraction,
        }

    def get_center(self):
        return 0.0, 0.0

    def get_scope_label(self):
        if self.root_body_id is None:
            root = self.world_model.get_entity(self.root_system_id)
            return root.get("name", self.root_system_id) if root else self.root_system_id

        body = self.world_model.get_entity(self.root_body_id)
        return body.get("name", self.root_body_id) if body else self.root_body_id

    def get_scope_breadcrumb(self):
        if self.root_body_id is None:
            return "Full star system"
        return "Local planetary space"

    def update(self, dt):
        repository_revision = getattr(self.world_model, "repository_revision", 0)
        if repository_revision != self._loaded_repository_revision:
            self.system.populate_from_world_model(
                world_model=self.world_model,
                year=self.year,
                root_system_id=self.root_system_id,
                root_body_id=self.root_body_id,
                time_seconds=self.seconds_since_epoch(),
            )
            self._loaded_repository_revision = repository_revision
            self._transfer_windows = {}
            self._spacecraft_designs = None
            self._tree = None
            self.selected_space_object = None
            self.selected_system_entity_id = None
            self.hover_space_object = None
            self.hover_system_entity_id = None
        self.sim_manager.update(dt)

    def get_entity(self, space_object, world_model=None):
        """
        Resolve world entity from a space object.

        If no world_model is provided, use the simulation's own world model.
        """
        if space_object.entity_id is None:
            return None

        model = world_model if world_model is not None else self.world_model
        entity = model.get_entity(space_object.entity_id)
        space_object.entity = entity
        return entity

    def get_selected_body_entity(self):
        """
        Return the source orbital entity for the currently selected body.
        """
        if self.selected_space_object is None:
            return None
        return self.system.get_source_entity_for_space_object(self.selected_space_object)

    def get_selection_inspector_payload(self):
        entity = self.get_selected_body_entity()
        if not entity:
            return None

        entity_id = entity.get("id")
        body_class = (
            entity.get("body_class")
            or entity.get("location_class")
            or entity.get("type", "body")
        )
        details = [
            f"Class: {body_class}",
            f"Repository ID: {entity_id}",
        ]
        start_year = entity.get("start_year")
        end_year = entity.get("end_year")
        if start_year not in (None, "") or end_year not in (None, ""):
            active_start = start_year if start_year not in (None, "") else "?"
            active_end = end_year if end_year not in (None, "") else "present"
            details.append(f"Active: {active_start} to {active_end}")

        return {
            "entity_id": entity_id,
            "title": entity.get("pretty_name") or entity.get("name") or entity_id,
            "kind": "Space body",
            "details": details,
            "actions": [
                {"id": "open_selection_wiki", "label": "Open Wiki Entry"},
            ] if entity_id else [],
        }

    # --------------------------------------------------
    # Transfer windows (docs/space_transfer_windows_v001.md)
    # --------------------------------------------------

    def _source_entity_id(self, space_object):
        source = self.system.get_source_entity_for_space_object(space_object)
        return source.get("id") if isinstance(source, dict) else None

    def _transfer_targets(self, origin_object):
        """Natural bodies on sibling orbits: same parent, not the origin itself."""
        parent = origin_object.orbit.parent
        targets = []
        for entry in self.system.get_entries():
            candidate = entry["object"]
            orbit = getattr(candidate, "orbit", None)
            if candidate is origin_object or not isinstance(orbit, KeplerOrbit) or orbit.parent is not parent:
                continue
            source = self.system.get_source_entity_for_space_object(candidate) or {}
            if str(source.get("location_class") or "").strip().lower() not in TRANSFER_TARGET_CLASSES:
                continue
            targets.append(candidate)
        return targets

    def get_transfer_windows(self, origin_object, target_object, count=1):
        """
        The next direct windows from origin to target, cached per pair until
        the view's date passes the first departure.
        """
        key = (self._source_entity_id(origin_object), self._source_entity_id(target_object), count)
        now = self.seconds_since_epoch()
        windows = self._transfer_windows.get(key)
        if windows is None or (windows and windows[0].leg.depart_t < now):
            windows = find_direct_windows(
                TransferBody.from_space_object(origin_object, self.system.get_source_entity_for_space_object(origin_object)),
                TransferBody.from_space_object(target_object, self.system.get_source_entity_for_space_object(target_object)),
                now,
                count=count,
            )
            self._transfer_windows[key] = windows
        return windows

    def _transfer_windows_are_current(self, origin_object, target_object):
        key = (self._source_entity_id(origin_object), self._source_entity_id(target_object), 1)
        windows = self._transfer_windows.get(key)
        return windows is not None and not (windows and windows[0].leg.depart_t < self.seconds_since_epoch())

    def _spacecraft_design_profiles(self):
        """(where the craft come from, [(design id, name, space profile)]) for the transfer panel."""
        if self._spacecraft_designs is None:
            self._spacecraft_designs = self._load_transfer_craft()
        return self._spacecraft_designs

    def _load_transfer_craft(self):
        if not hasattr(self.world_model, "get_entities_by_dataset"):
            return "no craft", []
        collection = self.world_model.get_entity(self.transfer_collection_id) if self.transfer_collection_id else None
        if not isinstance(collection, dict):
            return "all spacecraft designs", spacecraft_design_profiles(self.world_model)
        context = CollectionContext(year=self.get_calendar_date().year)
        designs = [
            (item.entity["id"], item.entity.get("pretty_name") or item.entity.get("name") or item.entity["id"],
             space_profile_from_design(item.entity, self.world_model))
            for item in collection_view(collection, self.world_model, context)
            if item.entity.get("type") == "vehicle"
        ]
        return collection.get("pretty_name") or collection.get("name") or self.transfer_collection_id, designs

    def _transfer_domain(self, origin_object):
        """Interplanetary when the origin orbits a star, orbital when it orbits a planet."""
        parent_source = self.system.get_source_entity_for_space_object(origin_object.orbit.parent) or {}
        is_star = (
            str(parent_source.get("location_class") or "").strip().lower() == "star"
            or parent_source.get("system_role") == "star"
        )
        return INTERPLANETARY if is_star else ORBITAL

    @staticmethod
    def _wrapped_list(lead, names, width=TRANSFER_PANEL_LINE_CHARS):
        """A comma list over as many panel lines as it needs, continued with an indent."""
        lines = []
        current = lead
        for index, name in enumerate(names):
            piece = name + ("," if index < len(names) - 1 else "")
            if current.strip() and current != lead and len(current) + 1 + len(piece) > width:
                lines.append(current)
                current = "  " + piece
            else:
                current = current + ("" if current == lead else " ") + piece
        lines.append(current)
        return lines

    def get_transfer_panel_lines(self, solve_budget=1):
        """The transfer panel as plain text, one string per line."""
        return [entry["text"] for entry in self.get_transfer_panel_entries(solve_budget)]

    @staticmethod
    def _duration_label(seconds):
        cycles = duration_cycles(seconds)
        return f"{cycles:.0f} cycles" if cycles < CYCLES_PER_YEAR else f"{cycles / CYCLES_PER_YEAR:.1f} years"

    def get_transfer_panel_entries(self, solve_budget=1):
        """
        The slim transfer-window panel: the next window from the selected body
        to each body on a sibling orbit, soonest first, with how many of the
        checked craft meet each window's requirements
        (docs/logistics_simulation_concept_v001.md). A window row selects that
        window; the selected window lists the craft that can fly it, each a
        button that starts a journey.

        Read every frame; at most `solve_budget` targets are solved per call
        (about 25 ms each), so the list fills in over a few frames instead of
        stalling the view.
        """
        origin_object = getattr(self, "selected_space_object", None)
        if not isinstance(getattr(origin_object, "orbit", None), KeplerOrbit):
            return []
        targets = self._transfer_targets(origin_object)
        if not targets:
            return []

        rows = []
        pending = 0
        for target_object in targets:
            if not self._transfer_windows_are_current(origin_object, target_object):
                if solve_budget <= 0:
                    pending += 1
                    continue
                solve_budget -= 1
            windows = self.get_transfer_windows(origin_object, target_object)
            if windows:
                rows.append((windows[0], target_object))

        origin_id = self._source_entity_id(origin_object)
        domain = self._transfer_domain(origin_object)
        craft_source, designs = self._spacecraft_design_profiles()
        shielding = "Deep-space" if domain == INTERPLANETARY else "Orbital"
        entries = [
            _panel_entry(f"Transfer windows from {origin_object.name}"),
            _panel_entry(f"{shielding} shielding; life support for the flight"),
        ]
        destinations_by_design = {}
        chosen = None
        for window, target_object in sorted(rows, key=lambda row: row[0].leg.depart_t):
            target_id = self._source_entity_id(target_object)
            requirements = link_from_transfer_window(window, domain).requirements
            eligible = [(design_id, name) for design_id, name, profile in designs if is_eligible(profile, requirements)]
            for _design_id, name in eligible:
                destinations_by_design.setdefault(name, []).append(target_object.name)
            selected = getattr(self, "selected_transfer", None) == (origin_id, target_id)
            if selected:
                chosen = (window, target_object, target_id, eligible)
            craft = f"{len(eligible)} craft" if eligible else "no craft"
            entries.append(_panel_entry(
                f"{date_from_seconds(window.leg.depart_t).short_label()}  {target_object.name}  "
                f"{window.total_dv / 1000.0:.2f} km/s, {self._duration_label(window.leg.tof)} | {craft}",
                {"action": "select_window", "target_id": target_id}, "row", selected,
            ))
        if pending:
            entries.append(_panel_entry(f"Calculating {pending} more..."))
        entries.append(_panel_entry(f"Checked: {craft_source}, {len(designs)} craft"))
        for name, destinations in destinations_by_design.items():
            entries.extend(_panel_entry(line) for line in self._wrapped_list(f"{name}: ", destinations))
        without_figures = sum(1 for _design_id, _name, profile in designs if "delta_v_m_s" not in profile)
        if without_figures:
            entries.append(_panel_entry(
                "1 spacecraft design lacks figures" if without_figures == 1
                else f"{without_figures} spacecraft designs lack figures"
            ))
        if chosen is not None:
            window, target_object, target_id, eligible = chosen
            entries.append(_panel_entry(
                f"Fly to {target_object.name}, departs {date_from_seconds(window.leg.depart_t).short_label()}:"
            ))
            for design_id, name in eligible:
                entries.append(_panel_entry(
                    f"Start journey with {name}",
                    {"action": "start_journey", "target_id": target_id, "design_id": design_id}, "button",
                ))
            if not eligible:
                entries.append(_panel_entry("No checked craft meets this window"))
        return entries

    # --------------------------------------------------
    # Journeys (docs/logistics_simulation_concept_v001.md section 3.5)
    # --------------------------------------------------

    def handle_panel_action(self, payload):
        """A click on the transfer or journey panel; taken even on the panel's background."""
        payload = payload or {}
        action = payload.get("action")
        if action == "select_window":
            origin = getattr(self, "selected_space_object", None)
            key = (self._source_entity_id(origin) if origin is not None else None, payload.get("target_id"))
            self.selected_transfer = None if self.selected_transfer == key else key
        elif action == "start_journey":
            self.start_journey(payload.get("design_id"), payload.get("target_id"))
        elif action == "jump_to_departure":
            self.jump_to_departure()
        elif action == "warp_faster":
            self.sim_clock.set_time_scale(self.sim_clock.time_scale * 10.0)
        elif action == "warp_slower":
            self.sim_clock.set_time_scale(max(1.0, self.sim_clock.time_scale / 10.0))
        elif action == "follow_craft":
            self.follow_craft = not self.follow_craft
        elif action == "end_journey":
            self.journey = None
            self.follow_craft = False
            self.selected_node = None
        elif self.journey is not None and action in {"select_node", "adjust_node", "add_node", "delete_node"}:
            self._edit_nodes(action, payload)
        return True

    def _edit_nodes(self, action, payload):
        """Select, nudge, add or delete a manoeuvre node; nodes already passed stay as flown."""
        journey = self.journey
        now = self.seconds_since_epoch()
        nodes = list(journey.nodes)
        index = payload.get("index")
        if action == "select_node":
            self.selected_node = None if self.selected_node == index else index
            return
        if action == "add_node":
            added = Node(max(now, journey.start_t) + NEW_NODE_LEAD_CYCLES * CYCLE_SECONDS)
            nodes.append(added)
        elif index is None or not 0 <= index < len(nodes) or nodes[index].t < now:
            return
        elif action == "delete_node":
            del nodes[index]
            added = None
        else:
            field_name, delta = payload.get("field"), float(payload.get("delta") or 0.0)
            value = getattr(nodes[index], field_name) + delta
            if field_name == "t":
                value = max(value, now + 60.0)
            added = replace(nodes[index], **{field_name: value})
            nodes[index] = added
        self.journey = journey.with_nodes(nodes)
        self.selected_node = self.journey.nodes.index(added) if added is not None else None

    def _transfer_body(self, space_object):
        return TransferBody.from_space_object(space_object, self.system.get_source_entity_for_space_object(space_object))

    def _body_tree(self):
        """Every body the craft can orbit, as a tree of spheres of influence; rebuilt when the repository changes."""
        if self._tree is None:
            bodies = []
            for entry in self.system.get_entries():
                space_object = entry["object"]
                body_id = self._source_entity_id(space_object)
                if not body_id:
                    continue
                orbit = space_object.orbit
                source = self.system.get_source_entity_for_space_object(space_object) or {}
                if orbit is None:
                    try:
                        radius = float(source.get("radius_m") or 0.0)
                    except (TypeError, ValueError):
                        radius = 0.0
                    bodies.append(TreeBody(body_id, space_object.name, None, G * float(space_object.mass or 0.0),
                                           radius, math.inf))
                elif isinstance(orbit, KeplerOrbit):
                    elements = replace(self._transfer_body(space_object), id=body_id)
                    bodies.append(TreeBody(body_id, space_object.name, self._source_entity_id(orbit.parent),
                                           elements.mu, elements.radius, elements.soi_radius, elements))
            self._tree = BodyTree(bodies)
        return self._tree

    def start_journey(self, design_id, target_id):
        """Plan a journey for a craft design along the next window from the selected body to the target."""
        origin = getattr(self, "selected_space_object", None)
        target = self.system.objects_by_id.get(target_id) if target_id else None
        design = self.world_model.get_entity(design_id) if design_id else None
        if not isinstance(getattr(origin, "orbit", None), KeplerOrbit) or target is None or not isinstance(design, dict):
            return False
        windows = self.get_transfer_windows(origin, target)
        propulsion = design_propulsion_state(design, self.world_model)
        if not windows or propulsion is None:
            return False
        tree = self._body_tree()
        origin_id = self._source_entity_id(origin)
        try:
            self.journey = Journey.plan(
                craft_id=design_id, craft_name=design.get("pretty_name") or design.get("name") or design_id,
                origin=tree[origin_id].elements, target=tree[target_id].elements,
                window=windows[0], propulsion=propulsion, tree=tree,
            )
        except (KeyError, ValueError):
            return False
        self.selected_transfer = None
        self.selected_node = None
        return True

    def jump_to_departure(self):
        """Move the clock to half a cycle before the first burn still to come."""
        if self.journey is None:
            return False
        now = self.seconds_since_epoch()
        upcoming = [node.t for node in self.journey.nodes if node.t >= now]
        if not upcoming:
            return False
        delta = upcoming[0] - 0.5 * CYCLE_SECONDS - now
        if delta <= 0.0:
            return False
        self.sim_clock.time += delta
        self.system.update(delta)
        return True

    @staticmethod
    def _distance_label(metres):
        return f"{metres / 1e9:.2f} million km" if metres >= 1e9 else f"{metres / 1000.0:,.0f} km"

    def get_journey_panel_entries(self):
        journey = self.journey
        if journey is None:
            return []
        now = self.seconds_since_epoch()
        target = journey.target_name
        entries = [
            _panel_entry(f"Journey: {journey.craft_name}"),
            _panel_entry(f"{journey.origin_name} to {target}: planned capture "
                         f"{date_from_seconds(journey.capture_t).short_label()}"),
        ]
        upcoming = [node for node in journey.nodes if node.t >= now]
        situation = journey.situation(now)
        if upcoming:
            situation += f": next burn in {self._duration_label(upcoming[0].t - now)}"
        entries.append(_panel_entry(situation))
        kind, figure = journey.outcome()
        entries.append(_panel_entry({
            "orbit": lambda: f"{target}: captured, periapsis {self._distance_label(figure)} up",
            "flyby": lambda: f"{target}: flyby, periapsis {self._distance_label(figure)} up",
            "impact": lambda: f"{target}: impact",
            "miss": lambda: f"{target}: missed by {self._distance_label(figure)}",
        }[kind]()))
        available = journey.propulsion.delta_v_m_s()
        over = " - over budget" if journey.planned_dv > available + 1e-6 else ""
        entries.append(_panel_entry(f"Delta-v {journey.planned_dv / 1000.0:.2f} of {available / 1000.0:.2f} km/s{over}"))
        entries.append(_panel_entry(
            f"Propellant {journey.propulsion.propellant_kg / 1000.0:.1f} t to "
            f"{max(0.0, journey.propulsion_after().propellant_kg) / 1000.0:.1f} t"
        ))
        for index, node in enumerate(journey.nodes):
            entries.append(_panel_entry(
                f"Node {index + 1} {date_from_seconds(node.t).short_label()}: prograde {node.prograde:+,.0f}, "
                f"radial {node.radial:+,.0f} m/s" + (" (done)" if node.t < now else ""),
                {"action": "select_node", "index": index}, "row", self.selected_node == index,
            ))
        selected = self.selected_node
        if selected is not None and selected < len(journey.nodes) and journey.nodes[selected].t >= now:
            # A transfer is touchy: a few m/s at the escape burn move the arrival by
            # hundreds of thousands of km, so prograde has a fine row too.
            def nudge(label, field_name, deltas, scale=1.0):
                return _panel_buttons([
                    (f"{delta:+g}", {"action": "adjust_node", "index": selected, "field": field_name, "delta": delta * scale})
                    for delta in deltas
                ], label)
            entries.append(nudge("Prograde m/s", "prograde", (-100, -10, 10, 100)))
            entries.append(nudge("fine", "prograde", (-1, -0.1, 0.1, 1)))
            entries.append(nudge("Radial m/s", "radial", (-100, -10, -1, 1, 10, 100)))
            entries.append(nudge("Time cycles", "t", (-1, -0.1, 0.1, 1), CYCLE_SECONDS))
            entries.append(_panel_buttons([("Delete node", {"action": "delete_node", "index": selected})]))
        entries.append(_panel_buttons([
            ("Add node", {"action": "add_node"}),
            ("Stop following" if self.follow_craft else "Follow craft", {"action": "follow_craft"}),
            ("End journey", {"action": "end_journey"}),
        ]))
        warp = [
            (f"Warp x10 (x{self.sim_clock.time_scale:,.0f})", {"action": "warp_faster"}),
            ("Warp /10", {"action": "warp_slower"}),
        ]
        if upcoming:
            warp.append(("Jump to burn", {"action": "jump_to_departure"}))
        entries.append(_panel_buttons(warp))
        return entries

    def _frame_world_position(self, frame_id):
        space_object = self.system.objects_by_id.get(frame_id)
        return space_object.get_position() if space_object is not None else (0.0, 0.0)

    def get_journey_draw_data(self):
        """
        The predicted path, the craft and its nodes, in world coordinates, for
        the renderer. Each piece is drawn round its body where that body is
        now, as a map of a patched-conic flight shows it.
        """
        journey = self.journey
        if journey is None:
            return None
        segments = []
        for frame_id, kind, points in journey.segments():
            fx, fy = self._frame_world_position(frame_id)
            segments.append((kind, [(fx + x, fy + y) for x, y in points]))

        def on_path(t, segment):
            fx, fy = self._frame_world_position(segment.frame_id)
            x, y = segment.conic.state_at(t)[0]
            return fx + x, fy + y

        prediction = journey.prediction
        nodes = []
        for index, node in enumerate(journey.nodes):
            ending = next((segment for segment in prediction.segments
                           if segment.ends == "node" and abs(segment.t_end - node.t) < 1e-3), None)
            if ending is not None:
                nodes.append({"position": on_path(node.t, ending), "label": str(index + 1),
                              "selected": index == self.selected_node})
        now = self.seconds_since_epoch()
        return {
            "segments": segments,
            "position": on_path(now, prediction.segment_at(now)),
            "label": journey.craft_name,
            "nodes": nodes,
        }

    def get_camera_focus(self):
        """The craft, while following it; None leaves the camera to the player."""
        if not self.follow_craft:
            return None
        drawn = self.get_journey_draw_data()
        return drawn["position"] if drawn else None

    def clear_body_label_hitboxes(self):
        self.body_label_hitboxes = []

    def register_body_label_hitbox(self, source_entity_id, rect):
        if not source_entity_id or rect is None:
            return
        for entry in self.system.get_entries():
            obj = entry["object"]
            source = self.system.get_source_entity_for_space_object(obj)
            if isinstance(source, dict) and source.get("id") == source_entity_id:
                self.body_label_hitboxes.append(
                    {
                        "entity_id": source_entity_id,
                        "object": obj,
                        "rect": rect.copy(),
                    }
                )
                return

    def _pick_labelled_space_object(self, screen_pos):
        for hitbox in reversed(self.body_label_hitboxes):
            rect = hitbox.get("rect")
            if rect is not None and rect.collidepoint(screen_pos):
                return hitbox.get("object")
        return None

    def _pick_space_object(self, camera, screen_pos):
        """
        Pick the nearest visible body under the cursor using a screen-space radius.
        """
        labelled_obj = self._pick_labelled_space_object(screen_pos)
        if labelled_obj is not None:
            return labelled_obj

        sx, sy = screen_pos
        best_obj = None
        best_dist_sq = None

        for entry in self.system.get_entries():
            obj = entry["object"]
            bx, by = obj.get_position()

            center = camera.world_to_screen((bx, by))
            if center is None:
                continue

            layer_stack = entry["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            max_pixel_radius = 0
            for layer in layers:
                pixel_size = max(1, int(layer["size"] * camera.zoom))
                max_pixel_radius = max(max_pixel_radius, pixel_size // 2)

            pick_radius = max(8, max_pixel_radius + 6)

            dx = sx - center[0]
            dy = sy - center[1]
            dist_sq = dx * dx + dy * dy

            if dist_sq > pick_radius * pick_radius:
                continue

            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_obj = obj
                best_dist_sq = dist_sq

        return best_obj

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Update hover state from pointer motion.
        """
        picked_obj = self._pick_space_object(camera, screen_pos)

        self.hover_space_object = picked_obj
        self.hover_screen_pos = screen_pos

        if picked_obj is None:
            self.hover_system_entity_id = None
            return

        source_entity = self.system.get_source_entity_for_space_object(picked_obj)
        self.hover_system_entity_id = source_entity.get("id") if source_entity else None

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Handle pointer input for the space simulation.
        """
        import pygame

        # Selection happens on press. A release also arrives when the press
        # went to a selection-card button, and picking empty space then
        # would drop the selection the button just acted on.
        if getattr(event, "type", None) == pygame.MOUSEBUTTONUP:
            return

        picked_obj = self._pick_space_object(camera, screen_pos)

        self.hover_space_object = picked_obj
        self.hover_screen_pos = screen_pos

        if picked_obj is None:
            self.selected_space_object = None
            self.selected_system_entity_id = None
            self.hover_system_entity_id = None
            return

        self.selected_space_object = picked_obj

        source_entity = self.system.get_source_entity_for_space_object(picked_obj)
        self.selected_system_entity_id = source_entity.get("id") if source_entity else None
        self.hover_system_entity_id = self.selected_system_entity_id
