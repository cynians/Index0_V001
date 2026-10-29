import unittest
from types import SimpleNamespace

import pygame

from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.person import person_editor as editor
from simulations.person.person_renderer import PersonRenderer
from simulations.person.person_simulation import PersonSimulation
from simulations.person.person_genetics import create_person_dna, decode_person_dna, inherit_person_dna, set_body_trait
from world.personality import AXES, birth_baseline, personality
from world.place_tree import PlaceTree


PLACES = [
    {"id": "system_sol", "type": "location", "location_class": "star_system", "pretty_name": "Sol System"},
    {"id": "body_sol", "type": "location", "location_class": "star", "pretty_name": "Sun", "parent_location": "system_sol"},
    {"id": "planet_earth", "type": "location", "location_class": "planet", "pretty_name": "Earth", "parent_location": "body_sol"},
    {"id": "geo_germany", "type": "location", "location_class": "country", "pretty_name": "Germany", "parent_location": "planet_earth"},
    {"id": "city_berlin", "type": "location", "location_class": "city", "pretty_name": "Berlin",
     "parent_location": "geo_germany", "start_year": 1237},
    {"id": "unit_granite", "type": "location", "location_class": "geologic_unit", "pretty_name": "Granite",
     "parent_location": "geo_germany"},
    {"id": "loc_barracks", "type": "location", "location_class": "building", "pretty_name": "Barracks",
     "parent_location": "city_berlin"},
]
WORDS = [
    {"id": "tag_trait_kind", "type": "tag", "tag_class": "personality", "pretty_name": "Kind",
     "big_five": {"agreeableness": 0.82}},
    {"id": "tag_trait_pacifist", "type": "tag", "tag_class": "personality", "pretty_name": "Pacifist",
     "big_five": {"agreeableness": 0.8}, "excludes_actions": ["Violence"]},
]
COLLECTIONS = [
    {"id": "coll_lore", "type": "collection", "collection_class": "shared_knowledge", "pretty_name": "Camp Lore",
     "includes": ["loc_barracks"]},
    {"id": "coll_knowledge_ada", "type": "collection", "collection_class": "personal_knowledge",
     "pretty_name": "Knowledge of Ada", "includes": ["coll_lore", "loc_barracks"]},
    {"id": "coll_training", "type": "collection", "collection_class": "shared_knowledge", "pretty_name": "Cook Training",
     "includes": []},
]
JOBS = [{"id": "job_cook", "type": "job", "pretty_name": "Cook"}]


class _Loader:
    def __init__(self, world):
        self.world = world
        self.entities = world.entities
        self.whole = []
        self.fields = []

    def persist_entity(self, entity):
        self.whole.append(entity)
        self.world.add(entity.get("_dataset") or "entries", entity)
        return True

    def persist_entity_fields(self, entity, fields):
        self.fields.append((entity["id"], set(fields)))
        return True


class _World:
    def __init__(self, people=()):
        self.datasets = {"locations": [], "tags": [], "collections": [], "jobs": [], "people": []}
        self.entities = {}
        for dataset, rows in (("locations", PLACES), ("tags", WORDS), ("collections", COLLECTIONS),
                              ("jobs", JOBS), ("people", people)):
            for row in rows:
                self.add(dataset, dict(row))
        self.loader = _Loader(self)
        self.repository_revision = 0

    def add(self, dataset, entity):
        entity["_dataset"] = dataset
        rows = self.datasets.setdefault(dataset, [])
        rows[:] = [row for row in rows if row.get("id") != entity["id"]] + [entity]
        self.entities[entity["id"]] = entity

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, name):
        return self.datasets.get(name, [])

    def mark_repository_changed(self):
        self.repository_revision += 1


def _key(sim, text=None, key=None):
    sim.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": key or 0, "unicode": text or ""}))


def _click(sim, **hitbox):
    sim._editor_click(hitbox)


class PlaceTreeTests(unittest.TestCase):
    def test_places_skip_stars_and_rock_units_and_know_their_years(self):
        tree = PlaceTree(_World())
        self.assertEqual("system_sol", tree.parent("planet_earth"))
        self.assertNotIn("unit_granite", tree.places)
        self.assertEqual(["system_sol", "planet_earth", "geo_germany", "city_berlin"], tree.chain("city_berlin"))
        self.assertEqual(["city_berlin"], tree.search("berl"))
        self.assertFalse(tree.existed("city_berlin", 1100))
        self.assertTrue(tree.existed("city_berlin", 2370))
        self.assertIsNone(tree.existed("geo_germany", 2370))
        self.assertEqual("not founded until 1237", tree.existence_text("city_berlin", 1100))


