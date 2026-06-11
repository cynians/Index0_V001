import re
from pathlib import Path

import yaml

from simulations.space.stellar import habitable_zone_for_luminosity
from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.crust import (
    MAJOR_CRUST_TARGET_PERCENT,
    PERIODIC_TABLE_ROWS,
    TRACE_RESERVE_PERCENT,
    add_abundant_trace_element,
    classify_crust_type,
    crust_composition_from_seed,
    default_crust_composition,
    estimate_crust_density_kg_m3,
    set_major_element_abundance,
)
from simulations.world_gen.heightmap import derive_heightmap_model
from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.planetary_physics import derive_planet_physics
from simulations.world_gen.terrain_seed import derive_terrain_seed_model
from simulations.world_gen.tectonics import (
    advance_tectonics_model,
    derive_crater_model,
    derive_tectonic_model,
)
from world.year_utils import parse_year


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
    SEED_FIELDS = [
        ("radius_earth", "Radius (Earth)"),
        ("core_radius_fraction", "Core Radius Fraction"),
        ("crust_thickness_km", "Crust Thickness (km)"),
        ("angular_velocity_deg_per_hour", "Spin Rate (deg/h)"),
        ("water_fraction", "Surface Water"),
        ("volatile_inventory", "Volatiles"),
        ("tectonics_mode", "Tectonics"),
    ]
    DEFAULT_SEED = {
        "radius_earth": 1.0,
        "core_radius_fraction": 0.55,
        "crust_thickness_km": 35.0,
        "angular_velocity_deg_per_hour": 15.0,
        "water_fraction": 0.5,
        "volatile_inventory": "earthlike",
        "tectonics_mode": "unknown",
    }
    VISIBLE_PHYSICAL_FIELD_IDS = {
        "radius_earth",
        "core_radius_fraction",
        "crust_thickness_km",
        "angular_velocity_deg_per_hour",
        "water_fraction",
    }

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
        self.seed_field_rects = {}
        self.crust_slider_rects = {}
        self.crust_add_trace_button_rect = None
        self.crust_save_button_rect = None
        self.periodic_table_rect = None
        self.periodic_element_rects = {}
        self.control_panel_rect = None
        self.heightmap_preview_rect = None
        self.heightmap_preview_zoom = 1.0
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self.planet_name_prompt_active = False
        self.planet_name_buffer = ""
        self.commit_status = ""
        self.planet_hitboxes = []
        self.selected_world_gen_planet_id = planet_location_id
        self.active_seed_field = "radius_earth"
        self.seed_input_buffers = {
            field_id: self._format_seed_input(value)
            for field_id, value in self.DEFAULT_SEED.items()
        }
        self.crust_composition = default_crust_composition()
        self.active_crust_slider_symbol = None
        self.periodic_table_open = False
        self.editor_stage = "crust"
        if isinstance(self.planet_entity, dict):
            self._load_seed_buffers_from_planet(self.planet_entity)

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

    def is_fullscreen_editor_active(self):
        return self._selected_planet_entity() is not None

    def consumes_global_escape(self):
        return self.is_fullscreen_editor_active()

    def update(self, dt):
        self.sim_clock.update(dt)

    def set_input_field_rects(self, rects):
        self.input_field_rects = dict(rects or {})

    def set_seed_field_rects(self, rects):
        self.seed_field_rects = dict(rects or {})

    def set_crust_ui_rects(self, slider_rects=None, add_trace_rect=None, save_rect=None, periodic_rect=None, element_rects=None):
        self.crust_slider_rects = dict(slider_rects or {})
        self.crust_add_trace_button_rect = add_trace_rect
        self.crust_save_button_rect = save_rect
        self.periodic_table_rect = periodic_rect
        self.periodic_element_rects = dict(element_rects or {})

    def set_control_panel_rect(self, rect):
        self.control_panel_rect = rect

    def set_heightmap_preview_rect(self, rect):
        self.heightmap_preview_rect = rect

    def set_planet_hitboxes(self, hitboxes):
        self.planet_hitboxes = list(hitboxes or [])

    def _screen_pos_from_event_or_mouse(self, event):
        pos = getattr(event, "pos", None)
        if pos is not None:
            return pos
        try:
            import pygame

            return pygame.mouse.get_pos()
        except Exception:
            return None

    def _zoom_heightmap_preview(self, wheel_y):
        if wheel_y == 0:
            return False
        factor = 1.18 ** float(wheel_y)
        self.heightmap_preview_zoom = max(1.0, min(12.0, self.heightmap_preview_zoom * factor))
        self.commit_status = f"Heightmap zoom x{self.heightmap_preview_zoom:.2f}"
        return True

    def handle_pre_camera_event(self, event):
        import pygame

        if event.type != pygame.MOUSEWHEEL:
            return False
        if self.editor_stage != "heightmap" or self._selected_planet_entity() is None:
            return False
        if self.heightmap_preview_rect is None:
            return False
        mouse_pos = self._screen_pos_from_event_or_mouse(event)
        if mouse_pos is None or not self.heightmap_preview_rect.collidepoint(mouse_pos):
            return False
        return self._zoom_heightmap_preview(getattr(event, "y", 0))

    def _resolve_entity_id(self, entity_id):
        loader = getattr(self.world_model, "loader", None)
        aliases = getattr(loader, "entity_aliases", {}) if loader is not None else {}
        return aliases.get(entity_id, entity_id)

    def _normalize_year(self, value):
        return parse_year(value)

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
        candidate_by_id = {}
        if hasattr(self.world_model, "get_entities_by_dataset"):
            for entity in self.world_model.get_entities_by_dataset("locations"):
                if self._orbital_entity_is_active(entity):
                    candidate_by_id[entity.get("id")] = entity
        else:
            for entity in self.world_model.get_active_entities(
                self.year,
                dataset_name="locations",
                entity_type="location",
            ):
                candidate_by_id[entity.get("id")] = entity

        loader = getattr(self.world_model, "loader", None)
        loader_locations = getattr(loader, "datasets", {}).get("locations", []) if loader is not None else []
        for entity in loader_locations:
            if self._orbital_entity_is_active(entity):
                candidate_by_id[entity.get("id")] = entity

        for entity in candidate_by_id.values():
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

    def _format_seed_input(self, value):
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value if value is not None else "")

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
            "parent_location": parent_star_id,
            "parent_body": parent_star_id,
            "semi_major_axis_m": semi_major_au * self.AU_M,
            "eccentricity": eccentricity,
            "periapsis_au": periapsis_au,
            "apoapsis_au": apoapsis_au,
            "mean_anomaly_deg_at_epoch": 0.0,
            "display_color": [92, 148, 206],
            "tags": ["world_gen_candidate", "orbit_locked"],
            "environment_summary": {
                "status": "orbit_locked",
                "summary": "Initial world-generation seed: orbital placement locked; physical planet model pending.",
            },
            "geology_summary": {
                "status": "pending",
                "start_condition": "Define radius, mass, rotation, volatile inventory, and plate tectonics mode.",
            },
            "offspring": [],
        }

    def _selected_planet_entity(self):
        if not self.selected_world_gen_planet_id or self.world_model is None:
            return None
        entity = self.world_model.get_entity(self.selected_world_gen_planet_id)
        if not isinstance(entity, dict):
            return None
        class_key = str(entity.get("location_class") or entity.get("body_class") or "").strip().lower()
        return entity if class_key == "planet" else None

    def _load_seed_buffers_from_planet(self, planet):
        seed = planet.get("world_gen_seed") if isinstance(planet.get("world_gen_seed"), dict) else {}
        if "angular_velocity_deg_per_hour" not in seed and seed.get("rotation_hours"):
            try:
                seed["angular_velocity_deg_per_hour"] = 360.0 / max(0.0001, float(seed.get("rotation_hours")))
            except (TypeError, ValueError):
                pass
        for field_id, default_value in self.DEFAULT_SEED.items():
            self.seed_input_buffers[field_id] = self._format_seed_input(seed.get(field_id, default_value))
        if self.active_seed_field not in self.seed_input_buffers:
            self.active_seed_field = "radius_earth"
        self.crust_composition = crust_composition_from_seed(seed)

    def _select_planet_for_worldgen(self, entity_id):
        self.selected_world_gen_planet_id = entity_id
        planet = self._selected_planet_entity()
        if planet is None:
            return False
        self._load_seed_buffers_from_planet(planet)
        self.editor_stage = "crust"
        name = planet.get("name", entity_id)
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self.commit_status = f"Selected {name}; define physical seed"
        return True

    def _coerce_seed_payload(self):
        seed = {}
        numeric_fields = {
            "radius_earth",
            "core_radius_fraction",
            "crust_thickness_km",
            "angular_velocity_deg_per_hour",
            "water_fraction",
        }
        for field_id, _label in self.SEED_FIELDS:
            text = str(self.seed_input_buffers.get(field_id, "")).strip()
            if field_id in numeric_fields:
                try:
                    value = float(text)
                except ValueError:
                    return None
                if field_id in {"radius_earth", "crust_thickness_km", "angular_velocity_deg_per_hour"} and value <= 0:
                    return None
                if field_id == "core_radius_fraction" and not 0.0 <= value <= 0.95:
                    return None
                if field_id == "water_fraction" and not 0.0 <= value <= 1.0:
                    return None
                seed[field_id] = value
            else:
                seed[field_id] = text or self.DEFAULT_SEED[field_id]
        seed["crust_composition"] = self._serializable_crust_composition()
        seed["derived_planet_physics"] = self._derive_planet_physics(seed)
        seed["mass_earth"] = seed["derived_planet_physics"]["mass_earth"]
        seed["rotation_hours"] = seed["derived_planet_physics"]["rotation_period_hours"]
        return seed

    def _serializable_crust_composition(self):
        composition = crust_composition_from_seed({"crust_composition": self.crust_composition})
        composition["major_elements"] = [
            {
                "symbol": element["symbol"],
                "name": element["name"],
                "abundance_percent": round(float(element["abundance_percent"]), 4),
            }
            for element in composition.get("major_elements", [])
        ]
        composition["trace_reserve_percent"] = TRACE_RESERVE_PERCENT
        return composition

    def _crust_major_total(self):
        return sum(float(element.get("abundance_percent", 0.0)) for element in self.crust_composition.get("major_elements", []))

    def _current_seed_values(self):
        seed = {}
        for field_id, _label in self.SEED_FIELDS:
            text = str(self.seed_input_buffers.get(field_id, "")).strip()
            if field_id in {
                "radius_earth",
                "core_radius_fraction",
                "crust_thickness_km",
                "angular_velocity_deg_per_hour",
                "water_fraction",
            }:
                try:
                    seed[field_id] = float(text)
                except ValueError:
                    seed[field_id] = self.DEFAULT_SEED[field_id]
            else:
                seed[field_id] = text or self.DEFAULT_SEED[field_id]
        seed["crust_composition"] = self._serializable_crust_composition()
        return seed

    def _estimate_crust_density(self):
        return estimate_crust_density_kg_m3(self.crust_composition)

    def _derive_planet_physics(self, seed=None):
        return derive_planet_physics(seed or self._current_seed_values(), self._estimate_crust_density())

    def _crust_classification(self):
        return classify_crust_type(self.crust_composition)

    def _selected_semi_major_axis_au(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            return None
        value = planet.get("semi_major_axis_m")
        try:
            if value:
                return float(value) / self.AU_M
        except (TypeError, ValueError):
            pass
        periapsis = self._parse_float(planet.get("periapsis_au"))
        apoapsis = self._parse_float(planet.get("apoapsis_au"))
        if periapsis is not None and apoapsis is not None:
            return (periapsis + apoapsis) / 2.0
        return None

    def _derive_atmosphere_model(self, seed=None, physics=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        return derive_atmosphere_model(
            seed=seed,
            physics=physics,
            stellar_luminosity_solar=self.star_luminosity_solar,
            semi_major_axis_au=self._selected_semi_major_axis_au() or 1.0,
        )

    def _derive_interior_regime_model(self, seed=None, physics=None, atmosphere=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        atmosphere = atmosphere or self._derive_atmosphere_model(seed, physics)
        return derive_interior_regime_model(
            seed=seed,
            physics=physics,
            atmosphere=atmosphere,
            crust_type=self._crust_classification(),
        )

    def _derive_terrain_seed_model(self, seed=None, physics=None, atmosphere=None, regime=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        atmosphere = atmosphere or self._derive_atmosphere_model(seed, physics)
        regime = regime or self._derive_interior_regime_model(seed, physics, atmosphere)
        return derive_terrain_seed_model(
            seed=seed,
            physics=physics,
            atmosphere=atmosphere,
            regime=regime,
        )

    def _derive_heightmap_model(self, terrain=None, seed=None, physics=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        terrain = terrain or self._derive_terrain_seed_model(seed, physics)
        planet = planet or self._selected_planet_entity() or {}
        return derive_heightmap_model(
            terrain=terrain,
            seed=seed,
            physics=physics,
            planet_id=planet.get("id", ""),
            tectonic_model=planet.get("tectonic_model") if isinstance(planet.get("tectonic_model"), dict) else None,
            crater_model=planet.get("crater_model") if isinstance(planet.get("crater_model"), dict) else None,
        )

    def _derive_tectonic_model(self, terrain=None, seed=None, physics=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        terrain = terrain or self._derive_terrain_seed_model(seed, physics)
        planet = planet or self._selected_planet_entity() or {}
        return derive_tectonic_model(
            terrain=terrain,
            seed=seed,
            physics=physics,
            planet_id=planet.get("id", ""),
        )

    def _derive_crater_model(self, terrain=None, seed=None, physics=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        terrain = terrain or self._derive_terrain_seed_model(seed, physics)
        planet = planet or self._selected_planet_entity() or {}
        return derive_crater_model(
            terrain=terrain,
            seed=seed,
            physics=physics,
            planet_id=planet.get("id", ""),
        )

    def _set_crust_abundance_from_screen_x(self, symbol, screen_x):
        rect = self.crust_slider_rects.get(symbol)
        if rect is None or rect.width <= 0:
            return False
        fraction = max(0.0, min(1.0, (float(screen_x) - rect.x) / rect.width))
        self.crust_composition = set_major_element_abundance(
            self.crust_composition,
            symbol,
            fraction * MAJOR_CRUST_TARGET_PERCENT,
        )
        self.commit_status = "Crust composition adjusted"
        return True

    def _add_abundant_trace_element(self, symbol):
        before = [element.get("symbol") for element in self.crust_composition.get("major_elements", [])]
        self.crust_composition = add_abundant_trace_element(self.crust_composition, symbol)
        after = [element.get("symbol") for element in self.crust_composition.get("major_elements", [])]
        self.periodic_table_open = False
        if before == after:
            self.commit_status = f"{symbol} is already explicit"
            return False
        self.commit_status = f"Added {symbol} to explicit crust composition"
        return True

    def _persist_existing_location_entity(self, entity):
        entry_path = self._locations_entry_path()
        try:
            data = yaml.safe_load(entry_path.read_text(encoding="utf-8")) if entry_path.exists() else []
        except (OSError, yaml.YAMLError):
            return False

        if not isinstance(data, list):
            return False

        entity_id = entity.get("id")
        for index, item in enumerate(data):
            if isinstance(item, dict) and item.get("id") == entity_id:
                data[index] = self._serializable_entity(entity)
                try:
                    entry_path.write_text(
                        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                except OSError:
                    return False
                return True
        return False

    def _save_selected_planet_seed(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False

        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: radius/spin/crust > 0, core 0-0.95, water 0-1"
            return False

        planet["world_gen_seed"] = seed
        tags = list(planet.get("tags") or [])
        if "world_gen_seeded" not in tags:
            tags.append("world_gen_seeded")
        planet["tags"] = tags
        planet["environment_summary"] = {
            "status": "seed_defined",
            "summary": (
                f"Water fraction {seed['water_fraction']:.2f}; "
                f"volatile inventory {seed['volatile_inventory']}."
            ),
        }
        planet["geology_summary"] = {
            "status": "seed_defined",
            "start_condition": (
                f"Crust major elements total {self._crust_major_total():.2f}% plus "
                f"{TRACE_RESERVE_PERCENT:.2f}% implicit trace reserve; "
                f"mean density {seed['derived_planet_physics']['mean_density_kg_m3']:.0f} kg/m3; "
                f"tectonics {seed['tectonics_mode']}."
            ),
        }
        planet["crust_composition"] = seed["crust_composition"]
        planet["derived_planet_physics"] = seed["derived_planet_physics"]
        planet["mass_kg"] = seed["derived_planet_physics"]["mass_kg"]
        planet["radius_m"] = seed["derived_planet_physics"]["radius_m"]
        planet["rotation_period_hours"] = seed["derived_planet_physics"]["rotation_period_hours"]

        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        self.commit_status = "Saved planet seed" if persisted else "Seed saved in memory"
        self.editor_stage = "atmosphere"
        if persisted:
            self.commit_status = "Crust saved; atmosphere model ready"
        else:
            self.commit_status = "Crust saved in memory; atmosphere model ready"
        return True

    def _save_atmosphere_model(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False

        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: fix physical inputs before atmosphere"
            return False

        atmosphere = self._derive_atmosphere_model(seed, seed["derived_planet_physics"])
        planet["atmosphere_model"] = atmosphere
        planet["atmosphere_summary"] = {
            "status": "modeled",
            "surface_pressure_bar": atmosphere["surface_pressure_bar"],
            "estimated_surface_temperature_k": atmosphere["estimated_surface_temperature_k"],
            "dominant_gases": [
                item["molecule"]
                for item in atmosphere.get("composition", [])[:3]
            ],
        }
        tags = list(planet.get("tags") or [])
        if "atmosphere_modeled" not in tags:
            tags.append("atmosphere_modeled")
        planet["tags"] = tags

        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        self.editor_stage = "regime"
        if persisted:
            self.commit_status = "Atmosphere saved; interior regime ready"
        else:
            self.commit_status = "Atmosphere saved in memory; interior regime ready"
        return True

    def _save_interior_regime_model(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False

        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: fix physical inputs before regime"
            return False

        physics = seed["derived_planet_physics"]
        atmosphere = planet.get("atmosphere_model")
        if not isinstance(atmosphere, dict):
            atmosphere = self._derive_atmosphere_model(seed, physics)
            planet["atmosphere_model"] = atmosphere

        regime = self._derive_interior_regime_model(seed, physics, atmosphere)
        planet["interior_regime_model"] = regime
        planet["surface_process_model"] = regime.get("surface_processes", {})
        planet["map_generation_recipe"] = regime.get("map_recipe", [])
        planet["geology_summary"] = {
            "status": "regime_modeled",
            "tectonic_regime": regime["interior"]["tectonic_regime"],
            "volcanic_activity": regime["interior"]["volcanic_activity"],
            "crater_retention": regime["surface_processes"]["crater_retention"],
            "primary_topography": regime["surface_processes"]["primary_topography"],
        }
        planet["environment_summary"] = {
            "status": "surface_regime_modeled",
            "hydrologic_cycle": regime["surface_processes"]["hydrologic_cycle"],
            "erosion_processes": list(regime["surface_processes"].get("erosion_processes", [])),
            "surface_pressure_bar": regime["surface_processes"]["surface_pressure_bar"],
            "surface_temperature_k": regime["surface_processes"]["surface_temperature_k"],
        }
        tags = list(planet.get("tags") or [])
        for tag in ("interior_regime_modeled", "surface_processes_modeled"):
            if tag not in tags:
                tags.append(tag)
        planet["tags"] = tags

        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        self.editor_stage = "terrain"
        if persisted:
            self.commit_status = "Regime saved; terrain seed ready"
        else:
            self.commit_status = "Regime saved in memory; terrain seed ready"
        return True

    def _save_terrain_seed_model(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False

        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: fix physical inputs before terrain"
            return False

        physics = seed["derived_planet_physics"]
        atmosphere = planet.get("atmosphere_model")
        if not isinstance(atmosphere, dict):
            atmosphere = self._derive_atmosphere_model(seed, physics)
            planet["atmosphere_model"] = atmosphere

        regime = planet.get("interior_regime_model")
        if not isinstance(regime, dict):
            regime = self._derive_interior_regime_model(seed, physics, atmosphere)
            planet["interior_regime_model"] = regime
            planet["surface_process_model"] = regime.get("surface_processes", {})

        terrain = self._derive_terrain_seed_model(seed, physics, atmosphere, regime)
        canvas = terrain.get("map_canvas", {})
        planet["terrain_seed_model"] = terrain
        planet["map_generation_recipe"] = terrain.get("map_recipe", [])
        planet["map_layers"] = terrain.get("map_layers", [])
        planet["map_projection"] = canvas.get("projection", "equirectangular")
        planet["map_canvas_width_px"] = canvas.get("width_px", 2048)
        planet["map_canvas_height_px"] = canvas.get("height_px", 1024)
        if terrain.get("tectonics", {}).get("enabled"):
            tectonic_model = self._derive_tectonic_model(terrain, seed, physics, planet)
            planet["tectonic_model"] = tectonic_model
            planet.pop("crater_model", None)
            planet.pop("heightmap_model", None)
            map_status = "tectonic_plates_defined"
            geology_status = "tectonic_plates_defined"
            self.editor_stage = "tectonics"
        else:
            crater_model = self._derive_crater_model(terrain, seed, physics, planet)
            planet["crater_model"] = crater_model
            planet.pop("tectonic_model", None)
            heightmap = self._derive_heightmap_model(terrain, seed, physics, planet)
            planet["heightmap_model"] = heightmap
            map_status = "crater_heightmap_seeded"
            geology_status = "crater_heightmap_seeded"
            self.editor_stage = "heightmap"

        planet["map_status"] = map_status
        planet["geology_summary"] = {
            "status": geology_status,
            "tectonic_regime": terrain["tectonics"]["regime"],
            "plate_count": terrain["tectonics"]["plate_count"],
            "relief_driver": terrain["heightfield"]["relief_driver"],
            "crater_density": terrain["cratering"]["density"],
        }
        if isinstance(planet.get("heightmap_model"), dict):
            planet["geology_summary"]["elevation_range_m"] = [
                planet["heightmap_model"]["min_elevation_m"],
                planet["heightmap_model"]["max_elevation_m"],
            ]
        planet["hydrology_summary"] = {
            "status": "seeded",
            "cycle": terrain["hydrology"]["cycle"],
            "target_ocean_fraction": terrain["hydrology"]["target_ocean_fraction"],
            "drainage_enabled": terrain["hydrology"]["drainage_enabled"],
        }
        planet["environment_summary"] = {
            "status": map_status,
            "erosion_processes": list(terrain["erosion"].get("processes", [])),
            "erosion_strength": terrain["erosion"]["strength"],
            "liquid_water_possible": terrain["hydrology"]["liquid_water_possible"],
        }
        tags = list(planet.get("tags") or [])
        stage_tags = ["terrain_seeded", "map_layers_seeded"]
        if terrain.get("tectonics", {}).get("enabled"):
            stage_tags.extend(["tectonic_plates_defined"])
        else:
            stage_tags.extend(["crater_field_seeded", "heightfield_seeded", "heightmap_seeded"])
        for tag in stage_tags:
            if tag not in tags:
                tags.append(tag)
        planet["tags"] = tags

        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        if terrain.get("tectonics", {}).get("enabled"):
            self.commit_status = "Tectonic plates ready"
        else:
            self.commit_status = "Cratered heightmap ready"
        if not persisted:
            self.commit_status += " in memory"
        return True

    def _advance_tectonics_model(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False

        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: fix physical inputs before advancing tectonics"
            return False

        terrain = planet.get("terrain_seed_model")
        if not isinstance(terrain, dict):
            physics = seed["derived_planet_physics"]
            atmosphere = planet.get("atmosphere_model") if isinstance(planet.get("atmosphere_model"), dict) else None
            regime = planet.get("interior_regime_model") if isinstance(planet.get("interior_regime_model"), dict) else None
            terrain = self._derive_terrain_seed_model(seed, physics, atmosphere, regime)
            planet["terrain_seed_model"] = terrain

        tectonic_model = planet.get("tectonic_model")
        if not isinstance(tectonic_model, dict):
            tectonic_model = self._derive_tectonic_model(terrain, seed, seed["derived_planet_physics"], planet)

        advanced = advance_tectonics_model(tectonic_model, terrain, million_years=125.0)
        planet["tectonic_model"] = advanced
        planet.pop("crater_model", None)
        heightmap = derive_heightmap_model(
            terrain=terrain,
            seed=seed,
            physics=seed["derived_planet_physics"],
            planet_id=planet.get("id", ""),
            tectonic_model=advanced,
        )
        planet["heightmap_model"] = heightmap
        planet["map_status"] = "tectonics_advanced"
        planet["geology_summary"] = {
            "status": "tectonics_advanced",
            "tectonic_age_myr": advanced["age_myr"],
            "plate_count": advanced["plate_count"],
            "orogenic_uplift": advanced["surface_effects"]["orogenic_uplift"],
            "ocean_basin_opening": advanced["surface_effects"]["ocean_basin_opening"],
            "erosion_progress": advanced["surface_effects"]["erosion_progress"],
            "elevation_range_m": [
                heightmap["min_elevation_m"],
                heightmap["max_elevation_m"],
            ],
        }
        tags = list(planet.get("tags") or [])
        for tag in ("tectonics_advanced", "heightfield_seeded", "heightmap_seeded"):
            if tag not in tags:
                tags.append(tag)
        planet["tags"] = tags

        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        self.editor_stage = "heightmap"
        self.commit_status = "Advanced tectonics; heightmap ready" if persisted else "Advanced tectonics in memory; heightmap ready"
        return True

    def _refresh_heightmap_model(self):
        planet = self._selected_planet_entity()
        if planet is None:
            self.commit_status = "Select a planet first"
            return False
        terrain = planet.get("terrain_seed_model")
        if not isinstance(terrain, dict):
            self.commit_status = "Save terrain before refreshing heightmap"
            return False
        seed = self._coerce_seed_payload()
        if seed is None:
            self.commit_status = "Seed invalid: fix physical inputs before heightmap"
            return False
        heightmap = derive_heightmap_model(
            terrain=terrain,
            seed=seed,
            physics=seed["derived_planet_physics"],
            planet_id=planet.get("id", ""),
            tectonic_model=planet.get("tectonic_model") if isinstance(planet.get("tectonic_model"), dict) else None,
            crater_model=planet.get("crater_model") if isinstance(planet.get("crater_model"), dict) else None,
        )
        planet["heightmap_model"] = heightmap
        if isinstance(planet.get("geology_summary"), dict):
            planet["geology_summary"]["elevation_range_m"] = [
                heightmap["min_elevation_m"],
                heightmap["max_elevation_m"],
            ]
        loader = getattr(self.world_model, "loader", None)
        if loader is not None and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files({planet.get("id")})
        persisted = self._persist_existing_location_entity(planet)
        self.commit_status = "Refreshed heightmap" if persisted else "Refreshed heightmap in memory"
        return True

    def _heightmap_can_advance_tectonics(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            return False
        if isinstance(planet.get("crater_model"), dict):
            return False
        if planet.get("map_status") == "crater_heightmap_seeded":
            return False
        terrain = planet.get("terrain_seed_model")
        if isinstance(terrain, dict) and bool((terrain.get("tectonics") or {}).get("enabled")):
            return True
        regime = planet.get("interior_regime_model")
        if isinstance(regime, dict):
            interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
            if interior.get("tectonic_regime") in {"plate_tectonics", "mobile_lid"}:
                return True
        geology = planet.get("geology_summary")
        if isinstance(geology, dict) and geology.get("tectonic_regime") in {"plate_tectonics", "mobile_lid"}:
            return True
        surface = planet.get("surface_process_model")
        if isinstance(surface, dict) and surface.get("primary_topography") == "plate_boundaries_mountain_belts_and_trenches":
            return True
        tectonic_model = planet.get("tectonic_model")
        return isinstance(tectonic_model, dict) and bool(tectonic_model.get("plates"))

    def _handle_heightmap_primary_action(self):
        if self._heightmap_can_advance_tectonics():
            return self._advance_tectonics_model()
        return self._refresh_heightmap_model()


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
        if not self.explicit_parent_system_id:
            self.planet_location_id = planet["id"]
            self.planet_entity = planet
        self.selected_world_gen_planet_id = planet["id"]
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
        selected_planet = self._selected_planet_entity()
        terrain_model = (
            selected_planet.get("terrain_seed_model")
            if isinstance(selected_planet, dict) and isinstance(selected_planet.get("terrain_seed_model"), dict)
            else self._derive_terrain_seed_model()
        )
        heightmap_model = (
            selected_planet.get("heightmap_model")
            if isinstance(selected_planet, dict) and isinstance(selected_planet.get("heightmap_model"), dict)
            else self._derive_heightmap_model(terrain=terrain_model, planet=selected_planet)
        )
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
            "selected_planet": selected_planet,
            "seed_fields": [
                {
                    "id": field_id,
                    "label": label,
                    "text": self.seed_input_buffers.get(field_id, ""),
                    "active": field_id == self.active_seed_field,
                }
                for field_id, label in self.SEED_FIELDS
            ],
            "crust_composition": self._serializable_crust_composition(),
            "crust_major_total_percent": self._crust_major_total(),
            "crust_target_percent": MAJOR_CRUST_TARGET_PERCENT,
            "trace_reserve_percent": TRACE_RESERVE_PERCENT,
            "crust_density_kg_m3": self._estimate_crust_density(),
            "crust_type": self._crust_classification(),
            "derived_planet_physics": self._derive_planet_physics(),
            "periodic_table_open": self.periodic_table_open,
            "periodic_table_rows": PERIODIC_TABLE_ROWS,
            "editor_stage": self.editor_stage,
            "atmosphere_model": self._derive_atmosphere_model(),
            "interior_regime_model": self._derive_interior_regime_model(),
            "terrain_seed_model": terrain_model,
            "heightmap_model": heightmap_model,
            "tectonic_model": (
                selected_planet.get("tectonic_model")
                if isinstance(selected_planet, dict) and isinstance(selected_planet.get("tectonic_model"), dict)
                else self._derive_tectonic_model(terrain=terrain_model, planet=selected_planet)
            ),
            "crater_model": (
                selected_planet.get("crater_model")
                if isinstance(selected_planet, dict) and isinstance(selected_planet.get("crater_model"), dict)
                else None
            ),
            "star": self.star_entity,
            "scope_label": self.get_scope_label(),
            "breadcrumb": self.get_scope_breadcrumb(),
            "summary_lines": self._summary_lines(model),
            "orbit_pick_stage": self.orbit_pick_stage,
            "pending_orbit_radius_au": self.pending_orbit_radius_au,
            "planet_name_prompt_active": self.planet_name_prompt_active,
            "planet_name_buffer": self.planet_name_buffer,
            "commit_status": self.commit_status,
            "selected_world_gen_planet_id": self.selected_world_gen_planet_id,
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

    def _cycle_seed_field(self, direction=1):
        field_ids = [field_id for field_id, _label in self.SEED_FIELDS if field_id in self.VISIBLE_PHYSICAL_FIELD_IDS]
        if self.active_seed_field not in field_ids:
            self.active_seed_field = field_ids[0]
            return
        index = field_ids.index(self.active_seed_field)
        self.active_seed_field = field_ids[(index + direction) % len(field_ids)]

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

            if self._selected_planet_entity() is not None:
                if event.key == pygame.K_ESCAPE:
                    if self.periodic_table_open:
                        self.periodic_table_open = False
                    else:
                        self.selected_world_gen_planet_id = None
                    self.commit_status = ""
                    return
                if event.key == pygame.K_TAB:
                    self._cycle_seed_field(-1 if event.mod & pygame.KMOD_SHIFT else 1)
                    return
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if self.editor_stage == "atmosphere":
                        self._save_atmosphere_model()
                    elif self.editor_stage == "regime":
                        self._save_interior_regime_model()
                    elif self.editor_stage == "terrain":
                        self._save_terrain_seed_model()
                    elif self.editor_stage == "heightmap":
                        self._handle_heightmap_primary_action()
                    elif self.editor_stage == "tectonics":
                        self._advance_tectonics_model()
                    else:
                        self._save_selected_planet_seed()
                    return
                if event.key == pygame.K_BACKSPACE:
                    buffer_text = self.seed_input_buffers.get(self.active_seed_field, "")
                    self.seed_input_buffers[self.active_seed_field] = buffer_text[:-1]
                    return
                if event.key == pygame.K_DELETE:
                    self.seed_input_buffers[self.active_seed_field] = ""
                    return
                text = getattr(event, "unicode", "")
                if text and text.isprintable():
                    allowed = "0123456789.-" if self.active_seed_field in {
                        "radius_earth",
                        "core_radius_fraction",
                        "crust_thickness_km",
                        "angular_velocity_deg_per_hour",
                        "water_fraction",
                    } else None
                    if allowed is None or text in allowed:
                        self.seed_input_buffers[self.active_seed_field] = (
                            self.seed_input_buffers.get(self.active_seed_field, "") + text
                        )
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
            if self.periodic_table_open:
                return
            for field_id, rect in self.seed_field_rects.items():
                if rect.collidepoint(mouse_pos):
                    self.active_seed_field = field_id
                    return
            for field_id, rect in self.input_field_rects.items():
                if rect.collidepoint(mouse_pos):
                    self.active_input_field = field_id
                    return

    def handle_pointer_event(self, event, camera, screen_pos):
        import pygame

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.active_crust_slider_symbol = None
            return

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        if self.periodic_table_open:
            for symbol, rect in self.periodic_element_rects.items():
                if rect.collidepoint(screen_pos):
                    self._add_abundant_trace_element(symbol)
                    return
            if self.periodic_table_rect is None or not self.periodic_table_rect.collidepoint(screen_pos):
                self.periodic_table_open = False
            return

        if self.control_panel_rect is not None and self.control_panel_rect.collidepoint(screen_pos):
            if self.editor_stage == "atmosphere":
                if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                    self._save_atmosphere_model()
                return
            if self.editor_stage == "regime":
                if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                    self._save_interior_regime_model()
                return
            if self.editor_stage == "terrain":
                if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                    self._save_terrain_seed_model()
                return
            if self.editor_stage == "heightmap":
                if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                    self._handle_heightmap_primary_action()
                return
            if self.editor_stage == "tectonics":
                if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                    self._advance_tectonics_model()
                return
            if self.crust_add_trace_button_rect is not None and self.crust_add_trace_button_rect.collidepoint(screen_pos):
                self.periodic_table_open = True
                self.commit_status = "Select an element to promote from trace reserve"
                return
            if self.crust_save_button_rect is not None and self.crust_save_button_rect.collidepoint(screen_pos):
                self._save_selected_planet_seed()
                return
            for symbol, rect in self.crust_slider_rects.items():
                if rect.collidepoint(screen_pos):
                    self.active_crust_slider_symbol = symbol
                    self._set_crust_abundance_from_screen_x(symbol, screen_pos[0])
                    return
            return

        for entity_id, rect in self.planet_hitboxes:
            if rect.collidepoint(screen_pos):
                self._select_planet_for_worldgen(entity_id)
                return

        radius_au = self._distance_au_from_world_point(camera.screen_to_world(screen_pos))
        if radius_au is None:
            return

        self.selected_world_gen_planet_id = None
        if self.orbit_pick_stage == "second" and self.pending_orbit_radius_au is not None:
            self._set_elliptical_orbit_from_radius(radius_au)
            return

        self._set_circular_orbit_from_radius(radius_au)

    def handle_pointer_motion(self, event, camera, screen_pos):
        if self.active_crust_slider_symbol:
            self._set_crust_abundance_from_screen_x(self.active_crust_slider_symbol, screen_pos[0])
