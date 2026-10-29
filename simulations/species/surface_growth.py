"""Bounded substrate-attached growth, independent of camera and soil roots.

Surface charts use metres: wall charts reuse the solid pixel mask, and trunk
charts unwrap circumference into arc length. Geometry is a representative
thallus, not a colony age estimate or a calibrated physiological model.
"""
from __future__ import annotations

import math
from collections import deque
from copy import deepcopy

from simulations.species.solid_structures import SolidStructureField, _finite_float
from simulations.species.surface_supports import (
    normalise_surface_supports, rock_chart_direction, rock_point, rock_normal, rock_bounds,
)

SURFACE_GRAMMAR_VERSION = 6
MAX_GRID_RADIUS = 48


def _number(value, default, lower, upper):
    return max(lower, min(upper, _finite_float(value, default)))


def _midpoint(value, default, lower, upper):
    if not isinstance(value, dict):
        return default
    if "typical_m" in value:
        return _number(value["typical_m"], default, lower, upper)
    lo = _number(value.get("min_m"), default, lower, upper)
    hi = _number(value.get("max_m"), lo, lower, upper)
    return (lo + max(lo, hi)) / 2


def _mapping(value):
    return value if isinstance(value, dict) else {}


def surface_palette(profile, fallback):
    """Optional authored visual colours, shared by organism and population views."""
    palette = _mapping(profile.get("visual_calibration")).get("thallus_palette")
    if not isinstance(palette, (list, tuple)) or len(palette) != 4:
        return fallback
    if not all(isinstance(row, (list, tuple)) and len(row) == 3 for row in palette):
        return fallback
    return tuple(tuple(round(_number(c, 0, 0, 255)) for c in row) for row in palette)


def surface_disc_colors(profile, fallback):
    calibration = _mapping(profile.get("visual_calibration"))
    result = []
    for key, default in zip(("apothecium_rim_rgb", "apothecium_disc_rgb"), fallback):
        row = calibration.get(key)
        result.append(tuple(round(_number(c, 0, 0, 255)) for c in row)
                      if isinstance(row, (list, tuple)) and len(row) == 3 else default)
    return tuple(result)


def _areole_polygon(i, j, step, seed, inset):
    """Local Voronoi cells avoid a square-grid texture on the thallus."""
    def center(a,b):
        h=(a*1640531513 ^ b*2654435761 ^ seed*83492791)&0xffffffff
        return ((a+((h&255)/255-.5)*.6)*step,
                (b+(((h>>8)&255)/255-.5)*.6)*step)
    x,y=center(i,j)
    polygon=[(x-step*1.5,y-step*1.5),(x+step*1.5,y-step*1.5),
             (x+step*1.5,y+step*1.5),(x-step*1.5,y+step*1.5)]
    for di,dj in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
        a,b=center(i+di,j+dj);nx,ny=a-x,b-y;mx,my=(a+x)/2,(b+y)/2
        clipped=[]
        for first,second in zip(polygon,polygon[1:]+polygon[:1]):
            d1=(first[0]-mx)*nx+(first[1]-my)*ny
            d2=(second[0]-mx)*nx+(second[1]-my)*ny
            if d1<=0:
                clipped.append(first)
            if (d1<=0)!=(d2<=0):
                t=d1/(d1-d2)
                clipped.append((first[0]+t*(second[0]-first[0]),first[1]+t*(second[1]-first[1])))
        polygon=clipped
    return [(x+(a-x)*(1-inset),y+(b-y)*(1-inset)) for a,b in polygon]


