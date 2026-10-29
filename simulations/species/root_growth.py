"""Bounded root architecture proxies, independent of shoot RNG and rendering.

Depth-class dimensions and stature-scaled fallbacks are runtime assumptions,
never botanical measurements.
The graph describes representative axes, not every absorptive root or root hair.
"""
import math
import random


def shallow_radial_profile(value):
    """Opt-in root envelope: a tap plus shallow lateral axes, independently sized."""
    if not isinstance(value,dict) or value.get('form') != 'shallow_radial':
        return None
    ranges={'tap_depth_m':(.01,3.),'lateral_depth_m':(.005,.4),'spread_radius_m':(.02,30.)}
    for key,(lo,hi) in ranges.items():
        n=value.get(key)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not lo <= n <= hi:
            return None
    count=value.get('radial_axes')
    if isinstance(count,bool) or not isinstance(count,int) or not 3 <= count <= 16:
        return None
    if value['lateral_depth_m'] > value['tap_depth_m']:
        return None
    return {'form':'shallow_radial','version':1,**{k:float(value[k]) for k in ranges},
            'radial_axes':count,'status':str(value.get('status') or 'provisional_root_envelope')}


def root_profile(growth):
    architecture = str(growth.get("root_architecture") or "").lower()
    radial=growth.get('shallow_radial_profile')
    if radial and architecture == 'mixed':
        return {'architecture':'mixed','depth_class':'shallow', 'target_depth_m':radial['tap_depth_m'],
                'target_spread_radius_m':radial['spread_radius_m'], 'depth_source':radial['status'],
                'spread_source':radial['status'],'grammar_version':8,'support':'stem_base',
                'shallow_radial_profile':radial}
    depth_class = str(growth.get("root_depth_class") or "").lower()
    depth = {"shallow": 0.35, "intermediate": 1.0, "deep": 2.0}.get(depth_class, 0.6)
    source = "depth_class_default" if depth_class in {"shallow", "intermediate", "deep"} else "runtime_default"
    authored = growth.get("max_root_depth")
    if isinstance(authored, dict):
        value = authored.get("max_m", authored.get("value_m"))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            depth, source = float(value), "authored_max_root_depth"
    max_height = growth.get("max_height_m")
    valid_height = (isinstance(max_height, (int, float)) and not isinstance(max_height, bool)
                    and math.isfinite(max_height) and max_height > 0)
    if source == "runtime_default" and valid_height:
        # An unknown root envelope should not give a dwarf herb the same
        # 60 cm depth as a metre-scale plant. Scale only the unsupported
        # fallback; a supplied depth/class still wins, including deep roots
        # on short plants. Mature stature avoids tying roots to seasonal
        # shoot loss. The coefficient and bounds are qualitative budgets.
        scaled_depth = max(.05, min(.6, float(max_height) * .75))
        if scaled_depth < depth:
            depth, source = scaled_depth, "stature_scaled_runtime_default"
    architecture_key = architecture if architecture in {"taproot", "fibrous", "adventitious", "mixed"} else "other_unknown"
    spread_coefficient = {
        "taproot": 0.65, "fibrous": 0.85, "adventitious": 0.8, "mixed": 1.25,
    }.get(architecture_key, 1.0)
    target_spread_radius = depth * spread_coefficient
    spread_source = "depth_architecture_default"
    # Depth and lateral reach need separate fallbacks for compact, deep-rooted
    # forbs. Deriving both from depth gave a 35 cm lupine and a metre-scale
    # chicory the same 2.6 m-wide root envelope. This is a bounded display
    # proxy, not a measured lateral root extent; an authored profile wins.
    if (architecture_key == "taproot" and growth.get("growth_form") == "forb"
            and growth.get("plant_woodiness") == "herbaceous" and valid_height):
        stature_radius = max(0.05, float(max_height) * 0.65)
        if stature_radius < target_spread_radius:
            target_spread_radius = stature_radius
            spread_source = "bounded_forb_taproot_proxy"
    # Rooting depth and lateral reach are different dimensions. Deriving both
    # from depth alone made a 110 m tree's mature root system only ~5 m wide.
    # Large trees now get a bounded, height-aware lateral envelope while the
    # authored depth remains untouched. The threshold is implicit in max():
    # ordinary trees retain the established depth/architecture result exactly.
    if (growth.get("shape") == "tree"
            and valid_height):
        height_scaled_radius = min(35.0, float(max_height) * 0.12)
        if height_scaled_radius > target_spread_radius:
            target_spread_radius = height_scaled_radius
            spread_source = "bounded_tree_height_proxy"
    return {"architecture": architecture if architecture in {"taproot", "fibrous", "adventitious", "mixed"} else "other_unknown",
            "depth_class": depth_class or "other_unknown", "target_depth_m": depth,
            "depth_source": source, "target_spread_radius_m": target_spread_radius,
            "spread_source": spread_source,
            "grammar_version": (8 if spread_source == "bounded_forb_taproot_proxy" else
                                7 if architecture_key != "other_unknown" else
                                6 if source == "stature_scaled_runtime_default" else 5),
            "support": "rhizome" if growth.get("shape") == "aquatic" or growth.get("growth_behaviour") == "rhizomatous_clonal" else "stem_base"}


