"""Climatic and topographic controls for solid-surface natural materials.

The catalog answers "can this material exist from the available chemistry?"
These profiles answer "where could it plausibly be exposed or concentrated?"
Every natural material id is mapped explicitly so new catalog entries cannot
quietly inherit a generic planetary paint rule.
"""

import math


def _profile(*, weights, temperature_k=None, precipitation_mm=None,
             substrate="land", abundance=1.0, regionality=0.35,
             min_weathering=None, min_drainage=None, max_ice=None,
             requires_active_hydrology=False, requires_active_volcanism=False):
    return {
        "weights": dict(weights),
        "temperature_k": temperature_k,
        "precipitation_mm": precipitation_mm,
        "substrate": substrate,
        "abundance": float(abundance),
        "regionality": float(regionality),
        "min_weathering": min_weathering,
        "min_drainage": min_drainage,
        "max_ice": max_ice,
        "requires_active_hydrology": bool(requires_active_hydrology),
        "requires_active_volcanism": bool(requires_active_volcanism),
    }


AFFINITY_ARCHETYPES = {
    "felsic_bedrock": _profile(
        weights={"land": 0.30, "highland": 0.24, "erosion": 0.14, "slope": 0.12, "regional": 0.20},
        abundance=0.95, regionality=0.28,
    ),
    "mafic_bedrock": _profile(
        weights={"land": 0.25, "volcanic": 0.26, "highland": 0.16, "resurfacing": 0.18, "regional": 0.15},
        abundance=0.95, regionality=0.32,
    ),
    "ultramafic_bedrock": _profile(
        weights={"land": 0.22, "volcanic": 0.24, "highland": 0.20, "slope": 0.14, "regional": 0.20},
        abundance=0.58, regionality=0.48,
    ),
    "intermediate_volcanic": _profile(
        weights={"land": 0.20, "volcanic": 0.31, "resurfacing": 0.24, "highland": 0.12, "regional": 0.13},
        abundance=0.82, regionality=0.38,
    ),
    "felsic_volcanic": _profile(
        weights={"land": 0.18, "volcanic": 0.34, "resurfacing": 0.24, "highland": 0.10, "regional": 0.14},
        abundance=0.68, regionality=0.44,
    ),
    "fresh_pyroclastic": _profile(
        weights={"land": 0.14, "volcanic": 0.38, "resurfacing": 0.30, "slope": 0.08, "regional": 0.10},
        abundance=0.50, regionality=0.58, requires_active_volcanism=True,
    ),
    "plutonic_mineral": _profile(
        weights={"land": 0.24, "highland": 0.25, "erosion": 0.20, "slope": 0.12, "regional": 0.19},
        abundance=0.58, regionality=0.46,
    ),
    "metamorphic_uplift": _profile(
        weights={"land": 0.20, "highland": 0.28, "slope": 0.22, "erosion": 0.18, "regional": 0.12},
        abundance=0.42, regionality=0.56,
    ),
    "hydrothermal": _profile(
        weights={"land": 0.14, "volcanic": 0.24, "resurfacing": 0.26, "slope": 0.10, "drainage": 0.10, "regional": 0.16},
        abundance=0.34, regionality=0.68,
    ),
    "sulfide_ore": _profile(
        weights={"land": 0.12, "volcanic": 0.25, "resurfacing": 0.27, "highland": 0.10, "weathering": 0.08, "regional": 0.18},
        abundance=0.25, regionality=0.74,
    ),
    "heavy_mineral": _profile(
        weights={"land": 0.18, "erosion": 0.18, "deposition": 0.21, "shoreline": 0.16, "drainage": 0.13, "regional": 0.14},
        abundance=0.28, regionality=0.68,
    ),
    "fluvial_sediment": _profile(
        weights={"land": 0.14, "lowland": 0.21, "drainage": 0.27, "deposition": 0.24, "shoreline": 0.06, "regional": 0.08},
        precipitation_mm=(120.0, 450.0, 2600.0, 5000.0), abundance=0.88, regionality=0.25,
        requires_active_hydrology=True,
    ),
    "fine_basin_sediment": _profile(
        weights={"land": 0.12, "lowland": 0.25, "deposition": 0.30, "drainage": 0.14, "shoreline": 0.10, "regional": 0.09},
        precipitation_mm=(80.0, 300.0, 3200.0, 5000.0), abundance=0.78, regionality=0.30,
    ),
    "sand": _profile(
        weights={"land": 0.13, "lowland": 0.18, "aeolian": 0.25, "deposition": 0.18, "shoreline": 0.17, "regional": 0.09},
        precipitation_mm=(0.0, 0.0, 900.0, 2200.0), abundance=0.90, regionality=0.27,
    ),
    "loess": _profile(
        weights={"land": 0.15, "lowland": 0.14, "aeolian": 0.31, "deposition": 0.18, "glacial": 0.12, "regional": 0.10},
        temperature_k=(245.0, 260.0, 290.0, 305.0), precipitation_mm=(80.0, 180.0, 700.0, 1300.0),
        abundance=0.58, regionality=0.42,
    ),
    "conglomerate": _profile(
        weights={"land": 0.14, "slope": 0.20, "erosion": 0.20, "drainage": 0.20, "deposition": 0.14, "regional": 0.12},
        precipitation_mm=(100.0, 350.0, 3000.0, 5000.0), abundance=0.52, regionality=0.50,
    ),
    "carbonate_basin": _profile(
        weights={"land": 0.10, "lowland": 0.22, "deposition": 0.25, "shoreline": 0.18, "drainage": 0.10, "carbonate": 0.15},
        temperature_k=(265.0, 280.0, 315.0, 335.0), precipitation_mm=(80.0, 250.0, 2200.0, 4200.0),
        abundance=0.62, regionality=0.38,
    ),
    "spring_carbonate": _profile(
        weights={"land": 0.12, "drainage": 0.24, "volcanic": 0.20, "slope": 0.12, "carbonate": 0.18, "regional": 0.14},
        temperature_k=(260.0, 275.0, 330.0, 370.0), abundance=0.26, regionality=0.74,
    ),
    "evaporite": _profile(
        weights={"land": 0.12, "lowland": 0.25, "aridity": 0.28, "deposition": 0.18, "shoreline": 0.10, "regional": 0.07},
        temperature_k=(260.0, 280.0, 335.0, 365.0), precipitation_mm=(0.0, 0.0, 280.0, 750.0),
        abundance=0.46, regionality=0.56,
    ),
    "hydrated_alteration": _profile(
        weights={"land": 0.16, "weathering": 0.24, "drainage": 0.18, "volcanic": 0.13, "slope": 0.10, "regional": 0.19},
        temperature_k=(250.0, 270.0, 315.0, 345.0), precipitation_mm=(120.0, 400.0, 3200.0, 5000.0),
        abundance=0.52, regionality=0.46,
    ),
    "clay_weathering": _profile(
        weights={"land": 0.14, "weathering": 0.30, "drainage": 0.17, "deposition": 0.18, "lowland": 0.11, "regional": 0.10},
        temperature_k=(255.0, 275.0, 315.0, 345.0), precipitation_mm=(180.0, 550.0, 3500.0, 5000.0),
        abundance=0.76, regionality=0.30, min_weathering=0.06,
    ),
    "saprolite": _profile(
        weights={"land": 0.18, "weathering": 0.34, "drainage": 0.14, "low_slope": 0.14, "age": 0.12, "regional": 0.08},
        temperature_k=(265.0, 282.0, 315.0, 338.0), precipitation_mm=(350.0, 800.0, 3600.0, 5000.0),
        abundance=0.54, regionality=0.38, min_weathering=0.12,
    ),
    "laterite": _profile(
        weights={"land": 0.13, "weathering": 0.34, "drainage": 0.15, "highland": 0.08, "low_slope": 0.12, "age": 0.10, "regional": 0.08},
        temperature_k=(278.0, 291.0, 315.0, 335.0), precipitation_mm=(650.0, 1200.0, 3300.0, 4800.0),
        abundance=0.34, regionality=0.58, min_weathering=0.20, min_drainage=0.08, max_ice=0.05,
    ),
    "bauxite": _profile(
        weights={"land": 0.10, "weathering": 0.38, "drainage": 0.18, "highland": 0.08, "low_slope": 0.10, "age": 0.10, "regional": 0.06},
        temperature_k=(283.0, 296.0, 315.0, 330.0), precipitation_mm=(900.0, 1600.0, 3400.0, 4700.0),
        abundance=0.16, regionality=0.78, min_weathering=0.32, min_drainage=0.16, max_ice=0.0,
    ),
    "nickel_laterite": _profile(
        weights={"land": 0.10, "weathering": 0.34, "drainage": 0.14, "highland": 0.11, "low_slope": 0.09, "age": 0.10, "regional": 0.12},
        temperature_k=(280.0, 293.0, 316.0, 335.0), precipitation_mm=(700.0, 1300.0, 3200.0, 4700.0),
        abundance=0.12, regionality=0.82, min_weathering=0.26, min_drainage=0.10, max_ice=0.0,
    ),
    "iron_weathering": _profile(
        weights={"land": 0.15, "weathering": 0.29, "drainage": 0.12, "aridity": 0.10, "age": 0.12, "regional": 0.12, "low_slope": 0.10},
        temperature_k=(260.0, 280.0, 325.0, 350.0), precipitation_mm=(80.0, 300.0, 2600.0, 4300.0),
        abundance=0.42, regionality=0.48, min_weathering=0.08,
    ),
    "duricrust": _profile(
        weights={"land": 0.14, "weathering": 0.24, "aridity": 0.18, "low_slope": 0.16, "age": 0.16, "regional": 0.12},
        temperature_k=(265.0, 282.0, 325.0, 345.0), precipitation_mm=(80.0, 220.0, 1000.0, 1900.0),
        abundance=0.30, regionality=0.60, min_weathering=0.08,
    ),
    "organic_wetland": _profile(
        weights={"land": 0.12, "lowland": 0.22, "humidity": 0.22, "drainage": 0.10, "deposition": 0.18, "low_slope": 0.10, "regional": 0.06},
        temperature_k=(260.0, 275.0, 310.0, 325.0), precipitation_mm=(500.0, 900.0, 4000.0, 5000.0),
        abundance=0.24, regionality=0.60, min_drainage=0.04,
    ),
    "glacial_sediment": _profile(
        weights={"land": 0.12, "glacial": 0.38, "lowland": 0.12, "deposition": 0.18, "polar": 0.12, "regional": 0.08},
        temperature_k=(180.0, 220.0, 271.0, 282.0), precipitation_mm=(40.0, 180.0, 2200.0, 4000.0),
        abundance=0.72, regionality=0.32,
    ),
    "impact": _profile(
        weights={"impact": 0.90, "regional": 0.10}, substrate="either",
        abundance=0.94, regionality=0.0,
    ),
    "water_ice": _profile(
        weights={"ice": 0.44, "polar": 0.24, "highland": 0.12, "ocean": 0.10, "regional": 0.10},
        temperature_k=(20.0, 20.0, 268.0, 278.0), substrate="either", abundance=1.0, regionality=0.18,
    ),
    "co2_ice": _profile(
        weights={"ice": 0.34, "polar": 0.36, "highland": 0.14, "regional": 0.16},
        temperature_k=(20.0, 20.0, 175.0, 205.0), substrate="either", abundance=0.72, regionality=0.30,
    ),
    "sulfur_surface": _profile(
        weights={"land": 0.10, "volcanic": 0.34, "resurfacing": 0.32, "highland": 0.08, "regional": 0.16},
        temperature_k=(40.0, 80.0, 360.0, 390.0), abundance=0.36, regionality=0.62,
    ),
}


