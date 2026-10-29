"""Areal material composition for every world-generation LOD.

Each map level produces three separate products (see
docs/worldgen_material_lod_plan_v001.md):

* substrate: areal rock composition.  LOD0 derives it from lithotectonic
  setting memberships x ontology recipes; every child draws discrete mapped
  units from its parent's composition and keeps a purity-weighted remainder,
  so the expected child composition equals the parent composition;
* cover: fractions of regolith, sediment and ice classes resolved from the
  level's own climate, drainage and geomorphology, each mapped to a catalogue
  material through its ontology formation category;
* visible composition: ``(1 - cover) * substrate + cover materials``, the
  areal fractions True Color mixes linearly.

Architecture invariants: materials, formation categories, setting weights,
optical and mechanical profiles are ontology facts; everything here is a
disposable NumPy projection written to the region's own raster bundle.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import natural_materials
from simulations.world_gen.array_noise import domain_warp_uv, hash_unit, seed_int
from simulations.world_gen.lithotectonic_settings import (
    LITHOTECTONIC_MODEL_VERSION,
    SETTING_IDS,
    SETTINGS,
    box_blur,
    classify_lithotectonic_settings,
    composition_from_memberships,
    normalized_candidate,
    recipe_matrix,
    resolve_setting_recipes,
)
from simulations.world_gen.mechanical_lithology import (
    mechanical_profile_for_material,
    terrain_response_factors,
)


MATERIAL_LOD_MODEL_VERSION = "material-lod-v1-areal-composition"

# Share of a mapped unit occupied by its named lithology.  The remainder is
# the parent's composition (minor lithologies below the unit's map scale).
UNIT_PURITY_BY_LEVEL = {0: 0.0, 1: 0.70, 2: 0.82, 3: 0.90, 4: 0.95, 5: 0.95, 6: 0.97, 7: 0.97}
# Typical mapped-unit size resolved at each level (the cell size a map
# without a grid assumes).  The units themselves are the planet's
# (``crust_units``): a map takes the finest unit rung at least
# ``crust_units.MIN_UNIT_CELLS`` of its cells wide, so a tile refined over a
# footprint far larger than its level's does not turn into single-cell units.
UNIT_SCALE_M_BY_LEVEL = {1: 60_000.0, 2: 6_000.0, 3: 1_200.0, 4: 300.0, 5: 80.0, 6: 20.0, 7: 6.0}
MIN_UNIT_CELLS = 8.0
# Parent composition is Gaussian-smoothed by this many parent cells before a
# child samples it, so child contacts do not trace parent pixels.
PARENT_CONTACT_SMOOTHING_CELLS = 1.5

# Cover classes resolve to catalogue materials through ontology formation
# categories (and, where a category is shared, the affinity profile).
COVER_CLASSES = (
    ("ice", {"volatile_ice"}, None),
    ("alluvium", {"fluvial_sediment"}, None),
    ("aeolian_sand", {"aeolian_sediment", "quartz_sand_accumulation"}, {"sand"}),
    ("loess", {"aeolian_sediment"}, {"loess"}),
    ("lateritic_mantle", {"lateritic_regolith", "saprolitic_regolith"}, None),
    ("clay_mantle", {"weathering_clay"}, None),
    ("duricrust", {"duricrust"}, None),
    ("ferric_coating", {"iron_weathering"}, None),
    ("airless_regolith", {"impact_material"}, None),
    ("impact_ejecta", {"impact_material"}, None),
    ("evaporite", {"evaporite_basin"}, None),
    ("glacial_till", {"glacial_sediment"}, None),
)
# Classes defined by landscape position.  Their materials share formation
# categories with other covers, so they are selected by the ontology's
# ``surface_affinity_profile.depositional_environments`` instead.
ENVIRONMENT_COVER_CLASSES = (
    ("talus", "talus_apron"),
    ("wet_hollow", "wet_hollow"),
)
COVER_CLASS_IDS = tuple(item[0] for item in COVER_CLASSES) + tuple(item[0] for item in ENVIRONMENT_COVER_CLASSES)
# A class without an available material hands its area to its analogue.
COVER_FALLBACKS = {
    "loess": "aeolian_sand",
    "lateritic_mantle": "clay_mantle",
    "duricrust": None,
    "clay_mantle": None,
}
MAX_COVER_FRACTION = 0.97
CLIMATE_DEFINED_COVER_CLASSES = {"duricrust", "lateritic_mantle", "clay_mantle"}

# Surface routing (material_routing.py) per level.  Alluvium keeps this share
# of its area as clasts of the upstream substrate mix (provenance); the rest
# is the catalogue fines.  From BED_SORTING_MIN_LEVEL the share follows
# stream power instead.
PROVENANCE_LITHIC_SHARE = {1: 0.35, 2: 0.45, 3: 0.5}
# Beach sand is sorted and worn: this share of it is still clasts of the rock upstream.
BEACH_LITHIC_SHARE = 0.1
# A delta plain is the river's own alluvium, finer than its bed upstream.
DELTA_LITHIC_SHARE = 0.25
# Rock scarps (``rock_scarps``): the banked foot of a face is talus through
# and through; the rampart in the weak bed below carries a thinner, patchy
# mantle of the cap's debris over its own rock (Schumm & Chorley 1966).
SCARP_TALUS_COVER = 0.9
# Share of a cell that must be rock face for it to shed rockfall.
SCARP_FACE_SOURCE_SHARE = 0.1
SCARP_RAMPART_DEBRIS_COVER = 0.35
CATENA_MIN_LEVEL = 3
TALUS_MIN_LEVEL = 3
FAULT_MIN_LEVEL = 3
CHANNEL_BELT_MIN_LEVEL = 3
BED_SORTING_MIN_LEVEL = 4


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def resample_rows(rows, height, width, default=0.0):
    """Point-aligned bilinear resample of a same-footprint grid to (H, W)."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        return np.full((height, width), float(default), dtype=np.float64)
    source_width = min(len(row) for row in rows)
    if source_width < 1:
        return np.full((height, width), float(default), dtype=np.float64)
    values = np.asarray([row[:source_width] for row in rows], dtype=np.float64)
    values = np.where(np.isfinite(values), values, float(default))
    source_height = values.shape[0]
    if (source_height, source_width) == (height, width):
        return values
    fy = np.linspace(0.0, source_height - 1, height)[:, None]
    fx = np.linspace(0.0, source_width - 1, width)[None, :]
    y0 = np.clip(np.floor(fy).astype(np.int64), 0, source_height - 1)
    x0 = np.clip(np.floor(fx).astype(np.int64), 0, source_width - 1)
    y1 = np.clip(y0 + 1, 0, source_height - 1)
    x1 = np.clip(x0 + 1, 0, source_width - 1)
    ty = fy - y0
    tx = fx - x0
    top = values[y0, x0] * (1.0 - tx) + values[y0, x1] * tx
    bottom = values[y1, x0] * (1.0 - tx) + values[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def _source_bounds(heightmap):
    bounds = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    return {
        "min_u": float(bounds.get("min_u", 0.0) or 0.0),
        "max_u": float(bounds.get("max_u", 1.0) if bounds.get("max_u") is not None else 1.0),
        "min_v": float(bounds.get("min_v", 0.0) or 0.0),
        "max_v": float(bounds.get("max_v", 1.0) if bounds.get("max_v") is not None else 1.0),
    }


def grid_uv(heightmap, height, width):
    bounds = _source_bounds(heightmap)
    u = bounds["min_u"] + (bounds["max_u"] - bounds["min_u"]) * np.arange(width) / max(1, width - 1)
    v = bounds["min_v"] + (bounds["max_v"] - bounds["min_v"]) * np.arange(height) / max(1, height - 1)
    return u, v, bounds


def _candidate_passes_planet_gate(candidate, tags):
    requirements = candidate.get("formation_requirements") if isinstance(candidate.get("formation_requirements"), dict) else {}
    required_all = set(requirements.get("required_all_planet_tags") or [])
    required_any = set(requirements.get("required_any_planet_tags") or [])
    return required_all.issubset(tags) and (not required_any or bool(required_any.intersection(tags)))


def _climate_bounds(candidate, key):
    """Climate niche of a cover material: ontology card first, then candidate."""
    material = natural_materials.MATERIAL_BY_ID.get(str(candidate.get("material_id") or "")) or {}
    for profile in (material.get("surface_affinity_profile"), candidate.get("surface_affinity_profile")):
        if isinstance(profile, dict) and profile.get(key):
            try:
                bounds = [float(value) for value in profile[key]]
            except (TypeError, ValueError):
                continue
            if len(bounds) == 4:
                return tuple(bounds)
    return None


def _trapezoid(values, bounds):
    if not bounds:
        return np.ones(np.shape(values), dtype=np.float64)
    outer_low, ideal_low, ideal_high, outer_high = bounds
    values = np.asarray(values, dtype=np.float64)
    rise = np.where(values >= ideal_low, 1.0, (values - outer_low) / max(1e-9, ideal_low - outer_low))
    fall = np.where(values <= ideal_high, 1.0, (outer_high - values) / max(1e-9, outer_high - ideal_high))
    fit = np.clip(np.minimum(rise, fall), 0.0, 1.0)
    outside = (values > outer_high) | ((values < outer_low) & (outer_low < ideal_low))
    return np.where(outside, 0.0, fit)


def _surface_cover_candidates(natural_material_model):
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    tags = {str(tag) for tag in model.get("planet_tags") or []}
    return [
        candidate
        for candidate in (
            normalized_candidate(item) for item in model.get("likely_materials") or []
            if isinstance(item, dict) and item.get("material_id")
        )
        if str(candidate.get("spatial_representation") or "") == "surface_cover"
        and _candidate_passes_planet_gate(candidate, tags)
    ]


def _depositional_environments(candidate):
    material = natural_materials.MATERIAL_BY_ID.get(str(candidate.get("material_id") or "")) or {}
    for profile in (material.get("surface_affinity_profile"), candidate.get("surface_affinity_profile")):
        if isinstance(profile, dict) and profile.get("depositional_environments"):
            return {str(value) for value in profile["depositional_environments"]}
    return set()


def _cover_options(matches):
    matches = sorted(matches, key=lambda item: (
        -float(item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0),
        -float(item.get("confidence", 0.0) or 0.0),
        str(item["material_id"]),
    ))
    return [
        {
            "material_id": str(candidate["material_id"]),
            "prevalence": max(0.02, float(candidate.get("prevalence_score", candidate.get("confidence", 0.1)) or 0.1)),
            "temperature_k": _climate_bounds(candidate, "temperature_k"),
            "precipitation_mm": _climate_bounds(candidate, "precipitation_mm"),
        }
        for candidate in matches
    ]


def resolve_environment_candidates(natural_material_model, environment):
    """Cover materials whose ontology card lists ``environment``, best first."""
    return _cover_options([
        candidate
        for candidate in _surface_cover_candidates(natural_material_model)
        if environment in _depositional_environments(candidate)
    ])


def resolve_cover_materials(natural_material_model):
    """Map each cover class to its candidate catalogue materials.

    Returns ``(primary, candidates)``: ``primary[class]`` is the most
    prevalent material (or None when the class is unavailable on this
    planet); ``candidates[class]`` lists every chemistry- and tag-valid
    material of the class with its ontology climate niche.  Cover area is
    shared among candidates by climate fit at each cell.
    """
    covers = _surface_cover_candidates(natural_material_model)
    primary = {}
    candidates = {}
    for class_id, categories, profiles in COVER_CLASSES:
        matches = []
        for candidate in covers:
            category = str(candidate.get("formation_category") or "")
            profile_id = str((candidate.get("surface_affinity_profile") or {}).get("profile_id") or "")
            if category not in categories:
                continue
            if profiles is not None and profile_id not in profiles:
                continue
            matches.append(candidate)
        candidates[class_id] = _cover_options(matches)
        primary[class_id] = candidates[class_id][0]["material_id"] if candidates[class_id] else None
    for class_id, environment in ENVIRONMENT_COVER_CLASSES:
        candidates[class_id] = resolve_environment_candidates(natural_material_model, environment)
        primary[class_id] = candidates[class_id][0]["material_id"] if candidates[class_id] else None
    return primary, candidates


def derive_cover_fractions(
    *,
    shape,
    land,
    partition,
    temperature_k,
    precipitation_mm,
    processes,
    ice_mask,
    airless,
    cover_materials,
    lowland_rank=None,
    oxidizing=False,
    impact_ejecta=None,
    catena=None,
    talus=None,
    surface_age=None,
):
    """Return ``{class_id: fraction[H, W]}`` of the visible surface.

    ``partition`` is the geomorphic surface partition (exposed bedrock,
    colluvial, alluvial, weathered-mantle and residual-regolith fractions);
    ``processes`` holds aeolian, weathering, deposition and glacial fields.
    Colluvium and cold frost-shattered regolith stay substrate: they are
    fragments of the local rock, not a new material.

    ``catena`` (LOD3+, ``material_routing.catena_fields``) thins weathered
    mantle on crests, thickens it on toeslopes and collects fines in wet
    hollows.  ``talus`` is the rockfall-apron fraction below cliffs; like
    ejecta it buries the classes beneath it, more so where frost shatters
    the rock face.  ``surface_age`` (0 fresh .. 1 old, 0.5 where unknown;
    ``floodplain_relics``) sorts duricrust and iron films by how long a
    surface has stood: they take time to form, so ground a river crossed
    lately has little of either.
    """
    zeros = np.zeros(shape, dtype=np.float64)
    bedrock = partition.get("exposed_bedrock_fraction", zeros + 0.35)
    alluvial = partition.get("alluvial_cover_fraction", zeros)
    mantle = partition.get("weathered_mantle_fraction", zeros) + partition.get("residual_regolith_fraction", zeros)
    slope = partition.get("slope", zeros)
    if catena:
        thinning = mantle * 0.5 * catena["crest"]
        thickening = bedrock * 0.4 * catena["toeslope"]
        mantle = mantle - thinning + thickening
        bedrock = bedrock + thinning - thickening
    aeolian = processes.get("aeolian", zeros)
    weathering = processes.get("weathering", zeros)
    deposition = processes.get("deposition", zeros)
    glacial = processes.get("glacial", zeros)
    temperature = np.asarray(temperature_k, dtype=np.float64)
    precipitation = np.asarray(precipitation_mm, dtype=np.float64)

    fractions = {class_id: zeros.copy() for class_id in COVER_CLASS_IDS}
    if airless:
        fractions["airless_regolith"] = np.clip(1.0 - bedrock * 0.75, 0.0, MAX_COVER_FRACTION)
    else:
        aeolian_share = np.clip(aeolian / (aeolian + weathering + 0.05), 0.0, 1.0)
        dry = _smooth01((450.0 - precipitation) / 350.0)
        semi_arid = np.exp(-(((precipitation - 420.0) / 220.0) ** 2))
        cool = _smooth01((292.0 - temperature) / 20.0)
        # Wind-blown sand accumulates in depositional sinks (basins, valley
        # floors, lee lowlands); the rest of an arid plain is a gravel lag of
        # the local rock (desert pavement), which stays substrate.
        lowland = np.asarray(lowland_rank, dtype=np.float64) if lowland_rank is not None else np.full(shape, 0.5)
        valley = partition.get("valley", zeros)
        sink = np.clip(0.15 + deposition * 6.0 + (1.0 - lowland) * 0.45 + valley * 0.3, 0.0, 1.0)
        fractions["aeolian_sand"] = mantle * aeolian_share * dry * sink * 0.6
        fractions["loess"] = mantle * aeolian_share * semi_arid * cool * 0.6
        fractions["evaporite"] = mantle * np.clip(deposition * 2.0, 0.0, 1.0) * dry * dry * np.clip(1.0 - slope, 0.0, 1.0) * (1.0 - lowland) * 0.9
        remaining = np.clip(mantle - fractions["aeolian_sand"] - fractions["loess"] - fractions["evaporite"], 0.0, None)
        hot_wet = _smooth01((temperature - 290.0) / 10.0) * _smooth01((precipitation - 1100.0) / 700.0)
        humid = _smooth01((precipitation - 450.0) / 500.0)
        frost = _smooth01((268.0 - temperature) / 12.0)
        if catena:
            # Saturated hollows gather silt and clay washed off the slopes
            # (and gley in place); arid or frozen ground does not saturate.
            fractions["wet_hollow"] = remaining * catena["wet"] * humid * (1.0 - frost) * 0.7
            remaining = remaining - fractions["wet_hollow"]
        fractions["lateritic_mantle"] = remaining * hot_wet * (1.0 - frost)
        fractions["clay_mantle"] = remaining * humid * (1.0 - hot_wet) * (1.0 - frost)
        # Duricrusts and varnish coat only part of a stable arid surface.
        standing = 1.0 if surface_age is None else 0.4 + 1.2 * np.clip(np.asarray(surface_age, dtype=np.float64), 0.0, 1.0)
        fractions["duricrust"] = np.minimum(remaining, remaining * (1.0 - humid) * _smooth01((temperature - 275.0) / 15.0) * 0.35 * standing)
        # Rubification: iron-oxide films on weathered mantle and wind-worked
        # sand under an oxidizing atmosphere.  Strongest where warm,
        # seasonally dry and long exposed; the coating's optical colouring
        # power (ontology card) makes a modest areal share visible.
        if oxidizing:
            seasonal = _smooth01((precipitation - 60.0) / 250.0) * (1.0 - _smooth01((precipitation - 1600.0) / 900.0))
            fractions["ferric_coating"] = (
                (remaining - fractions["duricrust"] + fractions["aeolian_sand"] * 0.5)
                * seasonal
                * _smooth01((temperature - 278.0) / 14.0)
                * (0.12 + 0.18 * np.clip(weathering * 3.0, 0.0, 1.0))
                * standing
            )
        fractions["glacial_till"] = np.clip(glacial * 1.6, 0.0, 1.0) * _smooth01((284.0 - temperature) / 14.0) * np.clip(1.0 - bedrock, 0.0, 1.0) * 0.8
        fractions["alluvium"] = alluvial
    fractions["ice"] = np.where(ice_mask, MAX_COVER_FRACTION, 0.0)
    if talus is not None:
        frost_shattering = _smooth01((283.0 - temperature) / 15.0)
        fractions["talus"] = np.clip(talus, 0.0, 0.9) * (0.55 + 0.45 * frost_shattering)
        for class_id in COVER_CLASS_IDS:
            if class_id not in {"talus", "ice"}:
                fractions[class_id] = fractions[class_id] * (1.0 - fractions["talus"])
    if impact_ejecta is not None:
        # Fresh ejecta blankets and rims bury whatever lay there before.
        fractions["impact_ejecta"] = np.clip(impact_ejecta, 0.0, 1.0) * 0.85
        for class_id in COVER_CLASS_IDS:
            if class_id not in {"impact_ejecta", "ice"}:
                fractions[class_id] = fractions[class_id] * (1.0 - fractions["impact_ejecta"])

    for class_id, analogue in COVER_FALLBACKS.items():
        if cover_materials.get(class_id):
            continue
        if analogue and cover_materials.get(analogue):
            fractions[analogue] = fractions[analogue] + fractions[class_id]
        fractions[class_id] = zeros.copy()
    for class_id in COVER_CLASS_IDS:
        if not cover_materials.get(class_id):
            fractions[class_id] = zeros.copy()

    non_ice = [class_id for class_id in COVER_CLASS_IDS if class_id != "ice"]
    ice = fractions["ice"]
    for class_id in non_ice:
        fractions[class_id] = fractions[class_id] * (1.0 - ice)
    total = sum(fractions[class_id] for class_id in COVER_CLASS_IDS)
    scale = np.where(total > MAX_COVER_FRACTION, MAX_COVER_FRACTION / np.maximum(total, 1e-9), 1.0)
    for class_id in COVER_CLASS_IDS:
        fractions[class_id] = np.where(land, np.clip(fractions[class_id] * scale, 0.0, 1.0), 0.0).astype(np.float32)
    return fractions


def assemble_visible_composition(
    substrate_ids,
    substrate,
    cover_fractions,
    cover_candidates,
    *,
    temperature_k,
    precipitation_mm,
    lithic_sources=None,
    candidate_groups=None,
):
    """Combine substrate and cover into areal fractions over one material list.

    Each cover class's area is shared among its candidate materials in
    proportion to ``prevalence x temperature fit x precipitation fit`` from
    their ontology climate niches (so calcrete, ferricrete and rock varnish,
    or water and CO2 ice, sort themselves by climate).

    ``lithic_sources[class] = (share, composition)`` gives part of a class's
    area to rock fragments: ``share`` of it is laid out as ``composition``
    (``[substrate materials, H, W]``), e.g. alluvium clasts from the upstream
    substrate or talus from the cliff above.  ``candidate_groups[class]`` is
    a list of ``(weight, options)`` that replaces the class's candidates for
    the remaining area, e.g. channel-bed versus floodplain sediment by
    stream power.
    """
    material_ids = list(substrate_ids)
    index = {material_id: position for position, material_id in enumerate(material_ids)}
    cover_total = np.zeros(substrate.shape[1:], dtype=np.float32)
    for class_id in COVER_CLASS_IDS:
        cover_total += cover_fractions[class_id]
    layers = [substrate[position] * (1.0 - cover_total) for position in range(substrate.shape[0])]
    lithic_sources = lithic_sources or {}
    candidate_groups = candidate_groups or {}

    def add(material_id, values):
        if material_id not in index:
            index[material_id] = len(material_ids)
            material_ids.append(material_id)
            layers.append(np.zeros(substrate.shape[1:], dtype=np.float32))
        layers[index[material_id]] = layers[index[material_id]] + values.astype(np.float32)

    def allocate(class_id, fraction, options):
        fits = [
            _trapezoid(temperature_k, option["temperature_k"]) * _trapezoid(precipitation_mm, option["precipitation_mm"])
            for option in options
        ]
        weights = [option["prevalence"] * fit for option, fit in zip(options, fits)]
        total = sum(weights)
        if class_id in CLIMATE_DEFINED_COVER_CLASSES:
            # The class itself is a climate product: area no candidate's
            # niche supports stays a gravel lag of the local rock.
            class_fit = np.maximum.reduce(fits) if len(fits) > 1 else fits[0]
            allocated = fraction * class_fit
            for option, weight in zip(options, weights):
                add(option["material_id"], allocated * np.where(total > 1e-9, weight / np.maximum(total, 1e-9), 0.0))
            return (fraction - allocated).astype(np.float32)
        # Transported covers (sand, alluvium, till, ...) were placed by
        # process fields; where no niche fits, the most prevalent candidate
        # keeps the area.
        fallback = total <= 1e-9
        for position, (option, weight) in enumerate(zip(options, weights)):
            share = np.where(fallback, 1.0 if position == 0 else 0.0, weight / np.maximum(total, 1e-9))
            add(option["material_id"], fraction * share)
        return None

    returned = np.zeros(substrate.shape[1:], dtype=np.float32)
    for class_id in COVER_CLASS_IDS:
        fraction = cover_fractions[class_id]
        options = cover_candidates.get(class_id) or []
        if not options or not np.any(fraction):
            continue
        lithic = lithic_sources.get(class_id)
        if lithic is not None:
            share, source = lithic
            lithic_area = (fraction * np.clip(share, 0.0, 1.0)).astype(np.float32)
            for position in range(substrate.shape[0]):
                layers[position] = layers[position] + lithic_area * source[position].astype(np.float32)
            fraction = fraction - lithic_area
        groups = [(weight, group) for weight, group in candidate_groups.get(class_id) or [] if group]
        if not groups:
            groups = [(None, options)]
        group_total = sum(np.asarray(weight, dtype=np.float64) for weight, _group in groups) if groups[0][0] is not None else None
        for weight, group in groups:
            group_fraction = fraction if weight is None else fraction * np.where(
                group_total > 1e-9, np.asarray(weight) / np.maximum(group_total, 1e-9), 1.0 / len(groups),
            )
            left = allocate(class_id, group_fraction, group)
            if left is not None:
                returned += left
    for position in range(substrate.shape[0]):
        layers[position] = layers[position] + substrate[position] * returned
    cover_total = cover_total - returned
    return material_ids, np.stack(layers).astype(np.float32), cover_total


def label_components(classes, *, wrap_x=False, valid=None):
    """4-connected component labels of an integer class raster (NumPy only)."""
    classes = np.asarray(classes)
    height, width = classes.shape
    labels = np.arange(height * width, dtype=np.int64).reshape(height, width)
    active = np.ones(classes.shape, dtype=bool) if valid is None else np.asarray(valid, dtype=bool)
    labels = np.where(active, labels, -1)
    for _iteration in range(4096):
        previous = labels
        candidates = [labels]
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            rolled_labels = np.roll(labels, shift, axis=axis)
            rolled_classes = np.roll(classes, shift, axis=axis)
            same = (rolled_classes == classes) & active & (rolled_labels >= 0)
            if axis == 0:
                edge = 0 if shift == 1 else height - 1
                same[edge, :] = False
            elif not wrap_x:
                edge = 0 if shift == 1 else width - 1
                same[:, edge] = False
            candidates.append(np.where(same, rolled_labels, np.iinfo(np.int64).max))
        labels = np.where(active, np.minimum.reduce(candidates), -1)
        # Pointer jumping: follow each label to its own current label.
        flat = labels.ravel()
        positive = flat >= 0
        for _jump in range(8):
            jumped = np.where(positive, flat[np.where(positive, flat, 0)], -1)
            if np.array_equal(jumped, flat):
                break
            flat = jumped
        labels = flat.reshape(height, width)
        if np.array_equal(labels, previous):
            break
    unique, dense = np.unique(labels, return_inverse=True)
    dense = dense.reshape(height, width)
    if unique.size and unique[0] < 0:
        dense = dense - 1
    return dense.astype(np.int32)


def material_relief_retention(material_ids):
    values = []
    for material_id in material_ids:
        material = natural_materials.MATERIAL_BY_ID.get(str(material_id)) or {"id": material_id}
        profile = mechanical_profile_for_material(material)
        values.append(float(terrain_response_factors({"aggregate_profile": profile}).get("relief_retention", 1.0) or 1.0))
    return np.asarray(values, dtype=np.float32)


def _latitude_weights(v_values):
    return np.clip(np.cos((0.5 - np.asarray(v_values, dtype=np.float64)) * math.pi), 0.02, 1.0)


def _climate_fields(heightmap, water_cycle, atmosphere, shape, elevation, v_values):
    height, width = shape
    climate = (water_cycle or {}).get("climate_grid") if isinstance((water_cycle or {}).get("climate_grid"), dict) else {}
    temperature_rows = climate.get("temperature_rows_k")
    precipitation_rows = climate.get("annual_precipitation_rows_mm")
    if temperature_rows:
        temperature = resample_rows(temperature_rows, height, width, 273.15)
        climate_source = "resolved_climate"
    else:
        atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
        try:
            mean_temperature = float(atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 250.0)) or 250.0)
        except (TypeError, ValueError):
            mean_temperature = 250.0
        polar = np.abs(np.asarray(v_values)[:, None] - 0.5) * 2.0
        temperature = np.maximum(20.0, mean_temperature + 12.0 - polar * 48.0 - np.maximum(0.0, elevation - float(heightmap.get("sea_level_m") or 0.0)) * 0.0062)
        climate_source = "pre_climate_proxy"
    if precipitation_rows:
        precipitation = np.maximum(0.0, resample_rows(precipitation_rows, height, width, 0.0))
    else:
        polar = np.abs(np.asarray(v_values)[:, None] - 0.5) * 2.0
        precipitation = np.broadcast_to(np.maximum(80.0, 900.0 * (1.0 - polar * 0.7)), shape).astype(np.float64)
    return temperature, precipitation, climate_source