def build_distributed_adventitious_roots(profile, maturity, seed, contacts):
    """Build one bounded root cluster at every established stem contact.

    ``contacts`` contains absolute ``position`` values and placement
    ``parent_index`` values.  Returned root-node positions are relative to the
    corresponding contact; integer parents refer to earlier returned nodes.
    This keeps root development independent of the shoot grammar while letting
    any stoloniferous or rhizomatous plant reuse the same contact-root rule.
    """
    architecture = str(profile.get("architecture") or "other_unknown")
    if architecture != "adventitious" or not contacts:
        return [], {
            "root_architecture": architecture,
            "root_depth_source": profile.get("depth_source", "runtime_default"),
            "root_depth_m": 0.0,
            "root_spread_m": 0.0,
            "root_length_m": 0.0,
            "root_segment_count": 0,
            "root_support_node_count": 0,
            "root_cluster_count": 0,
            "root_cluster_spread_m": 0.0,
            "root_system_span_m": 0.0,
            "root_distribution": "unresolved",
            "root_model_status": "unresolved",
        }

    age = max(0.0, min(1.0, float(maturity)))
    target_depth = max(0.01, float(profile.get("target_depth_m", 0.6) or 0.6))
    developed_depth = target_depth * age
    primary_count = max(1, math.ceil(4 * age))
    lateral_elongation = max(0.0, min(1.0, (age - 0.15) / 0.45))
    nodes = []
    absolute_positions = []
    local_radii = []

    def add_axis(contact_index, parent, start, end, order, thickness, segments):
        chain = []
        for segment_index in range(1, segments + 1):
            t = segment_index / segments
            horizontal_t = math.sin(t * math.pi / 2)
            vertical_t = t ** 1.18
            point = tuple(
                start[axis] + (end[axis] - start[axis])
                * (vertical_t if axis == 2 else horizontal_t)
                for axis in range(3)
            )
            nodes.append({
                "parent": parent,
                "contact_index": contact_index,
                "position": point,
                "order": order,
                "kind": "root_section",
                "thickness": thickness * (1.0 - 0.82 * t),
            })
            parent = len(nodes) - 1
            chain.append(parent)
        return chain

    for contact_index, contact in enumerate(contacts):
        contact_position = tuple(float(value) for value in contact["position"])
        # A submerged rhizome has already used some of the authored vertical
        # envelope.  Limiting the remaining descent keeps max_root_depth a
        # whole-plant ceiling rather than multiplying it at every node.
        remaining_depth = max(0.0, developed_depth - max(0.0, -contact_position[2]))
        phase_rng = random.Random(int(seed) ^ 0x6C31 ^ (contact_index * 104729))
        phase = phase_rng.random() * math.tau
        for axis_index in range(primary_count):
            axis_rng = random.Random(
                int(seed) ^ 0x7319 ^ (contact_index * 104729) ^ (axis_index * 7919)
            )
            angle = phase + axis_index * 2.399963229728653
            elongation = (1. if axis_index == 0 else
                          max(0., min(1., (age-axis_index/4)/(1-axis_index/4))))
            horizontal_reach = developed_depth * axis_rng.uniform(0.28, 0.58) * elongation
            vertical_reach = remaining_depth * (
                1.0 if axis_index == 0 else axis_rng.uniform(0.52, 0.88)
            ) * elongation
            end = (
                math.cos(angle) * horizontal_reach,
                math.sin(angle) * horizontal_reach,
                -vertical_reach,
            )
            chain = add_axis(contact_index, -1, (0.0, 0.0, 0.0), end, 0, 0.72, 4)
            if lateral_elongation <= 0.0:
                continue
            host = chain[2]
            host_point = nodes[host]["position"]
            side = angle + (-1.0 if axis_index % 2 else 1.0) * 1.05
            lateral_length = developed_depth * 0.18 * lateral_elongation * elongation
            lateral_end = (
                host_point[0] + math.cos(side) * lateral_length,
                host_point[1] + math.sin(side) * lateral_length,
                max(-remaining_depth, host_point[2] - remaining_depth * 0.08 * lateral_elongation * elongation),
            )
            add_axis(contact_index, host, host_point, lateral_end, 1, 0.27, 3)

    total_length = 0.0
    for index, node in enumerate(nodes):
        contact_position = tuple(float(value) for value in contacts[node["contact_index"]]["position"])
        parent_position = (
            nodes[node["parent"]]["position"] if node["parent"] >= 0 else (0.0, 0.0, 0.0)
        )
        total_length += math.dist(node["position"], parent_position)
        absolute = tuple(contact_position[axis] + node["position"][axis] for axis in range(3))
        absolute_positions.append(absolute)
        local_radii.append(math.hypot(node["position"][0], node["position"][1]))

    contact_positions = [tuple(float(value) for value in contact["position"]) for contact in contacts]
    all_positions = contact_positions + absolute_positions
    x_values = [point[0] for point in all_positions]
    y_values = [point[1] for point in all_positions]
    max_radius = max(math.hypot(point[0], point[1]) for point in all_positions)
    return nodes, {
        "root_architecture": architecture,
        "root_depth_source": profile.get("depth_source", "runtime_default"),
        "root_depth_m": round(max(0.0, -min(point[2] for point in all_positions)), 4),
        "root_spread_m": round(2.0 * max_radius, 4),
        "root_length_m": round(total_length, 4),
        "root_segment_count": len(nodes),
        "root_support_node_count": len(contacts),
        "root_cluster_count": len(contacts),
        "root_cluster_spread_m": round(2.0 * max(local_radii, default=0.0), 4),
        "root_system_span_m": round(max(max(x_values) - min(x_values), max(y_values) - min(y_values)), 4),
        "root_distribution": "contact_nodes",
        "root_model_status": "distributed_adventitious_proxy",
    }


