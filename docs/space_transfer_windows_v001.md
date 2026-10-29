# Space Sim: transfer windows, the mathematics (study v001)

Status: study, 2026-10-27. Nothing implemented yet. Planets stay on their
fixed Kepler orbits; only spacecraft get orbital calculations. The first
tool is a transfer-window readout when a planet is selected in the space
view, of the form

    Year 2026, transfer window to Mars from Earth, required delta-v 5.7 km/s

Manoeuvre nodes come later and reuse the same pieces.

## 1. What the space sim had (before slice 1)

Slice 1 (section 10) has since fixed the periapsis rotation, the calendar
and the missing velocity; the rest still holds.

- `simulations/space/orbit.py` `KeplerOrbit`: 2D ellipse from `a`, `e`,
  `M0`; `mu = G * parent.mass`; mean anomaly advanced by `n * dt` and
  Kepler's equation solved by Newton. Motion is counter-clockwise.
- The periapsis of every orbit points along +x. Stored
  `argument_of_periapsis_deg`, `longitude_of_ascending_node_deg` and
  `inclination_deg` are loaded (`world/entity_loader.py`) but not used.
- The calendar year does not move the planets. `SpaceSimulation(year=...)`
  only decides which entities are active; every body starts at its stored
  `mean_anomaly_deg_at_epoch`, whatever the year, and the clock starts at 0.
- No velocity is exposed for a body.
- Sol's planets carry real osculating elements (Wikipedia infobox values,
  J2000 for the planets; the dwarf planets and asteroids come from other
  epochs). Generated planets get `a`, `e`, `M0` only; no periapsis angle.
- `DynamicOrbit` (semi-implicit Euler over every body) exists for later
  spacecraft, but one tick is `4.8 s * time_scale`, so at high time warp it
  will not hold an orbit. Spacecraft should ride conics too (section 7).

## 2. Body positions and velocities at any time (ephemeris)

For a body with `a, e, M0, varpi` around a parent with `mu`:

    n  = sqrt(mu / a^3)                       mean motion, period P = 2*pi/n
    M  = M0 + n * (t - t_epoch)               computed from absolute time, not accumulated
    M  = E - e*sin(E)                         Kepler's equation, Newton on E
    x' = a*(cos E - e),   y' = b*sin E        b = a*sqrt(1 - e^2), perifocal frame
    vx' = -a*n*sin E / (1 - e*cos E)
    vy' =  b*n*cos E / (1 - e*cos E)
    rotate (x', y') and (vx', vy') by varpi

`varpi` is the longitude of periapsis. Since the sim is planar, the 3D
orbit is projected onto the reference plane with `varpi = Omega + omega`
(ascending node plus argument of periapsis), the standard approximation for
small inclinations. Inclination itself is dropped, so plane-change costs
are not counted.

`t` must be a real date: seconds since a defined epoch (section 6).

## 3. First estimate: synodic period and Hohmann transfer

Circular, coplanar orbits of radius `r1` (origin) and `r2` (target):

    synodic period   S   = 1 / |1/P1 - 1/P2|          windows repeat every S
    transfer orbit   a_t = (r1 + r2) / 2
    time of flight   TOF = pi * sqrt(a_t^3 / mu)
    departure v_inf  v1  = sqrt(mu/r1) * (sqrt(2*r2/(r1+r2)) - 1)
    arrival v_inf    v2  = sqrt(mu/r2) * (1 - sqrt(2*r1/(r1+r2)))
    phase angle      phi = pi - n2 * TOF                target ahead of origin by phi at departure
    next window      t   = t_now + wrap(phi - phi_now) / (n2 - n1)

`wrap` brings the angle into one turn with the sign of `n2 - n1` (negative
for an inner target, where the phase angle is negative too: Venus -54 deg).
This is exact only for circular orbits. It is used as the seed for the
search and as a check.

Earth to Mars from the stored elements: S = 780 d, TOF = 259 d,
phi = 44.3 deg, v_inf 2.94 km/s out and 2.65 km/s in.

How far the phase-angle date alone is off on the real (eccentric) orbits,
measured against the Lambert optimum of section 4:

