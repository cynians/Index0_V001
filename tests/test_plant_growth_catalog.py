import unittest

from ui.card import EntityCard
from world.plant_growth_catalog import (
    PLANT_GROWTH_BEHAVIOUR_CHOICES,
    PLANT_GROWTH_BEHAVIOUR_FIELD,
    PLANT_GROWTH_FORM_CHOICES,
    PLANT_GROWTH_BEHAVIOR_HEADINGS,
    PLANT_LIFE_CYCLE_CHOICES,
    PLANT_LIFE_CYCLE_BEHAVIOR_HEADINGS,
    PLANT_LIFESPAN_FIELD,
    canonical_plant_growth_behaviour,
    canonical_plant_growth_form,
)
from world.plant_traits import (
    PLANT_LEGACY_FIELDS,
    PLANT_TRAIT_DROPDOWN_FIELDS,
    PLANT_TRAIT_FIELDS,
    plant_trait_choice_rows,
)
from world.schema_loader import SchemaLoader
from world.species_inheritance import refresh_species_inheritance, resolve_species_field


class PlantGrowthCatalogTests(unittest.TestCase):
    def test_catalog_has_nested_behaviour_path_and_consolidated_choices(self):
        self.assertEqual(
            ["Behaviour", "Plant Behaviour", "Plant Growth Behaviour"],
            [row["label"] for row in PLANT_GROWTH_BEHAVIOR_HEADINGS],
        )
        form_values = {choice["value"] for choice in PLANT_GROWTH_FORM_CHOICES}
        self.assertIn("tree", form_values)
        self.assertIn("forb", form_values)
        behaviour_values = {choice["value"] for choice in PLANT_GROWTH_BEHAVIOUR_CHOICES}
        self.assertIn("rosette_short_internode", behaviour_values)
        self.assertIn("rhizomatous_clonal", behaviour_values)
        self.assertNotIn("perennial_forb_rosette", form_values)

    def test_legacy_values_resolve_to_dropdown_choices(self):
        self.assertEqual("forb", canonical_plant_growth_form("perennial_forb_rosette"))
        self.assertEqual("shrub", canonical_plant_growth_form("deciduous_shrub"))
        self.assertEqual("rosette_short_internode", canonical_plant_growth_behaviour("rosette"))

    def test_life_cycle_uses_the_same_nested_behaviour_path(self):
        self.assertEqual(
            ["Behaviour", "Plant Behaviour", "Plant Life-Cycle Behaviour"],
            [row["label"] for row in PLANT_LIFE_CYCLE_BEHAVIOR_HEADINGS],
        )
        self.assertEqual(
            ["ephemeral", "annual", "biennial", "short_lived_perennial", "perennial"],
            [choice["value"] for choice in PLANT_LIFE_CYCLE_CHOICES],
        )

    def test_species_schema_uses_functional_traits_without_legacy_fields(self):
        schema = SchemaLoader(
            schema_entities=[
                {
                    "id": "schema_species",
                    "schema": "species",
                    "fields": {"plant_life_cycle": {"type": "string"}},
                }
            ]
        ).get_schema("species")
        fields = schema["fields"]
        self.assertIn("plant_lifespan", fields)
        self.assertIn("plant_growth_behaviour", fields)
        self.assertIn("leaf_arrangement", fields)
        self.assertIn("leaf_structure", fields)
        self.assertIn("root_architecture", fields)
        self.assertNotIn("plant_life_cycle", fields)
        self.assertNotIn("worldgen_suitability_profile", fields)
        self.assertTrue(PLANT_TRAIT_FIELDS.issubset(fields))
        self.assertTrue(PLANT_LEGACY_FIELDS.isdisjoint(fields))

    def test_categorical_trait_fields_have_nested_dropdown_rows(self):
        for field_key in PLANT_TRAIT_DROPDOWN_FIELDS:
            rows = plant_trait_choice_rows(field_key)
            self.assertGreaterEqual(len(rows), 4, field_key)
            self.assertEqual("heading", rows[0]["kind"], field_key)
            self.assertTrue(any(row.get("kind") != "heading" for row in rows), field_key)

        self.assertNotIn("mature_height", PLANT_TRAIT_DROPDOWN_FIELDS)
        self.assertNotIn("temperature_range", PLANT_TRAIT_DROPDOWN_FIELDS)
        self.assertNotIn("succulence", PLANT_TRAIT_DROPDOWN_FIELDS)

    def test_parent_inference_uses_authored_offspring_and_child_reads_fallback(self):
        parent = {"id": "clade_genus", "type": "cladistics", "_dataset": "cladistics"}
        child_a = {
            "id": "spec_a",
            "type": "species",
            "_dataset": "species",
            "parents": ["clade_genus"],
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "rosette_short_internode",
            "plant_lifespan": "perennial",
        }
        child_b = {
            "id": "spec_b",
            "type": "species",
            "_dataset": "species",
            "parents": ["clade_genus"],
        }

        class Loader:
            def __init__(self):
                self.entities = {item["id"]: item for item in (parent, child_a, child_b)}

        loader = Loader()
        changed = refresh_species_inheritance(loader)
        self.assertIn("clade_genus", changed)
        self.assertEqual("forb", parent["plant_growth_form"])
        self.assertEqual("rosette_short_internode", parent["plant_growth_behaviour"])
        self.assertEqual("perennial", parent["plant_lifespan"])
        self.assertEqual(
            "offspring_consensus",
            parent["inferred_field_sources"]["plant_growth_form"]["kind"],
        )
        resolved_growth = resolve_species_field(loader, child_b, "plant_growth_form")
        self.assertEqual("inferred", resolved_growth["provenance"])
        self.assertEqual("forb", resolved_growth["value"])

        resolved_behaviour = resolve_species_field(loader, child_b, "plant_growth_behaviour")
        self.assertEqual("inferred", resolved_behaviour["provenance"])
        self.assertEqual("rosette_short_internode", resolved_behaviour["value"])

        resolved = resolve_species_field(loader, child_b, "plant_lifespan")
        self.assertEqual("inferred", resolved["provenance"])
        self.assertEqual("perennial", resolved["value"])

    def test_parent_conflict_stays_unknown(self):
        parent = {"id": "clade_genus", "type": "cladistics", "_dataset": "cladistics"}
        child_a = {"id": "spec_a", "type": "species", "_dataset": "species", "parents": ["clade_genus"], "plant_lifespan": "annual"}
        child_b = {"id": "spec_b", "type": "species", "_dataset": "species", "parents": ["clade_genus"], "plant_lifespan": "perennial"}

        class Loader:
            entities = {item["id"]: item for item in (parent, child_a, child_b)}

        refresh_species_inheritance(Loader())
        self.assertNotIn("plant_lifespan", parent)
        self.assertIn("plant_lifespan", parent["inference_conflicts"])

    def test_species_growth_form_edit_uses_controlled_choice(self):
        card_view = EntityCard(
            {
                "id": "spec_test_plant",
                "common_name": "Test Plant",
                "type": "species",
                "_dataset": "species",
                "plant_growth_form": "forb",
            },
            dataset_name="species",
        )
        card = {
            "is_edit_mode": True,
            "active_edit_field": None,
            "draft_edit_buffers": {},
        }
        self.assertTrue(card_view.begin_edit_field(card, "plant_growth_form"))
        self.assertTrue(card["choice_picker_open"])
        rows = card_view.controlled_choice_rows("plant_growth_form")
        woody_index = next(
            index for index, row in enumerate(rows) if row.get("value") == "shrub"
        )
        self.assertTrue(card_view.select_controlled_choice(card, woody_index))
        self.assertTrue(card_view.commit_edit_field(card))
        self.assertEqual("shrub", card_view.entity["plant_growth_form"])

    def test_species_growth_behaviour_edit_uses_separate_controlled_choice(self):
        card_view = EntityCard(
            {
                "id": "spec_test_growth_behaviour",
                "common_name": "Test Plant",
                "type": "species",
                "_dataset": "species",
                "plant_growth_form": "forb",
                PLANT_GROWTH_BEHAVIOUR_FIELD: "iterative_indeterminate",
            },
            dataset_name="species",
        )
        card = {
            "is_edit_mode": True,
            "active_edit_field": None,
            "draft_edit_buffers": {},
        }
        self.assertTrue(card_view.begin_edit_field(card, PLANT_GROWTH_BEHAVIOUR_FIELD))
        self.assertTrue(card["choice_picker_open"])
        rhizome_index = next(
            index for index, row in enumerate(card_view.controlled_choice_rows(PLANT_GROWTH_BEHAVIOUR_FIELD))
            if row.get("value") == "rhizomatous_clonal"
        )
        self.assertTrue(card_view.select_controlled_choice(card, rhizome_index))
        self.assertTrue(card_view.commit_edit_field(card))
        self.assertEqual("rhizomatous_clonal", card_view.entity[PLANT_GROWTH_BEHAVIOUR_FIELD])

    def test_species_life_cycle_edit_uses_same_controlled_choice(self):
        card_view = EntityCard(
            {
                "id": "spec_test_life_cycle",
                "common_name": "Test Plant",
                "type": "species",
                "_dataset": "species",
                PLANT_LIFESPAN_FIELD: "perennial_woody",
            },
            dataset_name="species",
        )
        card = {
            "is_edit_mode": True,
            "active_edit_field": None,
            "draft_edit_buffers": {},
        }
        self.assertTrue(card_view.begin_edit_field(card, PLANT_LIFESPAN_FIELD))
        self.assertTrue(card["choice_picker_open"])
        annual_index = next(
            index for index, row in enumerate(card_view.controlled_choice_rows(PLANT_LIFESPAN_FIELD))
            if row.get("value") == "annual"
        )
        self.assertTrue(card_view.select_controlled_choice(card, annual_index))
        self.assertTrue(card_view.commit_edit_field(card))
        self.assertEqual("annual", card_view.entity[PLANT_LIFESPAN_FIELD])


if __name__ == "__main__":
    unittest.main()
