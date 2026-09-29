"""Physical formation niches and spatial representations for natural materials.

Material chemistry answers whether a phase can exist.  A formation category
answers how it can form, which host/environment it needs, and how it should be
represented on a map.  The registry is intentionally data-driven: new material
cards may declare ``formation_category`` directly, while the affinity-profile
mapping keeps older catalog records compatible.
"""


FORMATION_CATEGORIES = {
    "igneous_intrusive_felsic": {
        "process": "silicic_magma_differentiation_and_intrusive_crystallization",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["felsic_crust", "silica_rich_crust"],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_intrusive_intermediate": {
        "process": "intermediate_magma_differentiation_intrusion_and_exhumation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": [
            "intermediate_silicate_crust", "plate_tectonic_surface", "felsic_crust",
        ],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_intrusive_alkaline": {
        "process": "alkali_rich_magma_intrusion_crystallization_and_exhumation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": [
            "intermediate_silicate_crust", "volcanic_surface",
            "felsic_crust", "mafic_crust",
        ],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_extrusive_mafic": {
        "process": "mafic_lava_extrusion_cooling_and_flow_emplacement",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": [
            "mafic_crust", "basaltic_surface", "volcanic_surface",
        ],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_hypabyssal_mafic": {
        "process": "shallow_mafic_dike_and_sill_intrusion_cooling_and_exhumation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": [
            "mafic_crust", "basaltic_surface", "volcanic_surface",
        ],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_mafic": {
        "process": "mafic_magma_crystallization_extrusion_or_exhumation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["mafic_crust", "basaltic_surface", "volcanic_surface"],
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_ultramafic": {
        "process": "mantle_derived_ultramafic_crystallization_and_exposure",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["mafic_crust", "ultramafic_tendency", "volcanic_surface"],
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "kimberlite_pipe": {
        "process": "volatile_rich_mantle_melt_ascent_through_explosive_diatreme_pipe",
        "spatial_representation": "bounded_deposit",
        "required_any_planet_tags": ["ultramafic_tendency", "volcanic_surface"],
        "host_formation_categories": ["igneous_ultramafic", "igneous_mafic"],
        "local_minimums": {"volcanic": 0.18},
        "valid_scale_levels": [2, 3, 4],
    },
    "igneous_extrusive_intermediate": {
        "process": "intermediate_magma_extrusion_and_cooling",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["intermediate_silicate_crust", "volcanic_surface"],
        "local_minimums": {"volcanic": 0.20},
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "igneous_extrusive_felsic": {
        "process": "silicic_magma_extrusion_and_cooling",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["felsic_crust", "silica_rich_crust"],
        "local_minimums": {"volcanic": 0.18},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "volcanic_glass": {
        "process": "rapid_quenching_of_silica_rich_lava",
        "spatial_representation": "bedrock_unit",
        "required_all_planet_tags": ["active_volcanism"],
        "required_any_planet_tags": ["felsic_crust", "silica_rich_crust"],
        "local_minimums": {"volcanic": 0.45, "resurfacing": 0.30},
        "valid_scale_levels": [2, 3, 4],
    },
    "pyroclastic_deposit": {
        "process": "explosive_eruption_fragmentation_and_deposition",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["active_volcanism"],
        "local_minimums": {"volcanic": 0.45, "resurfacing": 0.30},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "plutonic_crystalline_phase": {
        "process": "intrusive_crystallization_and_later_exhumation",
        "spatial_representation": "constituent_abundance",
        "required_any_planet_tags": ["silicate_crust", "felsic_crust", "mafic_crust"],
        "host_formation_categories": [
            "igneous_intrusive_felsic", "igneous_intrusive_intermediate",
            "igneous_intrusive_alkaline", "igneous_mafic",
            "igneous_hypabyssal_mafic", "igneous_ultramafic",
        ],
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "mafic_rock_forming_phase": {
        "process": "crystallization_within_mafic_or_ultramafic_host_rock",
        "spatial_representation": "constituent_abundance",
        "required_any_planet_tags": ["mafic_crust", "basaltic_surface", "volcanic_surface"],
        "host_formation_categories": ["igneous_mafic", "igneous_ultramafic"],
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "regional_metamorphism": {
        "process": "burial_recrystallization_deformation_and_exhumation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["plate_tectonic_surface", "silicate_crust"],
        "local_minimums": {"highland": 0.18, "erosion": 0.10},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "hydrated_alteration": {
        "process": "fluid_rock_alteration_or_low_grade_metamorphism",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["hydrated_crust", "active_hydrology"],
        "host_formation_categories": [
            "igneous_mafic", "igneous_ultramafic", "regional_metamorphism",
        ],
        "local_minimums": {"weathering": 0.05},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "hydrothermal_vein": {
        "process": "fault_intrusion_fluid_circulation_and_precipitation",
        "spatial_representation": "bounded_deposit",
        "required_any_planet_tags": ["active_volcanism", "plate_tectonic_surface"],
        "local_minimums": {"volcanic": 0.20},
        "valid_scale_levels": [2, 3, 4],
    },
    "hydrothermal_sulfide": {
        "process": "hydrothermal_or_magmatic_sulfide_concentration",
        "spatial_representation": "bounded_deposit",
        "required_any_planet_tags": ["active_volcanism", "plate_tectonic_surface"],
        "host_formation_categories": [
            "igneous_mafic", "igneous_intrusive_felsic", "igneous_extrusive_intermediate",
        ],
        "local_minimums": {"volcanic": 0.20},
        "valid_scale_levels": [2, 3, 4],
    },
    "contact_metasomatic_skarn": {
        "process": "intrusion_driven_metasomatism_of_carbonate_host",
        "spatial_representation": "bounded_deposit",
        "required_all_planet_tags": ["carbonate_favorable"],
        "required_any_planet_tags": ["active_volcanism", "plate_tectonic_surface"],
        "host_formation_categories": ["carbonate_sedimentary_basin"],
        "local_minimums": {"volcanic": 0.25, "carbonate": 0.45},
        "valid_scale_levels": [2, 3, 4],
    },
    "magmatic_carbonatite": {
        "process": "rare_carbonate_rich_magma_intrusion_or_extrusion",
        "spatial_representation": "bedrock_unit",
        "required_all_planet_tags": ["carbon_bearing_crust", "active_volcanism"],
        "local_minimums": {"volcanic": 0.40, "carbonate": 0.20},
        "valid_scale_levels": [2, 3, 4],
    },
    "late_stage_pegmatite": {
        "process": "volatile_rich_late_stage_intrusive_crystallization",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["felsic_crust", "silica_rich_crust"],
        "host_formation_categories": ["igneous_intrusive_felsic"],
        "valid_scale_levels": [2, 3, 4],
    },
    "fluvial_sediment": {
        "process": "fluvial_erosion_transport_sorting_and_deposition",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["active_hydrology"],
        "local_minimums": {"drainage": 0.10, "deposition": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "colluvial_sediment": {
        "process": "gravity_driven_rockfall_creep_and_footslope_accumulation",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": ["weathered_surface", "plate_tectonic_surface"],
        "local_minimums": {"colluvial_cover": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "littoral_sediment": {
        "process": "wave_current_and_shoreline_sorting",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["active_hydrology"],
        "local_minimums": {"shoreline": 0.42},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "aeolian_sediment": {
        "process": "wind_transport_sorting_and_dune_accumulation",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": ["aeolian_surface", "weathered_surface"],
        "local_minimums": {"aeolian": 0.30, "low_slope": 0.20},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "quartz_sand_accumulation": {
        "process": "quartz_rich_parent_weathering_abrasion_transport_sorting_and_accumulation",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": [
            "silica_rich_crust", "weathered_surface",
            "active_hydrology", "aeolian_surface",
        ],
        "local_minimums": {"low_slope": 0.08},
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "clastic_sedimentary_basin": {
        "process": "basin_deposition_burial_compaction_and_cementation",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["weathered_surface", "active_hydrology"],
        "local_minimums": {"deposition": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "carbonate_sedimentary_basin": {
        "process": "carbonate_sedimentation_precipitation_and_diagenesis",
        "spatial_representation": "bedrock_unit",
        "required_all_planet_tags": ["carbonate_favorable"],
        "local_minimums": {"carbonate": 0.45, "deposition": 0.06},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "spring_carbonate": {
        "process": "groundwater_discharge_and_carbonate_precipitation",
        "spatial_representation": "bounded_deposit",
        "required_all_planet_tags": ["active_hydrology", "carbonate_favorable"],
        "local_minimums": {"drainage": 0.16, "carbonate": 0.45},
        "valid_scale_levels": [2, 3, 4],
    },
    "evaporite_basin": {
        "process": "closed_basin_evaporation_and_brine_concentration",
        "spatial_representation": "bedrock_unit",
        "required_any_planet_tags": ["evaporite_favorable", "arid_surface"],
        "local_minimums": {"aridity": 0.45, "deposition": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "weathering_clay": {
        "process": "chemical_weathering_transport_and_fine_sediment_accumulation",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": ["weathered_surface", "hydrated_crust"],
        "local_minimums": {"weathering": 0.06},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "saprolitic_regolith": {
        "process": "deep_in_place_chemical_weathering_of_bedrock",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["weathered_surface"],
        "local_minimums": {"weathering": 0.12, "low_slope": 0.20},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "lateritic_regolith": {
        "process": "prolonged_warm_wet_leaching_and_residual_enrichment",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["weathered_surface", "active_hydrology"],
        "local_minimums": {"weathering": 0.20, "drainage": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "residual_bauxite": {
        "process": "prolonged_residual_lateritic_weathering",
        "spatial_representation": "bounded_deposit",
        "required_all_planet_tags": ["weathered_surface", "active_hydrology"],
        "host_formation_categories": [
            "igneous_intrusive_felsic", "igneous_mafic", "clastic_sedimentary_basin",
        ],
        "local_minimums": {"weathering": 0.32, "drainage": 0.16, "low_slope": 0.18},
        "valid_scale_levels": [2, 3, 4],
    },
    "nickel_laterite": {
        "process": "ultramafic_weathering_and_downprofile_nickel_enrichment",
        "spatial_representation": "bounded_deposit",
        "required_all_planet_tags": ["weathered_surface", "active_hydrology"],
        "host_formation_categories": ["igneous_ultramafic"],
        "local_minimums": {"weathering": 0.26, "drainage": 0.10},
        "valid_scale_levels": [2, 3, 4],
    },
    "placer_concentration": {
        "process": "erosional_liberation_hydraulic_sorting_and_concentration",
        "spatial_representation": "bounded_deposit",
        "required_all_planet_tags": ["active_hydrology"],
        "host_formation_categories": ["fluvial_sediment", "littoral_sediment"],
        "local_minimums": {"drainage": 0.12, "deposition": 0.10},
        "valid_scale_levels": [2, 3, 4],
    },
    "kimberlitic_diamond": {
        "process": "deep_mantle_crystallization_and_rapid_kimberlitic_transport",
        "spatial_representation": "bounded_deposit",
        "required_any_planet_tags": ["volcanic_surface", "active_volcanism"],
        "host_formation_categories": ["igneous_ultramafic"],
        "local_minimums": {"volcanic": 0.15},
        "valid_scale_levels": [3, 4],
    },
    "iron_weathering": {
        "process": "oxidative_weathering_and_residual_iron_enrichment",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": ["oxidizing_surface", "weathered_surface"],
        "local_minimums": {"weathering": 0.08},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "duricrust": {
        "process": "pedogenic_cementation_and_landscape_stability",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["weathered_surface"],
        "local_minimums": {"weathering": 0.08, "low_slope": 0.20},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "organic_wetland_sediment": {
        "process": "wetland_primary_production_burial_and_preservation",
        "spatial_representation": "surface_cover",
        "required_all_planet_tags": ["active_hydrology"],
        "local_minimums": {"humidity": 0.35, "low_slope": 0.25},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "glacial_sediment": {
        "process": "glacial_entrainment_transport_and_till_deposition",
        "spatial_representation": "surface_cover",
        "local_minimums": {"glacial": 0.50},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "impact_material": {
        "process": "impact_excavation_shock_metamorphism_and_ejecta_deposition",
        "spatial_representation": "bedrock_unit",
        "local_minimums": {"impact": 0.25},
        "valid_scale_levels": [1, 2, 3, 4],
    },
    "volatile_ice": {
        "process": "volatile_condensation_freezing_and_cold_trapping",
        "spatial_representation": "surface_cover",
        "local_minimums": {"ice": 0.35},
        "valid_scale_levels": [0, 1, 2, 3, 4],
    },
    "sulfur_surface": {
        "process": "volcanic_sulfur_emplacement_condensation_or_frost_accumulation",
        "spatial_representation": "surface_cover",
        "required_any_planet_tags": ["volcanic_surface", "active_volcanism"],
        "local_minimums": {"volcanic": 0.20},
        "valid_scale_levels": [1, 2, 3, 4],
    },
}


PROFILE_FORMATION_CATEGORIES = {
    "felsic_bedrock": "igneous_intrusive_felsic",
    "mafic_bedrock": "igneous_mafic",
    "ultramafic_bedrock": "igneous_ultramafic",
    "intermediate_volcanic": "igneous_extrusive_intermediate",
    "felsic_volcanic": "igneous_extrusive_felsic",
    "fresh_pyroclastic": "pyroclastic_deposit",
    "plutonic_mineral": "plutonic_crystalline_phase",
    "metamorphic_uplift": "regional_metamorphism",
    "hydrothermal": "hydrothermal_vein",
    "sulfide_ore": "hydrothermal_sulfide",
    "heavy_mineral": "placer_concentration",
    "fluvial_sediment": "fluvial_sediment",
    "colluvial_sediment": "colluvial_sediment",
    "fine_basin_sediment": "clastic_sedimentary_basin",
    "sand": "clastic_sedimentary_basin",
    "loess": "aeolian_sediment",
    "conglomerate": "clastic_sedimentary_basin",
    "carbonate_basin": "carbonate_sedimentary_basin",
    "spring_carbonate": "spring_carbonate",
    "evaporite": "evaporite_basin",
    "hydrated_alteration": "hydrated_alteration",
    "clay_weathering": "weathering_clay",
    "saprolite": "saprolitic_regolith",
    "laterite": "lateritic_regolith",
    "bauxite": "residual_bauxite",
    "nickel_laterite": "nickel_laterite",
    "iron_weathering": "iron_weathering",
    "duricrust": "duricrust",
    "organic_wetland": "organic_wetland_sediment",
    "glacial_sediment": "glacial_sediment",
    "impact": "impact_material",
    "water_ice": "volatile_ice",
    "co2_ice": "volatile_ice",
    "sulfur_surface": "sulfur_surface",
}


MATERIAL_FORMATION_OVERRIDES = {
    "mat_basalt": "igneous_extrusive_mafic",
    "mat_diabase": "igneous_hypabyssal_mafic",
    "mat_diorite": "igneous_intrusive_intermediate",
    "mat_monzonite": "igneous_intrusive_intermediate",
    "mat_syenite": "igneous_intrusive_alkaline",
    "mat_nepheline_syenite": "igneous_intrusive_alkaline",
    "mat_silica_sand": "quartz_sand_accumulation",
    "mat_kimberlite": "kimberlite_pipe",
    "mat_obsidian": "volcanic_glass",
    "mat_travertine": "spring_carbonate",
    "mat_skarn": "contact_metasomatic_skarn",
    "mat_carbonatite": "magmatic_carbonatite",
    "mat_pegmatite": "late_stage_pegmatite",
    "mat_beach_sand": "littoral_sediment",
    "mat_dune_sand": "aeolian_sediment",
    "mat_alluvium": "fluvial_sediment",
    "mat_colluvium": "colluvial_sediment",
    "mat_talus": "colluvial_sediment",
    "mat_glacial_till": "glacial_sediment",
    "mat_diamond": "kimberlitic_diamond",
    "mat_lapis_lazuli_marble": "contact_metasomatic_skarn",
}


def formation_category_for_material(material_id, profile_id=None, explicit=None):
    """Resolve a card declaration first, then a compatibility profile mapping."""
    category_id = str(explicit or "").strip()
    if category_id:
        return category_id if category_id in FORMATION_CATEGORIES else None
    override = MATERIAL_FORMATION_OVERRIDES.get(str(material_id or ""))
    if override:
        return override
    return PROFILE_FORMATION_CATEGORIES.get(str(profile_id or ""))


def formation_contract(
    material_id,
    material_subclass=None,
    profile_id=None,
    *,
    explicit_category=None,
    explicit_representation=None,
):
    """Return the normalized physical niche stored on material cards."""
    category_id = formation_category_for_material(
        material_id, profile_id, explicit_category
    )
    definition = dict(FORMATION_CATEGORIES.get(category_id) or {})
    representation = str(
        explicit_representation
        or definition.get("spatial_representation")
        or ""
    )
    subclass = str(material_subclass or "").lower()
    # A category describes genesis, while the material's phase determines
    # whether it is a host unit or a modal constituent of that unit.
    if subclass == "mineral" and representation not in {"bounded_deposit"}:
        representation = "constituent_abundance"
    elif subclass in {"sediment", "regolith", "ice"} and representation not in {
        "bounded_deposit"
    }:
        representation = "surface_cover"
    elif subclass == "rock" and representation == "constituent_abundance":
        representation = "bedrock_unit"
    return {
        "category_id": category_id,
        "status": "resolved" if category_id else "unresolved",
        "formation_process": definition.get("process"),
        "spatial_representation": representation or "unresolved",
        "required_all_planet_tags": list(definition.get("required_all_planet_tags") or []),
        "required_any_planet_tags": list(definition.get("required_any_planet_tags") or []),
        "host_formation_categories": list(definition.get("host_formation_categories") or []),
        "local_minimums": dict(definition.get("local_minimums") or {}),
        "valid_scale_levels": list(definition.get("valid_scale_levels") or []),
        "registry_version": "natural-material-formation-v1",
    }


def formation_suitability(contract, context, available_host_categories=()):
    """Apply hard causal prerequisites before continuous affinity scoring."""
    contract = contract if isinstance(contract, dict) else {}
    context = context if isinstance(context, dict) else {}
    tags = set(context.get("planet_tags") or [])
    required_all = set(contract.get("required_all_planet_tags") or [])
    required_any = set(contract.get("required_any_planet_tags") or [])
    if not required_all.issubset(tags):
        return 0.0
    if required_any and not required_any.intersection(tags):
        return 0.0
    for feature, minimum in (contract.get("local_minimums") or {}).items():
        try:
            if float(context.get(feature, 0.0) or 0.0) < float(minimum):
                return 0.0
        except (TypeError, ValueError):
            return 0.0
    required_hosts = set(contract.get("host_formation_categories") or [])
    available_hosts = set(available_host_categories or [])
    if required_hosts and not required_hosts.intersection(available_hosts):
        return 0.0
    return 1.0