MATERIAL_PROFILE_TYPES = {
    "mat_quartz": "plutonic_mineral",
    "mat_plagioclase_feldspar": "plutonic_mineral",
    "mat_alkali_feldspar": "plutonic_mineral",
    "mat_olivine": "mafic_bedrock",
    "mat_pyroxene": "mafic_bedrock",
    "mat_amphibole": "hydrated_alteration",
    "mat_biotite": "plutonic_mineral",
    "mat_calcite": "carbonate_basin",
    "mat_gypsum": "evaporite",
    "mat_hematite": "iron_weathering",
    "mat_magnetite": "mafic_bedrock",
    "mat_ilmenite": "heavy_mineral",
    "mat_basalt": "mafic_bedrock",
    "mat_granite": "felsic_bedrock",
    "mat_sandstone": "sand",
    "mat_silica_sand": "sand",
    "mat_clay_rich_regolith": "clay_weathering",
    "mat_impact_breccia": "impact",
    "mat_limestone": "carbonate_basin",
    "mat_dolomite": "carbonate_basin",
    "mat_shale": "fine_basin_sediment",
    "mat_siltstone": "fine_basin_sediment",
    "mat_conglomerate": "conglomerate",
    "mat_rhyolite": "felsic_volcanic",
    "mat_andesite": "intermediate_volcanic",
    "mat_gabbro": "mafic_bedrock",
    "mat_peridotite": "ultramafic_bedrock",
    "mat_serpentine": "hydrated_alteration",
    "mat_talc": "metamorphic_uplift",
    "mat_chlorite": "hydrated_alteration",
    "mat_kaolinite": "clay_weathering",
    "mat_montmorillonite": "clay_weathering",
    "mat_halite": "evaporite",
    "mat_sylvite": "evaporite",
    "mat_anhydrite": "evaporite",
    "mat_pyrite": "sulfide_ore",
    "mat_chalcopyrite": "sulfide_ore",
    "mat_sphalerite": "sulfide_ore",
    "mat_galena": "sulfide_ore",
    "mat_chromite": "heavy_mineral",
    "mat_cassiterite": "heavy_mineral",
    "mat_bauxite": "bauxite",
    "mat_laterite": "laterite",
    "mat_graphite": "metamorphic_uplift",
    "mat_diamond": "heavy_mineral",
    "mat_water_ice": "water_ice",
    "mat_carbon_dioxide_ice": "co2_ice",
    "mat_sulfur_ice": "sulfur_surface",
    "mat_obsidian": "felsic_volcanic",
    "mat_pumice": "fresh_pyroclastic",
    "mat_scoria": "fresh_pyroclastic",
    "mat_tuff": "fresh_pyroclastic",
    "mat_mudstone": "fine_basin_sediment",
    "mat_chert": "carbonate_basin",
    "mat_marl": "carbonate_basin",
    "mat_slate": "metamorphic_uplift",
    "mat_quartzite": "metamorphic_uplift",
    "mat_loess": "loess",
    "mat_alluvium": "fluvial_sediment",
    "mat_glacial_till": "glacial_sediment",
    "mat_evaporite_crust": "evaporite",
    "mat_travertine": "spring_carbonate",
    "mat_phosphorite": "carbonate_basin",
    "mat_banded_iron_formation": "fine_basin_sediment",
    "mat_goethite": "iron_weathering",
    "mat_limonite": "iron_weathering",
    "mat_garnet": "metamorphic_uplift",
    "mat_zircon": "heavy_mineral",
    "mat_apatite": "plutonic_mineral",
    "mat_fluorite": "hydrothermal",
    "mat_native_sulfur": "sulfur_surface",
    "mat_nickel_laterite": "nickel_laterite",
    "mat_saprolite": "saprolite",
    "mat_calcrete": "duricrust",
    "mat_ferricrete": "duricrust",
    "mat_zeolite": "hydrated_alteration",
    "mat_blueschist": "metamorphic_uplift",
    "mat_eclogite": "metamorphic_uplift",
}


