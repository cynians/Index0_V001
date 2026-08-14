import unittest

from simulations.world_gen.material_formation import (
    FORMATION_CATEGORIES,
    formation_contract,
)
from simulations.world_gen.natural_materials import (
    configure_material_catalog,
    natural_material_entries,
)


from simulations.world_gen.regional_materials import derive_regional_material_model
from world.persistent_ontology_store import PersistentOntologyStore
from pathlib import Path


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


def _regional_inputs(material_id, name, subclass, profile_id, *, tags, level):
    candidate = {
        "material_id": material_id,
        "name": name,
        "material_subclass": subclass,
        "confidence": 0.98,
        "relative_abundance": 0.75,
        "prevalence_score": 0.735,
        "minimum_map_detail_level": level,
        "surface_affinity_profile": {"profile_id": profile_id},
    }
    natural = {"planet_tags": list(tags), "likely_materials": [candidate]}
    heightmap = {
        "sea_level_m": -100.0,
        "min_elevation_m": 0.0,
        "max_elevation_m": 1000.0,
        "region_width_m": 1_000_000.0,
        "region_height_m": 600_000.0,
        "sample_grid": {
            "rows": [[350.0 + x * 20.0 for x in range(5)] for _y in range(5)]
        },
    }
    climate = {
        "climate_grid": {
            "temperature_rows_k": [[296.0] * 5 for _y in range(5)],
            "annual_precipitation_rows_mm": [[1600.0] * 5 for _y in range(5)],
            "annual_runoff_rows_mm": [[700.0] * 5 for _y in range(5)],
        }
    }
    evolution = {
        "process_grid": {
            "chemical_weathering_rows": [[0.7] * 5 for _y in range(5)],
            "sediment_deposition_rows": [[0.5] * 5 for _y in range(5)],
            "erosion_potential_rows": [[0.3] * 5 for _y in range(5)],
            "relative_surface_age_rows": [[0.8] * 5 for _y in range(5)],
        }
    }
    return natural, heightmap, climate, evolution


class MaterialFormationSystemTests(unittest.TestCase):
    def test_every_geologic_material_card_has_a_resolved_physical_niche(self):
        entries = [
            entry
            for entry in natural_material_entries()
            if entry.get("material_system_role") == "natural_geologic_material"
        ]
        self.assertEqual(210, len(entries))
        for entry in entries:
            self.assertIn(entry["formation_category"], FORMATION_CATEGORIES)
            self.assertIn(
                entry["spatial_representation"],
                {
                    "bedrock_unit",
                    "surface_cover",
                    "constituent_abundance",
                    "bounded_deposit",
                },
                entry["id"],
            )
            self.assertEqual("resolved", entry["formation_contract_status"])

    def test_future_card_can_declare_formation_category_directly(self):
        contract = formation_contract(
            "mat_future_test",
            "rock",
            explicit_category="contact_metasomatic_skarn",
        )
        self.assertEqual("contact_metasomatic_skarn", contract["category_id"])
        self.assertEqual("bounded_deposit", contract["spatial_representation"])
        self.assertIn(
            "carbonate_sedimentary_basin",
            contract["host_formation_categories"],
        )

    def test_rock_forming_mineral_is_abundance_not_pure_deposit(self):
        inputs = _regional_inputs(
            "mat_pyroxene",
            "Pyroxene",
            "mineral",
            "mafic_bedrock",
            tags={"mafic_crust", "basaltic_surface", "volcanic_surface"},
            level=1,
        )
        model = derive_regional_material_model(
            *inputs,
            map_seed="pyroxene-constituent",
            detail_level=1,
        )
        self.assertEqual(1, model["occurrence_count"])
        occurrence = model["occurrences"][0]
        self.assertEqual(
            "constituent_abundance",
            occurrence["spatial_representation"],
        )
        self.assertEqual(
            "mineral_constituent_abundance",
            occurrence["occurrence_role"],
        )
        self.assertIsNone(occurrence["deposit_body"])
        self.assertFalse(occurrence["abundance_field"]["bounded_body"])

    def test_obsidian_requires_current_volcanic_process(self):
        inputs = _regional_inputs(
            "mat_obsidian",
            "Obsidian",
            "rock",
            "felsic_volcanic",
            tags={"felsic_crust", "silica_rich_crust", "volcanic_surface"},
            level=2,
        )
        model = derive_regional_material_model(
            *inputs,
            map_seed="inactive-obsidian",
            detail_level=2,
        )
        self.assertEqual(0, model["occurrence_count"])
        self.assertEqual(0.0, model["candidate_evaluations"][0]["best_score"])


if __name__ == "__main__":
    unittest.main()
