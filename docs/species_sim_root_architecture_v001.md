# Species Sim root architecture

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
other forms use a compact stem-base support.

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

Snapshots expose `root_depth_m` (below the crown), `root_spread_m` (twice maximum
horizontal distance from the crown), `root_length_m`, `root_segment_count`,
`root_visible_segment_count`, `root_origin_z_m`, `root_depth_source`, and
`root_model_status`. Adventitious graphs also report support-node count.
Ecological outcomes carry depth, spread, length, source, and model status.
These metrics do not yet alter resource uptake or mortality.

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
and true clonal-ramet rooting remain future work. The existing aboveground oak
preview also needs its own separate fidelity pass.

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