PROFILE_MINIMUM_DETAIL_LEVEL = {
    "fresh_pyroclastic": 1,
    "plutonic_mineral": 1,
    "metamorphic_uplift": 1,
    "spring_carbonate": 2,
    "evaporite": 1,
    "hydrated_alteration": 1,
    "clay_weathering": 1,
    "saprolite": 1,
    "laterite": 1,
    "iron_weathering": 1,
    "duricrust": 1,
    "organic_wetland": 1,
    "hydrothermal": 2,
    "sulfide_ore": 2,
    "heavy_mineral": 2,
    "bauxite": 2,
    "nickel_laterite": 2,
    "sulfur_surface": 1,
}


MATERIAL_MINIMUM_DETAIL_OVERRIDES = {
    "mat_banded_iron_formation": 2,
    "mat_gabbro": 1,
    "mat_obsidian": 2,
    "mat_diamond": 3,
    "mat_zircon": 2,
    "mat_apatite": 2,
    "mat_fluorite": 2,
    "mat_phosphorite": 2,
    "mat_travertine": 2,
}


def _distribution_scale(level):
    return {
        0: "planetary_province",
        1: "macroregional_occurrence",
        2: "regional_deposit",
        3: "local_occurrence",
        4: "site_outcrop",
    }.get(int(level or 0), "local_occurrence")


