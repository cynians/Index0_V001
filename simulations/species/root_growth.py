"""Bounded root architecture proxies, independent of shoot RNG and rendering.

Depth-class dimensions are runtime assumptions, never botanical measurements.
The graph describes representative axes, not every absorptive root or root hair.
"""
import math
import random


def root_profile(growth):
    architecture = str(growth.get("root_architecture") or "").lower()
    depth_class = str(growth.get("root_depth_class") or "").lower()
    depth = {"shallow": 0.35, "intermediate": 1.0, "deep": 2.0}.get(depth_class, 0.6)
    source = "depth_class_default" if depth_class in {"shallow", "intermediate", "deep"} else "runtime_default"
    authored = growth.get("max_root_depth")
    if isinstance(authored, dict):
        value = authored.get("max_m", authored.get("value_m"))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            depth, source = float(value), "authored_max_root_depth"
    return {"architecture": architecture if architecture in {"taproot", "fibrous", "adventitious", "mixed"} else "other_unknown",
            "depth_class": depth_class or "other_unknown", "target_depth_m": depth,
            "depth_source": source, "grammar_version": 2,
            "support": "rhizome" if growth.get("shape") == "aquatic" or growth.get("growth_behaviour") == "rhizomatous_clonal" else "stem_base"}


def build_root_graph(profile, maturity, seed):
    """Return parent-first relative nodes; -1 denotes the existing root crown."""
    architecture = profile["architecture"]
    if architecture == "other_unknown":
        return [], {"root_architecture": architecture, "root_depth_source": profile["depth_source"],
                    "root_depth_m": 0.0, "root_spread_m": 0.0, "root_length_m": 0.0,
                    "root_segment_count": 0, "root_model_status": "unresolved"}
    rng = random.Random(int(seed) ^ 0x5A17)
    age = max(0.0, min(1.0, float(maturity)))
    depth = profile["target_depth_m"] * (0.025 + 0.975 * age ** 0.65)
    spread = depth * {"taproot": 0.65, "fibrous": 0.85, "adventitious": 0.8, "mixed": 1.25}[architecture]
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
                          "kind": kind, "thickness": thickness * (1 - 0.65 * t)})
            parent = len(nodes) - 1
            chain.append(parent)
        return chain

    phase = rng.random() * math.tau
    if architecture in {"taproot", "mixed"}:
        main = axis(-1, (depth * 0.04, 0.0, -depth), 0, 1.5)
        count = max(2, round(3 + 7 * age))
        origins = [main[i % 4] for i in range(count)]
    elif architecture == "adventitious":
        # The supporting stem remains a separate module; roots begin at its
        # nodes rather than embedding a rhizome in a root asset.
        reach = depth * (1.1 if profile.get("support") == "rhizome" else 0.22)
        supports = []
        for side in (-1, 1):
            supports.extend(axis(-1, (side * reach, 0.0, 0.0), 0, 1.4, "root_support"))
        count = max(2, round(2 + 14 * age))
        origins = [supports[(i * 3) % len(supports)] for i in range(count)]
    else:
        count = max(2, round(2 + 14 * age))
        origins = [-1] * count
    for i, parent in enumerate(origins):
        # Per-axis randomness prevents newly emerging fine roots from
        # consuming random values previously used by another primary axis.
        rng = random.Random(int(seed) ^ (0x1F31 + i * 7919))
        angle = phase + i * 2.39996
        reach = spread * rng.uniform(0.55, 1.0)
        start = nodes[parent]["position"] if parent >= 0 else (0, 0, 0)
        end = (start[0] + math.cos(angle) * reach, start[1] + math.sin(angle) * reach,
               -depth * (1.0 if i == 0 else 0.55 + 0.45 * rng.random()))
        end = (end[0], end[1], min(end[2], start[2] - depth * 0.08))
        order = 1 if architecture in {"taproot", "mixed"} else 0
        chain = axis(parent, end, order, 0.7)
        if age > 0.15:
            for host in chain[1:4]:
                point = nodes[host]["position"]
                side = angle + rng.choice((-1, 1)) * 0.9
                elongation = min(1.0, (age - 0.15) / 0.35)
                length = reach * 0.22 * elongation
                axis(host, (point[0] + math.cos(side) * length,
                            point[1] + math.sin(side) * length,
                            max(-depth, point[2] - depth * 0.12 * elongation)), order + 1, 0.25)
    positions = [(0.0, 0.0, 0.0)] + [n["position"] for n in nodes]
    total_length = sum(math.dist(n["position"], nodes[n["parent"]]["position"] if n["parent"] >= 0 else (0, 0, 0)) for n in nodes if n["kind"] == "root_section")
    stats = {"root_architecture": architecture, "root_depth_source": profile["depth_source"],
             "root_depth_m": round(-min(p[2] for p in positions), 4),
             "root_spread_m": round(2 * max(math.hypot(p[0], p[1]) for p in positions), 4),
             "root_length_m": round(total_length, 4), "root_segment_count": sum(n["kind"] == "root_section" for n in nodes),
             "root_support_node_count": sum(n["kind"] == "root_support" for n in nodes),
             "root_model_status": "architectural_proxy"}
    return nodes, stats
