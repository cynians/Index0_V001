"""Unit tests for PlantCatalogue's leaf-descendant computation."""

from world.plant_catalogue import PLANTAE_ID, PlantCatalogue


def _entity(entity_id, entity_type, parents=None):
    return {"id": entity_id, "type": entity_type, "parents": parents or []}


def _synthetic_entities():
    return {
        PLANTAE_ID: _entity(PLANTAE_ID, "cladistics"),
        "cladis_subclade": _entity("cladis_subclade", "cladistics", [PLANTAE_ID]),
        "spec_leaf_one": _entity("spec_leaf_one", "species", ["cladis_subclade"]),
        "spec_leaf_two": _entity("spec_leaf_two", "species", ["cladis_subclade"]),
        # A species that unusually has a recorded taxonomic child of its own
        # is not a terminal/leaf descendant.
        "spec_with_child": _entity("spec_with_child", "species", ["cladis_subclade"]),
        "spec_child_of_species": _entity("spec_child_of_species", "species", ["spec_with_child"]),
        # Not reachable from Plantae at all; must not appear anywhere.
        "spec_unrelated": _entity("spec_unrelated", "species", ["cladis_other_root"]),
    }


def test_leaf_species_ids_excludes_species_with_taxonomic_children():
    catalogue = PlantCatalogue.build(_synthetic_entities())

    assert catalogue.is_species("spec_leaf_one")
    assert catalogue.is_species("spec_with_child")
    assert catalogue.is_species("spec_child_of_species")

    assert catalogue.is_leaf_species("spec_leaf_one")
    assert catalogue.is_leaf_species("spec_leaf_two")
    assert catalogue.is_leaf_species("spec_child_of_species")
    assert not catalogue.is_leaf_species("spec_with_child")
    assert not catalogue.is_leaf_species("cladis_subclade")


def test_leaf_species_ids_excludes_entities_unreachable_from_plantae():
    catalogue = PlantCatalogue.build(_synthetic_entities())

    assert "spec_unrelated" not in catalogue.entity_ids
    assert "spec_unrelated" not in catalogue.leaf_species_ids


def test_leaf_species_ids_is_subset_of_species_ids():
    catalogue = PlantCatalogue.build(_synthetic_entities())

    assert catalogue.leaf_species_ids <= catalogue.species_ids
