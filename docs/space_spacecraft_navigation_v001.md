# Space Sim: spacecraft navigation (study v001)

Status: study, 2026-10-28. Nothing implemented. Builds on
`docs/space_transfer_windows_v001.md` (planar ephemeris, Lambert, transfer
windows, interplanetary calendar).

Later the same day the owner placed this inside a general logistics
simulation (`docs/logistics_simulation_concept_v001.md`): this study is now
the fine detail of the space domain there. Section 8 is replaced by that
concept's section 3.5: a distinct craft stores its journey plan (orbit state
at an epoch plus nodes), staged and durable when the user saves, not a
ticking position.

## 1. Goal and layers

The owner's target is a version of the space view centred on a spacecraft,
opened later from a computer or navigation station inside the vehicle sim.
In it the player sees the craft's delta-v, the transfer windows from where
the craft is, and sets a custom trajectory with manoeuvre nodes as in KSP.
For now the work is the simulation that supplies that view, shown in a
generic view.

Three layers, each only reading the one below:

1. **Vehicle sim** supplies what the craft can do: masses, engines,
   propellant on board (a `PropulsionState`).
2. **Navigation sim** (new, pure Python and numpy, no pygame): the craft's
   trajectory, its delta-v budget, the manoeuvre nodes, the predicted path
   with its events, and transfer windows from the craft's position.
3. **Views** draw it: a generic spacecraft-centred space view now, the
   navigation-station screen later. Neither computes anything itself.

This is the same core/realization split the vehicle sim already uses:
`VehicleSimulation.derive_capabilities()` is the core the aircraft
realization reads.

## 2. What exists

- Space sim: planets on fixed Kepler orbits (`KeplerOrbit.state_at`), time
  as seconds since J2000 (`world/interplanetary_calendar.py`), and
  `simulations/space/transfer.py` (planar Lambert, escape and capture
  burns, windows; `TransferLeg` keeps the v_inf vectors).
- Spacecraft are location entities with `location_class` `spacecraft`,
  `orbital_spacecraft`, ... or `space_station`. The space view loads them on
  a fixed Kepler orbit like a moon. A station is a hybrid: the same entity
  also carries a vehicle design (`tests/test_space_station_hybrid.py`), which
  is the natural home for a craft's engines and tanks.
- `DynamicOrbit` (semi-implicit Euler over every body) exists but one tick
  is `4.8 s * time_scale`, so it cannot hold an orbit under time warp. It is
  replaced by conics on rails below.
- Vehicle sim: `derive_capabilities()` sums component mass and a thrust
  *proxy* (engine mass x g x a fixed thrust-to-weight). Ports are
  qualitative (`fuel`, `thrust`); `thruster_component` and
  `propulsion_space` defaults exist, but there is no typed thrust, specific
  impulse, propellant capacity or propellant load anywhere, and designer
  specifications are free-text rows. **Delta-v cannot come from the vehicle
  sim yet.**

## 3. Delta-v from the vehicle sim

    rocket equation        dv = Isp * g0 * ln(m_wet / m_dry),   g0 = 9.80665 m/s2
    engines firing at once F = sum(F_i),  Isp = F / sum(F_i / Isp_i)
    propellant after a burn m_after = m_before * exp(-dv / (Isp * g0))
    burn time              t = (m_before * Isp * g0 / F) * (1 - exp(-dv / (Isp * g0)))
    stages (later)         sum of the per-stage dv, each stage dropping its dry mass

What the navigation sim needs, as one value passed in:

    PropulsionState
        dry_mass_kg          everything but propellant
        propellant_kg        what is on board now
        engines              [{thrust_n, specific_impulse_s}]   vacuum figures

What the vehicle side lacks (its own task, section 9 slice V):

- typed component fields: engine `thrust_n` and `specific_impulse_s`, tank
  `propellant_capacity_kg` and the propellant (a material reference);
- per-craft propellant load, which is operational state, not design;
- `VehicleSimulation.derive_propulsion_state()` building the value above.

