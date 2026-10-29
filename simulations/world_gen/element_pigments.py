"""Element pigments: how a planet's trace elements colour its ground.

Phenomenon card (copper, the first element with authored data)
-----------------------------------------------------------------
* **Real examples.** Green and blue copper oxide zones over porphyry and
  sediment-hosted deposits: chrysocolla, brochantite and atacamite in the
  Atacama Desert, malachite and azurite at Bisbee and on the dolomitic shales
  of the Katanga Copperbelt, native copper in the sulfur-poor basalts of the
  Keweenaw.  Humid ground over the same ore shows a red-brown iron "leached
  cap": the copper is gone (Anderson 1982; Chavez 2000, SEG Newsletter 41;
  Reich & Vasconcelos 2015, Elements 11).
* **Amounts.** Earth's upper crust holds ~28 ppm Cu (Rudnick & Gao 2003);
  basalt ~90, granite ~10, shale ~45, limestone ~4 (Turekian & Wedepohl
  1961).  A planet scales each rock's content by its own enrichment over
  that reference (``trace_element_ppm`` on the rock cards).
* **Primary hosts.** Copper is chalcophile and takes sulfur before iron
  does: chalcopyrite while sulfur lasts, then the sulfur-poorer bornite and
  chalcocite, then native copper (the element card's ``primary_hosts``).
* **Release.** Sulfides and native copper oxidize in years to millennia
  where air and moisture reach them; the rate goes as the square root of
  dissolved O2 (Williamson & Rimstidt 1994, Geochim. Cosmochim. Acta 58).
  A reducing air keeps them fresh.  Sulfides oxidize in moist air too; a
  metal corrodes only while its surface is wet (the "time of wetness" of
  ISO 9223; Leygraf & Graedel 2000): in dry air copper keeps its metal under
  a brown cuprite tarnish (its weathered colour), in wet air it goes green.
* **Loss.** Released Cu2+ is carried off by the water passing through the
  weathering zone: tau = depth (theta + rho_b Kd) / q, with Kd from the
  element's sorption against pH (Sauve, Hendershot & Allen 2000).  Sulfide
  oxidation makes acid (low Kd, fast loss), carbonate rock buffers it
  (high Kd).  Over a residence time t the surface keeps
  (tau / t)(1 - exp(-t / tau)) of what it released.  The water cannot
  carry more than the stable phases leave dissolved (the element's
  ``solubility_log_molar`` against pH): trace copper is sorption-limited,
  massive copper solubility-limited -- a copper roof loses ~1-2 g/m2 a year
  and keeps its patina even in rain.
* **Fixing.** What stays forms the secondary mineral whose stability niche
  fits (each mineral card's ``supergene_stability``): carbonates with a
  buffer and the air's CO2 (malachite; azurite above log pCO2 ~ -3.45 bar,
  Vink 1986), chrysocolla on silicate rock in dry climates, atacamite only
  where hyper-aridity keeps chloride, brochantite from acid sulfate,
  tenorite in warm deserts.  No stable phase: the copper leaches.
* **Leached caps.** The iron of the oxidizing sulfides (chalcopyrite, and
  the pyrite that comes with most ore) stays as iron oxide where acid water
  does not carry it off: goethite, or hematite where it is warm and dry
  (Schwertmann & Taylor 1989; Cornell & Schwertmann 2003).  Over a pyritic
  deposit on unbuffered rock the copper leaches and a red-brown cap stays;
  over carbonate the copper stays as the oxide zone's carbonates
  (Anderson 1982, the classic leached-cap readings).
* **Deposits.** An ore system (``regional_materials``: style, grade and
  pyrite from the element card's ``metallogeny.styles``) is copper and pyrite
  in the ground, not a coloured patch: the same rules turn it into what its
  surface shows (fresh sulfides, a leached cap or an oxide zone).
* **Why this LOD.** Rock provinces and climate belts are LOD0 features, so
  the minerals show from orbit; deposits are mapped from LOD2.  The same rule
  runs at every level from the level's own rock mix and climate.
* **Abiotic caveat.** Soil CO2 from respiration (malachite on silicate
  rock in humid soils) and organic complexing are left out: only the air's
  CO2 and the rock's carbonate buffer.
* **Layers.** The rock map (``material_lod._element_minerals``), which
  true colour mixes.

Values from the literature were entered from memory and are unverified.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import natural_materials
from simulations.world_gen.material_chemistry import ATOMIC_MASS

PPM_PER_PERCENT = 1.0e4
# Visible share of a coloured secondary mineral in the weathered top layer,
# f = 1 - exp(-m / PIGMENT_VISIBILITY_WT_PERCENT) for m its mass percent:
# about a sixth at 1 wt%, half at 4 wt% (a few percent of malachite or
# iron oxide colours a soil throughout).
PIGMENT_VISIBILITY_WT_PERCENT = 6.0
# Iron oxides colour far more per gram: about 1 wt% hematite makes a soil red
# and goethite a few percent yellow-brown (Torrent et al. 1983; Schwertmann
# 1993): half the ground's colour at ~1 wt%.
IRON_OXIDE_VISIBILITY_WT_PERCENT = 1.5
# Opaque grains in fresh rock barely change its colour at a few percent
# (basalt carries ~4 % magnetite): a third at 12 wt%.
PRIMARY_VISIBILITY_WT_PERCENT = 30.0
# Sulfide and native-metal oxidation in moist air at Earth's O2: a
# ~100 um grain lasts ~1 kyr (Williamson & Rimstidt 1994 rates).  Dry ground
# keeps a tenth of the rate through moisture films.
SULFIDE_OXIDATION_RATE_PER_YR = 1.0e-3
DRY_OXIDATION_SHARE = 0.1
# Atmospheric corrosion of metal in dry air (below ~60 % relative humidity)
# is a hundredth of its wet rate (ISO 9223 time-of-wetness classes).
METAL_DRY_CORROSION_SHARE = 0.01
EARTH_O2_BAR = 0.21
# Weathering-zone water: volumetric content and bulk density (kg/L).
REGOLITH_WATER_CONTENT = 0.3
REGOLITH_BULK_DENSITY_KG_L = 1.5
WEATHERING_ZONE_DEPTH_M = 1.0
MIN_RUNOFF_M_PER_YR = 1.0e-5
# pH of the weathering-zone water: silicate-buffered ~6, carbonate-buffered
# ~8; oxidizing sulfide drives it to ~3 (gossans 2-3) unless the rock can
# neutralise the acid.  Acid-base accounting (Sobek et al. 1978; Price 2009):
# acid potential 31.25 kg CaCO3 per tonne per wt% sulfide sulfur against the
# neutralising potential of the rock's carbonate (10 kg CaCO3/t per wt%
# CaCO3) and silicates (~10 kg/t); a ratio NP/AP below 1 drains acid, above 2
# stays neutral.
SILICATE_PH = 6.0
CARBONATE_PH_RISE = 2.0
ACID_PH_DROP = 3.0
ACID_POTENTIAL_PER_SULFUR_WT = 31.25
CARBONATE_NP_PER_WT = 10.0
SILICATE_NP_KG_T = 10.0
NEUTRALISATION_RATIO = (1.0, 2.0)
# Rock carbonate and silica as niche fields: CO2 / 44 wt% (pure limestone
# = 1), SiO2 / 45 wt% (any silicate rock = 1).
CARBONATE_FULL_CO2_WT = 44.0
SILICA_FULL_SIO2_WT = 45.0
WEATHERING_ACTIVATION_J_MOL = 60_000.0
GAS_CONSTANT = 8.314462618
# Far-travelled sediment (wind-blown sand and loess, evaporites) comes from
# the planet's crust at large, not from the ground under it: no district share.
FAR_TRAVELLED_CATEGORIES = frozenset({"aeolian_sediment", "quartz_sand_accumulation", "evaporite_basin"})
# Ferric iron stays where it forms above pH ~3; the acid water of a pyritic
# cap (pH 2-3) carries part of it off as Fe2+ and sulfate complexes.
IRON_ACID_LOSS = 0.3
PYRITE_ID = "mat_pyrite"

_REFERENCE_CACHE = {}
_BULK_CACHE = {}


def _card(material_id):
    return natural_materials.MATERIAL_BY_ID.get(str(material_id or "")) or {}


def material_reference_percent(material_id, element):
    """Earth-reference content (wt %) of ``element`` in a material, None if unknown.

    Rocks give it in ``trace_element_ppm``; minerals carry it in their
    formula composition.  A rock without the entry is unknown (the caller
    uses the crust reference, as for an unlisted element).
    """
    key = (str(material_id or ""), str(element))
    if key not in _REFERENCE_CACHE:
        card = _card(material_id)
        value = None
        trace = card.get("trace_element_ppm")
        composition = card.get("elemental_composition_wt")
        if isinstance(trace, dict) and element in trace:
            value = float(trace[element] or 0.0) / PPM_PER_PERCENT
        elif isinstance(composition, dict) and composition and card.get("material_subclass") in {"mineral", "ice"}:
            value = float(composition.get(element, 0.0) or 0.0)
        _REFERENCE_CACHE[key] = value
    return _REFERENCE_CACHE[key]


def material_bulk_percent(material_id, component):
    """A rock's bulk ``component`` (e.g. ``"CO2"``, ``"SiO2"``) in wt %, None if it has no bulk chemistry."""
    key = (str(material_id or ""), str(component))
    if key not in _BULK_CACHE:
        bulk = _card(material_id).get("bulk_composition_wt")
        _BULK_CACHE[key] = float(bulk.get(component, 0.0) or 0.0) if isinstance(bulk, dict) and bulk else None
    return _BULK_CACHE[key]


