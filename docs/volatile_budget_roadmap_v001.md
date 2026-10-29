# Volatile budget roadmap v001 — making every stage follow the elements

Started 2026-09-24. Builds on `docs/volatile_budget_v001.md` (the budget
itself) and `docs/entity_field_overview_material_v001.md` §8 (element-driven
material roster). Goal: once the player sets the element distribution, every
screen — air, seas, ices, rocks, colours, climate, moons, history — agrees
with it. Earth's composition at 1 AU must stay Earth.

Each phase ends with a **visual checkpoint**: a sheet of LOD0 true-colour and
material maps for a fixed set of worlds (`tools/volatile_showcase.py`), sent to
the user before the phase is called done.

Reference worlds (same seeds every checkpoint): Earth @ 1 AU, the same Earth
inventory @ 0.72 AU (Venus), Titan-like icy inventory @ 9.5 AU, Mars crust @
1.52 AU; later phases add Pluto-like, Europa-like and Io-like bodies.

Status legend: `[ ]` open, `[~]` in progress, `[x]` done.

---

## Phase 1 — The surface agrees with the budget

Why: air and seas follow the elements, but the material roster and ices still
use older rules (Titan lists marble, CO2 ice and hematite; CO2 ice layers
appear with no CO2 in the air).

* [x] **1.1 Climate consistency.** The water-cycle grid disagreed with the
  budget (Titan 181 K vs 93 K: sea surfaces clamped to water's 268-307 K;
  Earth 3 K cold). Now: the SST range follows the liquid's freezing point;
  latitude contrast and seasons scale with the atmosphere's radiative time
  constant P/(g T^3) (`meridional_contrast_factor`); the planet grid is
  anchored to the budget mean (`_anchor_area_weighted_mean`). Earth
  288/297/270 K (mean/equator/poles), Titan 92.8/93.1/91.9 K, Mars 214/241/166 K.
* [x] **1.2 Planet tags from the budget** (`_add_volatile_budget_tags`):
  oxidizing / reducing / intermediate surface, water vs hydrocarbon liquid
  (methane rain does not weather rock into clays), `carbonate_favorable` from
  carbonate-locked CO2 or CO2 over open water, `volatile_ice_<species>`. The
  crust panel uses the same tags (the budget is known at the crust stage).
* [x] **1.3 Redox-aware availability** (`oxidized_family_fraction`, from
  formulas and modal mineralogy): on reducing worlds rocks with >= 15 %
  carbonate / sulfate / ferric phases vanish, smaller shares scale down;
  intermediate worlds halve them.
* [x] **1.4 Surface ices from condensates**: budget `surface_ice_species`
  (condensed ices, freezing seas, winter-pole frost via `coldest_surface_k`,
  icy crust). Ice materials need their volatile there; their existence no
  longer depends on crust chemistry. N2/CH4 ice materials deferred to 2.4.
* [x] **1.5 Biogenic rocks only on Earth** (user decision 2026-09-24):
  ontology `biogenic_origin` on lignite, anthracite, oil shale, chalk, coquina,
  diatomite, radiolarite, phosphorite (tools/author_material_chemistry.py);
  the roster keeps them only with the `biosphere_history` tag (planet_earth).
* [x] **1.6 Headless isolation**: headless runs (tests, demos, the showcase)
  wrote planets and geology into the live ontology. `RunLocalOntologySink`
  keeps a run's persistence in memory. 234 leaked rows remain in
  `.cache/ontology` (11 planets incl. planet_volatile_demo_*,
  planet_headless_*, planet_parity, planet_test_1; 133 geologic units, 85
  cover patches, 3 orbital spaces, 2 entries) -- cleanup awaits the user's OK.
* [x] Visual checkpoint 1 (sent 2026-09-24): Earth unchanged; Venus basalt/
  anorthosite under the sulfuric deck; Titan water-ice bedrock, orange haze,
  methane seas on 2.3 % of the map (real Titan ~1 %); Mars polar H2O caps
  (8 %), CO2 frost possible, still grey. Found and fixed on the way: Mars kept
  ~1800 ppm SO2 (cold-air sulfur removal now 1e-4) and trace condensates
  counted as surface ices (now >= 5 cm global).

Acceptance: Earth's roster unchanged (×1 Earth); Titan shows no carbonates,
sulfates, ferric oxides or CO2 ice; Mars keeps sulfates and ferric oxides.

## Phase 2 — The surface looks like it should

* [x] **2.1 Ferric dust** cover for dry, oxidized, windy worlds (Mars is red).
  `true_color_physics.py`: ferric staining (iron x oxidant x wet/dry
  alteration rate x time), dust mantle swept where gusts saltate sand
  (Shao-Lu threshold vs a dissipation-balance wind; air density exp(-z/H)
  gives bright uplands, dark lowlands), sand abrasion of coatings.
* [x] **2.2 Organic sediments** (haze fallout) for reducing, hazy worlds:
  tholin burial from haze optical depth x age. Dunes as landforms: open.
* [x] **2.3 Crater erasure**: gravity-scaled crater depth/rim (Pike);
  volcanic resurfacing = time-integrated heat loss, applied as lava
  flooding of the lowest terrain (smooth plains + cratered highlands);
  methane-haze burial lowers retention. Titan: few craters.
* [ ] **2.4 Non-water ice colours**: CO2 frost, N2/CH4 ice (pinkish, Pluto),
  sulfur (Io).
