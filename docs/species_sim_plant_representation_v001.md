# Species Sim plant representation

[Mongolian Locoweed woody cushion](species_sim_oxytropis_aciphylla_v001.md)
adds compact woody axes, seasonal compound leaves, persistent spinous rachises,
pea flowers and pale pods, with five editable modules and landscape previews.

[Siberian spruce layered crown and hanging cones](species_sim_picea_obovata_v001.md)
composes short-needle conifer traits and editable organs, fixes the optional
primary-density ceiling and interpolated whorl sockets, and separates biological
needle dimensions from collective shoot artwork. Existing pine and fir controls
remain unchanged.

[Fireweed rhizome patches and ascending racemes](species_sim_chamaenerion_angustifolium_v001.md)
adds seasonal leafy aerial axes on persistent rhizomes, upward-moving flowering,
closed capsules below flowers and six editable organ modules, with production
BioSim and map evidence.

[Common morel soil-fruiting ascocarps](species_sim_morchella_esculenta_v001.md)
adds a reusable pitted, stalked fungal body plan, persistent diagnostic soil
mycelium and independent fruiting flushes, with editable artwork, metric cap/stalk
dimensions and production BioSim/map previews.

[Silver Birch pendant branchlets](species_sim_betula_pendula_v001.md)
separates arched supporting limbs from hanging fine shoots, with measured-range
leaf scale, explicit short shoots, stable cohort accounting and production
BioSim/map evidence. Existing birch artwork is preserved.

[Woods Rose renewing canes](species_sim_rosa_woodsii_v001.md)
adds persistent basal slots with young, branched and ageing cane cohorts,
replacement through time and lateral flower/hip clusters. The saved refinement
includes matched before/after, seasonal and production BioSim renderer views.

[Wood Anemone persistent rhizomes and seasonal shoots](species_sim_anemone_nemorosa_v001.md)
adds reusable below-ground persistence, summer aerial dormancy and spring
return, with saved editable organs and matched before/after evidence.

[Interrupted Clubmoss surface axes and upright shoots](species_sim_spinulum_annotinum_v001.md)
implements a portable microphyll-shoot recipe and separate spore-cone module.
The plant and four editable assets are saved, with matched before/after,
lifecycle and production BioSim renderer evidence.

[Soaptree Yucca terminal rosettes](species_sim_yucca_elata_v001.md) adds bounded
persistent axes, terminal leaf crowns, retained dead-leaf skirts and crown-borne
panicles, with preserved before/after evidence and production BioSim previews.

[BioSim pixel-cap asset review](species_sim_biosim_pixel_caps_v001.md) compares
all 56 live authored Plantae species at 84, 165 and 220 pixels, connects edited
organ artwork through the sprite caches, and records the first Nordmann fir
shoot-asset refinement.

Low creeping herbs can opt into separate petiole geometry, unequal paired
blades and an authored leaf pitch. A shared rounded-head recipe composes
measured corolla openings on separate tubes, with later fruit groups remaining
display proxies. [Narrow Leaf Sand Verbena](species_sim_abronia_angustifolia_v001.md)
records the annual composition, photo critique, four editable modules,
unchanged mature comparison plants and unresolved root/fruit details.

