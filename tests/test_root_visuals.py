import pygame
from types import SimpleNamespace

from simulations.species.root_growth import root_profile, build_root_graph
from simulations.species.root_visuals import root_segment_style
from simulations.species.root_comparison import comparison_entities
from simulations.species.species_simulation import SpeciesSimulation
from world.plant_catalogue import PLANTAE_ID


def placement(scale=.6, level=1, kind='root_section'):
    return [kind, 0, 0, 0, -.1, 0, scale, level]


def test_tissue_widths_and_colours_distinguish_form_order_and_maturity():
    tree = {'shape': 'tree', 'plant_woodiness': 'woody'}
    grass = {'shape': 'graminoid', 'plant_woodiness': 'herbaceous'}
    coarse, brown = root_segment_style(tree, placement(), 1.)
    fine, pale = root_segment_style(tree, placement(.1, 3), 1.)
    grass_radius, cream = root_segment_style(grass, placement(), 1.)
    assert coarse > grass_radius > fine > 0
    assert brown != cream and sum(pale) > sum(brown)
    assert root_segment_style(tree, placement(), .05)[0] < coarse
    assert grass_radius < .001  # A grass primary is not several centimetres wide.
    assert root_segment_style(grass, placement(kind='root_support'), 1.)[0] > grass_radius


def test_axes_taper_continuously_and_keep_bounded_graph():
    for architecture in ('taproot', 'fibrous', 'mixed', 'adventitious'):
        graph, stats = build_root_graph(root_profile({'root_architecture': architecture}), 1., 303)
        assert len(graph) < 400
        for i, node in enumerate(graph):
            if node['parent'] >= 0:
                parent = graph[node['parent']]
                if parent['order'] == node['order'] and parent['kind'] == node['kind']:
                    assert node['thickness'] <= parent['thickness']
            assert node['thickness'] > 0


def test_comparison_uses_taxonomy_and_retains_unresolved_developed_species():
    datasets = {'cladistics': [{'id': PLANTAE_ID, 'type': 'cladistics'}], 'species': [
        {'id': 'known', 'type': 'species', 'parents': [PLANTAE_ID], 'plant_growth_behaviour': 'tussock_tillering', 'root_architecture': 'fibrous'},
        {'id': 'missing', 'type': 'species', 'parents': [PLANTAE_ID], 'plant_growth_behaviour': 'fern_fronding'},
        {'id': 'fake', 'type': 'species', 'plant_growth_behaviour': 'tussock_tillering'},
        {'id': 'undeveloped', 'type': 'species', 'parents': [PLANTAE_ID]}]}
    assert [e['id'] for e in comparison_entities(datasets)] == ['known', 'missing']


def test_roots_to_compare_and_keyboard_routing_preserve_individual_comparison():
    from app.input_router import InputRouter
    sim = SpeciesSimulation(species_entity={'id': 'test'})
    sim.set_active_simulation_panel_tab('roots')
    sim.set_active_simulation_panel_tab('compare')
    assert sim.comparison_subject == 'roots'
    app = SimpleNamespace(get_active_simulation=lambda: sim, knowledge_layer_active=False)
    router = InputRouter(app)
    for key in (pygame.K_s, pygame.K_RIGHT):
        assert router._handle_keydown_navigation(pygame.event.Event(pygame.KEYDOWN, key=key))
    assert sim.root_comparison_common_scale and sim.root_comparison_page == 1
    assert router._handle_keydown_navigation(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    assert sim.comparison_subject == 'individual'
