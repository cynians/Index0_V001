"""Physical optical defaults for naturally occurring surface materials.

``display_color`` remains a cartographic/UI property.  The profiles in this
module describe representative linear visible reflectance and the processes
that modify what an orbital camera sees.  They are deliberately compact:
formation categories supply defaults for future cards, while well-known
materials can override those defaults without changing the renderer.
"""

from __future__ import annotations

import copy
import math


MATERIAL_OPTICAL_PROFILE_VERSION = "natural-material-optics-v3"


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _linear_channel_from_srgb(channel):
    value = _clamp(float(channel or 0.0) / 255.0)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _reflectance_from_display_color(color, albedo=0.18):
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        color = [132, 126, 116]
    linear = [_linear_channel_from_srgb(color[index]) for index in range(3)]
    luminance = (
        linear[0] * 0.2126
        + linear[1] * 0.7152
        + linear[2] * 0.0722
    )
    scale = _clamp(albedo, 0.01, 0.95) / max(0.005, luminance)
    return [round(_clamp(channel * scale, 0.005, 0.95), 5) for channel in linear]


def _profile(
    reflectance,
    *,
    albedo,
    roughness=0.62,
    grain=0.28,
    wet_darkening=0.23,
    oxidation=0.0,
    hydration=0.0,
    space_weathering=0.18,
    mixing_mode="intimate",
    opacity_depth_mm=18.0,
    optical_coloring_power=1.0,
    weathered_reflectance=None,
    weathering_color_response=0.18,
    fracture_darkening=0.18,
    surface_fabric="massive",
    fabric_strength=0.0,
):
    profile = {
        "visible_reflectance": {
            "red_650nm": float(reflectance[0]),
            "green_550nm": float(reflectance[1]),
            "blue_450nm": float(reflectance[2]),
        },
        "broadband_albedo": float(albedo),
        "photometric_roughness": float(roughness),
        "grain_size_sensitivity": float(grain),
        "wet_darkening_factor": float(wet_darkening),
        "oxidation_response": float(oxidation),
        "hydration_response": float(hydration),
        "space_weathering_response": float(space_weathering),
        "mixing_mode": str(mixing_mode),
        "optical_opacity_depth_mm": float(opacity_depth_mm),
        # Relative visible colouring power at equal mapped abundance.  Fine,
        # opaque pigments and alteration coatings can dominate a rock's
        # colour at low mass fraction; clear crystals and coarse framework
        # grains usually cannot.  This is intentionally separate from the
        # material's hue and from its cartographic display colour.
        "optical_coloring_power": float(optical_coloring_power),
        # These are material properties rather than rendering presets.  They
        # let a newly-authored material describe how the same rock differs on
        # a fresh face, a weathered face, and along open fractures.
        "weathering_color_response": float(weathering_color_response),
        "fracture_darkening_factor": float(fracture_darkening),
        "surface_fabric": str(surface_fabric),
        "surface_fabric_strength": float(fabric_strength),
    }
    if weathered_reflectance is not None:
        profile["weathered_visible_reflectance"] = {
            "red_650nm": float(weathered_reflectance[0]),
            "green_550nm": float(weathered_reflectance[1]),
            "blue_450nm": float(weathered_reflectance[2]),
        }
    return profile