These are ontology schema changes, so they come with an author script in
`tools/` and the field overview docs. Until they exist the navigation sim
takes `PropulsionState` as an argument, and tests and the generic view use
an explicitly written test craft; nothing guessed is written to the store.

## 4. Trajectory: patched conics on rails

A craft's state is `(frame body, epoch t0, r0, v0)`: position and velocity
relative to the body whose sphere of influence it is in. Planar, like the
rest of the sim.

- **Elements from state**: `h = x*vy - y*vx`, energy `v^2/2 - mu/r`,
  eccentricity vector `((v^2 - mu/r) r - (r.v) v) / mu`, `a = -mu / (2*energy)`.
  Ellipse, parabola or hyperbola.
- **Propagation**: the universal-variable Kepler solution (Stumpff
  functions C(z), S(z)); one formula for all three conic kinds. Analytic, so
  time warp costs nothing and the orbit does not drift.
- **Sphere of influence**: `r_SOI = a * (m / M)^(2/5)` per body.
  - Leaving: when `|r| > r_SOI` of the frame body, change frame to its
    parent: `r' = r + R_body(t)`, `v' = v + V_body(t)`.
  - Entering: for each body orbiting the frame body, find the first time
    `|r(t) - R_b(t)| < r_SOI_b`: sample the arc, then bisect on the
    crossing. The hierarchy (moon in planet in star) works the same at every
    level.
- **Prediction**: a list of segments `(frame body, conic, t_start, t_end,
  end reason)` where the reason is SOI exit, SOI entry, a node, impact
  (`r < radius`) or the horizon; plus events on them: periapsis, apoapsis,
  closest approach to a chosen target, SOI changes.
- **Limit**: patched conics ignore every body but the frame body, as in KSP.

## 5. Manoeuvre nodes

- **A node** is `(t, dv_prograde, dv_radial)`. Prograde is along the
  velocity relative to the frame body at `t`; radial-out is in the plane,
  perpendicular to it, away from the body. The sim is planar, so there is no
  normal component.
- **Applying**: take the predicted state at `t`, add the delta-v, predict
  again from there. Nodes chain in time order; editing one re-predicts
  everything after it. All analytic, cheap enough to redo on every drag.
- **Budget**: each node draws propellant by the rocket equation; show the
  delta-v used and left per node and in total, and flag a node that asks for
  more than is left.
- **Burn timing**: the burn time from section 3; a KSP-style countdown
  starts half of it before the node.
- **Execution, first version**: impulsive. When the clock reaches a node the
  craft's state jumps by its delta-v and the node is used up; time warp drops
  to x1 before a node. Finite burns (thrust integrated along a steering law)
  come later; they matter for low-thrust engines.
- **Node from a transfer window**: for a craft in a parking orbit of radius
  `r_p`, the window gives `v_inf` (a vector) on its departure date. The
  departure hyperbola has `e = 1 + r_p * v_inf^2 / mu`, and its outgoing
  asymptote lies `arccos(-1/e)` ahead of periapsis. So the burn goes at the
  longitude `angle(v_inf) - arccos(-1/e)` (counter-clockwise motion), on the
  craft's first pass there near the departure date, with
  `dv = sqrt(v_inf^2 + 2*mu/r_p) - v_now`. Patched-conic offsets leave a
  small miss at the target; a correction node fixes it, as in KSP.
- **Capture node**: in the target's sphere of influence the predicted
  hyperbola gives the periapsis; a retrograde node there, sized like
  `capture_burn`, ends in orbit.

## 6. Transfer windows from the craft

The search in `transfer.py` stays as it is. What changes:

- the origin is the craft's current frame body;
- the escape cost comes from the craft's actual orbit (its speed at
  periapsis), not an assumed 200 km circular orbit;
- each window is compared with the delta-v left, and offers "make node"
  (section 5).

## 7. The generic view

