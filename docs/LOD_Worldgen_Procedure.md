# LOD Worldgen Procedure

The living process document for improving world generation one level of
detail (LOD) at a time. Each round picks a LOD, adds one **real-world
geographic phenomenon** that first becomes visible at that scale, follows it
down the LOD chain until it is no longer recognizable, and, as a parallel
track, audits and corrects something that **already exists** at that LOD.

Work from:

```text
C:\Users\logol\PycharmProjects\Index0_V001
```

A round is not complete when the code runs. It must leave a physically
defensible mechanism, a chain of renders proving where the phenomenon
appears, persists and fades out, a before/after for the existing-feature fix,
targeted tests, and an entry in the round log (§8).

## Invocation and token-efficient reading

Treat "LOD procedure", "LOD worldgen procedure", "LOD round", or "pick a LOD
and add a phenomenon" as references to this document. Do not create a
duplicate under another name.

Read the heading index first, then §1-§3. Load later sections when the round
reaches them. Scale and layer contracts live in
[worldgen_lod_mechanism_matrix_v001.md](worldgen_lod_mechanism_matrix_v001.md);
do not copy them here, read the relevant rows.

## 1. Non-negotiable contracts

These come from the project rules and the mechanism matrix; every round obeys
them.

1. **Real phenomenon, real science.** The phenomenon must exist on real
   planets (Earth first, other bodies where physics allows). Its size,
   spacing and occurrence come from published scaling relations or
   measurements, cited in the code docstring and the round log, not from
   "looks right".
2. **Driven by existing physical fields.** Heightfield, drainage, climate,
   water cycle, materials, tectonics. No decorative noise that is not tied to
   a process; no map-space sinusoids (use `sphere_noise.py` / `array_noise.py`
   in a physical frame).
3. **Abiotic layers stay abiotic.** Height, material, True Color and Koppen
   never assume vegetation. If the real phenomenon depends on vegetation
   (e.g. bank cohesion from roots), model the abiotic case and leave a hook
   for the future Biosphere layer.
4. **Child = parent + bounded, scale-specific residual.** A level adds only
   what its parent could not resolve (scale gate, §4.3); it must not redraw a
   feature the parent already carries. Changes are zero-mean at the parent's
   spacing (`fluvial_relief.conserve_parent_scale`) and fade at the tile edge
   (`PARENT_EDGE_FADE_FRACTION`).
5. **Ontology is the only durable source of semantic facts.** New material
   roles go through the `tools/author_*.py` pattern and its schema, not a
   Python dict. Generated geometry is stored compactly (parameters,
   centrelines, seeds) and rasterized on demand, not as extra full rasters.
6. **Layers are views of one solution.** Height, True Color, materials and
   hydrology must agree on where the phenomenon is (one geometry, many
   consumers).
7. **No live worlds, no legacy.** World generation is finished before any
   world is generated to keep (owner, 2026-10-05; `AGENTS.md`): every stored
   world is a test fixture. No migrations, compatibility shims or fallbacks
   for old records; regenerate instead, and never hold a mechanism back for
   the sake of stored worlds.
8. **Never run the full test suite.** Run targeted modules only; long
   worldgen runs go to the background and are iterated from captured
   fixtures.
9. **A level is a scale of ground, not a count of refinements.** A map's
   level is read off its footprint (§2,
   `regional_refinement.LEVEL_MAX_EXTENT_M`), and every refinement goes
   exactly one level down with cells at least three times finer
   (`MIN_REFINEMENT_STEP`). A footprint too large for that is refused with
   the largest that works; one that is levels finer gets the maps in
   between first, each one level down, stored and used again
   (`generate_refined_region`). Recipes may therefore be switched and sized
   by level; none may assume a cell size its level's range does not hold.

## 2. Scale reference (Earth-sized body)

The footprint column is the rule (contract 9): the longest side decides the
level. The cell spacing follows from the grids of
`refinement_sample_dimensions` (513 columns to Region scale, 385 below, the
10 cm floor from Plot scale).

| LOD | Name | Footprint (longest side) | Cell spacing | Typical first-visible phenomena |
|---|---|---:|---:|---|
| 0 | Planet | over 8,192 km | ~78 km | plates, continents, basins, climate belts |
| 1 | Macroregion | 512-8,192 km | 1-16 km | ranges, forelands, principal rivers |
| 2 | Region | 45-512 km | 88 m-1 km | range segments, valleys, tributaries, shelves |
| 3 | Local | 6-45 km | 16-117 m | ridges, gullies, floodplains, dunes, cliffs |
| 4 | Site | 0.85-6 km | 2.2-16 m | channels, banks, bars, outcrops, fans, talus |
| 5 | Parcel | 107-850 m | 0.28-2.2 m | small gullies, terraces, bank forms |
| 6 | Plot | up to 107 m | 0.1-0.28 m | rills, hummocks, ledges |
| 7 | Survey | up to 38 m, under a Plot coarser than the floor | 0.1 m | microdrainage, bedrock steps, tide pools |

The chains of the round log lie inside these ranges: 1,090 and 8,100 km at
2.1 and 15.8 km a cell, 120 km at 234 m, 16 km at 42 m, 2.4 km at 6.25 m,
300 m at 0.78 m, 38 m at 0.1 m; each is small enough to be its parent's
child.

**Visibility rule of thumb.** A feature of characteristic size `L` first
reads as a *shape* when `L >= ~4 dx` (at least a few cells across) and is
seen *whole* while `L <= ~F/2` (footprint `F`). Below `~1.5 dx` it survives
only as a mixed-cell fraction (material share, alpha, roughness). Above `F`
it survives only as an inherited slope, material or boundary condition.

## 3. Round overview

| Step | Track | Output |
|---|---|---|
| 3.1 Pick the LOD | both | LOD number (random or user-given) |
| 3.2 Choose the phenomenon | A (new) | phenomenon card (§4.1) |
| 3.3 Audit the current LOD | B (existing) | findings list, one chosen fix |
| 3.4 Implement | A + B | code, tests, compact stored geometry |
| 3.5 Chain test | A | LOD N -> LOD 7 contact sheet, persistence table |
| 3.6 Before/after | B | same-seed render pair and numbers |
| 3.7 Close | both | matrix doc rows, round log (§8), visual checkpoint |

Pick the LOD with `py -c "import random; print(random.randint(1, 7))"` unless
the user names one.

## 4. Track A: a real phenomenon that first appears at this LOD

### 4.1 Phenomenon card (write before coding)

- **Name and real examples** (named places / planets).
- **Characteristic sizes** with sources: length, width, relief, spacing,
  and how they scale with the controlling variables (discharge, slope,
  grain size, climate, gravity...).
- **Why this LOD:** the scale test of §2 (first LOD where `L >= ~4 dx` for
  typical instances, and why the parent cannot show it).
- **Formation mechanism and controls**, including the conditions under which
  it does *not* form (regime thresholds).
- **Abiotic caveat** if the real form depends on life.
- **Layers it must appear in** (height, materials, water, True Color) and the
  single geometry they all read.

### 4.2 Implementation rules

- One module owns the phenomenon; consumers call its rasterizer.
- Deterministic from the map seed and world-anchored positions.
- Parameters come from the card's scaling relations, as named module
  constants with the citation next to them.
- Summaries go into the level's model (e.g. `heightmap_model[...]`) so
  diagnostics and the UI can report what was generated and why.

### 4.3 The scale gate (persistence without redrawing)

Each instance "belongs" to the first level whose cell spacing resolves it.
A level handles an instance only when `L >= k dx_child` and
`L < k dx_parent` (the parent could not resolve it). Deeper levels inherit
the instance through the heightfield/material lineage and may add only the
smaller members of the same family (e.g. smaller channels). If the mechanism
does not yet run at the parent's level, the upper bound is dropped for the
first active level; record that in the round log.

### 4.4 Chain test

Build the chain from a captured fixture (never a full live run per
iteration):

1. Refine a LOD N tile centred on a representative instance.
2. Refine LOD N+1 ... LOD 7 children centred on the same instance (one bend,
   one bar, one bank...).
3. For every level record: visible in which layers; inherited or regenerated;
   lineage Delta-E (`material_lineage.py`) and height box-filter error
   against the parent; the level at which the phenomenon stops being
   recognizable and what remains of it (slope, material, moisture).
4. Compose a contact sheet (height hillshade + True Color + material per
   level) and look at it before writing any claim about it.

## 5. Track B: audit and correct an existing feature at this LOD

1. Render the chosen LOD with the **current** code (same seed as track A).
2. List what is visibly wrong or scientifically weak: grid artefacts,
   frames, streaks, wrong scale, wrong material logic, broken lineage,
   performance hot spots. Probe the input fields along a transect before
   blaming the colour code.
3. Pick one item (ideally the most visible or most wrong); fix it at the
   cause; keep the fix inside the parent-child contract.
4. Produce a same-seed before/after pair and the numbers that changed.

Track B findings not fixed in the round go to the round log as open items.

## 6. Tooling

- Fixture capture and chain building: capture LOD0+LOD1 once with
  `headless_runner.run_isolated_headless_worldgen` (keep the run's
  `planet.json`; ~5 min), then refine each level with the full production
  `generate_refined_region` (80-130 s per level) and a `SimpleNamespace`
  world model, so every parent carries its water cycle and materials, which
  LOD4+ mechanisms read. Terrain-only refinement is faster but leaves those
  out.
- Region `bounds` are not latitude: `y = -90 + 180 v`, and grid rows run
  from `min_y` to `max_y`. A pick that assumes north-up lands on the mirrored
  place.
- Place each child on the phenomenon (e.g. the largest channel, a bend
  apex, a bank) and reuse the same footprints for before/after renders.
  A code change at LOD N changes every level >= N: rebuild from the lowest
  affected level.
- Run chains in the background and read the log when the job ends.
- Renders: `material_heatmaps.load_raster_bundle_surface`,
  `true_color.render_true_color_surface`.
- Lineage: `material_lineage.py` (mean Delta-E < 6, p95 < 15).
- Keep scratch scripts in the session scratchpad; promote a script into
  `tools/` once two rounds have needed it.

## 7. Closing checklist

- [ ] Phenomenon card cited in the module docstring.
- [ ] Scale gate implemented and verified at LOD N+1 (no redraw).
- [ ] Chain contact sheet reviewed and sent to the user.
- [ ] Track B before/after reviewed and sent.
- [ ] Targeted tests added or updated and run (never the full suite).
- [ ] `worldgen_lod_mechanism_matrix_v001.md` rows updated.
- [ ] Round log entry (§8) with open items.

## 8. Round log

Newest first. One entry per round: LOD, phenomenon (track A), existing fix
(track B), persistence result, open items.

### Caprock benches - held to their ground, cut by the parent's rivers (2026-10-20)

Track B, LOD2-4: open item 1 of the consistency walk below. The walk's
Region carried a ruler-straight 150 km caprock wall (crest 80-120 m over a
220 m relief plain, a groove 40-60 m under the plain at its foot) that
dammed a lake the Macroregion lacks and gave the 13,500 m3/s through-river
no gap.

**Cause** (found offline on the Region's captured landform inputs: 12 s a
run instead of a 170 s refinement). The wall is no cuesta. It stands on a
~100 m flexure of the stack's reference horizon (504 -> 600 m over 2 km)
under a flat plain at 716 m; the plain cuts only mudstone (130-270 m above
the horizon) and the conglomerate cap begins at 274 m. `rock_scarps` lays a
scarp out for the slope at which the ground cuts the beds as if that slope
ran through the scarp's whole run (6 km here); in the 2-3 flexure cells the
run gate opened and the remap stood the cap up by +100 m and cut the foot by
-60 m, back to nothing on either side. `hold_above_outlets` then raised
10,522 cells (900 km2) behind it to its lip, and the lake delta filled a
2,566 km2 lake.

**Fix** (`regional_landforms`, applied to the order a level builds):
- `hold_scarps_to_ground`: within a step's reach (its change over the slope
  its profile was laid out for, so the distance at which the ground would
  have that height), nothing is cut below the lowest ground (base level:
  Powell 1875; the foot is a strike vale at the ground's level, not a moat),
  and nothing stands above the highest ground unless the ground there cuts
  the beds up to that level (differential erosion: Gilbert 1877; cuestas,
  hogbacks, strike vales: Davis 1899, Jukes 1862, Thornbury 1954). On a
  slope that runs through its scarps the staircase is unchanged. The holds
  are written into the order's weight record (each node takes the least any
  cell its interpolation reaches allows; the steps are linear in it), so
  `restep`, rockfall and the rock, soil and colour layers read what was built.
- `water_gap_corridor`: the rivers the parent carries (as big as the smallest
  river it records) are routed over this level's ground before the steps,
  with the boundary inflow at each entry's own catchment runoff; a gap as
  wide as the river's bankfull channel (`alluvial_channels` hydraulic
  geometry, as for canyons) gets weight 0: superposed and antecedent drainage
  (Powell 1875, Davis 1889, Oberlander 1965; rivers that keep pace: Burbank
  et al. 1996, Humphrey & Konrad 2000). References from memory, unverified.

**Result**, Region regenerated from `cw_lod1` over the same footprint (169 s;
`images/cw_lod2_look.png`, `images/cw_lod2_bench_profiles.png`):

| | before | now |
|---|---|---|
| bench max change | 140.6 m | 10.3 m (4,871 cells held; 129 m of foot and 139 m of crest taken back) |
| cells held above their outlet | 10,522 | 593 |
| lakes | 23, 4.9 % (largest 1,011 km2) | 8, 0.3 % (largest 22.5 km2); the lake delta's lake 2,566 -> 94 km2 |
| water fraction | 0.076 | 0.028 |
| against LOD1 (box) | water 0.053 vs 0.0021, presence 0.90, wetness +18 %, height RMS 7.0 m | water 0.0051 vs 0.0021, presence 0.92, wetness +1.4 %, height RMS 1.8 m |
| through-river | 13,579 m3/s, south edge | 13,536 m3/s, south edge |

Profiles across the flexure are the ground's own drop sharpened to a step
(805 -> 793 m at x 0.59), with no crest over the plain and no trench at the
foot; the precipitation stripes and the Aw/BSh fingers along the wall are
gone. Gaps: rivers from 6,415 km2 (911 cells), 3,418 gap cells, 90 of them
where a step of up to 137 m would have stood; the through-river's gap floor
1.5 km. On this tile the flexure cuts no strong bed, so no bench remains.

Tests: `test_regional_landforms` 25 (new `WaterGapTest`: a parent river
crosses a flank of scarps at its own level and drains, none without river
records; `HeldToGroundTest`: a cap the plain never reaches is no wall and its
foot no moat, and the record steps the same ground; a cap that crops out
still stands as a hogback; a staircase on a slope is left as it was);
`test_river_handoff` + `test_terrain_lod_improvements` 36;
`test_scarp_canyons` + `test_low_shore_floor` 25. All pass.

**Open.**
1. A gap is at least as wide as the weight record's nodes are apart (64 a
   side: 2.3 km on a Region, ~310 m on a Local), so a Region gap is wider
   than its river; a finer record (`rock_scarps.WEIGHT_RECORD_CELLS`) would
   give the river's own width.
2. The hogback (a cap that crops out on flat ground) is checked on a
   synthetic flexure only; no generated tile has shown one yet.
3. `cw_lod3`-`cw_lod7` are stale: refined from the Region before this fix.
4. `river_deltas` still sizes a lake delta from the tile's mean runoff
   (36,886 m3/s for the through-river against 13,445 at the inflow).
5. The routing and windows add ~2.3 s to a Region's landforms (12.3 -> 14.6 s).

### Consistency walk - one new world from planet to Survey (2026-10-20)

Owner: "lets check world gen consistency by generating a new world from top
to bottom LODs. taking notes and checking whether things work or there are
mechanics that dont function/are not quite there yet", then "fix one package
for each LOD, then regenerate it from the parent to see if it worked".

Look-only (nothing written to the store): production headless planet
(generic randomizer seed 20261020, Earth-like volatiles, plate tectonics;
radius 1.21 Earth, 60.6 % ocean), then one `generate_refined_region` per
level, each a short burst: Macroregion 2,000 km, Region 150 km, Local 20 km,
Site 3 km, Parcel 400 m, Plot 80 m, Survey 30 m, following the planet's
largest river to its mouth and a caprock bench. Notes, tables, pictures and
scripts: `artifacts/consistency_walk/` (`NOTES.md`, `walk.py`, `look.py`,
`verify.py`); cases `artifacts/stress_ground_water/cases/cw_*.pickle`.

**What held.** Climate is conserved exactly from LOD2 down (temperature RMS
0.02-0.07 K); height box-filters to the parent within a few metres at every
level; from the Site down everything checked agrees (water table, soil
water, wetness classes; `lod_flora_chain` same plants on the same ground
0.90-0.98 by cover). **What failed was water above the Site:** river
geometry, discharge, lakes and which rivers reach a child.

**Packages (each regenerated from its parent over the same footprint).**
- LOD0: a river segment that joins another has mouth "confluence" (the
  mouth test looked one cell past its end); coastal/interior precipitation
  diagnostic reads shore distance the right way round (was 0 mm); the
  terrain screen's ocean row says "from water, N m layer". Fixed.
- LOD1: `drainage._flat_potential` drains filled flats down `2 d_low -
  d_high` (Garbrecht & Martz 1997; Barnes et al. 2014) instead of the
  flood's epsilon rings (straight 45-degree and axis lines); accumulation in
  topological order; a flat's exits step only below its floor, with a loop
  guard. Inherited trunks are traced on the child's own flow from where
  they enter (`_trace_on_child_flow`, kept at their bends): trunk points in
  the sea 7 of 57 -> 0. **Not fixed:** a straight 5-12 m ridge across a
  filled basin on the Macroregion is built inside the LOD1 refinement (not
  the parent, not the stream-power pit lift; capping that lift was tried
  and reverted: LOD2 lakes 13 -> 96 and a 500 s Local map).