def normalise_surface_profile(value):
    value = value if isinstance(value, dict) else {}
    result = deepcopy(value)
    if value.get('atmospheric_tolerance'):
        from simulations.species.surface_atmosphere import validate_atmospheric_tolerance, ATMOSPHERE_RESPONSE_VERSION
        validate_atmospheric_tolerance(value['atmospheric_tolerance'])
        result['atmospheric_response_version'] = ATMOSPHERE_RESPONSE_VERSION
    result["thallus_form"] = str(value.get("thallus_form") or "other_unknown")
    result["diameter_m"] = _number(_mapping(value.get("colony_diameter")).get("max_m"),
        _number(_mapping(value.get("visual_calibration")).get("colony_diameter_m"), .1, .001, 2), .001, 2)
    result["thickness_m"] = _midpoint(value.get("thallus_thickness"),
        _number(_mapping(value.get("visual_calibration")).get("thickness_m"), .001, .00001, .05), .00001, .05)
    result["lobe_width_m"] = _midpoint(value.get("marginal_lobe_width"), .0012, .0001, .02)
    result["apothecium_diameter_m"] = _number(_mapping(value.get("visual_calibration")).get("apothecium_diameter_m"),
        _midpoint(value.get("apothecium_diameter"), .001, .0001, .01), .0001, .01)
    rate = _mapping(value.get("radial_expansion_rate"))
    lo = _number(rate.get("min_m_per_year"), .001, 0, .1)
    hi = _number(rate.get("max_m_per_year"), .003, lo, .1)
    result["radial_rate_m_per_year"] = (lo + hi) / 2
    result["radial_rate_source"] = "reported_range_midpoint" if rate else "runtime_default"
    if rate and str(rate.get('status', '')).startswith('fictional'):
        result['radial_rate_source'] = 'authored_design_range_midpoint'
    result["central_weathering"] = _number(_mapping(value.get("visual_calibration")).get("central_weathering"), .3, 0, 1)
    result["outline_irregularity"] = _number(_mapping(value.get("visual_calibration")).get("outline_irregularity"), .65, 0, 1)
    result["tuft_height_m"] = _midpoint(value.get("tuft_height"), .015, .001, .10)
    calibration = _mapping(value.get("visual_calibration"))
    result["tuft_spacing_m"] = _number(calibration.get("tuft_spacing_m"), .008, .003, .05)
    result["axis_width_m"] = _number(calibration.get("axis_width_m"), .0007, .0001, .003)
    result["phyllocladium_diameter_m"] = _number(calibration.get("phyllocladium_diameter_m"), .0015, .0002, .005)
    result["branching_fraction"] = _number(calibration.get("branching_fraction"), .5, 0, 1)
    return result


def surface_development(profile, environment, maturity):
    """Explicit preview controls and supplied wet-time history, never lifespan inference."""
    maximum = profile["diameter_m"]/2
    initial = _number(environment.get("surface_initial_radius_m"), 0, 0, maximum)
    source = "developmental_preview_fraction_not_calendar_age"
    radius = maximum*maturity
    effective_years = None
    history = environment.get("surface_history")
    if isinstance(history, (list, tuple)):
        effective_years = 0.
        for interval in history[:256]:
            if isinstance(interval, dict):
                effective_years += _number(interval.get("years"), 0, 0, 1000)*surface_activity(profile,interval)["surface_activity"]
        source = "supplied_hydration_history_qualitative_effective_growth_years"
        if profile.get('atmospheric_tolerance'):
            source = 'supplied_environment_history_qualitative_effective_growth_years'
    elif environment.get("surface_growth_years") is not None:
        effective_years = _number(environment["surface_growth_years"], 0, 0, 1000)
        source = ("nominal_reported_annual_range_midpoint_with_size_cap" if profile["radial_rate_source"] != "runtime_default"
                  else "qualitative_runtime_rate_not_species_age_estimate")
        if profile['radial_rate_source'] == 'authored_design_range_midpoint':
            source = 'nominal_authored_design_annual_range_midpoint_with_size_cap'
    if effective_years is not None:
        radius = min(maximum, initial+effective_years*profile["radial_rate_m_per_year"])
    reproductive = _number(environment.get("surface_reproductive_progress"), maturity, 0, 1)
    weathering = _number(environment.get("surface_weathering_progress"), 1, 0, 1)
    loss = _number(environment.get("surface_tissue_loss"), 0, 0, 1)
    hydration = surface_activity(profile,environment)
    if loss == 1:
        state = "lost"
    elif loss:
        state = "damaged"
    elif hydration["surface_activity"] == 0:
        state = "dormant"
    else:
        state = "established" if reproductive > 0 else "expanding"
    return {"surface_radius_m": radius, "surface_radius_source": source,
            "surface_effective_growth_years": effective_years,
            "surface_reproductive_progress": reproductive,
            "surface_weathering_progress": weathering,
            "surface_tissue_loss": loss, "surface_lifecycle_state": state,
            "surface_lifecycle_timing_status": "explicit_controls_maturity_and_death_age_unknown"}


