from types import SimpleNamespace

import pygame
import pytest

from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.map.map_simulation import MapSimulation
from ui.ui_manager import UIManager


class IdentityCamera:
    width = 1000
    height = 700
    x = 5.0
    y = 5.0
    zoom = 1.0

    def world_to_screen(self, position):
        return (
            (position[0] - self.x) * self.zoom + self.width / 2,
            (position[1] - self.y) * self.zoom + self.height / 2,
        )


def test_biosphere_builder_is_map_native():
    sim = BiosphereSimulation.reference_site()

    assert sim.render_mode == "map"
    assert sim.simulation_mode == "biosphere_builder"
    assert sim.get_map_size() == 10.0
    assert sim.get_active_layer_label() == "Isometric biosphere development"
    assert sim.ecology.summary()["spatial_model"] == "continuous_population_patches"


def test_biosphere_controls_use_supported_button_state_contract():
    sim = BiosphereSimulation.reference_site()
    pygame.font.init()
    ui = UIManager()

    ui.rebuild_for_state(sim, 1280, 800, camera=None, world_model=sim.world_model)

    catalogue_button = next(button for button in ui.buttons if button.id == "biosphere_open_species_picker")
    pause_button = next(button for button in ui.buttons if button.id == "biosphere_set_speed:0")
    assert catalogue_button.city_builder_primary is True
    assert pause_button.map_layer_active is True
    assert not any(button.id == "biosphere_advance_season" for button in ui.buttons)


def test_full_screen_species_picker_exposes_preview_traits_and_blocks_map_input():
    sim = BiosphereSimulation.reference_site()
    pygame.font.init()
    ui = UIManager()
    sim.open_species_picker()

    ui.rebuild_for_state(sim, 1280, 800, camera=None, world_model=sim.world_model)
    surface = pygame.Surface((1280, 800))
    ui.draw(surface, pygame.font.SysFont("consolas", 16))

    assert ui.biosphere_picker_open
    assert ui.biosphere_picker_model["focused"]["trait_lines"]
    assert ui.biosphere_picker_model["focused"]["id"] == sim.BIOMASSER_ID
    assert any(button.id == "biosphere_picker_confirm" for button in ui.buttons)
    outside = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (5, 5)})
    assert ui.handle_event(outside) == "__ui_consumed__"


def test_realtime_speed_controls_advance_without_manual_season_step():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)

    assert sim.set_builder_time_scale(4.0)
    sim.update(sim.seconds_per_season / 4.0)

    assert sim.ecology.season == 1
    assert sim.get_biosphere_time_state()["season"] == "Summer"


def test_species_picker_focus_confirm_and_locked_species_contract():
    sim = BiosphereSimulation.reference_site()
    model = sim.get_species_picker_model()
    birch = next(item for item in sim.get_species_catalog_items() if item["id"] == "spec_betula_pendula")

    assert not birch["enabled"]
    assert "Requires" in birch["unlock_label"]
    sim.set_builder_time_scale(4.0)
    assert sim.open_species_picker()
    assert sim.builder_paused
    assert sim.focus_species_picker_item("spec_betula_pendula")
    assert not sim.confirm_species_picker_selection()
    assert sim.species_picker_open
    assert model["focused"]["id"] == sim.BIOMASSER_ID

    assert sim.focus_species_picker_item(sim.BIOMASSER_ID)
    assert sim.confirm_species_picker_selection()
    assert not sim.species_picker_open
    assert sim.builder_time_scale == 4.0


def test_introduction_establishes_and_spreads_after_seasons():
    sim = BiosphereSimulation.reference_site()
    introduction = sim.place_selected_species(5.0, 5.0)
    initial = sim.ecology.summary()

    assert introduction is not None
    assert initial["introductions"] == 1

    sim.advance_seasons(12)
    developed = sim.ecology.summary()

    assert developed["season"] == 12
    assert developed["occupied_cell_species"] > initial["occupied_cell_species"]
    assert developed["biomass_index"] > initial["biomass_index"]


def test_different_habitats_produce_different_outcomes():
    wet = BiosphereSimulation.reference_site()
    dry = BiosphereSimulation.reference_site()
    wet.ecology.introduce("spec_nymphaea_alba", 3.0, 3.6, 0.7)
    dry.ecology.introduce("spec_nymphaea_alba", 8.2, 3.6, 0.7)

    wet.advance_seasons(16)
    dry.advance_seasons(16)

    assert wet.ecology.summary()["biomass_index"] > dry.ecology.summary()["biomass_index"]


def test_click_places_introduction_but_drag_does_not():
    sim = BiosphereSimulation.reference_site()
    camera = IdentityCamera()
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1})
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1})

    sim.handle_pointer_event(down, camera, (500, 350))
    sim.handle_pointer_event(up, camera, (500, 350))

    assert len(sim.ecology.introductions) == 1

    sim.is_camera_dragging = True
    sim.camera_drag_has_moved = True
    sim.handle_pointer_event(up, camera, (520, 400))
    assert len(sim.ecology.introductions) == 1


def test_builder_layers_are_derived_and_non_pickable():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(4)

    overlays = [layer for layer in sim.get_layers() if layer.get("draw_order") in {820, 950}]

    assert overlays
    assert any(layer.get("shape") == "polygon" for layer in overlays)
    assert not any(layer.get("shape") == "rect" for layer in overlays)
    assert all(layer.get("pickable") is False for layer in overlays)


