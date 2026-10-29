"""Regular design candidates include terminal plants and fungi."""
from types import SimpleNamespace
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tools import plant_mechanics_regression_sample as sample


@pytest.fixture
def live_candidates(monkeypatch):
    entities = {
        "cladis_plants_plantae": {"type": "cladistics"},
        "cladis_fungi": {"type": "cladistics"},
        "plant": {"id": "plant", "type": "species", "parents": ["cladis_plants_plantae"],
                  "common_name": "Plant", "plant_growth_form": "tree"},
        "fungal_parent": {"id": "fungal_parent", "type": "species", "parents": ["cladis_fungi"]},
        "configured_fungus": {"id": "configured_fungus", "type": "species", "parents": ["fungal_parent"],
                              "common_name": "Configured fungus", "fungal_body_module_ref": "illust_saved"},
        "bare_fungus": {"id": "bare_fungus", "type": "species", "parents": ["cladis_fungi"]},
        "animal": {"id": "animal", "type": "species"},
    }
    monkeypatch.setattr(sample, "_load_live_entities", lambda: entities)
    world = SimpleNamespace(loader=SimpleNamespace(get=entities.get), resolved_species_entity=entities.get,
                            get_entity=entities.get)
    monkeypatch.setattr(sample, "WorldModel", lambda: world)
    return entities


@pytest.mark.parametrize("scope,count,expected", [
    ("all", 3, {"plant", "configured_fungus", "bare_fungus"}),
    ("plants", 1, {"plant"}),
    ("fungi", 2, {"configured_fungus", "bare_fungus"}),
])
def test_scope_selects_only_terminal_taxa_and_is_reproducible(live_candidates, scope, count, expected):
    manifest = sample.select_sample(303, count, scope)
    assert {entry["species_id"] for entry in manifest["entries"]} == expected
    assert sample.select_sample(303, count, scope) == manifest
    assert manifest["scope"] == scope
    for entry in manifest["entries"]:
        assert entry["kingdom"] == ("Plantae" if entry["species_id"] == "plant" else "Fungi")
        assert entry["maturity_fraction"] == 1.
        assert entry["age_days"] > 0
        assert entry["preview_stage"] == "representative_mature"
    assert manifest["preview_policy"] == "mature_leafy_or_flowering"


def test_fungal_authoring_is_counted_and_empty_fungi_are_flagged(live_candidates):
    entries = {entry["species_id"]: entry for entry in sample.select_sample(303, 3)["entries"]}
    assert entries["configured_fungus"]["authored_field_count"] == 1
    assert entries["configured_fungus"]["needs_authoring"] is False
    assert entries["bare_fungus"]["needs_authoring"] is True
    with pytest.raises(ValueError):
        sample.select_sample(303, 1, "animals")
    with pytest.raises(RuntimeError):
        sample.select_sample(303, 2, "plants")


def test_completed_exclusions_keep_terminal_membership_and_fixed_seed(live_candidates):
    manifest = sample.select_sample(303, 2, "all", ["configured_fungus"])
    assert {e["species_id"] for e in manifest["entries"]} == {"plant", "bare_fungus"}
    assert manifest["excluded_species_ids"] == ["configured_fungus"]
    assert sample.select_sample(303, 2, "all", ["configured_fungus"]) == manifest
    # Removing a terminal fungus must not promote its parent into the draw.
    assert "fungal_parent" not in {e["species_id"] for e in manifest["entries"]}
    with pytest.raises(RuntimeError):
        sample.select_sample(303, 3, "all", ["configured_fungus"])
    assert sample.select_sample(303, 3, "all", []) == sample.select_sample(303, 3, "all")


def test_render_reuses_frozen_age_even_when_maturity_trait_changes(live_candidates):
    manifest = sample.select_sample(303, 1, "plants")
    age = manifest["entries"][0]["age_days"]
    output = Path(__file__).resolve().parents[1]/"artifacts"/f".sample_test_{uuid4().hex}"
    output.mkdir()
    try:
        sample.render_sample(manifest, output, "before")
        live_candidates["plant"]["maturity_rate"] = "slow"
        sample.render_sample(manifest, output, "after")
        reports = [json.loads((output/f"{status}_metrics.json").read_text()) for status in ("before", "after")]
        assert reports[0]["cases"][0]["age_days"] == reports[1]["cases"][0]["age_days"] == round(age, 4)
        assert reports[0]["cases"][0]["life_state"]["phase"] != reports[1]["cases"][0]["life_state"]["phase"]
    finally:
        for status in ("before", "after"):
            folder = output/status
            if folder.exists():
                for file in folder.iterdir():
                    file.unlink()
                folder.rmdir()
        for file in output.iterdir():
            file.unlink()
        output.rmdir()
