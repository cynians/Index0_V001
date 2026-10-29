"""Deck builder: unit cards and the formation decks made from them.

A unit card (dataset ``unit_cards``) is one deployable package a faction can
field, in the manner of a WARNO deck card: "GGO Sol Marine Tank Platoon" is
three tanks and the crew their vehicle design lists. A formation's deck
(``deck_cards`` on the formation, ``[{card, count}]``) is the cards it fields;
its strength is counted from the cards, never stored.

A card says what one copy takes from the world when it is fielded:

- ``card_manpower``: ``[{id, role, rank, count, is_command}]``, the people
  listed by role.
- ``card_equipment``: ``[{id, kind: vehicle|item, vehicle|item: entity id,
  count}]``. A vehicle brings its crew into the card's manpower: the vehicle
  design's ``crew_roles`` unless the entry carries its own. Transport is not
  chosen per deck; a card that rides in something lists it here.

Fielding a copy on a realization formation's deck draws those people and
that equipment from a pop and from depots (see ``fielding``); what is short
is kept on the deck row as ``short`` and the copy is fielded understrength.
The people a deck holds are shown by role as saved people, a few
representatives and a crowd (see ``formation_people``).

A card is edited as a draft and written when the editor's Save is pressed.
Deck changes are written at once, like the rest of Formation Sim's structure
edits.
"""

import copy
import re

import pygame

from simulations.formation.fielding import Fielding
from simulations.formation.formation_people import FormationPeople
from world.temporal import entity_available_at, latest_formation_snapshot


CARD_DATASET = "unit_cards"
CATEGORY_VOCAB = (
    "Command", "Infantry", "Armor", "Recon", "Support", "Artillery",
    "Air Defense", "Helicopters", "Aircraft", "Logistics", "Naval", "Space",
)
HEADER_FIELDS = ("name", "card_category")
EQUIPMENT_KINDS = ("vehicle", "item")


def category_order(category):
    try:
        return (CATEGORY_VOCAB.index(category), "")
    except ValueError:
        return (len(CATEGORY_VOCAB), str(category or "").casefold())


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


