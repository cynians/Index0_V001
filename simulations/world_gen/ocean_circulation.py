"""Continent-aware, reduced-complexity ocean circulation for world generation."""

import math
from collections import deque


MODEL_VERSION = "ocean-circulation-v3"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _wind(latitude_fraction):
    latitude = float(latitude_fraction)
    absolute = abs(latitude)
    hemisphere = 1.0 if latitude >= 0.0 else -1.0
    if absolute < 0.10:
        return -0.45, 0.0
    if absolute < 0.34:
        return -0.92, 0.16 * hemisphere
    if absolute < 0.68:
        return 0.92, -0.10 * hemisphere
    return -0.68, 0.12 * hemisphere


def _neighbors(width, height, x, y, wrap_x=True):
    if wrap_x or x > 0:
        yield (x - 1) % width, y
    if wrap_x or x + 1 < width:
        yield (x + 1) % width, y
    if y > 0:
        yield x, y - 1
    if y + 1 < height:
        yield x, y + 1


def _label_basins(ocean_mask, wrap_x=True):
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    labels = [[-1 for _x in range(width)] for _y in range(height)]
    basins = []
    for y in range(height):
        for x in range(width):
            if not ocean_mask[y][x] or labels[y][x] >= 0:
                continue
            basin_id = len(basins)
            queue = deque([(x, y)])
            labels[y][x] = basin_id
            cells = []
            while queue:
                cx, cy = queue.popleft()
                cells.append((cx, cy))
                for nx, ny in _neighbors(width, height, cx, cy, wrap_x=wrap_x):
                    if ocean_mask[ny][nx] and labels[ny][nx] < 0:
                        labels[ny][nx] = basin_id
                        queue.append((nx, ny))
            basins.append(cells)
    return labels, basins


def _blocked(ocean_mask, x, y, wrap_x=True):
    height = len(ocean_mask)
    width = len(ocean_mask[0]) if height else 0
    if y < 0 or y >= height or (not wrap_x and (x < 0 or x >= width)):
        return True
    return not ocean_mask[y][x % width]


def _cyclic_ocean_runs(row, wrap_x=True):
    width = len(row)
    if not width or not any(row):
        return []
    if not wrap_x:
        runs, start = [], None
        for index, value in enumerate(row + [False]):
            if value and start is None:
                start = index
            elif not value and start is not None:
                runs.append((start, index - 1, index - start))
                start = None
        return runs
    if all(row):
        return [(0, width - 1, width)]
    land_start = next(index for index, value in enumerate(row) if not value)
    runs, active = [], []
    for offset in range(1, width + 1):
        x = (land_start + offset) % width
        if row[x]:
            active.append(x)
        elif active:
            runs.append((active[0], active[-1], len(active)))
            active = []
    if active:
        runs.append((active[0], active[-1], len(active)))
    return runs


