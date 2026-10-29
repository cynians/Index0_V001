# Entity Field Overview — Material (world-generation chemistry)

Version: v001
Date: 2026-09-24

> **Status — IMPLEMENTED 2026-09-24.** Decisions (§6): rocks carry both bulk
> composition and modal mineralogy; Earth reference = upper continental crust;
> unlisted elements = Earth-like background; templates, mineral mechanics and
> the crust panel included.  §2-§4 describe the pre-change state and are kept
> for the record; §8 is the as-built state.

## 1. Purpose

Part of the per-entity-class field audit series. This one covers the fields
through which a planet's **element distribution** is meant to decide which
natural materials exist on it. The design intent: the element distribution is
the first step of planet generation, and the roster of present materials
follows from it. In practice the roster barely changes with the distribution.

- **Source:** SQLite quadstore behind `ontology/index0.owl`
  (`PersistentOntologyStore.load_datasets()["materials"]`).
- **Population:** 356 material entities; 319 enter the world-generation
  cache; 210 are roster-eligible (100 minerals, 79 rocks, 16 sediments,
  12 regolith types, 3 ices).  The 92 element entities and 17 atmospheric
  gases are handled separately.
- Audit scripts (scratch): `audit_materials.py`, `audit_roster_variation.py`,
  `audit_chemistry_fields.py`.

## 2. How the element distribution reaches the roster today

1. The seed carries `crust_composition`: explicit `major_elements` (normalised
   to 99 %) plus `trace_elements`, set by planet template, randomisation or the
   periodic-table editor (`world_gen_sim.py`, `crust.py`).
2. `natural_materials.derive_planet_material_tags` turns it into coarse tags
   (`silica_rich_crust` at Si >= 27 %, `mafic_crust`, `sulfur_bearing_crust` at
   S >= 0.01 %, ...).
3. `natural_materials.derive_natural_material_model` loops over the
   210 materials:
   - **gate:** every element in `required_element_thresholds` (and each
     `required_element_groups` entry) must reach its threshold, otherwise the
     material is dropped;
   - **confidence:** `0.68 * chemistry + 0.12 * group + 0.20 * tags`, where the
     chemistry score is `min(1, abundance / (2 * threshold))`;
   - **relative abundance:** fixed ontology value
     `surface_affinity_profile.abundance`, adjusted by hard-coded special cases
     in code (basalt = 1.0 under active volcanism, anorthosite x 0.42,
     ultramafic x 1.72, graphite as foundation at C >= 8 %).
4. The LOD0 material map (`lithotectonic_settings.resolve_setting_recipes`)
   weights rocks by `lithotectonic_setting_weights` x relative abundance, using
   only materials that passed the gate.

## 3. Why the catalogue looks the same for every distribution

### 3.1 Stale roster on the crust screen (fixed)

The crust editor's "Possible Materials" panel read the planet's **stored**
`natural_material_model` whenever one existed, and editing elements never
invalidated it. After a planet had been generated once, no edit changed the
panel. Fixed in `WorldGenSimulation.get_preview_payload`: on the crust stage a
stored roster whose `element_profile` differs from the edited composition is
replaced by a live derivation, memoised per composition
(`_live_natural_material_model`). Test:
`test_world_gen_orbit_clicks.test_crust_screen_materials_follow_the_edited_element_distribution`.

### 3.2 Chemistry only gates presence, and the gates are loose

Measured rosters for eight compositions (same tags):

| Composition | Roster | Planetary | Shared with Earth |
|---|---|---|---|
| Earth (template, no traces) | 129 | 43 | 129 |
| Ocean world | 147 | 49 | 114 |
| Cratered airless | 132 | 39 | 114 |
| Metal-core airless | 111 | 33 | 97 |
| Differentiated icy | 140 | 48 | 108 |
| Carbon-rich rocky | 141 | 48 | 107 |
| No Al, alkalis or Ca | 61 | 25 | 58 |
| Sulfur-iron | 76 | 25 | 64 |

