"""Curated first-screen presets.

Every value used by a template must populate an editable first-screen control.
The extra keyword arguments on older catalog entries are accepted while legacy
worlds migrate, but are intentionally not returned as active preset data.
Atmosphere, interior, terrain, and climate are derived after the preset has
finished populating the screen.
"""


ROCK = [("O", 45.0), ("Si", 26.0), ("Fe", 8.0), ("Mg", 7.0), ("Al", 6.0), ("Ca", 4.0), ("Na", 2.0), ("K", 1.0)]
ICE = [("O", 55.0), ("H", 7.0), ("Si", 13.0), ("Fe", 7.0), ("Mg", 6.0), ("C", 3.0), ("N", 2.0), ("S", 2.0)]
GAS = [("H", 72.5), ("He", 24.5), ("O", 1.15), ("C", 0.78), ("N", 0.34), ("S", 0.22), ("Ne", 0.16), ("Ar", 0.08)]


def _template(label, planet_class, *, category="Terrestrial", elements=ROCK,
              radius=(0.75, 1.35), core=(0.42, 0.68), crust=(18.0, 55.0),
              spin=(9.0, 24.0), water=(0.15, 0.78), volatiles=("earthlike",),
              tectonics=("unknown",), description="", **_legacy_hidden_traits):
    return {
        "label": label,
        "category": category,
        "description": description,
        "planet_class": planet_class,
        "major_elements": list(elements),
        "numeric_ranges": {
            "radius_earth": radius,
            "core_radius_fraction": core,
            "crust_thickness_km": crust,
            "angular_velocity_deg_per_hour": spin,
            "water_fraction": water,
        },
        "water_range": water,
        "volatile_options": list(volatiles),
        "tectonics_options": list(tectonics),
    }


