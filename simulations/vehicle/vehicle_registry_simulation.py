"""
Vehicle Registry: a full-viewport screen listing individually constructed
units (dataset ``vehicle_units``, see
docs/entity_field_overview_vehicle_unit_v001.md and _v002.md) of one vehicle
*design* entity. A design represents the type/blueprint; a unit is one
specific, serial-numbered constructed instance of it -- this is the registry
of those instances, grouped by version (outer) and production batch (inner).

Self-contained like WorldGenSim: draws and hit-tests its own buttons/cells
(tracked as rects on this object, set by VehicleRegistryRenderer each frame)
rather than routing through ui/ui_manager.py's UIButton list, since this is a
dedicated full-viewport screen like the Vehicle Designer already is.

v2: ``produced_by``/``assigned_faction`` (and ``production_line_id`` once a
producer is resolved) are edited through a small self-contained search
picker (see ``open_picker``/``_picker_matches``/``_commit_picker_selection``)
rather than plain text. Typing a name that doesn't match any candidate and
committing it stores that raw string in the field anyway -- an "unfinished
link" -- rather than requiring a resolved entity id; the renderer flags
values that don't resolve to a real entity so they can be replaced later.

A unit can also start out even lighter than that: ``unit_placeholders`` is a
list of ``{"name": ...}`` entries stored directly on the vehicle *design*
entity (not a ``vehicle_units`` row at all) -- "we know a unit like this
exists, we just haven't catalogued it yet." ``promote_placeholder`` turns one
into a real ``vehicle_units`` entity with one call.
"""

import pygame

from engine.clock import Clock
from engine.simulation_manager import SimulationManager


ROMAN_MARK_ORDER = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}


