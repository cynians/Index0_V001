# Volatile budget v001 — the element distribution decides air, seas and ices

Status: implemented 2026-09-24 (`simulations/world_gen/volatile_budget.py`).
Tests: `tests/test_volatile_budget.py`.

## 1. Principle

The planet's element distribution is the first input of world generation and
everything after it follows from it: the material roster (see
`entity_field_overview_material_v001.md` §8), and now also the atmosphere,
the surface temperature, which liquid forms seas and which volatiles freeze.
Earth's composition at 1 AU must give an Earth-like planet; the same
composition closer to the Sun must give Venus; a Titan-like icy inventory far
out must give nitrogen air and methane seas, not water oceans.

The element list is the **whole surface inventory**: crust, hydrosphere and
atmosphere together. Earth's is 0.45 % H (oceans and rock-bound water), 0.32 %
C (carbonate rock), 0.022 % N (the air). Unlisted elements take the Earth
upper-crust background (the ontology `earth_upper_crust_abundance_ppm`, with a
built-in fallback for the volatile elements).

There is no legacy path for rocky worlds any more. "Surface Water" and
"Volatiles" on the first screen are **derived, read-only** values; gas and ice
giants keep the envelope model.

## 2. Where it sits

```
elements + size + tectonics + orbit
        │
        ▼
volatile_budget.derive_volatile_budget ──► seed (water_fraction, volatile_inventory,
        │                                        surface_fluid, surface_liquid_depth_m,
        │                                        frozen_ocean_depth_m, volatile_budget,
        │                                        crust_composition.volatile_envelope_percent)
        ▼
atmosphere.derive_atmosphere_model   composition, pressure, temperature, class label (clouds/haze)
interior_regime                      liquid water / alternate-fluid flags from the budget
terrain_seed                         global liquid depth + fluid (hydrology.surface_fluid);
                                     frozen water >= 100 m fills basins, less is polar ice
ice-albedo pass (sim)                ice sheets capped at water depth / 1.5 km of the surface,
                                     coldest cells first (icy crusts uncapped: ice is bedrock)
water_cycle / heightmap              unchanged: flood the hypsometry with that depth
true_color                           sea colour per fluid; thick hazes (Titan orange, Venus
                                     sulfuric) tint the disc by their opacity
material_chemistry                   rock chemistry = inventory − air/seas/surface ices
```

`WorldGenSimulation._apply_element_volatiles` runs at the end of both seed
builders (`_current_seed_values`, `_coerce_seed_payload`) and caches the
budget on an input fingerprint (`budget_input_key`: element rows, size,
tectonics, age, albedo, eccentricity, luminosity, semi-major axis).

## 3. Model

1. **Inventory.** Reservoir mass = crust thickness × area × density (ice-rich
   crusts are lighter). Element mass fractions give moles.
2. **Speciation — oxygen budget.** Oxygen first makes the cation oxides
   (ferrous iron). Iron can give its oxygen back down to metal (the
   iron–wüstite buffer, `IRON_REDOX_BUFFER`), so a rock-dominated inventory
   only turns reducing when it is short of oxygen beyond what its iron can
   supply. Then hydrogen → H2O, carbon → CO → CO2 (one oxygen before the
   second: oxygen-short inventories outgas CO), sulfur → sulfate. Hydrogen
   left over makes CH4 (with carbon), NH3, H2S, H2. Redox state: oxidized
   (enough oxygen for all volatiles), reducing (methane/hydrogen or less than
   half the oxygen needed), else intermediate.
3. **Surface exchange** by regime (`EXCHANGE_FRACTIONS`): active (plates),
   stagnant lid, inactive, icy. Water beyond the rock-bound 1.2 wt % is at the
   surface; on icy worlds (≥ 30 % water, T_eq < 200 K) the water ice is the
   crust itself, not a sea.
