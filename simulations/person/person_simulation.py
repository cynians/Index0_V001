import re
from pathlib import Path

from engine.clock import Clock
from engine.logger import logger
from engine.simulation_manager import SimulationManager
from world.year_utils import parse_year


class PersonSimulation:
    """
    Timeline-first dossier skeleton for person entities.

    This deliberately starts as a thin runtime shell: it owns a selected person,
    exposes timeline/history hooks to UIManager, and persists inspector edits to
    the backing YAML entry.
    """

    ENTRY_PATH = Path(__file__).resolve().parents[2] / "entries" / "people.yaml"

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

    def _entry_path_for_person(self, person):
        dataset_name = person.get("_dataset") or "people"
        return Path(__file__).resolve().parents[2] / "entries" / f"{dataset_name}.yaml"

    def _persist_person_updates(self, person, updates):
        entity_id = person.get("id")
        if not entity_id:
            return False

        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if getattr(loader, "use_ontology", False) and hasattr(loader, "persist_entity"):
            person.update(updates)
            if not person.get("_dataset"):
                person["_dataset"] = "people"
            return loader.persist_entity(person)

        entry_path = self._entry_path_for_person(person)
        entry_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            text = entry_path.read_text(encoding="utf-8") if entry_path.exists() else ""
        except OSError as exc:
            logger.error(f"[PersonSimulation] Failed to read {entry_path}: {exc}")
            return False

        found = self._find_yaml_entity_block(text, entity_id)
        if found is None:
            entity = {key: value for key, value in person.items() if not str(key).startswith("_")}
            entity.update(updates)
            block = self._format_yaml_entity_block(entity)
            separator = "" if not text.strip() else "\n"
            updated_text = text.rstrip() + separator + block
        else:
            block_start, block_end = found
            block = text[block_start:block_end]
            for key, value in updates.items():
                block = self._replace_yaml_plain_field_in_block(block, key, value)
            updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")

        try:
            entry_path.write_text(updated_text, encoding="utf-8")
        except OSError as exc:
            logger.error(f"[PersonSimulation] Failed to write {entry_path}: {exc}")
            return False

        return True

    def _find_yaml_entity_block(self, text, entity_id):
        start_pattern = rf"(?m)^- id: {re.escape(str(entity_id))}\s*$"
        start_match = re.search(start_pattern, text)
        if not start_match:
            return None

        next_match = re.search(r"(?m)^- id: ", text[start_match.end():])
        block_start = start_match.start()
        block_end = start_match.end() + next_match.start() if next_match else len(text)
        return block_start, block_end

    def _replace_yaml_plain_field_in_block(self, block_text, key, value):
        lines = block_text.rstrip("\n").splitlines()
        new_field_lines = self._format_yaml_value_lines(key, value)

        target_prefix = f"  {key}:"
        index = 0
        while index < len(lines):
            if not lines[index].startswith(target_prefix):
                index += 1
                continue

            end_index = index + 1
            while end_index < len(lines):
                line = lines[end_index]
                if line.startswith("  ") and not line.startswith("    "):
                    break
                if line.startswith("- id: "):
                    break
                end_index += 1

            return "\n".join(lines[:index] + new_field_lines + lines[end_index:]) + "\n"

        insert_index = len(lines)
        for index, line in enumerate(lines):
            if line.startswith("  entry_status:"):
                insert_index = index
                break

        return "\n".join(lines[:insert_index] + new_field_lines + lines[insert_index:]) + "\n"

    def _format_yaml_scalar(self, value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)

        text = str(value)
        if text == "":
            return "''"
        if "\n" in text:
            lines = text.splitlines()
            return "|\n" + "\n".join(f"    {line}" for line in lines)

        needs_quote = (
            text.strip() != text
            or text.lower() in {"null", "none", "true", "false", "yes", "no"}
            or any(ch in text for ch in [":", "#", "{", "}", "[", "]", ","])
        )
        if needs_quote:
            return "'" + text.replace("'", "''") + "'"
        return text

    def _format_yaml_value_lines(self, key, value):
        if isinstance(value, list):
            if not value:
                return [f"  {key}: []"]
            lines = [f"  {key}:"]
            lines.extend(f"    - {self._format_yaml_scalar(item)}" for item in value)
            return lines

        if isinstance(value, dict):
            if not value:
                return [f"  {key}: {{}}"]
            lines = [f"  {key}:"]
            for child_key, child_value in value.items():
                lines.append(f"    {child_key}: {self._format_yaml_scalar(child_value)}")
            return lines

        scalar = self._format_yaml_scalar(value)
        if scalar.startswith("|\n"):
            return [f"  {key}: {scalar}"]
        return [f"  {key}: {scalar}"]

    def _format_yaml_entity_block(self, entity):
        ordered_keys = ["id", "pretty_name", "name", "type"]
        keys = [key for key in ordered_keys if key in entity]
        keys.extend(key for key in entity.keys() if key not in keys and not str(key).startswith("_"))

        lines = []
        for index, key in enumerate(keys):
            prefix = "- " if index == 0 else "  "
            value_lines = self._format_yaml_value_lines(key, entity.get(key))
            if not value_lines:
                continue
            first = value_lines[0]
            if first.startswith("  "):
                first = prefix + first[2:]
            lines.append(first)
            lines.extend(value_lines[1:])

        return "\n".join(lines).rstrip() + "\n"
