import re
from pathlib import Path

import yaml

from simulations.space.stellar import habitable_zone_for_luminosity


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

    def __init__(self, world_model=None, planet_location_id=None, parent_system_id=None, year=2400):
        from engine.clock import Clock

        self.render_mode = "world_gen"
        self.year = year
        if world_model is None:
            from world.world_model import WorldModel

            world_model = WorldModel()
        self.world_model = world_model
        self.planet_location_id = planet_location_id
        self.planet_entity = self.world_model.get_entity(planet_location_id) if planet_location_id else None
        self.explicit_parent_system_id = parent_system_id

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
        self.control_panel_rect = None
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self.planet_name_prompt_active = False
        self.planet_name_buffer = ""
        self.commit_status = ""

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
        system = self.world_model.get_entity(self.parent_system_id) if self.parent_system_id else None
        if system:
            return f"{system.get('name', self.parent_system_id)} Planet"
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

    def set_control_panel_rect(self, rect):
        self.control_panel_rect = rect

    def _resolve_entity_id(self, entity_id):
        loader = getattr(self.world_model, "loader", None)
        aliases = getattr(loader, "entity_aliases", {}) if loader is not None else {}
        return aliases.get(entity_id, entity_id)

    def _normalize_year(self, value):
        if value in (None, "", "null"):
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except ValueError:
                return None
        return None

    def _orbital_entity_is_active(self, entity):
        start = self._normalize_year(entity.get("start_year"))
        end = self._normalize_year(entity.get("end_year"))
        if start is not None and self.year < start:
            return False
        if end is not None and self.year > end:
            return False
        return True

    def _resolve_parent_system_id(self):
        if self.explicit_parent_system_id:
            return self._resolve_entity_id(self.explicit_parent_system_id)

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
        orbital_location_classes = {
            "star",
            "planet",
            "moon",
            "dwarf_planet",
            "asteroid",
            "comet",
            "space_station",
            "station",
            "orbital_body",
            "spacecraft",
            "orbital_spacecraft",
            "planetary_spacecraft",
            "system_spacecraft",
            "interstellar_spacecraft",
        }
        if hasattr(self.world_model, "get_entities_by_dataset"):
            candidate_entities = [
                entity for entity in self.world_model.get_entities_by_dataset("locations")
                if self._orbital_entity_is_active(entity)
            ]
        else:
            candidate_entities = self.world_model.get_active_entities(
                self.year,
                dataset_name="locations",
                entity_type="location",
            )

        for entity in candidate_entities:
            class_key = str(entity.get("location_class") or "").strip().lower()
            is_orbital_body = (
                entity.get("system_role") == "orbital_body"
                or (class_key in orbital_location_classes and bool(entity.get("star_system")))
            )
            if not is_orbital_body:
                continue
            if self._resolve_entity_id(entity.get("star_system")) != self.parent_system_id:
                continue
            bodies.append(entity)
        return bodies

    def _resolve_primary_star(self):
        for entity in self._active_system_bodies():
            if entity.get("body_class") == "star" or entity.get("location_class") == "star":
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

    def _format_input_au(self, value):
        text = f"{max(0.0, float(value)):.4f}".rstrip("0").rstrip(".")
        return text or "0"

    def _input_value(self, field_id):
        return self._parse_float(self.input_buffers.get(field_id))

    def _set_orbit_distances(self, periapsis_au, apoapsis_au):
        self.input_buffers["periapsis_au"] = self._format_input_au(periapsis_au)
        self.input_buffers["apoapsis_au"] = self._format_input_au(apoapsis_au)
        self.commit_status = ""
        self._recalculate_model()

    def _set_circular_orbit_from_radius(self, radius_au):
        self.pending_orbit_radius_au = radius_au
        self.orbit_pick_stage = "second"
        self._set_orbit_distances(radius_au, radius_au)

    def _set_elliptical_orbit_from_radius(self, radius_au):
        first_radius_au = self.pending_orbit_radius_au
        if first_radius_au is None:
            self._set_circular_orbit_from_radius(radius_au)
            return

        periapsis_au = min(first_radius_au, radius_au)
        apoapsis_au = max(first_radius_au, radius_au)
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self._set_orbit_distances(periapsis_au, apoapsis_au)

    def _distance_au_from_world_point(self, world_point):
        try:
            wx, wy = world_point
            radius_m = (float(wx) ** 2 + float(wy) ** 2) ** 0.5
        except (TypeError, ValueError):
            return None
        radius_au = radius_m / self.AU_M
        return radius_au if radius_au > 0 else None

    def _slug_from_text(self, text):
        slug = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
        return slug or "planet"

    def _unique_entity_id(self, base_id):
        loader = getattr(self.world_model, "loader", None)
        entities = getattr(loader, "entities", {}) if loader is not None else {}
        if base_id not in entities:
            return base_id

        index = 2
        while f"{base_id}_{index:02d}" in entities:
            index += 1
        return f"{base_id}_{index:02d}"

    def _primary_star_id(self):
        if isinstance(self.star_entity, dict) and self.star_entity.get("id"):
            return self.star_entity.get("id")
        return None

    def _locations_entry_path(self):
        loader = getattr(self.world_model, "loader", None)
        entries_directory = getattr(loader, "entries_directory", None)
        if entries_directory is not None:
            return Path(entries_directory) / "locations.yaml"
        return Path(__file__).resolve().parents[2] / "entries" / "locations.yaml"

    def _persist_location_entity(self, entity):
        entry_path = self._locations_entry_path()
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        block = yaml.safe_dump([self._serializable_entity(entity)], sort_keys=False, allow_unicode=True).rstrip() + "\n"
        try:
            text = entry_path.read_text(encoding="utf-8") if entry_path.exists() else ""
            separator = "" if not text.strip() or text.rstrip().endswith("\n\n") else "\n"
            entry_path.write_text(text.rstrip() + separator + block, encoding="utf-8")
        except OSError:
            return False
        return True

    def _serializable_entity(self, entity):
        return {
            key: value
            for key, value in entity.items()
            if not str(key).startswith("_")
        }

    def _register_location_entity(self, entity):
        loader = getattr(self.world_model, "loader", None)
        if loader is None:
            return
        loader.datasets.setdefault("locations", []).append(entity)
        loader.entities[entity["id"]] = entity
        if hasattr(loader, "build_reference_graph"):
            loader.build_reference_graph()
        graph = getattr(self.world_model, "touch_degrees", None)
        if graph is not None and hasattr(graph, "refresh"):
            graph.refresh()

    def _build_committed_planet_entity(self, name):
        model = self._recalculate_model()
        if not model.get("orbit_valid"):
            return None

        planet_name = str(name or "").strip()
        if not planet_name:
            return None

        semi_major_au = model.get("semi_major_axis_au")
        eccentricity = model.get("eccentricity")
        periapsis_au = model.get("periapsis_au")
        apoapsis_au = model.get("apoapsis_au")
        parent_star_id = self._primary_star_id()
        base_id = f"planet_{self._slug_from_text(planet_name)}"
        entity_id = self._unique_entity_id(base_id)

        return {
            "id": entity_id,
            "pretty_name": planet_name,
            "name": planet_name,
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "location_role": "orbital_body",
            "star_system": self.parent_system_id,
            "parent_location": self.parent_system_id,
            "parent_body": parent_star_id,
            "semi_major_axis_m": semi_major_au * self.AU_M,
            "eccentricity": eccentricity,
            "periapsis_au": periapsis_au,
            "apoapsis_au": apoapsis_au,
            "mean_anomaly_deg_at_epoch": 0.0,
            "display_color": [92, 148, 206],
            "tags": ["world_gen_candidate"],
            "wiki_mentions": [],
            "offspring": [],
        }

    def _open_planet_name_prompt(self):
        self.planet_name_prompt_active = True
        self.planet_name_buffer = ""
        self.commit_status = "Name the new planet"

    def _cancel_planet_name_prompt(self):
        self.planet_name_prompt_active = False
        self.planet_name_buffer = ""
        self.commit_status = ""

    def _commit_named_planet(self):
        planet = self._build_committed_planet_entity(self.planet_name_buffer)
        if planet is None:
            self.commit_status = "Enter a planet name"
            return False

        self._register_location_entity(planet)
        persisted = self._persist_location_entity(planet)
        self.planet_location_id = planet["id"]
        self.planet_entity = planet
        self.planet_name_prompt_active = False
        self.planet_name_buffer = ""
        self.commit_status = f"Created planet: {planet['name']}" if persisted else "Created in memory; save failed"
        return True

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

        habitable_zone = habitable_zone_for_luminosity(self.star_luminosity_solar)
        habitable_inner_au = habitable_zone["habitable_zone_inner_au"]
        habitable_outer_au = habitable_zone["habitable_zone_outer_au"]

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
            "orbit_pick_stage": self.orbit_pick_stage,
            "pending_orbit_radius_au": self.pending_orbit_radius_au,
            "planet_name_prompt_active": self.planet_name_prompt_active,
            "planet_name_buffer": self.planet_name_buffer,
            "commit_status": self.commit_status,
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
            if self.planet_name_prompt_active:
                if event.key == pygame.K_ESCAPE:
                    self._cancel_planet_name_prompt()
                    return
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._commit_named_planet()
                    return
                if event.key == pygame.K_BACKSPACE:
                    self.planet_name_buffer = self.planet_name_buffer[:-1]
                    return
                text = getattr(event, "unicode", "")
                if text and text.isprintable():
                    self.planet_name_buffer += text
                    return
                return

            if event.key == pygame.K_TAB:
                self._cycle_input_field(-1 if event.mod & pygame.KMOD_SHIFT else 1)
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.planetary_model.get("orbit_valid"):
                    self._open_planet_name_prompt()
                else:
                    self.commit_status = "Set an orbit before naming a planet"
                return
            if event.key == pygame.K_BACKSPACE:
                buffer_text = self.input_buffers.get(self.active_input_field, "")
                self.input_buffers[self.active_input_field] = buffer_text[:-1]
                self.pending_orbit_radius_au = None
                self.orbit_pick_stage = "first"
                self._recalculate_model()
                return
            if event.key == pygame.K_DELETE:
                self.input_buffers[self.active_input_field] = ""
                self.pending_orbit_radius_au = None
                self.orbit_pick_stage = "first"
                self._recalculate_model()
                return

            text = getattr(event, "unicode", "")
            if text and text in "0123456789.-":
                buffer_text = self.input_buffers.get(self.active_input_field, "")
                self.input_buffers[self.active_input_field] = buffer_text + text
                self.pending_orbit_radius_au = None
                self.orbit_pick_stage = "first"
                self._recalculate_model()
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos
            for field_id, rect in self.input_field_rects.items():
                if rect.collidepoint(mouse_pos):
                    self.active_input_field = field_id
                    return

    def handle_pointer_event(self, event, camera, screen_pos):
        import pygame

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        if self.control_panel_rect is not None and self.control_panel_rect.collidepoint(screen_pos):
            return

        radius_au = self._distance_au_from_world_point(camera.screen_to_world(screen_pos))
        if radius_au is None:
            return

        if self.orbit_pick_stage == "second" and self.pending_orbit_radius_au is not None:
            self._set_elliptical_orbit_from_radius(radius_au)
            return

        self._set_circular_orbit_from_radius(radius_au)
