# Biosphere Builder redesign v0.1

## Product thesis

BioSim is a biological city builder played directly on the current map. The player does not paint a finished biome. They introduce species and interventions into inherited terrain, then observe establishment, competition, succession, dispersal, failure and ecosystem services through time.

The map is the world, not a launcher for a separate square-grid ecology screen.

## Replace the old architecture

The legacy `BioregionSimulation` bundled map scale, environmental cells, weather, vegetation visuals, species selection and ecological state into one prototype. It remains useful as reference code, but it is no longer the product boundary.

The redesign has three independently inspectable layers:

1. **Substrate** — inherited map/worldgen facts: geometry, elevation, hydrology, soil, exposure, climate and disturbance history.
2. **Plan** — player-authored introductions and interventions: species, footprint, propagule pressure, timing and method.
3. **Outcome** — simulated, disposable state: abundance, biomass, establishment, competition, spread and ecosystem services.

Only the plan is analogous to construction orders in a city builder. A placement is never proof that a species survives.

## Core play loop

1. Read terrain and diagnose limiting factors.
2. Choose a species from the ontology-backed palette.
3. Place an introduction footprint on the map.
4. Run the clock at the desired speed and watch seasonal succession unfold.
5. Inspect where the introduction established, failed or spread.
6. Add complementary species or interventions and compare trajectories.

The first implemented vertical slice supports steps 2–5. It uses an authored high-detail target substrate expressed with worldgen nomenclature until worldgen can produce reliable site-scale data.

## City-builder translation

| City builder concept | Biosphere Builder concept |
|---|---|
| Terrain and zoning | Habitat substrate and protected/excluded areas |
| Building catalogue | Species and intervention palette |
| Construction order | Propagule introduction |
| Construction progress | Germination and establishment |
| Utilities | Water, light, nutrients and trophic support networks |
| Coverage | Canopy, roots, pollination, decomposition and habitat services |
| Traffic/flow | Dispersal, runoff, nutrient transport and animal movement |
| Growth phases | Seasonal succession and life-history transitions |
| Hazards | Drought, fire, disease, invasion and collapse |
| City statistics | Diversity, resilience, biomass, services and maintenance cost |

## Simulation boundaries

- SpeciesSim owns organism-scale morphology, physiology and representative life histories.
- Worldgen owns physical substrate generation and its scale-dependent projections.
- SpaceSim supplies incident stellar energy and orbital/seasonal forcing.
- Biosphere Builder owns population cohorts, spatial interactions, ecological networks, interventions and succession.
- The ontology owns authored identity and traits. Runtime defaults are visibly labelled and never persisted as facts.

## Spatial and temporal model

The builder operates in continuous metres inside the map footprint. An introduction creates an irregular circular population patch with a free-coordinate centre, radius and abundance. Growth expands that footprint and deterministic satellite patches model dispersal; overlapping footprints provide continuous competition. There is no ecology or placement grid, and neither populations nor representatives carry row/column addresses.

The play surface uses a 2:1 isometric projection. The terrain diamond, population footprints, shadows and upright SpeciesSim plants share one world-to-screen transform; plants are depth-sorted by their continuous world position. Pointer placement uses the exact inverse transform, so the apparent ground point is the simulated point.

The initial clock is seasonal. Later, processes use separate stable cadences:

- event cadence for placement, removal, fire and disturbance;
- seasonal cadence for establishment, growth and dispersal;
- annual cadence for succession, soil development and population viability;
- slow cadence for geomorphology and climate coupling.

## Implemented v0.1

- `BiosphereSimulation` subclasses the current `MapSimulation` and therefore uses map navigation, scale, terrain layers and rendering.
- The ontology-backed species catalogue feeds the palette; a four-species fallback exists for the reference fixture, including the engineered lichen bootstrap.
- Click placement creates a `SpeciesIntroduction` with location, radius, pressure and season.
- A deterministic continuous ecology kernel models habitat suitability, growth, overlap competition and satellite dispersal.
- Derived population footprints render as translucent irregular ground patches beneath representative individuals.
- Persistent representatives emit deterministic scene instances rendered through SpeciesSim's plant blueprint, growth snapshot and authored organ-sprite pipeline.
- Succession runs on a continuous real-time clock with pause, 1×, 4× and 16× controls; one season is 30 real seconds at 1× in the current gameplay tuning.
- Missing ecology traits use growth-form defaults with explicit provenance.

## Lifeless-world bootstrap and representatives

A newly drawn biosphere polygon with no species roster or distribution is treated as a selection envelope, not an already living biome. BioSim derives one reproducible pseudo-random point inside that polygon and opens a local 10×10 m founding patch around it. The source-map point is retained in launch context so later worldgen adapters can sample the correct terrain.

The initial species menu contains only Biomasser 13B. Living biomass and occupied area grow from the placed introduction. At 6 kg of living biomass the pioneer palette unlocks; this is an explicit gameplay threshold, not a biological constant.

