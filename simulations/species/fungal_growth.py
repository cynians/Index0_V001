"""Stationary wood colonies with independent, recurring bracket fruiting bodies.

This is a bounded structural lab. Model days, colonisation and fruiting gates
are illustrative calibration, not measured physiology or wood-decay rates.
"""
import math
import random
from copy import deepcopy

FUNGAL_GRAMMAR_VERSION = 2
FUNGAL_WEATHERING_PALETTE_VERSION = 1


def number(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        value = default
    return max(low, min(high, float(value)))


def normalise_profile(profile):
    from world.fungal_traits import validate_fungal_profile
    validate_fungal_profile(profile)
    p = deepcopy(profile)
    fit = p.get("visual_calibration") or {}
    clock = p.get("simulation_calibration") or {}
    def metric(field, default):
        data = p.get(field) or {}
        low = number(data.get("min_m"), .001, .001, 5)
        high = number(data.get("max_m"), 5, low, 5)
        return number(fit.get(field + "_m"), data.get("typical_m", default), low, high)
    sessile = p.get("attachment") == "sessile"
    p["resolved"] = {"cap_width_m": metric("cap_width", .23),
                     "stipe_length_m": 0. if sessile else metric("stipe_length", .035),
                     "stipe_diameter_m": 0. if sessile else metric("stipe_diameter", .025),
                     "body_count": round(number(fit.get("body_count"), 5, 1, 24)),
                     "colony_model_days": number(clock.get("colony_model_days"), 90, 10, 1000),
                     "first_flush_model_days": number(clock.get("first_flush_model_days"), 30, 1, 1000),
                     "flush_cycle_model_days": number(clock.get("flush_cycle_model_days"), 120, 10, 1000)}
    for key in ("body_variant_keys", "cap_width_scale_range", "body_cluster_count"):
        if key in fit:
            p["resolved"][key] = deepcopy(fit[key])
    if 'weathering_palette' in fit:
        p['resolved']['weathering_palette_version'] = FUNGAL_WEATHERING_PALETTE_VERSION
    return p


def fungal_blueprint(entity, species_id):
    if entity["fungal_growth_profile"].get("body_form") in {"pitted_stalked", "sessile_cup"}:
        from simulations.species.ground_fungi import ground_fungal_blueprint
        return ground_fungal_blueprint(entity, species_id)
    from simulations.species.plant_assets import PlantBlueprint, PlantModule
    from world.fungal_traits import FUNGAL_ASSET_FIELDS
    p = normalise_profile(entity["fungal_growth_profile"]); r = p["resolved"]
    anchors = entity.get("fungal_module_anchors") or {}
    modules = [PlantModule("mycelium", "mycelium", length_m=.01, radius_m=.001)]
    for role, field in FUNGAL_ASSET_FIELDS.items():
        anchor = anchors.get(role) or {}
        modules.append(PlantModule(role, role, asset_ref=entity.get(field), length_m=r["cap_width_m"],
            radius_m=r["stipe_diameter_m"] * .5,
            attachment_point=tuple(anchor.get("attachment_point", (.25, .75))),
            growth_axis=tuple(anchor.get("growth_axis", (0., -1.))),
            visual={"depicted_size_m": anchor.get("depicted_size_m", r["cap_width_m"]), "metric_axis": "width"}))
        for key, variant in sorted((anchor.get("variants") or {}).items()):
            if not isinstance(variant,dict) or not variant.get("asset_ref"):
                continue
            modules.append(PlantModule(f"{role}:{key}", role, asset_ref=variant["asset_ref"],
                length_m=r["cap_width_m"], radius_m=r["stipe_diameter_m"]*.5,
                attachment_point=tuple(variant.get("attachment_point",(.25,.75))),
                growth_axis=tuple(variant.get("growth_axis",(0.,-1.))),
                visual={"depicted_size_m":variant.get("depicted_size_m",r["cap_width_m"]),"metric_axis":"width"}))
    maturity = r["colony_model_days"]
    return PlantBlueprint(species_id, str(entity.get("common_name") or entity.get("binomial_name") or species_id),
        modules, root_module_id="mycelium", growth={"shape": "fungus", "growth_form": "fungus",
            "growth_behaviour": "wood_colonising_fungus", "fungal_grammar_version": FUNGAL_GRAMMAR_VERSION,
            "fungal_growth_profile": p, "maturity_days": maturity, "max_height_m": .15,
            "life_history": {"class": "persistent_fungal_colony", "age_limit_days": maturity + 720,
                             "reproductive_start_days": r["first_flush_model_days"], "senescence_start_days": maturity + 720}},
        lod_policy={"0": "one_representative_bracket", "1": "half_brackets", "2": "all_brackets"})


def wood_test_fixture(kind="trunk", material="dead_hardwood"):
    """A diagnostic support; callers choose a compatible material when known."""
    from world.fungal_traits import FUNGAL_SUBSTRATES
    if material not in FUNGAL_SUBSTRATES:
        raise ValueError(f"Unsupported diagnostic wood material: {material}")
    return {"fungal_substrates": [{"id": "wood_test_asset", "material": material,
        "start_m": [0, 0, 0 if kind == "trunk" else .16],
        "end_m": [0, 0, 1.2] if kind == "trunk" else [1.1, 0, .16], "radius_m": .16}],
        "substrate_context_source": "explicit_representative_wood_test_fixture_not_species_trait"}


def normalise_wood(environment):
    values = environment.get("fungal_substrates")
    if not isinstance(values, list):
        return []
    supports = []
    seen = set()
    for i, item in enumerate(values[:12]):
        if not isinstance(item, dict): continue
        start, end = item.get("start_m"), item.get("end_m")
        if not all(isinstance(p, (list, tuple)) and len(p) == 3 and
                   all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in p)
                   for p in (start, end)): continue
        radius = number(item.get("radius_m"), 0, 0, 3)
        if radius <= 0 or math.dist(start, end) < .01: continue
        start, end = ([round(max(-100, min(100, v)), 4) for v in p] for p in (start, end))
        length = math.dist(start, end)
        if not .01 <= length <= 20: continue
        sid = str(item.get("id") or f"wood_{i}")
        if sid in seen: continue
        supports.append({"id": sid, "material": str(item.get("material") or "other_unknown"),
                         "start_m": start, "end_m": end, "radius_m": radius, "length_m": length,
                         "wood_remaining_fraction": number(item.get("wood_remaining_fraction"), 1, 0, 1)})
        support=supports[-1]
        axis_points=item.get("axis_points_m")
        axis_radii=item.get("axis_radii_m")
        if axis_points is not None:
            valid=(isinstance(axis_points,list) and 2<=len(axis_points)<=256
                   and isinstance(axis_radii,list) and len(axis_radii)==len(axis_points)
                   and all(isinstance(p,(list,tuple)) and len(p)==3 and
                           all(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v) and abs(v)<=100 for v in p)
                           for p in axis_points)
                   and all(not isinstance(r,bool) and isinstance(r,(int,float)) and math.isfinite(r) and 0<r<=3 for r in axis_radii))
            if not valid:
                supports.pop();continue
            arc=sum(math.dist(a,b) for a,b in zip(axis_points,axis_points[1:]))
            if not .01<=arc<=20 or any(math.dist(a,b)<1e-6 for a,b in zip(axis_points,axis_points[1:])):
                supports.pop();continue
            support.update(axis_points_m=deepcopy(axis_points),axis_radii_m=list(axis_radii),
                           start_m=list(axis_points[0]),end_m=list(axis_points[-1]),length_m=arc,radius_m=max(axis_radii))
        facing=item.get("attachment_facing_m")
        if isinstance(facing,(list,tuple)) and len(facing)==3 and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in facing):
            if sum(v*v for v in facing)>1e-8:support["attachment_facing_m"]=list(facing)
        for key in ("source_species_id","source_snapshot_fingerprint","source_seed","source_age_days","source_lod",
                    "source_trunk_placement_indices","wound_interval_m","support_source"):
            if key in item:support[key]=deepcopy(item[key])
        seen.add(sid)
    return supports


