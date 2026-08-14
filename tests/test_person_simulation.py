import unittest

from simulations.person.person_simulation import PersonSimulation


class _WorldStub:
    def __init__(self, entities=None):
        self.entities = dict(entities or {})

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class PersonSimulationTests(unittest.TestCase):
    def setUp(self):
        self.person = {
            "id": "person_test",
            "type": "person",
            "pretty_name": "Test Person",
        }
        self.world = _WorldStub({self.person["id"]: self.person})
        self.sim = PersonSimulation(self.world, self.person["id"], year=2400)

    def test_starts_on_four_point_map_with_autonomous_queue(self):
        self.assertEqual("autonomous", self.sim.control_mode)
        self.assertEqual({"bed", "food", "job", "target"}, set(self.sim.test_points))
        self.assertGreaterEqual(len(self.sim.task_queue), 2)
        self.assertEqual("food", self.sim.task_queue[0]["point_id"])

    def test_player_task_preempts_autonomous_work(self):
        self.sim._begin_next_queued_task()
        self.assertEqual("autonomous", self.sim.active_task["source"])

        self.assertTrue(self.sim.assign_player_task("target"))

        self.assertIsNone(self.sim.active_task)
        self.assertEqual("player", self.sim.task_queue[0]["source"])
        self.assertEqual("target", self.sim.task_queue[0]["point_id"])

    def test_direct_control_moves_to_clicked_destination(self):
        self.assertTrue(self.sim.set_control_mode("direct"))
        self.assertTrue(self.sim.command_direct_move((6.0, 0.0)))

        self.sim._update_runtime(1.0)
        self.assertAlmostEqual(3.2, self.sim.position[0], places=4)
        self.sim._update_runtime(1.0)

        self.assertEqual([6.0, 0.0], self.sim.position)
        self.assertIsNone(self.sim.direct_target)

    def test_direct_point_order_moves_and_uses_point(self):
        self.sim.set_control_mode("direct")
        self.sim.needs["food"] = 10.0
        food_position = self.sim.test_points["food"]["position"]
        self.sim.position = [food_position[0], food_position[1]]

        self.assertTrue(self.sim.command_direct_move(food_position, point_id="food"))
        self.sim._update_runtime(1.0)
        self.sim._update_runtime(3.0)

        self.assertIsNone(self.sim.active_task)
        self.assertGreater(self.sim.needs["food"], 60.0)

    def test_job_point_uses_assigned_job_name(self):
        employment = {
            "id": "employment_test",
            "type": "employment",
            "job": "job_farmer",
        }
        job = {
            "id": "job_farmer",
            "type": "job",
            "pretty_name": "Subsistence Farmer",
        }
        self.person["employment_assignments"] = [employment["id"]]
        self.world.entities.update({employment["id"]: employment, job["id"]: job})

        sim = PersonSimulation(self.world, self.person["id"], year=2400)

        self.assertEqual("Subsistence Farmer", sim.test_points["job"]["label"])

    def test_needs_panel_combines_live_needs_with_authored_wishes_and_goals(self):
        self.person["wishes"] = ["Share a meal"]
        self.person["goals"] = ["Build a secure home"]

        model = self.sim.get_needs_panel_model()

        self.assertEqual(5, len(model["tiers"]))
        self.assertEqual("physiological", model["tiers"][0]["id"])
        self.assertEqual("Share a meal", model["wishes"][0]["label"])
        self.assertEqual("person record", model["wishes"][0]["source"])
        self.assertEqual("Build a secure home", model["goals"][0]["label"])

    def test_personality_panel_reads_authored_big_five_and_marks_missing_axes(self):
        self.person.update({
            "big_five_openness": 72,
            "big_five_conscientiousness": 0.81,
            "big_five_extraversion": 0.34,
            "big_five_agreeableness": 0.63,
        })

        model = self.sim.get_personality_panel_model()
        axes = {axis["id"]: axis for axis in model["axes"]}

        self.assertAlmostEqual(0.72, axes["openness"]["value"])
        self.assertTrue(axes["conscientiousness"]["authored"])
        self.assertFalse(axes["neuroticism"]["authored"])
        self.assertEqual(0.5, axes["neuroticism"]["value"])
        self.assertFalse(model["all_authored"])


if __name__ == "__main__":
    unittest.main()