- Thresholds are placeholders on a few round values (O 12/14/16/18 %, Si
  4/5/6 %, Al 1-2 %, S 0.01/0.02 %, C 0.02 %). Any silicate crust clears them,
  so about 100 materials are present on every rocky planet.
- The chemistry score saturates at twice the threshold. Nearly every rock
  scores 0.8-0.98 on every silicate composition, so the panel's top-5 lists
  (ranked by confidence) are identical.
- Chemistry never sets *how much* of a material forms: a crust with 30 % S
  and one with 1 % S get the same sulfide abundances. Abundance is a fixed
  ontology number plus code special cases.
- The LOD0 map lets tectonic settings choose rocks; chemistry only removes
  some of them.

### 3.3 Template compositions leave elements out

- The default "Silicate terrestrial" template lists 8 elements and no traces:
  no C, S, P, Ti, Mn, Cl or F. An Earth-like default therefore has no
  limestone, gypsum, sulfides or apatite unless randomisation happens to
  add those traces (adding Earth's real trace levels raises its roster from
  129 to 169 materials).
- Ocean world, cratered airless, icy and carbon-rich templates have no K, so
  granite, rhyolite, arkose, micas and K-feldspars are impossible there.

## 4. Ontology field audit (210 roster-eligible materials)

| Field | Coverage | Quality | Used by |
|---|---|---|---|
| `chemical_formula` | 210 | **101 are prose**, not chemistry: 73 of 79 rocks ("felsic intrusive silicate rock"), 14 of 16 sediments, 9 of 12 regolith types, 5 minerals. Solid solutions use placeholders (amphibole `A0-1B2C5T8O22(OH,F,Cl)2`, garnet `X3Y2(SiO4)3`) | display only |
| `required_element_thresholds` | 210 | Generated placeholder magnitudes (see §3.2); 21 materials ignore formula elements (biotite not gated on Fe/Mg, augite not on Fe/Na/Ti, monazite not on La/Nd/Th); 2 gate on elements their formula lacks | roster gate |
| `required_element_groups` | 7 | fine where present | roster gate |
| `surface_affinity_profile.abundance` | 210 | 25 hand-set values; fixed per material, independent of chemistry | relative abundance |
| `lithotectonic_setting_weights` | 72 | none on minerals (expected); 8 rocks without | LOD0 recipes |
| `mechanical_class` / `mechanical_rock_profile` | 210 | 9 class-level defaults; 32 minerals typed `jointed_volcanic_rock` (chalcopyrite among them), a rock and a mineral typed `massive_ice` | relief retention |
| `optical_surface_profile` | 210 | material-specific (210 distinct) | True Color |
| `natural_material_subclass` | 18 | duplicates `material_subclass` | none found |
| Element entities (92) | — | `rarity` class only; **no quantitative crustal abundance**. The Earth reference lives in code (`crust.EARTH_CRUST_MAJOR_ELEMENTS`, `material_catalog` rarity tables) | tags, trace sampling |

Missing entirely:

1. **Elemental composition of minerals** (mass fraction per element), which
   can be computed from the formula for fixed-stoichiometry minerals.
2. **End-member definitions for solid solutions** (olivine Fo-Fa, plagioclase
   Ab-An, pyroxenes, amphiboles, garnets, micas).
3. **Bulk composition of rocks, sediments and regolith** (major-oxide wt %:
   SiO2, TiO2, Al2O3, FeO(t), MnO, MgO, CaO, Na2O, K2O, P2O5, plus CO2, SO3,
   Cl, H2O where relevant). This is the one field that would let the element
   distribution decide rocks.
4. **Reference crustal abundance per element** (ppm), so an enrichment
   relative to Earth can be computed from the ontology rather than from
   code.

## 5. Proposed design: element distribution -> roster -> abundances

1. **Full element distribution.** Explicit elements as today; every other
   element fills the 1 % trace reserve in proportion to its reference crustal
   abundance, scaled by explicit trace picks. "Not listed" then means
   "Earth-like background", not "absent"; setting an element to zero makes it
   absent.