class NewPersonTests(unittest.TestCase):
    def setUp(self):
        self.world = _World()
        self.sim = PersonSimulation(self.world, None, year=2400, initial_view="editor")
        self.sim.start_new_person("city_berlin", seed="seed-a")
        self.state = self.sim.person_editor

    def test_a_new_person_is_born_where_and_when_chosen_and_named_by_typing(self):
        self.assertEqual(2370, self.state["draft"]["start_year"])
        self.assertEqual("city_berlin", self.state["draft"]["birth_location"])
        _click(self.sim, kind="focus", input="name")
        for char in "Ada Lind":
            _key(self.sim, char)
        _key(self.sim, key=pygame.K_BACKSPACE)
        _key(self.sim, "d")
        self.assertEqual("Ada Lind", self.state["draft"]["pretty_name"])
        self.assertEqual("person_ada_lind", self.sim.person_entity_id)
        self.assertEqual("Ada Lind", self.sim.get_person_name())
        _click(self.sim, kind="year_delta", delta=-10)
        self.assertEqual(2360, self.state["draft"]["start_year"])
        _click(self.sim, kind="place_choose", field="birth_location", place_id="geo_germany")
        self.assertEqual("geo_germany", self.state["draft"]["birth_location"])
        self.assertEqual("geo_germany", editor.browsed_place(self.state, "birth_location", self.world))

    def test_save_writes_the_whole_new_person_and_their_knowledge_collection(self):
        self.assertFalse(self.sim.save_person_editor())
        editor.set_name(self.state, "Ada Lind", self.world)
        _click(self.sim, kind="word", word="Kind")
        _click(self.sim, kind="sex", sex="female")
        _click(self.sim, kind="place_choose", field="residence", place_id="loc_barracks")
        _click(self.sim, kind="job", job_id="job_cook")
        _click(self.sim, kind="knowledge", collection_id="coll_lore")
        self.assertFalse(self.sim.set_person_view("simulation"))
        self.assertTrue(self.sim.save_person_editor())
        collection, person = self.world.loader.whole
        self.assertEqual(["coll_lore"], collection["includes"])
        self.assertEqual("personal_knowledge", collection["collection_class"])
        self.assertEqual("person_ada_lind", person["id"])
        self.assertEqual(collection["id"], person["knowledge_collection"])
        for field, value in (("start_year", 2370), ("birth_location", "city_berlin"), ("birth_seed", "seed-a"),
                             ("sex", "female"), ("residence", "loc_barracks"), ("is_employed_as", "job_cook"),
                             ("personality_adjectives", ["Kind"])):
            self.assertEqual(value, person[field])
        self.assertTrue(person["genetic_dna"].startswith("I0DNA1_"))
        self.assertIs(self.world.get_entity("person_ada_lind"), person)
        self.assertFalse(self.state["dirty"])
        _click(self.sim, kind="simulation")
        self.assertEqual({"id": "knowledge_launch_mode", "entity_id": "person_ada_lind", "launch_mode": "person"},
                         self.sim.consume_pending_navigation_action())

    def test_birth_seed_draws_the_baseline_and_hand_set_axes_stay(self):
        draft = self.state["draft"]
        self.assertAlmostEqual(birth_baseline("seed-a", "openness"), personality(draft)["openness"].baseline)
        editor.adjust_baseline(self.state, "agreeableness", 0.05)
        set_agreeableness = draft["big_five_agreeableness"]
        before = {axis: personality(draft)[axis].baseline for axis in AXES}
        editor.reroll_birth(self.state, seed="seed-b")
        after = personality(draft)
        self.assertEqual(set_agreeableness, after["agreeableness"].baseline)
        self.assertEqual("authored", after["agreeableness"].baseline_source)
        self.assertNotEqual(before["openness"], after["openness"].baseline)
        editor.reset_baseline(self.state, "agreeableness")
        self.assertEqual("birth", personality(draft)["agreeableness"].baseline_source)

    def test_words_list_by_axis_and_name_their_exclusions(self):
        editor.set_word_axis(self.state, "agreeableness")
        self.assertEqual(["Kind", "Pacifist"], [row["label"] for row in editor.word_rows(self.state, self.world)])
        editor.toggle_word(self.state, "Pacifist")
        self.assertEqual(["Pacifist excludes Violence"], editor.chosen_exclusions(self.state, self.world))
        editor.toggle_word(self.state, "pacifist")
        self.assertNotIn("personality_adjectives", self.state["draft"])


