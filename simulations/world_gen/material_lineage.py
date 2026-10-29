"""True Color lineage check: a child map must look like its parent from afar.

The material LOD contract (docs/worldgen_material_lod_plan_v001.md section 5)
requires a child's True Color, box-filtered onto its parent's pixels, to
match the parent within a mean Delta-E budget.  Colour here is the linear
areal mixture of each material's ontology reflectance, i.e. the renderer's
first step before lighting, wetness and weathering, so the check measures
the material products themselves.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from simulations.world_gen import natural_materials
from simulations.world_gen.material_optics import material_optical_surface_profile, reflectance_triplet

# CIE76 Delta-E between parent pixels and box-filtered children.  About 2 is
# a just-noticeable difference; child levels re-derive cover from their own
# climate and relief, so a few units of drift are expected.
TRUE_COLOR_LINEAGE_BUDGET = {"mean_delta_e": 6.0, "p95_delta_e": 15.0}

# Linear sRGB (D65) to XYZ.
_RGB_TO_XYZ = np.asarray([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_D65_WHITE = np.asarray([0.95047, 1.0, 1.08883])


def material_reflectance(material_ids):
    """``[materials, 3]`` fresh visible reflectance from the ontology cards."""
    rows = []
    for material_id in material_ids:
        material = natural_materials.MATERIAL_BY_ID.get(str(material_id)) or {}
        profile = material_optical_surface_profile(
            material_id,
            formation_category=material.get("formation_category"),
            material_subclass=material.get("material_subclass"),
            display_color=material.get("display_color"),
            explicit=material.get("optical_surface_profile"),
        )
        rows.append(reflectance_triplet(profile))
    return np.asarray(rows, dtype=np.float64).reshape(-1, 3)


def composition_reflectance(material_ids, composition):
    """Linear RGB reflectance ``[H, W, 3]`` of an areal composition ``[M, H, W]``."""
    composition = np.asarray(composition, dtype=np.float64)
    total = np.maximum(composition.sum(axis=0), 1e-9)
    mixed = np.tensordot(material_reflectance(material_ids), composition, axes=([0], [0]))
    return np.moveaxis(mixed / total[None], 0, -1)


def linear_rgb_to_lab(rgb):
    """CIE L*a*b* (D65) of linear sRGB values ``[..., 3]``."""
    xyz = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0) @ _RGB_TO_XYZ.T / _D65_WHITE
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    return np.stack([
        116.0 * f[..., 1] - 16.0,
        500.0 * (f[..., 0] - f[..., 1]),
        200.0 * (f[..., 1] - f[..., 2]),
    ], axis=-1)


def _sample_indices(bounds, shape):
    height, width = shape
    u = bounds["min_u"] + (bounds["max_u"] - bounds["min_u"]) * np.arange(width) / max(1, width - 1)
    v = bounds["min_v"] + (bounds["max_v"] - bounds["min_v"]) * np.arange(height) / max(1, height - 1)
    return u, v


def lineage_delta_e(parent, child, *, wrap_x=False):
    """Delta-E of the child's box-filtered colour against its parent's pixels.

    ``parent`` and ``child`` are dicts with ``material_ids``, ``composition``
    (``[M, H, W]`` visible areal fractions) and ``bounds`` (global UV).  Each
    child sample joins its nearest parent sample; parent pixels with fewer
    than 60 % of the typical child count (partly outside the child tile) are
    skipped.
    """
    parent_rgb = composition_reflectance(parent["material_ids"], parent["composition"])
    child_rgb = composition_reflectance(child["material_ids"], child["composition"])
    parent_height, parent_width = parent_rgb.shape[:2]
    pb = parent["bounds"]
    child_u, child_v = _sample_indices(child["bounds"], child_rgb.shape[:2])
    fx = (child_u - pb["min_u"]) / max(1e-12, pb["max_u"] - pb["min_u"]) * (parent_width - 1)
    fy = (child_v - pb["min_v"]) / max(1e-12, pb["max_v"] - pb["min_v"]) * (parent_height - 1)
    ix = np.rint(fx).astype(np.int64)
    iy = np.rint(fy).astype(np.int64)
    if wrap_x:
        ix = ix % max(1, parent_width - 1)
    valid = (iy[:, None] >= 0) & (iy[:, None] < parent_height) & (ix[None, :] >= 0) & (ix[None, :] < parent_width)
    cells = (np.clip(iy, 0, parent_height - 1)[:, None] * parent_width + np.clip(ix, 0, parent_width - 1)[None, :])[valid]
    counts = np.bincount(cells, minlength=parent_height * parent_width)
    sums = np.stack([
        np.bincount(cells, weights=child_rgb[..., channel][valid], minlength=parent_height * parent_width)
        for channel in range(3)
    ], axis=-1)
    covered = counts > 0
    if not covered.any():
        return {"parent_cells": 0, "mean_delta_e": None, "p95_delta_e": None, "max_delta_e": None}
    typical = float(np.median(counts[covered]))
    complete = counts >= max(1.0, 0.6 * typical)
    filtered = sums[complete] / counts[complete][:, None]
    reference = parent_rgb.reshape(-1, 3)[complete]
    delta = np.linalg.norm(linear_rgb_to_lab(filtered) - linear_rgb_to_lab(reference), axis=-1)
    return {
        "parent_cells": int(complete.sum()),
        "child_samples_per_parent_cell": round(typical, 1),
        "mean_delta_e": round(float(delta.mean()), 3),
        "p95_delta_e": round(float(np.percentile(delta, 95.0)), 3),
        "max_delta_e": round(float(delta.max()), 3),
    }


def visible_composition_from_bundle(model, storage_root):
    """``{material_ids, composition, bounds}`` from a material heatmap model's bundle."""
    from simulations.world_gen.material_heatmaps import load_raster_bundle_arrays

    layers = [layer for layer in model.get("layers") or [] if layer.get("bundle_layer_id")]
    bundle = Path(storage_root) / model["bundle_path"]
    arrays = load_raster_bundle_arrays(bundle, [layer["bundle_layer_id"] for layer in layers])
    material_ids = []
    planes = []
    for layer in layers:
        rgba = arrays.get(layer["bundle_layer_id"])
        if rgba is None:
            continue
        material_ids.append(layer["material_id"])
        planes.append(rgba[..., 3].astype(np.float64) / 255.0)
    return {
        "material_ids": material_ids,
        "composition": np.stack(planes) if planes else np.zeros((0, 1, 1)),
        "bounds": dict(model["source_uv_bounds"]),
    }
