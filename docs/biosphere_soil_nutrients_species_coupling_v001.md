# BioSim soil nutrients × SpeciesSim MWP

Implemented and visually compared on 2026-09-16. This extends the organic-soil
succession slice with explicit nitrogen and phosphorus state. It is a bounded,
deterministic gameplay model, not a calibrated nutrient budget.

## Contract and ownership

Worldgen now exports two immutable **parent inventory potentials**,
`parent_nitrogen_index` and `parent_phosphorus_index`, from the local
geochemical element profile. These are not plant availability or fertility.
BioSim initializes and owns the changing pools:

- litter N and P;
- organic N and P;
- plant-available N and P;
- a finite weatherable mineral-P reserve.

The original worldgen arrays are sampled but never mutated. A lifeless map has
zero litter, SOM, organic N and organic P. Atmospheric N deposition and slow
mineral-P weathering are explicit abiotic fluxes, so plant-available pools may
change without life while every biological flux remains zero.

## Species field contract

The live decoded ontology was inspected before implementation. The shared
`PlantBlueprint.growth` contract now carries these existing fields:

| Field | Runtime use | Missing-value behaviour |
|---|---|---|
| `nitrogen_fixation` | `active` and `associated` provide bounded N response and fixation flux | no fixation |
| `mycorrhizal_type` | changes access to existing available P and the mineral-P weathering rate | neutral multiplier |
| `root_architecture` | fibrous/adventitious systems favour topsoil-P access; tap/mixed systems favour deeper N access | neutral |
| `root_depth_class`, `max_root_depth` | fallback resource-exploration geometry | neutral intermediate fallback |
| SpeciesSim root depth/spread | replaces the fallback when an actual representative has resolved roots | fallback remains visible |
| `nutrition_mode` | transported through the blueprint for the next trophic/decomposer pass | no effect in this MWP |

No live plant currently authors `nitrogen_fixation = active` or `associated`.
Consequently the rendered live-catalogue run reports exactly zero biological N
fixation. Active fixation appears only in a labelled controlled test/probe; the
runtime does not infer it from a species name, growth form, or pioneer role.

The same `resolve_plant_nutrient_response()` function is used at both scales:

1. BioSim combines local N/P pools with the profile's authored traits to limit
   patch suitability using the more limiting nutrient.
2. Representative SpeciesSim organisms receive the same local pools. Their
   actual generated root depth and spread produce N/P response, stress,
   limiting nutrient and provenance diagnostics.
3. Mean vitality/fecundity/mortality returns to BioSim as population growth and
   dispersal feedback. Mean root exploration returns to the soil field, where
   it affects uptake and P release during the following seasonal step.

This closes the intended soil → individual → population → soil loop without a
second species-trait interpretation.

## Fluxes and safeguards

Plant turnover moves explicit runtime-default tissue N/P concentrations into
litter. Decomposition partitions litter nutrients between organic and
plant-available pools; organic pools mineralize slowly. Living biomass draws
down available N/P. Authored N fixers add atmospheric N. Roots and mycorrhizae
can accelerate transfer from the finite mineral-P reserve, but cannot create P.
All pools are non-negative, finite, serializable and spatial.

These coefficients are deliberately qualitative. Plant-specific tissue
stoichiometry, microbial biomass, sorption/desorption, gaseous N loss,
leaching/runoff transport, pH-dependent P chemistry and decomposer populations
remain future work. Scientific evidence also cautions against a universal
"early succession is N-limited" rule: field and microcosm experiments found P,
not N, limiting the earliest succession at cold-arid glacial sites
([Darcy et al. 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC5966225/)).
Controlled root experiments found topsoil-foraging architectures favoured P
acquisition while deeper systems favoured deep resources
([Ho et al. 2005](https://pure.psu.edu/en/publications/root-architectural-tradeoffs-for-water-and-phosphorus-acquisition/)).
Radiotracer experiments showed that mycorrhizal plants could acquire phosphate
from very P-deficient soils that some non-mycorrhizal plants did not
([Mosse et al. 1973](https://nph.onlinelibrary.wiley.com/doi/abs/10.1111/j.1469-8137.1973.tb02056.x)).
These sources support the direction of the mechanisms, not the numerical
coefficients used here.

## Observable comparison

The pre-change organic-only image and metrics are retained under
`artifacts/soil_nutrients_mwp/baseline/`. The final six-panel production-renderer
comparison is at
`artifacts/soil_nutrients_mwp/final/soil_nutrient_comparison.png`: lifeless and
season-15 states are each shown as organic matter, available N and available P.
The matching JSON records all soil fluxes, representative feedback and clearly
labelled controlled trait probes.

In the deterministic reference run, the lifeless substrate starts with 0 SOM,
0 organic N, 0 organic P, 0.0213 g N/m² available and 0.0411 g P/m² available.
At season 15, the introduced lichen/ryegrass community has 0.02753 kg SOM/m²,
0.320235 g organic N/m² and 0.032272 g organic P/m² on average. Biological N
fixation remains 0 because neither live species authors that trait. Ryegrass
representatives return resolved root geometry and mean N/P responses of 0.9060
and 0.9327.

## Verification

```powershell
py -m tools.render_soil_nutrients_mwp --output artifacts/soil_nutrients_mwp/final
py -m pytest tests/test_biosphere_soil_nutrients.py tests/test_biosphere_soil_succession.py tests/test_biosphere_builder.py tests/test_biosphere_recruitment.py tests/test_biosphere_vegetation.py tests/test_generated_landscape_biosphere_bridge.py -q
```

Tests cover ontology-to-blueprint field transport, fingerprint changes,
nutrient-limited SpeciesSim vitality, fixation opt-in, mycorrhizal P access with
no P creation, lifeless controls, living uptake/cycling, non-negative finite
pools, snapshot round trips, representative feedback and worldgen inventory
fields. The focused suite passes 53 tests; the expanded SpeciesSim, root,
geochemistry and highest-LOD regression selection passes 139 tests plus 28
subtests.
