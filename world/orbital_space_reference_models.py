"""Auto-create an "orbital space" location for every star and planet.

Moons, space stations and spacecraft conceptually orbit *around* a body
without being *on* it. Before this module, they attached directly to the
body's own surface location, so a repository/timeline query for "what is at
Earth" could not distinguish a lunar space station from something standing
on the ground. Grouping orbiting things under a distinct, automatically
maintained orbital-space location keeps "in orbit around Earth" a genuine,
separate place from "on Earth" -- and gives the random year/location picker
a real, selectable entry like "2025 - Earth Orbit", since that picker only
requires an extant `locations`-dataset entity, not a special orbital flag.

This follows the same idempotent, lazily-materializing idiom as
earth_reference_models.py's `_ensure_earth_hierarchy_location`: it never
overwrites anything a player or another system authored, only fills in the
one companion entity per host body if it is missing.
"""

ORBITAL_SPACE_LOCATION_CLASS = "orbital_space"
_HOST_LOCATION_CLASSES = {"star", "planet"}


def _runtime_entity_store(target):
    if hasattr(target, "entities"):
        entities = getattr(target, "entities", {})
        datasets = getattr(target, "datasets", None)
        if not isinstance(datasets, dict):
            datasets = {}
            target.datasets = datasets
        return entities, datasets
    return target, {}


def _ensure_dataset_entry(dataset, entity):
    entity_id = entity.get("id") if isinstance(entity, dict) else None
    if entity_id and not any(isinstance(item, dict) and item.get("id") == entity_id for item in dataset):
        dataset.append(entity)


def orbital_space_entity_id(body_id):
    return f"orbit_{body_id}"


def apply_orbital_space_reference_models(target):
    """Ensure every star/planet has a matching orbital-space location.

    Returns True if any entity was created or updated, mirroring the other
    apply_*_reference_models functions so callers can treat them uniformly.
    """
    entities, datasets = _runtime_entity_store(target)
    if not isinstance(entities, dict) or not isinstance(datasets, dict):
        return False

    locations = datasets.setdefault("locations", [])
    changed = False
    for body_id, body in list(entities.items()):
        if not isinstance(body, dict):
            continue
        location_class = str(body.get("location_class") or body.get("body_class") or "").strip().lower()
        if location_class not in _HOST_LOCATION_CLASSES:
            continue

        orbit_id = orbital_space_entity_id(body_id)
        body_name = str(body.get("name") or body.get("pretty_name") or body_id)
        orbit_entity = entities.get(orbit_id)
        if not isinstance(orbit_entity, dict):
            orbit_entity = {
                "id": orbit_id,
                "name": f"{body_name} Orbit",
                "pretty_name": f"{body_name} Orbit",
                "type": "location",
                "_dataset": "locations",
                "location_class": ORBITAL_SPACE_LOCATION_CLASS,
                "system_role": "orbital_space",
                "parent_location": body_id,
                "parents": [body_id],
                "orbits_body_id": body_id,
                "star_system": body.get("star_system"),
                "start_year": body.get("start_year"),
                "end_year": body.get("end_year"),
                "orbital_space_reference_generated": True,
                "environment_summary": {
                    "status": "orbital_space",
                    "summary": (
                        f"The volume of space in orbit around {body_name}, distinct "
                        f"from its surface. Moons, stations, and spacecraft orbiting "
                        f"{body_name} belong here rather than on {body_name} itself."
                    ),
                },
            }
            entities[orbit_id] = orbit_entity
            changed = True
        else:
            if body.get("star_system") and orbit_entity.get("star_system") != body.get("star_system"):
                orbit_entity["star_system"] = body.get("star_system")
                changed = True
            if orbit_entity.get("parent_location") != body_id:
                orbit_entity["parent_location"] = body_id
                changed = True

        _ensure_dataset_entry(locations, orbit_entity)

        constituents = body.get("constituents")
        if isinstance(constituents, list):
            if orbit_id not in constituents:
                constituents.append(orbit_id)
                changed = True
        elif not constituents:
            body["constituents"] = [orbit_id]
            changed = True

    return changed