def fungal_life_state(growth, age):
    r = growth["fungal_growth_profile"]["resolved"]
    maturity = min(1., max(0., age / r["colony_model_days"]))
    age_after_first = age - r["first_flush_model_days"]
    phase = "colonising"; expansion = sporulation = weathering = 0.
    cycle = max(0, int(age_after_first // r["flush_cycle_model_days"]))
    progress = (age_after_first % r["flush_cycle_model_days"]) / r["flush_cycle_model_days"]
    if age_after_first >= 0:
        if progress < .12:
            phase = "emerging"; expansion = .08 + .28 * progress / .12
        elif progress < .35:
            phase = "expanding"; expansion = .36 + .64 * (progress - .12) / .23
        elif progress < .55:
            phase = "sporulating"; expansion = 1.; sporulation = 1.
        elif progress < .72:
            phase = "weathering"; expansion = 1.; weathering = (progress - .55) / .17
        else:
            phase = "between_flushes"
    return {"phase": phase, "maturity": maturity, "flush_index": cycle,
            "fruit_body_expansion": round(expansion, 5), "sporulation_factor": sporulation,
            "reproductive_factor": sporulation, "fruiting_factor": expansion,
            "weathering_factor": round(weathering, 5), "senescence_factor": 0., "active_factor": 1.,
            "clock_source": "illustrative_model_days_not_measured_lifespan"}


def _frame(wood):
    start, end = wood["start_m"], wood["end_m"]
    axis = [(end[i]-start[i])/wood["length_m"] for i in range(3)]
    # Pick a transverse pair perpendicular to the actual wood axis.
    reference = [0, 0, 1] if abs(axis[2]) < .8 else [1, 0, 0]
    a = [axis[1]*reference[2]-axis[2]*reference[1], axis[2]*reference[0]-axis[0]*reference[2], axis[0]*reference[1]-axis[1]*reference[0]]
    n = math.sqrt(sum(v*v for v in a)); a = [v/n for v in a]
    b = [axis[1]*a[2]-axis[2]*a[1], axis[2]*a[0]-axis[0]*a[2], axis[0]*a[1]-axis[1]*a[0]]
    return axis, a, b


def wood_axis_sample(wood, fraction):
    if wood.get("axis_points_m"):
        from simulations.species.fungal_tree_support import sample_axis
        point,radius,tangent=sample_axis(wood["axis_points_m"],wood["axis_radii_m"],fraction*wood["length_m"])
        local={"start_m":point,"end_m":[point[i]+tangent[i] for i in range(3)],"length_m":1.}
        axis,a,b=_frame(local)
        return point,radius,axis,a,b
    axis,a,b=_frame(wood)
    return [wood["start_m"][i]+axis[i]*wood["length_m"]*fraction for i in range(3)],wood["radius_m"],axis,a,b


def build_fungal_snapshot(sim, age, lod):
    if sim.blueprint.growth.get("ground_fungal_version"):
        from simulations.species.ground_fungi import build_ground_fungal_snapshot
        return build_ground_fungal_snapshot(sim, age, lod)
    from simulations.species.plant_assets import PlantGrowthSnapshot
    p = sim.blueprint.growth["fungal_growth_profile"]; r = p["resolved"]
    state = fungal_life_state(sim.blueprint.growth, age); maturity = state["maturity"]
    woods = normalise_wood(sim.environment)
    moisture = number(sim.environment.get("fungal_moisture"), 1, 0, 1)
    fruiting_allowed = bool(sim.environment.get("fungal_fruiting_enabled", True)) and moisture > 0
    placements = []; paths = {}; attachments = []; bodies = []; points = []
    volume = 0.; canonical_nodes = 0; active_supports = 0
    for support_index, wood in enumerate(woods):
        start, end = wood["start_m"], wood["end_m"]; radius = wood["radius_m"]
        points.extend(tuple(v + offset * radius for v in pt) for pt in wood.get("axis_points_m",(start,end)) for offset in (-1,1))
        if wood["material"] not in p["substrates"] or wood["wood_remaining_fraction"] <= 0: continue
        active_supports += 1
        axis, a, b = _frame(wood)
        colonised = maturity * wood["wood_remaining_fraction"]
        if wood.get("axis_points_m"):
            volume += sum(math.pi*r*r*math.dist(a,b) for a,b,r in zip(wood["axis_points_m"],wood["axis_points_m"][1:],wood["axis_radii_m"][1:]))*colonised
        else:
            volume += math.pi * radius**2 * wood["length_m"] * colonised
        canonical_nodes += 33 if colonised > 0 else 0
        # One bounded diagnostic network inside wood, never soil roots.
        host = -1
        if colonised > 0:
            for branch in range(3 if lod == 2 else 1):
                previous = -1
                for node in range(11):
                    t = .05 + .9 * colonised * node / 10
                    center,local_radius,_,radial_a,radial_b=wood_axis_sample(wood,t)
                    position = [center[i]+radial_a[i]*math.sin(node*.9+branch)*local_radius*.32 +
                                radial_b[i]*math.cos(node*.7+branch)*local_radius*.25 for i in range(3)]
                    idx = len(placements)
                    placements.append(["mycelium", previous, *[round(v, 4) for v in position], 0., colonised, 0])
                    if previous >= 0: paths[str(idx)] = [placements[previous][2:5], placements[idx][2:5]]
                    if host < 0: host = idx
                    previous = idx
        if not fruiting_allowed or state["fruit_body_expansion"] <= 0 or colonised <= 0: continue
        count = max(1, round(r["body_count"] * colonised))
        visible = {round(i*(count-1)/max(1, (1 if lod == 0 else math.ceil(count/2) if lod == 1 else count)-1))
                   for i in range(1 if lod == 0 else math.ceil(count/2) if lod == 1 else count)}
        rng = random.Random(f"{sim.seed}:{wood['id']}:{state['flush_index']}")
        variation_rng = random.Random(f"{sim.seed}:{wood['id']}:{state['flush_index']}:variation")
        variant_keys = r.get("body_variant_keys", [])
        variant_offset = variation_rng.randrange(len(variant_keys)) if variant_keys else 0
        groups = r.get("body_cluster_count")
        group_positions = [(.3 + .42*g/max(1,groups-1) + variation_rng.uniform(-.07,.07),
                            variation_rng.uniform(-1.1,1.1)) for g in range(groups)] if groups else []
        for ordinal in range(count):
            t = .25 + .42 * ordinal / max(1, r["body_count"]-1) + rng.uniform(-.035, .035)
            # A front-facing transverse attachment; the support's position,
            # orientation and radius determine the real substrate socket.
            theta = -.7 + ordinal * .32 + rng.uniform(-.12, .12)
            if groups:
                t,theta = group_positions[(ordinal//2)%groups]
                t = max(.15,min(.85,t + (ordinal%2-.5)*.045 + variation_rng.uniform(-.012,.012)))
                theta += (ordinal%2-.5)*.4 + variation_rng.uniform(-.1,.1)
            center,local_radius,axis,a,b=wood_axis_sample(wood,t)
            if wood.get("attachment_facing_m"):
                facing=wood["attachment_facing_m"]
                theta=math.atan2(sum(facing[i]*b[i] for i in range(3)),sum(facing[i]*a[i] for i in range(3)))+theta*.12
            normal = [a[i]*math.cos(theta) + b[i]*math.sin(theta) for i in range(3)]
            position = [center[i]+normal[i]*local_radius for i in range(3)]
            width = r["cap_width_m"] * (.76 + rng.random()*.24) * state["fruit_body_expansion"]
            if "cap_width_scale_range" in r:
                dimension = p.get("cap_width") or {}
                full_width = r["cap_width_m"]*variation_rng.uniform(*r["cap_width_scale_range"])
                width = max(dimension.get("min_m",.001),min(dimension.get("max_m",5),full_width))*state["fruit_body_expansion"]
            body = {"id": f"{wood['id']}:{state['flush_index']}:{ordinal}", "substrate_id": wood["id"],
                    "socket_m": [round(v, 4) for v in position], "normal": normal,
                    "cap_width_m": width, "weathering_factor": state["weathering_factor"],
                    "sporulation_factor": state["sporulation_factor"], "placement_index": None}
            if variant_keys:
                body["variant_key"] = variant_keys[(ordinal+variant_offset)%len(variant_keys)]
            body.update(substrate_axis_fraction=t,substrate_center_m=center,substrate_radius_m=local_radius)
            direction = [normal[i]*.6 + (.8 if i == 2 else 0) for i in range(3)]
            norm = math.sqrt(sum(v*v for v in direction))
            stem_length = r["stipe_length_m"] * state["fruit_body_expansion"]
            cap_socket = [position[i]+direction[i]/norm*stem_length for i in range(3)]
            body.update(cap_socket_m=cap_socket, stipe_length_m=stem_length,
                        stipe_diameter_m=r["stipe_diameter_m"]*state["fruit_body_expansion"])
            center = [cap_socket[i]+normal[i]*width*.24 for i in range(3)]
            points.extend((tuple(center[i]-width*.6 for i in range(3)), tuple(center[i]+width*.6 for i in range(3))))
            if ordinal in visible:
                idx = len(placements); body["placement_index"] = idx
                placements.append(["fruiting_body", host, *body["socket_m"], 0., width/r["cap_width_m"], 1])
                attachments.append({"placement_index": idx, "host_placement_index": host,
                                    "socket": "wood_surface", "substrate_id": wood["id"], "position_m": body["socket_m"]})
            bodies.append(body)
    bounds = [v for axis in range(3) for v in (min((pt[axis] for pt in points), default=0), max((pt[axis] for pt in points), default=.01))]
    stats = {"maturity": maturity, "life_phase": state["phase"], "life_state": state,
             "fungal_substrates": woods, "substrate_context_source": sim.environment.get("substrate_context_source", "supplied"),
             "fungal_bodies": bodies, "fungal_active_substrate_count": active_supports,
             "colonised_wood_volume_proxy_m3": round(volume, 7), "canonical_mycelium_node_count": canonical_nodes,
             "estimated_fruiting_body_count": len(bodies), "visible_fruiting_body_count": sum(b["placement_index"] is not None for b in bodies),
             "sporulating_area_proxy_m2": round(sum(math.pi*(b["cap_width_m"]*.5)**2*.65*b["sporulation_factor"] for b in bodies), 7),
             "root_segment_count": 0, "root_length_m": 0., "root_depth_m": 0., "leaf_count": 0,
             "estimated_leaf_count": 0, "leaf_area_m2": 0., "stem_count": 0, "branch_count": 0,
             "leaf_cluster_count": 0, "placement_count": len(placements)}
    return PlantGrowthSnapshot(sim.species_id, sim.blueprint.fingerprint(), sim.seed, age, lod,
        {m.id:m.to_dict() for m in sim.blueprint.modules}, placements, bounds,
        placement_paths=paths, attachment_points=attachments, stats=stats)


def fungal_ecological_outcome(sim, environment=None):
    if sim.blueprint.growth.get("ground_fungal_version"):
        from simulations.species.ground_fungi import ground_fungal_ecological_outcome
        return ground_fungal_ecological_outcome(sim, environment)
    from types import SimpleNamespace
    environment = {**sim.environment, **(environment or {})}
    context = SimpleNamespace(environment=environment, blueprint=sim.blueprint, species_id=sim.species_id, seed=sim.seed)
    snap = build_fungal_snapshot(context, sim.age_days, sim.lod)
    stats = snap.stats
    vitality = min(1., stats["colonised_wood_volume_proxy_m3"] / .05) * (1-number(environment.get("fungal_drought_stress"), 0, 0, 1))
    return {"species_id": sim.species_id, "age_days": sim.age_days, "maturity": stats["maturity"],
        "vitality": round(vitality, 5), "growth_rate": round(vitality * (1-stats["maturity"]), 5),
        "fecundity": round(vitality * min(1., stats["sporulating_area_proxy_m2"]/.1), 5),
        "mortality_risk": round(1-vitality, 5), "leaf_area_proxy": 0., "photosynthesis_proxy": 0.,
        "resource_demand": round(vitality*.05, 5), "wood_decay_activity_proxy": round(vitality, 5),
        "colonised_wood_volume_proxy_m3": stats["colonised_wood_volume_proxy_m3"],
        "estimated_fruiting_body_count": stats["estimated_fruiting_body_count"],
        "sporulating_area_proxy_m2": stats["sporulating_area_proxy_m2"],
        "wood_decay_rate_source": "unknown_no_mass_or_nutrient_flux_implemented"}
