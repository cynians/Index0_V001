"""Author person needs-panel and Big Five fields into the ontology schema.

The ontology is the durable semantic source. Runtime person code may cache or
project these values for display, but this module does not create a parallel
registry and deliberately does not invent scores for existing people.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


PERSON_PSYCHOLOGY_FIELDS = {
    "wishes": {
        "type": "string_list",
        "section": "Needs and Agency",
        "optional": True,
    },
    "goals": {
        "type": "string_list",
        "section": "Needs and Agency",
        "optional": True,
    },
    "big_five_openness": {
        "type": "number",
        "section": "Personality - Big Five",
        "optional": True,
    },
    "big_five_conscientiousness": {
        "type": "number",
        "section": "Personality - Big Five",
        "optional": True,
    },
    "big_five_extraversion": {
        "type": "number",
        "section": "Personality - Big Five",
        "optional": True,
    },
    "big_five_agreeableness": {
        "type": "number",
        "section": "Personality - Big Five",
        "optional": True,
    },
    "big_five_neuroticism": {
        "type": "number",
        "section": "Personality - Big Five",
        "optional": True,
    },
    "personality_adjectives": {
        "type": "string_list",
        "section": "Personality - Big Five",
        "optional": True,
    },
}


def _schema_name(entity):
    return str(
        entity.get("schema")
        or entity.get("name")
        or entity.get("id")
        or ""
    ).removeprefix("schema_")


def build_changes(datasets):
    schemas = {
        _schema_name(entity): dict(entity)
        for entity in datasets.get("schemas", [])
        if isinstance(entity, dict)
    }
    person_schema = schemas.get("person")
    if person_schema is None:
        raise RuntimeError("Ontology does not contain the person schema")
    person_schema["fields"] = {
        **(person_schema.get("fields") or {}),
        **PERSON_PSYCHOLOGY_FIELDS,
    }
    return [person_schema]


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} person psychology schema entity")


if __name__ == "__main__":
    main()
