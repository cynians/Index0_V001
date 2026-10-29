# Lolium perenne tillering & disturbance response — implementation plan

**Status: implemented and compared, 2026-09-05.**

## Implementation record

The original research handoff is retained below as historical context. The live
persistent Lolium row now uses `tussock_tillering`, `resprouting: strong`, and
`regeneration_strategy: mixed`; `clonal_spread: low` remains unchanged. Mixed
retains seed recruitment alongside vegetative persistence, consistent with the
FEIS distinction between disturbed habitats and managed pasture. Only these
three fields were persisted; experimental treatments were not authored.

The blueprint carries all three traits. Resprouting multiplies only the supplied
disturbance input by absent=1, weak=.8, moderate=.55, strong=.3. Unknown/unset
preserves the full penalty. Water, light, disease, temperature and competition
are unaffected. This changes vitality and its derived fecundity, growth and
mortality proxies. It does not grant a fecundity bonus or simulate a timed
post-disturbance tiller rebound.

Clonal spread scales tiller crown radius and lateral drift: none=.12 (zero drift),
low=1, moderate=1.6, high=2.4. Unknown/unset preserves the historical low-spread
default rather than asserting absence. The existing maturity-driven tiller
count is retained. Seeded shoot orientation and height variation break perfect
symmetry; foliage occupies the lower three nodes, and spikes attach exactly at
culm tips at LOD 1 and 2. Seedling leaves and crown radius grow with maturity.
Canonical tiller counts, leaf totals and area remain stable across LODs.

The tussock gallery now samples seedling, juvenile, mature vegetative,
reproductive and senescent stages (four seeds each), so flowering cannot be
missed between maturity and senescence. Other growth grammars keep their stages.

### Baseline and acceptance

Captured before editing with the actual renderer: Lolium, age 200 days, seed
101, LOD 1, no environmental stress. Baseline: one culm, five stem sections,
four leaves, no visible spikes. Final: nine tillers, 45 stem sections, 27 leaves,
nine spikes. Roots and authored pixel organ assets were retained.

Matched-scale spread comparison gives tiller radii of .0048, .0801, .1280 and
.1920 m (rounded render coordinates); all treatments keep nine tillers and
27 leaves. The measured radius is the greatest horizontal stem-node distance
from the crown, not the leaf-tip footprint or a rhizome extension rate.
At disturbance .6, vitality is .8473/.8617/.8796/.8975 for absent/weak/moderate/
strong; unknown gives .8473. Strong still incurs a cost relative to unstressed
vitality. These are bounded qualitative coefficients, not calibrated biology.

### Reproduce and inspect

Run `py -m tools.render_lolium_tillering` from the project root. It reads the live
persistent species, uses explicit labelled trait overrides, and preserves the
saved pre-change snapshot for the before/after panel.

- [Before/after diagnostics](../artifacts/lolium_tillering/diagnostics.png)
- [20-case growth gallery](../artifacts/lolium_tillering/growth_gallery.png)
- [Roots](../artifacts/lolium_tillering/roots.png)
- [Spread treatments](../artifacts/lolium_tillering/spread_comparison.png)
- [Disturbance treatments](../artifacts/lolium_tillering/disturbance_comparison.png)
- [Metrics](../artifacts/lolium_tillering/results.json)

Images were inspected. The first pass exposed oversized newborn leaves and a
gallery missing the reproductive interval; both were corrected and rerendered.
App launch was attempted, but no targetable Index_0 window was exposed, so these
are renderer previews and do not verify live navigation.

### Verification and related repair

43 targeted tests plus 28 subtests passed across `test_lolium_tillering.py`,
`test_species_simulation.py`, `test_species_diagnostics.py`, and
`test_forest_ecology.py`. Coverage includes response direction, zero/unknown
inputs, bounded spread, deterministic geometry, exact organ attachment,
LOD stability, blueprint/snapshot round trips, and reproductive gallery coverage.

Persisting the previously unused resprouting property exposed an imported-store
resource allocator collision. New data-property creation now synchronizes the
allocator as individual creation already did. A temporary-store regression test
reproduces a stale allocator, adds a new trait, and verifies it after reopening.
The live fields were read back successfully. The baked Lolium blueprint,
200-day snapshot and five-day telemetry were refreshed.

Remaining limits: no grazing/fire event timeline, no simulated tiller mortality
or regrowth burst, no seedbank dynamics or compatibility/pollination model.
Regeneration strategy is carried as metadata, not a new recruitment mechanism.
Roots retain the pre-existing coarse architectural proxy. Senescence still uses
the existing life-history model rather than individual tiller turnover.

