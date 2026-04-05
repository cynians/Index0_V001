class ScaleHelper:
    """
    Shared scaling helpers for preview boxes and drawing-canvas suggestions.
    """

    DEFAULT_CANVAS_W = 128
    DEFAULT_CANVAS_H = 96

    @staticmethod
    def extract_dimensions_m(entity):
        """
        Extract X/Y/Z dimensions in meters when available.
        """
        if entity is None:
            return None

        def _safe_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        x = _safe_float(entity.get("dimension_x_m"))
        y = _safe_float(entity.get("dimension_y_m"))
        z = _safe_float(entity.get("dimension_z_m"))

        if x is None and y is None and z is None:
            return None

        return {
            "x": x,
            "y": y,
            "z": z,
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
    def _pixel_art_target_width(longest_side_m, max_canvas_w=4096):
        if longest_side_m < 2:
            return 64
        if longest_side_m < 10:
            return 96
        if longest_side_m < 50:
            return 128
        if longest_side_m < 200:
            return 192
        if longest_side_m < 1000:
            return 256
        if longest_side_m < 10000:
            return 384
        if longest_side_m < 100000:
            return 512
        if longest_side_m < 1000000:
            return 1024
        return min(4096, max_canvas_w)

    @staticmethod
    def _suggest_pair(width_basis, height_basis, role_name, max_canvas_w=4096, default_w=128, default_h=96):
        if width_basis is None or height_basis is None or width_basis <= 0 or height_basis <= 0:
            return {
                "role": role_name,
                "width": default_w,
                "height": default_h,
                "basis": "default",
            }

        longest_side_m = max(width_basis, height_basis)
        target_w = ScaleHelper._pixel_art_target_width(longest_side_m, max_canvas_w=max_canvas_w)
        aspect = height_basis / width_basis
        target_h = max(32, int(round(target_w * aspect)))

        return {
            "role": role_name,
            "width": target_w,
            "height": target_h,
            "basis": f"{width_basis}m x {height_basis}m",
        }

    @staticmethod
    def suggest_canvas_from_dimensions(entity, max_canvas_w=4096):
        """
        Suggest a restrained pixel-art drawing canvas from entity dimensions.

        Small/medium objects get much smaller canvases than before.
        Planetary-scale bodies can still go large.
        """
        dims = ScaleHelper.extract_dimensions_m(entity)

        if dims is None:
            return {
                "width": 128,
                "height": 96,
                "basis": "default",
            }

        x = dims.get("x")
        y = dims.get("y")
        z = dims.get("z")

        width_basis = x
        height_basis = y

        if width_basis is None or height_basis is None:
            if x is not None and z is not None:
                width_basis = x
                height_basis = z

        if width_basis is None or height_basis is None or width_basis <= 0 or height_basis <= 0:
            return {
                "width": 128,
                "height": 96,
                "basis": "default",
            }

        longest_side_m = max(width_basis, height_basis)
        target_w = ScaleHelper._pixel_art_target_width(longest_side_m, max_canvas_w=max_canvas_w)
        aspect = height_basis / width_basis
        target_h = max(32, int(round(target_w * aspect)))

        return {
            "width": target_w,
            "height": target_h,
            "basis": f"{width_basis}m x {height_basis}m",
        }

    @staticmethod
    def suggest_vehicle_view_canvases(entity, max_canvas_w=4096):
        """
        Suggest separate front / side / top placeholder canvases for vehicles.

        Uses:
        - X = length
        - Y = width
        - Z = height
        """
        dims = ScaleHelper.extract_dimensions_m(entity)

        if dims is None:
            return [
                {"view": "front", "width": 96, "height": 96, "basis": "default"},
                {"view": "side", "width": 128, "height": 96, "basis": "default"},
                {"view": "top", "width": 128, "height": 96, "basis": "default"},
            ]

        x = dims.get("x")
        y = dims.get("y")
        z = dims.get("z")

        def _suggest_pair_local(width_basis, height_basis, view_name):
            if width_basis is None or height_basis is None or width_basis <= 0 or height_basis <= 0:
                return {
                    "view": view_name,
                    "width": 128,
                    "height": 96,
                    "basis": "default",
                }

            longest_side_m = max(width_basis, height_basis)
            target_w = ScaleHelper._pixel_art_target_width(longest_side_m, max_canvas_w=max_canvas_w)
            aspect = height_basis / width_basis
            target_h = max(32, int(round(target_w * aspect)))

            return {
                "view": view_name,
                "width": target_w,
                "height": target_h,
                "basis": f"{width_basis}m x {height_basis}m",
            }

        return [
            _suggest_pair_local(y, z, "front"),
            _suggest_pair_local(x, z, "side"),
            _suggest_pair_local(x, y, "top"),
        ]

    @staticmethod
    def suggest_default_media_roles(entity):
        """
        Return the default ordered media-role list for an entity.
        """
        if entity is None:
            return ["card"]

        dataset = entity.get("_dataset")
        entity_type = entity.get("type")
        location_class = entity.get("location_class")

        if entity_type == "vehicle" or dataset == "vehicles":
            return ["card", "design", "front", "side", "top"]

        if entity_type == "species" or dataset == "species":
            return ["card", "portrait", "diagram"]

        if dataset in {"components", "items", "materials"} or entity_type in {"component", "item", "material"}:
            return ["card", "diagram"]

        if dataset == "locations" or entity_type == "location" or location_class is not None:
            return ["card", "map"]

        return ["card"]

    @staticmethod
    def suggest_media_canvas(entity, role, max_canvas_w=4096):
        """
        Suggest a canvas for a specific media role.
        """
        role = (role or "card").lower()
        dims = ScaleHelper.extract_dimensions_m(entity)

        if role == "card":
            base = ScaleHelper.suggest_canvas_from_dimensions(entity, max_canvas_w=max_canvas_w)
            return {
                "role": role,
                "width": base["width"],
                "height": base["height"],
                "basis": base["basis"],
            }

        if role in {"front", "side", "top"}:
            vehicle_views = {
                item["view"]: item
                for item in ScaleHelper.suggest_vehicle_view_canvases(entity, max_canvas_w=max_canvas_w)
            }
            chosen = vehicle_views.get(role)
            if chosen is None:
                return {
                    "role": role,
                    "width": 128,
                    "height": 96,
                    "basis": "default",
                }
            return {
                "role": role,
                "width": chosen["width"],
                "height": chosen["height"],
                "basis": chosen["basis"],
            }

        if role == "map":
            if dims is not None:
                x = dims.get("x")
                y = dims.get("y")
                if x is not None and y is not None and x > 0 and y > 0:
                    return ScaleHelper._suggest_pair(x, y, role, max_canvas_w=max_canvas_w, default_w=256, default_h=160)
            return {
                "role": role,
                "width": 256,
                "height": 160,
                "basis": "default",
            }

        if role == "portrait":
            return {
                "role": role,
                "width": 96,
                "height": 128,
                "basis": "portrait_default",
            }

        if role == "diagram":
            return {
                "role": role,
                "width": 160,
                "height": 120,
                "basis": "diagram_default",
            }

        return {
            "role": role,
            "width": 128,
            "height": 96,
            "basis": "default",
        }

    @staticmethod
    def suggest_media_canvases(entity, max_canvas_w=4096):
        """
        Return ordered media-role suggestions for an entity.
        """
        roles = ScaleHelper.suggest_default_media_roles(entity)
        return [
            ScaleHelper.suggest_media_canvas(entity, role, max_canvas_w=max_canvas_w)
            for role in roles
        ]

    @staticmethod
    def preview_fit_mode_for_role(role):
        """
        Return a simple preview-fit policy hint for UI rendering.
        """
        role = (role or "card").lower()

        if role in {"map", "diagram", "front", "side", "top", "card"}:
            return "contain"

        if role == "portrait":
            return "contain_center"

        return "contain"

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