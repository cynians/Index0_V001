MAP_SURFACE_FIELDS = (
    "bounds",
    "geometry",
    "map_canvas_width_px",
    "map_canvas_height_px",
    "map_status",
    "map_generation_recipe",
    "map_layers",
    "heightmap_model",
    "material_heatmap_model",
)

ORBITAL_LOCATION_CLASSES = {
    "star",
    "planet",
    "moon",
    "dwarf_planet",
    "asteroid",
    "comet",
    "space_station",
    "station",
    "spacecraft",
    "orbital_spacecraft",
    "planetary_spacecraft",
    "system_spacecraft",
    "interstellar_spacecraft",
}


def _entity_id(entity):
    return str(entity.get("id") or "").strip()


def _dataset_name(entity):
    return str(entity.get("_dataset") or entity.get("type") or "").strip()


def _location_class(entity):
    return str(entity.get("location_class") or "").strip()


def _body_class(entity):
    return str(entity.get("body_class") or entity.get("location_class") or "").strip()


def _has_map_surface(entity):
    return any(bool(entity.get(field)) for field in MAP_SURFACE_FIELDS)


def _has_structural_parent_hint(entity):
    return any(bool(entity.get(field)) for field in ("parent_location", "parent_entity", "parent_body", "parents"))


def _is_location(entity):
    return (
        _dataset_name(entity) == "locations"
        or entity.get("type") == "location"
        or bool(entity.get("location_class"))
    )


def _is_star_system(entity):
    return entity.get("system_role") == "star_system" or _location_class(entity) in {
        "star_system",
        "stellar_system",
    }


def _is_orbital_body(entity):
    return entity.get("system_role") == "orbital_body" or _location_class(entity) in ORBITAL_LOCATION_CLASSES


def _option(mode, label, reason, priority, entity_id):
    return {
        "mode": mode,
        "label": label,
        "reason": reason,
        "priority": priority,
        "action": {
            "id": "knowledge_launch_mode",
            "entity_id": entity_id,
            "launch_mode": mode,
        },
    }


class LaunchAffordanceResolver:
    """
    Describes current simulation launch affordances for repository entities.

    This is intentionally a hardcoded bridge over the simulations that exist
    today. It gives cards and navigation one shared vocabulary without turning
    the future simulation matrix into a premature framework.
    """

    def options_for_entity(self, entity):
        if not isinstance(entity, dict):
            return []

        entity_id = _entity_id(entity)
        if not entity_id:
            return []

        dataset_name = _dataset_name(entity)
        location_class = _location_class(entity)
        body_class = _body_class(entity)
        options = []

        if _is_location(entity):
            if _is_star_system(entity):
                options.append(_option("space", "Space", "Open the star-system orbital view.", 100, entity_id))
                options.append(_option("world_gen", "World Gen", "Create or edit generated planets in this system.", 80, entity_id))
                return options

            if location_class == "building":
                options.append(_option("building", "Building", "Open the building/interior workspace.", 100, entity_id))
                return options

            if location_class == "room":
                options.append(_option("building", "Building", "Open this room through its parent building.", 100, entity_id))
                return options

            if location_class in {"space_station", "station"}:
                if entity.get("star_system"):
                    options.append(_option("space", "Space", "Open the station in its orbital context.", 110, entity_id))
                options.append(_option("building", "Interior", "Open the station interior and room map.", 100, entity_id))
                options.append(_option("vehicle", "Design", "Open component and systems design.", 90, entity_id))
                if _has_map_surface(entity):
                    options.append(_option("map", "Map", "Open the station map workspace.", 80, entity_id))
                return options

            if _is_orbital_body(entity):
                star_system_id = entity.get("star_system")
                if body_class == "planet":
                    if star_system_id:
                        options.append(_option("space", "Space", "Open this planet in local orbital context.", 100, entity_id))
                    elif entity.get("location_entity"):
                        options.append(_option("map", "Map", "Open the linked surface location.", 90, entity_id))

                    options.append(_option("world_gen", "World Gen", "Generate, resume, or inspect this planet.", 85, entity_id))
                    if _has_map_surface(entity):
                        options.append(_option("map", "Map", "Open the planet surface/map workspace.", 75, entity_id))
                    return options

                if star_system_id:
                    options.append(_option("space", "Space", "Open the parent star-system orbital view.", 100, entity_id))
                if entity.get("location_entity") or _has_map_surface(entity):
                    options.append(_option("map", "Map", "Open the linked map/location workspace.", 80, entity_id))
                return options

            has_person_site_context = bool(
                entity.get("person_simulation_enabled")
                or entity.get("simulation_points")
                or entity.get("resident_people")
                or entity.get("present_pops")
                or entity.get("visitor_scenarios")
            )
            if _has_map_surface(entity):
                options.append(_option("map", "Map", "Open the authored location map workspace.", 100, entity_id))
                if has_person_site_context:
                    options.append(_option("site_people", "Site Simulation", "Run people and pop representatives on this authored map.", 95, entity_id))
            elif _has_structural_parent_hint(entity):
                options.append(_option("place_parent", "Place on Parent", "This map has not been defined yet.", 100, entity_id))
            else:
                options.append(_option("map", "Map", "Open the location map workspace.", 100, entity_id))
                if has_person_site_context:
                    options.append(_option("site_people", "Site Simulation", "Run people and pop representatives at this location.", 95, entity_id))
            if entity.get("biosphere_entity_id"):
                options.append(_option("biosphere", "Biosphere", "Open the Biosphere overlaying this location.", 90, entity_id))
            return options

        if dataset_name == "vehicles":
            return [_option("vehicle", "Design", "Open the vehicle design workspace.", 100, entity_id)]

        if dataset_name == "people" or entity.get("type") == "person":
            return [_option("person", "Person", "Open the person dossier simulation.", 100, entity_id)]

        if dataset_name == "pops" or entity.get("type") == "pop":
            return [_option("pop", "Pop", "Open the population composition view.", 100, entity_id)]

        if dataset_name == "formations" or entity.get("type") == "formation":
            return [
                _option("formation", "Formation Sim", "Open the formation hierarchy and organization view.", 100, entity_id),
                _option("formation_create", "Add subordinate", "Create a formation or blueprint under this formation.", 90, entity_id),
            ]

        if dataset_name in {"cladistics", "species"} or entity.get("type") in {"cladistics", "species"}:
            return [_option("phylogeny", "Phylogeny", "Open the phylogeny simulation.", 100, entity_id)]

        if dataset_name == "systems":
            if entity.get("system_role") == "star_system":
                return [_option("space", "Space", "Open the star-system orbital view.", 100, entity_id)]
            if entity.get("system_role") == "orbital_body":
                options.append(_option("space", "Space", "Open the orbital context.", 100, entity_id))
                if entity.get("location_entity"):
                    options.append(_option("map", "Map", "Open the linked surface location.", 80, entity_id))
                return options

        return []

    def default_mode_for_entity(self, entity):
        options = self.options_for_entity(entity)
        if not options:
            return None

        if _is_location(entity) and _is_orbital_body(entity) and _body_class(entity) == "planet":
            if not entity.get("star_system") and _has_map_surface(entity):
                return "map"
            return "space" if any(option["mode"] == "space" for option in options) else options[0]["mode"]

        return options[0]["mode"]
