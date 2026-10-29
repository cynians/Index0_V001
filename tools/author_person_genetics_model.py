"""Author Person DNA and birth fields plus minimal clothing items in the live ontology."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

CLOTHING_ENTITIES = (
    {
        "id": "cat_clothing", "_dataset": "categories", "type": "category",
        "name": "Clothing", "pretty_name": "Clothing", "category_kind": "form",
        "parents": ["cat_manufactured_good"],
        "category_notes": "Wearable item sub-category; garments remain ordinary items.",
    },
    {
        "id": "item_test_toga", "_dataset": "items", "type": "item",
        "name": "Test Toga", "pretty_name": "Test Toga",
        "categories": ["cat_clothing"], "default_unit": "garment",
        "portable": "hand", "storage_modes": ["folded"],
        "descriptive_capabilities": ["wearable", "editor_clothing_overlay"],
        "wearable_slots": ["torso", "legs"],
        "appearance_profile": {
            "silhouette": "toga", "primary_color": "#d9d0b6", "accent_color": "#8d6f45",
        },
        "clothing_reference_body_shape": {"stature": 0.5, "leg_length": 0.5, "arm_length": 0.5, "torso_width": 0.5, "shoulder_width": 0.5, "head_size": 0.5},
        "clothing_sizing_axes": ["stature", "leg_length", "arm_length", "torso_width", "shoulder_width", "head_size"],
    },
    {
        "id": "item_test_suit", "_dataset": "items", "type": "item",
        "name": "Test Suit", "pretty_name": "Test Suit",
        "categories": ["cat_clothing"], "default_unit": "garment",
        "portable": "hand", "storage_modes": ["folded", "hanging"],
        "descriptive_capabilities": ["wearable", "editor_clothing_overlay"],
        "wearable_slots": ["torso", "arms", "legs"],
        "appearance_profile": {
            "silhouette": "suit", "primary_color": "#263447", "accent_color": "#e6e1d7",
        },
        "clothing_reference_body_shape": {"stature": 0.5, "leg_length": 0.5, "arm_length": 0.5, "torso_width": 0.5, "shoulder_width": 0.5, "head_size": 0.5},
        "clothing_sizing_axes": ["stature", "leg_length", "arm_length", "torso_width", "shoulder_width", "head_size"],
    },
)


def author_person_genetics_model(path=ONTOLOGY_PATH):
    store = PersistentOntologyStore(Path(path))
    datasets = store.load_datasets()
    schema = next(entity for entity in datasets["schemas"] if entity.get("id") == "schema_person")
    fields = dict(schema.get("fields") or {})
    fields["genetic_dna"] = {
        "type": "string",
        "section": "Genetics and Appearance",
        "optional": True,
        "description": (
            "Versioned, checksum-protected Person Editor genotype string. "
            "I0DNA1 currently encodes skin tone and bounded body-proportion loci."
        ),
    }
    fields["equipped_clothing"] = {
        "type": "entity_list", "target": "items",
        "section": "Genetics and Appearance", "optional": True,
        "description": "Ordinary clothing items currently layered over the DNA-decoded naked body.",
    }
    fields["birth_location"] = {
        "type": "entity", "target": "locations",
        "section": "Birth", "optional": True,
        "description": (
            "Where the person was born; the year is start_year. Chosen in the Person Editor "
            "from the place tree (world/place_tree.py)."
        ),
    }
    fields["birth_seed"] = {
        "type": "string",
        "section": "Birth", "optional": True,
        "description": (
            "What the person's birth draws are made from: the Big Five birth baseline "
            "(world/personality.py) and a new person's first DNA. Absent, the id is used."
        ),
    }
    schema["fields"] = fields
    item_schema =next(entity for entity in datasets["schemas"] if entity.get("id") == "schema_item")
    item_fields = dict(item_schema.get("fields") or {})
    item_fields["wearable_slots"] = {
        "type": "string_list", "section": "Clothing", "optional": True,
    }
    item_fields["appearance_profile"] = {
        "type": "object", "section": "Clothing", "optional": True,
        "description": "Lightweight renderer profile; clothing remains an ordinary categorized item.",
    }
    item_fields["clothing_design_ref"] = {
        "type": "string", "section": "Clothing", "optional": True,
        "description": "Project-relative Pixel Studio document for the authored reference garment.",
    }
    item_fields["clothing_reference_body_shape"] = {
        "type": "object", "section": "Clothing", "optional": True,
        "description": "DNA body metrics used as the landmark frame for the reference drawing.",
    }
    item_fields["clothing_sizing_axes"] = {
        "type": "string_list", "section": "Clothing", "optional": True,
        "description": "Human DNA metrics used when deriving fitted garment pixels.",
    }
    item_schema["fields"] = item_fields
    return bool(store.persist_entities([schema, item_schema, *CLOTHING_ENTITIES]))


if __name__ == "__main__":
    if not author_person_genetics_model():
        raise SystemExit("Could not persist the person genetics schema")
    print("Authored Person DNA and birth fields and two categorized clothing items")