def _process_fields(surface_evolution, shape):
    height, width = shape
    grid = (surface_evolution or {}).get("process_grid") if isinstance((surface_evolution or {}).get("process_grid"), dict) else {}

    def field(key):
        rows = grid.get(key)
        return np.clip(resample_rows(rows, height, width, 0.0), 0.0, 1.0) if rows else np.zeros(shape, dtype=np.float64)

    return {
        "aeolian": field("aeolian_transport_rows"),
        "weathering": field("chemical_weathering_rows"),
        "deposition": field("sediment_deposition_rows"),
        "glacial": field("glacial_erosion_rows"),
    }


def _mask_rows(heightmap, key, shape):
    rows = (heightmap.get("surface_masks") or {}).get(key) if isinstance(heightmap.get("surface_masks"), dict) else None
    if not rows:
        return np.zeros(shape, dtype=bool)
    return resample_rows([[1.0 if value else 0.0 for value in row] for row in rows], shape[0], shape[1], 0.0) >= 0.5


def _elevation(heightmap):
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    width = min(len(row) for row in rows)
    return np.asarray([row[:width] for row in rows], dtype=np.float64)


def _is_airless(atmosphere):
    try:
        return float((atmosphere or {}).get("surface_pressure_bar", 1.0) or 0.0) < 0.0015
    except (TypeError, ValueError):
        return False