# Representative natural-surface endmembers. Values are not claims about a
# pure crystal under every geometry; they are stable starting points for
# exposed rock, soil, sediment, frost, and coatings in a visual simulation.
OPTICAL_FAMILIES = {
    "felsic_rock": _profile(
        [0.36, 0.31, 0.25], albedo=0.31, roughness=0.56,
        grain=0.24, wet_darkening=0.26, oxidation=0.08,
        weathered_reflectance=[0.40, 0.33, 0.25],
        weathering_color_response=0.22, fracture_darkening=0.28,
        surface_fabric="massive", fabric_strength=0.06,
    ),
    "intermediate_rock": _profile(
        [0.20, 0.19, 0.17], albedo=0.19, roughness=0.62,
        grain=0.25, wet_darkening=0.25, oxidation=0.08,
        weathered_reflectance=[0.23, 0.19, 0.15],
        weathering_color_response=0.25, fracture_darkening=0.27,
        surface_fabric="volcanic_flow", fabric_strength=0.12,
    ),
    "mafic_rock": _profile(
        [0.075, 0.080, 0.076], albedo=0.08, roughness=0.66,
        grain=0.20, wet_darkening=0.30, oxidation=0.15,
        weathered_reflectance=[0.13, 0.075, 0.045],
        weathering_color_response=0.42, fracture_darkening=0.23,
        surface_fabric="volcanic_flow", fabric_strength=0.16,
    ),
    "ultramafic_rock": _profile(
        [0.13, 0.15, 0.095], albedo=0.13, roughness=0.68,
        grain=0.25, wet_darkening=0.28, oxidation=0.26,
        weathered_reflectance=[0.18, 0.12, 0.055],
        weathering_color_response=0.46, fracture_darkening=0.22,
    ),
    "volcanic_glass": _profile(
        [0.035, 0.038, 0.040], albedo=0.038, roughness=0.32,
        grain=0.12, wet_darkening=0.18, oxidation=0.08,
        mixing_mode="areal",
    ),
    "pyroclastic": _profile(
        [0.22, 0.19, 0.15], albedo=0.19, roughness=0.84,
        grain=0.58, wet_darkening=0.28, oxidation=0.12,
        opacity_depth_mm=8.0,
        weathered_reflectance=[0.29, 0.22, 0.15],
        weathering_color_response=0.32, fracture_darkening=0.12,
        surface_fabric="fragmental", fabric_strength=0.18,
    ),
    "metamorphic_rock": _profile(
        [0.18, 0.18, 0.17], albedo=0.18, roughness=0.58,
        grain=0.22, wet_darkening=0.27,
        weathered_reflectance=[0.22, 0.20, 0.17],
        weathering_color_response=0.24, fracture_darkening=0.30,
        surface_fabric="foliated", fabric_strength=0.58,
    ),
    "hydrated_rock": _profile(
        [0.13, 0.16, 0.135], albedo=0.15, roughness=0.68,
        grain=0.30, wet_darkening=0.24, hydration=0.42,
        weathered_reflectance=[0.18, 0.21, 0.15],
        weathering_color_response=0.38, fracture_darkening=0.20,
        surface_fabric="foliated", fabric_strength=0.25,
        optical_coloring_power=1.18,
    ),
    "siliciclastic": _profile(
        [0.32, 0.25, 0.17], albedo=0.25, roughness=0.78,
        grain=0.46, wet_darkening=0.34, oxidation=0.10,
        opacity_depth_mm=10.0,
        weathered_reflectance=[0.38, 0.29, 0.18],
        weathering_color_response=0.30, fracture_darkening=0.25,
        surface_fabric="bedded", fabric_strength=0.48,
    ),
    "fine_sediment": _profile(
        [0.22, 0.19, 0.15], albedo=0.19, roughness=0.82,
        grain=0.55, wet_darkening=0.39, hydration=0.18,
        opacity_depth_mm=6.0,
        weathered_reflectance=[0.25, 0.20, 0.14],
        weathering_color_response=0.38, fracture_darkening=0.34,
        surface_fabric="bedded", fabric_strength=0.56,
    ),
    "carbonate": _profile(
        [0.52, 0.49, 0.40], albedo=0.47, roughness=0.60,
        grain=0.35, wet_darkening=0.24,
        weathered_reflectance=[0.58, 0.52, 0.40],
        weathering_color_response=0.20, fracture_darkening=0.34,
        surface_fabric="bedded", fabric_strength=0.64,
    ),
    "evaporite": _profile(
        [0.68, 0.65, 0.54], albedo=0.63, roughness=0.52,
        grain=0.44, wet_darkening=0.19,
        mixing_mode="coating", opacity_depth_mm=3.0,
        weathered_reflectance=[0.75, 0.70, 0.59],
        weathering_color_response=0.16, fracture_darkening=0.08,
        surface_fabric="bedded", fabric_strength=0.42,
        optical_coloring_power=1.35,
    ),
    "weathered_clay": _profile(
        [0.25, 0.20, 0.13], albedo=0.20, roughness=0.88,
        grain=0.62, wet_darkening=0.42, oxidation=0.24,
        hydration=0.38, mixing_mode="coating", opacity_depth_mm=4.0,
        optical_coloring_power=1.55,
    ),
    "lateritic": _profile(
        [0.35, 0.105, 0.055], albedo=0.17, roughness=0.86,
        grain=0.58, wet_darkening=0.32, oxidation=0.88,
        mixing_mode="coating", opacity_depth_mm=4.0,
        optical_coloring_power=2.35,
    ),
    "ferric": _profile(
        [0.32, 0.075, 0.040], albedo=0.14, roughness=0.80,
        grain=0.52, wet_darkening=0.28, oxidation=1.0,
        mixing_mode="coating", opacity_depth_mm=2.0,
        optical_coloring_power=3.20,
    ),
    "sulfide_ore": _profile(
        [0.08, 0.075, 0.060], albedo=0.075, roughness=0.48,
        grain=0.18, wet_darkening=0.12, oxidation=0.45,
        mixing_mode="areal",
    ),
    "crystalline_mineral": _profile(
        [0.24, 0.24, 0.22], albedo=0.235, roughness=0.42,
        grain=0.36, wet_darkening=0.20, mixing_mode="intimate",
        optical_coloring_power=0.62,
    ),
    "impact_regolith": _profile(
        [0.15, 0.145, 0.135], albedo=0.145, roughness=0.90,
        grain=0.66, wet_darkening=0.20, space_weathering=0.62,
        opacity_depth_mm=7.0,
    ),
    "glacial_sediment": _profile(
        [0.32, 0.32, 0.30], albedo=0.315, roughness=0.82,
        grain=0.52, wet_darkening=0.31, opacity_depth_mm=8.0,
    ),
    "carbonaceous": _profile(
        [0.025, 0.027, 0.025], albedo=0.026, roughness=0.72,
        grain=0.34, wet_darkening=0.08, space_weathering=0.24,
    ),
    "water_ice": _profile(
        [0.78, 0.86, 0.92], albedo=0.85, roughness=0.48,
        grain=0.78, wet_darkening=0.04, space_weathering=0.06,
        mixing_mode="translucent", opacity_depth_mm=12.0,
    ),
    "carbon_dioxide_ice": _profile(
        [0.82, 0.86, 0.88], albedo=0.85, roughness=0.42,
        grain=0.70, wet_darkening=0.02, space_weathering=0.04,
        mixing_mode="translucent", opacity_depth_mm=8.0,
    ),
    "sulfur": _profile(
        [0.72, 0.53, 0.055], albedo=0.52, roughness=0.70,
        grain=0.48, wet_darkening=0.12, oxidation=0.10,
        mixing_mode="coating", opacity_depth_mm=3.0,
        optical_coloring_power=2.30,
    ),
}


