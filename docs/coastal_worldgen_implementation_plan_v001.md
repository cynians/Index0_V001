# Coastal World Generation and Storage Implementation Plan

Version: v001  
Date: 2026-07-22  
Status: Implemented

## Implementation record

Implemented in July 2026 across the production world-generation, regional-refinement, map, headless-validation, and storage paths.

- `storage_policy.py` defines guarded roots and temporary/retained/pinned lifecycles.
- `.i0wg` bundles provide atomic, checksummed single-file headless output and report/replay readers.
- The legacy 133-file Sol benchmark was migrated to the validated pinned `solar-system-benchmark.i0wg` bundle.
- Canonical `.i0r` generation now uses validated atomic replacement and records owner, input, generator, layer-hash, and creation metadata.
- `refresh_heightmap_derivatives()` supplies volume-balanced sea level, rebuilt masks, spherical hypsometry, shelves, and source fingerprints for planetary and regional products.
- `coastal_geomorphology.py` supplies the shoreline graph, causal measurements, reduced wave/tide/relative-sea-level models, sediment budgets, multiaxial classification, delta/estuary enrichment, and regional landform materialization.
- Planets and generated regions persist coastal models and summaries; older saved worlds rebuild stale derivatives on access.
- The map and headless renderer expose coastal assemblages, wave/tidal indicators, longshore transport, confidence, and coastal reports.
- Scientific fixtures and storage invariants cover deterministic IDs, causal gates, seam behavior, biosphere gating, canonical file counts, bundle validation, and production-route integration.

The July 2026 multiscale corrective update additionally separates morphology from geologic character, inherits a stable coastal-system identity across refinements, bounds relief by physical footprint and inherited coastal regime, introduces Site-to-Survey feature gates, removes sub-resolution coastal checkerboards, preserves non-wrapping local patch edges, marks every next child footprint in benchmark renders, removes duplicate embedded regional heightmaps from persisted surface-evolution records, and scales feedback iteration count by scientifically meaningful map level.

The explicitly deferred high-fidelity items at the end of this document remain deferred.

## Outcomes

This plan delivers two connected changes:

1. Replace threshold-and-noise coastlines with a deterministic, multiaxial coastal geomorphology model derived from existing tectonic, topographic, oceanographic, climatic, hydrological, cryospheric, and material state.
2. Stop world generation and validation from producing persistent directory trees and orphaned assets by separating durable world truth, reproducible derived assets, and disposable diagnostics.

The ordinary player-authored world-generation boundary remains the first screen. Coast types, wave and tidal regimes, sediment budgets, and landforms are derived results rather than new authored controls.

## Completed cleanup baseline

The pre-implementation cleanup retained only:

- `artifacts/headless_worldgen/solar-system-benchmark`
- Faux-Sol `.i0r` material bundles
- tracked Earth and Solar System reference data

All other headless generation runs and root material bundles were removed. The cleanup removed 38 obsolete run trees, 1,530 artifact files, 33 non-Sol root raster bundles, several empty legacy material directories, and approximately 2.9 GB of generated data. These outputs were untracked and are not recoverable through Git.

## Governing decisions

### Scientific model

- A coast is represented by several compatible classifications, not one exclusive coast-type enum.
- The planetary model stores durable causal summaries and shoreline segment scaffolds. Finer landforms are materialized only at a map scale that can resolve them.
- Biological landforms remain gated. World generation may produce reef, mangrove, salt-marsh, or oyster-reef accommodation potential, but a Biosphere result is required before those landforms become biologically occupied.
- Reduced-physics results must expose confidence and causal inputs. Missing satellite data may reduce tidal confidence; it must not trigger an arbitrary tidal regime.
- The coastal model initially diagnoses the final surface without changing it. Terrain-changing coastal refinement follows only after classification is stable and tested.

### Storage model

Generated data is divided into three storage classes:

1. **Durable world truth** — entity identity, first-screen input contract, deterministic seeds, model versions, compact causal summaries, shoreline segment IDs, and authored overrides. This remains repository-backed.
2. **Derived reproducible assets** — height/material/coastal raster layers and regional chunks. These live in one versioned bundle per planet or region family and may be regenerated from durable truth.
3. **Diagnostic artifacts** — stage screenshots, contact sheets, isolated replay repositories, timing traces, and comparison reports. These are temporary by default and retained only when explicitly requested or pinned as a golden benchmark.

Sol is the first pinned benchmark. Pinned outputs are exempt from ordinary retention and garbage collection.

