# Plant species research and field-assignment instruction

Use the following instruction in the web-based research interface. It is self-contained: the interface does not need to know Index 0 or its codebase.

---

I will give you the scientific or common name of one plant species. Research that species and help me fill its Index 0 plant fields manually.

## Working method

1. Confirm the accepted scientific name and the intended taxon. Mention important synonyms or taxonomic ambiguity before assigning fields.
2. Research the species using reliable botanical sources. Prefer primary literature, taxonomic authorities, national or university floras, botanical gardens, forestry/agricultural agencies, and curated trait databases. Cross-check claims where practical.
3. Report intrinsic species traits, not the conditions at one observation site. If a trait varies by population, age, season, cultivar, or environment, say so.
4. Never guess merely to complete the form. Use **Other / unknown** where that is an available choice; otherwise report **Leave blank — insufficient evidence**. Distinguish a directly sourced value from a cautious inference.
5. For every assignment, give the exact field name, the exact selectable label shown below, a one-sentence reason, confidence (**high**, **medium**, or **low**), and one or more source links. Do not invent new dropdown labels.
6. Keep the final answer optimized for manual entry. Start with a compact table of dropdown assignments in the same order as the field catalogue below. Then give optional non-dropdown values, unresolved or conflicting fields, and sources.

## Dropdown field catalogue

The label before the colon is the field name. The text after it explains what the field represents. **Allowed values** are the only labels I can select.

Exact internal keys, in the same order as the catalogue: `plant_growth_form`, `plant_growth_behaviour`, `plant_lifespan`, `plant_life_form`, `plant_woodiness`, `mature_height_class`, `growth_rate`, `maturity_rate`, `longevity_class`, `leaf_phenology`, `leaf_size_class`, `leaf_structure`, `leaf_arrangement`, `leaf_attachment_pattern`, `leaf_clustering`, `plant_shoot_dimorphism`, `plant_leaf_distribution`, `photosynthesis_pathway`, `root_architecture`, `root_depth_class`, `reproductive_mode`, `seed_size_class`, `clonal_spread`, `resprouting`, `regeneration_strategy`, `nitrogen_fixation`, `nutrition_mode`, `mycorrhizal_type`, `shade_tolerance`, `moisture_preference`, `waterlogging_tolerance`, `salinity_tolerance`.

### Primary form and life history

- **Plant Growth Form**: the broad botanical body plan, independent of detailed shoot architecture. Allowed values: **Tree; Shrub; Subshrub; Forb; Graminoid; Vine; Fern; Moss; Succulent; Aquatic; Other / unknown**.
- **Plant Growth Behaviour**: the primary modular architecture or spread grammar. Choose the closest dominant strategy; several may be biologically present, but this field takes one. Allowed values: **Iterative / indeterminate shoot; Unbranched / single axis; Determinate / sympodial shoot; Rosette / short-internode; Branched woody architecture; Climbing / twining / scrambling; Creeping / prostrate; Tussock / tillering; Rhizomatous clonal spread; Stoloniferous / runner spread; Suckering / basal clonal spread; Fern / fronding; Basal succulent rosette; Moss mat**.
- **Plant Lifespan**: normal life-cycle duration. Allowed values: **Ephemeral; Annual; Biennial; Short-lived perennial; Perennial**.
- **Plant Life Form**: Raunkiær-style position/protection of renewal buds during the adverse season. **Therophyte** survives chiefly as seed; **Hemicryptophyte** has buds at the soil surface; **Geophyte** has protected below-ground buds; **Chamaephyte** has low buds close above ground; **Phanerophyte** has exposed perennial buds well above ground; **Hydrophyte** has submerged or aquatic overwintering organs. Allowed values: **Therophyte; Hemicryptophyte; Geophyte; Chamaephyte; Phanerophyte; Hydrophyte; Other / unknown**.
- **Woodiness**: whether persistent lignified support tissue defines the plant. Allowed values: **Woody; Herbaceous; Other / unknown**.
- **Mature Height Class**: a relative stature category for the mature plant. Use the species' normal mature stature and growth form; the program defines no hard numerical thresholds. Allowed values: **Dwarf; Low; Medium; Tall; Canopy; Emergent; Other / unknown**.
- **Growth Rate**: relative rate of biomass or structural growth under suitable conditions, not time to first reproduction. Allowed values: **Slow; Moderate; Fast; Other / unknown**.
- **Maturity Rate**: relative speed at which an individual reaches reproductive maturity. Allowed values: **Rapid; Fast; Moderate; Slow; Other / unknown**.
- **Longevity Class**: relative expected individual lifespan within its broad plant context. The program defines no hard year thresholds, so explain the evidence used. Allowed values: **Very short; Short; Moderate; Long; Very long; Other / unknown**.