class DeckBuilder:
    """Deck state for one Formation Sim tab: the deck being built, the card
    catalog beside it, and the card editor's draft."""

    def __init__(self, sim):
        self.sim = sim
        self.target_id = None
        self.catalog_query = ""
        self.catalog_search_active = False
        self.catalog_category = None
        self.catalog_scroll = 0
        self.deck_scroll = 0
        self.content_heights = {"catalog": 0, "deck": 0, "people": 0}
        self.editor = None
        self.notice = ""
        self.fielding = Fielding(self)
        self.people = FormationPeople(self)
        self.people_selected = None
        self.people_scroll = 0

    # ------------------------------------------------------------------
    # Reading cards and decks
    # ------------------------------------------------------------------

    def _entity(self, entity_id):
        world = self.sim.world_model
        return world.get_entity(entity_id) if world is not None and entity_id else None

    def _dataset(self, name):
        get_dataset = getattr(self.sim.world_model, "get_dataset", None) if self.sim.world_model else None
        if not callable(get_dataset):
            return []
        entities = get_dataset(name) or []
        entities = entities.values() if isinstance(entities, dict) else entities
        return [entity for entity in entities if isinstance(entity, dict) and entity.get("id")]

    def target_formation_id(self):
        for candidate in (self.target_id, self.sim.formation_id):
            if candidate and self.sim._is_formation_entity_id(candidate):
                return candidate
        return None

    def set_target(self, formation_id):
        if not self.sim._is_formation_entity_id(formation_id):
            return False
        self.target_id = formation_id
        self.sim.selected_node_id = formation_id
        self.deck_scroll = 0
        self.people_scroll = 0
        self.people_selected = None
        self.notice = ""
        return True

    def formation_label(self, formation_id=None):
        formation_id = formation_id or self.target_formation_id()
        node = self.sim._find_node(formation_id)
        if node is not None:
            return node.get("label") or formation_id
        entity = self._entity(formation_id)
        if isinstance(entity, dict):
            return self.sim._display_label(entity.get("pretty_name") or entity.get("name") or formation_id)
        return self.sim.root_name

    def formation_faction_id(self, formation_id=None):
        entity = self._entity(formation_id or self.target_formation_id())
        factions = self.sim._relation_ids(entity.get("faction")) if isinstance(entity, dict) else []
        return factions[0] if factions else None

    def cards(self):
        return [
            entity for entity in self._dataset(CARD_DATASET)
            if entity.get("_dataset") == CARD_DATASET or entity.get("type") == "unit_card"
        ]

    def card(self, card_id):
        entity = self._entity(card_id)
        if isinstance(entity, dict) and (entity.get("_dataset") == CARD_DATASET or entity.get("type") == "unit_card"):
            return entity
        return None

    def card_label(self, card):
        return self.sim._display_label(card.get("pretty_name") or card.get("name") or card.get("id") or "Card")

    @staticmethod
    def card_category(card):
        return " ".join(str(card.get("card_category") or "").split()) or "Uncategorized"

    @staticmethod
    def manpower(card):
        raw = (card or {}).get("card_manpower")
        rows = []
        for index, entry in enumerate(raw if isinstance(raw, (list, tuple)) else []):
            if not isinstance(entry, dict):
                continue
            rows.append({
                "id": str(entry.get("id") or "").strip() or f"man_{index + 1}",
                "role": " ".join(str(entry.get("role") or "").split()) or "Personnel",
                "rank": " ".join(str(entry.get("rank") or "").split()),
                "count": _count(entry.get("count", 1)),
                "is_command": bool(entry.get("is_command")),
            })
        return rows

    @staticmethod
    def equipment(card):
        raw = (card or {}).get("card_equipment")
        rows = []
        for index, entry in enumerate(raw if isinstance(raw, (list, tuple)) else []):
            if not isinstance(entry, dict):
                continue
            kind = "vehicle" if str(entry.get("kind") or "").strip().lower() == "vehicle" else "item"
            reference = str(entry.get(kind) or "").strip()
            if not reference:
                continue
            row = {"id": str(entry.get("id") or "").strip() or f"eq_{index + 1}", "kind": kind,
                   kind: reference, "count": _count(entry.get("count", 1))}
            if kind == "vehicle" and entry.get("crew_roles") is not None:
                row["crew_roles"] = entry["crew_roles"]
            rows.append(row)
        return rows

    def entry_crew(self, entry):
        if entry.get("kind") != "vehicle":
            return []
        slot = {"vehicle_id": entry.get("vehicle")}
        if entry.get("crew_roles") is not None:
            slot["crew_roles"] = entry["crew_roles"]
        return self.sim.design_vehicle_crew(slot)

    def entry_crew_size(self, entry):
        return sum(_count(role.get("count", 0)) for role in self.entry_crew(entry) if isinstance(role, dict))

    def entry_profile(self, entry):
        vehicle = self.sim._vehicle_node(entry["vehicle"]) if entry.get("vehicle") else None
        return str((vehicle or {}).get("profile") or "vehicle").casefold()

    def equipment_label(self, entry):
        reference = entry.get(entry.get("kind")) or ""
        if entry.get("kind") == "vehicle":
            node = self.sim._vehicle_node(reference)
            if node is not None:
                return node["label"]
        entity = self._entity(reference)
        if isinstance(entity, dict):
            return self.sim._display_label(entity.get("pretty_name") or entity.get("name") or reference)
        return f"{reference} (missing)"

    def item_detail(self, item):
        """The item's first category, by name: "Small Arm" for an assault rifle."""
        for category_id in self.sim._relation_ids(item.get("categories")):
            category = self._entity(category_id)
            if isinstance(category, dict):
                return self.sim._display_label(category.get("pretty_name") or category.get("name") or category_id)
            return category_id.removeprefix("cat_").replace("_", " ").capitalize()
        return ""

    def card_totals(self, card):
        vehicles = items = personnel = crew = 0
        for entry in self.manpower(card):
            personnel += entry["count"]
        for entry in self.equipment(card):
            if entry["kind"] == "vehicle":
                vehicles += entry["count"]
                crew += entry["count"] * self.entry_crew_size(entry)
            else:
                items += entry["count"]
        return {"vehicles": vehicles, "items": items, "personnel": personnel, "crew": crew,
                "people": personnel + crew}

    def card_draw(self, card):
        """What fielding one copy takes: people by role (crew included) and equipment by entity."""
        people = {}
        for entry in self.manpower(card):
            people[entry["role"]] = people.get(entry["role"], 0) + entry["count"]
        equipment = {}
        for entry in self.equipment(card):
            key = (entry["kind"], entry[entry["kind"]])
            equipment[key] = equipment.get(key, 0) + entry["count"]
            for role in self.entry_crew(entry):
                if isinstance(role, dict):
                    label = str(role.get("role") or "Crew")
                    people[label] = people.get(label, 0) + entry["count"] * _count(role.get("count", 0))
        return {"people": people, "equipment": equipment}

    def deck_entries(self, formation_id=None):
        entity = self._entity(formation_id or self.target_formation_id())
        if not isinstance(entity, dict):
            return []
        state = latest_formation_snapshot(entity, self.sim.year)
        raw = state.get("deck_cards", entity.get("deck_cards")) if isinstance(state, dict) else entity.get("deck_cards")
        rows = []
        by_card = {}
        for item in raw if isinstance(raw, (list, tuple)) else []:
            short = {}
            if isinstance(item, str):
                card_id, count = item, 1
            elif isinstance(item, dict):
                card_id, count = item.get("card") or item.get("id"), item.get("count", 1)
                raw_short = item.get("short")
                if isinstance(raw_short, dict):
                    short = {str(key): _count(value) for key, value in raw_short.items()}
            else:
                continue
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 1
            card_id = str(card_id or "").strip()
            if not card_id or count <= 0:
                continue
            short = {key: value for key, value in short.items() if value > 0}
            if card_id in by_card:
                by_card[card_id]["count"] += count
                for key, value in short.items():
                    by_card[card_id]["short"][key] = by_card[card_id]["short"].get(key, 0) + value
                continue
            by_card[card_id] = {"card": card_id, "count": count, "short": short}
            rows.append(by_card[card_id])
        return rows

    def deck_count(self, card_id, formation_id=None):
        return next((row["count"] for row in self.deck_entries(formation_id) if row["card"] == card_id), 0)

    @staticmethod
    def _empty_totals():
        return {"cards": 0, "vehicles": 0, "items": 0, "people": 0, "short_people": 0, "short_equipment": 0}

    def deck_summary(self, formation_id=None):
        totals = self._empty_totals()
        rows = []
        for entry in self.deck_entries(formation_id):
            card = self.card(entry["card"])
            count = entry["count"]
            totals["cards"] += count
            if card is None:
                rows.append({"card_id": entry["card"], "card": None, "count": count, "missing": True,
                             "label": entry["card"], "category": "Missing cards", "totals": None})
                continue
            card_totals = self.card_totals(card)
            for key in ("vehicles", "items", "people"):
                totals[key] += count * card_totals[key]
            totals["short_people"] += entry["short"].get("people", 0)
            totals["short_equipment"] += sum(value for key, value in entry["short"].items() if key != "people")
            rows.append({
                "card_id": entry["card"], "card": card, "count": count, "missing": False, "short": entry["short"],
                "label": self.card_label(card), "category": self.card_category(card),
                "totals": card_totals, "available": entity_available_at(card, self.sim.year),
            })
        groups = {}
        for row in rows:
            groups.setdefault(row["category"], []).append(row)
        ordered = sorted(groups.items(), key=lambda item: category_order(item[0]))
        return {"rows": rows, "groups": ordered, "totals": totals}

    def subordinate_totals(self, formation_id=None):
        formation_id = formation_id or self.target_formation_id()
        node = self.sim._find_node(formation_id)
        totals = self._empty_totals()
        if node is None:
            return totals
        for child in node.get("children") or []:
            for descendant in self.sim._walk(child):
                entity_id = descendant.get("entity_id")
                if not entity_id:
                    continue
                for key, value in self.deck_summary(entity_id)["totals"].items():
                    totals[key] += value
        return totals

    def catalog(self, category_filter=True):
        factions = {self.formation_faction_id()} - {None}
        query = self.catalog_query.casefold().strip()
        options = []
        for card in self.cards():
            owners = set(self.sim._relation_ids(card.get("faction")))
            if owners and not owners & factions:
                continue
            if not entity_available_at(card, self.sim.year):
                continue
            category = self.card_category(card)
            if category_filter and self.catalog_category and category != self.catalog_category:
                continue
            label = self.card_label(card)
            if query and query not in label.casefold() and query not in category.casefold():
                continue
            options.append({"id": card["id"], "label": label, "category": category,
                            "totals": self.card_totals(card), "card": card})
        return sorted(options, key=lambda option: (category_order(option["category"]), option["label"].casefold()))

    def catalog_categories(self):
        categories = {option["category"] for option in self.catalog(category_filter=False)}
        return sorted(categories, key=category_order)

    # ------------------------------------------------------------------
    # Changing the deck
    # ------------------------------------------------------------------

    def _write_deck(self, formation_id, rows):
        entity = self._entity(formation_id)
        if not isinstance(entity, dict):
            return False
        before = self.sim._blueprint_view_state(entity) if entity.get("formation_kind") == "blueprint" else None
        rows = [
            {"card": row["card"], "count": int(row["count"]), **({"short": row["short"]} if row.get("short") else {})}
            for row in rows if row["count"] > 0
        ]
        changed = self.sim._save_entity_fields(formation_id, {"deck_cards": rows})
        if changed and before is not None:
            self.sim._record_blueprint_change(formation_id, before)
        return changed

    def change_card_count(self, card_id, delta, formation_id=None):
        formation_id = formation_id or self.target_formation_id()
        rows = self.deck_entries(formation_id)
        row = next((entry for entry in rows if entry["card"] == card_id), None)
        card = self.card(card_id)
        if formation_id is None or (card is None and row is None):
            return False
        if row is None:
            if delta <= 0:
                return False
            row = {"card": card_id, "count": 0, "short": {}}
            rows.append(row)
        self.notice = ""
        draws = card is not None and self.fielding.draws(formation_id)
        if delta > 0 and draws:
            report = self.fielding.field(formation_id, card, delta)
            for key, value in report["short"].items():
                row["short"][key] = row["short"].get(key, 0) + value
            self.notice = self.fielding.notice(self.card_label(card), report)
        elif delta < 0 and draws:
            row["short"] = self.fielding.stand_down(formation_id, card, row["short"], min(-delta, row["count"]))
        row["count"] = max(0, row["count"] + delta)
        return self._write_deck(formation_id, rows)

    def remove_card(self, card_id, formation_id=None):
        formation_id = formation_id or self.target_formation_id()
        rows = self.deck_entries(formation_id)
        row = next((entry for entry in rows if entry["card"] == card_id), None)
        card = self.card(card_id)
        if row is not None and card is not None and self.fielding.draws(formation_id):
            self.fielding.stand_down(formation_id, card, row["short"], row["count"])
        return self._write_deck(formation_id, [entry for entry in rows if entry["card"] != card_id])

    # ------------------------------------------------------------------
    # Card editor
    # ------------------------------------------------------------------

    def new_card(self):
        if self.target_formation_id() is None:
            self.notice = "Open a stored formation to make cards for it."
            return False
        draft = {
            "_dataset": CARD_DATASET,
            "type": "unit_card",
            "name": "",
            "pretty_name": "",
            "entry_status": "draft",
            "card_category": self.catalog_category or "Infantry",
        }
        faction_id = self.formation_faction_id()
        if faction_id:
            draft["faction"] = faction_id
        self._open_editor(draft, is_new=True)
        self.start_field("name")
        return True

    def edit_card(self, card_id):
        card = self.card(card_id)
        if card is None:
            return False
        self._open_editor(copy.deepcopy(card), is_new=False)
        return True

    def _open_editor(self, draft, is_new):
        draft["card_manpower"] = self.manpower(draft)
        draft["card_equipment"] = self.equipment(draft)
        self.editor = {"draft": draft, "is_new": is_new, "focus": None, "buffer": "",
                       "picker": None, "picker_query": "", "status": ""}
        self.catalog_search_active = False
        self.notice = ""

    def close_editor(self):
        self.editor = None

    def _entry(self, entry_id):
        if self.editor is None:
            return None
        draft = self.editor["draft"]
        return next((entry for entry in draft["card_manpower"] + draft["card_equipment"]
                     if entry["id"] == entry_id), None)

    def start_field(self, field, entry_id=None):
        if self.editor is None:
            return False
        draft = self.editor["draft"]
        if entry_id:
            entry = self._entry(entry_id)
            editable = ("role", "rank", "count") if entry is not None and "kind" not in entry else ("count",)
            if entry is None or field not in editable:
                return False
            value = entry.get(field, "")
        elif field == "name":
            value = draft.get("pretty_name") or draft.get("name") or ""
        elif field in HEADER_FIELDS:
            value = draft.get(field, "")
        else:
            return False
        self.editor["focus"] = (field, entry_id)
        self.editor["buffer"] = "" if value is None else str(value)
        self.editor["picker"] = None
        return True

    def cancel_field(self):
        if self.editor is not None:
            self.editor["focus"] = None
            self.editor["buffer"] = ""

    def commit_field(self):
        editor = self.editor
        if editor is None or editor["focus"] is None:
            return True
        field, entry_id = editor["focus"]
        value = " ".join(editor["buffer"].split())
        draft = editor["draft"]
        if entry_id:
            entry = self._entry(entry_id)
            if entry is None:
                self.cancel_field()
                return False
            if field == "count":
                count = _number(value)
                if not isinstance(count, int) or count < 1:
                    editor["status"] = "A count is a whole number of 1 or more."
                    return False
                entry["count"] = count
            elif field == "role":
                if not value:
                    editor["status"] = "Every person entry needs a role."
                    return False
                entry["role"] = value
            else:
                entry[field] = value
        elif field == "name":
            if not value:
                editor["status"] = "A card needs a name."
                return False
            draft["name"] = draft["pretty_name"] = value
        elif field == "card_category":
            if not value:
                editor["status"] = "A card needs a category."
                return False
            draft["card_category"] = value
        self.cancel_field()
        editor["status"] = ""
        return True

    def next_field(self):
        if self.editor is None or self.editor["focus"] is None:
            return False
        field, entry_id = self.editor["focus"]
        if not self.commit_field():
            return False
        if entry_id is None and field in HEADER_FIELDS:
            index = HEADER_FIELDS.index(field)
            if index + 1 < len(HEADER_FIELDS):
                return self.start_field(HEADER_FIELDS[index + 1])
        return True

    def set_category(self, category):
        if self.editor is None or not category:
            return False
        self.cancel_field()
        self.editor["draft"]["card_category"] = category
        return True

    def _next_entry_id(self, prefix):
        draft = self.editor["draft"]
        existing = {entry["id"] for entry in draft["card_manpower"] + draft["card_equipment"]}
        index = 1
        while f"{prefix}_{index}" in existing:
            index += 1
        return f"{prefix}_{index}"

    def add_personnel_entry(self):
        if self.editor is None or not self.commit_field():
            return False
        entry = {"id": self._next_entry_id("man"), "role": "Rifleman", "rank": "", "count": 1, "is_command": False}
        self.editor["draft"]["card_manpower"].append(entry)
        return self.start_field("role", entry["id"])

    def open_picker(self, kind):
        if self.editor is None or kind not in EQUIPMENT_KINDS or not self.commit_field():
            return False
        self.editor["picker"] = kind
        self.editor["picker_query"] = ""
        return True

    def vehicle_options(self):
        query = (self.editor or {}).get("picker_query", "").casefold().strip()
        options = []
        for vehicle in self.sim._vehicle_entities():
            if not isinstance(vehicle, dict) or not vehicle.get("id") or not entity_available_at(vehicle, self.sim.year):
                continue
            node = self.sim._vehicle_node(vehicle["id"])
            if node is None or (query and query not in node["label"].casefold()):
                continue
            crew = sum(_count(role.get("count", 0)) for role in node.get("crew_roles") or [])
            options.append({"id": vehicle["id"], "label": node["label"],
                            "detail": f"crew {crew}" if crew else "no crew listed", "warn": not crew})
        return sorted(options, key=lambda option: option["label"].casefold())

    def item_options(self):
        query = (self.editor or {}).get("picker_query", "").casefold().strip()
        options = []
        for item in self._dataset("items"):
            if not entity_available_at(item, self.sim.year):
                continue
            label = self.sim._display_label(item.get("pretty_name") or item.get("name") or item["id"])
            detail = self.item_detail(item)
            if query and query not in label.casefold() and query not in detail.casefold():
                continue
            options.append({"id": item["id"], "label": label, "detail": detail, "warn": False})
        return sorted(options, key=lambda option: (not option["detail"], option["detail"].casefold(),
                                                   option["label"].casefold()))

    def picker_options(self):
        kind = (self.editor or {}).get("picker")
        if kind == "vehicle":
            return self.vehicle_options()
        return self.item_options() if kind == "item" else []

    def add_equipment_entry(self, kind, entity_id):
        if self.editor is None or kind not in EQUIPMENT_KINDS:
            return False
        if kind == "vehicle" and self.sim._vehicle_node(entity_id) is None:
            return False
        if kind == "item" and not isinstance(self._entity(entity_id), dict):
            return False
        equipment = self.editor["draft"]["card_equipment"]
        existing = next((entry for entry in equipment
                         if entry["kind"] == kind and entry.get(kind) == entity_id), None)
        if existing is not None:
            existing["count"] += 1
        else:
            equipment.append({"id": self._next_entry_id("eq"), "kind": kind, kind: entity_id, "count": 1})
        self.editor["picker"] = None
        self.editor["picker_query"] = ""
        return True

    def adjust_entry(self, entry_id, delta):
        entry = self._entry(entry_id)
        if entry is None:
            return False
        self.cancel_field()
        entry["count"] = max(1, entry["count"] + delta)
        return True

    def toggle_entry_command(self, entry_id):
        entry = self._entry(entry_id)
        if entry is None or "kind" in entry:
            return False
        entry["is_command"] = not entry.get("is_command")
        return True

    def remove_entry(self, entry_id):
        if self._entry(entry_id) is None:
            return False
        self.cancel_field()
        draft = self.editor["draft"]
        for field in ("card_manpower", "card_equipment"):
            draft[field] = [entry for entry in draft[field] if entry["id"] != entry_id]
        return True

    def _new_card_id(self, label):
        slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_") or "unit"
        candidate = base = f"card_{slug}"
        index = 2
        while self._entity(candidate) is not None:
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def save_card(self):
        editor = self.editor
        if editor is None or not self.commit_field():
            return None
        draft = editor["draft"]
        label = draft.get("pretty_name") or draft.get("name")
        if not label:
            editor["status"] = "Give the card a name before saving."
            self.start_field("name")
            return None
        if not draft["card_manpower"] and not draft["card_equipment"]:
            editor["status"] = "Add people or equipment to the card."
            return None
        loader = getattr(self.sim.world_model, "loader", None) if self.sim.world_model else None
        if loader is None or not hasattr(loader, "persist_entity"):
            editor["status"] = "The repository is unavailable."
            return None
        entity = copy.deepcopy(draft)
        if editor["is_new"]:
            entity["id"] = self._new_card_id(label)
        if not loader.persist_entity(entity):
            editor["status"] = f"Could not save {entity['id']} to the repository."
            return None
        if hasattr(self.sim.world_model, "mark_repository_changed"):
            self.sim.world_model.mark_repository_changed([entity["id"]])
        self.editor = None
        if editor["is_new"]:
            self.change_card_count(entity["id"], 1)
            self.notice = f"Saved {label}. " + (self.notice or "Added it to this deck.")
        else:
            self.notice = f"Saved {label}."
        return entity["id"]

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def wants_keys(self):
        return self.editor is not None or self.catalog_search_active

    @staticmethod
    def _typed(buffer, event, limit=80):
        if event.key == pygame.K_BACKSPACE:
            return buffer[:-1]
        character = getattr(event, "unicode", "")
        if character and character.isprintable() and len(buffer) < limit:
            return buffer + character
        return buffer

    def handle_key(self, event):
        editor = self.editor
        if editor is not None:
            if editor["picker"]:
                if event.key == pygame.K_ESCAPE:
                    editor["picker"] = None
                elif event.key == pygame.K_RETURN:
                    options = self.picker_options()
                    if len(options) == 1:
                        self.add_equipment_entry(editor["picker"], options[0]["id"])
                else:
                    editor["picker_query"] = self._typed(editor["picker_query"], event)
            elif editor["focus"] is not None:
                if event.key == pygame.K_ESCAPE:
                    self.cancel_field()
                elif event.key == pygame.K_RETURN:
                    self.commit_field()
                elif event.key == pygame.K_TAB:
                    self.next_field()
                else:
                    editor["buffer"] = self._typed(editor["buffer"], event)
            elif event.key == pygame.K_ESCAPE:
                self.close_editor()
            elif event.key == pygame.K_RETURN:
                self.save_card()
            return True
        if self.catalog_search_active:
            if event.key == pygame.K_ESCAPE:
                self.catalog_query = ""
                self.catalog_search_active = False
            elif event.key == pygame.K_RETURN:
                self.catalog_search_active = False
            else:
                self.catalog_query = self._typed(self.catalog_query, event)
                self.catalog_scroll = 0
            return True
        return False

    def handle_wheel(self, screen_pos, direction, hitboxes):
        for key, area_name, attribute in (("deck:catalog:list", "catalog", "catalog_scroll"),
                                          ("deck:area", "deck", "deck_scroll"),
                                          ("deck:people:list", "people", "people_scroll")):
            area = hitboxes.get(key)
            if area is not None and area.collidepoint(screen_pos):
                maximum = max(0, self.content_heights[area_name] - area.height)
                value = getattr(self, attribute) + (60 if direction > 0 else -60)
                setattr(self, attribute, max(0, min(maximum, value)))
                return True
        return False

    def handle_click(self, key):
        """Act on the clicked deck hitbox. Returns True when the click was the deck's."""
        if not key.startswith("deck:"):
            return False
        if key != "deck:catalog:search":
            self.catalog_search_active = False
        if self.editor is not None:
            return self._handle_editor_click(key)
        if key == "deck:catalog:search":
            self.catalog_search_active = True
        elif key == "deck:catalog:new":
            self.new_card()
        elif key.startswith("deck:catalog:category:"):
            category = key[len("deck:catalog:category:"):]
            self.catalog_category = None if category == "*" else category
            self.catalog_scroll = 0
        elif key.startswith("deck:catalog:edit:"):
            self.edit_card(key[len("deck:catalog:edit:"):])
        elif key.startswith("deck:catalog:card:"):
            self.change_card_count(key[len("deck:catalog:card:"):], 1)
        elif key.startswith("deck:card:plus:"):
            self.change_card_count(key[len("deck:card:plus:"):], 1)
        elif key.startswith("deck:card:minus:"):
            self.change_card_count(key[len("deck:card:minus:"):], -1)
        elif key.startswith("deck:card:remove:"):
            self.remove_card(key[len("deck:card:remove:"):])
        elif key.startswith("deck:card:edit:"):
            self.edit_card(key[len("deck:card:edit:"):])
        elif key.startswith("deck:people:"):
            self._handle_people_click(key[len("deck:people:"):])
        return True

    def _handle_people_click(self, key):
        action, _, person_id = key.partition(":")
        if action == "pick":
            self.people_selected = None if self.people_selected == person_id else person_id
        elif action == "save":
            formation_id = self.target_formation_id()
            saved = self.people.save(formation_id, person_id)
            if saved:
                self.people_selected = saved
                self.notice = (f"Saved {self.fielding.label(saved)} as a person serving in "
                               f"{self.formation_label(formation_id)}.")
            else:
                self.notice = "Could not save that person."
        elif action in ("open", "edit") and self._entity(person_id) is not None:
            self.sim.pending_navigation_action = {
                "id": "knowledge_launch_mode", "entity_id": person_id,
                "launch_mode": "person" if action == "open" else "person_editor",
            }

    def _handle_editor_click(self, key):
        editor = self.editor
        if editor["picker"]:
            if key.startswith("deck:editor:picker:pick:"):
                return self.add_equipment_entry(editor["picker"], key[len("deck:editor:picker:pick:"):]) or True
            if key == "deck:editor:picker:close" or not key.startswith("deck:editor:picker"):
                editor["picker"] = None
            return True
        focus = editor["focus"]
        clicked_focus = (
            focus is not None
            and key == (f"deck:editor:entry:{focus[1]}:{focus[0]}" if focus[1] else f"deck:editor:field:{focus[0]}")
        )
        if focus is not None and not clicked_focus and key != "deck:editor:cancel" and not self.commit_field():
            self.cancel_field()
        if key == "deck:editor:save":
            self.save_card()
        elif key == "deck:editor:cancel":
            self.close_editor()
        elif key == "deck:editor:add_vehicle":
            self.open_picker("vehicle")
        elif key == "deck:editor:add_item":
            self.open_picker("item")
        elif key == "deck:editor:add_personnel":
            self.add_personnel_entry()
        elif key.startswith("deck:editor:field:") and not clicked_focus:
            self.start_field(key[len("deck:editor:field:"):])
        elif key.startswith("deck:editor:category:"):
            self.set_category(key[len("deck:editor:category:"):])
        elif key.startswith("deck:editor:entry:") and not clicked_focus:
            entry_id, field = key[len("deck:editor:entry:"):].rsplit(":", 1)
            self.start_field(field, entry_id)
        elif key.startswith("deck:editor:entry_plus:"):
            self.adjust_entry(key[len("deck:editor:entry_plus:"):], 1)
        elif key.startswith("deck:editor:entry_minus:"):
            self.adjust_entry(key[len("deck:editor:entry_minus:"):], -1)
        elif key.startswith("deck:editor:entry_command:"):
            self.toggle_entry_command(key[len("deck:editor:entry_command:"):])
        elif key.startswith("deck:editor:entry_remove:"):
            self.remove_entry(key[len("deck:editor:entry_remove:"):])
        return True
