# World-generation LOD mechanism matrix

Status: design and audit note; no generation behavior is changed by this file.

This document is the working scale contract for the world-generation rewrite.
It separates physical extent, scientific sample spacing, and visible feature
scale. A child map is a refinement of its immediate parent, not a second
independent generation of the same place.

## Immediate findings

The current canonical planet has an 8192 x 4096 render canvas but only a
385 x 193 scientific height grid. On an Earth-sized body this is about 108 km
between samples. The previous 100 km first child therefore covered roughly
one parent cell and mostly inherited a smooth interpolated slope. Its large
render grid did not create new parent-scale geographic information.

The current refinement code also samples the root production tectonic field
again for every child. That preserves some broad truth, but it violates the
desired strict LOD N-1 lineage and makes a root update an implicit dependency
of every descendant. The replacement contract must retain the parent snapshot
and parent fingerprint explicitly, then invalidate or regenerate descendants
deliberately when that snapshot changes.

## Target physical scale contract

The ranges are defaults for an Earth-sized body and should be expressed as a
scale profile, not hard-coded rectangles. A UI zoom selects a footprint inside
the profile. The 100 km diagnostic window belongs at LOD2, not LOD1.

| LOD | Name | Typical footprint | Scientific sample spacing | Complete features that should read here |
|---|---|---:|---:|---|
| 0 | Planet | full body | 10–40 km; 1025 x 513 baseline, 2049 x 1025 benchmark | plates, continents, ocean basins, major mountain systems, global climate, major rivers and lakes |
| 1 | Macroregion | 500–2,000 km | 1–10 km | continental margins, mountain ranges, forelands, large basins, principal river networks, regional climate |
| 2 | Region | 50–250 km; 100 km default test | 100–500 m | range segments, valleys, tributaries, medium lakes, shelves, coast assemblages, material provinces |
| 3 | Local | 5–30 km | 10–100 m | local ridges, gullies, streams, floodplains, beaches, wetlands, dunes, cliffs, local climate |
| 4 | Site | 0.5–5 km | 0.5–10 m | channels, banks, outcrops, talus, fans, soil transitions, site-scale coastal forms |
| 5 | Parcel | 100–500 m | 0.1–1 m | small gullies, terraces, stream banks, local depressions, rock exposures |
| 6 | Plot | 20–100 m | 0.1 m floor | rills, hummocks, minor channels, bank microtopography, ledges, sparse ground-detail anchors |
| 7 | Survey | 5–30 m | 0.1 m floor | shallow hollows, microdrainage, rills, bedrock steps, tide pools, surveyable surface detail |

The profile is intentionally not a promise that every feature exists in every
map. It states the scale at which a feature is allowed to become complete.
Below that scale, its parent influence remains as a boundary condition,
material field, climate field, or slope, while the named complete feature is
no longer expected to be distinguishable.

## Layer contracts

The LOD is a shared scientific context. Render layers are different views of
that context; they are not independent generators and must not quietly use a
different geography, climate, or material assignment.

| Layer | Required inputs | What the image means | Forbidden behavior |
|---|---|---|---|
| Heightmap / relief | Current LOD heightfield, sea level, masks, derivatives | Physical elevation and terrain form at the current footprint | Replacing the parent surface with an unrelated texture or treating render pixels as scientific samples |
| True Color | The same heightfield plus current material heatmap optical profiles, exposure, geomorphology, water, and atmosphere | Material-coloured surface whose luminance and shadows follow the same terrain normals | Independent geology, independent albedo terrain, or use of cartographic material colours as physical reflectance |
| Surface Materials | The same heightfield partition, ontology material IDs, formation/context fields, and material rasters | Analytical categorical/probabilistic material distribution | Presenting geological map colours as True Color or inventing a material field disconnected from elevation/process context |
| Climate / hydrology | Current parent-derived climate grid, water cycle, drainage, rivers, lakes, and local orographic conditioning | Climate zones, water routing, flow, and hydrologic state at the current scale | Reclassifying climate from image colours or drawing rivers unrelated to the current drainage graph |
| Coastal geomorphology | Same elevation/sea level, shoreline graph, waves/tides, sediment and water-cycle fields | Shoreline structure and coastal assemblages | A separate coastline, independent sea level, or border decoration mistaken for geography |
| Temperature / precipitation / weathering diagnostics | Current climate and surface-process fields | Scalar diagnostic views of the same climate/process solution | Decorative gradients that do not correspond to the stored fields |
| Locations / regions / overlays | Ontology-authored or generated spatial entities | Human, political, ecological, or selection context over terrain | Covering or rewriting the scientific terrain surface |