def _prune_materials(material_ids, composition, *, minimum_peak=0.02, limit=40):
    peaks = composition.reshape(composition.shape[0], -1).max(axis=1)
    means = composition.reshape(composition.shape[0], -1).mean(axis=1)
    order = sorted(range(len(material_ids)), key=lambda index: (-means[index], material_ids[index]))
    keep = [index for index in order if peaks[index] >= minimum_peak][:limit]
    keep.sort()
    kept = composition[keep]
    total = kept.sum(axis=0)
    kept = kept / np.maximum(total, 1e-6)[None]
    return [material_ids[index] for index in keep], kept.astype(np.float32)


def _surface_context(planet, heightmap, *, water_cycle, surface_evolution, atmosphere):
    from simulations.world_gen.surface_geomorphology import derive_surface_material_partition_fields

    elevation = _elevation(heightmap)
    shape = elevation.shape
    u_values, v_values, bounds = grid_uv(heightmap, shape[0], shape[1])
    sea_level = heightmap.get("sea_level_m")
    land = elevation >= float(sea_level) if sea_level is not None else np.ones(shape, dtype=bool)
    partition = derive_surface_material_partition_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=(shape[1], shape[0]),
    ) or {}
    partition = {
        key: np.asarray(value, dtype=np.float64)
        for key, value in partition.items()
        if hasattr(value, "shape") and tuple(value.shape) == shape
    }
    temperature, precipitation, climate_source = _climate_fields(heightmap, water_cycle, atmosphere, shape, elevation, v_values)
    return {
        "elevation": elevation,
        "shape": shape,
        "u": u_values,
        "v": v_values,
        "bounds": bounds,
        "sea_level": sea_level,
        "land": land,
        "partition": partition,
        "temperature": temperature,
        "precipitation": precipitation,
        "climate_source": climate_source,
        "processes": _process_fields(surface_evolution, shape),
        "ice": _mask_rows(heightmap, "ice_rows", shape) & land,
        "impact_ejecta": regional_crater_ejecta((planet or {}).get("crater_model"), shape),
        "shelf": _mask_rows(heightmap, "continental_shelf_rows", shape).astype(np.float64),
        "airless": _is_airless(atmosphere),
        "wrap_x": bool(heightmap.get("wrap_x", False)) and bounds["min_u"] <= 1e-6 and bounds["max_u"] >= 1.0 - 1e-6,
    }


def regional_crater_ejecta(crater_model, shape):
    """Rim, ejecta blanket and fractured floor of a regional crater model.

    Regional crater models place craters in local 0..1 coordinates with a
    metre diameter and the region's physical extent; each crater only
    touches the cells inside 2.15 radii.  Returns None when the model has no
    metre-scale craters.
    """
    crater_model = crater_model if isinstance(crater_model, dict) else {}
    craters = crater_model.get("craters") or []
    width_m = float(crater_model.get("region_width_m", 0.0) or 0.0)
    height_m = float(crater_model.get("region_height_m", 0.0) or 0.0)
    if not craters or width_m <= 0.0 or height_m <= 0.0 or not any(
        isinstance(crater, dict) and crater.get("diameter_m") is not None for crater in craters
    ):
        return None
    height, width = shape
    x_values = np.arange(width) / max(1, width - 1)
    y_values = np.arange(height) / max(1, height - 1)
    field = np.zeros(shape, dtype=np.float64)
    for crater in craters:
        if not isinstance(crater, dict) or crater.get("diameter_m") is None:
            continue
        try:
            center_x = min(1.0, max(0.0, float(crater.get("x", 0.5) or 0.5)))
            center_y = min(1.0, max(0.0, float(crater.get("y", 0.5) or 0.5)))
            radius_x = max(1e-12, float(crater["diameter_m"]) * 0.5 / width_m)
            radius_y = max(1e-12, float(crater["diameter_m"]) * 0.5 / height_m)
        except (TypeError, ValueError):
            continue
        columns = np.nonzero(np.abs(x_values - center_x) <= radius_x * 2.15)[0]
        rows = np.nonzero(np.abs(y_values - center_y) <= radius_y * 2.15)[0]
        if columns.size == 0 or rows.size == 0:
            continue
        distance = np.hypot(
            (x_values[columns][None, :] - center_x) / radius_x,
            (y_values[rows][:, None] - center_y) / radius_y,
        )
        rim = np.exp(-(((distance - 1.0) / 0.13) ** 2))
        ejecta = np.where(distance >= 1.0, np.exp(-np.maximum(0.0, distance - 1.0) / 0.36), 0.0)
        floor = np.maximum(0.0, 1.0 - distance) * 0.18
        value = np.where(distance <= 2.15, np.clip(rim * 0.92 + ejecta * 0.72 + floor, 0.0, 1.0), 0.0)
        block = np.ix_(rows, columns)
        field[block] = np.maximum(field[block], value)
    return field


