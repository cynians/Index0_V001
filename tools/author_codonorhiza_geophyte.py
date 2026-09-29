"""Author the documented corm on the live Codonorhiza species entity."""

import json
from pathlib import Path

from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIES_ID = "spec_codonorhiza_elandsmontana"
SOURCE = "https://www.sanbi.org/wp-content/uploads/2024/05/2015_Strelitzia35.pdf"


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    entity = loader.entities.get(SPECIES_ID)
    if not isinstance(entity, dict):
        raise RuntimeError(f"Missing live species: {SPECIES_ID}")
    if entity.get("plant_life_form") != "geophyte":
        raise RuntimeError("Expected the authored geophyte life form before adding its organ type")

    output = PROJECT_ROOT / "artifacts" / "codonorhiza_geophyte_v001"
    output.mkdir(parents=True, exist_ok=True)
    before_path = output / "ontology_fields_before.json"
    if not before_path.exists():
        before_path.write_text(json.dumps({
            "id": SPECIES_ID,
            "plant_life_form": entity.get("plant_life_form"),
            "belowground_storage": entity.get("belowground_storage"),
        }, indent=2), encoding="utf-8")

    entity["belowground_storage"] = ["corm"]
    if not loader.persist_entity(entity):
        raise RuntimeError(f"Could not persist {SPECIES_ID}")
    (output / "authored_fields.json").write_text(json.dumps({
        "id": SPECIES_ID,
        "plant_life_form": "geophyte",
        "belowground_storage": ["corm"],
        "source": SOURCE,
        "source_basis": "Species description: obconic corm, 10–15 mm diameter.",
    }, indent=2), encoding="utf-8")
    print(json.dumps({"authored": SPECIES_ID, "belowground_storage": ["corm"]}, indent=2))


if __name__ == "__main__":
    main()