### Leaves and shoots

- **Leaf Phenology**: seasonal persistence or shedding of leaves. **Marcescent** means dead leaves are retained for a time. Allowed values: **Evergreen; Deciduous; Semi-deciduous; Drought-deciduous; Marcescent; Other / unknown**.
- **Leaf Size Class**: relative size of a typical mature photosynthetic leaf or equivalent organ. The program defines no fixed area thresholds. Allowed values: **Very small; Small; Medium; Large; Very large; Other / unknown**.
- **Leaf Structure**: gross organization of the leaf. Allowed values: **Simple; Pinnately compound; Palmately compound; Scale-like; Needle-like; Frond-like; Other / unknown**.
- **Leaf Arrangement**: phyllotactic placement at nodes or along the axis. **Distichous** means arranged in two ranks; **fascicled** means borne in bundles. Allowed values: **Alternate; Opposite; Whorled; Basal; Distichous; Spiral; Fascicled; Other / unknown**.
- **Leaf Attachment**: where foliage is concentrated on the plant architecture. Allowed values: **Along stem; Terminal cluster; Basal rosette; Branch tips; Mixed; Other / unknown**.
- **Leaf Clustering**: local grouping pattern of leaves. Allowed values: **Solitary; Paired; Tufted; Rosette; Dense cluster; Distributed; Other / unknown**.
- **Shoot Dimorphism**: whether one shoot system serves all roles or distinct long and short shoots occur. Allowed values: **Single shoot system; Long and short shoots; Other / unknown**.
- **Leaf Distribution**: simulation-facing distribution of foliage over shoots. Allowed values: **Along shoot; Mixed long / short shoots; Terminal cluster; Basal rosette; Other / unknown**.

### Physiology, roots, and reproduction

- **Photosynthesis Pathway**: dominant carbon-fixation pathway. Allowed values: **C3; C4; CAM; Other / unknown**.
- **Root Architecture**: dominant root-system organization. **Adventitious** roots arise from stems or other non-radicle organs; **mixed** combines major strategies. Allowed values: **Taproot; Fibrous; Adventitious; Mixed; Other / unknown**.
- **Root Depth Class**: relative depth of the effective root system. Use typical established plants and acknowledge strong soil dependence. Allowed values: **Shallow; Intermediate; Deep; Other / unknown**.
- **Reproductive Mode**: whether reproduction is sexual, vegetative/clonal, both, or apomictic (seed without normal fertilization). Allowed values: **Sexual; Vegetative; Both; Apomictic; Other / unknown**.
- **Seed Size Class**: relative size of the seed or principal sexual propagule. The program defines no fixed mass thresholds. Allowed values: **Tiny; Small; Medium; Large; Very large; Other / unknown**.
- **Clonal Spread**: importance/intensity of spatial spread by connected or vegetative ramets. Allowed values: **None; Low; Moderate; High; Other / unknown**.
- **Resprouting**: capacity to regenerate shoots after damage from surviving stems, roots, lignotubers, crowns, or other protected tissue. Allowed values: **Absent; Weak; Moderate; Strong; Other / unknown**.
- **Regeneration Strategy**: dominant establishment or recovery route. Allowed values: **Seed bank; Vegetative recruitment; Resprouting; Disturbance colonization; Gap recruitment; Mixed; Other / unknown**.

### Nutrition, symbiosis, and environment

- **Nitrogen Fixation**: relationship to biological nitrogen fixation. **Associated / facultative** means a non-obligate association; **Active / capable** means the plant forms or maintains a functional fixing symbiosis. Allowed values: **None; Associated / facultative; Active / capable; Other / unknown**.
- **Nutrition Mode**: principal way the plant obtains carbon and mineral nutrition. Allowed values: **Autotrophic; Parasitic; Hemiparasitic; Mycoheterotrophic; Carnivorous; Mixotrophic; Other / unknown**.
- **Mycorrhizal Type**: dominant documented root–fungus association. Allowed values: **None; Arbuscular; Ectomycorrhizal; Ericoid; Orchid; Mixed; Other / unknown**.
- **Shade Tolerance**: ability of an established plant to persist and function under low light; do not confuse it with shade preference. Allowed values: **Low; Medium; High; Other / unknown**.
- **Moisture Preference**: typical moisture regime in which the species performs well. **Mesic** means moderately and reliably moist, neither dry nor saturated. Allowed values: **Very dry; Dry; Mesic; Moist; Wet; Aquatic; Other / unknown**.
- **Waterlogging Tolerance**: ability to survive prolonged saturated, oxygen-poor soil. Allowed values: **Low; Medium; High; Other / unknown**.
- **Salinity Tolerance**: ability to tolerate saline soil or water. Allowed values: **Low; Medium; High; Other / unknown**.

