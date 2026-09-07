# Species Sim plant representation

Further developments: [oak foliage and 32-pixel organ](species_sim_oak_foliage_v001.md),
[Plantae catalogue, shade and Forest View spacing](species_sim_forest_shade_v001.md),
and [birch/oak/horse-chestnut tree architecture](species_sim_tree_architecture_v001.md).

Species Sim is a local biological growth lab for one ontology species. It is
deliberately separate from map, bioregion, and other scenery systems.

## Fidelity contract

The plant model is explicitly three-dimensional even though the current
diagnostic and scenery views are 2D projections. Positions, curved stem paths,
and compact per-placement orientation frames live in z-up model space; pixel
modules remain 2D reusable assets that are oriented into that space and then
projected orthographically. This keeps the representation volumetric without
requiring mesh authoring.

Species Sim is the expensive organism-level layer that a future BioSim can run
for a bounded representative cohort of every relevant species. BioSim supplies
local conditions and selects representative or archetypal organisms; Species
Sim returns compact ecological outcomes such as growth, health, resource use,
fecundity, mortality, recruitment, competition, and disturbance response.
Those outcomes influence the population and assemblage, without requiring every
organism in the population to exist as a detailed simulation object.

The detail budget is adaptive. Small herbs may resolve individual leaves when
that changes the result. Large trees should generally resolve a structural
graph, branch orders, leaf-area cohorts, roots, litter, and representative
active shoots. A single-leaf object is therefore an available detail level,
not a universal simulation requirement.

Detailed state is transient by default. Species Sim produces compact summaries
for BioSim, while authored blueprints, baked growth products, and explicitly
important narrative states may be stored. Population state remains the
authoritative aggregate for large populations.

## Controlled growth behaviour vocabulary

The species card separates two related fields under **Behaviour → Plant
Behaviour**. `plant_growth_form` is the broad botanical body plan: tree, shrub,
subshrub, forb, graminoid, vine, fern, moss, succulent, aquatic, or
other/unknown. `plant_growth_behaviour` is the modular architectural grammar
nested under **Plant Growth Behaviour**: unbranched/single axis,
iterative/indeterminate shoot,
determinate/sympodial shoot, rosette/short-internode, branched woody,
climbing/twining/scrambling, creeping/prostrate, tussock/tillering,
rhizomatous clonal, stoloniferous/runner, and suckering/basal clonal spread.
Species Sim uses the pair together: form supplies the botanical body-plan
defaults, while behaviour selects the procedural growth grammar.

This is intentionally a primary strategy rather than a claim that plant growth
forms or architectural behaviours are mutually exclusive. Axis continuity,
branching rhythm and timing, lateral-axis orientation, flowering position and
apical control are now separate controlled fields. Phyllotaxis remains derived
from leaf arrangement; determinacy and reiteration can be refined separately
later. Existing ontology rows are artefacts for this pass and are not migrated;
new authored entries use the split functional fields directly.