2. **Mineral availability (ores, accessories, evaporites):** Liebig's law on
   the characteristic elements of the mineral's composition,
   `A = A_ref x clip(min_e(E_planet(e) / E_ref(e)), 0, cap)`. Twice Earth's
   copper gives twice the chalcopyrite; no copper gives none.
3. **Rock availability (bulk units):** a rock needs its bulk chemistry to be
   reachable from the crust by differentiation. For each element, the required
   enrichment is `r = c_rock(e) / E_planet(e)`. Enrichments above what melting
   and fractionation can reach are penalised (about 4x for incompatible K,
   Na, P and Ti; 2x for Fe, Mg and Ca; 1.5x for Si and Al), weighted by the
   element's share of the rock. The result is scaled against the same
   calculation for Earth, `A = A_ref x F(planet) / F(Earth)`, so an Earth
   composition reproduces today's reference abundances.
4. **Roster** = materials whose `A` clears a floor, ranked by `A` (replaces
   the saturating confidence). Environment gates (hydrology, atmosphere,
   volcanism tags in `formation_requirements`) stay as they are.
5. **LOD0 recipes** multiply setting weights by chemistry availability instead
   of only gating, so a K-poor planet's arcs give tonalite and trondhjemite
   rather than granite.
6. **Remove code special cases** (basalt, anorthosite, ultramafic multipliers,
   graphite foundation); they fall out of the chemistry.
7. **Crust panel** shows availability relative to Earth and the limiting
   element per material.

## 6. Decisions needed

