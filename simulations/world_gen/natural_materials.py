
"""Ontology-derived runtime material queries for world generation.

Architecture invariants: every material entity and all semantic properties are
authored in the ontology; the mappings below are disposable startup caches.
Generated planets are not persistence targets yet, so changed worldgen
contracts invalidate prior products rather than requiring compatibility paths.
"""

import math

from simulations.world_gen.crust import crust_composition_from_seed
from simulations.world_gen.material_affinities import (
    material_affinity_profile,
    material_distribution_role,
)
from simulations.world_gen.material_formation import formation_contract
from simulations.world_gen.material_optics import (
    linear_reflectance_to_srgb,
    material_optical_surface_profile,
    reflectance_triplet,
)


NATURAL_MATERIAL_CATALOG_VERSION = "natural-materials-v9-ontology-runtime-cache"

# Material truth is loaded from the ontology by WorldModel at application
# startup. This is only an in-memory query cache, never a second registry.
_MATERIAL_CATALOG = ()
MATERIAL_BY_ID = {}
GAS_MATERIAL_BY_MOLECULE = {}



def _coerce_color(value, fallback=None):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [max(0, min(255, int(value[index]))) for index in range(3)]
        except (TypeError, ValueError):
            return fallback
    if isinstance(value, str):
        # Every other user-editable color field in the app (card_color,
        # card_header_color, wiki_field_colors) is stored as a "#rrggbb"
        # hex string -- accept the same format here so a color set from
        # the material card's color picker actually takes effect, not
        # just the [r, g, b] list format the authoring migration writes.
        text = value.strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return [int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)]
            except ValueError:
                return fallback
    return fallback


def material_display_color(material_id, fallback=None):
    material = MATERIAL_BY_ID.get(str(material_id or ""))
    if not isinstance(material, dict):
        return _coerce_color(fallback, [142, 142, 136])
    return _coerce_color(material.get("display_color"), _coerce_color(material.get("band_color"), _coerce_color(fallback, [142, 142, 136])))


def material_geological_map_color(material_id, fallback=None):
    """Return the ontology-authored analytical map color for a material."""
    material = MATERIAL_BY_ID.get(str(material_id or ""))
    neutral = _coerce_color(fallback, [122, 126, 124])
    if not isinstance(material, dict):
        return neutral
    return _coerce_color(material.get("geological_map_color"), neutral)


def configure_material_catalog(materials):
    """Build the process-local material cache from ontology-loaded entries."""
    global _MATERIAL_CATALOG, MATERIAL_BY_ID, GAS_MATERIAL_BY_MOLECULE
    entries = tuple(
        material
        for material in (materials or [])
        if isinstance(material, dict)
        and material.get("id")
        and material.get("material_class") != "material_family"
        and material.get("worldgen_participation") != "none"
    )
    _MATERIAL_CATALOG = entries
    MATERIAL_BY_ID = {str(material["id"]): material for material in entries}
    GAS_MATERIAL_BY_MOLECULE = {
        str(material["atmosphere_molecule"]): material
        for material in entries
        if material.get("material_subclass") == "atmospheric_gas"
        and material.get("atmosphere_molecule")
    }
    return len(entries)


def ensure_material_catalog_configured():
    if not _MATERIAL_CATALOG:
        raise RuntimeError(
            "World-gen material cache is empty; initialize WorldModel from "
            "the ontology before generating a world"
        )


# These compact phase data are deliberately conservative.  They decide
# whether a material can persist as the listed surface phase; the geological
# heatmap decides where a viable material can accumulate.
SURFACE_PHASE_PROPERTIES = {
    "mat_water_ice": {
        "phase": "water_frost",
        "molecule": "H2O",
        "triple_temperature_k": 273.16,
        "triple_pressure_bar": 0.006117,
        "sublimation_enthalpy_j_mol": 51_000.0,
    },
    "mat_carbon_dioxide_ice": {
        "phase": "carbon_dioxide_frost",
        "molecule": "CO2",
        "triple_temperature_k": 216.58,
        "triple_pressure_bar": 5.185,
        "sublimation_enthalpy_j_mol": 25_200.0,
    },
    "mat_sulfur_ice": {
        "phase": "solid_elemental_sulfur",
        "solid_temperature_max_k": 388.36,
    },
}
PHASE_MODEL_VERSION = "surface-phase-v1"
GAS_CONSTANT_J_MOL_K = 8.314462618


