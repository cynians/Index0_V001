"""Controlled vocabulary for the primary architecture of plant growth.

The literature treats plant architecture as a combination of dimensions rather
than one universal list of mutually exclusive growth forms.  This catalog is
therefore deliberately a *primary strategy* picker for the species card.  The
orthogonal axis-continuity, branching-rhythm/timing, lateral-axis orientation,
flowering-position and apical-control traits live in ``world.plant_traits``;
phyllotaxis remains derived from leaf arrangement.
"""

from world.plant_traits import (
    PLANT_TRAIT_DROPDOWN_FIELDS,
    canonical_plant_trait_value,
    plant_trait_choice_rows,
    plant_trait_display_label,
)

PLANT_GROWTH_FORM_FIELD = "plant_growth_form"
PLANT_GROWTH_BEHAVIOUR_FIELD = "plant_growth_behaviour"
# ``plant_life_cycle`` is retained only as a read/edit compatibility alias for
# hand-built cards.  The active schema field is ``plant_lifespan``.
PLANT_LIFESPAN_FIELD = "plant_lifespan"
PLANT_LIFE_CYCLE_FIELD = "plant_life_cycle"

PLANT_GROWTH_FORM_HEADINGS = (
    {"kind": "heading", "depth": 0, "label": "Behaviour"},
    {"kind": "heading", "depth": 1, "label": "Plant Behaviour"},
    {"kind": "heading", "depth": 2, "label": "Plant Growth Form"},
)

PLANT_GROWTH_FORM_CHOICES = (
    {
        "value": "tree",
        "label": "Tree",
        "description": "A woody plant typically organized around a persistent main axis.",
    },
    {
        "value": "shrub",
        "label": "Shrub",
        "description": "A woody plant with multiple persistent or near-ground axes.",
    },
    {
        "value": "subshrub",
        "label": "Subshrub",
        "description": "A low plant with woody basal tissue and herbaceous or seasonal upper growth.",
    },
    {
        "value": "forb",
        "label": "Forb",
        "description": "A non-graminoid herbaceous flowering plant.",
    },
    {
        "value": "graminoid",
        "label": "Graminoid",
        "description": "A grass-like plant with narrow leaves and usually basal or jointed shoots.",
    },
    {
        "value": "vine",
        "label": "Vine",
        "description": "A climbing or trailing plant whose support strategy is structurally important.",
    },
    {
        "value": "fern",
        "label": "Fern",
        "description": "A vascular spore-bearing plant with fronds rather than flowers or seeds.",
    },
    {
        "value": "moss",
        "label": "Moss",
        "description": "A small non-vascular or bryophyte-like ground-forming plant.",
    },
    {
        "value": "succulent",
        "label": "Succulent",
        "description": "A plant whose body plan is strongly shaped by water-storage tissue.",
    },
    {
        "value": "aquatic",
        "label": "Aquatic",
        "description": "A plant structurally adapted to submerged, floating, or emergent growth.",
    },
    {
        "value": "other_unknown",
        "label": "Other / unknown",
        "description": "Use when the broad botanical body plan is not yet known.",
    },
)

PLANT_GROWTH_FORM_OPTION_ROWS = PLANT_GROWTH_FORM_HEADINGS + PLANT_GROWTH_FORM_CHOICES

PLANT_GROWTH_BEHAVIOUR_HEADINGS = (
    {"kind": "heading", "depth": 0, "label": "Behaviour"},
    {"kind": "heading", "depth": 1, "label": "Plant Behaviour"},
    {"kind": "heading", "depth": 2, "label": "Plant Growth Behaviour"},
)

