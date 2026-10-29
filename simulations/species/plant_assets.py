"""Portable plant authoring and scenery products.

The ontology identifies a species and can optionally point at a blueprint.
Large pixel documents and generated growth products live in the asset store,
so an ontology entity does not grow a copy of every leaf placement.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine import asset_files
from world.plant_growth_catalog import (
    canonical_plant_growth_behaviour,
    canonical_plant_growth_form,
    canonical_plant_life_cycle,
)
from world.plant_traits import (
    PLANT_ARCHITECTURE_RANGE_FIELDS,
    PLANT_TRAIT_FIELDS,
    normalised_plant_trait_range,
)
from simulations.species.root_growth import root_profile


PLANT_ASSET_SCHEMA_VERSION = 4
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Plant geometry is authored and simulated in a right-handed, z-up model
# space.  Pixel modules remain 2D assets; the renderer projects this model
# orthographically for the current diagnostic and scenery views.
PLANT_MODEL_SPACE = {
    "dimensions": 3,
    "up_axis": "z",
    "depth_axis": "y",
    "projection": "orthographic",
    "asset_dimension": 2,
}

PLANT_LIFE_HISTORY_PROFILES = {
    "ephemeral": {
        "cycle_days": 45.0,
        "age_limit_days": 45.0,
        "reproductive_start_fraction": 0.50,
        "senescence_start_fraction": 0.80,
        "terminal_reproduction": True,
        "overwintering": False,
    },
    "annual": {
        "cycle_days": 365.0,
        "age_limit_days": 365.0,
        "reproductive_start_fraction": 0.50,
        "senescence_start_fraction": 0.86,
        "terminal_reproduction": True,
        "overwintering": False,
    },
    "biennial": {
        "cycle_days": 730.0,
        "age_limit_days": 730.0,
        "reproductive_start_fraction": 0.50,
        "senescence_start_fraction": 0.88,
        "terminal_reproduction": True,
        "overwintering": True,
    },
    "short_lived_perennial": {
        "cycle_days": 365.0,
        "age_limit_days": 3650.0,
        "reproductive_start_fraction": 0.35,
        "senescence_start_fraction": 0.80,
        "terminal_reproduction": False,
        "overwintering": True,
    },
    "perennial": {
        "cycle_days": 365.0,
        "age_limit_days": None,
        "reproductive_start_fraction": 0.35,
        "senescence_start_fraction": 0.75,
        "terminal_reproduction": False,
        "overwintering": True,
    },
}


def plant_life_history_profile(value, maturity_days):
    """Resolve the categorical lifespan into transient Species Sim timings."""

    canonical_lifespan = canonical_plant_life_cycle(value)
    lifespan = canonical_lifespan if canonical_lifespan in PLANT_LIFE_HISTORY_PROFILES else "perennial"
    source = "authored" if canonical_lifespan in PLANT_LIFE_HISTORY_PROFILES else "runtime_default"
    template = PLANT_LIFE_HISTORY_PROFILES.get(lifespan, PLANT_LIFE_HISTORY_PROFILES["perennial"])
    profile = dict(template)
    cycle_days = float(profile["cycle_days"])
    maturity_days = max(1.0, float(maturity_days))
    profile.update(
        {
            "class": lifespan,
            "maturity_days": maturity_days,
            "reproductive_start_days": max(
                maturity_days,
                cycle_days * float(profile["reproductive_start_fraction"]),
            ),
            "senescence_start_days": max(
                maturity_days,
                cycle_days * float(profile["senescence_start_fraction"]),
                # Slow perennial trees should have a meaningful mature,
                # reproductive interval instead of becoming senescent on the
                # exact day their authored maturity is reached.
                maturity_days + (cycle_days * 0.25 if lifespan == "perennial" else 0.0),
            ),
            "source": source,
        }
    )
    return profile


def normalised_plant_trait(value, default=0.5):
    """Read a continuous 0..1 plant trait without letting bad data break sim."""

    return float(normalised_plant_trait_range(value, default)["typical"])


def species_architecture_defaults(species_id, form, base_defaults):
    """Nudge a growth form's default canopy-shape coefficients per species.

    Without this, every species that hasn't authored
    branch_droop/crown_openness/etc renders with the *exact same* floats as
    every other species of the same growth form -- a landscape of
    unauthored trees (or shrubs, or forbs, ...) is visually indistinguishable
    clones differing only in height and colour. This only ever changes the
    *default* used when a field is unauthored: an authored value is read
    directly by ``normalised_plant_trait`` and never touches this function.
    Rendering-level only, deterministic, bounded, never persisted -- same
    spirit as ``SpeciesRenderer._species_tint``.
    """
    if not species_id or species_id == "unknown_species":
        return base_defaults
    rng = random.Random(sum(ord(char) for char in f"{species_id}:{form}:architecture"))
    return tuple(
        max(0.0, min(1.0, base + rng.uniform(-0.07, 0.07)))
        for base in base_defaults
    )


def quantitative_plant_trait(value, default, minimum=0.0, maximum=None):
    """Resolve an authored point or range to a bounded typical runtime value."""

    candidate = value
    if isinstance(value, dict):
        candidate = value.get("typical_m", value.get("typical"))
        if candidate is None:
            lower = value.get("min_m", value.get("min"))
            upper = value.get("max_m", value.get("max"))
            try:
                candidate = (float(lower) + float(upper)) * 0.5
            except (TypeError, ValueError):
                candidate = upper if upper is not None else lower
    try:
        result = float(candidate)
    except (TypeError, ValueError):
        result = float(default)
    result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result

def is_plant_species_entity(entity: dict[str, Any] | None, plant_catalogue=None) -> bool:
    """Constant-time membership in the repository's Plantae ancestry index.

    Standalone callers must supply a catalogue; names and trait presence are
    never evidence of ancestry. Explicit SpeciesSimulation fixtures can still
    be constructed without a repository for isolated grammar experiments.
    """
    return bool(isinstance(entity,dict) and plant_catalogue is not None
                and plant_catalogue.is_species(entity.get("id")))


def is_surface_species_entity(entity, entities):
    """Verified fungal growth-lab eligibility, without changing Plantae."""
    if not isinstance(entity,dict) or entity.get("plant_growth_form") != "lichen":
        return False
    if entity.get("plant_growth_behaviour") != "surface_covering" or not entity.get("surface_growth_profile"):
        return False
    from world.plant_catalogue import PlantCatalogue
    return PlantCatalogue.build(entities or {},root_id="cladis_fungi").is_species(entity.get("id"))


def is_fungal_growth_species_entity(entity, entities):
    if not isinstance(entity, dict) or not entity.get("fungal_growth_profile"):
        return False
    from world.fungal_traits import validate_fungal_profile
    from world.plant_catalogue import PlantCatalogue
    try:
        validate_fungal_profile(entity["fungal_growth_profile"])
    except (ValueError, TypeError):
        return False
    return PlantCatalogue.build(entities or {}, root_id="cladis_fungi").is_species(entity.get("id"))


def _safe_id(value: str, fallback: str = "plant") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip())
    return text.strip("._-") or fallback


def _tuple3(value, default=(0.0, 0.0, 0.0)):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return tuple(default)
    try:
        return tuple(float(value[index]) for index in range(3))
    except (TypeError, ValueError):
        return tuple(default)


def _tuple2(value, default=(0.5, 0.9)):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return tuple(default)
    try:
        return tuple(float(value[index]) for index in range(2))
    except (TypeError, ValueError):
        return tuple(default)


def pixel_asset_depicted_size_m(asset_ref: str | None) -> float | None:
    """Read the physical display size authored in a Pixel Studio document.

    The PNG is the raster product; its adjacent ``.layers.json.gz`` document
    owns the metric size.  Keep this separate from ``PlantModule.length_m``:
    length can drive structural/physiological formulas, while depicted size is
    only the scale of the authored reusable sprite.
    """

    if not asset_ref:
        return None
    asset_path = Path(str(asset_ref))
    if not asset_path.is_absolute():
        asset_path = _PROJECT_ROOT / asset_path
    document_path = asset_path.with_suffix(".layers.json.gz")
    try:
        with asset_files.open_gzip_text(document_path) as handle:
            document = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    dimensions = document.get("dimensions_m") if isinstance(document, dict) else None
    if not isinstance(dimensions, dict):
        return None
    candidates = [dimensions.get("size")]
    candidates.extend(dimensions.get(key) for key in ("length", "width", "height"))
    values = []
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0.0:
            values.append(value)
    return max(values) if values else None


@dataclass(frozen=True)
class PlantModule:
    """One authored reusable part of a plant."""

    id: str
    kind: str
    asset_ref: str | None = None
    texture_set_ref: str | None = None
    length_m: float = 0.1
    radius_m: float = 0.01
    sockets: tuple[str, ...] = ("base", "tip")
    attachment_point: tuple[float, float] = (0.5, 0.9)
    growth_axis: tuple[float, float] = (0.0, -1.0)
    visual: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "asset_ref": self.asset_ref,
            "texture_set_ref": self.texture_set_ref,
            "length_m": self.length_m,
            "radius_m": self.radius_m,
            "sockets": list(self.sockets),
            "attachment_point": list(self.attachment_point),
            "growth_vector": list(self.growth_axis),
            "growth_axis": list(self.growth_axis),
            "visual": dict(self.visual),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlantModule":
        return cls(
            id=str(value.get("id") or "module"),
            kind=str(value.get("kind") or "stem_section"),
            asset_ref=value.get("asset_ref"),
            texture_set_ref=value.get("texture_set_ref"),
            length_m=float(value.get("length_m", 0.1) or 0.1),
            # Zero is an explicit absent stalk, not a missing dimension.
            radius_m=float(0.01 if value.get("radius_m") is None else value["radius_m"]),
            sockets=tuple(str(item) for item in value.get("sockets", ("base", "tip"))),
            attachment_point=_tuple2(value.get("attachment_point")),
            growth_axis=_tuple2(value.get("growth_vector") or value.get("growth_axis"), (0.0, -1.0)),
            visual=dict(value.get("visual") or {}),
        )


@dataclass
class PlantBlueprint:
    """Species-specific authored parts plus procedural growth parameters."""

    species_id: str
    display_name: str
    modules: list[PlantModule]
    root_module_id: str = "root"
    growth: dict[str, Any] = field(default_factory=dict)
    lod_policy: dict[str, Any] = field(default_factory=dict)
    model_space: dict[str, Any] = field(default_factory=lambda: dict(PLANT_MODEL_SPACE))
    version: int = PLANT_ASSET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.version,
            "kind": "plant_blueprint",
            "species_id": self.species_id,
            "display_name": self.display_name,
            "root_module_id": self.root_module_id,
            "modules": [module.to_dict() for module in self.modules],
            "growth": dict(self.growth),
            "lod_policy": dict(self.lod_policy),
            "model_space": dict(self.model_space),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlantBlueprint":
        return cls(
            species_id=str(value.get("species_id") or "unknown_species"),
            display_name=str(value.get("display_name") or value.get("species_id") or "Plant"),
            root_module_id=str(value.get("root_module_id") or "root"),
            modules=[PlantModule.from_dict(item) for item in value.get("modules", []) if isinstance(item, dict)],
            growth=dict(value.get("growth") or {}),
            lod_policy=dict(value.get("lod_policy") or {}),
            model_space={**PLANT_MODEL_SPACE, **dict(value.get("model_space") or {})},
            version=int(value.get("schema_version", PLANT_ASSET_SCHEMA_VERSION) or PLANT_ASSET_SCHEMA_VERSION),
        )

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def module(self, module_id: str) -> PlantModule | None:
        return next((module for module in self.modules if module.id == module_id), None)

    @classmethod
    def from_species_entity(cls, entity: dict[str, Any], species_id: str | None = None) -> "PlantBlueprint":
        """Build a safe starter blueprint, including for sparsely annotated plants."""
        species_id = str(species_id or entity.get("id") or "unknown_species")
        if entity.get("fungal_growth_profile"):
            from simulations.species.fungal_growth import fungal_blueprint
            return fungal_blueprint(entity, species_id)
        display_name = str(
            entity.get("common_name")
            or entity.get("binomial_name")
            or entity.get("pretty_name")
            or entity.get("name")
            or species_id
        )
        raw_form = str(entity.get("plant_growth_form") or "")
        form = canonical_plant_growth_form(raw_form)
        behaviour = canonical_plant_growth_behaviour(entity.get("plant_growth_behaviour"))
        # Read-only compatibility for the old artefact vocabulary. New
        # entries should author the two fields separately.
        raw_form_key = raw_form.lower().replace("-", "_").replace(" ", "_")
        if not behaviour:
            if "rosette" in raw_form_key:
                behaviour = "rosette_short_internode"
            elif raw_form_key in {"deciduous_shrub", "evergreen_shrub", "branched_woody"}:
                behaviour = "branched_woody"
            elif raw_form_key in {"climber", "vine"}:
                behaviour = "climbing_support_dependent"
        if not behaviour and form == "graminoid":
            behaviour = "tussock_tillering"
        if not behaviour:
            behaviour = {
                "fern": "fern_fronding",
                "succulent": "basal_succulent_rosette",
                "moss": "moss_mat",
            }.get(form, "iterative_indeterminate")

        module_anchors = entity.get("plant_module_anchors") or {}
        leaf_anchor = module_anchors.get("leaf") if isinstance(module_anchors, dict) else {}
        flower_anchor = module_anchors.get("flower") if isinstance(module_anchors, dict) else {}
        fruit_anchor = module_anchors.get("fruit") if isinstance(module_anchors, dict) else {}
        leaf_anchor = leaf_anchor if isinstance(leaf_anchor, dict) else {}
        flower_anchor = flower_anchor if isinstance(flower_anchor, dict) else {}
        fruit_anchor = fruit_anchor if isinstance(fruit_anchor, dict) else {}

        def depicted_size(anchor, asset_ref):
            try:
                authored = float(anchor.get("depicted_size_m"))
            except (TypeError, ValueError):
                authored = None
            if authored is not None and math.isfinite(authored) and authored > 0.0:
                return authored
            return pixel_asset_depicted_size_m(asset_ref)

        is_rosette = behaviour == "rosette_short_internode"
        is_climber = behaviour == "climbing_support_dependent" or form == "vine"
        is_aquatic = form == "aquatic"
        is_tree = form == "tree"
        is_shrub = form in {"shrub", "subshrub"} or (behaviour == "branched_woody" and not is_tree)

        mature_height = entity.get("mature_height")
        if isinstance(mature_height, dict):
            mature_height = mature_height.get("max_m") or mature_height.get("value_m") or mature_height.get("max")
        try:
            mature_height = float(mature_height) if mature_height is not None else None
        except (TypeError, ValueError):
            mature_height = None
        height_class = str(entity.get("mature_height_class") or "").lower().replace("-", "_").replace(" ", "_")
        height_class_max = {
            "dwarf": 0.25,
            "low": 0.75,
            "medium": 2.0,
            "tall": 6.0,
            "canopy": 15.0,
        }.get(height_class)
        if mature_height is None and height_class_max is not None:
            mature_height = height_class_max
        growth_rate = str(entity.get("growth_rate") or "").lower()
        growth_rate_bias = {"slow": 0.28, "moderate": 0.55, "fast": 0.82}.get(growth_rate, 0.55)
        maturity_rate = str(entity.get("maturity_rate") or "").lower()
        maturity_days = {"rapid": 30.0, "fast": 60.0, "moderate": 120.0, "slow": 365.0}.get(maturity_rate)
        if maturity_days is None:
            maturity_days = {
                "tree": 120.0,
                "shrub": 120.0,
                "subshrub": 75.0,
                "fern": 90.0,
                "succulent": 90.0,
                "moss": 30.0,
            }.get(form, 45.0)
        lifespan = canonical_plant_life_cycle(entity.get("plant_lifespan"))
        if lifespan == "ephemeral":
            maturity_days = min(maturity_days, 20.0)
        elif lifespan == "annual":
            maturity_days = min(maturity_days, 90.0)
        elif lifespan == "biennial":
            maturity_days = max(maturity_days, 365.0)
        life_history = plant_life_history_profile(lifespan, maturity_days)

        if is_aquatic:
            shape = "aquatic"
            max_height, internode, branch_probability = 0.35, 0.28, 0.0
        elif is_rosette:
            shape = "rosette"
            max_height, internode, branch_probability = 0.45, 0.16, 0.0
        elif is_climber:
            shape = "climber"
            max_height, internode, branch_probability = 2.2, 0.28, 0.35
        elif is_tree:
            shape = "tree"
            max_height, internode, branch_probability = 5.0, 0.45, 0.52
        elif form == "shrub":
            shape = "shrub"
            max_height, internode, branch_probability = 2.2, 0.32, 0.62
        elif form == "subshrub":
            shape = "subshrub"
            max_height, internode, branch_probability = 0.9, 0.22, 0.48
        elif form == "forb":
            shape = "forb"
            max_height, internode, branch_probability = 1.0, 0.20, 0.34
        elif form == "graminoid":
            shape = "graminoid"
            max_height, internode, branch_probability = 0.9, 0.18, 0.22
        elif form == "fern":
            shape = "fern"
            max_height, internode, branch_probability = 1.25, 0.18, 0.18
        elif form == "moss":
            shape = "moss"
            max_height, internode, branch_probability = 0.12, 0.08, 0.05
        elif form == "succulent":
            shape = "succulent"
            max_height, internode, branch_probability = 0.9, 0.16, 0.08
        else:
            shape = "herb"
            max_height, internode, branch_probability = 1.2, 0.24, 0.24

        if mature_height is not None:
            reference_height = max_height
            max_height = max(0.1, mature_height)
            if is_tree:
                # The branching grammar is capped to a compact number of
                # generations, so tall trees need longer structural units to
                # reach their authored mature height.
                internode = max(internode, max_height / 14.0)
            elif max_height < reference_height:
                # An authored mature height below the shape's reference
                # stature (e.g. a dwarf/low shrub) otherwise keeps that
                # shape's larger reference internode, starving branch
                # generations toward 1-2 and rendering as a bare skeletal
                # stick instead of a proportioned miniature of the same
                # architecture. Scale the internode down to preserve the
                # shape's designed generation density. Authored heights at
                # or above the reference are left untouched.
                internode = max(0.02, internode * (max_height / reference_height))
        leaf_arrangement = str(entity.get("leaf_arrangement") or "").lower()
        phyllotaxis = 137.5
        if leaf_arrangement == "opposite":
            phyllotaxis = 180.0
        elif leaf_arrangement == "whorled":
            phyllotaxis = 90.0
        elif leaf_arrangement == "distichous":
            phyllotaxis = 180.0
        if str(entity.get("leaf_attachment_pattern") or "").lower() == "basal_rosette" and not is_aquatic and form != 'succulent':
            shape = "rosette"
            behaviour = "rosette_short_internode"
            # A basal attachment may select this grammar for an otherwise
            # unclassified herb. It must not discard a sourced stature.
            max_height = max(0.1, mature_height) if mature_height is not None else 0.45
            internode = max(0.02, 0.16 * max_height / 0.45)
            branch_probability = 0.0

        leaves_per_node = 2 if shape in {"tree", "shrub", "subshrub", "climber"} else 1
        if leaf_arrangement in {"alternate", "distichous"}:
            leaves_per_node = 1
        elif leaf_arrangement == "opposite":
            leaves_per_node = 2
        elif leaf_arrangement == "whorled":
            leaves_per_node = 3
        if str(entity.get("leaf_clustering") or "").lower() in {"solitary", "tufted", "rosette"}:
            leaves_per_node = 1

        leaf_size = str(entity.get("leaf_size_class") or "").lower().replace("-", "_")
        leaf_structure = str(entity.get("leaf_structure") or "simple").lower().replace("-", "_").replace(" ", "_")
        leaf_division_order = max(1, min(4, round(quantitative_plant_trait(entity.get("leaf_division_order"), 1, 1, 4))))
        leaf_size_lengths = {
            "very_small": 0.06,
            "small": 0.10,
            "medium": 0.15,
            "large": 0.24,
            "very_large": 0.38,
        }
        leaf_length = leaf_size_lengths.get(leaf_size, 0.22)
        scaled_tree_leaf_default = False
        if (is_tree and leaf_size not in leaf_size_lengths
                and entity.get("leaf_length") in (None, "", {}, [])
                and not entity.get("plant_leaf_module_ref")):
            # Unknown dimensions need a conservative placeholder on small
            # trees: the old 22 cm leaf also drove shoot lengths, overwhelming
            # a low/dwarf crown. This is a qualitative runtime coefficient,
            # never an authored measurement or a change to known leaf sizes.
            bounded_default = min(leaf_length, max(0.002, max_height * 0.05))
            scaled_tree_leaf_default = bounded_default < leaf_length
            leaf_length = bounded_default
        leaf_length = quantitative_plant_trait(entity.get("leaf_length"), leaf_length, 0.002, 100.0)
        upper_bound_frond = (form == "fern" and isinstance(entity.get("leaf_length"), dict)
                             and entity["leaf_length"].get("status") == "reported_upper_bound_not_typical"
                             and not entity["leaf_length"].get("typical_m"))
        if upper_bound_frond:
            # A reported extreme does not say all ordinary mature fronds
            # attain it. This labelled display default is not an authored
            # typical measurement; the maximum remains on the species card.
            leaf_length *= .65
        leaf_cluster_size = max(1, round(quantitative_plant_trait(entity.get("leaf_cluster_size"), 3, 1, 200)))
        leaflet_count = max(0, round(quantitative_plant_trait(entity.get("leaflet_count"), 0, 0, 2000)))
        leaflet_length = quantitative_plant_trait(entity.get("leaflet_length"), leaf_length * 0.24, 0.001, 20.0)
        leaflet_width = quantitative_plant_trait(entity.get("leaflet_width"), max(0.004, leaf_length * 0.05), 0.0002, 5.0)
        frond_stipe_fraction = normalised_plant_trait(entity.get("frond_stipe_fraction"), 0.36)
        if form == "succulent":
            # Succulent blades are structural organs, not small generic
            # leaves. Their authored socket stays at the base while the
            # 3D-oriented extent determines the visible rosette envelope.
            leaf_length = max(leaf_length, max_height * 0.55)
        elif form == "fern":
            leaf_length = max(leaf_length, 0.16)

        # Architectural categories choose the grammar; these normalised
        # values tune its expression continuously.  Tree defaults are
        # intentionally open and pendulous, while other plant forms retain a
        # neutral profile until they author their own values.
        default_distribution = "along_shoot" if (
            str(entity.get("leaf_attachment_pattern") or "").lower() == "along_stem"
            or form in {"fern", "moss"}
        ) else "terminal_cluster"
        leaf_distribution = str(entity.get("plant_leaf_distribution") or default_distribution).lower().replace("-", "_").replace(" ", "_")
        shoot_dimorphism = str(entity.get("plant_shoot_dimorphism") or ("long_and_short_shoots" if is_tree else "single_shoot_system")).lower().replace("-", "_").replace(" ", "_")
        architecture_defaults = {
            "tree": (0.68, 0.55, 0.72, 0.56, 0.45, 0.68, 0.58),
            "shrub": (0.28, 0.42, 0.42, 0.38, 0.28, 0.46, 0.42),
            "subshrub": (0.18, 0.30, 0.34, 0.32, 0.22, 0.34, 0.30),
            "forb": (0.12, 0.22, 0.30, 0.42, 0.20, 0.24, 0.24),
            "graminoid": (0.08, 0.16, 0.18, 0.62, 0.14, 0.18, 0.34),
            "fern": (0.36, 0.32, 0.48, 0.30, 0.34, 0.42, 0.40),
            "moss": (0.02, 0.12, 0.18, 0.26, 0.18, 0.12, 0.55),
            "succulent": (0.10, 0.18, 0.25, 0.48, 0.12, 0.16, 0.28),
            "aquatic": (0.06, 0.18, 0.65, 0.34, 0.18, 0.18, 0.46),
        }.get(form, (0.35, 0.35, 0.45, 0.45, 0.25, 0.35, 0.35))
        architecture_defaults = species_architecture_defaults(species_id, form, architecture_defaults)
        branch_droop = normalised_plant_trait(entity.get("plant_branch_droop"), architecture_defaults[0])
        branch_angle_gradient = normalised_plant_trait(entity.get("plant_branch_angle_gradient"), architecture_defaults[1])
        crown_openness = normalised_plant_trait(entity.get("plant_crown_openness"), architecture_defaults[2])
        leaf_spacing_bias = normalised_plant_trait(entity.get("plant_leaf_spacing_bias"), architecture_defaults[3])
        leaf_depth_gradient = normalised_plant_trait(entity.get("plant_leaf_depth_gradient"), architecture_defaults[4])
        fine_twig_density = normalised_plant_trait(entity.get("plant_fine_twig_density"), architecture_defaults[5])
        leaf_cluster_density = normalised_plant_trait(entity.get("plant_leaf_cluster_density"), architecture_defaults[6])
        apical_control = normalised_plant_trait(
            entity.get("plant_apical_control"),
            0.72 if shape == "tree" else 0.52,
        )
        # Neutral default 0.0 regardless of form/species (unlike the other
        # architecture coefficients above) so a species that hasn't authored
        # this renders through crown_shape's shared envelope completely
        # unchanged -- only an explicit authored value narrows the crown.
        crown_taper = normalised_plant_trait(entity.get("plant_crown_taper"), 0.0)
        # Same neutral-0.0-default convention as crown_taper: unauthored
        # species get the existing fixed height-fraction trunk radius
        # completely unchanged.
        trunk_girth = normalised_plant_trait(entity.get("plant_trunk_girth"), 0.0)
        trunk_straightness = normalised_plant_trait(entity.get("plant_trunk_straightness"), 0.0)
        from simulations.species.leaf_development import authored_leaf_attachment_angle
        leaf_attachment_angle = authored_leaf_attachment_angle(entity.get("plant_leaf_attachment_angle"))
        from simulations.species.lateral_shoots import (
            LATERAL_SHOOT_FIELDS, LATERAL_SHOOT_VERSION,
            authored_shoot_control, supports_lateral_shoot_controls,
        )
        lateral_controls = {field: authored_shoot_control(entity.get(field))
                            if supports_lateral_shoot_controls(entity) else None
                            for field in LATERAL_SHOOT_FIELDS}
        primary_controls_supported = is_tree and bool(
            entity.get("plant_leaf_distribution") or entity.get("leaf_attachment_pattern") == "along_stem")
        primary_branch_density = (authored_shoot_control(entity.get("plant_primary_branch_density"))
                                  if primary_controls_supported else None)
        primary_branch_length = (authored_shoot_control(entity.get("plant_primary_branch_length"))
                                 if primary_controls_supported else None)
        from simulations.species.bloom_cohorts import supports_bloom_cohorts
        bloom_density = (authored_shoot_control(entity.get("plant_bloom_density"))
                         if supports_bloom_cohorts(entity) else None)
        # ``fascicled`` selects the shared-socket grammar; the explicit count
        # carries the biology.  This is deliberately independent of canopy
        # density so two-, three-, and five-needle pines can reuse the same
        # mechanism without species-specific code.
        raw_fascicle_size = entity.get("leaf_fascicle_size")
        try:
            raw_fascicle_size = int(round(float(raw_fascicle_size)))
        except (TypeError, ValueError):
            raw_fascicle_size = 3
        fascicle_size = max(1, min(12, raw_fascicle_size)) if leaf_arrangement == "fascicled" else 0
        if fascicle_size:
            leaves_per_node = fascicle_size
        architecture_ranges = {
            field_name.removeprefix("plant_"): normalised_plant_trait_range(
                entity.get(field_name),
                {
                    "plant_branch_droop": branch_droop,
                    "plant_branch_angle_gradient": branch_angle_gradient,
                    "plant_crown_openness": crown_openness,
                    "plant_leaf_spacing_bias": leaf_spacing_bias,
                    "plant_leaf_attachment_angle": leaf_attachment_angle,
                    **lateral_controls,
                    "plant_leaf_depth_gradient": leaf_depth_gradient,
                    "plant_fine_twig_density": fine_twig_density,
                    "plant_leaf_cluster_density": leaf_cluster_density,
                    "plant_apical_control": apical_control,
                    "plant_crown_taper": crown_taper,
                    "plant_trunk_girth": trunk_girth,
                    "plant_trunk_straightness": trunk_straightness,
                    "plant_primary_branch_density": primary_branch_density,
                    "plant_primary_branch_length": primary_branch_length,
                    "plant_bloom_density": bloom_density,
                }[field_name],
            )
            for field_name in PLANT_ARCHITECTURE_RANGE_FIELDS
            if field_name != "plant_trunk_straightness" or entity.get(field_name) not in (None, "", {}, [])
            if field_name != "plant_leaf_attachment_angle" or leaf_attachment_angle is not None
            if field_name not in lateral_controls or lateral_controls[field_name] is not None
            if field_name != "plant_primary_branch_density" or primary_branch_density is not None
            if field_name != "plant_primary_branch_length" or primary_branch_length is not None
            if field_name != "plant_bloom_density" or bloom_density is not None
        }

        def architecture_category(field_name):
            return str(entity.get(field_name) or "other_unknown").lower().replace("-", "_").replace(" ", "_")

        belowground_storage = entity.get("belowground_storage") or []
        if isinstance(belowground_storage, str):
            belowground_storage = [belowground_storage]
        else:
            belowground_storage = list(belowground_storage)

        growth = {
            "clonal_spread": entity.get("clonal_spread") or "other_unknown",
            "resprouting": entity.get("resprouting") or "other_unknown",
            "regeneration_strategy": entity.get("regeneration_strategy") or "other_unknown",
            "shade_tolerance": entity.get("shade_tolerance", "other_unknown"),
            "plant_life_form": str(entity.get("plant_life_form") or "other_unknown")
            .lower().replace("-", "_").replace(" ", "_"),
            "belowground_storage": belowground_storage,
            "shape": shape,
            "growth_form": form,
            "growth_behaviour": behaviour,
            "maturity_days": maturity_days,
            "max_height_m": max_height,
            "internode_length_m": internode,
            "branch_probability": branch_probability,
            "branch_angle_deg": 28.0 if shape != "rosette" else 0.0,
            "phyllotaxis_deg": phyllotaxis,
            "leaves_per_node": leaves_per_node,
            "leaf_arrangement": leaf_arrangement,
            "apical_dominance": apical_control,
            "apical_control": apical_control,
            "architecture_ranges": architecture_ranges,
            "growth_rate_bias": growth_rate_bias,
            "initial_cover_bias": 0.35,
            # These are resolved copies of existing ontology fields. They let
            # growth grammars use the functional schema without inventing a
            # species-specific data model.
            "plant_woodiness": str(entity.get("plant_woodiness") or ""),
            "leaf_phenology": str(entity.get("leaf_phenology") or ""),
            "leaf_size_class": leaf_size,
            "leaf_structure": leaf_structure,
            "leaf_division_order": leaf_division_order,
            "leaf_length_m": leaf_length,
            "leaf_cluster_size": leaf_cluster_size,
            "leaflet_count": leaflet_count,
            "leaflet_length_m": leaflet_length,
            "leaflet_width_m": leaflet_width,
            "frond_stipe_fraction": frond_stipe_fraction,
            "leaf_attachment_pattern": str(entity.get("leaf_attachment_pattern") or ""),
            "leaf_clustering": str(entity.get("leaf_clustering") or ""),
            "shoot_dimorphism": shoot_dimorphism,
            "leaf_distribution": leaf_distribution,
            "shoot_distribution_grammar": 1 if is_tree and (entity.get("plant_leaf_distribution") or entity.get("leaf_attachment_pattern") == "along_stem") else 0,
            "axis_continuity": architecture_category("plant_axis_continuity"),
            "self_pruning": architecture_category("plant_self_pruning"),
            "crown_shape": architecture_category("plant_crown_shape"),
            "crown_taper": crown_taper,
            "trunk_girth": trunk_girth,
            "branching_rhythm": architecture_category("plant_branching_rhythm"),
            "branching_timing": architecture_category("plant_branching_timing"),
            "lateral_axis_orientation": architecture_category("plant_lateral_axis_orientation"),
            "flowering_position": architecture_category("plant_flowering_position"),
            "reproductive_structure": architecture_category("plant_reproductive_structure"),
            "leaf_spacing_bias": leaf_spacing_bias,
            "branch_droop": branch_droop,
            "branch_angle_gradient": branch_angle_gradient,
            "crown_openness": crown_openness,
            "leaf_depth_gradient": leaf_depth_gradient,
            "fine_twig_density": fine_twig_density,
            "leaf_cluster_density": leaf_cluster_density,
            "fascicle_size": fascicle_size,
            "fascicle_grammar_version": 1,
            "reproductive_mode": str(entity.get("reproductive_mode") or ""),
            "root_architecture": str(entity.get("root_architecture") or ""),
            "root_depth_class": str(entity.get("root_depth_class") or ""),
            "max_root_depth": entity.get("max_root_depth"),
            "nitrogen_fixation": str(entity.get("nitrogen_fixation") or "other_unknown"),
            "nutrition_mode": str(entity.get("nutrition_mode") or "other_unknown"),
            "mycorrhizal_type": str(entity.get("mycorrhizal_type") or "other_unknown"),
            "longevity_class": str(entity.get("longevity_class") or ""),
            "life_history": life_history,
        }
        from simulations.species.leaf_palette import leaf_palette
        authored_leaf_palette = leaf_palette(entity.get("plant_leaf_palette"))
        if authored_leaf_palette:
            growth["leaf_palette"] = authored_leaf_palette
        if scaled_tree_leaf_default:
            growth["leaf_length_source"] = "runtime_tree_height_default"
        from simulations.species.seasonal_rhizomes import seasonal_rhizome_profile
        seasonal_rhizome = seasonal_rhizome_profile(entity.get('plant_shoot_profile'))
        if (seasonal_rhizome and form == 'forb' and behaviour == 'rhizomatous_clonal'
                and growth['plant_woodiness'] == 'herbaceous'):
            growth['seasonal_rhizome_profile'] = seasonal_rhizome
            growth['seasonal_rhizome_version'] = seasonal_rhizome['version']
        from simulations.species.creeping_uprights import creeping_upright_profile
        upright = creeping_upright_profile(entity.get('plant_shoot_profile'))
        if upright and behaviour in {'stoloniferous_clonal', 'rhizomatous_clonal', 'creeping_prostrate'}:
            growth['creeping_upright_profile'] = upright
            growth['creeping_upright_version'] = upright['version']
        from simulations.species.terminal_rosettes import terminal_rosette_profile
        from simulations.species.offset_rosettes import offset_rosette_profile
        offsets=offset_rosette_profile(entity.get('plant_shoot_profile'))
        if offsets and form=='succulent' and behaviour=='basal_succulent_rosette':
            growth['offset_rosette_profile']=offsets
            growth['offset_rosette_version']=offsets['version']
        terminal = terminal_rosette_profile(entity.get("plant_shoot_profile"))
        if terminal and form in {"tree", "shrub", "succulent", "other_unknown"}:
            growth["terminal_rosette_profile"] = terminal
            growth["terminal_rosette_version"] = terminal["version"]
        if is_tree:
            growth["tree_leader_foliage_version"] = 1
            subpattern = architecture_category("plant_branching_subpattern")
            if subpattern == 'planar_foliage_sprays':
                from simulations.species.planar_sprays import planar_spray_profile
                spray = planar_spray_profile(entity.get('plant_shoot_profile'))
                if spray and leaf_structure in {'needle_like','scale_like'}:
                    growth['branching_subpattern'] = subpattern
                    growth['branching_subpattern_version'] = spray['version']
                    growth['planar_spray_version'] = spray['version']
                    growth['planar_spray_profile'] = spray
            if subpattern in {"decurrent_scaffold", "tiered_conifer", "pendant_branchlets"}:
                growth["branching_subpattern"] = subpattern
                growth["branching_subpattern_version"] = 1
                if subpattern == 'tiered_conifer' and primary_branch_density is not None and primary_branch_density > 0:
                    growth['branching_subpattern_version'] = 2
                if subpattern == 'pendant_branchlets':
                    from simulations.species.pendant_branchlets import PENDANT_BRANCHLET_VERSION
                    growth['pendant_branchlet_version'] = PENDANT_BRANCHLET_VERSION
            from simulations.species.woody_axes import woody_axes_profile
            axes = woody_axes_profile(entity.get("plant_shoot_profile"))
            if axes:
                growth["woody_axes_profile"] = axes
                growth["woody_axes_version"] = axes["version"]
            if (growth["branching_rhythm"] == "rhythmic"
                    and growth["crown_shape"] == "conical"
                    and growth["shoot_distribution_grammar"]):
                growth["young_conical_crown_version"] = 1
        if form == "graminoid" and growth["plant_woodiness"] == "woody":
            from simulations.species.woody_graminoid_shoots import GRAMMAR_VERSION
            growth["woody_graminoid_grammar_version"] = GRAMMAR_VERSION
        if (form == "graminoid" and growth["plant_woodiness"] != "woody"
                and growth["leaf_attachment_pattern"] not in {"basal", "basal_tuft"}):
            growth["graminoid_leaf_angle_grammar_version"] = 1
        if (form == "forb" and growth["plant_woodiness"] == "herbaceous"
                and behaviour in {"suckering_clonal", "rhizomatous_clonal", "stoloniferous_clonal"}
                and growth["leaf_attachment_pattern"] == "along_stem"):
            growth["clonal_forb_shoot_grammar_version"] = 1
            growth["forb_leaf_placement_version"] = 1
            from simulations.species.clonal_forb_profiles import clonal_forb_profile
            shoot_profile = clonal_forb_profile(entity.get("plant_shoot_profile"))
            if shoot_profile:
                growth["clonal_forb_profile"] = shoot_profile
                growth["clonal_forb_profile_version"] = shoot_profile["version"]
            from simulations.species.leaf_development import LEAF_DEVELOPMENT_VERSION
            growth["forb_leaf_development_version"] = LEAF_DEVELOPMENT_VERSION
            leaf_upper = (entity.get("leaf_length") or {}).get("max_m") if isinstance(entity.get("leaf_length"), dict) else None
            upper_scale = 1.45
            if isinstance(leaf_upper, (int, float)) and not isinstance(leaf_upper, bool) and math.isfinite(leaf_upper) and leaf_upper > 0:
                upper_scale = leaf_upper / max(.002, leaf_length)
            growth["forb_leaf_length_upper_scale"] = max(.1, min(1.55, upper_scale))
        if upper_bound_frond:
            growth["leaf_length_source"] = "runtime_upper_bound_illustration_fraction"
            growth["leaf_length_upper_bound_fraction"] = .65
        if "trunk_straightness" in architecture_ranges:
            growth["trunk_straightness"] = trunk_straightness
        if primary_branch_density is not None:
            growth["primary_branch_density"] = primary_branch_density
        if primary_branch_length is not None:
            growth["primary_branch_length"] = primary_branch_length
        if bloom_density is not None:
            growth["bloom_density"] = bloom_density
        if leaf_attachment_angle is not None:
            growth["leaf_attachment_angle"] = leaf_attachment_angle
            growth["leaf_attachment_angle_version"] = 1
            if (behaviour == "rhizomatous_clonal" and leaf_distribution == "terminal_cluster"
                    and leaf_structure == "pinnately_compound"):
                from simulations.species.pinnate_crowns import PINNATE_CROWN_VERSION
                growth["pinnate_crown_version"] = PINNATE_CROWN_VERSION
        for field, value in lateral_controls.items():
            if value is not None:
                growth[field.removeprefix("plant_")] = value
                growth["lateral_shoot_geometry_version"] = LATERAL_SHOOT_VERSION
        if entity.get("frond_pinna_arrangement"):
            growth["frond_pinna_arrangement"] = str(entity["frond_pinna_arrangement"])
        if form == "fern" and behaviour == "fern_fronding":
            from simulations.species.fern_fronds import FERN_FROND_GRAMMAR_VERSION
            growth["fern_frond_grammar_version"] = FERN_FROND_GRAMMAR_VERSION
        if shape == "aquatic":
            from simulations.species.floating_leaves import AQUATIC_ROSETTE_VERSION
            from simulations.species.emergent_rosettes import emergent_rosette_profile
            emergent = emergent_rosette_profile(entity.get("plant_shoot_profile"))
            if emergent:
                growth["emergent_rosette_profile"] = emergent
                growth["emergent_rosette_version"] = emergent["version"]
            else:
                growth["aquatic_rosette_version"] = AQUATIC_ROSETTE_VERSION
        if behaviour == "surface_covering":
            from simulations.species.surface_growth import normalise_surface_profile, SURFACE_GRAMMAR_VERSION
            growth["surface_growth_profile"] = normalise_surface_profile(entity.get("surface_growth_profile"))
            # Carry authored population mass into the portable surface recipe.
            # Keep existing surface bodies' small area proxy when absent.
            biosphere = entity.get('biosphere_growth_profile')
            if isinstance(biosphere, dict):
                from simulations.species.surface_atmosphere import finite_number
                density = finite_number(biosphere.get('carrying_biomass_kg_m2'))
                if density is not None and density >= 0:
                    growth['surface_biomass_kg_m2'] = min(20., density)
            growth["max_height_m"] = (growth["surface_growth_profile"]["tuft_height_m"]
                                      if growth["surface_growth_profile"]["thallus_form"] == "fruticose"
                                      else growth["surface_growth_profile"]["thickness_m"])
            growth["surface_grammar_version"] = SURFACE_GRAMMAR_VERSION
            growth["shape"] = "lichen" if form == "lichen" else "moss"
        from simulations.species.columnar_succulents import columnar_profile
        columnar = columnar_profile(entity.get('plant_shoot_profile'))
        if form == 'succulent' and behaviour == 'columnar_succulent' and columnar:
            growth['columnar_profile'] = columnar
            growth['columnar_version'] = columnar['version']
            leaf_length = columnar['spine_size_m']
            growth['leaf_length_m'] = leaf_length
            height_data=entity.get('mature_height')
            typical=height_data.get('typical_m') if isinstance(height_data,dict) else None
            if (isinstance(typical,(int,float)) and not isinstance(typical,bool)
                    and math.isfinite(typical) and .01 <= typical <= 100.):
                growth['max_height_m'] = float(typical)
                growth['columnar_height_source'] = 'authored_typical_height'
        elif form == 'succulent' and behaviour == 'columnar_succulent':
            growth['columnar_model_status'] = 'unresolved_missing_shoot_profile'
        from simulations.species.root_growth import shallow_radial_profile
        radial = shallow_radial_profile(entity.get('plant_root_profile'))
        if radial and growth.get('root_architecture') == 'mixed':
            growth['shallow_radial_profile'] = radial
        growth["root_profile"] = root_profile(growth)
        from simulations.species.basal_fan_shoots import basal_fan_profile
        fan_profile = basal_fan_profile(entity.get("plant_shoot_profile"))
        if (fan_profile and form == "forb" and behaviour == "determinate_sympodial"
                and growth["plant_woodiness"] == "herbaceous"
                and growth["leaf_attachment_pattern"] == "mixed"):
            growth["basal_fan_profile"] = fan_profile
            leaf_length = fan_profile["basal_leaf_length_m"]
            growth["leaf_length_m"] = leaf_length
            growth["basal_fan_leaf_length_m"] = leaf_length
        if (form == "forb" and behaviour == "rosette_short_internode"
                and growth["leaf_attachment_pattern"] == "mixed"):
            from simulations.species.rosette_shoots import ROSETTE_SHOOT_GRAMMAR_VERSION, rosette_shoot_profile
            growth["rosette_shoot_grammar_version"] = ROSETTE_SHOOT_GRAMMAR_VERSION
            rosette_profile = rosette_shoot_profile(entity.get("plant_shoot_profile"))
            if rosette_profile is not None:
                growth["rosette_shoot_profile"] = rosette_profile
        if (form == 'forb' and behaviour == 'determinate_sympodial'
                and growth['plant_woodiness'] == 'herbaceous'
                and growth['leaf_attachment_pattern'] in {'along_stem', 'mixed'}):
            from simulations.species.sympodial_herbs import sympodial_herb_profile
            from simulations.species.flower_terminated_forks import fork_profile
            fork=fork_profile(entity.get('plant_shoot_profile'))
            if (fork and entity.get('plant_branching_subpattern')=='flower_terminated_forks'
                    and growth['reproductive_structure']=='flower' and growth['flowering_position']=='terminal'):
                growth['flower_fork_profile']=fork
                growth['flower_fork_version']=fork['version']
                growth['branching_subpattern']='flower_terminated_forks'
                growth['forb_leaf_placement_version']=1
            herb_profile = sympodial_herb_profile(entity.get('plant_shoot_profile'))
            if herb_profile:
                growth['sympodial_herb_profile'] = herb_profile
                growth['sympodial_herb_version'] = herb_profile['version']
                growth['forb_leaf_placement_version'] = 1
            if growth['reproductive_structure']=='flower' and growth['flowering_position']=='terminal':
                from simulations.species.cyme_herbs import cyme_herb_profile
                cyme_profile=cyme_herb_profile(entity.get('plant_shoot_profile'))
                if cyme_profile:
                    growth['cyme_herb_profile']=cyme_profile
                    growth['cyme_herb_version']=cyme_profile['version']
                    growth['forb_leaf_placement_version']=1
        from simulations.species.plant_reproduction import reproductive_profile
        if (form=='forb' and behaviour=='rosette_short_internode'
                and canonical_plant_growth_behaviour(entity.get('plant_growth_behaviour'))=='rosette_short_internode'
                and growth['plant_woodiness']=='herbaceous'
                and growth['leaf_attachment_pattern']=='basal_rosette'
                and growth['reproductive_structure']=='panicle'):
            from simulations.species.paniculate_rosettes import paniculate_rosette_profile
            pan_rosette=paniculate_rosette_profile(entity.get('plant_shoot_profile'))
            if pan_rosette:
                growth['paniculate_rosette_profile']=pan_rosette
                growth['paniculate_rosette_version']=pan_rosette['version']
                growth['forb_leaf_placement_version']=1
                # The basal attachment shortcut above resets legacy rosettes
                # to 45 cm. This explicit metric recipe retains authored
                # stature and the root fallback derived from that stature.
                if mature_height is not None:
                    growth['max_height_m']=max(.1,mature_height)
                    growth['root_profile']=root_profile(growth)
        if (form=='graminoid' and behaviour=='tussock_tillering'
                and growth['plant_woodiness']=='herbaceous'
                and growth['leaf_attachment_pattern'] in {'basal','basal_tuft'}
                and growth['reproductive_structure']=='spike'):
            from simulations.species.mixed_tillers import mixed_tiller_profile
            mixed=mixed_tiller_profile(entity.get('plant_shoot_profile'))
            if mixed:
                growth['mixed_tiller_profile']=mixed
                growth['mixed_tiller_version']=mixed['version']
        if (form == 'graminoid' and behaviour == 'tussock_tillering'
                and growth['plant_woodiness'] == 'herbaceous'
                and growth['leaf_attachment_pattern'] == 'basal_tuft'
                and growth['reproductive_structure'] == 'digitate_spike_cluster'):
            from simulations.species.tufted_sedges import tufted_sedge_profile
            sedge_profile = tufted_sedge_profile(entity.get('plant_shoot_profile'))
            if sedge_profile:
                growth['tufted_sedge_profile'] = sedge_profile
                growth['tufted_sedge_version'] = sedge_profile['version']
        seasonal_profile = reproductive_profile(entity.get("plant_reproductive_profile"))
        if seasonal_profile is not None:
            growth["reproductive_profile"] = seasonal_profile
            if (is_tree and growth.get("shoot_distribution_grammar")
                    and growth.get("leaf_phenology") in {"deciduous", "drought_deciduous"}
                    and "leaf_out_start" in seasonal_profile):
                growth["tree_leaf_season_version"] = 1
            if is_climber and growth.get("leaf_attachment_pattern") == "along_stem":
                growth["vine_organ_geometry_version"] = 1
                if growth['plant_woodiness']=='woody':
                    from simulations.species.vine_organs import branched_vine_profile
                    vine_shoots=branched_vine_profile(entity.get('plant_shoot_profile'))
                    if vine_shoots:
                        growth['branched_vine_profile']=vine_shoots
                        growth['branched_vine_version']=vine_shoots['version']
        from simulations.species.inflorescences import inflorescence_profile
        cluster_profile = inflorescence_profile(entity.get("plant_inflorescence_profile"))
        expected_cluster = {"compound_umbel": "compound_umbel", "capitulum_cluster": "capitulum", "raceme": "flower", "umbellate_head": "flower"}.get(
            (cluster_profile or {}).get("form"), "panicle")
        if cluster_profile is not None and growth.get("reproductive_structure") == expected_cluster:
            growth["inflorescence_profile"] = cluster_profile
            if cluster_profile.get("form") == "umbellate_head":
                growth["umbellate_head_version"] = cluster_profile["version"]
        if (form == "forb" and behaviour == "rosette_short_internode"
                and growth["plant_woodiness"] == "herbaceous"
                and growth["leaf_attachment_pattern"] == "basal_rosette"
                and (growth.get("inflorescence_profile") or {}).get("form") == "raceme"):
            from simulations.species.rosette_racemes import rosette_raceme_profile
            rosette_raceme = rosette_raceme_profile(entity.get("plant_shoot_profile"))
            if rosette_raceme:
                growth["rosette_raceme_profile"] = rosette_raceme
                growth["rosette_raceme_version"] = rosette_raceme["version"]
        if (form == "forb" and behaviour == "rosette_short_internode"
                and growth["plant_woodiness"] == "herbaceous"
                and growth["leaf_attachment_pattern"] == "basal_rosette"
                and growth["flowering_position"] == "terminal"
                and growth["reproductive_structure"] == "capitulum"):
            from simulations.species.scape_rosettes import scape_rosette_profile
            scape = scape_rosette_profile(entity.get("plant_shoot_profile"))
            if scape:
                growth["scape_rosette_profile"] = scape
                growth["scape_rosette_version"] = scape["version"]
        if (form == "forb" and behaviour == "rosette_short_internode"
                and growth["plant_woodiness"] == "herbaceous"
                and growth["leaf_attachment_pattern"] == "basal_rosette"
                and growth["flowering_position"] == "lateral"
                and growth["reproductive_structure"] == "flower"):
            growth["lateral_rosette_scapes_version"] = 1
        if (form == "forb" and growth["plant_woodiness"] == "herbaceous"
                and behaviour == "unbranched_single_axis"
                and shoot_dimorphism == "long_and_short_shoots"
                and leaf_distribution == "mixed_long_short_shoots"):
            from simulations.species.dimorphic_herbs import dimorphic_herb_profile
            dimorphic_profile = dimorphic_herb_profile(entity.get("plant_shoot_profile"))
            if dimorphic_profile:
                growth["dimorphic_herb_profile"] = dimorphic_profile
                growth["dimorphic_herb_profile_version"] = dimorphic_profile["version"]
                growth["structural_raceme_version"] = 1
                growth["forb_leaf_placement_version"] = 1
        if (growth.get("clonal_forb_shoot_grammar_version") and seasonal_profile
                and growth["reproductive_structure"] == "capitulum"
                and growth["flowering_position"] == "terminal"):
            growth["clonal_forb_reproduction_version"] = 1
            if "leaf_out_start" in seasonal_profile:
                growth["clonal_forb_leaf_season_version"] = 1
        if (form == 'subshrub' and behaviour == 'branched_woody'
                and growth['plant_woodiness'] == 'woody'
                and growth['leaf_structure'] == 'pinnately_compound'):
            from simulations.species.cushion_subshrubs import cushion_profile
            cushion = cushion_profile(entity.get('plant_shoot_profile'))
            if cushion:
                growth['cushion_profile'] = cushion
                growth['cushion_version'] = cushion['version']
                growth['cushion_height_m'] = quantitative_plant_trait(
                    entity.get('mature_height'), max_height, .01, max_height)
        if (form == "subshrub" and behaviour == "iterative_indeterminate"
                and lifespan in {"annual", "short_lived_perennial"}
                and growth["leaf_attachment_pattern"] == "along_stem"
                and growth["leaf_distribution"] == "along_shoot"
                and growth["reproductive_structure"] == "capitulum"
                and growth["flowering_position"] == "terminal"):
            growth["short_lived_subshrub_shoot_version"] = 1
            growth["forb_leaf_placement_version"] = 1
        if (form == "forb" and behaviour == "iterative_indeterminate"
                and growth["plant_woodiness"] == "herbaceous"
                and growth["leaf_distribution"] == "along_shoot"):
            from simulations.species.basal_herbs import basal_herb_profile
            herb = basal_herb_profile(entity.get("plant_shoot_profile"))
            if herb:
                growth["basal_herb_profile"] = herb
                growth["basal_herb_version"] = herb["version"]
                if "upper_leaf_arrangement" in herb:
                    growth["leaf_arrangement_transition_version"] = 1
                growth["basal_herb_height_m"] = quantitative_plant_trait(
                    entity.get("mature_height"), max_height, .1, max_height)
                growth["forb_leaf_placement_version"] = 1
        if (form == "subshrub" and behaviour == "iterative_indeterminate"
                and growth["plant_woodiness"] == "woody"
                and growth["leaf_distribution"] == "along_shoot"):
            from simulations.species.basal_subshrubs import basal_subshrub_profile
            basal = basal_subshrub_profile(entity.get("plant_shoot_profile"))
            if basal:
                growth["basal_subshrub_profile"] = basal
                growth["basal_subshrub_version"] = basal["version"]
                growth["basal_subshrub_height_m"] = quantitative_plant_trait(
                    entity.get("mature_height"), max_height, .1, max_height)
                growth["forb_leaf_placement_version"] = 1
        if (form == "forb" and growth["plant_woodiness"] == "herbaceous"
                and behaviour == "iterative_indeterminate"
                and growth["reproductive_structure"] == "compound_umbel"
                and growth["leaf_attachment_pattern"] == "along_stem"):
            growth["umbellifer_forb_grammar_version"] = 1
            growth["forb_leaf_placement_version"] = 1
            from simulations.species.leaf_development import LEAF_DEVELOPMENT_VERSION
            growth["forb_leaf_development_version"] = LEAF_DEVELOPMENT_VERSION
            growth["forb_leaf_length_upper_scale"] = 1.25
        if (form == "forb" and growth["plant_woodiness"] == "herbaceous"
                and behaviour == "iterative_indeterminate"
                and not growth.get("umbellifer_forb_grammar_version")):
            growth["iterative_forb_cohort_version"] = 1
        if growth.get("growth_behaviour") == "creeping_prostrate":
            growth["creeping_grammar_version"] = 2
            if is_shrub and growth["plant_woodiness"] == "woody":
                from simulations.species.creeping_woody import creeping_woody_profile
                woody_profile = creeping_woody_profile(entity.get("plant_shoot_profile"))
                if woody_profile:
                    growth["creeping_woody_profile"] = woody_profile
                    growth["creeping_woody_profile_version"] = woody_profile["version"]
                    growth["creeping_woody_height_m"] = quantitative_plant_trait(
                        entity.get("mature_height"), max_height, .02, min(1., max_height))
            if form == "forb" and growth["plant_woodiness"] == "herbaceous":
                from simulations.species.creeping_herbs import creeping_herb_profile
                creeping_profile = creeping_herb_profile(entity.get("plant_shoot_profile"))
                if creeping_profile:
                    if leaf_arrangement == "distichous":
                        creeping_profile["version"] = max(3, creeping_profile["version"])
                    growth["creeping_herb_profile"] = creeping_profile
                    growth["creeping_herb_profile_version"] = creeping_profile["version"]
                    growth["forb_leaf_placement_version"] = 1
        if (is_shrub and behaviour == "branched_woody"
                and growth["crown_shape"] in {"irregular", "spreading", "ovoid"}
                and growth["lateral_axis_orientation"] in {"orthotropic", "plagiotropic", "mixed", "pendent"}):
            growth["shrub_cane_grammar_version"] = 1
            growth["shrub_height_m"] = quantitative_plant_trait(
                entity.get("mature_height"), max_height, 0.1, max_height)
            growth["shrub_height_source"] = "authored_typical_or_range_midpoint"
            if leaf_arrangement == "fascicled":
                growth["shrub_fascicle_grammar_version"] = 1
            if growth["crown_shape"] == "spreading":
                growth["shrub_crown_envelope_version"] = 1
        if (growth.get("shrub_cane_grammar_version")
                and form in {"shrub", "subshrub"}
                and growth["plant_woodiness"] == "woody"
                and growth["shoot_dimorphism"] == "long_and_short_shoots"
                and growth["flowering_position"] in {"lateral", "mixed"}):
            from simulations.species.woody_spurs import woody_spur_profile
            spurs = woody_spur_profile(entity.get("plant_shoot_profile"))
            if spurs:
                growth["woody_spur_profile"] = spurs
                growth["woody_spur_version"] = 1
        from simulations.species.renewing_canes import renewing_cane_profile
        renewing = renewing_cane_profile(entity.get('plant_shoot_profile'))
        if (renewing and growth.get('shrub_cane_grammar_version')
                and growth['plant_woodiness'] == 'woody'):
            growth['renewing_cane_profile'] = renewing
            growth['renewing_cane_version'] = renewing['version']
        if form == 'moss' and behaviour == 'moss_mat':
            from simulations.species.moss_turfs import moss_turf_profile
            moss_profile = moss_turf_profile(entity.get('plant_shoot_profile'))
            if moss_profile:
                growth['moss_turf_profile'] = moss_profile
                growth['moss_turf_version'] = moss_profile['version']
                growth['max_height_m'] = moss_profile['shoot_length_m']
        from simulations.species.root_visuals import root_visual_profile
        growth["root_visual_profile"] = root_visual_profile(growth)
        flower_asset_ref = str(entity.get("plant_flower_module_ref") or "") or None
        fruit_asset_ref = str(entity.get("plant_fruit_module_ref") or "") or None
        flower_depicted_size = depicted_size(flower_anchor, flower_asset_ref)
        fruit_depicted_size = depicted_size(fruit_anchor, fruit_asset_ref)
        if seasonal_profile:
            flower_depicted_size = flower_depicted_size or seasonal_profile["flower_size_m"]
            fruit_depicted_size = fruit_depicted_size or seasonal_profile["fruit_size_m"]
        if growth.get("basal_fan_profile"):
            flower_depicted_size = flower_depicted_size or fan_profile["flower_size_m"]
            fruit_depicted_size = fruit_depicted_size or fan_profile["fruit_size_m"]
        modules = [
            # Life-form modules are present in the portable recipe but are
            # instantiated only when the corresponding growth grammar needs
            # them.  A renewal organ is deliberately not called a bulb/corm:
            # plant_life_form locates the bud, while belowground_storage names
            # the organ when that independent field has been authored.
            PlantModule("renewal_organ", "renewal_organ", length_m=0.015, radius_m=0.0075,
                        sockets=("base", "renewal_bud")),
            PlantModule("renewal_bud", "renewal_bud", length_m=0.008, radius_m=0.003,
                        sockets=("base", "shoot")),
            PlantModule("root_support", "stem_section", length_m=0.1, radius_m=0.02),
            PlantModule("root_section", "root_section", length_m=0.1, radius_m=0.01,
                        asset_ref=str(entity.get("plant_root_module_ref") or "") or None),
            PlantModule(
                "root", "root",
                asset_ref=str(entity.get("plant_root_module_ref") or "") or None,
                length_m=0.16, radius_m=0.05, sockets=("tip",),
            ),
            PlantModule(
                "stem_section", "stem_section", length_m=internode,
                radius_m=(growth["emergent_rosette_profile"]["petiole_radius_m"] if growth.get("emergent_rosette_profile")
                          else growth["dimorphic_herb_profile"]["stem_radius_m"] if growth.get("dimorphic_herb_profile")
                          else growth["creeping_woody_profile"]["stem_radius_m"] if growth.get("creeping_woody_profile")
                          else growth["creeping_herb_profile"]["stem_radius_m"] if growth.get("creeping_herb_profile")
                          else growth["clonal_forb_profile"]["stem_radius_m"] if growth.get("clonal_forb_profile")
                          else growth['scape_rosette_profile']['scape_radius_m'] if growth.get('scape_rosette_version')
                          else 0.0015 if growth.get('lateral_rosette_scapes_version')
                          else growth['paniculate_rosette_profile']['stem_radius_m'] if growth.get('paniculate_rosette_version')
                          else growth['flower_fork_profile']['stem_radius_m'] if growth.get('flower_fork_version')
                          else growth['sympodial_herb_profile']['stem_radius_m'] if growth.get('sympodial_herb_version')
                          else fan_profile["stem_radius_m"] if growth.get("basal_fan_profile") else 0.035),
                asset_ref=str(entity.get("plant_stem_module_ref") or "") or None,
                texture_set_ref=str(entity.get("plant_stem_texture_set_ref") or entity.get("plant_bark_texture_set_ref") or "") or None,
            ),
            PlantModule(
                "branch_section", "branch_section", length_m=internode * 0.8,
                radius_m=(growth["dimorphic_herb_profile"]["stem_radius_m"]*.65 if growth.get("dimorphic_herb_profile")
                          else growth["creeping_woody_profile"]["stem_radius_m"]*.65 if growth.get("creeping_woody_profile")
                          else growth["creeping_herb_profile"]["stem_radius_m"]*.65 if growth.get("creeping_herb_profile")
                          else growth["clonal_forb_profile"]["stem_radius_m"]*.65 if growth.get("clonal_forb_profile")
                          else growth['paniculate_rosette_profile']['stem_radius_m']*.65 if growth.get('paniculate_rosette_version')
                          else growth['flower_fork_profile']['stem_radius_m'] if growth.get('flower_fork_version')
                          else growth['sympodial_herb_profile']['stem_radius_m']*.65 if growth.get('sympodial_herb_version')
                          else fan_profile["stem_radius_m"]*.65 if growth.get("basal_fan_profile") else 0.022),
                asset_ref=str(entity.get("plant_branch_module_ref") or "") or None,
                texture_set_ref=str(entity.get("plant_branch_texture_set_ref") or entity.get("plant_bark_texture_set_ref") or "") or None,
            ),
            PlantModule(
                "leaf",
                "leaf",
                asset_ref=str(entity.get("plant_leaf_module_ref") or "") or None,
                length_m=leaf_length,
                radius_m=(
                    growth['offset_rosette_profile']['leaf_width_m']*.5 if growth.get('offset_rosette_version')
                    else
                    growth['terminal_rosette_profile']['leaf_width_m']*.5 if growth.get('terminal_rosette_version')
                    else growth['columnar_profile']['spine_size_m']*.5 if growth.get('columnar_version')
                    else growth["creeping_woody_profile"]["leaf_width_m"]*.5 if growth.get("creeping_woody_profile")
                    else 0.06 if form == "succulent"
                    else 0.001 if leaf_structure == "needle_like"
                    else 0.003 if leaf_structure == "scale_like"
                    else max(0.012, min(0.08, leaflet_width * 0.35)) if leaf_structure in {"pinnately_compound", "frond_like"}
                    else growth["dimorphic_herb_profile"]["leaf_width_m"]*.5 if growth.get("dimorphic_herb_profile")
                    else growth["clonal_forb_profile"]["leaf_width_m"]*.5 if growth.get("clonal_forb_profile", {}).get("leaf_width_m")
                    else growth["creeping_herb_profile"]["leaf_width_m"]*.5 if growth.get("creeping_herb_profile")
                    else growth['paniculate_rosette_profile']['leaf_width_m']*.5 if growth.get('paniculate_rosette_version')
                    else growth['flower_fork_profile']['leaf_width_m']*.5 if growth.get('flower_fork_version')
                    else growth['sympodial_herb_profile']['leaf_width_m']*.5 if growth.get('sympodial_herb_version')
                    else fan_profile["leaf_width_m"]*.5 if growth.get("basal_fan_profile") else 0.012
                ),
                sockets=("base",),
                attachment_point=_tuple2(leaf_anchor.get("attachment_point")),
                growth_axis=_tuple2(leaf_anchor.get("growth_vector") or leaf_anchor.get("growth_axis"), (0.0, -1.0)),
                visual={
                    "leaf_structure": leaf_structure,
                    **({'visual_unit':'spine_cluster','depicted_size_m':leaf_anchor.get('depicted_size_m')}
                       if growth.get('columnar_version') and leaf_anchor.get('visual_unit') == 'spine_cluster' else {}),
                    "leaf_arrangement": leaf_arrangement,
                    **({"frond_pinna_arrangement": growth["frond_pinna_arrangement"]}
                       if "frond_pinna_arrangement" in growth else {}),
                    **({"visual_unit": "pinnule", "depicted_size_m": leaf_anchor.get("depicted_size_m")}
                       if leaf_structure == "frond_like" and leaf_anchor.get("visual_unit") == "pinnule" else {}),
                    **({"visual_unit": "leaflet", "depicted_size_m": leaf_anchor.get("depicted_size_m")}
                       if growth.get("pinnate_crown_version") and leaf_anchor.get("visual_unit") == "leaflet" else {}),
                    "leaf_division_order": leaf_division_order,
                    "leaflet_count": leaflet_count,
                    "leaflet_length_m": leaflet_length,
                    "leaflet_width_m": leaflet_width,
                    "frond_stipe_fraction": frond_stipe_fraction,
                    # Whole-blade width and ultimate-segment dimensions are
                    # different hierarchical scales in a divided frond.
                    "frond_blade_width_m": (
                        leaf_length * (0.56 + 0.24 * crown_openness)
                        if leaf_structure == "frond_like" else 0.0
                    ),
                    "frond_arch": (
                        0.16
                        if leaf_structure in {"pinnately_compound", "frond_like"} and leaf_distribution == "terminal_cluster"
                        else 0.08
                        if leaf_structure == "frond_like" and behaviour == "fern_fronding"
                        else 0.0
                    ),
                },
            ),
            PlantModule(
                "flower",
                "flower",
                asset_ref=flower_asset_ref,
                length_m=(flower_depicted_size or 0.16) if (growth.get("shrub_cane_grammar_version") or growth.get("basal_fan_profile") or growth.get("aquatic_rosette_version") or growth.get("emergent_rosette_version") or growth.get("clonal_forb_reproduction_version") or growth.get("creeping_woody_profile_version") or growth.get("creeping_herb_profile_version") or growth.get("structural_raceme_version") or growth.get('sympodial_herb_version') or growth.get('flower_fork_version') or growth.get('paniculate_rosette_version') or growth.get('scape_rosette_version') or growth.get('lateral_rosette_scapes_version') or growth.get('columnar_version') or growth.get('terminal_rosette_version') or growth.get('offset_rosette_version')) else 0.16,
                radius_m=flower_depicted_size*.5 if (growth.get("basal_fan_profile") or growth.get("creeping_woody_profile_version") or growth.get("creeping_herb_profile_version") or growth.get("structural_raceme_version") or growth.get('sympodial_herb_version') or growth.get('flower_fork_version') or growth.get('paniculate_rosette_version') or growth.get('lateral_rosette_scapes_version') or growth.get('columnar_version') or growth.get('terminal_rosette_version') or growth.get('offset_rosette_version')) and flower_depicted_size else 0.018,
                sockets=("base",),
                attachment_point=_tuple2(flower_anchor.get("attachment_point")),
                growth_axis=_tuple2(flower_anchor.get("growth_vector") or flower_anchor.get("growth_axis"), (0.0, -1.0)),
                visual={"depicted_size_m": flower_depicted_size} if flower_depicted_size else {},
            ),
            PlantModule(
                "fruit", "fruit",
                asset_ref=fruit_asset_ref,
                length_m=(fruit_depicted_size or 0.1) if (growth.get("shrub_cane_grammar_version") or growth.get("basal_fan_profile") or growth.get("emergent_rosette_version") or growth.get("clonal_forb_reproduction_version") or growth.get("creeping_woody_profile_version") or growth.get("structural_raceme_version") or growth.get('sympodial_herb_version') or growth.get('flower_fork_version') or growth.get('paniculate_rosette_version') or growth.get('scape_rosette_version') or growth.get('lateral_rosette_scapes_version') or growth.get('columnar_version') or growth.get('terminal_rosette_version')) else 0.1,
                radius_m=fruit_depicted_size*.5 if (growth.get("basal_fan_profile") or growth.get("creeping_woody_profile_version") or growth.get("creeping_herb_profile_version") or growth.get("structural_raceme_version") or growth.get('sympodial_herb_version') or growth.get('flower_fork_version') or growth.get('paniculate_rosette_version') or growth.get('lateral_rosette_scapes_version') or growth.get('columnar_version') or growth.get('terminal_rosette_version')) and fruit_depicted_size else 0.025, sockets=("base",),
                attachment_point=_tuple2(fruit_anchor.get("attachment_point")),
                growth_axis=_tuple2(fruit_anchor.get("growth_vector") or fruit_anchor.get("growth_axis"), (0.0, -1.0)),
                visual={"depicted_size_m": fruit_depicted_size} if fruit_depicted_size else {},
            ),
        ]
        if growth.get("basal_subshrub_profile") or growth.get("basal_herb_profile"):
            from dataclasses import replace
            p = growth.get("basal_subshrub_profile") or growth["basal_herb_profile"]
            modules = [replace(m, radius_m=p["stem_radius_m"] * (1 if m.id == "stem_section" else .5))
                       if m.id in {"stem_section", "branch_section"} else
                       replace(m, radius_m=p["leaf_width_m"] * .5) if m.id == "leaf" else
                       replace(m, length_m=flower_depicted_size or .02, radius_m=(flower_depicted_size or .02)*.5) if m.id == "flower" else
                       replace(m, length_m=fruit_depicted_size or .02, radius_m=(fruit_depicted_size or .02)*.5) if m.id == "fruit" else m
                       for m in modules]
        if growth.get("rosette_raceme_profile"):
            from dataclasses import replace
            radius = growth["rosette_raceme_profile"]["stem_radius_m"]
            modules = [replace(m, radius_m=radius) if m.id == "stem_section" else
                       replace(m, length_m=flower_depicted_size, radius_m=flower_depicted_size * .5)
                       if m.id == "flower" and flower_depicted_size else
                       replace(m, length_m=fruit_depicted_size, radius_m=fruit_depicted_size * .5)
                       if m.id == "fruit" and fruit_depicted_size else m
                       for m in modules]
        if growth.get('cyme_herb_version'):
            from dataclasses import replace
            p=growth['cyme_herb_profile']
            modules=[replace(module,radius_m=p['shoot_radius_m'] if module.id=='stem_section' else p['shoot_radius_m']*.4)
                     if module.id in {'stem_section','branch_section'} else
                     replace(module,radius_m=p['leaf_width_m']*.5) if module.id=='leaf' else
                     replace(module,length_m=(flower_depicted_size or .0021) if module.id=='flower' else (fruit_depicted_size or .0032),
                             radius_m=((flower_depicted_size or .0021) if module.id=='flower' else (fruit_depicted_size or .0032))*.5)
                     if module.id in {'flower','fruit'} else module for module in modules]
        if (form == 'forb' and behaviour == 'rhizomatous_clonal'
                and growth['plant_woodiness'] == 'herbaceous' and growth['flowering_position'] == 'terminal'
                and growth['reproductive_structure'] == 'flower' and growth['leaf_attachment_pattern'] == 'along_stem'):
            from simulations.species.rhizome_racemes import rhizome_raceme_profile
            p = rhizome_raceme_profile(entity.get('plant_shoot_profile'))
            if p:
                from dataclasses import replace
                growth['rhizome_raceme_profile'] = p
                growth['rhizome_raceme_version'] = p['version']
                modules = [replace(m,radius_m=p['stem_radius_m']) if m.id=='stem_section' else
                           replace(m,radius_m=p['rhizome_radius_m']) if m.id=='branch_section' else
                           replace(m,radius_m=p['leaf_width_m']*.5) if m.id=='leaf' else
                           replace(m,length_m=p['flower_size_m'],radius_m=p['flower_size_m']*.5) if m.id=='flower' else
                           replace(m,length_m=p['capsule_length_m'],radius_m=.002) if m.id=='fruit' else m for m in modules]
        if growth.get('woody_axes_profile',{}).get('leaf_width_m'):
            from dataclasses import replace
            width=growth['woody_axes_profile']['leaf_width_m']
            modules=[replace(m,radius_m=width*.5) if m.id=='leaf' else m for m in modules]
        if growth.get('mixed_tiller_version'):
            from dataclasses import replace
            p=growth['mixed_tiller_profile']
            modules=[replace(m,radius_m=p['culm_radius_m']) if m.id in {'stem_section','branch_section'}
                     else replace(m,radius_m=p['leaf_width_m']*.5) if m.id=='leaf'
                     else replace(m,length_m=p['spike_length_m'],radius_m=p['spike_width_m']*.5,
                                  visual={**m.visual,'visual_unit':'whole_spike'}) if m.id=='flower'
                     else m for m in modules]
        if growth.get('tufted_sedge_version'):
            from dataclasses import replace
            p = growth['tufted_sedge_profile']
            radii = {'stem_section':p['culm_radius_m'],'branch_section':p['culm_radius_m']*.35,'leaf':p['leaf_width_m']*.5}
            modules = [replace(module,radius_m=radii[module.id]) if module.id in radii else module for module in modules]
            modules = [replace(module,length_m=p['spikelet_length_m'],radius_m=p['spikelet_width_m']*.5,
                               visual={**module.visual,'visual_unit':'multi_floret_spikelet'})
                       if module.id in {'flower','fruit'} else module for module in modules]
        if growth.get("woody_spur_version"):
            from dataclasses import replace
            p = growth["woody_spur_profile"]
            radii = {"stem_section":p["stem_radius_m"], "branch_section":p["branch_radius_m"], "leaf":p["leaf_width_m"]*.5}
            modules = [replace(m, radius_m=radii[m.id]) if m.id in radii else m for m in modules]
        calyx = (seasonal_profile or {}).get("persistent_calyx_display")
        if calyx and growth.get("woody_spur_version"):
            growth["persistent_calyx_version"] = 1
            calyx_anchor = (entity.get("plant_module_anchors") or {}).get("calyx", {})
            modules.append(PlantModule("calyx", "calyx",
                asset_ref=str(entity.get("plant_calyx_module_ref") or "") or None,
                length_m=calyx["calyx_size_m"], radius_m=calyx["calyx_size_m"]*.5,
                attachment_point=tuple(calyx_anchor.get("attachment_point", (.5,.5))),
                visual={"depicted_size_m":calyx["calyx_size_m"]}))
        if behaviour == "surface_covering":
            body_module = "moss_patch" if form == "moss" else "thallus"
            modules = [
                PlantModule(body_module, body_module, sockets=("surface", "apothecium")),
                PlantModule("apothecium", "apothecium", sockets=("surface",)),
            ]
            if growth["surface_growth_profile"]["thallus_form"] == "fruticose":
                modules.extend(PlantModule(kind, kind, sockets=("surface",)) for kind in
                               ("pseudopodetium", "phyllocladium", "cephalodium", "soralium"))
        if growth.get('moss_turf_version'):
            from dataclasses import replace
            moss_profile = growth['moss_turf_profile']
            modules = [replace(m, radius_m=moss_profile['stem_radius_m'] * (1. if m.kind == 'stem_section' else .65))
                       if m.kind in {'stem_section', 'branch_section'} else
                       replace(m, radius_m=moss_profile['leaf_width_m'] * .5) if m.kind == 'leaf' else m
                       for m in modules if m.id in {'stem_section', 'branch_section', 'leaf'}]
        if growth.get('pendant_branchlet_version'):
            from dataclasses import replace
            modules = [replace(m, length_m=flower_depicted_size, radius_m=flower_depicted_size*.12)
                       if m.id == 'flower' and flower_depicted_size else m for m in modules]
        if growth.get('seasonal_rhizome_version'):
            from dataclasses import replace
            p = growth['seasonal_rhizome_profile']
            modules = [replace(module, length_m=flower_depicted_size or .025,
                               radius_m=(flower_depicted_size or .025)*.5)
                       if module.id == 'flower' else
                       replace(module, length_m=p['fruit_head_size_m'],
                               radius_m=p['fruit_head_size_m']*.5,
                               visual={**module.visual, 'visual_unit': 'achene_head'})
                       if module.id == 'fruit' else module for module in modules]
        if growth.get('creeping_upright_version'):
            from dataclasses import replace
            p = growth['creeping_upright_profile']
            modules = [replace(module, radius_m=p['leaf_width_m']*.5)
                       if module.id == 'leaf' else module for module in modules]
            anchor = module_anchors.get('strobilus', {})
            anchor = anchor if isinstance(anchor, dict) else {}
            modules.append(PlantModule('strobilus', 'strobilus',
                asset_ref=str(entity.get('plant_strobilus_module_ref') or '') or None,
                length_m=p['strobilus_length_m'], radius_m=p['strobilus_width_m']*.5,
                sockets=('base',), attachment_point=_tuple2(anchor.get('attachment_point')),
                growth_axis=_tuple2(anchor.get('growth_vector') or anchor.get('growth_axis'), (0., -1.)),
                visual={'depicted_size_m': p['strobilus_length_m']}))
        if growth.get('planar_spray_version') and growth.get('shoot_dimorphism')=='axial_and_peripheral_shoots':
            variant = (leaf_anchor.get('variants') or {}).get('axial') or {}
            modules.append(PlantModule('axial_leaf','leaf',asset_ref=variant.get('asset_ref'),
                length_m=growth['planar_spray_profile']['axial_leaf_length_m'],
                radius_m=growth['planar_spray_profile']['axial_leaf_width_m']*.5,
                attachment_point=_tuple2(variant.get('attachment_point'),(.5,.9)),
                visual={'visual_unit':'appressed_scale_leaf_shoot','depicted_size_m':variant.get('depicted_size_m',.06)}))
        return cls(
            species_id=species_id,
            display_name=display_name,
            modules=modules,
            growth=growth,
            **({"root_module_id": body_module} if behaviour == "surface_covering" else
               {"root_module_id": "stem_section"} if growth.get('moss_turf_version') else {}),
            lod_policy={"0": "skeleton", "1": "major_leaves", "2": "full"},
        )


@dataclass
class PlantGrowthSnapshot:
    """A baked species result; placements are arrays to keep scenery compact."""

    species_id: str
    blueprint_fingerprint: str
    seed: int
    age_days: float
    lod: int
    modules: dict[str, dict[str, Any]]
    placements: list[list[Any]]
    bounds_m: list[float]
    model_space: dict[str, Any] = field(default_factory=lambda: dict(PLANT_MODEL_SPACE))
    # Optional curved paths for stem/branch placements. Most segments remain
    # endpoint-only, keeping scenery references compact; only non-linear
    # segments store intermediate world-space points keyed by placement index.
    placement_paths: dict[str, list[list[float]]] = field(default_factory=dict)
    # A compact orthonormal frame for every placement.  This is the 3D model
    # orientation; the legacy rotation value in each placement remains the
    # convenient projected azimuth used by the 2D asset renderer.
    placement_orientations: dict[str, dict[str, Any]] = field(default_factory=dict)
    attachment_points: list[dict[str, Any]] = field(default_factory=list)
    leaf_clusters: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    version: int = PLANT_ASSET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.version,
            "kind": "plant_growth_snapshot",
            "species_id": self.species_id,
            "blueprint_fingerprint": self.blueprint_fingerprint,
            "seed": self.seed,
            "age_days": self.age_days,
            "lod": self.lod,
            "modules": self.modules,
            "placements": self.placements,
            "bounds_m": self.bounds_m,
            "model_space": self.model_space,
            "placement_paths": self.placement_paths,
            "placement_orientations": self.placement_orientations,
            "attachment_points": self.attachment_points,
            "leaf_clusters": self.leaf_clusters,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlantGrowthSnapshot":
        return cls(
            species_id=str(value.get("species_id") or "unknown_species"),
            blueprint_fingerprint=str(value.get("blueprint_fingerprint") or ""),
            seed=int(value.get("seed", 0) or 0),
            age_days=float(value.get("age_days", 0.0) or 0.0),
            lod=int(value.get("lod", 2) or 0),
            modules=dict(value.get("modules") or {}),
            placements=[list(item) for item in value.get("placements", []) if isinstance(item, (list, tuple))],
            bounds_m=[float(item) for item in value.get("bounds_m", [0.0] * 6)],
            model_space={**PLANT_MODEL_SPACE, **dict(value.get("model_space") or {})},
            placement_paths={
                str(key): [list(point) for point in points if isinstance(point, (list, tuple)) and len(point) >= 3]
                for key, points in (value.get("placement_paths") or {}).items()
                if isinstance(points, list)
            },
            placement_orientations={
                str(key): dict(orientation)
                for key, orientation in (value.get("placement_orientations") or {}).items()
                if isinstance(orientation, dict)
            },
            attachment_points=[dict(item) for item in value.get("attachment_points", []) if isinstance(item, dict)],
            leaf_clusters=[dict(item) for item in value.get("leaf_clusters", []) if isinstance(item, dict)],
            stats=dict(value.get("stats") or {}),
            version=int(value.get("schema_version", PLANT_ASSET_SCHEMA_VERSION) or PLANT_ASSET_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class PlantSceneReference:
    """Map/scenery reference: one recipe + transform, not a duplicated plant."""

    species_id: str
    blueprint_ref: str
    snapshot_ref: str | None = None
    seed: int = 0
    lod: int = 1
    position_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: float = 0.0
    scale: float = 1.0
    model_space: str = "3d_orthographic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "species_plant_instance",
            "species_id": self.species_id,
            "blueprint_ref": self.blueprint_ref,
            "snapshot_ref": self.snapshot_ref,
            "seed": self.seed,
            "lod": self.lod,
            "position_m": list(self.position_m),
            "rotation_deg": self.rotation_deg,
            "scale": self.scale,
            "model_space": self.model_space,
        }


class PlantAssetStore:
    """Gzip JSON store for authored blueprints and optional baked snapshots."""

    def __init__(self, root: str | Path = "assets/plants"):
        self.root = Path(root)
        self.blueprint_root = self.root / "blueprints"
        self.snapshot_root = self.root / "snapshots"

    def blueprint_path(self, species_id: str) -> Path:
        return self.blueprint_root / f"{_safe_id(species_id)}.json.gz"

    def snapshot_path(self, snapshot: PlantGrowthSnapshot) -> Path:
        environment = snapshot.stats.get("environment")
        suffix = "_e" + hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()[:12] if environment else ""
        return self.snapshot_root / _safe_id(snapshot.species_id) / (
            f"{snapshot.blueprint_fingerprint}_s{snapshot.seed}_a{int(round(snapshot.age_days))}d_l{snapshot.lod}{suffix}.json.gz"
        )

    def _write(self, path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with gzip.open(temp_path, "wt", encoding="utf-8", compresslevel=6) as handle:
                json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        return path.as_posix()

    def save_blueprint(self, blueprint: PlantBlueprint) -> str:
        return self._write(self.blueprint_path(blueprint.species_id), blueprint.to_dict())

    def load_blueprint(self, species_id: str) -> PlantBlueprint | None:
        path = self.blueprint_path(species_id)
        try:
            with asset_files.open_gzip_text(path) as handle:
                return PlantBlueprint.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save_snapshot(self, snapshot: PlantGrowthSnapshot) -> str:
        return self._write(self.snapshot_path(snapshot), snapshot.to_dict())

    def load_snapshot(self, snapshot: PlantGrowthSnapshot) -> PlantGrowthSnapshot | None:
        path = self.snapshot_path(snapshot)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return PlantGrowthSnapshot.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def blueprint_ref(self, species_id: str) -> str:
        return self.blueprint_path(species_id).as_posix()

    def make_scene_reference(self, blueprint: PlantBlueprint, snapshot: PlantGrowthSnapshot | None = None, **kwargs) -> PlantSceneReference:
        return PlantSceneReference(
            species_id=blueprint.species_id,
            blueprint_ref=self.blueprint_ref(blueprint.species_id),
            snapshot_ref=self.snapshot_path(snapshot).as_posix() if snapshot else None,
            seed=int(kwargs.get("seed", snapshot.seed if snapshot else 0)),
            lod=int(kwargs.get("lod", snapshot.lod if snapshot else 1)),
            position_m=_tuple3(kwargs.get("position_m")),
            rotation_deg=float(kwargs.get("rotation_deg", 0.0) or 0.0),
            scale=float(kwargs.get("scale", 1.0) or 1.0),
        )