def _atmospheric_partial_pressure_bar(atmosphere, molecule):
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    try:
        total_pressure = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    except (TypeError, ValueError):
        total_pressure = 0.0
    fraction = 0.0
    for component in atmosphere.get("composition") or []:
        if not isinstance(component, dict) or str(component.get("molecule") or "") != str(molecule):
            continue
        try:
            fraction = max(fraction, float(component.get("fraction", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return total_pressure * fraction


def material_surface_phase_profile(material_id, atmosphere=None):
    """Return phase constraints for one material at the world's atmosphere."""
    material_id = str(material_id or "")
    property_model = SURFACE_PHASE_PROPERTIES.get(material_id)
    if not isinstance(property_model, dict):
        return {
            "model_version": PHASE_MODEL_VERSION,
            "material_id": material_id,
            "phase": "structural_solid",
            "stability_kind": "solid",
            "transition_temperature_k": None,
        }

    profile = dict(property_model)
    profile.update({"model_version": PHASE_MODEL_VERSION, "material_id": material_id})
    if "solid_temperature_max_k" in profile:
        profile["stability_kind"] = "solid_to_liquid"
        profile["transition_temperature_k"] = float(profile["solid_temperature_max_k"])
        return profile

    partial_pressure = max(1e-12, _atmospheric_partial_pressure_bar(atmosphere, profile["molecule"]))
    triple_pressure = max(1e-12, float(profile["triple_pressure_bar"]))
    triple_temperature = float(profile["triple_temperature_k"])
    sublimation_enthalpy = max(1.0, float(profile["sublimation_enthalpy_j_mol"]))
    # Clausius–Clapeyron, anchored at the triple point.  It is an explicit
    # approximation, suitable for a generator rather than a full EOS.
    denominator = (
        1.0 / triple_temperature
        - GAS_CONSTANT_J_MOL_K / sublimation_enthalpy * math.log(partial_pressure / triple_pressure)
    )
    transition = triple_temperature if denominator <= 0.0 else 1.0 / denominator
    profile.update({
        "stability_kind": "sublimation",
        "partial_pressure_bar": partial_pressure,
        "transition_temperature_k": max(35.0, min(triple_temperature, transition)),
    })
    return profile


def material_surface_phase_stability(material_id, temperature_k, atmosphere=None, profile=None):
    """Evaluate whether a material can persist in its named surface phase."""
    profile = profile if isinstance(profile, dict) else material_surface_phase_profile(material_id, atmosphere=atmosphere)
    try:
        temperature_k = float(temperature_k)
    except (TypeError, ValueError):
        temperature_k = 0.0
    transition = profile.get("transition_temperature_k")
    if transition is None or temperature_k <= 0.0:
        stability = 1.0
    else:
        transition = float(transition)
        softness = max(2.5, transition * 0.025)
        stability = max(0.0, min(1.0, 0.5 + (transition - temperature_k) / (softness * 2.0)))
    return {
        **profile,
        "temperature_k": round(temperature_k, 3),
        "stability": round(stability, 5),
        "stable": stability >= 0.5,
    }


def _blend_colors(weighted_colors, fallback=(132, 126, 116)):
    total = sum(max(0.0, float(weight or 0.0)) for _color, weight in weighted_colors)
    if total <= 0.0:
        return list(fallback)
    channels = [0.0, 0.0, 0.0]
    for color, weight in weighted_colors:
        color = _coerce_color(color)
        if color is None:
            continue
        weight = max(0.0, float(weight or 0.0))
        for index in range(3):
            channels[index] += color[index] * weight
    return [max(24, min(238, int(round(value / total)))) for value in channels]


def _shift_color(color, offset):
    color = _coerce_color(color, [132, 126, 116])
    return [max(20, min(245, int(channel + offset))) for channel in color]


def _mix_colors(color_a, color_b, weight_b):
    """Return a bounded RGB mix without leaking palette math into renderers."""
    color_a = _coerce_color(color_a, [132, 126, 116])
    color_b = _coerce_color(color_b, [132, 126, 116])
    weight_b = max(0.0, min(1.0, float(weight_b or 0.0)))
    return [
        max(20, min(245, int(round(color_a[index] * (1.0 - weight_b) + color_b[index] * weight_b))))
        for index in range(3)
    ]


def _surface_phase_candidates(material_model, atmosphere=None):
    """Choose materials that can control a planet's visible ground colour.

    A composition inference lists every material plausibly present in the
    crust.  Ore minerals are important for resources but should not turn a
    sulfur-coated or basaltic world into an average of every trace mineral.
    Ices, regolith and exposed rocks are therefore treated as surface phases;
    the returned weight is a visual coverage proxy, not a mass fraction.
    """
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    try:
        surface_temperature_k = float(
            atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 0.0)) or 0.0
        )
    except (TypeError, ValueError):
        surface_temperature_k = 0.0
    class_weights = {
        "ice": 5.0,
        "regolith": 1.15,
        "rock": 2.20,
        "mineral": 0.42,
    }
    candidates = []
    planetary_phases = material_model.get("planetary_surface_materials")
    source_materials = (
        planetary_phases
        if isinstance(planetary_phases, list) and planetary_phases
        else material_model.get("likely_materials") or []
    )
    for index, item in enumerate(source_materials):
        if not isinstance(item, dict) or not item.get("material_id"):
            continue
        detail_level = int(item.get("minimum_map_detail_level", 0) or 0)
        if detail_level > 0:
            continue
        material_id = str(item["material_id"])
        catalog_item = MATERIAL_BY_ID.get(material_id, {})
        material_subclass = str(item.get("material_subclass") or catalog_item.get("material_subclass") or "").lower()
        class_weight = class_weights.get(material_subclass, 0.25)
        confidence = max(0.05, float(item.get("confidence", item.get("fraction", 0.0)) or 0.0))
        evidence_tags = {str(tag) for tag in (item.get("evidence_tags") or [])}
        surface_evidence = sum(
            1
            for tag in evidence_tags
            if tag.endswith("_surface") or tag in {"airless_regolith", "cratered_regolith", "impact_gardening"}
        )
        rank_weight = max(0.45, 1.0 - index * 0.06)
        visual_weight = confidence * class_weight * (1.0 + min(0.35, surface_evidence * 0.12)) * rank_weight
        # Deposits and transported regolith can dominate individual basins,
        # but they must not recolour an entire planet at global resolution.
        distribution_scale = str(item.get("distribution_scale") or "planetary_province")
        if distribution_scale != "planetary_province":
            visual_weight *= 0.18
        if material_subclass == "regolith" and not evidence_tags.intersection(
            {"airless_regolith", "cratered_regolith", "impact_gardening"}
        ):
            visual_weight *= 0.58
        phase_stability = material_surface_phase_stability(
            material_id,
            surface_temperature_k,
            atmosphere=atmosphere,
        )
        visual_weight *= float(phase_stability["stability"])
        if visual_weight <= 0.002:
            continue
        formation_category = item.get("formation_category") or catalog_item.get(
            "formation_category"
        )
        optical_profile = material_optical_surface_profile(
            material_id,
            formation_category=formation_category,
            material_subclass=material_subclass,
            display_color=item.get("display_color"),
            explicit=(
                item.get("optical_surface_profile")
                or catalog_item.get("optical_surface_profile")
            ),
        )
        candidates.append({
            "material_id": material_id,
            "name": item.get("name") or catalog_item.get("name") or material_id,
            "material_subclass": material_subclass or "unknown",
            "display_color": material_display_color(material_id, item.get("display_color")),
            "optical_surface_profile": optical_profile,
            "optical_color": linear_reflectance_to_srgb(
                reflectance_triplet(optical_profile)
            ),
            "confidence": confidence,
            "visual_weight": visual_weight,
            "evidence_tags": sorted(evidence_tags),
            "phase_stability": phase_stability,
        })

    # Volatile solids are visually dominant where they persist.  This gives a
    # cold sulfur world its own yellow, sulfur-frosted identity instead of
    # blending it into the colours of associated sulphides and ores.
    ices = [item for item in candidates if item["material_subclass"] == "ice"]
    if ices:
        return sorted(ices, key=lambda item: (-item["visual_weight"], item["name"]))[:4]

    exposed = [item for item in candidates if item["material_subclass"] in {"regolith", "rock"}]
    if exposed:
        return sorted(exposed, key=lambda item: (-item["visual_weight"], item["name"]))[:4]
    return sorted(candidates, key=lambda item: (-item["visual_weight"], item["name"]))[:5]


def natural_material_entries():
    """Return the startup cache built from ontology material individuals."""
    ensure_material_catalog_configured()
    return list(_MATERIAL_CATALOG)


def derive_atmospheric_material_model(atmosphere):
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    composition_rows = atmosphere.get("composition") if isinstance(atmosphere.get("composition"), list) else []
    candidates = []
    for row in composition_rows:
        if not isinstance(row, dict):
            continue
        molecule = row.get("molecule")
        material = GAS_MATERIAL_BY_MOLECULE.get(molecule)
        if material is None:
            continue
        try:
            fraction = max(0.0, float(row.get("fraction", 0.0) or 0.0))
        except (TypeError, ValueError):
            fraction = 0.0
        if fraction <= 0.0005:
            continue
        candidates.append({
            "material_id": material["id"],
            "name": material["name"],
            "material_subclass": material["material_subclass"],
            "scientific_classification": material["scientific_classification"],
            "chemical_formula": material["chemical_formula"],
            "molecule": molecule,
            "fraction": round(fraction, 6),
            "percent": round(fraction * 100.0, 3),
            "band_color": list(material["band_color"]),
            "display_color": material_display_color(material["id"], material["band_color"]),
        })
    candidates.sort(key=lambda item: (-item["fraction"], item["name"]))
    return {
        "status": "inferred",
        "catalog_version": NATURAL_MATERIAL_CATALOG_VERSION,
        "likely_materials": candidates,
        "dominant_materials": [item["material_id"] for item in candidates[:5]],
    }


def atmospheric_band_palette(atmosphere):
    model = derive_atmospheric_material_model(atmosphere)
    materials = model.get("likely_materials") or []
    if not materials:
        return {
            "base_color": [150, 160, 172],
            "bands": [[130, 140, 154], [168, 176, 188], [118, 128, 142]],
        }

    total = sum(float(item.get("fraction", 0.0) or 0.0) for item in materials) or 1.0
    base = [0.0, 0.0, 0.0]
    for item in materials:
        weight = float(item.get("fraction", 0.0) or 0.0) / total
        color = item.get("band_color") or [150, 160, 172]
        for index in range(3):
            base[index] += color[index] * weight

    try:
        temperature = float(atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 250.0)) or 250.0)
    except (TypeError, ValueError):
        temperature = 250.0
    if temperature >= 650.0:
        tint = [44, 20, -12]
    elif temperature <= 170.0:
        tint = [-24, 16, 36]
    else:
        tint = [0, 0, 0]

    base = [
        max(32, min(238, int(base[index] + tint[index])))
        for index in range(3)
    ]
    bands = []
    offsets = [-32, 22, -14, 36, -24, 12, -8, 28]
    for index, offset in enumerate(offsets):
        channel_shift = (index % 3) * 5
        bands.append([
            max(24, min(245, base[0] + offset + channel_shift)),
            max(24, min(245, base[1] + int(offset * 0.55))),
            max(24, min(245, base[2] - int(offset * 0.25))),
        ])
    return {"base_color": base, "bands": bands}