def clear_caches():
    _REFERENCE_CACHE.clear()
    _BULK_CACHE.clear()


def _linear_rgb(card, fallback=(0.18, 0.17, 0.15)):
    reflectance = (card.get("optical_surface_profile") or {}).get("visible_reflectance") or {}
    values = (reflectance.get("red_650nm"), reflectance.get("green_550nm"), reflectance.get("blue_450nm"))
    if all(value is not None for value in values):
        return [float(value) for value in values]
    return list(fallback)


def _host_allocation(hosts, element_percent, sulfur_percent):
    """Shares of the element held by each primary host.

    Hosts come in order of preference.  The first sulfide whose sulfur need
    the planet's sulfur covers takes everything; otherwise the
    sulfur-poorest sulfide takes what sulfur can hold and the first
    sulfur-free host (native metal) the rest.
    """
    shares = [0.0] * len(hosts)
    if not hosts or element_percent <= 0.0:
        return shares
    sulfides = [index for index, host in enumerate(hosts) if host["sulfur_per_element"] > 0.0]
    free = [index for index, host in enumerate(hosts) if host["sulfur_per_element"] <= 0.0]
    for index in sulfides:
        if element_percent * hosts[index]["sulfur_per_element"] <= sulfur_percent:
            shares[index] = 1.0
            return shares
    if not sulfides:
        shares[free[0]] = 1.0
        return shares
    poorest = min(sulfides, key=lambda index: hosts[index]["sulfur_per_element"])
    held = min(1.0, sulfur_percent / max(1e-12, element_percent * hosts[poorest]["sulfur_per_element"]))
    if not free:
        shares[poorest] = 1.0
        return shares
    shares[poorest] = held
    shares[free[0]] = 1.0 - held
    return shares


