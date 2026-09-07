"""Deterministic light/establishment experiment, not a calibrated forest model.

All distances are metres. Positions are fixed before light is sampled, so
neighbour responses cannot depend on generation order or move existing trees.
"""
import math
import random


def shade_profile(value):
    thresholds = {"low": .55, "medium": .30, "high": .12}
    return {"tolerance": value if value in thresholds else "other_unknown",
            "minimum_light": thresholds.get(value, .35),
            "source": "runtime_response_default"}


def light_at(x, y, z, trees, exclude=None):
    light = 1.0
    for tree in trees:
        if tree["id"] == exclude or tree["height_m"] <= z:
            continue
        radius = tree["radius_m"]
        distance = math.hypot(x-tree["x"], y-tree["y"])
        # Smooth crown edges avoid abrupt branch responses across a boundary.
        overlap = max(0., 1.-(distance/(radius*1.25))**2)
        vertical = min(1., (tree["height_m"]-z)/(tree["height_m"]*.35))
        light *= 1.-overlap*vertical*tree["opacity"]
    return max(.02, min(1., light))


def environment_for(tree, trees, tolerance):
    radius = tree["radius_m"]
    directions = [light_at(tree["x"]+math.cos(i*math.pi/4)*radius,
                           tree["y"]+math.sin(i*math.pi/4)*radius,
                           tree["height_m"]*.45, trees, tree["id"]) for i in range(8)]
    mean = sum(directions)/8
    # The vector carries contrast strength: uniform darkness has no direction.
    vector = [sum((v-mean)*fn(i*math.pi/4) for i,v in enumerate(directions))/4
              for fn in (math.cos, math.sin)]
    return {"light_fraction": light_at(tree["x"],tree["y"],tree["height_m"]*.35,trees,tree["id"]),
            "directional_light": directions, "growth_bias": vector,
            "shade_tolerance": tolerance, "model": "forest_light_v1"}


def branch_response(environment, angle, height_fraction):
    if not environment:
        return 1., 0.
    values = environment.get("directional_light") or [environment.get("light_fraction",1.)]*8
    u = (angle % math.tau)/math.tau*len(values)
    i = int(u)
    light = values[i]*(1-u+i)+values[(i+1)%len(values)]*(u-i)
    # Upper branches have greater sky access than lower crown branches.
    light += (1-light)*max(0.,min(1.,height_fraction))**2*.6
    minimum = shade_profile(environment.get("shade_tolerance"))["minimum_light"]
    retention = min(1., max(.08, (light/minimum)*light**(minimum*.6)))
    # Even above the establishment threshold, declining light gradually
    # reduces supported foliage; tolerant plants decline more slowly.
    retention = min(retention, light**(minimum*.6))
    bias = environment.get("growth_bias",[0.,0.])
    turn = max(-.4,min(.4, (bias[1]*math.cos(angle)-bias[0]*math.sin(angle))*.65))
    return retention, turn


def build_forest_plan(growth, seed=1, spacing="medium", tolerance=None):
    factor = {"dense": .62,"medium": 1.,"open": 1.55}[spacing]
    profile = shade_profile(tolerance if tolerance is not None else growth.get("shade_tolerance"))
    height = max(.2,float(growth.get("max_height_m",10.)))
    radius = height*.22
    gap = radius*1.9*factor
    rng = random.Random(int(seed)+9201)
    openness = growth.get("crown_openness")
    opacity = .9-.5*float(.5 if openness is None else openness)
    trees = []
    # Rejection sampling gives irregular gaps without overlapping trunks.
    # A broad clearing breaks up the stand without imposing rows.
    positions = []
    for attempt in range(10000):
        x, y = rng.uniform(-2.65, 2.65), rng.uniform(-2.65, 2.65)
        if math.hypot(x-.55, y+.35) < .72:
            continue
        if any(math.hypot(x-px, y-py) < .63 for px, py in positions):
            continue
        positions.append((x, y))
        if len(positions) == 28:
            break
    # Keep the paired diagnostic's focal tree nearest the map centre.
    focal = min(range(len(positions)), key=lambda i: math.hypot(*positions[i]))
    positions[4], positions[focal] = positions[focal], positions[4]
    for i, (x, y) in enumerate(positions):
        maturity = rng.uniform(.30, 1.) if i % 4 == 0 and i != 4 else rng.uniform(.65, 1.)
        trees.append({"id": i, "x": x*gap, "y": y*gap,
                      "height_m": height*maturity, "radius_m": radius*maturity,
                      "maturity": maturity, "opacity": opacity, "seed": int(seed)+i*31})
    for tree in trees:
        tree["environment"] = environment_for(tree,trees,profile["tolerance"])
    # Candidate locations are shared across tolerance treatments. Spacing
    # scales the same spatial pattern; recruitment never repositions adults.
    recruits = []
    for i in range(36):
        x,y = rng.uniform(-2.65,2.65)*gap,rng.uniform(-2.65,2.65)*gap
        light = light_at(x,y,height*.03,trees)
        clearance = all(math.hypot(x-t["x"],y-t["y"])>height*.025 for t in trees)
        recruits.append({"x":x,"y":y,"light":light,
                         "established":clearance and light>=profile["minimum_light"]})
    return {"seed":seed,"spacing":spacing,"spacing_m":gap,"shade":profile,
            "tolerance_override":tolerance is not None,"trees":trees,"recruits":recruits,
            "extent_m":gap*2.75+radius,"mean_ground_light":sum(r["light"] for r in recruits)/len(recruits),
            "established_count":sum(r["established"] for r in recruits)}