PLANT_GROWTH_BEHAVIOUR_CHOICES = (
    {
        "value": "iterative_indeterminate",
        "label": "Iterative / indeterminate shoot",
        "short_label": "Iterative shoot",
        "description": "Repeated shoot units continue to extend from active apices.",
    },
    {
        "value": "unbranched_single_axis",
        "label": "Unbranched / single axis",
        "short_label": "Single culm",
        "description": "One primary upright stem carries leaves and may end in one terminal inflorescence.",
    },
    {
        "value": "determinate_sympodial",
        "label": "Determinate / sympodial shoot",
        "short_label": "Determinate shoot",
        "description": "A shoot segment ends and continuation shifts to a lateral unit.",
    },
    {
        "value": "rosette_short_internode",
        "label": "Rosette / short-internode",
        "short_label": "Rosette",
        "description": "Leaves are concentrated around a compressed stem axis.",
    },
    {
        "value": "branched_woody",
        "label": "Branched woody architecture",
        "short_label": "Branched woody",
        "description": "Persistent axes form a hierarchical trunk and branch system.",
    },
    {
        "value": "climbing_support_dependent",
        "label": "Climbing / twining / scrambling",
        "short_label": "Climbing",
        "description": "The plant gains height through external support or contact.",
    },
    {
        "value": "creeping_prostrate",
        "label": "Creeping / prostrate",
        "short_label": "Creeping",
        "description": "Horizontal or near-ground axes spread across the substrate.",
    },
    {
        "value": "tussock_tillering",
        "label": "Tussock / tillering",
        "short_label": "Tussock",
        "description": "Repeated basal shoots form a tuft or compact clump.",
    },
    {
        "value": "rhizomatous_clonal",
        "label": "Rhizomatous clonal spread",
        "short_label": "Rhizomatous clone",
        "description": "Below-ground horizontal axes produce connected ramets.",
    },
    {
        "value": "stoloniferous_clonal",
        "label": "Stoloniferous / runner spread",
        "short_label": "Runner clone",
        "description": "Above-ground runners produce daughter plantlets or rooting nodes.",
    },
    {
        "value": "suckering_clonal",
        "label": "Suckering / basal clonal spread",
        "short_label": "Suckering clone",
        "description": "New shoots arise from roots, crowns, or persistent basal tissue.",
    },
    {
        "value": "fern_fronding",
        "label": "Fern / fronding",
        "short_label": "Fronding",
        "description": "Repeated fronds rise from a crown or rhizome and carry leaflets along a rachis.",
    },
    {
        "value": "basal_succulent_rosette",
        "label": "Basal succulent rosette",
        "short_label": "Succulent rosette",
        "description": "Fleshy leaves radiate from a compressed water-storing base.",
    },
    {
        "value": "moss_mat",
        "label": "Moss mat",
        "short_label": "Moss mat",
        "description": "Low repeated shoots form a spreading carpet close to the substrate.",
    },
)

PLANT_GROWTH_BEHAVIOUR_OPTION_ROWS = PLANT_GROWTH_BEHAVIOUR_HEADINGS + PLANT_GROWTH_BEHAVIOUR_CHOICES
# US spelling alias for existing callers.
PLANT_GROWTH_BEHAVIOR_HEADINGS = PLANT_GROWTH_BEHAVIOUR_HEADINGS

PLANT_LIFE_CYCLE_BEHAVIOR_HEADINGS = (
    {"kind": "heading", "depth": 0, "label": "Behaviour"},
    {"kind": "heading", "depth": 1, "label": "Plant Behaviour"},
    {"kind": "heading", "depth": 2, "label": "Plant Life-Cycle Behaviour"},
)

PLANT_LIFE_CYCLE_CHOICES = (
    {
        "value": "ephemeral",
        "label": "Ephemeral",
        "description": "Completes its active life phase very rapidly when conditions permit.",
    },
    {
        "value": "annual",
        "label": "Annual",
        "description": "Normally completes its life cycle within one growing season or year.",
    },
    {
        "value": "biennial",
        "label": "Biennial",
        "description": "Normally requires two growing seasons, commonly vegetative then reproductive.",
    },
    {
        "value": "short_lived_perennial",
        "label": "Short-lived perennial",
        "description": "Persists for multiple years but has a relatively short adult lifespan.",
    },
    {
        "value": "perennial",
        "label": "Perennial",
        "description": "Persists and can reproduce across multiple years or seasons.",
    },
)

PLANT_LIFE_CYCLE_OPTION_ROWS = PLANT_LIFE_CYCLE_BEHAVIOR_HEADINGS + PLANT_LIFE_CYCLE_CHOICES

# Values already present in the ontology are retained as readable aliases so
# the first controlled edit does not silently destroy existing vocabulary.
PLANT_GROWTH_FORM_LEGACY_ALIASES = {
    "perennial_forb_rosette": "forb",
    "rosette": "forb",
    "deciduous_shrub": "shrub",
    "evergreen_shrub": "shrub",
    "woody": "tree",
    "herb": "forb",
    "climber": "vine",
    "liana": "vine",
}

PLANT_GROWTH_BEHAVIOUR_LEGACY_ALIASES = {
    "rosette": "rosette_short_internode",
    "branched_woody": "branched_woody",
    "climber": "climbing_support_dependent",
    "vine": "climbing_support_dependent",
    "runner": "stoloniferous_clonal",
    "rhizome": "rhizomatous_clonal",
}

