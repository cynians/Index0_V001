# Biosphere on generated terrain, and the terraforming loop

Status 2026-10-02. Two parts: the hookup of the Biosphere builder to world
generation, and the terraforming loop on top of it (the audit, the owner's
decisions, the kernel that implements them, and what is still open).

Related: [builder redesign](biosphere_builder_redesign_v001.md),
[soil succession](biosphere_soil_succession_mwp_v001.md),
[soil nutrients](biosphere_soil_nutrients_species_coupling_v001.md),
[city simulation concept](city_simulation_concept_v001.md).

## 1. Using it

1. Open a refined region at Site level (samples 12 m apart or finer), or a
   city map founded on one.
2. Sidebar, TERRAIN: **Start Biosphere Here**. On coarser maps the button says
   *refine to Site first*.
3. Click dry ground. Open water is refused with a notice; right click or Esc
   cancels.
4. The Biosphere tab opens on that point: barren ground, a 10 m living area,
   only the bootstrap organism plantable.
5. Wheel zooms about the cursor, dragging pans, **Relief ×1/×2/×5** exaggerates
   height for reading the land, **Recentre** returns to the living area.
6. **PLANT** opens the catalogue; the button beside it cycles the seeding
   tool (by hand, or a 5 / 20 / 60 m disc). The ring under the pointer shows
   where a click sows. Time runs at 1x to 64x.

The site is drawn on its region and on every map that region was refined from;
its selection card opens the Biosphere again.

## 2. Model

### Site

`simulations/biosphere/terrain_site.py`. A Biosphere site is a parentless
`site_meters` location (`location_class: biosphere_patch`,
`location_role: biosphere_terrain_site`) laid over one refined region, exactly
like a city:

- `bounds` are the region's physical footprint in metres, so a city and a
  Biosphere over the same region share one frame;
- `terrain_source_map_id` names the region; nothing is copied;
- `biosphere_founding_point_local_m` is where life starts;
- `geographic_source_bounds` is the founding square in the region's own
  coordinates, which is what parent maps draw.

No new ontology fields: all of these already existed for cities and for the
polygon Biosphere flow.

### Ground and climate

`simulations/map/worldgen_substrate.py` gained `LayeredSubstrate`: the region,
overridden by finer refined patches where they exist (finest wins). The city
substrate is now the same class. It answers single points and numpy arrays.

What the ecology reads from the region:

| Biosphere input | Worldgen field |
|---|---|
| elevation, open water | heightfield, `surface_water_grid`. Open water means deeper than 5 cm: worldgen flags every characteristic channel, and a refined chunk in a steppe is 17 % rills that run 4 cm deep after rain. They are ground. |
| soil moisture | `runoff_grid.wetness_index_rows` (climate water balance plus channel and water proximity) |
| temperature | `climate_grid` annual mean and coldest/warmest month normals |
| precipitation, Köppen zone | `climate_grid` (shown to the player; precipitation is not a separate growth term, wetness carries it) |
| soil depth, pH, parent N and P | `regolith_soil_model.grid` |

Species traits that were authored but unused are now consumed:

- `moisture_preference` places a species on the wetness index
  (very_dry 0.08, dry 0.20, mesic 0.42, moist 0.58, wet 0.78, aquatic 0.92)
  unless `biosphere_growth_profile.moisture_optimum` is authored. Qualitative
  placement, labelled as such in `SpeciesProfile.moisture_source`.
- `frost_tolerance.min_c` against the coldest-month normal.
- Every plant shares a generic thermal envelope until it authors its own: no
  growth where the warmest month stays under 5 to 10 °C, heat injury from 38 to
  48 °C monthly mean. Temperature multiplies suitability; it is only judged
  where worldgen resolved the seasons.

Not connected yet: slope and aspect do not change light (generated regions
carry no `surface_solar_exposure`), `soil_ph_range`, `salinity_tolerance`,
`waterlogging_tolerance`, and seasonality (every season is the same).

### Chunks on demand

A Site region resolves the ground every 8 m; a 10 m living area needs more.
`TerrainDetail` lays a fixed lattice of about 128 m chunks over the region and
refines one more level (129 x 129 samples, 1 m) only under the living area.
A chunk costs 12 to 17 s and is an ordinary persisted `generated_region`
child of the region, so a city on the same region uses it too.

In the app the simulation holds its clock, draws one frame with the notice
*Refining ground*, then runs worldgen with a live progress bar. Chunks are
requested under the founding square, and wherever a view closer than 4 px per
metre rests for a second (with a six-second pause between chunks): detail
follows the eye, not every sown hectare. A failed chunk is reported and not
retried.
Chunks meet the region within 2 cm at their edges (worldgen fades child detail
to the parent), so tiles are seamless in height; a refined chunk still reads
rougher than unrefined ground beside it, most visibly with relief exaggerated.

**Looking closely must not change what grows.** Only elevation is faded to
the parent. Every other field of a chunk is re-derived from the chunk's own
models and drifts. Measured on the founding chunk of the prototype site
against the region over the same ground:

| Field | Region | Chunk |
|---|---|---|
| annual mean temperature | 311.0 K | 312.8 K (+1.8 K; coldest and warmest month the same) |
| precipitation | 483 mm (477 to 489) | 434 mm (345 to 826 within 128 m) |
| wetness index | 0.052 | 0.177 (median 0.07, rills 0.49: 17 % of cells are channels, each with a three-cell damp halo) |
| soil depth | 0.63 m | 0.46 m |

With chunks appearing wherever the view rests, a lichen sown where the player
had looked built a quarter more soil than the same lichen beside it, and the
chunk showed as a straight-edged greener tile. The site substrate is therefore
built with two rules (`LayeredSubstrate(..., climate_from_base=True,
conserved_fields=("soil_moisture",))`):

- **The region is the climate.** Temperature (mean, coldest, warmest month),
  precipitation and the Köppen zone are read from the region everywhere.
- **A chunk shows where the region's water sits; it does not add water.** A
  chunk keeps its own wetness pattern, brought to the region's mean over the
  same ground. Its driest ground stays as dry as the chunk found it (that is
  what the climate gives); only the surplus above that, what the chunk puts
  into rills and hollows, is scaled, and never past the top of the range. On
  the founding chunk the ground between rills reads 0.048 and the rills
  0.061, around the region's 0.052: the region has almost no surplus to
  place there. Where the region itself carries a stream through a chunk, the
  chunk's channels take that water. A chunk whose driest ground is already
  wetter than the region's mean reads as the region.
- A field a chunk does not carry is read from the layer beneath it.

A first attempt scaled the whole pattern by one factor. It conserved the mean
but dried the ground between rills to 0.02, below what the climate term of
the index can give, and left the chunk as a browner tile with green veins.

The cause is fixed in world generation as well (parent conservation pass,
2026-10-02, round log of [LOD_Worldgen_Procedure.md](LOD_Worldgen_Procedure.md)):
a refined child now holds its parent's climate, its wetness is measured in
metres and by what a channel carries, and a rill takes no soil. A chunk
refined with that code reads temperature +0.000 K, precipitation -0.00 mm,
wetness 0.165 against 0.165 and soil depth 1.42 m against 1.41 m of its
region. The two substrate rules above stay: they cost nothing on such
chunks and still guard regions and chunks generated before the pass.

Other views (the city) keep plain finest-wins layering. The drift itself is a
worldgen matter and is not fixed here.

**Chunks refined from 2026-10-03 on** (fine-level pass, round log of
[LOD_Worldgen_Procedure.md](LOD_Worldgen_Procedure.md)) differ from the
table above in what they carry, not in how the site reads them:

- wetness and open water are read off the chunk's own ground
  (`simulations/world_gen/fine_hydrology.py`): no rills drawn a cell wide
  with a three-cell halo; open water only in a carved channel, a lake or the
  sea; the ground's share of the climate's water moved from crests into
  hollows, swales and wash floors, and a wet margin beside water by height
  above it;
- soil depth, pH and the other soil fields are the region's over the same
  ground, with depth changed by curvature and by the fills and bars of
  relic channels;
- on a river's plain the chunk has relief of its own: the chutes of the
  relic-channel hierarchy (`floodplain_relics.py`), 7 m wide and up to 0.4 m
  deep on the prototype's plain;
- on layered rock a chunk can hold scarps (`rock_scarps.py`, rock-cliff pass
  of the same day): a rock face has no soil and shows its bed's rock, the
  talus banked against it holds 0.12 m of soil at most in pockets and drains
  freely, the rampart below carries a skin of 0.4 m, and no soil lies on any
  ground steeper than repose. `rock_scarps.heightmap_scarp_fields` gives the
  share of each cell under face, talus and rampart; the site does not read
  it yet. On a rock shore the sea has cut a platform with a cliff behind
  it (`sea_cliffs.py`, sea-cliff pass of 2026-10-05): the cliff carries
  no soil where it stands steeper than repose, but the dry strip of
  platform at its foot is not marked as wave-washed and gets soil and
  plants like level ground. Streams crossing such scarps run in canyons (`scarp_canyons.py`,
  canyon pass of 2026-10-05): a chunk there is a floor a few metres wide
  between walls of the same faces and debris slopes, and a chunk on a wall
  is bare rock from edge to edge.

The two substrate rules stay as they are. Chunks stored before that date
keep the old rasters until they are refined again.

### Isometric ground