def build_root_graph(profile, maturity, seed):
    """Return parent-first relative nodes; -1 denotes the existing root crown."""
    if profile.get('shallow_radial_profile'):
        return build_shallow_radial_roots(profile, maturity, seed)
    architecture = profile["architecture"]
    if architecture == "other_unknown":
        return [], {"root_architecture": architecture, "root_depth_source": profile["depth_source"],
                    "root_depth_m": 0.0, "root_spread_m": 0.0, "root_length_m": 0.0,
                    "root_segment_count": 0, "root_model_status": "unresolved"}
    rng = random.Random(int(seed) ^ 0x5A17)
    age = max(0.0, min(1.0, float(maturity)))
    # Use the same structural age clock as shoots. The former concave curve
    # gave a 10%-mature seedling 24% of its final root depth. Separate axes
    # now emerge and elongate from their sockets rather than appearing long.
    development = age
    depth = profile["target_depth_m"] * development
    default_spread = profile["target_depth_m"] * {
        "taproot": 0.65, "fibrous": 0.85, "adventitious": 0.8, "mixed": 1.25,
    }[architecture]
    spread = float(profile.get("target_spread_radius_m", default_spread)) * development
    nodes = []

    def axis(parent, end, order, thickness, kind="root_section"):
        start = nodes[parent]["position"] if parent >= 0 else (0.0, 0.0, 0.0)
        chain = []
        for i in range(1, 6):
            t = i / 5
            horizontal_t = math.sin(t * math.pi / 2) if kind == "root_section" else t
            vertical_t = t ** 1.25 if kind == "root_section" else t
            point = tuple(start[j] + (end[j] - start[j]) * (vertical_t if j == 2 else horizontal_t) for j in range(3))
            nodes.append({"parent": parent, "position": point, "order": order,
                          "kind": kind, "thickness": thickness * (1 - (0.94 if kind == "root_section" else 0.65) * t)})
            parent = len(nodes) - 1
            chain.append(parent)
        return chain

    phase = rng.random() * math.tau
    if architecture in {"taproot", "mixed"}:
        main = axis(-1, (depth * 0.04, 0.0, -depth), 0, 1.5)
        mature_count = 10
        count = max(1, math.ceil(mature_count * age))
        origins = [main[i % 4] for i in range(count)]
    elif architecture == "adventitious":
        # The supporting stem remains a separate module; roots begin at its
        # nodes rather than embedding a rhizome in a root asset.
        reach = depth * (1.1 if profile.get("support") == "rhizome" else 0.22)
        supports = []
        for side in (-1, 1):
            supports.extend(axis(-1, (side * reach, 0.0, 0.0), 0, 1.4, "root_support"))
        mature_count = 16
        count = max(1, math.ceil(mature_count * age))
        origins = [supports[(i * 3) % len(supports)] for i in range(count)]
    else:
        mature_count = 16
        count = max(1, math.ceil(mature_count * age))
        origins = [-1] * count
    for i, parent in enumerate(origins):
        # Per-axis randomness prevents newly emerging fine roots from
        # consuming random values previously used by another primary axis.
        rng = random.Random(int(seed) ^ (0x1F31 + i * 7919))
        angle = phase + i * 2.39996
        reach = spread * rng.uniform(0.55, 1.0)
        start = nodes[parent]["position"] if parent >= 0 else (0, 0, 0)
        onset = i / mature_count
        axis_elongation = (1. if i == 0 and architecture in {"fibrous", "adventitious"} else
                           max(0., min(1., (age-onset)/(1-onset))))
        end = (start[0] + math.cos(angle) * reach, start[1] + math.sin(angle) * reach,
               -depth * (1.0 if i == 0 else 0.55 + 0.45 * rng.random()))
        end = (end[0], end[1], min(end[2], start[2] - depth * 0.08))
        end = tuple(start[j] + (end[j]-start[j])*axis_elongation for j in range(3))
        order = 1 if architecture in {"taproot", "mixed"} else 0
        chain = axis(parent, end, order, 0.7)
        if age > 0.15:
            for host in chain[1:4]:
                point = nodes[host]["position"]
                side = angle + rng.choice((-1, 1)) * 0.9
                elongation = min(1.0, (age - 0.15) / 0.35)
                length = math.hypot(end[0]-start[0], end[1]-start[1]) * 0.22 * elongation
                axis(host, (point[0] + math.cos(side) * length,
                            point[1] + math.sin(side) * length,
                            max(-depth, point[2] - depth * 0.12 * elongation * axis_elongation)), order + 1, 0.25)
    positions = [(0.0, 0.0, 0.0)] + [n["position"] for n in nodes]
    total_length = sum(math.dist(n["position"], nodes[n["parent"]]["position"] if n["parent"] >= 0 else (0, 0, 0)) for n in nodes if n["kind"] == "root_section")
    stats = {"root_architecture": architecture, "root_depth_source": profile["depth_source"],
             "root_depth_m": round(-min(p[2] for p in positions), 4),
             "root_spread_m": round(2 * max(math.hypot(p[0], p[1]) for p in positions), 4),
             "root_length_m": round(total_length, 4), "root_segment_count": sum(n["kind"] == "root_section" for n in nodes),
             "root_support_node_count": sum(n["kind"] == "root_support" for n in nodes),
             "root_model_status": "architectural_proxy"}
    return nodes, stats


