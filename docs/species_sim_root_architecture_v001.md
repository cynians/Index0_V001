# Species Sim root architecture

Historical species-run previews and evidence files were removed during the 2026-10-13 artifact cleanup. Statements below about retained evidence describe the original run; those artifact paths are no longer available. Authored species and assets remain in the project.

## 2026-10-11 — gradual root development and mature candidate previews

Candidate selection now shows a representative mature, leafy or flowering
stage, rather than drawing a random juvenile age. Fungal recipes choose mature
bodies in a flush. `simulations/species/preview_timing.py` chooses this model
age deterministically; the sample manifest freezes `age_days` for regression.
An authored maturity change can therefore change morphology without secretly
moving the comparison into another season. Historical samples keep their ages;
the current three candidates also have a separately saved mature presentation.

The earlier dwarf-plant correction only scaled **unknown depth defaults** by
mature stature. Common Chicory has an authored deep-root category, resolving
to the existing 2 m class proxy, and was outside that correction. Its juvenile
rosette appeared beside an already extensive root network: the old extent
curve supplied 24% of target depth at 10% structural maturity, with long lateral
axes appearing when their count increased.

Known root architectures now use linear structural-age expansion from zero
to their existing mature depth/spread envelope. Side axes emerge at bounded,
evenly spaced developmental thresholds and elongate from their parent sockets.
Fine-root elongation follows its host's development. Distributed adventitious
clusters use the same age clock. Roots use structural age, not seasonal foliage
or bolting height: established roots do not shrink when perennial foliage falls.
Deep roots may still extend farther than a basal rosette is tall.

This is root grammar version 7, carried in known-architecture blueprint
fingerprints. Unknown architecture stays unresolved. No authored field, depth
class, mature envelope, shoot placement, organ asset or taxonomy was changed.
The curve and emergence thresholds are **qualitative simulation coefficients**,
not measured Chicory growth rates. The general distinction between primary,
lateral and adventitious root development is supported by the University of
Minnesota's [The Science of Plants: Roots](https://open.lib.umn.edu/horticulture/chapter/3-3-roots/).

Observable criteria: small early depth/length; monotonic root development;
new axes beginning near their sockets; stable seed directions; unchanged mature
metrics and shoots; canonical root outcomes independent of LOD; valid finite
parent-first geometry; deterministic and portable snapshots; frozen sample age
despite a maturity-trait change.

Evidence under `artifacts/plant_design/pass_20261011_01/root_development/` uses
the real renderer, seed 303, LOD 2, neutral environment and the same physical
camera across six ages and before/after sheets. `verification.json` checks all
shoot placements unchanged and mature root metrics unchanged. At 5% maturity,
Chicory root depth falls from 0.3282 m to 0.1000 m. At the originally sampled
77.532 days, representative root length falls from 16.2365 m to 6.3615 m,
depth from 1.5180 m to 1.2922 m, and radial diameter from 1.8466 m to 1.0258 m.
Mature results remain depth 2 m, diameter 2.4329 m and length 26.6542 m.

The original three-case regression retains all recorded ages and seeds:
Chicory changes as intended; Narrow Leaf Sand Verbena and Summer Lilac are
unchanged. `mature_sample.json` and `mature_preview/before_contact_sheet.png`
re-present those same candidates at mature ages without replacing that baseline.
All dimensions from depth classes remain labelled runtime proxies. Detailed
soil constraints, species-specific root chronology and turnover remain unresolved.

Verification: 169 tests and 46 subtests passed across root geometry/appearance,
candidate selection, seasonal context, rosette growth, Chicory assets, general
Species Sim, texture rendering, species views and Biosphere soil/nutrients.
All 26 final focused checks passed, including frozen-age rendering integration.
The existing Woods Rose golden fingerprint, seasonal and structural assertions
were retained; unknown roots do not activate the changed grammar. The live app was launched,
but capture failed with `FrameArrived timed out: timed out waiting on channel`,
followed by `window capture timed out: timed out waiting on channel` on a
fresh-window retry. Images are renderer previews; live navigation
was not verified.