def surface_outline_factor(angle, seed, irregularity):
    phase = (seed % 997)/997*math.tau
    # A stable broad outline surrounds the finer marginal lobes. Its axes and
    # indentations remain fixed during expansion rather than rotating with age.
    uneven = (.48 + .24*math.sin(2*angle+phase) + .17*math.cos(3*angle-phase*.7)
              + .11*math.sin(5*angle+phase*.3))
    return 1-irregularity*.40*uneven


def surface_activity(profile, environment):
    """Instantaneous pulse response; dormancy never removes established cover."""
    if profile.get('atmospheric_tolerance'):
        from simulations.species.surface_atmosphere import atmosphere_response
        atmospheric = atmosphere_response(profile, environment)
        # Reuse the hydration/light response without recursively applying air.
        water_profile = {k: v for k, v in profile.items() if k != 'atmospheric_tolerance'}
        water = surface_activity(water_profile, environment)
        if water['surface_hydration_status'] == 'unresolved_neutral':
            water['surface_activity'] *= _number(environment.get('light_availability'), 1, 0, 1)
            water['surface_activity'] *= 1 - _number(environment.get('temperature_stress'), 0, 0, 1)
        water['surface_activity'] = round(water['surface_activity'] * atmospheric['atmospheric_activity'], 6)
        return {**water, **atmospheric}
    if "thallus_hydration" not in environment or environment.get("thallus_hydration") is None:
        return {"surface_activity": 1., "surface_hydration_status": "unresolved_neutral",
                "surface_water_source": "direct_thallus_wetting"}
    hydration = _number(environment["thallus_hydration"], 0, 0, 1)
    if profile.get("hydration_response") == "pulse_overhydration_depression":
        # The shape is supported by research; .45 and .05 are qualitative
        # coefficients on an uncalibrated scene hydration scale.
        activity = hydration / .45 if hydration <= .45 else 1 - .95 * (hydration - .45) / .55
    else:
        activity = hydration
    light = _number(environment.get("light_availability"), 1, 0, 1)
    thermal = 1 - _number(environment.get("temperature_stress"), 0, 0, 1)
    return {"surface_activity": round(activity * light * thermal, 6),
            "surface_hydration": hydration, "surface_hydration_status": "qualitative_pulse_response",
            "surface_water_source": "direct_thallus_wetting"}


