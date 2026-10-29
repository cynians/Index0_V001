"""Small analytic support recipes, rasterized without stored meshes/models.

Rock charts use an exponential map on a reference sphere, deformed into a
rounded ellipsoid. Chart distances approximate surface metres; they are not
exact geodesics on the deformed rock. Only body patches have polygon paths.
"""
from __future__ import annotations

import math
import json
from copy import deepcopy
from pathlib import Path

from engine import asset_files
from simulations.species.solid_structures import _finite_float

ROCK_SUPPORT_VERSION = 1
ROCK_TEST_ASSET = Path(__file__).resolve().parents[2]/"assets/plants/preview/rock_test_asset.json"


def rock_fixture(path=ROCK_TEST_ASSET):
    return json.loads(asset_files.read_text(path))


def rock_lifecycle_treatments(asset, profile=None, growth_years=None):
    """Reviewable experimental scenes, shared by the lab and evidence tool."""
    common = {"thallus_hydration":.45, "surface_reproductive_progress":1,
              "surface_weathering_progress":1}
    history = [{"years":25,"thallus_hydration":.45},{"years":5,"thallus_hydration":0}]
    cases = [
        ("YOUNG | 2.5 active test years", {"surface_growth_years":2.5,
          "surface_reproductive_progress":0,"surface_weathering_progress":0}),
        ("EXPANDING | 10 active test years", {"surface_growth_years":10,
          "surface_reproductive_progress":0,"surface_weathering_progress":.25}),
        ("ESTABLISHED | 25 active test years", {"surface_growth_years":25}),
        ("DRY | 5 further years, no growth", {"surface_history":history,"thallus_hydration":0}),
        ("REWET | same retained colony", {"surface_history":history,"thallus_hydration":.45}),
        ("DAMAGED | 45% test tissue loss", {"surface_growth_years":25,"surface_tissue_loss":.45}),
    ]
    if growth_years is not None:
        if len(growth_years) != 3 or not all(math.isfinite(v) and 0 <= v <= 1000 for v in growth_years) or list(growth_years) != sorted(growth_years):
            raise ValueError('Lifecycle previews need three ordered finite growth-year controls')
        young, expanding, established = growth_years
        from simulations.species.surface_growth import surface_activity
        activity = surface_activity(profile or {}, {'thallus_hydration': .45})['surface_activity']
        history = [{'years': established/max(activity, .001), 'thallus_hydration': .45},
                   {'years': 5, 'thallus_hydration': 0}]
        cases = [
            (f'YOUNG | {young:g} effective growth years', {'surface_growth_years': young, 'surface_reproductive_progress': 0, 'surface_weathering_progress': 0}),
            (f'EXPANDING | {expanding:g} effective growth years', {'surface_growth_years': expanding, 'surface_reproductive_progress': 0, 'surface_weathering_progress': .25}),
            (f'ESTABLISHED | {established:g} effective growth years', {'surface_growth_years': established}),
            ('DRY | 5 further years, no growth', {'surface_history': history, 'thallus_hydration': 0}),
            ('REWET | same retained colony', {'surface_history': history, 'thallus_hydration': .45}),
            ('DAMAGED | 45% test tissue loss', {'surface_growth_years': established, 'surface_tissue_loss': .45})]
    if profile and profile.get("radial_rate_source") == "runtime_default":
        radius = profile["diameter_m"]/2
        cases = [
            ("YOUNG | 10% size preview", {"surface_initial_radius_m":radius*.1,"surface_reproductive_progress":0}),
            ("EXPANDING | 40% size preview", {"surface_initial_radius_m":radius*.4,"surface_reproductive_progress":0}),
            ("ESTABLISHED | full size preview", {"surface_initial_radius_m":radius}),
            ("DRY | retained size preview", {"surface_initial_radius_m":radius,"thallus_hydration":0}),
            ("REWET | same retained colony", {"surface_initial_radius_m":radius}),
            ("DAMAGED | 45% test tissue loss", {"surface_initial_radius_m":radius,"surface_tissue_loss":.45}),
        ]
        common["surface_growth_years"] = 0
    return [(name,{**deepcopy(asset),**common,**overrides}) for name,overrides in cases]


