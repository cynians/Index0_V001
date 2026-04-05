class VehicleDesignController:
    """
    Stores vehicle design-state and design-specific interaction logic.

    Current slice:
    * stores physical vehicle dimensions in SI units
    * stores a simple component catalog
    * stores placed design components in local vehicle-space meters
    * exposes design render payloads
    * supports true drag-and-drop placement and repositioning inside the hull
    * can bootstrap its state from repository entities
    * resolves hierarchical functional requirements by vehicle class
    * evaluates which requirements are satisfied by currently placed components
    * prefers repository-defined vehicle/component metadata before fallback maps
    """

    CATALOG_PANEL_X = 18
    CATALOG_PANEL_Y = 18
    CATALOG_PANEL_W = 320
    CATALOG_ENTRY_H = 28
    CATALOG_HEADER_H = 28
    CATALOG_PADDING = 10

    VEHICLE_CLASS_PARENTS = {
        "vehicle": [],
        "ground_vehicle": ["vehicle"],
        "car": ["ground_vehicle"],
        "urban_taxi": ["car"],
        "compact_grand_touring_convertible": ["car"],
        "suv": ["car"],
        "race_car": ["car"],
        "amphibious_front_line_transport": ["ground_vehicle"],
        "naval_vehicle": ["vehicle"],
        "naval_combat_drone": ["naval_vehicle"],
        "fleet_destroyer": ["naval_vehicle"],
        "spacecraft": ["vehicle"],
        "interplanetary_cargo_transport": ["spacecraft"],
        "mars_cargo_lander": ["spacecraft"],
        "communications_cruiser": ["spacecraft"],
        "artillery": ["vehicle"],
        "towed_anti_tank_gun": ["artillery"],
        "stealth_air_dominance_fighter": ["vehicle"],
    }

    VEHICLE_CLASS_REQUIREMENTS = {
        "vehicle": [
            "structure",
            "control",
        ],
        "ground_vehicle": [
            "locomotion_ground",
        ],
        "car": [
            "wheels",
            "propulsion_road",
        ],
        "race_car": [
            "performance_wheels",
        ],
        "naval_vehicle": [
            "hull",
            "propulsion_marine",
        ],
        "spacecraft": [
            "spaceframe",
            "propulsion_space",
        ],
        "mars_cargo_lander": [
            "landing_system",
            "cargo_handling",
        ],
        "communications_cruiser": [
            "communications_system",
        ],
        "interplanetary_cargo_transport": [
            "cargo_handling",
        ],
        "artillery": [
            "weapon_system",
            "carriage",
        ],
        "stealth_air_dominance_fighter": [
            "propulsion_air",
            "flight_surfaces",
        ],
    }

    COMPONENT_CATEGORY_HINTS = {
        "engine_component": {"propulsion_road", "powertrain"},
        "motor_component": {"propulsion_road", "powertrain"},
        "wheel_component": {"locomotion_ground", "wheels"},
        "performance_wheel_component": {"locomotion_ground", "wheels", "performance_wheels"},
        "track_component": {"locomotion_ground", "tracks"},
        "control_component": {"control"},
        "cockpit_component": {"control"},
        "body_component": {"structure", "body"},
        "vehicle_body_component": {"structure", "body"},
        "frame_component": {"structure", "spaceframe"},
        "hull_component": {"structure", "hull"},
        "roof_system_component": {"body"},
        "landing_gear_component": {"landing_system"},
        "cargo_component": {"cargo_handling"},
        "comm_component": {"communications_system"},
        "weapon_component": {"weapon_system"},
        "carriage_component": {"carriage"},
        "aero_surface_component": {"flight_surfaces"},
        "thruster_component": {"propulsion_space"},
        "reactor_component": {"propulsion_space", "powertrain"},
        "marine_drive_component": {"propulsion_marine"},
        "jet_engine_component": {"propulsion_air", "powertrain"},
        "drive_system_component": {"propulsion_road", "powertrain"},
    }

    REQUIREMENT_TO_OPERATIONAL_GROUP = {
        "structure": "Structure",
        "body": "Structure",
        "spaceframe": "Structure",
        "hull": "Structure",
        "control": "Crew & Control",
        "locomotion_ground": "Mobility",
        "wheels": "Mobility",
        "performance_wheels": "Mobility",
        "tracks": "Mobility",
        "carriage": "Mobility",
        "propulsion_road": "Powertrain",
        "propulsion_space": "Powertrain",
        "propulsion_marine": "Powertrain",
        "propulsion_air": "Powertrain",
        "powertrain": "Powertrain",
        "landing_system": "Mobility",
        "cargo_handling": "Cargo",
        "communications_system": "Sensors & Comms",
        "weapon_system": "Weapons",
        "flight_surfaces": "Control Surfaces",
    }

    REQUIREMENT_TO_SUBSYSTEM = {
        "structure": "core structure",
        "body": "body",
        "spaceframe": "spaceframe",
        "hull": "hull",
        "fuselage": "fuselage",
        "wings": "wings",
        "tail": "tail",
        "control": "control linkages",
        "cockpit": "cockpit",
        "avionics": "avionics",
        "locomotion_ground": "ground locomotion",
        "wheels": "wheels",
        "performance_wheels": "performance wheels",
        "tracks": "tracks",
        "carriage": "carriage",
        "landing_system": "landing system",
        "propulsion_road": "road propulsion",
        "propulsion_space": "space propulsion",
        "propulsion_marine": "marine propulsion",
        "propulsion_air": "air propulsion",
        "powertrain": "powertrain core",
        "cargo_handling": "cargo handling",
        "communications_system": "communications",
        "weapon_system": "weapon system",
        "flight_surfaces": "flight surfaces",
    }

    def __init__(self, world_model=None, vehicle_entity=None):
        self.world_model = world_model
        self.vehicle_entity = vehicle_entity

        self.vehicle_dimensions_m = self._load_vehicle_dimensions_m(vehicle_entity)
        self.component_catalog = self._load_component_catalog(world_model, vehicle_entity)
        self.placed_components = self._load_placed_components(world_model, vehicle_entity)

        if not self.placed_components and self.component_catalog:
            first_entry = self.component_catalog[0]
            self.placed_components = [
                {
                    "instance_id": "placed_component_001",
                    "catalog_id": first_entry["id"],
                    "label": first_entry["label"],
                    "component_type": first_entry["component_type"],
                    "satisfies_categories": list(first_entry.get("satisfies_categories", [])),
                    "operational_groups": list(first_entry.get("operational_groups", [])),
                    "subsystem_labels": list(first_entry.get("subsystem_labels", [])),
                    "local_rect_m": {
                        "x": 0.8,
                        "y": 1.4,
                        "width": first_entry["dimensions_m"]["x"],
                        "height": first_entry["dimensions_m"]["y"],
                    },
                }
            ]

        self.next_component_index = self._infer_next_component_index()

        self.hover_component_id = None
        self.selected_component_id = None
        self.active_catalog_component_id = None
        self.hover_catalog_component_id = None

        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

    def _load_vehicle_dimensions_m(self, vehicle_entity):
        if vehicle_entity:
            return {
                "x": float(vehicle_entity.get("dimension_x_m", 10.0)),
                "y": float(vehicle_entity.get("dimension_y_m", 4.0)),
                "z": float(vehicle_entity.get("dimension_z_m", 3.0)),
            }

        return {
            "x": 10.0,
            "y": 4.0,
            "z": 3.0,
        }

    def _infer_satisfies_categories_from_entity(self, entity):
        categories = set()

        component_class = str(entity.get("component_class", "")).strip().lower()
        categories.update(self.COMPONENT_CATEGORY_HINTS.get(component_class, set()))

        for field_name in ("functional_roles", "tags", "satisfies_categories"):
            values = entity.get(field_name, [])
            if isinstance(values, list):
                for value in values:
                    text = str(value).strip().lower()
                    if text:
                        categories.add(text)

        label_text = " ".join(
            str(entity.get(key, ""))
            for key in ("pretty_name", "name", "component_class")
        ).lower()

        if "wheel" in label_text:
            categories.update({"locomotion_ground", "wheels"})
        if "track" in label_text:
            categories.update({"locomotion_ground", "tracks"})
        if "engine" in label_text or "motor" in label_text:
            categories.update({"powertrain"})
        if "performance" in label_text and "wheel" in label_text:
            categories.update({"performance_wheels"})
        if "control" in label_text or "cockpit" in label_text:
            categories.update({"control"})
        if "body" in label_text or "chassis" in label_text:
            categories.update({"structure", "body"})
        if "hull" in label_text:
            categories.update({"hull", "structure"})
        if "landing" in label_text and "gear" in label_text:
            categories.update({"landing_system"})
        if "cargo" in label_text:
            categories.update({"cargo_handling"})
        if "comm" in label_text or "antenna" in label_text or "relay" in label_text:
            categories.update({"communications_system"})
        if "weapon" in label_text or "gun" in label_text or "cannon" in label_text:
            categories.update({"weapon_system"})
        if "thruster" in label_text or "rocket" in label_text:
            categories.update({"propulsion_space"})
        if "marine" in label_text or "propeller" in label_text:
            categories.update({"propulsion_marine"})
        if "jet" in label_text or "turbofan" in label_text:
            categories.update({"propulsion_air", "powertrain"})
        if "roof" in label_text:
            categories.update({"body"})

        return sorted(categories)

    def _build_catalog_entry_from_component_entity(self, entity):
        raw_operational_groups = entity.get("operational_groups", [])
        operational_groups = [str(v).strip() for v in raw_operational_groups if str(v).strip()]

        raw_subsystem_labels = entity.get("subsystem_labels", [])
        subsystem_labels = [str(v).strip() for v in raw_subsystem_labels if str(v).strip()]

        return {
            "id": entity.get("id"),
            "label": entity.get("pretty_name", entity.get("name", entity.get("id", "component"))),
            "component_type": entity.get("component_class", "component"),
            "entry_type": entity.get("type", "component"),
            "dimensions_m": {
                "x": float(entity.get("dimension_x_m", 1.0)),
                "y": float(entity.get("dimension_y_m", 1.0)),
                "z": float(entity.get("dimension_z_m", 1.0)),
            },
            "mass_kg": float(entity.get("mass_kg", 0.0)),
            "power_kw": float(entity.get("power_kw", 0.0)),
            "satisfies_categories": self._infer_satisfies_categories_from_entity(entity),
            "operational_groups": operational_groups,
            "subsystem_labels": subsystem_labels,
        }

    def _default_component_catalog(self):
        return [
            {
                "id": "comp_engine_inline_compact",
                "label": "Inline Engine",
                "component_type": "engine_component",
                "entry_type": "component",
                "dimensions_m": {"x": 2.2, "y": 1.2, "z": 1.4},
                "mass_kg": 680.0,
                "power_kw": 180.0,
                "satisfies_categories": ["propulsion_road", "powertrain"],
                "operational_groups": ["Powertrain"],
                "subsystem_labels": ["road propulsion"],
            },
            {
                "id": "comp_engine_vblock_heavy",
                "label": "V-Block Engine",
                "component_type": "engine_component",
                "entry_type": "component",
                "dimensions_m": {"x": 2.8, "y": 1.5, "z": 1.6},
                "mass_kg": 980.0,
                "power_kw": 320.0,
                "satisfies_categories": ["propulsion_road", "powertrain"],
                "operational_groups": ["Powertrain"],
                "subsystem_labels": ["road propulsion"],
            },
        ]

    def _load_component_catalog(self, world_model, vehicle_entity):
        if world_model is None or vehicle_entity is None:
            return self._default_component_catalog()

        component_ids = vehicle_entity.get("design_catalog_components", [])
        catalog = []

        for component_id in component_ids:
            entity = world_model.get_entity(component_id)
            if entity is None:
                continue
            catalog.append(self._build_catalog_entry_from_component_entity(entity))

        return catalog or self._default_component_catalog()

    def _load_placed_components(self, world_model, vehicle_entity):
        placed = []

        if vehicle_entity is None:
            return placed

        design_placed_components = vehicle_entity.get("design_placed_components", [])
        for entry in design_placed_components:
            if not isinstance(entry, dict):
                continue

            component_id = entry.get("component_id")
            component_entity = world_model.get_entity(component_id) if (world_model and component_id) else None

            if component_entity is not None:
                label = component_entity.get("pretty_name", component_entity.get("name", component_id))
                component_type = component_entity.get("component_class", "component")
                entry_type = component_entity.get("type", "component")
                width = float(entry.get("width_m", component_entity.get("dimension_x_m", 1.0)))
                height = float(entry.get("height_m", component_entity.get("dimension_y_m", 1.0)))
                satisfies_categories = self._infer_satisfies_categories_from_entity(component_entity)

                raw_operational_groups = component_entity.get("operational_groups", [])
                operational_groups = [str(v).strip() for v in raw_operational_groups if str(v).strip()]

                raw_subsystem_labels = component_entity.get("subsystem_labels", [])
                subsystem_labels = [str(v).strip() for v in raw_subsystem_labels if str(v).strip()]
            else:
                label = entry.get("label", component_id or "component")
                component_type = entry.get("component_type", "component")
                entry_type = entry.get("entry_type", "component")
                width = float(entry.get("width_m", 1.0))
                height = float(entry.get("height_m", 1.0))

                raw_categories = entry.get("satisfies_categories", [])
                satisfies_categories = [str(v).strip().lower() for v in raw_categories if str(v).strip()]

                raw_operational_groups = entry.get("operational_groups", [])
                operational_groups = [str(v).strip() for v in raw_operational_groups if str(v).strip()]

                raw_subsystem_labels = entry.get("subsystem_labels", [])
                subsystem_labels = [str(v).strip() for v in raw_subsystem_labels if str(v).strip()]

            placed.append(
                {
                    "instance_id": entry.get("instance_id", "placed_component_001"),
                    "catalog_id": component_id,
                    "label": label,
                    "component_type": component_type,
                    "entry_type": entry_type,
                    "satisfies_categories": satisfies_categories,
                    "operational_groups": operational_groups,
                    "subsystem_labels": subsystem_labels,
                    "local_rect_m": {
                        "x": float(entry.get("local_x_m", 0.0)),
                        "y": float(entry.get("local_y_m", 0.0)),
                        "width": width,
                        "height": height,
                    },
                }
            )

        return placed

    def _infer_next_component_index(self):
        max_index = 0
        for component in self.placed_components:
            instance_id = component.get("instance_id", "")
            if not instance_id.startswith("placed_component_"):
                continue
            try:
                index_value = int(instance_id.split("_")[-1])
                max_index = max(max_index, index_value)
            except ValueError:
                continue
        return max_index + 1 if max_index > 0 else 1

    def get_vehicle_dimensions_m(self):
        return dict(self.vehicle_dimensions_m)

    def get_component_catalog(self):
        return list(self.component_catalog)

    def get_grouped_component_catalog(self):
        grouped = {}

        def entry_type_rank(entry):
            entry_type = str(entry.get("entry_type", "component")).strip().lower()
            return 0 if entry_type == "assembly" else 1

        sorted_entries = sorted(
            self.component_catalog,
            key=lambda entry: (
                entry_type_rank(entry),
                str(entry.get("entry_type", "component")).strip().lower(),
                (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                str(entry.get("label", "")),
            ),
        )

        for entry in sorted_entries:
            entry_type = str(entry.get("entry_type", "component")).strip().lower() or "component"
            group_name = (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems")
            group_name = str(group_name).strip() or "General Systems"

            section_title = f"{entry_type.title()}s / {group_name}"
            bucket = grouped.setdefault(
                section_title,
                {
                    "title": section_title,
                    "entry_type": entry_type,
                    "group_name": group_name,
                    "entries": [],
                },
            )
            bucket["entries"].append(entry)

        sections = list(grouped.values())
        sections.sort(
            key=lambda section: (
                0 if section["entry_type"] == "assembly" else 1,
                section["group_name"],
                section["title"],
            )
        )
        return sections



    def get_component_catalog_entry(self, catalog_id):
        for entry in self.component_catalog:
            if entry.get("id") == catalog_id:
                return entry
        return None

    def get_catalog_panel_rect(self):
        grouped_catalog = self.get_grouped_component_catalog()
        row_height = self.CATALOG_ENTRY_H
        section_gap = 8

        total_rows = 0
        for section in grouped_catalog:
            total_rows += 1
            total_rows += len(section.get("entries", []))

        height = (
            self.CATALOG_HEADER_H
            + self.CATALOG_PADDING
            + total_rows * row_height
            + max(0, len(grouped_catalog) - 1) * section_gap
            + self.CATALOG_PADDING
        )

        return {
            "x": self.CATALOG_PANEL_X,
            "y": self.CATALOG_PANEL_Y,
            "width": self.CATALOG_PANEL_W,
            "height": max(height, self.CATALOG_HEADER_H + self.CATALOG_PADDING * 2),
            "section_gap": section_gap,
        }

    def get_catalog_entry_rects(self):
        rects = []
        panel = self.get_catalog_panel_rect()
        grouped_catalog = self.get_grouped_component_catalog()

        entry_x = panel["x"] + self.CATALOG_PADDING
        entry_y = panel["y"] + self.CATALOG_HEADER_H + self.CATALOG_PADDING
        entry_w = panel["width"] - 2 * self.CATALOG_PADDING
        row_height = self.CATALOG_ENTRY_H
        section_gap = panel.get("section_gap", 8)

        for section in grouped_catalog:
            rects.append(
                {
                    "kind": "section",
                    "section_title": section["title"],
                    "catalog_id": None,
                    "label": section["title"],
                    "x": entry_x,
                    "y": entry_y,
                    "width": entry_w,
                    "height": row_height - 6,
                }
            )
            entry_y += row_height

            for entry in section.get("entries", []):
                rects.append(
                    {
                        "kind": "entry",
                        "section_title": section["title"],
                        "catalog_id": entry["id"],
                        "label": entry.get("label", entry["id"]),
                        "entry_type": entry.get("entry_type", "component"),
                        "group_name": (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                        "x": entry_x + 12,
                        "y": entry_y,
                        "width": entry_w - 12,
                        "height": row_height - 4,
                    }
                )
                entry_y += row_height

            entry_y += section_gap

        return rects

    def get_catalog_entry_at_screen_position(self, screen_pos):
        sx, sy = screen_pos
        for rect in self.get_catalog_entry_rects():
            if rect.get("kind") != "entry":
                continue
            if (
                rect["x"] <= sx <= rect["x"] + rect["width"]
                and rect["y"] <= sy <= rect["y"] + rect["height"]
            ):
                return rect["catalog_id"]
        return None

    def get_placed_components(self):
        return list(self.placed_components)

    def _resolve_vehicle_class_chain(self, vehicle_class):
        normalized = str(vehicle_class or "vehicle").strip().lower() or "vehicle"
        ordered = []
        visited = set()

        explicit_parents = []
        if self.vehicle_entity is not None:
            raw_parents = self.vehicle_entity.get("vehicle_class_parents", [])
            if isinstance(raw_parents, list):
                explicit_parents = [
                    str(parent).strip().lower()
                    for parent in raw_parents
                    if str(parent).strip()
                ]

        def visit(class_name):
            if class_name in visited:
                return
            visited.add(class_name)

            if class_name == normalized and explicit_parents:
                parent_list = explicit_parents
            else:
                parent_list = self.VEHICLE_CLASS_PARENTS.get(class_name, [])

            for parent in parent_list:
                visit(parent)

            ordered.append(class_name)

        visit(normalized)
        if "vehicle" not in visited:
            visit("vehicle")
        return ordered

    def get_resolved_required_categories(self):
        if self.vehicle_entity is not None:
            explicit_required = self.vehicle_entity.get("required_categories", [])
            explicit_overrides = self.vehicle_entity.get("required_category_overrides", [])

            if isinstance(explicit_required, list) and explicit_required:
                resolved = []
                seen = set()

                for category in explicit_required:
                    text = str(category).strip().lower()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    resolved.append(
                        {
                            "category": text,
                            "source_class": "entry_required_categories",
                        }
                    )

                if isinstance(explicit_overrides, list):
                    for category in explicit_overrides:
                        text = str(category).strip().lower()
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        resolved.append(
                            {
                                "category": text,
                                "source_class": "entry_required_category_overrides",
                            }
                        )

                return resolved

        vehicle_class = ""
        if self.vehicle_entity is not None:
            vehicle_class = self.vehicle_entity.get("vehicle_class", "vehicle")

        class_chain = self._resolve_vehicle_class_chain(vehicle_class)
        resolved = []
        seen = set()

        for class_name in class_chain:
            for requirement in self.VEHICLE_CLASS_REQUIREMENTS.get(class_name, []):
                if requirement in seen:
                    continue
                seen.add(requirement)
                resolved.append(
                    {
                        "category": requirement,
                        "source_class": class_name,
                    }
                )

        return resolved

    def _get_component_satisfaction_categories(self, component):
        categories = set()

        for value in component.get("satisfies_categories", []):
            text = str(value).strip().lower()
            if text:
                categories.add(text)

        component_type = str(component.get("component_type", "")).strip().lower()
        categories.update(self.COMPONENT_CATEGORY_HINTS.get(component_type, set()))

        label_text = " ".join(
            str(component.get(key, ""))
            for key in ("label", "catalog_id", "component_type")
        ).lower()

        if "wheel" in label_text:
            categories.update({"locomotion_ground", "wheels"})
        if "performance" in label_text and "wheel" in label_text:
            categories.update({"performance_wheels"})
        if "track" in label_text:
            categories.update({"locomotion_ground", "tracks"})
        if "engine" in label_text or "motor" in label_text:
            categories.update({"powertrain"})
        if "control" in label_text or "cockpit" in label_text:
            categories.update({"control"})
        if "body" in label_text or "chassis" in label_text:
            categories.update({"structure", "body"})
        if "hull" in label_text:
            categories.update({"hull", "structure"})
        if "landing" in label_text and "gear" in label_text:
            categories.update({"landing_system"})
        if "cargo" in label_text:
            categories.update({"cargo_handling"})
        if "comm" in label_text or "antenna" in label_text or "relay" in label_text:
            categories.update({"communications_system"})
        if "weapon" in label_text or "gun" in label_text or "cannon" in label_text:
            categories.update({"weapon_system"})
        if "roof" in label_text:
            categories.update({"body"})

        return categories

    def get_requirement_status_list(self):
        required = self.get_resolved_required_categories()
        placed = self.get_placed_components()

        placed_category_map = {}
        for component in placed:
            categories = self._get_component_satisfaction_categories(component)
            for category in categories:
                placed_category_map.setdefault(category, []).append(component)

        results = []
        for requirement in required:
            category = requirement["category"]
            matching_components = placed_category_map.get(category, [])
            results.append(
                {
                    "category": category,
                    "source_class": requirement["source_class"],
                    "is_satisfied": bool(matching_components),
                    "matching_component_ids": [c.get("instance_id") for c in matching_components],
                    "matching_component_labels": [c.get("label", c.get("instance_id", "component")) for c in matching_components],
                }
            )

        return results

    def get_operational_system_summary(self):
        """
        Group hierarchical requirement status into operational system buckets
        with child subsystems. Prefer repository-defined operational_groups and
        subsystem_labels when available.
        """
        requirement_status = self.get_requirement_status_list()
        grouped = {}

        for entry in requirement_status:
            category = entry.get("category", "requirement")
            group_name = self.REQUIREMENT_TO_OPERATIONAL_GROUP.get(category, "General Systems")
            subsystem_name = self.REQUIREMENT_TO_SUBSYSTEM.get(category, category.replace("_", " "))

            bucket = grouped.setdefault(
                group_name,
                {
                    "group": group_name,
                    "children": [],
                    "component_labels": [],
                    "all_satisfied": True,
                    "any_satisfied": False,
                },
            )

            is_satisfied = bool(entry.get("is_satisfied"))
            matching_component_labels = list(entry.get("matching_component_labels", []))
            child_status = "active" if is_satisfied else "missing"

            bucket["children"].append(
                {
                    "category": category,
                    "label": subsystem_name,
                    "source_class": entry.get("source_class", "vehicle"),
                    "status": child_status,
                    "matching_component_labels": matching_component_labels,
                }
            )

            if is_satisfied:
                bucket["any_satisfied"] = True
            else:
                bucket["all_satisfied"] = False

            for label in matching_component_labels:
                if label not in bucket["component_labels"]:
                    bucket["component_labels"].append(label)

        for component in self.get_placed_components():
            component_labels = [component.get("label", component.get("instance_id", "component"))]

            raw_groups = component.get("operational_groups", [])
            raw_subsystems = component.get("subsystem_labels", [])

            if raw_groups:
                for index, group_name in enumerate(raw_groups):
                    group_name = str(group_name).strip() or "General Systems"
                    subsystem_name = None

                    if index < len(raw_subsystems):
                        subsystem_name = str(raw_subsystems[index]).strip() or None
                    if subsystem_name is None and raw_subsystems:
                        subsystem_name = str(raw_subsystems[0]).strip() or None
                    if subsystem_name is None:
                        subsystem_name = component.get("label", component.get("instance_id", "component"))

                    bucket = grouped.setdefault(
                        group_name,
                        {
                            "group": group_name,
                            "children": [],
                            "component_labels": [],
                            "all_satisfied": True,
                            "any_satisfied": False,
                        },
                    )

                    existing_child = None
                    for child in bucket["children"]:
                        if child.get("label") == subsystem_name:
                            existing_child = child
                            break

                    if existing_child is None:
                        bucket["children"].append(
                            {
                                "category": None,
                                "label": subsystem_name,
                                "source_class": "component_subsystem_labels",
                                "status": "active",
                                "matching_component_labels": list(component_labels),
                            }
                        )
                    else:
                        for label in component_labels:
                            if label not in existing_child["matching_component_labels"]:
                                existing_child["matching_component_labels"].append(label)
                        existing_child["status"] = "active"

                    for label in component_labels:
                        if label not in bucket["component_labels"]:
                            bucket["component_labels"].append(label)

                    bucket["any_satisfied"] = True

        summary = []
        for group_name, bucket in grouped.items():
            if bucket["all_satisfied"]:
                status = "active"
            elif bucket["any_satisfied"]:
                status = "incomplete"
            else:
                status = "missing"

            summary.append(
                {
                    "group": group_name,
                    "status": status,
                    "children": bucket["children"],
                    "component_labels": bucket["component_labels"],
                }
            )

        desired_order = {
            "Structure": 0,
            "Crew & Control": 1,
            "Powertrain": 2,
            "Mobility": 3,
            "Cargo": 4,
            "Sensors & Comms": 5,
            "Weapons": 6,
            "Control Surfaces": 7,
            "General Systems": 8,
        }

        summary.sort(key=lambda item: (desired_order.get(item["group"], 99), item["group"]))
        return summary

    def get_world_base_rect(self, vehicle_position):
        dims = self.get_vehicle_dimensions_m()
        return {
            "x": vehicle_position.get("x", 0.0) - dims["x"] / 2.0,
            "y": vehicle_position.get("y", 0.0) - dims["y"] / 2.0,
            "width": dims["x"],
            "height": dims["y"],
        }

    def _clamp_local_rect_to_hull(self, local_rect):
        dims = self.get_vehicle_dimensions_m()

        width = max(0.1, min(local_rect.get("width", 1.0), dims["x"]))
        height = max(0.1, min(local_rect.get("height", 1.0), dims["y"]))

        max_x = max(0.0, dims["x"] - width)
        max_y = max(0.0, dims["y"] - height)

        x = min(max(0.0, local_rect.get("x", 0.0)), max_x)
        y = min(max(0.0, local_rect.get("y", 0.0)), max_y)

        return {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

    def _world_to_local_xy(self, vehicle_position, world_x, world_y):
        base_rect = self.get_world_base_rect(vehicle_position)
        return world_x - base_rect["x"], world_y - base_rect["y"]

    def _hull_contains_world_position(self, vehicle_position, world_x, world_y):
        base_rect = self.get_world_base_rect(vehicle_position)
        return (
            base_rect["x"] <= world_x <= base_rect["x"] + base_rect["width"]
            and base_rect["y"] <= world_y <= base_rect["y"] + base_rect["height"]
        )

    def get_world_design_blocks(self, vehicle_position):
        base_rect = self.get_world_base_rect(vehicle_position)
        world_blocks = []

        for component in self.placed_components:
            local_rect = component.get("local_rect_m", {})
            world_blocks.append(
                {
                    "id": component.get("instance_id"),
                    "label": component.get("label", component.get("instance_id", "component")),
                    "component_type": component.get("component_type", "component"),
                    "catalog_id": component.get("catalog_id"),
                    "entry_type": component.get("entry_type", "component"),
                    "satisfies_categories": list(component.get("satisfies_categories", [])),
                    "operational_groups": list(component.get("operational_groups", [])),
                    "subsystem_labels": list(component.get("subsystem_labels", [])),
                    "x": base_rect["x"] + local_rect.get("x", 0.0),
                    "y": base_rect["y"] + local_rect.get("y", 0.0),
                    "width": local_rect.get("width", 1.0),
                    "height": local_rect.get("height", 1.0),
                }
            )

        return world_blocks

    def get_drag_preview_block(self, vehicle_position):
        if not self.dragging_catalog_component_id or not self.drag_preview_local_rect_m:
            return None

        catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
        if catalog_entry is None:
            return None

        base_rect = self.get_world_base_rect(vehicle_position)
        local_rect = self.drag_preview_local_rect_m

        return {
            "id": "__drag_preview__",
            "label": catalog_entry.get("label", "component"),
            "component_type": catalog_entry.get("component_type", "component"),
            "catalog_id": catalog_entry.get("id"),
            "entry_type": catalog_entry.get("entry_type", "component"),
            "satisfies_categories": list(catalog_entry.get("satisfies_categories", [])),
            "operational_groups": list(catalog_entry.get("operational_groups", [])),
            "subsystem_labels": list(catalog_entry.get("subsystem_labels", [])),
            "x": base_rect["x"] + local_rect.get("x", 0.0),
            "y": base_rect["y"] + local_rect.get("y", 0.0),
            "width": local_rect.get("width", 1.0),
            "height": local_rect.get("height", 1.0),
        }

    def get_design_payload(self, vehicle_position):
        return {
            "base_rect": self.get_world_base_rect(vehicle_position),
            "blocks": self.get_world_design_blocks(vehicle_position),
            "drag_preview_block": self.get_drag_preview_block(vehicle_position),
            "component_catalog": self.get_component_catalog(),
            "grouped_component_catalog": self.get_grouped_component_catalog(),
            "catalog_panel_rect": self.get_catalog_panel_rect(),
            "catalog_entry_rects": self.get_catalog_entry_rects(),
            "selected_component_id": self.selected_component_id,
            "hover_component_id": self.hover_component_id,
            "active_catalog_component_id": self.active_catalog_component_id,
            "hover_catalog_component_id": self.hover_catalog_component_id,
            "dragging_component_id": self.dragging_component_id,
            "dragging_catalog_component_id": self.dragging_catalog_component_id,
            "requirement_status": self.get_requirement_status_list(),
        }

    def component_at_world_position(self, vehicle_position, world_x, world_y):
        for block in reversed(self.get_world_design_blocks(vehicle_position)):
            block_min_x = block["x"]
            block_max_x = block["x"] + block["width"]
            block_min_y = block["y"]
            block_max_y = block["y"] + block["height"]

            if block_min_x <= world_x <= block_max_x and block_min_y <= world_y <= block_max_y:
                return block

        return None

    def set_hover_component(self, component_id):
        self.hover_component_id = component_id

    def set_selected_component(self, component_id):
        self.selected_component_id = component_id

    def set_active_catalog_component(self, catalog_id):
        self.active_catalog_component_id = catalog_id

    def set_hover_catalog_component(self, catalog_id):
        self.hover_catalog_component_id = catalog_id

    def _make_component_instance(self, catalog_entry, local_rect):
        instance_id = f"placed_component_{self.next_component_index:03d}"
        self.next_component_index += 1

        return {
            "instance_id": instance_id,
            "catalog_id": catalog_entry["id"],
            "label": catalog_entry["label"],
            "component_type": catalog_entry["component_type"],
            "entry_type": catalog_entry.get("entry_type", "component"),
            "satisfies_categories": list(catalog_entry.get("satisfies_categories", [])),
            "operational_groups": list(catalog_entry.get("operational_groups", [])),
            "subsystem_labels": list(catalog_entry.get("subsystem_labels", [])),
            "local_rect_m": self._clamp_local_rect_to_hull(local_rect),
        }

    def _get_component_by_instance_id(self, instance_id):
        for component in self.placed_components:
            if component.get("instance_id") == instance_id:
                return component
        return None

    def _build_local_rect_from_pointer(self, width, height, local_x, local_y, pointer_offset):
        offset_x = 0.0
        offset_y = 0.0
        if pointer_offset:
            offset_x = pointer_offset.get("x", 0.0)
            offset_y = pointer_offset.get("y", 0.0)

        return self._clamp_local_rect_to_hull(
            {
                "x": local_x - offset_x,
                "y": local_y - offset_y,
                "width": width,
                "height": height,
            }
        )

    def begin_catalog_drag(self, catalog_id):
        catalog_entry = self.get_component_catalog_entry(catalog_id)
        if catalog_entry is None:
            return False

        dims = catalog_entry.get("dimensions_m", {})
        self.dragging_catalog_component_id = catalog_id
        self.dragging_component_id = None
        self.drag_pointer_offset_local_m = {
            "x": dims.get("x", 1.0) / 2.0,
            "y": dims.get("y", 1.0) / 2.0,
        }
        self.drag_preview_local_rect_m = None
        self.active_catalog_component_id = catalog_id
        return True

    def begin_component_drag(self, vehicle_position, component_id, world_x, world_y):
        component = self._get_component_by_instance_id(component_id)
        if component is None:
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        rect = component.get("local_rect_m", {})

        self.dragging_component_id = component_id
        self.dragging_catalog_component_id = None
        self.drag_preview_local_rect_m = None
        self.drag_pointer_offset_local_m = {
            "x": local_x - rect.get("x", 0.0),
            "y": local_y - rect.get("y", 0.0),
        }
        self.selected_component_id = component_id
        return True

    def update_drag(self, vehicle_position, world_x, world_y):
        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            if self.dragging_catalog_component_id:
                self.drag_preview_local_rect_m = None
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)

        if self.dragging_component_id:
            component = self._get_component_by_instance_id(self.dragging_component_id)
            if component is None:
                return False

            rect = component.get("local_rect_m", {})
            component["local_rect_m"] = self._build_local_rect_from_pointer(
                rect.get("width", 1.0),
                rect.get("height", 1.0),
                local_x,
                local_y,
                self.drag_pointer_offset_local_m,
            )
            return True

        if self.dragging_catalog_component_id:
            catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
            if catalog_entry is None:
                return False

            dims = catalog_entry.get("dimensions_m", {})
            self.drag_preview_local_rect_m = self._build_local_rect_from_pointer(
                dims.get("x", 1.0),
                dims.get("y", 1.0),
                local_x,
                local_y,
                self.drag_pointer_offset_local_m,
            )
            return True

        return False

    def end_drag(self, vehicle_position, world_x, world_y):
        created_id = None

        if self.dragging_catalog_component_id and self.drag_preview_local_rect_m:
            catalog_entry = self.get_component_catalog_entry(self.dragging_catalog_component_id)
            if catalog_entry is not None and self._hull_contains_world_position(vehicle_position, world_x, world_y):
                new_component = self._make_component_instance(catalog_entry, self.drag_preview_local_rect_m)
                self.placed_components.append(new_component)
                self.selected_component_id = new_component["instance_id"]
                created_id = new_component["instance_id"]

        ended_component_id = self.dragging_component_id

        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

        if created_id:
            return created_id

        if ended_component_id:
            return ended_component_id

        return None

    def cancel_drag(self):
        self.dragging_component_id = None
        self.dragging_catalog_component_id = None
        self.drag_pointer_offset_local_m = None
        self.drag_preview_local_rect_m = None

    def place_active_catalog_component_at_world_position(self, vehicle_position, world_x, world_y):
        if not self.active_catalog_component_id:
            return None

        catalog_entry = self.get_component_catalog_entry(self.active_catalog_component_id)
        if not catalog_entry:
            return None

        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            return None

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        dims = catalog_entry.get("dimensions_m", {})

        local_rect = {
            "x": local_x - dims.get("x", 1.0) / 2.0,
            "y": local_y - dims.get("y", 1.0) / 2.0,
            "width": dims.get("x", 1.0),
            "height": dims.get("y", 1.0),
        }

        new_component = self._make_component_instance(catalog_entry, local_rect)
        self.placed_components.append(new_component)
        self.selected_component_id = new_component["instance_id"]
        return new_component["instance_id"]

    def move_selected_component_to_world_position(self, vehicle_position, world_x, world_y):
        if not self.selected_component_id:
            return False

        if not self._hull_contains_world_position(vehicle_position, world_x, world_y):
            return False

        target_component = self._get_component_by_instance_id(self.selected_component_id)
        if target_component is None:
            return False

        local_x, local_y = self._world_to_local_xy(vehicle_position, world_x, world_y)
        current_rect = target_component.get("local_rect_m", {})

        new_local_rect = {
            "x": local_x - current_rect.get("width", 1.0) / 2.0,
            "y": local_y - current_rect.get("height", 1.0) / 2.0,
            "width": current_rect.get("width", 1.0),
            "height": current_rect.get("height", 1.0),
        }
        target_component["local_rect_m"] = self._clamp_local_rect_to_hull(new_local_rect)
        return True