* [ ] **2.5 Where seas sit**: liquid fills the deepest basins by hypsometry;
  Titan's lakes should gather at the cold, rainy poles (evaporation vs
  precipitation), not in random crater floors.
* [x] **2.6 Venus true-colour stripes**: were a map-space dune sinusoid;
  all map-space sinusoids (diagonal "sine curve" artifacts, date-line
  seams) replaced by seamless sphere noise (`sphere_noise.py`); gradients
  are periodic across the date line.
* [ ] Visual checkpoint 2 (+ Pluto-like, Io-like).

## Phase 3 — Icy bodies and moons

* [ ] **3.1 Interior density for ice-rich compositions** in
  `planetary_physics` (rock core + ice/ocean mantle): Titan g ≈ 0.14,
  Ganymede ≈ 0.15, Europa ≈ 0.13. Retention and pressure then follow.
* [ ] **3.2 Tidal heating → subsurface oceans** under ice shells (shell
  thickness, ocean depth), linked to cryovolcanism.
* [ ] **3.3 Moon environment**: sputtering by the parent planet's
  magnetosphere (Europa, Io: near-airless), stellar distance via the parent.
* [ ] Visual checkpoint 3 (+ Europa-like, Ganymede-like, Enceladus-like).

## Phase 4 — Chemistry refinements

* [ ] **4.1 Photochemical steady state**: methane lifetime vs resupply,
  ethane/tholin production (feeds 2.2 and the sea mixture), CO2 photolysis
  (trace CO, O2), abiotic O2 ceiling.
* [ ] **4.2 Radiogenic gases**: 40Ar from K × age, 4He from U/Th.
* [ ] **4.3 Liquid mixtures**: CH4–C2H6–N2 seas, brines (freezing-point
  depression; Mars seasonal brines), ammonia–water.
* [ ] Visual checkpoint 4.

## Phase 5 — History instead of one steady state

* [ ] **5.1 Staged evolution**: magma-ocean outgassing → early wet phase →
  faint young Sun (luminosity vs age) → integrated escape → carbonate memory
  (a desiccated world keeps carbonates from its wet past).
* [ ] **5.2 Timeline output** (pressure, temperature, ocean depth vs time)
  for the UI.
* [ ] Visual checkpoint 5 (Venus timeline, desiccated world, early Earth).

## Phase 6 — Player-facing and hygiene

* [ ] **6.1 "Where did my elements go"** panel: per element, rock / seas /
  air / lost to space.
* [ ] **6.2 "Why" read-outs** for verdicts (runaway: absorbed flux vs the
  282 W/m² limit; carbonates hold N bar of CO2; escape removed X).
* [ ] **6.3 Test hygiene**: triage the pre-existing failures
  (`test_world_gen_orbit_clicks` ×10, `test_headless_worldgen` ×3) —
  several belong to areas other sessions/Codex own; coordinate, don't
  rewrite blindly.

---

## Open decisions (ask the user)

* ~~Biogenic sediments~~ — decided: Earth only (1.5).
* Delete the 234 rows headless runs leaked into the live ontology (1.6)?

## Session log

* 2026-09-24 — roadmap written; phase 1: 1.1-1.6 implemented, tests in
  tests/test_volatile_budget.py (SurfaceConsistencyTests) and
  tests/test_headless_worldgen.py (HeadlessIsolationTests); visual checkpoint
  via `python tools/volatile_showcase.py --out <dir>`.
* 2026-09-25 — physical true colour, six same-seed iterations (showcase).
  Artifacts: sphere noise replaces map-space sinusoids; spherical plate
  metric + rough margins (no triangular continents); Poisson crater
  placement; periodic gradients.  Colour: `true_color_physics.py`
  (Rayleigh from the gas column, haze/dust/sulfuric-deck aerosols,
  ferric/dust/space-weathering/organic alteration, saltation dust,
  direct-beam share for relief shading, (1+cos)/2 sky view); oceans by
  absolute depth (exp(-2Kz)); rivers by channel width vs pixel.  Terrain:
  Pike crater scaling, heat-integrated lava flooding.  Result: Mars
  (138,107,80) ~ observed disc colour, Titan ochre haze, Venus pale deck,
  barren Earth tan land / navy sea.  Tests: tests/test_true_color_physics.py,
  tests/test_crater_resurfacing.py.  Known limits: Titan's surface under
  its organic blanket is nearly uniform (no dune fields/bright highlands
  yet).
* 2026-09-26 — barren Earth pass.  Wetness/aridity from the aridity index
  P/PET (180 mm/yr had counted as 65 % "wet"); ferric weathering in
  physical time (wet ~30 kyr, dry photo-oxidation ~200 Myr) over a
  residence time H/E from runoff- and slope-driven erosion, so tropics
  redden, temperate ground browns, tundra/cold deserts stay grey and Mars
  still rusts over Gyr; goethite/hematite by wet share and temperature;
  pigment from each rock's oxidizable iron (ontology Fe x (1 - oxidized
  share)).  Artifacts: continent/ocean fraction blended across plate
  boundaries (~300 km margin) removes the 97x49 stair-step coasts; winds
  calm in the subtropical ridge / polar front instead of flipping on
  unit-vector normalisation.  Tests: tests/test_planet_surface_continuity.py,
  EarthWeatheringTests.  Known: test_orbital_climate_forcing
  ...regional_climate_matches_parent_at_patch_edges fails in the working
  tree (passes at HEAD; not from this pass -- coarse 5-row parent Köppen
  vs child).