FORMATION_OPTICAL_FAMILIES = {
    "igneous_intrusive_felsic": "felsic_rock",
    "igneous_mafic": "mafic_rock",
    "igneous_ultramafic": "ultramafic_rock",
    "kimberlite_pipe": "ultramafic_rock",
    "igneous_extrusive_intermediate": "intermediate_rock",
    "igneous_extrusive_felsic": "felsic_rock",
    "volcanic_glass": "volcanic_glass",
    "pyroclastic_deposit": "pyroclastic",
    "plutonic_crystalline_phase": "crystalline_mineral",
    "mafic_rock_forming_phase": "mafic_rock",
    "regional_metamorphism": "metamorphic_rock",
    "hydrated_alteration": "hydrated_rock",
    "hydrothermal_vein": "crystalline_mineral",
    "hydrothermal_sulfide": "sulfide_ore",
    "contact_metasomatic_skarn": "metamorphic_rock",
    "magmatic_carbonatite": "carbonate",
    "late_stage_pegmatite": "felsic_rock",
    "fluvial_sediment": "siliciclastic",
    "colluvial_sediment": "siliciclastic",
    "littoral_sediment": "siliciclastic",
    "aeolian_sediment": "siliciclastic",
    "clastic_sedimentary_basin": "siliciclastic",
    "carbonate_sedimentary_basin": "carbonate",
    "spring_carbonate": "carbonate",
    "evaporite_basin": "evaporite",
    "weathering_clay": "weathered_clay",
    "saprolitic_regolith": "weathered_clay",
    "lateritic_regolith": "lateritic",
    "residual_bauxite": "lateritic",
    "nickel_laterite": "lateritic",
    "placer_concentration": "crystalline_mineral",
    "kimberlitic_diamond": "ultramafic_rock",
    "iron_weathering": "ferric",
    "duricrust": "weathered_clay",
    "organic_wetland_sediment": "carbonaceous",
    "glacial_sediment": "glacial_sediment",
    "impact_material": "impact_regolith",
    "volatile_ice": "water_ice",
    "sulfur_surface": "sulfur",
}


