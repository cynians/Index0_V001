"""Continuous-coordinate ecology kernel for the isometric Biosphere builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from simulations.species.forest_ecology import light_at, shade_profile
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.plant_nutrition import resolve_plant_nutrient_response


def _clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class SpeciesProfile:
    species_id: str
    label: str
    growth_form: str
    growth_rate: float
    dispersal: float
    moisture_optimum: float
    moisture_tolerance: float
    light_minimum: float
    carrying_biomass_kg_m2: float
    color: tuple[int, int, int]
    provenance: str
    shade_tolerance: str = "other_unknown"
    light_requirement_source: str = "growth_form_default"
    mature_height_m: float = 1.0
    maturity_days: float = 120.0
    crown_openness: float = 0.5
    succession_tier: int = 1
    soil_organic_requirement_kg_m2: float = 0.035
    succession_source: str = "growth_form_runtime_default"
    nitrogen_fixation: str = "other_unknown"
    nutrition_mode: str = "other_unknown"
    mycorrhizal_type: str = "other_unknown"
    root_architecture: str = "other_unknown"
    root_depth_class: str = "other_unknown"
    max_root_depth: object = None


@dataclass(frozen=True)
class SpeciesIntroduction:
    introduction_id: str
    species_id: str
    x: float
    y: float
    radius_world: float
    propagule_pressure: float
    season: int


@dataclass
class PopulationPatch:
    patch_id: str
    species_id: str
    x: float
    y: float
    radius_m: float
    abundance: float
    season_introduced: int
    seed: int
    soil_fertility_bonus: float = 0.0
    development_days: float = 1.0
    establishment_canopies: tuple | None = None


_FORM_DEFAULTS = {
    "tree": (0.10, 0.045, 7.5, 0.48, 0.30, 0.22),
    "shrub": (0.16, 0.070, 3.5, 0.46, 0.34, 0.18),
    "graminoid": (0.29, 0.125, 1.4, 0.48, 0.42, 0.28),
    "forb": (0.25, 0.105, 1.0, 0.52, 0.38, 0.25),
    "succulent": (0.13, 0.050, 2.1, 0.22, 0.25, 0.35),
    "aquatic": (0.22, 0.095, 2.4, 0.88, 0.20, 0.18),
    "lichen": (0.48, 0.180, 2.8, 0.38, 0.52, 0.12),
}


def profile_from_entity(entity):
    entity = entity or {}
    species_id = str(entity.get("id") or "unknown_species")
    label = entity.get("pretty_name") or entity.get("name") or species_id.replace("spec_", "").replace("_", " ").title()
    growth_form = str(entity.get("plant_growth_form") or "forb").strip().lower()
    defaults = _FORM_DEFAULTS.get(growth_form, _FORM_DEFAULTS["forb"])
    authored = entity.get("biosphere_growth_profile") if isinstance(entity.get("biosphere_growth_profile"), dict) else {}

    def number(key, default):
        try:
            value = float(authored.get(key, default))
            return value if math.isfinite(value) else float(default)
        except (TypeError, ValueError):
            return float(default)

    digest = hashlib.sha256(species_id.encode("utf-8")).digest()
    shade = shade_profile(str(entity.get("shade_tolerance") or "other_unknown").lower())
    light_default = shade["minimum_light"] if shade["tolerance"] != "other_unknown" else defaults[5]
    try:
        explicit_light = "light_minimum" in authored and math.isfinite(float(authored["light_minimum"]))
    except (TypeError, ValueError):
        explicit_light = False
    light_source = ("authored biosphere light_minimum" if explicit_light else
                    "shade_tolerance qualitative default" if shade["tolerance"] != "other_unknown" else
                    "growth_form_default")
    growth = PlantBlueprint.from_species_entity(entity, species_id).growth
    roles = entity.get("succession_roles") or entity.get("ecological_roles") or []
    if isinstance(roles, str):
        roles = [roles]
    roles = {str(role).strip().lower() for role in roles}
    explicit_tier = authored.get("succession_tier", entity.get("succession_tier"))
    try:
        succession_tier = max(0, min(3, int(explicit_tier)))
        succession_source = "authored succession_tier"
    except (TypeError, ValueError):
        if entity.get("biosphere_bootstrap_species") or growth_form in {"lichen", "aquatic"} or "primary_pioneer" in roles:
            succession_tier = 0
        elif growth_form in {"graminoid", "forb", "fern"}:
            succession_tier = 1
        elif growth_form in {"shrub", "subshrub", "succulent"}:
            succession_tier = 2
        elif growth_form == "tree":
            succession_tier = 3
        else:
            succession_tier = 1
        succession_source = "growth_form runtime default"
    from simulations.biosphere.soil_succession import SoilOrganicMatterField
    explicit_requirement = authored.get(
        "minimum_soil_organic_matter_kg_m2",
        entity.get("minimum_soil_organic_matter_kg_m2"),
    )
    try:
        organic_requirement = max(0.0, float(explicit_requirement))
        if not math.isfinite(organic_requirement):
            raise ValueError
        succession_source = f"{succession_source}; authored organic-matter requirement"
    except (TypeError, ValueError):
        organic_requirement = SoilOrganicMatterField.requirement_for_tier(succession_tier)
    return SpeciesProfile(
        species_id=species_id, label=str(label), growth_form=growth_form,
        growth_rate=_clamp(number("seasonal_growth_rate", defaults[0]), 0.01, 0.8),
        dispersal=_clamp(number("seasonal_dispersal", defaults[1]), 0.0, 0.45),
        carrying_biomass_kg_m2=max(0.05, number("carrying_biomass_kg_m2", defaults[2])),
        moisture_optimum=_clamp(number("moisture_optimum", defaults[3])),
        moisture_tolerance=max(0.08, number("moisture_tolerance", defaults[4])),
        light_minimum=_clamp(number("light_minimum", light_default)),
        color=(58 + digest[0] % 78, 122 + digest[1] % 112, 55 + digest[2] % 76),
        provenance="authored biosphere_growth_profile" if authored else f"visible {growth_form} runtime defaults",
        shade_tolerance=shade["tolerance"], light_requirement_source=light_source,
        mature_height_m=max(0.01, min(150.0, float(growth["max_height_m"]))),
        maturity_days=max(1.0, float(growth["maturity_days"])),
        crown_openness=_clamp(growth["crown_openness"]),
        succession_tier=succession_tier,
        soil_organic_requirement_kg_m2=organic_requirement,
        succession_source=succession_source,
        nitrogen_fixation=growth["nitrogen_fixation"],
        nutrition_mode=growth["nutrition_mode"],
        mycorrhizal_type=growth["mycorrhizal_type"],
        root_architecture=growth["root_architecture"] or "other_unknown",
        root_depth_class=growth["root_depth_class"] or "other_unknown",
        max_root_depth=growth["max_root_depth"],
    )


class BiosphereEcology:
    """Population patches spread and overlap in continuous world coordinates."""

    MODEL_VERSION = "biosphere-soil-succession-v1"
    DAYS_PER_SEASON = 91.3125

    def __init__(self, bounds, profiles, columns=None, rows=None):
        self.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        self.profiles = {profile.species_id: profile for profile in profiles}
        self.patches: list[PopulationPatch] = []
        self.introductions = []
        self.season = 0
        self._next_introduction = 1
        self._next_patch = 1
        self.canopy_light_enabled = True
        self._canopy_cache = None
        self._season_canopies = None
        self.substrate = None
        self.soil = None
        self.representative_feedback = {}

    def canopy_footprints(self):
        """Ecological patch envelopes, independent of decorative plant counts/LOD."""
        if self._season_canopies is not None:
            return self._season_canopies
        key = tuple(sorted((p.patch_id, p.species_id, p.x, p.y, p.radius_m,
                            p.abundance, p.development_days,
                            self.profiles[p.species_id].mature_height_m,
                            self.profiles[p.species_id].maturity_days,
                            self.profiles[p.species_id].crown_openness,
                            self.profiles[p.species_id].growth_form) for p in self.patches))
        if self._canopy_cache is not None and self._canopy_cache[0] == key:
            return self._canopy_cache[1]
        canopies = []
        for p in sorted(self.patches, key=lambda p: p.patch_id):
            profile = self.profiles[p.species_id]
            height = profile.mature_height_m * _clamp(p.development_days / profile.maturity_days)
            if profile.growth_form not in {"tree", "shrub", "subshrub"} or height < 0.25:
                continue
            canopies.append({"id": p.patch_id, "x": p.x, "y": p.y,
                             "height_m": height, "radius_m": p.radius_m,
                             "opacity": (0.90 - 0.50 * profile.crown_openness) * _clamp(p.abundance)})
        self._canopy_cache = key, canopies
        return canopies

    def ground_light_at(self, x, y, sample_height_m=0.05, exclude_patch_id=None):
        """Available light including substrate exposure and shared crown attenuation."""
        incident = self._substrate_environment_at(x, y)["surface_solar_exposure"]
        if not self.canopy_light_enabled:
            return incident
        return incident * light_at(x, y, sample_height_m, self.canopy_footprints(), exclude_patch_id)

    def _recruitment_response(self, species_id, light):
        if not self.canopy_light_enabled:
            return 1.0
        minimum = self.profiles[species_id].light_minimum
        if minimum <= 0.0:
            return 1.0
        # A short transition below the existing shade experiment's threshold.
        # These coefficients are qualitative, not measured seedling physiology.
        return _clamp((light / minimum - 0.65) / 0.35)

    def recruitment_at(self, species_id, x, y):
        return self._recruitment_response(species_id, self.ground_light_at(x, y))

    def _cohort_support(self, patch):
        """Area samples preserve bright margins of a seedbed with a dark centre."""
        factors, lights = [], []
        for index in range(25):
            radius = patch.radius_m * math.sqrt((index + 0.5) / 25)
            angle = index * 2.399963229728653
            x, y = patch.x + math.cos(angle) * radius, patch.y + math.sin(angle) * radius
            if not self.contains(x, y):
                continue
            light = self.ground_light_at(x, y)
            lights.append(light)
            factors.append(self._recruitment_response(patch.species_id, light))
        return ((sum(factors) / len(factors), sum(lights) / len(lights)) if factors else (0.0, 0.0))

    @property
    def width(self):
        return self.bounds["max_x"] - self.bounds["min_x"]

    @property
    def height(self):
        return self.bounds["max_y"] - self.bounds["min_y"]

    def contains(self, x, y):
        return self.bounds["min_x"] <= float(x) <= self.bounds["max_x"] and self.bounds["min_y"] <= float(y) <= self.bounds["max_y"]

    def abiotic_environment_at(self, x, y):
        """Return only inherited mineral/climate state, never biological soil."""
        if self.substrate is not None:
            return self.substrate.environment_at(x, y)
        nx = _clamp((float(x) - self.bounds["min_x"]) / max(0.001, self.width))
        ny = _clamp((float(y) - self.bounds["min_y"]) / max(0.001, self.height))
        channel = math.exp(-((nx - (0.23 + 0.18 * ny)) ** 2) / 0.006)
        ridge = math.exp(-((nx - 0.76) ** 2 + (ny - 0.30) ** 2) / 0.045)
        return {
            "elevation_norm": _clamp(0.18 + 0.46 * nx + 0.24 * ridge),
            "soil_moisture": _clamp(0.26 + 0.58 * channel + 0.18 * (1.0 - ny) - 0.17 * ridge),
            "soil_fertility": _clamp(0.48 + 0.28 * channel - 0.12 * ridge),
            "surface_solar_exposure": _clamp(0.82 - 0.16 * ny + 0.08 * ridge),
            "channel_presence": _clamp(channel),
            "temperature_k": 289.0,
            "runtime_default_fields": ("soil_fertility",),
            "parent_nitrogen_index": 0.18,
            "parent_phosphorus_index": 0.42,
        }

    def _substrate_environment_at(self, x, y):
        environment = self.abiotic_environment_at(x, y)
        environment = dict(environment)
        if self.soil is not None:
            organic = self.soil.environment_at(x, y)
            environment.update(organic)
            mineral_is_resolved = "soil_fertility" not in environment.get("runtime_default_fields", ())
            mineral = _clamp(environment.get("soil_fertility", 0.0)) if mineral_is_resolved else 0.0
            environment["mineral_nutrient_index"] = mineral if mineral_is_resolved else None
            environment["soil_fertility"] = _clamp(
                organic["organic_fertility_index"] if not mineral_is_resolved
                else mineral * 0.55 + organic["organic_fertility_index"] * 0.45
            )
            environment["soil_fertility_source"] = (
                "mineral substrate plus biosphere organic matter" if mineral_is_resolved
                else "biosphere organic matter; mineral nutrients unresolved"
            )
        else:
            bonus = sum(
                patch.soil_fertility_bonus * max(0.0, 1.0 - math.hypot(float(x) - patch.x, float(y) - patch.y) / max(0.05, patch.radius_m))
                for patch in self.patches if patch.soil_fertility_bonus > 0.0
            )
            environment["soil_fertility"] = _clamp(environment.get("soil_fertility", 0.0) + bonus)
        return environment

    def environment_at(self, x, y, sample_height_m=0.05, exclude_patch_id=None):
        environment = self._substrate_environment_at(x, y)
        environment["sample_x"] = float(x)
        environment["sample_y"] = float(y)
        environment["plant_available_light"] = self.ground_light_at(x, y, sample_height_m, exclude_patch_id)
        environment["ground_light_fraction"] = environment["plant_available_light"]
        return environment

    def _suitability(self, profile, environment):
        if self.substrate is not None and profile.growth_form != "aquatic" and (environment.get("open_water", False) or not environment.get("terrain_elevation_known", True)):
            return 0.0
        moisture_score = _clamp(1.0 - abs(environment["soil_moisture"] - profile.moisture_optimum) / profile.moisture_tolerance)
        light = environment.get("plant_available_light", environment["surface_solar_exposure"])
        light_score = _clamp((light - profile.light_minimum) / max(0.08, 1.0 - profile.light_minimum))
        factors = [(0.48, moisture_score), (0.22, light_score)]
        if self.soil is not None:
            organic_support = self.soil.support_at(
                environment.get("sample_x", 0.0),
                environment.get("sample_y", 0.0),
                profile.soil_organic_requirement_kg_m2,
            ) if "sample_x" in environment else (
                1.0 if profile.soil_organic_requirement_kg_m2 <= 0.0 else
                _clamp((environment.get("soil_organic_matter_kg_m2", 0.0) / profile.soil_organic_requirement_kg_m2 - 0.45) / 0.55)
            )
            factors.append((0.22, organic_support))
            nutrient = resolve_plant_nutrient_response({
                "nitrogen_fixation": profile.nitrogen_fixation,
                "mycorrhizal_type": profile.mycorrhizal_type,
                "root_architecture": profile.root_architecture,
                "root_depth_class": profile.root_depth_class,
                "max_root_depth": profile.max_root_depth,
            }, environment)
            # Liebig-like limitation: the scarcest nutrient controls this
            # factor, while the rest of suitability remains multifactorial.
            factors.append((0.18, min(nutrient["nitrogen_response"], nutrient["phosphorus_response"])))
        if "soil_fertility" not in environment.get("runtime_default_fields", ()) or self.soil is not None:
            factors.append((0.08, environment["soil_fertility"]))
        weight = sum(item[0] for item in factors)
        return _clamp(sum(item_weight * score for item_weight, score in factors) / max(1e-9, weight))

    def _new_patch(self, species_id, x, y, radius_m, abundance, season_introduced, seed_text):
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        patch = PopulationPatch(
            patch_id=f"population_patch_{self._next_patch:04d}", species_id=species_id,
            x=float(x), y=float(y), radius_m=max(0.12, float(radius_m)),
            abundance=_clamp(abundance, 0.01, 0.98), season_introduced=int(season_introduced),
            seed=int.from_bytes(digest[:4], "big"),
        )
        self._next_patch += 1
        self.patches.append(patch)
        return patch

    def introduce(self, species_id, x, y, radius_world, propagule_pressure=0.28):
        if species_id not in self.profiles or not self.contains(x, y):
            return None
        introduction = SpeciesIntroduction(
            introduction_id=f"introduction_{self._next_introduction:04d}", species_id=species_id,
            x=float(x), y=float(y), radius_world=max(0.18, float(radius_world)),
            propagule_pressure=_clamp(propagule_pressure, 0.02, 0.95), season=self.season,
        )
        self._next_introduction += 1
        self.introductions.append(introduction)
        self._new_patch(species_id, x, y, introduction.radius_world, introduction.propagule_pressure, self.season,
                        f"{species_id}:{x:.5f}:{y:.5f}:{self.season}:{introduction.introduction_id}")
        return introduction

    def species_patches(self, species_id=None):
        return [patch for patch in self.patches if species_id is None or patch.species_id == species_id]

    def abundance_at(self, species_id, x, y):
        # Do not render or retain terrestrial populations beneath imported open water.
        # This is an occupancy guard, not species-specific flood/salinity physiology.
        if self.substrate is not None and self.profiles[species_id].growth_form != "aquatic" and not self.substrate.terrestrial_habitat_at(x,y):
            return 0.0
        abundance = 0.0
        recruitment = None
        for patch in self.species_patches(species_id):
            distance = math.hypot(float(x) - patch.x, float(y) - patch.y)
            if distance <= patch.radius_m:
                factor = 1.0
                if patch.development_days < self.profiles[species_id].maturity_days:
                    if recruitment is None:
                        recruitment = self.recruitment_at(species_id, x, y)
                    factor = recruitment
                elif patch.establishment_canopies is not None and self.canopy_light_enabled:
                    # Maturing a seedbed must not create adults in previously shaded holes.
                    incident = self._substrate_environment_at(x, y)["surface_solar_exposure"]
                    birth_light = incident * light_at(x, y, 0.05, patch.establishment_canopies)
                    factor = self._recruitment_response(species_id, birth_light)
                abundance += patch.abundance * factor * math.sqrt(max(0.0, 1.0 - distance / patch.radius_m))
        return _clamp(abundance)

    def total_abundance_at(self, x, y):
        return _clamp(sum(self.abundance_at(species_id, x, y) for species_id in self.profiles), 0.0, 4.0)

    def representative_sites(self, species_id, count=12):
        candidates = []
        for patch in self.species_patches(species_id):
            candidates.append((self.abundance_at(species_id, patch.x, patch.y), patch.x, patch.y))
            for index in range(24):
                angle = (patch.seed % 6283) / 1000.0 + index * 2.399963229728653
                distance = patch.radius_m * math.sqrt((index + .5) / 24)
                x, y = patch.x + math.cos(angle) * distance, patch.y + math.sin(angle) * distance
                if self.contains(x, y):
                    candidates.append((self.abundance_at(species_id, x, y), x, y))
        return sorted((c for c in candidates if c[0] > .003), key=lambda item: (-item[0], item[2], item[1]))[:max(0, int(count))]

    def _competition_at_patch(self, patch):
        total = 0.0
        for other in self.patches:
            if other is patch:
                continue
            overlap = max(0.0, 1.0 - math.hypot(patch.x - other.x, patch.y - other.y) / max(0.05, patch.radius_m + other.radius_m))
            total += other.abundance * overlap * (0.45 if other.species_id == patch.species_id else 0.75)
        return _clamp(total)

    def _spawn_satellite(self, patch, profile, dispersal_multiplier):
        if patch.abundance < 0.42 or len(self.species_patches(patch.species_id)) >= 12 or (self.season + patch.seed) % 3:
            return
        angle_seed = hashlib.sha256(f"{patch.patch_id}:{self.season}".encode("utf-8")).digest()
        angle = int.from_bytes(angle_seed[:2], "big") / 65535.0 * math.tau
        distance = patch.radius_m * (1.05 + profile.dispersal * 1.8 * dispersal_multiplier)
        x, y = patch.x + math.cos(angle) * distance, patch.y + math.sin(angle) * distance
        recruitment = self.recruitment_at(patch.species_id, x, y)
        if self.contains(x, y) and recruitment > 0.0:
            self._new_patch(patch.species_id, x, y, max(0.16, patch.radius_m * 0.24),
                            max(0.035, patch.abundance * profile.dispersal * 0.55) * recruitment, self.season + 1,
                            f"satellite:{patch.patch_id}:{self.season}")

    def advance(self, seasons=1, representative_feedback=None):
        representative_feedback = representative_feedback or {}
        self.representative_feedback = representative_feedback
        for _ in range(max(0, int(seasons))):
            # Freeze neighbour shade for the season; no generation-order light feedback.
            self._season_canopies = self.canopy_footprints()
            for patch in sorted(self.patches, key=lambda p: p.patch_id):
                profile = self.profiles[patch.species_id]
                feedback = representative_feedback.get(patch.species_id) or {}
                growth_multiplier = _clamp(feedback.get("growth_multiplier", 1.0), 0.25, 1.75)
                dispersal_multiplier = _clamp(feedback.get("dispersal_multiplier", 1.0), 0.25, 1.75)
                mortality = _clamp(feedback.get("mortality_pressure", 0.0), 0.0, 0.20)
                juvenile = patch.development_days < profile.maturity_days
                recruitment, seedbed_light = self._cohort_support(patch) if juvenile else (1.0, 0.0)
                height = profile.mature_height_m * _clamp(patch.development_days / profile.maturity_days)
                environment = self.environment_at(patch.x, patch.y, max(0.05, height * 0.5), patch.patch_id)
                if juvenile:
                    environment["plant_available_light"] = seedbed_light
                suitability = self._suitability(profile, environment)
                competition = self._competition_at_patch(patch)
                growth = profile.growth_rate * growth_multiplier * suitability * recruitment * patch.abundance * max(0.0, 1.0 - patch.abundance - competition * 0.55)
                stress = ((1.0 - suitability) * 0.075 + (1.0 - recruitment) * 0.35) * patch.abundance
                patch.abundance = _clamp(patch.abundance + growth - stress - mortality * patch.abundance)
                patch.development_days += self.DAYS_PER_SEASON * recruitment
                if juvenile and patch.development_days >= profile.maturity_days:
                    patch.establishment_canopies = tuple(dict(c) for c in self._season_canopies
                                                         if c["id"] != patch.patch_id)
                patch.radius_m = max(0.12, patch.radius_m + profile.dispersal * dispersal_multiplier * recruitment * (0.12 + patch.abundance * 0.34))
                if self.soil is None and patch.species_id == "spec_biomasser_13b":
                    patch.soil_fertility_bonus = _clamp(patch.soil_fertility_bonus + patch.abundance * 0.004, 0.0, 0.22)
                self._spawn_satellite(patch, profile, dispersal_multiplier)
            self.patches = [patch for patch in self.patches if patch.abundance > 0.006]
            if self.soil is not None:
                self.soil.advance(self, 1)
            self._season_canopies = None
            self.season += 1
        return self.summary()

    def edge_abundance(self):
        return max((patch.abundance for patch in self.patches if
                    patch.x - patch.radius_m <= self.bounds["min_x"] or patch.x + patch.radius_m >= self.bounds["max_x"] or
                    patch.y - patch.radius_m <= self.bounds["min_y"] or patch.y + patch.radius_m >= self.bounds["max_y"]), default=0.0)

    def expand(self, margin_cells=4):
        margin = max(0.5, min(self.width, self.height) * 0.2)
        self.bounds = {
            "min_x": self.bounds["min_x"] - margin, "max_x": self.bounds["max_x"] + margin,
            "min_y": self.bounds["min_y"] - margin, "max_y": self.bounds["max_y"] + margin,
        }
        return 0, 0

    def population_footprints(self):
        return [{"patch_id": patch.patch_id, "species_id": patch.species_id, "x": patch.x, "y": patch.y,
                 "radius_m": patch.radius_m, "abundance": patch.abundance,
                 "color": self.profiles[patch.species_id].color} for patch in self.patches]

    def summary(self):
        domain_area = max(0.01, self.width * self.height)
        total_kg = 0.0
        footprint = 0.0
        species = []
        for species_id, profile in self.profiles.items():
            patches = self.species_patches(species_id)
            if not patches:
                continue
            area = sum(math.pi * patch.radius_m ** 2 for patch in patches)
            biomass = sum(math.pi * patch.radius_m ** 2 * patch.abundance * profile.carrying_biomass_kg_m2 for patch in patches)
            footprint += area
            total_kg += biomass
            species.append({"species_id": species_id, "population_patches": len(patches),
                            "shade_tolerance": profile.shade_tolerance, "light_minimum": profile.light_minimum,
                            "light_requirement_source": profile.light_requirement_source,
                            "established_patches": sum(patch.abundance >= 0.18 for patch in patches),
                            "biomass_kg": round(biomass, 3)})
        established = sum(item["established_patches"] for item in species)
        result = {
            "model_version": self.MODEL_VERSION, "spatial_model": "continuous_population_patches",
            "recruitment_model": "canopy_light_v1" if self.canopy_light_enabled else "disabled_control",
            "season": self.season, "introductions": len(self.introductions),
            "population_patch_count": len(self.patches), "occupied_cell_species": len(self.patches),
            "established_cell_species": established, "biomass_index": round(total_kg, 3),
            "living_biomass_kg": round(total_kg, 3), "living_footprint_m2": round(min(domain_area, footprint), 3),
            "species": species,
        }
        if self.soil is not None:
            result["soil"] = self.soil.summary()
        return result
