import unittest

from simulations.person.person_simulation import PersonSimulation
from world.personality import (
    AUTHORED_SPREAD,
    AXES,
    BIRTH_SPREAD,
    HERITABILITY,
    POPULATION_SD,
    AxisValue,
    birth_baseline,
    inherited_birth,
    character,
    combine,
    exclusion,
    personality,
    position,
    trait_index,
)
from world.tag_rows import lookup_key


class FakeWorld:
    def __init__(self, *entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


def word(name, excludes=None, **axes):
    entity = {"id": f"tag_trait_{name.lower()}", "_dataset": "tags", "name": name, "tag_class": "personality",
              "big_five": axes}
    if excludes:
        entity["excludes_actions"] = excludes
    return entity


def world(*people):
    return FakeWorld(
        word("Kind", agreeableness=0.85),
        word("Merciful", agreeableness=0.85),
        word("Cruel", agreeableness=0.05),
        word("Obedient", openness=0.25, conscientiousness=0.8, agreeableness=0.75),
        word("Dutiful", conscientiousness=0.85),
        word("Pacifist", excludes=["Violence"], agreeableness=0.75),
        {"id": "tag_action_violence", "_dataset": "tags", "name": "Violence", "tag_class": "action"},
        {"id": "tag_action_torture", "_dataset": "tags", "name": "Torture", "tag_class": "action",
         "parents": ["tag_action_violence"],
         "trait_profiles": {"for": [["Cruel"], ["Obedient"]], "against": [["Kind"], ["Merciful"]]}},
        *people,
    )


def person(person_id, *words, **scores):
    return {"id": person_id, "_dataset": "people", "type": "person", "pretty_name": person_id,
            "personality_adjectives": list(words), **scores}


def born_average(model, *words):
    """A person born exactly at the population mean, with these words."""
    traits = trait_index(model)
    distribution = {}
    for axis in AXES:
        places = [position(traits[lookup_key(name)])[axis] for name in words
                  if axis in position(traits[lookup_key(name)])]
        mean, spread = combine(0.5, BIRTH_SPREAD, places)
        distribution[axis] = AxisValue(axis, 0.5, BIRTH_SPREAD, "birth", mean, spread, ())
    return distribution


class DistributionTests(unittest.TestCase):
    def test_words_move_the_birth_distribution_and_narrow_it(self):
        model = world()
        birth = personality(person("p1"), model)["conscientiousness"]
        one = personality(person("p1", "Dutiful"), model)["conscientiousness"]
        two = personality(person("p1", "Dutiful", "Obedient"), model)["conscientiousness"]

        self.assertEqual(("birth", BIRTH_SPREAD), (birth.baseline_source, birth.spread))
        self.assertAlmostEqual(birth_baseline("p1", "conscientiousness"), birth.value)
        self.assertEqual(combine(birth.value, BIRTH_SPREAD, [0.85]), (one.value, one.spread))
        self.assertLess(two.spread, one.spread)
        self.assertLess(one.spread, birth.spread)
        self.assertEqual((("Dutiful", 0.85), ("Obedient", 0.8)), two.words)

    def test_an_authored_score_is_a_surer_birth_estimate_words_move_less(self):
        model = world()
        authored = personality(person("p2", "Cruel", big_five_agreeableness=0.6), model)["agreeableness"]
        born = combine(0.6, BIRTH_SPREAD, [0.05])

        self.assertEqual(("authored", AUTHORED_SPREAD), (authored.baseline_source, authored.baseline_spread))
        self.assertGreater(authored.value, born[0])
        self.assertLess(authored.value, 0.6)

    def test_a_pacifist_excludes_torture_because_torture_is_violence(self):
        model = world()

        self.assertEqual("Pacifist excludes Violence", exclusion(person("p3", "Pacifist"), ["torture"], model))
        self.assertIsNone(exclusion(person("p4", "Kind"), ["torture"], model))


class TortureOrderTests(unittest.TestCase):
    """The worked example of docs/person_personality_concept_v001.md, for people born average."""

    def term(self, *words):
        model = world()
        return character(born_average(model, *words), ["torture"], model)[0]

    def test_the_same_order_lands_differently(self):
        self.assertAlmostEqual(0.0, self.term(), places=6)
        self.assertLess(self.term("Kind"), -30)
        self.assertLess(self.term("Kind", "Merciful"), self.term("Kind"))
        self.assertGreater(self.term("Cruel"), 40)
        self.assertGreater(self.term("Obedient"), 10)

    def test_a_person_sim_order_carries_the_character_term(self):
        model = world(person("person_subject", "Cruel"))
        sim = PersonSimulation(model, "person_subject", year=2400)
        task_id = sim.assign_external_task(
            "job", label="Torture the prisoner", issuer_label="Commander", duty_weight=0.9, action_tags=["torture"],
        )
        task = next(task for task in sim.external_task_allocations if task.get("id") == task_id)

        labels = [item["label"] for item in sim._score_task(task)["score_breakdown"]]
        self.assertTrue(any(label.startswith("Character: fits Cruel") for label in labels))

    def test_a_pacifist_refuses_the_order_outright(self):
        model = world(person("person_subject", "Pacifist"))
        sim = PersonSimulation(model, "person_subject", year=2400)
        task_id = sim.assign_external_task(
            "job", label="Torture the prisoner", issuer_label="Commander", duty_weight=0.9, action_tags=["torture"],
        )

        self.assertFalse(any(task.get("id") == task_id for task in sim.external_task_allocations))
        self.assertEqual(("refused", "Torture the prisoner"),
                         (sim.decision_history[0]["event"], sim.decision_history[0]["label"]))
        self.assertIn("Pacifist excludes Violence", sim.decision_history[0]["explanation"])


class InheritedBirthTests(unittest.TestCase):
    def test_each_known_parent_pulls_the_birth_mean_and_explains_some_spread(self):
        mean, spread = inherited_birth([])
        self.assertEqual((0.5, POPULATION_SD), (mean, spread))
        mean, spread = inherited_birth([(0.9, 0.0), (0.9, 0.0)])
        self.assertAlmostEqual(0.5 + HERITABILITY * 0.4, mean)
        self.assertAlmostEqual(POPULATION_SD * (1 - HERITABILITY ** 2 / 2) ** 0.5, spread)
        mean, _spread = inherited_birth([(0.9, 0.0)])
        self.assertAlmostEqual(0.5 + HERITABILITY / 2 * 0.4, mean)

    def test_a_child_of_kind_parents_is_drawn_around_them(self):
        mother = person("p_mother", "Kind", "Merciful")
        father = person("p_father", "Kind")
        family = {"id": "pop_family", "_dataset": "pops", "type": "pop"}
        child = {**person("p_child"), "parents": ["p_mother", "p_father", "pop_family"]}
        model = world(mother, father, family, child)
        parents = personality(child, model)["agreeableness"]
        alone = personality(person("p_child"), model)["agreeableness"]
        self.assertEqual("inherited", parents.baseline_source)
        self.assertEqual(("p_mother", "p_father"), tuple(name for name, _value in parents.parents))
        expected, spread = inherited_birth([(value.value, value.spread) for value in (
            personality(mother, model)["agreeableness"], personality(father, model)["agreeableness"])])
        self.assertAlmostEqual(birth_baseline("p_child", "agreeableness", expected, spread), parents.baseline)
        self.assertGreater(expected, 0.55)
        self.assertEqual("birth", alone.baseline_source)
        authored = personality({**child, "big_five_agreeableness": 0.3}, model)["agreeableness"]
        self.assertEqual(("authored", 0.3), (authored.baseline_source, authored.baseline))

    def test_a_loop_of_parents_ends(self):
        first = {**person("p_first"), "parents": ["p_second"]}
        second = {**person("p_second"), "parents": ["p_first"]}
        values = personality(first, world(first, second))
        self.assertEqual("inherited", values["openness"].baseline_source)


if __name__ == "__main__":
    unittest.main()