MATERIAL_OPTICAL_OVERRIDES = {
    # Sierra Nevada calibration: fresh granitoid is pale neutral to subtly
    # pink, with dark joint faces and only weak internal fabric.
    "mat_granite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.43, "green_550nm": 0.385, "blue_450nm": 0.33,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.47, "green_550nm": 0.39, "blue_450nm": 0.29,
        },
        "broadband_albedo": 0.39,
        "surface_fabric": "massive",
        "surface_fabric_strength": 0.04,
        "fracture_darkening_factor": 0.34,
    },
    "mat_basalt": {"family_id": "mafic_rock"},
    "mat_gabbro": {"family_id": "mafic_rock"},
    "mat_diabase": {"family_id": "mafic_rock"},
    "mat_komatiite": {
        "family_id": "ultramafic_rock",
        "visible_reflectance": {
            "red_650nm": 0.085, "green_550nm": 0.095, "blue_450nm": 0.077,
        },
        "broadband_albedo": 0.092,
    },
    "mat_peridotite": {
        "family_id": "ultramafic_rock",
        "visible_reflectance": {
            "red_650nm": 0.13, "green_550nm": 0.15, "blue_450nm": 0.088,
        },
        "broadband_albedo": 0.135,
    },
    "mat_dunite": {
        "family_id": "ultramafic_rock",
        "visible_reflectance": {
            "red_650nm": 0.17, "green_550nm": 0.20, "blue_450nm": 0.095,
        },
        "broadband_albedo": 0.178,
    },
    # Mg-rich olivine can give fresh ultramafic exposures an olive cast;
    # Fe-rich fayalite and most pyroxenes remain much darker and browner.
    # These are intimate rock-forming phases, not green paint, so their
    # colouring power remains deliberately moderate.
    "mat_olivine": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.17, "green_550nm": 0.215, "blue_450nm": 0.095,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.20, "green_550nm": 0.145, "blue_450nm": 0.07,
        },
        "broadband_albedo": 0.196,
        "optical_coloring_power": 0.95,
        "weathering_color_response": 0.48,
    },
    "mat_forsterite": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.20, "green_550nm": 0.255, "blue_450nm": 0.12,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.22, "green_550nm": 0.16, "blue_450nm": 0.075,
        },
        "broadband_albedo": 0.232,
        "optical_coloring_power": 1.05,
        "weathering_color_response": 0.50,
    },
    "mat_fayalite": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.085, "green_550nm": 0.070, "blue_450nm": 0.042,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.20, "green_550nm": 0.085, "blue_450nm": 0.035,
        },
        "broadband_albedo": 0.071,
        "optical_coloring_power": 0.82,
        "weathering_color_response": 0.58,
    },
    "mat_enstatite": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.13, "green_550nm": 0.145, "blue_450nm": 0.095,
        },
        "broadband_albedo": 0.137,
        "optical_coloring_power": 0.72,
    },
    "mat_augite": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.055, "green_550nm": 0.068, "blue_450nm": 0.052,
        },
        "broadband_albedo": 0.064,
        "optical_coloring_power": 0.72,
    },
    "mat_pyroxene": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.075, "green_550nm": 0.082, "blue_450nm": 0.065,
        },
        "broadband_albedo": 0.079,
        "optical_coloring_power": 0.68,
    },
    "mat_kimberlite": {
        "family_id": "ultramafic_rock",
        "visible_reflectance": {
            "red_650nm": 0.095, "green_550nm": 0.105, "blue_450nm": 0.092,
        },
        "broadband_albedo": 0.102,
    },
    "mat_syenite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.36, "green_550nm": 0.31, "blue_450nm": 0.255,
        },
        "broadband_albedo": 0.315,
    },
    "mat_nepheline_syenite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.29, "green_550nm": 0.255, "blue_450nm": 0.22,
        },
        "broadband_albedo": 0.258,
    },
    "mat_monzonite": {
        "family_id": "intermediate_rock",
        "visible_reflectance": {
            "red_650nm": 0.235, "green_550nm": 0.22, "blue_450nm": 0.19,
        },
        "broadband_albedo": 0.218,
    },
    "mat_tonalite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.42, "green_550nm": 0.40, "blue_450nm": 0.365,
        },
        "broadband_albedo": 0.399,
    },
    "mat_granodiorite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.39, "green_550nm": 0.355, "blue_450nm": 0.305,
        },
        "broadband_albedo": 0.355,
    },
    "mat_anorthosite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.52, "green_550nm": 0.50, "blue_450nm": 0.47,
        },
        "broadband_albedo": 0.50,
    },
    "mat_obsidian": {"family_id": "volcanic_glass"},
    # Andes calibration: intermediate and silicic volcanic rocks remain
    # neutral on fresh faces but develop warmer ferric weathering skins.
    "mat_andesite": {
        "family_id": "intermediate_rock",
        "visible_reflectance": {
            "red_650nm": 0.19, "green_550nm": 0.185, "blue_450nm": 0.17,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.285, "green_550nm": 0.19, "blue_450nm": 0.115,
        },
        "broadband_albedo": 0.185,
        "weathering_color_response": 0.48,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.18,
    },
    # Alkaline/intermediate volcanic provinces should not collapse to the
    # same neutral swatch. Mineralogy produces subtle but orbitally useful
    # distinctions: feldspar-rich trachyte is pale and warm, phonolite often
    # carries a green-grey cast, and latite is a darker brown-grey unit.
    "mat_trachyte": {
        "family_id": "intermediate_rock",
        "visible_reflectance": {
            "red_650nm": 0.34, "green_550nm": 0.285, "blue_450nm": 0.225,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.43, "green_550nm": 0.30, "blue_450nm": 0.19,
        },
        "broadband_albedo": 0.292,
        "weathering_color_response": 0.36,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.14,
    },
    "mat_phonolite": {
        "family_id": "intermediate_rock",
        "visible_reflectance": {
            "red_650nm": 0.205, "green_550nm": 0.245, "blue_450nm": 0.205,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.29, "green_550nm": 0.285, "blue_450nm": 0.18,
        },
        "broadband_albedo": 0.226,
        "weathering_color_response": 0.32,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.15,
    },
    "mat_latite": {
        "family_id": "intermediate_rock",
        "visible_reflectance": {
            "red_650nm": 0.255, "green_550nm": 0.215, "blue_450nm": 0.165,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.36, "green_550nm": 0.235, "blue_450nm": 0.13,
        },
        "broadband_albedo": 0.222,
        "weathering_color_response": 0.43,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.16,
    },
    "mat_dacite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.31, "green_550nm": 0.29, "blue_450nm": 0.265,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.39, "green_550nm": 0.29, "blue_450nm": 0.21,
        },
        "broadband_albedo": 0.292,
        "weathering_color_response": 0.38,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.16,
    },
    "mat_rhyolite": {
        "family_id": "felsic_rock",
        "visible_reflectance": {
            "red_650nm": 0.39, "green_550nm": 0.34, "blue_450nm": 0.30,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.47, "green_550nm": 0.35, "blue_450nm": 0.25,
        },
        "broadband_albedo": 0.35,
        "weathering_color_response": 0.34,
        "surface_fabric": "volcanic_flow",
        "surface_fabric_strength": 0.14,
    },
    "mat_tuff": {
        "family_id": "pyroclastic",
        "visible_reflectance": {
            "red_650nm": 0.31, "green_550nm": 0.25, "blue_450nm": 0.19,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.40, "green_550nm": 0.27, "blue_450nm": 0.17,
        },
        "broadband_albedo": 0.265,
    },
    "mat_pumice": {
        "family_id": "pyroclastic",
        "visible_reflectance": {
            "red_650nm": 0.47, "green_550nm": 0.44, "blue_450nm": 0.39,
        },
        "broadband_albedo": 0.44,
    },
    # Ferric phases are texture dependent.  Fine weathering products are
    # strong red/ochre pigments; coarse crystalline hematite can be gray.
    # The surface layer represents the fine weathered expression while the
    # bounded abundance and coating mode control where it is actually seen.
    "mat_hematite": {"family_id": "ferric"},
    "mat_goethite": {
        "family_id": "ferric",
        "visible_reflectance": {
            "red_650nm": 0.34, "green_550nm": 0.17, "blue_450nm": 0.055,
        },
        "broadband_albedo": 0.20,
        "optical_coloring_power": 2.75,
    },
    "mat_magnetite": {
        "family_id": "sulfide_ore",
        "visible_reflectance": {
            "red_650nm": 0.035, "green_550nm": 0.034, "blue_450nm": 0.033,
        },
        "broadband_albedo": 0.034,
    },
    "mat_graphite": {"family_id": "carbonaceous"},
    "mat_anthracite": {"family_id": "carbonaceous"},
    "mat_lignite": {"family_id": "carbonaceous"},
    "mat_oil_shale": {"family_id": "carbonaceous"},
    "mat_water_ice": {"family_id": "water_ice"},
    "mat_carbon_dioxide_ice": {"family_id": "carbon_dioxide_ice"},
    "mat_sulfur_ice": {"family_id": "sulfur"},
    "mat_native_sulfur": {"family_id": "sulfur"},
    "mat_halite": {"family_id": "evaporite"},
    "mat_sylvite": {"family_id": "evaporite"},
    "mat_gypsum": {"family_id": "evaporite"},
    "mat_anhydrite": {"family_id": "evaporite"},
    "mat_rock_salt": {"family_id": "evaporite"},
    "mat_evaporite_crust": {"family_id": "evaporite"},
    "mat_kaolinite": {
        "family_id": "weathered_clay",
        "visible_reflectance": {
            "red_650nm": 0.66, "green_550nm": 0.62, "blue_450nm": 0.53,
        },
        "broadband_albedo": 0.62,
        "optical_coloring_power": 1.45,
    },
    "mat_montmorillonite": {
        "family_id": "weathered_clay",
        "visible_reflectance": {
            "red_650nm": 0.36, "green_550nm": 0.31, "blue_450nm": 0.23,
        },
        "broadband_albedo": 0.32,
        "optical_coloring_power": 1.30,
    },
    # Hydration and low-grade alteration are the principal route to broad
    # natural green rock units.  They remain tied to hydrated-alteration
    # distributions rather than being applied by climate or latitude alone.
    "mat_serpentine": {
        "family_id": "hydrated_rock",
        "visible_reflectance": {
            "red_650nm": 0.115, "green_550nm": 0.205, "blue_450nm": 0.105,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.17, "green_550nm": 0.225, "blue_450nm": 0.12,
        },
        "broadband_albedo": 0.175,
        "optical_coloring_power": 1.42,
        "mixing_mode": "areal",
    },
    "mat_chlorite": {
        "family_id": "hydrated_rock",
        "visible_reflectance": {
            "red_650nm": 0.070, "green_550nm": 0.145, "blue_450nm": 0.075,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.10, "green_550nm": 0.16, "blue_450nm": 0.085,
        },
        "broadband_albedo": 0.118,
        "optical_coloring_power": 1.28,
    },
    "mat_calcite": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.69, "green_550nm": 0.68, "blue_450nm": 0.62,
        },
        "broadband_albedo": 0.675,
        "optical_coloring_power": 0.78,
    },
    "mat_travertine": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.66, "green_550nm": 0.59, "blue_450nm": 0.43,
        },
        "broadband_albedo": 0.59,
        "mixing_mode": "areal",
        "optical_coloring_power": 1.18,
    },
    "mat_quartz": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.62, "green_550nm": 0.61, "blue_450nm": 0.58,
        },
        "broadband_albedo": 0.61,
        "mixing_mode": "translucent",
        "optical_coloring_power": 0.42,
    },
    "mat_plagioclase_feldspar": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.46, "green_550nm": 0.455, "blue_450nm": 0.42,
        },
        "broadband_albedo": 0.454,
        "optical_coloring_power": 0.52,
    },
    "mat_alkali_feldspar": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.53, "green_550nm": 0.405, "blue_450nm": 0.365,
        },
        "broadband_albedo": 0.44,
        "optical_coloring_power": 0.62,
    },
    "mat_chalk": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.72, "green_550nm": 0.71, "blue_450nm": 0.66,
        },
        "broadband_albedo": 0.70,
    },
    # Zagros calibration: resistant pale carbonate beds alternate with much
    # darker, more easily weathered mudrocks. The map can therefore express
    # real lithologic ridges and valleys without a named mountain preset.
    "mat_limestone": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.56, "green_550nm": 0.535, "blue_450nm": 0.455,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.62, "green_550nm": 0.55, "blue_450nm": 0.42,
        },
        "broadband_albedo": 0.535,
        "surface_fabric": "bedded",
        "surface_fabric_strength": 0.72,
        "fracture_darkening_factor": 0.38,
    },
    "mat_dolomite": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.48, "green_550nm": 0.45, "blue_450nm": 0.37,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.55, "green_550nm": 0.48, "blue_450nm": 0.36,
        },
        "broadband_albedo": 0.452,
        "surface_fabric": "bedded",
        "surface_fabric_strength": 0.68,
    },
    "mat_shale": {
        "family_id": "fine_sediment",
        "visible_reflectance": {
            "red_650nm": 0.115, "green_550nm": 0.105, "blue_450nm": 0.09,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.18, "green_550nm": 0.145, "blue_450nm": 0.105,
        },
        "broadband_albedo": 0.106,
        "surface_fabric": "bedded",
        "surface_fabric_strength": 0.74,
        "fracture_darkening_factor": 0.40,
    },
    "mat_mudstone": {
        "family_id": "fine_sediment",
        "visible_reflectance": {
            "red_650nm": 0.15, "green_550nm": 0.13, "blue_450nm": 0.105,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.22, "green_550nm": 0.17, "blue_450nm": 0.115,
        },
        "broadband_albedo": 0.134,
        "surface_fabric": "bedded",
        "surface_fabric_strength": 0.34,
    },
    "mat_sandstone": {
        "family_id": "siliciclastic",
        "visible_reflectance": {
            "red_650nm": 0.41, "green_550nm": 0.30, "blue_450nm": 0.19,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.49, "green_550nm": 0.34, "blue_450nm": 0.19,
        },
        "broadband_albedo": 0.315,
        "surface_fabric": "bedded",
        "surface_fabric_strength": 0.58,
    },
    # Himalayan collision-belt calibration: actual metamorphic lithologies
    # carry foliation; quartzite and marble remain brighter resistant units.
    "mat_gneiss": {
        "family_id": "metamorphic_rock",
        "visible_reflectance": {
            "red_650nm": 0.245, "green_550nm": 0.235, "blue_450nm": 0.215,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.30, "green_550nm": 0.265, "blue_450nm": 0.22,
        },
        "broadband_albedo": 0.235,
        "surface_fabric": "foliated",
        "surface_fabric_strength": 0.82,
        "fracture_darkening_factor": 0.34,
    },
    "mat_schist": {
        "family_id": "metamorphic_rock",
        "visible_reflectance": {
            "red_650nm": 0.16, "green_550nm": 0.155, "blue_450nm": 0.14,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.22, "green_550nm": 0.19, "blue_450nm": 0.15,
        },
        "broadband_albedo": 0.155,
        "surface_fabric": "foliated",
        "surface_fabric_strength": 0.76,
    },
    "mat_slate": {
        "family_id": "metamorphic_rock",
        "visible_reflectance": {
            "red_650nm": 0.085, "green_550nm": 0.095, "blue_450nm": 0.105,
        },
        "broadband_albedo": 0.094,
        "surface_fabric": "foliated",
        "surface_fabric_strength": 0.66,
    },
    "mat_quartzite": {
        "family_id": "metamorphic_rock",
        "visible_reflectance": {
            "red_650nm": 0.49, "green_550nm": 0.47, "blue_450nm": 0.43,
        },
        "weathered_visible_reflectance": {
            "red_650nm": 0.54, "green_550nm": 0.50, "blue_450nm": 0.43,
        },
        "broadband_albedo": 0.473,
        "surface_fabric": "massive",
        "surface_fabric_strength": 0.10,
    },
    "mat_marble": {
        "family_id": "carbonate",
        "visible_reflectance": {
            "red_650nm": 0.67, "green_550nm": 0.655, "blue_450nm": 0.61,
        },
        "broadband_albedo": 0.654,
        "surface_fabric": "foliated",
        "surface_fabric_strength": 0.24,
    },
    "mat_diatomite": {
        "family_id": "siliciclastic",
        "visible_reflectance": {
            "red_650nm": 0.64, "green_550nm": 0.62, "blue_450nm": 0.56,
        },
        "broadband_albedo": 0.61,
    },
    "mat_bauxite": {"family_id": "lateritic"},
    "mat_laterite": {"family_id": "lateritic"},
    "mat_nickel_laterite": {"family_id": "lateritic"},
    "mat_limonite": {
        "family_id": "ferric",
        "visible_reflectance": {
            "red_650nm": 0.38, "green_550nm": 0.205, "blue_450nm": 0.065,
        },
        "broadband_albedo": 0.235,
        "optical_coloring_power": 2.65,
    },
    "mat_ferricrete": {"family_id": "ferric"},
    # Spectacular hydrothermal colours are real but spatially restricted.
    # They are therefore strong optical endmembers with areal/bounded mixing,
    # never a planet-wide tint.
    "mat_cinnabar": {
        "family_id": "sulfide_ore",
        "visible_reflectance": {
            "red_650nm": 0.47, "green_550nm": 0.035, "blue_450nm": 0.025,
        },
        "broadband_albedo": 0.13,
        "mixing_mode": "areal",
        "optical_coloring_power": 1.75,
    },
    "mat_realgar": {
        "family_id": "sulfide_ore",
        "visible_reflectance": {
            "red_650nm": 0.60, "green_550nm": 0.115, "blue_450nm": 0.025,
        },
        "broadband_albedo": 0.21,
        "mixing_mode": "areal",
        "optical_coloring_power": 1.70,
    },
    "mat_orpiment": {
        "family_id": "sulfide_ore",
        "visible_reflectance": {
            "red_650nm": 0.68, "green_550nm": 0.47, "blue_450nm": 0.045,
        },
        "broadband_albedo": 0.49,
        "mixing_mode": "areal",
        "optical_coloring_power": 1.65,
    },
    "mat_fluorite": {
        "family_id": "crystalline_mineral",
        "visible_reflectance": {
            "red_650nm": 0.25, "green_550nm": 0.17, "blue_450nm": 0.34,
        },
        "broadband_albedo": 0.205,
        "mixing_mode": "translucent",
        "optical_coloring_power": 0.48,
    },
    "mat_impact_breccia": {"family_id": "impact_regolith"},
    "mat_glacial_till": {"family_id": "glacial_sediment"},
    "mat_dune_sand": {
        "family_id": "siliciclastic",
        "visible_reflectance": {
            "red_650nm": 0.43, "green_550nm": 0.32, "blue_450nm": 0.19,
        },
        "broadband_albedo": 0.33,
    },
    "mat_beach_sand": {
        "family_id": "siliciclastic",
        "visible_reflectance": {
            "red_650nm": 0.48, "green_550nm": 0.42, "blue_450nm": 0.32,
        },
        "broadband_albedo": 0.42,
    },
    "mat_silica_sand": {
        "family_id": "siliciclastic",
        "visible_reflectance": {
            "red_650nm": 0.60, "green_550nm": 0.57, "blue_450nm": 0.50,
        },
        "broadband_albedo": 0.57,
    },
}