1. **Rock chemistry field:** bulk major-oxide composition (recommended:
   standard literature averages, one field, directly comparable with the
   crust), modal mineralogy (mineral fractions; needs every constituent
   mineral's chemistry first), or both.
2. **Reference abundances:** Rudnick & Gao (2003) upper continental crust
   (recommended), or bulk continental crust.
3. **Unlisted elements:** Earth-like background as in §5.1 (recommended), or
   absent unless listed.
4. **Templates:** add realistic minor elements (C, S, P, Ti, Mn, Cl, F, H) and
   restore K where its absence isn't intended.
5. **Mechanical-class cleanup** for minerals: in this change or later.

## 7. Plan once decided

1. Ontology migration tool (`tools/author_material_chemistry.py`, SQLite
   store, full-dict merges, no `.owl` export unless requested): element
   reference abundances; mineral compositions from formulas plus authored
   end-members; bulk compositions for rocks, sediments and regolith;
   thresholds derived from composition (kept only as overrides).
2. `material_availability.py`: element distribution -> availability per
   material; `derive_natural_material_model` and the LOD0 recipes use it; code
   special cases removed.
3. Template minor elements; crust panel showing availability and limiting
   elements.
4. Tests: Earth reproduces reference abundances; removing K removes granite
   and raises tonalite; doubling Cu doubles copper minerals; a sulfur-iron
   crust ranks sulfides and ironstones high. Plus the LOD0 map and Delta-E
   lineage on a non-Earth composition.

## 8. As built

**Ontology** (`tools/author_material_chemistry.py`, live store, no `.owl`
export; re-runnable):

- 92 element cards: `earth_upper_crust_abundance_ppm` (Rudnick & Gao 2003
  upper crust; C 3240 ppm from Wedepohl 1995 so carbonate rocks count; S and
  H, noble gases, Rh, Te, short-lived nuclides from CRC).  Entered from
  memory; unverified against the primary tables.
- 103 minerals and 3 ices: `elemental_composition_wt` from the formula; 31 carry
  `composition_endmembers` (feldspars, amphiboles, pyroxenes, olivine, micas,
  chlorite, garnet, apatite, monazite, ...) or a `computational_formula`.
- 79 rocks, 16 sediments, 12 regolith types: `bulk_composition_wt` (component
  formula -> wt %), `modal_mineralogy_wt` (mineral id -> wt %, `modal_basis`
  normative for glassy and organic rocks) and the derived composition.  The
  modal mineralogy reproduces the bulk chemistry within 7.1 cation wt % for
  every entry (test).
- `required_element_thresholds` are now derived from the composition (the
  crust abundance at which a material falls to 15 % of its Earth
  availability), replacing the placeholders.
- `schema_materials` declares the eight new fields (section "Chemistry").
- Mechanical classes (`tools/author_mechanical_lithology.py`) follow
  subclass and formation category instead of substring matches; 80 materials
  changed (sulfides and oxides no longer "jointed volcanic rock", pumice and
  sinter no longer ice, clastic rocks no longer regolith).
- Rock-specific strength (same tool, 2026-10-05): each of the 79 rocks
  carries `uniaxial_compressive_strength_mpa`, `discontinuity_spacing_m` and
  `durability_index` in its `mechanical_rock_profile`, its own density and
  permeability, and the indices derived from them (`rock_mass_strength_rating`,
  `slope_resistance_index`, `erodibility_index`, ...; `profile_basis`
  `rock_specific_strength_v1`).  Typical values inside published ranges,
  entered from memory; unverified against the primary tables.  Minerals,
  sediments, regolith and ice keep their class profile.  See the
  rock-strength pass in `LOD_Worldgen_Procedure.md`.

**Runtime** (`simulations/world_gen/material_chemistry.py`,
`natural_materials.derive_natural_material_model`):

- `planet_element_distribution`: listed elements as set (a listed zero is
  absent); every unlisted element at its reference abundance.
- `material_availability_detail`: relative to the default Earth-like crust
  run through the same distribution.  Essential elements (>= 2 % of the
  material) must be present; enrichment beyond what differentiation reaches
  (K 4x, Na 3x, Si 1.7x, ...) is penalised quadratically; minor elements a
  material concentrates (>= 1 % share, >= 10x the crust: Cu in chalcopyrite, C
  in limestone) follow stoichiometric Liebig; a crust rich in an element the
  material lacks dilutes it (ramp 2-40 % of the crust, floor 0.3).  Capped at
  10x.  Returns the limiting element and whether it is scarce or diluting.
- Roster: availability >= 0.12; `relative_abundance` = ontology Earth
  abundance x availability; `availability_vs_earth`, `limiting_element`,
  `limiting_kind` on every candidate.  The ultramafic and graphite special
  cases are gone; minerals defined by an exotic enrichment (>= 5 % of the
  crust) that are not bounded deposits become foundational (graphite and
  carbonates on a carbon world, native sulfur and evaporites on a sulfur
  world).  Active volcanism still favours fresh basalt (a process, not
  chemistry).
- Regional occurrences drop candidates whose planet-level prerequisites can
  never be met before the evaluation budget is spent (recorded as
  `rejected: planet_prerequisites`); with background ores in every roster,
  volcanic-only deposits had crowded plausible materials out.
- Crust screen: "Possible Materials" follows the edited distribution, ranks by
  abundance and shows `x2.1 Earth`, `K-limited` or `diluted by S`, with
  enriched entries green and scarce ones amber.
- Templates list realistic minor elements (Earth-like templates exactly the
  reference values, so they read x1); K restored where its absence was not
  intended (ocean, icy, carbon-rich; lunar-like stays K-poor).

Measured rosters (same tags): Earth 210 materials, all at x1; K = 0 removes 51
(granite, K-feldspars, micas, sylvite) and keeps basalt and tonalite; a
100x copper crust puts chalcopyrite at x10; a carbon world has graphite,
diamond (regional), carbonates foundational; a sulfur-iron world 37
materials led by native sulfur, pyrite and evaporites.

Tests: `tests/test_material_chemistry.py` (formulas, background, availability,
ontology completeness and modal consistency, roster behaviour), the crust
screen test in `test_world_gen_orbit_clicks.py`, and the material-map
scenarios (`tools/verify_material_map_scenarios.py`), which pass unchanged.
