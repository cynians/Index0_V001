"""Pure clothing-editor geometry and persistence helpers.

One garment is painted against a reference person.  Runtime sizes are derived
from that single source layer by mapping pixels between DNA body landmarks.
"""

from copy import deepcopy


CANVAS_WIDTH = 48
CANVAS_HEIGHT = 96
DEFAULT_BODY_SHAPE = {
    "stature": 0.5,
    "leg_length": 0.5,
    "arm_length": 0.5,
    "torso_width": 0.5,
    "shoulder_width": 0.5,
    "head_size": 0.5,
}
SIZE_PROFILES = {
    "small": {key: 0.30 for key in DEFAULT_BODY_SHAPE},
    "reference": dict(DEFAULT_BODY_SHAPE),
    "large": {key: 0.72 for key in DEFAULT_BODY_SHAPE},
}


def normalized_body_shape(body_shape=None):
    source = body_shape if isinstance(body_shape, dict) else {}
    result = {}
    for key, default in DEFAULT_BODY_SHAPE.items():
        try:
            value = float(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        result[key] = max(0.0, min(1.0, value))
    return result


def body_landmarks(body_shape=None, width=CANVAS_WIDTH, height=CANVAS_HEIGHT):
    """Return pixel-space skeletal anchors for a long, spindly person."""
    shape = normalized_body_shape(body_shape)
    cx = (width - 1) / 2.0
    stature = 0.88 + 0.10 * shape["stature"]
    top = height * (1.0 - stature) / 2.0
    bottom = height - top - 1.0
    span = bottom - top
    head_r = span * (0.035 + 0.016 * shape["head_size"])
    head_y = top + head_r
    shoulder_y = top + span * 0.145
    hip_y = top + span * (0.44 - 0.055 * (shape["leg_length"] - 0.5))
    ankle_y = bottom - 1.0
    shoulder_half = width * (0.085 + 0.065 * shape["shoulder_width"])
    torso_half = width * (0.050 + 0.060 * shape["torso_width"])
    wrist_y = shoulder_y + (hip_y - shoulder_y) * (0.72 + 0.55 * shape["arm_length"])
    wrist_dx = shoulder_half + width * (0.035 + 0.035 * shape["arm_length"])
    return {
        "center_x": cx, "top_y": top, "bottom_y": bottom,
        "head_y": head_y, "head_radius": head_r,
        "shoulder_y": shoulder_y, "hip_y": hip_y, "ankle_y": ankle_y,
        "shoulder_half": shoulder_half, "torso_half": torso_half,
        "left_shoulder_x": cx - shoulder_half, "right_shoulder_x": cx + shoulder_half,
        "left_wrist_x": cx - wrist_dx, "right_wrist_x": cx + wrist_dx,
        "wrist_y": wrist_y,
    }


def _blank(width, height):
    return [[None for _ in range(width)] for _ in range(height)]


def _paint_disc(pixels, cx, cy, radius, color):
    radius = max(1, int(round(radius)))
    for y in range(max(0, int(cy) - radius), min(len(pixels), int(cy) + radius + 1)):
        for x in range(max(0, int(cx) - radius), min(len(pixels[0]), int(cx) + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                pixels[y][x] = color


def _paint_line(pixels, start, end, radius, color):
    x1, y1 = start
    x2, y2 = end
    steps = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) * 2))
    for step in range(steps + 1):
        ratio = step / steps
        _paint_disc(pixels, x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio, radius, color)


def human_reference_pixels(body_shape=None, width=CANVAS_WIDTH, height=CANVAS_HEIGHT):
    marks = body_landmarks(body_shape, width, height)
    pixels = _blank(width, height)
    color = (86, 177, 205)
    _paint_disc(pixels, marks["center_x"], marks["head_y"], marks["head_radius"], color)
    _paint_line(pixels, (marks["center_x"], marks["shoulder_y"]), (marks["center_x"], marks["hip_y"]), 1.2, color)
    _paint_line(pixels, (marks["left_shoulder_x"], marks["shoulder_y"]), (marks["right_shoulder_x"], marks["shoulder_y"]), 1.0, color)
    _paint_line(pixels, (marks["left_shoulder_x"], marks["shoulder_y"]), (marks["left_wrist_x"], marks["wrist_y"]), 1.0, color)
    _paint_line(pixels, (marks["right_shoulder_x"], marks["shoulder_y"]), (marks["right_wrist_x"], marks["wrist_y"]), 1.0, color)
    foot_spread = width * 0.055
    _paint_line(pixels, (marks["center_x"] - 1, marks["hip_y"]), (marks["center_x"] - foot_spread, marks["ankle_y"]), 1.0, color)
    _paint_line(pixels, (marks["center_x"] + 1, marks["hip_y"]), (marks["center_x"] + foot_spread, marks["ankle_y"]), 1.0, color)
    return pixels


def clothing_workspace_mask(body_shape=None, width=CANVAS_WIDTH, height=CANVAS_HEIGHT, padding=5):
    reference = human_reference_pixels(body_shape, width, height)
    mask = [[False for _ in range(width)] for _ in range(height)]
    occupied = [(x, y) for y, row in enumerate(reference) for x, value in enumerate(row) if value is not None]
    for x, y in occupied:
        for yy in range(max(0, y - padding), min(height, y + padding + 1)):
            for xx in range(max(0, x - padding), min(width, x + padding + 1)):
                if (xx - x) ** 2 + (yy - y) ** 2 <= padding ** 2:
                    mask[yy][xx] = True
    return mask