def pigment_systems(natural_material_model):
    """Elements with authored supergene data, prepared for this planet (plain lists, stored in the true-colour model)."""
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    profile = model.get("element_profile") if isinstance(model.get("element_profile"), dict) else {}
    try:
        reference = natural_materials.reference_element_distribution()
    except Exception:
        return []
    systems = []
    for card in natural_materials.MATERIAL_BY_ID.values():
        behaviour = card.get("supergene_behaviour")
        symbol = str(card.get("element_symbol") or "")
        if card.get("material_subclass") != "element" or not isinstance(behaviour, dict) or not symbol:
            continue
        reference_percent = float(reference.get(symbol, 0.0) or 0.0)
        planet_percent = float(profile.get(symbol, reference_percent) or 0.0)
        if reference_percent <= 0.0:
            continue
        hosts = []
        for material_id in behaviour.get("primary_hosts") or []:
            host = _card(material_id)
            composition = host.get("elemental_composition_wt") or {}
            element_wt = float(composition.get(symbol, 0.0) or 0.0)
            if element_wt <= 0.0:
                continue
            hosts.append({
                "material_id": material_id,
                "element_wt_percent": element_wt,
                "sulfur_per_element": float(composition.get("S", 0.0) or 0.0) / element_wt,
                "iron_per_element": float(composition.get("Fe", 0.0) or 0.0) / element_wt,
                "rgb": _linear_rgb(host),
            })
        shares = _host_allocation(hosts, planet_percent, float(profile.get("S", reference.get("S", 0.0)) or 0.0))
        for host, share in zip(hosts, shares):
            host["share"] = round(share, 6)
        phases = []
        for material_id in behaviour.get("secondary_phases") or []:
            phase = _card(material_id)
            stability = phase.get("supergene_stability") or {}
            element_wt = float((phase.get("elemental_composition_wt") or {}).get(symbol, 0.0) or 0.0)
            if element_wt <= 0.0 or not isinstance(stability.get("niche"), dict):
                continue
            phases.append({
                "material_id": material_id,
                "element_wt_percent": element_wt,
                "rgb": _linear_rgb(phase),
                "niche": {str(key): [float(value) for value in bounds] for key, bounds in stability["niche"].items()},
                "relative_stability": float(stability.get("relative_stability", 1.0) or 1.0),
            })
        iron_phases = []
        for material_id in behaviour.get("leached_cap_phases") or []:
            phase = _card(material_id)
            stability = phase.get("supergene_stability") or {}
            iron_wt = float((phase.get("elemental_composition_wt") or {}).get("Fe", 0.0) or 0.0)
            if iron_wt <= 0.0 or not isinstance(stability.get("niche"), dict):
                continue
            iron_phases.append({
                "material_id": material_id,
                "iron_wt_percent": iron_wt,
                "niche": {str(key): [float(value) for value in bounds] for key, bounds in stability["niche"].items()},
                "relative_stability": float(stability.get("relative_stability", 1.0) or 1.0),
            })
        present_hosts = [host for host in hosts if host.get("share", 0.0) > 0.0]
        metallogeny = dict(card.get("metallogeny") or {})
        # Ore systems: the planet's main host carries the ore; pyrite comes
        # with it only while sulfur is left over (the host took all it needs).
        main_host = max(present_hosts, key=lambda host: host["share"]) if present_hosts else None
        sulfur_left = bool(main_host and main_host["sulfur_per_element"] > 0.0 and main_host["share"] >= 1.0)
        styles = {}
        for district_type, style in (metallogeny.get("styles") or {}).items():
            low, high = (float(value) for value in style.get("grade_wt_percent") or (0.0, 0.0))
            styles[str(district_type)] = {
                "style": str(style.get("style") or district_type),
                # Ore keeps its concentration over the crust as an odds ratio, as rocks do.
                "grade_wt_percent": [float(rock_content_percent(low, reference_percent, planet_percent)),
                                     float(rock_content_percent(high, reference_percent, planet_percent))],
                "pyrite_to_host": float(style.get("pyrite_to_host", 0.0) or 0.0) if sulfur_left else 0.0,
                "geometry": str(style.get("geometry") or "stockwork_and_lenses"),
            }
        pyrite = (natural_materials.MATERIAL_BY_ID.get(PYRITE_ID) or {}).get("elemental_composition_wt") or {}
        systems.append({
            "element": symbol,
            "planet_percent": planet_percent,
            "reference_percent": reference_percent,
            "enrichment": planet_percent / reference_percent,
            "primary_hosts": present_hosts,
            "secondary_phases": phases,
            "leached_cap_phases": iron_phases,
            "pyrite": {"material_id": PYRITE_ID, "iron_fraction": float(pyrite.get("Fe", 0.0) or 0.0) / 100.0,
                       "sulfur_fraction": float(pyrite.get("S", 0.0) or 0.0) / 100.0} if pyrite else None,
            "deposit_host": main_host["material_id"] if main_host else None,
            "deposit_styles": styles,
            "sorption_log_kd_l_per_kg": [list(map(float, pair)) for pair in behaviour.get("sorption_log_kd_l_per_kg") or [[6.0, 2.0]]],
            "solubility_log_molar": [list(map(float, pair)) for pair in behaviour.get("solubility_log_molar") or []],
            "molar_mass_g": float(ATOMIC_MASS.get(symbol, 0.0)),
            "metallogeny": metallogeny,
        })
    systems.sort(key=lambda system: system["element"])
    return systems


