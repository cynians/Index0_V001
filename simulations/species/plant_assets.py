"""Portable plant authoring and scenery products.

The ontology identifies a species and can optionally point at a blueprint.
Large pixel documents and generated growth products live in the asset store,
so an ontology entity does not grow a copy of every leaf placement.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

def is_plant_species_entity(entity: dict[str, Any] | None, plant_catalogue=None) -> bool:
    """Constant-time membership in the repository's Plantae ancestry index.

    Standalone callers must supply a catalogue; names and trait presence are
    never evidence of ancestry. Explicit SpeciesSimulation fixtures can still
    be constructed without a repository for isolated grammar experiments.
    """
    return bool(isinstance(entity,dict) and plant_catalogue is not None
                and plant_catalogue.is_species(entity.get("id")))


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
            radius_m=float(value.get("radius_m", 0.01) or 0.01),
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
        leaf_anchor = leaf_anchor if isinstance(leaf_anchor, dict) else {}
        flower_anchor = flower_anchor if isinstance(flower_anchor, dict) else {}

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
            max_height = max(0.1, mature_height)
            if is_tree:
                # The branching grammar is capped to a compact number of
                # generations, so tall trees need longer structural units to
                # reach their authored mature height.
                internode = max(internode, max_height / 14.0)
        leaf_arrangement = str(entity.get("leaf_arrangement") or "").lower()
        phyllotaxis = 137.5
        if leaf_arrangement == "opposite":
            phyllotaxis = 180.0
        elif leaf_arrangement == "whorled":
            phyllotaxis = 90.0
        elif leaf_arrangement == "distichous":
            phyllotaxis = 180.0
        if str(entity.get("leaf_attachment_pattern") or "").lower() == "basal_rosette" and not is_aquatic:
            shape = "rosette"
            behaviour = "rosette_short_internode"
            max_height, internode, branch_probability = 0.45, 0.16, 0.0

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
        leaf_length = {
            "very_small": 0.06,
            "small": 0.10,
            "medium": 0.15,
            "large": 0.24,
            "very_large": 0.38,
        }.get(leaf_size, 0.22)
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
        architecture_ranges = {
            field_name.removeprefix("plant_"): normalised_plant_trait_range(
                entity.get(field_name),
                {
                    "plant_branch_droop": branch_droop,
                    "plant_branch_angle_gradient": branch_angle_gradient,
                    "plant_crown_openness": crown_openness,
                    "plant_leaf_spacing_bias": leaf_spacing_bias,
                    "plant_leaf_depth_gradient": leaf_depth_gradient,
                    "plant_fine_twig_density": fine_twig_density,
                    "plant_leaf_cluster_density": leaf_cluster_density,
                    "plant_apical_control": apical_control,
                }[field_name],
            )
            for field_name in PLANT_ARCHITECTURE_RANGE_FIELDS
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
            "leaf_attachment_pattern": str(entity.get("leaf_attachment_pattern") or ""),
            "leaf_clustering": str(entity.get("leaf_clustering") or ""),
            "shoot_dimorphism": shoot_dimorphism,
            "leaf_distribution": leaf_distribution,
            "shoot_distribution_grammar": 1 if is_tree and (entity.get("plant_leaf_distribution") or entity.get("leaf_attachment_pattern") == "along_stem") else 0,
            "axis_continuity": architecture_category("plant_axis_continuity"),
            "branching_rhythm": architecture_category("plant_branching_rhythm"),
            "branching_timing": architecture_category("plant_branching_timing"),
            "lateral_axis_orientation": architecture_category("plant_lateral_axis_orientation"),
            "flowering_position": architecture_category("plant_flowering_position"),
            "leaf_spacing_bias": leaf_spacing_bias,
            "branch_droop": branch_droop,
            "branch_angle_gradient": branch_angle_gradient,
            "crown_openness": crown_openness,
            "leaf_depth_gradient": leaf_depth_gradient,
            "fine_twig_density": fine_twig_density,
            "leaf_cluster_density": leaf_cluster_density,
            "reproductive_mode": str(entity.get("reproductive_mode") or ""),
            "root_architecture": str(entity.get("root_architecture") or ""),
            "root_depth_class": str(entity.get("root_depth_class") or ""),
            "max_root_depth": entity.get("max_root_depth"),
            "longevity_class": str(entity.get("longevity_class") or ""),
            "life_history": life_history,
        }
        growth["root_profile"] = root_profile(growth)
        from simulations.species.root_visuals import root_visual_profile
        growth["root_visual_profile"] = root_visual_profile(growth)
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
                "stem_section", "stem_section", length_m=internode, radius_m=0.035,
                asset_ref=str(entity.get("plant_stem_module_ref") or "") or None,
                texture_set_ref=str(entity.get("plant_stem_texture_set_ref") or entity.get("plant_bark_texture_set_ref") or "") or None,
            ),
            PlantModule(
                "branch_section", "branch_section", length_m=internode * 0.8, radius_m=0.022,
                asset_ref=str(entity.get("plant_branch_module_ref") or "") or None,
                texture_set_ref=str(entity.get("plant_branch_texture_set_ref") or entity.get("plant_bark_texture_set_ref") or "") or None,
            ),
            PlantModule(
                "leaf",
                "leaf",
                asset_ref=str(entity.get("plant_leaf_module_ref") or "") or None,
                length_m=leaf_length,
                radius_m=0.06 if form == "succulent" else 0.012,
                sockets=("base",),
                attachment_point=_tuple2(leaf_anchor.get("attachment_point")),
                growth_axis=_tuple2(leaf_anchor.get("growth_vector") or leaf_anchor.get("growth_axis"), (0.0, -1.0)),
                visual={"leaf_structure": leaf_structure},
            ),
            PlantModule(
                "flower",
                "flower",
                asset_ref=str(entity.get("plant_flower_module_ref") or "") or None,
                length_m=0.16,
                radius_m=0.018,
                sockets=("base",),
                attachment_point=_tuple2(flower_anchor.get("attachment_point")),
                growth_axis=_tuple2(flower_anchor.get("growth_vector") or flower_anchor.get("growth_axis"), (0.0, -1.0)),
            ),
            PlantModule(
                "fruit", "fruit",
                asset_ref=str(entity.get("plant_fruit_module_ref") or "") or None,
                length_m=0.1, radius_m=0.025, sockets=("base",),
            ),
        ]
        return cls(
            species_id=species_id,
            display_name=display_name,
            modules=modules,
            growth=growth,
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
            with gzip.open(path, "rt", encoding="utf-8") as handle:
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