def test_established_cells_emit_deterministic_species_sprite_instances():
    first = BiosphereSimulation.reference_site()
    second = BiosphereSimulation.reference_site()
    for simulation in (first, second):
        simulation.place_selected_species(5.0, 5.0)
        simulation.advance_seasons(12)

    instances = first.get_species_sprite_instances()

    assert instances
    assert instances == second.get_species_sprite_instances()
    assert {item["species_id"] for item in instances} == {"spec_biomasser_13b"}
    assert all(0 <= item["age_bucket"] <= 3 for item in instances)


def test_species_sim_sprites_render_at_biosphere_map_positions():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(8)
    surface = pygame.Surface((1000, 700), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))

    BiosphereBuilderRenderer(SimpleNamespace(camera=IdentityCamera())).draw(surface, sim)

    assert surface.get_bounding_rect(min_alpha=1).width > 0


def test_population_maintains_four_deep_representatives_and_uses_their_feedback():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)

    assert len(sim.representatives.items("spec_biomasser_13b", alive_only=True)) == 4

    sim.advance_seasons(1)
    feedback = sim.last_representative_feedback["spec_biomasser_13b"]
    representatives = sim.representatives.items("spec_biomasser_13b", alive_only=True)

    assert feedback["representative_count"] == 4
    assert all(item.age_days > 90.0 for item in representatives)
    assert all(item.last_outcome.get("aggregation_scope") == "representative_organism_to_population" for item in representatives)


def test_biomasser_biomass_unlocks_pioneer_species():
    sim = BiosphereSimulation.reference_site()

    assert not sim.select_species("spec_betula_pendula")
    sim.place_selected_species(5.0, 5.0)
    sim.advance_seasons(8)

    assert sim.pioneers_unlocked()
    assert sim.select_species("spec_betula_pendula")


def test_polygon_founding_point_is_reproducible_and_inside_selection():
    sim = object.__new__(MapSimulation)
    patch = {
        "id": "loc_test_founding_polygon",
        "bounds": {"type": "polygon", "points": [(10.0, 20.0), (110.0, 20.0), (90.0, 80.0), (20.0, 70.0)]},
    }

    first = sim._biosphere_founding_point(patch)
    second = sim._biosphere_founding_point(patch)

    assert first == second
    assert sim._point_in_polygon_points(first["source"][0], first["source"][1], patch["bounds"]["points"])


def test_living_domain_expands_and_preserves_representative_alignment():
    sim = BiosphereSimulation.reference_site()
    sim.maximum_extent_m = 20.0
    sim.place_selected_species(5.0, 5.0)
    representative = sim.representatives.items(alive_only=True)[0]
    old_position = (representative.x, representative.y)
    edge_patch = sim.ecology.species_patches(sim.BIOMASSER_ID)[0]
    edge_patch.x = sim.bounds["min_x"] + edge_patch.radius_m * 0.5
    edge_patch.abundance = 0.25

    assert sim._expand_if_population_reaches_edge()
    assert sim.get_map_size() > 10.0
    assert (representative.x, representative.y) == old_position
    assert sim.ecology.contains(representative.x, representative.y)


def test_isometric_projection_round_trips_free_world_coordinates():
    sim = BiosphereSimulation.reference_site()
    surface = pygame.Surface((1000, 700), pygame.SRCALPHA)
    renderer = BiosphereBuilderRenderer(SimpleNamespace(camera=IdentityCamera()))
    renderer.draw(surface, sim)
    state = sim._isometric_projection_state
    world = (3.137, 7.421)
    screen = renderer._iso(state, *world)

    restored = sim._screen_to_world(IdentityCamera(), screen)

    assert restored == pytest.approx(world)


def test_asset_test_forest_places_every_available_plant_at_free_coordinates():
    sim = BiosphereSimulation.reference_site()

    species_ids = sim.plant_asset_test_forest()

    assert species_ids
    assert set(species_ids) == {profile.species_id for profile in sim.species_profiles}
    assert {patch.species_id for patch in sim.ecology.patches} == set(species_ids)
    positions = {(round(patch.x, 4), round(patch.y, 4)) for patch in sim.ecology.patches}
    assert len(positions) == len(species_ids)
    assert all(not hasattr(item, "column") and not hasattr(item, "row") for item in sim.representatives.items())


def test_map_sprite_click_selects_runtime_representative():
    sim = BiosphereSimulation.reference_site()
    sim.place_selected_species(5.0, 5.0)
    surface = pygame.Surface((1000, 700), pygame.SRCALPHA)
    renderer = BiosphereBuilderRenderer(SimpleNamespace(camera=IdentityCamera()))
    renderer.draw(surface, sim)
    representative_id, hitbox = sim._representative_screen_hitboxes[-1]
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1})
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1})

    sim.handle_pointer_event(down, IdentityCamera(), hitbox.center)
    sim.handle_pointer_event(up, IdentityCamera(), hitbox.center)

    assert sim.selected_representative_id == representative_id
    assert sim.get_selection_inspector_payload()["actions"][0]["id"] == "biosphere_launch_representative"
