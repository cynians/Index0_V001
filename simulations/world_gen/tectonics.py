import math


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _wrapped_delta(a, b):
    delta = float(a) - float(b)
    if delta > 0.5:
        delta -= 1.0
    elif delta < -0.5:
        delta += 1.0
    return delta


def _wrapped_distance(ax, ay, bx, by):
    dx = _wrapped_delta(ax, bx)
    dy = float(ay) - float(by)
    return math.hypot(dx, dy)


def _mantle_current_at(nx, ny, cell_count=3):
    vx = 0.0
    vy = 0.0
    for index in range(cell_count):
        phase = index / max(1, cell_count)
        cx = (phase * 0.37 + 0.18) % 1.0
        cy = 0.24 + (index % 3) * 0.24
        dx = _wrapped_delta(nx, cx)
        dy = ny - cy
        falloff = math.exp(-((dx * dx + dy * dy) / 0.085))
        swirl = -1.0 if index % 2 else 1.0
        vx += (-dy * swirl + 0.18 * math.sin(math.tau * (ny + phase))) * falloff
        vy += (dx * swirl + 0.12 * math.cos(math.tau * (nx - phase))) * falloff
    length = math.hypot(vx, vy)
    if length <= 1e-9:
        return {"x": 0.0, "y": 0.0, "speed_cm_per_year": 0.0}
    speed = _clamp(length * 5.5, 0.5, 8.5)
    return {
        "dir_x": round(vx / length, 4),
        "dir_y": round(vy / length, 4),
        "speed_cm_per_year": round(speed, 3),
    }


def _plate_centers(count):
    centers = []
    golden = 0.61803398875
    for index in range(count):
        nx = (0.12 + index * golden) % 1.0
        band = index % 4
        ny = 0.16 + band * 0.22 + 0.055 * math.sin(index * 1.73)
        ny = _clamp(ny, 0.08, 0.92)
        centers.append((nx, ny))
    return centers


def _nearest_plate_index(nx, ny, plates):
    best_index = 0
    best_distance = 999.0
    for index, plate in enumerate(plates):
        distance = _wrapped_distance(nx, ny, plate["center_x"], plate["center_y"])
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _boundary_kind(plate_a, plate_b):
    dx = _wrapped_delta(plate_b["center_x"], plate_a["center_x"])
    dy = plate_b["center_y"] - plate_a["center_y"]
    normal_len = math.hypot(dx, dy) or 1.0
    nx = dx / normal_len
    ny = dy / normal_len
    rel_vx = plate_b["velocity_x_cm_year"] - plate_a["velocity_x_cm_year"]
    rel_vy = plate_b["velocity_y_cm_year"] - plate_a["velocity_y_cm_year"]
    normal_motion = rel_vx * nx + rel_vy * ny
    shear_motion = abs(rel_vx * -ny + rel_vy * nx)
    if normal_motion < -0.65:
        if plate_a["plate_type"] != plate_b["plate_type"]:
            return "subduction"
        return "collision"
    if normal_motion > 0.55:
        return "divergent"
    if shear_motion > 0.7:
        return "transform"
    return "passive"