def build_shallow_radial_roots(profile, maturity, seed):
    """Bounded representative axes; all lengths emerge continuously from zero."""
    p=profile['shallow_radial_profile'];fraction=max(0.,min(1.,float(maturity)))
    nodes=[]
    def axis(parent,start,end,order,thickness):
        for k in range(1,8):
            t=k/7
            point=tuple(start[a]+(end[a]-start[a])*t for a in range(3))
            nodes.append({'parent':parent,'position':point,'order':order,'kind':'root_section',
                          'thickness':thickness*(1-.85*t)})
            parent=len(nodes)-1
    axis(-1,(0,0,0),(0,0,-p['tap_depth_m']*fraction),0,1.1)
    phase=random.Random(seed ^ 0x1683).random()*math.tau
    for i in range(p['radial_axes']):
        onset=i*.05
        progress=max(0.,(fraction-onset)/(1-onset))
        if not progress:
            continue
        angle=phase+i*math.tau/p['radial_axes']
        reach=p['spread_radius_m']*progress
        end=(math.cos(angle)*reach,math.sin(angle)*reach,-p['lateral_depth_m']*progress)
        axis(-1,(0,0,0),end,1,.7)
    positions=[(0,0,0)]+[n['position'] for n in nodes]
    length=sum(math.dist(n['position'],nodes[n['parent']]['position'] if n['parent'] >= 0 else (0,0,0)) for n in nodes)
    return nodes, {'root_architecture':'mixed','root_depth_source':profile['depth_source'],
                   'root_depth_m':round(-min(v[2] for v in positions),6),
                   'root_spread_m':round(2*max(math.hypot(v[0],v[1]) for v in positions),6),
                   'root_length_m':round(length,6),'root_segment_count':len(nodes),
                   'root_model_status':'shallow_radial_architectural_proxy',
                   'root_distribution':'shallow_radial_with_tap',
                   'root_lateral_depth_m':round(p['lateral_depth_m']*fraction,6)}