4. **Escape.** Jeans escape of light gases; energy-limited XUV loss of free
   H2 and He (`XUV_FLUENCE_1AU_J_M2`, efficiency 0.1); a non-thermal loss
   exp(−k·F·exp(−(v_esc/v0)²)) that strips small, strongly irradiated bodies
   (Mars keeps a few percent; Earth and Venus nearly all), applied to surface
   water on non-icy worlds too.
5. **Climate.** Surface temperature = the first stable radiative equilibrium
   above the bare-rock temperature (scan + bisection). At each temperature
   every condensable is capped by its saturation vapour pressure
   (Clausius–Clapeyron from its triple point, none above the critical point,
   relative-humidity caps for minor condensables) and the rest condenses. A
   grey two-stream greenhouse T_s = T_eq (1 + 0.75 τ)^¼ with τ from H2O
   (saturating: water bands close while windows stay open), CO2, CH4, NH3,
   SO2 and pressure broadening/collision-induced absorption.
6. **Runaway greenhouse** is explicit: absorbed starlight above the
   Simpson–Nakajima limit (282 W m⁻²) keeps a wet planet's oceans as steam
   and its hydrogen escapes (`STEAM_WATER_LOSS_GYR`). A CO2 greenhouse hot
   enough to boil the oceans (steam > 10 % of the air above 340 K) does the
   same.
7. **Carbonate–silicate cycle.** With open oceans (ramping in between 253 and
   273 K) on any non-icy world (open water on rock forms carbonates whatever
   the tectonics; tectonics decides how much carbon comes back), weathering
   regulates CO2 at
   p0 · open⁻² · exp((288 K − T)/7 K), the Walker–Hays–Kasting balance with
   β = 0.5; everything above is locked in carbonate rock. An Earth moved
   outward builds a CO2 greenhouse instead of freezing solid.
8. **Sinks and labels.** Sulfur gases rain out over water and are
   photochemically removed in cold air. Abiotic O2 stays trace (biology owns
   O2). The dominant surface liquid names `surface_fluid` (water,
   methane_ethane, liquid_nitrogen, liquid_carbon_dioxide, …); the class label
   (`temperate_nitrogen`, `runaway_co2`, `methane_nitrogen`, `dry_co2`,
   `exosphere`, …) only drives clouds, hazes and colour.
9. **Rock chemistry.** The element mass in air, seas and surface ices
   (`envelope_element_percent`) is stored on the composition as
   `volatile_envelope_percent`; `planet_element_distribution` removes it, so the
   material roster sees rock (Earth's 0.45 % H inventory leaves ~0.15 % in
   its rocks, the same as the material reference).

## 4. Templates and randomizer

* Earth-like presets list the full inventory (`silicate_terrestrial`: H 0.45,
  N 0.022, O raised to oxidize them). `ocean_world` H 0.9;
  `desiccated_former_ocean` H 0.05 (below the rock-bound level even under eccentric jitter) and C 0.01 (thin air);
  `runaway_greenhouse_terrestrial` dry with C 0.6.
* Catalog presets that do not list H/C/N get them from their water range and
  volatile preset (`_fill_template_volatile_elements`,
  `hydrogen_percent_for_water_index`, `preset_volatile_elements`), with the
  oxygen that water and CO2 need. Hycean worlds list excess hydrogen.
* The randomizer keeps each preset's oxygen-to-demand ratio
  (`_rebalance_oxygen`): oxygen follows the jittered cations instead of being
  an independent dial that flipped Earth-like seeds into methane worlds.
* `set_volatile_targets(water_index, preset)` pins a diagnostic world to a
  water/pressure family (used by the headless `earthlike_constraints`).

## 5. Calibration (midpoint seeds)

