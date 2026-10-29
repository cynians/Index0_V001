"""Person Editor: make a person, or change one, in steps saved together.

A person is made in the order a life starts: who they are (name, sex),
their birth (place and year), their parents (optional, up to two people;
the genome is drawn from theirs), their genetics (the DNA string: skin tone
and body loci; clothing is an item worn over it), their personality (the Big
Five from birth, moved by words; world/personality.py), their life (home,
job, workplace, shared knowledge), then a review. Every step edits one
working copy of the person entity, the draft. Nothing reaches the ontology
until Save; PersonSimulation.save_person_editor writes what save_plan
returns. See docs/person_simulation_concept_v001.md, Cycle 9.
"""

from __future__ import annotations

import copy
import re
import secrets

from simulations.person.person_assets import assess_person_readiness
from simulations.person.person_genetics import (
    BODY_TRAITS,
    SKIN_TONES,
    create_person_dna,
    decode_person_dna,
    inherit_person_dna,
    set_body_trait,
    set_skin_tone,
)
from simulations.person.person_knowledge import KNOWLEDGE_FIELD, PERSONAL_KNOWLEDGE, SHARED_KNOWLEDGE
from world.personality import (
    AXES,
    SEED_FIELD,
    WORDS_FIELD,
    authored_baseline,
    birth_seed,
    label as trait_label,
    personality,
    position,
    trait_index,
)
from world.place_tree import place_tree
from world.tag_rows import lookup_key


STEPS = (
    {"id": "person", "label": "Person"},
    {"id": "birth", "label": "Birth"},
    {"id": "parents", "label": "Parents"},
    {"id": "genetics", "label": "Genetics"},
    {"id": "personality", "label": "Personality"},
    {"id": "life", "label": "Life"},
    {"id": "review", "label": "Review"},
)
STEP_IDS = tuple(step["id"] for step in STEPS)
SEXES = ({"id": "female", "label": "Female"}, {"id": "male", "label": "Male"}, {"id": None, "label": "Not set"})
LIFE_TABS = (
    {"id": "residence", "label": "Home", "kind": "place"},
    {"id": "is_employed_as", "label": "Job", "kind": "job"},
    {"id": "is_employed_at", "label": "Workplace", "kind": "place"},
    {"id": "knowledge", "label": "Shared knowledge", "kind": "knowledge"},
)
PLACE_FIELDS = ("birth_location", "residence", "is_employed_at")
TEST_CLOTHING_IDS = ("item_test_toga", "item_test_suit")
BASELINE_FIELDS = {axis: f"big_five_{axis}" for axis in AXES}
EDITED_FIELDS = (
    "pretty_name", "name", "sex", "start_year", "birth_location", "parents", SEED_FIELD,
    "genetic_dna", "equipped_clothing", WORDS_FIELD, *BASELINE_FIELDS.values(),
    "residence", "is_employed_as", "is_employed_at", KNOWLEDGE_FIELD,
)
TEXT_INPUTS = ("name", "year", "place_search", "people_search", "word_search")
PERSON_DATASETS = ("people", "person")
MAX_PARENTS = 2
# A parent younger than this at the birth is flagged, like one born after it.
YOUNGEST_PARENT_AGE = 12
# A new person is born this many years before the simulation's year.
ADULT_AGE = 30
NAME_MAX = 48


def _new_seed():
    return secrets.token_hex(6)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").casefold()).strip("_")


def person_id_from_name(name, taken=()):
    """person_<name>, numbered when that id is taken."""
    base = f"person_{_slug(name) or 'unnamed'}"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}_{number}", number + 1
    return candidate


def _clothing_id(person):
    equipped = (person or {}).get("equipped_clothing") or []
    if isinstance(equipped, str):
        equipped = [equipped]
    # Keep other clothing items too, though the picker offers two garments.
    return next((item_id for item_id in equipped if isinstance(item_id, str) and item_id), None)


def _shared_includes(person, world_model):
    collection = _entity(world_model, (person or {}).get(KNOWLEDGE_FIELD))
    return [
        item for item in (collection or {}).get("includes") or []
        if _collection_class(_entity(world_model, item)) == SHARED_KNOWLEDGE
    ]


