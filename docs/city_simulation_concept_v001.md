# City Simulation Concept v001

Status: concept in discussion, 2026-10-01. Slice 0 is implemented (§7);
nothing else is. §2 records decisions taken with the project owner; §3 is an
audit of what the codebase already provides; §4–§6 are proposals built on
that audit.

## 1. Goal

An Ostriv-like settlement game inside Index0. The player picks a point on a
generated world, receives a start scenario derived from that point's context,
and grows a town: placing blueprints, watching residents haul, build, farm and
raise families. The town is a viewpoint over shared ontology facts, not a
separate game world.

Target stack, as stated by the owner:

```
Map Sim -> Bioregion Sim -> City Sim -> Person / Pop / Market
```

## 2. Decisions taken

| Topic | Decision |
|---|---|
| Player role | Overseer first (place, prioritise). Drop-in to a person comes later. |
| Job assignment | Pawns choose their own jobs from open vacancies. Player may pin or forbid. |
| Population | Two tiers. A minimum of ontology persons run the full Person sim. Everyone else is a persistent **light resident**: family ties, randomised traits, a home, a workplace, abstract demand baskets (Victoria 3 style). |
| Start scenario | Derived from the chosen point's context, then editable before starting. |
| Construction | Bill of materials from the blueprint; materials hauled to the site; builders raise it in visible stages. |
| Economy | No economy-mode field for now. A city has exactly one market, the internal one; its state is the aggregate of city production and consumption. Further modes arrive with the market system. |
| Pawn presence | Every resident is always a walking pawn with simple routines and real hauling. |
| First kit | Era-agnostic framework gated by known technologies; first content is low-tech (timber, clay, thatch, farming). |
| Pressures in v1 | Food. Births, ageing, death. No seasons, no migration, no trade yet. |
| Persistence | City run file plus an ontology summary, written only on explicit save. |
| Calendar | True 365-day year with fast-forward. |
| First site | A new generated planet, `City_World_Test`, refined down the LODs by the owner to a suitable spot. |
| Food | Fields with an assigned species, evaluated by representative Species Sims; preferably a bio layer running underneath the whole city. |
| Bio layer | "Bioregion Sim" means the Biosphere kernel (§3.3). |
| World state | Living. Resident vegetation comes from plant species that are already implemented. Topsoil only as far as the sim needs it; no separate soil concept. |
| Town footprint | LOD4 by default, not a commitment: the founding bridge accepts a refined region of any LOD between 100 m and 30 km. |

## 3. What already exists

### 3.1 World generation

| Fact | Where |
|---|---|
| Eight LODs, Planet to Survey. LOD4 "Site" is 0.5–5 km at about 7.5 m per sample; LOD5 "Parcel" is 100–500 m at about 1 m. | `regional_refinement.DETAIL_LEVELS`, `docs/LOD_Worldgen_Procedure.md` §2 |
| Each refinement is a `generated_region` location entity carrying height, water cycle, drainage, coast, materials, soil, True Color and material-occurrence cards. | `regional_refinement.generate_refined_region` |
| Children are parent surface plus a bounded residual; rivers, channels and fans are inherited by stored geometry. | `docs/worldgen_lod_mechanism_matrix_v001.md` |
| Soil model gives depth, pH, moisture, salinity, porosity, parent N and P. It deliberately excludes organic matter and fertility. | `regolith_soils.py` |
| Climate grid stores annual temperature, annual precipitation and a seasonality index. Twelve monthly normals are computed for Köppen classification but not persisted. | `water_cycle._monthly_climate_normals` |
| Refinement takes roughly 80–130 s per level. | LOD procedure §6 |

Consequences for the city sim:

- LOD4 is the natural town footprint. LOD5 children can add building-scale
  relief where wanted.
- Clay, stone and ore come from `material_heatmap_model` and
  `regional_material_occurrences`. The concept doc already names a Material
  Affordance Resolver for exactly this (§19); it is not built.
- A generated world is **abiotic by rule**. There are no trees and no
  topsoil until a Biosphere is established on it.