class VehicleRegistrySimulation:
    TEXT_FIELDS = (
        "serial_number", "produced_by", "production_line_id", "batch_label",
        "version_label", "year_constructed", "year_destroyed", "fate_notes",
        "assigned_faction", "current_link_entity_id",
    )

    RELATION_FIELDS = {
        "produced_by": "producers",
        "assigned_faction": "factions",
    }

    def __init__(self, world_model=None, vehicle_entity_id=None):
        self.render_mode = "vehicle_registry"
        self.show_time_ui = False
        self.world_model = world_model
        self.vehicle_entity_id = vehicle_entity_id

        self.sim_clock = Clock(base_dt=1.0)

        class _DummySystem:
            def update(self, dt):
                pass

        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.active_cell = None  # (unit_id, field_name)
        self._active_cell_buffer = ""
        self.selected_unit_id = None
        self._picker = None  # {unit_id, field_name, query, candidates, selected_index}

        self._cell_hitboxes = []  # (unit_id, field_name, rect)
        self._picker_row_hitboxes = []  # (index, rect) -- index == len(matches) is the "use raw text" row
        self._placeholder_hitboxes = []  # (index, rect) -- "Create Unit" buttons
        self._add_placeholder_button_rect = None
        self._back_button_rect = None

    @property
    def year(self):
        return 2400

    def update(self, dt):
        self.sim_manager.update(dt)

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def _loader(self):
        return getattr(self.world_model, "loader", None) if self.world_model is not None else None

    def _all_entities(self, dataset_name):
        loader = self._loader()
        datasets = getattr(loader, "datasets", None) if loader is not None else None
        if isinstance(datasets, dict):
            return [row for row in datasets.get(dataset_name, []) if isinstance(row, dict)]
        return []

    def get_vehicle_entity(self):
        if self.world_model is None or not self.vehicle_entity_id:
            return None
        return self.world_model.get_entity(self.vehicle_entity_id)

    def get_vehicle_name(self):
        entity = self.get_vehicle_entity()
        return entity.get("name", self.vehicle_entity_id) if isinstance(entity, dict) else self.vehicle_entity_id

    def get_units(self):
        return [
            row for row in self._all_entities("vehicle_units")
            if row.get("represents_design") == self.vehicle_entity_id
        ]

    def _unit_by_id(self, unit_id):
        return next((u for u in self.get_units() if u.get("id") == unit_id), None)

    def _entity_label(self, entity_id, dataset_name=None):
        entity_id = str(entity_id or "").strip()
        if not entity_id or self.world_model is None:
            return None
        entity = self.world_model.get_entity(entity_id)
        if not isinstance(entity, dict):
            return None
        if dataset_name and entity.get("_dataset") not in (dataset_name, None):
            return None
        return entity.get("name") or entity.get("pretty_name") or entity_id

    def _producer_name(self, producer_id):
        return self._entity_label(producer_id) or (str(producer_id).strip() or None)

    # ------------------------------------------------------------------
    # Grouping: version (outer) -> production batch (inner)
    # ------------------------------------------------------------------

    def _version_sort_key(self, version_label, insertion_index):
        if not version_label:
            return (3, 0, insertion_index)
        normalized = str(version_label).strip().lower()
        if normalized == "prototype":
            return (0, 0, insertion_index)
        if normalized.startswith("mk"):
            roman = normalized[2:].strip()
            if roman in ROMAN_MARK_ORDER:
                return (1, ROMAN_MARK_ORDER[roman], insertion_index)
        return (2, 0, insertion_index)

    def _group_by_batch(self, units):
        units = sorted(units, key=lambda unit: str(unit.get("serial_number") or unit.get("id") or ""))
        groups = {}
        order = []
        for unit in units:
            line_id = str(unit.get("production_line_id") or "").strip()
            key = line_id or None
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(unit)

        result = []
        for key in order:
            group_units = groups[key]
            label = next((unit.get("batch_label") for unit in group_units if unit.get("batch_label")), None)
            if not label:
                if key is None:
                    label = "Ungrouped"
                else:
                    producer_name = next(
                        (self._producer_name(unit.get("produced_by")) for unit in group_units if unit.get("produced_by")),
                        None,
                    )
                    label = f"{producer_name} — Line {key}" if producer_name else f"Batch: {key}"
            result.append({"key": key, "label": label, "units": group_units})
        return result

    def get_grouped_units(self):
        """
        Two-level grouping: version_label (outer, e.g. "Prototype"/"Mk I"/
        "Mk II", sorted by a small natural-order heuristic) -> production
        batch (inner, unchanged logic from v1).
        """
        units = self.get_units()
        version_groups = {}
        version_order = []
        for insertion_index, unit in enumerate(units):
            version_label = str(unit.get("version_label") or "").strip() or None
            if version_label not in version_groups:
                version_groups[version_label] = {"units": [], "insertion_index": insertion_index}
                version_order.append(version_label)
            version_groups[version_label]["units"].append(unit)

        version_order.sort(key=lambda label: self._version_sort_key(label, version_groups[label]["insertion_index"]))

        result = []
        for version_label in version_order:
            result.append({
                "version_label": version_label or "Unspecified",
                "batches": self._group_by_batch(version_groups[version_label]["units"]),
            })
        return result

    def get_placeholders(self):
        vehicle = self.get_vehicle_entity()
        if not isinstance(vehicle, dict):
            return []
        return [entry for entry in (vehicle.get("unit_placeholders") or []) if isinstance(entry, dict)]

    def get_registry_payload(self):
        return {
            "vehicle_id": self.vehicle_entity_id,
            "vehicle_name": self.get_vehicle_name(),
            "version_groups": self.get_grouped_units(),
            "placeholders": self.get_placeholders(),
            "active_cell": self.active_cell,
            "active_cell_buffer": self._active_cell_buffer,
            "selected_unit_id": self.selected_unit_id,
            "picker": self._picker_payload(),
        }

    # ------------------------------------------------------------------
    # Mutations: full unit records
    # ------------------------------------------------------------------

    def _next_serial_suggestion(self):
        existing = {str(unit.get("serial_number") or "") for unit in self.get_units()}
        index = 1
        while f"Sn-{index}" in existing:
            index += 1
        return f"Sn-{index}"

    def _create_unit_entity(self, serial=None):
        if self.world_model is None or not self.vehicle_entity_id:
            return None
        loader = self._loader()
        if loader is None or not hasattr(loader, "persist_entity"):
            return None

        existing_ids = {row.get("id") for row in self._all_entities("vehicle_units")}
        index = 1
        while f"unit_{self.vehicle_entity_id}_{index:03d}" in existing_ids:
            index += 1
        unit_id = f"unit_{self.vehicle_entity_id}_{index:03d}"
        serial = str(serial or "").strip() or self._next_serial_suggestion()
        entity = {
            "id": unit_id,
            "type": "vehicle_unit",
            "_dataset": "vehicle_units",
            "pretty_name": serial,
            "represents_design": self.vehicle_entity_id,
            "serial_number": serial,
        }
        if not loader.persist_entity(entity):
            return None
        self.selected_unit_id = unit_id
        self.active_cell = (unit_id, "serial_number")
        self._active_cell_buffer = serial
        return unit_id

    def _commit_active_cell(self):
        if self.active_cell is None or self.world_model is None:
            return
        unit_id, field_name = self.active_cell
        value = self._active_cell_buffer
        if field_name in ("year_constructed", "year_destroyed"):
            stripped = value.strip()
            coerced = None
            if stripped:
                try:
                    coerced = float(stripped)
                except ValueError:
                    coerced = None
            self.world_model.set_literal(unit_id, field_name, coerced)
        else:
            self.world_model.set_literal(unit_id, field_name, value)

    def set_active_cell(self, unit_id, field_name):
        if field_name not in self.TEXT_FIELDS:
            return False
        self.close_picker()
        if self.active_cell is not None:
            self._commit_active_cell()
        unit = self._unit_by_id(unit_id)
        if unit is None:
            return False
        current = unit.get(field_name)
        self.active_cell = (unit_id, field_name)
        self._active_cell_buffer = "" if current is None else str(current)
        self.selected_unit_id = unit_id
        return True

    def clear_active_cell(self, commit=True):
        if commit:
            self._commit_active_cell()
        self.active_cell = None
        self._active_cell_buffer = ""

    # ------------------------------------------------------------------
    # Mutations: relation picker (produced_by / assigned_faction /
    # production_line_id once a producer is resolved)
    # ------------------------------------------------------------------

    def _relation_candidates(self, dataset_name):
        candidates = []
        for entity in self._all_entities(dataset_name):
            entity_id = entity.get("id")
            if not entity_id:
                continue
            label = entity.get("name") or entity.get("pretty_name") or entity_id
            candidates.append({"id": entity_id, "label": str(label)})
        candidates.sort(key=lambda item: item["label"].lower())
        return candidates

    def _producer_lines_for(self, producer_id):
        producer_id = str(producer_id or "").strip()
        if not producer_id or self.world_model is None:
            return []
        producer = self.world_model.get_entity(producer_id)
        if not isinstance(producer, dict):
            return []
        out = []
        for raw_line in producer.get("production_lines") or []:
            if not isinstance(raw_line, dict):
                continue
            line_id = str(raw_line.get("line_id") or raw_line.get("id") or "").strip()
            if not line_id:
                continue
            label = raw_line.get("batch_label") or raw_line.get("label")
            if not label:
                product_id = str(raw_line.get("product_id") or "").strip()
                product = self.world_model.get_entity(product_id) if product_id else None
                product_name = product.get("name") if isinstance(product, dict) else None
                label = f"{product_name} — {line_id}" if product_name else line_id
            out.append({"id": line_id, "label": str(label)})
        return out

    def open_picker(self, unit_id, field_name):
        if field_name in self.RELATION_FIELDS:
            candidates = self._relation_candidates(self.RELATION_FIELDS[field_name])
        elif field_name == "production_line_id":
            unit = self._unit_by_id(unit_id)
            producer_id = unit.get("produced_by") if unit else None
            candidates = self._producer_lines_for(producer_id)
            if not candidates:
                return False
        else:
            return False

        if self.active_cell is not None:
            self._commit_active_cell()
        self.active_cell = None
        self._active_cell_buffer = ""

        current_value = str((self._unit_by_id(unit_id) or {}).get(field_name) or "").strip()
        matched_index = next((i for i, c in enumerate(candidates) if c["id"] == current_value), None)
        self._picker = {
            "unit_id": unit_id,
            "field_name": field_name,
            # If the current value already resolves to a candidate, start
            # browsing fresh with it pre-selected; otherwise it's an
            # unresolved/typed name, so surface it in the query box for
            # editing rather than losing it silently.
            "query": "" if matched_index is not None else current_value,
            "candidates": candidates,
            "selected_index": matched_index or 0,
        }
        self.selected_unit_id = unit_id
        return True

    def _picker_matches(self):
        if self._picker is None:
            return []
        query = self._picker["query"].strip().lower()
        candidates = self._picker["candidates"]
        if not query:
            return list(candidates)
        return [c for c in candidates if query in c["label"].lower() or query in c["id"].lower()]

    def _picker_payload(self):
        if self._picker is None:
            return None
        matches = self._picker_matches()
        return {
            "unit_id": self._picker["unit_id"],
            "field_name": self._picker["field_name"],
            "query": self._picker["query"],
            "matches": matches,
            "selected_index": self._picker["selected_index"],
        }

    def close_picker(self):
        self._picker = None

    def _commit_picker_selection(self, index=None):
        if self._picker is None:
            return False
        matches = self._picker_matches()
        if index is None:
            index = self._picker["selected_index"]
        unit_id = self._picker["unit_id"]
        field_name = self._picker["field_name"]
        if 0 <= index < len(matches):
            value = matches[index]["id"]
        else:
            value = self._picker["query"].strip()
            if not value:
                self._picker = None
                return False
        if self.world_model is not None:
            self.world_model.set_literal(unit_id, field_name, value)
        self._picker = None
        return True

    def _handle_picker_key(self, event):
        if event.key == pygame.K_ESCAPE:
            self._picker = None
            return True
        matches = self._picker_matches()
        if event.key == pygame.K_UP:
            self._picker["selected_index"] = max(0, self._picker["selected_index"] - 1)
            return True
        if event.key == pygame.K_DOWN:
            self._picker["selected_index"] = min(len(matches), self._picker["selected_index"] + 1)
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_picker_selection()
            return True
        if event.key == pygame.K_BACKSPACE:
            self._picker["query"] = self._picker["query"][:-1]
            self._picker["selected_index"] = 0
            return True
        if event.unicode and event.unicode.isprintable():
            self._picker["query"] += event.unicode
            self._picker["selected_index"] = 0
            return True
        return True

    # ------------------------------------------------------------------
    # Mutations: unit placeholders ("unfinished links") + promotion
    # ------------------------------------------------------------------

    def add_placeholder(self, name=None):
        if self.world_model is None or not self.vehicle_entity_id:
            return None
        name = str(name or "").strip() or self._next_serial_suggestion()
        updated = self.get_placeholders() + [{"name": name}]
        self.world_model.set_literal(self.vehicle_entity_id, "unit_placeholders", updated)
        return name

    def promote_placeholder(self, index):
        placeholders = self.get_placeholders()
        if not (0 <= index < len(placeholders)):
            return None
        name = placeholders[index].get("name") or ""
        remaining = placeholders[:index] + placeholders[index + 1:]
        if self.world_model is not None:
            self.world_model.set_literal(self.vehicle_entity_id, "unit_placeholders", remaining)
        return self._create_unit_entity(serial=name)

    def handle_specification_key(self, event):
        """
        Same click-to-edit-text-cell keydown idiom as
        VehicleDesignSimulation.handle_specification_key -- app/input_router.py
        checks this hook by name ahead of the generic keydown path.
        """
        if event.type != pygame.KEYDOWN:
            return False

        if self._picker is not None:
            return self._handle_picker_key(event)

        if self.active_cell is None:
            return False

        if event.key == pygame.K_ESCAPE:
            self.active_cell = None
            self._active_cell_buffer = ""
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.clear_active_cell(commit=True)
            return True
        if event.key == pygame.K_BACKSPACE:
            self._active_cell_buffer = self._active_cell_buffer[:-1]
            return True
        if event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
            self._active_cell_buffer = ""
            return True
        if event.unicode and event.unicode.isprintable():
            self._active_cell_buffer += event.unicode
            return True
        return True

    # ------------------------------------------------------------------
    # Hitbox bookkeeping (set by the renderer each frame)
    # ------------------------------------------------------------------

    def set_cell_hitboxes(self, hitboxes):
        self._cell_hitboxes = list(hitboxes or [])

    def set_picker_row_hitboxes(self, hitboxes):
        self._picker_row_hitboxes = list(hitboxes or [])

    def set_placeholder_hitboxes(self, hitboxes):
        self._placeholder_hitboxes = list(hitboxes or [])

    def set_registry_button_rects(self, add_placeholder_rect=None, back_rect=None):
        self._add_placeholder_button_rect = add_placeholder_rect
        self._back_button_rect = back_rect

    def handle_pointer_event(self, event, camera, screen_pos):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False

        if self._picker is not None:
            for index, rect in self._picker_row_hitboxes:
                if rect.collidepoint(screen_pos):
                    self._commit_picker_selection(index)
                    return True
            self._picker = None
            return True

        if self._add_placeholder_button_rect is not None and self._add_placeholder_button_rect.collidepoint(screen_pos):
            self.add_placeholder()
            return True

        if self._back_button_rect is not None and self._back_button_rect.collidepoint(screen_pos):
            self.clear_active_cell(commit=True)
            return True

        for index, rect in self._placeholder_hitboxes:
            if rect.collidepoint(screen_pos):
                self.promote_placeholder(index)
                return True

        for unit_id, field_name, rect in self._cell_hitboxes:
            if rect.collidepoint(screen_pos):
                if field_name in self.RELATION_FIELDS and self.open_picker(unit_id, field_name):
                    return True
                if field_name == "production_line_id":
                    unit = self._unit_by_id(unit_id)
                    producer_id = unit.get("produced_by") if unit else None
                    if producer_id and self.open_picker(unit_id, field_name):
                        return True
                self.set_active_cell(unit_id, field_name)
                return True

        if self.active_cell is not None:
            self.clear_active_cell(commit=True)
        return False