def _entity(world_model, entity_id):
    getter = getattr(world_model, "get_entity", None)
    return getter(entity_id) if callable(getter) and isinstance(entity_id, str) and entity_id else None


def _collection_class(entity):
    return str((entity or {}).get("collection_class") or "")


def _base_state(draft, original, world_model):
    shared = _shared_includes(original, world_model)
    return {
        "draft": draft,
        "original": original,
        "is_new": original is None,
        "step": STEP_IDS[0],
        "focus": None,
        "inputs": {"name": str(draft.get("pretty_name") or draft.get("name") or ""),
                   "year": "" if draft.get("start_year") is None else str(draft.get("start_year")),
                   "place_search": "", "people_search": "", "word_search": ""},
        "browse": {},
        "life_tab": LIFE_TABS[0]["id"],
        "word_axis": None,
        "scroll": {},
        "shared_knowledge": list(shared),
        "original_shared_knowledge": list(shared),
        "dirty": original is None,
        "status": "",
    }


def new_person_editor_state(person, world_model=None):
    """Edit a stored person: the draft starts as a copy of them."""
    original = copy.deepcopy(person) if isinstance(person, dict) else {}
    draft = copy.deepcopy(original)
    authored = str(draft.get("genetic_dna") or "").strip()
    has_dna = bool(authored and decode_person_dna(authored)["valid"])
    if not has_dna:
        draft["genetic_dna"] = create_person_dna(birth_seed(draft), "medium")
    state = _base_state(draft, original, world_model)
    state["dirty"] = not has_dna
    state["status"] = "Loaded the person." if has_dna else "Made a preview DNA from their birth seed; save to keep it."
    return state


def new_person_state(world_model=None, year=2400, birth_location=None, seed=None):
    """A person not yet made: born ADULT_AGE years before the year, nothing stored until Save."""
    seed = str(seed or _new_seed())
    draft = {
        "id": person_id_from_name("", _taken_ids(world_model)),
        "_dataset": "people",
        "type": "person",
        SEED_FIELD: seed,
        "start_year": int(year) - ADULT_AGE,
        "genetic_dna": create_person_dna(seed, "medium"),
    }
    if birth_location:
        draft["birth_location"] = birth_location
    state = _base_state(draft, None, world_model)
    state["status"] = "A new person. Name them, then go through the steps; Save writes them."
    return state


def _taken_ids(world_model):
    loader = getattr(world_model, "loader", None)
    entities = getattr(loader, "entities", None)
    if isinstance(entities, dict):
        return set(entities)
    getter = getattr(world_model, "get_dataset", None)
    return {entity.get("id") for entity in (getter("people") if callable(getter) else None) or [] if isinstance(entity, dict)}


def _refresh_dirty(state):
    if state["is_new"]:
        state["dirty"] = True
        return
    original, draft = state["original"] or {}, state["draft"]
    state["dirty"] = (
        any(original.get(field) != draft.get(field) for field in EDITED_FIELDS)
        or state["shared_knowledge"] != state["original_shared_knowledge"]
    )


def changed_fields(state):
    original, draft = state["original"] or {}, state["draft"]
    return [field for field in EDITED_FIELDS if original.get(field) != draft.get(field)]


def _set(state, field, value):
    if value is None or value == [] or value == "":
        state["draft"].pop(field, None)
    else:
        state["draft"][field] = value
    _refresh_dirty(state)


# --- steps and typing ---

def set_step(state, step_id):
    if step_id not in STEP_IDS:
        return False
    state["step"] = step_id
    state["focus"] = None
    return True


def move_step(state, offset):
    index = STEP_IDS.index(state["step"]) + int(offset)
    return set_step(state, STEP_IDS[max(0, min(len(STEP_IDS) - 1, index))])


def focus_input(state, input_id):
    state["focus"] = input_id if input_id in TEXT_INPUTS else None
    return True


def type_text(state, text, world_model=None):
    """Add typed characters to the focused input."""
    focus = state.get("focus")
    if focus not in TEXT_INPUTS:
        return False
    text = "".join(char for char in str(text or "") if char.isprintable())
    if focus == "year":
        text = "".join(char for char in text if char.isdigit() or char == "-")
    if not text:
        return False
    current = state["inputs"][focus]
    if focus == "name":
        current = (current + text)[:NAME_MAX]
    else:
        current += text
    _write_input(state, focus, current, world_model)
    return True


