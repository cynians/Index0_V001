"""Bounded tuft geometry on surface charts; all density controls are visual fits."""
import math

from simulations.species.surface_supports import cross


def append_fruticose(profile, chart, development, seed, placements, paths, orientations):
    """Add pseudopodetia, phyllocladia and optional symbiont/reproductive bodies.

    Metre paths reuse the sprite renderer. Bases follow the substrate normal;
    these fungal axes are deliberately separate from vascular stems/leaves.
    """
    height = profile["tuft_height_m"]
    progress = min(1., development["surface_radius_m"] / (profile["diameter_m"] / 2))
    spacing = profile["tuft_spacing_m"]
    step = max(profile["lobe_width_m"]*.65,profile["diameter_m"]/96,.00025)
    stride = max(1, math.ceil(spacing/step))
    basal = list(enumerate(placements))
    occupied = set()
    counts = {"pseudopodetium_count": 0, "phyllocladium_count": 0,
              "cephalodium_count": 0, "soralium_count": 0}

    def add(kind, parent, point, polygon, width=0.):
        index = len(placements)
        placements.append([kind, parent, *[round(x, 6) for x in point], 0., 1., 1])
        paths[str(index)] = [[round(x, 6) for x in p] for p in polygon]
        orientations[str(index)] = {"surface_chart": chart.kind, "width_m": width}
        return index

    def disc(kind, parent, point, radius, tangent, other, phase):
        ring = []
        for k in range(10):
            a = k * math.tau / 10
            r = radius * (1 + .12 * math.sin(5*a + phase))
            ring.append(tuple(point[i] + r*(math.cos(a)*tangent[i] + math.sin(a)*other[i]) for i in range(3)))
        return add(kind, parent, point, ring)

    for parent, body in basal:
        if body[0] != "thallus":
            continue
        # Stable selection of one attachment per coarse tuft cell. Cells that
        # lose their basal tissue cannot retain floating branches.
        base = body[2:5]
        # Actual chart UV, independent of curved support point coordinates.
        polygon = paths[str(parent)]
        uv = orientations[str(parent)].get("uv_m")
        if uv is None:
            continue
        grid = (round(uv[0]/step),round(uv[1]/step))
        cell = (grid[0]//stride,grid[1]//stride)
        # The chosen tile is fixed by cell and seed, so loss of that tile
        # removes its tuft without relocating it. A shared grid origin used
        # to line every pseudopodetium up in conspicuous straight rows.
        cell_hash = (cell[0]*73856093 ^ cell[1]*19349663 ^ seed*83492791) & 0xffffffff
        slot = (cell[0]*stride + cell_hash % stride,
                cell[1]*stride + (cell_hash >> 11) % stride)
        if grid != slot:
            continue
        if cell in occupied or len(occupied) >= 96:
            continue
        occupied.add(cell)
        h = (cell[0]*73856093 ^ cell[1]*19349663 ^ seed*83492791) & 0xffffffff
        if h % 5 == 0:
            continue
        a, b, c = polygon[:3]
        normal = cross([b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)])
        length = math.sqrt(sum(x*x for x in normal))
        normal = tuple(x/max(length, 1e-12) for x in normal)
        helper = (0,0,1) if abs(normal[2]) < .9 else (0,1,0)
        tangent = cross(helper, normal)
        length = math.sqrt(sum(x*x for x in tangent))
        tangent = tuple(x/max(length, 1e-12) for x in tangent)
        other = cross(normal, tangent)
        phase = h / 0xffffffff * math.tau
        stalk_height = height * progress * (.55 + .45*((h >> 8) % 1000)/1000)
        lean = tuple(.24*(math.cos(phase)*tangent[i]+math.sin(phase)*other[i]) for i in range(3))
        tip = tuple(base[i]+stalk_height*(normal[i]+lean[i]) for i in range(3))
        axis = add("pseudopodetium", parent, tip, [base, tip], profile["axis_width_m"])
        counts["pseudopodetium_count"] += 1
        axes = [(axis, base, tip)]
        if h % 100 < profile["branching_fraction"]*100 and progress > .25:
            for sign in (-1, 1):
                junction = tuple(base[i]+.55*(tip[i]-base[i]) for i in range(3))
                end = tuple(junction[i]+stalk_height*(.38*normal[i]+sign*.28*tangent[i]+.14*other[i]) for i in range(3))
                child = add("pseudopodetium", axis, end, [junction, end], profile["axis_width_m"]*.65)
                axes.append((child, junction, end))
                counts["pseudopodetium_count"] += 1
        for axis_index, start, end in axes:
            for k in range(1, 8):
                f = (k + .22*math.sin(phase*3 + axis_index*.17 + k*2.4))/8
                phi = phase+k*2.4+axis_index*.31
                scale_r = profile["phyllocladium_diameter_m"] / 2 * (.75+.25*math.cos(phi))
                # Increasing concentration near the tips, with larger basal
                # scales; both are morphology fits rather than leaf organs.
                for side in range(3 if f>.5 else 2):
                    angle = phi + side*math.tau/3
                    lateral = tuple(math.cos(angle)*tangent[i]+math.sin(angle)*other[i] for i in range(3))
                    site = max(.04,min(.96,f+.025*math.sin(angle*2+k)))
                    point = tuple(start[i]+site*(end[i]-start[i])+lateral[i]*scale_r*.9 for i in range(3))
                    disc("phyllocladium", axis_index, point, scale_r*(1.25-.4*f), tangent, other, phi)
                    counts["phyllocladium_count"] += 1
        reproductive = development["surface_reproductive_progress"]
        if h % 11 == 0 and reproductive > .5:
            disc("apothecium", axis, tip, profile["apothecium_diameter_m"]/2, tangent, other, phase)
        if profile.get("joint_symbiont_dispersal") == "terminal_soredia" and h % 7 == 0 and reproductive > .3:
            disc("soralium", axis, tip, .0008, tangent, other, phase)
            counts["soralium_count"] += 1
        if profile.get("cyanobiont") and h % 9 == 0 and progress > .4:
            point = tuple(base[i]+.25*(tip[i]-base[i]) for i in range(3))
            disc("cephalodium", axis, point, .00045, tangent, other, phase)
            counts["cephalodium_count"] += 1
    return counts
