"""Metallogenic districts: where a planet's ore-forming processes gather an element.

Phenomenon card (copper, the first element with data)
-----------------------------------------------------
* **Real examples.** The porphyry copper belts of the Andes (Chuquicamata,
  Escondida, El Teniente) and the south-western USA, above subducting slabs;
  the sediment-hosted Central African Copperbelt and the Kupferschiefer in
  rift and intracontinental basins; volcanogenic massive sulfides at
  spreading ridges and in rifts (Cyprus, the Iberian Pyrite Belt); magmatic
  Ni-Cu sulfides and native copper in plume-fed flood basalts (Norilsk,
  Keweenaw).
* **Shares.** Porphyry deposits hold about 60 % of the copper mined,
  sediment-hosted about 20 %, massive sulfides about 6 %, magmatic and
  native copper the rest (Kesler & Wilkinson 2008, Geology 36; Singer 1995;
  Sillitoe 2010, Econ. Geol. 105; Hitzman et al. 2005).  The element card's
  ``metallogeny.districts`` holds them.
* **Where.** Each district type is its tectonic setting's own band in the
  planet's orogen forcing (the same geometry the heights read): the
  magmatic arc on the overriding plate (``arc`` band, segmented along strike
  by the arc pulses; continental arcs over island arcs), the rift axis of
  continental rifts, the ridge of oceanic spreading, and the hotspot tracks
  by their volume.  Belts are not fertile everywhere: inherited lithospheric
  fertility makes metallogenic provinces (Richards 2003; Hronsky et al. 2012),
  here a planet noise of ~1000 km provinces.
* **How much.** A share ``district_share`` of the crust's copper sits in its
  districts, split between the types by those shares; the rest is the
  background each rock carries (``trace_element_ppm``).  The local factor
  ``E = (1 - f) + f * sum_k w_k F_k / <F_k>`` (area-weighted planet means)
  averages exactly 1 over the planet: districts move copper, they do not
  make it.
* **Why LOD0.** Belts are hundreds of km long and tens wide: they show from
  orbit.  Deposits inside them (km) are LOD2+: one ore system per element
  and tile (``regional_materials``), its style (porphyry, sediment-hosted,
  massive sulfide, magmatic) that of the district type gathering the most
  there (``district_contributions``), grade and pyrite from the element
  card's ``metallogeny.styles``.
* **Layers.** The rock map's element minerals (``material_lod._element_minerals``
  -> ``element_pigments.surface_minerals``), which true colour mixes, and
  the regional deposits (``regional_materials``) read the same
  ``enrichment``.

Values from the literature were entered from memory and are unverified.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.sphere_noise import sphere_fbm

DISTRICT_TYPES = ("arc_magmatism", "rift_basin", "spreading_ridge", "mantle_plume")
# Island arcs carry smaller porphyry systems than continental arcs (thinner
# crust, less magma differentiation: the Philippines against the Andes).
ISLAND_ARC_WEIGHT = 0.6
# Metallogenic provinces: planet noise blobs (``features`` per radius) and the
# share of a belt that is fertile.
PROVINCE_FEATURES = 6.0
PROVINCE_THRESHOLD = (0.35, 0.65)
# The grid the planet means are taken on.
MEAN_GRID = (192, 96)
_MEAN_CACHE = {}


def _mechanism_fields(u_values, v_values, tectonic_model):
    """Each district type's band (0..1) on the ``v_values`` x ``u_values`` grid."""
    from simulations.world_gen.heightmap import _np_segment_forcing, iter_orogen_segment_geometry

    u_values = np.asarray(u_values, dtype=np.float64)
    v_values = np.asarray(v_values, dtype=np.float64)
    shape = (v_values.size, u_values.size)
    fields = {key: np.zeros(shape) for key in DISTRICT_TYPES}
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    if tectonic_model.get("boundary_segments"):
        for item in iter_orogen_segment_geometry(u_values, v_values, tectonic_model):
            system = item["system"]
            mechanism = str(system.get("mechanism") or "")
            if mechanism not in {"ocean_continent_subduction", "island_arc_subduction", "continental_rift", "oceanic_spreading"}:
                continue
            response = _np_segment_forcing(item["segment"], system, item["signed_distance"], item["influence"])
            profile = system.get("forcing_profile") if isinstance(system.get("forcing_profile"), dict) else {}
            if mechanism in {"ocean_continent_subduction", "island_arc_subduction"}:
                peak = max(1.0, float(profile.get("volcanic_construction_peak_m", 0.0) or 0.0))
                band = np.clip(response["volcanic_construction_m"] / peak, 0.0, 1.0)
                band = band * (1.0 if mechanism == "ocean_continent_subduction" else ISLAND_ARC_WEIGHT)
                key = "arc_magmatism"
            elif mechanism == "continental_rift":
                peak = max(1.0, float(profile.get("tectonic_subsidence_peak_m", 0.0) or 0.0))
                band = np.clip(response["tectonic_subsidence_m"] / peak, 0.0, 1.0)
                key = "rift_basin"
            else:
                band = np.clip(response["divergent_influence"], 0.0, 1.0)
                key = "spreading_ridge"
            band = np.where(item["valid"], band, 0.0)
            rows, columns = item["rows"], item["columns"]
            np.maximum(fields[key][rows, columns], band, out=fields[key][rows, columns])
        hotspots = tectonic_model.get("hotspot_model")
        if hotspots:
            from simulations.world_gen.lithotectonic_settings import _hotspot_evidence

            u_grid, v_grid = np.meshgrid(u_values, v_values)
            fields["mantle_plume"] = np.clip(_hotspot_evidence(hotspots, u_grid, v_grid), 0.0, 1.0)
    return fields