The first two-coast L0-L7 validation run used 103.6 MB of temporary repository storage. Cleanup prevented that footprint from becoming persistent, but the footprint itself is too large for the intended number of generated planets. Follow-up storage work must measure serialized fields by owner and stage, remove duplicated parent truth from child records, compress or quantize regenerable grids, store regional refinements lazily, and enforce per-planet plus aggregate byte budgets. Retention policy controls lifetime; it does not replace storage-density optimization.

The corrective single-coast run measured a 51,981,725-byte uncompressed planet JSON snapshot and a 2,888,671-byte compressed no-image `.i0wg` bundle. The temporary regional benchmark repository emitted no retained entity files, and only the explicitly retained image/report set survived cleanup. This demonstrates the preferred lifecycle, but player-world durable storage still needs the same compressed/lazy representation rather than a 52 MB plain snapshot per planet.

## Target generation sequence

1. Generate tectonic and geological history.
2. Generate heightfield and solve sea level against water volume.
3. Generate ocean circulation, climate, drainage, lakes, rivers, and first-pass deltas.
4. Run the existing two bounded climate-landscape feedback iterations.
5. Refresh all sea-level-dependent heightmap derivatives.
6. Extract a stable shoreline graph.
7. Derive coastal forcing, substrate, and sediment-budget fields.
8. Classify shoreline segments and enrich delta/estuary records.
9. Persist the compact planetary coastal model and refresh provenance, materials, soils, realism audit, and summaries.
10. During regional refinement, inherit parent coastal segments and materialize scale-appropriate landforms.
11. Reconcile local drainage once after terrain-changing coastal refinement.
12. Render the coastal layer from persisted generated truth.

## Workstream A — Storage containment and lifecycle

This workstream runs first so coastal validation does not recreate the deleted sprawl.

### A1. Storage policy and paths

- Add a small storage-policy module shared by UI world generation, headless generation, batch tools, and regional refinement.
- Make repository paths explicit rather than inferring durable output from the source checkout.
- Keep ordinary diagnostic work under an ignored cache or operating-system temporary directory.
- Require an explicit `--output`, `--retain`, or pinned benchmark configuration before diagnostics persist.
- Add path-scope validation before cleanup, replacement, pruning, or garbage collection.

### A2. Single-file headless run bundle

- Introduce a versioned `.i0wg` ZIP bundle, following the existing `.i0r` bundle pattern.
- Store `manifest.json`, input contract, summary, planet snapshot, fingerprints, optional regional snapshot, and optional rendered images inside the bundle.
- Generate through an isolated temporary repository, close all handles, write the final bundle atomically, and remove the temporary tree on success or handled failure.
- Default to summary and fingerprints without screenshots. `--render` and `--retain-debug` opt into heavier diagnostics.
- Convert the retained Solar System benchmark to a pinned bundle once bundle reading and report tooling are ready.

### A3. Canonical derived-asset lifecycle

- Preserve one deterministic `.i0r` bundle path per canonical planet instead of appending new files for every regeneration.
- Write replacements to a temporary sibling, validate the manifest, then atomically replace the active bundle.
- Record owner entity ID, input fingerprint, generator version, layer hashes, and creation time in the bundle manifest.
- On planet deletion, ID change, or regeneration invalidation, remove the old bundle only after confirming no entity still references it.
- Add a repository maintenance command that reports and optionally deletes orphaned bundles, stale temporary files, and unpinned expired diagnostics.

### A4. Retention and regression protection

- Support `temporary`, `retained`, and `pinned` retention classes.
- Apply age/count/byte limits only to temporary diagnostics.
- Keep tests in temporary directories.
- Change batch tools to produce one bundle per run or series rather than nested run repositories.
- Add tests proving that repeated generation of the same planet does not increase the canonical derived-file count.

## Workstream B — Heightmap derivative correctness

### B1. Shared derivative refresh

Extract a shared `refresh_heightmap_derivatives()` operation from `heightmap.py`.

For planetary maps it must:

- Re-solve sea level from conserved equivalent global water depth after surface evolution.
- Rebuild land, ocean, ice-adjacency, and coastal masks.
- Recalculate area-weighted hypsometry and ocean fraction.
- Recalculate shelf width, depth, gradient, and sediment-wedge fields.
- Preserve longitude wrapping and avoid double-counting the duplicate seam column.

For regional maps it must inherit the planetary sea-level datum and recompute only local masks and morphology.