def optical_family_for_material(
    material_id,
    formation_category=None,
    material_subclass=None,
):
    override = MATERIAL_OPTICAL_OVERRIDES.get(str(material_id or "")) or {}
    if override.get("family_id") in OPTICAL_FAMILIES:
        return override["family_id"]
    family_id = FORMATION_OPTICAL_FAMILIES.get(str(formation_category or ""))
    if family_id:
        return family_id
    subclass = str(material_subclass or "").lower()
    return {
        "rock": "intermediate_rock",
        "sediment": "fine_sediment",
        "regolith": "impact_regolith",
        "ice": "water_ice",
        "mineral": "crystalline_mineral",
    }.get(subclass, "crystalline_mineral")


def material_optical_surface_profile(
    material_id,
    *,
    formation_category=None,
    material_subclass=None,
    display_color=None,
    explicit=None,
):
    """Resolve a normalized optical profile for a natural material card."""
    family_id = optical_family_for_material(
        material_id,
        formation_category,
        material_subclass,
    )
    profile = copy.deepcopy(OPTICAL_FAMILIES[family_id])
    override = MATERIAL_OPTICAL_OVERRIDES.get(str(material_id or "")) or {}
    for key, value in override.items():
        if key != "family_id":
            profile[key] = copy.deepcopy(value)
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            if key not in {"profile_version", "material_id"}:
                profile[key] = copy.deepcopy(value)

    reflectance = profile.get("visible_reflectance")
    if not isinstance(reflectance, dict):
        values = _reflectance_from_display_color(
            display_color,
            profile.get("broadband_albedo", 0.18),
        )
        reflectance = {
            "red_650nm": values[0],
            "green_550nm": values[1],
            "blue_450nm": values[2],
        }
    for key in ("red_650nm", "green_550nm", "blue_450nm"):
        reflectance[key] = round(_clamp(reflectance.get(key), 0.002, 0.98), 5)
    weathered_reflectance = profile.get("weathered_visible_reflectance")
    if not isinstance(weathered_reflectance, dict):
        weathered_reflectance = dict(reflectance)
    for key in ("red_650nm", "green_550nm", "blue_450nm"):
        weathered_reflectance[key] = round(
            _clamp(weathered_reflectance.get(key), 0.002, 0.98),
            5,
        )
    surface_fabric = str(profile.get("surface_fabric") or "massive")
    if surface_fabric not in {
        "massive", "bedded", "foliated", "volcanic_flow", "fragmental",
    }:
        surface_fabric = "massive"
    mixing_mode = str(profile.get("mixing_mode") or "intimate")
    if mixing_mode not in {"intimate", "areal", "coating", "translucent"}:
        mixing_mode = "intimate"

    profile.update({
        "profile_version": MATERIAL_OPTICAL_PROFILE_VERSION,
        "material_id": str(material_id or ""),
        "family_id": family_id,
        "visible_reflectance": reflectance,
        "weathered_visible_reflectance": weathered_reflectance,
        "broadband_albedo": round(
            _clamp(profile.get("broadband_albedo"), 0.002, 0.98),
            5,
        ),
        "photometric_roughness": round(
            _clamp(profile.get("photometric_roughness", 0.6)),
            5,
        ),
        "grain_size_sensitivity": round(
            _clamp(profile.get("grain_size_sensitivity", 0.3)),
            5,
        ),
        "wet_darkening_factor": round(
            _clamp(profile.get("wet_darkening_factor", 0.2)),
            5,
        ),
        "oxidation_response": round(
            _clamp(profile.get("oxidation_response", 0.0)),
            5,
        ),
        "hydration_response": round(
            _clamp(profile.get("hydration_response", 0.0)),
            5,
        ),
        "space_weathering_response": round(
            _clamp(profile.get("space_weathering_response", 0.15)),
            5,
        ),
        "weathering_color_response": round(
            _clamp(profile.get("weathering_color_response", 0.18)),
            5,
        ),
        "fracture_darkening_factor": round(
            _clamp(profile.get("fracture_darkening_factor", 0.18)),
            5,
        ),
        "surface_fabric": surface_fabric,
        "mixing_mode": mixing_mode,
        "surface_fabric_strength": round(
            _clamp(profile.get("surface_fabric_strength", 0.0)),
            5,
        ),
        "optical_coloring_power": round(
            _clamp(profile.get("optical_coloring_power", 1.0), 0.1, 6.0),
            5,
        ),
        "optical_opacity_depth_mm": round(
            max(0.05, float(profile.get("optical_opacity_depth_mm", 12.0) or 12.0)),
            4,
        ),
        "source_kind": (
            "material_override"
            if str(material_id or "") in MATERIAL_OPTICAL_OVERRIDES
            else "formation_category_default"
            if formation_category in FORMATION_OPTICAL_FAMILIES
            else "material_subclass_default"
        ),
        "calibration_state": "representative_visible_endmember",
    })
    return profile


def reflectance_triplet(profile, fallback=(0.18, 0.17, 0.15)):
    profile = profile if isinstance(profile, dict) else {}
    values = profile.get("visible_reflectance")
    if not isinstance(values, dict):
        return list(fallback)
    return [
        _clamp(values.get("red_650nm"), 0.002, 0.98),
        _clamp(values.get("green_550nm"), 0.002, 0.98),
        _clamp(values.get("blue_450nm"), 0.002, 0.98),
    ]


def linear_reflectance_to_srgb(reflectance):
    result = []
    for channel in reflectance:
        value = _clamp(channel)
        encoded = (
            12.92 * value
            if value <= 0.0031308
            else 1.055 * math.pow(value, 1.0 / 2.4) - 0.055
        )
        result.append(max(0, min(255, int(round(encoded * 255.0)))))
    return result