ADDITIONAL_PLANET_TEMPLATES = {
    "cold_desert_terrestrial": _template(
        "Cold desert terrestrial", "cold_desert_terrestrial", category="Terrestrial",
        radius=(0.45, 0.85), core=(0.45, 0.62), crust=(35, 90), spin=(10, 22), water=(0.01, 0.12),
        volatiles=("thin", "dry"), tectonics=("stagnant_lid", "inactive"),
        atmosphere_regime="dry_co2", volatile_pressure_scale=0.35, surface_age_myr_range=(1800, 4300),
        impact_flux_factor_range=(0.8, 1.35), geologic_style="cold_desert", climate_mode="seasonal",
        description="Thin CO2 air, old cratered uplands, dust, glaciers and episodic runoff.",
    ),
    "anoxic_ocean_world": _template(
        "Anoxic ocean world", "anoxic_ocean_terrestrial", radius=(0.8, 1.3), water=(0.52, 0.82),
        volatiles=("earthlike", "wet"), tectonics=("mobile_lid",), atmosphere_regime="anoxic_nitrogen",
        greenhouse_efficiency=1.15, biosphere_state="anoxic_or_microbial", ocean_fraction_target_range=(0.58, 0.82),
        description="Young ocean-bearing world with reducing nitrogen/CO2 air and active plates.",
    ),
    "snowball_terrestrial": _template(
        "Snowball terrestrial", "snowball_terrestrial", radius=(0.7, 1.35), water=(0.45, 0.86),
        volatiles=("earthlike", "wet"), tectonics=("mobile_lid", "episodic_lid"), bond_albedo=0.68,
        atmosphere_regime="cold_nitrogen", climate_mode="snowball", target_ice_fraction_range=(0.78, 0.98),
        ocean_fraction_target_range=(0.52, 0.78), surface_age_myr_range=(40, 650),
        impact_flux_factor_range=(0.35, 0.75), resurfacing_fraction_range=(0.55, 0.88),
        max_crater_diameter_km=280.0, geologic_style="glaciated",
        description="Ice-covered ocean world dominated by glacial transport and high albedo.",
    ),
    "water_rich_super_earth": _template(
        "Water-rich super-Earth", "water_rich_super_earth", radius=(1.35, 2.25), core=(0.38, 0.58),
        crust=(12, 42), water=(0.72, 0.96), volatiles=("wet", "dense"), tectonics=("mobile_lid", "stagnant_lid"),
        atmosphere_regime="temperate_nitrogen", volatile_pressure_scale=1.8, ocean_fraction_target_range=(0.78, 0.92),
        high_pressure_ice=True, description="High-gravity ocean planet with deep seas and compressed relief.",
    ),
    "dry_super_earth": _template(
        "Dry super-Earth", "dry_super_earth", radius=(1.35, 2.45), core=(0.42, 0.68), crust=(18, 65),
        water=(0.0, 0.08), volatiles=("dry", "dense"), tectonics=("stagnant_lid", "episodic_lid"),
        atmosphere_regime="dry_co2", volatile_pressure_scale=1.8, geologic_style="arid_stagnant_lid",
        description="Massive arid rocky planet with dense CO2 air, shields and preserved basins.",
    ),
    "high_obliquity_terrestrial": _template(
        "High-obliquity terrestrial", "seasonal_terrestrial", water=(0.18, 0.72),
        volatiles=("earthlike", "wet"), tectonics=("mobile_lid", "episodic_lid"), axial_tilt_deg_range=(48, 88),
        climate_mode="seasonal", seasonal_cycle=True, description="Strongly tilted world with extreme seasonal temperature and ice migration.",
    ),
    "heat_pipe_volcanic_world": _template(
        "Heat-pipe volcanic world", "volcanic_terrestrial", radius=(0.45, 1.35), crust=(5, 28), spin=(8, 45),
        water=(0, 0.04), volatiles=("thin", "dense"), tectonics=("heat_pipe",), atmosphere_regime="mixed_volcanic",
        tidal_heating_w_m2_range=(0.18, 2.5), geologic_style="heat_pipe_volcanic", resurfacing_fraction_range=(0.55, 0.95),
        description="High heat-flow body resurfaced by shields, lava plains and volcanic conduits.",
    ),
    "episodic_lid_world": _template(
        "Episodic-lid world", "episodic_lid_terrestrial", water=(0.05, 0.55),
        volatiles=("dry", "earthlike", "dense"), tectonics=("episodic_lid",), geologic_style="episodic_rifting",
        resurfacing_fraction_range=(0.25, 0.72), description="Long quiet intervals punctuated by rifting and global resurfacing episodes.",
    ),
    "iron_dominated_planet": _template(
        "Iron-dominated planet", "iron_planet", elements=[("O", 31), ("Si", 17), ("Fe", 34), ("Mg", 8), ("S", 5), ("Ni", 3), ("Ca", 1), ("Al", 1)],
        radius=(0.35, 1.15), core=(0.7, 0.9), crust=(3, 30), water=(0, 0.03), volatiles=("none", "thin"),
        tectonics=("inactive", "stagnant_lid"), core_density_kg_m3=7200, geologic_style="metal_rich_cratered",
        description="Very dense differentiated rocky body with an oversized metallic core.",
    ),
    "core_poor_silicate_world": _template(
        "Core-poor silicate world", "core_poor_terrestrial", core=(0.04, 0.28), crust=(30, 105),
        water=(0.05, 0.55), volatiles=("dry", "earthlike"), tectonics=("stagnant_lid", "episodic_lid"),
        mantle_density_kg_m3=3450, geologic_style="thick_silicate_lid", description="Weakly differentiated silicate-rich planet with a small metallic core.",
    ),
    "cold_gas_giant": _template(
        "Cold gas giant", "gas_giant", category="Giant planets", elements=GAS, radius=(8, 12.5), core=(0.02, 0.18),
        crust=(0.2, 5), spin=(25, 75), water=(0, .12), volatiles=("dense",), tectonics=("inactive",),
        atmosphere_regime="gas_giant", bond_albedo=.42, description="Hydrogen-helium giant with cool ammonia and water cloud decks.",
    ),
    "hot_gas_giant": _template(
        "Hot gas giant", "gas_giant", category="Giant planets", elements=GAS, radius=(9, 15), core=(0.02, 0.16),
        crust=(0.2, 4), spin=(18, 55), water=(0, .08), volatiles=("dense",), tectonics=("inactive",),
        atmosphere_regime="hot_gas_giant", bond_albedo=.12, climate_mode="tidally_locked", synchronous_rotation=True,
        description="Highly irradiated giant with inflated envelope and strong day-night forcing.",
    ),
    "mini_neptune": _template(
        "Mini-Neptune", "sub_neptune", category="Giant planets", elements=GAS, radius=(2.2, 4.0), core=(.18, .48),
        crust=(2, 20), spin=(12, 50), water=(.12, .52), volatiles=("dense",), tectonics=("inactive",),
        atmosphere_regime="ice_giant", volatile_pressure_scale=8, description="Compact volatile-rich planet beneath a deep H/He envelope.",
    ),
    "hot_neptune": _template(
        "Hot Neptune", "ice_giant", category="Giant planets", elements=GAS, radius=(3.2, 5.2), core=(.08, .35),
        crust=(1, 12), spin=(18, 58), water=(.08, .35), volatiles=("dense",), tectonics=("inactive",),
        atmosphere_regime="hot_ice_giant", bond_albedo=.18, climate_mode="tidally_locked", synchronous_rotation=True,
        description="Warm irradiated Neptune-class world with methane-poor upper air.",
    ),
    "airless_differentiated_moon": _template(
        "Airless differentiated moon", "airless_rocky", category="Moons and dwarf worlds", radius=(.04, .3), core=(.3, .7),
        crust=(20, 120), spin=(.3, 8), water=(0, .02), volatiles=("none",), tectonics=("inactive",),
        synchronous_rotation=True, surface_age_myr_range=(2500, 4500), impact_flux_factor_range=(.8, 1.5),
        description="Differentiated, synchronously rotating, heavily cratered rocky satellite.",
    ),
    "hydrocarbon_cycle_world": _template(
        "Hydrocarbon-cycle world", "hydrocarbon_world", category="Moons and dwarf worlds", elements=ICE,
        radius=(.25, .75), core=(.25, .55), crust=(80, 350), spin=(.2, 3), water=(.05, .25),
        volatiles=("dense",), tectonics=("inactive", "cryotectonic"), atmosphere_regime="methane_nitrogen",
        volatile_pressure_scale=1.5, surface_fluid="methane_ethane", geologic_style="hydrocarbon_dunes_and_lakes",
        ocean_fraction_target_range=(.08, .28),
        description="Cold nitrogen world with methane rain, lakes, rivers and organic dunes.",
    ),
    "tidally_heated_volcanic_moon": _template(
        "Tidally heated volcanic moon", "tidal_volcanic_moon", category="Moons and dwarf worlds", radius=(.12, .35),
        core=(.35, .65), crust=(5, 35), spin=(.2, 3), water=(0, .02), volatiles=("thin",), tectonics=("heat_pipe",),
        tidal_heating_w_m2_range=(.5, 3.5), synchronous_rotation=True, geologic_style="sulfur_heat_pipe",
        resurfacing_fraction_range=(.75, .99), description="Io-like moon dominated by tidal heat, sulfur volcanism and rapid resurfacing.",
    ),
    "active_ocean_moon": _template(
        "Active subsurface-ocean moon", "icy_satellite", category="Moons and dwarf worlds", elements=ICE,
        radius=(.04, .3), core=(.3, .65), crust=(40, 220), spin=(.2, 5), water=(0, .04), volatiles=("none", "thin"),
        tectonics=("unknown",), bulk_ice_fraction_range=(.45, .72), surface_ice_fraction_range=(.94, 1),
        tidal_heating_w_m2_range=(.025, .22), resurfacing_fraction_range=(.28, .82), geologic_style="active_ice_shell",
        synchronous_rotation=True, description="Tidal cryotectonic moon with a subsurface ocean, fractures, chaos terrain and possible plumes.",
    ),
    "volatile_ice_dwarf": _template(
        "Volatile-ice dwarf", "volatile_ice_dwarf", category="Moons and dwarf worlds", elements=ICE,
        radius=(.12, .42), core=(.25, .6), crust=(100, 420), spin=(.3, 6), water=(0, .08), volatiles=("thin",),
        tectonics=("inactive", "cryotectonic"), atmosphere_regime="frozen_methane_nitrogen", surface_fluid="nitrogen_methane_ice",
        seasonal_cycle=True, geologic_style="volatile_frost_transport", description="Pluto/Triton-like dwarf with seasonal frost migration and sublimation landforms.",
    ),
    "dune_world": _template(
        "Dune world", "dune_terrestrial", radius=(.55, 1.5), water=(0, .035), volatiles=("thin", "dense"),
        tectonics=("stagnant_lid", "inactive"), atmosphere_regime="dry_co2", geologic_style="aeolian_dune_seas",
        aeolian_landforms=True, description="Dry atmosphere-bearing world with sand seas, wind corridors and yardangs.",
    ),
    "evaporite_world": _template(
        "Evaporite dying-ocean world", "evaporite_terrestrial", water=(.04, .24), volatiles=("dry", "earthlike"),
        tectonics=("stagnant_lid", "episodic_lid"), geologic_style="evaporite_basins", surface_fluid="brine",
        description="Retreating seas, saline terminal lakes, salt flats and layered paleoshorelines.",
    ),
    "lava_planet": _template(
        "Lava planet", "lava_planet", radius=(.55, 1.8), core=(.42, .72), crust=(2, 18), spin=(.2, 8),
        water=(0, .005), volatiles=("none", "thin"), tectonics=("heat_pipe",), atmosphere_regime="rock_vapor",
        geologic_style="magma_seas", surface_fluid="silicate_magma", synchronous_rotation=True, climate_mode="tidally_locked",
        tidal_heating_w_m2_range=(.15, 1.5), description="Hot rocky world with molten silicate terrain and intense day-night contrast.",
    ),
    "hycean_world": _template(
        "Hycean world", "hycean", category="Ocean and envelope worlds", radius=(1.6, 2.7), core=(.2, .48),
        crust=(20, 120), water=(.72, .98), volatiles=("dense",), tectonics=("stagnant_lid",), atmosphere_regime="hydrogen_ocean",
        volatile_pressure_scale=8, ocean_fraction_target_range=(.86, .94), high_pressure_ice=True,
        description="Deep global ocean beneath a hydrogen-rich atmosphere and high-pressure ice mantle.",
    ),
    "tidally_locked_terrestrial": _template(
        "Tidally locked terrestrial", "tidally_locked_terrestrial", category="Climate extremes", radius=(.65, 1.55),
        spin=(.2, 4), water=(.08, .75), volatiles=("thin", "earthlike", "dense"), tectonics=("stagnant_lid", "mobile_lid"),
        synchronous_rotation=True, climate_mode="tidally_locked", substellar_longitude_deg=0.0,
        description="Permanent dayside and nightside with atmospheric heat transport and a terminator climate belt.",
    ),
    "seasonal_volatile_world": _template(
        "Seasonal volatile world", "seasonal_volatile_terrestrial", category="Climate extremes", radius=(.35, 1.25),
        water=(.02, .42), volatiles=("thin", "earthlike"), tectonics=("inactive", "stagnant_lid"), axial_tilt_deg_range=(28, 78),
        seasonal_cycle=True, climate_mode="seasonal", surface_fluid="water_and_condensable_volatiles",
        description="Strong orbital seasons drive migrating frost, snow, lakes and atmospheric pressure.",
    ),
}
