"""Introduce unit cards, formation decks and what fielding them draws on.

A unit card (dataset ``unit_cards``, id prefix ``card_``) is one deployable
package a faction fields, in the manner of a WARNO deck card: the "GGO Sol
Marine Tank Platoon" is three tanks and the crew their vehicle design lists.
A formation's deck is the cards it fields. A card lists what one copy takes
from the world when it is fielded: manpower (people by role) and equipment
(vehicles and items). There are no deck points and no per-deck limits.

Fielding (``simulations/formation/fielding.py``) draws people from a service
pop and equipment from depot sites, and asks logistics to carry the equipment
to the formation; what is short is kept on the deck row and the copy is
fielded understrength.

What it does, as a single ``apply_changes`` transaction:

1. Schema. ``schema_unit_card`` (extends ``entity_core``): ``faction``,
   ``card_category``, ``card_manpower``, ``card_equipment``.
   ``schema_formation``: ``deck_cards``, ``manpower_pop``, ``supply_depot``
   (``deck_budget`` removed). ``schema_locations``: ``inventory_items`` and
   ``vehicle_stock`` for depots. ``schema_logistics``: ``cargo_manifest`` and
   ``requested_by``. ``schema_pop``: ``pop_type`` gains ``service``, with the
   text owned by ``tools/author_pop_system_model.py``. ``schema_person``:
   ``serves_in``, ``service_role``, ``service_rank`` and ``source_pop``, for a
   person saved from a formation's people (``formation_people.py``).
2. Data, each written once and then left to the app, since fielding changes
   it. All of it is test data with placeholder figures:
   - service pops for GGO Sol Marines, the US Army, US Air Force and US Navy,
     with the US Air Force and Navy formations drawing on theirs;
   - a GGO supply depot on Luna holding tanks, jeeps, exosuits, an assault
     carrier and rifles;
   - crew roles for four real vehicles that had none (T-64, MiG-21, Puma,
     Tatra 813);
   - unit cards for GGO and for the eras of vehicles in the store.
3. A card still in the first shape (``card_contents``, ``card_cost``,
   ``max_per_deck``) is rewritten into manpower and equipment, and
   ``deck_budget`` is dropped from any formation that carries one.

An entity is only added when everything it refers to exists. Runtime code
reads these definitions from the ontology; this module is not a parallel
registry. Re-runnable. The store is written; the ``.owl`` checkpoint is
exported only with ``--export``.
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.author_pop_system_model import POP_SCHEMA_FIELDS
from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "unit_card_model"

CATEGORY_VOCAB = (
    "Command", "Infantry", "Armor", "Recon", "Support", "Artillery",
    "Air Defense", "Helicopters", "Aircraft", "Logistics", "Naval", "Space",
)

SCHEMA_UNIT_CARD_FIELDS = {
    "faction": {
        "type": "entity", "target": "factions", "section": "Card", "optional": True,
        "description": "The faction that fields this card; only its formations' decks offer it. "
                       "Blank means any faction's deck may use it.",
    },
    "card_category": {
        "type": "string", "section": "Card", "optional": True,
        "description": "Deck tab the card sits in. Suggested: " + " | ".join(CATEGORY_VOCAB)
                       + "; any other label works.",
    },
    "card_manpower": {
        "type": "object_list", "section": "Card", "optional": True,
        "description": (
            "People one copy of the card takes, by role: {id, role, rank, count, is_command}. "
            "Vehicle crew are not listed here; they come with the vehicles in card_equipment."
        ),
    },
    "card_equipment": {
        "type": "object_list", "section": "Card", "optional": True,
        "description": (
            "Equipment one copy of the card takes: {id, kind: vehicle|item, vehicle|item: entity id, count}. "
            "A vehicle brings its crew into the card's manpower: the vehicle design's crew_roles (else "
            "crew_complement) unless the entry lists its own. Transport is part of the card, not chosen per deck."
        ),
    },
}
RETIRED_CARD_FIELDS = ("card_contents", "card_cost", "max_per_deck")

NEW_FORMATION_FIELDS = {
    "deck_cards": {
        "type": "object_list", "section": "Formation Sim", "optional": True,
        "description": (
            "The unit cards this formation fields: {card: unit card id, count, short}. short is what fielding "
            "could not draw ({people: n, 'vehicle:<id>': n, 'item:<id>': n}); those copies are understrength."
        ),
    },
    "manpower_pop": {
        "type": "entity", "target": "pops", "section": "Formation Sim", "optional": True,
        "description": "The pop this formation's decks draw people from, and its subordinates' unless they "
                       "name their own. Blank: the nearest ancestor's, else the faction's first service pop.",
    },
    "supply_depot": {
        "type": "entity", "target": "locations", "section": "Formation Sim", "optional": True,
        "description": "The depot this formation's decks draw equipment from first, and its subordinates'. "
                       "The faction's other depots follow.",
    },
}
RETIRED_FORMATION_FIELDS = ("deck_budget",)

NEW_LOCATION_FIELDS = {
    "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
    "vehicle_stock": {
        "type": "object_list", "section": "Inventory", "optional": True,
        "description": "Vehicles held here, counted by design: {vehicle, quantity}. A depot's "
                       "(site_class depot) stock is what formation decks of its controlling faction draw on.",
    },
}

NEW_LOGISTICS_FIELDS = {
    "cargo_manifest": {
        "type": "object_list", "section": "Cargo", "optional": True,
        "description": "Cargo of several kinds: {kind: vehicle|item, vehicle|item: entity id, quantity}.",
    },
    "requested_by": {
        "type": "entity", "target": "formations", "section": "Route", "optional": True,
        "description": "The formation whose fielded cards asked for this delivery (route_class formation supply).",
    },
}

NEW_PERSON_FIELDS = {
    "serves_in": {
        "type": "entity", "target": "formations", "section": "Service", "optional": True,
        "description": "The formation this person serves in. They are one of the people its deck holds, "
                       "drawn from its manpower pop, not one more.",
    },
    "service_role": {
        "type": "string", "section": "Service", "optional": True,
        "description": "Their role in that formation, as the deck's cards name it (a card_manpower role or a "
                       "vehicle crew role).",
    },
    "service_rank": {"type": "string", "section": "Service", "optional": True},
    "source_pop": {
        "type": "entity", "target": "pops", "section": "Service", "optional": True,
        "description": "The pop this person was drawn from, such as a service pop.",
    },
}

GGO = "fac_ggo_sol_marine_command"
GGO_YEARS = {"start_year": 2448, "end_year": 5831}

EXAMPLE_CARD = {
    "id": "card_ggo_sol_marine_tank_platoon",
    "_dataset": "unit_cards",
    "type": "unit_card",
    "name": "GGO Sol Marine Tank Platoon",
    "pretty_name": "GGO Sol Marine Tank Platoon",
    "entry_status": "draft",
    "faction": GGO,
    "card_category": "Armor",
    "card_manpower": [],
    "card_equipment": [
        {"id": "eq_1", "kind": "vehicle", "vehicle": "veh_test_tank", "count": 3},
    ],
}


def _pop(pop_id, name, count, note, faction=None, **extra):
    pop = {"id": pop_id, "_dataset": "pops", "type": "pop", "name": name, "pretty_name": name,
           "pop_type": "service", "population_count": count, "entry_status": "draft",
           "wiki_entry": note + " Placeholder headcount, cumulative: the whole service, not one unit.", **extra}
    if faction:
        pop["faction"] = faction
    return pop


SERVICE_POPS = [
    _pop("pop_ggo_sol_marine_service_members", "GGO Sol Marine Service Members", 180000,
         "Everyone serving in the GGO Sol Marine Command; its formations' decks draw manpower from it.",
         faction=GGO, **GGO_YEARS),
    _pop("pop_us_army_service_members", "US Army Service Members", 480000,
         "Everyone serving in the US Army.", faction="fac_united_states_army"),
    _pop("pop_usaf_airmen", "US Air Force Airmen", 330000, "Everyone serving in the US Air Force."),
    _pop("pop_usn_sailors", "US Navy Sailors", 340000, "Everyone serving in the US Navy."),
]
FORMATION_POPS = {
    "form_united_states_air_force_usaf": "pop_usaf_airmen",
    "form_united_states_navy": "pop_usn_sailors",
}

DEPOTS = [
    {
        "id": "site_ggo_luna_supply_depot", "_dataset": "locations", "type": "location",
        "name": "GGO Sol Marine Supply Depot, Luna", "pretty_name": "GGO Sol Marine Supply Depot, Luna",
        "location_class": "site", "site_class": "depot", "parent_location": "body_luna",
        "controlling_factions": [GGO], "entry_status": "draft", **GGO_YEARS,
        "inventory_items": [
            {"item": "item_test_new_assault_rifle", "quantity": 600, "unit": "rifle"},
            {"item": "item_test_light_machine_gun", "quantity": 80, "unit": "gun"},
        ],
        "vehicle_stock": [
            {"vehicle": "veh_test_tank", "quantity": 9},
            {"vehicle": "veh_test_army_jeep", "quantity": 12},
            {"vehicle": "veh_test_exosuit", "quantity": 24},
            {"vehicle": "veh_test_spacecraft", "quantity": 1},
        ],
        "outbound_logistics_routes": [],
        "wiki_entry": "Test depot: GGO Sol Marine decks draw their equipment from here, and each formation "
                      "supplied gets a formation-supply logistics route out of it. Placeholder stock.",
    },
]

# Crew roles for vehicles in the store that had none. Well-known figures; the
# Puma also carries six dismounts, who are listed on the card.
VEHICLE_CREW = {
    "veh_t_64_main_battle_tank": [{"role": "Commander", "count": 1}, {"role": "Gunner", "count": 1},
                                  {"role": "Driver", "count": 1}],
    "veh_mig_21": [{"role": "Pilot", "count": 1}],
    "veh_sch_tzenpanzer_puma": [{"role": "Commander", "count": 1}, {"role": "Gunner", "count": 1},
                                {"role": "Driver", "count": 1}],
    "veh_tetra_813": [{"role": "Driver", "count": 1}],
}


def _card(card_id, name, category, manpower=(), equipment=(), faction=None, **extra):
    card = {"id": card_id, "_dataset": "unit_cards", "type": "unit_card", "name": name, "pretty_name": name,
            "entry_status": "draft", "card_category": category,
            "card_manpower": [{"id": f"man_{index}", "role": role, "rank": rank, "count": count, "is_command": lead}
                              for index, (role, rank, count, lead) in enumerate(manpower, 1)],
            "card_equipment": [{"id": f"eq_{index}", "kind": kind, kind: reference, "count": count}
                               for index, (kind, reference, count) in enumerate(equipment, 1)],
            **extra}
    if faction:
        card["faction"] = faction
    return card


ERA_CARDS = [
    _card("card_ggo_sol_marine_rifle_squad", "GGO Sol Marine Rifle Squad", "Infantry",
          manpower=[("Squad Leader", "Sergeant", 1, True), ("Rifleman", "Marine", 6, False),
                    ("Machine Gunner", "Marine", 2, False)],
          equipment=[("item", "item_test_new_assault_rifle", 7), ("item", "item_test_light_machine_gun", 2)],
          faction=GGO, **GGO_YEARS),
    _card("card_ggo_sol_marine_recon_patrol", "GGO Sol Marine Recon Patrol", "Recon",
          manpower=[("Patrol Leader", "Corporal", 1, True), ("Scout", "Marine", 1, False)],
          equipment=[("vehicle", "veh_test_army_jeep", 2), ("item", "item_test_new_assault_rifle", 2)],
          faction=GGO, **GGO_YEARS),
    _card("card_ggo_sol_marine_exosuit_section", "GGO Sol Marine Exosuit Section", "Infantry",
          manpower=[("Section Leader", "Sergeant", 1, True)],
          equipment=[("vehicle", "veh_test_exosuit", 4), ("item", "item_test_new_assault_rifle", 1)],
          faction=GGO, **GGO_YEARS),
    _card("card_ggo_sol_marine_assault_carrier", "GGO Sol Marine Assault Carrier", "Space",
          equipment=[("vehicle", "veh_test_spacecraft", 1)], faction=GGO, **GGO_YEARS),
    _card("card_fletcher_class_destroyer", "Fletcher-class Destroyer", "Naval",
          equipment=[("vehicle", "veh_fletcher_class_destroyer", 1)], start_year=1942, end_year=1971),
    _card("card_mig_21_flight", "MiG-21 Flight", "Aircraft",
          equipment=[("vehicle", "veh_mig_21", 2)], start_year=1959, end_year=2105),
    _card("card_t_64_tank_platoon", "T-64 Tank Platoon", "Armor",
          equipment=[("vehicle", "veh_t_64_main_battle_tank", 3)], start_year=1966, end_year=2034),
    _card("card_d_48_anti_tank_gun_section", "D-48 Anti-Tank Gun Section", "Support",
          equipment=[("vehicle", "veh_d48_gun", 2), ("vehicle", "veh_tetra_813", 2)],
          start_year=1967, end_year=2153),
    _card("card_f_22_raptor_pair", "F-22 Raptor Pair", "Aircraft",
          equipment=[("vehicle", "veh_f22_raptor", 2)], start_year=2005, end_year=2176),
    _card("card_panzergrenadier_group_puma", "Panzergrenadier Group (Puma)", "Infantry",
          manpower=[("Group Leader", "Unteroffizier", 1, True), ("Panzergrenadier", "Gefreiter", 5, False)],
          equipment=[("vehicle", "veh_sch_tzenpanzer_puma", 1)], start_year=2015, end_year=2131),
]


def _schema_by_name(datasets):
    out = {}
    for entity in datasets.get("schemas", []):
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("schema") or entity.get("name") or entity.get("id") or "")
        name = name.removeprefix("schema_")
        if name:
            out[name] = entity
    return out


def _unit_card_schema(schemas):
    existing = schemas.get("unit_card")
    if existing is None:
        return {
            "id": "schema_unit_card",
            "_dataset": "schemas",
            "type": "schema",
            "schema": "unit_card",
            "name": "unit_card",
            "pretty_name": "Unit Card",
            "extends": "entity_core",
            "fields": copy.deepcopy(SCHEMA_UNIT_CARD_FIELDS),
        }
    if existing.get("fields") == SCHEMA_UNIT_CARD_FIELDS:
        return None
    updated = copy.deepcopy(existing)
    updated["fields"] = copy.deepcopy(SCHEMA_UNIT_CARD_FIELDS)
    return updated


def _extended_schema(schema, new_fields, retired=(), keep_existing=False):
    """The schema with ``new_fields`` set (or only added when ``keep_existing``) and ``retired`` removed."""
    if schema is None:
        return None
    fields = dict(schema.get("fields") or {})
    wanted = {name: spec for name, spec in new_fields.items() if not (keep_existing and name in fields)}
    if all(fields.get(name) == spec for name, spec in wanted.items()) and not any(name in fields for name in retired):
        return None
    fields.update(copy.deepcopy(wanted))
    for name in retired:
        fields.pop(name, None)
    updated = copy.deepcopy(schema)
    updated["fields"] = fields
    return updated


def _reshaped_card(card):
    """A first-shape card (card_contents with vehicle and personnel slots) as manpower and equipment."""
    if not any(name in card for name in RETIRED_CARD_FIELDS):
        return None
    updated = {key: copy.deepcopy(value) for key, value in card.items() if key not in RETIRED_CARD_FIELDS}
    manpower = list(updated.get("card_manpower") or [])
    equipment = list(updated.get("card_equipment") or [])
    for slot in card.get("card_contents") or []:
        if not isinstance(slot, dict):
            continue
        if str(slot.get("kind") or "").lower() == "vehicle":
            if not slot.get("vehicle_id"):
                continue
            entry = {"id": f"eq_{len(equipment) + 1}", "kind": "vehicle", "vehicle": slot["vehicle_id"],
                     "count": slot.get("count", 1)}
            if slot.get("crew_roles") is not None:
                entry["crew_roles"] = slot["crew_roles"]
            equipment.append(entry)
        else:
            manpower.append({"id": f"man_{len(manpower) + 1}", "role": slot.get("role") or "Personnel",
                             "rank": slot.get("rank") or "", "count": slot.get("count", 1),
                             "is_command": bool(slot.get("is_command"))})
    updated["card_manpower"] = manpower
    updated["card_equipment"] = equipment
    return updated


def _references(entity):
    """Every entity id the authored entity points at."""
    ids = set()
    for field in ("faction", "parent_location"):
        if entity.get(field):
            ids.add(entity[field])
    ids.update(entity.get("controlling_factions") or [])
    for field in ("card_equipment", "inventory_items", "vehicle_stock"):
        for row in entity.get(field) or []:
            ids.update(row[key] for key in ("vehicle", "item") if row.get(key))
    return ids


def build_transaction(datasets):
    schemas = _schema_by_name(datasets)
    upserts = [change for change in (
        _unit_card_schema(schemas),
        _extended_schema(schemas.get("formation"), NEW_FORMATION_FIELDS, RETIRED_FORMATION_FIELDS),
        _extended_schema(schemas.get("locations"), NEW_LOCATION_FIELDS, keep_existing=True),
        _extended_schema(schemas.get("logistics"), NEW_LOGISTICS_FIELDS),
        _extended_schema(schemas.get("pop"), {"pop_type": POP_SCHEMA_FIELDS["pop_type"]}),
        _extended_schema(schemas.get("person"), NEW_PERSON_FIELDS),
    ) if change]
    cards = [entity for entity in datasets.get("unit_cards", []) if isinstance(entity, dict)]
    upserts += [change for change in map(_reshaped_card, cards) if change]
    for formation in datasets.get("formations", []):
        if isinstance(formation, dict) and any(name in formation for name in RETIRED_FORMATION_FIELDS):
            upserts.append({key: value for key, value in formation.items() if key not in RETIRED_FORMATION_FIELDS})

    by_id = {
        entity.get("id"): entity
        for entities in datasets.values() if isinstance(entities, list)
        for entity in entities if isinstance(entity, dict) and entity.get("id")
    }
    added = set()
    for entity in SERVICE_POPS + DEPOTS + [EXAMPLE_CARD] + ERA_CARDS:
        if entity["id"] not in by_id and _references(entity) <= set(by_id) | added:
            upserts.append(copy.deepcopy(entity))
            added.add(entity["id"])
    for formation_id, pop_id in FORMATION_POPS.items():
        formation = by_id.get(formation_id)
        if formation is not None and not formation.get("manpower_pop") and (pop_id in by_id or pop_id in added):
            upserts.append({**formation, "manpower_pop": pop_id})
    for vehicle_id, roles in VEHICLE_CREW.items():
        vehicle = by_id.get(vehicle_id)
        if vehicle is not None and not vehicle.get("crew_roles"):
            upserts.append({**vehicle, "crew_roles": copy.deepcopy(roles),
                            "crew_complement": sum(role["count"] for role in roles)})
    return upserts


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _validate(store):
    datasets = store.load_datasets()
    schemas = _schema_by_name(datasets)
    assert schemas["unit_card"].get("fields") == SCHEMA_UNIT_CARD_FIELDS, "schema_unit_card fields differ"
    formation_fields = schemas["formation"].get("fields", {})
    for name in NEW_FORMATION_FIELDS:
        assert name in formation_fields, f"{name} missing from schema_formation"
    for name in RETIRED_FORMATION_FIELDS:
        assert name not in formation_fields, f"{name} still on schema_formation"
    for schema_name, fields in (("locations", NEW_LOCATION_FIELDS), ("logistics", NEW_LOGISTICS_FIELDS),
                                ("person", NEW_PERSON_FIELDS)):
        for name in fields:
            assert name in schemas[schema_name].get("fields", {}), f"{name} missing from schema_{schema_name}"
    cards = datasets.get("unit_cards", [])
    for card in cards:
        stale = [name for name in RETIRED_CARD_FIELDS if name in card]
        assert not stale, f"{card.get('id')} still has {stale}"
    service = [pop["id"] for pop in datasets.get("pops", []) if pop.get("pop_type") == "service"]
    depots = [location["id"] for location in datasets.get("locations", []) if location.get("site_class") == "depot"]
    return {"unit_cards": len(cards), "service_pops": len(service), "depots": len(depots)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    parser.add_argument("--export", action="store_true", help="also export the .owl checkpoint")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    upserts = build_transaction(datasets)

    print(f"upserts: {len(upserts)}")
    for entity in upserts:
        print(f"  {entity.get('_dataset', '?'):<12} {entity['id']}")
    if args.dry_run:
        return
    if not upserts:
        print("nothing to do (ontology already matches)")
        return

    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    print(f"validated; dataset sizes: {_validate(store)}")
    if args.export:
        store.export_rdfxml(ONTOLOGY_PATH)
        store.compact_database()
        print("checkpoint exported")


if __name__ == "__main__":
    main()
