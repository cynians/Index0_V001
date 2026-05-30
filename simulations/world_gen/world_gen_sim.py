import math


class WorldGenSimulation:
    """
    Empty-start planetary world-generation workspace.

    This first pass captures orbital inputs and exposes a preview model for a
    parent-system render. Later stages can add climate, tectonics,
    precipitation, and weather products to planetary_model.
    """

    AU_M = 149_597_870_700.0
    SOLAR_MASS_KG = 1.98847e30

    INPUT_FIELDS = [
        ("periapsis_au", "Periapsis from Star (AU)"),
        ("apoapsis_au", "Apoapsis from Star (AU)"),
    ]

    def __init__(self, world_model=None, planet_location_id=None, year=2400):
        from engine.clock import Clock

        self.render_mode = "world_gen"
        self.year = year
        if world_model is None:
            from world.world_model import WorldModel

            world_model = WorldModel()
        self.world_model = world_model
        self.planet_location_id = planet_location_id
        self.planet_entity = self.world_model.get_entity(planet_location_id) if planet_location_id else None

        self.sim_clock = Clock(base_dt=1.0)
        self.preferred_zoom = 2.2e-9
        self.min_zoom = 2.0e-11
        self.max_zoom = 1.0e-7

        self.active_input_field = "periapsis_au"
        self.input_buffers = {
            "periapsis_au": "",
            "apoapsis_au": "",
        }
        self.input_field_rects = {}

        self.parent_system_id = self._resolve_parent_system_id()
        self.star_entity = self._resolve_primary_star()
        self.star_luminosity_solar = self._estimate_star_luminosity_solar(self.star_entity)
        self.planetary_model = {}
        self._recalculate_model()

    def get_center(self):
        return 0.0, 0.0

    def get_scope_label(self):
        if self.planet_entity:
            return self.planet_entity.get("name") or self.planet_location_id
        return "New Planet"

    def get_scope_breadcrumb(self):
        system = self.world_model.get_entity(self.parent_system_id) if self.parent_system_id else None
        system_name = system.get("name", self.parent_system_id) if system else "No parent system"
        star_name = self.star_entity.get("name", "Unknown star") if self.star_entity else "Unknown star"
        return f"{system_name} | primary: {star_name}"

    def update(self, dt):
        self.sim_clock.update(dt)

    def set_input_field_rects(self, rects):
        self.input_field_rects = dict(rects or {})

    def _resolve_entity_id(self, entity_id):
        loader = getattr(self.world_model, "loader", None)
        aliases = getattr(loader, "entity_aliases", {}) if loader is not None else {}
        return aliases.get(entity_id, entity_id)

    def _resolve_parent_system_id(self):
        entity = self.planet_entity or {}

        source_body_id = entity.get("derived_from_system_body")
        if source_body_id:
            source = self.world_model.get_entity(source_body_id)
            if source and source.get("star_system"):
                return self._resolve_entity_id(source.get("star_system"))

        if entity.get("star_system"):
            return self._resolve_entity_id(entity.get("star_system"))

        parent_id = entity.get("parent_location")
        while parent_id:
            parent = self.world_model.get_entity(parent_id)
            if not parent:
                break
            if parent.get("location_class") == "star_system" or parent.get("system_role") == "star_system":
                return self._resolve_entity_id(parent.get("id"))
            if parent.get("star_system"):
                return self._resolve_entity_id(parent.get("star_system"))
            parent_id = parent.get("parent_location")

        related = entity.get("related")
        if isinstance(related, list):
            for related_id in related:
                related_entity = self.world_model.get_entity(related_id)
                if related_entity and (
                    related_entity.get("location_class") == "star_system"
                    or related_entity.get("system_role") == "star_system"
                ):
                    return self._resolve_entity_id(related_entity.get("id"))

        return None

    def _active_system_bodies(self):
        if not self.parent_system_id:
            return []

        bodies = []
        for entity in self.world_model.get_active_entities(
            self.year,
            dataset_name="locations",
            entity_type="location",
        ):
            if entity.get("system_role") != "orbital_body":
                continue
            if self._resolve_entity_id(entity.get("star_system")) != self.parent_system_id:
                continue
            bodies.append(entity)
        return bodies

    def _resolve_primary_star(self):
        for entity in self._active_system_bodies():
            if entity.get("body_class") == "star":
                return entity
        return None

    def _estimate_star_luminosity_solar(self, star_entity):
        if not isinstance(star_entity, dict):
            return 1.0

        for key in ("luminosity_solar", "luminosity_l_sun"):
            value = self._parse_float(star_entity.get(key))
            if value is not None and value > 0:
                return value

        luminosity_w = self._parse_float(star_entity.get("luminosity_w"))
        if luminosity_w is not None and luminosity_w > 0:
            return luminosity_w / 3.828e26

        mass_kg = self._parse_float(star_entity.get("mass_kg"))
        if mass_kg is not None and mass_kg > 0:
            mass_solar = mass_kg / self.SOLAR_MASS_KG
            return max(0.01, mass_solar ** 3.5)

        return 1.0

    def _parse_float(self, value):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_float(self, value, digits=3):
        if value is None:
            return "n/a"
        return f"{value:.{digits}f}"

    def _input_value(self, field_id):
        return self._parse_float(self.input_buffers.get(field_id))

    def _recalculate_model(self):
        periapsis_au = self._input_value("periapsis_au")
        apoapsis_au = self._input_value("apoapsis_au")
        semi_major_au = None
        eccentricity = None
        orbit_valid = False

        if (
            periapsis_au is not None
            and apoapsis_au is not None
            and periapsis_au > 0
            and apoapsis_au > 0
            and apoapsis_au >= periapsis_au
        ):
            semi_major_au = (periapsis_au + apoapsis_au) / 2.0
            eccentricity = (apoapsis_au - periapsis_au) / (apoapsis_au + periapsis_au)
            orbit_valid = True

        luminosity = max(0.01, self.star_luminosity_solar or 1.0)
        habitable_inner_au = math.sqrt(luminosity / 1.1)
        habitable_outer_au = math.sqrt(luminosity / 0.53)

        self.planetary_model = {
            "planet_location_id": self.planet_location_id,
            "parent_system_id": self.parent_system_id,
            "primary_star_id": self.star_entity.get("id") if self.star_entity else None,
            "periapsis_au": periapsis_au,
            "apoapsis_au": apoapsis_au,
            "semi_major_axis_au": semi_major_au,
            "eccentricity": eccentricity,
            "orbit_valid": orbit_valid,
            "habitable_zone_inner_au": habitable_inner_au,
            "habitable_zone_outer_au": habitable_outer_au,
            "climate_patterns": None,
            "plate_tectonics": None,
            "weather": None,
            "precipitation": None,
        }
        return self.planetary_model

    def get_preview_payload(self):
        model = self._recalculate_model()
        return {
            "model": model,
            "fields": [
                {
                    "id": field_id,
                    "label": label,
                    "text": self.input_buffers.get(field_id, ""),
                    "active": field_id == self.active_input_field,
                }
                for field_id, label in self.INPUT_FIELDS
            ],
            "system_bodies": self._active_system_bodies(),
            "star": self.star_entity,
            "scope_label": self.get_scope_label(),
            "breadcrumb": self.get_scope_breadcrumb(),
            "summary_lines": self._summary_lines(model),
        }

    def _summary_lines(self, model):
        return [
            f"Semi-major axis: {self._format_float(model.get('semi_major_axis_au'))} AU",
            f"Eccentricity: {self._format_float(model.get('eccentricity'), digits=4)}",
            (
                "Goldilocks zone: "
                f"{self._format_float(model.get('habitable_zone_inner_au'))}-"
                f"{self._format_float(model.get('habitable_zone_outer_au'))} AU"
            ),
        ]

    def _cycle_input_field(self, direction=1):
        field_ids = [field_id for field_id, _label in self.INPUT_FIELDS]
        if self.active_input_field not in field_ids:
            self.active_input_field = field_ids[0]
            return
        index = field_ids.index(self.active_input_field)
        self.active_input_field = field_ids[(index + direction) % len(field_ids)]

    def handle_event(self, event):
        import pygame

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self._cycle_input_field(-1 if event.mod & pygame.KMOD_SHIFT else 1)
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._cycle_input_field(1)
                return
            if event.key == pygame.K_BACKSPACE:
                buffer_text = self.input_buffers.get(self.active_input_field, "")
                self.input_buffers[self.active_input_field] = buffer_text[:-1]
                self._recalculate_model()
                return
            if event.key == pygame.K_DELETE:
                self.input_buffers[self.active_input_field] = ""
                self._recalculate_model()
                return

            text = getattr(event, "unicode", "")
            if text and text in "0123456789.-":
                buffer_text = self.input_buffers.get(self.active_input_field, "")
                self.input_buffers[self.active_input_field] = buffer_text + text
                self._recalculate_model()
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos
            for field_id, rect in self.input_field_rects.items():
                if rect.collidepoint(mouse_pos):
                    self.active_input_field = field_id
                    return