def erase_text(state, world_model=None):
    focus = state.get("focus")
    if focus not in TEXT_INPUTS:
        return False
    _write_input(state, focus, state["inputs"][focus][:-1], world_model)
    return True


def _write_input(state, focus, value, world_model):
    state["inputs"][focus] = value
    if focus == "name":
        set_name(state, value, world_model)
    elif focus == "year":
        try:
            set_birth_year(state, int(value))
        except ValueError:
            pass
    elif focus == "place_search":
        state["scroll"].update({field: 0 for field in PLACE_FIELDS})
    elif focus == "word_search":
        state["scroll"]["words"] = 0
    elif focus == "people_search":
        state["scroll"]["parents"] = 0


def set_name(state, name, world_model=None):
    name = str(name or "").strip()[:NAME_MAX]
    _set(state, "pretty_name", name)
    _set(state, "name", name)
    if state["is_new"]:
        taken = _taken_ids(world_model)
        state["draft"]["id"] = person_id_from_name(name, taken)
    state["inputs"]["name"] = state["inputs"].get("name", "") if state.get("focus") == "name" else name
    return True


def set_sex(state, sex_id):
    if sex_id not in {sex["id"] for sex in SEXES}:
        return False
    _set(state, "sex", sex_id)
    return True


# --- birth ---

def set_birth_year(state, year):
    _set(state, "start_year", int(year))
    if state.get("focus") != "year":
        state["inputs"]["year"] = str(int(year))
    return True


def adjust_birth_year(state, delta, default_year=2400):
    year = state["draft"].get("start_year")
    year = int(default_year) - ADULT_AGE if year is None else int(year)
    state["focus"] = None
    return set_birth_year(state, year + int(delta))


def choose_place(state, field, place_id, world_model=None):
    """Choose a place for a place field, and open it if it holds places."""
    if field not in PLACE_FIELDS:
        return False
    tree = place_tree(world_model)
    if place_id is not None and place_id not in tree.places:
        return False
    _set(state, field, place_id)
    if place_id is not None and tree.has_children(place_id):
        state["browse"][field] = place_id
        state["scroll"][field] = 0
    state["inputs"]["place_search"] = ""
    state["focus"] = None
    return True


def browse_place(state, field, place_id, world_model=None):
    """Open a place in a place field's browser without choosing it; None opens the outermost places."""
    if field not in PLACE_FIELDS:
        return False
    tree = place_tree(world_model)
    state["browse"][field] = place_id if place_id in tree.places else None
    state["scroll"][field] = 0
    state["inputs"]["place_search"] = ""
    return True


def browsed_place(state, field, world_model=None):
    """The place a field's browser shows: where it was left, else around the chosen place, else birth."""
    if field in state["browse"]:
        return state["browse"][field]
    tree = place_tree(world_model)
    for candidate in (state["draft"].get(field), state["draft"].get("birth_location")):
        if candidate in tree.places:
            return candidate if tree.has_children(candidate) else tree.parent(candidate)
    return None


def place_rows(state, field, world_model=None):
    """The places the browser lists: search results, else what the browsed place holds."""
    tree = place_tree(world_model)
    query = state["inputs"].get("place_search", "")
    ids = tree.search(query) if query.strip() else tree.children(browsed_place(state, field, world_model))
    year = state["draft"].get("start_year")
    return [
        {
            "id": place_id,
            "label": tree.label(place_id),
            "class": tree.place_class(place_id).replace("_", " "),
            "within": " > ".join(tree.label(item) for item in tree.chain(place_id)[:-1][-3:]) if query.strip() else "",
            "opens": tree.has_children(place_id),
            "existed": tree.existed(place_id, year) if field == "birth_location" else None,
            "chosen": state["draft"].get(field) == place_id,
        }
        for place_id in ids
    ]


# --- parents ---

