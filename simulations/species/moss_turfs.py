"""Leafy bryophyte turfs in metres; qualitative hydration, no vascular organs.

An authored shoot recipe selects this path. Geometry represents a bounded
sample of shoots, not every ramet in a wild colony or a dated succession.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy

MOSS_TURF_VERSION = 1


def _finite(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(low, min(high, number))


def moss_turf_profile(value):
    """Validate explicit measured dimensions and bounded display coefficients."""
    if not isinstance(value, dict) or value.get('form') != 'leafy_moss':
        return None
    limits = {
        'patch_diameter_m': (.01, 1.), 'shoot_length_m': (.003, .25),
        'stem_radius_m': (.00002, .001), 'leaf_width_m': (.0001, .005),
        'shoot_spacing_m': (.003, .04), 'leaf_spacing_m': (.0003, .01),
        'branch_fraction': (0., 1.), 'shoot_lean': (0., .8),
        'hairpoint_fraction': (0., .7), 'outline_irregularity': (0., .8),
    }
    result = deepcopy(value)
    for key, (lo, hi) in limits.items():
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not lo <= raw <= hi:
            return None
        result[key] = float(raw)
    result['version'] = MOSS_TURF_VERSION
    return result


def moss_water_response(environment):
    """Scene wetting is explicit; absence does not mean desiccation.

    This steady-state display response is not a fit to recovery times or
    chlorophyll fluorescence. It must not estimate death from one dry sample.
    """
    raw = environment.get('moss_hydration')
    supplied = isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)
    hydration = _finite(raw if supplied else None, 1., 0., 1.)
    light = 1 - _finite(environment.get('light_stress'), 0., 0., 1.)
    thermal = 1 - _finite(environment.get('temperature_stress'), 0., 0., 1.)
    return {'moss_hydration': hydration, 'moss_hydration_status': 'explicit_qualitative_wetting' if supplied else 'unresolved_neutral',
            'moss_activity': round(hydration * light * thermal, 6),
            'moss_water_source': 'direct_shoot_wetting_no_soil_root_access'}


def build_moss_snapshot(simulation, age_days, lod, maturity):
    from simulations.species.plant_assets import PlantGrowthSnapshot
    growth = simulation.blueprint.growth
    profile = growth['moss_turf_profile']
    water = moss_water_response(simulation.environment)
    hydration = water['moss_hydration']
    development = _finite(maturity, 0., 0., 1.)
    radius = profile['patch_diameter_m'] * .5
    spacing = profile['shoot_spacing_m']
    # Fixed germination sites: growth reveals new shoots without relocating
    # existing ones. Canonical geometry is shared by every render detail.
    n = min(35, math.ceil(radius / spacing))
    sites = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            rng = random.Random((i * 73856093 ^ j * 19349663 ^ simulation.seed * 83492791) & 0xffffffff)
            x, y = (i + rng.uniform(-.36, .36)) * spacing, (j + rng.uniform(-.36, .36)) * spacing
            angle = math.atan2(y, x)
            outline = 1 - profile['outline_irregularity'] * (.5 + .25 * math.sin(angle * 5 + simulation.seed) + .25 * math.sin(angle * 9))
            if math.hypot(x, y) <= radius * outline:
                sites.append((x, y, rng.random(), rng.random(), rng.random()))
    sites.sort(key=lambda p: (math.hypot(p[0], p[1]), p[0], p[1]))
    sites = sites[:256]
    placements, paths, orientations, attachments = [], {}, {}, []
    leaf_count = shoot_count = branch_count = 0
    axis_length = leaf_area = 0.
    canonical_points = [(0., 0., 0.)]

    def add(kind, parent, point, path, forward=None, level=0):
        index = len(placements)
        placements.append([kind, parent, *[round(v, 7) for v in point], 0., 1., level])
        paths[str(index)] = [[round(v, 7) for v in p] for p in path]
        orientations[str(index)] = {'moss_organ': True, **({'forward': list(forward)} if forward else {})}
        canonical_points.extend(path)
        return index

    leaf_length = _finite(growth.get('leaf_length_m'), .004, .0002, .02)
    blade_fraction = 1 - profile['hairpoint_fraction']

    def axis(base, endpoint, parent, phase, level, ordinal):
        nonlocal axis_length, leaf_count, leaf_area
        delta = [endpoint[k] - base[k] for k in range(3)]
        length = math.sqrt(sum(v * v for v in delta))
        axis_length += length
        host = add('stem_section' if level == 0 else 'branch_section', parent, endpoint, [base, endpoint], level=level)
        count = min(40, max(2, round(length / profile['leaf_spacing_m'])))
        # Lower, ageing axes are visible under the leafy upper portion.
        for k in range(count):
            t = .18 + .82 * (k + .5) / count
            origin = [base[q] + delta[q] * t for q in range(3)]
            theta = phase + k * math.radians(growth.get('phyllotaxis_deg', 137.5))
            spread = .22 + .60 * hydration
            up = math.sqrt(max(0., 1 - spread * spread))
            direction = [math.cos(theta) * spread, math.sin(theta) * spread, up]
            size = leaf_length * (.65 + .35 * min(1., development * 1.4))
            blade_tip = [origin[q] + direction[q] * size * blade_fraction for q in range(3)]
            hair_direction = [math.cos(theta) * (.92 - .20 * hydration), math.sin(theta) * (.92 - .20 * hydration), .38 + .30 * hydration]
            norm = math.sqrt(sum(v * v for v in hair_direction))
            tip = [blade_tip[q] + hair_direction[q] / norm * size * profile['hairpoint_fraction'] for q in range(3)]
            leaf_count += 1
            leaf_area += size * blade_fraction * profile['leaf_width_m'] * .5
            canonical_points.extend([origin, blade_tip, tip])
            if lod == 0 or (lod == 1 and (ordinal + k) % 3):
                continue
            leaf = add('leaf', host, origin, [origin, blade_tip, tip], direction, level + 1)
            placements[leaf][6] = size / leaf_length
            orientations[str(leaf)]['moss_blade_fraction'] = blade_fraction
            attachments.append({'stem_placement_index': host, 'leaf_placement_index': leaf,
                                'socket': 'leaf', 'position_m': list(origin)})
        return host

    for ordinal, (x, y, h, turn, branch) in enumerate(sites):
        distance = math.hypot(x, y) / max(radius, 1e-9)
        onset = .03 + .62 * distance * distance
        local = max(0., min(1., (development - onset) / max(.01, 1 - onset)))
        if local <= 0:
            continue
        shoot_count += 1
        length = profile['shoot_length_m'] * (.45 + .55 * h) * local
        theta = turn * math.tau
        lean = profile['shoot_lean'] * length
        base = [x, y, 0.]
        endpoint = [x + math.cos(theta) * lean, y + math.sin(theta) * lean, length]
        host = axis(base, endpoint, -1, theta, 0, ordinal)
        attachments.append({'placement_index': host, 'socket': 'rhizoid_attachment',
                            'position_m': base, 'support_id': 'illustrative_ground_plane'})
        if branch < profile['branch_fraction'] and local > .45:
            branch_count += 1
            origin = [base[q] + (endpoint[q] - base[q]) * .55 for q in range(3)]
            end = [origin[0] + math.cos(theta + 1.8) * length * .26,
                   origin[1] + math.sin(theta + 1.8) * length * .26, origin[2] + length * .36]
            axis(origin, end, host, theta + 1.8, 1, ordinal)
    bounds = [v for k in range(3) for v in (min(p[k] for p in canonical_points), max(p[k] for p in canonical_points))]
    coverage = math.pi * (radius * development) ** 2 if shoot_count else 0.
    stats = {'moss_turf_version': MOSS_TURF_VERSION, 'moss_shoot_count': shoot_count,
             'moss_branch_count': branch_count, 'moss_represented_leaf_count': leaf_count,
             'moss_patch_area_m2': round(coverage, 9), 'moss_structural_length_m': round(axis_length, 7),
             'moss_geometry_status': 'bounded_representative_ground_turf',
             'moss_reproduction_status': 'spores_and_fragment_regeneration_documented_capsules_unresolved',
             'stem_count': shoot_count, 'branch_count': branch_count, 'estimated_leaf_count': leaf_count,
             'leaf_count': leaf_count, 'leaf_cluster_count': 0, 'leaf_area_m2': round(leaf_area, 9),
             'placement_count': len(placements), 'maturity': development, 'environment': dict(simulation.environment),
             'root_model_status': 'not_applicable_bryophyte_rhizoids_unresolved',
             'root_depth_source': 'not_applicable', 'root_depth_m': 0., 'root_length_m': 0.,
             'root_spread_m': 0., 'root_segment_count': 0, **water}
    return PlantGrowthSnapshot(species_id=simulation.species_id,
        blueprint_fingerprint=simulation.blueprint.fingerprint(), seed=simulation.seed,
        age_days=round(age_days, 3), lod=lod, modules={m.id:m.to_dict() for m in simulation.blueprint.modules},
        placements=placements, bounds_m=bounds, placement_paths=paths,
        placement_orientations=orientations, attachment_points=attachments, stats=stats)


def moss_ecological_outcome(simulation, environment=None):
    env = environment if isinstance(environment, dict) else simulation.environment
    water = moss_water_response(env)
    stats = simulation.render_snapshot.stats
    health = 1 - _finite(env.get('disturbance'), 0., 0., 1.)
    area = stats['moss_patch_area_m2']
    return {'species_id': simulation.species_id, 'age_days': simulation.render_snapshot.age_days,
            'status': 'qualitative_leafy_moss_response', 'vitality': health,
            'growth_rate': water['moss_activity'] * simulation.blueprint.growth.get('growth_rate_bias', .25) * health,
            'structural_biomass_proxy': area * .08 * health, 'standing_biomass_kg': area * .08 * health,
            'biomass_density_source': 'qualitative_moss_area_default', 'resource_demand': area * .02,
            'fecundity': 0., 'reproduction_status': stats['moss_reproduction_status'],
            'mortality_risk': 1 - health, 'leaf_area_proxy': stats['leaf_area_m2'] * water['moss_activity'],
            'estimated_leaf_count': stats['estimated_leaf_count'], 'root_depth_m': 0.,
            'root_length_m': 0., 'root_spread_m': 0., 'root_depth_source': 'not_applicable',
            'root_model_status': stats['root_model_status'],
            'nutrient_model_status': 'surface_wetting_and_deposition_no_vascular_root_access',
            'nitrogen_fixation_status': 'epiphytic_association_rate_unresolved' if simulation.blueprint.growth.get('nitrogen_fixation') == 'associated' else 'not_modelled',
            **water}


def draw_moss_leaf(screen, surface, points, half_width, blade_fraction):
    """Preserve the authored blade and hair-point pixels along the bent leaf."""
    if surface is None or len(points) != 3:
        return False
    import pygame
    from simulations.species.tufted_sedges import draw_blade_asset
    bounds = surface.get_bounding_rect()
    art = surface.subsurface(bounds).copy()
    split = max(1, min(art.get_height() - 1, round(art.get_height() * (1 - blade_fraction))))
    # Base-to-tip artwork: the pale upper strip is the hyaline hair point.
    blade = art.subsurface((0, split, art.get_width(), art.get_height() - split)).copy()
    draw_blade_asset(screen, blade, points[:2], half_width)
    hair = art.subsurface((0, 0, art.get_width(), split)).copy()
    draw_blade_asset(screen, hair, points[1:], max(.5, half_width * .16))
    return True
