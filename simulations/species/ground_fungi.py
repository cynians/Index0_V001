"""Bounded soil colonies and independent pitted, stalked ascocarps.

Dimensions are metric. Colony extent, diagnostic hyphae, flush clocks and
ecological activity are explicit qualitative calibrations, not biomass fluxes.
"""
import math
import random
from copy import deepcopy
from types import SimpleNamespace

from simulations.species.fungal_growth import number, fungal_life_state

GROUND_FUNGAL_VERSION = 1


def ground_fungal_blueprint(entity, species_id):
    from world.fungal_traits import validate_fungal_profile, FUNGAL_ASSET_FIELDS
    from simulations.species.plant_assets import PlantBlueprint, PlantModule
    p = deepcopy(entity['fungal_growth_profile'])
    validate_fungal_profile(p)
    cup = p['body_form'] == 'sessile_cup'
    fit = p.get('visual_calibration', {})
    clock = p.get('simulation_calibration', {})
    r = {key + '_m': p[key]['typical_m'] for key in
         ('cap_width', 'cap_height', 'stipe_length', 'stipe_diameter')}
    r.update(body_count=int(fit.get('body_count', 4)),
             colony_radius_m=fit.get('colony_radius_m', .18),
             mycelium_depth_m=fit.get('mycelium_depth_m', .04),
             colony_model_days=clock.get('colony_model_days', 90),
             first_flush_model_days=clock.get('first_flush_model_days', 120),
             flush_cycle_model_days=clock.get('flush_cycle_model_days', 82))
    if cup:
        r['body_variant_keys'] = list(fit.get('body_variant_keys', []))
        r['body_cluster_radius_ratio'] = fit.get('body_cluster_radius_ratio',1.)
    p['resolved'] = r
    modules = [PlantModule('mycelium', 'mycelium', length_m=.01, radius_m=.0005)]
    for role, field in FUNGAL_ASSET_FIELDS.items():
        a = (entity.get('fungal_module_anchors') or {}).get(role, {})
        modules.append(PlantModule(role, role, asset_ref=entity.get(field),
            length_m=r['cap_height_m'] + r['stipe_length_m'] if role == 'fruiting_body' else r['cap_width_m'],
            radius_m=r['cap_width_m'] / 2,
            attachment_point=tuple(a.get('attachment_point', (.5, .97) if role == 'fruiting_body' else (.5, .5))),
            growth_axis=tuple(a.get('growth_axis', (0., -1.))),
            visual={'depicted_size_m': a.get('depicted_size_m', .14),
                    'cap_join_fraction': number(a.get('cap_join_fraction'), .657143, .05, .95),
                    'metric_axis': 'height' if role == 'fruiting_body' else 'width'}))
        if cup:
            for key,variant in sorted((a.get('variants') or {}).items()):
                if not isinstance(variant,dict) or not variant.get('asset_ref'):continue
                modules.append(PlantModule(f'{role}:{key}',role,asset_ref=variant['asset_ref'],
                    length_m=r['cap_height_m'] if role == 'fruiting_body' else r['cap_width_m'],
                    radius_m=r['cap_width_m']/2,
                    attachment_point=tuple(variant.get('attachment_point',(.5,.97) if role=='fruiting_body' else (.5,.5))),
                    growth_axis=tuple(variant.get('growth_axis',(0.,-1.))),
                    visual={'depicted_size_m':variant.get('depicted_size_m',r['cap_width_m']),
                            'metric_axis':'height' if role=='fruiting_body' else 'width'}))
    maturity = r['colony_model_days']
    return PlantBlueprint(species_id, str(entity.get('common_name') or species_id), modules,
        root_module_id='mycelium', growth={'shape': 'fungus', 'growth_form': 'fungus',
        'growth_behaviour': 'soil_colonising_fungus', 'fungal_grammar_version': 2,
        'ground_fungal_version': 2 if cup else GROUND_FUNGAL_VERSION, 'fungal_growth_profile': p,
        'maturity_days': maturity, 'max_height_m': r['cap_height_m'] + r['stipe_length_m'],
        'life_history': {'class': 'persistent_fungal_colony', 'age_limit_days': maturity + 720,
        'reproductive_start_days': r['first_flush_model_days'], 'senescence_start_days': maturity + 720}},
        lod_policy={'0': 'one_body', '1': 'half_bodies', '2': 'all_bodies'})


