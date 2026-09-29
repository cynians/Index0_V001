"""Build Index 0's compact Dione height grid from NASA PDS Cassini SPC GeoTIFFs."""

import argparse
import json
import math
import struct
import urllib.request
from pathlib import Path


PDS_BASE = "https://sbnarchive.psi.edu/pds4/cassini/satellite-dione.cassini.shape-models-maps/data/global"
PRODUCTS = {
    "equatorial": "dione_eqradius_g.tif",
    "north": "dione_npradius_g.tif",
    "south": "dione_spradius_g.tif",
}
REFERENCE_RADIUS_M = 561_400.0
MISSING_LIMIT = -1.0e30


def _download_product(cache_dir, filename):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / filename
    if not path.exists():
        request = urllib.request.Request(
            f"{PDS_BASE}/{filename}",
            headers={"User-Agent": "Index0-Dione-reference-builder/1.0"},
        )
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    return path


def _read_float_geotiff(path):
    data = path.read_bytes()
    endian = "<" if data[:2] == b"II" else ">"
    if data[2:4] != struct.pack(endian + "H", 42):
        raise ValueError(f"Not a TIFF file: {path}")
    ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
    entry_count = struct.unpack_from(endian + "H", data, ifd_offset)[0]
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
    tags = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, value_type, count, value_offset = struct.unpack_from(endian + "HHII", data, offset)
        size = count * type_sizes[value_type]
        raw = data[offset + 8:offset + 12] if size <= 4 else data[value_offset:value_offset + size]
        tags[tag] = (value_type, count, raw)

    width = struct.unpack(endian + "H", tags[256][2][:2])[0]
    height = struct.unpack(endian + "H", tags[257][2][:2])[0]
    compression = struct.unpack(endian + "H", tags[259][2][:2])[0]
    sample_format = struct.unpack(endian + "H", tags[339][2][:2])[0]
    bits = struct.unpack(endian + "H", tags[258][2][:2])[0]
    if compression != 1 or sample_format != 3 or bits != 32:
        raise ValueError("Expected uncompressed IEEE-754 32-bit PDS radius GeoTIFF")
    strip_count = tags[273][1]
    strip_offsets = struct.unpack(endian + f"{strip_count}I", tags[273][2])
    byte_count_type = "H" if tags[279][0] == 3 else "I"
    strip_byte_counts = struct.unpack(endian + f"{strip_count}{byte_count_type}", tags[279][2])
    rows = []
    for strip_offset, byte_count in zip(strip_offsets, strip_byte_counts):
        value_count = byte_count // 4
        strip_values = struct.unpack_from(endian + f"{value_count}f", data, strip_offset)
        for row_offset in range(0, value_count, width):
            rows.append(list(strip_values[row_offset:row_offset + width]))
    if len(rows) != height:
        raise ValueError(f"Expected {height} rows, found {len(rows)}")
    return rows


def _sample(rows, x, y, wrap_x=False):
    height = len(rows)
    width = len(rows[0])
    if wrap_x:
        x %= width
    else:
        x = min(width - 1.0, max(0.0, x))
    y = min(height - 1.0, max(0.0, y))
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1 = (x0 + 1) % width if wrap_x else min(width - 1, x0 + 1)
    y1 = min(height - 1, y0 + 1)
    tx, ty = x - x0, y - y0
    samples = (
        (rows[y0][x0], (1.0 - tx) * (1.0 - ty)),
        (rows[y0][x1], tx * (1.0 - ty)),
        (rows[y1][x0], (1.0 - tx) * ty),
        (rows[y1][x1], tx * ty),
    )
    valid = [(value, weight) for value, weight in samples if value > MISSING_LIMIT]
    weight_sum = sum(weight for _, weight in valid)
    if not valid or weight_sum <= 0.0:
        return None
    return sum(value * weight for value, weight in valid) / weight_sum


def _sample_equatorial(rows, longitude_deg, latitude_deg):
    height, width = len(rows), len(rows[0])
    x = (longitude_deg % 360.0) / 360.0 * width - 0.5
    y = (55.0 - latitude_deg) / 110.0 * height - 0.5
    return _sample(rows, x, y, wrap_x=True)


def _sample_polar(rows, longitude_deg, latitude_deg, north=True):
    radius = REFERENCE_RADIUS_M
    longitude = math.radians(longitude_deg)
    latitude = math.radians(latitude_deg)
    if north:
        rho = 2.0 * radius * math.tan(math.pi / 4.0 - latitude / 2.0)
        map_x = rho * math.sin(longitude)
        map_y = -rho * math.cos(longitude)
    else:
        rho = 2.0 * radius * math.tan(math.pi / 4.0 + latitude / 2.0)
        map_x = rho * math.sin(longitude)
        map_y = rho * math.cos(longitude)
    resolution = 1588.91001416694576
    upper_left_x = -352738.023145061976
    upper_left_y = 352738.023145061976
    pixel_x = (map_x - upper_left_x) / resolution - 0.5
    pixel_y = (upper_left_y - map_y) / resolution - 0.5
    return _sample(rows, pixel_x, pixel_y)


def _global_radius(equatorial, north, south, longitude, latitude):
    if -50.0 <= latitude <= 50.0:
        return _sample_equatorial(equatorial, longitude, latitude)
    polar = _sample_polar(north if latitude > 0 else south, longitude, latitude, north=latitude > 0)
    if abs(latitude) >= 55.0:
        return polar
    equatorial_value = _sample_equatorial(equatorial, longitude, latitude)
    blend = (abs(latitude) - 50.0) / 5.0
    if polar is None:
        return equatorial_value
    if equatorial_value is None:
        return polar
    return equatorial_value * (1.0 - blend) + polar * blend


def build(output_path, cache_dir, width=257, height=129):
    sources = {
        key: _read_float_geotiff(_download_product(cache_dir, filename))
        for key, filename in PRODUCTS.items()
    }
    rows = []
    for row_index in range(height):
        latitude = 90.0 - row_index * 180.0 / (height - 1)
        row = []
        for col_index in range(width):
            longitude = 0.0 if col_index == width - 1 else col_index * 360.0 / (width - 1)
            radius = _global_radius(sources["equatorial"], sources["north"], sources["south"], longitude, latitude)
            if radius is None:
                raise ValueError(f"No radius sample at {latitude=}, {longitude=}")
            row.append(round(radius - REFERENCE_RADIUS_M))
        row[-1] = row[0]
        rows.append(row)

    values = [value for row in rows for value in row]
    payload = {
        "source": {
            "title": "Dione SPC Shape Models and Assessment Products V1.0",
            "pds_lid": "urn:nasa:pds:satellite-dione.cassini.shape-models-maps::1.0",
            "doi": "10.26033/bxx6-g543",
            "release_date": "2025-08-28",
            "mission": "Cassini-Huygens",
            "method": "stereophotoclinometry",
            "products": list(PRODUCTS.values()),
            "source_resolution_m_per_pixel": 1588.91,
        },
        "projection": "equirectangular",
        "longitude_direction": "positive_east",
        "latitude_type": "planetocentric",
        "vertical_datum": "mean_radius_561400m",
        "elevation_unit": "m",
        "width": width,
        "height": height,
        "wrap_x": True,
        "min_elevation_m": min(values),
        "max_elevation_m": max(values),
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("world/reference_data/dione_heightmap_reference.json"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/dione_pds"))
    args = parser.parse_args()
    build(args.output, args.cache)
