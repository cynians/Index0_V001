# World-generation material LOD plan v001

Status: accepted 2026-09-23; phases 0-5 implemented 2026-09-24; routing
follow-ups (provenance, catena, talus, faults, bed sorting) and the True
Color Delta-E acceptance check implemented 2026-09-24 (see §9, §10);
child-unit sizing bug, contact reconstruction and local relief shading fixed
2026-09-24 (Phase 8).
Companion to [the LOD mechanism matrix](worldgen_lod_mechanism_matrix_v001.md).

## 1. Why the material layer is being replaced

Measured on the production headless route (Earth-like seed, LOD0 followed by
one 1,000 km LOD1 refinement, 513 x 478 grid, no profiler attached):

| Step | LOD1 (670 s) | LOD0 |
|---|---|---|
| `_mountain_morphology_mask` (3 calls, per-cell `_orogen_forcing_at`) | 394 s | 2 s |
| per-pixel material raster (`generate_material_heatmap_model`) | 87 s | 1.6 s |
| regional occurrences + regolith/soils | 12 s | 2.7 s |
| water-cycle solves | 63 s (4x) | 105 s (5x), of which 71 s Koppen display grid |

Speed was only part of the problem. The material *model* was also wrong:

1. LOD0 painted one bedrock rock per tectonic plate (plate-distance Voronoi);
   cover was chosen from the climate at the plate centre.
2. LOD1+ used an unrelated algorithm: every pixel scored 36 candidates in pure
   Python against seeded random per-plate preferences and sine noise. Arcs,
   collisions, rifts, cratons and ocean-floor age barely decided lithology.
3. Lineage was broken: LOD1 re-queried root tectonics, never read the parent
   material raster, and narrowed chemistry to the single plate province under
   the region centre. A child was not a zoom of its parent.
4. Up to 18 RGBA "suitability" layers were stored; True Color treated their
   alpha as abundance with competitive exponents, so no pixel was an honest
   areal mixture.

## 2. Contract

Three separate products per LOD, all produced with NumPy (Python loops only
over settings, units and materials):

1. **Substrate**: what rock is at/near the surface. Decided by tectonic
   setting, inherited and subdivided at each LOD.
2. **Cover**: what lies on the rock (regolith, colluvium, alluvium, aeolian
   sand, loess, till, evaporite crust, ice/frost). Recomputed at each LOD from
   that LOD's climate, drainage and geomorphology; cover *material* comes from
   a source-lithology x climate lookup.
3. **Optics**: what it looks like. Render-time only: per-material areal
   fractions x the ontology optical profile of each material.

Invariants:

- **Composition is areal.** Every cell carries fractions over materials that
  describe its footprint. A 78 km LOD0 cell is a mixture, a 2 km LOD1 cell is
  mostly one mapped unit plus its setting's minor lithologies.
- **Mixture-preserving refinement.** A child unit's material is drawn from the
  parent composition at that location, and the child composition is
  `a_L * onehot(unit) + (1 - a_L) * parent_composition`. Its expectation is the
  parent composition, so a child's True Color box-filtered to parent pixels
  reproduces the parent.  Tested on composition means and as a True Color
  Delta-E budget (`material_lineage.py`, §5).
- **Strict N-1 inheritance.** Children sample the parent's material bundle
  (setting memberships at LOD0, unit rasters below). They do not re-query the
  root plate model for lithology.
- **Ontology owns the semantics.** Where each rock forms, and its typical
  areal share there, is authored on ontology material entities as
  `lithotectonic_setting_weights` (`tools/author_lithotectonic_settings.py`).
  Runtime recipes are rebuilt from the material catalog cache; setting ids
  are classifier categories owned by code.
- **Chemistry still gates.** Recipes resolve only through materials the
  crust inventory supports (`natural_material_model.likely_materials`), so
  exotic bulk chemistry swaps rocks instead of painting impossible ones.

## 3. Lithotectonic settings (LOD0 classifier)

Fuzzy per-cell memberships over:

| id | Evidence |
|---|---|
| `oceanic_ridge` | oceanic crust, young ocean-floor age, spreading-ridge band |
| `abyssal_ocean_floor` | oceanic crust, older floor |
| `oceanic_plateau` | oceanic crust on hotspot tracks / LIPs |
| `island_arc` | oceanic upper plate, subduction arc band |
| `continental_arc` | continental upper plate, subduction arc band |
| `forearc_accretionary` | trench / accretionary-margin / forearc bands |
| `collisional_orogen_core` | continental-collision hinterland core band |
| `fold_thrust_belt` | collision fold-thrust band, transpression |
| `foreland_basin` | collision foreland band, flexural subsidence |
| `exposed_shield` | craton ellipses in `exposed_shield` state |
| `continental_platform` | stable continental interior, covered cratons |
| `intracratonic_basin` | intracratonic basin discs |
| `continental_rift` | rift axis/shoulders, failed rifts (aulacogens), back-arc |
| `passive_margin_shelf` | continental shelf away from active margins |
| `continental_hotspot` | hotspot tracks on continental crust |
| `volcanic_plains` | plume-lid / stagnant-lid resurfacing, low basins |
| `ancient_highland_crust` | stagnant-lid or airless highlands |
| `impact_basin` | retained crater rims/ejecta |

Band evidence comes from the same boundary segments and orogen systems as the
heightfield (`orogen_setting_bands_grid`, sharing the segment geometry with
the vectorized `orogen_forcing_grid`), so rock belts line up with the
mountains the heightfield builds.

## 4. What kicks in at each LOD

| LOD | Substrate | Cover |
|---|---|---|
| 0 Planet | setting memberships x recipes = composition per cell; provinces (connected dominant-setting regions) become generated `geounit` cards with a composition and element budget | ice sheets, sand seas, evaporite pans in closed basins, weathered mantles, space-weathered regolith |
| 1 Macroregion | parent memberships smoothed by 1.5 parent cells and sampled with domain warp; strike-aligned warped cellular partition; unit material drawn from local composition by exponential race; purity `a_1 = 0.70` | alluvium on the drainage network, dune fields, till, weathering mantles, loess; **provenance**: 35 % of the alluvium area is clasts of the upstream substrate mix |
| 2 Region | sub-units drawn from parent unit composition (`a_2 = 0.82`); layered units get bed stacks cut by topography (outcrop = bed at depth), so outcrop belts follow valleys and ridges | geomorphic partition (alluvial/colluvial/mantle); regional occurrence bodies and crater ejecta overlay the composition; provenance share 45 % |
| 3 Local | finer partitions and thinner beds (`a_3 = 0.90`); **fault offsets** displace the unit lattice and bed stacks | same cover model at local resolution; **catena** (crests shed mantle, toeslopes gain it, saturated hollows collect fines); **talus** aprons of cliff rock below rock faces; provenance share 50 % |
| 4-5 Site/Parcel | finer partitions (`a = 0.95`); outcrop where cover is thin follows from the cover model | **channel-bed sorting**: stream power sets the clast share (20-75 %) and splits the fines between channel-bed (gravel, alluvium) and floodplain (silt, alluvium) materials |
| 6-7 Plot/Survey | no new fields | substrate references for sparse objects |

Routing (`material_routing.py`) runs on each level's own heightfield:
steepest-descent (D8) receivers, upstream sums by pointer doubling (no
per-cell Python loop), and the fields below.