class SurfaceChart:
    """A finite support face parameterized in metric u,v coordinates."""
    def __init__(self, environment, solids, supports, diameter):
        attachment = environment.get("surface_attachment") or {}
        attachment = attachment if isinstance(attachment, dict) else {}
        requested = str(attachment.get("support_id") or "")
        self.solid = next((s for s in solids.structures if s["id"] == requested), None)
        self.trunk = next((s for s in supports if s["id"] == requested), None)
        self.rocks = normalise_surface_supports(environment)
        self.rock = next((s for s in self.rocks if s["id"] == requested), None)
        self.valid = True
        raw_uv = attachment.get("uv_m") or [0, 0]
        self.uv = tuple(_number(raw_uv[i] if isinstance(raw_uv, (list, tuple)) and len(raw_uv) > i else 0,
                                0, -1000, 1000) for i in range(2))
        self.side = -1 if attachment.get("face") != "back" else 1
        self.angle = math.radians(_number(attachment.get("angle_deg"), -90, -360, 360))
        self.longitude = _number(attachment.get("longitude_deg"), -90, -360, 360)
        self.latitude = _number(attachment.get("latitude_deg"), 0, -89, 89)
        if self.solid:
            self.kind, self.id = "solid_mask_face", self.solid["id"]
        elif self.trunk:
            self.kind, self.id = "cylindrical_trunk", self.trunk["id"]
        elif self.rock:
            self.kind, self.id = "analytic_rounded_rock", self.rock["id"]
        elif requested:
            self.kind, self.id, self.valid = "unavailable", requested, False
        else:
            self.kind, self.id = "illustrative_specimen_plane", "specimen_plane"
        self.diameter = diameter

    def contains(self, u, v):
        if not self.valid:
            return False
        u += self.uv[0]; v += self.uv[1]
        if self.solid:
            s = self.solid; px = s["pixel_size_m"]
            column = int(math.floor(u / px + s["mask_width_px"] / 2))
            row = s["mask_height_px"] - 1 - int(math.floor(v / px))
            return (0 <= column < s["mask_width_px"] and 0 <= row < s["mask_height_px"]
                    and s["mask_rows"][row][column] == "#")
        if self.trunk:
            return (float(self.trunk.get("base_z_m", 0)) <= v <= float(self.trunk["top_z_m"])
                    and abs(u) < math.pi * float(self.trunk["radius_m"]))
        if self.rock:
            # Stop before the exponential map's antipodal singularity; large
            # multi-chart colonization is deliberately outside this fixture.
            return math.hypot(u,v) < .95*math.pi*sum(self.rock["radii_m"])/3
        return abs(u) <= self.diameter and abs(v) <= self.diameter

    def point(self, u, v, offset):
        u += self.uv[0]; v += self.uv[1]
        if self.solid:
            return SolidStructureField._local_to_world(self.solid,
                       (u, self.side * (self.solid["extrusion_depth_m"] / 2 + offset), v))
        if self.trunk:
            t = self.trunk; radius = float(t["radius_m"])
            theta = self.angle + u / radius
            center = list(t["center_m"])
            points = t.get("axis_points_m") or []
            for first, second in zip(points, points[1:]):
                if first[2] <= v <= second[2]:
                    fraction = (v - first[2]) / max(1e-9, second[2] - first[2])
                    center = [first[i] + fraction * (second[i] - first[i]) for i in range(2)]
                    break
            return (center[0] + math.cos(theta) * (radius + offset),
                    center[1] + math.sin(theta) * (radius + offset), v)
        if self.rock:
            direction = rock_chart_direction(self.rock,u,v,self.longitude,self.latitude)
            point = rock_point(self.rock,direction); normal = rock_normal(self.rock,direction)
            return tuple(point[i]+normal[i]*offset for i in range(3))
        # The unsupported specimen chart is a horizontal sample of exposed
        # substrate. A vertical chart made erect fruticose axes point into the
        # diagnostic camera and reduced the whole tuft to parallel rows.
        return (u, v, offset)

    def tile_supported(self, corners):
        if not all(self.contains(*p) for p in corners):
            return False
        if not self.solid:
            return True
        # At coarse scales, corners alone can straddle a narrow mask hole.
        low_u=min(p[0] for p in corners);high_u=max(p[0] for p in corners)
        low_v=min(p[1] for p in corners);high_v=max(p[1] for p in corners)
        spacing=self.solid["pixel_size_m"]*.5
        nu=max(1,math.ceil((high_u-low_u)/spacing));nv=max(1,math.ceil((high_v-low_v)/spacing))
        return all(self.contains(low_u+(high_u-low_u)*i/nu,low_v+(high_v-low_v)*j/nv)
                   for i in range(nu+1) for j in range(nv+1))


