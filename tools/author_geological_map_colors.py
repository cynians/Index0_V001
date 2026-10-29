"""Author analytical geological-map colors into ontology material records.

This is a one-time ontology migration, not a runtime palette registry. World
generation reads the persisted ``geological_map_color`` property from the
ontology-backed startup cache.
"""

import colorsys
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = ROOT / "ontology" / "index0.owl"

# Hand-balanced Test 6 units. These are intentionally restrained printed-map
# colors and remain separate from physical visible reflectance.
AUDITED_COLORS = {
    "mat_andesite": [179, 112, 99],
    "mat_silica_sand": [213, 190, 128],
    "mat_syenite": [155, 132, 166],
    "mat_granodiorite": [102, 139, 166],
    "mat_diorite": [94, 146, 146],
    "mat_granite": [184, 132, 143],
    "mat_tonalite": [138, 168, 180],
    "mat_monzonite": [190, 147, 104],
    "mat_nepheline_syenite": [130, 116, 154],
    "mat_diabase": [83, 127, 109],
    "mat_basalt": [70, 94, 115],
}


def _derived_color(material_id):
    """Create a restrained stable swatch to persist, never use at runtime."""
    digest = hashlib.sha256(str(material_id).encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535.0
    saturation = 0.28 + digest[2] / 255.0 * 0.12
    lightness = 0.54 + digest[3] / 255.0 * 0.10
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return [round(red * 255), round(green * 255), round(blue * 255)]


def author():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    records = []
    for entity in datasets.get("materials") or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("material_system_role") != "natural_geologic_material":
            continue
        material_id = str(entity.get("id") or "")
        replacement = dict(entity)
        replacement["geological_map_color"] = list(
            AUDITED_COLORS.get(material_id) or _derived_color(material_id)
        )
        records.append(replacement)
    if not records:
        raise RuntimeError("No natural geological material records found")
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist geological-map colors")
    store.export_rdfxml(ONTOLOGY_PATH)
    return records


if __name__ == "__main__":
    changed = author()
    invalid = [
        item.get("id")
        for item in changed
        if not isinstance(item.get("geological_map_color"), list)
        or len(item["geological_map_color"]) != 3
    ]
    if invalid:
        raise RuntimeError(f"Invalid geological map colors: {invalid}")
    print(f"Authored geological-map colors for {len(changed)} ontology materials.")