## Optional non-dropdown fields

Report these after the dropdown table only when sources support them. These fields do not have a closed list of allowed values.

- **Mature Height** (`mature_height`): normal mature height range as `min_m` and `max_m`, in metres; for example `{ "min_m": 0.4, "max_m": 1.0 }`.
- **Maximum Root Depth** (`max_root_depth`): documented maximum or defensible range in metres. State whether the number is typical or exceptional; use an object such as `{ "max_m": 2.0 }` or a sourced min/max range if the editor permits it.
- **Temperature Range** (`temperature_range`): supported physiological or survival range in degrees Celsius, not simply the climate of the native distribution; use explicit keys and explain their meaning.
- **Frost Tolerance** (`frost_tolerance`): documented lower-temperature tolerance in degrees Celsius, for example `{ "min_c": -20 }`.
- **Soil pH Range** (`soil_ph_range`): supported pH range, for example `{ "min": 5.0, "max": 7.5 }`.
- **Succulence** (`succulence`): open list naming water-storing organs, such as `leaf`, `stem`, or `root`; leave blank if the species is not meaningfully succulent or evidence is absent.
- **Below-ground Storage** (`belowground_storage`): open list of storage organs, such as `rhizome`, `tuber`, `bulb`, `corm`, `storage_root`, or `lignotuber`.
- **Pollination** (`pollination`): open list of pollination vectors or mechanisms, such as `wind`, `water`, `bee`, `moth`, `bird`, `bat`, `generalist_insect`, or `self_pollination`. Use only documented terms.
- **Dispersal** (`dispersal`): open list of propagule dispersal vectors or mechanisms, such as `wind`, `water`, `gravity`, `animal_external`, `animal_ingestion`, `ballistic`, or `human`.

### Normalized architecture refinements

These are optional simulation-facing values from **0.0 to 1.0**, not standardized botanical measurements. Suggest one only when morphology is well documented or clear in representative photographs. Treat **0.0** as little/none of the named tendency and **1.0** as very strong/high. Mark every value as an interpretive estimate, not a measured constant.

- **Leaf Spacing Bias** (`plant_leaf_spacing_bias`): strength/extent of leaf spacing or repeated placement along shoots.
- **Branch Droop** (`plant_branch_droop`): degree to which branches or fine axes hang downward.
- **Branch Angle Gradient** (`plant_branch_angle_gradient`): strength of systematic change in branch angle from lower to upper crown.
- **Crown Openness** (`plant_crown_openness`): openness and spacing of the crown rather than compact canopy density.
- **Leaf Depth Gradient** (`plant_leaf_depth_gradient`): strength of change in foliage placement from outer/upper to inner/lower crown regions.
- **Fine Twig Density** (`plant_fine_twig_density`): relative abundance of fine terminal twigs.
- **Leaf Cluster Density** (`plant_leaf_cluster_density`): density of leaves within local simulated foliage clusters.

### Technical asset fields

Do not research or assign these during biological data entry. They are authored inside the project and accept asset paths or editor-generated anchor objects: `plant_leaf_module_ref`, `plant_root_module_ref`, `plant_stem_module_ref`, `plant_branch_module_ref`, `plant_flower_module_ref`, `plant_fruit_module_ref`, and `plant_module_anchors`.

## Required answer format

Use this exact structure:

1. **Taxon check** — accepted name, common name, family, important synonyms, and ambiguity notes.
2. **Dropdown assignments** — a table with columns: `Field | Exact selection | Reason | Confidence | Sources`. Include every dropdown field. Use **Other / unknown** when available and evidence is insufficient.
3. **Optional researched values** — a table with columns: `Field | Proposed value and units | Evidence/qualification | Confidence | Sources`. Omit technical asset fields.
4. **Conflicts and blanks** — list uncertain, variable, or contradictory traits and say what evidence would resolve them.
5. **Possible distinctive mechanism (suggestion only)** — only if the species has a well-documented mechanism or behaviour that is genuinely distinctive and not already represented well by the fields. In at most one short paragraph, state:
   - what the mechanism is;
   - what it biologically entails (trigger, relevant organs/process, resource trade-off, and ecological consequence);
   - one high-level sentence on what a future simulation could represent.
   Do **not** write an implementation plan, invent parameters, or claim the mechanism is unique without evidence. If nothing strong is found, say **No additional mechanism suggested**.
6. **Sources** — a deduplicated list of links, naming the source organization or publication.

Wait for me to provide the plant species before beginning the research.

---

Schema note: this instruction covers all active fields in the project's `Simulation / Plant Ecology` species section. It deliberately excludes generic species fields for animals and project-internal visual asset authoring from the biological assignment workflow.