- Seasons could later be derived from the monthly-normal function that
  already exists, without new climate physics.

### 3.2 Map simulation

| Capability | Where |
|---|---|
| Drill-down: "Refine View to <Level>" on the visible window creates the next LOD child. | `MapSimulation.regenerate_visible_region` |
| Layers: height, True Color, materials, hydrology, coast, climate, contours. | `_build_layers`, `get_available_layer_kinds` |
| Drafting: point locations, squares, polygons, polylines, parent placement. | `begin_point_location_draft`, polygon editor |
| Blueprint ghost placement with rotation. | `begin_blueprint_placement`, `blueprint_placement.py` |
| Biosphere patch drafts and launch context. | `begin_biosphere_patch_draft`, `get_biosphere_launch_context` |
| Read-only physical sampler over a map's models. | `WorldgenSubstrate` |
| Subclass precedent: Building and Biosphere sims both extend `MapSimulation`. | `building_sim.py`, `biosphere_simulation.py` |

**The main gap.** Blueprint placement and Biosphere surface import both
require `map_coordinate_space: site_meters` with metre bounds. A
`generated_region` stores its bounds in its parent map's frame and its
physical size separately (`heightmap_model.region_width_m`). Only two maps
have real terrain in a metre frame today: `highest_lod_example_map` (real
survey data) and `highest_lod_generated_example_map`, which is a hand-built
one-off bridge (`generated_landscape_artifact.py`). There is no general way
to stand on a refined region in metres.

### 3.3 Bio layer

Two packages exist and the names are easy to confuse.

| Package | What it is |
|---|---|
| `simulations/biosphere/` | Live. `BiosphereSimulation(MapSimulation)`, self-described as a "map-native biological city builder". Species introductions, population patches, soil organic-matter succession, and 3–4 representative Species Sims per population advanced once per season. Reads `WorldgenSubstrate`. |
| `simulations/bioregion/` | Older grid prototype (weather, vertical water cycle, aggregate biomass). Has tests and a render mode, but `launch_bioregion_test_tab` actually opens the Biosphere builder. |

The owner's "Bioregion Sim" layer is therefore read as the Biosphere kernel:
`BiosphereEcology`, `SoilOrganicMatterField`, `RepresentativePopulationManager`.
Those three are separable from the builder's UI. Missing for farming: a
harvest output. Representatives report vitality, fecundity and mortality, not
a harvestable mass.

### 3.4 Buildings

Blueprint Designer, versioning, placement, lazy rooms and material textures
are shipped (`docs/building_blueprint_concept_v001.md` §8). `derive_geometry`
already returns every surface with its role, material and dimensions, which
is what a bill of materials needs. Six construction materials exist, all
industrial (softwood timber, brick, concrete, plaster, roof tile, steel
sheet). Placement is instant; construction as a process was explicitly
deferred.

### 3.5 People, pops, production, markets

| Piece | State |
|---|---|
| Person sim | Needs, task queue, inspectable task scoring (personality, job criticality, employer discipline, convictions), knowledge-bounded pathing on a 1 m grid, inventories, ownership-gated access. |
| Site sim | Authored persons as full agents; pops projected as a few representatives plus an aggregate; lightweight presences promoted on interaction and staged until Save. This is already the two-tier idea. It carries 27 lumber-specific references and runs in real-time seconds. |
| Production | Recipes, producers with inline production lines, jobs, employment and ownership are ontology entity families. Only the kitchen recipe executes. `RequirementResolver` reports job availability from technologies and site conditions. |
| Pops | Location, cultural and employment pops with static demographics. `update()` is an empty placeholder. |
| Markets | Runtime records for supply, demand, allocation and transactions, with aggregate and corporal modes. Not wired to anything. |
| Doctrine | Ownership and exchange doctrine exist as free text on **jobs** only. Factions and settlements have no economy field. |
| Runtime persistence | None. Worldgen has `.i0wg` bundles and a storage policy that a city run file can follow. |