def _element_abundance_map(crust_composition):
    composition = crust_composition_from_seed({"crust_composition": crust_composition})
    abundances = {}
    for group_name in ("major_elements", "trace_elements"):
        for element in composition.get(group_name) or []:
            symbol = str(element.get("symbol") or "").strip()
            if not symbol:
                continue
            try:
                abundance = float(element.get("abundance_percent", 0.0) or 0.0)
            except (TypeError, ValueError):
                abundance = 0.0
            abundances[symbol] = max(abundances.get(symbol, 0.0), abundance)
    return abundances


def derive_planet_material_tags(seed, atmosphere=None, regime=None, terrain=None, crust_type="unknown"):
    seed = seed if isinstance(seed, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    surface = regime.get("surface_processes") if isinstance(regime.get("surface_processes"), dict) else {}
    interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
    composition = _element_abundance_map(seed.get("crust_composition"))

    tags = {"natural_material_context", "silicate_crust"}
    crust_type_key = str(crust_type or interior.get("crust_type") or "unknown").replace(" ", "_")
    if crust_type_key and crust_type_key != "unknown":
        tags.add(f"{crust_type_key}_crust")
    if composition.get("Si", 0.0) >= 27.0:
        tags.add("silica_rich_crust")
    if composition.get("Fe", 0.0) >= 6.0:
        tags.add("iron_rich_crust")
    if composition.get("Mg", 0.0) + composition.get("Fe", 0.0) >= 8.0:
        tags.add("mafic_crust")
    if composition.get("Mg", 0.0) + composition.get("Fe", 0.0) >= 13.0:
        tags.add("ultramafic_tendency")
    if composition.get("Ti", 0.0) >= 0.05:
        tags.add("titanium_bearing_crust")
    if composition.get("C", 0.0) >= 0.01:
        tags.add("carbon_bearing_crust")
    if composition.get("S", 0.0) >= 0.01:
        tags.add("sulfur_bearing_crust")

    hydrology = surface.get("hydrologic_cycle") or terrain.get("hydrology", {}).get("cycle")
    if hydrology in {"active", "limited"}:
        tags.update({"active_hydrology", "weathered_surface", "hydrated_crust"})
    if terrain.get("hydrology", {}).get("target_ocean_fraction", 0.0) or seed.get("water_fraction", 0.0):
        try:
            if float(seed.get("water_fraction", 0.0) or 0.0) >= 0.35:
                tags.add("water_rich_surface")
        except (TypeError, ValueError):
            pass
    if surface.get("aeolian_activity") in {"weak", "moderate", "strong"}:
        tags.add("aeolian_surface")
    if surface.get("crater_retention") == "high" or terrain.get("cratering", {}).get("density", 0.0) >= 0.4:
        tags.update({"cratered_regolith", "impact_gardening"})
    if atmosphere.get("surface_pressure_bar", 1.0) < 0.01:
        tags.add("airless_regolith")
    if interior.get("volcanic_activity") in {"low", "moderate", "high"}:
        tags.add("volcanic_surface")
    if interior.get("volcanic_activity") in {"moderate", "high"}:
        tags.add("active_volcanism")
    if interior.get("tectonic_regime") in {"plate_tectonics", "mobile_lid"}:
        tags.add("plate_tectonic_surface")
    if crust_type_key in {"mafic", "metal-rich"} or "mafic_crust" in tags:
        tags.add("basaltic_surface")

    composition_rows = atmosphere.get("composition") if isinstance(atmosphere.get("composition"), list) else []
    gases = {row.get("molecule"): float(row.get("fraction", 0.0) or 0.0) for row in composition_rows if isinstance(row, dict)}
    if gases.get("CO2", 0.0) >= 0.05:
        tags.add("co2_bearing_atmosphere")
    if gases.get("O2", 0.0) >= 0.01 or "active_hydrology" in tags:
        tags.add("oxidizing_surface")
    if "active_hydrology" in tags and "co2_bearing_atmosphere" in tags and composition.get("Ca", 0.0) >= 1.0:
        tags.add("carbonate_favorable")
    credible_aqueous_reservoir = (
        "active_hydrology" in tags
        or (
            float(seed.get("water_fraction", 0.0) or 0.0) >= 0.08
            and str(seed.get("volatile_inventory") or "").strip().lower()
            not in {"", "none"}
        )
    )
    if (
        composition.get("S", 0.0) >= 0.01
        and composition.get("Ca", 0.0) >= 1.0
        and credible_aqueous_reservoir
    ):
        tags.add("evaporite_favorable")
    if seed.get("volatile_inventory") in {"dry", "thin"}:
        tags.add("arid_surface")
    return sorted(tags)


def _threshold_score(elements, thresholds):
    scores = []
    for symbol, threshold in (thresholds or {}).items():
        threshold = max(0.0001, float(threshold or 0.0))
        abundance = float(elements.get(symbol, 0.0) or 0.0)
        if abundance < threshold:
            return 0.0
        scores.append(min(1.0, abundance / (threshold * 2.0)))
    return sum(scores) / len(scores) if scores else 1.0


def _group_score(elements, groups):
    scores = []
    for group in groups or []:
        options = list(group.get("elements") or [])
        threshold = max(0.0001, float(group.get("threshold", 0.0) or 0.0))
        abundance = max(float(elements.get(symbol, 0.0) or 0.0) for symbol in options) if options else 0.0
        if abundance < threshold:
            return 0.0
        scores.append(min(1.0, abundance / (threshold * 2.0)))
    return sum(scores) / len(scores) if scores else 1.0


def derive_natural_material_model(crust_composition, planet_tags):
    elements = _element_abundance_map(crust_composition)
    tag_set = {str(tag) for tag in planet_tags or []}
    candidates = []
    for material in natural_material_entries():
        if material.get("material_subclass") in {"atmospheric_gas", "element"}:
            continue
        chemistry_score = _threshold_score(elements, material.get("required_element_thresholds"))
        group_score = _group_score(elements, material.get("required_element_groups"))
        if chemistry_score <= 0.0 or group_score <= 0.0:
            continue
        favorable = [tag for tag in material.get("favorable_planet_tags", []) if tag in tag_set]
        tag_score = min(1.0, len(favorable) / max(1, min(3, len(material.get("favorable_planet_tags", [])))))
        confidence = round(min(0.98, chemistry_score * 0.68 + group_score * 0.12 + tag_score * 0.20), 3)
        if confidence < 0.28:
            continue
        if confidence >= 0.75:
            occurrence = "common"
        elif confidence >= 0.52:
            occurrence = "probable"
        else:
            occurrence = "possible"
        affinity_profile = material_affinity_profile(material["id"])
        formation = formation_contract(
            material["id"],
            material.get("material_subclass"),
            (affinity_profile or {}).get("profile_id"),
            explicit_category=material.get("formation_category"),
            explicit_representation=material.get("spatial_representation"),
        )
        relative_abundance = max(
            0.0,
            min(
                1.0,
                float((affinity_profile or {}).get("abundance", 0.35) or 0.0),
            ),
        )
        profile_id = str((affinity_profile or {}).get("profile_id") or "")
        # Fixed profile abundance describes the usual world, but strongly
        # non-terrestrial bulk chemistry must be allowed to change which
        # substrate wins the limited planetary layer budget.
        if "ultramafic_tendency" in tag_set:
            if profile_id == "ultramafic_bedrock":
                relative_abundance = min(1.0, relative_abundance * 1.72)
            elif (
                profile_id == "mafic_bedrock"
                and material.get("material_subclass") == "rock"
            ):
                relative_abundance *= 0.72
        if "active_volcanism" in tag_set:
            if material.get("id") == "mat_basalt":
                relative_abundance = 1.0
            elif material.get("id") == "mat_anorthosite":
                # Anorthosite can form planetary provinces, but it should not
                # out-rank fresh basalt on a currently resurfacing mafic world.
                relative_abundance *= 0.42
        minimum_detail_level = int(
            (affinity_profile or {}).get("minimum_map_detail_level", 0) or 0
        )
        carbon_rich_foundation = (
            material.get("id") == "mat_graphite"
            and elements.get("C", 0.0) >= 8.0
        )
        if carbon_rich_foundation:
            minimum_detail_level = 0
            relative_abundance = 1.0
        elif material.get("material_subclass") == "mineral":
            minimum_detail_level = max(1, minimum_detail_level)
        prevalence_score = round(confidence * relative_abundance, 4)
        distribution_scale = {
            0: "planetary_province",
            1: "macroregional_occurrence",
            2: "regional_deposit",
            3: "local_occurrence",
            4: "site_outcrop",
        }.get(minimum_detail_level, "local_occurrence")
        candidates.append({
            "material_id": material["id"],
            "name": material["name"],
            "material_subclass": material["material_subclass"],
            "scientific_classification": material["scientific_classification"],
            "chemical_formula": material["chemical_formula"],
            "display_color": material_display_color(material["id"]),
            "geological_map_color": material_geological_map_color(material["id"]),
            "mechanical_class": material.get("mechanical_class"),
            "mechanical_rock_profile": dict(material.get("mechanical_rock_profile") or {}),
            "optical_surface_profile": material_optical_surface_profile(
                material["id"],
                formation_category=formation.get("category_id"),
                material_subclass=material["material_subclass"],
                display_color=material_display_color(material["id"]),
                explicit=material.get("optical_surface_profile"),
            ),
            "confidence": confidence,
            "relative_abundance": relative_abundance,
            "prevalence_score": prevalence_score,
            "occurrence": occurrence,
            "minimum_map_detail_level": minimum_detail_level,
            "distribution_scale": distribution_scale,
            "distribution_role": (
                "bedrock"
                if carbon_rich_foundation
                else material_distribution_role(
                    material["id"],
                    material.get("material_subclass"),
                    minimum_detail_level,
                )
            ),
            "evidence_tags": favorable,
            "surface_affinity_profile": affinity_profile,
            "formation_category": formation.get("category_id"),
            "formation_process": formation.get("formation_process"),
            "spatial_representation": formation.get("spatial_representation"),
            "formation_requirements": {
                "required_all_planet_tags": formation.get("required_all_planet_tags") or [],
                "required_any_planet_tags": formation.get("required_any_planet_tags") or [],
                "host_formation_categories": formation.get("host_formation_categories") or [],
                "local_minimums": formation.get("local_minimums") or {},
                "valid_scale_levels": formation.get("valid_scale_levels") or [],
            },
            "foundational_lithology": carbon_rich_foundation,
        })

    candidates.sort(key=lambda item: (
        -item["prevalence_score"],
        -item["confidence"],
        item["name"],
    ))
    palette = derive_planet_surface_palette({
        "likely_materials": candidates,
        "element_profile": elements,
    })
    planetary_materials = [
        item for item in candidates
        if int(item.get("minimum_map_detail_level", 0) or 0) == 0
    ]
    regional_candidates = [
        item for item in candidates
        if int(item.get("minimum_map_detail_level", 0) or 0) > 0
    ]
    return {
        "status": "inferred",
        "catalog_version": NATURAL_MATERIAL_CATALOG_VERSION,
        "planet_tags": sorted(tag_set),
        "element_profile": elements,
        "likely_materials": candidates,
        "planetary_surface_materials": planetary_materials,
        "regional_material_candidates": regional_candidates,
        "dominant_materials": [
            item["material_id"] for item in planetary_materials[:5]
        ],
        "surface_palette": palette,
    }


def derive_planet_surface_palette(material_model, atmosphere=None, terrain=None):
    material_model = material_model if isinstance(material_model, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    surface_phases = _surface_phase_candidates(material_model, atmosphere=atmosphere)
    weighted = [
        (item.get("optical_color") or item["display_color"], item["visual_weight"])
        for item in surface_phases
    ]
    evidence = [
        {
            "material_id": item["material_id"],
            "name": item["name"],
            "material_subclass": item["material_subclass"],
            "weight": round(item["visual_weight"], 4),
            "confidence": round(item["confidence"], 3),
            "display_color": item["display_color"],
            "optical_color": item.get("optical_color"),
            "optical_surface_profile": item.get("optical_surface_profile"),
            "phase": item["phase_stability"].get("phase"),
            "phase_transition_temperature_k": item["phase_stability"].get("transition_temperature_k"),
            "phase_stability": item["phase_stability"].get("stability"),
        }
        for item in surface_phases
    ]

    element_profile = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}
    phase_subclasses = {item["material_subclass"] for item in surface_phases}
    # Bulk chemistry supplies a useful fallback for ordinary rock worlds, but
    # it must not wash out a physically distinct surface phase such as sulfur
    # ice.  That phase has already formed from the bulk composition.
    if not phase_subclasses.intersection({"ice", "regolith", "rock"}):
        for symbol, abundance in sorted(element_profile.items(), key=lambda row: -float(row[1] or 0.0))[:4]:
            element_id = f"mat_element_{str(symbol).lower()}"
            color = material_display_color(element_id)
            weight = max(0.0, float(abundance or 0.0)) / 100.0 * 0.35
            weighted.append((color, weight))
            evidence.append({
                "material_id": element_id,
                "name": symbol,
                "weight": round(weight, 4),
                "display_color": color,
            })

    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    try:
        ocean_fraction = float(hydrology.get("target_ocean_fraction", 0.0) or 0.0)
        ice_fraction = float(hydrology.get("target_ice_fraction", 0.0) or 0.0)
    except (TypeError, ValueError):
        ocean_fraction = 0.0
        ice_fraction = 0.0
    # Oceans and sea ice have their own renderer layers.  Mixing their colours
    # into the land palette made every continent converge toward one muddy
    # global tint.  Only grounded ice modifies the land palette here.
    if ice_fraction > 0.02:
        weighted.append(([210, 224, 232], min(0.35, ice_fraction * 0.45)))

    if not weighted and isinstance(atmosphere.get("composition"), list):
        atmosphere_palette = atmospheric_band_palette(atmosphere)
        weighted.append((atmosphere_palette.get("base_color", [150, 160, 172]), 1.0))

    surface = _blend_colors(weighted)
    phase_palette = bool(surface_phases and phase_subclasses.intersection({"ice", "regolith", "rock"}))
    if phase_palette:
        # A phase-led palette preserves the terrain's relief while keeping the
        # material legible at a glance.  Sulfur ice consequently reads as
        # dark ochre lowlands, sulfur-yellow plains and pale sulfur frost at
        # altitude rather than a uniformly tan crater field.
        palette = [
            _mix_colors(surface, [26, 24, 20], 0.43),
            surface,
            _mix_colors(surface, [238, 232, 204], 0.30),
            _mix_colors(surface, [20, 18, 16], 0.58),
        ]
    else:
        palette = [
            _shift_color(surface, -28),
            surface,
            _shift_color(surface, 24),
            _shift_color(surface, -12),
        ]
    primary = surface_phases[0] if surface_phases else None
    return {
        "palette_version": 3,
        "selection_scope": "planetary_surface_only",
        "render_mode": "surface_phase" if phase_palette else "bulk_composition",
        "surface_color": surface,
        "palette": palette,
        "primary_surface_material": primary.get("material_id") if primary else None,
        "primary_surface_material_name": primary.get("name") if primary else None,
        "surface_materials": evidence[:4],
        "evidence": evidence[:8],
    }