`BiosphereBuilderRenderer` meshes the visible window of the heightfield in
screen space and paints it back to front, coloured by each layer's abiotic
true-colour raster (chunk tone matched to the region) and shaded by slope.
The ground under the view centre is the drawing plane, so terrain at 280 m
elevation stays on screen. A resting view is meshed finely once (100 to
200 ms) and reused; while the view moves a coarse mesh is drawn with the
resting picture slid over it, and the fine mesh waits until the view has been
still for a quarter second.

Frame times on the prototype site: about 9 ms at rest, 35 to 45 ms while
panning. Before this pass the builder HUD cost 33 ms per frame at rest because
the catalogue re-walked every soil cell per species per frame.

## 3. The terraforming loop

A new site on generated terrain starts with zero biomass and zero soil organic
matter; only the bootstrap organism can be planted. Everything after that is
built.

### 3.1 The audit that led here

`tools/biosphere_terraforming_playthrough.py` plants the bootstrap organism and
then the best-suited species each time a tier unlocks. Run against the kernel
as it stood on 2026-10-02 morning it showed a tech demo, not a loop: on the hot
prototype site only the lichen survived 40 years; with a mild climate swapped
in the whole ladder was done in 4 years; the living area reached 20 m either
way. The causes, each now addressed (3.2) or still open (3.6):

1. tiers unlocked site-wide from one soil cell;
2. suitability was a weighted mean, so zero water still gave 30 %;
3. pioneers were never displaced;
4. pioneers could not change the site's water or heat;
5. a species was capped at 12 patches that spread centimetres per season;
6. a season cost 0.4 to 0.7 s once trees stood;
7. nothing is saved.

### 3.2 Owner decisions (2026-10-02) and what implements them

| Decision | Implementation |
|---|---|
| Water and soil are hard limits | `BiosphereEcology.suitability_factors`: suitability = min(water, soil organic matter, temperature) x weighted mean(light, nutrients, fertility). Soil is judged where the plant stands. |
| Soil holds water, canopy cools | `moisture_retention_bonus`: organic matter lifts wetness towards 0.45, scaled by rain (full effect at 1000 mm/yr), half reached at 1 kg/m². Since 2026-10-10 the lift is reckoned for the site's ordinary ground (`typical_soil_moisture`, the median wetness of its land) and added everywhere alike: reckoned place by place it brought hollow, bank and rise to the same 0.42 to 0.44 and wiped out what the terrain had spread. **Water pass, same day** (owner: "wetness should work like it does in real life with drainage, precipitation and ground water"): on ground that tells the demand of the air, wetness is no index any more but the year's water balance of the plant asked about (`water_balance.py`, 3.3), and what a soil in the making adds is storage: raw ground keeps 35 % of the water the same ground holds once a soil has formed (`RAW_GROUND_STORAGE_SHARE`). The lift towards 0.45 is left for ground without those figures (hand-built plots, fixtures). `thermal_response`: a closed canopy lowers the warmest-month mean by 6 °C for what grows under it. |
| A plot that grows into the site | Seeding brushes (hand, 5, 20, 60 m), fronts that advance metres a year over ground that would carry the species, founders thrown up to a growth form's reach, discs fused instead of capped, living area up to 4 km, 64x. |
| Local soil plus a longer pioneer line | Soil tiers are local through the hard limit. The longer line needs authored species (3.6). |
| Real life spans where they can be found, generic ones where not (same day, after the refinement pass) | `simulations/species/plant_life_timing.py`: authored `maturity_age` / `longevity` in years, else a figure derived from growth form, `maturity_rate`, `longevity_class` and life cycle; the Biosphere maps real age onto Species Sim's developmental clock (3.3a). |

### 3.3 The kernel now

**Limits.** Water has two limits (`moisture_response`, 2026-10-10, owner:
dry-preferring plants should not be scored "too wet", and a plant's
tolerance of waterlogging and of poorly drained soil should count). Short of
the wetness a species grows best at it lacks water, down to nothing a
tolerance below. Above it more water does no harm while the ground drains:
rain alone brings ground to "fresh" (0.50) at most, and a pine is not hurt
by a soil that never dries. Only water standing in the roots is, by the
species' authored `waterlogging_tolerance` (the classes of Niinemets &
Valladares 2006): *low* bears wetness to 0.55 (a water table about a metre
down) and fails at 0.68 (45 cm); *medium* bears 0.62 and fails at 0.80
(15 cm); *high* bears any ground that is not open water. 28 of the 54 plant
species have it authored; the rest take low, medium or high by the wetness
they grow best at. A wet-ground plant still wants for water on fresh ground.
Soil support is 0 below 45 % of the tier's requirement and 1 at it;
temperature as in section 2; rooting depth (2026-10-10) is 1 where the
ground that can be rooted is at least 40 % as deep as the species roots and
0 below 10 % (`rooting_response`; the depth a species roots to is authored,
or its depth class's, or its growth form's: `rooting_depth_m`; the ground is
the map's `rootable_depth_m`, loose sediment included, else its soil depth:
`rootable_depth_of`). The lowest of the limits caps growth. Light, nutrients (the scarcer of N and P) and fertility
share the rest as a weighted mean (0.22 / 0.18 / 0.08).

*Heat and cold as zones* (2026-10-11, owner: exact limits are hard to find,
so a plant says in general terms what it bears). A species authors the
coldest and the warmest climate zone it grows wild in
(`thermal_range_coldest`, `thermal_range_warmest`; one ordered scale of
seven: frigid, cold, cool, mild, warm, hot, very hot), read off a
distribution map. Each zone stands for three monthly means
(`ecology.THERMAL_ZONE_C`):

| zone | roughly | coldest month it bears | warmest month it needs | warmest month it bears |
|---|---|---|---|---|
| frigid | polar, alpine | -40 | 6 | 12 |
| cold | boreal | -25 | 11 | 18 |
| cool | cool temperate | -10 | 15 | 22 |
| mild | warm temperate | 0 | 18 | 26 |
| warm | subtropical | 8 | 21 | 30 |
| hot | tropical | 15 | 25 | 36 |
| very hot | hot desert | 15 | 28 | 42 |

A plant is unharmed at a figure and gone six degrees beyond it. It takes the
winter it bears and the summer it needs from its coldest zone and the summer
it bears from its warmest, so "cold to very hot" bears a boreal winter and a
desert summer, and "hot" alone neither a cool winter nor a furnace. Exact
figures stand before the zones (`frost_tolerance.min_c` for the winter,
`temperature_range` for the summer); a plant that says nothing keeps the
limits all plants share and no winter limit. The warmth a plant needs is
asked of the open air, as a zone is read off a climate map; a canopy's six
degrees are relief from heat only (before, they also took warmth from what
grew under trees in cool summers). One scale cannot say "cool summers, mild
winters" (an oceanic coast, a tropical mountain): such a plant is placed by
its summers, which overstates the winters it bears until it authors a frost
figure. `tools/backfill_thermal_ranges.py` holds the ranges of the 53
species that were in the catalogue before the field, each with the wild
range it was read off; none was looked up afresh, so all are unverified.
They were written on 2026-10-11 (owner's go-ahead) and are in the
checkpoint; three species are left without (the engineered lichen,
*Diospyros whitei*, *Euphorbia dulcis*).

*Salt* (2026-10-11). Where a map tells whose water the ground water is
(`groundwater_salinity`, the share of sea water at the table, on ground with
sea in sight), the salt in reach of a plant's roots is a limit like water:
`salt_in_reach` counts it as far as the table lies within the roots or the
capillary rise above it, and `salt_response` sets it against the species'
`salinity_tolerance` (*low* bears 5 % sea water and fails at 25 %, *medium*
20 and 55 %, *high* the sea; a plant that says nothing counts as low, as
most of the catalogue does). A lily holds no sea, an oak no ground the tides flood, and a
tree is shut out of a wider band of an arid shore than a herb, because its
roots reach the salt table.

**What the ground hands over.** The climate's rain and the demand of the air
(yearly totals, driest and wettest month, the share of rain that falls in
summer, the coldest and warmest month), and from Site scale down: the depth
to the water table and the water a year brings from upslope or takes
(`fine_hydrology`), what a metre of the ground holds for plants, how high it
lifts water and how deep it can be rooted (`regolith_soils`: a fresh river
bar is 3 m of rootable gravel under a centimetre of soil), and the sunlight
a slope receives (`world_gen/solar_exposure.py`, in the map's
`insolation_grid`: level ground is 1, a 20 degree slope turned from the sun
at 45 degrees latitude 0.78). The generator gives no fertility, on purpose;
the Biosphere lets what life has built count as far as the soil's reaction
and salt allow (`mineral_soil_index`: full between pH 5.5 and 7.5, less by
salinity). Round log: `docs/LOD_Worldgen_Procedure.md`, water pass.

**Wetness is a water balance** (`simulations/biosphere/water_balance.py`,
2026-10-10). How wet a place is depends on who asks. Month by month rain and
run-on meet the demand of the air; what rain does not cover is drawn from
the water the plant's rooted soil holds (texture x rooting depth x how far a
soil has formed), ever harder the emptier it is; a store smaller than a
shower loses the rest of the shower; where the roots or the ground's
capillary rise reach the water table, ground water makes up what is missing.
The share of the year's demand that is met (AET / PET) is read onto the scale
the species' preferences are authored on (0.18 -> very dry 0.08, 0.30 -> dry
0.20, 0.80 -> mesic 0.42, 1.0 -> fresh 0.50). Above "fresh" only a water
table decides, for a plant it reaches: wet within 30 cm, very moist to
60 cm, moist to a metre. So a sand is drier than a loam under the same
rain, a sunny slope drier than a shaded one, raw ground drier than built
soil, a hollow fresher than a nose, and on a gravel bar a metre above the
river the herb stands dry and the tree rooted to the water moist. The kernel
asks it stand by stand (`point_wetness`, 13 microseconds), the solver over
the whole lattice per rooting depth (`plant_wetness`). `soil_moisture` in
the kernel's environment is the wetness for a herb (roots 0.4 m) and is what
the cursor and the crust read; `suitability_factors` returns the plant's
own as `wetness`. Sources and the figures that are this project's reading of
them are in the module's head.