def build_surface_snapshot(simulation, age_days, lod, maturity, solids, supports):
    from simulations.species.plant_assets import PlantGrowthSnapshot
    profile = simulation.blueprint.growth["surface_growth_profile"]
    environment = simulation.environment
    chart = SurfaceChart(environment, solids, supports, profile["diameter_m"])
    development = surface_development(profile,environment,maturity)
    radius = development["surface_radius_m"]
    # Fixed cells preserve established patch positions through expansion.
    step = max(profile["lobe_width_m"] * .65, profile["diameter_m"] / (2*MAX_GRID_RADIUS), .00025)
    n = min(MAX_GRID_RADIUS, int(math.ceil(radius / step)))
    candidates = {}
    half = step / 2
    phase = (simulation.seed % 997) / 997 * math.tau
    lobed = profile["thallus_form"] == "placodioid_crustose"
    foliose = profile["thallus_form"] == "foliose"
    fruticose = profile["thallus_form"] == "fruticose"
    lobe_count = max(12, min(256, round(math.tau * profile["diameter_m"] / (2*profile["lobe_width_m"]))))
    if foliose:
        spacing = _number(_mapping(profile.get("visual_calibration")).get("lobe_spacing_factor"), 1.9, 1.2, 4)
        lobe_count = max(12, min(256, round(math.pi*profile["diameter_m"]/(spacing*profile["lobe_width_m"]))))
    calibration = _mapping(profile.get("visual_calibration"))
    discrete_fraction = _number(calibration.get("discrete_lobe_fraction"), .65, 0, .85)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            u, v = i * step, j * step
            distance = math.hypot(u, v)
            angle = math.atan2(v, u)
            # Small radial marginal lobes, not leaf placements.
            lobe = (.65*math.sin(lobe_count*angle+phase)+.35*math.sin(lobe_count*.41*angle+phase)) if lobed else 0
            outline = surface_outline_factor(angle,simulation.seed,profile["outline_irregularity"]) if lobed or foliose or fruticose else 1.
            margin = radius*outline + min(radius*.06,profile["lobe_width_m"]*.9)*lobe
            corners = [(u-half,v-half),(u+half,v-half),(u+half,v+half),(u-half,v+half)]
            if distance > margin or radius <= 0 or not chart.tile_supported(corners):
                continue
            if foliose and distance > profile["diameter_m"]*.5*(1-discrete_fraction):
                # Fixed metric radiating strips remain in place through growth;
                # this is fungal thallus geometry, not a leaf arrangement.
                ray = round((lobe_count*angle+phase)/math.tau)
                rh = (ray*1640531513 ^ simulation.seed*83492791)&0xffffffff
                ray_phase = lobe_count*angle+phase+.8*math.sin(distance/(profile["lobe_width_m"]*5)+(rh%997)/997*math.tau)
                separation = abs(math.remainder(ray_phase, math.tau))/lobe_count*distance
                width_factor = .50+.30*((rh>>8)%1000)/1000
                if separation > profile["lobe_width_m"]*width_factor or distance > margin*(.78+.22*(rh%1000)/1000):
                    continue
            candidates[i, j] = (u, v, distance / max(radius, 1e-9), corners)
    # A connected surface front cannot jump a hole to disconnected substrate.
    reached = set(); queue = deque([(0, 0)] if (0, 0) in candidates else [])
    while queue:
        key = queue.popleft()
        if key in reached or key not in candidates:
            continue
        reached.add(key)
        i, j = key
        neighbours = ((1,0),(-1,0),(0,1),(0,-1))
        if foliose:
            neighbours += ((1,1),(-1,1),(1,-1),(-1,-1))
        queue.extend((i+di,j+dj) for di,dj in neighbours)
    placements = []; paths = {}; attachments = []; orientations = {}
    apothecia = []; live_cells = set()
    moss = simulation.blueprint.growth.get("growth_form") == "moss"
    apothecium_enabled = (not moss and (simulation.blueprint.growth.get("reproductive_structure") == "apothecium"
                         or profile.get("reproductive_structure") == "apothecia"))
    body_kind = "moss_patch" if moss else "thallus"
    for key in sorted(reached):
        u, v, fraction, corners = candidates[key]
        h = (key[0]*73856093 ^ key[1]*19349663 ^ simulation.seed*83492791) & 0xffffffff
        # Central weathering is an explicitly qualitative appearance control.
        # Lost central islands do not create new vegetative offspring.
        missing = lobed and fraction < .55 and h % 1000 < 70 * profile["central_weathering"]*development["surface_weathering_progress"]
        missing = missing or ((h >> 12) % 10000 < 10000*development["surface_tissue_loss"])
        if missing:
            continue
        live_cells.add(key)
        if lobed:
            inset = .045 if fraction > .7 else .085
            warped = _areole_polygon(*key,step,simulation.seed,inset)
            if chart.tile_supported(warped):
                corners = warped
        point = chart.point(u, v, profile["thickness_m"])
        index = len(placements)
        placements.append([body_kind, -1, *[round(x, 6) for x in point], 0., round(fraction, 6), 0])
        paths[str(index)] = [[round(x, 6) for x in chart.point(a,b,profile["thickness_m"])] for a,b in corners]
        # Every patch attaches to the environment directly, not a root index.
        attachments.append({"placement_index": index, "socket": "surface", "support_id": chart.id,
                            "position_m": list(placements[-1][2:5]), "uv_m": [u,v], "radial_fraction": fraction})
        orientations[str(index)] = {"surface_chart": chart.kind,
                                   "weathering_progress": development["surface_weathering_progress"]}
        if foliose:
            ray = round((lobe_count*math.atan2(v,u)+phase)/math.tau)
            orientations[str(index)]["lobe_tone"] = (ray*37+simulation.seed)%3+1
        if fruticose:
            orientations[str(index)]["uv_m"] = [u,v]
            orientations[str(index)]["thallus_form"] = "fruticose"
        fruit_site = h % 89 == 0
        if foliose:
            fruit_site = h % 10000 < 10000*_number(calibration.get("apothecium_probability"), .08, 0, .3)
        if apothecium_enabled and not fruticose and fraction < .72 and fruit_site and ((h >> 8)%1000)/1000 < development["surface_reproductive_progress"]:
            apothecia.append((index, u, v))
    canonical_apothecia = len(apothecia)
    for parent, u, v in apothecia:
        r = profile["apothecium_diameter_m"] / 2
        # Suppress any disc that would overhang a hole or colony edge.
        ring = [(u + r*math.cos(k*math.tau/12),v + r*math.sin(k*math.tau/12)) for k in range(12)]
        if not all(chart.contains(*p) and math.hypot(*p) < radius*.8 for p in ring):
            canonical_apothecia -= 1
            continue
        if foliose and not all((round(a/step),round(b/step)) in live_cells for a,b in ring):
            canonical_apothecia -= 1
            continue
        index = len(placements); point = chart.point(u,v,profile["thickness_m"]*1.1)
        placements.append(["apothecium",parent,*[round(x,6) for x in point],0.,1.,1])
        paths[str(index)] = [[round(x,6) for x in chart.point(a,b,profile["thickness_m"]*1.1)] for a,b in ring]
        orientations[str(index)] = {"surface_chart":chart.kind}
    tuft_stats = {}
    if fruticose and not moss:
        from simulations.species.surface_fruticose import append_fruticose
        tuft_stats = append_fruticose(profile, chart, development, simulation.seed,
                                     placements, paths, orientations)
        canonical_apothecia = sum(p[0] == "apothecium" for p in placements)
    points = [p for path in paths.values() for p in path]
    for s in solids.structures:
        b = solids.bounds_m(s); points.extend([(b[0],b[2],b[4]),(b[1],b[3],b[5])])
    for t in supports:
        x,y=t["center_m"]; r=t["radius_m"]
        points.extend([(x-r,y-r,t.get("base_z_m",0)),(x+r,y+r,t["top_z_m"])])
    for rock in chart.rocks:
        b = rock_bounds(rock); points.extend([(b[0],b[2],b[4]),(b[1],b[3],b[5])])
    if not points:
        points=[chart.point(0,0,0)]
    bounds=[value for axis in range(3) for value in (min(p[axis] for p in points),max(p[axis] for p in points))]
    body_paths=[paths[str(i)] for i,p in enumerate(placements) if p[0]==body_kind]
    # Cross-product triangle area uses the actual warped 3D polygons, and
    # therefore counts central cracks and curved substrates consistently.
    def polygon_area(points):
        a=points[0]; total=0.
        for b,c in zip(points[1:-1],points[2:]):
            u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)]
            cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            total+=math.sqrt(sum(x*x for x in cross))/2
        return total
    area=sum(polygon_area(p) for p in body_paths)
    photosynthetic_area = (sum(polygon_area(paths[str(i)]) for i,p in enumerate(placements)
                              if p[0] == "phyllocladium") if fruticose else area)
    stats={"surface_grammar_version": SURFACE_GRAMMAR_VERSION, "surface_support_id": chart.id,
           "surface_support_kind": chart.kind, "surface_attached": bool(body_paths),
           **development,
           "surface_coverage_m2": round(area,9), "surface_cell_size_m": step,
           "surface_cell_count": len(body_paths), "canonical_apothecium_count": canonical_apothecia,
           "surface_lobe_count":lobe_count if lobed or foliose else 0,
           "surface_central_weathering":profile["central_weathering"],
           "surface_outline_irregularity":profile["outline_irregularity"],
           "surface_geometry_status": "connected_surface_chart_approximation",
           "surface_photosynthetic_area_m2": round(photosynthetic_area,9),
           "surface_thallus_form": profile["thallus_form"], **tuft_stats,
           "root_model_status": "not_applicable_surface_body", "root_depth_source": "not_applicable",
           "root_depth_m": 0., "root_length_m": 0., "root_spread_m": 0., "root_segment_count": 0,
           "leaf_count": 0, "estimated_leaf_count": 0, "leaf_area_m2": 0., "leaf_cluster_count": 0,
           "stem_count": 0, "branch_count": 0, "placement_count": len(placements),
           "maturity": maturity, "environment": dict(environment),
           "solid_structures": solids.structures, "climbing_supports": supports,
           "surface_supports": chart.rocks,
           **surface_activity(profile,environment)}
    return PlantGrowthSnapshot(species_id=simulation.species_id,
        blueprint_fingerprint=simulation.blueprint.fingerprint(),seed=simulation.seed,
        age_days=round(age_days,3),lod=lod,modules={m.id:m.to_dict() for m in simulation.blueprint.modules},
        placements=placements,bounds_m=bounds,placement_paths=paths,
        placement_orientations=orientations,attachment_points=attachments,stats=stats)