Candidate sheets now use fixed representative mature display ages. Known root
systems develop gradually with structural age, with side axes elongating from
their sockets. See [gradual root development](species_sim_root_architecture_v001.md#2026-10-11--gradual-root-development-and-mature-candidate-previews)
for matched Chicory evidence, unchanged mature envelopes and regression checks.

Further developments: [oak foliage and 32-pixel organ](species_sim_oak_foliage_v001.md),
[African Baobab woody-axis proportions and drought-deciduous turnover](species_sim_adansonia_digitata_v001.md),
[collective flowering-crown coverage](species_sim_bloom_cohorts_v001.md),
[Silver Wattle primary branches and yellow head panicles](species_sim_acacia_dealbata_v001.md),
[Oriental Bittersweet seasonal vine organs](species_sim_celastrus_orbiculatus_v001.md),
[Elandsberg Paintpetal sparse foliage and flowering shoot](species_sim_codonorhiza_elandsmontana_v001.md),
[optional lateral shoot length and upward curvature](species_sim_lateral_shoots_v001.md),
[Pussyfoot leafy subshrub shoots and terminal head clusters](species_sim_praxelis_clematidea_v001.md),
[Plantae catalogue, shade and Forest View spacing](species_sim_forest_shade_v001.md),
[birch/oak/horse-chestnut tree architecture](species_sim_tree_architecture_v001.md),
[Palhinhaea stoloniferous clonal growth](species_sim_palhinhaea_stoloniferous_v001.md),
[Broadleaf Plantain rosette and spike calibration](species_sim_plantago_major_v001.md),
[Common Chicory mixed-leaf rosette bolting](species_sim_cichorium_intybus_v001.md),
[Common dandelion basal scapes and pappus heads](species_sim_taraxacum_officinale_v001.md),
[vine support search and tree climbing](species_sim_vine_climbing_v001.md),
[pixel-solid vine and tree interactions](species_sim_pixel_solid_interactions_v001.md),
[structural rods and helical vine ascent](species_sim_rod_support_v001.md),
and [Eastern white pine needle fascicles](species_sim_pinus_fascicles_v001.md).

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

The species card separates two related fields under **Behaviour â†’ Plant
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

The consolidation follows the architectural-model literature: HallÃ©, Oldeman,
and Tomlinson describe modular axes, branching, axis orientation, and
reiteration; Kurth and colleagues describe shoot-unit rules as a basis for
plant-architecture simulation; and Wang and Li summarize determinacy,
branching, and internode elongation as major architecture dimensions. See
[Plant Architecture: A Dynamic, Multilevel and Comprehensive Approach](https://pmc.ncbi.nlm.nih.gov/articles/PMC2802949/),
[Branching patterns: the simulation of plant architecture](https://doi.org/10.1016/0022-5193(79)90172-3),
[Tropical trees and forests: an architectural analysis](https://www.documentation.ird.fr/hor/fdi%3A09318),
and [Molecular Basis of Plant Architecture](https://doi.org/10.1146/annurev.arplant.59.032607.092902).

The same nested **Behaviour â†’ Plant Behaviour** path now contains
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

`leaf_fascicle_size` is an optional integer trait for fascicled leaves. It is
kept separate from `plant_leaf_cluster_density`: fascicle size is an organ
count, while cluster density remains a continuous renderer/canopy-fullness
calibration. The shared tree-shoot grammar can therefore represent two-,
three-, and five-needle pines without a species-ID branch.

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

1. **Ontology species** â€” identity, phylogeny, ecology, and the optional
   pointer fields `plant_blueprint_ref` and `plant_growth_snapshot_ref`.
2. **Plant blueprint** â€” a small gzipped JSON document containing authored
   reusable modules (`root`, `stem_section`, `branch_section`, `leaf`,
   `flower`, `fruit`) and species growth parameters. Each module may point at
   an illustration/pixel document authored with the existing editor.
3. **Growth snapshot / scene reference** â€” Species Sim emits compact module
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
Clonal environmental context is covered separately in
[Neighbour-root influence and clonal avoidance](species_sim_neighbour_root_influence_v001.md).

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

The [Woods Rose refinement pass](species_sim_rosa_woodsii_v001.md) adds an
opt-in trait-driven cane grammar, corrected organ scales, and seasonal
flower-to-hip and deciduous foliage behavior. Its five Pixel Studio assets
are saved and verified against the inspected design manifest.

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

Flower, inflorescence, fruit, and cone rendering now has a fixed six-species
before-state and an ordered refinement plan: [reproductive-organ visual
baseline](species_sim_reproductive_organs_v001.md).


Implemented Lolium tillering and trait comparisons: [implementation record](species_sim_lolium_tillering_plan_v001.md).

Root tissue visuals and cross-species Compare: [root comparison record](species_sim_root_architecture_v001.md#root-visual-refinement-and-cross-species-compare-2026-09-05).

Reference-image calibration, architecture ranges, and direct Pixel Studio handoff:
[Species Editor record](species_sim_editor_v001.md).

Below-ground renewal origins driven by `plant_life_form = geophyte`:
[geophyte life-form record](species_sim_geophyte_life_form_v001.md).

Plant Species Gradual Improvement for a trunkless rhizomatous palm, including
quantitative compound-frond fields and reusable terminal crowns:
[Nipa palm terminal-frond record](species_sim_nypa_terminal_fronds_v001.md).

Stationary wood-associated fungi reuse the growth clock, portable snapshots,
pixel asset workflow and diagnostic cameras, with independent persistent
mycelium and recurring bracket bodies. A verified Fungi card supplies an
explicit fungal recipe rather than vascular plant traits:
[Dryadâ€™s Saddle](species_sim_cerioporus_squamosus_v001.md).

Compatible rhizomatous terminal pinnate crowns may opt into metric curved
fronds with an authored `plant_leaf_attachment_angle`. Opening angle, crown
openness and branch droop control pose; missing angle retains the legacy
recipe. A `visual_unit=leaflet` asset composes inside the frond at leaflet
scale. Canonical crown bounds and ecological quantities remain stable across
LODs; this path is independent of fern pinnule composition.

Plant Species Gradual Improvement for rhizomatous ferns, including one-leaf-per-frond
semantics, hierarchical pinnae/pinnules, and distributed root sockets:
[Common bracken fern-frond record](species_sim_pteridium_fern_fronding_v001.md).

Factorial composition of two existing fields, with the graminoid culm grammar
mounted at generic rhizomatous-clonal ramet sockets:
[African alpine bamboo field-composition record](species_sim_oldeania_field_composition_v001.md).

Tree plus suckering-clonal composition:
[Coast redwood field-composition record](species_sim_sequoia_field_composition_v001.md).

Plant Species Gradual Improvement for a compact giant fern, including reusable
alternate primary pinnae and scale-separated frond hierarchy:
[Horse shoe fern primary-pinna record](species_sim_ptisana_pinna_arrangement_v001.md).

Conservative unknown leaf dimensions for small trees, preserving measured organs:
[White Stemmed Ebony refinement](species_sim_diospyros_whitei_v001.md).

Measured panicles assembled from individual flowers, with spatial bud/open/spent
progression and neutral legacy defaults:
[Summer Lilac inflorescence refinement](species_sim_buddleja_davidii_v001.md).

Lychee field composition, reference-derived compound-leaf/panicle/fruit assets,
and bounded compound-tree foliage sampling:
[Lychee design pass](species_sim_litchi_chinensis_v001.md).

Independent basal-frond and internal-pinna arrangement, measured pinnule assets,
and height-aware compact fern crowns:
[Horse Shoe Fern design pass](species_sim_ptisana_howeana_v001.md).

Connected graminoid blades rendered with physical width and smooth taper,
and irregular compound-panicle fallbacks with a terminal basal anchor:
[Wood Club Rush visual refinement](species_sim_scirpus_sylvaticus_visual_inspection_v001.md).

Flowering leafy forb shoots composed with clonal spread, physically sized
lobed leaf and tubular-head assets, and LOD-stable foliage cohorts:
[Creeping Thistle design pass](species_sim_cirsium_arvense_v001.md).

Sequential leaf development with independent length/width stretching of
the existing pixel asset and portable canonical cohort metadata:
[Leaf development refinement](species_sim_leaf_development_v001.md).

Spreading woody shrub crowns and physically sized broad-leaf fascicles with
canonical cohorts and editable leaf/stem/branch assets:
[Siberian Nitre design pass](species_sim_nitraria_sibirica_v001.md).

Two-level compound umbels composed from physically sized individual flowers,
with developing alternate compound leaves on an iterative forb:
[Spreading Hedge Parsley design pass](species_sim_torilis_arvensis_v001.md).

An optional authored leaf opening angle follows each local host twig while
preserving sockets, organ sizes and ecology:
[Leaf attachment angle](species_sim_leaf_attachment_angle_v001.md).

Surface-attached fungal bodies now also support fruticose tufts: see [Vesuvius Rock Lichen](species_sim_stereocaulon_vesuvianum_v001.md) for shared attachment geometry, distinct pseudopodetia/phyllocladia, pixel views and lifecycle verification.

The shared surface grammar also supports discrete foliose lobes and authored
thallus/apothecium palettes. See [Elegant Sunburst Lichen](species_sim_rusavskia_elegans_v001.md)
for the saved species design, corrected ancestry and verified catalogue admission.

Existing crown, pruning and twig controls also support a photograph-guided
Scots pine refinement with a deeper irregular crown and visible major limbs:
[Scots Pine variable refinement](species_sim_pinus_sylvestris_v001.md#10-photograph-based-variable-refinement-2026-10-05).

Ordinary tree leaders now carry their own terminal foliage cohort, with a
slender apex and camera-aware, landscape-budget-safe leaf/needle sampling:
[Terminal tree foliage](species_sim_tree_leader_foliage_v001.md).

Rooted floating rosettes now project their pixel blades onto the actual water
plane, with connected stalk sockets, physical leaf area and editable cup blooms:
[European White Water Lily refinement](species_sim_nymphaea_alba_v001.md).

Ascending multi-stem shrubs can compose physically sized individual flowers
into small stalked racemes without multiplying ecological reproductive organs:
[Sweet Mock Orange refinement](species_sim_philadelphus_coronarius_v001.md).

Broad spreading trees can carry separately connected hanging panicles and
fruit bodies, using sparse measured flower compositions and actual seasonal
viewer stages: [Kigelia design](species_sim_kigelia_africana_v001.md).

Node-based tree foliage cohorts now follow an authored deciduous leaf calendar
without removing woody axes or retained pods. Racemes also admit denser displays
and upright individual corollas on hanging axes:
[Black Locust design](species_sim_robinia_pseudoacacia_v001.md).

Ordinary iterative forbs retain canonical leaf cohorts when low detail hides
their sprites, and authored leaf angles now reach their asset projection:
[West Indian Wood Nettle design pass](species_sim_laportea_aestuans_v001.md).

Emergent aquatic clumps can opt into separate curved petioles, tilted planar
blades and fruiting peduncles that bend toward the water, while water lilies
retain horizontal floating blades through the same pixel projection:
[Green Arrow Arum design pass](species_sim_peltandra_virginica_v001.md).

Compact clonal herbs can opt into independent ramet reach, dense leafy nodes
and upper branching, with terminal capitula progressing to fruiting heads:
[New England Aster design pass](species_sim_symphyotrichum_novaeangliae_v001.md).

Small nonclonal creeping herbs can branch independently of vegetative spread,
with opposite foliage and connected axillary pedicels that recurve in fruit:
[Scarlet Pimpernel design pass](species_sim_lysimachia_arvensis_v001.md).

Dimorphic herbs can compose short basal vegetative shoots with an erect
fertile axis, using individually connected raceme flowers and capsules:
[Blue Toadflax design pass](species_sim_nuttallanthus_canadensis_v001.md).

Wood-associated bracket fungi can use explicit sessile attachment with zero
stalk dimensions, retaining the existing stalked recipe and portable zero
radii. Editable pale shelf and elongated-pore artwork demonstrates the path:
[Lampy Bracket design pass](species_sim_trametes_gibbosa_v001.md).

The same fungal path supports optional, paired editable cap variants and
deterministic width/grouping controls. Variant identity and substrate sockets
remain stable through growth and LOD; recipes without those controls keep
their previous snapshots. See the Lampy Bracket variety refinement above.

Optional fruiting-panicle display groups and large matched reproductive inspections are documented in [Moringaâ€™s visibility refinement](species_sim_moringa_oleifera_v001.md#2026-10-09-reproductive-visibility-refinement). They add display bodies at existing sockets while preserving canonical organs and ecology.

Higher-order fern pinnule assets now follow their supporting axes and form tapered secondary divisions. A shared canopy selector conceals underground rhizomes while preserving soil cutaways, including Species Editor previews. The generic fern inspection enlarges one frond separately from the patch. See [Common Brackenâ€™s rework](species_sim_pteridium_fern_fronding_v001.md#2026-10-09-common-bracken-rework) for the physical-unit audit, original editable artwork, matched comparison and Horse Shoe Fern reuse check.

Surface organisms can opt into authored pressure, gas partial-pressure and temperature growth envelopes. The same response drives exposure history and Biosphere suitability; standing mass can use the authored population density. [Biomasser 13B](species_sim_biomasser_13b_v001.md) demonstrates the fictional barren-rock pioneer, generic fertility trait and atmospheric inspection. Its numerical specification is a design choice, not an empirical real-lichen tolerance.

Wood fungi can opt into selected RGB colour-weathering pairs while retaining body shape, attachment and canonical ecology. The shared asset preview now selects an actual bracket for its close-up, and the fungal inspection can show matched fresh/weathered bodies. See [Violet Pored Bracket Fungus](species_sim_trichaptum_biforme_v001.md) for the thin sessile shelf recipe, editable paired artwork and violet-to-buff comparison.

Rhythmic conical tree crowns now resolve successive young whorls and apply
their authored pyramidal envelope before maturity. Mature geometry and other
crown/rhythm combinations are preserved; compatible recipes identify the
new grammar in their fingerprints. See [White Pine's young-crown recovery](species_sim_pinus_fascicles_v001.md#2026-10-09-young-crown-recovery)
for frozen stage comparisons, the expected Nordmann Fir effect, and ecology.

Wolf Apple composes the existing woody-tree and reproductive paths with
original lobed leaf, purple flower and green berry modules. Its open ascending
crown and enlarged matched branch inspection are documented in
[Wolf Apple](species_sim_solanum_lycocarpum_v001.md), including unknown root
dimensions, provisional display timing and preserved regression controls.

Leafy sympodial herbs can opt into a bounded shoot recipe with attached
cauline foliage, delayed ascending laterals and branched terminal heads.
Canonical morphology is shared across LODs; editable modules retain physical
sizes. See [Annual Fleabane's rework](species_sim_erigeron_annuus_v001.md) for
the two reference-photo targets, young-fork correction, native pixel verification,
single-season display and unchanged sampled controls.

Basal rosette forbs can opt into separate petiole and lamina geometry with
structural panicles of tiny stalked reproductive organs. The bounded recipe
preserves fertile geometry across bloom, fruit and leaf loss, while ecology
uses canonical foliage across LODs. [Alpine Sorrel](species_sim_oxyria_digyna_v001.md)
documents the original editable blades, flowers, winged fruits and axis strips,
regional uncertainty, root proxy and matched phase inspection.

Woody creeping shrubs can opt into a bounded runner/ascending-shoot recipe with
metric leaf spacing, lateral coverage and short-shoot branching. Default creeping
and herb recipes remain separate; canonical cohorts and axis length reach
Species Sim and Biosphere consistently across LOD. See [Black Crowberry](species_sim_empetrum_nigrum_v001.md)
for the photographed comparison, editable organ artwork and saved calibration.

Wood-associated fungal previews share the existing oak bark artwork on a fixed
diagnostic trunk. Unit horizontal projection makes flat caps and round supports
share the same metre scale, while actual-host compositions retain their scene
projection. The multi-view renderer keeps wood visible and labels fungal flush
phases, with matched early/mature details. See [Dryadâ€™s Saddle preview refinement](species_sim_cerioporus_squamosus_v001.md#2026-10-10--uniform-wood-reference-and-metric-preview-correction).

[Chicken of the Woods](species_sim_laetiporus_sulphureus_v001.md) composes the
same bracket grammar with sessile hardwood attachment, four paired shelf forms,
variable widths and an orange/yellow-to-cream weathering palette. Its original
editable modules and model-clock inspection keep persistent colonies distinct
from annual fruit bodies without claiming measured decay or growth rates.

An explicitly authored herbaceous sedge profile can produce metric basal
blades, separate involucral bracts and short rays bearing individual spikelet
visual units. Canonical structure and foliage area remain stable across LOD;
green-yellow flowering and brown fruiting artwork share the same sockets.
[Manyspike Flatsedge's refinement](species_sim_cyperus_polystachyos_v001.md#2026-10-10--structured-spikelets-metric-blades-and-distinct-fruiting)
records the photographed geometry, editable modules and limits of this
multi-floret display unit. Other tillering recipes retain their existing path.

Clonal forbs can opt into compact basal rosette blades alongside cauline foliage,
with seasonal leaf cohorts shared by Species Sim and Biosphere. Capitulum
compositions can declare measured width rather than length for the head artwork.
See [Pompom Weed](species_sim_eupatorium_macrocephalum_v001.md) for the photo-based
recipe, editable pink heads, frozen comparison and unresolved root dimensions.
### 2026-10-11 â€” flatsedge fascicle and tuft refinement

The opt-in tufted-sedge grammar now produces compact ray-aligned fascicles with
a bounded authored `cluster_spread_deg` control, and varies culm, blade and bract
posture. Spikelet directions are projected in the current camera. See
`species_sim_cyperus_polystachyos_v001.md` for frozen-baseline evidence, the two
photo-derived defects, 174 tests plus one additional projection test, unchanged
sample controls and remaining biological limits.

### 2026-10-11 â€” branched woody vine refinement

An explicit bounded `branched_vine` shoot profile adds connected lateral axes
and metre-scaled ground meander to the existing seasonal vine path. The viewer
separates a visible external support fixture from the unsupported ground scene.
See [Oriental Bittersweet](species_sim_celastrus_orbiculatus_v001.md) for the two
photo-derived defects, preserved biology/assets, original-sample regression and
168 passing tests. No second authored climber currently matches the recipe.


### 2026-10-11 â€” forked cyme herbs

An explicit bounded pleiochasial_herb profile builds connected primary rays,
paired forks, separate photosynthetic bracts and single cyathium/capsule sockets.
Metric modules and deterministic seasonal leaf cohorts share canonical ecology
across LOD. See [Sweet Spurge](species_sim_euphorbia_dulcis_v001.md) for references,
native artwork, 181 passing tests and the pending final refresh/checkpoint after
a command-runtime failure.


### 2026-10-11 â€” columnar succulents

The optional `columnar_succulent` growth behaviour and bounded shoot profile
build leafless photosynthetic columns with delayed ascending arms, connected
metric tissue and terminal areoles. A shared shallow-radial root recipe grows
with structural size. Expanded-leaf area stays zero; stem surface and geometric
tissue volume are separate diagnostics. See [Saguaro](species_sim_carnegiea_gigantea_v001.md)
for primary references, editable assets, chronological onset, projection checks,
unchanged sample controls and limits. Other succulent body plans stay unchanged.


### 2026-10-11 â€” short woody reproductive spurs and persistent sepals

An optional bounded `woody_spurs` shoot recipe extends the shared shrub path with
metric fine-node spacing, short lateral reproductive shoots and connected
pedicels. A persistent-calyx display composes independent native sepal and
drupelet artwork; sepals enlarge/red first while fruits ripen separately.
Canonical foliage and reproductive metrics reach BioSim across LOD. The calyx
role uses the normal Pixel Studio assignment and editor refresh paths. See
[Carnival Ochna](species_sim_ochna_serrulata_v001.md) for primary references,
native documents, the two photo-derived refinements, unchanged original-sample
controls and remaining biological limits. No second live species currently
uses the new recipe.

### 2026-10-18 â€” flower-terminated leafy fork modules

An opt-in herb recipe now constructs connected two-leaf sympodial units,
terminal cymes and lateral successor axes, with individual stalked flowers and
berries. Fork depth changes topology; organ dimensions remain independent.
See [Black Nightshade](species_sim_solanum_nigrum_v001.md) for inherited-baseline
correction, evidence, editable assets, tests and unresolved biology. The earlier
redwood planar-spray prototype was rejected; its original species recipe is
restored and the prototype remains inactive there.

### 2026-10-18 â€” mother and daughter succulent rosettes

The opt-in `offset_rosettes` shoot profile adds bounded daughter crowns with
independent developmental sizes and explicit concealed rhizomes. It reuses
the metric curved-blade component; offset count does not change the mother's
organ geometry. See [Century Plant](species_sim_agave_americana_offsets_v001.md)
for research, preserved baseline, comparison, tests and limits. Flowering and
maternal replacement are reserved for a later pass.

### 2026-10-18 â€” nonrepeating reproductive cycle of one rosette

An optional crown cycle extends offset rosettes with a terminal panicle and
mother-only senescence. Retained dead blades contribute no living leaf area;
daughter crowns persist and expand. The colony remains perennial. See
[Century Plant reproduction](species_sim_agave_americana_reproduction_v001.md)
for matched evidence, calibrated clock, editable assets and limits. This is a
bounded first-generation model; capsules and recursive descendant flowering
remain unresolved.

### 2026-10-20 â€” vegetative tillers and selected fertile culms

An opt-in `mixed_tillers` profile builds compressed leafy shoots alongside
selected elongated culms. Fertile fraction changes tall axes/spikes without
changing basal blade geometry or area. Whole-spike artwork follows physical
width and top projection. See [Perennial Ryegrass](species_sim_lolium_mixed_tillers_v001.md)
for sources, matched evidence, preserved legacy assets and limits.


Dwarf Morning Glory adds opt-in metric planar leaves and distichous runner leaves to the shared creeping-herb recipe; see [species design and verification](species_sim_evolvulus_nummularius_v001.md).


Orange Peel Fungus adds stalkless soil cups with paired native views and an explicit unresolved trophic mode; see [fungal design and verification](species_sim_aleuria_aurantia_v001.md).