def build_ground_fungal_snapshot(sim, age, lod):
    from simulations.species.plant_assets import PlantGrowthSnapshot
    r = sim.blueprint.growth['fungal_growth_profile']['resolved']
    cup = sim.blueprint.growth['fungal_growth_profile']['body_form'] == 'sessile_cup'
    state = fungal_life_state(sim.blueprint.growth, age)
    compatible = sim.environment.get('fungal_ground_substrate') == 'soil_humus'
    colonised = state['maturity'] if compatible else 0.
    moisture = number(sim.environment.get('fungal_moisture'), 1, 0, 1)
    expansion = state['fruit_body_expansion']
    enabled = bool(sim.environment.get('fungal_fruiting_enabled', True))
    placements, paths, sockets, bodies = [], {}, [], []
    radius = r['colony_radius_m'] * math.sqrt(colonised)
    depth = r['mycelium_depth_m']
    # Fixed network survives flush disappearance; no plant roots or wood fixture.
    if colonised > 0:
        rng = random.Random(f'{sim.seed}:ground_hyphae')
        for arm in range(8):
            parent = -1
            theta = arm * math.tau / 8
            for step in range(5):
                distance = radius * step / 4
                point = [distance * math.cos(theta), distance * math.sin(theta),
                         -depth * (.35 + .65 * rng.random())]
                i = len(placements)
                placements.append(['mycelium', parent, *point, 0., colonised, 0])
                if parent >= 0: paths[str(i)] = [placements[parent][2:5], point]
                parent = i
    count = r['body_count'] if colonised > 0 and expansion > 0 and moisture > 0 and enabled else 0
    visible = set(range(count)) if lod == 2 else set(range(0, count, 2)) if lod == 1 else {0}
    rng = random.Random(f'{sim.seed}:ground_bodies:{state["flush_index"]}')
    points = [(-radius, -radius, -depth), (radius, radius, 0.)]
    for ordinal in range(count):
        theta = ordinal * 2.399963 + rng.uniform(-.2, .2)
        distance = radius * (.25 + .55 * math.sqrt((ordinal + .5) / count))
        if cup:
            distance *= r['body_cluster_radius_ratio']
        base = [distance * math.cos(theta), distance * math.sin(theta), 0.]
        # One within-range size coefficient preserves cap/stalk proportions.
        size = .82 + .18 * rng.random()
        dims = {k: r[k + '_m'] * size * expansion for k in ('cap_width', 'cap_height', 'stipe_length', 'stipe_diameter')}
        if cup:
            # Young cups are relatively deep; full expansion opens the bowl.
            # This bounded shape schedule is a visual fit, not a measured rate.
            dims['cap_height'] *= (1.4-.4*expansion)*(1-.25*state['weathering_factor'])
        width = dims['cap_width']; height = dims['cap_height'] + dims['stipe_length']
        idx = None
        if ordinal in visible:
            idx = len(placements)
            placements.append(['fruiting_body', 0, *base, 0., size * expansion, 1])
            sockets.append({'placement_index': idx, 'host_placement_index': 0,
                'socket': 'soil_surface', 'substrate_id': 'ground_humus', 'position_m': base})
        body = {'id': f'ground:{state["flush_index"]}:{ordinal}', 'substrate_id': 'ground_humus',
                'socket_m': base, 'cap_socket_m': [*base[:2], dims['stipe_length']],
                'normal': [0, 0, 1], 'placement_index': idx,
                'weathering_factor': state['weathering_factor'], 'sporulation_factor': state['sporulation_factor'],
                **{k + '_m': v for k, v in dims.items()}}
        if cup:
            keys=[None,*(r.get('body_variant_keys') or [])]
            body.update(body_form='sessile_cup',opening_factor=expansion,
                        variant_key=keys[ordinal % len(keys)])
        bodies.append(body)
        points.extend([(base[0] - width/2, base[1] - width/2, 0.),
                       (base[0] + width/2, base[1] + width/2, height)])
    area = math.pi * radius**2
    stats = {'maturity': state['maturity'], 'life_phase': state['phase'], 'life_state': state,
        'fungal_substrates': [], 'fungal_ground_substrate': sim.environment.get('fungal_ground_substrate'),
        'substrate_context_source': sim.environment.get('substrate_context_source', 'supplied'),
        'fungal_bodies': bodies, 'fungal_active_substrate_count': int(compatible),
        'colonised_soil_area_proxy_m2': area, 'colonised_wood_volume_proxy_m3': 0.,
        'canonical_mycelium_node_count': len(placements) - len(visible.intersection(range(count))),
        'estimated_fruiting_body_count': count, 'visible_fruiting_body_count': sum(b['placement_index'] is not None for b in bodies),
        'sporulating_area_proxy_m2': sum((math.pi*(b['cap_width_m']/2)*math.hypot(b['cap_width_m']/2,b['cap_height_m'])
                                        if cup else math.pi*b['cap_width_m']*b['cap_height_m'])*b['sporulation_factor'] for b in bodies),
        'root_segment_count': 0, 'root_length_m': 0., 'root_depth_m': 0., 'leaf_count': 0,
        'estimated_leaf_count': 0, 'leaf_area_m2': 0., 'stem_count': 0, 'branch_count': 0,
        'leaf_cluster_count': 0, 'placement_count': len(placements)}
    bounds = [fn(p[a] for p in points) for a in range(3) for fn in (min, max)]
    return PlantGrowthSnapshot(sim.species_id, sim.blueprint.fingerprint(), sim.seed, age, lod,
        {m.id: m.to_dict() for m in sim.blueprint.modules}, placements, bounds,
        placement_paths=paths, attachment_points=sockets, stats=stats)