Implemented and compared on 2026-09-05. This is a representative structural
growth model, not a calibrated root physiology or soil simulation.

## Existing ontology candidates

Candidates were selected through `PersistentOntologyStore.load_datasets()`:
the decoded projection of the authoritative live SQLite quadstore for
`ontology/index0.owl`. No species fields were changed.

| Species | ID | Authored architecture | Authored depth class |
|---|---|---|---|
| English Oak | spec_quercus_robur | taproot | deep |
| Perennial Ryegrass | spec_lolium_perenne | fibrous | shallow |
| European White Water Lily | spec_nymphaea_alba | adventitious | shallow |

All three lack `max_root_depth`. Silver Birch also has authored root traits
(`mixed`, `intermediate`), but was not one of the three visual candidates.
The mixed grammar is covered by automated tests.

## Inputs and assumptions

- `root_architecture`: taproot, fibrous, adventitious, mixed, other_unknown.
  Missing/unknown architectures stay explicitly unresolved and generate no
  invented root network. The existing crown marker remains.
- `root_depth_class`: shallow = 0.35 m, intermediate = 1.0 m, deep = 2.0 m.
  Missing/unrecognised class uses 0.6 m. These are **runtime proxy values**,
  not measurements or botanical limits. They are never written to the ontology.
- `max_root_depth`: a finite positive `max_m` (or `value_m`) in the structured
  field overrides the class default. Units are explicitly metres; arbitrary
  strings and other units are not silently interpreted. Source metadata
  distinguishes authored maximum, depth-class default, and runtime default.
- Root extent increases with the existing species maturity fraction. It starts
  with a small initial root and reaches its target at structural maturity.
  Age is inherited from the existing Species Sim life-history model; this pass
  does not calibrate species-specific chronological growth rates.

