import math
import unittest
from pathlib import Path

import tools.author_mechanical_lithology as author
from simulations.world_gen import rock_scarps
from simulations.world_gen.mechanical_lithology import (
    derive_planetary_mechanical_lithology_model,
    mechanical_profile_for_material,
    terrain_response_factors,
)


class MechanicalLithologyTests(unittest.TestCase):
    def test_strong_crystalline_material_retains_more_relief_than_sand(self):
        granite = mechanical_profile_for_material({
            "mechanical_class": "massive_crystalline_rock",
            "mechanical_rock_profile": {
                "bulk_density_kg_m3": 2720,
                "erodibility_index": 0.23,
                "slope_resistance_index": 0.86,
                "elastic_strength_index": 0.82,
            },
        })
        sand = mechanical_profile_for_material({
            "mechanical_class": "unconsolidated_sediment",
            "mechanical_rock_profile": {
                "bulk_density_kg_m3": 2050,
                "erodibility_index": 0.93,
                "slope_resistance_index": 0.12,
                "elastic_strength_index": 0.10,
            },
        })
        strong = terrain_response_factors({"aggregate_profile": granite})
        weak = terrain_response_factors({"aggregate_profile": sand})
        self.assertGreater(strong["relief_retention"], weak["relief_retention"])
        self.assertGreater(strong["elastic_thickness_factor"], weak["elastic_thickness_factor"])
        self.assertLess(strong["erosion_susceptibility"], weak["erosion_susceptibility"])

    def test_planetary_prior_is_weighted_from_ontology_shaped_candidates(self):
        model = derive_planetary_mechanical_lithology_model({
            "likely_materials": [
                {
                    "material_id": "mat_granite",
                    "prevalence_score": 0.8,
                    "mechanical_class": "massive_crystalline_rock",
                    "mechanical_rock_profile": {
                        "bulk_density_kg_m3": 2720,
                        "erodibility_index": 0.23,
                        "slope_resistance_index": 0.86,
                        "elastic_strength_index": 0.82,
                    },
                },
                {
                    "material_id": "mat_silica_sand",
                    "prevalence_score": 0.2,
                    "mechanical_class": "unconsolidated_sediment",
                    "mechanical_rock_profile": {
                        "bulk_density_kg_m3": 2050,
                        "erodibility_index": 0.93,
                        "slope_resistance_index": 0.12,
                        "elastic_strength_index": 0.10,
                    },
                },
            ],
        })
        self.assertEqual("mechanical_lithology_prior_derived", model["status"])
        self.assertEqual("massive_crystalline_rock", model["dominant_mechanical_class"])
        self.assertAlmostEqual(0.8, model["class_weights"]["massive_crystalline_rock"])
        self.assertGreater(model["aggregate_profile"]["slope_resistance_index"], 0.6)


def _rock(material_id, mechanical_class="weak_sedimentary_rock"):
    return author.rock_profile(mechanical_class, author.ROCK_PROPERTIES[material_id])


def _face_deg(material_id):
    return math.degrees(math.atan(rock_scarps.face_gradient(_rock(material_id)["slope_resistance_index"])))