### B2. Compatibility

- Keep existing heightmap fields readable.
- Add explicit model versions and source-heightfield fingerprints to derived fields.
- Rebuild missing or stale derivatives when an older saved world is opened, without changing its deterministic parent truth.

## Workstream C — Shoreline graph and measurements

### C1. Extraction

- Extract the sea-level contour into connected, ordered shoreline chains.
- Resolve longitude-seam continuity and spherical segment length.
- Orient each chain consistently and calculate landward/seaward normals.
- Split chains at meaningful changes in tectonic setting, relief, exposure, substrate, river influence, or scale-appropriate curvature.
- Assign stable segment IDs derived from planet ID, parent coastline component, normalized position, and model version.

### C2. Segment measurements

Persist compact measurements for:

- Length and bounding geometry
- Inland relief and slope
- Nearshore gradient and shelf width
- Headland, embayment, enclosure, and archipelago indices
- Adjacent ocean basin and river mouths
- Ice, glacial erosion, volcanic, carbonate, and permafrost influence
- Local material and erodibility proxies
- Classification confidence and causal source fields

## Workstream D — Coastal forcing and sediment budget

### D1. Wave climate

- Derive prevailing wind direction and storm-energy proxy from existing atmospheric/climate state.
- Ray-cast directional open-water fetch within the connected ocean basin.
- Estimate significant wave-height class, peak-period class, breaker exposure, and shoreline incidence angle.
- Derive longshore-transport direction and capacity without claiming full spectral wave resolution.

### D2. Tidal regime

- Calculate astronomical tidal potential from stellar forcing and available satellite mass/orbit data.
- Apply reduced basin, inlet, and shelf amplification.
- Persist tidal range estimate, micro/meso/macro class, and confidence.
- Version the generation input contract if additional satellite facts become required for deterministic replay.

### D3. Relative sea level

- Derive long-term uplift/subsidence tendency from tectonic setting, sediment loading, isostatic ice influence, and geological history.
- Combine it with bounded eustatic history to classify emergent, stable, and submergent segments.
- Keep precise rates out of Tier 1 unless the inputs justify them.

### D4. Sediment and substrate

- Route river-supplied sediment from catchment erosion and discharge.
- Add cliff, glacial, aeolian, volcaniclastic, and carbonate sediment sources.
- Track mud, sand, gravel, bioclastic, and volcaniclastic fractions.
- Estimate alongshore transfer, accommodation, bypass, and local deficit/surplus.
- Reuse numerical material affinity inputs; do not make scientific classification depend on reading renderer raster files.

## Workstream E — Coastal classification

Each shoreline segment receives independent fields for:

- Tectonic setting: collision/active, trailing/passive, marginal sea, oceanic island, or uncertain
- Relative sea-level state: emergent, stable, or submergent
- Shoreline trajectory: prograding, approximately stable, retrograding, or mixed
- Substrate: resistant bedrock, erodible bedrock, mixed, sand, gravel, mud, carbonate, volcanic, or ice-rich
- Dominant forcing: wave, tide, fluvial, glacial, volcanic, chemical/karst, periglacial, or mixed
- Tidal class and wave-exposure class
- Primary and secondary geomorphic assemblages
- Confidence and rule trace

The first implemented assemblages are:

- Rocky cliff and headland-bay coast
- Clastic beach coast
- Barrier-lagoon coast
- Deltaic coast with river/wave/tide dominance
- Estuarine and drowned-valley coast
- Tidal-flat and wetland-accommodation coast
- Glacial fjord/fjard/skerry coast
- Volcanic coast
- Carbonate/karst coast
- Permafrost coast
- Emergent marine-terrace province

Beach morphodynamic state is calculated only for suitable wave-dominated sandy segments. Gravel beaches and mudflats use separate classifications.

## Workstream F — Regional landform materialization

### F1. Scale gates

- Planetary: margin setting, major cliffs/plains, shelves, large deltas, estuaries, fjords, archipelagos, and broad barrier systems.
- Macroregion: cliff belts, headlands, embayments, delta lobes, barrier chains, lagoons, tidal flats, reef accommodation, and skerry fields.
- Region: beaches, spits, tombolos, inlets, distributaries, marsh accommodation, dunes, and marine terraces.
- Local: berms, bar/trough systems, washover fans, dune ridges, shore platforms, stacks, caves, talus, and tidal-creek detail.

### F2. Parent-conditioned generation

