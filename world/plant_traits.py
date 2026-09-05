"""Practical functional-trait schema for plant species.

The schema intentionally sits above laboratory trait databases.  It keeps
traits that are useful to Species Sim, commonly documented, or often
recognisable from field references and photographs.  Most categorical values
remain open strings until botanical terminology has had a dedicated review.
"""

PLANT_TRAIT_SECTION = "Simulation / Plant Ecology"

PLANT_TRAIT_SCHEMA_FIELDS = {
    "plant_growth_form": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_growth_behaviour": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_lifespan": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_life_form": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_woodiness": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "mature_height": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
    "mature_height_class": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "growth_rate": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "maturity_rate": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "longevity_class": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_phenology": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_size_class": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_structure": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_arrangement": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_attachment_pattern": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "leaf_clustering": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    # These fields separate the architectural strategy from its continuous
    # expression.  Normalised values are intentionally 0..1 so a species can
    # sit anywhere between two named extremes without inventing new labels.
    "plant_shoot_dimorphism": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_leaf_distribution": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_leaf_spacing_bias": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_branch_droop": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_branch_angle_gradient": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_crown_openness": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_leaf_depth_gradient": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_fine_twig_density": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "plant_leaf_cluster_density": {"type": "number", "section": PLANT_TRAIT_SECTION, "optional": True, "min": 0.0, "max": 1.0},
    "photosynthesis_pathway": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "succulence": {"type": "string_list", "section": PLANT_TRAIT_SECTION, "optional": True},
    "root_architecture": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "root_depth_class": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "belowground_storage": {"type": "string_list", "section": PLANT_TRAIT_SECTION, "optional": True},
    "max_root_depth": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
    "reproductive_mode": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "pollination": {"type": "string_list", "section": PLANT_TRAIT_SECTION, "optional": True},
    "dispersal": {"type": "string_list", "section": PLANT_TRAIT_SECTION, "optional": True},
    "seed_size_class": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "clonal_spread": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "resprouting": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "regeneration_strategy": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "nitrogen_fixation": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "nutrition_mode": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "mycorrhizal_type": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "shade_tolerance": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "moisture_preference": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "waterlogging_tolerance": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "temperature_range": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
    "frost_tolerance": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
    "soil_ph_range": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
    "salinity_tolerance": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_leaf_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_root_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_stem_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_branch_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_flower_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_fruit_module_ref": {"type": "string", "section": PLANT_TRAIT_SECTION, "optional": True},
    "plant_module_anchors": {"type": "dict", "section": PLANT_TRAIT_SECTION, "optional": True},
}

PLANT_TRAIT_FIELDS = frozenset(PLANT_TRAIT_SCHEMA_FIELDS)

PLANT_DERIVED_FIELDS = frozenset({
    "plant_canopy_layer",
    "succession_roles",
    "worldgen_suitability_profile",
    "biosphere_growth_profile",
})

PLANT_LEGACY_FIELDS = frozenset({
    "plant_life_cycle",
    "plant_canopy_layer",
    "light_tolerance",
    "moisture_tolerance",
    "soil_texture_tolerance",
    "soil_drainage_tolerance",
    "soil_ph_tolerance",
    "temperature_tolerance_c",
    "frost_tolerance_c",
    "disturbance_tolerance",
    "trampling_tolerance",
    "altitude_tolerance_m",
    "worldgen_suitability_profile",
    "biosphere_growth_profile",
    "establishment_requirements",
    "rooting_profile",
    "reproductive_strategy",
    "dispersal_vectors",
    "succession_roles",
    "pollination_vectors",
    "biotic_interactions",
    "simulation_notes",
})


def _choices(*values):
    return tuple(
        {
            "value": value,
            "label": label,
        }
        for value, label in values
    )