| Process | Mechanism |
|---|---|
| Provenance | Every land cell supplies sediment `0.1 + clip(gradient / 0.25)` with its own substrate mix; the alluvium clasts at a cell are the supply-weighted mean over its catchment.  Routed on block means of at most 70,000 cells, then interpolated. |
| Catena | Topographic position (elevation minus a ~250 m window mean) gives crest and toeslope weights; `ln(a / tan b)` (one-cell mean against D8 streaks) gives wetness, scaled between its 85th and 99th land percentiles so only valley floors and flat hollows saturate.  Crests move up to half the mantle to bedrock, toeslopes 40 % of bedrock to mantle; wet hollows take up to 70 % of the remaining mantle where the climate is humid and unfrozen. |
| Talus | Faces steeper than ~40 deg shed debris along their receivers; below the angle of repose (~35 deg) it settles at `1 - exp(-spacing / 120 m)` per cell, so an apron has the same physical length (e-folding 120 m, cut off at 240 m) at every level.  The apron's material is the face's own rock; frost shattering raises the apron share. |
| Faults | A lattice of 7 unit scales in the strike frame holds at most one fault per cell (density 0.35-0.85 with tectonic strain; 30 % cross faults).  Displacement tapers to the tips and fades within two half-lengths, so a grid sees exactly the faults that reach it.  Lateral slip moves the unit lattice; vertical throw (6 % of the lateral on strike-parallel faults, 25 % on cross faults) shifts bed-stack depth, so outcrop belts step across the trace. |
| Channel belts (LOD3+) | Channels start at 0.5 km^2 of catchment (routed over the filled surface); floodplain half-width `15 m x A_km2^0.45`.  Alluvium is placed on the belts (0.9 of belt cover) instead of the geomorphic partition's film (kept at a quarter). |
| Bed sorting | Stream power `sqrt(area) x slope`, scaled to the 95th percentile over alluvial cells, times position in the belt: the thalweg zone (inner third) carries channel-bed sediment and coarse clasts, the rest of the belt floodplain fines. |

Landscape-position cover classes (`talus`, `wet_hollow`, channel bed,
floodplain) choose catalogue materials by the ontology field
`surface_affinity_profile.depositional_environments`, because several of
these cards share one formation category and profile (marine mud, lake mud
and silt are all `fine_basin_sediment`).

## 5. True Color

- Visible composition = `(1 - cover_total) * substrate_composition +
  sum(cover_c * onehot(cover_material_c))`.
- Stored as one alpha layer per material (areal fraction, `fraction_semantics
  = areal_surface_fraction`) in the region's `.i0r` bundle, plus packed
  setting, cover and unit rasters.
- `render_true_color_surface` mixes areal layers linearly (no competitive
  exponent) and then applies the existing per-material weathering blend,
  wetness, frost, space weathering, hillshade and atmosphere.
- Acceptance: child True Color box-filtered to the parent pixel matches the
  parent within a mean Delta-E budget; child substrate fractions match the
  parent composition within tolerance.
- The check (`material_lineage.lineage_delta_e`) mixes each material's
  ontology reflectance by areal fraction, averages child samples onto their
  nearest parent sample and compares CIE76 Delta-E.  Budget: mean < 6,
  95th percentile < 15.  Measured on the captured Earth-like planet (LOD1
  on the fixture region, LOD2 and LOD3 on terrain-only refinements, each
  with its own regional climate solve):

  | Step | Parent pixels | Mean | p95 | Max |
  |---|---|---|---|---|
  | LOD0 -> LOD1 | 169 | 5.3 | 10.3 | 17.8 |
  | LOD1 -> LOD2 | 3,619 | 4.2 | 12.9 | 20.5 |
  | LOD2 -> LOD3 | 1,972 | 1.9 | 9.6 | 11.5 |

  The first measurement (4.7 / 3.2 / 0.3 mean) was flattered by the unit
  sizing bug in §11: child tiles had one or two units, so a child was nearly
  its parent's mixture.  With 255 / 374 / 128 units per tile the budget
  still holds.

  Most of the drift is cover, which each level re-derives from its own
  climate and relief.  `tests/test_material_lod.py` checks the budget on a
  synthetic two-level chain (mean 1.3); drawing the child from the wrong
  parent mixture fails it (mean 8.6).

## 6. Performance budgets

Targets: LOD0 material stage < 1 s; LOD1 < 2 s at 513 x 478; True Color render < 0.5 s.
Measured: LOD0 product 3-4 s (settings, geomorphic partition, provinces and
cards included); LOD1 product about 2.6 s at 513 x 471 with provenance
routing; LOD2 2.8 s at 513 x 309; LOD3 0.9 s at 385 x 227 with catena, talus
and faults; True Color render 1-4.5 s depending on size (not yet optimised).
Substrate runs once when tectonics/heightfield change; cover runs after climate.

## 7. Ontology and generated cards