| pair | phase-angle date vs best date | dv flying the phase-angle date with the Hohmann TOF |
|---|---|---|
| Earth to Venus (e 0.017 and 0.007) | within 7 days | same as best |
| Earth to Mars (e 0.093) | 14 to 49 days off, 2026 to 2037 | 0.2 to 0.6 km/s above best |

So the phase angle is good enough as a seed but not as the answer.

## 4. The real calculation: Lambert's problem plus a porkchop search

Eccentric orbits (Mars e = 0.093) move the window by weeks and change its
cost from one window to the next. The tool to use is Lambert's problem:
given the origin's position `r1` at departure `t_d` and the target's
position `r2` at arrival `t_a = t_d + TOF`, find the conic arc from `r1` to
`r2` taking exactly TOF. It returns the spacecraft velocities `v1`, `v2` at
both ends. Then

    v_inf_dep = v1 - V_origin(t_d)
    v_inf_arr = v2 - V_target(t_a)

### Solver

Use the Lancaster/Izzo formulation (Izzo 2015, single revolution, prograde):

    c = |r2 - r1|,  s = (|r1| + |r2| + c) / 2
    lambda = +-sqrt(1 - c/s)     negative when the transfer angle exceeds 180 deg
    T = sqrt(2*mu/s^3) * TOF     non-dimensional time
    solve T(x) = T for x         T(x) falls monotonically on (-1, inf) for 0 revolutions
    ellipse   (x < 1): a = 1/(1-x^2), alpha = 2*acos(x),  beta = 2*asin(sqrt(lambda^2/a))
              T(x) = a^1.5 * ((alpha - sin alpha) - (beta - sin beta)) / 2
    hyperbola (x > 1): alpha = 2*acosh(x), beta = 2*asinh(sqrt(-lambda^2/a))
              T(x) = -(-a)^1.5 * ((beta - sinh beta) - (alpha - sinh alpha)) / 2
    (beta takes the sign of lambda)

Velocities, with `y = sqrt(1 - lambda^2 + lambda^2 x^2)`,
`gamma = sqrt(mu*s/2)`, `rho = (|r1| - |r2|)/c`, `sigma = sqrt(1 - rho^2)`:

    v_r1 =  gamma*((lambda*y - x) - rho*(lambda*y + x)) / |r1|
    v_r2 = -gamma*((lambda*y - x) + rho*(lambda*y + x)) / |r2|
    v_t1 =  gamma*sigma*(y + lambda*x) / |r1|
    v_t2 =  gamma*sigma*(y + lambda*x) / |r2|