def surface_ecological_outcome(growth, stats, environment):
    activity = surface_activity(growth["surface_growth_profile"],environment)
    area = float(stats.get("surface_coverage_m2",0))
    health = (1-_number(environment.get("disturbance"),0,0,1)) if area > 0 else 0.
    return {"status":"qualitative_surface_body_response", "vitality":health,
            "growth_rate":activity["surface_activity"]*growth.get("growth_rate_bias",.25)*health,
            "potential_radial_increment_m_per_year":growth["surface_growth_profile"]["radial_rate_m_per_year"]*activity["surface_activity"]*health,
            "photosynthetic_surface_area_m2":float(stats.get("surface_photosynthetic_area_m2",area))*activity["surface_activity"],
            "surface_coverage_m2":area,"resource_demand":area*.02,
            "structural_biomass_proxy":area*growth.get('surface_biomass_kg_m2', .08)*health,
            "standing_biomass_kg":area*growth.get('surface_biomass_kg_m2', .08)*health,
            "biomass_density_source":'authored_population_density' if 'surface_biomass_kg_m2' in growth else 'qualitative_surface_area_default',
            "fecundity":activity["surface_activity"]*health if stats.get("canonical_apothecium_count") or stats.get("soralium_count") else 0.,
            "reproduction_status":("ascospore_and_joint_symbiont_propagule_proxies_recruitment_not_simulated" if stats.get("soralium_count")
                                   else "fungal_ascospore_proxy_partner_encounter_not_simulated"),
            "mortality_risk":1-health,"estimated_leaf_count":0,"leaf_area_proxy":0.,
            "root_depth_m":0.,"root_spread_m":0.,"root_length_m":0.,
            "root_depth_source":"not_applicable","root_model_status":"not_applicable_surface_body",
            "nutrient_model_status":"surface_deposition_unresolved_no_soil_root_access",
            "nitrogen_fixation_status":("cyanobiont_association_rate_unresolved" if growth.get("surface_growth_profile",{}).get("cyanobiont") else "not_modelled"),
            "surface_lifecycle_state": stats.get("surface_lifecycle_state"),
            "surface_lifecycle_timing_status":"explicit_controls_maturity_and_death_age_unknown",
            **activity}