- New material field `lithotectonic_setting_weights` (setting id -> typical
  areal share), authored by `tools/author_lithotectonic_settings.py` into the
  live SQLite store. The `.owl` checkpoint is exported only on request.
- LOD0 provinces become `geounit_<planet>_<nn>` location cards (largest
  first, capped). LOD1+ units live in the region's unit table and bundle; they
  become cards only when something promotes them (mine, site).

## 8. Non-material speed fixes (Phase 0)

- `_mountain_morphology_mask`: NumPy relief window + exact vectorized
  `_orogen_forcing_at` (`orogen_forcing_grid`). The per-system combination is
  an iterated L6 norm, which is order independent, so segments accumulate
  `sum(v**6)`.
- Koppen display grid: vectorized bilinear sampling, monthly normals and
  Koppen thresholds (0 class mismatches over 131,841 cells; 29 s -> 0.37 s).

## 9. Phases

- [x] Phase 0: mountain-mask and Koppen vectorization.
- [x] Phase 1: settings classifier (`lithotectonic_settings.py`), ontology
  recipes (`tools/author_lithotectonic_settings.py`), areal LOD0 composition
  and provinces/cards (`material_lod.py`), areal True Color.
- [x] Phase 2: LOD1+ inheritance from the parent bundle, warped strike-aligned
  units with correlated (rank-uniform) draws, cover lookup; per-pixel scorer,
  `_tectonic_lithology_context`, one-rock-per-plate placement and single-plate
  narrowing removed.
- [x] Phase 3: LOD2+ bed stacks cut by topography (`_layered_draw`);
  provenance routing followed in Phase 6.
- [x] Phase 4: vectorized regolith/soils reading province chemistry from the
  LOD0 province index raster; regional craters add impact ejecta; regional
  occurrence bodies (deposits, mapped units) are rasterized into the
  composition at their footprint.
- [x] Phase 5: consumers, tests (`tests/test_material_lod.py`,
  `tests/test_worldgen_vectorised_parity.py`, updated placement, affinity and
  scenario tests), scenario tool semantics, LOD matrix doc.
- [x] Phase 6: routing follow-ups (`material_routing.py`): alluvium
  provenance from LOD1, catena, talus and fault offsets from LOD3,
  channel-bed sorting from LOD4; `depositional_environments` authored on 12
  sediment cards; manifests record `surface_routing` and `fault_traces`
  (`tests/test_material_routing.py`).
- [x] Phase 7: True Color lineage check (`material_lineage.py`) with the
  budget in §5.
- [x] Phase 8: child levels use the planet circumference
  (`material_heatmaps.planet_circumference_m`); parent composition is
  Gaussian-smoothed by `PARENT_CONTACT_SMOOTHING_CELLS` (1.5 parent cells)
  before sampling; unit lithology is an exponential race over per-material
  correlated draws (`_race_select`, `_correlated_unit_draws`); bed stacks
  return `use_beds, bed_index, weight` (`_layered_beds`).  LOD3+ True Color
  caps hillshade exaggeration by cell size and scales grain texture by its
  physical amplitude; LOD3+ geomorphology normalises landforms against a
  physical floor (`REGIONAL_LANDFORM_REFERENCE_SLOPE`).

## 10. Implementation notes

- Recipes follow ontology `lithotectonic_setting_weights`, scaled by the
  chemistry-adjusted `relative_abundance`.  On `ultramafic_tendency` worlds
  65% of a setting's mafic-volcanic share moves to ultramafic analogues;
  foundational lithologies (graphite on carbon-rich crust) join every land
  setting.  Planets without a plate model but with `plate_tectonic_surface`
  classify from freeboard (continental crust follows elevation).
- Cover classes: ice, alluvium, aeolian sand, loess, lateritic mantle, clay
  mantle, duricrust, ferric coating, airless regolith, impact ejecta,
  evaporite, glacial till.  Class area is shared among candidates by their
  ontology climate niche; climate-defined classes (duricrust, lateritic and
  clay mantles) return area outside every niche to the substrate.  Duricrust
  niches (calcrete, ferricrete, rock varnish) are authored on their cards.
- 33 common lithologies received rock-specific optical endmembers on their
  ontology cards (they previously shared formation-family defaults).