PLANT_LIFE_CYCLE_LEGACY_ALIASES = {
    "perennial_woody": "perennial",
    "short_lived_perennial": "short_lived_perennial",
    "short-lived_perennial": "short_lived_perennial",
}


def plant_growth_form_choices():
    """Return fresh choice dictionaries for UI consumers."""

    return [dict(choice) for choice in PLANT_GROWTH_FORM_CHOICES]


def canonical_plant_growth_form(value):
    """Map a stored or legacy value to the catalog's canonical ID."""

    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    return PLANT_GROWTH_FORM_LEGACY_ALIASES.get(text, text)


def plant_growth_form_choice(value):
    """Return the selected choice dictionary, if it is catalogued."""

    canonical = canonical_plant_growth_form(value)
    return next(
        (dict(choice) for choice in PLANT_GROWTH_FORM_CHOICES if choice["value"] == canonical),
        None,
    )


def plant_growth_form_display_label(value):
    """Return a user-facing label while preserving unknown legacy values."""

    choice = plant_growth_form_choice(value)
    if choice is not None:
        return choice["label"]
    text = str(value or "").strip()
    return f"Legacy: {text}" if text else "Choose a growth form"


def canonical_plant_growth_behaviour(value):
    """Map a stored architecture behaviour to its canonical grammar ID."""

    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    return PLANT_GROWTH_BEHAVIOUR_LEGACY_ALIASES.get(text, text)


def plant_growth_behaviour_display_label(value):
    canonical = canonical_plant_growth_behaviour(value)
    choice = next(
        (choice for choice in PLANT_GROWTH_BEHAVIOUR_CHOICES if choice["value"] == canonical),
        None,
    )
    text = str(value or "").strip()
    return choice["label"] if choice is not None else (f"Legacy: {text}" if text else "Choose a growth behaviour")


def canonical_plant_life_cycle(value):
    text = str(value or "").strip().lower().replace(" ", "_")
    if not text:
        return ""
    return PLANT_LIFE_CYCLE_LEGACY_ALIASES.get(text, text)


def plant_life_cycle_display_label(value):
    canonical = canonical_plant_life_cycle(value)
    choice = next(
        (choice for choice in PLANT_LIFE_CYCLE_CHOICES if choice["value"] == canonical),
        None,
    )
    if choice is not None:
        return choice["label"]
    text = str(value or "").strip()
    return f"Legacy: {text}" if text else "Choose a life cycle"


def controlled_plant_field_rows(field_key):
    if field_key == PLANT_GROWTH_FORM_FIELD:
        return [dict(row) for row in PLANT_GROWTH_FORM_OPTION_ROWS]
    if field_key == PLANT_GROWTH_BEHAVIOUR_FIELD:
        return [dict(row) for row in PLANT_GROWTH_BEHAVIOUR_OPTION_ROWS]
    if field_key in {PLANT_LIFESPAN_FIELD, PLANT_LIFE_CYCLE_FIELD}:
        return [dict(row) for row in PLANT_LIFE_CYCLE_OPTION_ROWS]
    if field_key in PLANT_TRAIT_DROPDOWN_FIELDS:
        return plant_trait_choice_rows(field_key)
    return []


def controlled_plant_field_display_label(field_key, value):
    if field_key == PLANT_GROWTH_FORM_FIELD:
        return plant_growth_form_display_label(value)
    if field_key == PLANT_GROWTH_BEHAVIOUR_FIELD:
        return plant_growth_behaviour_display_label(value)
    if field_key in {PLANT_LIFESPAN_FIELD, PLANT_LIFE_CYCLE_FIELD}:
        return plant_life_cycle_display_label(value)
    if field_key in PLANT_TRAIT_DROPDOWN_FIELDS:
        return plant_trait_display_label(field_key, value)
    return str(value or "")


def canonical_controlled_plant_value(field_key, value):
    if field_key == PLANT_GROWTH_FORM_FIELD:
        return canonical_plant_growth_form(value)
    if field_key == PLANT_GROWTH_BEHAVIOUR_FIELD:
        return canonical_plant_growth_behaviour(value)
    if field_key in {PLANT_LIFESPAN_FIELD, PLANT_LIFE_CYCLE_FIELD}:
        return canonical_plant_life_cycle(value)
    if field_key in PLANT_TRAIT_DROPDOWN_FIELDS:
        return canonical_plant_trait_value(field_key, value)
    return str(value or "")