## Original research handoff (historical)

## Why Lolium, why this field

A schema audit of `world/plant_traits.py` against the real simulation
consumers (`species_simulation.py`, `plant_assets.py`, `tree_shoots.py`,
`forest_ecology.py`, `root_growth.py`) found that the entire Reproduction,
Regeneration/Disturbance, and Nutrition/Symbiosis sections of the plant-trait
schema are authored on several species but never read by any simulation code
— `grep`-verified zero references outside `ui/card.py` and the `tools/author_*`
scripts for `seed_size_class`, `clonal_spread`, `resprouting`,
`regeneration_strategy`, `nitrogen_fixation`, `nutrition_mode`,
`mycorrhizal_type`, `pollination`, `dispersal`. `reproductive_mode` is read,
but only as a binary gate on whether flower modules render at all.

*Lolium perenne* was chosen over a tree species (oak/birch) because it uses
the generic single-axis placement grammar (`_grow_single_axis`,
[species_simulation.py:844](../simulations/species/species_simulation.py#L844)),
not the recursive node-based tree grammar in `tree_shoots.py` — there is no
branch-order/leaf-cohort machinery to work around. The user has agreed Lolium
does not need to remain the "unbranched single-axis" grammar-diversity
representative described in `species_sim_plant_representation_v001.md`; a
different species can take that role later.

## Current state (verified against live code)

- Diagnostic-view renders (Individual, 20 Growth Stages gallery, Roots — see
  attached previews from `tools/render_lolium_preview.py`-style rendering)
  show a **single culm for the entire lifespan**. Growth-gallery rows #13–20
  ("mature"/"senescent", 60–383 days) are structurally identical to each
  other: `seg 5 • br 0 • cl 4 • est leaves 4`. No tillering, no visible
  inflorescence at any authored stage.
- `_grow_single_axis` only ever places one terminal flower, gated on
  `lod >= 2` and `flowering_factor > 0.0`
  ([species_simulation.py:879](../simulations/species/species_simulation.py#L879)).
  The gallery/individual previews don't reach that LOD, so reproduction is
  invisible in practice even though `reproductive_mode: "sexual"` is authored.
- A second, unused growth grammar already exists for this exact purpose:
  `_grow_tussock` ([species_simulation.py:806](../simulations/species/species_simulation.py#L806))
  grows several independent basal shoots from one crown, each with its own
  leaves and a flower slot once reproductive. It is reachable via
  `plant_growth_behaviour: "tussock_tillering"`
  ([dispatch at species_simulation.py:1425](../simulations/species/species_simulation.py#L1425))
  and is even the automatic default for graminoids with no authored behaviour
  ([plant_assets.py:276](../simulations/species/plant_assets.py#L276)). Lolium
  overrides that default with `"unbranched_single_axis"`
  ([tools/author_lolium_perenne.py:196](../tools/author_lolium_perenne.py#L196)).
- Inside `_grow_tussock`, `shoot_count = max(3, round(4 + 5 * maturity))`
  ([species_simulation.py:813](../simulations/species/species_simulation.py#L813))
  and the per-shoot offset radius is a hard-coded `0.04 m` crown radius with a
  `0.01 m` per-generation drift
  ([species_simulation.py:820-821, 841-842](../simulations/species/species_simulation.py#L820)).
  Neither reads any authored trait — `clonal_spread` and `resprouting` have
  zero influence on either number.
- `get_ecological_outcome()` ([species_simulation.py:1647](../simulations/species/species_simulation.py#L1647))
  already accepts a `disturbance` environment key
  ([species_simulation.py:1663](../simulations/species/species_simulation.py#L1663))
  and folds it into a generic, species-blind `stress` average that uniformly
  depresses `vitality`/`fecundity`/`mortality_risk`. No species trait
  currently modulates how a given species *responds* to disturbance.

## Botanical grounding: Lolium perenne reproduction

- **Wind-pollinated (anemophilous)** and **genetically self-incompatible**
  (two-locus S–Z gametophytic system) — an obligate outcrosser in most
  natural populations; viable seed set needs a nearby, genetically distinct
  conspecific, not just "reproductive_mode: sexual."
- Seeds are comparatively large for a grass (~7.5 mg), **non-dormant**, and
  germinate readily with moisture — but the **soil seed bank is transient and
  poorly persistent**: buried seed disappears mainly by germinating, not by
  long-term dormancy.
- **Persistence and regrowth are dominated by tillering, not seed.** It is a
  true bunchgrass: some cultivars carry short rhizomes, but the species does
  **not** have a creeping/spreading habit.
- **Disturbance is the trigger for vegetative reproduction**: tiller number
  drops immediately after grazing, then rebounds to **1.5–3× the ungrazed
  count**; fire top-kills the plant but it resprouts quickly from surviving
  tissue, and fire specifically stimulates production of *reproductive*
  tillers.

Sources: [USFS FEIS species review](https://research.fs.usda.gov/feis/species-reviews/lolperp),
[self-compatibility genetics, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8554087/),
[S–Z self-incompatibility locus, PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8103805/).

This maps cleanly onto two already-existing, currently-inert levers:
`resprouting` (disturbance-triggered vegetative burst) and `clonal_spread`
(spread habit — and, per the research, Lolium's defining trait here is that
it does **not** spread far, not that it lacks tillers).

## Recommended authoring corrections (small, do first)

These are ontology-authoring edits, not simulation code, and should land in a
`tools/author_lolium_perenne.py` or equivalent update before/alongside the
mechanism work so the new code has correct data to run against:

1. `plant_growth_behaviour`: `"unbranched_single_axis"` → `"tussock_tillering"`.
   This alone (with zero code changes) starts routing Lolium through
   `_grow_tussock` and lets the existing gallery/renderer show multiple
   shoots and per-shoot flowering.
2. `regeneration_strategy`: `"seed_bank"` → `"vegetative_recruitment"` (or
   `"mixed"` if the implementer wants to keep the transient seed contribution
   visible). The current value contradicts the FEIS finding of a weak,
   transient seed bank and a tillering-dominated regeneration strategy.
3. `resprouting`: currently unauthored. Add `"strong"` — directly supported
   by the 1.5–3× post-grazing tiller rebound and the fire-resprouting
   behaviour above.
4. Leave `clonal_spread: "low"` as authored — it is correct for *spread
   distance*, which is the axis this plan wires it to (see Slice B below).
   Do not reinterpret it as tiller count.

## Mechanism, Slice A — `resprouting` modulates disturbance response

**Target:** `get_ecological_outcome()`, [species_simulation.py:1647](../simulations/species/species_simulation.py#L1647).
**Why first:** smallest possible diff, no dispatcher/grammar change, no new
environment plumbing — `disturbance` is already a live input
([line 1663](../simulations/species/species_simulation.py#L1663)), it's just
species-blind today.

Proposed shape (illustrative, not final):

- Read `resprouting` (`absent`/`weak`/`moderate`/`strong`/`other_unknown`)
  from `self.blueprint.growth` the same way `shade_tolerance` is read for
  Forest View.
- Apply a per-species dampening factor to the `disturbance` term specifically
  (not the whole `stress` average) before it enters the `vitality` formula at
  [line 1671-1676](../simulations/species/species_simulation.py#L1671) — e.g.
  `absent: 1.0` (full penalty, unchanged), `weak: 0.8`, `moderate: 0.55`,
  `strong: 0.3`. A strongly-resprouting species should still show *some*
  cost from a disturbance event (it's not free), just markedly less than a
  non-resprouting species under the same input.
- This is the same "trait modulates a shared environmental input" pattern
  already established for `shade_tolerance` in `forest_ecology.py`,
  applied to a different environment key and a different outcome fn — no new
  concepts, one new per-species multiplier table.
- Optional, closer to real biology: also feed `resprouting` into `fecundity`
  under a nonzero `disturbance` input, since FEIS explicitly notes fire
  "stimulates production of reproductive tillers" — a resprouter's fecundity
  should not simply collapse under disturbance the way a non-resprouter's
  does.

**How to verify (no rendering needed for this slice):** call
`get_ecological_outcome({"disturbance": 0.6})` on Lolium (`resprouting:
strong`) vs. a non-resprouting comparison species/override, at matched
maturity, and confirm vitality/fecundity separate in the expected direction.
This mirrors the existing `test_species_simulation.py:555` pattern
(`sim.get_ecological_outcome({"water_stress": 0.4, "competition": 0.2})`).

## Mechanism, Slice B — `clonal_spread` shapes tiller geometry

**Target:** `_grow_tussock()`, [species_simulation.py:806](../simulations/species/species_simulation.py#L806).
**Why second:** touches the dispatcher precondition (Lolium must actually be
authored as `tussock_tillering` first) and is a visual/render change, so it
needs the skill's baseline → treatment → comparison workflow, not just a
numeric assertion.

Proposed shape:

- Do **not** change `shoot_count`'s existing maturity-driven formula
  ([line 813](../simulations/species/species_simulation.py#L813)) — more
  shoots as a plant fills in is already a reasonable proxy and isn't what the
  research calls out as Lolium's distinguishing trait.
- Instead, scale the **crown offset radius** (`0.04` at
  [line 820-821](../simulations/species/species_simulation.py#L820)) and the
  **per-generation lateral drift** (`0.01` at
  [line 841-842](../simulations/species/species_simulation.py#L841)) by
  `clonal_spread`: e.g. `none`/unset: keep tillers essentially at the crown
  (very small radius, no drift — a tight single point), `low`: current
  constants (Lolium's real, non-creeping bunch habit), `moderate`: ~1.6×,
  `high`: ~2.4×. This directly encodes "low clonal_spread = tight,
  non-creeping tuft" vs. a genuinely spreading clonal species, which is what
  the field name and the research both actually describe.
- This makes `clonal_spread` visibly change the *footprint* of the tussock in
  the Individual/gallery views (tight tuft vs. sprawling patch) while
  `shoot_count`/maturity continues to control how full it looks — two
  orthogonal, individually legible knobs.

**How to verify:** render Lolium (or a clonal_spread="high" override of the
same species, matched seed/age/LOD, the way the Forest View doc used a single
oak with labelled shade-tolerance overrides) at `none`/`low`/`moderate`/`high`
and compare tussock footprint width in a paired image, plus assert
deterministic, bounded placement radii in a unit test.

## Other low-hanging fruit noted, not in this plan's scope

- `pollination` and `dispersal` are the only two Reproduction fields that are
  **schema-incomplete**, not just unwired: both are open `string_list` fields
  with no entry in `PLANT_TRAIT_CHOICES` at all (every other categorical
  field in the schema has a controlled vocabulary). Lolium's own research
  (wind-pollinated, self-incompatible) can't be authored cleanly today.
  Adding a small choice set (`wind`, `insect`, `self`, `water`, `mixed`,
  `other_unknown` for pollination; `wind`, `water`, `animal_external`,
  `animal_ingested`, `ballistic`, `gravity`, `human_dispersed`,
  `other_unknown` for dispersal) would benefit every authored species, not
  just this one, but is a separate, schema-level change and was left out of
  this plan to keep it scoped to one mechanism.
  - Note self-incompatibility itself is a *breeding-system* fact, not a
    pollination *vector* — it doesn't cleanly fit either field as currently
    named. Worth a short wiki-entry mention rather than forcing a schema fit.
- `moisture_preference` (`moist`) and `waterlogging_tolerance` (`medium`) are
  authored and fully inert (Environmental Response category) but are a
  distinct mechanism (soil moisture stress, not reproduction) and were the
  runner-up option from the original exploration — left for a later pass.

## Tests to extend

- `tests/test_species_simulation.py` already has
  `test_tussock_grass_adds_authored_inflorescence_after_reproductive_onset`
  (~line 250) and `test_short_telemetry_run_reports_growth_and_ecological_state`
  (~line 398) using generic `tussock_tillering` fixtures — extend these (or
  add siblings) with `clonal_spread` variants asserting radius/footprint
  differences, and add a `resprouting` variant asserting the
  `get_ecological_outcome({"disturbance": ...})` direction from Slice A.
  Keep both deterministic (fixed seed) and bounded (finite radius, shoot
  count still `>= 3`).
- No existing test pins `spec_lolium_perenne` to `unbranched_single_axis`
  behaviour specifically — the single-axis grammar test
  (`test_single_axis_has_one_culm_alternating_leaves_and_one_terminal_flower`,
  ~line 229) uses a synthetic `spec_single_culm` fixture, so retargeting
  Lolium's authored behaviour should not break it.

## Open questions for the implementer

1. Exact multiplier tables above (`0.3`–`1.0` for resprouting,
   `~0.0`–`2.4×` for clonal_spread radius) are illustrative starting points
   from this research pass, not calibrated values — pick something bounded
   and monotonic, then refine from the visual/numeric comparison per the
   skill process.
2. Whether Slice A's disturbance-dampening factor belongs on the
   `disturbance` term alone or should also touch `competition` (grazing is
   arguably both) — the FEIS material only speaks to grazing/fire, so
   starting with `disturbance` alone is the more conservative reading.
3. Whether to also correct `regeneration_strategy` for other authored
   graminoids/clonal species while touching this code path, or scope the
   authoring fix to Lolium only for this cycle.
