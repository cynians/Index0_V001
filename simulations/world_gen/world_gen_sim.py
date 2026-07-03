import random
import re
import hashlib
from pathlib import Path


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
    element_name,
    estimate_crust_density_kg_m3,
    set_major_element_abundance,
    trace_element_rarity,
    trace_element_weight,
    trace_promotion_abundance,
)
from simulations.world_gen.formation_theory import (
    candidate_orbits_au,
    formation_model_for_orbit,
    max_feasible_planets,
)
from simulations.world_gen.heightmap import derive_heightmap_model
from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.map_seed import resolved_map_seed, seed_range
from simulations.world_gen.material_catalog import element_symbols_by_rarity
from simulations.world_gen.natural_materials import (
    atmospheric_band_palette,
    derive_atmospheric_material_model,
    derive_natural_material_model,
    derive_planet_surface_palette,
    derive_planet_material_tags,
)
from simulations.world_gen.planetary_physics import derive_planet_physics
from simulations.world_gen.terrain_seed import derive_terrain_seed_model
from simulations.world_gen.tectonics import (
    advance_tectonics_model,
    derive_crater_model,
    derive_tectonic_model,
    mature_tectonics_model,
)
from world.year_utils import parse_year
from world.relation_mirror import mirror_location_sim_relations


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
        ("map_seed", "Map Seed"),
    ]
    DEFAULT_SEED = {
        "radius_earth": 1.0,
        "core_radius_fraction": 0.55,
        "crust_thickness_km": 35.0,
        "angular_velocity_deg_per_hour": 15.0,
        "water_fraction": 0.5,
        "volatile_inventory": "earthlike",
        "tectonics_mode": "unknown",
        "map_seed": "auto",
    }
    PLANET_TEMPLATES = {
        "silicate_terrestrial": {
            "label": "Silicate terrestrial",
            "planet_class": "terrestrial",
            "major_elements": [
                ("O", 46.86), ("Si", 27.84), ("Al", 8.14), ("Fe", 5.03),
                ("Ca", 3.62), ("Na", 2.81), ("K", 2.61), ("Mg", 2.11),
            ],
            "water_range": (0.12, 0.74),
            "volatile_options": ["dry", "wet", "earthlike"],
            "tectonics_options": ["stagnant_lid", "mobile_lid", "unknown"],
        },
        "ocean_world": {
            "label": "Ocean world",
            "planet_class": "ocean_world",
            "major_elements": [
                ("O", 51.0), ("Si", 22.0), ("Mg", 7.0), ("Fe", 6.0),
                ("Al", 5.0), ("Ca", 3.0), ("Na", 3.0), ("C", 1.0), ("S", 1.0),
            ],
            "water_range": (0.72, 0.98),
            "volatile_options": ["wet", "earthlike", "dense"],
            "tectonics_options": ["stagnant_lid", "mobile_lid", "episodic_lid"],
        },
        "desiccated_former_ocean": {
            "label": "Desiccated former ocean",
            "planet_class": "desert_terrestrial",
            "major_elements": [
                ("O", 43.0), ("Si", 26.0), ("Fe", 8.0), ("Mg", 6.0),
                ("Al", 7.0), ("Ca", 4.0), ("Na", 2.5), ("S", 1.6), ("C", 0.9),
            ],
            "water_range": (0.0, 0.08),
            "volatile_options": ["dry", "thin", "dense"],
            "tectonics_options": ["inactive", "stagnant_lid", "episodic_lid"],
        },
        "cratered_airless": {
            "label": "Cratered airless body",
            "planet_class": "airless_rocky",
            "major_elements": [
                ("O", 42.0), ("Si", 21.0), ("Fe", 12.0), ("Mg", 9.0),
                ("Al", 6.0), ("Ca", 5.0), ("Ti", 2.0), ("Na", 1.5), ("S", 0.5),
            ],
            "water_range": (0.0, 0.025),
            "volatile_options": ["none", "thin"],
            "tectonics_options": ["inactive"],
        },
        "carbon_rich": {
            "label": "Carbon-rich rocky",
            "planet_class": "carbon_rich_terrestrial",
            "major_elements": [
                ("O", 24.0), ("Si", 23.0), ("C", 18.0), ("Fe", 12.0),
                ("Mg", 9.0), ("Al", 5.0), ("Ca", 3.0), ("S", 2.0), ("Ni", 1.0),
            ],
            "water_range": (0.0, 0.35),
            "volatile_options": ["dry", "thin", "dense"],
            "tectonics_options": ["inactive", "stagnant_lid", "heat_pipe", "unknown"],
        },
        "gas_giant": {
            "label": "Gas giant",
            "planet_class": "gas_giant",
            "major_elements": [
                ("H", 72.5), ("He", 24.5), ("O", 1.15), ("C", 0.78),
                ("N", 0.34), ("S", 0.22), ("Ne", 0.16), ("Ar", 0.08),
            ],
            "water_range": (0.0, 0.12),
            "volatile_options": ["dense"],
            "tectonics_options": ["inactive"],
        },
        "ice_giant": {
            "label": "Ice giant",
            "planet_class": "ice_giant",
            "major_elements": [
                ("H", 48.0), ("He", 14.0), ("O", 18.0), ("C", 8.5),
                ("N", 5.0), ("S", 2.0), ("Ne", 1.0), ("Ar", 0.5), ("Si", 1.0), ("Fe", 1.0),
            ],
            "water_range": (0.08, 0.35),
            "volatile_options": ["dense"],
            "tectonics_options": ["inactive"],
        },
    }
    VISIBLE_PHYSICAL_FIELD_IDS = {
        "radius_earth",
        "core_radius_fraction",
        "crust_thickness_km",
        "angular_velocity_deg_per_hour",
        "water_fraction",
        "map_seed",
    }

    def __init__(self, world_model=None, planet_location_id=None, parent_system_id=None, year=2400):
        from engine.clock import Clock

        self.render_mode = "world_gen"
        self.request_close_tab = False
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
        self.crust_random_generic_button_rect = None
        self.crust_random_eccentric_button_rect = None
        self.crust_random_gas_giant_button_rect = None
        self.formation_theory_button_rect = None
        self.crust_save_button_rect = None
        self.world_gen_back_button_rect = None
        self.world_gen_complete_button_rect = None
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
        self.pending_back_stage = None
        self.planet_hitboxes = []
        self.selected_world_gen_planet_id = planet_location_id
        self.active_seed_field = "radius_earth"
        self.seed_input_buffers = {
            field_id: self._format_seed_input(value)
            for field_id, value in self.DEFAULT_SEED.items()
        }
        self.crust_composition = default_crust_composition()
        self.active_planet_template = "silicate_terrestrial"
        self.active_crust_slider_symbol = None
        self.periodic_table_open = False
        self.editor_stage = "crust"
        if isinstance(self.planet_entity, dict):
            self._load_seed_buffers_from_planet(self.planet_entity)

        self.parent_system_id = self._resolve_parent_system_id()
        self.star_entity = self._resolve_primary_star()
        self.star_luminosity_solar = self._estimate_star_luminosity_solar(self.star_entity)
        self.planetary_model = {}
        if isinstance(self.planet_entity, dict):
            self._repair_gas_giant_route_if_needed(self.planet_entity)
            self.editor_stage = self._resume_stage_for_planet(self.planet_entity)
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

    def consumes_global_keydown(self):
        return self.planet_name_prompt_active

    def update(self, dt):
        self.sim_clock.update(dt)

    def set_input_field_rects(self, rects):
        self.input_field_rects = dict(rects or {})

    def set_seed_field_rects(self, rects):
        self.seed_field_rects = dict(rects or {})

    def set_crust_ui_rects(
        self,
        slider_rects=None,
        add_trace_rect=None,
        save_rect=None,
        periodic_rect=None,
        element_rects=None,
        random_generic_rect=None,
        random_eccentric_rect=None,
        random_gas_giant_rect=None,
        complete_rect=None,
        back_rect=None,
    ):
        self.crust_slider_rects = dict(slider_rects or {})
        self.crust_add_trace_button_rect = add_trace_rect
        self.crust_random_generic_button_rect = random_generic_rect
        self.crust_random_eccentric_button_rect = random_eccentric_rect
        self.crust_random_gas_giant_button_rect = random_gas_giant_rect
        self.crust_save_button_rect = save_rect
        self.world_gen_complete_button_rect = complete_rect
        self.world_gen_back_button_rect = back_rect
        self.periodic_table_rect = periodic_rect
        self.periodic_element_rects = dict(element_rects or {})

    def set_control_panel_rect(self, rect):
        self.control_panel_rect = rect

    def set_formation_theory_button_rect(self, rect):
        self.formation_theory_button_rect = rect

    def set_heightmap_preview_rect(self, rect):
        self.heightmap_preview_rect = rect

    def set_planet_hitboxes(self, hitboxes):
        self.planet_hitboxes = list(hitboxes or [])

    def _clear_editor_hitboxes(self):
        self.seed_field_rects = {}
        self.crust_slider_rects = {}
        self.crust_add_trace_button_rect = None
        self.crust_random_generic_button_rect = None
        self.crust_random_eccentric_button_rect = None
        self.crust_random_gas_giant_button_rect = None
        self.formation_theory_button_rect = None
        self.crust_save_button_rect = None
        self.world_gen_back_button_rect = None
        self.world_gen_complete_button_rect = None
        self.periodic_table_rect = None
        self.periodic_element_rects = {}
        self.control_panel_rect = None

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

    def _iter_location_entities(self):
        seen = set()
        if hasattr(self.world_model, "get_entities_by_dataset"):
            for entity in self.world_model.get_entities_by_dataset("locations"):
                entity_id = entity.get("id") if isinstance(entity, dict) else None
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                yield entity

        loader = getattr(self.world_model, "loader", None)
        locations = getattr(loader, "datasets", {}).get("locations", []) if loader is not None else []
        for entity in locations:
            entity_id = entity.get("id") if isinstance(entity, dict) else None
            if entity_id in seen:
                continue
            seen.add(entity_id)
            yield entity

    def _find_existing_planet_entity(self, planet_name):
        slug = self._slug_from_text(planet_name)
        name_key = str(planet_name or "").strip().lower()
        candidate_ids = {f"planet_{slug}", f"loc_{slug}", slug}
        soft_match = None

        for entity in self._iter_location_entities():
            if not isinstance(entity, dict):
                continue
            class_key = str(entity.get("location_class") or entity.get("body_class") or "").strip().lower()
            if class_key != "planet":
                continue
            entity_system = self._resolve_entity_id(entity.get("star_system"))
            if entity_system and entity_system != self.parent_system_id:
                continue
            entity_id = str(entity.get("id") or "")
            label = str(entity.get("name") or entity.get("pretty_name") or "").strip().lower()
            if entity_id in candidate_ids:
                return entity
            if label == name_key:
                soft_match = entity

        return soft_match

    def _primary_star_id(self):
        if isinstance(self.star_entity, dict) and self.star_entity.get("id"):
            return self.star_entity.get("id")
        return None

    def _persist_location_entity(self, entity):
        loader = getattr(self.world_model, "loader", None)
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        entity["_dataset"] = "locations"
        persisted = loader.persist_entity(entity)
        if persisted and hasattr(self.world_model, "mark_repository_changed"):
            self.world_model.mark_repository_changed()
        if persisted:
            self._append_planet_to_system_wiki(entity)
        return persisted

    def _planet_wiki_link_line(self, planet):
        label = str(
            planet.get("name")
            or planet.get("pretty_name")
            or planet.get("id")
            or ""
        ).strip()
        return f"!! [[{label}]]" if label else ""

    def _append_planet_to_system_wiki(self, planet):
        if not isinstance(planet, dict) or self.world_model is None:
            return False
        class_key = str(planet.get("location_class") or planet.get("body_class") or "").strip().lower()
        if class_key not in {"planet", "dwarf_planet", "gas_giant", "ice_giant"}:
            return False
        system_id = self._resolve_entity_id(planet.get("star_system") or self.parent_system_id)
        if not system_id:
            return False
        system = self.world_model.get_entity(system_id)
        if not isinstance(system, dict):
            return False

        line = self._planet_wiki_link_line(planet)
        if not line:
            return False
        wiki_text = str(system.get("wiki_entry") or "")
        if line in wiki_text.splitlines():
            return False

        lines = wiki_text.splitlines()
        insert_at = None
        for index, existing_line in enumerate(lines):
            if existing_line.strip().casefold() == "! planets":
                insert_at = index + 1
                while insert_at < len(lines) and not lines[insert_at].startswith("! "):
                    insert_at += 1
                break

        if insert_at is None:
            prefix = wiki_text.rstrip()
            addition = f"! Planets\n{line}\n"
            system["wiki_entry"] = f"{prefix}\n\n{addition}" if prefix else addition
        else:
            lines.insert(insert_at, line)
            system["wiki_entry"] = "\n".join(lines).rstrip() + "\n"

        loader = getattr(self.world_model, "loader", None)
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        system["_dataset"] = system.get("_dataset") or "locations"
        persisted = loader.persist_entity(system)
        if persisted and hasattr(self.world_model, "mark_repository_changed"):
            self.world_model.mark_repository_changed()
        return bool(persisted)

    def _register_location_entity(self, entity):
        loader = getattr(self.world_model, "loader", None)
        if loader is None:
            return
        dataset = loader.datasets.setdefault("locations", [])
        for index, existing in enumerate(dataset):
            if isinstance(existing, dict) and existing.get("id") == entity.get("id"):
                dataset[index] = entity
                break
        else:
            dataset.append(entity)
        loader.entities[entity["id"]] = entity
        if hasattr(loader, "build_reference_graph"):
            loader.build_reference_graph()
        graph = getattr(self.world_model, "touch_degrees", None)
        if graph is not None and hasattr(graph, "refresh"):
            graph.refresh()

    def _committed_planet_fields(self, planet_name, model):
        semi_major_au = model.get("semi_major_axis_au")
        eccentricity = model.get("eccentricity")
        periapsis_au = model.get("periapsis_au")
        apoapsis_au = model.get("apoapsis_au")
        parent_star_id = self._primary_star_id()
        anomaly_seed = f"{self.parent_system_id}:{self._slug_from_text(planet_name)}:{semi_major_au:.6f}:{eccentricity:.6f}"
        return {
            "pretty_name": planet_name,
            "name": planet_name,
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "location_role": "orbital_body",
            "system_role": "orbital_body",
            "star_system": self.parent_system_id,
            "parent_location": parent_star_id,
            "parent_body": parent_star_id,
            "semi_major_axis_m": semi_major_au * self.AU_M,
            "eccentricity": eccentricity,
            "periapsis_au": periapsis_au,
            "apoapsis_au": apoapsis_au,
            "mean_anomaly_deg_at_epoch": round(seed_range(anomaly_seed, "mean_anomaly", 0.0, 360.0), 3),
            "map_projection": "equirectangular",
            "map_canvas_width_px": 2048,
            "map_canvas_height_px": 1024,
            "map_status": "orbit_locked",
            "bounds": {
                "type": "bbox",
                "min_x": -180.0,
                "max_x": 180.0,
                "min_y": -90.0,
                "max_y": 90.0,
            },
            "display_color": [92, 148, 206],
            "environment_summary": {
                "status": "orbit_locked",
                "summary": "Initial world-generation seed: orbital placement locked; physical planet model pending.",
            },
            "geology_summary": {
                "status": "pending",
                "start_condition": "Define radius, mass, rotation, volatile inventory, and plate tectonics mode.",
            },
        }

    def _formation_seed_for_planet(self, formation_model, planet_id=""):
        formation_model = formation_model if isinstance(formation_model, dict) else {}
        template_id = formation_model.get("suggested_planet_template") or "silicate_terrestrial"
        template = self.PLANET_TEMPLATES.get(template_id, self.PLANET_TEMPLATES["silicate_terrestrial"])
        seed_key = f"{self.parent_system_id}:{planet_id}:{formation_model.get('formation_orbit_au')}"
        water_low, water_high = formation_model.get("water_fraction_range") or template.get("water_range", (0.1, 0.6))
        radius_range = {
            "gas_giant": (4.0, 11.5),
            "ice_giant": (2.2, 4.5),
            "ocean_world": (0.85, 1.8),
            "cratered_airless": (0.18, 0.85),
            "desiccated_former_ocean": (0.45, 1.2),
            "carbon_rich": (0.55, 1.45),
        }.get(template_id, (0.65, 1.45))
        seed_digest = hashlib.sha256(seed_key.encode("utf-8")).hexdigest()[:8]
        return {
            "radius_earth": round(seed_range(seed_key, "formation_radius", *radius_range), 4),
            "core_radius_fraction": round(seed_range(seed_key, "formation_core", 0.36, 0.68), 4),
            "crust_thickness_km": round(seed_range(seed_key, "formation_crust", 18.0, 58.0), 4),
            "angular_velocity_deg_per_hour": round(seed_range(seed_key, "formation_spin", 5.0, 28.0), 4),
            "water_fraction": round(seed_range(seed_key, "formation_water", float(water_low), float(water_high)), 4),
            "volatile_inventory": formation_model.get("volatile_inventory") or template.get("volatile_options", ["earthlike"])[0],
            "tectonics_mode": "unknown",
            "map_seed": f"formation-{seed_digest}",
            "planet_template": template_id,
            "planet_template_label": template.get("label", template_id),
            "planet_class": template.get("planet_class", "terrestrial"),
            "formation_model": formation_model,
        }

    def _apply_seed_buffers_from_seed(self, seed):
        seed = seed if isinstance(seed, dict) else {}
        for field_id, default_value in self.DEFAULT_SEED.items():
            self.seed_input_buffers[field_id] = self._format_seed_input(seed.get(field_id, default_value))
        template_id = seed.get("planet_template")
        if template_id in self.PLANET_TEMPLATES:
            self.active_planet_template = template_id
            self.crust_composition = {
                "major_elements": [
                    {
                        "symbol": symbol,
                        "name": element_name(symbol),
                        "abundance_percent": abundance,
                    }
                    for symbol, abundance in self.PLANET_TEMPLATES[template_id].get("major_elements", [])
                ],
                "trace_reserve_percent": TRACE_RESERVE_PERCENT,
                "trace_elements": [],
            }

    def _build_committed_planet_entity(self, name):
        model = self._recalculate_model()
        if not model.get("orbit_valid"):
            return None

        planet_name = str(name or "").strip()
        if not planet_name:
            return None

        fields = self._committed_planet_fields(planet_name, model)
        existing_planet = self._find_existing_planet_entity(planet_name)
        if existing_planet is not None:
            existing_planet.update(fields)
            tags = list(existing_planet.get("tags") or [])
            for tag in ("world_gen_candidate", "orbit_locked"):
                if tag not in tags:
                    tags.append(tag)
            existing_planet["tags"] = tags
            existing_planet.setdefault("offspring", [])
            self._set_world_gen_progress(existing_planet, "crust", complete=False)
            mirror_location_sim_relations(existing_planet)
            return existing_planet

        base_id = f"planet_{self._slug_from_text(planet_name)}"
        entity_id = self._unique_entity_id(base_id)

        entity = {
            "id": entity_id,
            "tags": ["world_gen_candidate", "orbit_locked"],
            "offspring": [],
        }
        entity.update(fields)
        self._set_world_gen_progress(entity, "crust", complete=False)
        mirror_location_sim_relations(entity)
        return entity

    def _existing_orbital_planet_count(self):
        return sum(
            1
            for entity in self._active_system_bodies()
            if str(entity.get("location_class") or entity.get("body_class") or "").strip().lower()
            in {"planet", "dwarf_planet", "gas_giant", "ice_giant"}
        )

    def _existing_orbits_au(self):
        orbits = []
        for entity in self._active_system_bodies():
            try:
                semi_major_m = float(entity.get("semi_major_axis_m", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if semi_major_m > 0:
                orbits.append(semi_major_m / self.AU_M)
        return orbits

    def _unique_formation_planet_name(self, base_name):
        existing_names = {
            str(entity.get("name") or entity.get("pretty_name") or "").strip().lower()
            for entity in self._iter_location_entities()
            if isinstance(entity, dict)
        }
        candidate = str(base_name or "Formation Candidate").strip()
        if candidate.lower() not in existing_names:
            return candidate
        suffix = 2
        while f"{candidate} {suffix}".lower() in existing_names:
            suffix += 1
        return f"{candidate} {suffix}"

    def _add_formation_theory_planets(self):
        if not self.parent_system_id:
            self.commit_status = "Formation theory needs a parent star system"
            return False
        original_input_buffers = dict(self.input_buffers)
        original_selected_id = self.selected_world_gen_planet_id
        original_planet_entity = self.planet_entity
        original_stage = self.editor_stage
        existing_count = self._existing_orbital_planet_count()
        maximum = max_feasible_planets(self.star_luminosity_solar, existing_count=existing_count)
        remaining = maximum - existing_count
        if remaining <= 0:
            self.commit_status = f"Formation theory: feasible planet count reached ({existing_count}/{maximum})"
            return False
        add_count = min(2, remaining)
        orbits = candidate_orbits_au(
            self.star_luminosity_solar,
            self._existing_orbits_au(),
            count=add_count,
            system_id=self.parent_system_id or "system",
        )
        if not orbits:
            self.commit_status = "Formation theory found no stable open orbit gaps"
            return False

        created = []
        for index, orbit_au in enumerate(orbits):
            formation = formation_model_for_orbit(
                self.star_luminosity_solar,
                orbit_au,
                system_id=self.parent_system_id or "system",
                candidate_index=existing_count + index,
                mode="generic",
            )
            eccentricity = seed_range(f"{self.parent_system_id}:{orbit_au}", "formation_eccentricity", 0.0, 0.08)
            self.input_buffers["periapsis_au"] = self._format_input_au(orbit_au * (1.0 - eccentricity))
            self.input_buffers["apoapsis_au"] = self._format_input_au(orbit_au * (1.0 + eccentricity))
            self._recalculate_model()
            planet_name = self._unique_formation_planet_name(
                f"{self.get_scope_label()} Formation {existing_count + index + 1}"
            )
            planet = self._build_committed_planet_entity(planet_name)
            if planet is None:
                continue
            seed = self._formation_seed_for_planet(formation, planet_id=planet.get("id", ""))
            planet["formation_model"] = formation
            planet["suggested_planet_template"] = formation.get("suggested_planet_template")
            planet["world_gen_template"] = formation.get("suggested_planet_template")
            planet["formation_theory_seed"] = seed
            tags = list(planet.get("tags") or [])
            for tag in ("formation_theory_candidate", formation.get("formation_zone"), formation.get("suggested_planet_template")):
                if tag and tag not in tags:
                    tags.append(tag)
            planet["tags"] = tags
            self._register_location_entity(planet)
            if self._persist_location_entity(planet):
                created.append(planet)

        if not created:
            self.input_buffers = original_input_buffers
            self.selected_world_gen_planet_id = original_selected_id
            self.planet_entity = original_planet_entity
            self.editor_stage = original_stage
            self._recalculate_model()
            self.commit_status = "Formation theory could not create candidate planets"
            return False
        self.input_buffers = original_input_buffers
        self.selected_world_gen_planet_id = original_selected_id
        self.planet_entity = original_planet_entity
        self.editor_stage = original_stage
        self._recalculate_model()
        names = ", ".join(planet.get("name", planet.get("id")) for planet in created)
        self.commit_status = f"Formation theory added: {names}"
        return True

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
        using_formation_seed = False
        if not seed and isinstance(planet.get("formation_theory_seed"), dict):
            seed = planet.get("formation_theory_seed")
            using_formation_seed = True
        if "angular_velocity_deg_per_hour" not in seed and seed.get("rotation_hours"):
            try:
                seed["angular_velocity_deg_per_hour"] = 360.0 / max(0.0001, float(seed.get("rotation_hours")))
            except (TypeError, ValueError):
                pass
        for field_id, default_value in self.DEFAULT_SEED.items():
            self.seed_input_buffers[field_id] = self._format_seed_input(seed.get(field_id, default_value))
        if self.active_seed_field not in self.seed_input_buffers:
            self.active_seed_field = "radius_earth"
        template_id = str(seed.get("planet_template") or planet.get("suggested_planet_template") or planet.get("world_gen_template") or "").strip()
        if template_id not in self.PLANET_TEMPLATES:
            template_id = "gas_giant" if self._seed_payload_is_gas_giant(seed) else "silicate_terrestrial"
        self.active_planet_template = template_id
        if using_formation_seed:
            self._apply_seed_buffers_from_seed(seed)
        else:
            self.crust_composition = crust_composition_from_seed(seed)

    def _seed_payload_is_gas_giant(self, seed):
        seed = seed if isinstance(seed, dict) else {}
        class_key = str(seed.get("planet_class") or seed.get("planet_template") or "").strip().lower()
        if class_key in {"gas_giant", "ice_giant", "hot_gas_giant"}:
            return True
        physics = seed.get("derived_planet_physics") if isinstance(seed.get("derived_planet_physics"), dict) else {}
        for value in (physics.get("radius_earth"), seed.get("radius_earth")):
            try:
                if float(value or 0.0) >= 3.0:
                    return True
            except (TypeError, ValueError):
                pass
        for value in (physics.get("mass_earth"), seed.get("mass_earth")):
            try:
                if float(value or 0.0) >= 12.0:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def _planet_is_gas_giant_candidate(self, planet):
        if not isinstance(planet, dict):
            return False
        tags = set(planet.get("tags") or [])
        atmosphere = planet.get("atmosphere_model") if isinstance(planet.get("atmosphere_model"), dict) else {}
        if (
            "gas_giant" in tags
            or planet.get("surface_render_mode") == "gas_giant_bands"
            or planet.get("map_render_mode") == "gas_giant_bands"
            or atmosphere.get("has_solid_surface") is False
            or str(planet.get("body_subclass") or planet.get("planetary_class") or "").strip().lower() in {"gas_giant", "ice_giant", "hot_gas_giant"}
        ):
            return True
        seed = planet.get("world_gen_seed") if isinstance(planet.get("world_gen_seed"), dict) else {}
        if self._seed_payload_is_gas_giant(seed):
            return True
        try:
            return float(planet.get("radius_m", 0.0) or 0.0) >= 3.0 * 6_371_000.0
        except (TypeError, ValueError):
            return False

    def _apply_gas_giant_envelope_fields(self, planet, atmosphere, atmospheric_material_model=None):
        atmospheric_material_model = atmospheric_material_model or self._apply_atmospheric_materials(planet, atmosphere)
        planet["map_status"] = "gas_giant_envelope_modeled"
        planet["body_subclass"] = atmosphere.get("atmosphere_class") or "gas_giant"
        planet["planetary_class"] = atmosphere.get("atmosphere_class") or "gas_giant"
        planet["surface_render_mode"] = "gas_giant_bands"
        planet["map_render_mode"] = "gas_giant_bands"
        planet["environment_summary"] = {
            "status": "gas_giant_modeled",
            "atmosphere_class": atmosphere.get("atmosphere_class"),
            "dominant_gases": [
                item.get("molecule")
                for item in atmosphere.get("composition", [])[:3]
                if isinstance(item, dict)
            ],
            "dominant_materials": list(atmospheric_material_model.get("dominant_materials") or []),
        }
        planet["geology_summary"] = {
            "status": "not_applicable",
            "reason": "Gas giant envelope has no normal solid terrain route.",
        }
        for key in ("terrain_seed_model", "tectonic_model", "crater_model", "heightmap_model", "surface_process_model", "hydrology_summary"):
            planet.pop(key, None)
        tags = list(planet.get("tags") or [])
        for tag in ("gas_giant", "atmospheric_body", "no_solid_surface", "gas_giant_bands"):
            if tag not in tags:
                tags.append(tag)
        planet["tags"] = tags
        return planet

    def _repair_gas_giant_route_if_needed(self, planet):
        if not self._planet_is_gas_giant_candidate(planet):
            return False
        seed = self._coerce_seed_payload()
        if seed is None:
            return False
        atmosphere = planet.get("atmosphere_model") if isinstance(planet.get("atmosphere_model"), dict) else None
        needs_repair = (
            not isinstance(atmosphere, dict)
            or atmosphere.get("has_solid_surface") is not False
            or isinstance(planet.get("heightmap_model"), dict)
            or isinstance(planet.get("terrain_seed_model"), dict)
            or planet.get("surface_render_mode") != "gas_giant_bands"
        )
        if not needs_repair:
            return False
        atmosphere = self._derive_atmosphere_model(seed, seed["derived_planet_physics"])
        if atmosphere.get("has_solid_surface") is not False:
            return False
        planet["world_gen_seed"] = seed
        planet["atmosphere_model"] = atmosphere
        planet["atmosphere_summary"] = {
            "status": "modeled",
            "atmosphere_class": atmosphere.get("atmosphere_class", "unknown"),
            "has_solid_surface": False,
            "surface_pressure_bar": atmosphere["surface_pressure_bar"],
            "estimated_surface_temperature_k": atmosphere["estimated_surface_temperature_k"],
            "dominant_gases": [
                item["molecule"]
                for item in atmosphere.get("composition", [])[:3]
            ],
        }
        self._apply_gas_giant_envelope_fields(planet, atmosphere)
        self._set_world_gen_progress(planet, "complete" if planet.get("world_gen_complete") else "atmosphere", complete=bool(planet.get("world_gen_complete")))
        self._mirror_and_persist_planet(planet)
        return True

    def _select_planet_for_worldgen(self, entity_id):
        self.selected_world_gen_planet_id = entity_id
        planet = self._selected_planet_entity()
        if planet is None:
            return False
        self._load_seed_buffers_from_planet(planet)
        repaired = self._repair_gas_giant_route_if_needed(planet)
        self.editor_stage = self._resume_stage_for_planet(planet)
        name = planet.get("name", entity_id)
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self.commit_status = (
            f"Repaired gas giant envelope for {name}; stage {self.editor_stage}"
            if repaired else f"Selected {name}; stage {self.editor_stage}"
        )
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
        planet = self._selected_planet_entity() or {}
        seed["planet_id"] = planet.get("id") or self.selected_world_gen_planet_id or self.planet_location_id or ""
        seed["parent_system_id"] = self.parent_system_id
        template = self.PLANET_TEMPLATES.get(self.active_planet_template, self.PLANET_TEMPLATES["silicate_terrestrial"])
        seed["planet_template"] = self.active_planet_template
        seed["planet_template_label"] = template.get("label", self.active_planet_template)
        seed["planet_class"] = template.get("planet_class", "terrestrial")
        formation_model = planet.get("formation_model") if isinstance(planet.get("formation_model"), dict) else None
        if formation_model is None and isinstance(planet.get("formation_theory_seed"), dict):
            formation_model = planet["formation_theory_seed"].get("formation_model")
        if isinstance(formation_model, dict):
            seed["formation_model"] = formation_model
        seed["resolved_map_seed"] = resolved_map_seed(seed, planet_id=seed["planet_id"], system_id=self.parent_system_id)
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
                **({"rarity": element.get("rarity")} if element.get("rarity") else {}),
            }
            for element in composition.get("major_elements", [])
        ]
        composition["trace_reserve_percent"] = TRACE_RESERVE_PERCENT
        composition["trace_elements"] = [
            {
                "symbol": element.get("symbol"),
                "name": element.get("name") or element_name(element.get("symbol")),
                "abundance_percent": round(float(element.get("abundance_percent", 0.0) or 0.0), 4),
                "rarity": element.get("rarity") or trace_element_rarity(element.get("symbol")),
            }
            for element in composition.get("trace_elements", [])
            if element.get("symbol")
        ]
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
        planet = self._selected_planet_entity() or {}
        seed["planet_id"] = planet.get("id") or self.selected_world_gen_planet_id or self.planet_location_id or ""
        seed["parent_system_id"] = self.parent_system_id
        template = self.PLANET_TEMPLATES.get(self.active_planet_template, self.PLANET_TEMPLATES["silicate_terrestrial"])
        seed["planet_template"] = self.active_planet_template
        seed["planet_template_label"] = template.get("label", self.active_planet_template)
        seed["planet_class"] = template.get("planet_class", "terrestrial")
        formation_model = planet.get("formation_model") if isinstance(planet.get("formation_model"), dict) else None
        if formation_model is None and isinstance(planet.get("formation_theory_seed"), dict):
            formation_model = planet["formation_theory_seed"].get("formation_model")
        if isinstance(formation_model, dict):
            seed["formation_model"] = formation_model
        seed["resolved_map_seed"] = resolved_map_seed(seed, planet_id=seed["planet_id"], system_id=self.parent_system_id)
        seed["crust_composition"] = self._serializable_crust_composition()
        return seed

    def _estimate_crust_density(self):
        return estimate_crust_density_kg_m3(self.crust_composition)

    def _derive_planet_physics(self, seed=None):
        return derive_planet_physics(seed or self._current_seed_values(), self._estimate_crust_density())

    def _crust_classification(self):
        return classify_crust_type(self.crust_composition)

    def _reset_worldgen_seed_inputs(self):
        self.seed_input_buffers = {
            field_id: self._format_seed_input(value)
            for field_id, value in self.DEFAULT_SEED.items()
        }
        self.crust_composition = default_crust_composition()
        self.active_planet_template = "silicate_terrestrial"
        self.active_seed_field = "radius_earth"
        self.periodic_table_open = False
        self._clear_editor_hitboxes()

    def _reset_orbit_draft(self, clear_inputs=True):
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        self.selected_world_gen_planet_id = None
        self.planet_entity = None
        self.editor_stage = "crust"
        self._clear_editor_hitboxes()
        if clear_inputs:
            self.input_buffers = {"periapsis_au": "", "apoapsis_au": ""}
            self._recalculate_model()
        self._reset_worldgen_seed_inputs()

    def _resume_stage_for_planet(self, planet):
        if self._planet_is_gas_giant_candidate(planet):
            return "atmosphere"
        stage = str((planet or {}).get("world_gen_stage") or "").strip().lower()
        if stage in {"crust", "atmosphere", "regime", "terrain", "tectonics", "heightmap"}:
            return stage
        if planet.get("world_gen_complete"):
            return "heightmap"
        if not isinstance(planet.get("world_gen_seed"), dict):
            return "crust"
        if not isinstance(planet.get("atmosphere_model"), dict):
            return "atmosphere"
        atmosphere = planet.get("atmosphere_model") or {}
        if atmosphere.get("has_solid_surface") is False:
            return "atmosphere"
        if not isinstance(planet.get("interior_regime_model"), dict):
            return "regime"
        if not isinstance(planet.get("terrain_seed_model"), dict):
            return "terrain"
        if isinstance(planet.get("tectonic_model"), dict) and not isinstance(planet.get("heightmap_model"), dict):
            return "tectonics"
        return "heightmap"

    def _set_world_gen_progress(self, planet, stage, complete=False):
        if not isinstance(planet, dict):
            return
        stage = str(stage or "crust")
        tags = list(planet.get("tags") or [])
        for tag in list(tags):
            if tag.startswith("world_gen_stage_") or tag in {"world_gen_unfinished", "world_gen_complete"}:
                tags.remove(tag)
        tags.append("world_gen_complete" if complete else "world_gen_unfinished")
        if complete:
            planet["world_gen_complete"] = True
            planet["world_gen_stage"] = "complete"
            planet["world_gen_status_color"] = [92, 166, 126]
            tags.append("world_gen_stage_complete")
        else:
            planet["world_gen_complete"] = False
            planet["world_gen_stage"] = stage
            planet["world_gen_status_color"] = [210, 154, 74]
            tags.append(f"world_gen_stage_{stage}")
        has_material_palette = isinstance(planet.get("surface_palette"), dict) or isinstance(planet.get("atmospheric_material_model"), dict)
        if not has_material_palette and (
            not planet.get("display_color")
            or planet.get("display_color") in ([92, 148, 206], [210, 154, 74], [92, 166, 126])
        ):
            planet["display_color"] = planet["world_gen_status_color"]
        planet["tags"] = tags

    def _normalize_orbital_planet_fields(self, planet):
        if not isinstance(planet, dict):
            return planet
        planet["_dataset"] = "locations"
        planet["type"] = "location"
        planet["location_class"] = "planet"
        planet["location_role"] = "orbital_body"
        planet["system_role"] = "orbital_body"
        if not planet.get("star_system") and self.parent_system_id:
            planet["star_system"] = self.parent_system_id
        if not planet.get("parent_body") and planet.get("parent_location"):
            planet["parent_body"] = planet.get("parent_location")
        if not planet.get("parent_location") and planet.get("parent_body"):
            planet["parent_location"] = planet.get("parent_body")
        if not planet.get("parent_body") and self._primary_star_id():
            parent_star_id = self._primary_star_id()
            planet["parent_body"] = parent_star_id
            planet["parent_location"] = parent_star_id
        return planet

    def _mirror_and_persist_planet(self, planet):
        self._normalize_orbital_planet_fields(planet)
        mirror_location_sim_relations(planet)
        return self._persist_existing_location_entity(planet)

    def _derive_natural_material_model(self, seed=None, atmosphere=None, regime=None, terrain=None):
        seed = seed or self._current_seed_values()
        crust_type = self._crust_classification()
        planet_tags = derive_planet_material_tags(
            seed=seed,
            atmosphere=atmosphere,
            regime=regime,
            terrain=terrain,
            crust_type=crust_type,
        )
        return derive_natural_material_model(seed.get("crust_composition"), planet_tags)

    def _apply_atmospheric_materials(self, planet, atmosphere):
        atmospheric_material_model = derive_atmospheric_material_model(atmosphere)
        palette = atmospheric_band_palette(atmosphere)
        planet["atmospheric_material_model"] = atmospheric_material_model
        planet["atmospheric_materials"] = list(atmospheric_material_model.get("dominant_materials") or [])
        planet["atmosphere_bands"] = list(palette.get("bands") or [])
        planet["surface_palette"] = {
            "surface_color": list(palette.get("base_color") or [150, 160, 172]),
            "palette": list(palette.get("bands") or []),
            "source": "atmospheric_materials",
            "evidence": list(atmospheric_material_model.get("likely_materials") or [])[:5],
        }
        if palette.get("base_color"):
            planet["display_color"] = list(palette["base_color"])
        return atmospheric_material_model

    def _apply_surface_material_palette(self, planet, natural_material_model, atmosphere=None, terrain=None):
        palette = derive_planet_surface_palette(natural_material_model, atmosphere=atmosphere, terrain=terrain)
        planet["surface_palette"] = palette
        if palette.get("surface_color"):
            planet["display_color"] = list(palette["surface_color"])
        return palette

    def _apply_elemental_seed_palette(self, planet, seed):
        composition = crust_composition_from_seed({"crust_composition": seed.get("crust_composition")})
        element_profile = {}
        for group_name in ("major_elements", "trace_elements"):
            for element in composition.get(group_name) or []:
                if not isinstance(element, dict):
                    continue
                symbol = str(element.get("symbol") or "").strip()
                if not symbol:
                    continue
                try:
                    abundance = float(element.get("abundance_percent", 0.0) or 0.0)
                except (TypeError, ValueError):
                    abundance = 0.0
                element_profile[symbol] = max(element_profile.get(symbol, 0.0), abundance)
        palette = derive_planet_surface_palette({"element_profile": element_profile})
        palette["source"] = "crust_elements"
        planet["surface_palette"] = palette
        if palette.get("surface_color"):
            planet["display_color"] = list(palette["surface_color"])
        return palette

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

    def _derive_terrain_seed_model(self, seed=None, physics=None, atmosphere=None, regime=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        atmosphere = atmosphere or self._derive_atmosphere_model(seed, physics)
        regime = regime or self._derive_interior_regime_model(seed, physics, atmosphere)
        planet = planet or self._selected_planet_entity() or {}
        return derive_terrain_seed_model(
            seed=seed,
            physics=physics,
            atmosphere=atmosphere,
            regime=regime,
            planet_id=planet.get("id", ""),
            system_id=self.parent_system_id,
        )

    def _derive_heightmap_model(self, terrain=None, seed=None, physics=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        planet = planet or self._selected_planet_entity() or {}
        terrain = terrain or self._derive_terrain_seed_model(seed, physics, planet=planet)
        if isinstance(terrain, dict) and planet.get("simulated_geology_age_myr"):
            terrain = dict(terrain)
            terrain["simulated_age_myr"] = float(planet.get("simulated_geology_age_myr", 0.0) or 0.0)
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
        planet = planet or self._selected_planet_entity() or {}
        terrain = terrain or self._derive_terrain_seed_model(seed, physics, planet=planet)
        return derive_tectonic_model(
            terrain=terrain,
            seed=seed,
            physics=physics,
            planet_id=planet.get("id", ""),
        )

    def _derive_crater_model(self, terrain=None, seed=None, physics=None, planet=None):
        seed = seed or self._current_seed_values()
        physics = physics or self._derive_planet_physics(seed)
        planet = planet or self._selected_planet_entity() or {}
        terrain = terrain or self._derive_terrain_seed_model(seed, physics, planet=planet)
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
        self.crust_composition = add_abundant_trace_element(
            self.crust_composition,
            symbol,
            initial_abundance=trace_promotion_abundance(symbol),
        )
        after = [element.get("symbol") for element in self.crust_composition.get("major_elements", [])]
        self.periodic_table_open = False
        if before == after:
            self.commit_status = f"{symbol} is already explicit"
            return False
        self.commit_status = f"Added {symbol} ({trace_element_rarity(symbol)}) to explicit composition"
        return True

    def _random_float(self, rng, low, high):
        return low + (high - low) * rng.random()

    def _random_choice(self, rng, values):
        return values[int(rng.random() * len(values)) % len(values)]

    def _weighted_choice(self, rng, weighted_values):
        total = sum(max(0.0, float(weight)) for _value, weight in weighted_values)
        if total <= 0:
            return weighted_values[0][0]
        cursor = rng.random() * total
        for value, weight in weighted_values:
            cursor -= max(0.0, float(weight))
            if cursor <= 0:
                return value
        return weighted_values[-1][0]

    def _choose_planet_template(self, rng, mode):
        if mode == "gas_giant":
            return self._weighted_choice(rng, [("gas_giant", 0.68), ("ice_giant", 0.32)])
        if mode == "eccentric":
            return self._weighted_choice(
                rng,
                [
                    ("silicate_terrestrial", 0.24),
                    ("ocean_world", 0.18),
                    ("desiccated_former_ocean", 0.18),
                    ("cratered_airless", 0.18),
                    ("carbon_rich", 0.22),
                ],
            )
        return self._weighted_choice(
            rng,
            [
                ("silicate_terrestrial", 0.46),
                ("ocean_world", 0.20),
                ("desiccated_former_ocean", 0.18),
                ("cratered_airless", 0.16),
            ],
        )

    def _randomized_major_elements(self, rng, mode, template_id=None):
        template = self.PLANET_TEMPLATES.get(template_id or self.active_planet_template)
        base_rows = template.get("major_elements") if template else None
        base_elements = [
            {
                "symbol": symbol,
                "name": element_name(symbol),
                "abundance_percent": abundance,
            }
            for symbol, abundance in (base_rows or [])
        ] or default_crust_composition().get("major_elements", [])
        elements = []
        for element in base_elements:
            abundance = float(element.get("abundance_percent", 0.0))
            if mode == "gas_giant":
                factor = self._random_float(rng, 0.76, 1.28)
            elif mode == "eccentric":
                factor = self._random_float(rng, 0.35, 2.75)
            else:
                factor = self._random_float(rng, 0.82, 1.22)
            elements.append({
                "symbol": element.get("symbol"),
                "name": element.get("name"),
                "abundance_percent": max(0.01, abundance * factor),
            })

        if mode == "eccentric" and template_id not in {"gas_giant", "ice_giant"}:
            extra_pool = ["Ti", "Mn", "P", "S", "C", "Ni", "Cr"]
            for symbol in rng.sample(extra_pool, k=2):
                elements.append({
                    "symbol": symbol,
                    "name": element_name(symbol),
                    "abundance_percent": self._random_float(rng, 0.25, 4.5),
                })

        return crust_composition_from_seed({"crust_composition": {"major_elements": elements}})["major_elements"]

    def _weighted_trace_sample(self, rng, pool, count):
        available = list(dict.fromkeys(pool))
        selected = []
        while available and len(selected) < count:
            symbol = self._weighted_choice(rng, [(item, trace_element_weight(item)) for item in available])
            selected.append(symbol)
            available.remove(symbol)
        return selected

    def _randomized_trace_elements(self, rng, mode, template_id=None):
        if mode == "gas_giant" or template_id in {"gas_giant", "ice_giant"}:
            pool = ["C", "N", "O", "S", "Ne", "Ar", "Kr", "Xe", "P"]
            count = 3 + int(rng.random() * 3)
            high_by_rarity = {
                "common": 0.11,
                "uncommon": 0.045,
                "rare": 0.018,
                "very_rare": 0.006,
                "synthetic_or_transient": 0.001,
            }
            max_total = TRACE_RESERVE_PERCENT * 0.45
        elif mode == "eccentric":
            pool = [
                symbol for symbol in element_symbols_by_rarity("common", "uncommon", "rare", "very_rare")
                if symbol not in {"H", "He", "O", "Si", "Al", "Fe", "Ca", "Na", "K", "Mg"}
            ]
            count = 4 + int(rng.random() * 4)
            high_by_rarity = {
                "common": 0.18,
                "uncommon": 0.11,
                "rare": 0.045,
                "very_rare": 0.014,
                "synthetic_or_transient": 0.002,
            }
            max_total = TRACE_RESERVE_PERCENT * 0.82
        else:
            pool = [
                symbol for symbol in element_symbols_by_rarity("common", "uncommon", "rare")
                if symbol not in {"H", "He", "O", "Si", "Al", "Fe", "Ca", "Na", "K", "Mg"}
            ]
            count = 2 + int(rng.random() * 3)
            high_by_rarity = {
                "common": 0.08,
                "uncommon": 0.035,
                "rare": 0.012,
                "very_rare": 0.004,
                "synthetic_or_transient": 0.001,
            }
            max_total = TRACE_RESERVE_PERCENT * 0.35

        selected = self._weighted_trace_sample(rng, pool, count)
        traces = []
        for symbol in selected:
            rarity = trace_element_rarity(symbol)
            high = high_by_rarity.get(rarity, 0.02)
            traces.append({
                "symbol": symbol,
                "name": element_name(symbol),
                "rarity": rarity,
                "abundance_percent": round(self._random_float(rng, max(0.001, high * 0.08), high), 4),
            })
        total = sum(element["abundance_percent"] for element in traces)
        if total > max_total and total > 0:
            scale = max_total / total
            for element in traces:
                element["abundance_percent"] = round(element["abundance_percent"] * scale, 4)
        return traces

    def randomize_seed(self, mode="generic", rng=None):
        mode = "gas_giant" if mode == "gas_giant" else ("eccentric" if mode == "eccentric" else "generic")
        rng = rng or random.Random()
        template_id = self._choose_planet_template(rng, mode)
        template = self.PLANET_TEMPLATES.get(template_id, self.PLANET_TEMPLATES["silicate_terrestrial"])
        self.active_planet_template = template_id

        if mode == "gas_giant":
            numeric_ranges = {
                "radius_earth": (3.2, 11.8) if template_id == "gas_giant" else (2.8, 4.4),
                "core_radius_fraction": (0.02, 0.22),
                "crust_thickness_km": (0.2, 8.0),
                "angular_velocity_deg_per_hour": (18.0, 78.0),
                "water_fraction": template.get("water_range", (0.0, 0.35)),
            }
            volatile_options = template.get("volatile_options", ["dense"])
            tectonics_options = template.get("tectonics_options", ["inactive"])
            status = f"Generated {template.get('label', 'gas giant').lower()} seed"
        elif mode == "eccentric":
            numeric_ranges = {
                "radius_earth": (0.22, 2.6),
                "core_radius_fraction": (0.08, 0.82),
                "crust_thickness_km": (4.0, 145.0),
                "angular_velocity_deg_per_hour": (3.0, 95.0),
                "water_fraction": template.get("water_range", (0.0, 1.0)),
            }
            volatile_options = template.get("volatile_options", ["none", "thin", "dry", "wet", "earthlike", "dense"])
            tectonics_options = template.get("tectonics_options", ["inactive", "stagnant_lid", "mobile_lid", "episodic_lid", "heat_pipe", "unknown"])
            status = f"Generated eccentric {template.get('label', 'planet').lower()} seed"
        else:
            numeric_ranges = {
                "radius_earth": (0.75, 1.35),
                "core_radius_fraction": (0.42, 0.68),
                "crust_thickness_km": (18.0, 55.0),
                "angular_velocity_deg_per_hour": (9.0, 24.0),
                "water_fraction": template.get("water_range", (0.15, 0.78)),
            }
            volatile_options = template.get("volatile_options", ["dry", "wet", "earthlike"])
            tectonics_options = template.get("tectonics_options", ["stagnant_lid", "mobile_lid", "unknown"])
            status = f"Generated generic {template.get('label', 'planet').lower()} seed"

        for field_id, (low, high) in numeric_ranges.items():
            self.seed_input_buffers[field_id] = self._format_seed_input(
                round(self._random_float(rng, low, high), 4)
            )
        self.seed_input_buffers["volatile_inventory"] = self._random_choice(rng, volatile_options)
        self.seed_input_buffers["tectonics_mode"] = self._random_choice(rng, tectonics_options)
        self.seed_input_buffers["map_seed"] = f"{mode}-{rng.randrange(16 ** 8):08x}"
        self.crust_composition = {
            "major_elements": self._randomized_major_elements(rng, mode, template_id=template_id),
            "trace_reserve_percent": TRACE_RESERVE_PERCENT,
            "trace_elements": self._randomized_trace_elements(rng, mode, template_id=template_id),
        }
        self.periodic_table_open = False
        self.commit_status = status
        return True

    def _persist_existing_location_entity(self, entity):
        loader = getattr(self.world_model, "loader", None)
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        entity["_dataset"] = "locations"
        persisted = loader.persist_entity(entity)
        if persisted and hasattr(self.world_model, "mark_repository_changed"):
            self.world_model.mark_repository_changed()
        if persisted:
            self._append_planet_to_system_wiki(entity)
        return persisted

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
        planet["planetary_class"] = seed.get("planet_class", planet.get("planetary_class"))
        planet["world_gen_template"] = seed.get("planet_template")
        planet["mass_kg"] = seed["derived_planet_physics"]["mass_kg"]
        planet["radius_m"] = seed["derived_planet_physics"]["radius_m"]
        planet["rotation_period_hours"] = seed["derived_planet_physics"]["rotation_period_hours"]
        self._apply_elemental_seed_palette(planet, seed)

        self._set_world_gen_progress(planet, "atmosphere", complete=False)
        persisted = self._mirror_and_persist_planet(planet)
        seed_label = "Envelope" if self._seed_payload_is_gas_giant(seed) else "Crust"
        self.commit_status = "Saved planet seed" if persisted else "Seed saved in memory"
        self.editor_stage = "atmosphere"
        if persisted:
            self.commit_status = f"{seed_label} saved; atmosphere model ready"
        else:
            self.commit_status = f"{seed_label} saved in memory; atmosphere model ready"
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
        atmospheric_material_model = self._apply_atmospheric_materials(planet, atmosphere)
        planet["atmosphere_summary"] = {
            "status": "modeled",
            "atmosphere_class": atmosphere.get("atmosphere_class", "unknown"),
            "has_solid_surface": atmosphere.get("has_solid_surface", True),
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

        if atmosphere.get("has_solid_surface") is False:
            self._apply_gas_giant_envelope_fields(planet, atmosphere, atmospheric_material_model)
            self._set_world_gen_progress(planet, "atmosphere", complete=False)
            persisted = self._mirror_and_persist_planet(planet)
            self.editor_stage = "atmosphere"
            self.commit_status = "Gas giant atmosphere ready; complete worldgen" if persisted else "Gas giant ready in memory; complete worldgen"
            return True

        self._set_world_gen_progress(planet, "regime", complete=False)
        persisted = self._mirror_and_persist_planet(planet)
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

        self._set_world_gen_progress(planet, "terrain", complete=False)
        persisted = self._mirror_and_persist_planet(planet)
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

        if self._seed_payload_is_gas_giant(seed):
            atmosphere = self._derive_atmosphere_model(seed, seed["derived_planet_physics"])
            if atmosphere.get("has_solid_surface") is False:
                planet["world_gen_seed"] = seed
                planet["atmosphere_model"] = atmosphere
                planet["atmosphere_summary"] = {
                    "status": "modeled",
                    "atmosphere_class": atmosphere.get("atmosphere_class", "unknown"),
                    "has_solid_surface": False,
                    "surface_pressure_bar": atmosphere["surface_pressure_bar"],
                    "estimated_surface_temperature_k": atmosphere["estimated_surface_temperature_k"],
                    "dominant_gases": [
                        item["molecule"]
                        for item in atmosphere.get("composition", [])[:3]
                    ],
                }
                self._apply_gas_giant_envelope_fields(planet, atmosphere)
                self._set_world_gen_progress(planet, "atmosphere", complete=False)
                persisted = self._mirror_and_persist_planet(planet)
                self.editor_stage = "atmosphere"
                self.commit_status = "Gas giant envelope ready; complete worldgen" if persisted else "Gas giant envelope ready in memory; complete worldgen"
                return True

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
        natural_material_model = self._derive_natural_material_model(seed, atmosphere, regime, terrain)
        surface_palette = self._apply_surface_material_palette(planet, natural_material_model, atmosphere=atmosphere, terrain=terrain)
        canvas = terrain.get("map_canvas", {})
        planet["terrain_seed_model"] = terrain
        planet["natural_material_model"] = natural_material_model
        planet["natural_materials"] = list(natural_material_model.get("dominant_materials") or [])
        planet["map_generation_recipe"] = terrain.get("map_recipe", [])
        planet["map_layers"] = terrain.get("map_layers", [])
        planet["map_projection"] = canvas.get("projection", "equirectangular")
        planet["map_canvas_width_px"] = canvas.get("width_px", 2048)
        planet["map_canvas_height_px"] = canvas.get("height_px", 1024)
        if terrain.get("tectonics", {}).get("enabled"):
            tectonic_model = self._derive_tectonic_model(terrain, seed, physics, planet)
            tectonic_model = mature_tectonics_model(tectonic_model, terrain, cycles=4, million_years_per_cycle=45.0)
            planet["tectonic_model"] = tectonic_model
            planet.pop("crater_model", None)
            heightmap = self._derive_heightmap_model(terrain, seed, physics, planet)
            planet["heightmap_model"] = heightmap
            map_status = "tectonics_matured_heightmap_seeded"
            geology_status = "tectonics_matured_heightmap_seeded"
            self.editor_stage = "heightmap"
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
            "target_ice_fraction": terrain["hydrology"].get("target_ice_fraction", 0.0),
            "frozen_water_possible": terrain["hydrology"].get("frozen_water_possible", False),
            "drainage_enabled": terrain["hydrology"]["drainage_enabled"],
        }
        planet["materials_summary"] = {
            "status": "natural_materials_inferred",
            "catalog_version": natural_material_model.get("catalog_version"),
            "dominant_materials": list(natural_material_model.get("dominant_materials") or []),
            "likely_material_count": len(natural_material_model.get("likely_materials") or []),
            "surface_color": list(surface_palette.get("surface_color") or []),
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
            stage_tags.extend(["tectonic_plates_defined", "tectonics_advanced", "heightfield_seeded", "heightmap_seeded"])
            next_stage = "heightmap"
            complete = False
        else:
            stage_tags.extend(["crater_field_seeded", "heightfield_seeded", "heightmap_seeded"])
            next_stage = "heightmap"
            complete = False
        stage_tags.extend(natural_material_model.get("planet_tags") or [])
        stage_tags.append("natural_materials_inferred")
        for tag in stage_tags:
            if tag not in tags:
                tags.append(tag)
        planet["tags"] = tags

        self._set_world_gen_progress(planet, next_stage, complete=complete)
        persisted = self._mirror_and_persist_planet(planet)
        if terrain.get("tectonics", {}).get("enabled"):
            self.commit_status = "Matured tectonics; heightmap ready"
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

        advanced = mature_tectonics_model(tectonic_model, terrain, cycles=2, million_years_per_cycle=35.0)
        planet["tectonic_model"] = advanced
        planet.pop("crater_model", None)
        terrain_for_heightmap = dict(terrain)
        terrain_for_heightmap["simulated_age_myr"] = float(advanced.get("age_myr", 0.0) or 0.0)
        heightmap = derive_heightmap_model(
            terrain=terrain_for_heightmap,
            seed=seed,
            physics=seed["derived_planet_physics"],
            planet_id=planet.get("id", ""),
            tectonic_model=advanced,
        )
        heightmap["simulated_age_myr"] = terrain_for_heightmap["simulated_age_myr"]
        planet["heightmap_model"] = heightmap
        planet["simulated_geology_age_myr"] = terrain_for_heightmap["simulated_age_myr"]
        planet["map_status"] = "tectonics_advanced"
        planet["geology_summary"] = {
            "status": "tectonics_advanced",
            "tectonic_age_myr": advanced["age_myr"],
            "simulated_age_myr": terrain_for_heightmap["simulated_age_myr"],
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

        self._set_world_gen_progress(planet, "heightmap", complete=False)
        persisted = self._mirror_and_persist_planet(planet)
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
        current_age = 0.0
        if isinstance(planet.get("heightmap_model"), dict):
            current_age = float(planet["heightmap_model"].get("simulated_age_myr", 0.0) or 0.0)
        current_age = max(current_age, float(planet.get("simulated_geology_age_myr", 0.0) or 0.0))
        next_age = round(current_age + 25.0, 1)
        terrain = dict(terrain)
        terrain["simulated_age_myr"] = next_age
        tectonic_model = planet.get("tectonic_model") if isinstance(planet.get("tectonic_model"), dict) else None
        if isinstance(tectonic_model, dict):
            tectonic_model = advance_tectonics_model(tectonic_model, terrain, million_years=25.0)
            planet["tectonic_model"] = tectonic_model
            next_age = max(next_age, float(tectonic_model.get("age_myr", next_age) or next_age))
            terrain["simulated_age_myr"] = next_age
        heightmap = derive_heightmap_model(
            terrain=terrain,
            seed=seed,
            physics=seed["derived_planet_physics"],
            planet_id=planet.get("id", ""),
            tectonic_model=tectonic_model,
            crater_model=planet.get("crater_model") if isinstance(planet.get("crater_model"), dict) else None,
        )
        heightmap["simulated_age_myr"] = next_age
        planet["heightmap_model"] = heightmap
        planet["simulated_geology_age_myr"] = next_age
        if isinstance(planet.get("geology_summary"), dict):
            planet["geology_summary"]["elevation_range_m"] = [
                heightmap["min_elevation_m"],
                heightmap["max_elevation_m"],
            ]
            planet["geology_summary"]["simulated_age_myr"] = next_age
        self._set_world_gen_progress(planet, "heightmap", complete=False)
        persisted = self._mirror_and_persist_planet(planet)
        self.commit_status = f"Advanced heightmap to {next_age:.1f} Myr" if persisted else f"Advanced heightmap to {next_age:.1f} Myr in memory"
        return True

    def _heightmap_can_advance_tectonics(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            return False
        if planet.get("world_gen_complete"):
            return False
        if isinstance(planet.get("crater_model"), dict):
            return False
        if planet.get("map_status") == "crater_heightmap_seeded":
            return False
        tectonic_model = planet.get("tectonic_model")
        if isinstance(tectonic_model, dict) and tectonic_model.get("status") == "tectonics_advanced" and isinstance(planet.get("heightmap_model"), dict):
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
        return isinstance(tectonic_model, dict) and bool(tectonic_model.get("plates"))

    def _world_gen_can_finish(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            return False
        if planet.get("world_gen_complete"):
            return False
        if isinstance(planet.get("heightmap_model"), dict):
            return True
        atmosphere = planet.get("atmosphere_model")
        return isinstance(atmosphere, dict) and atmosphere.get("has_solid_surface") is False

    def _previous_stage_for_current_stage(self):
        return {
            "atmosphere": "crust",
            "regime": "atmosphere",
            "terrain": "regime",
            "tectonics": "terrain",
            "heightmap": "terrain",
        }.get(self.editor_stage)

    def _request_previous_worldgen_stage(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            return False
        previous = self._previous_stage_for_current_stage()
        if previous is None:
            self.pending_back_stage = "__exit_selected__"
            self.commit_status = "Back exits the selected planet and may discard unsaved inputs. Press Enter to confirm; Esc cancels."
            return True
        self.pending_back_stage = previous
        label = previous.replace("_", " ")
        self.commit_status = f"Back to {label} may discard later generated data. Press Enter to confirm; Esc cancels."
        return True

    def _confirm_previous_worldgen_stage(self):
        planet = self._selected_planet_entity()
        target = self.pending_back_stage
        if target == "__exit_selected__":
            self.pending_back_stage = None
            self._reset_orbit_draft(clear_inputs=False)
            self.commit_status = "Exited selected planet"
            return True
        if not isinstance(planet, dict) or not target:
            self.pending_back_stage = None
            return False
        if target == "crust":
            for key in (
                "atmosphere_model",
                "atmosphere_summary",
                "atmospheric_material_model",
                "atmospheric_materials",
                "atmosphere_bands",
                "interior_regime_model",
                "surface_process_model",
                "terrain_seed_model",
                "natural_material_model",
                "natural_materials",
                "tectonic_model",
                "crater_model",
                "heightmap_model",
                "map_generation_recipe",
                "map_layers",
                "hydrology_summary",
                "materials_summary",
            ):
                planet.pop(key, None)
        elif target == "atmosphere":
            for key in (
                "interior_regime_model",
                "surface_process_model",
                "terrain_seed_model",
                "natural_material_model",
                "natural_materials",
                "tectonic_model",
                "crater_model",
                "heightmap_model",
                "map_generation_recipe",
                "map_layers",
                "hydrology_summary",
                "materials_summary",
            ):
                planet.pop(key, None)
        elif target == "regime":
            for key in (
                "terrain_seed_model",
                "natural_material_model",
                "natural_materials",
                "tectonic_model",
                "crater_model",
                "heightmap_model",
                "map_generation_recipe",
                "map_layers",
                "hydrology_summary",
                "materials_summary",
            ):
                planet.pop(key, None)
        elif target == "terrain":
            for key in ("tectonic_model", "crater_model", "heightmap_model"):
                planet.pop(key, None)
            planet["map_status"] = "terrain_seeded"
        self.pending_back_stage = None
        self.editor_stage = target
        self._set_world_gen_progress(planet, target, complete=False)
        persisted = self._mirror_and_persist_planet(planet)
        self.commit_status = f"Returned to {target}" if persisted else f"Returned to {target} in memory"
        return True

    def _finish_world_gen(self):
        planet = self._selected_planet_entity()
        if not isinstance(planet, dict):
            self.commit_status = "Select a planet first"
            return False
        if not self._world_gen_can_finish():
            self.commit_status = "Complete the current worldgen stage first"
            return False
        self._set_world_gen_progress(planet, "complete", complete=True)
        persisted = self._mirror_and_persist_planet(planet)
        status = f"World generation complete: {planet.get('name', planet.get('id', 'planet'))}"
        self._reset_orbit_draft(clear_inputs=True)
        self.commit_status = status if persisted else f"{status} in memory"
        return True

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
        self._reset_orbit_draft(clear_inputs=True)
        self.commit_status = ""

    def _commit_named_planet(self):
        existing_planet = self._find_existing_planet_entity(self.planet_name_buffer)
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
        self.editor_stage = self._resume_stage_for_planet(planet)
        self.planet_name_prompt_active = False
        self.planet_name_buffer = ""
        self.pending_orbit_radius_au = None
        self.orbit_pick_stage = "first"
        action = "Linked planet" if existing_planet is planet else "Created planet"
        self.commit_status = f"{action}: {planet['name']}" if persisted else f"{action} in memory; save failed"
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
            "planet_template": self.active_planet_template,
            "planet_template_label": self.PLANET_TEMPLATES.get(self.active_planet_template, {}).get("label", self.active_planet_template),
            "planet_class": self.PLANET_TEMPLATES.get(self.active_planet_template, {}).get("planet_class", "terrestrial"),
            "derived_planet_physics": self._derive_planet_physics(),
            "periodic_table_open": self.periodic_table_open,
            "periodic_table_rows": PERIODIC_TABLE_ROWS,
            "editor_stage": self.editor_stage,
            "atmosphere_model": self._derive_atmosphere_model(),
            "interior_regime_model": self._derive_interior_regime_model(),
            "terrain_seed_model": terrain_model,
            "natural_material_model": (
                selected_planet.get("natural_material_model")
                if isinstance(selected_planet, dict) and isinstance(selected_planet.get("natural_material_model"), dict)
                else self._derive_natural_material_model(terrain=terrain_model)
            ),
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

            if self.pending_back_stage:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._confirm_previous_worldgen_stage()
                    return
                if event.key == pygame.K_ESCAPE:
                    self.pending_back_stage = None
                    self.commit_status = "Back cancelled"
                    return

            if self._selected_planet_entity() is not None:
                if event.key == pygame.K_ESCAPE:
                    if self.periodic_table_open:
                        self.periodic_table_open = False
                    else:
                        self._reset_orbit_draft(clear_inputs=False)
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

        selected_planet = self._selected_planet_entity()
        if self.control_panel_rect is not None and self.control_panel_rect.collidepoint(screen_pos):
            if selected_planet is None:
                if (
                    self.formation_theory_button_rect is not None
                    and self.formation_theory_button_rect.collidepoint(screen_pos)
                ):
                    self._add_formation_theory_planets()
                return
            if selected_planet is None and self.editor_stage != "crust":
                self._reset_orbit_draft(clear_inputs=False)
                return
            if (
                self.world_gen_complete_button_rect is not None
                and self.world_gen_complete_button_rect.collidepoint(screen_pos)
            ):
                self._finish_world_gen()
                return
            if (
                self.world_gen_back_button_rect is not None
                and self.world_gen_back_button_rect.collidepoint(screen_pos)
            ):
                self._request_previous_worldgen_stage()
                return
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
            if (
                self.crust_random_generic_button_rect is not None
                and self.crust_random_generic_button_rect.collidepoint(screen_pos)
            ):
                self.randomize_seed("generic")
                return
            if (
                self.crust_random_eccentric_button_rect is not None
                and self.crust_random_eccentric_button_rect.collidepoint(screen_pos)
            ):
                self.randomize_seed("eccentric")
                return
            if (
                self.crust_random_gas_giant_button_rect is not None
                and self.crust_random_gas_giant_button_rect.collidepoint(screen_pos)
            ):
                self.randomize_seed("gas_giant")
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

        if self.selected_world_gen_planet_id is not None or self.editor_stage != "crust":
            self._reset_orbit_draft(clear_inputs=False)
        if self.orbit_pick_stage == "second" and self.pending_orbit_radius_au is not None:
            self._set_elliptical_orbit_from_radius(radius_au)
            return

        self._set_circular_orbit_from_radius(radius_au)

    def handle_pointer_motion(self, event, camera, screen_pos):
        if self.active_crust_slider_symbol:
            self._set_crust_abundance_from_screen_x(self.active_crust_slider_symbol, screen_pos[0])