radial along `r/|r|`, tangential along `z x r/|r|` (counter-clockwise, the
sim's direction of motion).

Why this form and not the textbook universal-variable one (Curtis,
Bate-Mueller-White): that one uses `A = sin(dtheta)*sqrt(r1*r2/(1-cos dtheta))`,
which is zero at a 180 deg transfer and divides by zero there. In 3D that
case is rare because inclinations push real transfers off 180 deg. In a
planar sim it is exactly where the cheapest, Hohmann-like transfers sit. The
Izzo form only has trouble choosing the orbit plane at 180 deg, and in 2D the
plane is fixed, so it works straight through.

For a first version, bisection on `x` (about 60 to 90 steps, vectorised
with numpy over the whole grid) is simple and safe. Izzo's Householder
iteration converges in 3 to 5 steps if speed is needed later.

### Delta-v from v_inf (patched conics)

Planet to planet is three conics stitched at the sphere of influence
(`r_SOI = a * (m/M)^(2/5)`): leave the origin on a hyperbola, the Lambert
arc around the star, arrive on a hyperbola.

    ejection from a circular parking orbit r_p:
        dv_dep = sqrt(v_inf^2 + 2*mu_p/r_p) - sqrt(mu_p/r_p)
    capture at periapsis r_p into
        a low circular orbit:  dv_arr = sqrt(v_inf^2 + 2*mu_p/r_p) - sqrt(mu_p/r_p)
        a loose ellipse to r_a: dv_arr = sqrt(v_inf^2 + 2*mu_p/r_p) - sqrt(2*mu_p/r_p - 2*mu_p/(r_p + r_a))
        flyby or aerobraking:  dv_arr = 0

`mu_p = G * mass_kg`, `r_p = radius_m + parking altitude`. Both fields exist
on Sol's planets and generated ones.

The capture choice changes the answer a lot:

| target | v_inf arr | circular capture 200 km | loose ellipse (apoapsis = half SOI) |
|---|---|---|---|
| Mars | 2.65 km/s | 2.10 km/s | 0.70 km/s |
| Jupiter | 5.64 km/s | 17.87 km/s | 0.35 km/s |

So "required delta-v" should be shown as ejection + capture with the capture
kind named, or the gas giants will read absurdly high.

### Window search

1. Seed: the Hohmann phase-angle date of section 3.
2. Coarse grid over one synodic period of departure dates around the seed
   and TOF from about 0.4 to 1.6 of the Hohmann TOF. Solve Lambert at every
   point. Cost = dv_dep + dv_arr (or C3 = v_inf_dep^2 if only the launch
   matters).
3. Refine around the minimum with a finer local grid.
4. Repeat for the next N windows by stepping one synodic period.
5. Report the departure date as a calendar year (and day), TOF, arrival
   date, dv_dep, dv_arr, total.

About 10 000 Lambert solves cover one window to within a day; numpy does
that in a fraction of a second. Results are fixed for a given body pair and
epoch, so they can be cached.

## 5. Prototype check against the stored Sol elements

A look-only numpy prototype (planar ephemeris, the Lambert above, 2-day by
140-TOF grid over 2026-2038, cost = 200 km circular orbit to 200 km circular
orbit) found these Earth to Mars windows:

| departure | TOF | C3 | v_inf arr | total dv |
|---|---|---|---|---|
| 2026-10-30 | 312 d | 9.0 km2/s2 | 2.54 km/s | 5.68 km/s |
| 2028-12-02 | 291 d | 6.8 | 2.94 | 5.78 |
| 2031-01-17 | 258 d | 5.2 | 3.28 | 5.89 |
| 2033-03-29 | 216 d | 5.4 | 3.25 | 5.88 |
| 2035-06-25 | 216 d | 10.0 | 2.38 | 5.65 |
| 2037-08-17 | 275 d | 12.9 | 1.92 | 5.59 |

The dates fall on the commonly cited real Mars windows (late 2026, end 2028,
early 2031, spring 2033, mid 2035, late summer 2037). The C3 values are
lower than real mission figures because the planar model pays no plane
change.

With the periapsis longitude ignored, as the sim draws the orbits today, the
same search puts the windows at 2027-08, 2029-10, 2031-12, 2034-01 and
2036-02: 9 to 14 months wrong.

Earth to Venus: 2026-07-30, 2028-03-05, 2029-10-16, ... (TOF about 146 d,
6.85 km/s to low circular orbit). Earth to Jupiter: every 13 months from
2026-10-24, TOF about 1000 d, C3 74 to 79 km2/s2.

## 6. What has to change before the readout can be trusted

1. Honour the periapsis longitude in `KeplerOrbit`
   (`varpi = Omega + omega`, rotate the perifocal position). Without it Sol's
   windows are wrong by most of a year and the drawn orbits are mis-rotated.
2. Put the space view on a calendar: a defined epoch, `t` = seconds since
   that epoch, planet positions computed as `M0 + n*(t - t_epoch)` from the
   view's date, the date shown and advanced by the clock. Otherwise the
   readout and the picture disagree.
3. Give `KeplerOrbit` a pure `state_at(t)` returning position and velocity,
   used by both the view and the calculator.
4. Seed `argument_of_periapsis_deg` (and the node) in worldgen so generated
   systems do not have every periapsis lined up on +x. No live worlds, so
   this is a generator change only.
5. Sol's dwarf planets and asteroids use different element epochs; give
   them J2000 elements or an epoch field before windows to them are shown.
   This is authored content, so it needs the usual care.

## 7. Later: manoeuvre nodes

The same pieces carry over. A spacecraft is a conic in the sphere of
influence it is in (state vector to elements and back, propagated
analytically like the planets, so time warp is free). At a sphere-of-
influence boundary it is handed to the next body. A node is a delta-v
vector at a time on the current conic. The window tool's answer becomes the
initial node: ejection burn at the right point of the parking orbit, so that
the departure hyperbola's asymptote lines up with `v_inf_dep`.

## 8. Gravity assists via a planet B (later)

Owner, 2026-10-27: "via Planet B" means a gravity-assist flyby at B. Direct,
Hohmann-type transfers come first; the flyby search is built on top later.

A flyby trip is two Lambert legs, origin O to B (t0 to t1) and B to target
A (t1 to t2). At B:

    v_inf_in  = v_leg1(t1) - V_B(t1)
    v_inf_out = v_leg2(t1) - V_B(t1)
    unpowered flyby needs |v_inf_in| = |v_inf_out| and a turn angle delta with
        sin(delta/2) = 1/e,  e = 1 + r_p*v_inf^2/mu_B,  r_p >= radius + safe altitude
    powered flyby (burn at periapsis):
        delta = asin(1/e_in) + asin(1/e_out), solved for r_p
        dv_fb = |sqrt(v_inf_out^2 + 2*mu_B/r_p) - sqrt(v_inf_in^2 + 2*mu_B/r_p)|

The search runs over three dates instead of two, and good flyby geometries
come round much less often than direct windows. The Lambert solves stay
cheap: leg 1 on a (t0, t1) grid and leg 2 on a (t1, t2) grid, then combine
them per t1 with plain arithmetic, so the solve count is two 2D grids, not
one 3D grid.

What the direct tool must already provide so this needs no rework:

- Ephemeris and Lambert vectorised over arrays of any shape, not just one
  departure/TOF pair.
- A leg as a value of its own (bodies, dates, positions, both velocities,
  both v_inf vectors), so a flyby is two legs that share B and t1.
- v_inf kept as vectors, not only magnitudes: the flyby turn angle is the
  angle between them.
- Cost terms as separate functions (escape, capture, later flyby), summed
  by the search, so a flyby cost slots in between.

## 9. Decisions for the owner

- Origin: which body does the readout depart from? Recommended: a "Set as
  transfer origin" action on the selected planet, after which selecting any
  sibling shows windows from it. Alternative: list windows from every
  sibling.
- Epoch: one project-wide epoch (J2000, year 2000.0) for every system, so
  `mean_anomaly_deg_at_epoch` means the same thing everywhere? Recommended.
- Calendar: decided by the owner on 2026-10-27, see section 11.
- Delta-v definition: parking altitude (default 200 km) and capture kind.
  Recommended: headline = ejection to low orbit + capture to low circular
  orbit, the KSP convention, with the loose-ellipse capture shown beside it
  so gas giants read sensibly.
- Scope: siblings around one parent only (planet to planet, or moon to moon
  in local space). Planet to a moon of another planet chains conics and
  comes later.

## 10. Implementation plan: direct (Hohmann-type) transfers

Each slice lands, is tested and checked in the app before the next starts.

### Slice 1: orbits that follow their elements and the calendar

Built 2026-10-27 (`tests/test_space_orbits.py`). Checked with an off-screen
render of Sol through the real `SpaceSimulation` and `SpaceRenderer`: the
orbits are drawn turned by their periapsis longitude, and at the real Mars
oppositions of 2027, 2029 and 2031 the sim puts Mars within about 1 deg of
directly behind Earth (2 to 3 days of motion). Found along the way: the
stored Mars entity has `start_year` 2035, so the Sol view leaves Mars out
before 2035. That is authored content and was left as it is.

- `simulations/space/orbit.py` `KeplerOrbit`: take `varpi`; add a pure
  `state_at(t)` (position and velocity relative to the parent, `t` =
  seconds since epoch); `update(dt)` advances `t` and computes `M` from it
  instead of accumulating `M`; rotate `get_path_points` by `varpi`.
- `simulations/space/system.py` `_create_orbiting_object`: pass
  `varpi = radians(longitude_of_ascending_node_deg + argument_of_periapsis_deg)`
  (missing fields count as 0); `populate_from_world_model` takes the start
  time so bodies open where they are on that date.
- An interplanetary calendar helper (section 11): seconds since epoch to
  year, month and cycle, and back. One place, used by the view, the header
  and the transfer readout.
- `simulations/space/space_simulation.py`: start time = the start of
  `year` in that calendar; `seconds_since_epoch()` = start + clock time;
  the header (`ui/ui_manager.py` `_format_sim_time`) shows the space view's
  interplanetary date when the sim provides one, and the other sims keep
  today's header until local time is designed.
- Tests (`tests/test_space_orbits.py`): calendar round trip (seconds to
  year/month/cycle and back) and the year boundary; the periapsis lies in the direction
  `varpi`; `state_at` velocity matches a finite difference of position;
  the body sits at `M0` at `t = 0` and has moved by `n * t` at a later year;
  path points pass through the periapsis.
- App check: Sol's orbits drawn rotated (Mars's periapsis toward about
  336 deg); opening the view at different years shows different planet
  positions.

