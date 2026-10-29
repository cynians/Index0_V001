"""Woody crown with current shoots and node-based foliage cohorts.

Foliage is stored as ``leaf_clusters`` (a calculative cohort: estimated leaf
count, leaf area, position) rather than one simulation object per leaf. By
default (``detail=False``) a shoot also collapses to a single coarse spine
segment instead of one segment per leaf, since a mature crown otherwise
generates thousands of near-identical structural placements purely to give
per-leaf sprites somewhere to hang. ``detail=True`` reruns the exact same
per-leaf geometry used originally (full spine subdivision, one placement per
leaf) and is reserved for close-up diagnostics that need authentic shoot
geometry, not for the default whole-tree/forest render path.
"""
import math
import random
from simulations.species.forest_ecology import branch_response
from simulations.species.woody_axes import mature_axis_blend, trunk_radius


def has_young_conical_crown(growth):
    """Trait combination whose pyramidal habit is expressed before maturity."""
    return growth.get("branching_rhythm") == "rhythmic" and growth.get("crown_shape") == "conical"


def grow_tree_shoots(sim, placements, maturity, lod, clusters, attachments, paths, flowering_factor=0., fruiting_factor=0., detail=False, leaf_factor=1.):
    g = sim.blueprint.growth
    leaf_factor = float(leaf_factor)
    leaf_factor = max(0., min(1., leaf_factor)) if math.isfinite(leaf_factor) else 1.
    h = float(g["max_height_m"]) * max(.025, maturity)
    def trait(name, default):
        value = g.get(name)
        return max(0., min(1., float(default if value is None else value)))
    openness, droop = trait("crown_openness",.5), trait("branch_droop",.3)
    branch_angle_gradient = trait("branch_angle_gradient", .5)
    density, twig_density = trait("leaf_cluster_density",.5), trait("fine_twig_density",.5)
    spacing = trait("leaf_spacing_bias",.5)
    apical_control = trait("apical_control", .72)
    trunk_girth = trait("trunk_girth", 0.0)
    axes_profile = g.get("woody_axes_profile")
    decurrent = g.get("branching_subpattern") == "decurrent_scaffold"
    tiered_conifer = g.get("branching_subpattern") == "tiered_conifer"
    pendant = g.get('branching_subpattern') == 'pendant_branchlets'
    pendant_axes = []
    planar = bool(g.get('planar_spray_version'))
    planar_systems = []
    scaffold_blend = mature_axis_blend(maturity) if decurrent else 0.0
    trunk_irregularity = 1.0 - trait("trunk_straightness", 0.0)
    distribution = g.get("leaf_distribution", "along_shoot")
    dimorphic = g.get("shoot_dimorphism") == "long_and_short_shoots"
    axis_continuity = str(g.get("axis_continuity") or "other_unknown")
    self_pruning = str(g.get("self_pruning") or "other_unknown")
    crown_shape = str(g.get("crown_shape") or "other_unknown")
    branching_rhythm = str(g.get("branching_rhythm") or "other_unknown")
    branching_timing = str(g.get("branching_timing") or "other_unknown")
    lateral_orientation = str(g.get("lateral_axis_orientation") or "other_unknown")
    flowering_position = str(g.get("flowering_position") or "other_unknown")
    leaf_module = sim.blueprint.module("leaf")
    leaf_length = leaf_module.length_m
    leaf_radius = leaf_module.radius_m
    leaf_structure = str((leaf_module.visual or {}).get("leaf_structure") or "simple")
    fascicled = str(g.get("leaf_arrangement") or "") == "fascicled"
    fascicle_size = max(1, min(12, int(g.get("fascicle_size", 3) or 3))) if fascicled else 1
    leaf_area_per_leaf = (
        leaf_length * max(0.0004, leaf_radius * 2.0)
        if leaf_structure == "needle_like"
        else leaf_length ** 2 * 0.45
    )
    root = sim._add(placements,"root",-1,0,0,-.08,0,1,0)

    # Structural axis length excludes leafy-shoot spines on purpose: a
    # current-year leafy twig isn't standing woody biomass, and this figure
    # must stay stable regardless of how finely a shoot's spine happens to be
    # subdivided for rendering (see SpeciesSimulation.get_ecological_outcome).
    axis_length_m = [0.0]

    def segment(parent, end, order, radius, curved=False, curve_factor=1.0, start_point=None):
        start = placements[parent][2:5] if start_point is None else start_point
        path = sim._curved_segment_path(start,end,bend=math.dist(start,end)*.06*curve_factor,
                                       direction=1 if end[0]>=start[0] else -1) if curved else [start,end] if start_point is not None else None
        if start_point is not None and curved:
            path = [start,*path]
        return sim._add(placements,"stem_section" if order==0 else "branch_section",
                        parent,*end,0,radius,order+1,placement_paths=paths,path=path)

    def axis(parent,end,order,radius,steps=3,start_point=None):
        start = placements[parent][2:5] if start_point is None else start_point
        nodes=[]
        for i in range(1,steps+1):
            t=i/steps
            point=[start[j]+(end[j]-start[j])*t for j in range(3)]
            point[2]+=math.sin(t*math.pi)*math.dist(start,end)*.09
            if decurrent and order in {1, 2}:
                # A broad bend and one shallow change of direction, rather
                # than repeating elbows along every segment. The curvature
                # is shared by the whole limb, including its fork sockets.
                dx, dy = end[0] - start[0], end[1] - start[1]
                length_xy = max(1e-9, math.hypot(dx, dy))
                bend = math.sin(t * math.pi) * math.dist(start, end) * .055 * scaffold_blend
                handedness = -1 if (parent + order) % 2 else 1
                point[0] += -dy / length_xy * bend * handedness
                point[1] += dx / length_xy * bend * handedness
            step_start = start if i == 1 and start_point is not None else placements[parent][2:5]
            parent=segment(parent,point,order,radius*(1-.55*t),curved=order<2,
                           start_point=step_start if i == 1 and start_point is not None else None)
            if i == 1 and start_point is not None:
                sim._placement_orientation_hints[str(parent)] = {'structural_socket_m':list(start_point)}
            axis_length_m[0] += math.dist(step_start, point)
            nodes.append(parent)
        return nodes

    def leader_axis(height_scale=1.0, radius_scale=1.0, lean_angle=0.0, lean_strength=0.0, gnarl_salt=0):
        """Build one leader while retaining the visible history of axis succession.

        ``lean_angle``/``lean_strength`` give the leader a consistent
        directional tilt (as opposed to the small symmetric wiggle below,
        which stays centred) -- real trunks are rarely perfectly upright,
        and a fixed per-individual lean also visually separates co-dominant
        trunks (see trunk_count below) instead of leaving them parallel.

        Gnarliness: a real long-lived, or repeatedly stump/root-resprouting,
        tree develops a visibly twisted, knotty trunk with irregular
        thickening as it ages -- not the smooth, monotonically-tapering
        tube every species rendered as before this. But longevity alone is
        the wrong predictor on its own: some very long-lived trees (coast
        redwood, most single-leader conifers) stay famously straight and
        columnar their whole life, while others (mulberries, many
        sympodial-branching broadleafs) characteristically gnarl. The real
        botanical distinction is ``axis_continuity`` -- monopodial growth
        keeps one embryonic-derived axis dominant for the plant's life
        (mechanically straight), while sympodial growth proceeds through a
        succession of different lateral meristems taking over the lead
        (mechanically the textbook cause of a zigzag/crooked axis) -- so
        that's the primary gate here, with ``apical_control`` (strong
        single-leader dominance also resists gnarl) as a secondary
        correlate. Longevity/resprouting/maturity still set how much of
        that potential is expressed. No new field: a spiral path offset
        that rotates with height (twisting, not just a flat back-and-forth
        wiggle) plus one burl-like radius bulge at a seeded height. Cheap
        -- a handful of extra trig ops per segment, no extra placements --
        so it costs nothing additional at forest scale with thousands of
        instances on screen.
        """

        longevity_key = str(g.get("longevity_class") or "")
        if longevity_key in {"very_long", "long", "moderate", "short", "very_short"}:
            # Widely separated on purpose: most currently-authored trees
            # score moderate-to-very_long (real trees mostly are), and the
            # Species Editor preview always renders at full maturity -- a
            # narrow range here made *every* species preview show a similar,
            # fairly strong meander instead of gnarl reading as a trait of
            # specifically old/long-lived trees.
            longevity_gnarl = {
                "very_long": 0.85, "long": 0.42, "moderate": 0.14,
                "short": 0.04, "very_short": 0.01,
            }[longevity_key]
        else:
            # Most currently-authored tree species haven't authored
            # longevity_class yet -- without this they'd all fall back to one
            # identical constant and show literally the same gnarl strength,
            # the same class of "unauthored trait -> visually identical"
            # bug already fixed once for colour/canopy-shape defaults (see
            # SpeciesRenderer._species_tint / plant_assets.species_architecture_defaults).
            # Deterministic per-species jitter around a modest centre keeps
            # unauthored species differentiated instead of uniform.
            species_salt = sum(ord(char) for char in f"{sim.species_id}:longevity_gnarl")
            longevity_gnarl = max(0.03, min(0.35, 0.14 + random.Random(species_salt).uniform(-0.10, 0.10)))
        resprout_bonus = 0.10 if str(g.get("resprouting") or "").lower() in {"moderate", "strong"} else 0.0
        # monopodial (single continuous leader -- redwood, pine, most
        # excurrent conifers) mechanically resists gnarling regardless of
        # age; sympodial (successive lateral takeover -- the real cause of
        # a zigzag axis) amplifies it; the transitional form and unauthored
        # species sit at a neutral 1.0.
        axis_gnarl_multiplier = {"monopodial": 0.08, "sympodial": 1.6}.get(axis_continuity, 1.0)
        # Strong apical dominance (a persistently dominant single leader)
        # is a second, independent correlate of straight growth.
        apical_gnarl_multiplier = 1.3 - 0.6 * apical_control
        raw_gnarl = max(
            0.0,
            (longevity_gnarl + resprout_bonus)
            * axis_gnarl_multiplier
            * apical_gnarl_multiplier,
        )
        # A hard clamp at 1.0 made every very-long-lived sympodial tree hit
        # the same maximum.  That erased the authored apical-control signal
        # and produced equally extreme trunk excursions across the whole
        # category.  Smooth saturation keeps the value bounded while leaving
        # stronger apical control observably capable of straightening a
        # mature trunk.
        gnarl_trait = 1.0 - math.exp(-0.75 * raw_gnarl)
        gnarl_amount = gnarl_trait * (max(0.0, min(1.0, maturity)) ** 2.0)
        # 0 (unauthored) reproduces the original fixed radius exactly; 1 is
        # a strongly pachycaul, baobab-style stout trunk (up to 4x the
        # shared-default radius). Scales the whole taper profile uniformly
        # rather than reshaping it. An optional woody-axis recipe below
        # separately controls adult proportions and the taper curve.
        girth_multiplier = 1.0 + trunk_girth * 3.0
        species_shape_salt = sum(ord(char) for char in f"{sim.species_id}:gnarl_shape")
        gnarl_rng = random.Random(sim.seed * 60013 + gnarl_salt * 733 + species_shape_salt + 41)
        gnarl_phase = gnarl_rng.uniform(0, 2 * math.pi)
        # The leader is always sampled at exactly 12 straight segments,
        # independent of the species' actual height -- a fixed budget, not a
        # per-species one (raising it would add cost to every tree, gnarled
        # or not). At gnarl_amount near its ceiling (any very_long +
        # sympodial species reaches it -- see this function's docstring), a
        # freq this high put more than one full oscillation between some
        # sample pairs, so consecutive nodes could land almost as far apart
        # sideways as they were apart vertically -- a straight diagonal
        # "snapped stick" segment, not a curve, and the taller the species
        # the more obvious that reads (a tall tree's per-segment metre
        # spacing is larger, so the same undersampled swing is a bigger,
        # more jarring jump). Capped so even the highest roll stays inside
        # what 12 samples can still read as a smooth bend.
        gnarl_freq = gnarl_rng.uniform(1.2, 2.2)
        knot_phase = gnarl_rng.uniform(0, 2 * math.pi)
        knot_freq = gnarl_freq * gnarl_rng.uniform(1.5, 1.9)
        burl_t = gnarl_rng.uniform(0.2, 0.75)
        burl_width = gnarl_rng.uniform(0.08, 0.16)
        burl_strength = gnarl_rng.uniform(0.3, 0.6)

        parent = root
        nodes = []
        height_factor = (.88 if axis_continuity == "monopodial_to_sympodial" else .92) * height_scale
        if decurrent:
            height_factor *= 1.0 - .48 * scaffold_blend
        for i in range(1, 13):
            t = i / 12
            transition = max(0., (t - .5) / .5)
            if axis_continuity == "sympodial":
                offset = h * (.0025 + .0075 * t)
            elif axis_continuity == "monopodial_to_sympodial":
                offset = h * .014 * transition
            elif axis_continuity == "monopodial":
                # A persistently dominant single leader (coast redwood,
                # pine, most excurrent conifers) reads as famously
                # ramrod-straight, not just "less wiggly than average" --
                # see species_sim_sequoia comparison against a real
                # reference photo (near-zero visible trunk deviation).
                offset = h * .0004 * t
            else:
                offset = h * .0015 * t
            lean = lean_strength * .22 * h * height_scale * t
            # The offset direction rotates with t (not just alternating
            # sign), so this reads as a spiral twist up the trunk rather
            # than a flat side-to-side wiggle. A second, higher-frequency,
            # smaller-amplitude term rides on top of the smooth spiral so
            # the trunk reads as knotty/irregular rather than one graceful
            # curve.
            gnarl_dir = gnarl_phase + t * gnarl_freq * math.pi
            # Every other perturbation term here (offset, lean) scales with
            # t and is therefore ~0 right where the trunk meets the ground.
            # This one didn't: at gnarl_amount near its ceiling (any
            # very_long + sympodial species -- see leader_axis's docstring)
            # sin(gnarl_phase) alone could already put the very first
            # segment metres off-axis, reading as a snapped/kinked trunk
            # base rather than a gnarled one. Ramp it in over the same
            # first slice of the trunk instead of applying it at full
            # strength from t=0.
            gnarl_base_taper = min(1.0, t / 0.2)
            gnarl_offset = gnarl_amount * gnarl_base_taper * h * height_scale * (
                .24 * math.sin(t * math.pi * gnarl_freq + gnarl_phase)
                + .08 * math.sin(t * math.pi * knot_freq + knot_phase)
            )
            baseline_drift = h * (.001 if axis_continuity == "monopodial" else .012) * t
            end = (
                (baseline_drift + math.sin(i * 1.71) * offset + math.cos(lean_angle) * lean
                 + math.cos(gnarl_dir) * gnarl_offset) * trunk_irregularity,
                (math.cos(i * 1.37) * offset * .72 + math.sin(lean_angle) * lean
                 + math.sin(gnarl_dir) * gnarl_offset) * trunk_irregularity,
                h * height_factor * t,
            )
            if gnarl_salt and trunk_irregularity < 1.0:
                # Keep secondary trunks separated as straight inclined axes,
                # rather than overlapping tubes at the shared root collar.
                retained_lean = lean * (1.0 - trunk_irregularity)
                end = (end[0] + math.cos(lean_angle) * retained_lean,
                       end[1] + math.sin(lean_angle) * retained_lean, end[2])
            if decurrent:
                # The adult bole ends inside the crown. Gentle displacement
                # replaces height-scaled periodic gnarl; succession is
                # expressed by the scaffold forks above, not a sine-wave bole.
                bow = h * height_scale * .045 * gnarl_trait * math.sin(t * math.pi) * t
                adult = ((math.cos(gnarl_phase) * bow + math.cos(lean_angle) * lean * .16) * trunk_irregularity,
                         (math.sin(gnarl_phase) * bow + math.sin(lean_angle) * lean * .16) * trunk_irregularity,
                         end[2])
                end = tuple(end[j] * (1.0 - scaffold_blend) + adult[j] * scaffold_blend for j in range(3))
            start = placements[parent][2:5]
            burl_bump = 1.0 + gnarl_amount * burl_strength * math.exp(-((t - burl_t) / burl_width) ** 2)
            radius = max(.04, h * .014 * radius_scale * girth_multiplier) * (1 - .55 * t)
            if axes_profile:
                radius = trunk_radius(axes_profile, h, radius_scale, t, maturity, radius)
            radius *= burl_bump
            if decurrent:
                # The short bole retains supporting wood into the scaffold
                # junction. Keep a thin juvenile leader, then blend adult girth.
                adult_radius = h * .030 * radius_scale * (1.0 - .60 * t)
                radius = radius * (1.0 - scaffold_blend) + max(radius, adult_radius) * scaffold_blend
            # The terminal leader is a growing shoot, not a flat-cut bole.
            # Retain the established lower trunk and taper its last quarter
            # to a slender apex that its terminal foliage can actually cover.
            radius *= max(.025, min(1., ((1 - t) / .25) ** .8))
            parent = segment(parent, end, 0, radius,
                             curved=axis_continuity != "monopodial" and trunk_irregularity > 0.0,
                             curve_factor=trunk_irregularity)
            axis_length_m[0] += math.dist(start, end)
            nodes.append(parent)
        return nodes

    # Co-dominant trunk multiplicity: real trees with weak apical dominance
    # (multi-stemmed lindens, river birches, many basally-forking species)
    # commonly develop 2-3 trunks from near the base instead of one; strong
    # apical dominance (most conifers) almost never does. Rolled per
    # individual (seeded), not authored, so the same species shows a mix of
    # single- and multi-trunk individuals the way real stands do.
    arch_rng = random.Random(sim.seed * 104729 + 17)
    fork_chance = max(0.0, min(0.75, 0.85 - apical_control))
    trunk_count = 1
    if arch_rng.random() < fork_chance:
        trunk_count = 2
        if arch_rng.random() < fork_chance * 0.35:
            trunk_count = 3
    if decurrent:
        # Reiteration happens above the bole in this subpattern, rather than
        # allocating the crown to several separate, wavy basal trunks.
        trunk_count = 1

    # Lean was previously rolled the same way for every species regardless
    # of growth habit -- a coast redwood (monopodial, strong apical
    # control) would occasionally get the same lean roll as a weak-leader
    # broadleaf, when in reality a persistently dominant single leader
    # (strong negative geotropism holding the trunk vertical) is exactly
    # why redwoods/conifers read as famously ramrod-straight. Gate it the
    # same way as the gnarl mechanism.
    axis_lean_multiplier = {"monopodial": 0.08, "sympodial": 1.15}.get(axis_continuity, 1.0)
    apical_lean_multiplier = 1.3 - 0.8 * apical_control
    lean_multiplier = max(0.03, axis_lean_multiplier * apical_lean_multiplier)

    primary_lean_angle = arch_rng.uniform(0.0, 2 * math.pi)
    primary_lean_strength = (arch_rng.uniform(0.0, 1.0) ** 2) * lean_multiplier
    trunk_configs = [(1.0, 1.0, primary_lean_angle, primary_lean_strength)]
    for _ in range(trunk_count - 1):
        spread = arch_rng.uniform(math.radians(70), math.radians(180))
        side = -1 if arch_rng.random() < 0.5 else 1
        trunk_configs.append((
            arch_rng.uniform(0.78, 0.97),   # height_scale: rarely perfectly equal
            arch_rng.uniform(0.55, 0.85),   # radius_scale: thinner than the primary
            primary_lean_angle + side * spread,
            arch_rng.uniform(0.35, 1.0) ** 1.5,  # secondary trunks lean more visibly
        ))

    trunks = [leader_axis(*config, gnarl_salt=index) for index, config in enumerate(trunk_configs)]
    trunk = trunks[0]
    if maturity<.04:
        return {"structural_axis_length_m": axis_length_m[0]}

    def reproductive_site(short, start, target, points=None, hosts=None, base_parent=None):
        """Resolve one trait-driven reproductive socket on a leafy shoot.

        Dimorphic short shoots keep their established terminal socket. A
        single-shoot system now distinguishes lateral from terminal position;
        ``mixed`` uses a terminal site here because the same shoot cannot
        express both without inventing another organ count. This closes the
        zero-placement gap for mixed single-shoot conifers while preserving
        the existing Pinus short-shoot placement count.
        """

        if short:
            return True, target, None
        if flowering_position == "lateral":
            if points:
                index = min(len(points) - 1, max(0, len(points) // 2))
                return True, points[index], hosts[index] if hosts else None
            # The coarse shoot has only its base and terminal structural
            # sockets. Use the real axillary base socket instead of placing an
            # organ in unsupported mid-air halfway along the collapsed spine.
            return True, start, base_parent
        if flowering_position == "terminal":
            return True, target, None
        if flowering_position == "mixed" and not dimorphic:
            return True, target, None
        return False, target, None

    def leafy_shoot(parent,angle,length,short,identity,visual_positions=None):
        local=random.Random(sim.seed*1009+identity)
        start=placements[parent][2:5]
        count=4 if short else 7
        # A scaffold crown's terminal twig stands for a bounded spray of
        # fine shoots. Counts/area represent that same group at every LOD;
        # the renderer samples it without enlarging an individual oak leaf.
        spray_shoots = 1 + round(15 * scaffold_blend) if decurrent else 1
        # Upright lateral architecture applies to its leaf-bearing shoots
        # as well as the primary limb; otherwise foliage still forms flat
        # shelves even after the supporting branch is made ascending.
        shoot_rise = .65 - droop*.25 if lateral_orientation == "orthotropic" else .32-droop*.5
        target=(start[0]+math.cos(angle)*length,start[1]+math.sin(angle)*length,
                start[2]+length*shoot_rise)
        tangent=sim._normalise_vector(tuple(target[j]-start[j] for j in range(3)))
        side=sim._normalise_vector((-tangent[1],tangent[0],0))
        up=(-tangent[2]*side[1],tangent[2]*side[0],tangent[0]*side[1]-tangent[1]*side[0])
        shoot_type = "short" if short else "long"
        mean_scale = .95*(.65+.35*maturity)

        if not detail:
            # Coarse default: one spine segment, no per-leaf placements. The
            # cluster keeps enough (identity/angle/length/shoot_type) to
            # regenerate the exact detailed geometry later via detail=True.
            shoot_parent=segment(parent,target,4 if short else 3,.0015*(1-.6*.5))
            midpoint=[(start[j]+target[j])/2 for j in range(3)]
            estimated = count * fascicle_size if fascicled else count * (2 + round(10 * density))
            estimated *= spray_shoots
            estimated = round(estimated * leaf_factor)
            leaf_area = estimated * leaf_area_per_leaf * mean_scale ** 2
            cluster_id=sim._add_leaf_cluster(clusters,shoot_parent,*midpoint,estimated,
                                             leaf_area,4 if short else 3,density,allow_empty=True)
            clusters[-1]["phenology_factor"] = leaf_factor
            if decurrent:
                clusters[-1]["foliage_spray_radius_m"] = min(1.4, math.sqrt(max(0., leaf_area) / math.pi) * .72)
                r = clusters[-1]["foliage_spray_radius_m"] * 1.5
                clusters[-1]["organ_bounds_m"] = [midpoint[j] + sign*r for j in range(3) for sign in (-1, 1)]
            clusters[-1].update({"explicit_samples":False,"sample_placement_indices":[],
                                 "shoot_type":shoot_type,"identity":identity,
                                 "angle":angle,"length":length,
                                 "leaf_arrangement":"fascicled" if fascicled else g.get("leaf_arrangement"),
                                 "fascicle_size":fascicle_size if fascicled else 0,
                                 "fascicle_count":count if fascicled else 0})
            if visual_positions:
                # Rendering sockets only: these repeat the same calculative
                # foliage cohort along its supporting twig. They do not add
                # leaves, leaf area, clusters, or ecological biomass.
                clusters[-1]["visual_positions_m"] = [list(point) for point in visual_positions] + [midpoint]
            flower = sim.blueprint.module("flower")
            has_reproductive_site, reproductive_point, reproductive_parent = reproductive_site(
                short, start, target, base_parent=parent,
            )
            reproductive_parent = shoot_parent if reproductive_parent is None else reproductive_parent
            if g.get("bloom_density",0) > 0 and has_reproductive_site:
                clusters[-1]["bloom_axis_m"] = [list(start),list(target)]
            # No asset_ref requirement here: SpeciesRenderer already falls
            # back to a plain coloured dot for an unauthored "flower"
            # placement (see the generic `else` branch in
            # _draw_individual_uncached), so gating placement itself on
            # asset_ref meant flowers never appeared at all -- not even as
            # a fallback -- for any species without a flower pixel asset.
            if lod >= 2 and flowering_factor > 0 and flower and has_reproductive_site:
                sim._add(placements,"flower",reproductive_parent,*reproductive_point,0,.65+.35*flowering_factor,6)
            # Fruit had no placement path anywhere in the growth grammar --
            # the "fruit" kind/colour/module machinery existed but nothing
            # ever called sim._add(placements, "fruit", ...), so an
            # authored fruit pixel asset (e.g. a rose hip) was never drawn.
            # Reuses the same terminal-shoot sockets as flowers (real fruit
            # develops from a fertilised flower at the same position) but
            # only a fraction of them, scaled by fruiting_factor, rather
            # than every flowering position setting fruit.
            fruit = sim.blueprint.module("fruit")
            if (lod >= 2 and fruiting_factor > 0 and fruit and has_reproductive_site
                    and local.random() < fruiting_factor * 0.6):
                sim._add(placements,"fruit",reproductive_parent,*reproductive_point,0,.6+.4*fruiting_factor,6)
            return

        shoot_parent=parent
        points,leaves,hosts,scales=[],[],[],[]
        for i in range(count):
            f=(i+1)/count
            if distribution in {"terminal_cluster","branch_tips"} or short:
                f=.55+.45*f
            else:
                f=.12+.88*f**(1.7-spacing)
            point=[start[j]+(target[j]-start[j])*f for j in range(3)]
            shoot_parent=segment(shoot_parent,point,4 if short else 3,.0015*(1-.6*f))
            azimuth=i*math.radians(float(g.get("phyllotaxis_deg",137.5)))+.7
            scale=local.uniform(.82,1.08)*(.65+.35*maturity)
            scales.append(scale)
            points.append(point)
            hosts.append(shoot_parent)
            if lod==0 or (lod==1 and i%2):
                continue
            # Keep the twig and its random stream through seasonal shedding.
            # Detail samples are a view of the same calculative leaf cohort.
            if (i * .61803398875) % 1 >= leaf_factor:
                continue
            sample_count = min(2, fascicle_size) if fascicled and lod == 1 else fascicle_size
            for needle_index in range(sample_count):
                bundle_azimuth = azimuth + needle_index * math.tau / fascicle_size
                radial_weight = 0.32 if fascicled else 1.0
                forward_weight = 0.92 if fascicled else 0.35
                forward=sim._normalise_vector(tuple(
                    (side[j]*math.cos(bundle_azimuth)+up[j]*math.sin(bundle_azimuth))*radial_weight
                    + tangent[j]*forward_weight
                    for j in range(3)
                ))
                rotation=math.degrees(math.atan2(-(forward[0]+forward[1]*1.8),forward[2]))
                leaf=sim._add(placements,"leaf",shoot_parent,*point,rotation,scale,6)
                sim._placement_orientation_hints[str(leaf)]=sim._orientation_frame(forward)
                leaves.append(leaf)
        midpoint=points[len(points)//2]
        estimated = count * fascicle_size if fascicled else count * (2 + round(10 * density))
        estimated *= spray_shoots
        estimated = round(estimated * leaf_factor)
        cluster_id=sim._add_leaf_cluster(clusters,hosts[0],*midpoint,estimated,
                                         estimated*leaf_area_per_leaf*sum(s*s for s in scales)/count,4 if short else 3,density,allow_empty=True)
        clusters[-1]["phenology_factor"] = leaf_factor
        if decurrent:
            area = estimated * leaf_area_per_leaf * sum(s*s for s in scales)/count
            clusters[-1]["foliage_spray_radius_m"] = min(1.4, math.sqrt(max(0., area) / math.pi) * .72)
            r = clusters[-1]["foliage_spray_radius_m"] * 1.5
            clusters[-1]["organ_bounds_m"] = [midpoint[j] + sign*r for j in range(3) for sign in (-1, 1)]
        clusters[-1].update({"explicit_samples":bool(leaves),"sample_placement_indices":leaves,
                             "shoot_type":shoot_type,"identity":identity,
                             "angle":angle,"length":length,
                             "leaf_arrangement":"fascicled" if fascicled else g.get("leaf_arrangement"),
                             "fascicle_size":fascicle_size if fascicled else 0,
                             "fascicle_count":count if fascicled else 0})
        for leaf in leaves:
            host=placements[leaf][1]
            attachments.append({"stem_placement_index":host,"leaf_placement_index":leaf,
                                "cluster_id":cluster_id,"socket":"leaf","position_m":list(placements[host][2:5]),
                                "shoot_type":shoot_type})
        flower = sim.blueprint.module("flower")
        has_reproductive_site, reproductive_point, reproductive_parent = reproductive_site(
            short, start, target, points=points, hosts=hosts, base_parent=parent,
        )
        reproductive_parent = shoot_parent if reproductive_parent is None else reproductive_parent
        if g.get("bloom_density",0) > 0 and has_reproductive_site:
            clusters[-1]["bloom_axis_m"] = [list(start),list(target)]
        # See the coarse-path comment above: no asset_ref requirement.
        if lod >= 2 and flowering_factor > 0 and flower and has_reproductive_site:
            sim._add(placements,"flower",reproductive_parent,*reproductive_point,0,.65+.35*flowering_factor,6)
        fruit = sim.blueprint.module("fruit")
        if (lod >= 2 and fruiting_factor > 0 and fruit and has_reproductive_site
                and local.random() < fruiting_factor * 0.6):
            sim._add(placements,"fruit",reproductive_parent,*reproductive_point,0,.6+.4*fruiting_factor,6)

    # The x2.2 density boost is scoped to branching_rhythm=="rhythmic"
    # only -- that was the specific pattern with the actual problem (a
    # conifer's canopy expressed as ~7 widely-spaced discrete tiers,
    # reading as flat gappy bands instead of a continuous silhouette edge,
    # no crown_shape tuning could fix that once the geometry itself was
    # under-resolved). "diffuse"/"continuous"/unauthored species distribute
    # branches smoothly across the whole fraction range already and never
    # had that banding problem -- applying the same multiplier to them
    # (first attempt) silently overrode their own authored crown_openness,
    # visibly turning an open-canopy species like Silver Birch into a
    # dense solid blob with its trunk barely visible. Timed against the
    # existing densest species before accepting the extra cost for
    # rhythmic species (see species_sim_morus_nigra_v001.md Sec7h/Sec7i).
    _density_boost = 2.2 if branching_rhythm == "rhythmic" else 1.0
    branch_count=max(3,round((15-5*openness)*maturity*_density_boost))
    if decurrent:
        branch_count = max(4, round((9 - 2 * openness) * max(.4, maturity)))
    if "primary_branch_density" in g:
        # Extra primary axes fill a young crown continuously rather than
        # multiplying the tiny twigs on the same three horizontal shelves.
        # Explicit zero retains the original count and layout.
        # Dense, explicitly authored conifer whorls need more than sixteen
        # tiers. Keep the established budget for other architectures and
        # for conifers without this optional density control.
        limit = 96 if tiered_conifer else 48
        branch_count = max(3, min(limit, round(branch_count * (1 + 2*trait("primary_branch_density", 0.0)))))
    branches_per_tier = 2
    young_conical_crown = has_young_conical_crown(g)
    if branching_rhythm == "rhythmic":
        # Rhythmic branching is expressed as evenly-spaced modules on
        # discrete leader tiers, rotating by quarter_turn between tiers.
        # True opposite phyllotaxis is structurally paired (2 per node);
        # every other rhythmic species (most conifers -- spiral/whorled
        # branching) gets 3 per tier for a much more robust, camera-angle-
        # independent radial silhouette than a single opposite pair.
        branches_per_tier = 2 if g.get("leaf_arrangement") == "opposite" else 3
        tier_count = max(2, round(branch_count / branches_per_tier))
        if young_conical_crown:
            # Two tiers spread across the entire live leader become two
            # disconnected shelves. Resolve a young pyramidal crown with
            # successive whorls; mature budgets already exceed this floor.
            # This is a visual growth budget, not a literal annual whorl count.
            tier_floor = 2 + round(2 * min(1.0, max(0.0, maturity) / .20))
            tier_count = max(tier_floor, tier_count)
        branch_count = max(branches_per_tier * 2, branches_per_tier * tier_count)
    # Total branch count stays exactly what a single-trunk tree would get
    # (openness/maturity-driven, unchanged) even when multi-trunked, so a
    # cosmetic trunk-count roll never inflates total canopy/ecological
    # quantities -- it only redistributes the same mass across more stems.
    trunk_weights = [config[0] for config in trunk_configs]
    weight_total = sum(trunk_weights)
    # Self-pruning: how far up the trunk the live crown begins. Every
    # species used to start its lowest branch at the same fixed trunk node
    # (index 2, ~25% of height) -- real self-pruning trees (a coast redwood
    # in a closed stand being the extreme case) hold a long clear trunk and
    # only carry foliage near the top, since lower/shaded branches die and
    # drop as the tree grows. Scales in with maturity (a young tree hasn't
    # self-pruned yet); unauthored species reproduce the original fixed
    # node-2 default exactly.
    self_pruning_target_node = {
        "strong": 7.5, "moderate": 4.5, "light": 2.5, "none": 1.0,
    }.get(self_pruning, 2.0)
    clear_bole_low_node = 2.0 + (self_pruning_target_node - 2.0) * (max(0.0, min(1.0, maturity)) ** 1.3)
    if axes_profile:
        # A measured/calibrated crown base is not evidence of self-pruning.
        # Node zero is already 1/12 of the leader's height above the collar.
        target = axes_profile["crown_base_fraction"] * 12 - 1
        blend = mature_axis_blend(maturity)
        clear_bole_low_node = clear_bole_low_node * (1 - blend) + target * blend

    # Crown shape: the overall canopy silhouette outline. Every tree used
    # to fill the exact same fixed envelope (peak reach at 42% of height,
    # tapering off both ways) regardless of species -- a "Christmas tree"
    # conical conifer, a small flat-topped "umbrella" crown on a long bole
    # (a mature Scots pine being the textbook case), and a broad, low,
    # spreading canopy all looked identical apart from height/colour. Young
    # individuals normally blend from the shared rounded default, except
    # rhythmic conical crowns whose pyramidal habit is already present young,
    # and only take on their distinctive mature silhouette as they age,
    # so this blends from the default toward the authored target with
    # maturity rather than snapping to it. Unauthored species (and the
    # explicit "ovoid" choice, which names the existing default look) get
    # exactly the original fixed envelope at every maturity -- zero
    # behaviour change unless a species actually authors a different shape.
    _default_envelope_shape = (.42, .70, .08)
    _crown_shape_targets = {
        "conical": (.0, .95, .03),        # widest at the base, tapers to a near-point
        "umbrella": (.88, .30, .12),      # small, flat, concentrated near the top
        "spreading": (.35, 1.10, .35),    # broad and flat-ish throughout, no sharp peak
        "ovoid": (.52, .68, .12),        # rounded crown without an irregular secondary bump
        "irregular": (.55, .80, .32),     # rounded, fuller/less sparse than default
    }
    _target_center, _target_width, _target_floor = _crown_shape_targets.get(crown_shape, _default_envelope_shape)
    _shape_blend = max(0.0, min(1.0, maturity)) ** 0.8
    # A rounded juvenile default gave the top whorl almost half the reach
    # of the bottom one, contradicting an explicitly conical rhythmic crown.
    # Keep independent crown_taper maturation below on its existing curve.
    envelope_blend = 1.0 if young_conical_crown else _shape_blend
    envelope_center = _default_envelope_shape[0] + (_target_center - _default_envelope_shape[0]) * envelope_blend
    envelope_width = _default_envelope_shape[1] + (_target_width - _default_envelope_shape[1]) * envelope_blend
    envelope_floor = _default_envelope_shape[2] + (_target_floor - _default_envelope_shape[2]) * envelope_blend
    # crown_taper: a continuous refinement on top of crown_shape's discrete
    # pattern, letting one species-authored number pull a wide/round outline
    # (a "generic irregular crown", say) into a tall, narrow column -- e.g. a
    # self-pruning emergent conifer -- without a bespoke per-species code
    # branch. 0 (unauthored) leaves crown_shape's shared width/floor exactly
    # as authored for that pattern; 1 approaches a thin vertical column.
    # Scaled by maturity like the rest of the envelope blend -- a young tree
    # hasn't taken on its narrow mature profile yet.
    crown_taper = trait("crown_taper", 0.0) * _shape_blend
    if self_pruning in {"strong", "moderate"}:
        # A narrow tapered crown needs vertical room. Let taper trade some
        # of a self-pruned tree's compressed clear-bole zone for a longer,
        # slimmer live crown; otherwise the two valid traits combine into a
        # short lollipop. Zero/unauthored taper preserves the established
        # self-pruning result exactly.
        clear_bole_low_node = max(1.0, clear_bole_low_node - 1.5 * crown_taper)
    # A coast redwood's canopy is famously irregular, sometimes with a
    # distinct secondary mass of foliage lower down the trunk (reiterated
    # growth after crown damage/competition) rather than one smooth
    # envelope -- represented as one seeded secondary bump, only for
    # "irregular", that grows in with maturity alongside the rest of the
    # shape.
    envelope_bump_center = envelope_bump_strength = None
    if crown_shape == "irregular":
        bump_rng = random.Random(sim.seed * 7919 + 13)
        envelope_bump_center = bump_rng.uniform(0.15, 0.40)
        # The irregular secondary mass must live inside the continuous
        # taper rather than cancel it. Without this coupling, a high-taper
        # tree still received one full-width middle tier and collapsed into
        # a broad umbrella despite its otherwise narrow envelope.
        envelope_bump_strength = 0.55 * _shape_blend * (1.0 - 0.85 * crown_taper)

    for b in range(branch_count):
        local=random.Random(sim.seed*65537+b)
        if decurrent:
            fraction = max(0., min(1., (b + local.uniform(-.38, .38)) / max(1, branch_count - 1)))
        elif branching_rhythm == "rhythmic":
            tier_count = max(2, branch_count // branches_per_tier)
            tier = b // branches_per_tier
            fraction = tier / max(1, tier_count - 1)
        elif branching_rhythm == "diffuse":
            fraction = max(0., min(1., (b + local.uniform(-.34, .34)) / max(1, branch_count - 1)))
        else:
            fraction=b/max(1,branch_count-1)
        trunk_pick = local.random() * weight_total
        trunk_index = len(trunk_weights) - 1
        cumulative = 0.0
        for index, weight in enumerate(trunk_weights):
            cumulative += weight
            if trunk_pick <= cumulative:
                trunk_index = index
                break
        trunk_height_scale = trunk_configs[trunk_index][0]
        # The trunk only has 11 discrete nodes (0-10); when self-pruning
        # compresses the branch-bearing zone into a small slice of that
        # range (a self-pruning conifer's crown occupying only its top
        # ~20-30%), rounding to the nearest node collapses many different
        # branch tiers onto the *same* 2-3 nodes -- the crown reads as a
        # couple of flat bands instead of a smooth silhouette, no matter
        # what crown_shape says. Interpolate the actual attachment point
        # continuously between the two nearest trunk nodes instead; `host`
        # (the nearest node) still anchors the branch in the tree's
        # hierarchy, but the point it visually grows from is precise.
        host_position = min(10.0, max(0.0, clear_bole_low_node + fraction * (10 - clear_bole_low_node)))
        host_index = min(10, max(0, round(host_position)))
        host=trunks[trunk_index][host_index]
        lower_index = min(10, max(0, int(math.floor(host_position))))
        upper_index = min(10, lower_index + 1)
        blend_t = host_position - lower_index
        lower_point = placements[trunks[trunk_index][lower_index]][2:5]
        upper_point = placements[trunks[trunk_index][upper_index]][2:5]
        start = tuple(lower_point[axis_i] + (upper_point[axis_i] - lower_point[axis_i]) * blend_t for axis_i in range(3))
        if decurrent:
            start = placements[host][2:5]
        if branching_rhythm == "rhythmic":
            quarter_turn = math.pi * .5 if g.get("leaf_arrangement") == "opposite" else 2.39996
            slot = b % branches_per_tier
            angle = tier * quarter_turn + slot * (2 * math.pi / branches_per_tier) + local.uniform(-.08, .08)
        else:
            angle=b*2.39996+local.uniform(-.2,.2)
        retention, turn = branch_response(sim.environment,angle,fraction)
        angle += turn
        # A secondary trunk's branches scale with its own (shorter) height,
        # not the primary trunk's -- otherwise a thinner co-dominant stem
        # would carry oversized branches.
        branch_h = h * trunk_height_scale
        envelope = math.sqrt(max(envelope_floor, 1 - ((fraction - envelope_center) / envelope_width) ** 2))
        if envelope_bump_center is not None:
            envelope += envelope_bump_strength * math.exp(-((fraction - envelope_bump_center) / 0.10) ** 2)
        # Blend the category envelope toward a vertically tapered profile.
        # Narrowing a bell-shaped envelope's width concentrated all reach in
        # one middle tier, which visually produced the exact flat umbrella
        # this field was meant to avoid. A taper instead retains substantial
        # lower-crown reach and progressively shortens axes toward the leader.
        tapered_envelope = max(0.08, (1.0 - fraction) ** 0.65)
        envelope = envelope * (1.0 - crown_taper) + tapered_envelope * crown_taper
        envelope *= 1.0 - 0.60 * crown_taper
        if tiered_conifer:
            # A conical envelope alone leaves middle whorls almost as wide
            # as the basal ones. Shorten each successive layer visibly while
            # retaining the authored crown shape and its individual jitter.
            envelope *= 1.0 - .28 * fraction
        reach=branch_h*trait("primary_branch_length",.25)*envelope*(1.12-.4*openness)*local.uniform(.82,1.18)
        reach *= 1.34 - .52 * apical_control
        reach *= .55+.45*retention
        if decurrent:
            reach *= 1.0 - .14 * scaffold_blend
            reach *= 1.0 + (.45 - .80 * fraction) * scaffold_blend
        rise_bias = {
            "orthotropic": .46,
            "mixed": .28,
            "plagiotropic": .10,
            "pendent": -.02,
        }.get(lateral_orientation, .18)
        # Branch-angle gradient is the lower-to-upper change in insertion
        # angle, not a second droop control.  Centre it on 0.5 so the neutral
        # value exactly preserves the established tree grammar: stronger
        # gradients hold lower limbs flatter while lifting upper limbs,
        # producing a rounded/domed crown without changing branch reach or
        # node count.  Weaker gradients do the inverse.
        angle_gradient_shift = (branch_angle_gradient - 0.5) * 0.85 * (2.0 * fraction - 1.0)
        # A strong crown taper is not only a narrower horizontal envelope:
        # it also describes a vertically tapered crown. Lower axes stay
        # flatter (or descend slightly), while upper axes become increasingly
        # ascending. An unauthored/zero taper keeps the previous equation
        # byte-for-byte equivalent.
        tapered_rise_bias = rise_bias * (1.0 - 0.35 * crown_taper)
        taper_rise_shift = crown_taper * 0.42 * (2.0 * fraction - 1.0)
        primary_rise = reach * (tapered_rise_bias + .10 * fraction + angle_gradient_shift + taper_rise_shift)
        if axis_continuity == "monopodial_to_sympodial" and fraction > .72:
            # Once terminal reproduction ends leader extension, the upper
            # lateral axes overtake it and become the next crown modules.
            primary_rise += reach * .34
        end=(start[0]+math.cos(angle)*reach,start[1]+math.sin(angle)*reach,
             min(branch_h,start[2]+primary_rise-droop*branch_h*.035))
        if pendant:
            # Supporting limbs remain arched/ascending; fine branchlets carry
            # the strong downward curve. A single droop applied to all orders
            # cannot express that separation.
            end = (end[0],end[1],min(branch_h,start[2]+primary_rise+reach*.12))
        if decurrent:
            # Lower limbs spread; inner/upper successors rise to the dome.
            # Endpoints stay within the authored height and crown reach.
            adult_z = branch_h * (.44 + .48 * fraction) + local.uniform(-.035, .035) * branch_h
            end = (end[0], end[1], end[2] * (1.0 - scaffold_blend) + adult_z * scaffold_blend)
        primary_radius = max(.012, branch_h*.005)
        if axes_profile:
            blend = mature_axis_blend(maturity)
            primary_radius = primary_radius * (1 - blend) + branch_h * axes_profile["primary_branch_radius_ratio"] * blend
        if decurrent:
            supporting_radius = placements[host][6] * .68
            primary_radius = primary_radius * (1 - scaffold_blend) + min(supporting_radius, branch_h * .014) * scaffold_blend
        precise_socket = start if tiered_conifer and trait('primary_branch_density',0.) > 0 else None
        primary=axis(host,end,1,primary_radius,6 if decurrent else 4,start_point=precise_socket)
        if precise_socket is not None:
            attachments.append({'placement_index':primary[0],'host_placement_index':host,
                                'socket':'interpolated_whorl','position_m':list(start)})
        if planar:
            from simulations.species.planar_sprays import spray_frame
            profile=g['planar_spray_profile']
            plane_rng=random.Random(sim.seed*65537+b+17003)
            _,_,support_normal=spray_frame(angle,math.radians(profile['plane_tilt_deg']),
                math.radians(plane_rng.uniform(-profile['plane_roll_variation_deg'],profile['plane_roll_variation_deg'])))
            def plane_rise(direction, distance):
                return -distance*(support_normal[0]*math.cos(direction)+support_normal[1]*math.sin(direction))/support_normal[2]
        secondary_count = 2 + round(3 * twig_density)
        if branching_timing == "immediate":
            secondary_count += 1
        elif branching_timing == "delayed":
            secondary_count = max(2, secondary_count - 1)
        for s in range(secondary_count):
            host2=primary[min(len(primary)-1, (2+s//2) if decurrent else (1+s//2))]
            anchor=placements[host2][2:5]
            a2=angle+(-1 if s%2 else 1)*local.uniform(.45,1.1)
            reach2=reach*local.uniform(.30,.58)
            end2=(anchor[0]+math.cos(a2)*reach2,anchor[1]+math.sin(a2)*reach2,
                  min(h*1.03,anchor[2]+reach2*(local.uniform(.1,1.35)-droop*.3)))
            if pendant:
                end2 = (end2[0],end2[1],min(h*1.03,anchor[2]+reach2*local.uniform(.12,.5)))
            if tiered_conifer:
                # Keep second-order sprays near their supporting whorl.
                # The default broadleaf rise can bridge several leader tiers
                # and optically erase the rhythmic branching pattern.
                end2 = (end2[0], end2[1], min(h * 1.03,
                        anchor[2] + reach2 * local.uniform(-.08, .20)))
            if planar:
                # The supporting secondary system shares a shallow plane.
                # Changing only its terminal foliage leaves the generic
                # randomly ascending broadleaf scaffold visibly intact.
                end2 = (end2[0], end2[1], anchor[2] + plane_rise(a2,reach2))
            if decurrent:
                rise = reach2 * local.uniform(.28, .85)
                end2 = (end2[0], end2[1], min(h * 1.02, anchor[2] + rise))
            secondary_radius = max(.004,h*.0014)
            if decurrent:
                secondary_radius = secondary_radius * (1 - scaffold_blend) + placements[host2][6] * .45 * scaffold_blend
            secondary=axis(host2,end2,2,secondary_radius,4 if decurrent else 3)
            twig_count = 3 + round(3 * twig_density)
            if branching_timing == "immediate":
                twig_count += 1
            for t in range(twig_count):
                host3=secondary[t%len(secondary)]
                p=placements[host3][2:5]
                a3=a2+local.uniform(-1.3,1.3)
                if pendant:
                    from simulations.species.pendant_branchlets import grow_pendant_branchlet
                    identity=b*100000+s*1000+t*10
                    length=min(2.8,h*.09)*local.uniform(.65,1.)
                    record=grow_pendant_branchlet(sim,placements,host3,a3,length,identity,
                        maturity,lod,clusters,attachments,paths,leaf_factor,
                        flowering_factor,fruiting_factor,detail)
                    pendant_axes.append(record)
                    axis_length_m[0] += record['axis_length_m']
                    continue
                reach3=min(1.5,h*.055)*local.uniform(.55,1.)
                p3=(p[0]+math.cos(a3)*reach3,p[1]+math.sin(a3)*reach3,
                    p[2]+reach3*local.uniform(-droop,.65))
                if tiered_conifer:
                    # Small pendent tips give a fine, layered edge without
                    # turning each individual needle into a canopy tile.
                    p3 = (p3[0], p3[1], p[2] + reach3 * local.uniform(-.22, .12))
                if planar:
                    # Lateral twigs remain in the supporting plane instead
                    # of independently rising through neighbouring sprays.
                    p3 = (p3[0], p3[1], p[2] + plane_rise(a3,reach3))
                twig_nodes=axis(host3,p3,3,.003,3)
                identity=b*100000+s*1000+t*10
                # Stable per-shoot draw preserves paired comparisons and LOD.
                retained = random.Random(sim.seed*1009+identity+991).random() < retention
                if retained:
                    if planar:
                        from simulations.species.planar_sprays import grow_planar_spray
                        record=grow_planar_spray(sim,placements,twig_nodes[-1],a3,identity,
                            maturity,lod,clusters,attachments,paths,leaf_factor,detail,
                            support_normal=support_normal)
                        planar_systems.append(record)
                        axis_length_m[0] += record['axis_length_m']
                        continue
                    visual_positions = None
                    if distribution == "along_shoot" and leaf_structure in {"needle_like", "scale_like"}:
                        visual_count = 2 + round(4 * density)
                        if visual_count > 1:
                            # Cover the whole leaf-bearing secondary/twig
                            # transition, not only the terminal 2/3 of the
                            # twig. This keeps internal conifer limbs from
                            # reading as bare scaffolding while retaining the
                            # same single calculative foliage cohort.
                            candidates = (
                                [anchor]
                                + [placements[index][2:5] for index in secondary]
                                + [p]
                                + [placements[index][2:5] for index in twig_nodes[:-1]]
                            )
                            sample_count = visual_count - 1
                            if sample_count == 1:
                                visual_positions = [candidates[len(candidates) // 2]]
                            else:
                                visual_positions = [
                                    candidates[round(index * (len(candidates) - 1) / (sample_count - 1))]
                                    for index in range(sample_count)
                                ]
                    leafy_shoot(
                        twig_nodes[-1], a3, min(.65, leaf_length*5), False, identity,
                        visual_positions=visual_positions,
                    )
                if retained and dimorphic and distribution=="mixed_long_short_shoots":
                    for n,host4 in enumerate(twig_nodes[1:]):
                        leafy_shoot(host4,a3+(-1 if n else 1)*.85,leaf_length*1.6,True,identity+n+1)

    result = {"structural_axis_length_m": axis_length_m[0]}
    if tiered_conifer and trait('primary_branch_density',0.) > 0:
        result.update(tiered_primary_density_version=2,
                      conifer_primary_axis_count=branch_count,
                      conifer_tier_count=tier_count)
    if pendant:
        result.update(pendant_branchlet_version=g['pendant_branchlet_version'],
                      pendant_branchlet_count=len(pendant_axes),
                      pendant_branchlets=pendant_axes,
                      branchlet_representation='bounded_parallel_shoot_groups',
                      fruit_morphology_status='authored' if sim.blueprint.module('fruit').asset_ref else 'unresolved_not_displayed')
    if planar:
        result.update(planar_spray_version=g['planar_spray_version'],
                      planar_spray_count=len(planar_systems),planar_spray_systems=planar_systems,
                      reproductive_morphology_status='unresolved_not_displayed')
    return result
