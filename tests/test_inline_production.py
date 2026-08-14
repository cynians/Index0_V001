import unittest
from types import SimpleNamespace

import pygame

from ui.card import EntityCard
from world.requirement_resolver import RequirementResolver


class InlineProductionTests(unittest.TestCase):
    def setUp(self):
        self.producer = {
            "id": "producer_orbital_works",
            "type": "producer",
            "_dataset": "producers",
            "pretty_name": "Orbital Works",
        }
        self.vehicle = {
            "id": "veh_station_tender",
            "type": "vehicle",
            "_dataset": "vehicles",
            "pretty_name": "Station Tender",
        }
        self.site = {
            "id": "loc_lunar_yard",
            "type": "location",
            "_dataset": "locations",
            "location_class": "site",
        }
        self.job = {
            "id": "job_subsistence_farmer",
            "type": "job",
            "_dataset": "jobs",
            "pretty_name": "Subsistence Farmer",
            "unlock_technologies": ["tech_hydroponics"],
            "unlock_cultural_aspects": ["aspect_colony_self_reliance"],
            "unlock_production_outputs": [self.vehicle["id"]],
        }
        self.technology = {
            "id": "tech_hydroponics",
            "type": "technology",
            "_dataset": "technologies",
            "pretty_name": "Hydroponics",
        }
        self.cultural_aspect = {
            "id": "aspect_colony_self_reliance",
            "type": "cultural_aspect",
            "_dataset": "cultural_aspects",
            "pretty_name": "Colony Self-Reliance",
        }
        self.employment = {
            "id": "employment_colony_farmers",
            "type": "employment",
            "_dataset": "employments",
            "pretty_name": "Colony Farmers",
            "job": self.job["id"],
            "employed_people": ["person_colony_farmer"],
        }
        self.person = {
            "id": "person_colony_farmer",
            "type": "person",
            "_dataset": "people",
            "pretty_name": "Colony Farmer",
        }
        self.entities = {
            self.producer["id"]: self.producer,
            self.vehicle["id"]: self.vehicle,
            self.site["id"]: self.site,
            self.job["id"]: self.job,
            self.technology["id"]: self.technology,
            self.cultural_aspect["id"]: self.cultural_aspect,
            self.employment["id"]: self.employment,
            self.person["id"]: self.person,
        }
        self.loader = SimpleNamespace(
            entities=self.entities,
            datasets={
                "producers": [self.producer],
                "vehicles": [self.vehicle],
                "locations": [self.site],
            },
        )
        self.world = SimpleNamespace(
            loader=self.loader,
            get_entity=lambda entity_id: self.entities.get(entity_id),
        )
        self.card = EntityCard(self.producer, "producers", self.world)

    def test_adding_product_stores_inline_line_and_direct_relationships(self):
        state = {}

        self.assertTrue(self.card._add_production_line(state, self.vehicle["id"]))

        self.assertNotIn("production", self.loader.datasets)
        self.assertEqual(self.vehicle["id"], self.producer["production_lines"][0]["product_id"])
        self.assertEqual([self.vehicle["id"]], self.producer["produced_vehicles"])
        self.assertEqual([self.producer["id"]], self.vehicle["produced_by"])
        self.assertCountEqual(
            [self.producer["id"], self.vehicle["id"]],
            state["production_related_entity_update_ids"],
        )

    def test_legacy_card_is_migrated_without_losing_line_details(self):
        legacy = {
            "id": "prodline_old",
            "type": "production",
            "_dataset": "production",
            "produced_by": [self.producer["id"]],
            "output_vehicles": [self.vehicle["id"]],
            "production_location": self.site["id"],
            "production_rate_value": "12",
            "production_rate_period": "year",
            "start_year": "2300",
            "end_year": "2350",
        }
        self.entities[legacy["id"]] = legacy
        self.loader.datasets["production"] = [legacy]
        state = {}

        self.assertTrue(self.card._update_production_line(state, 0, rate_value="18"))

        self.assertEqual([legacy["id"]], state["production_removed_entity_ids"])
        self.assertEqual(
            {
                "line_id": legacy["id"],
                "product_id": self.vehicle["id"],
                "location_id": self.site["id"],
                "rate_value": "18",
                "rate_period": "year",
                "start_year": "2300",
                "end_year": "2350",
                "job_ids": [],
                "employed_technology_ids": [],
                "employment_ids": [],
            },
            self.producer["production_lines"][0],
        )
        self.assertEqual([self.vehicle["id"]], self.producer["produced_vehicles"])
        self.assertEqual([self.producer["id"]], self.vehicle["produced_by"])

    def test_removing_last_line_unlinks_producer_and_product(self):
        self.producer["production_lines"] = [
            {
                "product_id": self.vehicle["id"],
                "location_id": "",
                "rate_value": "4",
                "rate_period": "month",
                "start_year": "",
                "end_year": "",
            }
        ]
        self.producer["produced_vehicles"] = [self.vehicle["id"]]
        self.vehicle["produced_by"] = [self.producer["id"]]
        state = {}

        self.assertTrue(self.card._remove_production_line(state, 0))

        self.assertEqual([], self.producer["production_lines"])
        self.assertEqual([], self.producer["produced_vehicles"])
        self.assertEqual([], self.vehicle["produced_by"])

    def test_production_line_links_job_workflow_and_workforce(self):
        state = {}
        self.card._add_production_line(state, self.vehicle["id"])

        self.assertTrue(self.card._add_production_line_relation(state, 0, "job_ids", self.job["id"]))
        self.assertTrue(self.card._add_production_line_relation(state, 0, "employed_technology_ids", self.technology["id"]))
        self.assertTrue(self.card._add_production_line_relation(state, 0, "employment_ids", self.employment["id"]))

        line = self.producer["production_lines"][0]
        self.assertEqual([self.job["id"]], line["job_ids"])
        self.assertEqual([self.technology["id"]], line["employed_technology_ids"])
        self.assertEqual([self.employment["id"]], line["employment_ids"])
        self.assertEqual([self.job["id"]], self.producer["production_jobs"])
        self.assertEqual([self.technology["id"]], self.producer["production_technologies"])
        self.assertEqual([self.employment["id"]], self.producer["employment_assignments"])
        self.assertEqual([self.producer["id"]], self.job["associated_producers"])
        self.assertEqual([self.producer["id"]], self.employment["employers"])
        self.assertEqual(line["line_id"], self.employment["production_line_id"])
        self.assertEqual([self.employment["id"]], self.person["employment_assignments"])

    def test_job_doctrine_unlocks_from_production_context_not_era(self):
        self.producer["produced_vehicles"] = [self.vehicle["id"]]
        self.producer["associated_cultural_aspects"] = [self.cultural_aspect["id"]]
        line = {
            "product_id": self.vehicle["id"],
            "location_id": self.site["id"],
            "job_ids": [self.job["id"]],
            "employed_technology_ids": [self.technology["id"]],
        }

        report = RequirementResolver(self.world).job_availability_report(
            self.job, self.producer, self.site, line
        )

        self.assertTrue(report["complete"])
        self.assertCountEqual(["technology", "culture", "production"], [check["kind"] for check in report["checks"]])

        line["employed_technology_ids"] = []
        report = RequirementResolver(self.world).job_availability_report(
            self.job, self.producer, self.site, line
        )
        self.assertFalse(report["complete"])
        self.assertFalse(next(check for check in report["checks"] if check["kind"] == "technology")["satisfied"])


if __name__ == "__main__":
    unittest.main()