def rasterize_occurrences(context, occurrences, circumference_m):
    """Exposed areal fraction of bounded regional bodies, per material.

    Deposits expose part of their lobed footprint (``geometry_fill_fraction``);
    mapped lithologic or cover units expose most of it.  Modal constituents
    have no body and stay inside their host composition.  A body smaller
    than about two cells takes its area's share of the cell holding its
    centre (a 360 m porphyry in a 600 m LOD2 cell is a third of it, not
    nothing).  Ore systems
    (``ore_system``) are not a layer: they return as ``{element: {"share",
    "content_percent", "pyrite_wt"}}`` for ``_element_minerals``, which turns
    them into what their surface shows.  Returns ``(layers, roles, ore)``.
    """
    height, width = context["shape"]
    bounds = context["bounds"]
    center_v = 0.5 * (bounds["min_v"] + bounds["max_v"])
    x_scale = circumference_m * max(0.05, math.cos((0.5 - center_v) * math.pi))
    y_scale = circumference_m * 0.5
    u_values = context["u"]
    v_values = context["v"]
    cell_area_m2 = (
        abs(float(u_values[-1] - u_values[0])) / max(1, width - 1) * x_scale
        * abs(float(v_values[-1] - v_values[0])) / max(1, height - 1) * y_scale
    ) if width > 1 and height > 1 else 0.0
    layers = {}
    roles = {}
    ore = {}
    for occurrence in occurrences or []:
        if not isinstance(occurrence, dict) or not occurrence.get("material_id"):
            continue
        body = occurrence.get("deposit_body") or occurrence.get("material_unit") or {}
        geometry = body.get("geometry") if isinstance(body.get("geometry"), dict) else {}
        vertices = geometry.get("footprint_vertices") or []
        center = occurrence.get("center_global_uv") or {}
        if len(vertices) < 3 or "u" not in center:
            continue
        radius_m = float(geometry.get("bounding_radius_m") or occurrence.get("estimated_radius_m") or 0.0)
        if radius_m <= 0.0:
            continue
        dx = (u_values - float(center["u"]) + 0.5) % 1.0 - 0.5
        dx_m = dx * x_scale
        dy_m = (v_values - float(center["v"])) * y_scale
        is_deposit = occurrence.get("deposit_body") is not None
        system = occurrence.get("ore_system") if is_deposit else None
        # An ore system's weathered top (its cap or oxide zone) spans its whole
        # outline, as a mapped unit does; lenses and veins fill part of theirs.
        exposure = (
            float(geometry.get("geometry_fill_fraction", 0.4) or 0.4) * 0.8
            if is_deposit and not isinstance(system, dict)
            else 0.9
        )
        area_m2 = 0.5 * abs(sum(
            x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(vertices, list(vertices[1:]) + [vertices[0]])
        )) * radius_m * radius_m
        if area_m2 < 2.0 * cell_area_m2:
            # Smaller than about two cells: the cell holding the centre, by area.
            column, row = int(np.argmin(np.abs(dx_m))), int(np.argmin(np.abs(dy_m)))
            if abs(dx_m[column]) * 2.0 > abs(x_scale * (u_values[-1] - u_values[0])) / max(1, width - 1) * 1.01 \
                    or abs(dy_m[row]) * 2.0 > abs(y_scale * (v_values[-1] - v_values[0])) / max(1, height - 1) * 1.01:
                continue
            rows, columns = np.asarray([row]), np.asarray([column])
            inside = np.full((1, 1), True)
            exposure = exposure * min(1.0, area_m2 / cell_area_m2)
        else:
            columns = np.nonzero(np.abs(dx_m) <= radius_m)[0]
            rows = np.nonzero(np.abs(dy_m) <= radius_m)[0]
            if columns.size == 0 or rows.size == 0:
                continue
            px = dx_m[columns][None, :]
            py = dy_m[rows][:, None]
            orientation = math.radians(float(geometry.get("orientation_deg", 0.0) or 0.0))
            local_x = px * math.cos(orientation) + py * math.sin(orientation)
            local_y = -px * math.sin(orientation) + py * math.cos(orientation)
            angle = np.mod(np.arctan2(local_y, local_x), math.tau)
            vertex_angles = np.asarray([math.atan2(y, x) % math.tau for x, y in vertices])
            vertex_radii = np.asarray([math.hypot(x, y) for x, y in vertices])
            order = np.argsort(vertex_angles)
            vertex_angles = np.concatenate([vertex_angles[order], [vertex_angles[order][0] + math.tau]])
            vertex_radii = np.concatenate([vertex_radii[order], [vertex_radii[order][0]]])
            boundary = np.interp(angle, vertex_angles, vertex_radii, period=None) * radius_m
            inside = np.hypot(local_x, local_y) <= boundary
            if not inside.any():
                continue
        block = np.ix_(rows, columns)
        exposed = np.where(inside & context["land"][block], exposure, 0.0)
        if isinstance(system, dict) and system.get("element"):
            fields = ore.setdefault(str(system["element"]), {key: np.zeros((height, width), dtype=np.float64) for key in ("share", "content_percent", "pyrite_wt")})
            fields["share"][block] = np.maximum(fields["share"][block], exposed)
            fields["content_percent"][block] = np.maximum(fields["content_percent"][block], exposed * float(system.get("grade_wt_percent", 0.0) or 0.0))
            fields["pyrite_wt"][block] = np.maximum(fields["pyrite_wt"][block], exposed * float(system.get("pyrite_wt_percent", 0.0) or 0.0))
            continue
        material_id = str(occurrence["material_id"])
        layer = layers.setdefault(material_id, np.zeros((height, width), dtype=np.float64))
        layer[block] = np.maximum(layer[block], exposed)
        roles[material_id] = (
            "sparse_deposit" if is_deposit
            else "local_lithology" if occurrence.get("spatial_representation") == "bedrock_unit"
            else "local_material_unit"
        )
    return layers, roles, ore


def _overlay_occurrences(visible_ids, visible, occurrence_layers):
    """Bounded bodies replace the local composition under their footprint."""
    if not occurrence_layers:
        return visible_ids, visible
    visible_ids = list(visible_ids)
    total = np.zeros(visible.shape[1:], dtype=np.float32)
    for values in occurrence_layers.values():
        total += values.astype(np.float32)
    total = np.clip(total, 0.0, 0.95)
    layers = [visible[position] * (1.0 - total) for position in range(visible.shape[0])]
    for material_id, values in occurrence_layers.items():
        share = np.where(total > 0.0, values.astype(np.float32) / np.maximum(total, 1e-6) * total, 0.0)
        if material_id in visible_ids:
            layers[visible_ids.index(material_id)] = layers[visible_ids.index(material_id)] + share
        else:
            visible_ids.append(material_id)
            layers.append(share)
    return visible_ids, np.stack(layers).astype(np.float32)


def _lowland_rank(elevation, land):
    """0 at the local-scale lowest land, 1 at the highest (per map)."""
    values = elevation[land]
    if values.size < 8:
        return np.full(elevation.shape, 0.5)
    low, high = np.percentile(values, 10.0), np.percentile(values, 90.0)
    return np.clip((elevation - low) / max(1.0, high - low), 0.0, 1.0)


def _fresh_deposit(partition, cover, shape):
    """Lay a deposit the sea or a river is still working on over ``cover`` (0..1) of each cell.

    Sand the waves turn over every storm, and a delta plain every flood,
    carry no weathered mantle and show no bedrock: with only the alluvial
    share raised, a beach came out two thirds saprolite and laterite.
    """
    for key in ("weathered_mantle_fraction", "residual_regolith_fraction", "colluvial_cover_fraction", "exposed_bedrock_fraction"):
        if key in partition:
            partition[key] = partition[key] * (1.0 - cover)
    partition["alluvial_cover_fraction"] = np.maximum(partition.get("alluvial_cover_fraction", np.zeros(shape)), 0.95 * cover)


