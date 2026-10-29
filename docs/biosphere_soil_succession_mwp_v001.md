# BioSim organic-soil succession MWP

> **Superseded in part, 2026-10-02.** The tier thresholds are now 0.15 / 1.0 /
> 3.0 kg/m² and soil organic matter is a hard limit where the plant stands,
> not a weighted term. The stage table and season counts below describe the
> earlier kernel. See [the terraforming loop](biosphere_worldgen_hookup_v001.md#3-the-terraforming-loop).

Implemented and visually compared on 2026-09-16. This is a deterministic,
qualitative gameplay model of primary succession, not a calibrated pedogenesis,
soil-carbon or community-assembly model.

## Meaning and ownership

The soil contract is deliberately split:

- Worldgen owns the **inorganic substrate**: parent material, depth, porosity,
  permeability, pH, salinity, moisture and spatially distributed natural
  materials. `regolith_soil_model` explicitly lists organic matter, nutrient
  availability, fertility and bioturbation as excluded biological properties.
- BioSim owns the **biological overlay**: surface litter, stable soil organic
  matter, organic fertility contribution and surface stability. These begin at
  exactly zero when `bootstrap_lifeless` is true and never mutate worldgen.

The live ontology was inspected through
`PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()`, the
decoded projection of the authoritative persistent quadstore. It contains
`spec_biomasser_13b`, authored as an engineered lichen with
`succession_roles = [terraforming_bootstrap, primary_pioneer,
soil_crust_builder]`, plus mineral-weathering, biomass-accumulation and surface-
stabilisation roles. No ontology values were changed for this MWP.

## Mechanism

`SoilOrganicMatterField` is a 32 × 32 equal-area field over the current BioSim
domain. Each ecological season, every cell samples continuous population-patch
biomass. A growth-form turnover coefficient transfers a proxy fraction of that
standing biomass into litter. Temperature and moisture control litter
decomposition; 36% of decomposed litter enters stable soil organic matter and
the remainder is respired or mineralised. Exposed, dry soil loses a small
fraction of its stored organic matter. Both pools are finite, non-negative and
serialisable.

These fluxes are biomass-index-driven because BioSim patches do not yet expose
closed organism carbon budgets. They must not be interpreted as conservation-
grade carbon accounting. The older Bioregion `ProducerSoilEcosystem` retains
its separate physical-unit carbon ledger; unifying those two scales is future
work.

Local organic matter gates establishment through four tiers:

| Tier | Default requirement | Runtime growth forms |
|---:|---:|---|
| 0 | 0 kg/m² | authored bootstrap species, lichen, aquatic parallel succession |
| 1 | 0.035 kg/m² | graminoids, forbs, ferns |
| 2 | 0.25 kg/m² | shrubs, subshrubs, succulents |
| 3 | 0.75 kg/m² | trees |

An authored `succession_tier` or
`minimum_soil_organic_matter_kg_m2` takes precedence when present. Otherwise
the table is an explicit runtime default, shown in the species catalogue. The
thresholds and turnover rates are gameplay coefficients selected to make the
feedback legible over tens of seasons. They are not measured limits for the
listed species. Local suitability uses a soft transition around the threshold;
the catalogue unlocks a tier once at least one soil cell fully supports it.

The scientific direction, rather than these coefficients, is supported by
primary-succession evidence: global glacier-foreland chronosequences show soil
organic matter increasing with terrain age and plant inputs, with strong
climate modulation ([Mellor et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8048894/)).
A Venezuelan glacier-forefield chronosequence found changing lichen, bryophyte
and vascular-plant cover together with soil organic matter and nutrient
development ([Llambí et al. 2021](https://www.frontiersin.org/journals/ecology-and-evolution/articles/10.3389/fevo.2021.657755/full)).
Manipulative work also shows that lichen effects on soil carbon and nitrogen
depend on functional traits and climate, so the MWP does not treat every lichen
as an interchangeable fertiliser ([Concostrina-Zubiri et al. 2021](https://nph.onlinelibrary.wiley.com/doi/10.1111/nph.17143)).

## Observable sequence and refinement

The baseline renderer used a green substrate, accumulated a hidden per-lichen
fertility bonus and unlocked every non-lichen species at 6 kg total living
biomass. It could therefore jump directly from a small lichen patch to birch,
and it exposed no litter or organic-matter quantity. The baseline is retained
at `artifacts/soil_succession_mwp/baseline/`.

The MWP comparison uses the live plant catalogue with explicitly labelled
representative treatments: Biomasser 13B, perennial ryegrass, Woods' rose,
silver birch and English oak. This is a mechanism demonstration, not a claim
that those species form a natural assemblage. Fixed runtime state produces:

| Stage | Season | Species present | Supported tier | Mean / max SOM |
|---|---:|---|---:|---:|
| Barren mineral substrate | 0 | none | 0 | 0 / 0 kg/m² |
| Lichen biocrust | 2 | Biomasser 13B | 0 | 0.000275 / 0.022884 kg/m² |
| Herbaceous pioneers | 7 | + perennial ryegrass | 1 | 0.004767 / 0.246875 kg/m² |
| Developing shrub community | 11 | + Woods' rose | 2 | 0.014279 / 0.559245 kg/m² |
| Woodland-capable producer community | 30 | + birch and oak | 3 | 0.200587 / 3.045133 kg/m² |

The first visual pass made the soil response too blocky and allowed tier 2/3
too early. The field was refined from 20 × 20 to 32 × 32 and the shrub/tree
thresholds were separated. The final comparison pairs the actual populated
renderer with a vegetation-suppressed organic-soil diagnostic. Brown-to-olive
tint shows the biological overlay while the barren mineral surface remains
unchanged outside colonised areas.

## Verification and reproduction

Run:

```powershell
py -m tools.render_soil_succession_mwp --output artifacts/soil_succession_mwp/final
py -m pytest tests/test_biosphere_soil_succession.py tests/test_biosphere_builder.py tests/test_biosphere_recruitment.py tests/test_biosphere_vegetation.py tests/test_generated_landscape_biosphere_bridge.py -q
```

Outputs:

- `artifacts/soil_succession_mwp/final/soil_succession_comparison.png` — five
  production-renderer stages plus matching organic-soil diagnostics;
- `01_barren.png` through `05_woodland.png` and their `_soil.png` diagnostics;
- `soil_succession_metrics.json` — exact stage, biomass, litter, SOM and flux
  values.

Tests cover the zero-state/no-life invariant, deterministic accumulation,
ordered tier unlocks, spatial locality, finite/bounded pools, snapshot round
trip, procedural-domain expansion, and preservation of worldgen soil depth, pH
and mineral nutrient values while the biological overlay evolves.

Final verification: 60 BioSim/Bioregion/bridge tests and 23 geochemical/highest-
LOD substrate tests passed. The desktop app launched and remained in its main
render loop, but the Windows automation surface did not expose the Pygame
window. The supplied images are fresh production-renderer previews, not live
navigation screenshots.

## Remaining limits

This is the minimum working process, not a full ecosystem. Its nitrogen and
phosphorus follow-up is documented in
`biosphere_soil_nutrients_species_coupling_v001.md`. Decomposer and microbial
populations remain implicit in the decomposition/mineralization coefficients.
Explicit erosion and leaching transport, humus fractions, root turnover,
disturbance and animals are absent. Succession is
player/experiment-directed through species introductions; it does not invent a
regional species pool or automatic propagule rain. A later pass should connect
authored functional guilds and decomposers, then reconcile this patch-scale
field with the Bioregion carbon-and-nitrogen kernel.