## 4. Proposed architecture

```
generated_region (LOD4, abiotic, immutable)
   |  terrain source
city location (site_meters, metre bounds)      <- ontology: durable facts
   |-- placed buildings (location entities)
   |-- ontology persons
   |-- summary pop
   `-- city run file (assets/cities/<id>.run)  <- runtime: saved on request

CitySimulation(MapSimulation)
   |-- substrate      WorldgenSubstrate over the source region
   |-- bio layer      BiosphereEcology + soil + representatives
   |-- calendar       day clock, speeds, abstract fast-forward
   |-- stocks         per-building item quantities
   |-- construction   building sites, bill of materials, stages
   |-- residents      households and light residents, path graph
   |-- vacancies      jobs offered by buildings, self-assignment scoring
   `-- full persons   PersonSimulation agents for ontology persons
```

Points that follow from the audit:

- **City entity over the region, not on it.** The city is a `site_meters`
  location that names the generated region as its terrain source. The region
  stays regenerable and the abiotic rule is untouched.
- **Light residents live in the run file.** They become ontology persons only
  on promotion, staged until Save, as the Site sim already does.
- **Light pawns need a path graph.** A 3 km town is nine million cells on the
  person sim's 1 m grid. Roads and footpaths as a graph for light pawns; the
  1 m grid stays for full persons near buildings.
- **One clock.** Days are the base unit. The bio layer steps every 91 days.
  Fast-forward drops pawn movement and resolves hauling and consumption as
  daily flows.
- **Demand baskets reuse market records.** A household's daily basket is an
  aggregate `DemandRecord`; stocks are `SupplySnapshot`s. No prices in
  communal mode.

## 5. Proposed slices

| # | Slice | Proves |
|---|---|---|
| 0 | Metre-frame bridge: found a city over a LOD4 region, sample the substrate, place a blueprint on it | The owner's generated spot is buildable |
| 1 | Calendar, stocks, run-file save and load | A town persists |
| 2 | Construction: bill of materials, building sites, haulers, builders, stages; low-tech materials and items | The core Ostriv loop |
| 3 | Households and light residents, homes, vacancies, self-assignment, food baskets, starvation | A living population |
| 4 | Bio layer and fields: species on a field polygon, representatives, harvest; forestry from tree patches | Food and timber from the land |
| 5 | Demography: ageing, pairing, births, deaths, inheritance; summary pop | Years matter |
| 6 | Start scenario derivation and editor | The intended opening |
| 7 | Ontology persons as full agents in the city; drop-in | The second tier |
| 8 | Abstract fast-forward | Generations in a sitting |

Later: wages mode, trade, migration, seasons, the Material Affordance
Resolver as a general service.

Each slice that touches entity data also updates the matching
`tools/author_*.py` schema definitions.

## 6. Open questions

1. Harvest: which species fields say what part is edible and how much of
   the plant it is?
2. Vegetation establishment: which implemented species are residents of
   which ground, and how dense, before the settlers arrive?
3. LOD5 patch colour. A patch is visibly darker than the LOD4 ground it
   sits in, so patches show as rectangles in the city overview. This is True
   Color lineage drift between levels (worldgen), not compositing.
4. Patch coverage. A 300 x 170 m parcel takes about 80 s to refine; a 3 x 1.7 km town
   is about a hundred of them. Refine on demand where buildings go, in the
   background, or accept LOD4 ground outside the built-up area?
5. Placement rules beyond open water: slope, flood-prone ground, overlap
   with other buildings.

## 7. Implementation status

### 7.1 Slice 0 — metre-frame bridge (2026-10-01)

| Piece | File |
|---|---|
| Founding, terrain link, staleness check, substrate | `simulations/city/city_site.py` |
| Map sim reads terrain through `terrain_source_map_id` | `MapSimulation._own_generated_region` |
| Sidebar action on a refined region's map | `MapSimulation.get_city_founding_action`, `found_city` |
| "Found City Here" in the sidebar's TERRAIN section | `ui/ui_manager.py` |
| `found_city` action opens the city map | `app/navigation_controller.py` |
| Schema fields on `locations` | `tools/author_city_simulation_model.py` (applied 2026-10-01) |
| Tests | `tests/test_city_site.py` |