def derive_ocean_circulation(ocean_mask, mean_surface_temperature_k=288.0, rotation_hours=24.0,
                             wrap_x=True, source_uv_bounds=None, inherit_major_gyres=False):
    """Return wind-driven currents, basin structure, upwelling, and SST fields.

    This is deliberately intermediate in complexity: it resolves basin-scale
    circulation and climate feedbacks, not mesoscale eddies or a Navier-Stokes
    ocean.
    """
    if not ocean_mask or not ocean_mask[0]:
        return {"status": "unavailable", "model_version": MODEL_VERSION}
    height = len(ocean_mask)
    width = min(len(row) for row in ocean_mask)
    ocean_mask = [list(row[:width]) for row in ocean_mask]
    basin_rows, basin_cells = _label_basins(ocean_mask, wrap_x=bool(wrap_x))
    u_rows = [[0.0 for _x in range(width)] for _y in range(height)]
    v_rows = [[0.0 for _x in range(width)] for _y in range(height)]
    upwelling = [[0.0 for _x in range(width)] for _y in range(height)]
    rotation_factor = _clamp(24.0 / max(3.0, abs(float(rotation_hours or 24.0))), 0.25, 2.0)

    source_uv_bounds = source_uv_bounds if isinstance(source_uv_bounds, dict) else {}
    source_v0 = float(source_uv_bounds.get("min_v", 0.0) or 0.0)
    source_v1 = float(source_uv_bounds.get("max_v", 1.0) or 1.0)
    for y in range(height):
        global_v = source_v0 + (source_v1 - source_v0) * y / max(1, height - 1)
        latitude = (0.5 - global_v) * 2.0
        wind_u, wind_v = _wind(latitude)
        coriolis = math.sin(latitude * math.pi * 0.5) * rotation_factor
        for x in range(width):
            if not ocean_mask[y][x]:
                continue
            # Ekman-like deflection: right in the north, left in the south.
            u = wind_u + (-wind_v) * coriolis * 0.34
            v = wind_v + wind_u * coriolis * 0.34
            west_land = _blocked(ocean_mask, x - 1, y, wrap_x=bool(wrap_x))
            east_land = _blocked(ocean_mask, x + 1, y, wrap_x=bool(wrap_x))
            north_land = _blocked(ocean_mask, x, y - 1, wrap_x=bool(wrap_x))
            south_land = _blocked(ocean_mask, x, y + 1, wrap_x=bool(wrap_x))
            if west_land and u < 0.0:
                u *= 0.08
            if east_land and u > 0.0:
                u *= 0.08
            if north_land and v < 0.0:
                v *= 0.08
            if south_land and v > 0.0:
                v *= 0.08

            hemisphere = 1.0 if latitude >= 0.0 else -1.0
            if west_land and abs(latitude) > 0.12:
                # Western side of an ocean basin: narrow, fast, poleward flow.
                v += -hemisphere * (0.72 + abs(latitude) * 0.25)
                u += 0.12
            if east_land and abs(latitude) > 0.12:
                # Broad eastern boundary return flow and wind-driven upwelling.
                v += hemisphere * 0.34
                upwelling[y][x] = _clamp(0.35 + abs(wind_v - v) * 0.45)
            if abs(latitude) < 0.11:
                u -= 0.36
            u_rows[y][x], v_rows[y][x] = u, v

    # Subtropical ocean spans between continents seed basin-scale gyres.
    gyre_seeds = []
    for hemisphere_name, center_y, direction in (() if inherit_major_gyres else (("north", 0.32, 1.0), ("south", 0.68, -1.0))):
        if not (source_v0 <= center_y <= source_v1):
            continue
        center_y = (center_y - source_v0) / max(1e-12, source_v1 - source_v0)
        row_y = max(0, min(height - 1, int(round(center_y * (height - 1)))))
        for start, _end, run_length in _cyclic_ocean_runs(ocean_mask[row_y], wrap_x=bool(wrap_x)):
            if run_length < max(5, width // 18):
                continue
            center_x = (start + (run_length - 1) * 0.5) % width
            radius_x = max(4.0, run_length * 0.56)
            radius_y = max(3.0, height * 0.22)
            gyre_seeds.append((hemisphere_name, center_x, row_y, radius_x, radius_y, direction))
            for y in range(height):
                for x in range(width):
                    if not ocean_mask[y][x]:
                        continue
                    dx = ((x - center_x + width * 0.5) % width) - width * 0.5
                    dy = y - row_y
                    distance = math.hypot(dx / radius_x, dy / radius_y)
                    if distance > 1.35:
                        continue
                    envelope = math.exp(-((distance / 0.94) ** 2)) * 0.88
                    # Screen-space tangent: clockwise north, counterclockwise south.
                    tangent_u = -dy / radius_y * direction
                    tangent_v = dx / radius_x * direction
                    u_rows[y][x] += tangent_u * envelope
                    v_rows[y][x] += tangent_v * envelope

    # Basin-constrained smoothing represents the large-scale pressure field.
    for _iteration in range(8):
        next_u = [row[:] for row in u_rows]
        next_v = [row[:] for row in v_rows]
        for y in range(height):
            for x in range(width):
                if not ocean_mask[y][x]:
                    continue
                vectors = [(u_rows[ny][nx], v_rows[ny][nx]) for nx, ny in _neighbors(width, height, x, y, wrap_x=bool(wrap_x)) if ocean_mask[ny][nx]]
                if not vectors:
                    continue
                avg_u = sum(item[0] for item in vectors) / len(vectors)
                avg_v = sum(item[1] for item in vectors) / len(vectors)
                next_u[y][x] = u_rows[y][x] * 0.62 + avg_u * 0.38
                next_v[y][x] = v_rows[y][x] * 0.62 + avg_v * 0.38
        u_rows, v_rows = next_u, next_v

    # Restore the basin pressure-field circulation after diffusion. This is
    # the resolved Sverdrup/gyre component; wind bands alone look zonal and do
    # not carry heat around continental basins convincingly.
    for _hemisphere_name, center_x, row_y, radius_x, radius_y, direction in gyre_seeds:
        for y in range(height):
            for x in range(width):
                if not ocean_mask[y][x]:
                    continue
                dx = ((x - center_x + width * 0.5) % width) - width * 0.5
                dy = y - row_y
                distance = math.hypot(dx / radius_x, dy / radius_y)
                if distance > 1.28:
                    continue
                ring = math.exp(-(((distance - 0.62) / 0.50) ** 2)) * 0.72
                u_rows[y][x] += (-dy / radius_y) * direction * ring
                v_rows[y][x] += (dx / radius_x) * direction * ring

    speed_rows = [[0.0 for _x in range(width)] for _y in range(height)]
    sst_rows = [[None for _x in range(width)] for _y in range(height)]
    salinity_rows = [[None for _x in range(width)] for _y in range(height)]
    deep_water_formation_rows = [[0.0 for _x in range(width)] for _y in range(height)]
    max_speed = max(
        [math.hypot(u_rows[y][x], v_rows[y][x]) for y in range(height) for x in range(width) if ocean_mask[y][x]]
        or [1.0]
    )
    for y in range(height):
        global_v = source_v0 + (source_v1 - source_v0) * y / max(1, height - 1)
        latitude = (0.5 - global_v) * 2.0
        for x in range(width):
            if not ocean_mask[y][x]:
                continue
            u_rows[y][x] /= max_speed
            v_rows[y][x] /= max_speed
            speed = math.hypot(u_rows[y][x], v_rows[y][x])
            speed_rows[y][x] = speed
            poleward_heat = -v_rows[y][x] * (1.0 if latitude >= 0 else -1.0) * 7.5
            baseline = float(mean_surface_temperature_k) + 11.5 - 35.0 * (abs(latitude) ** 1.28)
            sst_rows[y][x] = max(268.0, min(307.0, baseline + poleward_heat - upwelling[y][x] * 5.5))
            subtropical_evaporation = math.exp(-(((abs(latitude) - 0.43) / 0.20) ** 2))
            equatorial_rain = math.exp(-((abs(latitude) / 0.15) ** 2))
            polar_freshening = _clamp((abs(latitude) - 0.72) / 0.28)
            salinity = 34.65 + subtropical_evaporation * 1.15 - equatorial_rain * 0.62 - polar_freshening * 0.72
            salinity_rows[y][x] = salinity
            deep_water_formation_rows[y][x] = _clamp((276.5 - sst_rows[y][x]) / 7.0) * _clamp((salinity - 34.25) / 1.1)

    basins = []
    gyres = []
    total = max(1, width * height)
    for basin_id, cells in enumerate(basin_cells):
        if not cells:
            continue
        mean_x = sum(x for x, _y in cells) / len(cells)
        mean_y = sum(y for _x, y in cells) / len(cells)
        basins.append({
            "id": f"ocean_basin_{basin_id + 1:02d}",
            "cell_fraction": round(len(cells) / total, 4),
            "center": {"x": round(mean_x / max(1, width - 1), 3), "y": round(mean_y / max(1, height - 1), 3)},
        })
    for hemisphere_name, gx, gy, _radius_x, _radius_y, _direction in gyre_seeds:
        basin_id = basin_rows[max(0, min(height - 1, int(gy)))][int(gx) % width]
        gyres.append({
            "id": f"gyre_{len(gyres) + 1:02d}",
            "basin_id": f"ocean_basin_{basin_id + 1:02d}" if basin_id >= 0 else None,
            "hemisphere": hemisphere_name,
            "rotation": "clockwise" if hemisphere_name == "north" else "counterclockwise",
            "center": {"x": round(gx / max(1, width - 1), 3), "y": round(gy / max(1, height - 1), 3)},
        })
    if not gyres and not inherit_major_gyres:
        for basin_id, cells in enumerate(basin_cells):
            for hemisphere_name, selected in (("north", [(x, y) for x, y in cells if y < height * 0.47]), ("south", [(x, y) for x, y in cells if y > height * 0.53])):
                if len(selected) < max(18, total * 0.004):
                    continue
                gx = sum(x for x, _y in selected) / len(selected)
                gy = sum(y for _x, y in selected) / len(selected)
                gyres.append({"id": f"gyre_{len(gyres) + 1:02d}", "basin_id": f"ocean_basin_{basin_id + 1:02d}", "hemisphere": hemisphere_name, "rotation": "clockwise" if hemisphere_name == "north" else "counterclockwise", "center": {"x": round(gx / max(1, width - 1), 3), "y": round(gy / max(1, height - 1), 3)}})

    vector_rows = [
        [[round(u_rows[y][x], 3), round(v_rows[y][x], 3)] if ocean_mask[y][x] else None for x in range(width)]
        for y in range(height)
    ]
    return {
        "status": "ocean_circulation_seeded",
        "model_version": MODEL_VERSION,
        "drivers": ["prevailing_winds", "planetary_rotation", "coriolis_effect", "continent_boundaries", "basin_connectivity", "temperature_density_contrast"],
        "width": width,
        "height": height,
        "basin_rows": basin_rows,
        "basins": basins,
        "gyres": gyres,
        "vector_rows": vector_rows,
        "speed_rows": [[round(value, 3) for value in row] for row in speed_rows],
        "sea_surface_temperature_rows_k": [[round(value, 1) if value is not None else None for value in row] for row in sst_rows],
        "surface_salinity_rows_psu": [[round(value, 2) if value is not None else None for value in row] for row in salinity_rows],
        "deep_water_formation_rows": [[round(value, 3) for value in row] for row in deep_water_formation_rows],
        "upwelling_rows": [[round(value, 3) for value in row] for row in upwelling],
        "summary": {
            "ocean_basin_count": len(basins),
            "major_gyre_count": len(gyres),
            "western_boundary_intensification": True,
            "coastal_upwelling": any(value > 0.25 for row in upwelling for value in row),
            "thermohaline_overturning_potential": round(max(max(row) for row in deep_water_formation_rows), 3),
        },
    }