def default_garment_pixels(style="toga", width=CANVAS_WIDTH, height=CANVAS_HEIGHT):
    """Seed the two test items without treating them as special entity types."""
    marks = body_landmarks(DEFAULT_BODY_SHAPE, width, height)
    pixels = _blank(width, height)
    style = str(style or "toga").lower()
    primary = (217, 208, 182) if style == "toga" else (38, 52, 71)
    accent = (141, 111, 69) if style == "toga" else (230, 225, 215)
    top = int(marks["shoulder_y"])
    hip = int(marks["hip_y"])
    cx = int(round(marks["center_x"]))
    half = max(3, int(round(marks["shoulder_half"])))
    bottom = int(marks["ankle_y"] - 7) if style == "toga" else int(marks["ankle_y"] - 2)
    for y in range(top, bottom + 1):
        if style == "toga":
            ratio = max(0.0, min(1.0, (y - hip) / max(1, bottom - hip)))
            row_half = round(half + ratio * 3)
        else:
            row_half = half if y <= hip else max(1, half // 2)
        for x in range(max(0, cx - row_half), min(width, cx + row_half + 1)):
            if style == "suit" and y > hip and abs(x - cx) <= 1:
                continue
            pixels[y][x] = primary
    if style == "suit":
        for y in range(top + 1, min(hip, top + 12)):
            pixels[y][cx] = accent
        for side in (-1, 1):
            _paint_line(pixels, (cx + side * half, top + 1),
                        (marks["left_wrist_x"] if side < 0 else marks["right_wrist_x"], marks["wrist_y"]),
                        1.5, primary)
    else:
        _paint_line(pixels, (cx - half, top), (cx + half, top + 6), 1.0, accent)
    return pixels


def _map_point(x, y, source, target):
    # Sleeves follow shoulder -> wrist independently of the torso.
    torso_edge = source["torso_half"] * 1.15
    if source["shoulder_y"] <= y <= source["wrist_y"] and abs(x - source["center_x"]) > torso_edge:
        side = -1 if x < source["center_x"] else 1
        sy = source["shoulder_y"]
        ratio = (y - sy) / max(1e-6, source["wrist_y"] - sy)
        source_anchor = source["left_shoulder_x"] if side < 0 else source["right_shoulder_x"]
        target_anchor = target["left_shoulder_x"] if side < 0 else target["right_shoulder_x"]
        target_wrist_x = target["left_wrist_x"] if side < 0 else target["right_wrist_x"]
        mapped_x = target_anchor + (target_wrist_x - target_anchor) * ratio + (x - source_anchor)
        mapped_y = target["shoulder_y"] + (target["wrist_y"] - target["shoulder_y"]) * ratio
        return mapped_x, mapped_y
    if y <= source["hip_y"]:
        ratio = (y - source["top_y"]) / max(1e-6, source["hip_y"] - source["top_y"])
        width_scale = target["torso_half"] / max(1e-6, source["torso_half"])
        return (target["center_x"] + (x - source["center_x"]) * width_scale,
                target["top_y"] + (target["hip_y"] - target["top_y"]) * ratio)
    ratio = (y - source["hip_y"]) / max(1e-6, source["ankle_y"] - source["hip_y"])
    width_scale = (0.7 + target["torso_half"]) / max(1e-6, 0.7 + source["torso_half"])
    return (target["center_x"] + (x - source["center_x"]) * width_scale,
            target["hip_y"] + (target["ankle_y"] - target["hip_y"]) * ratio)


def warp_clothing_pixels(pixels, source_body_shape, target_body_shape):
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    output = _blank(width, height)
    if not width or not height:
        return output
    source = body_landmarks(source_body_shape, width, height)
    target = body_landmarks(target_body_shape, width, height)
    for y, row in enumerate(pixels):
        for x, color in enumerate(row):
            if color is None:
                continue
            mapped_x, mapped_y = _map_point(x, y, source, target)
            tx, ty = int(round(mapped_x)), int(round(mapped_y))
            if 0 <= tx < width and 0 <= ty < height:
                output[ty][tx] = deepcopy(color)
                # A small forward splat prevents holes when a size grows.
                if tx + 1 < width and mapped_x - x > 0.35:
                    output[ty][tx + 1] = deepcopy(color)
                if ty + 1 < height and mapped_y - y > 0.35:
                    output[ty + 1][tx] = deepcopy(color)
    return output


def is_clothing_item(entity, world_model=None, clothing_category_id="cat_clothing"):
    """True for items categorized anywhere below the Clothing category."""
    if not isinstance(entity, dict) or str(entity.get("type") or entity.get("_dataset") or "").lower() not in {"item", "items"}:
        return False
    pending = list(entity.get("categories") or [])
    seen = set()
    while pending:
        category_id = str(pending.pop() or "").strip()
        if not category_id or category_id in seen:
            continue
        if category_id == clothing_category_id:
            return True
        seen.add(category_id)
        category = world_model.get_entity(category_id) if world_model is not None and hasattr(world_model, "get_entity") else None
        if isinstance(category, dict):
            parents = category.get("parents") or []
            pending.extend([parents] if isinstance(parents, str) else parents)
    return False