How it works:

- Open a refined region in Map. The sidebar shows **Found City Here**, or
  the reason it is unavailable. Founding creates a `location_class: city`
  location with `map_coordinate_space: site_meters` and bounds of
  `0..width_m` by `0..height_m`, then opens its map. If a city already
  stands on the region the button reopens it.
- The city stores `terrain_source_map_id` and no terrain models. The Map
  sim resolves relief, True Color, materials and hydrology from the region
  through the same path it uses for a location's own generated child.
- `city_substrate()` gives elevation, climate, water and soil at a metre
  position, for placement and later for the bio layer.
- Because the city is in site metres, the Blueprint Designer's **Place on
  Map** lists it and placement works unchanged.

Decisions taken while implementing:

- A city has no `parent_location`. The existing metre-frame sites have none
  either; a parent map would draw the metre bounds in its own frame. The
  region link is `terrain_source_map_id`; parent maps draw the city from
  `geographic_source_bounds` (§7.2).
- The city covers the whole region. A sub-window crop is not built.
- `terrain_is_stale()` compares the region's heightfield fingerprint with
  the one stored at founding. Nothing acts on it yet.

Found while verifying against real regions:

- `refined_lod4_55e6219abf` stores its elevation as a `__grid_bundle__`
  reference to `assets/maps/terrain_grids/*.i0g`. No current code reads that
  format and the file is gone, so the region has no usable terrain and
  founding is correctly refused. Regions generated by current code store
  rows inline.
- Older regions carry no soil or runoff grids; the substrate then reports
  defaults and lists them in `runtime_default_fields`.

Verification render: `artifacts/city_simulation/slice0_city_site_check.png`
(region `refined_lod3_8da8cd008c`, 6 km, founded in memory; the live
ontology was not written).

### 7.2 Slice 0b — parent maps, LOD5 patches, first prototype (2026-10-01)

Built by walking the real application; the process and every obstacle met
are in [City_Prototype_Creation_Process.md](City_Prototype_Creation_Process.md).

| Piece | Where |
|---|---|
| City marker and footprint outline on its region's map and every ancestor up to the planet; listed in the location tree and browser | `MapSimulation._terrain_linked_locations`, `_build_terrain_linked_location_layers` |
| "Up To Parent" and breadcrumb from a city lead to its region | `MapSimulation._navigation_parent_location_id` |
| Refine a parcel from inside the city map; the patch is a child of the source region and the city map stays open | `MapSimulation.regenerate_visible_region`, `_terrain_source_region`, `app/navigation_controller.py` |
| Patches of the source region composited into the city map | `MapSimulation._refined_region_models` |
| Native-resolution patch pass past the whole-map composite's resolution, feathered, cached | `MapRenderer._draw_native_refined_patches` |
| Ground sampler that prefers the finest patch at a point | `city_site.CitySubstrate`, `refined_patches` |
| Placement refuses open water; red ghost and status text | `BlueprintPlacement.ground_problem`, `MapSimulation.get_ground_substrate` |
| App driver and resumable walkthrough | `tools/app_driver.py`, `tools/city_prototype_walkthrough.py` |

Map bugs fixed on the way, both independent of cities:

- A map with terrain of its own treated its first refined child as its own
  surface. The planet map showed its LOD1 patch stretched over the globe.
- Composited child patches were written with zero alpha and scaled to
  screen as black holes.

The prototype: planet `planet_cityworld_prototype`, city
`city_refined_lod4_e7fa59b8b3_01` (3071 x 1727 m, on a river), LOD5 patch
`refined_lod5_0df56ec100` (302 x 170 m, 0.79 m per sample), one barracks on
the patch. Screenshots: `artifacts/city_simulation/prototype_walkthrough.png`
and `lod5_patch_render_check.png`.
