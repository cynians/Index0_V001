"""Age-aware snapshots of accumulated and currently active planetary processes."""


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def derive_planetary_evolution_model(seed, atmosphere=None, regime=None):
    seed = seed if isinstance(seed, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    system_age_gyr = max(0.01, float(seed.get("system_age_gyr", 4.5) or 4.5))
    formation_delay_myr = max(0.0, float(seed.get("formation_delay_myr", 5.0) or 5.0))
    body_age_gyr = max(0.0, system_age_gyr - formation_delay_myr / 1000.0)
    surface_age_myr = _clamp(seed.get("surface_age_myr", body_age_gyr * 1000.0), 0.0, body_age_gyr * 1000.0)
    water_loss = _clamp(seed.get("water_loss_fraction", 0.0), 0.0, 1.0)
    resurfacing = _clamp(seed.get("resurfacing_fraction", 0.0), 0.0, 1.0)
    atmosphere_class = str(atmosphere.get("atmosphere_class") or "unknown")
    tectonics = str((regime.get("interior") or {}).get("tectonic_regime") or seed.get("tectonics_mode") or "unknown")
    volcanic = str((regime.get("interior") or {}).get("volcanic_activity") or "unknown")

    events = [
        {"process": "accretion", "status": "complete", "ended_myr_after_formation": 100.0},
        {"process": "interior_differentiation", "status": "complete", "ended_myr_after_formation": 180.0},
    ]
    if water_loss > 0.05:
        events.append({
            "process": "surface_water_loss",
            "status": "complete" if water_loss >= 0.95 else "in_progress",
            "completion_fraction": water_loss,
            "result": "desiccated_surface" if water_loss >= 0.9 else "reduced_surface_water",
        })
    if atmosphere_class == "runaway_co2":
        events.append({"process": "runaway_greenhouse_transition", "status": "complete", "result": "dense_hot_co2_atmosphere"})
    if resurfacing > 0.02:
        events.append({
            "process": "volcanic_resurfacing",
            "status": "intermittently_active" if volcanic in {"moderate", "high"} else "mostly_complete",
            "completion_fraction": resurfacing,
            "surface_record_age_myr": surface_age_myr,
        })
    if tectonics in {"stagnant_lid", "episodic_lid", "heat_pipe"}:
        events.append({"process": "mantle_plume_deformation", "status": "intermittently_active"})

    return {
        "model_version": "planetary-evolution-snapshot-v1",
        "system_age_gyr": system_age_gyr,
        "body_age_gyr": round(body_age_gyr, 4),
        "surface_record_age_myr": round(surface_age_myr, 1),
        "snapshot_semantics": "completed processes are baked into the present surface; active processes are represented at a visible intermediate state",
        "processes": events,
    }