class RockSpecificStrengthTests(unittest.TestCase):
    """Rocks of one mechanical class differ as much as the classes do (tools/author_mechanical_lithology.py)."""

    def test_the_rating_adds_selbys_classes(self):
        # Strongest intact rock, widest joints, a rock that lasts; and the other end.
        self.assertAlmostEqual(author.rock_mass_strength_rating(400.0, 5.0, 1.0), 20.0 + 30.0 + 38.0)
        self.assertAlmostEqual(author.rock_mass_strength_rating(2.0, 0.01, 0.0), 5.0 + 8.0 + 14.0)
        # Between class middles the rating is read on a log scale.
        self.assertAlmostEqual(author.rock_mass_strength_rating(70.0, 0.55, 1.0), 14.0 + 21.0 + 38.0)
        self.assertGreater(author.rock_mass_strength_rating(100.0, 0.55, 1.0), author.rock_mass_strength_rating(70.0, 0.55, 1.0))

    def test_welding_decides_whether_a_pyroclastic_rock_holds_a_face(self):
        self.assertEqual(_face_deg("mat_pumice"), 0.0)
        self.assertEqual(_face_deg("mat_scoria"), 0.0)
        tuff, ignimbrite, welded = _face_deg("mat_tuff"), _face_deg("mat_ignimbrite"), _face_deg("mat_welded_ignimbrite")
        self.assertGreater(tuff, 40.0)
        self.assertGreater(ignimbrite, tuff + 5.0)
        self.assertGreater(welded, ignimbrite + 5.0)
        self.assertLess(welded, _face_deg("mat_diabase"))

    def test_sandstone_stands_over_shale(self):
        for strong in ("mat_sandstone", "mat_conglomerate", "mat_limestone", "mat_dolostone", "mat_greywacke"):
            self.assertGreater(_face_deg(strong), 60.0, strong)
        for weak in ("mat_shale", "mat_mudstone", "mat_claystone", "mat_lignite", "mat_rock_salt", "mat_gypsum_rock"):
            self.assertEqual(_face_deg(weak), 0.0, weak)
        # Ledge formers in between.
        for ledge in ("mat_siltstone", "mat_chalk", "mat_red_bed_sandstone"):
            self.assertGreater(_face_deg(ledge), 39.9, ledge)
            self.assertLess(_face_deg(ledge), 55.0, ledge)

    def test_every_rock_gets_indices_in_range_from_its_three_figures(self):
        self.assertEqual(len(author.ROCK_PROPERTIES), 79)
        for material_id in author.ROCK_PROPERTIES:
            profile = _rock(material_id)
            for name in ("erodibility_index", "slope_resistance_index", "fracture_density_index", "elastic_strength_index", "permeability_index"):
                self.assertGreaterEqual(profile[name], 0.0, (material_id, name))
                self.assertLessEqual(profile[name], 1.0, (material_id, name))
            self.assertGreaterEqual(profile["rock_mass_strength_rating"], 27.0, material_id)
            self.assertLessEqual(profile["rock_mass_strength_rating"], 88.0, material_id)
            self.assertAlmostEqual(profile["tensile_strength_mpa"], 0.1 * profile["uniaxial_compressive_strength_mpa"], places=2)
            self.assertEqual(profile["profile_basis"], "rock_specific_strength_v1")
        # Stronger, wider-jointed, more durable rock wears more slowly.
        erodibility = lambda material_id: _rock(material_id)["erodibility_index"]  # noqa: E731
        self.assertLess(erodibility("mat_quartzite"), erodibility("mat_sandstone"))
        self.assertLess(erodibility("mat_sandstone"), erodibility("mat_shale"))
        self.assertLess(erodibility("mat_welded_ignimbrite"), erodibility("mat_tuff"))
        self.assertGreater(erodibility("mat_pumice"), 0.9)

    def test_the_typical_rock_of_a_class_keeps_about_the_class_values(self):
        for material_id, mechanical_class in (
            ("mat_granite", "massive_crystalline_rock"), ("mat_basalt", "jointed_volcanic_rock"),
            ("mat_limestone", "strong_carbonate_rock"), ("mat_shale", "weak_sedimentary_rock"),
        ):
            rock = author.rock_profile(mechanical_class, author.ROCK_PROPERTIES[material_id])
            typical = author.PROFILES[mechanical_class]
            self.assertAlmostEqual(rock["slope_resistance_index"], typical["slope_resistance_index"], delta=0.03, msg=material_id)
            self.assertEqual(rock["fabric"], typical["fabric"])
            self.assertEqual(rock["friction_angle_deg"], typical["friction_angle_deg"])

    def test_other_materials_keep_their_class_profile(self):
        sand = {"id": "mat_silica_sand", "material_subclass": "sediment", "formation_category": "littoral_sediment"}
        self.assertEqual(author.mechanical_profile(sand), ("unconsolidated_sediment", author.PROFILES["unconsolidated_sediment"]))
        halite = {"id": "mat_halite", "material_subclass": "mineral", "formation_category": "evaporite_basin"}
        self.assertEqual(author.mechanical_profile(halite)[1], author.PROFILES["weak_evaporite_rock"])
        sandstone = {"id": "mat_sandstone", "material_subclass": "rock", "formation_category": "clastic_sedimentary_basin"}
        mechanical_class, profile = author.mechanical_profile(sandstone)
        self.assertEqual(mechanical_class, "weak_sedimentary_rock")
        self.assertEqual(profile["uniaxial_compressive_strength_mpa"], 60.0)

    def test_the_ontology_carries_what_the_tool_authors(self):
        from world.persistent_ontology_store import PersistentOntologyStore

        materials = PersistentOntologyStore(
            Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
        ).load_datasets().get("materials") or []
        rocks = {item["id"]: item for item in materials if isinstance(item, dict) and item.get("id") in author.ROCK_PROPERTIES}
        self.assertEqual(len(rocks), len(author.ROCK_PROPERTIES))
        for material_id, entity in rocks.items():
            mechanical_class, profile = author.mechanical_profile(entity)
            self.assertEqual(entity.get("mechanical_class"), mechanical_class, material_id)
            self.assertEqual(dict(entity.get("mechanical_rock_profile") or {}), profile, material_id)


if __name__ == "__main__":
    unittest.main()