def rock_content_percent(reference_percent, reference_crust_percent, planet_crust_percent):
    """A rock's content of the element on this planet (wt %).

    The rock keeps its Earth preference for the element as an odds ratio
    against the crust, k = c_rock / c_crust on Earth:
    c / (1 - c) = k p / (1 - p) for crust fraction p.  At trace levels this is
    the rock's reference times the planet's enrichment; at tens of percent
    it saturates below 100 % instead of running past it.
    """
    k = np.asarray(reference_percent, dtype=np.float32) / max(1e-12, float(reference_crust_percent))
    p = np.clip(np.asarray(planet_crust_percent, dtype=np.float32) / 100.0, 0.0, 0.999)
    return (100.0 * k * p / (1.0 + (k - 1.0) * p)).astype(np.float32)


def mix_content_percent(material_ids, weights, system, district_factor=None):
    """The element's content (wt %) of a mix of materials on this planet, each material by its share.

    A rock or sediment keeps its Earth preference for the element
    (``rock_content_percent``); a mineral has its formula's; a material that
    states neither is the planet's mean crust.  The ore districts' factor
    applies to what formed or weathered in place, not to far-travelled
    sediment.  A cover therefore dilutes or enriches by what it is made of.
    """
    weights = np.maximum(np.asarray(weights, dtype=np.float64), 0.0)
    element = system["element"]
    planet_percent = system["planet_percent"]
    local_percent = planet_percent * (np.asarray(district_factor, dtype=np.float64) if district_factor is not None else 1.0)
    content = np.zeros(weights.shape[1:], dtype=np.float64)
    for material_id, weight in zip(material_ids, weights):
        if not np.any(weight > 0.0):
            continue
        card = _card(material_id)
        reference = material_reference_percent(material_id, element)
        if card.get("material_subclass") in {"mineral", "ice"} and element not in (card.get("trace_element_ppm") or {}):
            value = float(reference or 0.0)
        else:
            far = str(card.get("formation_category") or "") in FAR_TRAVELLED_CATEGORIES
            value = rock_content_percent(
                system["reference_percent"] if reference is None else reference, system["reference_percent"],
                planet_percent if far else local_percent,
            )
        content += weight * value
    return (content / np.maximum(weights.sum(axis=0), 1e-9)).astype(np.float32)