def _year(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_person(entity):
    return isinstance(entity, dict) and (entity.get("type") == "person" or entity.get("_dataset") in PERSON_DATASETS)


def _people(world_model):
    getter = getattr(world_model, "get_dataset", None)
    people = {}
    for dataset in PERSON_DATASETS:
        for entity in (getter(dataset) if callable(getter) else None) or []:
            if _is_person(entity) and entity.get("id"):
                people.setdefault(entity["id"], entity)
    return list(people.values())


def parent_ids(state, world_model=None):
    """The people among the person's parents; other entries of ``parents`` (a family pop, a country) stay as they are."""
    return [item for item in state["draft"].get("parents") or [] if _is_person(_entity(world_model, item))]


def parent_dna(parent):
    """A parent's DNA: as stored, else the preview the editor shows for them."""
    dna = str(parent.get("genetic_dna") or "").strip()
    return dna if decode_person_dna(dna)["valid"] else create_person_dna(birth_seed(parent), "medium")


def parent_note(parent, birth_year):
    """What is odd about a parent for a birth in a year; empty when nothing is."""
    born, ended, year = _year(parent.get("start_year")), _year(parent.get("end_year")), _year(birth_year)
    if year is None:
        return ""
    if born is not None and born >= year:
        return f"born {born}, after them"
    if born is not None and year - born < YOUNGEST_PARENT_AGE:
        return f"aged {year - born} at the birth"
    if ended is not None and ended < year:
        return f"died {ended}, before the birth"
    return ""


def inherit_genome(state, world_model=None, seed=None):
    """Draw the genome from the chosen parents; the same parents and birth seed draw the same genome."""
    parents = [_entity(world_model, item) for item in parent_ids(state, world_model)]
    if not parents:
        return False
    seed = seed or ":".join([birth_seed(state["draft"]), *(parent["id"] for parent in parents)])
    _set(state, "genetic_dna", inherit_person_dna([parent_dna(parent) for parent in parents], seed))
    names = " and ".join(entity_label(world_model, parent["id"]) for parent in parents)
    state["status"] = f"Drew the genome from {names}; skin tone and loci can still be changed."
    return True


def toggle_parent(state, person_id, world_model=None):
    """Add a person as a parent (two at most) or take them away; the genome is drawn again from who is left."""
    if person_id == state["draft"].get("id") or not _is_person(_entity(world_model, person_id)):
        return False
    entries = list(state["draft"].get("parents") or [])
    if person_id in entries:
        entries.remove(person_id)
    elif len(parent_ids(state, world_model)) >= MAX_PARENTS:
        state["status"] = "Two parents are chosen; take one away first."
        return False
    else:
        entries.append(person_id)
    _set(state, "parents", entries)
    if not inherit_genome(state, world_model):
        state["status"] = "No parents: the genome stays as it is; Reroll genome draws a new one."
    return True


def parent_rows(state, world_model=None):
    """People who could be parents, the chosen ones first, each with their years and anything odd about them."""
    query = state["inputs"].get("people_search", "").strip().casefold()
    chosen = set(parent_ids(state, world_model))
    year = state["draft"].get("start_year")
    rows = []
    for person in _people(world_model):
        name = str(person.get("pretty_name") or person.get("name") or person["id"])
        if person["id"] == state["draft"].get("id") or (query and query not in name.casefold() and query not in person["id"]):
            continue
        born, ended = _year(person.get("start_year")), _year(person.get("end_year"))
        rows.append({
            "id": person["id"], "label": name, "born": born, "ended": ended,
            "age": None if born is None or _year(year) is None else _year(year) - born,
            "note": parent_note(person, year), "chosen": person["id"] in chosen,
            "has_dna": decode_person_dna(person.get("genetic_dna"))["valid"],
        })
    rows.sort(key=lambda row: (not row["chosen"], row["label"].casefold()))
    return rows


# --- genetics ---

def select_skin_tone(state, tone_id, person_id="person"):
    if tone_id not in {tone["id"] for tone in SKIN_TONES}:
        return False
    _set(state, "genetic_dna", set_skin_tone(state["draft"].get("genetic_dna"), tone_id, person_id))
    state["status"] = f"Skin tone locus set to {tone_id}."
    return True


def adjust_body_trait(state, trait_id, delta, person_id="person"):
    if trait_id not in {trait["id"] for trait in BODY_TRAITS}:
        return False
    dna = state["draft"].get("genetic_dna")
    current = decode_person_dna(dna)["body_shape"].get(trait_id, 0.5)
    _set(state, "genetic_dna", set_body_trait(dna, trait_id, current + float(delta), person_id))
    label = next(trait["label"] for trait in BODY_TRAITS if trait["id"] == trait_id)
    state["status"] = f"{label} locus adjusted."
    return True


def reroll_genome(state, seed=None, world_model=None):
    """A new genome: drawn again from the parents when there are any, else new loci with the skin tone kept."""
    if inherit_genome(state, world_model, seed or _new_seed()):
        return True
    tone = decode_person_dna(state["draft"].get("genetic_dna"))["skin_tone"]["id"]
    _set(state, "genetic_dna", create_person_dna(seed or _new_seed(), tone))
    state["status"] = "Drew a new genome; skin tone kept."
    return True


def select_clothing(state, clothing_id):
    if clothing_id not in {None, *TEST_CLOTHING_IDS}:
        return False
    _set(state, "equipped_clothing", [clothing_id] if clothing_id else [])
    state["status"] = "Naked body preview." if clothing_id is None else "Clothing item layered over the body."
    return True


def editor_appearance(state):
    return decode_person_dna(state["draft"].get("genetic_dna"))


def working_clothing_id(state):
    return _clothing_id(state["draft"])


# --- personality ---

def toggle_word(state, word):
    words = [str(item) for item in state["draft"].get(WORDS_FIELD) or []]
    key = lookup_key(word)
    kept = [item for item in words if lookup_key(item) != key]
    _set(state, WORDS_FIELD, kept if len(kept) < len(words) else words + [str(word)])
    return True


def adjust_baseline(state, axis, delta, world_model=None):
    """Move an axis's birth mean from where it stands, which makes it authored."""
    if axis not in BASELINE_FIELDS:
        return False
    current = authored_baseline(state["draft"], axis)
    if current is None:
        current = personality(state["draft"], world_model)[axis].baseline
    _set(state, BASELINE_FIELDS[axis], round(max(0.0, min(1.0, current + float(delta))), 2))
    return True


def reset_baseline(state, axis):
    """Back to the birth draw for an axis."""
    if axis not in BASELINE_FIELDS:
        return False
    _set(state, BASELINE_FIELDS[axis], None)
    return True


def reroll_birth(state, seed=None):
    """A new birth seed: a new draw on every axis that is not authored (still around the parents, if any)."""
    _set(state, SEED_FIELD, str(seed or _new_seed()))
    state["status"] = "Drew a new birth personality."
    return True


def set_word_axis(state, axis):
    state["word_axis"] = axis if axis in AXES else None
    state["scroll"]["words"] = 0
    return True


def word_rows(state, world_model=None):
    """Personality words, those speaking to the chosen axis highest first, each with its places."""
    unique = {}
    for entity in trait_index(world_model).values():
        unique.setdefault(entity.get("id"), entity)
    chosen = {lookup_key(word) for word in state["draft"].get(WORDS_FIELD) or []}
    query = state["inputs"].get("word_search", "").strip().casefold()
    axis = state.get("word_axis")
    rows = []
    for entity in unique.values():
        places = position(entity)
        name = trait_label(entity)
        if axis and axis not in places:
            continue
        if query and query not in name.casefold():
            continue
        rows.append({
            "label": name,
            "positions": places,
            "chosen": lookup_key(name) in chosen,
            "excludes": list(entity.get("excludes_actions") or []),
        })
    if axis:
        rows.sort(key=lambda row: (-row["positions"][axis], row["label"]))
    else:
        rows.sort(key=lambda row: row["label"].casefold())
    return rows


def editor_personality(state, world_model=None):
    return personality(state["draft"], world_model)


def chosen_exclusions(state, world_model=None):
    """What the person's words exclude outright: "Pacifist excludes Violence"."""
    traits = trait_index(world_model)
    found = []
    for word in state["draft"].get(WORDS_FIELD) or []:
        entity = traits.get(lookup_key(word))
        if entity and entity.get("excludes_actions"):
            found.append(f"{trait_label(entity)} excludes {', '.join(str(item) for item in entity['excludes_actions'])}")
    return found


# --- life ---

def set_life_tab(state, tab_id):
    if tab_id not in {tab["id"] for tab in LIFE_TABS}:
        return False
    state["life_tab"] = tab_id
    state["inputs"]["place_search"] = ""
    state["focus"] = None
    return True


def choose_job(state, job_id):
    """Choose a job, or drop it when it is the one chosen."""
    _set(state, "is_employed_as", None if state["draft"].get("is_employed_as") == job_id else job_id)
    return True


def toggle_shared_knowledge(state, collection_id):
    shared = state["shared_knowledge"]
    state["shared_knowledge"] = [item for item in shared if item != collection_id] if collection_id in shared else shared + [collection_id]
    _refresh_dirty(state)
    return True


def job_rows(state, world_model=None):
    getter = getattr(world_model, "get_dataset", None)
    jobs = [entity for entity in (getter("jobs") if callable(getter) else None) or [] if isinstance(entity, dict)]
    chosen = state["draft"].get("is_employed_as")
    return sorted(
        ({"id": job["id"], "label": str(job.get("pretty_name") or job.get("name") or job["id"]), "chosen": job["id"] == chosen}
         for job in jobs if job.get("id")),
        key=lambda row: row["label"].casefold(),
    )


def knowledge_rows(state, world_model=None):
    getter = getattr(world_model, "get_dataset", None)
    collections = [entity for entity in (getter("collections") if callable(getter) else None) or [] if isinstance(entity, dict)]
    return sorted(
        ({"id": entity["id"], "label": str(entity.get("pretty_name") or entity.get("name") or entity["id"]),
          "size": len(entity.get("includes") or []), "chosen": entity["id"] in state["shared_knowledge"]}
         for entity in collections if entity.get("id") and _collection_class(entity) == SHARED_KNOWLEDGE),
        key=lambda row: row["label"].casefold(),
    )


# --- review and save ---

def entity_label(world_model, entity_id, empty="not set"):
    entity = _entity(world_model, entity_id)
    if entity is None:
        return entity_id or empty
    return str(entity.get("pretty_name") or entity.get("name") or entity.get("common_name") or entity_id)


def step_done(state, step_id, world_model=None):
    draft = state["draft"]
    if step_id == "parents":
        return bool(parent_ids(state, world_model))
    if step_id == "person":
        return bool(draft.get("pretty_name"))
    if step_id == "birth":
        return draft.get("start_year") is not None and bool(draft.get("birth_location"))
    if step_id == "genetics":
        return decode_person_dna(draft.get("genetic_dna"))["valid"]
    if step_id == "personality":
        return bool(draft.get(WORDS_FIELD)) or any(draft.get(field) is not None for field in BASELINE_FIELDS.values())
    if step_id == "life":
        return any(draft.get(field) for field in ("residence", "is_employed_as", "is_employed_at")) or bool(state["shared_knowledge"])
    return not state["dirty"]


def readiness(state, world_model=None):
    draft = dict(state["draft"])
    if state["shared_knowledge"] and not draft.get(KNOWLEDGE_FIELD):
        draft[KNOWLEDGE_FIELD] = "(made on save)"
    return assess_person_readiness(draft, world_model)


def save_plan(state, world_model=None):
    """What Save writes: [(entity, fields)], fields None for a whole new entity; or a reason it cannot."""
    draft = state["draft"]
    name = draft.get("pretty_name") or draft.get("name") or draft.get("id")
    if state["is_new"] and not draft.get("pretty_name"):
        return "Give the person a name before saving."
    plan = []
    shared_changed = state["shared_knowledge"] != state["original_shared_knowledge"]
    collection_id = draft.get(KNOWLEDGE_FIELD)
    if shared_changed:
        stored = _entity(world_model, collection_id)
        if stored is not None:
            collection = copy.deepcopy(stored)
            kept = [item for item in collection.get("includes") or []
                    if _collection_class(_entity(world_model, item)) != SHARED_KNOWLEDGE]
            collection["includes"] = list(state["shared_knowledge"]) + kept
        else:
            collection_id = f"coll_knowledge_{draft['id'].removeprefix('person_')}"
            collection = {
                "id": collection_id, "_dataset": "collections", "type": "collection",
                "name": f"Knowledge of {name}", "pretty_name": f"Knowledge of {name}",
                "collection_class": PERSONAL_KNOWLEDGE,
                "includes": list(state["shared_knowledge"]), "member_records": [],
            }
            _set(state, KNOWLEDGE_FIELD, collection_id)
        plan.append((collection, None))
    if state["is_new"]:
        plan.append((copy.deepcopy(draft), None))
    else:
        fields = changed_fields(state)
        if fields:
            plan.append((draft, fields))
    return plan


def save_summary(state):
    """What Save would write, in words."""
    shared_changed = state["shared_knowledge"] != state["original_shared_knowledge"]
    if state["is_new"]:
        return "the new person" + (" and their knowledge collection" if state["shared_knowledge"] else "")
    fields = changed_fields(state)
    parts = [", ".join(fields)] if fields else []
    if shared_changed:
        parts.append("the shared collections their knowledge includes")
    return "; ".join(parts) or "nothing: no changes"


def mark_saved(state):
    state["original"] = copy.deepcopy(state["draft"])
    state["original_shared_knowledge"] = list(state["shared_knowledge"])
    state["is_new"] = False
    state["dirty"] = False


def revert_person_editor(state, world_model=None):
    if state["is_new"]:
        fresh = new_person_state(world_model, int(state["draft"].get("start_year") or 2400 - ADULT_AGE) + ADULT_AGE,
                                 state["draft"].get("birth_location"), state["draft"].get(SEED_FIELD))
        state.update(fresh)
        state["status"] = "Cleared the new person."
        return
    original = state["original"] or {}
    fresh = new_person_editor_state(original, world_model)
    step = state["step"]
    state.update(fresh)
    state["step"] = step
    state["status"] = "Reverted to the saved person."


# --- clicks ---

def click(state, hitbox, world_model=None, default_year=2400):
    """Apply a clicked editor control; returns the name of an action the simulation owns, or None."""
    kind = hitbox.get("kind")
    person_id = state["draft"].get("id") or "person"
    if kind in ("save", "revert", "new", "simulation"):
        return kind
    if kind == "step":
        set_step(state, hitbox.get("step"))
    elif kind == "back":
        move_step(state, -1)
    elif kind == "next":
        move_step(state, 1)
    elif kind == "focus":
        focus_input(state, hitbox.get("input"))
    elif kind == "sex":
        set_sex(state, hitbox.get("sex"))
    elif kind == "year_delta":
        adjust_birth_year(state, hitbox.get("delta", 0), default_year)
    elif kind == "place_choose":
        choose_place(state, hitbox.get("field"), hitbox.get("place_id"), world_model)
    elif kind == "place_browse":
        browse_place(state, hitbox.get("field"), hitbox.get("place_id"), world_model)
    elif kind == "place_clear":
        choose_place(state, hitbox.get("field"), None, world_model)
    elif kind == "skin_tone":
        select_skin_tone(state, hitbox.get("tone_id"), person_id)
    elif kind == "body_trait":
        adjust_body_trait(state, hitbox.get("trait_id"), hitbox.get("delta", 0.0), person_id)
    elif kind == "reroll_genome":
        reroll_genome(state, world_model=world_model)
    elif kind == "parent":
        toggle_parent(state, hitbox.get("person_id"), world_model)
    elif kind == "clothing":
        select_clothing(state, hitbox.get("clothing_id"))
    elif kind == "reroll_birth":
        reroll_birth(state)
    elif kind == "baseline_delta":
        adjust_baseline(state, hitbox.get("axis"), hitbox.get("delta", 0.0), world_model)
    elif kind == "baseline_reset":
        reset_baseline(state, hitbox.get("axis"))
    elif kind == "word_axis":
        set_word_axis(state, hitbox.get("axis"))
    elif kind == "word":
        toggle_word(state, hitbox.get("word"))
    elif kind == "life_tab":
        set_life_tab(state, hitbox.get("tab"))
    elif kind == "job":
        choose_job(state, hitbox.get("job_id"))
    elif kind == "knowledge":
        toggle_shared_knowledge(state, hitbox.get("collection_id"))
    else:
        return None
    if kind != "focus":
        state["focus"] = None
    return None


def scroll(state, key, rows):
    state["scroll"][key] = max(0, int(state["scroll"].get(key, 0)) + int(rows))
    return True
