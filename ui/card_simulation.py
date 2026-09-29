class CardSimulationMixin:
    def _is_component_card(self):
        return self.dataset_name == "components" or self.entity.get("type") in {"component", "assembly"}

    def _has_simulation_fields(self):
        if self._is_person_card():
            return True
        keys = set(self.entity.keys()) | set(self._get_schema_field_specs().keys())
        simulation_keys = (
            self.SPACE_SIM_FIELDS
            | self.MAP_SIM_FIELDS
            | self.WORLD_GEN_SIM_FIELDS
            | self.MATERIAL_SIM_FIELDS
            | self.PLANT_ECOLOGY_SIM_FIELDS
        )
        return bool(keys & simulation_keys)

    def _active_subtab_order(self):
        if self.active_tab == "simulation":
            if self._is_person_card():
                return self.PERSON_SIMULATION_SUBTAB_ORDER
            return self.SIMULATION_SUBTAB_ORDER
        return []

    def _default_simulation_subtab(self):
        if self._is_person_card():
            return "quotes"
        keys = set(self.entity.keys())
        if keys & (self.SPACE_SIM_FIELDS | {"mass_kg"}) and self._is_space_sim_context():
            return "orbital"
        if keys & self.MAP_SIM_FIELDS:
            return "map"
        if keys & self.WORLD_GEN_SIM_FIELDS:
            return "world_gen"
        if keys & self.MATERIAL_SIM_FIELDS:
            return "materials"
        if keys & self.PLANT_ECOLOGY_SIM_FIELDS:
            return "plant_ecology"
        return self.active_simulation_subtab if self.active_simulation_subtab in self.SIMULATION_SUBTAB_ORDER else "orbital"

    def _visible_sections(self):
        if self.active_tab == "simulation":
            if self._is_person_card() and self.active_simulation_subtab == "quotes":
                return []
            if self._is_person_card() and self.active_simulation_subtab == "data":
                return self.SIMULATION_SUBTAB_SECTIONS["data"]
            return self.SIMULATION_SUBTAB_SECTIONS.get(
                self.active_simulation_subtab,
                self.SIMULATION_SUBTAB_SECTIONS["orbital"],
            )
        return self.TAB_SECTIONS.get(self.active_tab, self.TAB_SECTIONS["general"])

    def _is_space_sim_context(self):
        return bool(
            self.entity.get("system_role")
            or self.entity.get("body_class")
            or self.entity.get("star_system")
            or self.entity.get("parent_body")
            or self.entity.get("derived_from_system_body")
            or self.entity.get("location_class") in {"star_system", "star", "planet", "moon"}
            or self.dataset_name == "systems"
        )

    def _is_location_field_relevant(self, field_key):
        if not self._is_location_card():
            return True

        class_key = str(
            self.entity.get("location_class")
            or self.entity.get("body_class")
            or ""
        ).strip().lower().replace(" ", "_").replace("-", "_")
        surface_classes = {
            "continent",
            "country",
            "state",
            "region",
            "city",
            "quarter",
            "site",
            "macro_site",
            "internal_passage",
            "island_chain",
            "atoll",
            "cluster",
        }
        orbital_classes = {
            "star_system",
            "stellar_system",
            "star",
            "planet",
            "moon",
            "dwarf_planet",
            "asteroid",
            "comet",
            "orbital_body",
        }
        building_only = {"building_class"}
        room_only = {"room_class", "floor_index", "floor_label", "room_number"}
        orbital_only = self.SPACE_SIM_FIELDS | {"mass_kg"}

        if class_key in surface_classes:
            return field_key not in (building_only | room_only | orbital_only)
        if class_key == "building":
            return field_key not in (room_only | orbital_only)
        if class_key == "room":
            return field_key not in orbital_only
        if class_key in orbital_classes:
            return field_key not in (building_only | room_only)
        return field_key not in (building_only | room_only)

    def _simulation_section_for_key(self, key):
        if key in self.SPACE_SIM_FIELDS:
            return "Simulation / Orbital"
        if key == "mass_kg" and self._is_space_sim_context():
            return "Simulation / Orbital"
        if key in self.MAP_SIM_FIELDS:
            return "Simulation / Map Sim"
        if key in self.MATERIAL_SIM_FIELDS:
            return "Simulation / Materials"
        if key in self.WORLD_GEN_SIM_FIELDS:
            return "Simulation / World Gen"
        if key in self.PLANT_ECOLOGY_SIM_FIELDS:
            return "Simulation / Plant Ecology"
        return None
