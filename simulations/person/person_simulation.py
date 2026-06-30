from engine.clock import Clock
from engine.logger import logger
from engine.simulation_manager import SimulationManager
from world.year_utils import parse_year


class PersonSimulation:
    """
    Timeline-first dossier skeleton for person entities.

    This deliberately starts as a thin runtime shell: it owns a selected person,
    exposes timeline/history hooks to UIManager, and persists inspector edits to
    the repository loader.
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

    def __init__(self, world_model=None, person_entity_id=None, year=2400):
        class _DummySystem:
            def update(self, dt):
                pass

        self.world_model = world_model
        self.person_entity_id = person_entity_id
        self.render_mode = "person"
        self.world_units_to_meters = 1.0
        self.year = int(year) if year is not None else 2400

        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 1.0
        self.max_zoom = 1.0
        self.preferred_zoom = 1.0

        self._pending_inspector_target = None

    def get_center(self):
        return 0.0, 0.0

    def update(self, dt):
        self.sim_manager.update(dt)

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

        return lines

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