- Replace generic near-sea-level noise with landform generators selected by the inherited segment model.
- Fade child detail to the parent surface and preserve segment identity across refinement boundaries.
- Conserve the regional sediment budget within stated tolerance.
- After barriers, lagoons, inlets, or delta lobes alter terrain, rerun local drainage once and update water-body connectivity.

## Workstream G — Persistence, UI, and reports

- Persist `coastal_geomorphology_model` and `coastal_summary` on planets and generated regions.
- Add coastal provenance nodes and invalidation dependencies.
- Add coastal fields to reset/rollback cleanup paths.
- Add a Coastal Geomorphology map layer with categorical segment colors, wave/tide overlays, transport arrows, landform symbols, and confidence-aware legend.
- Add a compact worldgen summary showing dominant coast assemblages, coastline length, estuary and delta counts, and tidal/wave distribution.
- Add a coastal report page to retained headless bundles; avoid emitting separate image files unless explicitly requested.

## Workstream H — Verification and acceptance gates

### Synthetic scientific fixtures

- Resistant, high-relief, exposed margin becomes rocky/cliffed.
- Low-gradient sand-surplus margin becomes beach/barrier-lagoon.
- Glacially overdeepened flooded valley becomes fjord rather than generic ria.
- River sediment surplus with weak marine reworking becomes river-dominated delta.
- Strong wave or tidal reworking produces the corresponding delta end member.
- Sheltered low-gradient muddy macrotidal coast becomes tidal-flat accommodation.
- Carbonate, volcanic, karst, and permafrost labels require their necessary upstream conditions.

### System invariants

- Deterministic seeds produce identical segment IDs and classifications.
- Longitude wrapping creates no split or duplicated coasts.
- Child regions inherit parent coastal regime and converge at patch edges.
- No coral reef is asserted without Biosphere support.
- No barrier forms on a sediment-starved cliff coast.
- No fjord forms without glacial excavation and marine inundation.
- Repeated worldgen and headless validation do not increase persistent file count unless retention was explicitly requested.
- Temporary output is removed after successful and failed handled runs.
- Sol benchmark replay remains readable and pinned.

## Delivery sequence

1. Storage A1-A4
2. Heightmap derivatives B1-B2
3. Shoreline graph C1-C2
4. Wave, tide, relative sea level, and sediment drivers D1-D4
5. Classification E
6. Persistence and initial map/report layer G
7. Planetary scientific fixtures and realism audit H
8. Regional materialization F
9. Regional invariants, performance profiling, and Sol benchmark refresh H

The first reviewable milestone ends after step 6: coast segments are scientifically classified, persisted, and visible, but do not yet modify terrain. The first terrain-changing milestone ends after step 8.

## Post-implementation verification (2026-07-23)

- A deterministic oxygenated ocean-plate world produced 113 persistent shoreline segments across 16 connected components and 134,093.1 km of resolved coastline.
- Showcase rendering exposed and corrected a classifier defect in which planet-wide volcanic provenance was being applied to every shoreline. Volcanic evidence is now spatially conditioned by hotspot tracks and active convergent margins; warm low-sediment carbonate-factory potential is likewise evaluated locally.
- The corrected benchmark resolves rocky cliffs, drowned-valley estuaries, headland-bay coasts, emergent marine terraces, and a deltaic segment, with wave exposure, tidal range, and longshore transport rendered over relief.
- Exact tectonic-boundary spatial indexing and immutable seeded-constant caching reduced an isolated heightfield solve from 68.26 s to 32.41 s (52.5%) with the same SHA-256 heightfield fingerprint.
- The complete production worldgen-and-render route fell from 247.88 s to 176.69 s (28.7%) with identical final heightfield fingerprint, elevation range, land/ocean/ice fractions, precipitation, and river count.
- Three explicitly requested showcase images are retained; both temporary full-generation work trees were removed after validation.

## Explicitly deferred from this implementation

The following are recorded in the conceptual document rather than silently entering this plan:

- Full spectral wave transformation and coastal CFD
- Harmonic tidal constituent simulation and explicit basin resonance through time
- Event-resolved storms, tsunamis, and seasonal sea-ice wave coupling
- Million-year dynamic shoreline migration and stratigraphic basin filling
- Three-dimensional sediment transport and facies architecture
- Ecological succession and biological construction of reefs, marshes, and mangroves
- A repository-wide database or content-addressed object store replacing current entity JSON storage
- Distributed or cloud artifact storage