# These are intentionally conservative UI vocabularies, not closed scientific
# ontologies.  ``other_unknown`` keeps the picker usable while terminology is
# still being reviewed.
PLANT_TRAIT_CHOICES = {
    "plant_life_form": _choices(
        ("therophyte", "Therophyte"),
        ("hemicryptophyte", "Hemicryptophyte"),
        ("geophyte", "Geophyte"),
        ("chamaephyte", "Chamaephyte"),
        ("phanerophyte", "Phanerophyte"),
        ("hydrophyte", "Hydrophyte"),
        ("other_unknown", "Other / unknown"),
    ),
    "plant_woodiness": _choices(
        ("woody", "Woody"),
        ("herbaceous", "Herbaceous"),
        ("other_unknown", "Other / unknown"),
    ),
    "mature_height_class": _choices(
        ("dwarf", "Dwarf"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("tall", "Tall"),
        ("canopy", "Canopy"),
        ("emergent", "Emergent"),
        ("other_unknown", "Other / unknown"),
    ),
    "growth_rate": _choices(
        ("slow", "Slow"),
        ("moderate", "Moderate"),
        ("fast", "Fast"),
        ("other_unknown", "Other / unknown"),
    ),
    "maturity_rate": _choices(
        ("rapid", "Rapid"),
        ("fast", "Fast"),
        ("moderate", "Moderate"),
        ("slow", "Slow"),
        ("other_unknown", "Other / unknown"),
    ),
    "longevity_class": _choices(
        ("very_short", "Very short"),
        ("short", "Short"),
        ("moderate", "Moderate"),
        ("long", "Long"),
        ("very_long", "Very long"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_phenology": _choices(
        ("evergreen", "Evergreen"),
        ("deciduous", "Deciduous"),
        ("semi_deciduous", "Semi-deciduous"),
        ("drought_deciduous", "Drought-deciduous"),
        ("marcescent", "Marcescent"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_size_class": _choices(
        ("very_small", "Very small"),
        ("small", "Small"),
        ("medium", "Medium"),
        ("large", "Large"),
        ("very_large", "Very large"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_structure": _choices(
        ("simple", "Simple"),
        ("pinnately_compound", "Pinnately compound"),
        ("palmately_compound", "Palmately compound"),
        ("scale_like", "Scale-like"),
        ("needle_like", "Needle-like"),
        ("frond_like", "Frond-like"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_arrangement": _choices(
        ("alternate", "Alternate"),
        ("opposite", "Opposite"),
        ("whorled", "Whorled"),
        ("basal", "Basal"),
        ("distichous", "Distichous"),
        ("spiral", "Spiral"),
        ("fascicled", "Fascicled"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_attachment_pattern": _choices(
        ("along_stem", "Along stem"),
        ("terminal_cluster", "Terminal cluster"),
        ("basal_rosette", "Basal rosette"),
        ("branch_tips", "Branch tips"),
        ("mixed", "Mixed"),
        ("other_unknown", "Other / unknown"),
    ),
    "leaf_clustering": _choices(
        ("solitary", "Solitary"),
        ("paired", "Paired"),
        ("tufted", "Tufted"),
        ("rosette", "Rosette"),
        ("dense_cluster", "Dense cluster"),
        ("distributed", "Distributed"),
        ("other_unknown", "Other / unknown"),
    ),
    "plant_shoot_dimorphism": _choices(
        ("single_shoot_system", "Single shoot system"),
        ("long_and_short_shoots", "Long and short shoots"),
        ("other_unknown", "Other / unknown"),
    ),
    "plant_leaf_distribution": _choices(
        ("along_shoot", "Along shoot"),
        ("mixed_long_short_shoots", "Mixed long / short shoots"),
        ("terminal_cluster", "Terminal cluster"),
        ("basal_rosette", "Basal rosette"),
        ("other_unknown", "Other / unknown"),
    ),
    "photosynthesis_pathway": _choices(
        ("c3", "C3"),
        ("c4", "C4"),
        ("cam", "CAM"),
        ("other_unknown", "Other / unknown"),
    ),
    "root_architecture": _choices(
        ("taproot", "Taproot"),
        ("fibrous", "Fibrous"),
        ("adventitious", "Adventitious"),
        ("mixed", "Mixed"),
        ("other_unknown", "Other / unknown"),
    ),
    "root_depth_class": _choices(
        ("shallow", "Shallow"),
        ("intermediate", "Intermediate"),
        ("deep", "Deep"),
        ("other_unknown", "Other / unknown"),
    ),
    "reproductive_mode": _choices(
        ("sexual", "Sexual"),
        ("vegetative", "Vegetative"),
        ("both", "Both"),
        ("apomictic", "Apomictic"),
        ("other_unknown", "Other / unknown"),
    ),
    "seed_size_class": _choices(
        ("tiny", "Tiny"),
        ("small", "Small"),
        ("medium", "Medium"),
        ("large", "Large"),
        ("very_large", "Very large"),
        ("other_unknown", "Other / unknown"),
    ),
    "clonal_spread": _choices(
        ("none", "None"),
        ("low", "Low"),
        ("moderate", "Moderate"),
        ("high", "High"),
        ("other_unknown", "Other / unknown"),
    ),
    "resprouting": _choices(
        ("absent", "Absent"),
        ("weak", "Weak"),
        ("moderate", "Moderate"),
        ("strong", "Strong"),
        ("other_unknown", "Other / unknown"),
    ),
    "regeneration_strategy": _choices(
        ("seed_bank", "Seed bank"),
        ("vegetative_recruitment", "Vegetative recruitment"),
        ("resprouting", "Resprouting"),
        ("disturbance_colonization", "Disturbance colonization"),
        ("gap_recruitment", "Gap recruitment"),
        ("mixed", "Mixed"),
        ("other_unknown", "Other / unknown"),
    ),
    "nitrogen_fixation": _choices(
        ("none", "None"),
        ("associated", "Associated / facultative"),
        ("active", "Active / capable"),
        ("other_unknown", "Other / unknown"),
    ),
    "nutrition_mode": _choices(
        ("autotrophic", "Autotrophic"),
        ("parasitic", "Parasitic"),
        ("hemiparasitic", "Hemiparasitic"),
        ("mycoheterotrophic", "Mycoheterotrophic"),
        ("carnivorous", "Carnivorous"),
        ("mixotrophic", "Mixotrophic"),
        ("other_unknown", "Other / unknown"),
    ),
    "mycorrhizal_type": _choices(
        ("none", "None"),
        ("arbuscular", "Arbuscular"),
        ("ectomycorrhizal", "Ectomycorrhizal"),
        ("ericoid", "Ericoid"),
        ("orchid", "Orchid"),
        ("mixed", "Mixed"),
        ("other_unknown", "Other / unknown"),
    ),
    "shade_tolerance": _choices(
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("other_unknown", "Other / unknown"),
    ),
    "moisture_preference": _choices(
        ("very_dry", "Very dry"),
        ("dry", "Dry"),
        ("mesic", "Mesic"),
        ("moist", "Moist"),
        ("wet", "Wet"),
        ("aquatic", "Aquatic"),
        ("other_unknown", "Other / unknown"),
    ),
    "waterlogging_tolerance": _choices(
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("other_unknown", "Other / unknown"),
    ),
    "salinity_tolerance": _choices(
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("other_unknown", "Other / unknown"),
    ),
}

PLANT_TRAIT_DROPDOWN_FIELDS = frozenset(PLANT_TRAIT_CHOICES)

PLANT_TRAIT_BEHAVIOR_PATHS = {
    "plant_life_form": ("Plant Life History", "Plant Life Form"),
    "plant_woodiness": ("Plant Life History", "Woodiness"),
    "mature_height_class": ("Plant Life History", "Mature Height Class"),
    "growth_rate": ("Growth", "Growth Rate"),
    "maturity_rate": ("Growth", "Maturity Rate"),
    "longevity_class": ("Growth", "Longevity Class"),
    "leaf_phenology": ("Leaf / Shoot Function", "Leaf Phenology"),
    "leaf_size_class": ("Leaf / Shoot Function", "Leaf Size Class"),
    "leaf_structure": ("Leaf / Shoot Function", "Leaf Structure"),
    "leaf_arrangement": ("Leaf / Shoot Architecture", "Leaf Arrangement"),
    "leaf_attachment_pattern": ("Leaf / Shoot Architecture", "Leaf Attachment"),
    "leaf_clustering": ("Leaf / Shoot Architecture", "Leaf Clustering"),
    "plant_shoot_dimorphism": ("Leaf / Shoot Architecture", "Shoot Dimorphism"),
    "plant_leaf_distribution": ("Leaf / Shoot Architecture", "Leaf Distribution"),
    "plant_leaf_spacing_bias": ("Leaf / Shoot Architecture", "Leaf Spacing Bias"),
    "plant_leaf_depth_gradient": ("Leaf / Shoot Architecture", "Leaf Depth Gradient"),
    "plant_leaf_cluster_density": ("Leaf / Shoot Architecture", "Leaf Cluster Density"),
    "plant_branch_droop": ("Branch Architecture", "Branch Droop"),
    "plant_branch_angle_gradient": ("Branch Architecture", "Branch Angle Gradient"),
    "plant_crown_openness": ("Branch Architecture", "Crown Openness"),
    "plant_fine_twig_density": ("Branch Architecture", "Fine Twig Density"),
    "photosynthesis_pathway": ("Physiology / Water Strategy", "Photosynthesis Pathway"),
    "root_architecture": ("Roots / Belowground", "Root Architecture"),
    "root_depth_class": ("Roots / Belowground", "Root Depth Class"),
    "reproductive_mode": ("Reproduction", "Reproductive Mode"),
    "seed_size_class": ("Reproduction", "Seed Size Class"),
    "clonal_spread": ("Reproduction", "Clonal Spread"),
    "resprouting": ("Regeneration / Disturbance", "Resprouting"),
    "regeneration_strategy": ("Regeneration / Disturbance", "Regeneration Strategy"),
    "nitrogen_fixation": ("Nutrition / Symbiosis", "Nitrogen Fixation"),
    "nutrition_mode": ("Nutrition / Symbiosis", "Nutrition Mode"),
    "mycorrhizal_type": ("Nutrition / Symbiosis", "Mycorrhizal Type"),
    "shade_tolerance": ("Environmental Response", "Shade Tolerance"),
    "moisture_preference": ("Environmental Response", "Moisture Preference"),
    "waterlogging_tolerance": ("Environmental Response", "Waterlogging Tolerance"),
    "salinity_tolerance": ("Environmental Response", "Salinity Tolerance"),
}


def plant_trait_choice_rows(field_key):
    choices = PLANT_TRAIT_CHOICES.get(field_key)
    if not choices:
        return []
    path = PLANT_TRAIT_BEHAVIOR_PATHS.get(field_key, (field_key,))
    headings = [
        {"kind": "heading", "depth": 0, "label": "Behaviour"},
        {"kind": "heading", "depth": 1, "label": "Plant Behaviour"},
    ]
    headings.extend(
        {"kind": "heading", "depth": index + 2, "label": label}
        for index, label in enumerate(path)
    )
    return headings + [dict(choice) for choice in choices]


def canonical_plant_trait_value(field_key, value):
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    return text


def plant_trait_display_label(field_key, value):
    canonical = canonical_plant_trait_value(field_key, value)
    choice = next(
        (choice for choice in PLANT_TRAIT_CHOICES.get(field_key, ()) if choice["value"] == canonical),
        None,
    )
    if choice:
        return choice["label"]
    return f"Custom: {value}" if value not in (None, "") else "Choose a value"