MATERIAL_AFFINITY_PROFILES = {}
for _material_id, _profile_id in MATERIAL_PROFILE_TYPES.items():
    _minimum_level = max(
        PROFILE_MINIMUM_DETAIL_LEVEL.get(_profile_id, 0),
        MATERIAL_MINIMUM_DETAIL_OVERRIDES.get(_material_id, 0),
    )
    MATERIAL_AFFINITY_PROFILES[_material_id] = {
        **AFFINITY_ARCHETYPES[_profile_id],
        "profile_id": _profile_id,
        "minimum_map_detail_level": _minimum_level,
        "distribution_scale": _distribution_scale(_minimum_level),
    }


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _range_suitability(value, bounds):
    """Trapezoidal suitability for (outer_low, ideal_low, ideal_high, outer_high)."""
    if not bounds:
        return 1.0
    outer_low, ideal_low, ideal_high, outer_high = (float(item) for item in bounds)
    value = float(value)
    if value <= outer_low or value >= outer_high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 1.0
    if value < ideal_low:
        return _clamp((value - outer_low) / max(1e-9, ideal_low - outer_low))
    return _clamp((outer_high - value) / max(1e-9, outer_high - ideal_high))


def material_affinity_profile(material_id):
    return MATERIAL_AFFINITY_PROFILES.get(str(material_id or ""))