- LOD2: the inflow record carries its catchment's mean climate
  (`catchment_means_mm`, gathered along the parent's routes with what the
  parent's own inflow brought) and the solver uses it before the tile's
  mean. Through-river: planet 13,303 m3/s; LOD1 16,272 -> 13,631; LOD2
  37,464 -> 13,579. Fixed.
- LOD3: inherited trunks are capped after clipping (the 16 strongest parent
  reaches were capped before clipping and none crossed the child): 0 -> 7
  trunks; the through-river now enters (17,738 km2 / 33 m3/s -> 22.4 M km2
  / 13,464 m3/s); water presence against LOD2 0.55 -> 0.93.
- LOD4: a child's inflow follows the parent's own drainage solver
  (`regional_refinement._parent_solver_routing`, rebuilt exactly from the
  parent's climate-grid elevation, sea and inflow) instead of a second D8 of
  the parent heightmap that disagreed with it. Site from the original
  Local: inflow 5.8 -> 443 km2, the stream the Local map draws across it is
  there (0 -> 457 channel cells). Fixed.
- LOD5-7: no consistency break found; no package.

**Open.**
1. Caprock bench (`regional_landforms` caprock_mesas_and_benches) at LOD2-3
   is one continuous wall with a moat below the plain at its foot; it dams a
   lake and gives a parent river no gap. A landform a level adds should
   leave water gaps where the parent's rivers cross.
2. The straight LOD1 ridge (above).
3. Climate fields of a Macroregion show the planet's grid (straight
   900 km stripe, blocks); materials at LOD1 read as a random Voronoi
   mosaic; LOD4 materials speckled by 29 % depression cells.
4. Inherited planet lakes come down as stepped boxes; a lake whose edge a
   child's border cuts loses its through-flow.
5. Flow regime is judged on the catchment's mean runoff, so a Nile-like
   exotic river (27 mm/yr) is "intermittent".
6. A hot, dry planet: 21 C mean, 592 mm global precipitation, 79 % of land
   arid - worth a calibration look.
7. No gullies or rills on an 86 m scarp at Parcel and Plot scale.
8. Channels still run along tile edges where the parent's river does, and
   in straight lines across lakes.

Tests: new `tests/test_river_handoff.py` (7: loop-free flat routing incl.
rounded ties, runoff reaches the outlet, chained-segment mouths, trunk cap
after clipping, traced trunk stops at the coast, inflow carries its
catchment's climate); `test_drainage_realism`, `test_material_routing`,
`test_shut_in_water`, `test_terrain_lod_improvements`,
`test_alluvial_channels`, `test_fine_scale_ground`, `test_scarp_canyons`,
`test_orbital_climate_forcing`: 146 pass. `test_world_gen_orbit_clicks`:
9 failures and 2 errors, all outside what this pass touched (gas-giant
routes, crater resurfacing, the removed `climate_zone_model`, material
catalogue version strings, randomizer labels, moon-draft ids); not run on
the code before this pass. `test_headless_worldgen` (full chains) not run.

### Copper and verdigris - a native-copper world (2026-10-18)

Owner: "lets try to generate a planet (you may mess with the composition and
or add needed materials) that is a mix of copper and verdigris weathered
copper".

**Card** (in `element_pigments.py`): copper metal in air goes green only
while wet; in dry air it keeps its metal under a brown cuprite tarnish
(time of wetness, ISO 9223; Leygraf & Graedel 2000; copper roofs stay
brown for decades in deserts, green in rain). Patina (basic carbonates,
chlorides, sulfates) forms in neutral water with the air's CO2 on any rock
(Keweenaw native copper on basalt, copper roofs; Graedel 1987). Water
saturates over the patina and carries off only what it can dissolve: a
copper roof loses ~1-2 g/m2 a year and keeps its green (runoff 1-5 mg/L,
Odnevall Wallinder & Leygraf). A crust of native metal is an oxygen sink:
abiotic O2 stays lower over it (Kasting 1993). Unverified.

**First try**, 45 % copper as a major element (sulfur runs short, 99.8 % of
the copper native): patina over 95 % of the land, no metal visible. The air
held the fixed abiotic trace (0.23 % of Earth's O2), grains stay 30-900 kyr
in the weathering zone, and native copper corroded at the sulfides' moist-air
rate: 40-98 % gone even in deserts.

**Built.**
- `element_pigments`: native metal hosts corrode with the wetness only
  (`METAL_DRY_CORROSION_SHARE` 0.01; sulfides keep the 0.1 moist-air share);
  leaching is capped by solubility (copper card `solubility_log_molar`
  against pH over tenorite and malachite: log Cu ~ 7.6 - 2 pH down to the
  ~1e-6 M complexes), so trace copper stays sorption-limited and massive
  copper solubility-limited; acid water is not capped (leached caps stay).
- Ontology (store written and verified in SQLite, `.owl` not exported):
  malachite's niche is neutral water (acid low) with the air's CO2 instead
  of carbonate rock; native copper reflects as copper metal (0.42 / 0.22 /
  0.13 linear, Johnson & Christy 1972) and tarnishes to 0.18 / 0.09 / 0.06
  along the oxidation driver.
- `volatile_budget`: `_speciate` reports `native_metal_mol_per_100g` (noble
  metal the oxygen could not oxidize); `abiotic_oxygen` divides the trace O2
  by 1 + metal / `NATIVE_METAL_OXYGEN_SINK_MOL` (0.01 mol/100 g halves it, a
  calibration). Earth's template has none.

**Result** (`artifacts/copper_verdigris_world_lod0.png`,
`artifacts/copper_verdigris_world_lod1_2.png`): the 45 % world's air holds
0.004 % of Earth's O2; 6-40 % of the metal corrodes (5th-95th percentile of
land). LOD0: native copper on 13 % of the map, patina on 22 % (chrysocolla
in the dry interiors, malachite where wetter, atacamite in hyper-arid
salt). Copper-brown coasts, slopes and cold south; teal-green basins. LOD1
(2100 km): copper north, patina south. LOD2 (300 km) at 28.7 N 59.6 W:
metal 0.65, patina 0.31 of the tile, patina in patches. The 2 % twin's
LOD0 got greener (patina 6.6 % of the map, was 2.9 %; Delta-E against the
Earth twin above 5 on 6.4 %, was 3.4 %).

**Open.**
- LOD2 patina is speckled cell by cell rather than following landforms:
  residence time from the local gradient is noisy at that scale (not
  traced).
- Metal shine is not drawn: the renderer mixes diffuse reflectances.
- The O2 sink's strength is one calibration for every native metal; Ni and
  Co have no supergene data.
- This world exists only as a scratch run (`twins/verdigris45`), not in the
  app's store.

### Ore systems - one deposit that weathers by the map's rules (2026-10-18)

Owner: "ok, adress the still open" (the open items of the entry below; no
regeneration owed, there are no live worlds).

**Card** (in `element_pigments.py` and `metallogeny.py`): a porphyry or
massive-sulfide deposit is one body whose minerals are zones: hypogene
chalcopyrite and pyrite at depth, the chalcocite blanket, the
malachite/azurite/chrysocolla oxide zone and the iron-oxide leached cap at
the top. Which one the surface shows follows from sulfide oxidation, the
acid its pyrite makes against the host's neutralising potential, and
climate: red-brown hematite caps in warm deserts, goethite in humid ground,
a green oxide zone over carbonate (Anderson 1982; Schwertmann & Taylor
1989; Sillitoe 2005; unverified).

**Built.**
- `regional_materials`: one ore system per element with districts and
  tile. The planet's main host (chalcopyrite, or native copper where sulfur
  runs short) is the deposit; the element's other minerals are its zones
  (evaluations say `ore_system_zone`) and are not placed. The occurrence
  carries `ore_system`: style from the district type gathering the most at
  the spot (`metallogeny.district_contributions`; the largest share outside
  every district), grade from the copper card's `metallogeny.styles`
  (planet-scaled like rock contents, capped at the host's copper), pyrite
  only while the planet has sulfur to spare. Name e.g. "Porphyry copper
  (Chalcopyrite)"; `deposit_body` takes the style's type, geometry and grade.
- `material_lod.rasterize_occurrences`: an ore system is copper and pyrite
  in the ground (`share`, `content_percent`, `pyrite_wt`), not a layer;
  `_element_minerals` hands it to `surface_minerals`, which turns it into
  fresh sulfides, copper minerals and the leached cap's goethite and
  hematite (from the sulfides' iron, minus what acid water takes). A body
  smaller than about two cells now takes its area's share of the cell
  holding its centre (before, a 360 m porphyry vanished from a 600 m LOD2
  cell; this holds for every deposit). An ore system's weathered top spans
  its whole outline (0.9, as a mapped unit), not a lens's fill fraction.
- Iron oxides colour by their own strength: half the ground's colour at
  ~1.5 wt% (`IRON_OXIDE_VISIBILITY_WT_PERCENT`; ~1 % hematite reddens a
  soil, Torrent et al. 1983, Schwertmann 1993), copper minerals keep 6 wt%.
  First chain run with the shared 6 wt% curve and the lens fill: the cap
  was in the map (iron oxide 12 % of a cell) but Delta-E 1.4 in true colour.
- `element_pigments.mix_content_percent`: copper of the visible mix, each
  material by what it is made of. Rocks and sediments by their
  `trace_element_ppm`, minerals by their formula (a deposit mineral was
  scaled like a rock before), anything without data as the planet's mean
  crust (it was left out). The districts' factor applies to what formed in
  place, not to wind-blown sand, loess or evaporites.
- Ontology (`tools/author_element_pigments.py`, store written and verified
  in SQLite, `.owl` not exported): copper `metallogeny.styles` (porphyry
  0.3-1.0 % Cu with pyrite 2x the chalcopyrite; sediment-hosted 1.0-3.5 %,
  0.3x; massive sulfide 0.8-3.0 %, 10x; magmatic 0.4-1.5 %, 3x),
  `supergene_behaviour.leached_cap_phases` [goethite, hematite] with
  `supergene_stability` niches on both, and the malachite-azurite gossan
  filed under `supergene_oxidation` (it was a hydrothermal sulfide).
- The LOD0 path of a child without its parent's composition now overlays
  occurrences before the element minerals, like the child path.
- *Found on the way:* `headless_runner`'s child centre fractions only
  steered a planet's globe focus; under a region parent the window stayed
  centred, so `regional_child_center_fractions` did nothing below LOD1. The
  camera now moves there.

**Result.**
- Earth twin in an arc district (26.4 N 118.5 E, district factor 7.8),
  chain LOD2 300 km -> LOD3 40 km -> LOD4 6 km centred on the deposit
  (`artifacts/copper_ore_system_lod2_4.png`): LOD2 places one "Porphyry
  copper (Chalcopyrite)", 0.44 % Cu with 2.5 % pyrite, 2.2 km radius; the
  tile's eleven other copper minerals were turned down as its zones, and a
  molybdenite deposit sits beside it. LOD3 and LOD4 inherit it. Its top is a
  leached cap: goethite 0.49 and hematite 0.24 of the richest cells, the
  copper mostly gone (chrysocolla 0.02, malachite 0.01); where streams cut
  the body, fresher ground (sulfides, some copper minerals) shows. True
  colour, cap against the ground around it: Delta-E 4.7 (LOD4), 5.7 (LOD3).
- Stored tiles re-derived: the 30 % tile in an arc district now holds one
  porphyry of native copper (95 % Cu, no pyrite: the planet's sulfur runs
  short) where six copper minerals stood as separate deposits.
- LOD0 twins unchanged by the copper mix (Delta-E Earth vs copper twin
  mean 0.55, p95 3.6; chrysocolla 2.2 % of the map).
- Tests: `tests/test_element_pigments.py` (leached cap on silicate rock,
  copper staying over carbonate, hematite in warm dry caps and goethite in
  humid ones, fresh ore under reducing air, the mix's copper per material),
  `tests/test_metallogeny.py` (zones, an arc porphyry with pyrite, no pyrite
  without spare sulfur), `tests/test_material_lod.py` (ore as copper and
  pyrite in the ground, sub-cell bodies).

**Open.**
- The zones below the surface (enrichment blanket depth and grade) are
  not modelled: nothing shows or mines below the surface yet. The leached
  copper leaves the cell; the blanket or exotic copper downslope (item 4)
  would hold it.
- Hydrothermal alteration halos (phyllic sericite, argillic clays,
  propylitic chlorite) -- the km-wide colour of porphyry districts in
  satellite images -- are not drawn; jarosite (acid, dry caps) is not a
  material yet.
- Deposit spots come from the refinement entity ids (`root_map_seed`), so
  the same planet generated again under another id places them elsewhere.
- One ore system per element and tile; districts with clusters of
  deposits get one per level.
- Other sulfide deposits (pyrite, galena, sphalerite, arsenopyrite ...)
  are still fresh sulfide patches under an oxidizing air: only elements
  with supergene data weather. Their pyrite and iron would make gossans by
  the same rules.
- The iron-oxide visibility (1.5 wt%) and the ore system's 0.9 exposure
  are calibrations.

### Mapped element minerals - one copper for map and colour (2026-10-17)

Owner: "ok continue" (item 2 of the copper plan: one solution for the tint
and the mapped minerals).

**Before.** True colour tinted pixels with copper's minerals
(`apply_element_pigments` inside `alter_surface`); the rock map did not
know them; LOD2+ deposits were placed by the older `mineralization_potential`
hint, apart from the ore districts.

**Built.**
- `element_pigments.surface_minerals` returns each element mineral's
  visible areal share (fresh hosts, weathering minerals) instead of a tint;
  the chemistry is unchanged.
- `material_lod._element_minerals` computes them from the visible mix
  (rock, cover and deposit bodies) with climate, runoff, residence time and
  the district factor (`residence_years` and `weathering_slope` now shared
  from `true_color_physics`); `_overlay_element_minerals` gives them their
  share and the rest of the cell gives way. LOD0 and child products.
- `material_heatmaps` keeps these layers whatever their mean share, flags
  them `visible_fraction` and records `element_mineral_summary`. True colour
  mixes them as that share (no coating boost) and computes no pigments of
  its own; its `element_districts` grid is gone
  (`planet-true-color-v18-element-minerals-mapped`).
- Regional deposits: a candidate that is at least 1 wt% of an element with
  districts has its selection score multiplied by the district factor at
  its spot (33-node grid over the tile from `metallogeny.enrichment`, the
  planet's seed from `strata.planet_strata_seed`). `suitability` stays the
  local 0..1 fit; occurrences record `ore_district_factor`. Other deposits
  keep the mineralization hint.

**Result.**
- 2 % twin, LOD0 (`artifacts/copper_minerals_mapped_lod0.png`): true colour
  as with the tint (Delta-E Earth twin vs copper twin: mean 0.57, p95 3.5);
  the rock map now shows the districts too (chrysocolla 2.2 %, malachite
  0.7 % of the map's area; the Earth twin's copper layers round to 0).
- LOD2 deposits, stored tiles re-derived: the 2 % tile between districts
  (factor 0.70) had 6 of its 8 deposits copper, now none; the 30 % tile in an
  arc district (factor 2.3-3.2) had 6, now 8.

**Open.**
- A district tile fills all 8 slots with copper minerals at separate spots:
  hypogene chalcopyrite and bornite, supergene chalcocite and covellite, the
  malachite/azurite oxide cap and the gossan are zones of one deposit
  (item 3, the weathering profile with depth). The older
  `mat_malachite_azurite_gossan` overlaps the single minerals.
- Cover materials without stated trace content are left out of the copper
  mean instead of diluting it, so copper minerals show through a cover in
  proportion to its share, not its thickness.
- Stored worlds need regenerating (no live worlds).

Tests: `tests/test_metallogeny.py` (tile grid, copper deposits),
`tests/test_element_pigments.py` (minerals as layers, no coating boost);
88 targeted tests pass.

### Ore districts - where a copper planet keeps its copper (2026-10-17)

Owner, asking what a credible copper planet needs: "lets work trough them
starting with 1" (1 = copper in districts, not an even tint).

**Card** in `simulations/world_gen/metallogeny.py`: porphyry belts above
subducting slabs, sediment-hosted copper in rift basins, massive sulfides at
spreading ridges, magmatic Ni-Cu and native copper in plume basalts; shares
of the copper mined 60+ / 20 / 6 / 4 % (Kesler & Wilkinson 2008, Singer 1995,
Sillitoe 2010; unverified). Each district type is its mechanism's own band
in the orogen forcing (the arc band with its along-strike pulses, the rift
axis, the ridge; hotspot tracks by volume), times metallogenic provinces
(planet noise, ~1000 km; Richards 2003, Hronsky 2012). Local factor
`E = (1 - f) + f sum w_k F_k / <F_k>`: area mean exactly 1, `f` = 0.3.

**Probe.** On the twin planet: 18 % of land at E > 2, max 15.6 with the
plume share at 10 % (narrow hotspot tracks); 4 % (closer to magmatic
copper's real share) gives 8.6.

**Built.** Copper element card `metallogeny` (district share, type shares,
basis; `tools/author_element_pigments.py`, schema field); the true-colour
model keeps one factor grid per element (`element_districts`, <= 257 nodes);
`element_pigments` reads it as the local crust abundance before each rock's
own preference. The regional tectonic snapshot now carries the hotspot model
(plume districts below LOD1). Model `planet-true-color-v17-ore-districts`.

**Track B found on the way: acid-base accounting.** In a district the
copper's sulfides made acid that no carbonate could neutralise (pH terms
were added: +2 carbonate, -3 acid). Now acid potential 31.25 kg CaCO3/t per
wt% oxidizing sulfide sulfur against neutralising potential 10 kg/t per wt%
CaCO3 plus 10 kg/t from silicates; NP/AP below 1 drains acid, above 2 stays
neutral (Sobek et al. 1978; Price 2009). A district over carbonate keeps
its copper minerals; over unbuffered rock its own sulfides leach them
(a leached cap), as in real porphyry districts.

**Result, 2 % twin LOD0** (`artifacts/copper_districts_lod0.png`): land
copper 2.0 % mean (planet 2 %), copper minerals cover 14 % of the land's
colour (was 10 %); teal districts on the north-eastern island and at the
end of the western continent, redder ground between; the richest belt lies
under the southern ice. LOD2 models carry the grid (the stored 2 % tile at
21.3 N 91.2 W lies between districts: 0.7 everywhere). Tests
`tests/test_metallogeny.py` (mass, arc side, window, buffered/unbuffered);
178 targeted tests pass.

**Open.** The leached cap shows no iron of its own (the sulfide iron does
not feed the ferric staining); deposits and mapped copper minerals still
placed apart from this field (item 2); IOCG and other types folded into the
arc share; `district_share` and the visibility constants are calibrations;
`mineralization_potential.py` (the older hint) is not yet replaced by this.

### Open points of the planet stack (2026-10-17)

Owner: "ok, lets adress the open points. please also provide pictures".

1. **Child rims.** `restep` sharpened parent faces up to the rim and
   rockfall worked there too (test tile: 136 m and 84 m off the parent). Both
   now fade with `rim_fade` like every other child detail; the canyon-only
   rockfall fade and its second `build_order` are gone. Real chain: LOD2,
   LOD3 and LOD4 rims are their parent's to 0.00 m (interior p99 245 / 19 /
   16 m). `tests/test_regional_landforms` asserts it.
   *Found on the way:* below LOD1 the landform step got `root_planet=None`,
   so the cliffs' stack had no tectonics (no folds, no uplift), the
   fallback seed "planet" and 40,075 km for the circumference. It now reads
   tectonics and seed from the parent's snapshot (all boundary segments, the
   planet's seed) and the circumference from `planet_circumference_m`.
2. **Units drawn per tile.** New `simulations/world_gen/crust_units.py`:
   units are cells of a jittered 3D lattice on the sphere (rungs 600 km ..
   6 m; a map takes the finest of 8 cells or more), measured
   anisotropically along the planet's strike (`strata.strike_field`,
   double-angle blend of the convergent segments) by 1.8 where the crust
   is shortened; draws per unit and material are a Gaussian copula of a
   smooth planet noise (weight 0.45, 1.2 units) and white noise (stronger
   correlation, 0.84 over 2.5 units, broke the parent's mixture: 27 % of a
   60 % rock, lineage dE p95 26); faults sit one per cell of a 3D lattice
   shell at the surface, oriented by the strike there, density from the
   strain at the fault's own centre. Contact warp seeded by the planet.
   Two chains centred 120 km apart: the same dominant rock on 94 % of their
   shared LOD1 ground (shifted 11 %; the rest is hairline contacts between
   the two grids) and 84 % at LOD2 (shifted 12 %; beds move with each tile's
   own terrain detail). Cost ~2 s units + ~1 s faults per LOD2 tile.
3. **One rock per bed per tile.** A cliff bed's rock is now the one most of
   its exposed cells draw on the rock map (`regional_landforms._stack_bed_rocks`
   from the parent's composition, the storage root handed to the landform
   step); the rock map draws beds from layered rocks only.
4. **A varied chain, and LOD4.** `HeadlessWorldGenConfig.regional_child_center_fractions`
   places each finer map in its parent. Chain 21.3 N 91.2 W, LOD3 on the most
   varied window of the LOD2 tile, LOD4 inside it (396 s): LOD2->3 the
   child's dominant rock is the parent's on 0.90 of parent cells (shifted
   0.38; gneiss 59 / phonolite 24 / siltstone 17 % against 60 / 14 / 25 %),
   LOD3->4 0.95 (one rock, says little; silt in new channels).
5. **Cost** of the second canyon `build_order`: removed with 1.

Figures `artifacts/strata_chain_lod2_3_4.png`, `units_overlap_lod{1,2}.png`,
`rim_lod2_minus_lod1.png`. Tests: `tests/test_crust_units.py` (new),
`test_material_lod` (the per-tile rank-uniform draw test removed with the
function), 215 targeted tests pass; `test_headless_worldgen` (full chains)
not run.

**Open.** Unit elongation follows the convergent segments only (transform
belts are not elongated); beds and units of two chains still differ where
their terrain detail differs (bed depth reads the tile's own elevation);
LOD5+ untested; the earlier note that `restep` siblings agree is now a
consequence of the rim fade, not measured on two siblings.

### Planet stack - layered rock that children inherit (2026-10-17)

Owner: "anchor the beds to the planet so children inherit them" (the open
item of the fold-stripe entry), then, choosing among options: the rock
cliffs cut the planet's stack too.

**Card** in `simulations/world_gen/strata.py`. One stack and one
structure for the planet: the exposed bed is the one at depth
`Z_ref - elevation`, `Z_ref` = rock uplift - tectonic subsidence + regional
warping (sphere noise, ~1500 km, 1 km) + folds; folds only where the crust
was shortened (crustal thickening index), each train parallel to its
convergent boundary segment (frames with one normal sense and one along
origin per orogen system), blended over 120 km (interference at bends),
periclinal and with wandering axes; fold orders 15 km down to 24 m, a map
including those of 8 cells or more. Beds: a nested partition (32
formations per block of 25.6 km depth, each bed split into 4, lognormal
thickness, 800 m nominal down to 0.2 m), a map drawing the finest order
whose outcrops stay 2 cells wide where bedding cuts the ground steeply. All
of it from planet position and the planet seed
(`world_gen_seed.resolved_map_seed`).

**Probe first.** On a real LOD3 child (2 % twin chain, 21.3 N 91.2 W,
scratch `inherit_check.py`) the child's rock matched its LOD2 parent at
chance (0.26 against a shifted-parent 0.26). The new stack itself inherited
(`child_probe.py`: 93 % dolostone composition, 97 % dolostone beds), but
`rock_scarps` kept its own per-level stack (random thicknesses per level,
planar dip of the first tile, 40 % parent-rock share) and overwrote the
rock map wherever its records reached: 100 % of layered ground.

**Built.**
- `strata.py` (structure, partition, per-cell and per-bed rock draws);
  `material_lod._layered_beds` draws layered units from it.
- `rock_scarps`: a record keeps the stack's horizon on a 128-node grid
  (`structure`, read by `dip_offset` for every consumer: restep, rockfall,
  canyons, sea cliffs, soils) instead of a planar dip frame; beds are the
  partition at `BED_ORDER` {2: 1, 3: 4, 4: 5}; a finer bed keeps the
  coarser record's rock `0.88 ** order gap`, else draws from the parent's
  rock mix with planet-anchored uniforms. `regional_landforms` evaluates
  the horizon for the tile and passes the planet seed.
- The rock map draws each bed's rock from the local composition; the cliff
  record's one rock per bed (for the profile's strength) shows only on
  faces (`face > 0.5`). A record holds one rock per bed for a whole tile,
  which cannot match a 300 km tile's local rock: on the second chain run it
  gave 0.38 against chance 0.22.
- `regional_landforms`: what a new order does because of the canyons it
  steps counts as theirs for the rim fade of their rockfall (a 487 m canyon
  reaching the rim leaked 2.3 m into it).

**Result.** Same chain, rock maps rebuilt with the final code
(`inherit_probe.py`): child mode = parent on 0.96 of parent cells (shifted
parent 0.74; the window is 97 % dolostone). A second chain on another window
was 99.9 % schist (0.99 / 0.99: says nothing). The mechanism on mixed folded
rock (`tests/test_strata.py`, child composition from the parent at 82 %
purity): 1.00 against chance 0.62. Neighbouring maps agree on their edge,
a coarse surface re-evaluated on a child equals the parent's, beds nest
(tests). 210 targeted tests pass.

**Open.**
1. `restep` changes a child's rim by up to 136 m on the test tile (each
   parent cell keeps its mean, but there is no rim fade); rockfall on the
   same rim 84 m. Not caused by this entry (its arithmetic is unchanged),
   larger with the taller cliffs; siblings re-step the same parent records,
   so they should agree, but this was not measured.
2. Cellular (non-layered) units still draw per tile chain, so two chains
   centred differently show other units at LOD1-2 (seen when the second
   chain recentred).
3. The cliff record keeps one rock per bed per tile; faces can show a rock
   the surrounding bench does not (lateral facies). Their strength comes
   from that one rock.
4. Real chains for a varied LOD2-LOD3 window still to be found; LOD4 not
   run.
5. Cost: one more `build_order` per tile where canyons exist.

### Fold stripes - layered rock at LOD2 (2026-10-17)

Owner: "lets adress the stripes" (open item 6 of the element-pigment
entry: long straight diagonal bands across whole LOD2 tiles, in True Color
and the material map).

**Probe first** (scratch `stripe_probe.py`: rebuild a stored tile's material
product with `_layered_beds` wrapped, then bed parity from each term alone).
On the 2 % twin's Region tile (300 km, strike 125 deg): bed-boundary density
0.20 with all terms, 0.026 from the land surface alone, 0.20 from fold plus
regional dip alone. The fold term's gradient was 12 times the ground's.
Two causes:

1. The fold was `sin(across / wavelength)`: one infinite, straight train with
   the same phase along the whole tile. Real fold trains are periclinal:
   anticlines plunge out after a few wavelengths and the next starts offset
   (Zagros whalebacks: wavelength 10-15 km, 50-200 km long; the Valley and
   Ridge zigzags at plunging noses).
2. Its amplitude was `0.15 + 0.85 x strain`, with strain the orogen
   forcing's `cumulative_strain_index`: the maximum of convergent, divergent
   and transform influence, up to 1.8, at or above 1 on 83 % of this
   planet's land. Folds at full amplitude nearly everywhere, rifts and
   transforms included, and never below 15 % on stable ground.

**Fix** (`material_lod._fold_surface`): the train's amplitude follows a
smooth envelope along strike (`FOLD_PERICLINE_ASPECT` 6 wavelengths) and
its axes wander (std `FOLD_AXIS_WANDER_WAVELENGTHS` 0.25, varying over one
fold length along strike and from fold to fold across it); it is scaled by
the crustal shortening, the forcing's `crustal_thickening_index`
(`_tile_shortening`), with no floor. Fault offsets keep the strain index.

**Before/after** (same tiles, only the material product rebuilt):

| tile | shortening | boundary density before | after | elevation alone |
|---|---|---|---|---|
| 2 % twin, 21.3 N 91.2 W | 0.92 | 0.202 | 0.111 | 0.026 |
| 30 % world, 26.0 N 76.6 W | 0.31 | (stripes) | 0.064 | 0.040 |

The strongly shortened tile keeps folds, as plunging, en echelon lenses in
patches with ground between them whose belts follow the topography; the
weakly shortened one shows broad units along the terrain and the regional
dip. Figures `artifacts/lod2_folds_before_after_site{1,2}.png`. Tests
`tests/test_layered_folds.py` (flat without shortening, die out along
strike, axes wander); `test_material_lod`, `test_material_routing`,
`test_geochemical_placement` pass.

**Open.** Beds are still drawn per level: bed thickness is the tile's
relief / 7 and the fold and bed seeds are the level's, so a child redraws
its parent's beds (contract 4); one strike per tile; the fold wavelength is
2.5 unit scales of the level, not a property of the rock.

### Element pigments - copper in true colour (2026-10-15)

The owner: "all worlds have the same coloration at lod-0"; test with two
worlds on the same inputs, one superrich in copper ("copper is perfect for
this because we can also check chemical weathering"). Scope agreed: a
general mechanism, copper first; 2 % Cu (about 700 times Earth's crust).

**How it was.** LOD0 colour = lithotectonic settings x rock recipes
(availability from the element distribution), climate covers that are one
material per planet, linear areal mixing of optical cards, then ferric
staining from each rock's iron. Rock cards list major oxides only, so trace
elements could not reach the colour; every copper mineral was a LOD2+
deposit. Rock colour change of the 18 LOD0 recipes against Earth (fresh
reflectance, before climate):

| crust | recipes changed | mean dE | max dE |
|---|---|---|---|
| Cu 2 % / Cr 1 % | 0 | 0.00 | 0.00 |
| Mn 3 % / S 3 % | 4 | 0.01 | 0.15 |
| Fe x2 | 18 | 11.0 | 31.6 |
| Ca x3 | 14 | 6.4 | 27.7 |
| Mg x4 | 18 | 9.6 | 28.2 |
| K x2.5 | 13 | 7.4 | 27.7 |

The real twins (`silicate_terrestrial`, seed `copper-twin-001`, 74 s each)
differed by mean dE 0.05. The 2 % twin's heightfield is not bit-identical
(other fingerprint), changes of a pixel at coasts only.

**Phenomenon card:** in the docstring of `simulations/world_gen/element_pigments.py`
(Atacama, Bisbee, Katanga, Keweenaw; Turekian & Wedepohl 1961, Rudnick & Gao
2003, Williamson & Rimstidt 1994, Sauve et al. 2000, Vink 1986, Chavez
2000, Reich & Vasconcelos 2015; entered from memory, unverified).

**Built.**

- Ontology (`tools/author_element_pigments.py`, store only, no `.owl`
  export): `trace_element_ppm` {Cu} on 107 rocks, sediments and regoliths;
  `supergene_behaviour` on the copper element card (primary hosts,
  secondary phases, log Kd against pH); seven new minerals with
  `supergene_stability` niches (malachite, azurite, chrysocolla, atacamite,
  brochantite, tenorite; native copper as a host); visible reflectances for
  chalcopyrite, bornite, chalcocite, covellite (they shared one grey) and
  cuprite (was grey; its display colour had its channels rotated to green).
  New formation category `supergene_oxidation` (constituent, LOD2+) and
  affinity profile.
- `element_pigments.py` owns the rule; `true_color._mix_areal_endmembers`
  carries each pixel's trace content (Earth reference), rock CO2 and SiO2;
  `appearance_environment` adds the air's O2 and CO2 and the planet's
  chloride; `alter_surface` applies it after the ferric staining. Model
  `planet-true-color-v16-element-pigments`.
- With Earth's sulfur, 2 % copper is 93 % native copper and 7 % chalcocite
  (copper takes sulfur first; there is not enough of it).

**Result on the twins** (abiotic air: O2 0.08 %, so sulfides oxidize at a
sixteenth of Earth's rate but still within the residence time). See the
before/after sheet in the session; numbers of the pigment step on land:

| ground | share of land | dE |
|---|---|---|
| humid (aridity < 0.1) | 0.13 | 1.1 |
| sub-humid | 0.20 | 1.9 |
| semi-arid | 0.45 | 5.3 |
| arid | 0.22 | 5.3 |
| silicate / mixed / carbonate rock | 0.27 / 0.64 / 0.09 | 1.7 / 5.4 / 1.7 |

Mean 0.7 wt% copper minerals (chrysocolla > malachite > azurite), visible
on a tenth of the land's colour: a grey-teal tint over the ferric brown,
strongest on dry ground; humid ground keeps little (leached); pure
limestone has almost no copper to show. The Earth twin is unchanged
(pigment cover 0.0002).

**Open items.**

1. Mapped copper minerals (LOD2+ deposits, including the old combined
   `mat_malachite_azurite_gossan`, filed as a hydrothermal sulfide) are not
   placed from the same field as the tint.
2. Dust: the dust mantle is ground from the colour before the pigments
   (copper does not reach Mars-like dust).
3. Only copper has data; Cr, Ni, Mn, Co, U, V are candidates for the same
   fields (no code change needed).
4. LOD0 sameness beyond trace elements: climate covers are one material per
   planet whatever rock lies under them (not measured yet); runoff on this
   world is low even where it is humid (median 46 mm).
5. Visibility constants (`PIGMENT_VISIBILITY_WT_PERCENT` 6,
   `PRIMARY_VISIBILITY_WT_PERCENT` 30) are calibrations, not measurements.

**Follow-up (2026-10-16): LOD2, and a 30 % copper world.** Owner: "what
would this look like at LOD2? also, lets try a 30% copper planet, even if it
is unrealistic, just to see how it behaves". Runs: headless, LOD1
2000 x 1200 km and LOD2 300 x 180 km around one point (250-280 s each).

- *LOD2, 2 % copper* (21.3 N 91.2 W, the strongest LOD0 tint): the tile's
  rocks are copper-richer than the LOD0 average (3.7 % against 1.6 %),
  1.9 wt% copper minerals, a quarter of the colour. The same region with
  Earth's copper against 2 %: dE mean 5.5, p95 7.5 (olive and grey-green
  over brown). The twins themselves differ by more (6.9): their heightfields
  are not identical, so the LOD2 lithology differs too; compare a region with
  copper on and off, not the two twins.
- *30 % copper* (copper a major element, every other element x 0.7) found
  three faults, all fixed with tests:
  1. Rock content scaled linearly ran past 100 % (basalt 95 %, skarn 160 %).
     `element_pigments.rock_content_percent` keeps each rock's preference as
     an odds ratio, c/(1-c) = k p/(1-p): linear at trace levels, saturating
     (basalt 58 % at 30 %).
  2. The volatile budget booked every cation as an oxide before the
     volatiles had oxygen, copper as CuO: 30 % copper took the oxygen of
     the water and the CO2 and made a reducing world (28 bar CH4, 525 K,
     no sea, Titan haze). Copper, nickel and cobalt oxides are less stable
     than water (Ellingham), so `volatile_budget.NOBLE_CATION_OXYGEN` gives
     them only the oxygen left after water and carbon; the rest stays
     native metal. After: 0.69 bar N2, 284 K, oceans, oxidized
     (`tests.test_volatile_budget.NobleMetalOxygenTests`). Earth unchanged.
  3. Chrysocolla, tenorite and the other weathering minerals passed the
     foundational-lithology rule (a mineral of an element that makes up
     >= 5 % of the crust becomes planetary bedrock) and entered the LOD0
     recipes, so their copper was counted twice (rock copper read 99 %).
     `natural_materials.ALTERATION_PRODUCT_CATEGORIES` keeps weathering
     products out of it: their planet-scale expression is the alteration.
- *Result, 30 %:* rocks average 23 % copper, nearly all native (Earth's
  sulfur holds 0.3 %); weathering leaves 12 wt% copper minerals, mostly
  chrysocolla: teal continents, red-brown where humid ground leached the
  copper. At LOD2 (26.0 N 76.6 W) the tile splits along the clay mantle:
  teal rock to the south, leached red-brown under the mantle to the north.

Further open items from the follow-up:

6. LOD2 tiles of both twins show long straight diagonal bands in True Color
   and the material map (layered beds, `material_lod._layered_beds`); they
   read as hatching across 300 km. Not looked into.
7. On the 30 % LOD2 tile a rectangle is left without any alteration and is
   not drawn as water either: probably a lake known only as a parent box,
   which True Color no longer draws but still takes out of the land mask.
   Not verified.

### Chain pass - the same ground from Site to Survey, and what a collection puts on it (2026-10-11)

The owner asked which level a Biosphere can first be run on, and for a
refined chunk of every level under it, checked for consistency, "to be able
to design and test inter-LOD interactions in regards to the collection".

**The first level is the Site** (LOD4). `terrain_site.founding_report` asks
for ground resolved to 12 m or finer, which is a Site's; and from the Site
down the generator writes what the Biosphere reads (water table, run-on,
soil water, floods, salt). Under it lie the Parcel (LOD5), the Plot (LOD6)
and the Survey (LOD7, the last step to the 10 cm floor, under a Plot wider
than 38 m). A Biosphere can be founded on any of them.

**The chains.** Two on Biosim World, each a map under the one before
(`tools/stress_ground_water.py make`, look-only, kept as cases):

| | wet (Cfb) | dry (Cfa, montane) | cells | made in |
|---|---|---|---|---|
| Site | `refined_lod4_29a30fb2ae`, 3.2 x 1.8 km | `refined_lod4_4ef0f98c8b` | 8.4 m | 66 s |
| Parcel | `wet_parcel`, 600 x 340 m | `dry_parcel` | 1.6 m | 65-77 s |
| Plot | `wet_plot`, 100 x 56 m | `dry_plot` | 0.26 m | 107-157 s |
| Survey | `wet_survey`, 38 x 21 m | `dry_survey` | 0.10 m | 30-35 s |

**The check** (`tools/lod_flora_chain.py check`, look-only): every map
under the first has its ground read twice, from itself and from the map
above, with every biome given the collection of its Koppen zone
(`tools/author_zone_collections.py`): the biome's word, the cover of every
layer, where each species stands, and whether the single plants set out
from above stand at the same spots.

**Found and put right.**

- *Every map drew its own woods.* A species' patches were placed by a noise
  in the map's own metre frame, ranked among the values of the window
  looked at, with a seed from the map's or the city's id; single plants
  were numbered by the lattice cell they fell in. So the same ground showed
  other woods at every level, in a city and in a Biosphere founded there:
  species stood on the same ground on a tenth to a fifth of it, and 4 to
  18 % of the trees set out from one map stood at the same spot on the map
  under it. Now both are the planet's
  (`potential_vegetation.GroundFrame`): a map says where on the planet its
  frame lies (`source_uv_bounds`, the planet's circumference), the patch
  noise is read at the place in the planet's own space and ranked over the
  whole planet (a rare plant is met on a twentieth of the planet, and a
  window holds a patch of it or none), a plant stands on one of the places
  a planet-wide lattice keeps for its spacing where the cover there takes
  it, and the seed is the planet's (`planet_seed`). Ground that does not
  say where it lies (a hand-built plot, a fixture) is a plane of its own.
- *A river wider than a tile lying in its bed was no river on it.*
  `alluvial_channels.channel_fields` kept a centreline only within a tenth
  of the tile's size beyond the tile. A Plot of 100 m on the bars of a
  river 382 m wide lost it: no channel, no bars (its Parcel called 42 % of
  that ground riverside, the Plot none), no floods, the river not in its
  list, new channels free to be carved in its bed. A centreline now counts
  as far beyond the tile as its channel and levees reach.
- *The solver's fill of a carved river counted as a lake.* A carved channel
  fades out towards a tile's rim, which shuts its trough, and the drainage
  solver fills it almost to the banks. On the dry Site that "lake" stood
  4.3 m above the river's mean-flow stage, drowned its bars and set the
  water table beside it: with the river at its own stage the table under
  the Site's land lies at a median of 3.5 m, not 2.1, and within 0.3 m of
  the surface on 5.5 % of it, not 9.5. A fill inside a carved channel and below its
  banks is now no water body (`fine_hydrology`; a lake that stands above
  the banks still drowns the channel).
- *A lake handed down as its parent's box flooded the whole tile.* The box
  says which lake it is; filled to the lake's level it took every hollow
  of the tile that lay as low, so a Parcel showed water on 76 % of ground
  its Site showed 57 % of. The box is kept to where the parent had water
  (`parent_open_water`).
- *A finer tile drained its parent's lakes.* The drainage solver of a
  finer tile finds a lake's sill again on its own ground, where a notch the
  parent could not see lets the water out lower. An old river channel that
  held two to three metres of water on the wet Site (lake levels 1328.1 and
  1329.0 m) lay all but dry on its Parcel (1327.5 and 1327.1 m): water on
  12 % of the Parcel's ground by the Site, on 8 % by the Parcel. A lake of
  the parent's now keeps the parent's level on the finer tile, which draws
  the shore on its own ground and does not look for the sill again
  (`fine_hydrology.parent_lake_level`; hollows the tile finds for itself
  stay its own): 13 % by the Parcel. The painted test showed this; the
  figures of the check had not, because they compare only ground that is
  land on both maps.

**Tests that are pictures** (`tools/lod_flora_chain.py`, painted as a city's
map paints its ground, each plant its species' own picture from above):
`zoom` paints the ground of every map of a chain from the map above it and
from itself, side by side; `zones` lays twelve climates over one map's
ground and paints each with the collection of its zone (desert bare but for
the water's edge, tundra a heath without a tree, taiga pine and birch).
The plant test of `check` is exact: a plant set out from the map above has
to stand at the same spot wherever the finer map gives its species as much
cover there, and all of them do (19,942 of 19,942 on the wet Parcel).

**After.**

| ground of | read from | same biome word | species on the same ground (by cover) | single trees found again |
|---|---|---|---|---|
| wet Parcel | its Site | 0.96 | 0.84 | 0.87 |
| wet Plot | its Parcel | 0.94 | 0.84 | 0.87 |
| wet Survey | its Plot | 0.98 | 0.97 | 4 of 4 |
| dry Parcel | its Site | 0.98 | 0.78 | 0.67 |
| dry Plot | its Parcel | 0.99 | 0.78 | 0.67 |
| dry Survey | its Plot | 1.00 | 0.94 | 0.91 |

Before the planet's anchoring the wet chain read 0.10, 0.10 and 0.20 for the
species and 0.18, 0.04 and 0.05 for the trees. A city's map and a Biosphere
founded on it (wet Site, 80 m of living area) now share 69 % of their
plants at the same spot, four trees in five; they shared none.

What still differs between a map and the one above is the ground itself
read more closely: the water's edge to a cell, and the smaller relic
threads a finer map adds to a flood plain (on the dry Plot some twenty
chute channels two to three metres wide, each with a fill that holds water
and does not drain, where its Parcel has two swales). Plants of moist and
soaked ground follow those; the woods do not move.

Also seen: what reads a map for the Biosphere counts water from 5 cm of
depth (`worldgen_substrate.OPEN_WATER_DEPTH_M`), so a brook shown as a
thread a few centimetres deep is ground beside a channel to it, and open
water only on the level that carves it.

Also seen: an uncarved brook is water at the level of the ground, and the
water table is held to it. On the wet Site that made the ground beside the
brook a wetland (48 % of the Plot's ground, where the Parcel read before
the brook was shown gave 9 %). A brook of that size is cut in a hand or
two; the level that cannot carve it holds its table that much too high.

**Open.** A flora is filed under a biome's key, which begins with the
Koppen class: ground whose warmest month lies on a class line (the wet Site
has 21.9 degrees, the line between Cfb and Cfa is 22) would change its
collection with a tenth of a degree, and nothing holds a finer map to its
parent's class but the conserved climate. The catalogue's spacing of plants
comes from the planet's kept pictures: two sessions that keep different
pictures would set other plants out. A biome's flora is still assigned
region by region.

### Salt pass - where the ground water of a coast is the sea's (2026-10-11)

The stress pass found ground water fed by the sea counted as fresh: on an
arid coast trees rooted into it and the shore read as a fen. Card first.

**Phenomenon card: the freshwater lens of a coast, and the salt ground
beside it.**

- *Name and real examples.* Fresh ground water floats on the sea water that
  lies in the ground under every coast: the lens of the Dutch dunes (Badon
  Ghyben 1888), of Norderney (Herzberg 1901), of every atoll and barrier
  island. Where no lens forms the ground water is the sea's: salt marsh and
  mangrove within reach of the tides (the Wadden Sea, the Sundarbans), and
  the sabkhas of arid coasts (Abu Dhabi), where too little rain falls to
  hold the sea out.
- *Characteristic sizes.* The boundary lies `rho_f / (rho_s - rho_f)` = 40
  times as far below sea level as the water table stands above it (sea
  water 1025, fresh water 1000 kg/m3): a table 0.5 m above the sea rides on
  20 m of fresh water. The boundary is a zone of mixing, not a surface,
  metres thick where tides and seasons pump it (Cooper et al. 1964; 5 to
  10 m on atolls, Underwood et al. 1992); a lens thinner than that is
  brackish to its top, which is why wells on low islands turn salt. Within
  reach of the tides the sea itself floods the ground: up to mean high
  water, half the tidal range above mean sea level.
- *Why this LOD.* The water table is reckoned from the Site (LOD4) down, and
  the salt of a shore is a matter of tens to hundreds of metres: a lens
  fresh to its top begins where the table has risen a hand above the sea,
  which under 300 mm of recharge is within tens of metres of the water
  line, and under none of it nowhere. A Local map (LOD3, cells of tens of
  metres) carries no water table.
- *Formation and controls.* Recharge against the pull of the sea: the
  generator's regional water table already has the sea as a fixed level and
  recharge piling ground water up behind it (Dupuit), so the height of the
  table above the sea is known under every cell. Tidal range (the parent's
  coastal model) sets how far the sea itself comes. It does *not* form: on
  a tile without sea (a Site a few kilometres inland of an arid coast reads
  fresh, a limit of the tile, noted); around lakes, whose salinity the
  generator does not yet tell.
- *Abiotic caveat.* None: the salt is in the water whether or not anything
  grows. What grows on it (salt marsh, mangrove) is the Biosphere's.
- *Layers and the single geometry.* One raster at the water table's own
  lattice, the share of sea water in the ground water at the table
  (`groundwater_salinity_rows`, 0 to 1), read off the same head the depth
  to the water table is read off. Consumers: the Biosphere's kernel and
  solver (a plant bears salt in reach of its roots by its authored
  `salinity_tolerance`) and the biome word (wet and salt is a salt marsh,
  not a fen). Height, materials and True Color do not change: the salt
  crust of a sabkha is left for a later round.

**Built.** `fine_hydrology.groundwater_salinity`: the share of sea water at
the table is `1 - (1 + 40) h / 5 m` between 0 and 1, `h` being the height of
the table above the sea; 1 in the sea and on ground no higher than mean
high water that is joined to the sea over ground as low (`tidal_ground`;
the tidal range is the one the shore's landforms were built with,
`tidal_range_m`). Written as `groundwater_salinity_rows` in the runoff grid
of a tile that has sea, with a summary in `fine_surface_hydrology`
(`salt_ground_water`); a finer tile takes its parent's figure
(`parent_groundwater_salinity`), as it takes the table. Substrate field
`groundwater_salinity`. The Biosphere reads it in `ecology.salt_in_reach`
(the salt counts as far as the ground water is within reach of a plant's
roots or of the capillary rise above it; a water plant meets all of it) and
`salt_response` (by `salinity_tolerance`: *low* bears 5 % sea water and
fails at 25 %, Maas & Hoffman 1977; *medium* 20 and 55 %; *high* the sea
itself, Flowers & Colmer 2008; a plant that says nothing counts as low), a
limit like water in the kernel and in the solver. `biomes`: wet ground
whose ground water is more sea than rain is a *salt marsh*
(`Cfb/salt_marsh`), with a flora of its own.

**Checked.** On a coast rising 2 cm a metre out of the sea
(`tests/test_salt_ground_water.py`): with no recharge the ground water is
the sea's under all the low ground, with 5 mm under the first hundred
metres, with 40 mm under a fringe (3 % of the land), with 300 mm under next
to none. On the arid coast of the stress pass (3 x 1.7 km, all within 3 m
of the sea, 272 mm of rain): salt 0.92 under ground half a metre above the
sea, 0.45 between one and two metres, 0.11 between two and five; 3 % of
the tile reads salt marsh and 1 % stays a fresh wetland (the hollows
inland); the salt takes trees from 13 to 6 % of the land (the same solver
with and without the raster; they were 17 % before the solver took the
kernel's competition figures the same day), and shuts them out of a wider
band than herbs because their roots reach the table. Sheet:
`artifacts/stress_ground_water/coast_salt_ground_water.png`.

**Open.** A Site without sea in sight reads fresh however near an arid coast
it lies (a Local map carries no table to hand down). Salt lakes and salt
springs are not told. The soil model's own `salinity_index_rows` (salts
left by evaporation, a qualitative index) still acts on every plant alike
through fertility; the tolerance of salt should read it too, once it is an
amount. No tidal range reached the test coast, so the tidal rule is checked
on built ground only. No halophyte in the catalogue but *Nitraria
sibirica*: a salt marsh stays bare.

**Track B: a brook lost in a pond.** The stress pass found a brook of
20 l/s carved on a Plot whose Parcel showed dry ground there. The Parcel
has the brook's water (inflow of 4 to 12 l/s at three points of its rim,
20 l/s gathered), but the rule for streams too narrow to carve read it off
the routing of the wetness terms, which ends in every water body: the
brook ran into a retained pond within a few cells and was not seen again.
A stream is now followed down the single path of steepest descent, as the
carving rule follows it, through any lake on its way and over its sill, to
a carved channel or the sea, and is water along all of its thread (the
riffles a finger deep too): 322 cells of brook on the Parcel, 68 of them
under the Plot's ground, where there were none. Sheet:
`artifacts/stress_ground_water/brook_parcel_and_plot.png`. *Why the Parcel
did not carve it* is the scale gate working on two slopes: the gate
estimates a channel's width from the slope of single cells (0.7 to 1.3 m
here, under the 2.4 m a Parcel resolves), the reach its Plot traced found
3.2 m on the valley slope of flat ground, width going with slope to the
power -0.2. Left as it is: the gate is a first sieve at every level, and
moving it moves every river. Biosim World's two Sites were made again in
place afterwards (66 and 67 s; `check` finds nothing; brooks are 0.16 and
0.49 % of their cells). On the dry Site one of them runs nearly straight
for 1.3 km along the foot of a straight step in the ground: the step is
the heightfield's own (it showed as a straight wet line before) and wants
a look of its own.

**Not built: the demand of the air in cold climates.** The stress pass read
a tile at 0 to 6 degrees with 1103 mm of demand as a tundra given a
desert's air. The tile lies at 16 degrees of latitude: a high plateau of
the tropics, under a tropical sun, with dry air. Such ground does have
that demand (El Alto, 4050 m, about 1300 mm a year against 600 mm of
rain), and the generator's figure for a dozen Earth climates lies within a
third of what is reported for them, arctic tundra included (189 mm against
200 to 250). The mechanism is right and was not touched. What the tile
lacked was plants of its cold: with the thermal range of the plant
catalogue (below) arctic-alpine species hold where the shared limits gave
0.1. Left from this: the generator's relative humidity is not read against
temperature (0.03 to 0.09 over cold dry ground, where even deserts keep
0.15), which matters little at cold temperatures; and frozen ground, the
thing that makes arctic lowland wet, is not in the generator at all.

### Stress pass - the water systems on five kinds of ground and three levels (2026-10-11)

The owner asked for the water table, run-on, floods, soil water, the
Biosphere's balance, the solver and the resident start to be stressed "at a
few different LODs and circumstances". `tools/stress_ground_water.py` does
it look-only: it refines maps in memory with the generator as it is, keeps
them as files under `artifacts/stress_ground_water` (a cache, 229 MB after
this pass) and writes nothing to the ontology. One subcommand is one burst.

**What was run.**

- *Ground no map hands over* (`extremes`): 34,560 single places of the
  balance (no rain to 20 m of it, no demand, frozen and scalding air, no
  store, missing figures, run-on of a kilometre either way), the same over
  arrays, every moisture preference against every waterlogging class and
  nonsense, flood returns for sections a nanometre to 60 m deep, and the
  fine hydrology on tiles that are dead flat, a 45 degree wall, three cells
  across, all sea, without rain, under 20 m of rain, a pit, centimetre
  roughness at 10 cm, kilometre cells called a Site. No crash, nothing out
  of range; the water table of a 1025 x 1025 tile takes 1.6 s.
- *Real ground* (`make`, `check`): the wet and the dry Site of Biosim World
  (Site), a Parcel under each, a Plot under the wet Parcel (100 x 56 m at
  0.26 m, 157 s to make: the longest burst), the hot-steppe Site of the
  city prototype made again by the generator as it is, a Site on a tundra
  upland with no river, a Site on an arid coast, and a Local map (coarser
  than a Site, where none of this is reckoned).
- *Eight climates over one map's ground* (`climates`): hyper-arid to wet
  oceanic, monsoon, boreal and tundra, laid in memory over each Site.
- *The played kernel* (`play`): a Biosphere opened on residents at sodden,
  moist, drained and river-bar points of every Site, of the Parcel and of
  the Plot, a tree or shrub brought in in year 3, six to eight years each.
  Seasons 2 to 190 ms in the median, 1.2 s at worst; opening 0.2 to 0.8 s.

**Found and put right.**

- *A finer tile reckoned a water table of its own.* Over the same ground a
  Parcel put it 0.37 m deeper than its Site (single points 1.6 m either
  way), and a tree met another wetness class on two points in five. A
  finer tile now takes its parent's table as a surface and measures its own
  ground against it (`fine_hydrology.parent_water_table`): mean within
  0.04 m, the same class on 86 to 91 % of points; a Plot against its Parcel
  within 0.02 m.
- *A finer tile moved nearly twice the run-on* (619 against 339 mm over the
  same ground): finer cells gather the same water into narrower lines. Its
  total is now its parent's (`parent_run_on`), the pattern its own.
- *Perched water was reckoned with the asking plant's own store*, so on
  sodden ground a tree's deep roots took up the surplus a herb's could not
  and the tree read drier than the herb (on more than 2 % of the dry Site's
  land under three of the eight climates). It is the soil's own store now
  (`water_balance.PERCHED_SOIL_DEPTH_M`).
- *Run-on's nought was taken before the rim was set aside*: ordinary ground
  read -2 mm.
- *A flood's field note was dated a season late, and a species the river
  took was said to have been "overgrown by taller plants".*

**Found and left** (each wants a decision or lies upstream).

- *The demand of the air in cold climates.* A tundra upland at 0 to 6
  degrees is given 1103 mm of demand against 216 mm of rain
  (`water_cycle.annual_reference_evaporation`: 4.5 MJ of radiation a day at
  the pole, no frozen season), reads "very dry" on 89 % of its land and
  carries nothing. A real tundra asks for 200 to 300 mm and is wet.
  *(Wrong, see the salt pass above: the tile is a tropical plateau at 16
  degrees of latitude, where that demand is real.)*
- *Ground water fed by the sea counts as fresh.* On the arid coast trees
  root into it (canopy 17 %) and the shore is a fen. It wants the salinity
  of ground water (a freshwater lens where recharge keeps one) and the
  plants' authored salinity tolerance.
- *What the solver gives a mixture is more than the kernel keeps.* Residents
  on marginal ground or under trees thin or die out within three to ten
  played years ("overgrown by taller plants"): the solver shares the ground
  layer by layer, the kernel sets every stand of the same disc against
  every other.
- *More of a Parcel floods than of the same ground at Site scale* (12 %
  against 6 % within ten years on the wet Site; the two agree on 93 % of
  points): the swales a Parcel cuts lie under the flood, the bars it raises
  were dry already.
- *A brook the Plot carves is not on its Parcel.* A stream of 20 l/s runs
  through the wet Plot as a carved channel 3.2 m wide (4.5 % of the Plot is
  its water); the Parcel lists the same stream among its rivers, has cells
  fine enough to carve it (1.6 m) and shows neither channel nor water.
  That is the channel pass's scale gate, not these systems; it shows in
  `artifacts/stress_ground_water/same_ground_three_levels.png`.
- *On dead flat or merely rough ground run-on follows the routing's noise*
  (up to 7.7 m a year into centimetre dimples at 10 cm cells). Wetness
  takes no harm, rain alone making ground fresh at most.
- *Heat and cold limits are not authored* for most plants: a coast redwood
  stands on a hot-steppe bar at 41 degrees.
- *A map made before these passes carries none of the rasters* and is read
  by its wetness index (the stored hot-steppe Site). No live worlds: make
  it again.
- *In a look-only session a stored map made again in place comes back with
  its stored models* (the refinement updates the stored entity, and with
  nothing written the heavy fields are read back from the store). It only
  matters to tools; the stress tool hides the stored id while it refines.

### Flood pass - how often the river covers its ground, and how often it reworks it (2026-10-10)

The water pass left bars carrying the vegetation of old ground. The owner:
"yes we should do this somehow". Card first, this time.

**Card.**

- *Name and examples.* Flood stage, and the reworking of bars. The bare and
  half-grown bars of the Platte, the Tagliamento and the Loire beside
  gallery woods a few metres higher; the bands of cottonwood of one age on
  the point bars of the Milk and the Missouri, each band a run of quiet
  years (Mahoney & Rood 1998); black poplar seedlings on Loire bars, half of
  which die by erosion and burial in floods (Wintenberger et al. 2019).
- *Sizes.* The bankfull flow returns about every year and a half (median
  1.5, range 1 to 4 and more; Dunne & Leopold 1978, Williams 1978; an
  incised channel floods far more rarely). Within the banks depth goes with
  discharge to the power 0.4 (Leopold & Maddock 1953). Flood peaks arrive
  like a Poisson process with exponentially spread excess (Todorovic &
  Zelenhasic 1970), which gives `Q_T / Q_bf = 1 + g ln(T / T_bf)`; the
  growth g is steeper the drier the climate. Over the banks the plain
  carries the excess as a wide, rough second channel (Manning):
  `rise / D = ((Q / Q_bf - 1) (W_c / W_f) (n_f / n_c)) ^ 3/5`. A gravel bed
  moves at about bankfull: bankfull stress is about 1.2 times the stress
  that starts it (Parker 1978), so a surface is reworked when the water
  over it is about as deep as five sixths of the bankfull depth.
- *Why this level.* Banks and bars exist from Site scale, where the channel
  is carved; height above the river has to be known to decimetres.
- *Mechanism and controls.* The stage a flood of a given return period
  reaches, from the carved channel's own section (bank, mean-flow stage,
  bankfull depth) and the plain's width; a cell is covered when that stage
  reaches it and reworked when it stands deep enough over it. *Does not
  form:* without a carved channel (streams too small to carve, lakes, the
  sea) there is no stage to reckon; ground beyond the reach of the channel's
  fields is never covered. Levees that keep low ground behind them dry, ice
  jams and backwater are not in it.
- *Abiotic caveat.* Plants roughen a plain and hold a bar; the roughness
  ratio is bare ground's. What stands on ground reworked every few years is
  for the Biosphere to say from the raster.
- *Layers.* `surface_water_grid`: how often a cell is covered and how often
  it is reworked, in years. One geometry: the carved channel's fields and
  the heightfield. Height, materials and colour already carry the bars.

**Measured** (Biosim World's Site `refined_lod4_4ef0f98c8b`, its hydrology
read again in memory from the stored heightfield; the store was not written,
the application was open).

- The river: 405 m wide, 5.9 m deep in the mean at bankfull, a plain 22
  channel widths across, bankfull about five times the mean flow, so peaks
  grow by 0.71 bankfull flows per e-fold of return period.
- Covered within 2 / 10 / 100 years: 10 %, 22 % and 40 % of the land.
  Reworked within 2 / 10 / 100 years: 0.9 %, 4.6 % and 8.5 %, a band along
  the channel and the lowest swales.
- Bars inside the banks (6 % of the land): covered every 1.1 years in the
  median, reworked every 5.3 (a tenth of them within 1.6, a tenth not within
  30). The levee the carved volume is returned as stands 2 m above the
  channel's bank level at its edge and is covered about every 20 years.
- Read off the nearest point of the channel, the stage jumped where the
  inside of a bend is as near to one limb as to the other, the river falling
  two metres across the tile: straight wedges of ground "never covered" beside
  ground covered every other year. Read along the valley axis the relics
  already measure from (`floodplain_relics.valley_frame`, one smooth curve),
  one height against the bank gives one answer.
- What stands there (resident vegetation, same solver, with and without):
  trees 0.10 -> 0.00 of the ground reworked every 5 to 15 years, 0.14 ->
  0.05 where it is every 15 to 60; herbs keep 0.34 to 0.70 of it; nothing
  changes on the 86 % of the land the river never reworks. Summed over the
  Site the species' shares move by tenths of a per cent.

**Rules.**

- `world_gen/river_floods.py` owns it: `discharge_for_stage`,
  `return_period_years`, `stage_above_bank_m`, `flood_fields`. Constants
  `BANKFULL_RETURN_YEARS` (1.5), `FLOOD_GROWTH` (0.4 humid to 1.5 arid, by
  the bankfull-to-mean flow the channel was sized with),
  `OVERBANK_ROUGHNESS_RATIO` (2), `REWORKING_DEPTH_SHARE` (0.4).
- `alluvial_channels.channel_fields` also returns the bankfull section's
  mean depth, its deepest point and the mean flow as a share of bankfull.
- `fine_hydrology` writes `flood_return_period_rows_years` and
  `flood_reworking_return_period_rows_years` into `surface_water_grid`
  (999 where no flood reaches) and a summary under
  `fine_surface_hydrology["floods"]`.
- The Biosphere's side: `docs/biosphere_worldgen_hookup_v001.md` 3.3.

**Tests.** `tests/test_river_floods.py` (8): the stage of a flood from the
section; the gradient from the water's edge to the plain, humid and arid; a
Site's two rasters; one height, one answer along a valley; what a plant
needs between two floods; the catalogue's verdict; a year's flood taking
what stands on reworked ground; trees standing back from the river.

**Open.**

- `REWORKING_DEPTH_SHARE` is a reading, not a measurement: it stands for a
  bar surface finer than the bed and a plant lost with centimetres of
  scour. The growth figures are of the right order; the arid curve was not
  checked against a published one.
- Levees do not keep ground behind them dry.
- Being covered does nothing yet beyond being told: no silt on the plain,
  no drowning (the water table sorts low ground already).
- A plain turned over by a migrating channel in centuries is not in it.
- Finer levels than Site reckon their own floods from the reaches they
  inherit, along the same axis.

### Water pass - the water table, run-on and what a soil holds (2026-10-10)

The owner: "wetness should work like it does in real life with drainage,
precipitation and ground water", for the Biosphere, at the levels where it
belongs; and river bars "should follow realistic mechanisms". The wetness
index says where the climate's surplus goes. It does not say how wet ground
is for a plant, which depends on the plant: that is a water balance, and
the generator's part is to hand over what the balance reads. The card was
written with the code, not before it.

**Card.**

- *Name and examples.* The water table and its reach. A river terrace three
  metres up whose trees stand in ground water while its grass burns off in
  summer (cottonwood galleries of the Great Plains, the gallery woods of
  central Texas and the East African highlands); sloughs and oxbows that
  stay wet behind a dry levee; the wet foot of a slope and the dry nose
  above it.
- *Sizes.* The table lies at the level of the water it drains to and rises
  between waters by about `R L^2 / 8T` (recharge R, spacing L, transmissivity
  T): decimetres under 40 mm of recharge and a kilometre between waters,
  metres under 300 mm. Capillary rise above it: centimetres in gravel and
  coarse sand, about a metre in loam, two and more in clay. Water a metre of
  soil holds for plants: 60 to 90 mm in coarse sand, 160 to 190 mm in loam,
  130 to 190 mm in clay (Salter & Williams 1969). On hillslopes the depth
  falls by `1 / f` for every e-fold of `a / tan(b)` (Beven & Kirkby 1979).
- *Why this level.* A table that matters to roots lies within a few metres
  of the ground, and the ground has to be known to decimetres along a bank
  or a swale: 8 m cells (Site) are the first that hold a floodplain's relief.
  Coarser levels keep the wetness index.
- *Mechanism and controls.* Steady flow to open water through ground of one
  transmissivity (Dupuit; Fan et al. 2013 run it worldwide), seeping out
  where it meets the ground; on slopes the soil mantle passing on the
  recharge gathered from upslope (TOPMODEL), along the steeper of the
  ground's slope and the fall to the water beneath (Hjerdt et al. 2004).
  Recharge alone feeds the table; runoff travels over the surface and is the
  run-on. *Does not form:* with no recharge the table is flat at the water's
  level and unreachable under high ground (Haitjema & Mitchell-Bruker 2005:
  recharge-controlled); with no open water on a tile only the hillslope
  reading exists.
- *Abiotic caveat.* None of it assumes plants. What a soil in the making
  adds to storage is the Biosphere's (`RAW_GROUND_STORAGE_SHARE`), not a
  generator field.
- *Layers.* `runoff_grid`: `water_table_depth_m_rows`,
  `lateral_water_rows_mm`. Soil grid: `available_water_capacity_rows_mm_per_m`,
  `capillary_rise_rows_m`, `rootable_depth_m_rows`. One geometry: the
  heightfield, the open water read off it and the topographic index the
  wetness index already uses. Height, materials and colour are unchanged.

**Measured** (Biosim World's Site `refined_lod4_4ef0f98c8b`, 3.2 x 1.8 km of
river valley floor, 933 mm of rain, 1944 mm of demand, 36 mm of recharge,
rebuilt in place in 67 s, heightfield unchanged).

- Depth to the table on land: 0.07 / 1.1 / 2.1 / 3.1 / 4.7 m (p05 / p25 /
  p50 / p75 / p95); within 30 cm on 9 % of the land, the swales and low
  banks. The hillslope reading is the shallower on 39 % of the land.
- A first version took the level of the nearest water in a straight line
  and drew the seam between two waters of different level as a straight
  edge across the map; the relaxed table has none. Along a tile's rim the
  routing gathers what cannot leave (run-on of +870 mm in the outermost
  row); the two rasters take what stands three cells in (`RIM_CELLS`).
- Run-on is measured from the tile's ordinary (median) cell: nought there,
  hundreds of millimetres along lines of flow. A first version measured it
  from the mean, which a few lines of flow hold up, and so took the ordinary
  cell's runoff and recharge off its rain: 120 of 933 mm here, 640 of
  1730 mm on the humid Site made later. The monthly balance sheds that
  surplus itself, so it went twice, and a humid plain read "mesic".
- Soil: 107 mm/m and 0.38 m of rise in the median (sandy alluvium), 190 and
  1.5 in the channel fills; rootable 3 m over the floodplain where the soil
  itself is 1 cm on the bars.
- Wetness for the Biosphere (built soil): a herb's 0.28 in the median (dry),
  a tree's 0.49 where its 2 m of roots reach the table. The share of land
  with under 5 % plant cover went from 27 % to 3 %; trees stand thickest
  where the table lies 1 to 2 m down (canopy 41 %; 61 % since a plant is
  no longer scored down for more water than it likes), not at all where it
  is at the surface, and thin where it lies below 3.5 m and they have the
  rain alone (17 %, then 18 %).
- A second Site in a wet part of the same planet (`refined_lod4_29a30fb2ae`:
  1732 mm of rain, 1308 mm of demand, 263 mm of recharge, 14 m of relief
  over 3.2 km): the table within 30 cm on 29 % of the land and within a
  metre on 65 %, flat ground that sheds nowhere under a wet climate, and
  two to three metres down along the river's levees. A herb's wetness 0.56
  in the median, built soil at the default point 0.50.

**Rules.**

- `fine_hydrology.regional_water_table`, `hillslope_water_table_depth`,
  `water_table_depth`; constants `AQUIFER_TRANSMISSIVITY_M2_PER_YEAR` (7300:
  a metre a day through twenty metres), `TRANSMISSIVITY_M2_PER_YEAR` (4400)
  and `CONDUCTIVITY_DECAY_PER_M` (1) for the soil mantle.
- `regolith_soils.soil_water_properties` (by clay share), relic fills fine
  and fresh bars coarse, `FLOODPLAIN_ROOTABLE_M` (3); a finer tile inherits
  the three fields with the rest of its parent's soil.
- `biosphere/water_balance.py` reads them (Thornthwaite & Mather's monthly
  book-keeping, Stephenson 1990 and 1998, Prentice et al. 1992 for the scale,
  Klinka et al. 1989 for the classes above fresh). The Biosphere's side is
  in `docs/biosphere_worldgen_hookup_v001.md` section 3.3.
- `biosphere/biomes.py`: a wetland is ground whose table stands within 30 cm.

**Added the same day: what the subsoil lets through.** The owner asked that
poorly drained soil count for plants. `regolith_soils.soil_drainage_rate`
writes `drainage_rate_rows_mm_per_day` from the clay share (the fall with
texture is Rawls, Brakensiek & Saxton's 1982 for topsoils; a subsoil at a
fifth of its topsoil is this module's reading): 1000 mm a day in sand, 10
in a clay loam, 1 in a clay; a silted channel 1, a fresh bar 1000. The
Biosphere's balance stands the water in the soil where a wet month leaves
more to drain than that. Measured: 11 mm a day in the median on the wet
Site (3.5 % of its land under 5), 295 on the dry Site (18 % under 5, its
channel fills, which the climate never fills). On neither does perched
water change what grows; it will on clay ground. Slopes are not in it.

**Persistence.** A finer tile cut out of a Site cannot see the water that
sets its table. `LayeredSubstrate` therefore takes the Site's depth and adds
the difference between the finer ground and the Site's at the point, so a
chunk's hollow is nearer the water and its rise further from it, on one
table. Since the stress pass (2026-10-11) the generator does the same when
it makes a finer tile: its own raster is its parent's table against its own
ground, and its run-on total its parent's.

**Tests.** `tests/test_water_balance.py` (15): the balance across climates,
ground and rooting depths; arrays against single places; soil water by
texture and on a floodplain, inherited by a child; the table between two
waters with and without recharge; hollows and wet climates; a low bank
against a terrace; the kernel, the biome word and the solver reading it.

**Open.**

- One transmissivity for all ground: a clay flat drains no worse than a
  sand. The soil model runs after the hydrology, so texture is not at hand.
- Floods are not modelled: no stage above the mean, no disturbance of
  bars, no recruitment band.
- Levels finer than Site write a table from their own tile only (see
  Persistence); a Biosphere on a Parcel without its Site beneath would read
  that.
- The demand of the air on this Site is twice its rain in a zone the
  temperatures name Humid Subtropical. Whether the zone label or the
  demand is off was not looked into.
- The Site's heightfield dips by about a metre over the five cells along
  its west rim (0.4 m a cell on three rows in four), and straight-edged
  steps cross it from north to south (the clearest along one column near
  the middle, 0.2 m against 0.06 m elsewhere). Both show in the table and
  the wetness drawn from it and were left as found.

### Open-points pass - ground keeps draining, sand within reach of the waves (2026-10-08)

The owner asked for the four points the lake pass left open: surface
evolution on freshly laid ground, the sea cliffs under the base-level rule,
tests for the sea mask, the sill rule and the lake drawing, and the beach
figures on current code. Re-checking the arid coast found three defects
more, and they were fixed in the same pass.

**1 - Surface evolution leaves ground the waves and rivers have just laid.**

- *Measured* (humid Local tile, raw evolution result captured): delta and
  lake fill moved by -0.9 / +0.16 / +1.2 m (p10 / p50 / p90) by the end of
  the step, the berm by up to +0.56 m. The solver lowers every cell by its
  own score and the parent's mean is then taken out, so flat deposits come
  out raised against the slopes round them.
- *Rule.* `regional_refinement._laid_ground` reads the beach's sand grid and
  the deltas' sediment grid (0.3 m of either is the surface), and
  `_edge_faded_evolution` scales its change by what is left.
- *Result.* Both passes move delta fill and beach by 0.00 m. What still
  moves on a delta plain is the river's own bed fit (-0.26 .. +0.14 m).

**2 - No step leaves ground deeper under its outlet than it was.**

- *Survey.* Arid Region tile, closed hollows of 2 m or more after each step
  (priority flood to the sea and the tile rim): none after the dissection.
  Rock steps: 45 hollows, 9.1 km2, up to 10 m (a tread lowered behind its
  own lip, a bed raised across a valley). Fans: two pits, 11 and 17 m deep,
  where the catchment's wear met the cone. Surface evolution: 2.7 and
  5.3 km2 more in its two passes (a reach that scores higher than the one
  below it). The last bed fit: 11 hollows, 1.4 km2, up to 10 m. At the end
  72 hollows, 11.1 km2 (0.31 % of the land), 17 lakes, and three "lake
  deltas" a thousand metres up. Humid Region tile: 47.1 km2 (0.79 %), the
  deepest 57 m, 66 lakes.
- *Rule.* `regional_landforms.depth_under_outlet` (how far a cell lies under
  the level its water leaves at) and `hold_above_outlets(change, elevation,
  sea_level)`: where a change leaves a cell deeper under its outlet than it
  was, the cell comes up by the difference. Running water wears ground down
  towards its outlet, never under it; a stream cuts its gap through a riser
  as fast as the riser comes to stand out, and a cell cannot hold the gap,
  so the ground behind stands level with the lip. A hollow the ground had
  keeps its depth. Applied to the rock steps (after the base-level hold),
  the fans, surface evolution (not under ice, which does overdeepen its
  bed) and the last bed fit. Not applied to floodplain relics (swales and
  abandoned channels are hollows on purpose); a lagoon behind a beach lies
  below sea level and is an outlet to this rule.
- *Result.* Arid Region tile: no hollow of 2 m at any step, lakes 17 -> 2,
  the shoreline cell for cell as before. Humid Region tile: 47.1 km2 -> 0,
  lakes 66 -> 15. The Local tiles under them hold none either (the arid one
  had 0.40 km2). The rock steps were held on 379 (Region) to 4,256 (Site)
  cells. A Region tile takes 105 to 121 s as before.

**3 - The sea cliffs under the base-level rule.** Unchanged within 2 %.

| Arid coast | Cut cells | Retreat (m) | Cliff heights (m) |
|---|---|---|---|
| Region, before / now | 0 / 0 | - | - |
| Local, before / now | 828 / 825 | 88-256 / 88-256 | 11.6-73.8 / 11.5-73.7 |
| Site, before / now | 5,779 / 5,893 (10.8 / 11.0 % of the land) | 12.6-245.1 / 13.2-245.1 | 1.3-68.0 / 1.4-68.4 |

**4 - A parent's sand only on a bed the waves can cover.** A parent's beach
cell handed its sand to every cell under it, also to the cliff top the
child resolves inside it: on the arid Site tile a tenth of the cells with
sand stood more than 29 m above the sea, were beach to the materials and
(since 1) held as laid ground. `shore_deposits.sand_within_reach` keeps
handed-down sand where the bed under it stands no higher than the highest
berm. Beach cover in the materials: Local 2.0 -> 0.8 %, Site 17.6 -> 6.9 %;
the beach itself is unchanged (376 and 1,997 cells), and nine tenths of the
Site tile's sand now stand below +1.1 m (before: a tenth above +29 m).

**5 - The parent contract takes a landform's side on this level's ground.**
The beach rule applied again to the arid Site tile moved 3 % of the land
(open since the beach pass). Not surface evolution: the rule on its own
result moves 5 cells, and no step after the landforms touches the cells in
question. The contract's reference is the parent's surface plus the
landforms' change; where the waves had planed this level's foreshore to
just under the sea the reference still stood 0.6 to 4.6 m above it, and the
contract lifted 218 cells back to a centimetre above the sea, a row of
specks the rule then took for bars and built 880 cells of land behind.
`_topology_without_landform_crossings` drops the parent's certainty where
the landforms took this level's own ground across sea level. Applied
again: 161 cells (0.34 % of the land, most 0.78 m) at Site scale, 45 cells
(0.08 %) at Local.

- *Tests.* New `tests/test_shut_in_water.py` (the sea mask in the heightmap
  masks, read back on other grids and by the fine hydrology; a regional lake
  at its sill, a planet lake in its gorge, a dry basin below its sill; lake
  water on the heightfield; True Color draws sea and lakes, leaves playas,
  parents' boxes and shut-in basins as ground). `OutletHoldTest`,
  `ParentContractTest`, the evolution and bed-fit holds, the reach of
  handed-down sand. 294 targeted tests pass.
- *Figures.* `.cache/screenshots/coasts/open_points_low_shore.png` and
  `open_points_arid_cliffs.png`, both chains regenerated on this code.
- *Open.* (1) The drainage solver reports lakes the heightfield does not
  have. One per Region tile lies along a closed tile edge (26.5 km2 and
  "67 m deep" on the humid tile, 8.4 km2 and "54 m" on the arid one) where
  every cell of the heightfield stands above its surface: never drawn, but
  in the water cycle and handed to children. Small ones come from the
  solver's grid at half the heightfield's resolution: 4.4 km2 are drawn as
  water on the humid Region tile, none of it in a hollow of the ground.
  (2) The hold fills up to the lip. A gap cut through the riser, a cell
  wide, is the other answer and was not tried. (3) With the hold, closed
  hollows come only from the parent and from this level's own detail:
  deflation pans, solution hollows and overdeepening outside the ice mask
  have no mechanism. (4) Sand outlines at Site and Parcel scale still
  follow the parent's cells (a staircase in the Site row of the low-shore
  sheet; 70 % of the Parcel tile's land carries sand). (5) Site tiles hold
  shallow hollows, 0.5 to 1.1 m on 4 % of the land on both worlds; not
  followed up. (6) The last bed fit moves single cells of the arid Region
  tile by up to 60 m; not looked at. (7) Carried over: no delta forms in
  the open sea on either world, the humid river-mouth chain is not rebuilt,
  planet maps are untouched by the sea mask and the sill rule.

### Lake pass - the sea mask, lakes at their sill, lake deltas (2026-10-07)

Agreed with the owner after the beach and delta pass: closed basins below
sea level should hold lakes of their own, and rivers should build deltas
into them. Four steps, each looked at on the humid Region tile before
the next, and one Local tile under it at the end. Step 4 found that the
basins the pass started from were not basins at all.

**Step 1 - which water is the sea.**

- *Survey.* "Sea" was decided as "at or below sea level" separately by the
  heightmap's masks, the water cycle (climate, ocean circulation, drainage
  outlets), the fine hydrology, True Color and the landforms. On the humid
  Region tile 969 cells (53 km2, up to 52 m below sea level) lie in two
  basins behind the shore that land shuts in; they were drawn as sea, were
  ocean to the climate, and the largest river of the tile (23,900 km2)
  ended in one of them.
- *Rule.* One mask for a regional map: the sea is the water joined through
  water to what the parent has as open sea (`sea_cliffs.joined_sea`,
  already used by waves, cliffs, deltas and beaches).
  `refresh_heightmap_derivatives(sea_mask=...)` writes it into
  `surface_masks` (`ocean_rows`, `land_rows`, flag `ocean_is_joined_sea`;
  `regional_refinement._sea_mask` at each of the five refreshes), and the
  water cycle, the fine hydrology and True Color read it
  (`heightmap.joined_sea_rows`). The material layer already read the masks.
  Planet maps are unchanged.
- *Result* (humid Region tile, same window). The two basins are land to
  every layer. The drainage gives them lakes by its own rules: 56 lakes on
  the tile, the two largest in the basins at 33 m and 12 m below sea level
  (4.8 and 2.9 km2). True Color shows the basin floors as bare ground and
  draws no lake there.
**Step 2 - a lake stands at its sill, and is drawn.**

- *Finding.* The drainage's lake rule cut an assumed spillway under every
  overflowing lake (up to 76 % of its depth): right for a planet map, whose
  cells hide the gorge, wrong for a map that has the sill in its own
  heights. The basin above held a lake 39 m under its own outlet. And True
  Color drew no lake at any level: lakes were in the water cycle and on no
  picture.
- *Rule.* On regional maps an overflowing lake stands at its spill level
  (`drainage._lake_components`). True Color draws retained lakes as water
  to their own level and depth (`fine_hydrology._lake_water`), leaving out
  terminal lakes whose runoff keeps less than half their floor wet.
- *Result.* The two basins hold lakes of 35 and 14 km2 at 4.7 and 1.2 m
  above the sea, with the river entering the lower one.

**Step 3 - a river fills the lake it enters** (`river_deltas.build_lake_deltas`,
before the sea's deltas in `regional_landforms`).

- *Rule.* A hollow at least 2 m deep below its sill is a lake if the
  largest river into it brings more water in a year than its surface loses
  (else a terminal lake: nothing built). A lake keeps nine tenths of the
  load whatever its waves do (there is no coast beyond to carry sand to),
  laid from the river's entry as topset and foreset through the lake, as
  far as the load of the stillstand goes and no farther than the far shore.
- *Result.* The largest river (23,600 km2, 41 m3/s, 144 kg/s: 15 km3 in
  6,000 years) fills the lower lake (1 km3) to its far shore: 35.6 km2 of
  valley floor where the lake was, and the river runs on over it to the
  sea. (A lake of 10 km2 at 12.5 m was left inside the same basin: the
  later steps had raised the fill unevenly. See step 4.)
**Step 4 - where the basins came from** (`regional_landforms.hold_above_base_level`).

- *Finding.* Following the filled basin through the steps showed its
  ground standing 21 to 107 m above the sea before the landform step and
  52 m below it after: the rock-scarp remap at Region scale (bed sets of 60
  to 250 m) had cut a bench into the coast and taken 945 cells (52 km2)
  that stood 20 to 89 m above the sea to 13 m below it at the median, by
  70 m at the median. Its weight fades with the height of the ground it
  starts from, not of the bench it cuts to. Both basins were this: the
  lagoon of the beach pass's low-shore figures, the hollow the largest
  river "ended in", the lakes of steps 2 and 3.
- *Rule.* What scarps and canyons cut leaves land at least 15 % of its
  height above the sea: down towards base level, never under it, and a low
  plain with the relief it had rather than a flat.
- *Result.* Ground below sea level that land shuts in: 146 cells (8 km2,
  at most 13 m deep, thin strips) against 969 (53 km2, 52 m). No lake on
  the coast larger than 3 km2; the river runs to the sea. On a Local tile
  under it (16 km at 42 m, on the coast): the parent's largest lake is
  taken over and drawn to the child's own ground (4.0 km2 at 10.6 m), seven
  small hollows in valleys are filled by their streams, and 0.3 km2 lies
  below sea level behind the shore.
- *Also.* True Color no longer draws a lake a level knows only as its
  parent's bounding box (water with straight edges); it draws the lakes
  the level found in its own ground.

- *Open.* (1) Surface evolution raised the flat floor a delta had laid by
  24 m in its first pass and 12 m in its second (medians, Region tile,
  before step 4). The case is gone with the basin, the behaviour is not:
  it belongs to the work on surface evolution after the landforms.
  (2) Lake outlines at Region scale are as coarse as the water cycle's grid
  (two heightmap cells), and every pit of 2 m in the terrain now shows as
  a pond. (3) What a full lake passes on is not followed to the next water
  downstream, and a lake's load is not taken off the mouth below it.
  (4) Only the largest river into a lake builds. (5) A lake the parent has
  and the child finds no hollow for is not drawn at the child's level.
  (6) Small upland hollows 40 to 80 m deep are filled by streams of half a
  cubic metre a second: right by the load, but such hollows are probably
  defects of the valley floors themselves. (7) Landform steps that test
  `ground < sea_level` themselves (rock scarps' fade towards the sea, the
  coastal model's shoreline graph) still take a basin floor for sea bed.
  (8) Planet maps are untouched: closed basins below sea level are still
  sea there, and their lakes keep the assumed spillway. (9) The figures of
  the beach pass were rendered before step 4; their shores stand, the
  lagoon in the low-shore sheet does not.
- *Tests.* `tests/test_river_deltas.py` (`LakeTest`: a delta where a river
  enters a lake, a small lake filled to its far shore and not built on
  again, a hollow its river cannot keep full, no hollows or no runoff).
  `tests/test_regional_landforms.py` (`BaseLevelTest`). The sea mask, the
  sill rule and the drawing of lakes have no test of their own yet. 304
  targeted tests pass.

### Beach and delta pass - LOD2 to LOD5 (2026-10-07)

Fourth ground feature: the depositional half of the coast. Owner's order:
"lets do depositional coast first, maybe we can also cover river deltas
with it". Test sites as in the sea-cliff pass (humid macroregion
`refined_lod1_d706b1dd88`, arid `refined_lod1_e51e1e63c2`, scratch store),
with new windows on a low humid shore and on the mouth of the largest
humid river.

**Survey: what a low coast and a river mouth were** (figures
`depositional_before_*.png` in `.cache/screenshots/coasts/`).

- *No sand anywhere.* Every coast segment of every tile from Region scale
  down is classed "rocky cliff" (fetch is measured inside the tile); no
  beach, bar or delta is built, and `mat_beach_sand` appears on no map.
- *Teeth.* At Local scale the low humid shore ran straight north-south
  with rectangular bays and teeth the size of the Region cells (234 m),
  and at Site scale one of them was a rectangular basin 500 m across. They
  are in the interpolated parent already: the Region tile's shoreline is
  rough at the scale of its own cells, and a child draws a one-cell notch
  as a rounded rectangle. `_refine_coastline` moves little (0.4 % of cells
  change side; 0.54 % of the final shore differs from the interpolated
  parent) and what it moves it moves in rectangles (heights shifted by
  -10 to +13 m inside the mixed parent cells, 81-85 % of which survives
  to the end).
- *A step along every shore.* At Parcel scale 86 % of the land within
  two cells of the water stood at 0.5 m (40 % at Site scale): four steps
  each applied a "stay land" floor of sea level + 0.5 m to every land
  cell, lowered or not (`_fluvial_dissection`, `_floodplain_flattening`,
  the last bed fit, and `alluvial_fans` on tiles with a fan).
- *Ponds with ocean waves.* The largest river (1,620 km2 at its mouth on
  the Local tile, falling 147 m in 9.7 km) ended in a pond below sea
  level 400 m behind the shore. `sea_cliffs.wave_heights` gave such ponds
  the full height of the waves offshore (no land within a parent cell of
  their middle), so they were cut like sea shores.
- *A trough along the shore.* On the Local tile the sea bed is 10 m deep
  170-250 m from the land and 6 m deep beyond (medians by distance); it is
  in the Region tile already, whose first sea cell is 10.8 m deep and the
  next ones 5.9 m. Traced after the pass (track B, item 4).

**Phenomenon card - beaches.**

- *Examples.* The pocket beaches of Cornwall and the Big Sur coast; the
  long beaches of the Landes and of Ninety Mile Beach; a bar across the
  mouth of a small inlet (Slapton Sands); a tombolo (Chesil in part).
- *Sizes and scaling.* Shoreface `h = A x^(2/3)` (Bruun 1954; Dean 1977),
  `A` about 0.1 m^(1/3) for fine sand, 0.125 for the medium sand taken
  here, more for gravel (Moore 1982; Dean 1987); depth of closure about
  1.75 heights of the year's largest waves (Hallermeier 1981; Birkemeier
  1985): 3.5 m and 150 m out for 2 m waves. Beach face 1 in 10 in medium
  sand (Bascom 1951). Berm at the run-up of the swash (Stockdon et al.
  2006), 0.57 wave heights for a sea as steep as the wind raises it
  (Pierson & Moskowitz 1964). Alongshore transport goes with wave height
  to the 2.5th power (CERC; Komar & Inman 1970) and evens a sandy
  shoreline out like diffusion (Pelnard-Considere 1956): for half-metre
  waves, tens of kilometres in 6,000 years. All figures from memory;
  unverified against the sources.
- *Why these levels.* A cove is filled at the first level whose cells
  resolve it (three cells across: 700 m at Region, 125 m at Local, 20 m
  at Site scale); the beach face (11 m wide under 2 m waves) is a shape
  from Site scale and one raised cell above it.
- *Controls, and where it does not form.* Sand and room. No beach where
  the bed in front is deeper than the waves offshore reach (a plunging
  cove), where no waves arrive (a pond), or on a salient.
- *Abiotic caveat.* No foredune (plants hold it), no beach rock, no reef.
- *Layers.* One height change; the sand's thickness is packed into the
  level's record (one byte a cell, deflated) and read by the material
  layer (`mat_beach_sand`, the ontology's only `shoreline` sediment).

**Phenomenon card - river deltas.**

- *Examples.* River-dominated: the Mississippi, the bay-head deltas of the
  Texas estuaries, Lake St Clair. Wave-dominated mouths with no delta to
  speak of: most rivers of an open ocean coast (the Columbia, the rivers
  of south-east Australia).
- *Sizes and scaling.* Load from BQART (Syvitski & Milliman 2007, 488
  rivers): `Qs = 0.02 B Q^0.31 A^0.5 R T` kg/s (checked against the paper's
  abstract and summaries: 0.0006 for Mt/yr, T at least 2 C). Fluvial
  dominance `R` = river sand flux over the most the waves can carry away
  on both flanks (Nienhuis, Ashton & Giosan 2015, checked against the
  authors' summaries); the wave capacity from CERC with `K = 0.39`.
  Retained share 0.4, foreset 2 degrees, topset from a bankfull Shields
  stress of 1.86 (Parker et al. 2007): from memory, unverified.
- *Why these levels.* A delta is built at the first level whose cells
  resolve its radius (four cells), like a fan.
- *Controls, and where it does not form.* `R >= 1`. On these worlds'
  open coasts (storm waves of 1.7-2.1 m) it does not: the largest humid
  river carries 121 kg/s and has `R = 0.2-0.3` in the open; the largest
  arid one 56 kg/s, `R = 0.27`.
- *Layers.* One height change; sediment thickness packed like the sand;
  the plain is the ontology's `floodplain` sediments.

**Mechanism.**

- *Beach* (`shore_deposits.py`, from `regional_landforms` after the cut
  shore and rockfall, from Region scale). (1) Low ground narrower than
  three cells and lower than the berm is planed off to the shoreface
  (islets, spits, the speckle a level's detail leaves on a flat shore).
  (2) Re-entrants are filled by a morphological closing of the land's
  side of the open sea, up to 1.5 km at the first level that builds
  beaches and up to two parent cells below it, only over a bed the waves
  offshore reach, and only as far as 600 m3 of sand per metre of shore
  go. (3) From the shoreline that leaves: the two-thirds shoreface out to
  the depth of closure where the bed lies deeper (on a bed that falls
  away, a prism at most as thick as the closure depth, thinning to the
  foot), the beach face and the berm behind.
- *The rule finds its own result again.* Closing is idempotent, sand is
  only added up to the profile, room is judged by the bed under the sand
  a coarser level laid (handed down in the record), and water the sand
  shuts in is left as water.
- *Delta* (`river_deltas.py`, before the beach). Mouths are where the
  routed flow (hollows filled, the parent's rivers brought in) reaches the
  open sea. For each: load, volume over the stillstand, `R` with the
  waves at the mouth. `R < 1`: nothing but a mouth kept open through the
  beach (from 1 m3/s). `R >= 1`: topset and foreset laid from the mouth by
  distance through the water, as far as the volume goes, and only through
  water where the river still outdoes the waves; the valley floor behind
  the mouth is raised to the plain.
- *Which water is the sea's* (`sea_cliffs.joined_sea`). Water joined
  through water to what the parent has as open sea; each level hands that
  down in its wave record (`open`). Waves, cut, deltas and beaches all
  read it.

**Existing features corrected (track B).**

1. *The half-metre step along the shore* (`regional_refinement._land_floor`,
   `alluvial_fans`). The floor is now where a cell already was if that was
   lower, and the fans' holds only ground a fan built or eroded. Found
   late: the first full run of the chains still had the step (77 % at
   Parcel scale) with only the fans corrected, because the last bed fit
   raised the foot of every beach face again.
2. *Ponds taken for the sea* (`sea_cliffs.wave_heights`). Water the land
   shuts in gets only its own wind sea.
3. *Teeth and speckle on a low shore.* Not corrected at their source; the
   beach closes the notches it has room and sand for and planes the
   speckle off, at every level, so a child no longer inherits them from a
   sandy shore.
4. *The moat and the rim along every shore* (`_edge_faded_evolution`,
   added the same day on the owner's go-ahead). Captured step by step on
   the humid Region tile: the first sea cell is 2.1 m deep after the
   landforms, 6.4 m after the first surface-evolution pass and 10.7 m
   after the second; the last land cell rises by 3 to 5 m at the median
   (16 m at the 90th percentile) each pass. Surface evolution works on
   the water cycle's grid (257 columns against the heightmap's 513 or
   385), so its change comes back smeared across the shoreline, and the
   step that takes each side's mean out left the smear standing: land
   beside the sea had lost too little, sea bed beside the land too much.
   Cells within the smear of the other side now take their own side's
   change from the cells behind them (`_solver_cells` gives the reach).
   Region tile after: 1.6 m at the first sea cell, 6.0 and 12.7 m beyond.

**What was tried first and dropped.**

1. *Shoreface filled to the profile whatever the depth:* 17 m of sand on
   a plunging bed. Now a prism bounded by the closure depth.
2. *Room judged by the sand surface:* each application found the last
   one's shoreface shallow enough to build the shore out over. Now the
   bed under the sand.
3. *Closing with the tile's outside taken for open water:* a large radius
   left the rim unclosed and a small one closed it, so a finer level
   filled what its parent seemed to have left (352 cells on one tile).
   The shore is now continued past the edge.
4. *Berm from the waves of the cove that was filled:* lower than the berm
   the same shore gets when looked at again. Now from the water the shore
   ends up facing.
5. *Open sea from depth alone, then from wave height at the rim:* a pond
   three metres deep seeded itself as sea; a sheltered cove with a fifth
   of the offshore waves counted as a pond one level down. Replaced by
   `joined_sea`.
6. *Deltas into basins the land shuts in:* such a basin is below sea level
   behind a sill; filled, its river left over the sill and the bed fit
   raised the whole plain to it (26 m at the median). A basin of that kind
   would hold a lake at its own level; none is built (open item 5).
7. *Deltas through any water:* a delta that had filled its inlet went on
   as a 4 km lobe into 2 m waves. It now stops where `R` falls under 1.

**Chain test.**

| Level | Site | Waves at the sand | Beach | Coves filled | Sand | Mouths | Half-metre step before / after | Applied again |
|---|---|---|---|---|---|---|---|---|
| LOD3, 41.67 m | low humid shore | 2.12-2.13 m | 308 cells (0.9 % of the land), berm 1.22-1.23 m, shoreface 58 cells | 151 cells of new land, closed to 469 m; 58 planed off | 686 thousand m3, thickest 2.87 m | 9 wave dominated | 7 % / 5 % | 26 cells over 5 cm (0.08 % of the land), most 2.17 m |
| LOD4, 6.25 m | low humid shore | 1.76-2.12 m | 1414 cells (4.4 % of the land), berm 1.01-1.22 m, shoreface 129 cells | 136 cells of new land, closed to 83 m; 0 planed off | 30 thousand m3, thickest 1.59 m | 3 wave dominated | 40 % / 11 % | 39 cells over 5 cm (0.13 % of the land), most 0.70 m |
| LOD5, 0.78 m | low humid shore | 2.12-2.12 m | 3330 cells (3.7 % of the land), berm 1.22-1.22 m, shoreface 347 cells | 145 cells of new land, closed to 12 m; 0 planed off | 0 thousand m3, thickest 0.81 m | none | 86 % / 2 % | 150 cells over 5 cm (0.18 % of the land), most 0.21 m |
| LOD3, 41.67 m | arid coves | 1.83-1.94 m | 372 cells (0.6 % of the land), berm 1.05-1.11 m, shoreface 950 cells | 237 cells of new land, closed to 469 m; 24 planed off | 2,391 thousand m3, thickest 4.05 m | 2 wave dominated | 23 % / 3 % | 47 cells over 5 cm (0.09 % of the land), most 2.82 m |
| LOD4, 6.25 m | arid coves | 1.88-1.90 m | 1981 cells (3.8 % of the land), berm 1.08-1.09 m, shoreface 3819 cells | 463 cells of new land, closed to 83 m; 0 planed off | 105 thousand m3, thickest 2.89 m | none | 6 % / 2 % | 1466 cells over 5 cm (3.06 % of the land), most 1.65 m |

"Applied again" is the beach rule run once more on the finished tile with
the tile's own sand as the sand below (what a child would find to add),
counted inside the rim band. The table is of the tiles refined after the
moat was removed (track B, item 4). Before that the same check moved 0.2
to 2.0 % of the land: the smeared surface-evolution change shifted the
shore cells after the beach was laid. It now moves 0.08 to 0.18 % on
the low shore and 0.09 % on the arid Local tile, and still 3 % on the
arid Site tile (open item 9). The Parcel row is the window of the
survey, which the new shore has left almost wholly on land; the figure
shows a Parcel window picked again on the shore.

Region scale (234 m): 28 beach cells on the humid tile, 81 on the arid one;
22 and 35 river mouths, all wave-dominated. Largest loads: humid 146 kg/s
from 23,900 km2 against 2.0 m waves, `R` 0.56; arid 56 kg/s from 168,800
km2 against 1.8 m waves, `R` 0.27.

The river-mouth chain (Local to Parcel) was refined with the beach and
delta rules but not again after the last two corrections (the floor and
the fresh-deposit cover): the owner's machine cut out twice during the
runs. Its survey figure is `depositional_before_mouth.png`.

Figures: `depositional_low_shore.png`, `depositional_arid_coves.png` in
`.cache/screenshots/coasts/` (before and after in alternate rows, same
windows but for the last Parcel row; the fourth panel shows the sand; both
rendered after the moat was removed).

**Tests.** `tests/test_shore_deposits.py` (profile figures, distances,
closing and opening; berm and face, shoreface, shallow and plunging beds,
cove filled and headlands left, deep cove, kept-open water, the rule on
its own result, a finer level's coves, room judged by the bed, washover,
ponds, sand against room, rim fade, the record), `tests/test_river_deltas.py`
(BQART, dominance, topset, volume; surface, shoreline by volume, a full
basin; a delta in sheltered water, none on an open coast, bigger rivers,
inherited deltas, unresolved ones, water the waves rule, the record),
`tests/test_sea_cliffs.py` (water the land shuts in), `tests/test_alluvial_fans.py`
(no floor under untouched land), `tests/test_low_shore_floor.py` (the three
steps leave a low shore low, each failing against the old floor; a blanket
smeared across the shore leaves neither rim nor moat, as far as the solver
grid smears), `tests/test_regional_landforms.py`
(`SeaCliffTest` allows sand on the cut shore).

**Open items.**

1. The Region tile's cell-scale shoreline roughness in ground too deep or
   too high for sand (notches 6 m deep, teeth 17 m high at the median on
   the humid tile, measured before the moat was removed: part of both was
   the moat and the rim). `_refine_coastline` shifts heights in rectangles
   of mixed parent cells; a shift of the profile along its own slope would
   not. Not measured again.
2. No delta is built on either test world: every river is wave-dominated
   in the open (`R` 0.56 at most), and the sheltered mouths are too small
   for the cells that see them. The rule is exercised by tests only; a
   world with a large river into a bay or with weaker waves has not been
   looked at.
3. The cusp of a wave-dominated mouth and the beaches its sand feeds: the
   sand of every river is one figure for the world. A budget handed down
   from the level that sees the whole coast (river and cliff sand, spread
   alongshore) would replace `BASE_SAND_M3_PER_M`.
4. One grain: no shingle, no mud flat. The ontology has no grain size.
5. Water below sea level that land shuts in is still drawn as sea. It
   would be a lake at its own level, or dry.
6. Barrier islands and lagoons of a shelving coast (none on these worlds:
   the sea bed falls 2-3 % from the shore), beach ridges, cusps, bars.
7. Shore classes: `coastal_geomorphology` still calls every coast below
   Macroregion "rocky cliff" and its depositional ramps are still there
   for the classes it never assigns. The classes should be read off what
   was built.
8. Distributaries and levees on a delta plain; lake deltas; tides.
9. The rule applied again to the arid Site tile still moves 3 % of the
   land by more than 5 cm (up to 1.65 m), against 0.2 % and less on the
   other tiles. Laying the sand with the waves of the shore as the cut
   left it (it was the shore before the cut) did not change that. The
   steps after the landforms are the suspects: surface evolution cuts
   flow lines through a berm, and the last bed fit grades over it.
10. The dry beach is level ground to the soil model and the Biosphere.
11. Constants from memory: `A`, face slope, closure factor, retained
    share, foreset, Shields stress, sand per metre.
12. A tile whose only sea is a sliver at its rim finds no water joined to
    the sea (the parent's `open` grid is sampled at 97 points a side) and
    builds nothing; it keeps its parent's sand.
13. The sand a level inherits is as coarse as its parent's cells: at Site
    scale the inland edge of the beach is stepped at 42 m and the band of
    sand is wider (60-100 m) than the face and berm the level itself
    builds (about 30 m).
14. On the arid chain the Parcel window of the sea-cliff pass now lies on
    land (the cove in front of it was filled at Site scale), and part of
    the sand it inherits lies across ledges the level steps again at the
    cliff foot: the scarp steps of a finer level do not know the sand.
    The coves of the Site tile also differ in outline from the earlier
    pass (its Local parent was refined again with this pass's
    corrections), so its rows are not a like-for-like pair.

### Scale rule - a level is a scale of ground (2026-10-06)

The owner's first run through the Map view (planet Bristoll, a stagnant-lid
world with one continent) made, with most of the planet in view, a
"Macroregion" of 25,000 x 8,400 km at 47.9 km a cell (the planet has 59 km)
and under it a "Region" of 3,640 km at 7.1 km a cell. The generator took
any footprint and called the result one level finer.

- *What went wrong.* Recipes are switched and sized by the level number.
  Rock units are 60 km at Macroregion and 6 km at Region scale
  (`material_lod.UNIT_SCALE_M_BY_LEVEL`): on those tiles a unit was a cell
  or less, 121,009 units over 148,257 cells on the Region tile, and a cell
  had its right neighbour's colour in 57 % of cases. The Region bed order
  (beds of 60-250 m, planes) ruled straight scarps across the continent.
  The opposite case, a small footprint straight from a coarse map, would
  have had none of the landforms the levels in between build.
- *Rule* (contract 9, §2). `footprint_level`, `max_refinement_extent_m`,
  `next_refinement_step`, `describe_refinement`; `generate_refined_region`
  plans the chain and `_generate_refined_step` makes one map. In-between
  maps take cell sizes in equal ratios down the levels, are centred on the
  target and are found again by `_reusable_refinement`.
- *Callers.* The Map view's button says what it would do ("Refine View to
  Site (3 maps)", "Zoom in to refine: max 8.2 Mm", "Finest level reached";
  `MapSimulation.get_refinement_action`) and can refine a selected place
  instead of the view. "Rebuild This Region" rebuilds in place
  (`allow_intermediate=False`). Biosphere chunks are a step of their own:
  a region closer than three times to the 1 m target is used as it is. The
  headless runner and the two tools that refine take the largest window
  that is still a level finer.
- *Also.* `material_lod.MIN_UNIT_CELLS = 8`: a mapped unit is never
  smaller than the grid resolves, whatever the level says. On the Region
  tile above, refined again: neighbours alike in 98 % of cases.
- *Tests.* `tests/test_refinement_scale.py`,
  `tests/test_material_lod.py` (units on a tile too coarse for its level),
  `tests/test_map_region_context.py`, `tests/test_map_ui_workspace.py`.
- *Chain test* (the arid Macroregion of the earlier passes, 1,090 km at
  2.1 km a cell, scratch store). Its whole footprint asked for again:
  refused, "at most 361 km". A Local window of 16 km asked for straight
  away: a Region of 152 km at 297 m a cell was made first, then the Local
  map at 41.7 m with that Region as its parent; 160 s for both, progress
  reported as "Region (1 of 2)" then "Local (2 of 2)" without stepping
  back. A second window 14 km away: one map to make, the Region used
  again. The stored chains of the earlier passes all have the level their
  footprint gives them.
- *Open.* A Survey (level 7) only exists under a Plot wider than 38 m. A
  place wider than 8,192 km (a large continent with its margin) cannot be
  one Macroregion; the grid would have to grow instead. Maps stored before
  the rule keep their number; their level is read off their footprint when
  they are refined.

### Sea-cliff pass - LOD2 to LOD5 (2026-10-05)

Third ground feature. The owner named beaches and coasts as the next
erosion-based forms after canyons ("canyons and coasts have quite a few
similarities"). This pass takes the erosional half, the shore waves cut
into rock; the beach and the low depositional coast are the next one.
Test sites: the humid macroregion `refined_lod1_d706b1dd88` and the arid
one `refined_lod1_e51e1e63c2`, in a scratch store with the rock strengths
of the rock-strength pass.

**Survey: what a coast was** (figures `coast_today_*.png` in
`.cache/screenshots/coasts/`).

- *Steep shores.* The land ramped into the sea: 33 degrees from -19 m to
  +44 m at LOD4, 49 degrees at LOD5, straight in plan. No platform, no
  cliff, no notch. The "rocky cliff" of `coastal_geomorphology` was a
  generic ramp (`sea + min(30 m, 0.72 x distance)`) blended over whatever
  stood within 160 m of the shore, with nothing of the rock in it.
- *Low shores.* The shoreline was a rectangle: straight runs along the
  parent's cell edges with right-angle corners at LOD3, LOD4 and LOD5,
  and land lying flat a metre above the sea behind it. At LOD5 the
  shallow sea and the low shore were a maze of pools.
- *Classes.* Of ten stored macroregions eight are "rocky cliff" from end
  to end and none has a single beach segment: the class scores hand-set
  weights of relief and gradient, and sand needs low relief, a gentle sea
  bed and no river at once.
- *Waves.* Fetch is measured inside the tile (48 cells at most): 430 to
  755 km at LOD1, 0.5 to 11 km at LOD2, 0.2 km at LOD3. Below LOD1 every
  coast is "sheltered". Tides are zero on planet Test.
- Square patches the size of a grandparent cell lie along the shore at
  LOD4: the weight of `_refine_coastline` (the mixed parent cells).

**Phenomenon card - sea cliffs and shore platforms.**

- *Examples.* The chalk cliffs and platform of the Seven Sisters; the
  mudstone platforms of Kaikoura; the drift cliffs of Holderness, going
  back a metre or two a year; the plunging granite and basalt cliffs
  that have hardly moved since the sea reached them.
- *Sizes and scaling.* Recession since the sea came to its level (6,000
  years on Earth) spans four orders of magnitude with rock: millimetres
  a year in granite, centimetres in shale and flysch, decimetres in chalk
  and weak Tertiary rocks, metres in glacial drift (Sunamura 1983, 1992).
  Platforms are tens to a few hundred metres wide, rarely more, because a
  platform shelters its own cliff (Trenhaile 1987, 2000). Cliff height is
  the height of the land cut into. All figures here are from memory;
  unverified against the sources.
- *Why these levels.* A retreat of 100-300 m (weak beds) is 2-7 cells at
  LOD3; 10-90 m (sandstone, limestone, ignimbrite) is 2-14 cells at
  LOD4; 2-6 m (basalt, granite) is 3-8 cells at LOD5. At LOD2 (234 m)
  only the weakest rock under high waves is a cell wide.
- *Controls, and where it does not form.* Rock strength at sea level and
  wave height at the cliff foot. No cut where the waves are spent before
  they reach the land: a shelving foreshore (a beach coast), a sheltered
  inlet, a platform already there.
- *Abiotic caveat.* Biological erosion and protection of platforms
  (borers, algal mats, reefs) are left out.
- *Layers.* One height change. The cliff is rock by the same rockfall
  rule as a canyon wall. The drowned part of the platform is the sea's;
  its dry part should be wave-washed rock and is not marked as such yet
  (open item 12).

**Mechanism** (`sea_cliffs.py`, called from `regional_landforms` after
the scarps and canyons of the level and before rockfall).

- *One field.* The cost of a metre of retreat at every point: one over
  the retreat of that rock under those waves, `W ln(1 + R / W)`, with
  `R = 300 m x (6 MPa / strength)^1.2 x (H / 1.5 m)^2` and `W = 130 H`.
  The shore is where the cost added up from deep water reaches 1.
  Because paths bend, a weak bed behind a breach in a strong one is
  hollowed out and a headland is flanked before it is cut through.
- *Through the water, then through the rock.* The sum starts where the
  water is 1.28 offshore wave heights deep and crosses shallow water at
  the cost of its bed's rock (`cost_distance`). That gives three
  behaviours with one rule: a shelving shore is left alone; a plunging
  one takes the whole retreat; and a level that inherits a platform cuts
  only what is left. On land the sum goes on with the waves each path
  left the water with (`cut_inland`): rock is cut by the waves that come
  the cheapest way to it, so the land behind the head of a creek is cut
  from the open shore beside it.
- *Nothing in the cost reads the height of the land.* The rule therefore
  finds its own result again on ground it has cut and rockfall has laid
  back, and a finer level adds only what the coarser one's cells could
  not hold.
- *Rock.* The bed at sea level in the bed order of Local scale (beds 1.5
  to 6 m, the band waves work on; `shore_orders`), wherever the sequence
  is (its scarps are faded out near the sea; the rock is not), strength
  from the bed's erodibility index; else the parent's rock mix. Every
  level reads the same beds.
- *Waves.* Storm wind (three times the prevailing mean) over the open
  water of the first parent grid with an ocean in view, fetch-limited and
  capped by the fully developed sea; each level records a 96-cell grid
  for its children (the sheltered height and the offshore one), takes
  away what its own land shelters within a parent cell and never goes
  below its own wind sea.
- *Form.* The platform rises with what the waves have spent on the way:
  half a wave height under the sea where they arrive whole, 0.3 wave
  heights above it at the cliff foot where they are spent, never deeper
  than the sea bed where they left the water. It is one profile for
  every level, so ground a coarser level cut to it is left as it is. The
  cliff is left to `rock_scarps.rockfall`, with the platform and the sea
  as sinks; `also=` gives rockfall the rock at each cell's height where
  no scarp order shows.
- *Scale.* A level draws the retreat still left from one cell on, whole
  from two; the cut fades at the tile rim.

**Existing features corrected (track B).**

1. *Generic rock-shore ramps.* The ramps of
   `materialize_regional_coastal_landforms` for rocky cliff, headland-bay,
   fjord and marine terrace are gone: they would wear the cut shore down
   again. The depositional classes keep theirs until the next pass.
2. *The maze of pools and the flat a metre above the sea*
   (`_center_detail_at_parent_scale`). Detail leaning towards sea level
   in a parent cell that is certainly land or sea is compressed against
   the cell's clearance from sea level, and that clearance had a floor of
   a metre. A sea bed 5 cm deep whose detail rose a millimetre was put at
   -1.00 m, its neighbour whose detail fell stayed at -0.05 m: every
   shallow sea bed and low shore at Parcel scale was a two-level maze
   with metre-high walls (1,207 of 3,600 cells of one window at exactly
   -1.00 m). The clearance is now the cell's own.
3. *Parent land that a landform drowned*
   (`_enforce_parent_height_contract`). The contract put every cell of a
   certainly-land parent cell back above the sea, also where this level's
   own landform had taken it under: 7,355 cells of a drowned platform
   came back as dry land in the shape of the parent's cells. The side a
   cell is held to is now that of the reference (the parent with the
   level's landforms in it).
4. *The blanket that drowned the low shores* (`_edge_faded_evolution`).
   Surface evolution scores weathering and erosion on every cell and
   lowers each by its score times an amplitude set by the tile's relief.
   On the humid Local tile all land went down by 3.7 m (2.4 to 4.5 m),
   at every level again: 97 % of the land under 2 m and 56 % of the land
   under 5 m ended under the sea, and the contract then put 801 cells of
   the parent's certainly-land cells back at 0.01 to 2.19 m. That is
   where the rectangular shorelines and the flats behind them came from.
   The parent has its denudation in its heights; the mean of the change
   over a parent cell is now taken out (land and sea bed each by
   itself), and the child keeps the relief the step adds inside a parent
   cell. Shorelines moved with it: the test windows of this pass had to
   be picked again.
5. *Falls graded away* (`material_routing.monotone_channel_beds`). The
   fitted river bed was smoothed along the river over six cells either
   way, the falls the river has of its own included. A stream dropping
   23 m over the new sea cliff at Local scale had its bed cut down by up
   to 9.5 m above the cliff and the platform below it raised by up to
   14 m (110 platform cells by more than half a metre on the arid tile).
   Only what the fit changed is graded now; this also keeps the falls at
   rock scarps and canyon heads from LOD1 to LOD3.

**What was tried first and dropped.**

1. *Sharing a retreat between levels by cell size* (each level its part
   of a partition): it needed a "first level", and a child cut again
   behind a platform its parent had cut. Replaced by starting the cost
   from deep water.
2. *Platform edge half a wave height under the sea, always:* on a low
   coast it dug a moat a metre deep along a shore whose sea bed lies at
   20 cm. The edge now starts at the level of the water in front.
3. *Shelter as the mean open distance:* a cove larger than the search
   radius counted as open sea, and every level took another 20 % off a
   straight coast (2.5 m of waves at LOD2, 0.7 m at LOD5). Now only water
   open to three quarters of the radius counts, and a shore takes the
   waves of the water in front of it.
4. *The rock of the finest bed order:* Site scale found weak decimetre
   beds where Local scale had read a strong bed and cut the shore again,
   233 m back at LOD4 and 85 m at LOD5. Every level now reads the same
   order.
5. *A platform profile measured from the shoreline:* run again on its own
   result it lowered the dry part of the platform each time (216 of 733
   cells re-cut at LOD3). The profile is now a function of what the waves
   have spent since deep water, the same whoever computes it.
6. *Deep water judged by the waves that reach it:* a platform in a cove
   the level's own land sheltered counted as deep again and the shore
   behind it was cut afresh. Deep is now judged by the offshore height.
7. *A cliff-height term* (a cliff 20 m high cut back half as far as a low
   shore, its debris guarding its foot), first as a cost of the rock,
   then as a bound on each cell. Both read ground the rule itself
   changes: as a cost it was gone once the high ground was platform; as
   a bound it took the slope rockfall had laid the cliff back to for a
   low shore. On the humid chain Parcel scale cut 20 % of its land again
   (3 m more at the median, 34 m at most, behind a cliff its parent had
   finished), and applied once more it would have cut as much again.
   Dropped: the evidence for the term was weak to begin with.
8. *Waves of the nearest sea cell for the rock behind it:* the land
   "behind" a sheltered sea cell at the head of a creek took its ripples
   and was left standing as a straight wall across the platform, metres
   high and a cell or two wide.

**Chain test.**

Chains refined again from Region scale with everything above in place;
windows picked on the exposed shore with the highest ground behind it.
"Applied again" is the rule run once more on the finished tile (every
later step included), counted inside the rim band: what a child would
find to cut that its parent had not left to it.

| Level | Site | Rock at the shore, waves | What the level cut | Cliff | Applied again |
|---|---|---|---|---|---|
| LOD2, 234 m | both | - | nothing: no retreat is a cell wide | - | - |
| LOD3, 42 m | arid | 6.2-6.6 MPa, 1.8-1.9 m | 869 cells (1.5 % of the land), 77 to 257 m back, 222 m at the median | 17-74 m, median 37 m | 43 cells by over 0.5 m (0.08 % of the land), 3 over 2 m |
| LOD3, 42 m | humid | 25.7 MPa, 2.1 m | 13 cells, 42 to 71 m back | 4-8 m | 15 cells over 0.5 m (0.03 %) |
| LOD4, 6.25 m | arid | 6.2-101 MPa, 1.6-1.9 m | 6,486 cells (13 % of the land): the cliff foot its parent's 42 m cells could not place, and the strong beds left standing as headlands between coves in the weak ones | 6-82 m, median 41 m | 69 cells over 0.5 m (0.16 %), most 14.9 m |
| LOD4, 6.25 m | humid | 71-91 MPa, 2.05 m | 220 cells, 9 to 21 m back | 1-6.5 m | 9 cells over 0.5 m (0.02 %), none over 2 m |
| LOD5, 0.78 m | arid | - | nothing: the tile lies on the platform with no deep water in view (open item 3) | 65 m, inherited | nothing |
| LOD5, 0.78 m | humid | 71-91 MPa, 2.05 m | 2,401 cells levelled by 1.5 cm on average (2.4 m at most): the inherited platform, 4 to 10 m wide | 0.3-2.9 m | none over 0.5 m (most 0.09 m) |

Before the cliff-height term went and the three steps behind the shore
were corrected, the humid Parcel tile cut 20 % of its land again and the
same rule applied once more to it would have cut 10,463 cells; the
arid Local tile was re-cut on 175 cells. The rule itself takes 0.02 to
0.2 s a tile; tiles take 73 to 84 s at these levels, as before.

Figures: `sea_cliffs_arid_chain.png`, `sea_cliffs_humid_chain.png` in
`.cache/screenshots/coasts/`.

**Tests.** `tests/test_sea_cliffs.py` (wave growth, shelter, the wind
sea of sheltered water, islets; recession by rock and waves, the
platform's own shelter; cost distance round a barrier; platform and
cliff, weak against strong rock, the height of the land not deciding,
a laid-back cliff not taken for a low shore, the land behind a sheltered
creek, the cove in a weak bed, the shelving foreshore, a finer level
cutting only what is left, a cut shore not cut again, rim fade, tide;
waves from the parent grid and from the parent's record; rock at sea
level), `tests/test_regional_landforms.py` (`SeaCliffTest`),
`tests/test_terrain_lod_improvements.py` (shallow water and low shores
keep their height), `tests/test_surface_visual_inheritance.py` (ground a
landform took across sea level stays there).

**Open items.**

1. No beach: the sand this erosion and the rivers supply is not laid
   down, on the platform or in the coves. Next pass, with item 2.
2. The low depositional coast. Its two worst faults went with track B
   (the blanket, the maze), but `coastal_geomorphology` still classes
   every coast below LOD1 as sheltered rocky cliff, no beach, barrier or
   delta is ever built, and `_refine_coastline` shifts heights by up to
   0.4 of the relief across a mixed parent cell: on a cliff that is
   noise of +-20 m (arid Local tile) which the shore cut then has to
   clear away.
3. A tile with no deep water in view cuts nothing, so a plot or parcel
   lying on a platform keeps the cliff foot as its parent's cells left
   it. The cost would have to be handed down like the waves.
4. Platform and cliff are bare of form: no notch, arch or gully, no ribs
   along the beds of a platform. A stream reaching a cliff falls over it
   (in 6,000 years a knickpoint goes back metres, so most valleys hang),
   but a large river gets no gorge either.
5. Beds are planes, so headlands and coves in a dipping sequence have
   straight sides (the arid Site tile).
6. What is left of re-cutting at Local scale (0.03 to 0.16 % of the
   land): river beds fitted more than 2.7 m under the sea count as deep
   water, and later steps move single platform cells.
7. One stillstand and one wave climate for the world; tides enter only
   as a band (planet Test has none).
8. A tile takes the water beyond its edge as open.
9. Cost is added up over eight neighbours: fronts are polygons, off by
   up to 8 % in distance.
10. Surface evolution still lowers every cell by a process score times
    an amplitude set by the tile's relief; only its mean over a parent
    cell is taken out now. It has no mass balance and no base level of
    its own.
11. Constants (recession by rock, the platform's shelter width, the
    storm factor, breaking depth) are from memory and fitted by eye.
12. The dry part of a platform (up to 0.3 wave heights over the sea, a
    strip as wide as three eighths of the retreat) is level ground to the
    soil model and to the Biosphere: it gets soil and plants where storm
    waves keep the rock bare.
13. Inland check of the track-B changes (canyon tiles of the canyon
    pass, Local scale, refined again): canyons as before (28 against 30
    on the arid tile, 24 against 24 on the humid one, same lengths and
    depths), land 2.3 m (arid) and 5.0 m (humid) higher on average, and
    on the humid tile 71 % of cells more than 2 m off that mean: the old
    blanket was up to 15 m thicker on valley sides than on flats.

### Canyon pass - LOD3 to LOD6 (2026-10-05)

Second ground feature of the owner's list ("rock cliffs, canyons and so
on", one at a time), taken up after the rock-strength pass below ("then
2"). Test sites as before: the arid layered macroregion
`refined_lod1_e51e1e63c2` and the humid one `refined_lod1_d706b1dd88` of
planet Test, each refined on its steepest ground down to LOD6 in a scratch
store, with the rock strengths of the pass below applied in memory.

**Survey: where a valley's depth came from.** Nowhere that could make a
canyon. `fluvial_relief.stream_power_relief` organises the noise a level
adds: its incision is capped at the local amplitude of that noise, with
one erodibility for every rock and linear diffusion for valley sides, so
valley depth knows nothing of discharge, of the relief above the river or
of the rock. With the rock cliffs of the last two passes every stream
that crossed an escarpment fell over it: a tile showed closed walls
100 m high running for kilometres, with the drainage crossing them as if
they were not there. One more thing was seen in passing: at LOD1-3 the
last bed fit (`_fit_final_channel_beds`) grades a river across such a
step over about six cells, a trench one cell wide and up to 40 m deep
above the scarp and a causeway below it.

**Phenomenon card - canyons cut back into scarps.**

- *Examples.* The gorge below Niagara Falls (about 11 km behind the
  escarpment its fall started from); the side canyons and alcoves of the Colorado
  Plateau rims (Book Cliffs, Roan Plateau, Canyonlands), where every wash
  that crosses a cap rock runs in a canyon as deep as the cliff; the
  gorges below cap-rock waterfalls generally.
- *Sizes and scaling.* Depth: the height of the scarp cut through, here
  up to 126 m (arid) and 174 m (humid). Length: how far the fall has
  retreated, `dx/dt = C A^p` with the catchment `A` above it (Rosenbloom &
  Anderson 1994; Crosby & Whipple 2006; Berlin & Anderson 2007 for the
  Roan Plateau: `p` 0.54 and about `1.1 A^0.54` m in 8 Myr): 1.3 km for
  0.5 km2, 23 km for 100 km2. Width: a floor as wide as the channel, walls
  at what the rock holds: 60-80 degrees in a strong bed, about 35 in a
  weak one, so 1.5 to 3 times the depth from rim to rim. The retreat law's
  figures are entered from memory; unverified against the papers.
- *Why this level.* A canyon through a bed set of LOD2 (60-250 m) is 100
  to 500 m wide: 0.4 to 2 cells at LOD2 (234 m), 2 to 12 at LOD3 (42 m).
  By the visibility rule it is a mixed cell at LOD2 and a shape at LOD3.
  The same holds one level down for each finer bed order.
- *Controls, and where it does not form.* No stream (catchment below the
  channel-head area): the scarp stays whole and the rill falls over it.
  No scarp: nothing to cut back into. Strong cap rock: slow retreat, an
  alcove instead of a canyon. Where the bench above comes down to the
  level of the scarp's foot the canyon ends by itself; where the retreat
  runs out it ends in a headwall.
- *Abiotic caveat.* None for the form. Vegetation holds debris on walls
  steeper than it would rest: the Biosphere's to add.
- *Layers.* One height change. Rock, soil and colour read the walls
  through `heightmap_scarp_fields` like any other scarp (bare face in the
  cap, debris below); hydrology routes on the cut ground, so the river is
  on the canyon floor.

**Mechanism** (`scarp_canyons.py`, called from `regional_landforms` right
after `restep`).

- *Which streams:* every cell whose catchment reaches
  `material_routing.CHANNEL_HEAD_AREA_M2` (0.5 km2, the stream of every
  other layer), routed as `channel_belts` routes and with the catchment
  rivers bring into the tile.
- *How deep:* a scarp is a change of height around the ground its beds
  were cut into, negative at the foot, positive above the brink. A
  stream carries the foot's value upstream with it (the running minimum
  of that change along the stream, never below the bed it flows to). So
  the floor continues the bench below the scarp, a canyon is never deeper
  than the highest scarp it has cut through, and it shallows out where
  the next bench comes down to that level. No depth parameter.
- *How far:* each cell spends `hop / (1.1 A^0.54 x rock factor)` of the
  retreat; at 1 the stream is back on the surface (the headwall) and
  stays there until the ground stops rising across it. The rock factor is
  inverse to the tensile strength of the strongest bed between floor and
  rim, read from the bed's erodibility index: 0.2 (quartzite) to 5
  (pumice, shale), 1 for sandstone. That exponent is a judgment: between
  no dependence and the inverse square of abrasion experiments (Sklar &
  Dietrich 2001).
- *How wide:* the floor is the bankfull channel
  (`alluvial_channels.bankfull_geometry`), at least a cell, cut no deeper
  than the stream itself. The walls are left to rockfall.
- *Scale gate:* a level cuts the canyons of the bed order its parent
  built (LOD2 bed sets at LOD3, LOD3 beds at LOD4, LOD4 beds at LOD5).
  `rock_scarps.restep(with_steps=True)` gives that order's height change
  at the child's grid, exactly. From the next level on a canyon is
  inherited relief, and `restep` cuts its walls into the cliffs and
  slopes of the beds they cross.
- *Conservation:* the rock is gone with the stream. The cut is not given
  back at the parent's scale (`mean_lowering_m` in the record), fades at
  the tile rim, and never goes below sea level.

**What was tried first and dropped.** Each on its first picture.

1. *Rivers cut to grade* (`bed = min(surface, bed below + k A^-0.45 x
   hop)`, walls opened to a strength angle): 78 % of a LOD3 tile cut by
   more than 2 m, 117 m on average, 1.3 km at LOD2. Everything was cut
   down to the tile's outlet. A river far below the land around it needs
   the parent's river profile, which no level has.
2. *Cutting at the level that builds the order:* 22 % of the LOD2 tile
   became canyon floor, a notch 137 m deep and 234 m wide for every
   stream of 0.5 km2.
3. *Floors as wide as the floodplain belt:* a river of 1,300 km2 planed a
   strip 760 m wide; 35 % of the LOD3 tile was lowered.
4. *Steepest-descent routing:* canyons ran in ruler-straight reaches over
   smooth benches and left straight walls two levels down.

**What the walls showed: rockfall.** `relax_to_strength` took each
cell's limit from the rock at its height before anything moved. A canyon
is cut from the rim, so every wall cell counted as cap rock all the way
down, and on the humid site walls in shale stood at 84 degrees: 81 % of
the cliff cells of the LOD3 tile were over 1.3 times what their rock
holds. `rock_scarps.rockfall` now reads the rock again every eight passes
as the ground moves (where an order shows is read once; which bed a cell
stands in follows its height). A wall cut through a cap over shale comes
to rest as a cliff in the cap and a debris slope under it. A wall many
cells high needs thousands of passes for that (the count grows with the
square of its height in cells: a child that steps a parent's canyon wall
again has a wall 25 cells high to settle), so a pass was made five times
cheaper (no allocation inside it) and rockfall is given up to 3,200. What
a canyon makes its walls shed fades at the tile rim like the cut itself.

Cell-to-cell relaxation leaves every column of a slope at its own level
(any corrugation under the limit is stable): a laid-back wall showed
streaks down the fall line, 2.1 m of cell-to-cell corrugation against
1.2 m in the ground rockfall was given. What rockfall moved is now spread
sideways over about a cell, as debris spreads when it settles, and
relaxed once more (0.8 m against 0.9 m given, on the next run); a floor a
stream keeps clear takes no part in the spread. Without the second
relaxation the spread undid the exact trimming of over-steep faces at the
fine levels (3,300 cells of the arid LOD5 tile over 77 degrees).

**Rock face on level ground.** `heightmap_scarp_fields` names the parts of
a scarp by height. Ground that rockfall had laid back, and at LOD5-6 any
ground whose ripples the undoing of the finer orders exaggerates, counted
as face wherever it lay at a face's height: 47 % of a nearly level LOD6
plot (median gradient 0.05) was bare "rock face" without soil. A part now
fills no more of a cell than the cell's own fall allows (a face is 40
degrees or steeper, so a cell of gradient 0.05 holds at most 6 % of face;
`shares_the_fall_allows`); the same plot shows 4.9 %, all of it steeper
than 0.3.

**Chain test** (figures: `.cache/screenshots/canyons/`).

| Level | Arid: ignimbrite, greywacke, chert and basalt over pumice and shale | Humid: lavas, sandstone, conglomerate and limestone over shale and mudstone |
|---|---|---|
| LOD2, 234 m | none cut (the order's own level); escarpments are closed lines | the same |
| LOD3, 42 m | 30 canyons through the bed sets, 158 km of canyon floor in a 16 x 10 km tile; the largest system 31.6 km (a river of 241 km2), the deepest 126 m; floors one cell wide (channel 12 m). Against the same tile with its scarps whole: 4.3 m lower on average, 22 % of the cells lowered by over 1 m, steepest cell 62 degrees. Dry: no river layer to compare | 24 canyons, 93 km, the largest 37 km (a river of 2,890 km2), the deepest 174 m, floors to 79 m wide. 12.6 m lower on average, 25 % of the cells; walls mostly between repose and cliff gradient. The 590 river reaches of the tile run on the floors |
| LOD4, 6 m | the same canyons, inherited: 91 m deep and about 200 m from rim to rim in section, walls cut into cliffs and ledges by `restep`, soil on the plateau and none on the walls; 128 new notches through the LOD3 beds, to 12.7 m deep and 300 m long | a V 158 m deep with a cliff at the rim, debris slopes below and the river on the floor; 183 cells over 77 degrees are the banks of the carved river channel; 9 new notches, to 1.7 m |
| LOD5, 0.8 m | one canyon wall: 84 m of banded cliffs and ledges, 71 degrees at the steepest; 19 notches through the LOD4 beds, to 1.6 m | a debris slope 69 m high above the river, a third of its cells over the cliff gradient; no new canyon |
| LOD6, 0.1 m | 37 m of wall in 22 m, 75 degrees, beds as bands of colour | 37 m of slope at about 48 degrees with an 82-degree bank at its foot; no beds resolved (the finer orders are gated out here) |

Lineage: the canyons of an order appear at one level and are never drawn
again; below it they are relief. On the arid site a canyon is one of a
network of gorges at LOD3, a canyon with stepped walls at LOD4 and a wall
of banded cliffs and ledges at LOD5 and LOD6. On the humid site it is a V
with a cliff at the rim and a river on the floor at LOD4, and from LOD5 a
plain debris slope with little on it (open item 7).

**Tests.** `tests/test_scarp_canyons.py` (retreat law and rock factor;
floor at the level of the bench below, never deeper than the scarp, never
rising downstream; valley sides and ground below the scarp untouched;
larger catchment and softer cap cut further and end in a headwall; no
stream or no steps, no canyon; rim fade; bankfull floor),
`tests/test_rock_scarps.py` (`RockfallRoundsTest`: a wall cut through a
cap lies back in the weak bed under it;
`test_a_finer_level_can_read_what_the_scarps_add_to_the_ground`;
`test_a_part_fills_no_more_of_a_cell_than_the_cells_fall_allows`),
`tests/test_regional_landforms.py` (`CanyonThroughParentScarpsTest`; no
canyon record at the order's own level, one for it a level down).

**Open items.**

1. A canyon whose scarp lies outside the tile downstream is not cut in
   that tile: canyons longer than a LOD3 tile end at its rim. Needs the
   parent to hand down where its streams run below their rims.
2. Rivers entrenched deeper than the scarps they cross, and any canyon a
   cell wide at LOD2: both need a river profile at the parent that is
   lower than the cell mean (item 1 of "tried first").
3. A river a level inherits runs on its parent's cell path, so its canyon
   is straight with 45-degree bends (humid site). The canyons of a tile's
   own streams wind.
4. No fan at a canyon's mouth and no alluvium on its floor: the rock
   removed is not routed as sediment.
5. One retreat coefficient for the world: it stands for the age of the
   scarps as well as for the climate of one plateau.
6. Walls that rockfall has laid back rest a little above the repose
   gradient, so the soil rule keeps them bare; a debris slope at rest
   would carry talus pockets. Debris that does not reach the stream stays
   where it falls (up to tens of metres at a mouth).
7. Faces are smooth walls: no joints, alcoves or sapping heads. On the
   humid site the walls at LOD5-6 are plain debris slopes: the finer bed
   orders are gated out there (their scarps would run longer than the
   parent's cells), so nothing steps them. Faint streaks down the fall
   line remain on its laid-back walls at LOD4.
8. The last bed fit at LOD1-3 grades a river over a step across six cells
   (survey above); with canyons it does so at headwalls.
9. Cost: a tile takes about as long as before at LOD3 (69 s), 6 to 13 s longer at LOD4 and 13 to 18 s longer at LOD5 (rockfall on walls many cells high; twice where a canyon was cut) and about as long as before at LOD6.

### Rock-strength pass - every rock its own strength (2026-10-05)

Owner's decision after the rock-cliff pass: give rocks their own hardness
"first, we want to arrive at a variety of erosion based formations", then
canyons. Follows open item 1 of the pass below.

**Finding.** The ontology gave every rock the profile of one of nine
mechanical classes, so pumice stood like welded ignimbrite and sandstone
lay like shale: 14 volcanic rocks at one strength, 18 "weak sedimentary"
rocks at another. Whole macroregions of layered rock had no strong bed
over a weak one.

**What a rock now carries** (`tools/author_mechanical_lithology.py`,
`ROCK_PROPERTIES`, 79 rocks). Three figures of its own: uniaxial
compressive strength of the intact rock (3 MPa pumice .. 250 MPa quartzite
and chert), typical spacing of bedding planes or joints (0.02 m shale ..
2 m granite and conglomerate) and durability (0 rock salt .. 1), plus bulk
density and a permeability index. Typical values inside the ranges of
Hoek & Brown (1997), Goodman (1989) and Bell (2007); entered from memory,
unverified against the primary tables, and not the measurement of any one
formation. The indices world generation reads are derived
(`rock_profile`):

- `slope_resistance_index` = Selby's (1980) rock-mass strength rating over
  100: intact strength 5..20 and joint spacing 8..30 read between his
  class middles on a log scale, the remaining terms 38 for flat beds of a
  rock that lasts, down to 14 for one that slakes or dissolves. Granite
  85, basalt 78, welded ignimbrite 76, sandstone 72, limestone 71,
  ignimbrite 66, red-bed sandstone 62, tuff 57, siltstone 56, chalk 54;
  below the 54 that holds a face: mudstone 42, pumice 40, shale 35,
  claystone 33. The typical rock of each class keeps its class value
  within 0.03.
- `erodibility_index` from tensile strength (a tenth of compressive),
  lowered for close joints and for rock that slakes: wear falls with the
  square of tensile strength (Sklar & Dietrich 2001); 0.455 index units
  per decade of strength, granite at its old 0.23.
- tensile strength, Mohr-Coulomb cohesion, fracture density and elastic
  strength follow from the same three figures; friction angle and fabric
  stay the class's. Minerals, sediments, regolith and ice keep their class
  profile.

**What the stronger contrasts showed, and three changes to
`rock_scarps`.** With 76 % of the beds cliff formers the first preview
drew walls 250 m high in rock that cannot hold them.

1. *One cliff per strong rock.* Strong beds merged into one unit whatever
   the rock (650 m "faces"). They now merge only while the rock stays the
   same: where sandstone lies on basalt the contact is a ledge
   (`scarp_units`). Weak beds on weak beds still make one slope.
2. *Only a face is sharpened.* Between two parent cells the remap has the
   gains of the slope its order was laid out for (a rampart laid out at 24
   degrees on a 1 % slope has a gain of 36). Relief the parent added since,
   a valley side through that rampart, was multiplied by it and weak rock
   stood up at 77 degrees. `restep` now applies its change only where a
   parent cell spans a face; elsewhere the child keeps the parent's slopes.
3. *Rockfall.* `relax_to_strength`: ground steeper than its rock holds
   (1.15 x the face gradient for a strong bed, the repose gradient for a
   weak one) fails cell to cell in eight directions until it stands at
   that angle; volume is kept. Run once per level after the steps
   (`rockfall_max_m` in the landform diagnostics). Open item 3 of the pass
   below is thereby bounded, not removed.

Also: the bed mix reads layers of role `bedrock` or `local_lithology` (the
older stored macroregions label their rock the second way).

**Preview** (scratch, the new profiles applied in memory; same two stored
macroregions, steepest ground each time).

| Level | Arid: ignimbrite sheets over pumice, then greywacke, chert and basalt over shale | Humid: lavas, sandstone, conglomerate and limestone over shale and mudstone |
|---|---|---|
| LOD2, 234 m | four escarpments across the tile, faces up to 116 m (56-68 degrees, 85 % bare); steepest cell 25 degrees | several scarp lines; steepest cell 30 degrees |
| LOD3, 42 m | two escarpments of about 135 m and contour-parallel ledges; 53 degrees | an escarpment 264 m high, cliff on top, debris slope below; 56 degrees |
| LOD4, 6 m | a 115 m scarp with a 73-degree cliff, ledges and benches below; 2.6 % of cells over the cliff gradient | the same escarpment: 73-degree cap, long slope; 2.1 % |
| LOD5, 0.8 m | a stepped ravine 44 m deep and a ringed butte; 80 degrees; 28 % | a 119 m slope under a 76-degree cap |
| LOD6, 0.1 m | a banded wall of steps, 52 m in 29 m; 77 degrees | 42 m of wall; 75 degrees |

With the class values the same humid site had nothing at LOD2 and 22, 44,
70 and 70 degrees at LOD3-6. Both chains pick the steepest ground of each
parent, so they show the extremes of a region, not its average.

**Tests.** `tests/test_mechanical_lithology.py` (`RockSpecificStrengthTests`:
Selby classes, welding, sandstone over shale, ranges, class-typical rocks,
other materials unchanged, and that the stored ontology equals the tool),
`tests/test_rock_scarps.py` (ledges between strong rocks, `RockfallTest`,
`test_only_a_face_is_sharpened`).

**State.** The tool and the code are in the shared tree. The ontology
write itself (`python tools/author_mechanical_lithology.py`, 79 records,
store only, no `.owl` export) waited on an open application on 2026-10-05;
until it has run, `test_the_ontology_carries_what_the_tool_authors` fails
and world generation uses the class values. The records as they were are
in `.cache/ontology_backups/`.

**Open items.**

1. New worlds will differ from old ones with the same seed: the planet's
   mechanical prior and the relief-retention raster read the same indices.
2. Durability is one number; a soluble rock is weak in the rain and a cap
   rock in the desert (gypsum mesas), which needs the climate.
3. Region-scale scarps are now common on layered ground with 2-4 % slopes.
   Their faces are steps one cell wide at LOD2 and are sharpened below.
4. Steepest-window chains end on walls; a walk-through of ordinary ground
   at each level has not been rendered.

### Rock-cliff pass - LOD2 to LOD6 (2026-10-03)

Not a round by lot. The owner asked for ground features away from rivers,
one at a time so each can be tested; rock cliffs are the first. Test site:
the humid layered macroregion `refined_lod1_d706b1dd88` of planet Test
(bedrock: basalt, rhyolite and trachyte flows among arkose, sandstone,
conglomerate and mudstone; 15.8 km cells), refined on its steepest ground
down to LOD6 in a scratch store.

**Survey: what a cliff was.** No stored map had a cell steeper than the
talus gradient (0.84) and none carried a bench record. The bench remap of
the per-LOD pass (P6) tied a bed's slope to its erodibility ratio, tempered
by climate, with an 8 % "cliff share":

- On the arid volcanic macroregions every bed has the same hardness (the
  ontology has nine mechanical classes: pumice, tuff and welded ignimbrite
  are all 0.35, sandstone and shale both 0.72), so the remap was the
  identity (`max_sharpening_m` 0.0 at LOD3-5; steepest cell 13 degrees).
- On the humid hard-and-soft site the steepest cell was 0.28 at LOD2 and
  0.42 at LOD3: a "300 m cliff" was a 24-degree ramp 3 km wide.
- The only cells over 0.84 at LOD4-5 were the banks of carved channels.

**Phenomenon card - the scarp of a layered sequence.**

- *Examples.* Colorado Plateau cliff-and-bench scarps (Tapeats and the
  Tonto Platform, Redwall, Coconino; the Book Cliffs), basalt trap steps
  (Columbia River, Deccan), dolostone over shale (Niagara Escarpment),
  sandstone ledges on Appalachian valley sides.
- *Sizes and controls.* A rock face stands at the angle its rock mass
  holds: strength-equilibrium slopes rise from about 35 degrees at a
  mass-strength rating of 50 to about 85 degrees at 90 (Selby 1980, 1982;
  Moon 1984). Talus rests at 33-37 degrees (Carson 1977; Statham 1976).
  The weak unit under a cap stands as a debris-mantled rampart of 28-38
  degrees in dry lands (Koons 1955; Schumm & Chorley 1966; Howard & Selby
  1994) and far lower where it weathers to a clayey mantle (threshold
  slopes, Carson & Kirkby 1972). Beyond the rampart the weak unit is
  stripped to a bench on the next strong bed. Strata are layered at every
  scale (bed sets of 50-300 m, beds of metres, bedding of decimetres;
  Campbell 1967).
- *Why these levels.* A scarp is seen as a shape when its run (height over
  slope) spans a few cells and it is the level's own when that run is under
  four parent cells: bed sets at LOD2, thick beds at LOD3, beds at LOD4.
  A face of a metre or two is whole cells from LOD5.
- *Where it does not form.* On a plain that cuts across the beds (they are
  bevelled); where no bed is strong enough to hold a face; under soil
  deeper than the step is high; on young lava cones.
- *Abiotic caveat.* Roots hold soil on ledges and steepen debris slopes;
  not modelled.
- *Layers.* Height, rock map, cover (bare rock, talus), soil; all from
  `rock_scarps.heightmap_scarp_fields`.

**Mechanism (`simulations/world_gen/rock_scarps.py`).** The parent's
bedrock layers (not its visible mantle) are drawn by areal share into a
stack of beds laid out in world-anchored blocks of elevation, one order per
level: 60-250 m at LOD2, 1.5-6 m at LOD3, 0.4-1.6 m at LOD4; 40 % of the
finer beds take the rock of the coarser bed they lie in; all orders share
one dip plane. Beds whose `slope_resistance_index` gives a face of at least
40 degrees are cliff formers (the catalogue's carbonates, lavas, foliated
and crystalline rocks: 56-80 degrees); the others form slopes. One scarp
runs from the middle of one bench to the middle of the next: half bench,
rampart (20-33 degrees by aridity), talus (the buried share of the strong
unit, 0.65), face (its exposed share, 35-100 % by aridity), half bench. The
gradients are limits, so the profile depends on the slope it is cut at; it
is tabulated on a ladder of slopes and applied as a remap of dip-corrected
elevation. The remap is the identity at mid-bench and the two half benches
are sized so that the ground raised above the brink equals the ground
lowered below the foot: no box-mean correction is needed. A scarp is built
where its run is at most two parent cells, fading out by four, and where
its face is higher than the parent's soil is deep (none at one soil depth,
whole from two). The record keeps the beds, the dip frame and coarse grids
of weight and slope; the two finer levels undo the orders at the parent's
cells, interpolate, and apply them again (`restep`), so a face stands at
its own angle as soon as cells resolve it and parent cells keep their
heights (tests: 5 cm). Older orders stay listed for the other layers.

Consumers: the rock map makes the mapped unit the rock of the bed at the
surface, bares the faces, banks talus on the buried foot (0.9) and a
thinner debris mantle on the rampart (0.35), and sheds rockfall from cells
that hold a tenth of face; soils have none on faces, at most 0.12 m on
talus (porosity 0.4, free-draining) and 0.4 m on ramparts. A cell wider
than a face holds the face's share of its width; flat ground at a strong
bed's level is that bed's rock but no face; any part of a scarp that finer
relief has tipped steeper than repose counts as face.

**What was tried first and dropped.** The same profile anchored at the
foot of each cycle with the old box-mean correction. It drew a striking
640 m escarpment with 60-degree faces at LOD3, but it turned a 1.3 %
regional slope into benches 57 km wide: the correction moved ground by up
to 593 m, lifted a rim and sank a moat around every scarp, and three
quarters of a Local tile lay in a "face" interval. A staircase that wide is
the parent's to draw, hence the run gate; with it the Region tile of this
site (slopes 0.8-1.9 %) cuts no bed set at all.

**Chain (same tiles with the scarp code switched off for comparison).**

| Level | Cells | Without scarps | With scarps | Parts (share of cells) |
|---|---|---|---|---|
| LOD2 | 234 m | steepest 0.15 | unchanged: a bed set's scarp (median 576 m) would run 30-70 km on these slopes, against parent cells of 15.8 km | none |
| LOD3 | 41.7 m | steepest 0.19 (11 deg) | 0.40 (22 deg); beds of 1.5-6 m, scarps of 11.7 m median (47.6 m max), ground moved by up to 11.2 m; faces up to 5.4 m, narrower than a cell: winding scarp lines along the valley sides | under 1 % each |
| LOD4 | 6.25 m | steepest 0.45 (24 deg) | 0.96 (44 deg); the LOD3 scarps stepped again, beds of 0.4-1.6 m added (scarps of 3.8 m median, ground moved by up to 4.7 m) | face 0.07 %, talus 0.6 %, rampart 1.4 % |
| LOD5 | 0.78 m | steepest 0.33 (18 deg), relief 27 m | 2.73 (70 deg), 2.9 % of cells over the cliff gradient, relief 37 m: two cliff lines with their debris slopes and benches; soil mean 1.39 m against 1.71 m | face 3.4 %, talus 7.3 %, rampart 6.8 % |
| LOD6 | 0.10 m | steepest 0.23 (13 deg), relief 4 m | 2.80 (70 deg), 11.9 % of cells over the cliff gradient, relief 22 m: one scarp fills the plot; soil mean 0.62 m against 1.70 m | face 13.4 %, talus 26.9 %, rampart 23.5 % |

The Region tile is unchanged and the first cliffs appear at Local scale as
low ledges. They are whole forms from Parcel scale: this is a humid site
(aridity 0.02-0.29: 37-54 % of a strong unit bare, ramparts of 20-24
degrees) with relief of a few tens of metres per kilometre.

**Track B - found on the way.**

1. *A tributary carried the discharge of the river it joins.* A reach was
   gauged at its last cell, which is the junction cell on the trunk: seven
   hillside rills at LOD3 were recorded as order-6 mainstems of 286 m3/s,
   inherited by LOD4 as "parent trunks" and drawn 45 m wide across a
   hillside. `drainage.derive_drainage_network` now gauges a reach that
   joins another stream at its own last cell (discharge, order, catchment).
   Test `test_a_tributary_keeps_its_own_flow_where_it_joins_a_trunk`.
2. *River lines wrapped around a regional tile.* `_smoothed_channel_points`
   took the display x modulo the width on every map, so the sinuosity of a
   path along the west edge jumped to the east edge and back; true colour
   was 66 % river on a LOD5 tile. Only planets wrap now. Test
   `test_a_path_along_a_tile_edge_is_not_drawn_across_the_tile`.
3. *The rim drain was listed as a river.* Ground that leaves the tile where
   the parent's flow does not is drained along the closed edge by the
   solver; from LOD4 (`fine_hydrology`) a path lying on the rim is no stream.
4. *Erosion trenches on steep ground.* Surface evolution scaled its height
   change with the tile's relief alone: on a steep parcel it cut single
   flow lines 3.5 m deep on 0.78 m cells (21.8 m on 6 m cells). The cut is
   now at most 0.35 cells deep (`FLOW_LINE_CUT_DEPTH_CELLS`). Test
   `test_a_cut_along_a_flow_line_is_no_deeper_than_its_cells_allow`.
5. *The bed sequence was drawn from the mantle.* At LOD2+ the parent's
   layer list is the visible surface: 85 % saprolite and laterite here, so
   "layered rock" was 5-19 % and no order was built. The mix is now the
   layers of role `bedrock`. Test `BedrockMixTest`.
6. *Soil on walls.* Soil depth had no slope rule. It now goes to zero
   between the repose and cliff gradients (0.70-0.84), whatever made the
   ground that steep.

**Tests.** `tests/test_rock_scarps.py` (23: face strength, profile angles,
mean height, run gate, bed blocks and hierarchy, build, restep, fields,
soil), `tests/test_regional_landforms.py` (`ScarpOrdersTest`,
`BedrockMixTest`; the bench tests of P6 are replaced),
`tests/test_material_routing.py` (a face narrower than a cell sheds talus),
`tests/test_drainage_realism.py`, `tests/test_surface_evolution.py`.
105 tests pass in these modules and `tests/test_fine_scale_ground.py`; 217 with the
water-cycle, parity, channel, fan, material and terrain modules.

**Open items.**

1. No stored world has an arid site with hard and soft beds, so the bare,
   full-height form of the profile (exposure 1.0, 33-degree ramparts) has
   only been seen in tests. The ontology decides this more than the code:
   with one hardness for pumice, tuff and welded ignimbrite, and one for
   sandstone and shale, volcanic plateaus and sandstone-over-shale mesas
   cannot form. Per-material `slope_resistance_index` values would fix it
   (an authoring change, not made).
2. Bed sets at Region scale need slopes of 2-4 % over 15 km cells and found
   none here. Staircases of escarpments tens of kilometres apart (cuestas,
   the Grand Staircase) would be Macroregion's to cut; not built.
3. The profile is laid out for the slope an order was built on. Where a
   finer level adds steeper relief, every part steepens together and a
   weak-rock rampart can stand as steep as a face (counted as face by the
   other layers). A profile laid out again for the local slope at each
   level is not built.
4. A face is a smooth wall at its angle plus the level's generic detail:
   no joints, alcoves, buttresses or fallen blocks; talus is a part of the
   profile, not cones under chutes. No springs at the foot of a cap.
5. Terrain is gentle everywhere, so cliffs are few and low. Canyons (next
   in the owner's list) cut the steep walls this module steps.
6. The rim drain of point 3 still exists in the solver at LOD1-3, and the
   Biosphere's ground texture still renders without material components.
7. A tile's record holds each order's beds and grids (about 150 kB per
   order, up to three orders).

### Fine-level pass - LOD5 and LOD6 (2026-10-03)

Not a round by lot. The Biosphere is to place plants by fine terrain, and
below LOD4 there was little to place them by. Survey first, then four fixes
(track B) and one phenomenon (track A), all on the Cityworld prototype's
stored LOD4 (3071 x 1727 m, 98 % floodplain of a braided river 84 m wide,
hot steppe), refined to LOD7 on two fixed footprints: the river with an
island, and a parcel of plain 400 m from it.

**Survey: what LOD5-7 added.**

| Level | Cells | New relief | Water rasters |
|---|---|---|---|
| LOD5 | 0.78 m | 4-5 cm rms of isotropic noise; up to 0.5 m where LOD4's carved banks are sharpened | 206-369 "rivers" in 300 x 170 m, 10-21 % of cells |
| LOD6 | 0.10 m | 0.5 cm rms, under the 1 cm rounding of stored heights: contour rings | 171 "rivers" in 38 x 38 m, straight bands |
| LOD7 | 0.10 m (LOD6's spacing) | none; +-1 cm rounding flips | 98 "rivers" in 10 x 10 m, 44 % of cells |

Causes: the detail amplitude falls to 2.5 / 0.24 / 0.07 m and the noise
uses a tenth of it; `_fluvial_dissection` returns below 1 m of new relief,
so nothing organises the noise; no landform first appears below LOD4 (dunes,
karst, patterned ground, duricrust and playas are classified once at planet
scale and never built); every flow path of the solver's top 24 % by
accumulation is a river (`_classify_channel_regime` judges runoff depth, not
discharge) at least 2 m wide (`_river_widths_m`) and 4 cm deep; wetness is a
climate constant plus those lines and a three-cell halo; soil depth is cut
to zero along them, and without a process grid (no surface evolution below
LOD5) falls to a constant 0.30 m; materials lose the plain's alluvium
because no channel belt of a 300 m tile reaches the area a belt needs.

**F1 - water read off the ground (`fine_hydrology.py`, LOD5+).** Finding:
the carved river (height, True Color, materials) and the water rasters were
two geometries; the rasters followed solver paths. From LOD5
`regional_refinement._regional_water_cycle` replaces the rasters: open water
is the carved section below its mean-flow stage (`channel_fields` now
returns `stage_m`), retained lakes and the sea; a path without a carved
channel is a stream only from 10 l/s mean flow; the river list keeps the
parent's trunks and streams that are not the carved channel's own bed.
Wetness keeps its coefficients and gains two terrain terms: the climate's
mobile water is redistributed by `a / tan(b)` (Beven & Kirkby 1979) of a
multiple-flow-direction routing (Quinn et al. 1991; Freeman 1991), total
unchanged; beside water the margin falls with height above the stage (HAND,
Renno et al. 2008; Nobre et al. 2011) over a capillary rise of 1 m and with
distance over three channel widths. Mobile is runoff, the recharge share
and half of the rain the coarse index counts as kept in place: plot-scale
runoff is several times a catchment's, most of it soaking in again a few
metres downslope (Yair & Kossovsky 2002; Wainwright & Parsons 2002).
Rasters are on the heightfield's own lattice; lakes a tile inherits as a
box are filled to their level. Same tiles: 369 -> 1 river on the river
parcel, wet cells follow both threads around the island; on the plain
parcel 451 -> 0 rivers, median wetness 0.045 with washes and channel floors
to 0.12 (95th percentile) and 0.19 at most, against 0.052 with lines of
0.5.

**F2 - height storage.** `exact_rounding.height_decimals`: four decimals
below 2 m spacing, at every rounding site of the regional pipeline
(refinement, landforms, surface evolution, coasts). The rings at LOD6-7 are
gone.

**F3 - soil.** From LOD5 a tile inherits its parent's soil over its
footprint (`regolith_soils._parent_soil_fields`; cells the parent holds
under water take the soil beside them) and adds what its relief decides:
depth by curvature (Heimsath et al. 1997), zero-mean at the parent's
spacing, and the fills and bars of the relic channels. Each order's fill
and thin bar cover are applied at the level that builds the order and are
zero-mean over its lanes (applied at every level that carried the order,
soil grew from 0.9 to 3.9 m down a chain). Plain, mean depth: LOD4 0.63 m
over the parcel, LOD5 0.70, LOD6 0.63 (was a constant 0.30), LOD7 0.67;
channel floors 0.9-1.2 m, bars 0.6 m.

**F4 - materials.** The floodplain of `floodplain_relics` is alluvial cover
at every level that carries the record; bars are bed material (coarser on
fresh ground), channel floors hold fines, on fans too; duricrust and iron
films follow surface age.

**Track A - relic channels (`floodplain_relics.py`, LOD4+).**

- *Phenomenon.* Bar-and-swale topography: the abandoned threads and chutes
  of the river that built a plain. Braidplains (Canterbury Plains rivers),
  young alluvial-fan surfaces (Death Valley; Frankel & Dolan 2007), the
  "negative relief" of large floodplains (Lewin & Ashworth 2014).
- *Sizes.* First-order threads as wide as a thread of the active belt
  (1.3 / 3 of the bankfull width, 2.2 mean depths deep; single-thread rivers:
  the channel itself, lanes four widths apart); each further order
  (Williams & Rust 1969; Bristow 1987; Kelly 2006) a fifth as wide, depth ~
  width^0.8 (Leopold & Maddock 1953). Remnant relief 25-90 % of the active
  depth (Martin & Edmonds 2022 count an abandoned channel as healed below
  a quarter); 30-45 % of thread length healed; old surfaces keep 35 % of
  the relief.
- *Why these levels.* A thread reads from four cells across: on the
  prototype river order 0 (36 m) at LOD4, order 1 (7.3 m) at LOD5, order 2
  (1.45 m) at LOD6; order 3 (0.29 m) is below the 0.1 m floor's four cells.
- *Mechanism.* Valley axis = the carved centreline smoothed over 0.75
  floodplain half-widths, stored once in global UV; cells are projected onto
  it as a smooth curve (`valley_frame`). Threads are lanes in that frame,
  wandering into each other; swale volume stands in the bars (zero-mean at
  the order's spacing, taken over a margin beyond the tile so siblings
  agree). Floodplain = within the half-width of `material_routing`'s area
  law, under its rise limit, and level (under 6-12 % over a quarter width).
  Chutes also cut the bars of the active belt above the mean-flow stage.
- *Abiotic.* No vegetation holds banks or traps silt.
- *Layers.* `heightmap_relic_fields` (floor, fill, floodplain, age) is read
  by materials and soils; water follows through the heightfield (F1).

Scale gate as section 4.3, with one deviation recorded here: an order the
parent could have resolved but does not carry is **not** made up for at the
first active level. The prototype's stored LOD4 has no relics, so its LOD5
children build order 1 and leave order 0 out
(`orders_left_to_the_parent_level`). Reason: the Biosphere refines LOD5
chunks under the eye, and a metre-deep swale 36 m wide that exists only
inside refined chunks ends at every chunk edge. Order 0 appears when the
LOD4 is regenerated.

**Chain (stored LOD4, plain parcel).**

| Level | Relic orders | Relief added (rms / max) | Visible in |
|---|---|---|---|
| LOD5 | 1 built | 9 cm / 36 cm | height, soil depth (floors 1.2 m, bars 0.6 m), materials (fines 61 % on floors, 31 % on bars), wetness (floors 0.067, bars 0.049: dry climate) |
| LOD6 | 1 sharpened, 2 built | 2.3 cm / 10 cm | height, soil depth, materials |
| LOD7 | none new (LOD6's spacing) | 0.1 cm | inherited |

On the river parcel the chutes also cut the island and the bars (LOD5
10 cm rms, LOD6 1.6 cm). A scratch regeneration of the LOD4 from the stored
LOD3 carries order 0 (threads 36 m wide, relief to 1.5 m, 30 % of the
plain) and its children all three orders; in a scratch world without the
ontology the bank silt-clay falls back to 12 %, so that river is not the
stored one's twin.

Tests: `tests/test_fine_scale_ground.py` (19). Unchanged and passing:
`test_alluvial_channels`, `test_alluvial_fans`, `test_regional_landforms`,
`test_material_routing`, `test_material_lod`, `test_surface_evolution`,
`test_drainage_realism`, `test_terrain_lod_improvements`,
`test_biosphere_terrain_site`. `test_coastal_geomorphology` fails in five
tests (deltas, a derivative version string) with and without this pass.

Open:

- **Slopes.** No stored world has a hilly LOD4 site. `_fluvial_dissection`
  still skips below 1 m of new relief, so hillslopes at LOD5-6 get noise and
  no rills or hollows. Needs a site and its own phenomenon card.
- **LOD7** resolves nothing LOD6 does not (same 0.1 m spacing below 38 m
  footprints).
- **LOD4's water rasters** (owner decision the same day): read off the
  ground like LOD5 (`FINE_HYDROLOGY_MIN_LEVEL = 4`). On the stored tile the
  comb of straight streams becomes the braided river with faint washes and
  242 rivers become 13. A LOD4 stored before keeps its old rasters until it
  is regenerated, and the Biosphere brings a chunk's wetness to the LOD4
  mean over the same ground, so an old LOD4's lines still reach it.
- **The run-on share is one figure for every cell size** (half of the rain
  kept in place); at 8 m cells most of that run-on stays inside the cell.
- **Wetness contrast in dry climates** is small in the index (floors 0.067,
  bars 0.049 on the prototype's plain) though it decides where dryland
  plants grow; whether the Biosphere reads it relatively is its question.
- **Order 0 on old regions**, see above; and sibling LOD4 tiles each take
  the axis from their own reach, so first-order threads do not line up
  across a LOD4 edge.
- **Scroll bars** of meandering rivers (spacing about half the channel
  width, Strick et al. 2018) are not built; single-thread plains get relic
  channels only.
- **Capillary rise** is 1 m for every soil; texture should set it.
- **Never built at any level:** dunes, patterned ground, karst, duricrust
  benches, playa polygons (planet-scale classes only).

**Owner decisions, same day.** (1) Rebuild the prototype's LOD4 so it
carries order 0: `tools/rebuild_refined_regions.py refined_lod4_e7fa59b8b3
refined_lod5_0df56ec100` runs the application's own rebuild on each stored
region (parent first; the application must be closed, the tool refuses
otherwise). Not run yet: the application was open. A scratch rebuild with
the conservation pass in place gives the LOD4 its LOD3's air over the same
ground (310.3 K, 758 mm, hot steppe throughout, against the stored 310.8 K
and 574 mm), 1 river for 242 and 2.0 % wet cells for 5.4 %. (2) Water read
off the ground from LOD4 (above). (3) The parent conservation pass below is
applied to the shared tree; `derive_surface_hydrology_grids` as it rewrites
it now serves LOD0-3.

### Parent conservation pass - climate, wetness, soil (2026-10-02)

Not a round: an audit of contract 4 for the fields that are not elevation.
Found from the Biosphere, where a 128 m / 1 m chunk under a Site region read
1.8 K warmer, 10 % drier and three times wetter in the soil than the ground
it lies on. Probed on the city prototype's chain (planet -> LOD1 -> ... ->
LOD4 -> chunk), each level compared with its parent over the same ground.

**Finding 1 - climate drifted at every level.** `derive_water_cycle_model`
mixed the child's own climate model with the parent's at a fixed weight
(0.80 at LOD1 down to 0.44 at LOD5). The child's model is the planet's
zonal formula evaluated again on the tile (4 K off the parent at the
chunk), followed by a moisture solve on the tile's own cells (terrain terms
relative to the tile's relief, so a 2 m bump on a 128 m tile rained 838 mm
against 345 mm beside it; rain balanced against evaporation inside the
tile) that re-applies dry-surface warming to a temperature that already
carries the parent's. At the chunk's centre the chain read:

| Level | Before: T / rain / Koppen | After |
|---|---|---|
| Planet | 307.8 K / 1554 mm / Aw | (unchanged) |
| LOD1 | 307.9 K / 1310 mm / Aw | 307.5 K / 1621 mm / Am |
| LOD2 | 308.6 K / 1012 mm / Aw | 307.4 K / 1637 mm / Am |
| LOD3 | 310.3 K / 716 mm / BSh | 307.4 K / 1637 mm / Am |
| LOD4 | 311.0 K / 483 mm / BWh | 307.4 K / 1637 mm / Am |
| chunk (1 m) | 313.1 K / 362 mm / BWh | 307.4 K / 1637 mm / Am |

Fix: `water_cycle._ParentClimate`. A child field is the parent's field at
the child's cells plus the child's own detail between two scales: smoothed
over the air's response length (`ATMOSPHERIC_RESPONSE_LENGTH_M` = 5 km:
cloud water takes ~1000 s to form and fall, Smith & Barstad 2004; ridge and
valley rainfall contrasts are observed down to about that scale, Anders et
al. 2007), minus its least-squares fit on the parent's lattice. The detail
is zero-mean around every parent sample and fades at the tile edge.
Temperature also follows the child's own height by the lapse rate. From
the level whose parent samples the ground finer than 5 km the child has no
detail of its own and skips its moisture solve. Also inherited: distance
to the sea (it was a fraction of the tile, so every inland child read as
mid-continent), the planet's circulation seed (each tile drew its own wind
meanders and seasonal phase), and the split of leftover water into runoff
and recharge (its slope term is relative to the tile's relief). Child
against parent after the fix: temperature within 0.03 K and rain within
0.2 % at LOD1 (rain still ranges 830-2940 mm inside the tile against
1040-2350 mm in the planet's samples), exact from LOD3 down. This repairs
the pre-existing failure of
`test_regional_climate_matches_parent_at_patch_edges`, whose expectation is
now the class of the interpolated normals. Tests
`ParentClimateConservationTests`.

**Finding 2 - wetness and open water depended on the sample spacing.** A
tile's stream cells are the top quarter of its flow accumulation, at any
level, and every routed path was drawn 2 m wide with at least 4.4 cm of
standing water, a +0.12 channel bonus and a +0.32 near-water halo of three
cells: 7 m at 1 m samples, 56 m at 8 m samples. The chunk's 238 "rivers"
carried 0.00008 m3/s at most. Its wetness index was 0.183 at 1 m samples and
0.305 at 8 m samples, against 0.052 in its parent. Fix
(`drainage.derive_surface_hydrology_grids`): depth and width follow the mean
discharge by hydraulic geometry with no floor; open water needs 2 cm of
characteristic depth; the wet margin is three channel widths wide (30 m at
a lake or sea shore), scaled by depth (saturated from 0.25 m), drawn as
cones in metres from the centreline, and a margin narrower than a cell wets
only its share of the cell. Discharges below 1 m3/s keep three significant
digits (they were rounded to 0.0). After: chunk 0.165 at 1 m, 0.165 at 8 m,
parent 0.165; on a chunk crossed by streams 0.179 at 1 m and 0.177 at 8 m
(before 0.237 and 0.353). A straight 20 m3/s river on level ground adds the
same mean wetness within 6 % at 0.5 to 32 m samples. Tests
`WettingBesideWaterTests`.

**Finding 3 - soil depth.** Three causes: the soil model gave no soil to
any cell flagged as water, including the 18 % of chunk cells with a rill;
chemical weathering followed the drifted climate; and a stream narrower
than a cell took the whole cell's soil. `water_fraction_rows` now gives the
share of each cell under water and `regolith_soils` scales depth by it.
Chunk against parent: 0.455 m against 0.626 m before, 1.422 m against
1.414 m after (the rebuilt chain is wetter, hence deeper soil); on the
stream chunk 1.399 m at 1 m, 1.368 m at 8 m, parent 1.374 m.

**Open items.**

- `surface_evolution` still normalises flow accumulation by the tile's own
  range, so the erosion and weathering indices behind soil depth differ by
  a few percent between a child and its parent (soil depth +6 % at LOD2,
  -3.6 % on the 8 m version of the chunk).
- Stream cells are still a quantile of each tile's accumulation: the share
  of cells flagged as channels depends on the sample spacing (5 % of the
  chunk at 1 m, 20 % at 8 m). They carry no water or wetness of their own
  now, but `channel_presence_rows` is not a physical quantity yet. A
  channel-head threshold in square metres (Montgomery & Dietrich 1992)
  would be.
- Channels wider than 17 samples are drawn 17 samples wide (`radius` cap in
  the raster painter); the wet margin is not affected.
- The child's own climate model keeps tile-relative terrain terms
  (`_terrain_metrics_arrays`, elevation normalised by the tile's span);
  they now only shape the zero-mean detail at LOD1-2.
- Regions generated before this pass keep their drifted climate and their
  old hydrology rasters until they are regenerated. A new child of such a
  region conserves that region's climate, not the planet's, and reads drier
  than the region's raster wherever that raster has rills with three-cell
  halos (the city prototype's patch: 0.055 against 0.152).
- `LayeredSubstrate(climate_from_base=True, conserved_fields=...)` in the
  Biosphere was the consumer-side guard for this drift; it is redundant for
  regions built after this pass and still protects older ones.

### Per-LOD improvement pass (2026-10-01)

Follow-up to the showcase: one improvement per LOD read off its pictures,
plus the showcase's open items. Each item names the picture finding, the
cause as found (most were not what the picture suggested), the fix and its
regression test.

| # | LOD | Item |
|---|---|---|
| P1 | 4 (all) | Rivers leave a tile only where the parent's flow leaves it |
| P2 | 1-3 | Through-rivers exist in the regional water cycle |
| P3 | 3-6 | Straight rays across floodplain floors |
| P4 | 1-3 | Rectangular coasts |
| P5 | 1-3 | Straight ice margins |
| P6 | 2-5 | Caprock cliffs stay sharp below LOD2 |
| P7 | 3-7 | Straight streaks in the material maps |
| P8 | 0 | A planet with closed basins and no lake |
| P9 | 1, 4 | Bevelled tile rim; frame around LOD4 material maps |

**P1 - parent exits.** Finding: a 93,600 km2 river clipped the corner of a
LOD4 tile centred on its parent's trunk. Cause: a child knew where parent
rivers enter, not where they leave; every other edge cell was an outlet.
First attempt (close the edges the parent flows in through) failed its own
test: flow parallel to an edge is neither in nor out, and the spurious exit
was there. Rule now: an edge cell is an outlet only where the parent's flow
leaves the footprint. `material_routing.boundary_inflow` records
`open_edges` (index runs per side, half a parent cell around every
outward crossing); `inflow_grid` gives every other edge cell a vanishing
inflow; `inlet_mask` closes any edge cell with inflow. A tile the parent
drains into (no exit) floods from its lowest cell: a closed basin. Tests
`ParentExitTests` (a dammed river spills through the parent's exit; without
the record it leaves through its entry side).

**P2 - through-rivers in regional hydrology.** Finding: no river drawn at
LOD3; the largest "river" of the LOD2 river tile carried 13 m3/s while a
440,000 km2 trunk crossed it. Cause: the regional drainage solve routes
only its own footprint. `water_cycle._solver_boundary_inflow` maps the
heightmap's `boundary_inflow` onto the 257-cell solver lattice (entry
cells with their upstream catchment as solver cells, closed edges as
inlets, the parent tile's mean land climate as the catchment's);
`drainage.derive_drainage_network(inflow=...)` accumulates it. Test
`test_a_river_entering_a_regional_tile_is_in_its_river_list`. Open: the
catchment's runoff is the parent tile's mean, not the true upstream mean.

**P3 - floodplain rays.** Finding: long straight light/dark wedges across
flat floors at LOD3-6. Not the distance-based rise (a synthetic bend
showed none): the bed level each floodplain cell takes from its nearest
channel cell is a field of flat wedges, one per kink of the routed channel,
and the fitted bed was a staircase (pool-adjacent-violators pools flats
and drops). Fixes: the fitted profile is graded along the river
(`BED_GRADE_CELLS`: a moving average of a non-increasing profile stays
non-increasing); the floor is built from the fitted bed; beside the
channel the floor follows it, farther out it is one surface smoothed at
floodplain scale (`_floodplain_scale`, 15 % of the widest half-width). A
second ray pattern, stars around meander bends at LOD4, was the final bed
fit filling the carved channel's scour pools: `_fit_final_channel_beds`
now stops where `alluvial_channels` carve (LOD4+).

**P4 - coasts.** Finding: rectangular bays and dead-straight shores from
LOD1 to LOD3. Not the interpolation: the sea-level contour of the
interpolated parent is a smooth bay. The relief synthesis adds a mean of
+650 m of detail (the regional tectonic re-sampling's offset against its
parent); `_center_detail_at_parent_scale` removed that only on land above
250 m, so the shallow bay stood 570 m above sea level until the final
parent-height contract pushed the parent's certain-ocean cells back under:
LOD0's rectangles. Fixes: (1) the offset is removed everywhere; where the
parent is certain (all four parent corners on one side) a cell stays on
that side, with detail towards sea level compressed exponentially instead
of clamped; in mixed parent cells detail may cross sea level (drowned
valleys), minus one-cell islands and ponds. (2) `_refine_coastline`: in
mixed parent cells the shore is shifted by a world-coherent fractal
displacement of up to 0.4 parent cells (octave gain 0.62, wavelengths from
the parent's spacing to two cells; Richardson 1961, Mandelbrot 1967),
applied as displacement times the relief across the parent cell, so gentle
coasts gain bays and headlands and steep ones stay straight. The shift is
part of the parent-height contract's reference. (3) The caprock remap
fades out over the last 60 m above sea level (it is anchored below the
lowest land and moved ground at sea level by tens of metres: a wall or a
pit on every shore cell). Tests `ShorelineTests`.

**P5 - ice margins.** Finding: a 15 km straight edge and 45-degree steps at
LOD3, already present in the LOD2 mask. Cause: the terrain term moves a
margin by at most half a parent cell and is zero on smooth ground, and the
noise term had three octaves at tile scale only. `_regional_ice_mask` v2:
the transition is widened by half a parent cell, the terrain mean spans
two parent cells, and a world-coherent fractal term covers every
wavelength from the parent's spacing down to two cells. Test
`test_a_straight_parent_margin_is_irregular_on_smooth_ground_at_every_scale`.
Open: the margin does not yet follow an equilibrium-line altitude.

**P6 - caprock below LOD2** (superseded by the rock-cliff pass, 2026-10-03: `rock_scarps.py`). Finding: no cliff steeper than the talus
gradient anywhere below LOD2, hence no talus. Cause: the benches are an
elevation remap made once at LOD2; children interpolate the remapped
surface and smear each cliff over a parent cell. Now the LOD2 record keeps
`strata` (bed table, contrast, dip frame, 64-cell grids of where the remap
applied and of the height its conservation gave back). A finer level
(to LOD5) recovers the smooth surface behind the parent's steps at the
parent's cells (`_strata_smooth`, bisection), interpolates that and steps
it again (`_caprock_sharpening`): cliffs as steep as its cells allow,
parent cells unchanged, record carried down. Tests `CaprockSharpeningTest`
(steepest slope 1.8x the interpolated one and above the cliff gradient;
parent samples within 5 m). On the real tile that alone changed little
(steepest bench 0.21 -> 0.24): the remap ties slope to the erodibility
ratio, and real bed sequences (erodibility 0.23-0.38 against 0.72) give
13-degree "cliffs" at any resolution. A rock face stands at an angle set
by rock-mass strength (Selby 1980), so beds at most
`CLIFF_FORMING_ERODIBILITY` now get `CLIFF_HORIZONTAL_SHARE` (8 %,
tempered by the climate contrast) of the horizontal distance the ratio
gives them: same bed sequence, 24 degrees at LOD2, 45 at LOD3 and LOD4,
cells above the talus gradient. Test
`test_strong_beds_hold_cliffs_whatever_the_erodibility_ratio`. The cliff
gain then exposed what the remap does to flat ground: applied to the
surface itself it multiplies all relief inside a strong bed's elevation
range, so a lowland plain resting on such a bed became a maze of worm-like
scarps with concentric outcrop rings (E_lowland LOD3). The remap now steps
the surface smoothed over two cells and is added to the ground as it is,
and it fades in with the regional slope (0.5-2 % of the surface smoothed
over six cells): streams cut benches where the land traverses the beds; a
plain on one bed stays a plain (bench cells: 22 % of the arc tile, 0 % of
the lowland tile).

**P7 - material streaks.** Finding: hatching inside the channel at LOD5-7,
straight belts on smooth slopes at LOD3-4. Causes: bed sorting multiplied
the channel's depth pattern by D8 stream power (single flow lines over the
bed), and the belt of a carved river's floodplain kept a routed-thalweg
gravel line; material routing used deterministic D8. Fixes: in a carved
channel the bed's power is its depth; the floodplain of a carved channel
holds overbank fines; `routing_jitter` (correlated sub-cell micro-relief,
half a cell's drop along the local slope) is the default of
`channel_belts` (terrain fits, floodplains, materials share one route) and
feeds provenance and the talus/catena receivers. Tests
`RoutingJitterTests`.

**P8 - lakes (LOD0).** Finding: no lake and no playa on a planet with 15
closed basins up to 367 m deep. Cause: `drainage._lake_components` grows a
lake from the deepest cell while runoff covers evaporation, then discarded
it when fewer than 3 cells remained; in a hyper-arid basin (192 mm rain,
2,340 mm potential evaporation) that is always. The minimum size now
filters depressions, not terminal lakes: a water-limited lake is kept,
with `terminal_fill_fraction` (budget over loss) scaling its depth. Same
planet: 10 terminal lakes, 9 gypsum playas and a salt pan. Test
`test_a_dry_planet_scale_basin_keeps_its_terminal_lake`.

**P9 - rim and frame.** Finding: a bevelled frame along LOD1 tile edges; a
frame of other material around LOD4 material maps. Cause of the rim: the
detail arrives faded to zero at the edge, and its plain box mean is too
small inside the fade band, so centring left a ridge there (up to 450 m
on a synthetic tile with the 650 m offset). The mean is now weighted by
the fade. Test `TileRimTests`. The frame was coarse bed material chosen in
that slightly steeper band; P7's floodplain rule removes it.

**State when the pass was paused (2026-10-01).** Code and tests for P1-P9
are in (158 targeted tests pass; nothing committed). Verified on rebuilt
tiles: P1/P2/P3 on the river chains (trunks cross LOD1-4), P4 on the
lowland LOD1 coast, P5 on the ice chain (before the last caprock changes),
P8 on the regenerated LOD0 (10 lakes, 10 playas), the bench gating on the
lowland plain. Not yet done: the final rebuild of every chain with the
last caprock version (only A_arc 1-4, H_cliff 3-4 and E_lowland 1-4 are
current; C_dry, D_ice, F_humid, G_coast and B_river are missing or stale),
the review of those pictures, and new sheets. Still open in the model:
cliffs at the H_cliff tiles reach 0.56-0.70, under the 0.84 talus
gradient, so caprock talus is not shown yet (the remap weight below 1
dilutes the step); the square shoreline corner and lagoon chain at the
G_coast river mouth were seen before the base-level and island fixes and
need a look after the rebuild. To resume: `run_final2.sh` in the session
scratchpad (waves of three chains; about 45 minutes, up to 10 GB of RAM).

### Showcase pass - every LOD on a fresh world (2026-10-01)

Not a round: a new world (`showcase-001`, water 0.71) with LOD0 annotated
and six LOD1+ chains placed on sites chosen from LOD0 data (arc volcanoes,
largest river, dry fold-thrust front, ice margin, a gentle lower course near
a mouth, the wettest warm land), each tile annotated with markers found from
the data, not placed by hand. Coverage per LOD: see the end of this entry.
The pass found three routing bugs that broke a big river crossing LOD2-4.

**Coverage (final images, marker found from the data):**

| LOD | Mechanisms with an example | Where |
|---|---|---|
| 0 | plate boundary classes (subduction, ridge/rift, transform, collision); 7 orogen system types; hotspot chain; craton, aulacogen, intracratonic basin; largest river; 4 coastal systems; mountain ice field; 5 Koppen climates; desert, karst, periglacial and duricrust provinces; 14 lithotectonic settings (second panel) | LOD0 #1-30 |
| 1 | arc stratovolcano; river inflow from the parent; stream-power trunk valleys; terrain-following ice margin; deltaic, marine-terrace and rocky-cliff coasts; clay, lateritic, aeolian-sand and till covers; mapped lithologic units (~60 km) | A_arc, B_river, D_ice, E_lowland, F_humid |
| 2 | caprock cliffs and benches; alluvial fans built (incl. volcanic ring plains); fan/channel gravel; provenance alluvium; ice margin; glacial till; deltaic coast | all chains |
| 3 | floodplains (flattened channel belts, monotone beds); faults offsetting units; bedrock scarp, ridge crest, incised valley; catena wet hollows (F_humid only: the world is dry); talus below a rock step (G_coast); inherited fan surfaces | all chains |
| 4 | resolved channels: braided and meandering (Leopold-Wolman, Schumm); bed sorting; inherited fan apex with radial fining; duricrust | B_river, E_lowland, C_dry, A_arc, F_humid |
| 5-7 | the LOD4 meander bend persists (42-87 m channel); recognizable as a channel to LOD6 (59 m tile), only bank, bar and water at LOD7 (18 m); object-detail contract from LOD6 | B_river |

Not shown, and why: lakes and craters (none on this planet); evaporite
pans, loess and ferric coatings (below the 20-30 % marker threshold in
every tile); delta planforms (classified, not built below LOD1); hotspot
edifices (no chain under a showcase site).

**Fix 1 - inlet stretch wider than the tile.** `inlet_mask` made the whole
entry side an inlet when the river's floodplain half-width exceeded the
tile (5.3 km against 2.8 km at LOD4); with no outlet near the entry the
flood seeded from an interior pit and the river ended in a round cap
mid-tile. The stretch is now capped at 1/8 of the side either way, but
never shorter than the edge band (`INLET_EDGE_BAND_FRACTION` = 4 % of the
side: the fade zone where a child keeps its parent's surface plus about a
parent cell); with only the floodplain half-width, a LOD2 river entering
through an interpolation pit left again 7 cells along the same edge.
Regression test `test_a_river_wider_than_the_tile_still_leaves_through_the_boundary`.

**Fix 2 - routed-channel trenches hundreds of metres deep (LOD1-3; see Fix 8).**
`surface_evolution._apply_channel_incision` forced every routed bed
`min(bed, previous_bed - drop)` with no bound, so a path the flood routing
carried over a rise or along a tile edge was cut through the whole rise:
598 m at LOD2 (nominal depth there ~2 m), the "left-edge dashes", and a
500 m notch exactly where the showcase river entered (tile edge 518 m below
its parent, against the zero-residual edge contract). Now the enforced bed
stops at twice the valley depth or a 3 % grade across one cell
(`CHANNEL_BREACH_DEPTH_FACTOR`, `CHANNEL_BREACH_SADDLE_GRADE`), whichever is
deeper, which keeps the existing 25 m saddle breach of
`test_routed_river_incises_ravine_and_enforces_downstream_gradient`.
Result: LOD2 max incision 598 -> 19 m, worst LOD2 edge residual
-518 -> -42 m. Regression test
`test_routed_path_over_a_high_sill_is_not_trenched`.

**Fix 3 - river beds that rise downstream (LOD1+).** Along the trunk
river (439,000 km2) 42-44 % of LOD2/LOD3 bed steps went uphill, with
closed pits of 17-24 m: inherited parent-scale relief survives because
every level's change is made zero-mean at the parent's spacing (and the
conservation adds bumps of its own where it lifts a channel whose
surroundings were lowered). A LOD4 child then found a lower exit just past
its inlet stretch than the parent's route over a sill: the river entered
and left the same edge 360 m later. A stage probe (`stage_probe.py`)
showed where each fix attempt failed: fitting only at LOD3 left the
inherited LOD2 pit at the inlet (the edge fade pins the child to its
parent there); fitting before the conservation was undone by it; and
regional surface evolution (erosion/deposition) moved the river off the
bed the dissection had fitted. Final design:
`material_routing.monotone_channel_beds` fits each channel path (trunk
first: largest head area, then longest) with the least-squares
non-increasing profile (pool adjacent violators: sills cut by as much as
pits are filled, each path keeps its bed volume; a tributary never joins
below the trunk; a path entering through the grid edge keeps its entry
level and only cuts below it, one leaving through the edge keeps its exit
level, because the edge fade pins both to the parent and a raised entry
comes back as a sill). `regional_refinement._fit_channel_beds` applies it
to rivers whose floodplain (twice its half-width) spans at least a cell: exact on the channel
cells, and the same correction smoothed along the river across the belt (a
cell-by-cell one printed the bed noise as floodplain stripes). It runs
after the conservation in `_fluvial_dissection` (LOD1+) and
`_floodplain_flattening` (LOD3+), and once more on the evolved surface
before the last water-cycle solve (`_fit_final_channel_beds`, routed on the
pre-evolution surface so the river keeps its course), all faded at tile
edges. Regression tests
`test_a_river_bed_never_rises_downstream_across_an_inherited_sill` (4.4 m
reverse rise before, < 0.5 m after), `MonotoneBedTests` and
`test_a_river_entering_in_a_pit_cuts_down_instead_of_raising_its_entry`.

**Fix 6 - surface evolution changed tile edges (LOD1-3).** Regional surface
evolution was the one child step without the edge fade: its drainage does
not see the catchment a river brings in, so it deposited 17 m on the
inflow edge cell and 32 m on the outflow edge of the LOD1 river tile,
breaking the child-edge = parent contract and turning the 231,000 km2
river back out of the tile after 4 cells. `_edge_faded_evolution` fades the
change like every other detail. Regression test
`test_surface_evolution_change_vanishes_at_the_tile_edge`.

**Fix 4 - talus on alluvial banks (LOD4+).** Once channels are carved
(`alluvial_channels`), their 4-5 m cut banks on 10 m cells exceed the
40-degree cliff gradient, and `talus_fields` shed "rockfall" from them
(16 % talus on the E_lowland meander bend). Cut banks in alluvium fail in
slump blocks of their own sediment. `talus_fields(rock=...)` takes the
cells that can shed rock; `material_lod` computes talus after the channel
belts and excludes every cell under half alluvial cover (a 47 % "talus"
apron on the walls of a gully cut into the B_river LOD4 floodplain) and the
resolved channels' banks. Rock steps keep their talus (G_coast LOD3,
below a caprock bench). Regression test `test_only_rock_faces_shed_talus`.

**Fix 5 - dotted pits along sparse river polylines (LOD1-3; see Fix 8).**
`surface_evolution._river_grid_path` kept only the polyline vertices, so a
river brought in as a sparse polyline was incised at isolated cells: a
chain of dark dots across E_lowland LOD1. It now rasterises every cell
between vertices. Regression test
`test_a_sparse_river_polyline_is_carved_between_its_vertices`.

**Fix 7 - 20-degree "fans" on river banks (LOD4+).** `alluvial_fans`
had a maximum catchment but no minimum: at Parcel scale every bank gully
mouth (catchment < 0.005 km2) passed the apex test, and the fan gradient
law (0.06 A^-0.25, calibrated on 0.1-1000 km2 basins) gave 0.38-0.42
(21 degrees): 8 built and 7 inherited cones along one meander's cut bank at
B_river LOD5, with dendritic catchment-erosion scars on the bank.
`MIN_FAN_CATCHMENT_KM2 = 0.1` (below it a gully mouth builds a colluvial or
debris cone, not an alluvial fan). Regression test
`test_gully_mouths_on_a_bank_build_no_fans` (fails without the floor).

**Fix 8 - routed-polyline incision off on regional tiles (LOD1-3).** With
Fix 5 the water cycle's long straight river polylines were carved along
their whole length: regular straight trenches across the LOD1 river tile
(row-direction curvature 2.3 -> 12.4 m after surface evolution, against
2.1-2.9 m along columns; stripes inherited at LOD2). Before Fix 5 the same
polylines were carved at their vertices only (the dotted pits). Both come
from carving terrain-independent polylines; on regional tiles the
stream-power dissection already organises valleys and `_fit_channel_beds`
makes rivers descend, so `_apply_channel_incision` now acts on planet maps
only (where it carves only bodies whose cells are under 12 km). Fixes 2 and
5 keep that planet-scale pass bounded and continuous. Row and column
curvature on the LOD1 tile: 2.81 / 2.67 m; the 231,000 km2 river still
crosses it.

**Result for fixes 1-8 (river routing)** (final river chain, same LOD1
footprint; trunk = the largest entering river followed over the filled
surface; at LOD4 the D8 path crosses the carved channel's pools, so its
pits are pool depths):

| Level | Before: trunk path | After: trunk path | Reverse rise / deepest pit, before -> after |
|---|---|---|---|
| LOD1 | 4 cells, leaves through its entry edge | 1,342 km edge to edge (1.3 M km2 at the exit) | 0 m / 0 m |
| LOD2 | crosses | 278 km edge to edge | 881 -> 40 m / 24 -> 7.4 m |
| LOD3 | crosses | 31 km edge to edge | 80 -> 1.7 m / 17 -> 0.8 m |
| LOD4 | 360 m, leaves through its entry edge | 3.1 km edge to edge (440,000 km2 trunk: 260 m braided and 90 m single-thread reaches) | - |

The lowland chain (E_lowland, 153,000 km2) is monotone at LOD2-3 (reverse
rise 2.4 / 0.15 m) and its LOD4 meander (52 m wide, 5.2 m bankfull, a
near-cutoff loop) crosses the tile over 7.2 km. Talus is also kept off
any ground with more than half alluvial cover (gullies cut into a
floodplain), not only off carved channel banks.

**Open items found by the showcase** (most important first; status after
the per-LOD improvement pass above: 1 -> P1, 2 -> P4, 3 -> P6, 4 -> P5,
5 -> P7, 6 -> P2 for the river list (surface evolution's own erosion still
ignores the inflow), 7 -> P3/P9 for the rim, creases and frame; the
speckled contacts, volcano outcrop rings and honeycomb texture remain):

1. A child knows where a parent river enters but not where it leaves: its
   own flood routing may send an entering river out through any lower edge
   cell beyond the inlet band (final E_lowland LOD4: a 93,600 km2 river
   clips the tile corner although the tile is centred on the parent's
   trunk; the floodplain's 0.4 % cross-valley rise beats the gentle
   down-valley slope). Fix idea: outlets only where the parent's flow
   leaves the footprint (exit masks from `boundary_inflow`'s parent
   routing), or carve the parent's channel centreline into the child as a
   guide.
2. Coastlines keep LOD0's 78 km cells: the "coastline is kept" contract
   carries LOD0's rectangular land/sea cells to LOD1 (E_lowland LOD1) and
   straight 200+ km shores to LOD2-3 (G_coast). Deltas are classified
   (`deltaic`) but have no planform below LOD1.
3. Caprock benches are a LOD2-only elevation remap; children interpolate
   them, so cliffs blur and talus is rare (it does appear below a bench
   step that stays sharp, G_coast LOD3); on a planar coastal ramp the
   benches run as straight steps parallel to the shore. Fix idea: store
   the bed table in the LOD2 record and re-sharpen at each finer level,
   like volcanoes, fans and channels.
4. Ice margins keep straight edges from LOD0/LOD1 cells (D_ice LOD3: a
   15 km straight edge and a 45-degree staircase already in the LOD2
   mask); the terrain term moves a margin by at most half a parent cell
   and does nothing on smooth ground. Fix idea: a contour/ELA-based margin.
5. Straight parallel D8 streaks in the material maps on planar slopes
   (G_coast LOD3, thin straight belts at E_lowland LOD3/4): material
   routing uses deterministic D8 where `fluvial_relief` uses stochastic
   receivers.
6. Regional water cycle and surface evolution still ignore
   `boundary_inflow`: through-rivers are missing from their drainage (the
   evolution deposits in them; now faded at edges and overridden by the
   final bed fit, but the hydrology itself is wrong).
7. Smaller: bevelled rim along LOD1 tile edges (E_lowland LOD1), dotted
   or speckled unit contacts (B_river LOD2 materials), outcrop rings on
   volcano cones in the materials, faint honeycomb texture in LOD3 True
   Color, rivers barely visible in LOD3 True Color (F_humid).
8. Not on this planet: lakes (none generated), craters (Earth-like
   atmosphere and erosion) - not missing, absent.
9. Pre-existing, unrelated: 5 failures in `tests/test_coastal_geomorphology.py`
   (delta assessments; a stale `heightmap-derivatives-v1` expectation);
   the module and test are committed and unchanged here.

Diagnostics used (scratchpad): `trunk_profile.py` (bed along the largest
routed river: drop, summed reverse rise, uphill share, deepest pit) and
`residual_check.py` (child minus bilinear parent, edge vs interior).

### Round 2 - LOD2 Region (2026-10-01)

**Track A - alluvial fans and bajadas at mountain fronts.**

- Phenomenon card. Real examples: Death Valley and Owens Valley fans and
  bajadas, the Tian Shan and Kunlun piedmonts, volcanic ring plains of
  Andean volcanoes in the Atacama; on Mars the Gale (Peace Vallis) and
  Saheki crater fans. Scaling from catchment area `A_d` (km2): fan area
  `A_f = c A_d^0.9` (Bull 1964; Hooke 1968: exponent 0.8-1.0, c 0.1-2),
  larger in drylands where flashy runoff delivers more sediment than the
  basin removes (Blair & McPherson 1994); fan gradient `S_f = a A_d^-b`
  with b 0.15-0.35 (Bull 1964; Harvey). Mechanism: a channel leaving its
  confined valley loses confinement and slope, its transport capacity drops
  and it builds a cone by avulsion. Needs running water (or debris flows)
  and sediment supply; neighbouring fans merge into a bajada. Why LOD2:
  typical radii 1-10 km are >= 4 cells at ~310 m but mostly < 4 cells at
  LOD1's ~2 km. Abiotic: yes.
- Implementation: `simulations/world_gen/alluvial_fans.py`, called from
  `regional_landforms` (level >= 2, before channels, which then route over
  the fan surface). c = 0.12 (humid) .. 0.6 (hyper-arid) from the parent's
  P/PET; a = 0.06, b = 0.25; concavity 0.25; cone anchored at the toe (one
  radius down the channel), so the fan head stands `(S_f - S_basin) R`
  above the old floor and backfills the canyon mouth. Volume taken from the
  catchment (slope-weighted, at most 30 % of a cell's height above the
  apex). Materials: `_surface_routing` splits alluvium into `alluvial_fan`
  gravel near the apex and `floodplain` sand/silt toward the toe.
- Synthetic range front (V-canyons, 8 % axes, 0.5 % plain, 32 km2
  catchments): arid fans R 2.8 km, 1.45 deg, up to 39 m thick, 0.1 km3
  each, coalescing; humid R 1.4 km, 20 m. Net volume change zero.
- First real run built R ~48 km "megafans" on 25,000 km2 through-rivers
  (any gentle slope change qualified for their 0.5 % fan gradient). Fixed
  with two mountain-front constraints: catchments <= 1,000 km2 (Harvey
  2011) and feeder channels >= 2 % steep.
- Test site: the fixture planet's "mountain" LOD1 (a high plateau with a
  stratovolcano arc, P/PET 0.24), LOD2 on a 2.2 km-relief volcano, then each
  child on the largest fan.
- Persistence (chain LOD2 -> LOD7):
  - LOD2 (173 km, 337 m): 6 fans, R 1.5-1.8 km but at most 11 m thick
    (their feeders enter valleys almost as steep as the fans): not
    visible. This plateau has no range front with >= ~15 km2 steep
    catchments opening onto flat ground.
  - LOD3 (21 km, 54 m): 17 new fans, R ~1.2 km, 24-29 m thick, coalescing
    into a bajada along the foot of the volcano's apron; visible as lighter
    gravel lobes in True Color (luminance +4.5) and 5.6 % fan cover.
  - LOD4 (2.9 km, 7.6 m): inside one fan (51 % of the tile); its edge reads
    as a material boundary; no new fans or channels.
  - LOD5-7 (406 m -> 18 m): uniform fan gravel; the fan is no longer
    recognizable, only its surface material and slope remain.
  - Lineage (child box-filtered vs parent): LOD4 0.13 m, LOD5 0.04 m,
    LOD6 0.008 m, LOD7 0.001 m RMS; LOD3 -5.3 m and LOD2 -10.2 m mean bias
    from surface evolution (see open items).
  - Verdict: on this terrain fans first read at LOD3 and stay recognizable
    through LOD4; LOD2-scale fans need higher-relief fronts than this
    plateau offers.

**Open items (round 2).**

- Fan outlines at child levels are circles (fan ground = within the radius
  and below the cone plus a tolerance); real toes are lobate. Store the
  built footprint (or thickness) with each fan instead.
- Try fans on a basin-and-range style site, where LOD2 fans should form.
- `surface_evolution` erosion is not mass-conserving: children sit 8-10 m
  below LOD1 on steep tiles (-8.3 m before this round's spacing fix,
  -10.2 m after).
- A row of short dark dashes along LOD2's inflow edge persists.
- A faint ring remains at the base of volcanoes, where the plateau's
  benches meet the thin lower apron.
- The regional tectonic snapshot has no seafloor-spreading model, so
  anything that recomputes slab-dependent geometry from it disagrees with
  LOD1; children must read the parent's landform records.

**Track B - surface evolution treated regional tiles as whole planets.**

- Cause: `surface_evolution.derive_surface_evolution_model` used
  `dy = pi R / (rows - 1)` (52 km per row on Earth, whatever the tile) and
  `dx` scaled by the cosine of a fake latitude taken from the row index.
  On regional tiles y-gradients were ~100x too small at LOD2 (a y-tilted
  ramp eroded at 0.027 against 0.061 for the same ramp along x), and the
  routed incision depth came from a ~0.6-10 km "cell".
- Fix: `_regional_extent_m` - regional patches (no wrap, region size known)
  use `region_width_m / (cols - 1)` and `region_height_m / (rows - 1)`.
  The pre-existing failing test
  `test_routed_river_incises_ravine_and_enforces_downstream_gradient`
  (a 4 km regional tile) passes now; new test
  `test_regional_patches_use_their_own_spacing_in_both_directions`.

**Track B - LOD2 caprock benches cut stratovolcanoes into terraced rings.**

- Finding: LOD2 volcanoes rendered as concentric "targets" with single-cell
  drops of 120-146 m. `_caprock_residual` remaps elevation for the whole
  tile so benches follow flat-lying beds - right for Grand Canyon-style
  strata, wrong for a younger constructional cone whose flows dip with its
  flanks.
- Fix: LOD1 records the arc volcanoes it builds (`volcanoes` in its
  `volcanic_arc` landform record); LOD2 rasterizes them from the parent
  record (`_inherited_arc_edifices`) and fades the caprock residual out
  above 60 m of edifice. Parent lineage is kept: no child re-evaluates root
  tectonics.
- Found on the way: `arc_volcanoes` cached on (seed, segment count,
  circumference) only, so a regional tectonic snapshot (which has no
  seafloor-spreading model, so a default slab age, a different dip and
  volcanoes ~35 km off) shared the planet's cache entry; whichever came
  first won. The key now includes plate count and the spreading model.
- Tests: `tests/test_regional_landforms.py` (cache separation, parent record
  rasterized in place, caprock leaves a recorded cone smooth).

### Round 1 - LOD4 Site (2026-09-30)

**Track A - alluvial channel planform (meandering / braided rivers).**

- Phenomenon card. Real examples: Rio Beni and lower Mississippi bends
  (meandering), Brahmaputra and Canterbury Plains rivers (braided), most
  pre-Devonian rivers (braided, unvegetated). Sizes: bankfull width
  `W ~ 2.7 Q^0.5`; meander wavelength `~11 W` (Leopold & Wolman 1960);
  bend radius `~2-3 W`; width/depth `F = 255 M^-1.08` and sinuosity
  `P = 0.94 M^0.25` with M the bank silt-clay percent (Schumm 1960, 1963);
  braided above `S = 0.012 Q^-0.44` (Leopold & Wolman 1957). Why LOD4: a
  channel reads as a shape only when `W >= ~1.5-2 dx`; LOD3 (~50 m) shows only
  the largest rivers as a line, LOD4 (~7 m) resolves channels of a few tens
  of metres with both banks and bars. Abiotic caveat: no vegetation, so bank
  strength comes from mud only (clay-mineral share of the parent's sediments,
  a lower bound on silt-clay).
- Implementation: `simulations/world_gen/alluvial_channels.py`, called from
  `regional_landforms.apply_regional_landforms` (level >= 4, with the tile's
  `boundary_inflow`). One geometry (global-UV centrelines in
  `heightmap_model.regional_landforms`) feeds the heightfield carve, the
  material bed sorting (`material_lod._surface_routing`) and True Color water
  (`true_color.render_true_color_surface`; the water-cycle polyline overlay
  skips rivers the carve resolves).
- Scale gate: carved where `W >= 1.5 dx` and (below LOD4) `W < 1.5 dx_parent`.
  Children inherit the centrelines, never re-carve them, and add only the
  sub-parent-scale part of the section (`S - G_{0.58 dx_parent} * S`), which
  sharpens cut banks without moving the parent-scale mean.
- Result on the fixture planet's main river (72,800 km2 at LOD4, runoff
  19.5 mm, aridity 0.63): bankfull 334 m3/s, mean 45 m3/s, bank silt-clay
  20 %, valley slope 0.0016 = 1.7x the braiding threshold, so ~75 % braided
  (~110 m belt) with a single-thread bend where the slope drops.
- Persistence (chain LOD4 -> LOD7 on that bend, plus branches on the cut
  bank and the point bar):
  - LOD4 (2.7 km, 7 m): planform readable (braids, bend, levees, water).
  - LOD5 (376 m, 1 m): one bend; inherited, never re-carved (0 new reaches);
    banks sharpened below the parent's spacing by up to 1.1 m; cut bank,
    inner slope and wetted width at mean flow all visible.
  - LOD6 (56 m, 0.15 m): the bend is no longer recognizable; only a bank
    (a ~1 m step) or open water remains; sharpening 0.08 m.
  - LOD7 (17 m, 0.1 m): water surface or bank slope only; nothing added.
  - Lineage (child box-filtered vs parent): RMS 0.031 / 0.003 / 0.001 m.
  - Verdict: the phenomenon (planform) is visible at LOD4-5 and gone at
    LOD6; its parts (bank, water) persist to LOD7.
- Found and fixed during the chain test: jump-flood nearest points polished
  along the centreline; braid threads use the integrated phase `int ds/W`
  (stored per reach, so children draw the parent's threads); children rebuild
  stored centrelines as Catmull-Rom curves (polyline kinks scalloped the
  banks); levees ramp up from the bank edge (was a step).

**Open items (next rounds).**

- `surface_evolution._apply_channel_incision` uses `pi R / (rows - 1)` as
  the y spacing of regional tiles (52 km at every level): routed incision is
  several times too deep at LOD1-3 (LOD3 max 72 m). Fix in a LOD1-3 round
  with before/after.
- Child water cycles ignore `boundary_inflow`: through-rivers are missing
  from `rivers` and from the True Color overlay at LOD1-3.
- Heights are rounded to 1 cm in several refinement steps; at LOD6-7
  (0.1 m cells) this shows as contour terraces in relief.
- Bank cohesion comes from clay minerals only; the ontology has no sediment
  texture (grain size) field, and all unconsolidated sediments share one
  mechanical profile. Braiding threshold is the (vegetated-river)
  Leopold-Wolman line; unvegetated calibration (Lapotre et al. 2019) pending.
- Meander history (scroll bars, oxbows, cutoffs) is not modelled yet.
- Channels are carved from LOD4; LOD3 could resolve the largest rivers.
- (Verified at the start of round 2: the `final2` rebuild with spline
  centrelines and the levee ramp removed the beaded point-bar line at
  LOD6/7.)

**Track B - catena stipple at LOD3/LOD4.**

- Finding: True Color at LOD3/LOD4 carried a uniform light stipple. Probing
  the material layers showed bedrock (granodiorite) poking through the
  calcrete/limonite cover on every 1-3-cell bump; switching the catena crest
  term off removed it.
- Cause: `material_routing.catena_fields` normalised topographic position by
  the map's own spread, which is scale-free: on a near-flat site decimetre
  roughness counted as full crests (50 % mantle thinning) and hollows.
- Fix: normalise by `max(spread, CATENA_RELIEF_FLOOR_M = 3 m)` (a few soil
  depths, Heimsath et al. 1997). Rugged maps are unchanged. Same-tile
  fine-scale luminance noise 2.02 -> 1.41 (the same as disabling crest
  thinning entirely). Regression test
  `test_decimetre_roughness_on_a_plain_is_not_a_catena`.

**Track B (found while tracing the test river) - parent rivers never entered
child tiles.**

- Finding: a 71,000 km2 river crossing into the LOD3 tile left it again at
  its entry cell; the tile's largest interior catchment was 1,900 km2, so
  floodplains, bed sorting and channels only ever saw local streams.
- Cause: `drainage._priority_flood` seeds every boundary cell of a regional
  grid as an outlet, including the cells where `boundary_inflow` injects the
  parent's rivers. The parent's own bed undulates by a few metres, so the
  child's floor just inside an entry is often higher than the edge cells
  beside it, and the flood spilled the whole catchment back out there.
- Fix: `material_routing.inlet_mask` - boundary cells of the valley floor a
  river enters through (floodplain half-width of its catchment, the
  `channel_belts` law; entries below a channel head's catchment are sheet
  flow and stay outlets) are not flood seeds. Used by `filled_routing`
  (`channel_belts`, `boundary_inflow` of the parent, `alluvial_channels`)
  and `fluvial_relief.stream_power_relief`. Same LOD3 terrain: interior
  catchment 1,900 -> 72,900 km2; 13 % of the boundary becomes inlet.
  Regression test `test_river_entering_through_a_notch_crosses_the_tile`.
  Side effect seen at LOD2: the row of dark pits along the tile's inflow
  edge (entry cells incised as sinks) disappears.

**Track B (exposed by the inlet fix) - floodplain seams and stripes.**

- Finding: once the big river really crossed LOD4, its 2.3 km floodplain
  covered the whole tile and showed straight 45-degree seams between
  tributaries and vertical stripes beside the river.
- Cause: `regional_refinement._floodplain_flattening` gave every cell the
  bed level of its nearest channel (chamfer propagation), which jumps at the
  boundary between two channels' zones and, beside an east-west river,
  copies the river's cell-scale bed noise down each column.
- Fix: blend the propagated bed level with a Gaussian at the parent's
  spacing and soften the belt weight over 1.5 cells (a floodplain surface is
  continuous). Regression test
  `test_wide_floodplain_has_no_stripes_from_the_rivers_bed_noise` (old rule
  0.22 m column-to-column std, bound 0.15 m).
- Also removed at LOD4+: the flattening's 0.5 m one-cell groove along every
  D8 channel, and `surface_evolution._apply_channel_incision` (forced
  downstream beds along the water cycle's straight river polylines, which
  cut ~2 m trenches with shoulders wherever a path crossed a rise). From Site
  scale on, `alluvial_channels` owns channel geometry; narrower channels are
  sub-cell. Regression test
  `test_site_scale_leaves_channel_geometry_to_alluvial_channels`.
- Floodplain islands: `material_routing.channel_belts` assigned each cell
  to its *nearest* channel, so every small tributary carved an unflattened
  island (sharp Voronoi seams) out of a big river's floodplain, and its
  chamfer propagation stopped after 64 cells (448 m at LOD4, against a
  2.3 km half-width). Now `_dominant_channel` (weighted jump flooding) gives
  each cell the channel whose floodplain reaches it furthest, and the belt
  weight tapers to zero over the last fifth of the half-width and towards
  the valley walls instead of stepping from 0.5 to 0. Regression test
  `test_tributaries_do_not_cut_islands_out_of_a_wide_floodplain`.