### Slice 2: worldgen seeds orbit orientation

Built 2026-10-27. `_committed_body_fields` now writes
`longitude_of_ascending_node_deg` and `argument_of_periapsis_deg`, each
0 to 360 from the same seed as the mean anomaly, for planets and moons. No
authoring script lists orbit fields; the card and repository browser
already show both. Planets generated before this keep no orientation until
they are regenerated (no live worlds, no migration). The world-gen orbit
design screen stays a schematic with periapsis along +x, as it already was
for Sol's planets.

- `simulations/world_gen/world_gen_sim.py`: seed `argument_of_periapsis_deg`
  and `longitude_of_ascending_node_deg` (0 to 360) from the existing anomaly
  seed. Update the authoring schema in `tools/author_*.py` if it lists orbit
  fields. Regenerate test systems; no migration.

### Slice 3: the transfer calculator (`simulations/space/transfer.py`)

Built 2026-10-27 (`tests/test_space_transfer.py`, 11 tests). Searching
three windows takes 70 to 90 ms (49 x 33 coarse grid, two 21 x 21
refinements, 52 bisection steps per Lambert solve), so slice 4 can compute
on selection without a worker thread. From 2026.000 with Sol's stored
elements:

| pair | windows (departure, flight, delta-v to low orbit, loose capture) |
|---|---|
| Earth to Mars | 2026.824, 853 cycles, 5.68 km/s (0.65); 2028.916, 798, 5.78 (0.85); 2031.043, 707, 5.89 (1.03) |
| Earth to Venus | 2026.575, 397 cycles, 6.85 km/s (0.47); 2028.175, 410, 6.84; 2029.788, 387, 6.84 |
| Earth to Jupiter | 2026.812, 2968 cycles, 24.21 km/s (0.33); 2027.893; 2028.974 |

