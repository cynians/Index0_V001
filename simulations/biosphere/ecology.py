"""Continuous-coordinate ecology kernel for the isometric Biosphere builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math


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
            return float(authored.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    digest = hashlib.sha256(species_id.encode("utf-8")).digest()
    return SpeciesProfile(
        species_id=species_id, label=str(label), growth_form=growth_form,
        growth_rate=_clamp(number("seasonal_growth_rate", defaults[0]), 0.01, 0.8),
        dispersal=_clamp(number("seasonal_dispersal", defaults[1]), 0.0, 0.45),
        carrying_biomass_kg_m2=max(0.05, number("carrying_biomass_kg_m2", defaults[2])),
        moisture_optimum=_clamp(number("moisture_optimum", defaults[3])),
        moisture_tolerance=max(0.08, number("moisture_tolerance", defaults[4])),
        light_minimum=_clamp(number("light_minimum", defaults[5])),
        color=(58 + digest[0] % 78, 122 + digest[1] % 112, 55 + digest[2] % 76),
        provenance="authored biosphere_growth_profile" if authored else f"visible {growth_form} runtime defaults",
    )


class BiosphereEcology:
    """Population patches spread and overlap in continuous world coordinates."""

    MODEL_VERSION = "biosphere-continuous-patches-v2"

    def __init__(self, bounds, profiles, columns=None, rows=None):
        self.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        self.profiles = {profile.species_id: profile for profile in profiles}
        self.patches: list[PopulationPatch] = []
        self.introductions = []
        self.season = 0
        self._next_introduction = 1
        self._next_patch = 1

    @property
    def width(self):
        return self.bounds["max_x"] - self.bounds["min_x"]

    @property
    def height(self):
        return self.bounds["max_y"] - self.bounds["min_y"]

    def contains(self, x, y):
        return self.bounds["min_x"] <= float(x) <= self.bounds["max_x"] and self.bounds["min_y"] <= float(y) <= self.bounds["max_y"]

    def environment_at(self, x, y):
        nx = _clamp((float(x) - self.bounds["min_x"]) / max(0.001, self.width))
        ny = _clamp((float(y) - self.bounds["min_y"]) / max(0.001, self.height))
        channel = math.exp(-((nx - (0.23 + 0.18 * ny)) ** 2) / 0.006)
        ridge = math.exp(-((nx - 0.76) ** 2 + (ny - 0.30) ** 2) / 0.045)
        local_bonus = sum(
            patch.soil_fertility_bonus * max(0.0, 1.0 - math.hypot(float(x) - patch.x, float(y) - patch.y) / max(0.05, patch.radius_m))
            for patch in self.patches if patch.soil_fertility_bonus > 0.0
        )
        return {
            "elevation_norm": _clamp(0.18 + 0.46 * nx + 0.24 * ridge),
            "soil_moisture": _clamp(0.26 + 0.58 * channel + 0.18 * (1.0 - ny) - 0.17 * ridge),
            "soil_fertility": _clamp(0.48 + 0.28 * channel - 0.12 * ridge + local_bonus),
            "surface_solar_exposure": _clamp(0.82 - 0.16 * ny + 0.08 * ridge),
            "channel_presence": _clamp(channel),
        }

    def _suitability(self, profile, environment):
        moisture_score = _clamp(1.0 - abs(environment["soil_moisture"] - profile.moisture_optimum) / profile.moisture_tolerance)
        light_score = _clamp((environment["surface_solar_exposure"] - profile.light_minimum) / max(0.08, 1.0 - profile.light_minimum))
        return _clamp(0.58 * moisture_score + 0.24 * light_score + 0.18 * environment["soil_fertility"])

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
        abundance = 0.0
        for patch in self.species_patches(species_id):
            distance = math.hypot(float(x) - patch.x, float(y) - patch.y)
            if distance <= patch.radius_m:
                abundance += patch.abundance * math.sqrt(max(0.0, 1.0 - distance / patch.radius_m))
        return _clamp(abundance)

    def total_abundance_at(self, x, y):
        return _clamp(sum(self.abundance_at(species_id, x, y) for species_id in self.profiles), 0.0, 4.0)

    def representative_sites(self, species_id, count=12):
        candidates = []
        for patch in self.species_patches(species_id):
            candidates.append((patch.abundance, patch.x, patch.y))
            for index in range(7):
                angle = (patch.seed % 6283) / 1000.0 + index * math.tau / 7.0
                distance = patch.radius_m * (0.32 + 0.08 * (index % 3))
                x, y = patch.x + math.cos(angle) * distance, patch.y + math.sin(angle) * distance
                if self.contains(x, y):
                    candidates.append((self.abundance_at(species_id, x, y), x, y))
        return sorted(candidates, key=lambda item: (-item[0], item[2], item[1]))[:max(0, int(count))]

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
        if self.contains(x, y):
            self._new_patch(patch.species_id, x, y, max(0.16, patch.radius_m * 0.24),
                            max(0.035, patch.abundance * profile.dispersal * 0.55), self.season + 1,
                            f"satellite:{patch.patch_id}:{self.season}")

    def advance(self, seasons=1, representative_feedback=None):
        representative_feedback = representative_feedback or {}
        for _ in range(max(0, int(seasons))):
            for patch in list(self.patches):
                profile = self.profiles[patch.species_id]
                feedback = representative_feedback.get(patch.species_id) or {}
                growth_multiplier = _clamp(feedback.get("growth_multiplier", 1.0), 0.25, 1.75)
                dispersal_multiplier = _clamp(feedback.get("dispersal_multiplier", 1.0), 0.25, 1.75)
                mortality = _clamp(feedback.get("mortality_pressure", 0.0), 0.0, 0.20)
                suitability = self._suitability(profile, self.environment_at(patch.x, patch.y))
                competition = self._competition_at_patch(patch)
                growth = profile.growth_rate * growth_multiplier * suitability * patch.abundance * max(0.0, 1.0 - patch.abundance - competition * 0.55)
                stress = (1.0 - suitability) * 0.075 * patch.abundance
                patch.abundance = _clamp(patch.abundance + growth - stress - mortality * patch.abundance)
                patch.radius_m = max(0.12, patch.radius_m + profile.dispersal * dispersal_multiplier * (0.12 + patch.abundance * 0.34))
                if patch.species_id == "spec_biomasser_13b":
                    patch.soil_fertility_bonus = _clamp(patch.soil_fertility_bonus + patch.abundance * 0.004, 0.0, 0.22)
                self._spawn_satellite(patch, profile, dispersal_multiplier)
            self.patches = [patch for patch in self.patches if patch.abundance > 0.006]
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
                            "established_patches": sum(patch.abundance >= 0.18 for patch in patches),
                            "biomass_kg": round(biomass, 3)})
        established = sum(item["established_patches"] for item in species)
        return {
            "model_version": self.MODEL_VERSION, "spatial_model": "continuous_population_patches",
            "season": self.season, "introductions": len(self.introductions),
            "population_patch_count": len(self.patches), "occupied_cell_species": len(self.patches),
            "established_cell_species": established, "biomass_index": round(total_kg, 3),
            "living_biomass_kg": round(total_kg, 3), "living_footprint_m2": round(min(domain_area, footprint), 3),
            "species": species,
        }