def _parent(person_id, tone, stature, born, **extra):
    dna = set_body_trait(create_person_dna(person_id, tone), "stature", stature)
    return {"id": person_id, "type": "person", "pretty_name": person_id.split("_")[-1].title(),
            "genetic_dna": dna, "start_year": born, **extra}


PARENTS = [
    _parent("person_mira", "light", 0.8, 2330),
    _parent("person_oskar", "light", 0.6, 2335, end_year=2365),
    _parent("person_tiny", "deep", 0.2, 2362),
]


class InheritanceTests(unittest.TestCase):
    def test_children_land_around_the_parents_and_mix_their_skin(self):
        mira, oskar, tiny = (person["genetic_dna"] for person in PARENTS)
        self.assertEqual(inherit_person_dna([mira, oskar], "s"), inherit_person_dna([mira, oskar], "s"))
        statures = [decode_person_dna(inherit_person_dna([mira, oskar], f"s{i}"))["body_shape"]["stature"] for i in range(300)]
        mean = sum(statures) / len(statures)
        self.assertAlmostEqual(0.7, mean, delta=0.03)
        self.assertLess(max(statures) - min(statures), 0.9)
        tones = [decode_person_dna(inherit_person_dna([mira, oskar], f"t{i}"))["skin_tone"]["id"] for i in range(200)]
        self.assertGreater(tones.count("light"), 150)
        mixed = [decode_person_dna(inherit_person_dna([mira, tiny], f"m{i}"))["skin_tone"]["id"] for i in range(200)]
        self.assertGreater(mixed.count("medium"), 100)
        one = [decode_person_dna(inherit_person_dna([tiny], f"o{i}"))["body_shape"]["stature"] for i in range(300)]
        self.assertAlmostEqual(0.35, sum(one) / len(one), delta=0.03)
        self.assertEqual(create_person_dna("seed"), inherit_person_dna(["broken"], "seed"))


class ParentsStepTests(unittest.TestCase):
    def setUp(self):
        self.world = _World(PARENTS + [{"id": "pop_family", "type": "pop"}])
        self.world.add("pops", {"id": "pop_family", "type": "pop"})
        self.sim = PersonSimulation(self.world, None, year=2400, initial_view="editor")
        self.sim.start_new_person("city_berlin", seed="seed-a")
        self.state = self.sim.person_editor

    def test_parents_are_optional_up_to_two_and_the_genome_follows_them(self):
        own = self.state["draft"]["genetic_dna"]
        self.assertFalse(editor.step_done(self.state, "parents", self.world))
        _click(self.sim, kind="parent", person_id="person_mira")
        with_mira = self.state["draft"]["genetic_dna"]
        self.assertNotEqual(own, with_mira)
        _click(self.sim, kind="parent", person_id="person_oskar")
        self.assertEqual(["person_mira", "person_oskar"], editor.parent_ids(self.state, self.world))
        both = self.state["draft"]["genetic_dna"]
        self.assertEqual(inherit_person_dna([PARENTS[0]["genetic_dna"], PARENTS[1]["genetic_dna"]],
                                            "seed-a:person_mira:person_oskar"), both)
        self.assertFalse(editor.toggle_parent(self.state, "person_tiny", self.world))
        self.assertFalse(editor.toggle_parent(self.state, "pop_family", self.world))
        _click(self.sim, kind="reroll_genome")
        self.assertNotEqual(both, self.state["draft"]["genetic_dna"])
        _click(self.sim, kind="parent", person_id="person_mira")
        _click(self.sim, kind="parent", person_id="person_oskar")
        self.assertNotIn("parents", self.state["draft"])
        self.assertTrue(editor.step_done(self.state, "genetics"))

    def test_other_entries_in_parents_stay_and_odd_parents_are_named(self):
        self.state["draft"]["parents"] = ["pop_family"]
        _click(self.sim, kind="parent", person_id="person_tiny")
        self.assertEqual(["pop_family", "person_tiny"], self.state["draft"]["parents"])
        self.assertEqual(["person_tiny"], editor.parent_ids(self.state, self.world))
        rows = {row["id"]: row for row in editor.parent_rows(self.state, self.world)}
        self.assertEqual("aged 8 at the birth", rows["person_tiny"]["note"])
        self.assertEqual("died 2365, before the birth", rows["person_oskar"]["note"])
        self.assertEqual("", rows["person_mira"]["note"])
        self.assertEqual(40, rows["person_mira"]["age"])
        self.assertEqual("person_tiny", editor.parent_rows(self.state, self.world)[0]["id"])
        editor.focus_input(self.state, "people_search")
        editor.type_text(self.state, "osk", self.world)
        self.assertEqual(["person_oskar"], [row["id"] for row in editor.parent_rows(self.state, self.world)])