def _bounded(value, default, lo, hi):
    return max(lo, min(hi, _finite_float(value, default)))


def normalise_surface_supports(environment):
    environment = environment if isinstance(environment,dict) else {}
    values = environment.get("surface_supports", [])
    if not isinstance(values, (list, tuple)):
        return []
    result = []
    for item in values[:16]:
        if not isinstance(item, dict) or item.get("kind") != "rounded_rock":
            continue
        raw_axes = item.get("radii_m", [])
        raw_center = item.get("center_m", [])
        axes = [_bounded(raw_axes[i] if isinstance(raw_axes, (list, tuple)) and len(raw_axes)>i else None,
                         (.07,.045,.055)[i], .005, 10) for i in range(3)]
        center = [_bounded(raw_center[i] if isinstance(raw_center, (list, tuple)) and len(raw_center)>i else None,
                           0, -1000, 1000) for i in range(3)]
        result.append({"id": str(item.get("id") or f"rock_{len(result)}"),
                       "kind": "rounded_rock", "radii_m": axes, "center_m": center,
                       "roughness": _bounded(item.get("roughness"), .07, 0, .12),
                       "shape_seed": int(_bounded(item.get("shape_seed"), 17, 0, 1000000)),
                       "render_pixel_size_m": _bounded(item.get("render_pixel_size_m"), .003, .0005, .02),
                       "render_style": "flat_palette_pixel_sprite",
                       "support_version": ROCK_SUPPORT_VERSION})
    return result


def rock_point(rock, direction):
    x,y,z = direction
    phase = rock["shape_seed"]*.37
    # Smooth directional bumps are continuous at every longitude and pole.
    bump = 1 + rock["roughness"]*(.55*math.sin(4*x+phase)*math.cos(3*z-phase)
                                 + .30*math.sin(5*y-2*z+phase) + .15*x*z)
    return tuple(rock["center_m"][i] + direction[i]*rock["radii_m"][i]*bump for i in range(3))


def rock_normal(rock, direction):
    # Numeric tangents include the bumps, so lighting and offset agree.
    helper = (0,0,1) if abs(direction[2]) < .9 else (0,1,0)
    a = cross(helper, direction); length = math.sqrt(sum(v*v for v in a))
    a = tuple(v/length for v in a); b = cross(direction,a)
    epsilon = .0001
    def shifted(tangent, sign):
        v = [direction[i]+sign*epsilon*tangent[i] for i in range(3)]
        length = math.sqrt(sum(x*x for x in v))
        return rock_point(rock, [x/length for x in v])
    tangents = []
    for tangent in (a,b):
        first,second = shifted(tangent,-1),shifted(tangent,1)
        tangents.append(tuple(second[i]-first[i] for i in range(3)))
    n = cross(*tangents); length = math.sqrt(sum(v*v for v in n))
    return tuple(v/length for v in n)


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def rock_chart_direction(rock, u, v, longitude_deg=-90, latitude_deg=0):
    lon,lat = math.radians(longitude_deg),math.radians(latitude_deg)
    origin = (math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat))
    east = (-math.sin(lon),math.cos(lon),0)
    north = (-math.sin(lat)*math.cos(lon),-math.sin(lat)*math.sin(lon),math.cos(lat))
    reference_radius = sum(rock["radii_m"])/3
    angle = math.hypot(u,v)/reference_radius
    factor = math.sin(angle)/max(math.hypot(u,v),1e-12)
    return tuple(math.cos(angle)*origin[i] + factor*(u*east[i]+v*north[i]) for i in range(3))


def rock_bounds(rock):
    return [value for i in range(3) for value in
            (rock["center_m"][i]-rock["radii_m"][i]*1.12,
             rock["center_m"][i]+rock["radii_m"][i]*1.12)]