**Ground that does not drain** (2026-10-10). Wetness above "fresh" comes
from a water table, as before, and now also from perched water: what a wet
month leaves over once demand is met and the store is full has to go down
through the subsoil, and where the subsoil passes less than arrives the water
stands in the soil (`water_balance`, from the soil model's
`drainage_rate_rows_mm_per_day`: 1000 mm a day in sand, 100 in a sandy
loam, 10 in a clay loam, 1 in a clay, 1 in a silted channel). The share of
the year it stands is read onto the same scale: a month 0.59, three months
0.67, half the year 0.76. Under 1730 mm of rain a subsoil passing 1 mm a
day stands wet for months; one passing 5 mm a day does not; in a dry
climate no clay waterlogs. Slopes are not in it: a clay hillside drains no
better than a clay flat.

**Floods** (2026-10-10). Beside a carved river the ground tells how often
the river covers it and how often it reworks it, in years
(`world_gen/river_floods.py`). A flood that reworks a surface takes what
grows on it. In a played Biosphere each year from the second has its largest
flood, drawn per site and year (`BiosphereEcology.flood_of_year`: one year
in two at least the two-year flood, one in ten the ten-year flood); it takes
the recorded plants standing on ground reworked at least that often, one by
one, and of a cover the share of its ground that lies that low
(`_river_flood`). What was sown in a year has that year. The field notes say
"The river rose as it does about every 6 years and reworked its low ground:
took 14 English Oak"; the cursor tells "flooded every 2 years, reworked
every 9 years"; the catalogue says "Cannot hold here: the river reworks
this ground about every 3 years, and it takes 40 years to grow up" where
under a fifth of such ground would carry the species full-grown
(`flood_standing_share = exp(-years to grow up / years between floods)`:
floods come without memory).

**Holding.** `BiosphereEcology.expected_cover` is the cover a population
settles at on open ground: where logistic growth balances the stress loss
`(1 - suitability) x 0.075` and a typical mortality of 0.010 per season. A
population holds where that cover is above zero. Fast growers fill poorer
ground than slow ones:

| | holds from | thrives from (cover 60 %) | cover at 60 % suitability |
|---|---|---|---|
| Lichen crust | 13 % | 28 % | 89 % |
| Grass, forb | 24 to 27 % | 45 to 49 % | 73 to 77 % |
| Shrub | 37 % | 62 % | 58 % |
| Tree | 49 % | 74 % | 33 % |

Catalogue verdicts, the sowing warning and the cursor readout all use this
one function, so "would thrive / hold / barely hold / fail" is said in the
species' own terms: 60 % suits a lichen well and a tree barely.

**Soil tiers** (organic matter where the plant stands): herbs 0.15, shrubs
1.0, trees 3.0 kg/m². Gameplay pacing values, in one table in
`soil_succession.py`.

**Amelioration.** A soil in the making holds more of the rain: the store of
the water balance grows from 35 % to all of what the ground holds as organic
matter builds up (half way at 1 kg/m²). On Biosim World's dry site (933 mm
of rain against 1944 mm of demand) a herb's wetness goes from 0.21 on raw
ground to 0.27 on built soil, on its wet site (1732 against 1308 mm) from
0.40 to 0.50. The
gain is smaller than the old lift, and smallest where every month's rain
falls short of demand anyway. Worldgen fields are never modified; the cursor
shows both parts.

**Layers.** A neighbour far below a plant (under a quarter of its height)
competes at 0.15 instead of 0.75; a neighbour standing well above it adds
4 % stress per season. Herbs under closed shrubs die out as "too shaded".

**Spread.** A front advances `4 x dispersal x (0.12 + 0.34 x abundance) x
suitability just beyond the rim` metres per season (rim sampled every fourth
season). Founders land between the rim and the growth form's reach (lichen
6 m, grass 8, forb 10, shrub 12, fern 15, tree 25) where they could hold. A
disc swallowed by a larger one of its species adds its plants to it; beyond
48 discs a species' two nearest are fused, area conserved.

**Sowing.** By hand as before, or over a disc: the stand starts thin
(`0.30 x sqrt(2 / radius)`, at least 0.05) and thickens where it can. The
living area grows to hold what is sown. By hand a click on an organism
inspects it; with a brush the click always sows (stands are full of
organisms) and a right click inspects.

**Wide stands.** A stand wider than 3 m is judged over its ground, not only
at its centre: the mean of the centre and four points at 55 % of its radius
(`_stand_ring`, refreshed with the rim every fourth season and after a
fusion). The stand and its rim are sampled at the height the stand has
reached and without its own crowns shading it. A 20 m sowing whose centre
lands in a damp gully no longer fails as a whole.

**Organisms keep pace.** Three representative organisms are regrown per
season, most overdue first, where "overdue" is measured against the organism's
own age (a young body changes every season, an older one may wait up to four),
and the quota rises so that none waits longer than four seasons. Before this
a tree's organisms were never regrown once three faster species stood beside
it, their vitality read zero, and the stand never took.

A body is due when the organism has grown by as much as the body's own age,
within a step of 2 to 10 % of full size, and at the latest when the organism
is full-grown. A full-grown body is due once a year if it has seasons to show
(leaf fall, flowers, fruit), otherwise only when its life moves on to another
stage; one at the oldest age Species Sim grows, never. A tree is regrown
about fourteen times in forty years instead of every season.

### 3.3a Life timing: real years on a developmental clock

Species Sim grows a body on a developmental clock sized for its age slider:
`maturity_rate` gives a tree 120 to 365 days to "mature", every perennial reads
*senescent* a year later, and no body grows past 10 to 11 years. Until this
change the ecology used the same number, so a sown pine stood 38 m tall in its
first year and the decades of the loop came from soil alone.

**Two figures per species** (`plant_life_timing.resolve_plant_life_timing`):

| | Authored (wins) | Generic fallback |
|---|---|---|
| Years to mature size and regular reproduction | `maturity_age: {typical_years}` | woody forms and ferns: tree 20, shrub 5, subshrub 3, succulent 6, fern 3, vine 4, times `maturity_rate` (rapid 0.35, fast 0.6, moderate 1, slow 2). Herbs, grasses, aquatics, crusts: the season or two their developmental clock already gives them. |
| Years an individual lives | `longevity: {typical_years, max_years}` | tree 150, shrub 30, subshrub 12, succulent 40, fern 25, vine 30, lichen 40, moss 10, grass 8, forb 6, aquatic 10, times `longevity_class` (very short 0.25 to very long 4). Short-lived perennials 6 (2 to 12). |

Annuals, biennials and ephemerals already run in real days and are left as
they are. A lifespan is never less than 1.5 times the maturity. Each figure
carries its source; the Species Catalogue shows *(authored)* or *(generic)*.