True Color has a stricter coupling rule than the analytical material layer:
material `display_color` and `geological_map_color` are cartographic
properties, while the physical colour contribution comes from each material's
optical surface profile. The True Color recipe must bind to the current
heightfield fingerprint and the exact material-layer/profile set.

## Layer-by-LOD acceptance matrix

The following is the expected visual and scientific behavior. “Inherited” does
not mean invisible: it means that a feature's causal influence, elevation,
slope, material, climate, drainage, and provenance continue even after its
named complete form is too large or too small to identify at that level.

| Layer | LOD0 Planet | LOD1 Macroregion | LOD2 Region | LOD3 Local | LOD4 Site | LOD5 Parcel | LOD6–7 Plot / Survey |
|---|---|---|---|---|---|---|---|
| Heightmap / relief | Continents, ocean basins, major ranges, broad basins | Parent-anchored margins, ranges, forelands, large basins | Range segments, valleys, shelves, medium relief | Local ridges, gullies, streams, floodplains | Channels, banks, outcrops, talus and fans | Small gullies, terraces, local depressions | Rills, ledges, microdrainage and surveyable microrelief |
| True Color | Planetary material provinces, ocean/ice, broad relief and atmospheric context | Follows parent ranges, basin structure, major valleys and material transitions | Preserves inherited ridges/valleys while showing regional lithology, exposure and terrain shading | Shows local rock/cover, slope, moisture and process contrast | Shows outcrops, talus, sediment and channel-side colour | Shows parcel-scale substrate and weathered-cover transitions | Shows only local surface appearance; no complete mountain or continental signature should be fabricated |
| Surface Materials | Broad lithologic provinces and stable material identity | Province boundaries and dominant bedrock/cover classes | Regional mixtures, occurrences and material contacts | Exposure, transported cover and local lithologic units | Outcrops, talus, fans and soil transitions | Small exposures and cover boundaries | Substrate references for sparse objects and microhabitats; no new global province |
| Climate / hydrology | Global zones, circulation proxies, major basins and rivers/lakes | Principal networks, regional climate gradients and large lakes | Tributaries, rain shadows, medium lakes and local water balance | Local streams, ponds, floodplains and microclimate | Channels, banks, runoff concentration and site moisture | Small gullies and bank routing | Rills, minor channels, pools and survey-scale drainage |
| Coastal | Global ocean/land mask, sea level, major shelves and coast | Continental margins and major coastal systems | Shoreline assemblages, shelves, deltas and regional sediment context | Beaches, cliffs, wetlands and local coastal forms | Banks, fans, small beaches and channel mouths | Local shoreline transitions | Tide pools and survey-scale coastal detail where physically supported |
| Temperature / precipitation / weathering | Planetary fields and climate envelopes | Regional gradients and seasonal contrasts | Orographic/rain-shadow and regional process contrasts | Microclimate and local process intensity | Site exposure and soil/weathering transitions | Parcel-scale process differences | Fine local gradients only; no unsupported precision beyond the terrain sample floor |

At every column, a child is `immediate-parent surface + bounded,
scale-specific residual`, with a smooth parent-edge transition. A deeper level
may add smaller structure, but it must not redraw a larger feature from a new
seed or silently replace the parent's geography.

## Existing mechanism inventory

The following mechanisms already exist in the normal world-generation route.
“First LOD” means the first level where the mechanism can be spatially
resolved as a meaningful map feature, not merely stored as a global summary.

