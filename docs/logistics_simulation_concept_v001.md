# Logistics simulation: dual detail across transport domains (concept v001)

Status: concept, 2026-10-28. Nothing implemented. Extends
`docs/conceptual_layer_overview_v007.txt` sections 14 to 16 and takes in
`docs/space_transfer_windows_v001.md` and
`docs/space_spacecraft_navigation_v001.md` as the space domain.

## 1. Owner's direction (2026-10-28)

One logistics simulation covers waterways, roads, paths, air travel, orbits
and so on, with the usual dual detail:

- **Coarse**: routes are described by the capabilities they require ("this
  transfer can be made by craft with more than X delta-v and deep-space
  shielding", "only rough-terrain vehicles get through here"). From that the
  sim knows which vehicles are eligible, and generates the ones a traveller
  meets on the fly.
- **Fine**: when an extant, distinct vehicle travels a route, the details are
  simulated, but only when needed or when the player wants to look.
- **Promotion**: a generic vehicle the player passes in the street becomes a
  distinct, real vehicle when clicked, and can be kept in the ontology.

## 2. What already exists to build on

- **The layer overview already sets the goal.** Logistics should "connect
  production demand to movement without simulating every person, vehicle,
  and cargo load at full resolution all the time", through corporal journeys
  and aggregate throughput "without resolving the same demand twice". It
  adds staged journey planning from a vehicle card, routes expanded with
  support stages rather than rejected, situated modes (person-task,
  producer-route, regional influence), road and river corridor strips, and
  route validity per domain (ground: shared map parent; orbital: shared
  parent body; interplanetary: same star system; interstellar: the
  stellar-neighbour graph). Section 16 asks for spacecraft orbital state,
  delta-v, nodes and a hand-off from map to orbit at the atmosphere boundary.
- **People already have the three tiers.** `SiteSimulation.resolve()` shows
  authored persons in full, a few stable runtime representatives per pop
  (ids and traits seeded from the pop), and the rest as one aggregate line;
  each presence carries `simulation_detail` (full, lightweight, aggregate),
  `source_pop` and `ontology_status`. Vehicles can use the same shape.
- **Lazy materialisation has precedents**: blueprint rooms become entities on
  demand (`building_sim.materialize_blueprint_room`), the biosphere keeps
  stands as records and simulates a few individuals, the formation sim has
  `promote_group`.
- **Vehicles**: design entities with installed components and qualitative
  ports; `VehicleSimulation` (runtime: waypoints, cargo, states);
  `derive_capabilities()` (mass, a thrust proxy, lift area);
  `AircraftFlightSimulation`; `SiteSimulation` spawns a cart on a schedule
  from `inbound_logistics_routes`. No typed thrust, specific impulse or
  propellant yet.
- **Routes**: `route_waypoints` on logistics records,
  `simulations/map/road_corridor_window.py` (rolling strip, not wired to the
  UI), river and waterway locations. No road network graph.
- **Space**: transfer windows (`simulations/space/transfer.py`) and the slim
  panel; the spacecraft navigation study (patched conics, nodes,
  `PropulsionState`).
- **Rules that shape this**: the ontology is the only durable source;
  ontology changes are staged and durable only when the user saves; a
  simulation mode is a viewpoint, not a second truth.

## 3. The model

### 3.1 Links: where something can travel

A link is a way between two places in one domain at one scale.

| part | content |
|---|---|
| domain | road, path, off-road, waterway, sea, air, orbital, interplanetary, interstellar |
| ends | locations in the existing hierarchy, valid per domain as in overview section 15 |
| requirements | thresholds in the shared vocabulary (3.3) |
| cost | duration, propellant or energy, risk |
| availability | when it is open: transfer windows, seasons, floods, ice, weather |

Links are derived, not authored one by one, and cached per scope:

- **Space**: from orbital mechanics. A window gives the delta-v and the
  flight time; the flight time gives life support; leaving a planet's
  magnetosphere gives the shielding class. Earth to Mars, 2026.824: delta-v
  at least 5.68 km/s from low orbit (3.63 escape, 2.05 capture), 853 cycles
  of life support, deep-space shielding.
- **Ground and water**: from the map: terrain class, slope, water depth and
  current, vegetation, built roads, bridges and fords. A corridor over rough
  ground without a road requires rough-terrain mobility, a slope limit and a
  wading depth at the ford.
- **Air**: from airfields and the atmosphere layers: runway length, range,
  ceiling.
- **Infrastructure** (ports, stations, airfields, roads) both opens links and
  offers support stages (refuelling, transfer of cargo).

### 3.2 Capability profile: what a vehicle can do

The same vocabulary as the requirements, so matching is a comparison.

- **Design profile**: from the vehicle design (extending
  `derive_capabilities()`): mobility class, slope, wading or draft, runway
  need, range and endurance, speed, delta-v (rocket equation from the
  propulsion figures), shielding class, life-support days, cargo and crew,
  atmosphere entry and ascent, docking.
- **Instance profile**: the distinct vehicle's actual state: propellant on
  board, cargo, wear, giving its real delta-v and range now.
- **Matching**: a profile is eligible for a link when it meets every
  requirement. For a journey of several links that fails, logistics expands
  the route with support stages instead of rejecting it (overview
  section 14).

### 3.3 One vocabulary for requirements and capabilities

A controlled list per domain, in the style of the component port resource
types, held as ontology schema fields with an author script in `tools/` (the
ontology stays the only source). First terms, to be confirmed:

- ground: `terrain_class` (paved, gravel, rough, any), `max_slope_deg`,
  `wading_depth_m`, `ground_pressure_kpa`, `axle_load_t`
- water: `draft_m`, `current_m_s`, `ice_class`
- air: `runway_length_m`, `range_km`, `ceiling_m`
- space: `delta_v_m_s`, `shielding_class` (none, orbital, deep_space),
  `life_support_days`, `atmosphere_entry`, `ascent_from_surface`, `docking`
- all: `cargo_t`, `crew`, `duration`

### 3.4 Coarse detail: traffic as an eligible population

- On each link, traffic is a population: vehicle designs times counts per
  unit of time. It comes from logistics demand (production, markets, pops,
  factions) where that exists; until then from a generic density by context
  (settlement density, road class, era, faction), labelled as such.
- Eligibility filters it: a design whose profile meets the link's
  requirements and that is available there (year, faction, technology,
  market), through the shared affordance resolver the overview asks about.
- What the player meets is **sampled deterministically**: seed = link,
  time bucket and stretch. The same stretch at the same time shows the same
  vehicles; nothing about them is stored. This is the pop-representative
  pattern applied to vehicles.
- Coarse motion has no physics: a position along the link from schedule and
  speed. In space a generic craft rides the window's transfer arc, which is
  exactly a `TransferLeg`.

### 3.5 Fine detail: a distinct vehicle travels

- A distinct vehicle is an ontology vehicle entity: an instance of a design,
  with owner, operator, cargo, propellant and its journey.
- What is stored is the **journey plan**, not a ticking position: links,
  departure times, and in space the orbit state at an epoch plus manoeuvre
  nodes. The position at any time follows from plan and clock, as the
  planets' do. That keeps runtime state out of the store (rule 2) while the
  journey itself is a durable fact once the user saves.
- When it is looked at, the domain realization simulates it: ground,
  `VehicleSimulation` along waypoints and the corridor strip; air,
  `AircraftFlightSimulation`; space, the navigation sim (patched conics,
  nodes, propellant by the rocket equation). Before departure its instance
  profile is checked against the links; consumption is updated as it goes.
- When nobody looks, even a distinct vehicle runs coarse, along its plan.

### 3.6 Promotion: generic to distinct

- Clicking a sampled vehicle creates a staged vehicle entity from the sample:
  design, seeded name or registration, owner and operator from the
  population's source, cargo, propellant, and its current link and place on
  it. It becomes durable when the user saves the ontology.
- The same seed means the entity matches what the player saw.
- From then on it is counted out of the population, so the same demand is
  not resolved twice.

## 4. Space as one domain

- **Links**: orbital (same parent body), interplanetary (the transfer
  windows between siblings), later interstellar (the neighbour graph).
  `transfer.py` already computes the delta-v and duration of each; the rules
  for shielding and life support follow from domain and duration.
- **The slim transfer panel is a coarse-level view**: the interplanetary
  links out of the selected body. A later row can add the requirement
  summary and the number of eligible designs.
- **Coarse traffic**: generic craft on transfer arcs in the space view,
  sampled from the eligible designs; clicking one promotes it.
- **Fine detail**: the spacecraft navigation study's slices N1 to N6 are the
  space realization. Their substance is unchanged; their section 8 now reads
  as this section 3.5 (store the plan, staged).

## 5. Where to start

| slice | what | done when |
|---|---|---|
| L1 vocabulary and profiles | the controlled vocabulary as ontology schema; `CapabilityProfile` from a design; matching | tests on an air design (the MiG-21), a ground cart and a written test craft |
| L2 space link requirements | delta-v, duration, life support, shielding per window | the panel's Earth to Mars window carries its requirements |
| L3 coarse traffic and sampling | population per link, deterministic sampling, generic vehicles drawn | the same stretch and time show the same vehicles |
| L4 promotion | click a generic vehicle, stage a distinct vehicle entity | it matches the sample and leaves the population |
| L5 space fine detail | navigation slices N1 to N6 for distinct craft | as in that study |
| L6 ground links | requirements from map rasters, corridor mode, same traffic and promotion | a rough-terrain corridor admits only matching designs |
| V vehicle fields | typed propulsion and mobility fields, per-vehicle propellant and cargo | its own task; L1 needs at least the space and ground terms |

Air and waterways follow L6 with the same machinery.

## 6. Decisions for the owner

- **First domain** for the general machinery: space (the link generator
  exists, and it is the current focus) or ground (where "a vehicle in the
  street" lives, and the lumber-site routes already run).
- **Vocabulary**: confirm the first terms and that they live as ontology
  schema fields with an author script.
- **Traffic before markets exist**: generic densities by context, clearly
  labelled (recommended), or no traffic until production and markets feed it.
- **Promoted vehicles after their journey**: stay as they are, or archive.
- **Distinct vehicles off screen** run coarse along their plan (recommended).

## 7. Progress

**2026-10-28: space first** (owner: ground is not ready yet). Built, with
`tests/test_logistics_capabilities.py`:

- `simulations/logistics/capabilities.py`: the space terms
  (`delta_v_m_s`, `shielding_class` none < orbital < deep_space,
  `life_support_s`, `atmosphere_entry`, `docking`) and `shortfalls()`,
  which lists each requirement a profile misses or cannot show. Life
  support is in seconds and shown in cycles; cargo and crew terms wait
  until a link asks for them.
- `simulations/space/propulsion.py`: `PropulsionState` and the rocket
  equation (navigation slice N2's budget).
- `simulations/logistics/vehicle_profiles.py`: a design's space profile
  from typed fields on its installed components' entities (proposed names:
  `thrust_n`, `specific_impulse_s`, `propellant_capacity_kg`,
  `shielding_class`, `life_support_s`, `docking`, `atmosphere_entry`;
  structural features may carry shielding and entry). Engines count only
  when wired to a tank; a term no component shows stays unknown. Dry mass
  is component mass only; the hull's own mass is not modelled yet.
- `simulations/logistics/links.py`: `Link` and `link_from_transfer_window`
  (L2's core). The 2026 Earth to Mars window asks 5.68 km/s, deep-space
  shielding and 312 days of life support; a test craft of 8.5 t dry with
  20 t of propellant at 450 s (5.34 km/s) falls short on delta-v alone, and
  a second tank makes it eligible.

The same day, on the owner's go-ahead, `tools/author_component_spaceflight_fields.py`
added the seven fields to `schema_components` (section Spaceflight; backup
in `artifacts/component_spaceflight_fields/`; OWL checkpoint exported;
recorded in `docs/entity_field_overview_item_component_v003.md`). No
component was given values: they are authored as designs need them.

Then the first design using them: `tools/create_test_craft_pathfinder.py`
authored `veh_test_craft_pathfinder` (system spacecraft, verification
sample) and six `comp_test_pathfinder_*` component entities: two 1.2 MN /
375 s engines, two 150 t tanks, a habitat with 2 years of life support, a
deep-space storm shelter, a docking port and a flight deck on a truss
spaceframe; backup in `artifacts/test_craft_pathfinder/`. Read back from
the store, its profile is 7.78 km/s, deep-space shielding, 2 years of life
support, docking, no atmosphere entry. Against the next windows from Earth
after 2026.000 (low orbit to low orbit):

| target | window | needs | Pathfinder |
|---|---|---|---|
| Venus | 2026.575 | 6.85 km/s, 397 cycles | eligible |
| Mars | 2026.824 | 5.68 km/s, 853 cycles | eligible |
| Mercury | 2026.325 | 12.65 km/s | delta-v short |
| Vesta | 2026.602 | 8.60 km/s | delta-v short |
| Ceres | 2027.113 | 9.17 km/s | delta-v short |
| Jupiter | 2026.812 | 24.21 km/s, 2968 cycles | delta-v and life support short |

**The panel shows it** (same day): under the title, the requirements every
row shares (deep-space shielding for an interplanetary window, orbital for
moon to moon; life support for the flight); each row ends with how many
spacecraft designs meet that window; the footer names each eligible design
with its destinations and counts the designs that have no figures yet.
`link_from_transfer_window` takes the domain (interplanetary when the origin
orbits a star, orbital otherwise); `spacecraft_design_profiles` lists every
design of a spacecraft class, cached until the repository changes. Earth
selected in the real app, year 2400: Mars and Venus "1 craft", footer
"Pathfinder Test Craft: Mars, Venus" and "23 spacecraft designs lack
figures".

Building the 24 profiles first took 2.05 s on selection, 1.2 s of it for
one design with no installed parts, for which the designer generated a
default layout and hull art. A design with nothing installed now returns
its structural features alone, and the designer gets only the keys the
profile reads: 73 ms for all 24, and the click that opens the panel fell
from 2.31 s to 0.28 s.

Next in the plan: L3, traffic as an eligible population sampled on the fly.

**Journeys along a transfer route** (same day; owner put the collection
workspace aside for this). A first fine-detail slice of section 3.5:

- `simulations/space/conics.py`: a coast arc from a position and velocity
  at a time, read at any time; ellipses and hyperbolas, either direction
  (navigation slice N1's core).
- `simulations/logistics/journey.py`: `Journey.plan(craft, window,
  propulsion)` keeps the plan only; the craft is parked at the origin before
  departure, on the window's transfer arc in flight, at the target after
  arrival. Burns are impulsive (escape, capture) and spend propellant by the
  rocket equation.
- Space view: a window row in the transfer panel selects it; the selected
  window lists the checked craft that can fly it as "Start journey with
  ..." buttons. A journey panel below shows route, dates, status (waiting /
  in flight with progress / arrived), delta-v and propellant before and
  after, with "Warp x10", "Warp /10", "End journey" and, while waiting,
  "Jump to departure". The renderer draws the arc and the craft. The
  journey lives for the session only; storing it as a staged plan comes
  later.

Walked in the real app through the panel's own clicks: Earth to Mars with
Pathfinder, year 2400 window (departs 2400.630, arrives 2401.392, 5.59 of
7.78 km/s, propellant 300.0 t to 33.5 t), jump to departure, warp to
x100,000, in flight 50% at 2401.012 with the craft drawn halfway along the
arc, arrived at Mars. Two faults found and fixed on the way: the shared UI
reset emptied the panel's click areas before every click was tested (a
click went through to the map and dropped the selection), and buttons
moved under the cursor when "Jump to departure" disappeared at departure
(it is now last).

**Patched conics** (same day, owner's pick over storing journeys). The
journey now flies five phases, each in its own body's frame: parked in a
200 km circular orbit at the origin, escaping on a departure hyperbola to
the edge of the origin's sphere of influence, cruising around the parent,
approaching on an arrival hyperbola, and in a 200 km orbit at the target
after the capture burn. `conics.hyperbola_through` solves each hyperbola so
its velocity at the sphere's edge is what the cruise needs there, and six
rounds of refinement make the legs meet (Earth to Mars: 0.0 m and 0.0000
m/s mismatch at both edges), so there are no course corrections. Burns
come out close to the window's estimate (2026 window: escape 3,586 m/s
against 3,626, capture 2,036 against 2,051). The panel names the phase;
"Follow craft" keeps the camera on the craft (`get_camera_focus`, read by
`CameraController.apply_constraints` every frame). Each leg is drawn round
its body where that body is now, cruise in strong green, hyperbolas
lighter, parking orbits dim. Walked in the real app, year 2400 window:
parked with the camera on the craft, escaping along the departure
hyperbola beside Luna's orbit, cruising halfway, approaching Mars past
Phobos and Deimos, in orbit at Mars; escape 3.76 + capture 1.78 of 7.78
km/s, propellant 300.0 t to 34.6 t.

**Manoeuvre nodes** (same day): a journey is now a parked start plus nodes
whose path is predicted through every sphere of influence; editing a node
in the journey panel re-predicts the flight and shows whether the craft is
captured, flies by, hits the surface or misses. Details in
`docs/space_spacecraft_navigation_v001.md` section 9.
