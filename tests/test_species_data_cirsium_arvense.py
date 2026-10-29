"""Live researched card and editable asset transport for Creeping Thistle."""
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


ROOT = Path(__file__).resolve().parents[1]
SID = "spec_cirsium_arvense"


def test_live_identity_researched_transport_and_deliberately_unknown_timing():
    world = WorldModel()
    raw, resolved = world.loader.get(SID), world.resolved_species_entity(SID)
    datasets = PersistentOntologyStore(ROOT / "ontology/index0.owl").load_datasets()
    entities = {e["id"]: e for rows in datasets.values() if isinstance(rows, list)
                for e in rows if isinstance(e, dict) and e.get("id")}
    assert PlantCatalogue.build(entities).is_leaf_species(SID)
    assert raw["parents"] == ["cladis_plume_thistles_cirsium"]
    updates = {
        "plant_growth_form": "forb", "plant_woodiness": "herbaceous",
        "plant_growth_behaviour": "suckering_clonal",
        "leaf_attachment_pattern": "along_stem", "leaf_structure": "simple",
        "plant_reproductive_structure": "capitulum", "plant_flowering_position": "terminal",
        "reproductive_mode": "both", "belowground_storage": ["storage_root"],
        "maturity_rate": "other_unknown", "longevity_class": "other_unknown",
    }
    for field, value in updates.items():
        assert raw[field] == resolved[field] == value
    assert not raw.get("maturity_age") and not raw.get("longevity")
    bp = PlantBlueprint.from_species_entity(resolved, SID)
    assert bp.growth["growth_behaviour"] == "suckering_clonal"
    assert raw["max_root_depth"] == {"min_m": 1.8, "status": "reported_lower_bound_maximum_unknown"}
    assert bp.growth["root_profile"]["target_depth_m"] == 2.0
    assert bp.growth["root_profile"]["depth_source"] == "depth_class_default"
    assert bp.growth["leaf_structure"] == "simple"
    assert bp.growth["clonal_forb_shoot_grammar_version"] == 1


def test_saved_pixel_studio_assets_reopen_with_the_reviewed_design():
    import pygame
    from tools.author_plant_assets import PixelEditorHost, load_manifest, render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI

    pygame.init()
    world = WorldModel()
    raw = world.loader.get(SID)
    host = PixelEditorHost(world.loader)
    manifest = load_manifest(ROOT / "assets" / "plant_asset_specs" / f"{SID}.json")
    try:
        for module in manifest["modules"]:
            role = module["role"]
            illustration = world.loader.get(module["illustration_id"])
            assert raw[f"plant_{role}_module_ref"] == illustration["media_path"]
            assert illustration["parents"] == [SID]
            assert illustration["plant_asset_role"] == role
            assert (ROOT / illustration["pixel_document_path"]).is_file()
            saved = pygame.image.load(ROOT / illustration["media_path"])
            assert saved.get_size() == (75, 75)
            assert pygame.image.tobytes(saved, "RGBA") == pygame.image.tobytes(render_module(module), "RGBA")
            editor = PixelArtEditorUI(host)
            assert editor.open(illustration["id"])
            if role in {"leaf", "flower"}:
                assert raw["plant_module_anchors"][role]["depicted_size_m"] == module["depicted_size_m"]
    finally:
        pygame.quit()