def material_affinity_score(material_id, context):
    """Return a normalized spatial suitability from an explicit profile."""
    profile = material_affinity_profile(material_id)
    if profile is None:
        return 0.0
    if profile.get("requires_active_hydrology") and not context.get(
        "active_hydrology"
    ):
        return 0.0
    if profile.get("requires_active_volcanism") and not context.get(
        "active_volcanism"
    ):
        return 0.0

    substrate = profile.get("substrate", "land")
    if substrate == "land" and context.get("ocean", 0.0) >= 0.5:
        return 0.0
    if substrate == "ocean" and context.get("ocean", 0.0) < 0.5:
        return 0.0

    temperature_fit = _range_suitability(
        context.get("temperature_k", 273.15),
        profile.get("temperature_k"),
    )
    precipitation_fit = _range_suitability(
        context.get("precipitation_mm", 0.0),
        profile.get("precipitation_mm"),
    )
    if temperature_fit <= 0.0 or precipitation_fit <= 0.0:
        return 0.0

    weathering = _clamp(context.get("weathering", 0.0))
    drainage = _clamp(context.get("drainage", 0.0))
    ice = _clamp(context.get("ice", 0.0))
    if profile.get("min_weathering") is not None and weathering < float(profile["min_weathering"]):
        return 0.0
    if profile.get("min_drainage") is not None and drainage < float(profile["min_drainage"]):
        return 0.0
    if profile.get("max_ice") is not None and ice > float(profile["max_ice"]):
        return 0.0

    weights = profile.get("weights") or {}
    weight_total = sum(max(0.0, float(weight)) for weight in weights.values())
    if weight_total <= 0.0:
        return 0.0
    spatial = sum(
        _clamp(context.get(feature, 0.0)) * max(0.0, float(weight))
        for feature, weight in weights.items()
    ) / weight_total

    climate_fit = math.sqrt(max(0.0, temperature_fit * precipitation_fit))
    score = spatial * climate_fit
    if (
        str(material_id or "") in {"mat_native_sulfur", "mat_sulfur_ice"}
        and context.get("wet_oxidizing_surface")
    ):
        # Exposed elemental sulfur is short-lived where liquid water and an
        # oxidizing surface continuously convert it to sulfate.  Fresh volcanic
        # replenishment can preserve small pockets, not planetary blankets.
        replenishment = _clamp(context.get("volcanic", 0.0)) * _clamp(
            context.get("resurfacing", 0.0)
        )
        score *= 0.03 + replenishment * 0.22
    return _clamp(score)
