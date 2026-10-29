# Species Sim tree architecture: birch, oak and horse chestnut

## Scope

This pass deliberately excludes day/night, seasonal forcing, precipitation,
soil-water balance and world-generation state. It models intrinsic woody growth
patterns that can be evaluated before those environment systems exist.

The live persistent ontology quadstore, read through
`PersistentOntologyStore(...).load_datasets()`, was the data authority. Its
decoded projection contained fully authored silver birch and English oak rows,
but the horse-chestnut row contained identity and ancestry only.

## Diagnosis and baseline

Birch and oak both selected `tree + branched_woody`, both carried long/short
shoot data, and both entered `grow_tree_shoots`. The generator varied droop,
openness, spacing and twig density, but it did not have terms for how successive
axes are constructed. The trees therefore shared one topology with different
proportions. Horse chestnut lacked all plant fields and fell through the old
generic tree defaults at one metre tall.

The fixed baseline is seed 303, LOD 2, authored maturity and shared physical
scale:

| Species | Height | Footprint x/y | Branch sections | Leaf cohorts | Architecture fields |
|---|---:|---:|---:|---:|---|
| Silver birch | 27.0 m | 15.5 / 14.9 m | 1,496 | 660 | unset |
| English oak | 38.0 m | 27.9 / 28.4 m | 2,587 | 1,170 | unset |
| Horse chestnut | 1.0 m | 0.3 / 0.3 m | 8 | 13 | unset |

`branch sections` is generator instrumentation, not a claim about the number of
botanical branches on a real mature tree.

## Architecture vocabulary

The new fields follow the observable axes used in plant-architecture research:

- `plant_axis_continuity`: monopodial, sympodial, monopodial-to-sympodial, or mixed.
- `plant_branching_rhythm`: rhythmic, continuous, or diffuse.
- `plant_branching_timing`: immediate/sylleptic, delayed/proleptic, or mixed.
- `plant_lateral_axis_orientation`: orthotropic, plagiotropic, or mixed.
- `plant_flowering_position`: lateral, terminal, or mixed.
- `plant_apical_control`: a 0..1 continuous expression range.

The continuous architecture controls (`plant_apical_control`, leaf spacing,
branch droop, branch-angle gradient, crown openness, leaf-depth gradient,
fine-twig density and leaf-cluster density) now store `min / typical / max`
envelopes rather than unexplained fixed values. The grammar consumes the
typical value. These are explicitly provisional visual-calibration ranges;
their exact normalized endpoints are not presented as direct botanical
measurements.

These dimensions come from the architectural synthesis of Barthélémy and
Caraglio: determinacy, monopodial/sympodial construction, branching rhythm and
timing, axis orientation, and flowering position are separate observations.
See [Plant Architecture: A Dynamic, Multilevel and Comprehensive Approach](https://pmc.ncbi.nlm.nih.gov/articles/PMC2802949/).

## Three authored profiles

### Silver birch — *Betula pendula*

The birch profile is sympodial, diffusely branched, mixed sylleptic/proleptic,
and plagiotropic with strong apical control. Existing long/short-shoot and high
droop values remain active. The generator now leaves a small zig-zag history in
the leader, scatters branch insertion and retains a narrow, open, fine crown.
The long/short-shoot and ramification basis is supported by
[Kull et al.'s crown-structure study](https://pmc.ncbi.nlm.nih.gov/articles/PMC4242242/).

### English oak — *Quercus robur*

The oak profile is monopodial and indeterminate, continuously branched, delayed
and plagiotropic, with lower apical control. It therefore develops fewer
suppressed laterals and broader persistent scaffold axes. A LiDAR/architectural
comparison reports this same monopodial, indeterminate trunk and continuous,
plagiotropic branching habit for *Q. robur*: [Recruiting Conventional Tree
Architecture Models into State-of-the-Art LiDAR Mapping](https://pmc.ncbi.nlm.nih.gov/articles/PMC5826307/).

### Horse chestnut — *Aesculus hippocastanum*

Horse chestnut is the third case because it changes construction during
ontogeny. Its authored row is now a large deciduous tree with opposite,
palmately compound leaves, paired rhythmic branching, mixed lateral-axis
orientation and terminal flowering. The leader is monopodial when juvenile;
at reproductive maturity, terminal inflorescences end extension and lateral
buds continue sympodially. The generator expresses this as opposite branch
pairs on repeated tiers and upper-crown successor axes, with large terminal
foliage cohorts. This transition is described in the [Biological Flora of the
British Isles account](https://besjournals.onlinelibrary.wiley.com/doi/10.1111/1365-2745.13116)
and in [Prenner et al.'s ontogenetic treatment of inflorescence diversity](https://pmc.ncbi.nlm.nih.gov/articles/PMC3828942/).

## Acceptance criteria and result

The change is accepted when:

1. The same seed and maturity produce deterministic snapshots.
2. The three species have visibly different front and top-down topology at a
   shared physical scale.
3. Horse-chestnut primary branches occur in opposite pairs on rhythmic tiers.
4. The authored architecture fields survive ontology → blueprint → snapshot.
5. Existing foliage-cohort, LOD and root tests remain green.
6. A permanent Species Sim diagnostic exposes the comparison.

All six criteria pass. Final fixed-seed measurements are:

| Species | Height | Footprint x/y | Branch sections | Leaf cohorts | Structural axis length |
|---|---:|---:|---:|---:|---:|
| Silver birch | 25.4 m | 13.6 / 13.8 m | 1,496 | 660 | 467.7 m |
| English oak | 34.9 m | 26.9 / 25.8 m | 2,080 | 936 | 793.4 m |
| Horse chestnut | 33.7 m | 20.8 / 18.4 m | 504 | 96 | 357.2 m |

The permanent **Tree Patterns** tab renders front and top-down rows from the
same snapshots and uses one physical scale across all three columns. The
reproducible artifact command is:

`py -m tools.render_tree_architecture_comparison --output artifacts/tree_architecture_v001/final`

## Current limits

This is a topology and diagnostic-fidelity pass, not an empirically calibrated
growth model. Crown damage, reiteration after injury, crown plasticity under
competition, age-dependent branch shedding and measured allometry are not yet
represented. The architecture fields are stable enough to extend those systems
later without coupling them to unfinished climate or water simulations.