def ground_fungal_ecological_outcome(sim, environment=None):
    env = {**sim.environment, **(environment or {})}
    stats = build_ground_fungal_snapshot(SimpleNamespace(environment=env, blueprint=sim.blueprint,
        species_id=sim.species_id, seed=sim.seed), sim.age_days, sim.lod).stats
    vitality = stats['maturity'] * stats['fungal_active_substrate_count'] * (1-number(env.get('fungal_drought_stress'), 0, 0, 1))
    return {'species_id': sim.species_id, 'age_days': sim.age_days, 'maturity': stats['maturity'],
        'vitality': vitality, 'growth_rate': vitality * (1-stats['maturity']),
        'fecundity': vitality * min(1., stats['sporulating_area_proxy_m2']/.1),
        'mortality_risk': 1-vitality, 'leaf_area_proxy': 0., 'photosynthesis_proxy': 0.,
        'resource_demand': vitality*.05, 'wood_decay_activity_proxy': 0.,
        'colonised_soil_area_proxy_m2': stats['colonised_soil_area_proxy_m2'],
        'estimated_fruiting_body_count': stats['estimated_fruiting_body_count'],
        'sporulating_area_proxy_m2': stats['sporulating_area_proxy_m2'],
        **({'feeding_mode_status': sim.blueprint.growth['fungal_growth_profile']['feeding_modes'][0]}
           if sim.blueprint.growth['fungal_growth_profile']['body_form']=='sessile_cup' else {}),
        'decomposition_rate_source': 'unknown_no_mass_or_nutrient_flux_implemented'}