def _surface_routing(context, heightmap, natural_material_model, substrate, *, level, circumference_m):
    """Routing-driven cover inputs for a child level (see material_routing).

    LOD1+: alluvium carries the upstream substrate mix (provenance).  LOD3+:
    catena and talus.  LOD4+: stream power sorts channel beds (coarse clasts
    and channel-bed sediment in fast reaches, floodplain fines in slack
    water).  Returns keyword arguments for the cover model plus a summary.
    """
    from simulations.world_gen import material_routing as routing

    level = int(level)
    shape = context["shape"]
    if level < 1:
        return {}
    dx, dy = routing.grid_spacing_m(heightmap, shape, context["bounds"], circumference_m)
    elevation, land = context["elevation"], context["land"]
    lithic_sources = {}
    summary = {"spacing_m": [round(dx, 2), round(dy, 2)]}
    result = {}
    from simulations.world_gen import rock_scarps

    scarps = rock_scarps.heightmap_scarp_fields(heightmap, shape)

    def bare_faces():
        """A rock face is bare rock: no mantle clings to it and no alluvium lies on it."""
        if scarps is None:
            return
        face = np.where(land, scarps["face"], 0.0)
        partition = context["partition"]
        for key in ("weathered_mantle_fraction", "residual_regolith_fraction", "alluvial_cover_fraction", "colluvial_cover_fraction"):
            if key in partition:
                partition[key] = partition[key] * (1.0 - face)
        partition["exposed_bedrock_fraction"] = np.maximum(partition.get("exposed_bedrock_fraction", np.zeros(shape)), face)

    if scarps is not None:
        bare_faces()
        for name in ("face", "talus", "rampart"):
            summary[f"scarp_{name}_fraction"] = round(float((scarps[name] > 0.5)[land].mean()) if land.any() else 0.0, 5)
    fine_routing = level >= min(CATENA_MIN_LEVEL, TALUS_MIN_LEVEL, BED_SORTING_MIN_LEVEL)
    # Material routing wanders like water over sub-cell relief instead of
    # ruling straight parallel D8 lines across smooth slopes.
    _receivers, true_gradient = routing.d8_receivers(elevation, dx=dx, dy=dy, wrap_x=context["wrap_x"], sinks=~land)
    # The same micro-relief as ``channel_belts`` uses by default, so talus,
    # catena and provenance follow the routes the terrain was shaped along.
    jitter = routing.routing_jitter(true_gradient, dx=dx, dy=dy, seed=routing.ROUTING_JITTER_SEED + shape[0] * 4099 + shape[1])
    if fine_routing:
        receivers, _jittered_gradient = routing.d8_receivers(elevation + jitter, dx=dx, dy=dy, wrap_x=context["wrap_x"], sinks=~land)
        gradient = true_gradient
        area = routing.upstream_area_m2(receivers, shape, dx=dx, dy=dy)
    def add_talus():
        """Rockfall aprons; only rock faces shed talus.

        Steep walls cut in alluvium (carved channel banks, gullies in a
        floodplain) fail in slumps of their own sediment, so cells under
        half alluvial cover (channel belts included) or near a carved
        channel are not sources.
        """
        from simulations.world_gen.alluvial_channels import heightmap_channel_fields

        rock = np.asarray(context["partition"].get("alluvial_cover_fraction", np.zeros(shape))) < 0.5
        resolved = heightmap_channel_fields(heightmap, shape)
        if resolved is not None:
            rock = rock & (resolved["distance_m"] > 0.5 * resolved["width_m"] * (1.0 + 4.0 * 1.5))
        faces = scarps["face"] > SCARP_FACE_SOURCE_SHARE if scarps is not None else None
        talus_fraction, talus_mix = routing.talus_fields(receivers, gradient, land, substrate, dx=dx, dy=dy, rock=rock, faces=faces)
        if scarps is not None:
            # The scarp profile says where the debris stands; rockfall
            # routing only spreads it further.
            banked = np.where(land, np.maximum(SCARP_TALUS_COVER * scarps["talus"], SCARP_RAMPART_DEBRIS_COVER * scarps["rampart"]), 0.0)
            talus_fraction = np.maximum(talus_fraction, banked)
            local_rock = np.asarray(substrate, dtype=np.float64)
            local_rock = local_rock / np.maximum(local_rock.sum(axis=0), 1e-9)[None]
            talus_mix = np.where((talus_mix.sum(axis=0) <= 1e-9)[None], local_rock, talus_mix)
        result["talus"] = talus_fraction
        lithic_sources["talus"] = (np.ones(shape, dtype=np.float32), talus_mix)
        summary["talus_mean_fraction"] = round(float(talus_fraction.mean()), 5)

    if context["airless"]:
        # No running water: no alluvium, catena or channel beds.
        if level >= TALUS_MIN_LEVEL:
            add_talus()
        result["lithic_sources"] = lithic_sources
        result["summary"] = summary
        return result
    provenance = routing.provenance_composition(elevation, land, substrate, dx=dx, dy=dy, wrap_x=context["wrap_x"], jitter=jitter)
    lithic_share = np.full(shape, PROVENANCE_LITHIC_SHARE.get(level, 0.5), dtype=np.float32)
    if level >= CATENA_MIN_LEVEL:
        catena = routing.catena_fields(elevation, land, gradient, area, dx=dx, dy=dy)
        result["catena"] = catena
        summary["catena_window_radius_cells"] = catena["window_radius_cells"]
    belts = None
    if level >= CHANNEL_BELT_MIN_LEVEL:
        # Local maps resolve where alluvium lies: on channel belts, not as a
        # thin film over every flow line of the geomorphic partition.
        belts = routing.channel_belts(
            elevation, land, dx=dx, dy=dy, wrap_x=context["wrap_x"],
            inflow_cells=routing.inflow_grid(shape, (heightmap or {}).get("boundary_inflow"), dx * dy),
            jitter=jitter,
        )
        partition = context["partition"]
        spread = partition.get("alluvial_cover_fraction", np.zeros(shape))
        partition["alluvial_cover_fraction"] = np.maximum(spread * 0.25, belts["belt"] * 0.9)
        summary["channel_belt_fraction"] = round(float((belts["belt"] > 0)[land].mean()) if land.any() else 0.0, 4)
    if level >= TALUS_MIN_LEVEL:
        add_talus()
    relics = None
    if level >= BED_SORTING_MIN_LEVEL:
        from simulations.world_gen.floodplain_relics import heightmap_relic_fields

        relics = heightmap_relic_fields(heightmap, shape)
        if relics is not None:
            # A surface the river left long ago carries more crust and
            # varnish than one it crossed lately (0 fresh .. 1 old).
            from simulations.world_gen.floodplain_relics import OLD_SURFACE_RELIEF_SHARE

            result["surface_age"] = np.where(
                relics["floodplain"] > 0.0,
                np.clip((1.0 - relics["fresh"]) / (1.0 - OLD_SURFACE_RELIEF_SHARE), 0.0, 1.0), 0.5,
            )
        alluvial = context["partition"].get("alluvial_cover_fraction", np.zeros(shape))
        # Belt routing includes rivers entering the tile; plain D8 area does not.
        power = routing.stream_power_index(belts["area_m2"] if belts is not None else area, gradient, alluvial)
        if belts is not None:
            # The thalweg zone (inner third of the belt) carries the bed load;
            # the rest of the belt is overbank floodplain.
            distance = np.where(np.isfinite(belts["distance_m"]), belts["distance_m"], np.inf)
            thalweg = np.clip(1.0 - distance / np.maximum(0.35 * belts["half_width_m"], max(dx, dy)), 0.0, 1.0)
            thalweg = np.where(belts["channel"], 1.0, thalweg)
            coarse = np.clip(thalweg * (0.5 + 0.5 * power), 0.0, 1.0)
        else:
            coarse = power
        from simulations.world_gen.alluvial_channels import heightmap_channel_fields

        channels = heightmap_channel_fields(heightmap, shape)
        if channels is not None:
            # Resolved channels (alluvial_channels): bed load in the pools and
            # thalweg, finer sand up the point bars, overbank fines on the
            # levees -- the carved geometry replaces the belt's D8 thalweg.
            near = channels["distance_m"] <= 0.5 * channels["width_m"] * (1.0 + 4.0 * 1.5)
            # In a carved channel the bed's power is its depth (thalweg and
            # pools coarse, bars fine): the accumulation of single flow lines
            # over the bed hatched it with straight streaks.  Its floodplain
            # holds overbank fines, not the bed load of a routed thalweg line.
            bed = np.clip(0.2 + 0.8 * channels["depth_fraction"], 0.0, 1.0)
            floodplain_of_carved = np.isfinite(channels["distance_m"]) & (
                channels["distance_m"] <= (belts["half_width_m"] if belts is not None else 0.0)
            )
            coarse = np.where(channels["in_channel"], bed, np.where(near | floodplain_of_carved, 0.0, coarse))
            partition = context["partition"]
            partition["alluvial_cover_fraction"] = np.maximum(
                partition.get("alluvial_cover_fraction", np.zeros(shape)),
                np.where(channels["in_channel"], 1.0, np.where(near, 0.9, 0.0)),
            )
            summary["resolved_channel_cell_fraction"] = round(float(channels["in_channel"][land].mean()) if land.any() else 0.0, 5)
        if relics is not None:
            # The plain a river built from its former courses
            # (floodplain_relics): its bars are the bed load the channel
            # left, coarser on ground the river crossed lately; an abandoned
            # channel fills with the fines of later floods.  A parcel too far
            # from the river to see its belt is still that river's plain.
            active = channels["in_channel"] if channels is not None else np.zeros(shape, dtype=bool)
            plain = np.where(land & ~active, relics["floodplain"], 0.0)
            bar_coarse = (1.0 - relics["floor"]) * (0.45 + 0.35 * relics["fresh"])
            coarse = coarse * (1.0 - plain) + bar_coarse * plain
            partition = context["partition"]
            partition["alluvial_cover_fraction"] = np.maximum(
                partition.get("alluvial_cover_fraction", np.zeros(shape)), 0.9 * plain)
            summary["relic_floodplain_fraction"] = round(float((plain > 0.5)[land].mean()) if land.any() else 0.0, 4)
            summary["relic_channel_floor_fraction"] = round(float((relics["floor"] * plain > 0.5)[land].mean()) if land.any() else 0.0, 4)
        lithic_share = np.clip(0.2 + 0.55 * coarse, 0.15, 0.8).astype(np.float32)
        groups = [
            (coarse, resolve_environment_candidates(natural_material_model, "channel_bed")),
            (1.0 - coarse, resolve_environment_candidates(natural_material_model, "floodplain")),
        ]
        result["candidate_groups"] = {"alluvium": [(weight, group) for weight, group in groups if group]}
        summary["stream_power_mean"] = round(float(power[land].mean()) if land.any() else 0.0, 4)
    from simulations.world_gen.alluvial_fans import FAN_MIN_LEVEL, heightmap_fan_fields

    fans = heightmap_fan_fields(heightmap, shape) if level >= FAN_MIN_LEVEL else None
    if fans is not None and np.any(fans["cover"][land] > 0.0):
        # Alluvial fans fine outward: gravel (ontology ``alluvial_fan``) at the
        # apex, sheetflood sand and silt (``floodplain``) towards the toe.
        cover = np.where(land, fans["cover"], 0.0)
        radial = np.clip(np.where(np.isfinite(fans["radial"]), fans["radial"], 1.0), 0.0, 1.0)
        fan_coarse = cover * (1.0 - radial) ** 0.7
        if relics is not None:
            # On a fan surface the gravel lies on the bars; its abandoned
            # channels hold the fines.
            fan_coarse = fan_coarse * (1.0 - relics["floor"] * relics["floodplain"])
        partition = context["partition"]
        partition["alluvial_cover_fraction"] = np.maximum(partition.get("alluvial_cover_fraction", np.zeros(shape)), 0.85 * cover)
        default_group = resolve_cover_materials(natural_material_model)[1].get("alluvium") or []
        toe_group = resolve_environment_candidates(natural_material_model, "floodplain") or default_group
        fan_group = resolve_environment_candidates(natural_material_model, "alluvial_fan") or toe_group
        base = (result.get("candidate_groups") or {}).get("alluvium") or [(np.ones(shape), default_group)]
        groups = [(fan_coarse, fan_group), (cover - fan_coarse, toe_group)] + [(weight * (1.0 - cover), group) for weight, group in base]
        result["candidate_groups"] = {"alluvium": [(weight, group) for weight, group in groups if group]}
        # Fan gravel is broken catchment rock.
        lithic_share = np.maximum(lithic_share, (0.2 + 0.5 * fan_coarse)).astype(np.float32)
        summary["fan_cover_fraction"] = round(float(cover[land].mean()) if land.any() else 0.0, 4)
    from simulations.world_gen.river_deltas import heightmap_delta_fields

    deltas = heightmap_delta_fields(heightmap, shape)
    if deltas is not None and np.any(deltas["cover"] > 0.0):
        # A delta plain (``river_deltas``) is the river's overbank sand and
        # mud, the ontology's ``floodplain`` sediments.
        plain = np.where(land, deltas["cover"], 0.0)
        partition = context["partition"]
        _fresh_deposit(partition, plain, shape)
        default_group = resolve_cover_materials(natural_material_model)[1].get("alluvium") or []
        plain_group = resolve_environment_candidates(natural_material_model, "floodplain") or default_group
        base = (result.get("candidate_groups") or {}).get("alluvium") or [(np.ones(shape), default_group)]
        groups = [(plain, plain_group)] + [(weight * (1.0 - plain), group) for weight, group in base]
        result["candidate_groups"] = {"alluvium": [(weight, group) for weight, group in groups if group]}
        lithic_share = (lithic_share * (1.0 - plain) + DELTA_LITHIC_SHARE * plain).astype(np.float32)
        summary["delta_plain_fraction"] = round(float((plain > 0.5)[land].mean()) if land.any() else 0.0, 5)
    from simulations.world_gen.shore_deposits import heightmap_shore_fields

    shore = heightmap_shore_fields(heightmap, shape)
    if shore is not None and np.any(shore["cover"] > 0.0):
        # Beach and shoreface (``shore_deposits``): sand the waves have sorted,
        # the ontology's ``shoreline`` sediments; mature, so few rock clasts.
        beach = np.where(land, shore["cover"], 0.0)
        partition = context["partition"]
        _fresh_deposit(partition, beach, shape)
        default_group = resolve_cover_materials(natural_material_model)[1].get("alluvium") or []
        beach_group = resolve_environment_candidates(natural_material_model, "shoreline") or default_group
        base = (result.get("candidate_groups") or {}).get("alluvium") or [(np.ones(shape), default_group)]
        groups = [(beach, beach_group)] + [(weight * (1.0 - beach), group) for weight, group in base]
        result["candidate_groups"] = {"alluvium": [(weight, group) for weight, group in groups if group]}
        lithic_share = (lithic_share * (1.0 - beach) + BEACH_LITHIC_SHARE * beach).astype(np.float32)
        summary["beach_cover_fraction"] = round(float((beach > 0.5)[land].mean()) if land.any() else 0.0, 5)
    lithic_sources["alluvium"] = (lithic_share, provenance)
    summary["alluvium_lithic_share_mean"] = round(float(lithic_share.mean()), 4)
    bare_faces()  # belts, channels and fans above may have laid alluvium across a face
    result["lithic_sources"] = lithic_sources
    result["summary"] = summary
    return result


def _cover_and_visible(context, natural_material_model, substrate_ids, substrate, routing=None):
    routing = routing or {}
    cover_materials, cover_candidates = resolve_cover_materials(natural_material_model)
    cover = derive_cover_fractions(
        shape=context["shape"],
        land=context["land"],
        partition=context["partition"],
        temperature_k=context["temperature"],
        precipitation_mm=context["precipitation"],
        processes=context["processes"],
        ice_mask=context["ice"],
        airless=context["airless"],
        cover_materials=cover_materials,
        lowland_rank=_lowland_rank(context["elevation"], context["land"]),
        oxidizing="oxidizing_surface" in set((natural_material_model or {}).get("planet_tags") or []),
        impact_ejecta=context.get("impact_ejecta"),
        catena=routing.get("catena"),
        talus=routing.get("talus"),
        surface_age=routing.get("surface_age"),
    )
    visible_ids, visible, cover_total = assemble_visible_composition(
        substrate_ids, substrate, cover, cover_candidates,
        temperature_k=context["temperature"], precipitation_mm=context["precipitation"],
        lithic_sources=routing.get("lithic_sources"),
        candidate_groups=routing.get("candidate_groups"),
    )
    visible_ids, visible = _prune_materials(visible_ids, visible)
    return cover, cover_materials, visible_ids, visible, cover_total