A space view with the camera on the craft and the frame of its current
sphere of influence. It draws the predicted segments (one colour per
segment), nodes as handles, and events as markers; a side panel shows the
delta-v budget, the node list and the windows. Input KSP-style: click the
trajectory to add a node, drag prograde/retrograde/radial handles, or type
values. The vehicle sim's navigation station later opens the same view for
the craft it sits in.

## 8. Where the craft's state lives (decision)

Recommended: on the craft's location entity, as `orbit_state`
(`frame_body`, `epoch_s`, `position_m`, `velocity_m_s`) and
`maneuver_nodes`, written through the world model. A craft's position is
world state that other sims (the vehicle station) need. A craft without
`orbit_state`, such as an authored station, stays on its fixed elements:
two kinds of craft, not a fallback for old records. Session-only state is
the alternative if persistence should wait.

## 9. Slices

Progress 2026-10-28: N1's core (`simulations/space/conics.py`: conic from
state, ellipse and hyperbola propagation, `hyperbola_through` a sphere's
edge, circular orbits) and N2's budget (`simulations/space/propulsion.py`)
are built, and a journey along a transfer window flies in patched conics
(`simulations/logistics/journey.py`; see the logistics concept, section
7). Not yet: general SOI detection for an arbitrary trajectory, manoeuvre
nodes, and journeys stored on the craft.

Later the same day, N3 and N4: `simulations/space/trajectory.py`
(`BodyTree` of spheres of influence built from the loaded system,
`predict()` chaining conic segments that end at a node, an exit into the
parent's frame, an entry into a child's sphere found by sampling then
bisection, an impact, or the horizon; `Node(t, prograde, radial)`). A
window journey is now a parked start plus two nodes, escape and capture,
and `Journey.with_nodes()` re-predicts in 2 to 5 ms. The untouched nodes
fly the plan (Mars entered at the planned second, captured 200 km up); 5
m/s more at the escape burn turns the capture into a flyby at 489,000 km,
20 m/s less misses Mars by millions of km. The journey panel lists the
nodes with delta-v left, the outcome (captured / flyby / impact / missed
by), and for the selected node prograde (coarse and fine to 0.1 m/s),
radial and time steps, delete and add. Walked in the real app with the
whole Sol system loaded (moons and asteroids in the tree): -20 m/s missed
by 3.42 million km, +20 back to captured 200 km up. Still open: journeys
stored on the craft, dragging nodes on the map, a ghost of each planet at
its encounter time (legs round a planet are drawn where it is now, the
cruise where it will be), finite burns.

| slice | what | done when |
|---|---|---|
| N1 conics | `simulations/space/conics.py`: state to elements and back, universal-variable propagation, SOI radius | round trips; energy and angular momentum conserved; matches `KeplerOrbit` for the planets; hyperbola flight times |
| N2 budget | `PropulsionState`, rocket equation, burn time, propellant after a burn | tests with written figures |
| N3 prediction | `simulations/space/trajectory.py`: segments, SOI changes, events | a 200 km Earth orbit plus the window's escape node leaves Earth's SOI and passes near Mars at the window's arrival date |
| N4 nodes | node list, chaining, budget, node from window, capture node | tests on the Earth to Mars case |
| N5 craft in the space sim | a craft object on a navigable conic (replaces `DynamicOrbit`); nodes executed on the clock; warp stop | tests plus a driven run |
| N6 generic view | drawing and node editing | real-app walkthrough |
| V vehicle side | typed propulsion fields, per-craft propellant, `derive_propulsion_state()` | its own task; N1 to N6 run on a test craft until then |

Gravity assists come on top of N3 and N4: a flyby is two legs meeting at a
body, and with nodes a flyby can also be flown by hand as in KSP.

## 10. Decisions for the owner

- Craft state stored on the entity (recommended) or session-only.
- Impulsive burns first (recommended), finite burns later.
- Nodes with prograde and radial only, since the sim is planar.
- Which bodies' spheres of influence count: every natural body with mass
  (recommended).
- Vehicle-side field names and units: `thrust_n`, `specific_impulse_s`
  (vacuum), `propellant_capacity_kg`, a propellant material reference.