def _provinces(u_grid, v_grid, seed):
    noise = sphere_fbm(seed, "metallogeny:provinces", u_grid, v_grid, features=PROVINCE_FEATURES, octaves=2)
    low, high = PROVINCE_THRESHOLD
    fertile = np.clip((noise - low) / (high - low), 0.0, 1.0)
    return fertile * fertile * (3.0 - 2.0 * fertile)


def _planet_means(tectonic_model, seed):
    key = (str(seed), str((tectonic_model or {}).get("map_seed")), len((tectonic_model or {}).get("boundary_segments") or []),
           len(((tectonic_model or {}).get("hotspot_model") or {}).get("hotspots") or []))
    if key not in _MEAN_CACHE:
        width, height = MEAN_GRID
        u_values = (np.arange(width) + 0.5) / width
        v_values = (np.arange(height) + 0.5) / height
        fields = _mechanism_fields(u_values, v_values, tectonic_model)
        u_grid, v_grid = np.meshgrid(u_values, v_values)
        provinces = _provinces(u_grid, v_grid, seed)
        area = np.cos((0.5 - v_grid) * math.pi)
        _MEAN_CACHE[key] = {name: float(np.sum(field * provinces * area) / np.sum(area)) for name, field in fields.items()}
    return _MEAN_CACHE[key]


def district_contributions(u_values, v_values, tectonic_model, metallogeny, seed):
    """``{district type: w_k F_k / <F_k>}`` on the ``v x u`` grid (empty without district data)."""
    u_values = np.asarray(u_values, dtype=np.float64)
    v_values = np.asarray(v_values, dtype=np.float64)
    metallogeny = metallogeny if isinstance(metallogeny, dict) else {}
    weights = {name: float(value) for name, value in (metallogeny.get("districts") or {}).items() if name in DISTRICT_TYPES}
    means = _planet_means(tectonic_model, seed)
    present = {name: weight for name, weight in weights.items() if weight > 0.0 and means.get(name, 0.0) > 1e-6}
    if float(metallogeny.get("district_share", 0.0) or 0.0) <= 0.0 or not present:
        return {}
    total = sum(present.values())
    fields = _mechanism_fields(u_values % 1.0, v_values, tectonic_model)
    u_grid, v_grid = np.meshgrid(u_values % 1.0, v_values)
    provinces = _provinces(u_grid, v_grid, seed)
    return {name: weight / total * fields[name] * provinces / means[name] for name, weight in present.items()}


def enrichment(u_values, v_values, tectonic_model, metallogeny, seed):
    """Factor (grid ``v x u``) by which the local crust holds more or less of the element than the planet's mean."""
    contributions = district_contributions(u_values, v_values, tectonic_model, metallogeny, seed)
    if not contributions:
        return np.ones((np.size(v_values), np.size(u_values)))
    share = float(metallogeny.get("district_share", 0.0) or 0.0)
    return (1.0 - share) + share * sum(contributions.values())