def derive_substrate_prior(tectonic_model, natural_material_model, *, map_seed, crater_model=None, radius_m=None, grid=(257, 129)):
    """Pre-heightfield substrate prior: settings from tectonics only.

    Supplies the heightfield with a spatial relief-retention raster (rock
    strength) before the terrain exists.  Passive margins and plate-less
    terrain classes need the heightfield and are resolved afterwards.
    """
    width, height = grid
    u_values = np.arange(width) / max(1, width - 1)
    v_values = np.arange(height) / max(1, height - 1)
    memberships, evidence = classify_lithotectonic_settings(
        u_values, v_values,
        tectonic_model=tectonic_model,
        crater_model=crater_model,
        radius_m=radius_m,
        planet_tags=(natural_material_model or {}).get("planet_tags"),
        smoothing_passes=2,
        wrap_x=True,
    )
    recipes, provenance = resolve_setting_recipes(natural_material_model)
    material_ids, matrix = recipe_matrix(recipes)
    composition = composition_from_memberships(memberships, matrix)
    retention = np.tensordot(material_relief_retention(material_ids), composition, axes=([0], [0]))
    retention = np.clip(retention / np.maximum(composition.sum(axis=0), 1e-6), 0.94, 1.06)
    return {
        "memberships": memberships,
        "material_ids": material_ids,
        "composition": composition,
        "recipes": recipes,
        "recipe_provenance": provenance,
        "relief_retention_rows": np.round(retention.astype(np.float64), 4).tolist(),
        "evidence": evidence,
        "map_seed": str(map_seed),
    }


def derive_lod0_material_product(planet, natural_material_model, heightmap, *, tectonic_model, water_cycle, surface_evolution, atmosphere,
                                 occurrences=None, circumference_m=None):
    """Full LOD0 product: settings, substrate, cover, visible, provinces.

    ``occurrences`` (regional bodies, with ``circumference_m``) only when a
    child map is classified directly because its parent's composition is
    unavailable.
    """
    context = _surface_context(planet, heightmap, water_cycle=water_cycle, surface_evolution=surface_evolution, atmosphere=atmosphere)
    memberships, evidence = classify_lithotectonic_settings(
        context["u"], context["v"],
        tectonic_model=tectonic_model,
        elevation=context["elevation"],
        sea_level=context["sea_level"],
        shelf=context["shelf"],
        crater_model=(planet or {}).get("crater_model"),
        radius_m=(planet or {}).get("radius_m") or ((planet or {}).get("derived_planet_physics") or {}).get("radius_m"),
        planet_tags=(natural_material_model or {}).get("planet_tags"),
        smoothing_passes=2,
        wrap_x=context["wrap_x"],
    )
    recipes, provenance = resolve_setting_recipes(natural_material_model)
    substrate_ids, matrix = recipe_matrix(recipes)
    substrate = composition_from_memberships(memberships, matrix)
    substrate_ids, substrate = _prune_materials(substrate_ids, substrate, minimum_peak=0.01, limit=48)
    cover, cover_materials, visible_ids, visible, cover_total = _cover_and_visible(context, natural_material_model, substrate_ids, substrate)
    occurrence_layers, occurrence_roles, ore = rasterize_occurrences(context, occurrences, circumference_m) if occurrences else ({}, {}, {})
    visible_ids, visible = _overlay_occurrences(visible_ids, visible, occurrence_layers)
    mineral_ids, minerals, mineral_summary = _element_minerals(
        context, planet, natural_material_model, heightmap, water_cycle=water_cycle, surface_evolution=surface_evolution,
        atmosphere=atmosphere, substrate_ids=visible_ids, substrate=visible, tectonic_model=tectonic_model, deposits=ore,
    )
    new_minerals = [material_id for material_id in mineral_ids if material_id not in visible_ids]
    visible_ids, visible = _overlay_element_minerals(visible_ids, visible, mineral_ids, minerals)
    dominant_setting = memberships.argmax(axis=0)
    units = label_components(dominant_setting, wrap_x=context["wrap_x"])
    retention = np.tensordot(material_relief_retention(substrate_ids), substrate, axes=([0], [0]))
    retention = np.clip(retention / np.maximum(substrate.sum(axis=0), 1e-6), 0.94, 1.06)
    return {
        "detail_level": 0,
        "context": context,
        "memberships": memberships,
        "setting_evidence": evidence,
        "recipes": recipes,
        "recipe_provenance": provenance,
        "substrate_ids": substrate_ids,
        "substrate": substrate,
        "cover": cover,
        "cover_materials": cover_materials,
        "cover_total": cover_total,
        "visible_ids": visible_ids,
        "visible": visible,
        "units": units,
        "unit_setting": dominant_setting,
        "relief_retention": retention,
        "occurrence_roles": occurrence_roles,
        "element_minerals": mineral_ids,
        "element_minerals_new": new_minerals,
        "element_mineral_summary": mineral_summary,
    }


def _element_minerals(context, planet, natural_material_model, heightmap, *, water_cycle, surface_evolution, atmosphere,
                      substrate_ids, substrate, tectonic_model, deposits=None):
    """Element minerals at the surface (``element_pigments.surface_minerals``) as map layers.

    The rock map and true colour show the same copper: its fresh host
    minerals and the weathering minerals over them (with the leached cap's
    iron oxides), from the content of the visible mix (each material by what
    it is made of, ``mix_content_percent``), the ore districts
    (``metallogeny``), the ore systems in the ground (``deposits``, from
    ``rasterize_occurrences``), climate, runoff and how long a grain stays in
    the weathering zone.  Returns ``(material_ids, fractions[M, H, W],
    summary)``; fractions are visible areal shares.
    """
    from simulations.world_gen import metallogeny
    from simulations.world_gen.element_pigments import (
        CARBONATE_FULL_CO2_WT, SILICA_FULL_SIO2_WT, material_bulk_percent, mix_content_percent, surface_minerals,
    )
    from simulations.world_gen.strata import planet_strata_seed
    from simulations.world_gen.surface_exposure import derive_surface_exposure_fields
    from simulations.world_gen.true_color import _grid_rows
    from simulations.world_gen.true_color_physics import appearance_environment, residence_years, weathering_slope

    planet = planet if isinstance(planet, dict) else {}
    env = appearance_environment(
        atmosphere, seed=planet.get("world_gen_seed") if isinstance(planet.get("world_gen_seed"), dict) else {},
        natural_material_model=natural_material_model,
    )
    systems = env.get("element_pigments") or []
    if not systems or context["airless"]:
        return [], np.zeros((0,) + context["shape"], dtype=np.float32), {}
    height, width = context["shape"]
    exposure = derive_surface_exposure_fields(
        heightmap, {}, water_cycle=water_cycle, surface_evolution=surface_evolution, target_size=(width, height),
    ) or {}

    def grid(name, default):
        value = exposure.get(name)
        return np.asarray(value, dtype=np.float32) if value is not None and np.shape(value) == (height, width) else np.full((height, width), default, dtype=np.float32)

    runoff_rows = _grid_rows(water_cycle or {}, ("annual_runoff_rows_mm",))
    runoff = np.maximum(resample_rows(runoff_rows, height, width, 0.0), 0.0) if runoff_rows else np.zeros((height, width))
    spacing_x = max(1.0, float(heightmap.get("sample_spacing_x_m") or heightmap.get("equator_resolution_m_per_px") or 1.0))
    spacing_y = max(1.0, float(heightmap.get("sample_spacing_y_m") or spacing_x))
    gradient_y, gradient_x = np.gradient(context["elevation"], spacing_y, spacing_x)
    gradient = np.hypot(gradient_x, gradient_y)
    composition = np.asarray(substrate, dtype=np.float64)
    weights = np.maximum(composition, 0.0)
    seed = planet_strata_seed(planet)
    contents = {}
    for system in systems:
        factor = None
        if (system.get("metallogeny") or {}).get("districts"):
            factor = metallogeny.enrichment(context["u"], context["v"], tectonic_model, system.get("metallogeny"), seed)
        contents[system["element"]] = mix_content_percent(substrate_ids, weights, system, factor)
    bulk = [material_bulk_percent(material_id, "CO2") for material_id in substrate_ids]
    known_bulk = np.asarray([value is not None for value in bulk])[:, None, None]
    carbon = np.asarray([value or 0.0 for value in bulk])[:, None, None]
    silica = np.asarray([material_bulk_percent(material_id, "SiO2") or 0.0 for material_id in substrate_ids])[:, None, None]
    bulk_weight = (weights * known_bulk).sum(axis=0)
    fractions, diagnostics = surface_minerals(
        env,
        {
            "element_content_percent": contents,
            "element_deposits": deposits or {},
            "rock_carbonate": np.where(bulk_weight > 1e-6, (weights * carbon * known_bulk).sum(axis=0) / np.maximum(bulk_weight, 1e-6) / CARBONATE_FULL_CO2_WT, np.nan),
            "rock_silica": np.where(bulk_weight > 1e-6, (weights * silica * known_bulk).sum(axis=0) / np.maximum(bulk_weight, 1e-6) / SILICA_FULL_SIO2_WT, np.nan),
            "aridity": grid("aridity", 1.0),
            "wetness": grid("wetness", 0.0),
            "temperature_k": context["temperature"],
            "runoff_mm": runoff,
        },
        context["land"] & ~context["ice"],
        residence_yr=residence_years(env, grid("age", 0.55), runoff, gradient),
        bedrock=grid("bedrock_exposure", 0.35),
        slope=weathering_slope(gradient),
    )
    material_ids = sorted(fractions)
    stack = np.stack([fractions[material_id] for material_id in material_ids]) if material_ids else np.zeros((0, height, width), dtype=np.float32)
    return material_ids, stack, diagnostics


def _overlay_element_minerals(visible_ids, visible, mineral_ids, minerals):
    """The minerals take their visible share of each cell; everything else there gives way in proportion.

    A mineral already in the mix (goethite of a ferric coating) adds to its layer.
    """
    if not mineral_ids:
        return visible_ids, visible
    total = np.clip(minerals.sum(axis=0), 0.0, 0.95)
    visible = np.asarray(visible) * (1.0 - total)[None]
    ids = list(visible_ids)
    layers = list(visible)
    for material_id, layer in zip(mineral_ids, minerals):
        if material_id in ids:
            layers[ids.index(material_id)] = layers[ids.index(material_id)] + layer
        else:
            ids.append(material_id)
            layers.append(layer)
    return ids, np.stack(layers).astype(np.float32)


def _gaussian_valid(values, sigma, radius):
    """Separable Gaussian over the last two axes, 'valid' mode (shrinks by radius)."""
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    kernel = (kernel / kernel.sum()).astype(values.dtype)
    width = values.shape[-1] - 2 * radius
    height = values.shape[-2] - 2 * radius
    horizontal = sum(kernel[index] * values[..., :, index:index + width] for index in range(kernel.size))
    return sum(kernel[index] * horizontal[..., index:index + height, :] for index in range(kernel.size))


