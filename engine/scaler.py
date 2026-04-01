class ScaleHelper:
    """
    Shared scaling helpers for preview boxes and drawing-canvas suggestions.
    """

    DEFAULT_CANVAS_W = 1600
    DEFAULT_CANVAS_H = 900

    @staticmethod
    def extract_dimensions_m(entity):
        """
        Extract X/Y/Z dimensions in meters when available.
        """
        if entity is None:
            return None

        x = entity.get("dimension_x_m")
        y = entity.get("dimension_y_m")
        z = entity.get("dimension_z_m")

        if x is None and y is None and z is None:
            return None

        return {
            "x": float(x) if x is not None else None,
            "y": float(y) if y is not None else None,
            "z": float(z) if z is not None else None,
        }

    @staticmethod
    def fit_size_into_box(content_w, content_h, box_w, box_h):
        """
        Fit a content rectangle into a box while preserving aspect ratio.
        """
        content_w = max(1.0, float(content_w))
        content_h = max(1.0, float(content_h))
        box_w = max(1.0, float(box_w))
        box_h = max(1.0, float(box_h))

        scale = min(box_w / content_w, box_h / content_h)
        return int(content_w * scale), int(content_h * scale)

    @staticmethod
    def suggest_canvas_from_dimensions(entity, max_canvas_w=2048):
        """
        Suggest a drawing-canvas size from entity dimensions when possible.
        """
        dims = ScaleHelper.extract_dimensions_m(entity)

        if dims is None:
            return {
                "width": ScaleHelper.DEFAULT_CANVAS_W,
                "height": ScaleHelper.DEFAULT_CANVAS_H,
                "basis": "default",
            }

        x = dims.get("x")
        y = dims.get("y")
        z = dims.get("z")

        width_basis = x
        height_basis = y

        if width_basis is None and height_basis is None:
            width_basis = x
            height_basis = z

        if width_basis is None or height_basis is None:
            return {
                "width": ScaleHelper.DEFAULT_CANVAS_W,
                "height": ScaleHelper.DEFAULT_CANVAS_H,
                "basis": "default",
            }

        if width_basis <= 0 or height_basis <= 0:
            return {
                "width": ScaleHelper.DEFAULT_CANVAS_W,
                "height": ScaleHelper.DEFAULT_CANVAS_H,
                "basis": "default",
            }

        preferred_widths = [1024, 1536, 2048]
        target_w = next((value for value in preferred_widths if value <= max_canvas_w), 1024)
        aspect = height_basis / width_basis
        target_h = max(256, int(round(target_w * aspect)))

        return {
            "width": target_w,
            "height": target_h,
            "basis": f"{width_basis}m x {height_basis}m",
        }

    @staticmethod
    def format_dimensions_label(entity):
        dims = ScaleHelper.extract_dimensions_m(entity)
        if dims is None:
            return "No physical dimensions recorded"

        parts = []
        if dims.get("x") is not None:
            parts.append(f"X {dims['x']} m")
        if dims.get("y") is not None:
            parts.append(f"Y {dims['y']} m")
        if dims.get("z") is not None:
            parts.append(f"Z {dims['z']} m")

        return " | ".join(parts) if parts else "No physical dimensions recorded"