- LOD0 True Color is honestly muted: a 78 km cell is an areal mixture.
  Regional colour contrast appears at LOD1+ where mapped units resolve.

## 11. Bugs found along the way

- Ice-albedo feedback wrote freezing cells from the 257 x 129 climate grid
  into the 513 x 257 ice mask by index, so every new ice cell landed in the
  top-left quadrant (the "small ice shelf in a corner").  Fixed by resampling
  (`world_gen_sim.ice_mask_with_freezing_climate`).
- The LOD1 heightfield does inherit its parent (correlation 0.994 on the
  captured Earth-like planet).  Visible artefacts remain in the regional
  relief itself: a faint frame from the parent-edge fade band, a steep
  straight coastal wall near a tile edge, and horizontal fold streaks.
- Old LOD1 material maps re-derived rock choice independently of the parent,
  so a refined patch showed different colours from its parent; composition
  inheritance replaces that.
- Regional derivative refreshes built the shelf and sediment-thickness model
  by sampling the planetary lithosphere at tile-local UV, i.e. as if the
  tile were the whole planet, and let the shelf distance wrap across the
  tile's east/west edges.  The refresh now maps the tile through its
  `source_uv_bounds` and does not wrap regional grids.
- Child material products took `heightmap["circumference_m"]` as the planet
  circumference, but regional heightmaps store their own width there.  Every
  child tile was treated as 40x (LOD1) to 240x (LOD2) smaller than it is:
  one or two units per tile, faults squeezed into metres, occurrence bodies
  far too large.  Regional heightmaps carry `planet_circumference_m`, which
  `planet_circumference_m()` now reads.
- A unit boundary rasterised at the parent resolution is a staircase of
  parent cells, and bilinear sampling printed it into the child (a 6-7 cell
  step every few parent cells at LOD2).  Smoothing the parent window by 1.5
  cells before sampling removes it (contact residual 4.1 -> 1.2 child cells
  in the test).
- The inverse-CDF draw walked materials in list order, so wherever the mixture
  changed from A to B, whatever sat between them in the list won a thin band
  along the contact (a ghost outline in 91 % of units crossing a contact; 2 %
  with the race).
- True Color normalised relief to each tile's span: a flat 107 m-relief LOD3
  tile was shaded about 25x, and geomorphology promoted 10 cm bumps to
  full-strength ridges that drove the fresh/weathered colour blend, so flat
  plains rendered as 'orange peel'.  Both are physical from LOD3 down; LOD1-2
  keep the span-relative look (drainage legibility there relies on it).
- Visible in every LOD1-3 render of the captured planet, and not part of the
  material layer: pixel-scale relief noise in the regional heightfield
  (reads as a gravel texture in True Color), the parent-edge fade frame, the
  straight coastal wall and the stair-stepped fold streaks noted above.

## 12. Measured performance

Headless Earth-like run (seed `profile-materials-001`), LOD0 plus one
1,000 km mountain-targeted LOD1 at 513 x 466, wall time from thin wrappers:

| | Start | After materials + first speed pass | Now |
|---|---|---|---|
| Whole run | 1,001 s | 328 s | 267 s |
| LOD1 refinement | 670 s | 94.5 s | 46.1 s |
| LOD1 derivative refreshes (3) | 394 s (mask alone) | 33.2 s | 4.0 s |
| LOD1 climate solves (4) | 63 s | 33.0 s | 14.1 s |
| LOD1 material product | 87 s | 2.8 s | 1.9 s (incl. provenance 0.4 s) |

Every speed change reproduces the previous per-cell result: bit for bit
for the shelf model, refresh masks, both climate passes, wind lattice,
maritime smoothing and drainage wetness; to about 1e-9 m for the sea-level
bisection; the orogen forcing's sixth powers (now products instead of
`pow`) change the last bits only, and the refreshed LOD0/LOD1 derivatives
are identical to the reference.
The parity tests are `tests/test_worldgen_vectorised_parity.py` and
`tests/test_material_lod.py`.

About 160 s of the LOD0 portion is still unattributed (runner setup,
persistence, the mountain-target search); the wrapped LOD0 stages total
about 60 s.