| Inventory | Orbit | T_s | P | Air | Surface |
|---|---|---|---|---|---|
| Earth | 1 AU | 288 K | 0.99 bar | N2 98 %, Ar 0.9 %, H2O 0.8 %, CO2 ~300 ppm | water, ~2.6 km global layer |
| Earth | 0.72 AU | ~700 K | ~52 bar | CO2 98 %, N2 2 %, SO2 ~150 ppm | none (runaway, water lost) |
| Earth | 1.52 AU | ~259 K | ~1.2 bar | N2 85 %, CO2 14 % | frozen ocean, open tropics |
| Earth + 0.1 % N | 1 AU | ~305 K | ~4.5 bar | N2 | water (warmer, no runaway) |
| Titan-like icy | 9.54 AU | 93 K | ~1 bar | N2 93 %, CH4 7 % | methane–ethane seas on water-ice crust |
| Mars crust | 1.52 AU | 215 K | 0.023 bar | CO2 79 %, N2 20 % | water ice ~13 m |
| Moon-sized | 1 AU | 255 K | 0 | — | airless |

Observed: Earth 288 K/1.013 bar; Venus 737 K/92 bar; Titan 93.65 K/1.467 bar
with 5.65 % CH4 near the surface (Huygens); Mars ~0.006 bar. The budget gets
Venus's regime but not its full pressure (Earth's carbon at stagnant-lid
exchange); Titan's pressure is low by ~30 %.

## 6. Known gaps

* `planetary_physics` gives small icy bodies too much gravity (Titan-like g
  0.33 vs 0.14), so Titan retention and Europa/Ganymede-class trace
  atmospheres (a few mbar) come out generous.
* No photochemistry: methane's ~10–30 Myr lifetime, hazes' anti-greenhouse,
  CO oxidation over water. Warm methane worlds keep too much CH4.
* Grey single-column climate: no latitudinal collapse of CO2, no clouds
  feedback, no seasonal condensation cycles (Mars caps).
* Argon is a crustal background, not radiogenic from potassium.
* No history: a desiccated world does not remember carbonates from its wet
  past; its carbon is whatever the elements say.
* Subsurface oceans of icy moons are not modelled (the ice crust is bedrock).
* The material roster is redox-blind: a reducing Titan-like world still lists
  carbonates, CO2 ice and hematite; the budget's `speciation` should gate
  them (and add organic/tholin sediments).
* Mars-like worlds render grey basalt, not rust: the true-colour
  `oxidized_dust` treatment only applies without material layers, and no
  oxidized-dust surface cover exists for dry, oxidized, aeolian worlds.
* Crater density on thick-atmosphere icy worlds (Titan) stays "moderate";
  methane rain and haze fallout should erase more.

## 7. Sources

* Walker, Hays & Kasting (1981), JGR 86, 9776 — carbonate–silicate feedback.
* Goldblatt, Robinson, Zahnle & Crisp (2013), Nature Geoscience 6, 661 —
  runaway greenhouse radiation limit ~282 W m⁻².
* Goldblatt et al. (2009), Nature Geoscience 2, 891 — nitrogen-enhanced
  greenhouse warming.
* Innes, Tsai & Pierrehumbert (2023), ApJ — runaway greenhouse on hycean worlds.
* Watson, Donahue & Walker (1981), Icarus 48, 150 — energy-limited escape;
  Ribas et al. (2005), ApJ 622, 680 — solar XUV history.
* Fulchignoni et al. (2005), Nature 438, 785 (https://www.nature.com/articles/nature04314) — Titan surface 93.65 K, 1.467 bar.
* https://en.wikipedia.org/wiki/Atmosphere_of_Titan — CH4 5.65 % near the surface.
* https://en.wikipedia.org/wiki/Methane_(data_page) — triple 90.67 K / 0.117 bar, critical 190.6 K / 46 bar, ΔH_vap 8.17 kJ mol⁻¹.
* Fegley (2004), Venus, Treatise on Geochemistry — Venus atmospheric carbon ~1.25e20 kg.
* https://www.sciencedirect.com/science/article/abs/pii/S0012821X00001953 — Earth's crustal carbon inventory.
* Taylor & McLennan (2009), Planetary Crusts — average Martian crust.