Architecture and depth remain independent: a taproot may be shallow, and a
fibrous system may be deep. The grammar is a compact proxy for the authored
primary architecture, not a claim that these categories are mutually exclusive
or immutable through a plant's life. General background on primary and fibrous
root development is provided by [RHS: How plants grow](https://www.rhs.org.uk/advice/understanding-plants/how-plants-grow).

## Structure and rendering

Taproot creates a dominant descending axis with attached lateral and fine
axes. Fibrous creates several similarly sized axes from the crown. Mixed
retains a descending main axis with a wider lateral footprint. Adventitious
creates roots at separate supporting-stem nodes. For the aquatic grammar,
the support is a short horizontal rhizome proxy at the existing submerged crown;
other non-clonal forms use a compact stem-base support.

When `root_architecture = adventitious` is combined with either
`stoloniferous_clonal` or `rhizomatous_clonal`, the root graph is distributed:
each established runner or rhizome contact owns a bounded local root cluster.
The clonal shoot grammar only reports contact sockets; root topology remains in
`root_growth.py`. This keeps the rule reusable without a species-ID conditional.
Suckering plants and non-adventitious architectures retain their existing root
models.

`root_section` represents only a root segment and reuses the optional root
asset. `root_support` is explicitly a **stem_section** module, drawn separately
from the roots. It is not counted as root length. This preserves the organ and
structure separation contract. Existing shoot placements are unchanged.

Root geometry uses the existing z-up 3D placement graph, parent indices and
orientation frames. Curved axes are approximated by short tapered segments.
All root segments descend at or below the crown; water-lily roots remain below
its submerged crown. Snapshot bounds include all visible root endpoints.

The **Roots** tab provides an enlarged view, scale bar, source label, crown or
sediment line, depth, radial diameter, and representative root length. Individual
and other diagnostic views use the same graph and renderer. Soil tinting is
applied only when clearing a view, so subsequent forest individuals do not
erase previously drawn roots.

## Compact outcomes and detail budgets

Snapshots expose `root_depth_m` (below the soil origin), `root_spread_m` (twice
maximum horizontal distance from the original crown), `root_length_m`,
`root_segment_count`, `root_visible_segment_count`, `root_origin_z_m`,
`root_depth_source`, and `root_model_status`. Distributed adventitious graphs
also report `root_distribution = contact_nodes`, contact/support and cluster
counts, local cluster diameter, and the whole root-system span. Those compact
distribution metrics also reach the ecological summary. They do not yet alter
resource uptake or mortality.

Canonical geometry is bounded to fewer than 400 nodes for the current grammar.
LOD filters branch orders with complete ancestry: 0 keeps primary axes, 1 adds
first-order laterals, and 2 includes fine axes. Compact root metrics are computed
from canonical geometry and stay identical across LODs. Root RNG is separate
from shoot RNG; per-axis seeds prevent fine-root emergence from reshuffling
pre-existing primary directions. Frozen older blueprints get compatible root
module definitions in their snapshots. The root profile's grammar version is
included in newly derived blueprint fingerprints.

## Comparison and refinement log

1. **Round 1:** Connected roots and metrics worked, but ryegrass and water lily
   looked nearly identical. Roots started at a single point, axes were too
   straight, and fine-root emergence consumed randomness for later axes.
2. **Round 2:** Added independent submerged supporting-stem nodes for the water
   lily, curved/tapered axes, stable per-axis randomness, gradual fine-root
   elongation, and the Roots tab. A deterministic deepest primary reaches the
   class-derived target in fibrous and adventitious systems.
3. **Final refinement:** Increased support visibility, labelled sediment/crown,
   added a same-scale comparison, preserved root graphs in forest drawing, and
   checked older blueprint compatibility.
4. **Clonal-contact refinement (2026-09-10):** Replaced the unrealistic single
   crown-centred adventitious fan for clonal plants with one bounded cluster per
   established stolon/rhizome contact. The helper is trait-driven, deterministic,
   LOD-stable in its canonical metrics, and covered for both clonal behaviours.

Mature seed 303, final runtime results:

| Candidate | Depth below crown | Radial diameter | Representative root length |
|---|---:|---:|---:|
| English Oak | 2.00 m | 2.43 m | 26.65 m |
| Perennial Ryegrass | 0.35 m | 0.55 m | 9.24 m |
| European White Water Lily | 0.35 m | 1.13 m | 8.99 m |

These are simulated structural quantities, not empirical species estimates.
The comparison is satisfactory for this architecture pass: three visibly
different attachment strategies, consistent development, valid connected
graphs, and explicit assumptions. Root turnover, real soil constraints,
water/nutrient uptake, root hairs, species-specific depth/spread calibration,
and substrate-dependent contact establishment remain future work. The existing
aboveground oak preview also needs its own separate fidelity pass.

## Reproduction and verification

Run `py -m tools.render_root_comparison --output artifacts/root_comparison_final`
from the project root. `SDL_VIDEODRIVER=dummy` enables headless rendering.

Outputs in `artifacts/root_comparison_final/`:

- `root_comparison.png`: whole plants and enlarged root details; independent
  scales are stated and each view has a scale bar.
- `root_common_scale.png`: all three root systems at the same scale.
- `root_growth_stages.png`: 10%, 40%, and 100% maturity using the same mature
  camera bounds within each species column.
- `spec_*_roots.png`: actual Roots-tab renderer previews.
- `root_comparison.json`: authored inputs, resolved defaults, and stage metrics.
- `seed_lod_audit.json`: 60 species/seed/age cases, each compared at three LODs.

Automated tests cover all four known architectures, finite geometry, parent
connectivity, bounded depth and node counts, progressive growth, seed stability,
LOD-independent metrics, round-trip snapshot serialization, unknown traits,
invalid numeric inputs, authored overrides, aquatic stem attachments, shoot
independence, and older blueprint compatibility.

The desktop app launched and entered its main loop, but the Windows automation
surface did not return its window. Images are fresh Species Sim renderer
previews, not live desktop screenshots; mouse navigation remains unverified.

## Root visual refinement and cross-species Compare (2026-09-05)

The earlier pixel-width conversion multiplied every root thickness proxy by
0.04 metres (0.05 for supports), including ryegrass. This made herbaceous roots
appear centimetres thick and gave all tissues one flat tan colour.

`root_visuals.py` now supplies explicitly labelled functional-form visual
defaults: tree radius multiplier .035 m, shrub .012 m, graminoid .0012 m,
aquatic .002 m, other herbaceous .0028 m. These multiply the existing tapered
axis proxy and a maturity factor; they are **not measured species diameters**.
Woody higher-order branches are reduced further to represent fine roots.
Brown coarse axes blend toward pale fine branches and terminal portions;
grass roots are cream/tan, aquatic roots muted ochre, and supporting rhizomes
remain separate stem organs. Colour is a visual cue, not a simulated root-age,
vitality, mycorrhiza or suberization measurement. Shared traits intentionally
produce similar roots: the two oaks are not assigned arbitrary species colours.

Each root segment is drawn as a tapered polygon with rounded joins, with
subtle highlights on coarse axes and a one-pixel visibility floor for fine
roots. That floor means subpixel roots are exaggerated at overview scale.
The fixed crown disc is omitted when a connected root graph exists. Explicit
root assets retain precedence over this fallback. The root grammar version is
3 (stronger terminal taper); a visual-profile version is included in the
blueprint fingerprint. Snapshot graph format and physical extents are retained.

Botanical basis: the large size range of woody and fine roots is discussed in
[The Ecology of Tree Roots](https://doi.org/10.48044/jauf.1982.047).
[McKenzie and Peterson's root-colour study](https://onlinelibrary.wiley.com/doi/full/10.1111/j.1438-8677.1995.tb00842.x)
reports brown regions and white growing tips, while showing that browning is
not simply synonymous with suberization. These support broad tissue distinctions,
not the selected numeric multipliers or exact RGB values.

### Comparison view

Open **Roots**, then **Compare**. **R** switches between the original individual
comparison and cross-species roots. **S** switches enlarged detail/shared physical
scale; **Left/Right** pages through developed plants. Opening Compare refreshes
the live candidate set; it is retained during rendering rather than traversing
the ontology each frame.

Candidates use the live quadstore plus the Plantae ancestry catalogue and an
authored growth behaviour. Six have resolved roots: Silver Birch, Perennial
Ryegrass, European White Water Lily, Broadleaf Plantain, Sessile Oak and English
Oak. The other five developed plants (Century Plant, Annual Fleabane, Pussyfoot,
Common Bracken, Woods Rose) are shown as unresolved because their root
architecture is unauthored. No ontology values were changed to manufacture
coverage. Each candidate is compared at 100% structural maturity, seed 303,
LOD 2; ages differ by the existing species maturity settings.

### Comparison artifacts and verification

- Baseline: `artifacts/root_visuals_before/`, captured before edits using
  `py -m tools.render_root_comparison --output artifacts/root_visuals_before`.
- Refined three-species comparison: `artifacts/root_visuals_after/root_comparison.png`.
- [Actual Compare view, enlarged](../artifacts/root_visuals_after/compare_detail_1.png).
- [Actual Compare view, shared scale](../artifacts/root_visuals_after/compare_shared_1.png).
- [Unresolved candidates](../artifacts/root_visuals_after/compare_detail_2.png).
- Live inputs and defaults: `artifacts/root_visuals_after/functional_plants.json`.
- Reproduce all cross-species screens: `py -m tools.render_functional_roots`.

Visual inspection confirmed visible taper, coarse/fine separation, distinct grass
and woody widths, and separate aquatic supports. A follow-up enlarged the scale
bars for readability. The baseline candidates retain exactly equal canonical
root depth, spread, length and segment counts. 54 tests plus 28 subtests pass
across root visuals, root growth, Lolium, species simulation, species diagnostics
and forest ecology. New coverage verifies width/colour ordering, age response,
taper, catalogue eligibility, missing traits, and Compare keyboard routing.

The app did not expose a targetable window on the live inspection attempt.
These are actual-renderer previews, not proof of live mouse navigation. Real
species-specific root diameters, root-age cohorts, soil interactions and turnover
remain uncalibrated; the refinement improves legibility and tissue hierarchy.

Neighbour occupancy can now steer clonal connectors without pretending that a
soil model exists: [neighbour-root influence implementation](species_sim_neighbour_root_influence_v001.md).

## 2026-10-10: stature-scaled fallback for unknown root dimensions

The next regular plant sample exposed an unsupported root envelope on
Elandsberg Paintpetal / `spec_codonorhiza_elandsmontana`. At 56.92% maturity,
seed 461708635, model day 25.614 and LOD 2, its 5.93 cm shoot sat above a
root system with a 42.06 cm depth proxy and 79.26 cm span. This was actual
geometry, not a zoom discrepancy. The user requested a sensible scaled fallback.

### Authority, reference and scope

The live quadstore's decoded projection and resolved row contain
`mature_height={min_m:0.15,max_m:0.21}` and `root_architecture=adventitious`,
but no `root_depth_class` or `max_root_depth`. The blueprint supplied a fixed
60 cm unknown-depth default and a 48 cm spread-radius budget. The current
row has 40 authored simulation fields; it is a terminal Plantae species under
`cladis_paintpetals_codonorhiza`. The entire row remains exactly unchanged.

The [existing Paintpetal reference pass](species_sim_codonorhiza_elandsmontana_v001.md#references-and-exactly-two-defects)
documents the inspected habit and flower photographs. Its
[SANBI primary description, printed p.96](https://www.sanbi.org/wp-content/uploads/2024/05/2015_Strelitzia35.pdf)
was checked again: stature is 150–210 mm and the corm diameter is 10–15 mm.
That supports the authored stature and separate corm identity, not a measured
root-depth claim. Root dimensions remain unknown. No photographs, organ
artwork, taxonomy, life timing or authored traits were changed in this
mechanism-only refinement.

The two refinement targets were **excessive fallback depth** and **excessive
fallback lateral reach**, which together dominated the tiny shoot. The shared
fallback now handles both. It does not presume that a real plant's roots must
be shorter than its shoot, or infer underground dimensions from a habit photo.

### Rule and precedence

`root_growth.root_profile` applies the following policy:

1. A valid positive numeric `max_root_depth.max_m` or `value_m` takes precedence.
2. A recognized `root_depth_class` retains its existing proxy: shallow 0.35 m,
   intermediate 1 m, deep 2 m.
3. With neither available, and a finite positive `max_height_m`, the mature
   default depth is `clamp(0.75 * max_height_m, 0.05, 0.60)` metres.
4. Missing/invalid height retains the neutral 0.60 m default. Missing/unknown
   root architecture still produces unresolved roots, not invented structure.

Only defaults actually reduced by stature receive
`depth_source=stature_scaled_runtime_default` and profile grammar version 6.
Unaffected profiles retain version 5 and their exact previous fingerprints.
Both dimensions and the version are already carried in portable blueprints
and cache keys. There is no species-ID branch, migration or world-version path.

The 0.75 coefficient, 5 cm floor and 60 cm ceiling are qualitative simulation
budgets, not empirical root allometry. Mature stature is used so seasonal loss
of an aerial shoot does not erase the underground system. The existing root
development curve still controls age. Lateral reach uses the same architecture
coefficients (taproot .65, fibrous .85, adventitious .8, mixed 1.25) and the new
depth. Large-tree height-based spread, structural attachment, topology, RNG,
root tissue widths, leaf geometry, corm and renewal-bud depth are preserved.

### Frozen comparison and results

Controls were captured before changing code in
`artifacts/plant_design/pass_20261010_01/frozen_roots.json`. They include the
exact selected sample and seed-303 mature/flowering stages, all at LOD 2.

Matched before/after at three ages
uses the same metric camera within each pair. Original sampled preview
is retained separately. The multi-view sheet's canopy and side cutaway are
independently fitted as labelled; they should not be compared by pixel size.

| Case | Root depth proxy, cm before → after | Root span, cm before → after | Canonical root axis length, m before → after |
|---|---:|---:|---:|
| Original juvenile sample | 42.06 → 11.04 | 79.26 → 20.81 | 7.033 → 1.8462 |
| Mature, day 45, seed 303 | 60 → 15.75 | 102.39 → 26.88 | 15.4135 → 4.046 |
| Flowering, day 167.75, seed 303 | 60 → 15.75 | 102.39 → 26.88 | 15.4135 → 4.046 |

Depth statistics describe root elongation below its origin. Paintpetal's
separate corm origin remains 2.5 cm below ground, so the sampled deepest
root is 13.54 cm below soil (previously 44.56 cm). Root/support counts and
connectivity are unchanged. All shoot placements and foliage cohorts are
exactly unchanged in the frozen comparisons. The new live blueprint
fingerprint is `992af865001c626e`, previously `3d5506be16b2f558`.

Canonical root length, depth and spread now reflect the smaller envelope;
this is not a renderer-only correction. Species Sim ecological output and
live BioSim representatives carry the same profile. LOD affects drawn root
detail but leaves those root quantities stable. Paintpetal's canonical leaf
area also remains stable across LOD.

The original three-candidate manifest was rerendered at the recorded seeds
and ages. Only Paintpetal changes, with the expected bounds and fingerprint;
African Alpine Bamboo and Manyspike Flatsedge are unchanged. The bamboo's
height is above the fallback ceiling transition, while Flatsedge has an
explicit shallow depth class. Evidence is in the pass's
`regression/comparison/report.json` and `root_verification.json`.

### Verification and limits

```powershell
py -m pytest tests/test_root_growth.py tests/test_root_visuals.py tests/test_basal_fan_shoots.py tests/test_species_simulation.py tests/test_species_diagnostics.py tests/test_species_editor.py tests/test_biosphere_vegetation.py tests/test_biosphere_soil_nutrients.py -q -p no:cacheprovider
```

**126 passed, 42 subtests passed**, 16.69 s. New coverage verifies monotonic
stature response and clamps; valid-depth/class precedence; absent, invalid,
zero and unknown inputs; topology and deterministic proportional graph
scaling; parent validity and finite geometry; portability/cache versions;
unchanged shoots; canonical root LOD metrics; live field transport; and
BioSim representative handoff. Changed Python files compile and scoped
`git diff --check` passes. This is not a full-suite claim.

A read-only full-app event Driver opened Paintpetal's card, Species Sim,
Roots and Species Editor. Off-screen surfaces were visually inspected and
the root source label appeared correctly. This is a production app/renderer
preview, not a visible-desktop navigation claim. The pass's `app_check.json`
retains the result. No ontology persistence or checkpoint export was necessary.

Actual root dimensions, root turnover, corm-derived attachment anatomy and
species-specific allometry remain uncalibrated. A future measured depth can
replace the fallback without changing this mechanism. The final live-catalogue
search found **Scarlet Pimpernel / `spec_lysimachia_arvensis`** as another
supported small plant with unknown depth: its 0.5 m stature gives a 0.375 m
fallback. Its annual therophyte/taproot combination contrasts with Paintpetal's
perennial geophyte/adventitious roots. No species data was authored for it.

### 2026-10-11 — optional shallow radial roots

A validated `plant_root_profile` with form `shallow_radial` separates a tap
from shallow lateral axes and independently controls depth and radial reach.
It is an authored representative envelope, excluded from taxonomic consensus.
Saguaro uses its nonlinear shoot-size fraction for progressive root growth;
other root recipes retain their existing grammar. See
[Saguaro](species_sim_carnegiea_gigantea_v001.md) for measured constraints versus
calibration, deterministic/LOD-stable tests and the mature/young comparison.