| Mechanism | Current implementation | First LOD | Lower-LOD behavior and eventual visibility limit |
|---|---|---:|---|
| Formation/template randomization | Generic, eccentric, gas-giant, and template-driven seeds | 0 | Remains a global boundary condition; never becomes a local map feature |
| Planetary physics | Mass, radius, gravity, density, orbit, spin, radiation | 0 | Feeds every descendant; not independently visible below planetary context |
| Atmosphere and volatile history | Atmosphere composition, pressure, escape proxies, surface regime | 0 | Global and climatic forcing; local descendants inherit pressure and chemistry |
| Interior thermal and tectonic regime | Interior heat, lid regime, hydrologic and resurfacing state | 0 | Becomes inherited forcing; not a local visual feature by itself |
| Pre-present geological history | Rifting, accretion, collision, arcs, breakup, transforms, latent events | 0 | Event identity persists, but complete events/ranges are only spatially visible through their structures |
| Spherical plate partition and motion | Closed seeded plates, Euler poles, neighbours, triple junctions | 0 | Plate boundaries can remain legible at LOD1; local descendants inherit plate ownership and kinematics |
| Boundary classes | Convergent, divergent, transform, subduction, collision, passive margins | 0 | Complete boundary systems read at LOD0–1; only local fault/relief expressions remain at LOD2+ |
| Cratons, terranes, sutures, rifts, basins, embayments | Seeded continental process fields and tectonic-conditioned lithosphere | 0 | Provinces and margins read at LOD0–1; individual structures become regional at LOD2–3 |
| Hotspot and island chains | Age-progressive seeded hotspot chains | 0 | Chains read at LOD0–1; individual edifices/islands resolve at LOD2–4 |
| Orogen systems | Coherent boundary grouping and cross-range forcing | 0 | Whole ranges read at LOD0–1; range segments at LOD2; local ridge/valley structure below |
| Deformation, flexure, and isostatic response | Separate coarse uplift, subsidence, strain, loads, flexural and isostatic fields | 0 | Remains an inherited field; its complete broad response is not expected below LOD2 |
| Mechanical lithology | Material-derived planetary mechanical classes and relief response | 0 | Broad relief retention at LOD0; differential slopes and exposures become visible at LOD2–4 |
| Crater field and impact gardening | Explicit craters, size filtering, atmospheric/water preservation, degradation | 0 | Large basins at LOD0–1; regional craters at LOD2–4; microcraters only at LOD5–7 on airless surfaces |
| Primary heightfield | Production tectonic height sampler, crustal fields, bounded noise, craters | 0 | Broad elevation must be inherited at every level; added wavelengths belong only to the child scale |
| Mountain relief | Boundary profiles, orogen forcing, branching/fractal detail, relief limits | 0 | Complete mountain ranges at LOD0–1; segments/ridges at LOD2–4; only slopes, ledges, and microrelief at LOD6–7 |
| Ocean volume and sea level | Water inventory, hypsometry, sea-level solve, ocean/land masks, shelves | 0 | Coast and shelf remain inherited; complete ocean basins disappear below LOD1 |
| Ice and snow | Inventory-ranked ice mask, seasonal snow, ice-albedo feedback, glacial proxy | 0 | Ice caps at LOD0; glacier regions at LOD1–2; snowfields and ice margins at LOD3–5 |
| Orbital and seasonal climate | Latitude, insolation, atmosphere, temperature, seasonality, circulation proxies | 0 | Climate zones at LOD0–1; regional climate at LOD2; microclimate at LOD3–4 |
| Ocean heat and wind/moisture forcing | Ocean circulation and climate-grid transport proxies | 0 | Large circulation belongs at LOD0–1; local windward/rain-shadow effects at LOD2–4 |
| Drainage and watersheds | Priority-flood routing, flow directions, accumulation, basins, catchments | 0 | Major basins at LOD0–1; tributary networks at LOD1–2; channels and microdrainage at LOD3–7 |
| Lakes and outlets | Water-balance-constrained lakes, spillways, endorheic state | 0 | Great lakes at LOD0–1; regional lakes at LOD2–3; ponds and pools at LOD4–7 |
| Rivers and sediment routing | Branching rivers, stream order, discharge, deltas, distributaries, sediment proxies | 0 | Major rivers at LOD0; principal networks at LOD1; tributaries at LOD2–3; channels/banks at LOD4–7 |
| Surface evolution | Fluvial, chemical, aeolian, glacial, hillslope, crater degradation, deposition, incision | 0 | Global process fields at LOD0; landform-producing feedback at LOD1–3; local forms at LOD4–7 |
| Coastal geomorphology | Shoreline graph, wave/tide proxies, relative sea level, sediment budgets, gated landforms | 0 | Shorelines/shelves at LOD0–1; coast assemblages at LOD2–3; beaches, cliffs, deltas at LOD3–5; tide pools at LOD7 |
| Surface geomorphology | Ridges, valleys, scarps, incised valleys, talus, alluvium, mantled plains, exposure | 0 | Broad interpretation at LOD0; complete regional landforms at LOD1–3; local exposure/talus at LOD4–7 |
| Natural material formation | Ontology materials inferred from crust, tags, atmosphere, regime, water, temperature | 0 | Material identity persists everywhere; only spatial exposure becomes finer with LOD |
| Material provinces and heatmaps | Affinity layers, compact raster bundles, regional occurrence selection | 0 | Provinces at LOD0–1; regional mixtures at LOD2–4; surface exposure/soil at LOD4–7 |
| Mineralization potential | Tectonic/mineralization proxy and regional occurrences | 0 | Broad potential at LOD0–1; deposits become meaningful at LOD2–5; mine geometry is not yet present |
| Regolith and soils | Material-, climate-, hydrology-, and terrain-conditioned soil model | 0 | Planetary soil tendency at LOD0; profiles and transitions at LOD3–6; organic horizons are future |
| Specialized abiotic landforms | Desert morphology, duricrust, karst, periglacial ground, playa/evaporite basins, plume-lid features | 0 | Regime/province summaries at LOD0–1; complete landforms at LOD2–5; grains and objects are future |
| True Color and material optics | Heightmap, exposure, geomorphology, material endmembers, weathering, water and atmosphere | 0 | Must render at every LOD from the immediate parent-derived height/material fields; it must not invent independent geology |
| Diagnostic map layers | Heightmap hillshade, True Color, surface materials, climate/rivers, coastal geomorphology, temperature, precipitation, chemical weathering | 0 | Visibility changes with scale; each layer must report inherited inputs and missing assets rather than silently fall back |