def _trapezoid(values, bounds):
    outer_low, ideal_low, ideal_high, outer_high = bounds
    values = np.asarray(values, dtype=np.float32)
    rising = np.clip((values - outer_low) / max(1e-9, ideal_low - outer_low), 0.0, 1.0)
    falling = np.clip((outer_high - values) / max(1e-9, outer_high - ideal_high), 0.0, 1.0)
    return np.minimum(rising, falling)


def _arrhenius(temperature_k):
    temperature = np.clip(np.asarray(temperature_k, dtype=np.float32), 150.0, 700.0)
    return np.exp(-WEATHERING_ACTIVATION_J_MOL / GAS_CONSTANT * (1.0 / temperature - 1.0 / 288.0))


def surface_minerals(env, fields, land, *, residence_yr, bedrock, slope):
    """The element minerals at the surface: fresh hosts and the weathering minerals over them.

    For every element in ``env["element_pigments"]``.  ``fields``: arrays
    ``element_content_percent`` (dict per element, the element in the
    visible mix: ``mix_content_percent``), ``element_deposits`` (dict per
    element of ``{"share", "content_percent", "pyrite_wt"}`` arrays: the ore
    systems' part of each cell and what it adds), ``rock_carbonate``,
    ``rock_silica``, ``aridity``, ``wetness``, ``temperature_k``,
    ``runoff_mm``.  Returns ``(fractions, diagnostics)``: ``{material_id:
    visible areal fraction}`` (what the rock map shows and true colour mixes)
    and per-element numbers.
    """
    systems = env.get("element_pigments") or []
    land = np.asarray(land, dtype=bool)
    shape = land.shape
    if not systems:
        return {}, {}

    def field(name, default):
        value = fields.get(name)
        return np.asarray(value, dtype=np.float32) if value is not None else np.full(shape, default, dtype=np.float32)

    aridity = field("aridity", 1.0)
    wetness = field("wetness", 0.0)
    temperature = field("temperature_k", 288.0)
    runoff_m = np.maximum(field("runoff_mm", 0.0) / 1000.0, MIN_RUNOFF_M_PER_YR)
    carbonate = np.clip(np.nan_to_num(field("rock_carbonate", 0.0), nan=0.0), 0.0, 1.0)
    silica = np.clip(np.nan_to_num(field("rock_silica", 0.5), nan=0.5), 0.0, 1.0)
    residence = np.maximum(np.asarray(residence_yr, dtype=np.float32), 1.0)
    bedrock = np.asarray(bedrock, dtype=np.float32)
    slope = np.asarray(slope, dtype=np.float32)
    o2_relative = float(env.get("o2_relative", 0.0) or 0.0)
    base_rate = SULFIDE_OXIDATION_RATE_PER_YR * math.sqrt(max(0.0, o2_relative)) * np.minimum(3.0, _arrhenius(temperature))
    # Sulfides oxidize in moist air as well; metal corrodes only while wet.
    oxidized = 1.0 - np.exp(-base_rate * (DRY_OXIDATION_SHARE + (1.0 - DRY_OXIDATION_SHARE) * wetness) * residence)
    corroded = 1.0 - np.exp(-base_rate * (METAL_DRY_CORROSION_SHARE + (1.0 - METAL_DRY_CORROSION_SHARE) * wetness) * residence)
    contents = fields.get("element_content_percent") or {}
    deposits = fields.get("element_deposits") or {}
    zeros = np.zeros(shape, dtype=np.float32)
    fractions = {}
    diagnostics = {}

    def add(material_id, share):
        fractions[material_id] = fractions.get(material_id, 0.0) + share

    for system in systems:
        element = system["element"]
        content = contents.get(element)
        content = np.asarray(content, dtype=np.float32) if content is not None else np.full(shape, system["planet_percent"], dtype=np.float32)
        deposit = deposits.get(element) or {}
        deposit_share = np.clip(np.asarray(deposit.get("share", zeros), dtype=np.float32), 0.0, 1.0)
        # An ore system replaces its share of the cell's ground.
        content = content * (1.0 - deposit_share) + np.asarray(deposit.get("content_percent", zeros), dtype=np.float32)
        pyrite_wt = np.asarray(deposit.get("pyrite_wt", zeros), dtype=np.float32)
        pyrite = system.get("pyrite") or {}
        # Fresh rock: host minerals (and the ore's pyrite) that have not oxidized.
        sulfur_wt = pyrite_wt * float(pyrite.get("sulfur_fraction", 0.0))
        iron_wt = pyrite_wt * float(pyrite.get("iron_fraction", 0.0))
        primary, primary_ids = [], []
        released_wt = zeros
        for host in system["primary_hosts"]:
            held = content * float(host["share"])
            # A sulfide oxidizes, a native metal corrodes.
            lost = oxidized if float(host["sulfur_per_element"]) > 0.0 else corroded
            primary.append(held * 100.0 / float(host["element_wt_percent"]) * (1.0 - lost))
            primary_ids.append(host["material_id"])
            released_wt = released_wt + held * lost
            sulfur_wt = sulfur_wt + held * float(host["sulfur_per_element"])
            iron_wt = iron_wt + held * float(host.get("iron_per_element", 0.0))
        if pyrite:
            primary.append(pyrite_wt * (1.0 - oxidized))
            primary_ids.append(pyrite["material_id"])
        fresh = np.sum(primary, axis=0) if primary else zeros
        primary_wt = fresh
        f_fresh = np.where(land, 1.0 - np.exp(-fresh / PRIMARY_VISIBILITY_WT_PERCENT), 0.0)
        # Weathering: released metal, what the water leaves, and the phase that fixes it.
        acid_potential = ACID_POTENTIAL_PER_SULFUR_WT * sulfur_wt * oxidized
        # CaCO3 wt% = 100 x carbonate (CO2 / 44 wt%).
        neutralising = CARBONATE_NP_PER_WT * 100.0 * carbonate + SILICATE_NP_KG_T
        ratio = neutralising / np.maximum(acid_potential, 1e-9)
        low, high = NEUTRALISATION_RATIO
        acid = np.clip((high - ratio) / (high - low), 0.0, 1.0)
        ph = np.clip(SILICATE_PH + CARBONATE_PH_RISE * carbonate - ACID_PH_DROP * acid, 2.5, 9.0)
        curve = sorted(system["sorption_log_kd_l_per_kg"])
        log_kd = np.interp(ph, [pair[0] for pair in curve], [pair[1] for pair in curve]).astype(np.float32)
        storage = REGOLITH_WATER_CONTENT + REGOLITH_BULK_DENSITY_KG_L * np.power(10.0, log_kd)
        tau = WEATHERING_ZONE_DEPTH_M * storage / runoff_m
        retained = tau / residence * (1.0 - np.exp(-residence / tau))
        solubility = sorted(system.get("solubility_log_molar") or [])
        if solubility and system.get("molar_mass_g"):
            # The water carries at most what the stable phases leave
            # dissolved (g per m2 a year) of what the zone releases.
            log_molar = np.interp(ph, [pair[0] for pair in solubility], [pair[1] for pair in solubility])
            carried = runoff_m * 1000.0 * np.power(10.0, log_molar) * float(system["molar_mass_g"])
            released = released_wt / 100.0 * REGOLITH_BULK_DENSITY_KG_L * 1.0e6 * WEATHERING_ZONE_DEPTH_M / residence
            retained = 1.0 - np.minimum(1.0 - retained, carried / np.maximum(released, 1e-12))
        niche_fields = {
            "aridity": aridity,
            "temperature_k": temperature,
            "carbonate": carbonate,
            "silica": silica,
            "chloride": np.clip(aridity * aridity * float(env.get("chloride_ratio", 1.0) or 0.0), 0.0, 1.0),
            "acid": acid,
            "log_pco2_bar": np.full(shape, float(env.get("log_pco2_bar", -3.4)), dtype=np.float32),
        }

        def niche_weights(phases):
            stabilities = []
            for phase in phases:
                stability = np.ones(shape, dtype=np.float32)
                for name, bounds in phase["niche"].items():
                    if name in niche_fields:
                        stability = stability * _trapezoid(niche_fields[name], bounds)
                stabilities.append(stability)
            if not stabilities:
                return zeros, None, np.ones(shape, dtype=np.float32)
            stack = np.stack(stabilities)
            weights = stack * np.asarray([phase["relative_stability"] for phase in phases], dtype=np.float32)[:, None, None]
            return stack.max(axis=0), weights, np.maximum(weights.sum(axis=0), 1e-9)

        presence, weights, weight_total = niche_weights(system["secondary_phases"])
        fixed = released_wt * retained * presence
        phase_masses = [
            fixed * weights[index] / weight_total * 100.0 / float(phase["element_wt_percent"])
            for index, phase in enumerate(system["secondary_phases"])
        ]
        # The leached cap: the sulfides' iron as iron oxide, whatever the copper does.
        iron_phases = system.get("leached_cap_phases") or []
        _iron_presence, iron_weights, iron_total = niche_weights(iron_phases)
        iron_kept = iron_wt * oxidized * (1.0 - IRON_ACID_LOSS * acid)
        iron_masses = [
            iron_kept * iron_weights[index] / iron_total * 100.0 / float(phase["iron_wt_percent"])
            for index, phase in enumerate(iron_phases)
        ] if iron_weights is not None else []
        copper_wt = np.sum(phase_masses, axis=0) if phase_masses else zeros
        iron_oxide_wt = np.sum(iron_masses, axis=0) if iron_masses else zeros
        # Each kind by its own colouring strength; together they cover what
        # either leaves uncovered.
        f_copper = 1.0 - np.exp(-copper_wt / PIGMENT_VISIBILITY_WT_PERCENT)
        f_iron = 1.0 - np.exp(-iron_oxide_wt / IRON_OXIDE_VISIBILITY_WT_PERCENT)
        f_weathered = (1.0 - (1.0 - f_copper) * (1.0 - f_iron)) * (1.0 - 0.45 * bedrock * slope)
        f_weathered = np.where(land, np.clip(f_weathered, 0.0, 0.95), 0.0)
        copper_part = f_copper / np.maximum(f_copper + f_iron, 1e-9)
        # The weathering minerals lie over the fresh rock: its hosts show
        # through the rest.  Within each kind, each mineral takes its mass share.
        f_fresh = f_fresh * (1.0 - f_weathered)
        for material_id, mass in zip(primary_ids, primary):
            add(material_id, f_fresh * mass / np.maximum(primary_wt, 1e-9))
        for phase, mass in zip(system["secondary_phases"], phase_masses):
            add(phase["material_id"], f_weathered * copper_part * mass / np.maximum(copper_wt, 1e-9))
        for phase, mass in zip(iron_phases, iron_masses):
            add(phase["material_id"], f_weathered * (1.0 - copper_part) * mass / np.maximum(iron_oxide_wt, 1e-9))
        if land.any():
            diagnostics[element] = {
                "enrichment": round(float(system["enrichment"]), 3),
                "content_mean_wt_percent": float(content[land].mean()),
                "deposit_share_max": float(deposit_share.max()),
                "fresh_host_mean_wt_percent": float(fresh[land].mean()),
                "oxidized_mean": float((released_wt / np.maximum(content, 1e-12))[land].mean()),
                "retained_mean": float(retained[land].mean()),
                "presence_mean": float(presence[land].mean()),
                "pigment_mean_wt_percent": float(copper_wt[land].mean()),
                "iron_oxide_mean_wt_percent": float(iron_oxide_wt[land].mean()),
                "pigment_visible_mean": float((f_weathered * copper_part)[land].mean()),
                "phase_mean_wt_percent": {phase["material_id"]: round(float(mass[land].mean()), 5) for phase, mass in zip(system["secondary_phases"], phase_masses)},
                "primary_hosts": {host["material_id"]: host["share"] for host in system["primary_hosts"]},
            }
    return {key: np.asarray(value, dtype=np.float32) for key, value in fractions.items() if np.any(np.asarray(value) > 1e-4)}, diagnostics
