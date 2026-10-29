import unittest

import pygame

from simulations.person.person_editor import new_person_editor_state, select_clothing, working_clothing_id
from simulations.person.person_genetics import (
    BODY_TRAITS,
    create_person_dna,
    decode_person_dna,
    set_body_trait,
    set_skin_tone,
)
from simulations.person.person_simulation import PersonSimulation
from simulations.person.person_renderer import PersonRenderer
from app.launch_affordance_resolver import LaunchAffordanceResolver
from tools.author_person_genetics_model import CLOTHING_ENTITIES


class _World:
    def __init__(self, person, extra=None):
        self.entities = {person["id"]: person, **(extra or {})}
        self.loader = None

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class _RecordingLoader:
    def __init__(self):
        self.calls = []

    def persist_entity_fields(self, entity, fields):
        self.calls.append((entity, tuple(fields)))
        return True


class PersonGeneticsTests(unittest.TestCase):
    def test_canonical_human_silhouette_is_long_and_spindly(self):
        geometry = PersonRenderer._spindly_geometry((200, 500), 360)
        shoulder_width = geometry["shoulders"][1][0] - geometry["shoulders"][0][0]
        leg_length = geometry["left_leg"][1][1] - geometry["left_leg"][0][1]
        torso_length = geometry["hip_y"] - geometry["shoulders"][0][1]
        self.assertLess(shoulder_width / geometry["height"], 0.15)
        self.assertGreater(leg_length, torso_length * 1.5)
        self.assertGreater(geometry["head"].height, geometry["head"].width)

    def test_body_shape_loci_are_bounded_and_visibly_directional(self):
        short = {trait["id"]: 0.5 for trait in BODY_TRAITS}
        long = dict(short)
        short["leg_length"] = 0.0
        long["leg_length"] = 1.0
        narrow = dict(short)
        wide = dict(short)
        narrow["torso_width"] = 0.0
        wide["torso_width"] = 1.0
        short_geometry = PersonRenderer._spindly_geometry((200, 500), 360, short)
        long_geometry = PersonRenderer._spindly_geometry((200, 500), 360, long)
        narrow_geometry = PersonRenderer._spindly_geometry((200, 500), 360, narrow)
        wide_geometry = PersonRenderer._spindly_geometry((200, 500), 360, wide)
        self.assertLess(long_geometry["hip_y"], short_geometry["hip_y"])
        self.assertLess(narrow_geometry["torso"][1][0] - narrow_geometry["torso"][0][0],
                        wide_geometry["torso"][1][0] - wide_geometry["torso"][0][0])

    def test_body_trait_mutation_changes_only_its_reserved_locus(self):
        original = create_person_dna("body-seed", "deep")
        changed = set_body_trait(original, "arm_length", 1.0)
        before = decode_person_dna(original)
        after = decode_person_dna(changed)
        locus = next(trait["locus"] for trait in BODY_TRAITS if trait["id"] == "arm_length")
        differences = [index for index, pair in enumerate(zip(before["reserved_loci"], after["reserved_loci"])) if pair[0] != pair[1]]
        self.assertEqual([locus], differences)
        self.assertEqual(1.0, after["body_shape"]["arm_length"])

    def test_person_launch_affordances_offer_editor_then_simulation(self):
        options = LaunchAffordanceResolver().options_for_entity(
            {"id": "person_test", "type": "person", "_dataset": "people"}
        )
        self.assertEqual(["person_editor", "person"], [option["mode"] for option in options])

    def test_three_skin_tones_round_trip_through_one_string(self):
        strings = []
        for tone in ("light", "medium", "deep"):
            value = create_person_dna("person_seed", tone)
            strings.append(value)
            decoded = decode_person_dna(value)
            self.assertTrue(decoded["valid"])
            self.assertEqual(tone, decoded["skin_tone"]["id"])
        self.assertEqual(3, len(set(strings)))

    def test_changing_tone_preserves_reserved_loci(self):
        original = create_person_dna("person_seed", "light")
        changed = set_skin_tone(original, "deep")
        self.assertEqual(
            decode_person_dna(original)["reserved_loci"],
            decode_person_dna(changed)["reserved_loci"],
        )

    def test_corruption_is_visible_and_uses_safe_preview(self):
        value = create_person_dna("person_seed", "deep")
        decoded = decode_person_dna(value[:-1] + ("A" if value[-1] != "A" else "B"))
        self.assertFalse(decoded["valid"])
        self.assertEqual("checksum_mismatch", decoded["status"])
        self.assertEqual("medium", decoded["skin_tone"]["id"])

    def test_missing_dna_creates_unsaved_deterministic_editor_preview(self):
        first = new_person_editor_state({"id": "person_test"})
        second = new_person_editor_state({"id": "person_test"})
        self.assertEqual(first["draft"]["genetic_dna"], second["draft"]["genetic_dna"])
        self.assertTrue(first["dirty"])

    def test_person_editor_routes_tone_click_and_runtime_payload_reads_dna(self):
        person = {"id": "person_test", "name": "Test", "genetic_dna": create_person_dna("x", "light")}
        sim = PersonSimulation(_World(person), "person_test", initial_view="editor")
        sim.set_person_editor_hitboxes([
            {"kind": "skin_tone", "tone_id": "deep", "rect": pygame.Rect(0, 0, 40, 40)},
        ])
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (10, 10)}),
            None,
            (10, 10),
        )
        self.assertEqual("deep", decode_person_dna(sim.person_editor["draft"]["genetic_dna"])["skin_tone"]["id"])
        person["genetic_dna"] = sim.person_editor["draft"]["genetic_dna"]
        self.assertEqual("deep", sim.get_person_render_payload()["appearance"]["skin_tone_id"])

        sim.set_person_editor_hitboxes([
            {"kind": "body_trait", "trait_id": "leg_length", "delta": .05, "rect": pygame.Rect(0, 0, 40, 40)},
            {"kind": "clothing", "clothing_id": "item_test_toga", "rect": pygame.Rect(50, 0, 40, 40)},
        ])
        dna_before = sim.person_editor["draft"]["genetic_dna"]
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (10, 10)}), None, (10, 10),
        )
        self.assertNotEqual(dna_before, sim.person_editor["draft"]["genetic_dna"])
        sim.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (60, 10)}), None, (60, 10),
        )
        self.assertEqual("item_test_toga", working_clothing_id(sim.person_editor))

    def test_clothing_is_an_item_subcategory_and_not_part_of_dna(self):
        by_id = {entity["id"]: entity for entity in CLOTHING_ENTITIES}
        self.assertEqual(["cat_manufactured_good"], by_id["cat_clothing"]["parents"])
        for item_id in ("item_test_toga", "item_test_suit"):
            self.assertEqual("item", by_id[item_id]["type"])
            self.assertEqual(["cat_clothing"], by_id[item_id]["categories"])
        state = new_person_editor_state({"id": "person_test"})
        dna_before = state["draft"]["genetic_dna"]
        self.assertTrue(select_clothing(state, "item_test_toga"))
        self.assertEqual(dna_before, state["draft"]["genetic_dna"])
        self.assertEqual("item_test_toga", working_clothing_id(state))

    def test_save_persists_dna_and_equipped_item_relation_together(self):
        person = {"id": "person_test", "type": "person", "genetic_dna": create_person_dna("save")}
        extras = {entity["id"]: entity for entity in CLOTHING_ENTITIES}
        world = _World(person, extras)
        world.loader = _RecordingLoader()
        sim = PersonSimulation(world, person["id"], initial_view="editor")
        self.assertTrue(sim.select_editor_clothing("item_test_suit"))
        self.assertTrue(sim.adjust_editor_body_trait("torso_width", .05))
        self.assertTrue(sim.save_person_editor())
        self.assertEqual(["item_test_suit"], person["equipped_clothing"])
        self.assertEqual({"genetic_dna", "equipped_clothing"}, set(world.loader.calls[0][1]))
        self.assertEqual("item_test_suit", sim.get_person_render_payload()["clothing"]["id"])


if __name__ == "__main__":
    unittest.main()