## Mechanisms required but not yet complete

These are either named in the concept document or required to make the scale
contract scientifically useful:

- A first-class formation-theory route: condensation fronts, disk metallicity,
  formation versus present orbit, core accretion, gas capture, late delivery,
  volatile loss, and thermal evolution.
- Dynamic plate topology and geological-structure inheritance. Current plate
  motion mostly moves centres and recalculates kinematics; it does not fully
  deform persistent faults, folds, units, or boundaries through time.
- Persistent 2.5D geological columns and vector structures: faults, folds,
  detachments, shear zones, intrusions, volcanic centres, basin boundaries,
  bedding, foliation, metamorphic cores, and crustal roots.
- A spatial mechanical-rock contract with strength, cohesion, friction,
  permeability, fracture/jointing, bedding, foliation, and nonlinear
  erodibility rather than only a planetary prior.
- Stateful landscape evolution: mass-conserving sediment transport, landslides,
  debris transfer, nonlinear slope thresholds, transport capacity, fans,
  floodplains, knickpoints, divide migration, river capture, glacier flow,
  basal thermal state, and erosion/deposition-driven isostatic feedback.
- A spatial dynamic-topography field and a reusable volcanic-edifice model for
  supply, composition, vent migration, collapse, calderas, and age.
- Full or staged groundwater/aquifer and permeability coupling, glacier mass
  balance, ice-dammed lakes, variable lake chemistry, and transient floods.
- Higher-fidelity ocean/climate processes: full GCM/CFD, seasonal sea-ice and
  wave coupling, harmonic tides, spectral wave transformation, storms,
  tsunamis, and long-term coast migration with stratigraphy.
- Process-based deposit genesis: intrusions, hydrothermal fluids, redox fronts,
  sedimentary and metamorphic history, geometry, tonnage, and preservation.
- Biological occupation: vegetation, organic soils, reefs, marshes, mangroves,
  Biosphere/BioSim populations, and sparse deterministic ground objects.

## Parent-child invariants for implementation

1. LOD0 is the canonical full-planet snapshot. It contains the broadest
   reproducible variation and stores the global fields needed by every child.
2. LOD N stores `parent_map_id`, `parent_heightfield_fingerprint`,
   `parent_material_fingerprint`, `source_uv_bounds`, and the exact scale
   contract used to create it.
3. LOD N samples only LOD N-1 for inherited elevation, topology, climate,
   hydrology, materials, and structures. Root data may remain in the ancestry
   record for audit, but it is not a second live input to child generation.
4. A child is `parent_surface + bounded_scale_specific_residual`; the residual
   must be zero or smoothly reduced at the parent patch boundary.
5. Changing LOD0 marks descendants stale by fingerprint. It does not silently
   rebuild every descendant or leave descendants falsely marked current.
6. Every child model and raster must be generated in the same isolated asset
   namespace as its persisted region, so True Color and other layers can be
   replayed without hidden shared project files.
7. A mechanism may become visually incomplete at a deeper LOD, but its causal
   influence and provenance continue through the parent contract.