**Full size comes after seed (2026-10-22).** The generic figure in the table
is when a plant sets seed. A woody plant (tree, shrub, vine) without an
authored `maturity_age` goes on growing: it stands full-grown at a fifth of
its lifespan (`FULL_SIZE_SHARE_OF_LIFE`), never before it sets seed. A slow,
very long-lived tree (oak) sets seed at 40 and is full-grown at 120; a
generic tree at 20 and 30; a birch at 40 and 40. `maturity_days` is full size;
`seed_days` (`PlantLifeTiming.seed_days`, `SpeciesProfile.seed_days`) is when
it sets seed and when its life phases turn adult. An authored `maturity_age`
is still both. Found by the exemplar run on a fresh Cfb Site
(`artifacts/biosim_exemplar/`): with full size at the seed age a redwood stood
49 m at ten years, a Nordmann fir 3 m at one; now 49 m at 58 years and 3 m at
seven. The share is a generic placement (height growth levels off at a fifth
to a third of a tree's life), not a measurement. Pacing probe
(`--climate temperate --brush 20`, 30 years): tiers unlock in the same years
(4, 11, 23), biomass within 2 %.
None of the 60 sowable plants authors a figure yet:
`artifacts/biosphere_terraforming/life_timing_backfill_questionnaire.md` is
the research prompt and the table of what is assumed until then.

**What uses them.**

- *Stand height* grows linearly to mature height over the real maturity, and
  with it canopy shade, cooling and overtopping.
- *Standing biomass* is cover times carrying biomass times the share of
  mature height reached (2 % for seedlings). Litter, roots and nutrient demand
  follow it; the ground a stand covers does not.
- *Seed.* A stand throws founders only once it sets seed (`seed_days`: full
  size, or earlier for a woody plant). Before that its front creeps at a
  quarter of the rate (0.4 / 0.7 / 1.0 for low / moderate / high
  `clonal_spread`).
- *The seedbed stage* (a cohort judged by light at the ground) keeps the
  short span of the developmental clock: it is establishment, not growing up.
- *Organisms.* `RepresentativeBody` is a Species Sim body that lives in real
  time: its shape is grown at `developmental_days(real age)`, its life phase,
  seasons and senescence are Species Sim's own rules read against the real
  age, maturity and lifespan. Senescence is the last fifth of adult life; an
  individual dies of old age between 75 and 100 % of the species' lifespan and
  is replaced by a seedling. Species Sim's own view is untouched.
- *Condition.* Species Sim scales vitality by a body's size. Read that way a
  tree would count as failing for the decades it takes to grow, so the
  outcome is taken as for a full-grown body in the same state
  (`RepresentativePopulationManager.condition`).

**Told to the player.** The catalogue lines (with "Sets seed: from about N
years" where that comes before full size); "Introduced English Oak; full
size in about 40 years"; "Rosa Woodsii sets seed" ("is full-grown and sets
seed" where the two coincide); the height of each population's tallest stand
in the populations table.

**Ground detail** follows the eye, not every sown hectare: chunks are refined
under the founding square and wherever a view closer than 4 px/m rests for a
second.

### 3.3b Stands of individuals (owner's direction, 2026-10-10)

The owner's direction: a population is not an area that plants are drawn in.
It is individuals kept at different levels of detail. A few of them are
simulated in full; how those fare steers the plants of their species around
them, each at a random strength between 0.5 and 1.5. The others are drawn
from ten individuals the planet keeps of the species from its first
settlement, joined by every simulated plant that comes of age there. When a
simulated plant dies, another is picked and followed.

**What is kept as what.**

| | Kept as | Simulated in depth | Drawn as |
|---|---|---|---|
| Crusts (lichen) and swards (a grass under 2.5 m) | cover: discs with a centre, a radius and a cover, as in 3.3 | three or four organisms where the cover is densest | map symbols sampled from the cover |
| Every other plant | individuals (`individuals.IndividualRegister`): one record per plant with its place, how far it is behind its stand's founding cohort, the season it rooted, the kept individual it looks like, and how many plants it stands for | up to three plants of a stand and four of a species, picked among its plants and spread out | itself: the kept individual it is, at the stage it has reached |

**A stand is its plants.** The disc of 3.3 stays, so fronts, founders,
fusion, canopy shade, competition and soil inputs work as they did, but for
these species its cover is derived: plants times the ground one plant takes,
over the disc. The ground one plant takes (`BiosphereEcology.spacing_m`) is
the crown spacing the display used (tree 0.28, shrub 0.40, fern 0.30 of mature
height, at least 0.28 to 0.46 m) and, for a plant that is not a tree, at least
30 % of how wide the planet's first kept individual of it stands full-grown: a
rose is a bush of two metres, a creeping thistle a clone of six, a bamboo a
grove of twenty. Sowing a cover over a disc sets `cover x room` plants, never
fewer than one; a plant set by hand stands where it was set, and a stand is
never smaller than the ground its plants take. Seedlings root one to a place,
land plants on land and water plants in water, and where the light at the
ground lets them (the seedbed rule of the cover kernel, now applied where
each plant stands).

**One balance, read as plants.** Per stand and season:
`gain = growth rate x suitability x recruitment x (1 - cover - 0.55 x
competition) x sum(plants x growth taken from the simulated neighbour)`,
`loss = (stress + overtopping) x plants + sum(mortality taken from the
simulated neighbour)`, with the cover kernel's coefficients. What is left
over roots as seedlings (a Poisson draw); a shortfall is paid in plants, the
young and those beside a failing simulated neighbour first, a simulated plant
last. `expected_cover`, and with it every verdict in the catalogue and under
the cursor, is unchanged: a stand fills to the same cover and fails on the
same ground. Two things are new. A stand at its balance keeps the plants it
has instead of trading them every season, and where the species holds at all
the last plant of a stand is not lost to its own crowding. A plant that has
lived its span (75 to 100 % of the species' lifespan) leaves its place to a
seedling of its own.

**Taking after the simulated neighbour.** Each season a simulated plant
reports a growth multiplier (0.68 + 0.72 x vitality) and a mortality (risk x
0.018), as the species' organisms always did. Every other plant of the
species takes both from the simulated plant nearest to it, at a strength
drawn anew for each plant each season between 0.5 and 1.5: its growth is
`1 + (multiplier - 1) x strength`, its mortality `mortality x strength`. A
plant's growth is kept as its lag behind the stand's founding cohort, so
plants beside a thriving neighbour pull ahead and those beside a failing one
fall behind, each by its own measure. Before any plant of a species is
simulated, the species' mean figures stand in.

**The simulated plants** are recorded plants. The first picked is the best
grown and most central; each further one is the plant furthest from those
already followed, the better grown of two as far. A plant picked beyond 12 %
of full size is followed from the age it has and keeps the seed of the kept
individual it was drawn as, so it does not change its look. A seedling gets a
seed of its own, and the season it comes of age it joins the planet's kept
individuals (22 at most beside the founders) and its record becomes that
individual. A simulated plant that dies of age or at the end of its life
cycle leaves a seedling in its place; one that fails leaves a gap; one taken
by its stand's losses is gone with them. Another is picked at the next
season's start; after the first pick of a season no more are made once 40 ms
have gone into growing bodies.

**The planet's kept pictures** (`plant_pictures.PlanetPlantPictures`). One
collection per planet (`terrain_root_planet_id` of the site; a site off any
planet keeps its own), shared by every Biosphere opened on it in a session.
At a species' first settlement ten individuals are laid down: a seed each and
the conditions of the place (the light at the ground, which Species Sim does
not shape a plant by yet). Each is kept at seven stages (6, 16, 30, 48, 68,
85 and 100 % of full size). A body is grown the first time a view needs it,
in the season it looks its best (in leaf, and in flower or fruit where the
species authors a year), and is the same every time. The renderer keeps up
to 1200 pictures made from them. Nothing of it is saved: like the rest of the
Biosphere, the collection lasts as long as the session.

**Too many plants to record.** Above 20 000 records a species' records are
halved and each survivor stands for the neighbour that went (`count`);
simulated plants are never the ones to go. Where a view has the budget, the
plants a record stands for are drawn around it.

**What changed for the player.** The populations table counts plants for
these species (a bare number) and stands for crusts and swards (`48x`). A
stand of trees is as many trees as its ground has room for: a 4.5 m disc is
one oak, not a thicket of symbols. A stand's biomass counts its young plants
as young. A bamboo is drawn as the plants it is.

### 3.4 What it plays like

`tf_scale`-style run on unrefined ground: three 60 m lichen sowings, then each
rung sown with a 20 m brush at the founding point as soon as it would hold
there. Measured with real life timing (all figures generic: nothing authored
yet).

| | Prototype site (hot, wetness 0.05) | Same ground, mild wet climate |
|---|---|---|
| Crust established | year 5 | year 3 |
| Herb soil | year 9 | year 4 |
| Shrub soil | year 17 | year 6 |
| Woodland-capable soil | year 30 | year 10 |
| Shrub sown / full-grown, sets seed | Agathosma year 18 / 23 | Rosa year 7 / 12 |
| Tree sown / full-grown, sets seed | Scots pine year 31 / 51 | English oak year 11 / 51 |
| Tree biomass | 0.3 t at year 35, 3.8 t at 50, 15 t in 47 stands at 80 | 0.1 t at year 15, 8 t at 50, 23 t in 42 stands at 80 |
| Year 80 | 11 ha; lichen 107 t and reported as overgrown from year 66, Agathosma 4.5 t dwindling under the pines | 30 ha; lichen 308 t, forb 14 t, roses 14 t |
| Season tick | 20 to 75 ms up to the trees, 75 to 130 ms after | 140 to 260 ms from year 15 |

Before this the same run had the tree full-grown within its first year and
in 48 stands twenty years after sowing. Populations past their seedling
stage are also healthier than they were (no permanent senescence), so mature
stands spread about 1.8 times faster: the living area at year 80 is 11 and
30 ha instead of 8 and 17.

In the app at 64x the first 18 years take about 47 s at 21 fps; at 16x a
year is 7.5 s. With woods on the site a season tick is still longer than the
frame it falls in (see 3.6).

### 3.5 What the player is told

- **Catalogue** as a ladder (bootstrap, then by tier; within a tier what the
  site can carry comes before what it cannot), each entry with its tier, a
  badge (PIONEER, MARGINAL, NEEDS SHADE, UNFIT HERE, LOCKED) and a verdict
  from the kernel's own arithmetic: *Can pioneer the raw ground*, *Suits this
  site once soil is built*, *Marginal even on built soil*, *Needs built soil
  and a nurse canopy*, *Cannot hold here*, each with the reason.
- **Top bar** in landscape units: living biomass and soil stocks in kg or
  tonnes, living area in m² or hectares, the soil tier reached out of 3.
- **Populations** table in the left panel, heaviest first: stands, biomass
  and a trend mark (up, down, level over the last year), red while a
  population is dwindling. A row brings the population into view and selects
  one of its organisms.
- **Field notes**: introductions (with a warning when the spot will not hold
  the species), establishment after two years, soil stages with the number of
  species they open, living-area growth, populations that have lost a third
  of their best biomass, and populations that died out. Declines name the
  cause that is actually acting: *overgrown by taller plants*, *crowded out*,
  *holding too thinly to recover*, or the limiting site factor.
- **Cursor readout**: elevation, wetness (and how much of it the soil holds),
  soil organic matter, N and P under the pointer, and whether the selected
  species would thrive, hold, barely hold or fail there and why.
- **Scale bar** in the ground strip, measured along the ground (the engine's
  own bar measures the Map camera and is hidden here).
- **Seeding ring** under the pointer at the size of the current tool.

Names in status lines and notes drop the scientific part ("English Oak", not
"English Oak - Quercus robur").

### 3.5a What the landscape looks like

- **Plants are drawn to scale** in a terrain view: sprite height is mature
  height x maturity x px/m, up to 320 px, so trees tower over shrubs close
  by. The legibility floor (22 px for a herb) fades out as the view zooms
  out, so from afar a grass sward is texture and a tree is still a tree.
  Non-terrain patches keep the old symbol sizes.
- **One pixel size for every plant (owner's choice, 2026-10-22).** A kept
  picture is held to 320 px whatever the plant's size, so an oak's holds 8 px
  to the metre and a plantain's 440. A view that needs a plant larger than
  its kept picture used to enlarge it: at 40 px/m an oak was 4.6-pixel blocks
  beside herbs in single pixels. Now it is painted again at the view's size
  (`BiosphereBuilderRenderer._view_picture`, in steps of 1.25, kept on disk
  beside the kept picture, painted only while the view rests and one a
  frame; the enlarged picture stands in until then). Species Sim draws it
  with `pixel_scale` = that painting's height over the kept picture's
  painting: every pixel floor, cap and size at which foliage changes how it
  is drawn is scaled, so the plant looks as its kept picture does, in finer
  pixels (painted at the view's size without it, conifers, ginkgo, birch and
  horse chestnut lost half their crown). Painting one tree this large takes
  0.4 to 2 s the first time; from disk 0.1 s. Still enlarged: a tree past
  the 1,400 px a view draws at most (an oak at 120 px/m is 0.38 of its
  height), and a wide plant beyond the 4,096 px panel.
- **Plants stand a crown apart** (tree 0.28, shrub 0.40, fern 0.30 of mature
  height) instead of one every half metre, so a wood is not a wall of
  overlapping trunks. Since 3.3b this is the ground a recorded plant takes,
  not a display rule: what is drawn is what stands there.
- **The display budget goes to the ground in view.** The sampler takes the
  visible ground as a window (a box in `x - y` and `x + y`, snapped to an
  eighth of the view and of one size per zoom, so density never changes while
  panning). On a site with 190 stands a close view showed 11 to 34 display
  plants; it now shows 220 to 300. Abundance for all candidates is computed
  at once (`vegetation.population_abundances`, equal to the point-by-point
  answer to 1e-12): one picture of the vegetation cost 515 ms and was retaken
  every season; it costs about 40 ms.
- **Soil tint** is draped per pixel through a screen-to-ground map (3 px
  blocks at rest, 9 px while moving) and fades in at the living area's edge,
  replacing the stepped polygons.
- **Chunk textures** are sampled from a mip matched to the ground step, which
  removes the sparkle of 1 m rasters seen from afar.
- **Shadows** are proportional to the plant and skipped under sprites smaller
  than 14 px.

### 3.6 Still open

- **Cold ground.** Frozen ground is not in the generator: arctic lowland is
  as wet as its rain against its demand makes it, not as wet as ground that
  cannot drain. No plant of dry cold plateaus (puna, cold steppe) is in the
  catalogue.
- **Pioneer line.** One land organism below tier 1, no nitrogen-fixing herb
  or shrub, no moss. About 24 species lack `plant_growth_form` and show as
  tier-1 forbs, including trees (Robinia, Litchi, Moringa, Kigelia). Both go
  through `docs/Plant_Design_Process.md`. Biomasser 13B authors no
  `nitrogen_fixation`, so the bootstrap organism itself reads
  "nitrogen-starved" on raw ground.
- **The crust is thinned, not displaced.** Under pines and oaks it is now
  reported as overgrown and loses a third of its mass, but it keeps most of
  the site's biomass: its carrying biomass (3.2 kg/m²) equals shrubland's.
- **Nitrogen is unbounded** (over 100 g/m² after decades). There is no
  leaching, and the books do not balance: litter returns nitrogen that
  uptake never removed from the soil.
- **Season cost.** 75 to 260 ms once woods stand (140 to 540 ms before life
  timing and the refinement pass). What is left is
  mostly the ecology step over some 190 stands and the bodies of short-lived
  herbs, which are regrown every season while they grow.
- **Refined chunks drift from their parent** in climate, wetness and soil
  depth (table in section 2). The Biosphere reads around it; worldgen should
  conserve the parent's means when it refines.
- **Every life figure is generic.** No species authors `maturity_age` or
  `longevity` yet; silver birch reads as a slow tree (40 years), 24 species
  without `plant_growth_form` as six-week forbs (Robinia, Litchi, Kigelia
  among them). The questionnaire in `artifacts/biosphere_terraforming/` is
  ready to hand to a researcher; answers are authored per the Plant Design
  Process.
- **Height is linear in age** and biomass linear in height. Real trees gain
  height early and mass late.
- **Seasons.** A body's leaf and flower state follows the day of the year it
  was last grown in; a deciduous shrub regrown in winter stands leafless
  until its next turn.
- **Display density is still thinned at site scale**: zoomed out, a species
  spread over the whole site is drawn at a fraction of its real density, and
  the lichen crust reads mainly through the soil tint.
- **A stand is one disc** for the ground it is judged by: averaged over five
  points, but the same for every plant in it. Its plants do root only where
  light and water let them (3.3b).
- **Individuals (3.3b), still to do.** Species Sim does not yet shape a plant
  by its light, so the kept individuals differ by seed only; the conditions
  they would need are recorded. The collection is not saved. Canopy shade and
  soil inputs read a stand's disc and cover, not each plant's crown. A species
  has at most four simulated plants, so a far stand may take after a distant
  neighbour.
- **Bodies are the season's cost.** Regrowing the body of a simulated plant
  takes 0.3 to 0.7 s for a lichen crust or a bamboo. Measured 2026-10-10 on a
  site with a crust, a bamboo, a short-lived subshrub and a fir: 20 to 150 ms
  in a quiet season, about a second when several bodies fall due. Not measured
  against the cover kernel on the same site.
- **Persistence.** Nothing is saved; closing the tab ends the run.
- **Every season is the same** for the ecology; no dormancy, no drought year.
- **Interventions** (irrigation, shelter, amendment) are not there; a site
  whose rain cannot be held stays at lichen.
- **A temperate prototype region** does not exist yet; the mild results above
  come from an in-memory climate swap.

### 3.7 From a Biosphere run to a city: biome floras (owner's decisions, 2026-10-10)

The loop: plants A and B are established; the player introduces C in a
Biosphere; it establishes and is entered in that biome's extant plants; a
city founded in the same biome finds it growing, as often as it is common.

**Biomes** (`simulations/biosphere/biomes.py`). A biome is the Koppen class
of the ground, split by wetness and height only where a word exists: *open
water*, *wetland* (the water table within 30 cm of the surface; on a map
that does not tell its depth, wetness from 0.75), *riverside* (a channel); *montane*
(from 1000 m), *alpine* (above that, warmest month under 10 C). Dry ground and
hills have no word and no biome of their own. `Cfb`, `Cfb/wetland`,
`Cfb/wetland/montane` ("Montane Temperate Oceanic wetland").

**Floras and collections** (`simulations/biosphere/flora.py`). Both are
Biosphere entities (dataset `biospheres`) with a `collection_role`:

* a *biome flora* overlays its planet and names its biome. Its
  `plant_records` hold, per species, a rarity (dominant, common, occasional,
  rare), where the rarity came from, the year it was established and the
  share of the living area it held. A Biosphere run writes an entry when a
  species establishes and brings its rarity up to date once a year
  (`BiosphereSimulation._enter_flora`; rarity from share: 50 %, 15 %, 3 %).
* a *plant collection* is a named list of species with a rarity each. A flora
  names one in `plant_collection`; its species are then present at its
  rarities, sown or not, and the flora follows the collection when that is
  edited. Rarities play produced stand until then and again once it is taken
  away. Set on the flora's card, or for every biome of a region at once:
  `python tools/author_biome_flora_model.py assign --region <id> --collection <id>`.

`tools/author_biome_flora_model.py` puts the fields into `schema_biosphere`
and writes two example collections (European temperate woodland and meadow;
European temperate wetland).

**What grows where** (`simulations/biosphere/potential_vegetation.py`).
`resident_vegetation` works out the vegetation an established biome carries
on a piece of ground without playing it through: the kernel's own arithmetic
at its balance (`potential_suitability`, `expected_cover_array` in
`ecology.py`), on built soil. Canopy (from 8 m), understorey (2 m), field
(0.3 m) and ground layers are settled from the top, each in the light the
ones above leave; within a layer the commoner species first. Every species
also stands under and beside the others as the kernel sets its stands against
each other (2026-10-11; `BiosphereEcology.competition_weight`, `overtops`,
`COMPETITION_SHARE`, the same figures `_competition_at_patch` uses): of the
cover that shares its ground, three quarters count against its growth, 15 %
where the neighbour is under a quarter of its height, and what stands well
above it adds to its losses. Before, layers met only through light, and the
solver gave a sward 90 % cover under closed oaks where the played kernel
kept a few per cent of it under a wide canopy (0.25 where the stand's rim
reaches the edge of the wood); residents set out from the solver then
thinned or died out within years. The covers press on each other, so they
are settled in three rounds (`BALANCE_ROUNDS`). A rarity is the
share of the ground that suits a species on which it is met at all (1, 0.6,
0.2, 0.05), in patches of its own with ragged outlines. A climber is no layer:
it holds at most half the crowns of the shrubs and trees that carry it. A
plant rooted under water holds only the shallows, all of them to 1.5 m and
none from 3 m (`AQUATIC_DEPTH_M`). The ground is read as the kernel reads it:
each species meets the wetness of its own rooting depth
(`ResidentVegetation.wetness_by_rooting`, from `water_balance.plant_wetness`
on built soil), the ground that can be rooted against the depth it roots to,
the sunlight of the slope, and the salt in reach of its roots. On ground the river reworks, a species holds
the share of it that has been left alone for as long as the species takes
to grow up (`flood_standing_share`): herbs on a bar reworked every three
years, trees only where decades pass between floods.
Single plants are set out from the cover per piece of ground when asked for,
the same ones each time.

*The planet's, not the map's* (2026-10-11). Where a species' patches lie and
where its plants stand is placed in the planet's own coordinates
(`GroundFrame`: the map's metre frame against `source_uv_bounds` and the
planet's circumference): the patch noise is read at the place in the
planet's space and ranked over the whole planet, a plant stands on one of
the places a planet-wide lattice keeps for its spacing, and the seed is the
planet's (`planet_seed`). A Site, the Parcel, Plot and Survey under it, a
city's map and a Biosphere founded on any of them show the same woods and
the same trees; a finer map only reads the ground more closely. Before, each
drew its own. A rarity is therefore a share of the planet's ground, and a
window of a map holds more of a species' patches or fewer.
`tools/lod_flora_chain.py check` reads the ground of every map of a chain
from itself and from the map above and compares.

*A collection for every climate* (`tools/author_zone_collections.py`,
2026-10-11). One plant collection to each of the 31 Koppen zones the
generator knows (`biosphere_collection_koppen_<zone>`), from the 57 plants
of the catalogue: a plant is in a zone's collection when the zone lies
within the climates it grows wild in and the kernel's limits let it live
over most of the zone's winters and summers. One list holds a zone's plants
of dry, ordinary and wet ground and of open water; the ground sorts them.
`assign --region` sets the floras of the biomes a region shows, each by its
own zone's collection. The catalogue is small and from every continent, so
a collection mixes floras that never met, and some zones are thin: no
tropical grass, no tree of the coldest winters, nothing for an ice cap.

**On the city map** (`simulations/city/city_vegetation.py`,
`MapSimulation._resident_vegetation_layers`, `MapRenderer._draw_plant_field_layer`).
Low layers are a tint. Everything from two metres up is a plant where it
stands, drawn as its species' own picture from above: the planet's picture
collection keeps the first two individuals of each species, full-grown, as
Species Sim's top-down view draws them (`PlanetPlantPictures.map_sprite`;
kept between sessions under `.cache/planet_plant_pictures/`), and every
coarser version is made from that (`map_sprite_at`). Close in a painted pixel
is a screen pixel; further out it takes up to three, with a coarser picture.
The field is painted in tiles as they are first seen.

Known gaps:

* Species Sim draws no leaf smaller than about three pixels, so the top view
  is drawn large and reduced. Conifers are the other way round and are kept
  at the small drawing.
* An oak from above shows its trunk and scaffold through the crown: the top
  view places foliage on the outer shoots only.
* The solver assumes built soil and reads the niche traits as authored. Most
  plants have no heat limit and many share one moisture optimum, so a hot
  steppe accepts Scots pine. Backfilling those traits is plant-design work.
* A city's buildings do not clear the plants under them yet.
* A Biosphere opened in a biome that has a flora starts with it growing
  (below, "Opening on ground that has a flora"). Each resident species is one
  stand over the living area, so the kernel judges it over the whole area:
  where the solver stands the plants is where they start, and under a closed
  canopy a sward thins to about a tenth within ten years.
* The depth limit for water plants is in the solver only.
* River bars (water pass): a bar is loose sediment, rootable to 3 m, that
  holds little water (70 mm a metre) and lifts it a hand's breadth. What
  stands on it is decided by the depth to the river's water: trees and
  shrubs whose roots reach it, and herbs only as far as the rain carries
  them. On Biosim World's dry site the land with under 5 % plant cover went
  from 27 % to 3 %. Floods (3.3) then take the trees off the ground the river
  reworks within decades. Still not in it: the band in which seedlings get
  away (Mahoney & Rood 1998: 0.6 to 2 m above the late-summer river, a
  falling stage their roots can follow), and a full-grown tree that outlasts
  a flood the played kernel takes it in.
* A climate zone says nothing certain about wetness. Biosim World's first
  site is Humid Subtropical by its temperatures and rain, and its rain falls short
  of the demand of its air in every month and meets under half of it over
  the year: dry woodland. The
  temperate collection assigned to it holds along the ground water and thins
  out on the rises. A flora per zone and water regime, or a zone label that
  reads the balance, is not decided.
* With the one-sided water limit a plant of dry ground is at home on fresh
  ground too (Scots pine and Agave read 100 % on the wet site). In the field
  such plants are crowded out there by faster ones; the kernel leaves that to
  its competition, which does not know that a stress-tolerator grows slowly.

**Opening on ground that has a flora** (`simulations/biosphere/resident_start.py`,
2026-10-10). A Biosphere founded where the biomes have a flora does not open
bare. What grows there is worked out by the solver above over a window round
the living area and set out as the first populations: every species one
grown stand, its plants where the solver stands them and as far grown as it
has them, a sward or a crust as a cover of the same share
(`BiosphereEcology.found_grown_stand`). The soil under them is built (4 kg
of organic matter a square metre where the flora covers half the ground or
more), so every tier can be planted from the first day. They are the site's
own: nothing is told of their establishing, a plot's share of them does not
rewrite the planet's flora, and they do not make the living area grow. Only
what the player brings in does, and the ground it grows into comes with its
residents. From then on they compete, are taken by the river and die out
like any population. On the wet site a 10 m plot opens with ryegrass,
plantain and two oaks in 1.3 s; left alone for ten years the oaks and the
plantain hold and the ryegrass thins under the oaks from 0.69 to 0.10.
`--residents` on the playthrough tool opens a site this way; without it the
tool plays primary succession from bare ground (context `start_bare`).

**Floods on a city's map** (`simulations/city/city_floods.py`). A city whose
Site tells its floods has a *Floods* check box in the map's view panel: the
ground the river covers within 2, 10 and 100 years, tinted over the map and
the plants on it. Nothing is decided by it yet; buildings are not asked.

**Biosim World** (generated 2026-10-10 with
`tools/city_prototype_walkthrough.py --name "Biosim World" --orbit-au 1.005 --min-temperature-k 277`).
`planet_biosim_world` in Test System Prime: 63 % ocean, 23 rivers, 17 climate
zones from ice cap to tropics. Refined to the site `refined_lod4_4ef0f98c8b`
(3.2 x 1.8 km, humid subtropical at 1100 m, on a river 9 m deep), with the
city `city_refined_lod4_4ef0f98c8b_01` on it. The woodland collection is
assigned to its ordinary ground, the wetland collection to its open water,
riverside and wetland.

    python tools/render_city_resident_vegetation.py --city city_refined_lod4_4ef0f98c8b_01
    python tools/biosphere_terraforming_playthrough.py --region refined_lod4_4ef0f98c8b --years 36 --brush 20 \
        --city city_refined_lod4_4ef0f98c8b_01 --shots artifacts/biosim_world_loop

Both are look-only. The second plays a Biosphere on the site and then draws
the city with what the run entered in the flora: in 36 years the crust
organism (year 3), Horse Shoe Fern (year 14) and Buddleja (year 20), each
"by gameplay" beside the collection's species.

Since the water pass the site is read as the dry woodland its figures make
it. The solver sorts the collection along the water table: wood club-rush
where it stands within 30 cm (9 % of the land, no tree), bracken, birch and
ryegrass where it lies 0.3 to 1 m down, English oak thickest where it lies 1
to 2 m down (canopy 61 % there, 18 % where it is deeper than 3.5 m), Scots
pine and plantain on the rises; along the river the ground it reworks
within decades carries herbs and no tree. A played run at the default point
(table 2.5 m down, built soil 0.27) goes crust (year 3), chicory (year 6),
Agave (year 15): plantain, pine and Agave suit, the oak is marginal. With
`--climate temperate` (900 mm of rain against 650 mm of demand) the tiers
unlock in years 4, 11 and 27.

**The wet site** (owner, 2026-10-10: a wetter part of the planet for the
temperate collection). `refined_lod4_29a30fb2ae` (3.2 x 1.8 km) under
`refined_lod1_2208f14140`, `refined_lod2_3ca58810bc` and
`refined_lod3_120074578e`, with the city `city_refined_lod4_29a30fb2ae_01`:
Temperate Oceanic at 600 m, 14 to 22 °C through the year, 1732 mm of rain
against 1308 mm of demand, a river of 63 m³/s between levees and old
channels on a plain with 14 m of relief. The collections are assigned to its
four biomes (Oceanic 69 %, Oceanic wetland 28 %, open water 2 %, riverside
0.6 %). No ground is bare: ryegrass on 49 % of the land, English oak on
32 %, wood club-rush on 28 % (the flats whose water stands at the surface,
drawn in the dull olive of its own picture, which reads as brown on the
map), bracken on 22 %, plantain on 11 %, birch on 5 %, sessile oak on 4 %.
The pedunculate oak, which bears some waterlogging, holds the moist ground
(canopy 0.49 where the table lies 0.3 to 1 m down); the sessile oak, which
bears little, keeps to the rises. A played run from bare ground at the
default point (built soil 0.50) finds 38 of 41 herbs, all 8 shrubs and all
20 trees suited, and unlocks the tiers in years 5 and 14.

    python tools/render_city_resident_vegetation.py --city city_refined_lod4_29a30fb2ae_01
    python tools/biosphere_terraforming_playthrough.py --region refined_lod4_29a30fb2ae --years 30

**One writer at a time.** A write to the ontology made while any other
process has it open can be reported as done, be seen through the store's
cache, and still not be in the database (seen 2026-10-10 with a second
session's authoring tool running). Check the process list right before a
write, and check the result in the database's `resources` table.
`tools/author_biome_flora_model.py` does the second on its own.

### 3.8 From the map to the Biosphere: the surroundings (owner, 2026-10-12)

Section 3.7 is the map taking from the Biosphere: what runs establish is
what a city's map grows. This is the other way. The isometric view looks
at ground a map already shows with its woods and meadows, and until now
drew ten metres of living area in bare mineral ground. It now shows round
the living area what the map has there
(`simulations/biosphere/surroundings.py`, `BiosphereSimulation.surroundings`).

**What is shown** (as of 2026-10-13; owner: no blended colour on the
ground, the ground in coarse pixels, the green from plant pictures at the
plants' own density, and plants that grow in patches drawn as patches).

* *The same plants at the same places.* They are the planet's places
  (`ResidentVegetation.individuals`). Beyond the ground read for the
  residents (160 m round the living area) they are those of a reading of the
  whole ground on a city map's lattice (`potential_vegetation.MAP_CELLS`),
  place for place the plants that map draws; nearer, those of the residents'
  own closer reading. Within 6 m of the living area each is the very kept
  individual and stage it is as a resident (`resident_start.kept_individual`);
  further off one of two individuals at three sizes.
* *All of them.* A view is given up to 30,000 plants, trees first and layer
  by layer down. They are painted once, from the far edge to the near, into
  one picture when the view rests (`_surrounding_plant_layer`); those that
  reach in among the living area's own plants are drawn one by one between
  them. Only a plant that would stand under two pixels, or a species with
  more than a million places in the view, is left to the ground.
* *The ground in blocks.* Soil and what is not drawn as plants are blocks of
  four screen pixels (`_paint_ground_pixels`), each one tone of soil or the
  colour of a plant, on a lattice of the ground itself, so a block keeps its
  colour while the view pans. The living area's soil is drawn the same way.
* *Patches.* A sward, a crust, and a plant whose `clonal_spread` is high and
  that stands no taller than 0.6 m, a mat (`Surroundings.grows_in_patches`;
  a taller one, a thistle or bracken, read as noise on the ground), is drawn
  as the ground it covers (`patch_cover`, `_ground_patches`): beds with an
  outline, in a texture made of the species' own picture from above, up to
  three blocks high with a darker side towards the viewer; one in eight of
  its plants stands on it as its own picture. The living area's swards are
  filled the same way, and their grass is drawn as its own picture too.
* *Plant pictures.* A kept plant is painted with all its leaves, large
  enough for a leaf to be 3.8 pixels long, and reduced as a map reduces a
  plant's picture (`plant_pictures.map_sprite_at`): thin twigs and small
  leaves stay, in few tones. Painted at the kept size with three leaves a
  cluster, as before, a birch stood bare. Needles are painted small as
  before. The pictures are kept on disk beside those from above
  (`isometric/`), with the measured widths of the plants. Shadows are one
  translucent shade of coarse pixels. Every kept plant stands in one light
  (lighter at its top, darker at its foot) and one range of colour (`_lit`,
  `_calmed`: no colour purer than 0.62 or lighter than 0.80); half of the
  plants further off are shown mirrored; and a small plant is drawn at most
  half as tall again as it is, where it used to be drawn up to six times
  its size beside trees drawn true.
* *While the view moves* the pictures last painted go with the ground;
  ground they do not reach is drawn in blocks three times as large with all
  its plants as blocks, until the view rests and its plants are set out.

**What it is not.** Nothing of it is simulated. It does not grow, die, seed
into the living area or shade it; it is there until the living area takes
it over. Buildings, roads and fields of a city are not shown. A site that
opens bare (`start_bare`, or a planet without floras) has no surroundings.

**Cost** (wet Site, 1600 x 900). Setting out the plants of a view: 0.06 s
close in, 0.4 to 1.6 s further out, in steps of about 20 ms a frame.
Painting them into their picture: 5 to 70 ms. The ground: 60 ms when a view
comes to rest. A frame: 6 to 8 ms with 15,000 plants in the picture. The
first painting of a broad-leaved plant's picture takes about 0.4 s (0.1 s
before); from then on it is read from disk, and the application opens a
Biosphere there in 10 frames and 4 s.

**Measured** (`tools/biosphere_surroundings.py`, look-only, wet Site, living
area at 1995, 655 m): beyond the residents' window the view has every tall
plant of the map at the same place. Within it, 63 to 81 % of the map's:
there the Biosphere reads the ground in cells of 2.5 m and the map in cells
of 25 m, on ground sampled every 8.4 m. Read at 12 m the map would agree on
76 to 84 %, at 6 m on 86 to 93 % (and take 23 s to read). The two readings
of one ground differ for the same reason a Site and its Parcel do: a finer
reading settles the cover again instead of refining the coarser one.

**A meadow close in is grass, not beds (2026-10-23).** On a meadow with a
few oaks (Cfa Site `bx_cfa_site`, `artifacts/biosim_exemplar/meadow_compare/`)
the sward's patches read as dark camouflage beds at 40 px/m, though a
ryegrass tuft stands 28 px high there. Now a sward whose tufts stand
`SWARD_PLANTS_FROM_PX` (12) or more pixels high, and of which the view can
show at least every other tuft, is drawn as its plants and has no patch
(`Surroundings.as_plants`); so is the living area's own
(`_own_patch_cover`, and up to `MAX_SWARD_INSTANCES` tufts from the
sampler). `PLANT_BUDGET` 30,000 -> 80,000: a close view of a meadow holds
some 40,000 plants; a resting frame still paints in hundredths of a second.
Further out a sward stays a patch, but flat (no side) and in finer clumps
(`SWARD_CLUMP_BLOCKS`): a turf rather than raised beds. Still bare: the soil
between the tufts shows brown, and Species Sim's ryegrass is a fan of blades
lying flat.

**Still open.** A finer reading that keeps the cover of the one above it;
the surroundings shading and seeding into the living area; a city's
buildings and fields; the 320 pixel limit on a picture's height, which
draws a 25 m tree under its size closer than 13 pixels to the metre (left:
a higher limit is paid in memory for every kept tree); oak, birch and
buddleja, which stay thin with all their leaves drawn.

### 3.9 Who grows where, measured (2026-10-13)

`tools/flora_distribution_audit.py --site <Site> --zone <Koppen zone>`
(look-only) lays a zone's climate and collection over a Site's ground,
reads it with the solver and asks what a natural vegetation would show.
`--all` gives a line for each of twelve climates: the yardstick. On the
wet Site's ground, before the first changes and after them (2026-10-13):

| zone | species in the collection | sharing a 25 m cell | on a closed wood's floor | bare land |
|---|---|---|---|---|
| Af | 10 | 2.2 -> 2.7 | 1.3 -> 1.7 | 0 % |
| Aw | 12 | 1.8 -> 3.3 | 0.2 -> 0.9 | 3 % |
| BWh | 6 | 0.0 -> 0.1 | no wood | 97 -> 90 % |
| BSh | 11 | 0.8 -> 1.5 | 0.1 -> 1.1 | 27 -> 8 % |
| BSk | 16 | 1.4 -> 1.9 | no wood | 10 -> 3 % |
| Csa | 20 | 2.1 -> 3.3 | 0.7 -> 0.7 | 2 -> 1 % |
| Cwa | 21 | 2.0 -> 3.7 | 0.6 -> 1.6 | 4 -> 3 % |
| Cfa | 30 | 3.3 -> 6.0 | 1.6 -> 4.1 | 2 -> 1 % |
| Cfb | 32 | 2.7 -> 4.9 | 1.2 -> 2.6 | 0 % |
| Dfb | 25 | 3.0 -> 4.2 | 1.0 -> 1.6 | 0 % |
| Dfc | 15 | 2.2 -> 3.4 | 0.7 -> 1.6 | 0 % |
| ET | 4 | 1.6 -> 1.7 | no wood | 2 % |

**The first changes** (owner's plan of 2026-10-13, steps 3, 4 and 6):

* *Scattered or in beds* (`potential_vegetation.aggregation`). A rarity
  used to be the share of the ground a species was met on at all, at its
  full cover there: every species in patches of its own, and few of them on
  one piece of ground. Now only a plant that spreads by runners
  (`clonal_spread` high) keeps to beds. One that comes from seed is met on
  more ground and stands thinner there (an occasional plant on 45 % of the
  ground that suits it at 45 % of its cover, where it was on 20 % at all of
  it). The cover it holds in all is the same.
* *Soil reaction* (`ecology.reaction_response`). A species with an authored
  `soil_ph_range` grows within it and fails a unit of pH beyond, in the
  kernel and in the solver, and is told so ("soil too sour or too limy").
  Six species have a range; the two Sites vary by a tenth to a quarter of a
  unit of pH, so on them it changes little. Fertility is left as it was: the
  generator gives none on purpose, and no species has a nutrient demand yet.
* *Crusts.* The solver sets a crust out on ground with less than 15 cm of
  soil, as far as it is that thin and nothing that roots covers it
  (`CRUST_SOIL_DEPTH_M`). The wet Site has no such ground: its lichens still
  appear nowhere there, rightly.

* *Commonness as a run measured it* (`flora.ground_share_of`,
  `BiomeFlora.ground_share`; owner, 2026-10-13: start an empty Biosphere,
  establish plants, derive how common each is from the run, generate the
  rest of that biosphere from it). A run already entered each established
  species in its biome's flora with the share of the living area it held,
  once a year. The solver now reads that share itself, off the line the four
  rarities are steps of, where it read the letter: two plants a run left
  unequally common stay so on every map made from it. A species a
  collection set keeps what its letter stands for; collections are
  scaffolding until floras come from play. `--stored` on the audit measures
  a Site with its planet's own floras.
* *Time* (`potential_vegetation.fire_return_years`, `stand_age_years`,
  `closure_years`, `recovery_years`). Fire by climate, in classes: none in
  a desert or where it is wet through the year, every 4 years under a
  tropical dry season, 8 in steppe, 35 in dry woodland, 150 in cold conifer
  wood, 400 in moist temperate wood. The years since the last fire lie over
  the planet in patches of some 600 m, spread as fires without memory leave
  them (most ground young, some very old). A species is back on burnt
  ground within three tenths of the years it takes to grow up (a woody one
  in no fewer than five), sooner if it sprouts again from its stock
  (`resprouting`), and its plants there are no older than the fire. Besides
  that every cell of wood has its gaps: a wood loses about a hundredth of
  its canopy a year, so a tree holds exp(-closure/100) of what it could.
  No grazing (owner). The figures are from memory of the literature (Bond
  and Keeley 2005, Johnson 1992, Van Wagner 1978, Runkle 1985) and not
  looked up. With it the savanna's closed wood falls from 20 % of the land
  to 7 %, and a cell holds 5.4 species under Cfb, 6.2 under Cfa, 4.7 under
  Dfb, 4.4 under Cwa.

Still to do of that plan: the figures behind the classes (moisture optima,
waterlogging, salt, succession tier, a nutrient demand, tolerance of fire);
companions that share part of a patch pattern; and whether a Biosphere
opened on bare ground should show its surroundings fill in as its plants
enter the flora (today they appear on the maps, and round the living area
the next time it is opened).

What the solver has: water sorts the species (table, wetness, floods,
waterlogging), shade keeps light-demanding plants from under trees, depth
of soil and salt limit them, and rarity gives each a share of the ground in
patches of its own.

What it lacks for a natural picture:

* *Species to share ground with.* Two species to a 600 m2 cell where a wood
  or a steppe has dozens. The collections are short, and what is in them
  does not stand together: of the fifteen herbs and shrubs of the oceanic
  wood ten stand away from its trees and one (sweet spurge) under them, so
  the woods have nearly empty floors.
* *The plants a climate is made of.* The cold steppe has no steppe grass and
  no riverside tree: creeping thistle holds 24 % of its land, and its only
  tree, a pine, stands where its patches fall and not along the water.
* *Ground other than wet and dry.* The solver takes nutrients and fertility
  as given and reads no lime, sand or clay, though the generator lays the
  rock and its materials. Within one Site the climate is one, so water is
  the only axis along which a community changes.
* *Time, beyond fire and gaps.* No grazing, no old field, no tree that
  bears fire by its bark: `succession_tier` and a tolerance of fire are
  authored for no species.
* *Crusts on open soil.* A crust is set out on stone only; the crusts of
  dry open soil between plants are not.
* *Figures.* No species has a moisture optimum of its own: most have a
  class (nine different optima among 32 species, five light minima), six
  have nothing. Waterlogging is unauthored for 12 of 32, salt for 16.
* *Floras from play.* The two Sites' floras are still set by collections;
  none has been played from bare ground yet.

## 4. Files and verification

| File | Role |
|---|---|
| `simulations/biosphere/terrain_site.py` | founding, frame, chunk lattice and refinement |
| `simulations/map/worldgen_substrate.py` | `LayeredSubstrate`, array sampling, Köppen lookup, region climate and conserved wetness for on-demand chunks |
| `simulations/biosphere/biosphere_simulation.py` | terrain-linked domain, chunk resolution, view controls, field notes, diagnosis |
| `simulations/biosphere/biosphere_renderer.py` | isometric heightfield, ground colour, living-area outline, seeding ring, plant pictures painted once and rescaled |
| `simulations/biosphere/ecology.py` | limits and amelioration, layered competition, spread and fusing, named factors, site potential; stands of individuals: founding, the balance read as plants, taking after the simulated neighbour |
| `simulations/biosphere/individuals.py` | the register of recorded plants, stand by stand; records that stand for several plants |
| `simulations/biosphere/plant_pictures.py` | a planet's kept individuals per species, their bodies stage by stage, the season a kept body is shown in |
| `simulations/biosphere/soil_succession.py` | tier thresholds; vectorised soil step (matches the cell-by-cell version to 1e-14) |
| `simulations/species/plant_life_timing.py` | real maturity and lifespan per species: authored figures, generic fallbacks, the map onto Species Sim's developmental clock |
| `world/plant_traits.py` | optional trait fields `maturity_age`, `longevity` |
| `simulations/biosphere/representatives.py` | `RepresentativeBody` living in real time; bodies regrown when they have grown; condition apart from size; death of old age; simulated plants picked among a stand's recorded plants and replaced when they die |
| `simulations/biosphere/vegetation.py` | what a view shows: recorded plants as they are, cover sampled; view window and array abundance in terrain views |
| `simulations/biosphere/water_balance.py` | wetness as the year's water balance of a plant: monthly rain and demand, the rooted soil's store, run-on, ground water; arrays and single places |
| `simulations/biosphere/biomes.py` | biome words; a wetland by the depth of its water table |
| `simulations/world_gen/river_floods.py` | how often a carved river covers and reworks each cell; read by the kernel's yearly flood and the solver's standing share |
| `simulations/biosphere/resident_start.py` | a Biosphere on ground that has a flora opens with it growing; residents of ground the living area grows into |
| `simulations/biosphere/surroundings.py` | what the map shows round a Biosphere's living area: its plants at their places, the colour of the rest, the soil under it; drawn, not simulated |
| `tools/flora_distribution_audit.py` | look-only: a zone's climate and collection over a Site's ground; who grows, what places each species, how many share ground, how wet and dry ground differ, where the solver's figures come from; `--shots` opens a Biosphere on it |
| `tools/biosphere_surroundings.py` | look-only: a city's map and the Biosphere opened on the same ground side by side, and how many of the map's plants the view has at the same place |
| `simulations/city/city_floods.py` | the Floods overlay of a city's map |
| `tools/author_zone_collections.py` | a plant collection for every Koppen zone (`check`, `assign --region`); dry run unless `--apply` |
| `tools/lod_flora_chain.py` | look-only: the ground of every map of a Site > Parcel > Plot > Survey chain read from itself and from the map above, with the zone collections on it |
| `tools/backfill_thermal_ranges.py` | the thermal ranges of the species that were in the catalogue before the field, each with the wild range it was read off (unverified); dry run unless `--apply` |
| `tools/stress_ground_water.py` | look-only stress runs of all of the above: impossible ground, real ground at three levels, eight climates, the played kernel (round log, stress pass) |
| `tools/biosphere_terraforming_playthrough.py` | pacing probe (`--climate temperate`, `--brush R`) |
| `simulations/map/map_simulation.py` | *Start Biosphere Here* pick mode |
| `app/navigation_controller.py` | opening sites, refinement redraw callback |
| `ui/ui_manager.py` | sidebar button, top bar units, populations table, ground strip with scale bar, field notes, catalogue verdicts |
| `engine/window.py`, `engine/renderer.py` | engine scale bar and flat map skipped for this view; sprite painting budget |
| `tools/app_driver.py` | look-only sessions now also redirect refined rasters to a temp folder |

```powershell
C:\Users\logol\Index\.venv\Scripts\python.exe -m unittest tests.test_biosphere_terrain_site tests.test_city_site tests.test_map_ui_workspace
py -m pytest tests/test_biome_flora.py tests/test_biosphere_individuals.py tests/test_biosphere_builder.py tests/test_biosphere_recruitment.py tests/test_biosphere_vegetation.py tests/test_biosphere_soil_succession.py tests/test_biosphere_soil_nutrients.py tests/test_biosphere_ecosystem.py tests/test_highest_lod_example_map.py tests/test_map_picking.py tests/test_navigation_building.py -q
C:\Users\logol\Index\.venv\Scripts\python.exe tools/biosphere_terraforming_playthrough.py --years 40 --shots artifacts/biosphere_terraforming
```

The flow was driven through the real app headlessly with ontology writes
disabled. No site or chunk has been stored in the live ontology yet; the first
real click will be the first persisted site.