Also run on harder pairs without trouble: Earth to Mercury (e 0.2),
Earth to Neptune (29.5-year flights), Mars to Earth, and two orbits 2%
apart (windows 34 years apart).

Pure numpy, no pygame, nothing stored.

- `TransferBody`: id, name, `a, e, M0, varpi`, `mu`, radius, SOI radius;
  built from a space object or entity.
- `planar_state(bodies_elements, t)`: vectorised version of section 2.
- `lambert_planar(r1, r2, tof, mu)`: section 4, vectorised, 0 revolutions,
  prograde, bisection.
- `escape_burn(v_inf, mu, r_p)`, `capture_burn(v_inf, mu, r_p, r_a=None)`.
- `hohmann_estimate(origin, target, mu)`: TOF, phase angle, v_inf, synodic
  period; `next_phase_date(origin, target, after_t)`.
- `TransferLeg` (section 8's leg value) and `TransferWindow` (one leg plus
  ejection, capture and total delta-v).
- `find_direct_windows(origin, target, mu, after_t, count=3)`: seed from the
  phase-angle date; coarse grid of plus or minus a quarter synodic period by
  0.5 to 1.5 Hohmann TOF; widen if the minimum sits on the grid edge; refine
  around it; step one synodic period for the next window.
- Tests (`tests/test_space_transfer.py`, orbit elements written in the test,
  not read from the store): Lambert across exactly 180 deg between circular
  orbits returns the Hohmann v_inf; a Lambert arc propagated by Kepler for
  its TOF ends on `r2`; Earth to Mars finds the 2026 window within a few
  days of 2026-10-30 at about 5.7 km/s; Earth to Venus gives a negative
  phase angle; windows come out in date order, one per synodic period.