The numerical domain begins at 10×10 m. When a population footprint reaches an edge, the solver grows the continuous domain around it without moving populations or representatives. Expansion stops at the selected polygon envelope's projected extent (with a 1 km prototype safety cap). This separates the initially living footprint from the much larger area the player selected.

Every spatial species population maintains up to four persistent representatives. These are real `SpeciesSimulation` instances with stable IDs, seeds, ages, health and reproduction history. Each season:

1. population abundance and local map environment provide moisture, light, competition and disease pressure to each representative;
2. SpeciesSim advances the organism and returns vitality, fecundity and mortality risk;
3. the representative manager aggregates those outcomes;
4. the population solver uses that feedback to modify growth, mortality and dispersal;
5. changed population state becomes the representatives' environment on the next season.

Representative sprites are selectable on the map and in the population panel. The selection inspector can open the exact live representative instance in SpeciesSim, rather than starting an unrelated generic preview.

## City-builder interface

BioSim uses a dedicated map overlay instead of inheriting the generic Map Tools menu. Aggregate biomass, colonised area, population count and deep-lived representatives are grouped in the top status bar. Population tools and representatives occupy the left management panel. The active planting tool, seasonal clock, progress and acceleration controls form a bottom command dock, leaving the centre of the map as the primary play surface.

The species catalogue is a modal full-screen picker. Its paged list includes the complete available plant catalogue and visible succession locks. Focusing an entry produces a deterministic SpeciesSim organism preview and lists its authored description, growth form, seasonal growth, dispersal, carrying biomass, moisture niche, minimum light, succession role and trait provenance. Confirming an available species closes the picker and arms it as the active planting tool; modal input cannot leak through into map placement.

This hybrid design is closest to a small deterministic set of persistent super-individuals coupled to an aggregate population field. The design rationale follows the super-individual approach described by [Scheffer et al. (1995)](https://doi.org/10.1016/0304-3800(94)00055-M). Model components and scheduling are documented explicitly in the spirit of the ecological ODD protocol described by [Grimm et al. (2006)](https://doi.org/10.1016/j.ecolmodel.2006.04.023). Those references support the architecture, not the prototype coefficients.

## Asset test forest

The deterministic `BioSim: Reference Site` launch is a visual integration fixture. It scans resolved plant entities for module and texture references that exist on disk, lays every matching species out at staggered free coordinates, and matures its deep representatives for immediate inspection. The current ontology resolves eight asset-backed plants: *Codonorhiza elandsmontana*, English oak, European white water lily, blue water lily, perennial ryegrass, Woods' rose, sessile oak and silver birch. This fixture deliberately bypasses succession locks; polygon-founded gameplay biospheres still begin lifeless with Biomasser 13B.

## Authority, acceptance and reproduction

`spec_biomasser_13b` is authored in the authoritative decoded live quadstore as an engineered lichen species derived from *Lecanora muralis* stock and associated with TELOS. Its seasonal growth, dispersal, carrying-biomass and habitat-preference values are explicitly fictional gameplay parameters. The RDF/XML checkpoint `ontology/index0.owl` did not contain this entity immediately after persistence; it is a lagging checkpoint, not the source used for this verification.

The implemented slice is accepted when:

- a placed population creates no more than four persistent, deterministic representatives;
- population abundance and local environment affect each representative's deep simulation;
- aggregated vitality, fecundity and mortality affect the next population season;
- representatives age across seasons and the selected sprite opens that exact live simulation;
- a lifeless polygon launch begins with a reproducible point inside the polygon, a 10×10 m domain, zero accumulated biomass and only Biomasser available;
- pioneer plants unlock at the visible biomass threshold; and
- edge colonisation enlarges the numerical domain without moving representatives or losing population state;
- isometric screen/world transforms round-trip free coordinates; and
- the reference test forest includes every plant whose authored module asset resolves on disk.

Focused verification:

```powershell
py -m pytest tests/test_biosphere_builder.py tests/test_navigation_building.py tests/test_map_picking.py tests/test_map_ui_workspace.py tests/test_species_simulation.py tests/test_forest_ecology.py -q
py tools/render_biosphere_ui_preview.py
```

The production-renderer comparison is `artifacts/biosphere_isometric_asset_forest.png`.

## Next vertical slices

1. Replace the reference environment sampler with adapters for inherited heightmap, runoff, regolith/soil, climate and surface-exposure rasters.
2. Add inspect mode with point-sampled limiting factors and species outcome explanations.
3. Add placement tools for patches, lines/corridors and density brushes.
4. Add intervention catalogue: watering, shade, soil amendment, deadwood, fire and containment.
5. Add functional guilds and ecological networks: producers, decomposers, pollinators, herbivores and predators.
6. Add scenario branches and before/after comparison without mutating ontology facts.
7. Persist plans as dedicated scenario entities only after the transient design workflow is stable.