The consolidation follows the architectural-model literature: Hallé, Oldeman,
and Tomlinson describe modular axes, branching, axis orientation, and
reiteration; Kurth and colleagues describe shoot-unit rules as a basis for
plant-architecture simulation; and Wang and Li summarize determinacy,
branching, and internode elongation as major architecture dimensions. See
[Plant Architecture: A Dynamic, Multilevel and Comprehensive Approach](https://pmc.ncbi.nlm.nih.gov/articles/PMC2802949/),
[Branching patterns: the simulation of plant architecture](https://doi.org/10.1016/0022-5193(79)90172-3),
[Tropical trees and forests: an architectural analysis](https://www.documentation.ird.fr/hor/fdi%3A09318),
and [Molecular Basis of Plant Architecture](https://doi.org/10.1146/annurev.arplant.59.032607.092902).

The same nested **Behaviour → Plant Behaviour** path now contains
**Plant Life-Cycle Behaviour**, with the controlled choices ephemeral, annual,
biennial, short-lived perennial, and perennial.

Species Sim resolves `plant_lifespan` into a transient life-history profile.
The profile supplies juvenile duration, reproductive onset, senescence timing,
terminal-death or overwintering behaviour, and a bounded preview horizon where
one is needed. `growth_rate` and `maturity_rate` remain independent modifiers;
they change how quickly a plant reaches its life-history milestones without
changing the category itself. Missing or unrecognised lifespan data uses a
perennial-like runtime default marked `runtime_default` and is never written
back to the ontology.

The resulting life phases are `juvenile`, `mature_vegetative`, `reproductive`,
`senescent`, and `dead`. These phases affect structural products where
appropriate, especially reproductive modules, and feed the compact outcome
fields `vitality`, `fecundity`, and `mortality_risk`. Seasonal cues can later
refine the profile without changing the authored dropdown vocabulary.

## Functional plant-trait schema

The active species schema is deliberately one abstraction level above a
laboratory trait database. It stores practical intrinsic traits for life
history, size, growth rate, leaf phenology and placement, photosynthesis,
succulence, root architecture, storage, reproduction, dispersal, regeneration,
nutrition/symbiosis, and environmental response. Architecture-relevant fields
such as `leaf_arrangement`, `leaf_attachment_pattern`, and `leaf_clustering`
remain in the ecology schema because they affect procedural organ placement;
purely cosmetic leaf appearance belongs to the visual plant model.

The first continuous architecture refinements are normalised 0..1 fields:
`plant_branch_droop`, `plant_branch_angle_gradient`, `plant_crown_openness`,
`plant_leaf_spacing_bias`, and `plant_leaf_depth_gradient`. They tune a named
strategy without forcing every intermediate form into a new category. The
orthogonal categorical fields `plant_shoot_dimorphism` and
`plant_leaf_distribution` describe whether a species has long and short shoots
and whether leaves are distributed along shoots, terminally clustered, or use a
mixed pattern.

The silver birch representative uses `long_and_short_shoots` and
`mixed_long_short_shoots`. Its grammar keeps a dominant leader and an open,
pyramidal crown, distributes leaves along primary lateral shoots, and adds
compact paired leaves to fine terminal shoots. This is a compact architectural
proxy: a mature tree resolves branch orders and leaf placements in Species Sim,
while later population and scenery products can reduce the result to leaf-area
cohorts or a baked scene.

## Leaf-cluster resolution

Snapshots distinguish `leaf_sample_count`, `leaf_cluster_count`, and
`estimated_leaf_count`. A small plant can keep one visible leaf as one
calculative cluster. A mature tree instead attaches many spatially localised
leaf clusters to shoot segments and twigs. Each cluster carries an estimated
leaf count, leaf area, health, phenology factor, and visual density. The
renderer expands that cluster into a few sampled sprites, while physiology and
future BioSim handoff use the estimated count and area. This allows canopy
detail to increase with maturity without creating one expensive simulation
object per leaf.

Categorical traits are the default. Nullable quantitative refinements such as
`mature_height`, `max_root_depth`, `temperature_range`, `frost_tolerance`, and
`soil_ph_range` may be added when references provide them. Derived outcomes
such as canopy position, succession role, suitability, and growth success are
not primitive species traits.

The card uses the nested dropdown for categorical single-value traits. Range
objects and open-ended multi-value traits remain direct fields until they have
a dedicated range editor or multi-select vocabulary.

The existing ontology rows are artefacts for this schema pass and are not
migrated. The new schema is code-owned, so new authored entries use the
functional fields directly; the old field names are excluded from the active
species card/schema.

## Species inheritance

Species and cladistic relations use a general directional inheritance service
for behaviour and simulation data. A parent clade may resolve a field only from
authored descendant values, and only when those sources agree. Derived values
carry `inferred_field_sources`; they are not treated as authored sources for a
grandparent. A species with an unknown local field may read a resolved parent
value as an effective fallback without writing that value into the child.

Cards mark these effective fallbacks as **inferred** with a teal row/value
treatment. Editing the row creates a local authored override. Conflicts remain
unknown instead of being guessed.

## Three layers

1. **Ontology species** — identity, phylogeny, ecology, and the optional
   pointer fields `plant_blueprint_ref` and `plant_growth_snapshot_ref`.
2. **Plant blueprint** — a small gzipped JSON document containing authored
   reusable modules (`root`, `stem_section`, `branch_section`, `leaf`,
   `flower`, `fruit`) and species growth parameters. Each module may point at
   an illustration/pixel document authored with the existing editor.
3. **Growth snapshot / scene reference** — Species Sim emits compact module
   placement arrays plus 3D orientation frames. A map stores only a scene reference: species, blueprint,
   optional snapshot, seed, LOD, transform. It does not store or simulate
   individual leaves.

Snapshots are deterministic products keyed by blueprint fingerprint, seed, age,
and LOD. LOD 0 is a skeleton, LOD 1 keeps major leaves, and LOD 2 is the full
preview. This makes it possible to bake one representative plant and instance
it thousands of times across scenery while preserving variation through seed
and transform.

The initial generator is intentionally a growth grammar rather than a fixed
mesh: buds extend internodes, branch probabilistically, and leaves are placed
by phyllotaxis. Authored modules can therefore change the look without
changing the biological growth code.

Growth-form defaults are deliberately distinct in the runtime grammar. Trees
and shrubs use persistent branching; subshrubs use a lower, more open branch
system; forbs use a flexible herbaceous axis; graminoids use a culm or tiller
profile; ferns grow multiple arching fronds with distributed leaflets; mosses
grow low mats; succulents grow compact fleshy rosettes; and aquatic plants use
surface-reaching petioles. These are defaults, not hard biological limits: an
authored growth behaviour can still select a more specific architecture.

The Individual diagnostic view includes a 1.75 m human silhouette and shares
the plant's model-space scale. The silhouette is a display reference only and
is never added to the simulation graph or scenery products.

## Module attachment points

Root architecture now drives a separate bounded belowground graph and a
dedicated **Roots** diagnostic tab. See
[Root architecture implementation and comparison](species_sim_root_architecture_v001.md)
for the ontology candidates, runtime assumptions, validation, and refinement log.

Reusable pixel modules are authored as single organs on transparent canvases.
The Pixel Studio **Guide** tool records a normalized `attachment_point` and a
`growth_vector` as metadata; these guides are not exported into the art. The
attachment point is the socket that joins a leaf, spike, or other organ to its
parent stem, while the growth vector describes the organ's authored direction
from that socket toward its tip. Species Sim aligns the vector to the growth
pattern, scales the sprite from its depicted physical size, and lets a growing
stem expose explicit attachment-point records for leaves. This keeps one
narrow leaf asset reusable across many plants, mirrors it for alternate
handedness when needed, and avoids treating the whole image canvas as the
connection point.

### Module authoring invariants

One pixel module represents one reusable organ or one reusable structural
section. A **leaf module is one botanical leaf**. For a compound leaf, that
single module may include the rachis and its leaflets, but it must not include a
stem section, twig, branch, flower, or a miniature canopy. The growth grammar
creates the stem and branch attachment points, then chooses, mirrors, rotates,
and scales that one leaf module at each placement.

Stem/trunk and branch/twig appearance are authored separately as structural
modules or texture sets. They are not drawn into the leaf asset. The canonical
blueprint references are `plant_stem_module_ref`,
`plant_branch_module_ref`, and `plant_leaf_module_ref`; the corresponding
editor entries are available from both the species-card toolbelt and the
Media edit tab. This separation is required even when a species has a very
short stem or when a low-detail preview makes several structures look like one
shape. The same rule applies to root, flower, fruit, and other reproductive
organs.

Stem-like placements may optionally carry a compact curved path in the baked
snapshot. Straight segments remain endpoint-only; petioles and peduncles can
store a few intermediate world-space points when the species architecture
needs a bent or gently bowed connection. The renderer consumes either form,
so map/scenery references do not need to know how the curve was generated.

## Current representatives

The authored representatives intentionally cover different growth
grammars:

- *Lolium perenne* uses a graminoid tussock-tillering blueprint with reusable
  long blades and per-tiller terminal spikes.
- *Nymphaea alba* uses an aquatic, determinate-sympodial blueprint with a
  submerged rhizome, petiole-generated surface attachment points, broad
  notched floating leaves, and alternating surface flower positions.
- *Betula pendula* uses a tall, branched-woody blueprint with an airy bud
  budget, curved trunk/branch paths, distributed toothed leaves, and hanging
  catkin modules.
- *Rosa woodsii* uses independent leaf, cane, branch, flower, and hip references.
  Its compound leaf is a single organ with alternate placement. The generic
  shrub/subshrub branching grammar now grows several outward-directed canes
  from one crown, with branch rise reduced by branch order and the authored
  droop factor. This is an architectural preview, not a calibrated species model.

### Shrub placement refinement (2026-09-05)

Explicit alternate and distichous arrangements resolve to one leaf per node;
opposite resolves to two, and whorled uses a three-leaf runtime default.
Branching-grammar leaves and terminal flowers attach at the actual shoot
endpoint, so lateral extension no longer leaves their sockets behind the stem.
Shrub and subshrub basal canes spread in both horizontal model dimensions.
Their deterministic bud budgets and skeleton-only LOD remain bounded.

The Woods Rose source was checked through the live quadstore's decoded
projection. All five organ/structure references were present. Fresh diagnostic
renders were generated for individual, gallery, forest, and comparison views.
Further work includes species-specific cane renewal, seasonal flowering/hip
succession, and calibration of organ sizes and mature crown dimensions.

The water-lily case is grounded in the species descriptions from [RHS](https://www.rhs.org.uk/plants/11623/nymphaea-alba-%28h%29/details),
[NParks](https://www.nparks.gov.sg/florafaunaweb/flora/2/2/2271), and [NZ Flora](https://www.nzflora.info/factsheet/Taxon/Nymphaea-alba.html).
The authored values are simulation inputs, not a claim that every species
trait is fully resolved by the current schema.


Implemented Lolium tillering and trait comparisons: [implementation record](species_sim_lolium_tillering_plan_v001.md).

Root tissue visuals and cross-species Compare: [root comparison record](species_sim_root_architecture_v001.md#root-visual-refinement-and-cross-species-compare-2026-09-05).

Reference-image calibration, architecture ranges, and direct Pixel Studio handoff:
[Species Editor record](species_sim_editor_v001.md).

Below-ground renewal origins driven by `plant_life_form = geophyte`:
[geophyte life-form record](species_sim_geophyte_life_form_v001.md).