def _parent_composition_sampler(parent, smoothing_cells=PARENT_CONTACT_SMOOTHING_CELLS):
    """Return ``sample(u, v) -> (material_ids, composition[M, H, W])``.

    A parent raster fixes a contact only to within one parent cell, and a
    unit boundary rasterised at the parent resolution is a staircase of
    whole parent cells.  Sampling it bilinearly printed that staircase into
    the child (a 6-7 cell step every few parent cells at LOD2).  The window
    the child needs is Gaussian-smoothed by ``smoothing_cells`` parent cells
    first, so child contacts follow the underlying line instead of the
    steps.  Smoothing conserves the mixture, so the expected child
    composition is unchanged.
    """
    material_ids = list(parent["material_ids"])
    composition = np.asarray(parent["composition"], dtype=np.float32)
    bounds = parent["bounds"]
    _material_count, parent_height, parent_width = composition.shape
    wrap_x = bool(parent.get("wrap_x")) and parent_width > 2
    radius = int(math.ceil(3.0 * smoothing_cells)) if smoothing_cells > 0.0 else 0

    def sample(u_grid, v_grid):
        span_u = max(1e-12, bounds["max_u"] - bounds["min_u"])
        span_v = max(1e-12, bounds["max_v"] - bounds["min_v"])
        local_u = (u_grid - bounds["min_u"]) / span_u
        if wrap_x:
            local_u = np.mod(local_u, 1.0)
        fx = np.clip(local_u, 0.0, 1.0) * (parent_width - 1)
        fy = np.clip((v_grid - bounds["min_v"]) / span_v, 0.0, 1.0) * (parent_height - 1)
        if wrap_x:
            # Unwrap about the child's centre so a window across the seam is contiguous.
            period = parent_width - 1
            centre = float(np.asarray(fx).flat[np.asarray(fx).size // 2])
            fx = centre + np.mod(fx - centre + 0.5 * period, period) - 0.5 * period
        x_lo = int(np.floor(fx.min())) - radius
        y_lo = int(np.floor(fy.min())) - radius
        columns = np.arange(x_lo, int(np.floor(fx.max())) + 2 + radius)
        rows = np.arange(y_lo, int(np.floor(fy.max())) + 2 + radius)
        columns = np.mod(columns, parent_width - 1) if wrap_x else np.clip(columns, 0, parent_width - 1)
        rows = np.clip(rows, 0, parent_height - 1)
        window = composition[:, rows][:, :, columns]
        if radius:
            window = _gaussian_valid(window, float(smoothing_cells), radius)
        gx = fx - (x_lo + radius)
        gy = fy - (y_lo + radius)
        x0 = np.clip(np.floor(gx).astype(np.int64), 0, window.shape[2] - 1)
        y0 = np.clip(np.floor(gy).astype(np.int64), 0, window.shape[1] - 1)
        x1 = np.clip(x0 + 1, 0, window.shape[2] - 1)
        y1 = np.clip(y0 + 1, 0, window.shape[1] - 1)
        tx = (gx - np.floor(gx)).astype(np.float32)
        ty = (gy - np.floor(gy)).astype(np.float32)
        top = window[:, y0, x0] * (1.0 - tx) + window[:, y0, x1] * tx
        bottom = window[:, y1, x0] * (1.0 - tx) + window[:, y1, x1] * tx
        sampled = top * (1.0 - ty) + bottom * ty
        return material_ids, sampled / np.maximum(sampled.sum(axis=0), 1e-6)[None]

    return sample


def _race_select(composition, uniform_at):
    """Draw one material per cell from ``composition`` by exponential race.

    ``uniform_at(m)`` gives each cell's uniform for material ``m``; the
    winner is ``argmin(-log(u_m) / p_m)``, which picks ``m`` with
    probability ``p_m``.  The inverse-CDF draw it replaces walked the
    materials in list order, so where the mixture changed from A to B across
    a contact, whatever sat between A and B in the list won a thin band
    along the contact (a 'ghost' outline).  The race has no order: a third
    material wins no more often at a contact than anywhere else.
    """
    best = np.full(composition.shape[1:], np.inf)
    winner = np.zeros(composition.shape[1:], dtype=np.int64)
    for index in range(composition.shape[0]):
        share = composition[index]
        present = share > 1e-9
        if not present.any():
            continue
        uniform = np.clip(uniform_at(index), 1e-12, 1.0 - 1e-12)
        score = np.where(present, -np.log(uniform) / np.maximum(share, 1e-9), np.inf)
        better = score < best
        winner[better] = index
        best = np.where(better, score, best)
    return winner


def _metric_frame_parameters(circumference_m, center_v, strike_degrees):
    latitude = (0.5 - float(center_v)) * math.pi
    x_scale = circumference_m * max(0.05, math.cos(latitude))
    y_scale = circumference_m * 0.5
    uv_angle = math.radians(float(strike_degrees or 0.0))
    angle = math.atan2(math.sin(uv_angle) * y_scale, math.cos(uv_angle) * x_scale)
    return x_scale, y_scale, angle


def _metric_frame(u_grid, v_grid, circumference_m, center_v, strike_degrees):
    """Rotate global UV into metres along/across structural strike.

    ``strike_degrees`` is measured in UV space (as stored on boundary
    segments); it is converted to the local metric frame first.
    """
    x_scale, y_scale, angle = _metric_frame_parameters(circumference_m, center_v, strike_degrees)
    x = u_grid * x_scale
    y = v_grid * y_scale
    along = x * math.cos(angle) + y * math.sin(angle)
    across = -x * math.sin(angle) + y * math.cos(angle)
    return along, across


def _tile_strain(context, tectonic_model):
    """Cumulative tectonic strain (0..1) on the tile, from the orogen forcing."""
    if isinstance(tectonic_model, dict) and tectonic_model.get("boundary_segments"):
        try:
            from simulations.world_gen.heightmap import cached_orogen_forcing_grid

            forcing = cached_orogen_forcing_grid(context["u"], context["v"], tectonic_model)
            return np.clip(forcing["cumulative_strain_index"], 0.0, 1.0)
        except (KeyError, TypeError, ValueError):
            pass
    return np.zeros(context["shape"])


def derive_child_material_product(
    planet,
    natural_material_model,
    heightmap,
    *,
    parent,
    level,
    map_seed,
    circumference_m,
    strike_degrees=0.0,
    water_cycle=None,
    surface_evolution=None,
    atmosphere=None,
    tectonic_model=None,
    occurrences=None,
):
    """Refine a parent composition into mapped units at ``level``.

    Units are drawn from the parent composition, smoothed and sampled
    through a domain warp (so contacts do not follow parent pixels), by an
    exponential race over per-material draws per strike-elongated cellular
    unit (``_race_select``).  Layered units at LOD2+ draw per bed instead,
    so outcrop belts follow the topography (see ``_layered_beds``).  The child composition keeps the unit purity from
    ``UNIT_PURITY_BY_LEVEL`` and fills the rest from the parent composition,
    which makes the expected child composition equal to the parent's.
    """
    context = _surface_context(planet, heightmap, water_cycle=water_cycle, surface_evolution=surface_evolution, atmosphere=atmosphere)
    height, width = context["shape"]
    u_grid = np.broadcast_to(context["u"][None, :], context["shape"])
    v_grid = np.broadcast_to(context["v"][:, None], context["shape"])
    parent_bounds = parent["bounds"]
    parent_height, parent_width = np.asarray(parent["composition"]).shape[1:]
    parent_cell_u = (parent_bounds["max_u"] - parent_bounds["min_u"]) / max(1, parent_width - 1)
    parent_cell_v = (parent_bounds["max_v"] - parent_bounds["min_v"]) / max(1, parent_height - 1)
    warp_amplitude = max(parent_cell_u, parent_cell_v) * 1.1
    from simulations.world_gen import crust_units, strata

    planet_seed = strata.planet_strata_seed(planet)
    warp_seed = seed_int(planet_seed, f"material_lod{level}:contact_warp")
    warped_u, warped_v = domain_warp_uv(
        u_grid, v_grid, warp_seed,
        amplitude=warp_amplitude,
        frequency=max(4.0, 1.0 / max(1e-9, warp_amplitude * 3.0)),
    )
    material_ids, parent_composition = _parent_composition_sampler(parent)(warped_u, warped_v)

    center_v = 0.5 * (context["bounds"]["min_v"] + context["bounds"]["max_v"])
    along, across = _metric_frame(u_grid, v_grid, circumference_m, center_v, strike_degrees)
    unit_scale = UNIT_SCALE_M_BY_LEVEL.get(int(level), 6.0)
    cell_m = unit_scale / MIN_UNIT_CELLS
    if width > 1 and height > 1:
        cell_m = max(
            math.hypot(float(along[0, 1] - along[0, 0]), float(across[0, 1] - across[0, 0])),
            math.hypot(float(along[1, 0] - along[0, 0]), float(across[1, 0] - across[0, 0])),
        )
        unit_scale = max(unit_scale, MIN_UNIT_CELLS * cell_m)
    # Units and faults are the planet's (``crust_units``): a map of this
    # scale draws the same ones as its neighbours and its other relatives.
    unit_scale = crust_units.unit_scale_for(cell_m)
    radius_m = circumference_m / math.tau
    unit_seed = seed_int(planet_seed, f"crust_units:{unit_scale:g}")
    tectonics = tectonic_model if isinstance(tectonic_model, dict) else {}
    strike_east, strike_south = strata.strike_field(u_grid, v_grid, tectonic_model=tectonics, circumference_m=circumference_m)
    shortening = np.zeros(context["shape"])
    if tectonics.get("boundary_segments"):
        from simulations.world_gen.heightmap import cached_orogen_forcing_grid

        shortening = np.clip(cached_orogen_forcing_grid(context["u"], context["v"], tectonics)["crustal_thickening_index"], 0.0, 1.0)
    fault_traces = []
    heave = None
    shift = None
    if int(level) >= FAULT_MIN_LEVEL:
        def strain_at(fault_u, fault_v):
            if not tectonics.get("boundary_segments"):
                return np.zeros(np.shape(fault_u))
            from simulations.world_gen.heightmap import cached_orogen_forcing_grid

            return np.asarray([
                float(cached_orogen_forcing_grid(np.asarray([fu]), np.asarray([fv]), tectonics)["cumulative_strain_index"][0, 0])
                for fu, fv in zip(np.ravel(fault_u), np.ravel(fault_v))
            ])

        shift, heave, faults = crust_units.planet_faults(
            u_grid, v_grid, unit_scale_m=unit_scale, radius_m=radius_m, seed=unit_seed, strain_at=strain_at,
            strike_at=lambda fault_u, fault_v: strata.strike_field(fault_u, fault_v, tectonic_model=tectonics, circumference_m=circumference_m),
        )
        for start, end, throw, vertical, kind in faults:
            fault_traces.append({
                "points_uv": [[round(start[0], 7), round(start[1], 7)], [round(end[0], 7), round(end[1], 7)]],
                "throw_m": round(float(throw), 1),
                "vertical_throw_m": round(float(vertical), 1),
                "kind": kind,
            })
    unit_keys, unit_centres = crust_units.unit_cells(
        u_grid, v_grid, unit_scale_m=unit_scale, radius_m=radius_m, seed=unit_seed,
        strike_east=strike_east, strike_south=strike_south,
        anisotropy=1.0 + (crust_units.UNIT_ANISOTROPY - 1.0) * shortening, shift=shift,
    )
    unit_values = crust_units.unit_draws(unit_keys, unit_centres, material_ids, unit_scale_m=unit_scale, seed=unit_seed)
    layered_weight = None
    strata_summary = None
    unit_material = _race_select(parent_composition, lambda index: unit_values[index])
    if int(level) >= 2:
        use_beds, bed_material, layered_weight, strata_summary = _layered_beds(
            planet, material_ids, parent_composition, context,
            circumference_m=circumference_m, cell_m=cell_m, tectonic_model=tectonic_model, heave=heave,
        )
        unit_material = np.where(use_beds, bed_material, unit_material)
    if int(level) >= 2:
        from simulations.world_gen import rock_scarps

        scarps = rock_scarps.heightmap_scarp_fields(heightmap, context["shape"])
        if scarps is not None:
            # Both cut the planet's one stack (``strata``), so the beds agree;
            # the cliff record holds one rock per bed for the whole tile (its
            # strength shapes the profile) while the rock map draws each
            # bed's rock from the local composition (a formation changes
            # facies over hundreds of kilometres).  Where a face stands, it
            # shows the strong bed that holds it.
            position_of = {material_id: position for position, material_id in enumerate(material_ids)}
            of_rock = np.asarray([position_of.get(material_id, -1) for material_id in scarps["rock_materials"]] + [-1], dtype=np.int64)
            drawn = of_rock[scarps["rock"]]
            unit_material = np.where((drawn >= 0) & (scarps["face"] > 0.5), drawn, unit_material)
    purity = UNIT_PURITY_BY_LEVEL.get(int(level), 0.9)
    substrate = parent_composition * (1.0 - purity)
    onehot = np.zeros_like(substrate)
    np.put_along_axis(onehot, unit_material[None], 1.0, axis=0)
    substrate = substrate + onehot * purity
    material_ids, substrate = _prune_materials(material_ids, substrate, minimum_peak=0.01, limit=48)
    # Unit ids: one per (cellular unit, drawn lithology).
    keys = (unit_keys % (1 << 50)) * 64 + unit_material.astype(np.int64)
    _unique, units = np.unique(keys, return_inverse=True)
    units = units.reshape(context["shape"]).astype(np.int32)
    routing = _surface_routing(
        context, heightmap, natural_material_model, substrate,
        level=int(level), circumference_m=circumference_m,
    )
    cover, cover_materials, visible_ids, visible, cover_total = _cover_and_visible(
        context, natural_material_model, material_ids, substrate, routing=routing,
    )
    occurrence_layers, occurrence_roles, ore = rasterize_occurrences(context, occurrences, circumference_m)
    visible_ids, visible = _overlay_occurrences(visible_ids, visible, occurrence_layers)
    mineral_ids, minerals, mineral_summary = _element_minerals(
        context, planet, natural_material_model, heightmap, water_cycle=water_cycle, surface_evolution=surface_evolution,
        atmosphere=atmosphere, substrate_ids=visible_ids, substrate=visible, tectonic_model=tectonic_model, deposits=ore,
    )
    new_minerals = [material_id for material_id in mineral_ids if material_id not in visible_ids]
    visible_ids, visible = _overlay_element_minerals(visible_ids, visible, mineral_ids, minerals)
    retention = np.tensordot(material_relief_retention(material_ids), substrate, axes=([0], [0]))
    retention = np.clip(retention / np.maximum(substrate.sum(axis=0), 1e-6), 0.94, 1.06)
    return {
        "detail_level": int(level),
        "context": context,
        "parent_material_ids": list(parent["material_ids"]),
        "unit_purity": purity,
        "unit_scale_m": unit_scale,
        "unit_material_index": unit_material,
        "layered_weight": layered_weight,
        "substrate_ids": material_ids,
        "substrate": substrate,
        "cover": cover,
        "cover_materials": cover_materials,
        "cover_total": cover_total,
        "visible_ids": visible_ids,
        "visible": visible,
        "occurrence_roles": occurrence_roles,
        "units": units,
        "relief_retention": retention,
        "fault_traces": fault_traces,
        "strata": strata_summary,
        "element_minerals": mineral_ids,
        "element_minerals_new": new_minerals,
        "element_mineral_summary": mineral_summary,
        "surface_routing_summary": routing.get("summary") or {},
    }


_LAYERED_CATEGORIES = {
    "carbonate_sedimentary_basin",
    "clastic_sedimentary_basin",
    "evaporite_basin",
    "igneous_extrusive_mafic",
    "igneous_extrusive_intermediate",
    "igneous_extrusive_felsic",
    "pyroclastic_deposit",
    "regional_metamorphism",
}


def _is_layered_material(material_id):
    material = natural_materials.MATERIAL_BY_ID.get(str(material_id)) or {}
    return str(material.get("formation_category") or "") in _LAYERED_CATEGORIES


def _layered_beds(planet, material_ids, composition, context, *, circumference_m, cell_m, tectonic_model, heave=None):
    """Draw layered units per bed of the planet's stack (``strata``).

    The exposed bed at a cell is the one the land surface cuts at
    ``depth = Z_ref - elevation``, with ``Z_ref`` the stack's reference
    horizon from planet fields only (rock uplift, subsidence, regional
    warping, folds where the crust was shortened): valleys expose lower beds,
    ridges keep caps, folds bend the outcrop belts, and a child map cuts the
    same stack as its parent.  ``heave`` (fault vertical offset of this map,
    metres) shifts the depth, so belts step across fault traces.
    Non-layered compositions keep the cellular draw.

    Returns ``(use_beds, bed_material, weight, summary)``: cells that draw
    per bed, the bed's material index per cell, the layered weight and a
    summary for the model.
    """
    from simulations.world_gen import strata

    layered_share = np.zeros(context["shape"], dtype=np.float32)
    for position, material_id in enumerate(material_ids):
        if _is_layered_material(material_id):
            layered_share += composition[position]
    forcing = None
    if isinstance(tectonic_model, dict) and tectonic_model.get("boundary_segments"):
        try:
            from simulations.world_gen.heightmap import cached_orogen_forcing_grid

            forcing = cached_orogen_forcing_grid(context["u"], context["v"], tectonic_model)
        except (KeyError, TypeError, ValueError):
            forcing = None
    seed = strata.planet_strata_seed(planet)
    u_grid = np.broadcast_to(context["u"][None, :], context["shape"])
    v_grid = np.broadcast_to(context["v"][:, None], context["shape"])
    horizon = strata.reference_horizon(
        u_grid, v_grid, tectonic_model=tectonic_model, circumference_m=circumference_m,
        seed=seed, cell_m=cell_m, forcing=forcing,
    )
    depth = horizon - context["elevation"]
    if heave is not None:
        # The upthrown side exposes deeper beds, so belts step at faults.
        depth = depth + heave
    order = strata.resolved_order(depth, cell_m)
    # Beds are layered rock: plutons and the like stay in the cellular draw.
    layered_composition = np.asarray(composition, dtype=np.float64) * np.asarray(
        [1.0 if _is_layered_material(material_id) else 0.0 for material_id in material_ids])[:, None, None]
    layered_composition = layered_composition / np.maximum(layered_composition.sum(axis=0), 1e-9)[None]
    bed_material, beds_by_order = strata.bed_materials(depth, layered_composition, material_ids, order=order, seed=seed)
    weight = np.clip((layered_share - 0.35) / 0.3, 0.0, 1.0)
    use_beds = hash_unit(beds_by_order[0], np.zeros(context["shape"], dtype=np.int64), seed_int(seed, "strata:layered")) < weight
    summary = {
        "bed_order": int(order),
        "bed_thickness_m": strata.BED_THICKNESS_LADDER_M[order],
        "fold_wavelengths_m": strata.fold_wavelengths(cell_m),
        "strata_seed": seed,
    }
    return use_beds, bed_material, weight, summary


def province_table(product, *, planet_id, natural_material_model, crust_composition=None, map_seed="worldgen", max_cards=48, minimum_area_fraction=0.0015):
    """Summarise LOD0 provinces and build their generated location cards."""
    from simulations.world_gen import geochemical_placement as placement

    units = product["units"]
    context = product["context"]
    substrate = product["substrate"]
    substrate_ids = product["substrate_ids"]
    land = context["land"]
    weights = np.broadcast_to(_latitude_weights(context["v"])[:, None], units.shape)
    total_weight = float(weights.sum())
    count = int(units.max()) + 1 if units.size else 0
    flat_units = units.ravel()
    flat_weights = weights.ravel()
    area = np.bincount(flat_units, weights=flat_weights, minlength=count)
    land_area = np.bincount(flat_units, weights=(flat_weights * land.ravel()), minlength=count)
    angle = context["u"][None, :] * math.tau
    sin_u = np.bincount(flat_units, weights=(np.broadcast_to(np.sin(angle), units.shape).ravel() * flat_weights), minlength=count)
    cos_u = np.bincount(flat_units, weights=(np.broadcast_to(np.cos(angle), units.shape).ravel() * flat_weights), minlength=count)
    mean_v = np.bincount(flat_units, weights=(np.broadcast_to(context["v"][:, None], units.shape).ravel() * flat_weights), minlength=count)
    setting_of_unit = np.zeros(count, dtype=np.int64)
    setting_of_unit[flat_units] = product["unit_setting"].ravel()
    composition_sums = np.stack([
        np.bincount(flat_units, weights=(substrate[index].ravel() * flat_weights), minlength=count)
        for index in range(len(substrate_ids))
    ])
    visible = product["visible"]
    visible_ids = product["visible_ids"]
    cover_ids = set(product["cover_materials"].values()) - {None}
    provinces = []
    for unit in range(count):
        if area[unit] <= 0.0:
            continue
        composition = composition_sums[:, unit] / area[unit]
        order = np.argsort(-composition)[:6]
        top = [[substrate_ids[index], round(float(composition[index]), 4)] for index in order if composition[index] > 0.005]
        center_u = (math.atan2(sin_u[unit], cos_u[unit]) / math.tau) % 1.0
        center_v = float(mean_v[unit] / area[unit])
        setting_id = SETTING_IDS[int(setting_of_unit[unit])]
        provinces.append({
            "id": f"province_{unit:04d}",
            "unit_index": unit,
            "setting_id": setting_id,
            "setting_label": next(item["label"] for item in SETTINGS if item["id"] == setting_id),
            "area_fraction": round(float(area[unit] / total_weight), 6),
            "land_fraction": round(float(land_area[unit] / area[unit]), 4),
            "center_u": round(center_u, 6),
            "center_v": round(center_v, 6),
            "center_x": round(center_u, 6),
            "center_y": round(center_v, 6),
            "composition": top,
            "material_id": top[0][0] if top else None,
            "continentality": 0.95 if SETTINGS[int(setting_of_unit[unit])]["crust"] == "continental" else 0.1 if SETTINGS[int(setting_of_unit[unit])]["crust"] == "oceanic" else 0.5,
        })
    # Dominant cover per province (area of each cover material within it).
    if cover_ids:
        cover_positions = [(visible_ids.index(material_id), material_id) for material_id in cover_ids if material_id in visible_ids]
        cover_area = {
            material_id: np.bincount(flat_units, weights=(visible[position].ravel() * flat_weights), minlength=count)
            for position, material_id in cover_positions
        }
        for province in provinces:
            unit = province["unit_index"]
            best = max(
                ((values[unit] / area[unit], material_id) for material_id, values in cover_area.items()),
                default=(0.0, None),
            )
            if best[1] and best[0] >= 0.12:
                province["cover_material_id"] = best[1]
                province["cover_share"] = round(float(best[0]), 4)
    # Element budget: partition the crust inventory over provinces by area and
    # crust type so the area-weighted province profiles equal the global one.
    global_elements = natural_materials._element_abundance_map(crust_composition or {}) if crust_composition else dict((natural_material_model or {}).get("element_profile") or {})
    sources = [
        {"id": province["id"], "area_fraction": max(1e-6, province["area_fraction"]), "continentality": province["continentality"]}
        for province in provinces
    ]
    profiles = placement._local_element_profiles(global_elements, sources, str(map_seed)) if sources and global_elements else [{} for _ in sources]
    for province, elements in zip(provinces, profiles):
        province["elements"] = elements

    candidates = {
        str(item.get("material_id")): item
        for item in (natural_material_model or {}).get("likely_materials") or []
        if isinstance(item, dict) and item.get("material_id")
    }
    card_provinces = sorted(
        (
            province for province in provinces
            if province["area_fraction"] >= minimum_area_fraction
            and province["land_fraction"] >= 0.5
            and province.get("material_id") in candidates
        ),
        key=lambda item: (-item["area_fraction"], item["id"]),
    )[:max_cards]
    cards = []
    for number, province in enumerate(card_provinces, start=1):
        province["body_id"] = f"geounit_{planet_id}_{number:02d}"
        card = placement._body_card(planet_id, province, candidates[province["material_id"]])
        card["name"] = f"{province['setting_label']} — {card['name'].split(' — ')[0]}"
        card["pretty_name"] = card["name"]
        card["lithotectonic_setting"] = province["setting_id"]
        card["material_composition"] = [
            {"material_id": material_id, "areal_fraction": share}
            for material_id, share in province["composition"]
        ]
        cards.append(card)
        cover_id = province.get("cover_material_id")
        if cover_id and cover_id in candidates:
            province["cover_body_id"] = f"geocover_{planet_id}_{number:02d}"
            province["cover_category"] = candidates[cover_id].get("formation_category")
            cover_card = placement._body_card(planet_id, province, candidates[cover_id], kind="surface_material_cover")
            cover_card["surface_cover_share"] = province.get("cover_share")
            cards.append(cover_card)
    return provinces, cards
