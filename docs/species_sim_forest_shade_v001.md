# Plantae catalogue and Forest View shade experiment

Implemented 2026-09-05; extends the root and oak foliage development cycle.

## Membership and runtime use

`world/plant_catalogue.py` starts at `cladis_plants_plantae` and traverses reverse
`parents` edges through species/cladistics nodes, with cycle protection. Names,
traits and asset references do not establish membership. Illustrations attached
to plants are not taxa. Missing/disconnected ancestry is excluded.

`EntityLoader.build_entity_index()` builds the immutable catalogue on repository
load/rebuild. Taxonomy persistence, deletion and repository mutations refresh it.
`WorldModel.plant_catalogue`, `is_plant` and `is_plant_species` provide runtime set
lookups. Species Sim launch, card tools and browser tools share this catalogue.
Explicit navigation also checks membership. Direct simulation construction is
still available for fixtures and previews. No per-frame ancestry traversal or
second persistent catalogue copy is needed.

Live persistent-store check: **169 Plantae taxa; 33 species**.

## Inputs and treatments

Shade tolerance dropdown: Low / Medium / High / Other–unknown. Oak
(`spec_quercus_robur`) is medium; birch, ryegrass and white water lily are low.
There is no authored high representative, so comparisons use the **same oak
with labelled runtime overrides**, without changing ontology values.

Other oak inputs: mature height 20–40 m, crown openness .43, branch droop .30,
fine twig density .92, cohort density .84, alternate leaves, mixed long/short
shoots. Stand dimensions use the blueprint's resolved maximum height.

## Mechanism and controls

`forest_ecology.py` creates nine established trees at seeded positions and
relative ages. Dense/medium/open scales their initial spacing. Tolerance never
moves established trees. Thirty-six candidate seedling sites are tested for
available light and trunk clearance.

Neighbour crowns attenuate light multiplicatively, with smooth horizontal edges
and height dependence. Crown openness controls attenuation; tolerance controls
the recipient's response. Eight crown-edge samples provide a directional light
field and contrast-weighted growth vector. Uniform shade has no direction.
All neighbours are sampled before their responses, avoiding order dependence.

Experimental minimum-light thresholds: low .55, medium .30, high .12, unknown
.35. These are modelling defaults, not measured species coefficients. Branches
turn modestly toward brighter space, extend less and retain fewer leafy shoots
in shade. Upper branches receive a sky-access allowance. Tolerant plants retain
more shaded foliage; they do not prefer darkness. Roots remain independent.

Species Sim → Forest shows a light map, crown footprints, establishment markers
and gold directional indicators. Two equal-scale views compare the centre tree
with itself without neighbours. **S** cycles spacing; **T** cycles authored
tolerance / low / medium / high overrides. Ages stay fixed in this testbed.
Results and surfaces are cached by seed, blueprint, treatments and viewport.
Baked snapshots include an environment digest to prevent shaded/unshaded
products with the same age and seed from overwriting each other.

Directional crown response currently applies to the node-based tree grammar,
including oak. Other growth forms have the stand diagnostics but not equivalent
branch plasticity. Seedlings are establishment markers, not growing individuals.
This is a qualitative single-species experiment, not a calibrated competition,
seasonal mortality, hydrology or photon-transport model.

## Comparison and refinement

The previous Forest View shuffled gallery plants with decorative depth scales;
it calculated no neighbour light. Round one introduced spatial light and growth
response. It exposed saturation above the establishment threshold: medium and
high both retained 810 centre-tree cohorts. Narrow panels also made trees small.

Round two added gradual foliage retention above that threshold and larger,
vertically stacked views at shared scale. Seed 303, nine adults, 36 sites:

| Spacing | Tolerance override | Established | Mean site light | Centre cohorts |
|---|---|---:|---:|---:|
| Dense | Low | 0 | 35.0% | 663 |
| Dense | Medium | 26 | 35.0% | 738 |
| Dense | High | 34 | 35.0% | 777 |
| Open | Low | 29 | 82.6% | 810 |
| Open | Medium | 36 | 82.6% | 810 |
| Open | High | 36 | 82.6% | 810 |

The unshaded centre-tree control has 810 cohorts. Treatments converge in full
sun and separate under shade. Cohorts are represented foliage, not measured
individual leaf counts.

Reproduce: `py -m tools.render_forest_shade_comparison`. Round-one artifacts:
`artifacts/forest_shade_round1/`; final panels and six-case comparison:
`artifacts/forest_shade_final/`. `results.json` records positions, light,
environment and cohort counts. Images are **renderer previews**, not live app
screenshots. Live navigation has not been verified.

Tests cover ancestry cycles/disconnection, repository rebuild/reparent refresh,
light bounds, treatment direction, deterministic geometry, sockets, portable
modules, canonical LOD quantities, environment cache separation and controls.
The image-loader test passed outside the sandbox because Windows temporary
directory permissions prevented it running inside the restricted filesystem.
Final targeted regression run: **124 passed, 28 subtests passed**. Python
compilation passed. The oak asset was verified as 32 × 32 with binary alpha.

## References and limits

[USFS crown condition and light](https://research.fs.usda.gov/treesearch/29267),
[primary crown-plasticity research](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2014.00275/full)
and [USFS regeneration across light environments](https://research.fs.usda.gov/treesearch/53625)
motivate the mechanisms. They do not validate the chosen thresholds, crown
envelopes, stand layout or oak age curve. Those require further calibration.

Reusable process: installed skill `index0-data-field-development`; versioned
source `docs/skills/index0-data-field-development/SKILL.md`.