def derive_tectonic_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    tectonics = terrain.get("tectonics") if isinstance(terrain.get("tectonics"), dict) else {}
    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    requested_count = int(tectonics.get("plate_count", 8) or 8)
    plate_count = max(3, min(18, requested_count))
    ocean_fraction = _clamp(hydrology.get("target_ocean_fraction", 0.45), 0.0, 0.92)

    plates = []
    for index, (center_x, center_y) in enumerate(_plate_centers(plate_count)):
        current = _mantle_current_at(center_x, center_y)
        plate_type = "oceanic" if ((index / max(1, plate_count - 1)) < ocean_fraction) else "continental"
        if index % 5 == 0:
            plate_type = "mixed"
        speed = current["speed_cm_per_year"]
        plates.append({
            "id": f"plate_{index + 1:02d}",
            "center_x": round(center_x, 4),
            "center_y": round(center_y, 4),
            "plate_type": plate_type,
            "velocity_x_cm_year": round(current["dir_x"] * speed, 3),
            "velocity_y_cm_year": round(current["dir_y"] * speed, 3),
            "speed_cm_per_year": speed,
        })

    currents = []
    for row in range(3):
        for col in range(5):
            nx = (col + 0.5) / 5.0
            ny = (row + 0.5) / 3.0
            current = _mantle_current_at(nx, ny)
            currents.append({
                "pos_x": round(nx, 4),
                "pos_y": round(ny, 4),
                **current,
            })

    sample_w = 73
    sample_h = 37
    owner_rows = []
    boundary_segments = []
    boundary_pairs = {}
    for row in range(sample_h):
        ny = row / max(1, sample_h - 1)
        owner_row = []
        for col in range(sample_w):
            nx = col / max(1, sample_w - 1)
            owner_row.append(_nearest_plate_index(nx, ny, plates))
        owner_rows.append(owner_row)

    for row in range(sample_h - 1):
        for col in range(sample_w - 1):
            a = owner_rows[row][col]
            east = owner_rows[row][col + 1]
            south = owner_rows[row + 1][col]
            if east != a:
                pair = tuple(sorted((a, east)))
                x = (col + 0.5) / max(1, sample_w - 1)
                y1 = row / max(1, sample_h - 1)
                y2 = (row + 1) / max(1, sample_h - 1)
                boundary_segments.append({"x1": x, "y1": y1, "x2": x, "y2": y2, "plate_a": plates[pair[0]]["id"], "plate_b": plates[pair[1]]["id"]})
                boundary_pairs[pair] = boundary_pairs.get(pair, 0) + 1
            if south != a:
                pair = tuple(sorted((a, south)))
                x1 = col / max(1, sample_w - 1)
                x2 = (col + 1) / max(1, sample_w - 1)
                y = (row + 0.5) / max(1, sample_h - 1)
                boundary_segments.append({"x1": x1, "y1": y, "x2": x2, "y2": y, "plate_a": plates[pair[0]]["id"], "plate_b": plates[pair[1]]["id"]})
                boundary_pairs[pair] = boundary_pairs.get(pair, 0) + 1

    boundaries = []
    for (a, b), length in sorted(boundary_pairs.items(), key=lambda item: item[1], reverse=True):
        kind = _boundary_kind(plates[a], plates[b])
        boundaries.append({
            "plate_a": plates[a]["id"],
            "plate_b": plates[b]["id"],
            "kind": kind,
            "sample_length": length,
            "activity": round(min(1.0, length / max(1, sample_w)), 3),
        })

    return {
        "status": "plates_defined",
        "planet_id": planet_id,
        "age_myr": 0.0,
        "plate_count": plate_count,
        "sample_grid": {"width": sample_w, "height": sample_h, "owners": owner_rows},
        "plates": plates,
        "mantle_currents": currents,
        "boundary_segments": boundary_segments,
        "boundaries": boundaries,
        "notes": [
            "Plate motion is seeded from mantle current cells before terrain is uplifted.",
            "Advancing tectonics turns convergent boundaries into mountains/trenches and divergent boundaries into ocean basins.",
        ],
    }


def advance_tectonics_model(tectonic_model, terrain, million_years=125.0):
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    boundaries = list(tectonic_model.get("boundaries") or [])
    age = float(tectonic_model.get("age_myr", 0.0) or 0.0) + max(1.0, float(million_years or 1.0))
    uplift = 0.0
    basin = 0.0
    erosion = 0.0
    for boundary in boundaries:
        activity = float(boundary.get("activity", 0.0) or 0.0)
        kind = boundary.get("kind")
        if kind in {"collision", "subduction"}:
            uplift += activity
        elif kind == "divergent":
            basin += activity
        if kind in {"collision", "subduction", "divergent"}:
            erosion += activity * 0.35

    advanced = dict(tectonic_model)
    advanced["status"] = "tectonics_advanced"
    advanced["age_myr"] = round(age, 1)
    advanced["geologic_time_step_myr"] = max(1.0, float(million_years or 1.0))
    time_factor = min(1.0, age / 125.0)
    advanced["surface_effects"] = {
        "orogenic_uplift": round(min(1.0, time_factor * 0.65 + uplift / max(1.0, len(boundaries) * 0.12)), 3),
        "ocean_basin_opening": round(min(1.0, time_factor * 0.55 + basin / max(1.0, len(boundaries) * 0.10)), 3),
        "erosion_progress": round(min(1.0, age / 320.0 + erosion / max(1.0, len(boundaries) * 1.8)), 3),
    }
    return advanced


def derive_crater_model(terrain, seed=None, physics=None, planet_id=""):
    terrain = terrain if isinstance(terrain, dict) else {}
    cratering = terrain.get("cratering") if isinstance(terrain.get("cratering"), dict) else {}
    density = _clamp(cratering.get("density", 0.65), 0.0, 1.0)
    max_km = max(10.0, float(cratering.get("max_crater_diameter_km", 400.0) or 400.0))
    count = int(12 + density * 34)
    craters = []
    golden = 0.61803398875
    for index in range(count):
        nx = (0.07 + index * golden) % 1.0
        ny = 0.08 + ((index * 0.37) % 0.84)
        scale = 1.0 / ((index % 9) + 1)
        diameter = max(3.0, max_km * (0.12 + 0.88 * scale))
        craters.append({
            "id": f"crater_{index + 1:02d}",
            "x": round(nx, 4),
            "y": round(ny, 4),
            "diameter_km": round(diameter, 2),
            "depth_m": round(min(4200.0, diameter * 18.0), 1),
            "rim_height_m": round(min(950.0, diameter * 4.2), 1),
        })
    return {
        "status": "craters_seeded",
        "planet_id": planet_id,
        "density": round(density, 3),
        "craters": craters,
        "notes": [
            "Crater fields are used for bodies without active tectonics or atmospheric erosion.",
            "Large basins are sparse; smaller impacts fill the remaining surface.",
        ],
    }
