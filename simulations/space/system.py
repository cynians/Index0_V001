from pathlib import Path
import math
import yaml


class CelestialSystem:
    """
    Space-system container.

    Responsibilities:
    * store instantiated space objects
    * expose renderer-safe entries
    * update all objects
    * populate itself from the 'systems' dataset in WorldModel
    """

    def __init__(self):
        self._entries = []
        self.objects_by_id = {}

    EARTH_RADIUS_M = 6_371_000.0
    EARTH_MAP_WIDTH_UNITS = 4000.0

    def _project_root(self):
        return Path(__file__).resolve().parents[2]

    def _locations_file_path(self):
        return self._project_root() / "entries" / "locations.yaml"

    def _systems_file_path(self):
        return self._project_root() / "entries" / "systems.yaml"

    def _generated_location_id_for_body(self, body_entity):
        body_id = body_entity.get("id", "")
        if body_id.startswith("body_"):
            return "planet_" + body_id[len("body_"):]
        return f"planet_{body_id}"

    def _map_size_from_radius(self, radius_m):
        radius_m = float(radius_m or self.EARTH_RADIUS_M)
        map_width_units = max(
            256,
            int(round(radius_m * self.EARTH_MAP_WIDTH_UNITS / self.EARTH_RADIUS_M))
        )
        map_height_units = max(128, int(round(map_width_units / 2)))
        return map_width_units, map_height_units

    def _canvas_size_for_map_width(self, map_width_units):
        if map_width_units <= 2500:
            return 2048, 1024
        if map_width_units <= 5000:
            return 4096, 2048
        if map_width_units <= 9000:
            return 8192, 4096
        return 16384, 8192

    def build_generated_location_entry(self, body_entity):
        location_id = self._generated_location_id_for_body(body_entity)
        body_name = body_entity.get("name", location_id)
        radius_m = float(body_entity.get("radius_m", self.EARTH_RADIUS_M) or self.EARTH_RADIUS_M)

        map_width_units, map_height_units = self._map_size_from_radius(radius_m)
        canvas_width_px, canvas_height_px = self._canvas_size_for_map_width(map_width_units)

        half_w = map_width_units // 2
        half_h = map_height_units // 2

        return {
            "id": location_id,
            "pretty_name": body_name,
            "name": body_name,
            "type": "location",
            "location_class": "planet",
            "location_role": "planetary_root",
            "coords": {
                "type": "point",
                "x": 0,
                "y": 0,
            },
            "bounds": {
                "type": "bbox",
                "min_x": -half_w,
                "max_x": half_w,
                "min_y": -half_h,
                "max_y": half_h,
            },
            "derived_from_system_body": body_entity.get("id"),
            "map_projection": "equirectangular",
            "map_status": "empty_generated",
            "map_canvas_width_px": canvas_width_px,
            "map_canvas_height_px": canvas_height_px,
            "population": {
                "y0": 0,
            },
            "start_year": 0,
        }

    def _load_yaml_list(self, path):
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        if not isinstance(data, list):
            raise ValueError(f"Expected list YAML in {path}")
        return data

    def _write_yaml_list(self, path, data):
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    def _append_generated_location_entry(self, path, entry):
        """
        Append one generated location entry to locations.yaml with readable spacing
        and a visual header, instead of rewriting the whole file.

        Format:
        * two leading newlines before the block
        * one header comment with id and pretty name
        * YAML block for a single list item
        """
        entry_id = entry.get("id", "unknown_location")
        entry_name = entry.get("pretty_name") or entry.get("name") or entry_id
        header = f"#----------{entry_id}----{entry_name}-----------"

        yaml_block = yaml.safe_dump(
            [entry],
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).rstrip()

        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(header)
            f.write("\n")
            f.write(yaml_block)
            f.write("\n")

    def _append_generated_location_entry(self, path, entry):
        """
        Append one generated location entry to locations.yaml while preserving
        existing file layout better than rewriting the full YAML list.

        Format:
        * one blank line before the generated block
        * one header comment containing id and name
        * the generated YAML entry block
        """
        entry_id = entry.get("id", "unknown_location")
        entry_name = entry.get("name") or entry.get("pretty_name") or entry_id
        header = f"#----------{entry_id}----{entry_name}-----------"

        yaml_block = yaml.safe_dump(
            [entry],
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).rstrip()

        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(header)
            f.write("\n")
            f.write(yaml_block)
            f.write("\n")

    def ensure_location_anchor_for_body_entity(self, body_entity, world_model=None):
        """
        Ensure that a persistent location root exists for the given orbital body.

        Returns:
            tuple(location_id, created_new_location)
        """
        if not body_entity:
            return None, False

        existing_location_id = body_entity.get("location_entity")
        if existing_location_id:
            if world_model is None or world_model.get_entity(existing_location_id) is not None:
                return existing_location_id, False

        generated_entry = self.build_generated_location_entry(body_entity)
        generated_location_id = generated_entry["id"]

        locations_path = self._locations_file_path()
        systems_path = self._systems_file_path()

        locations_data = self._load_yaml_list(locations_path)
        systems_data = self._load_yaml_list(systems_path)

        location_exists = any(entry.get("id") == generated_location_id for entry in locations_data)

        if not location_exists:
            locations_data.append(generated_entry)
            self._append_generated_location_entry(locations_path, generated_entry)

        body_id = body_entity.get("id")
        systems_changed = False

        for entry in systems_data:
            if entry.get("id") != body_id:
                continue

            if entry.get("location_entity") != generated_location_id:
                entry["location_entity"] = generated_location_id
                systems_changed = True
            break

        if systems_changed:
            self._write_yaml_list(systems_path, systems_data)

        return generated_location_id, (not location_exists)

    def get_source_entity_for_space_object(self, space_object):
        for entry in self._entries:
            if entry["object"] is space_object:
                return entry.get("source_entity")
        return None

    def add(self, obj, name=None, layers=None, source_entity=None):
        """
        Register a space object in the system.
        """
        entry = {
            "object": obj,
            "name": name or obj.name,
            "layers": layers,
            "entity_id": getattr(obj, "entity_id", None),
            "source_entity": source_entity,
        }

        self._entries.append(entry)

        if source_entity is not None:
            source_entity_id = source_entity.get("id")
            if source_entity_id:
                self.objects_by_id[source_entity_id] = obj

    def get_entries(self):
        """
        Return all system entries with minimal, renderer-safe structure.
        """
        entries = []

        for entry in self._entries:
            obj = entry["object"]

            entries.append({
                "object": obj,
                "name": entry["name"],
                "layers": entry["layers"],
                "entity_id": getattr(obj, "entity_id", None)
            })

        return entries

    def _iter_active_entities(self, world_model, year):
        """
        Yield active entities from the world model.

        This keeps the loader resilient to small API differences.
        """
        if hasattr(world_model, "get_active_entities"):
            for entity in world_model.get_active_entities(year):
                yield entity
            return

        if hasattr(world_model, "entities_active") and hasattr(world_model, "get_entity"):
            for entity_id in world_model.entities_active(year):
                entity = world_model.get_entity(entity_id)
                if entity:
                    yield entity
            return

        raise AttributeError("WorldModel has no supported active-entity API.")

    def _get_active_system_entities(self, world_model, year, root_system_id):
        """
        Return active orbital-body entries for the selected star system.
        """
        active_entities = list(self._iter_active_entities(world_model, year))

        return [
            entity for entity in active_entities
            if entity.get("_dataset") == "systems"
            and entity.get("type") == "system"
            and entity.get("system_role") == "orbital_body"
            and entity.get("star_system") == root_system_id
        ]

    def _coerce_color(self, value, fallback=(180, 180, 180)):
        """
        Convert entry display_color data into an RGB tuple.
        """
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return fallback

        try:
            return (
                int(value[0]),
                int(value[1]),
                int(value[2]),
            )
        except (TypeError, ValueError):
            return fallback

    def _create_layers_for_entity(self, entity):
        """
        Create a minimal MapLayerStack from physical body size and display color.
        """
        from simulations.map.map_layers import MapLayerStack

        radius_m = float(entity.get("radius_m", 1.0) or 1.0)
        diameter_m = max(radius_m * 2.0, 1.0)
        color = self._coerce_color(entity.get("display_color"))

        stack = MapLayerStack(radius_m * 2.2)
        stack.add_layer({
            "name": "surface",
            "color": color,
            "x": 0.0,
            "y": 0.0,
            "size": diameter_m,
        })

        return stack

    def _create_root_object(self, entity):
        """
        Create a root body with no orbital parent.
        """
        from simulations.space.object import SpaceObject

        entity_id = entity.get("location_entity")

        obj = SpaceObject(
            name=entity.get("name", entity.get("id")),
            mass=float(entity.get("mass_kg", 0.0) or 0.0),
            position=(0.0, 0.0),
            entity_id=entity_id
        )
        obj.source_system_entity_id = entity.get("id")
        return obj

    def _create_orbiting_object(self, entity, parent_obj):
        """
        Create a body orbiting an already-instantiated parent body.
        """
        from simulations.space.object import SpaceObject
        from simulations.space.orbit import KeplerOrbit

        entity_id = entity.get("location_entity")

        orbit = KeplerOrbit(
            parent=parent_obj,
            a=float(entity.get("semi_major_axis_m", 0.0) or 0.0),
            e=float(entity.get("eccentricity", 0.0) or 0.0),
            M0=float(entity.get("mean_anomaly_deg_at_epoch", 0.0) or 0.0),
        )

        obj = SpaceObject(
            name=entity.get("name", entity.get("id")),
            mass=float(entity.get("mass_kg", 0.0) or 0.0),
            orbit=orbit,
            entity_id=entity_id
        )
        obj.source_system_entity_id = entity.get("id")
        return obj

    def populate_from_world_model(self, world_model, year, root_system_id):
        """
        Populate the celestial system from active entries in the 'systems' dataset.

        Expected entry shape:
        * type: system
        * system_role: orbital_body
        * star_system: <root system id>
        """
        self._entries = []
        self.objects_by_id = {}

        bodies = self._get_active_system_entities(world_model, year, root_system_id)

        if not bodies:
            return

        pending = {entity["id"]: entity for entity in bodies}
        stalled_last_round = False

        while pending:
            created_any = False

            for entity_id in list(pending.keys()):
                entity = pending[entity_id]
                parent_body_id = entity.get("parent_body")

                if not parent_body_id:
                    obj = self._create_root_object(entity)
                    layers = self._create_layers_for_entity(entity)
                    self.add(
                        obj,
                        name=entity.get("name"),
                        layers=layers,
                        source_entity=entity
                    )
                    del pending[entity_id]
                    created_any = True
                    continue

                parent_obj = self.objects_by_id.get(parent_body_id)
                if parent_obj is None:
                    continue

                obj = self._create_orbiting_object(entity, parent_obj)
                layers = self._create_layers_for_entity(entity)
                self.add(
                    obj,
                    name=entity.get("name"),
                    layers=layers,
                    source_entity=entity
                )
                del pending[entity_id]
                created_any = True

            if created_any:
                stalled_last_round = False
                continue

            if stalled_last_round:
                unresolved_ids = ", ".join(sorted(pending.keys()))
                raise ValueError(
                    f"Could not resolve orbital parents in systems dataset: {unresolved_ids}"
                )

            stalled_last_round = True

    def update(self, dt):
        """
        Update all space objects.
        """
        objects = [entry["object"] for entry in self._entries]

        for obj in objects:
            obj.update(dt, attractors=objects)