class StoredPersonTests(unittest.TestCase):
    def test_saving_a_stored_person_writes_only_what_changed_and_keeps_their_own_knowledge(self):
        world = _World([{"id": "person_ada", "type": "person", "pretty_name": "Ada", "name": "Ada",
                         "knowledge_collection": "coll_knowledge_ada"}])
        sim = PersonSimulation(world, "person_ada", initial_view="editor")
        state = sim._ensure_person_editor()
        self.assertEqual(["coll_lore"], state["shared_knowledge"])
        _click(sim, kind="knowledge", collection_id="coll_lore")
        _click(sim, kind="knowledge", collection_id="coll_training")
        _click(sim, kind="year_delta", delta=1)
        self.assertTrue(sim.save_person_editor())
        collection = world.loader.whole[0]
        self.assertEqual(["coll_training", "loc_barracks"], collection["includes"])
        person_id, fields = world.loader.fields[0]
        self.assertEqual("person_ada", person_id)
        self.assertEqual({"start_year", "genetic_dna"}, fields)
        self.assertEqual(2400 - editor.ADULT_AGE + 1, world.get_entity("person_ada")["start_year"])


class EditorWiringTests(unittest.TestCase):
    def test_places_offer_a_new_person_born_there_but_star_systems_do_not(self):
        resolver = LaunchAffordanceResolver()
        modes = lambda entity: [option["mode"] for option in resolver.options_for_entity(entity)]
        self.assertIn("person_create", modes({**PLACES[4], "_dataset": "locations"}))
        self.assertNotIn("person_create", modes({**PLACES[0], "_dataset": "locations"}))
        self.assertNotIn("person_create", modes({**PLACES[5], "_dataset": "locations"}))

    def test_new_person_born_here_opens_a_new_person_tab_in_the_editor(self):
        from app.navigation_controller import NavigationController

        tabs = SimpleNamespace(tabs=[], active_index=0, add_tab=lambda tab: tabs.tabs.append(tab),
                               activate_tab_by_key=lambda key: False)
        app = SimpleNamespace(
            world_model=_World(), tab_manager=tabs, knowledge_layer_active=True,
            camera_controller=SimpleNamespace(setup_for_sim=lambda sim: None),
            get_active_simulation=lambda: SimpleNamespace(year=2400),
        )
        self.assertTrue(NavigationController(app).launch_entity_mode("city_berlin", "person_create"))
        self.assertEqual("New Person", tabs.tabs[-1].name)
        sim = tabs.tabs[-1].sim_instance.simulation
        self.assertTrue(sim.is_person_editor_active())
        self.assertEqual("city_berlin", sim.person_editor["draft"]["birth_location"])
        self.assertTrue(sim.person_editor["is_new"])

    def test_every_step_draws_and_its_controls_reach_the_editor(self):
        pygame.init()
        pygame.font.init()
        world = _World()
        sim = PersonSimulation(world, None, year=2400, initial_view="editor")
        sim.start_new_person("city_berlin", seed="seed-a")
        renderer = PersonRenderer(SimpleNamespace(camera=None, default_font=pygame.font.SysFont("consolas", 16),
                                                  width=1200, height=800))
        surface = pygame.Surface((1200, 800))
        kinds_by_step = {}
        for step in editor.STEP_IDS:
            sim.set_editor_step(step)
            renderer.draw(surface, sim)
            kinds_by_step[step] = {hitbox["kind"] for hitbox in sim._person_editor_hitboxes}
        self.assertIn("place_choose", kinds_by_step["birth"])
        self.assertIn("focus", kinds_by_step["parents"])
        self.assertIn("skin_tone", kinds_by_step["genetics"])
        self.assertIn("word", kinds_by_step["personality"])
        self.assertIn("baseline_delta", kinds_by_step["personality"])
        self.assertIn("life_tab", kinds_by_step["life"])
        self.assertIn("next", kinds_by_step["person"])
        self.assertNotIn("next", kinds_by_step["review"])
        sim.set_editor_step("person")
        renderer.draw(surface, sim)
        button = next(hitbox for hitbox in sim._person_editor_hitboxes if hitbox["kind"] == "next")
        sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": button["rect"].center}),
                                 None, button["rect"].center)
        self.assertEqual("birth", sim.person_editor["step"])


if __name__ == "__main__":
    unittest.main()