def build_mixed_contact_roots(profile, maturity, seed, contacts):
    """Retain a primary root and add shallow roots at grounded woody axes.

    Contact zero is the original crown. Up to 16 established contacts are
    represented; their depth is a bounded proxy, never a field measurement.
    All returned nodes use the distributed-root contact convention.
    """
    nodes, stats = build_root_graph(profile, maturity, seed)
    for node in nodes:
        node["contact_index"] = 0
    if float(maturity) < 0.25 or len(contacts) < 2:
        return nodes, stats
    local_profile = {**profile, "architecture": "adventitious",
                     "target_depth_m": float(profile["target_depth_m"])*0.35}
    extra, local_stats = build_distributed_adventitious_roots(local_profile, maturity, seed, contacts[1:])
    offset = len(nodes)
    for node in extra:
        node["contact_index"] += 1
        if node["parent"] >= 0:
            node["parent"] += offset
    nodes.extend(extra)
    positions = [tuple(contacts[n["contact_index"]]["position"][a]+n["position"][a] for a in range(3)) for n in nodes]
    stats.update({
        "root_architecture": "mixed", "root_model_status": "primary_and_contact_root_proxy",
        "root_distribution": "crown_and_contact_nodes", "root_cluster_count": len(contacts),
        "root_segment_count": len(nodes), "root_length_m": round(stats["root_length_m"]+local_stats["root_length_m"],4),
        "root_depth_m": round(max(0.0,-min(p[2] for p in positions)),4),
        "root_spread_m": round(2*max(math.hypot(p[0],p[1]) for p in positions),4),
        "root_contact_depth_source": "bounded_fraction_of_root_depth_proxy",
    })
    return nodes, stats