### Slice 4: the readout in the space view

Built 2026-10-27, reshaped 2026-10-28 on the owner's direction: a slim
panel of its own, apart from the selection card, holding only transfer
windows. Selecting a body lists the next window from it to every natural
body on a sibling orbit (planets, dwarf planets, moons, asteroids, comets),
soonest first (`SpaceSimulation.get_transfer_panel_lines`, drawn by
`ui_manager` under the top-right buttons). One target is solved per frame,
so the list fills in over a few frames; flights of a year or more read in
years. The first version's "Set as Transfer Origin" action, card lines and
origin marker were removed. Earth selected in the real app (read-only
driver run), year 2400, filled in 0.4 s:

    Transfer windows from Earth
    2400.050  Uranus  14.62 km/s, 16.2 years
    2400.056  Saturn  18.19 km/s, 6.6 years
    ...
    2400.630  Mars  5.59 km/s, 762 cycles
    2400.657  Venus  6.84 km/s, 391 cycles
    ...

The walkthrough found one bug, fixed: the input router also hands the
mouse release of a card-button click to the simulation, and the space view
picked empty space on it and dropped the selection. The space view now
selects on press only. Other simulations still receive that release.

Follow-up the same day: the time bar under the space header now runs
through the current month, ruled 0, 25, 50, 75, 100 cycles passed (the
sim supplies `timeline_labels`; other sims keep 00:00 to 24:00). Checked in
a read-only real-app frame. (An origin marker was added the same day and
removed with the origin action on 2026-10-28.)

- Selecting a planet whose sibling is the chosen origin adds lines to
  `get_selection_inspector_payload`, for example
  `Year 2026.826: transfer window to Mars from Earth, delta-v 5.7 km/s (eject 3.6, capture 2.1), 854 cycles`.
- The payload is read every frame, so windows are computed once per
  selection and cached per (origin, target), and recomputed only when the
  view's date passes the first listed departure. Measure the solve time;
  move it to a worker thread only if it hitches the frame (more than about
  100 ms).
- Works in both scopes: planets around the star, and moons in local
  planetary space.
- App check per the UI-wiring rule: select origin and target in the running
  app and read the lines, not just the unit tests.

### After that

- Optional: draw the transfer arc of the next window in the space view.
- Gravity-assist search (section 8) on the same legs.
- Manoeuvre nodes (section 7).

## 11. Interplanetary calendar

Owner, 2026-10-27: the setting does not run on 365-day years. The
interplanetary year is split into 1000 cycles, grouped into 10 months of
100 cycles. It is always shown against a planet's local time, which gets
its own system adapted to local circumstances later; local time is out of
scope here.

Confirmed by the owner on 2026-10-27, built in
`world/interplanetary_calendar.py`:

- Year length: the Julian year, 365.25 days of 86 400 s = 31 557 600 s.
  Year numbers stay in step with Earth's history and Sol's J2000 elements;
  one cycle is 31 557.6 s, about 8 h 46 min.
- Epoch: year 2000 starts at J2000 (2000-01-01 12:00), the epoch of the
  orbit elements. Year Y starts at `(Y - 2000) * 31 557 600 s`.
- Months numbered 1 to 10 (owner's choice) and, to match, cycles 1 to 100
  within a month, like days of a month.
- Short form: the year to three decimals, the thousandths that have passed.
  Long form counts from 1, so `2026.826` = Year 2026, Month 9, Cycle 27.
- Durations in cycles (a 312-day flight is 854 cycles), or in years for
  long ones.

Section 5's Earth to Mars windows in this calendar:

| departure | interplanetary date |
|---|---|
| 2026-10-30 | 2026.826 (Month 9, Cycle 27) |
| 2028-12-02 | 2028.918 (Month 10, Cycle 19) |
| 2031-01-17 | 2031.043 (Month 1, Cycle 44) |
| 2033-03-29 | 2033.238 (Month 3, Cycle 39) |
| 2035-06-25 | 2035.478 (Month 5, Cycle 79) |
| 2037-08-17 | 2037.624 (Month 7, Cycle 25) |
