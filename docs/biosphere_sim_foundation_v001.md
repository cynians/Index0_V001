# Biosphere Simulation foundation v001

Status: implemented qualitative foundation; not ecologically calibrated.

This pass replaces the generic one-way vegetation update in Bioregion
Simulation with the first closed ecological loop and supplies a deterministic
high-detail target map for development. It does not author or mutate ontology
entities.

## Runtime boundary

`BioregionSimulation` remains the orchestrator. Worldgen or a conforming map
fixture supplies abiotic boundary conditions, while `ProducerSoilEcosystem`
owns transient biological state and fluxes. Durable Biosphere entities remain
recipes and summaries; per-timestep biomass, litter and nutrient values are not
ontology facts.

The implemented loop is:

1. Surface PAR and terrain exposure determine potentially usable light.
2. Leaf area attenuates light through a bounded Beer-Lambert canopy proxy.
3. Water, temperature and mineral nitrogen constrain gross production.
4. Plant respiration and stress-sensitive turnover reduce living biomass.
5. Turnover enters litter.
6. Decomposition transfers litter carbon into soil organic matter and soil
   respiration, and releases a mineral-nitrogen proxy.
7. Production consumes soil water and mineral nitrogen.
8. Living biomass and soil organic matter increase erosion resistance.

The canopy attenuation form follows the established Monsi-Saeki application
of exponential light extinction to leaf area, as republished and translated in
[Monsi and Saeki (2005)](https://doi.org/10.1093/aob/mci052). The temperature
response uses a conventional Q10-style runtime proxy; the broader empirical
basis and limitations of temperature-response formulations are discussed by
[Lloyd and Taylor (1994)](https://doi.org/10.2307/2389824). These references
support the functional forms, not the coefficients chosen for this prototype.

The flux ledger uses `kg m-2`, `g m-2`, and `mm` names so transfers are
inspectable. Historical `plant_biomass`, `plant_health`, `top_moisture`, and
`deep_moisture` fields remain normalized compatibility adapters for the
existing renderer and hydrology prototype.

## Reference target

`simulations/bioregion/reference_site.py` creates the **Temperate Catchment
BioSim Reference Site**:

- LOD4 `Site`, 1 km x 1 km;
- 10 m stated scientific spacing and a 101 x 101 source grid;
- parent ID in the LOD3 `Local` namespace;
- coherent elevation, stream, wetness, temperature, precipitation, soil depth,
  porosity, permeability, pH, salinity, erosion and solar-exposure fields;
- worldgen-compatible model names, including `heightmap_model`,
  `water_cycle_model`, `river_model`, `regolith_soil_model`, material fields,
  `surface_evolution_model`, and abiotic `true_color_model`;
- explicit `authored_reference_fixture` provenance.

The fixture is a target contract. It deliberately does not claim that the
current planetary generator resolved genuine 10 m geography.

## Acceptance criteria and observations

Fixed comparisons use the same terrain and initial vegetation.

- Determinism: identical inputs and duration return identical cell state and
  flux ledgers.
- Response direction: a wet cell must produce more biomass than an otherwise
  identical dry cell.
- Conservation: change in plant + litter + soil-organic carbon equals gross
  production minus plant and soil respiration, within numeric tolerance.
- Bounds: normalized display health, biomass, and water remain within 0..1 and
  fluxes remain finite.
- Spatial contract: the reference site contains at least three soil regimes
  and a resolved wet stream corridor.
- Rendering: the existing production Bioregion renderer must show a visible
  biomass/canopy difference between inherited-moisture and drought treatments.

The 120-day renderer comparison is
`artifacts/biosphere_reference_site_comparison.png`. The inherited-moisture
treatment retained mean biomass of 1.193 kg/m2 and ground-light fraction 0.406;
the paired drought treatment reached 0.488 kg/m2 and ground-light fraction
0.682. These are qualitative model results, not field-calibrated predictions.

## Reproduction

Run:

```powershell
py -m pytest tests/test_biosphere_ecosystem.py tests/test_bioregion_simulation.py -q
py tools/render_biosphere_reference_site.py
```

The app itself was launched with `py -m app.app` and ran normally. The available
desktop-control surface could not expose the Pygame window for navigation, so
the image above is a production-renderer preview, not a live app screenshot.

## Chosen coefficients and unresolved science

The productivity, Q10 respiration, turnover, decomposition, nitrogen-use,
water-use, canopy-extinction and erosion-resistance coefficients are bounded
runtime defaults chosen to make causal directions and transfers observable.
They have not been fitted to a biome or species. This pass therefore makes no
empirical claim about absolute biomass, productivity, drought mortality, soil
carbon or recovery time.

The next scientific step is to replace the generic producer pool with
species/functional cohorts and translate real Species Sim traits and
representative-organism outcomes into these rates. Subsequent work still needs
orbital-to-surface PAR, lateral runoff, groundwater, phenology, dispersal,
competition, decomposer cohorts, disturbance, animals, trophic flows and
parent/child Biosphere aggregation.
