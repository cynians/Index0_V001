from copy import deepcopy

import pytest

from tools.author_plant_species import AuthoringError, author_species, prepare_update, validate_updates


def test_branched_rosette_recipe_rejects_out_of_bounds_and_incomplete_controls():
    profile = {"form": "branched_rosette", "internode_variation": .5,
               "axis_deflection": .18, "lateral_length_ratio": .26,
               "secondary_branch_probability": .8}
    validate_updates({"plant_shoot_profile": profile})
    for changes in ({"axis_deflection": 1.}, {"secondary_branch_probability": True}):
        with pytest.raises(AuthoringError):
            validate_updates({"plant_shoot_profile": {**profile, **changes}})
    with pytest.raises(AuthoringError):
        validate_updates({"plant_shoot_profile": {"form": "branched_rosette"}})


def datasets_for(species=None):
    plant = {
        "id": "cladis_plants_plantae",
        "_dataset": "cladistics",
        "type": "cladistics",
        "parents": [],
    }
    genus = {
        "id": "cladis_example",
        "_dataset": "cladistics",
        "type": "cladistics",
        "parents": ["cladis_plants_plantae"],
    }
    species = species or {
        "id": "spec_example",
        "_dataset": "species",
        "type": "species",
        "parents": ["cladis_example"],
        "plant_growth_form": "shrub",
        "inferred_field_sources": {"plant_growth_form": "cladis_example", "shade_tolerance": "cladis_example"},
        "inference_conflicts": {"plant_growth_form": ["tree", "shrub"]},
    }
    return {"cladistics": [plant, genus], "species": [species]}


class FakeStore:
    def __init__(self, datasets):
        self.datasets = deepcopy(datasets)
        self.persisted_fields = None
        self.ontology_path = "ontology/index0.owl"
        self.exported = False

    def load_datasets(self):
        return deepcopy(self.datasets)

    def persist_entity_fields(self, entity, field_names):
        self.persisted_fields = set(field_names)
        saved = self.datasets["species"][0]
        for field_name in field_names:
            saved[field_name] = deepcopy(entity.get(field_name))
        return True

    def export_rdfxml(self, output_path):
        assert output_path == self.ontology_path
        self.exported = True


def test_prepare_update_preserves_taxonomy_and_clears_inherited_provenance():
    entity, diff, changed_fields = prepare_update(
        datasets_for(),
        "spec_example",
        {
            "plant_growth_form": "tree",
            "plant_crown_openness": {
                "min": 0.2,
                "typical": 0.4,
                "max": 0.6,
                "status": "provisional_visual_calibration",
                "source": "https://example.test/photo",
            },
        },
    )

    assert entity["id"] == "spec_example"
    assert entity["parents"] == ["cladis_example"]
    assert entity["inferred_field_sources"] == {"shade_tolerance": "cladis_example"}
    assert entity["inference_conflicts"] == {}
    assert diff["plant_growth_form"] == {"before": "shrub", "after": "tree"}
    assert {"inferred_field_sources", "inference_conflicts"} <= changed_fields


def test_author_species_is_dry_run_by_default_then_point_persists_and_verifies():
    store = FakeStore(datasets_for())
    updates = {"plant_growth_form": "tree", "wiki_entry": "# Example"}

    dry_run = author_species(store, "spec_example", updates)
    assert dry_run["status"] == "dry_run"
    assert store.persisted_fields is None

    applied = author_species(store, "spec_example", updates, apply=True, export_checkpoint=True)
    assert applied["status"] == "persisted_and_reloaded"
    assert {"plant_growth_form", "wiki_entry"} <= store.persisted_fields
    assert store.exported is True


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"parents": ["cladis_other"]}, "Identity/taxonomy"),
        ({"plant_growth_form": "Tree"}, "exact live-schema value"),
        ({"plant_crown_openness": 0.5}, "schema type dict"),
        (
            {"plant_crown_openness": {"min": 0.5, "typical": 0.4, "max": 0.8}},
            "min <= typical <= max",
        ),
        ({"invented_trait": "value"}, "Unsupported species-card fields"),
    ],
)
def test_authoring_rejects_unsafe_or_invalid_updates(updates, message):
    with pytest.raises(AuthoringError, match=message):
        prepare_update(datasets_for(), "spec_example", updates)


def test_authoring_rejects_species_outside_plantae():
    datasets = datasets_for()
    datasets["species"].append(
        {
            "id": "spec_not_a_plant",
            "_dataset": "species",
            "type": "species",
            "parents": ["cladis_animals"],
        }
    )
    with pytest.raises(AuthoringError, match="not a species below"):
        prepare_update(datasets, "spec_not_a_plant", {"plant_growth_form": "tree"})
