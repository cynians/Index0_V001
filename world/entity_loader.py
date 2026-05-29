import json
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class EntityLoader:
    """
    Loads entity datasets from the entries directory.

    Supported formats
    -----------------
    JSON / YAML

    Dataset structure
    -----------------
    Each dataset file contains a list of entities:

    - id: entity_id
      name: ...
      type: ...
    """

    CORE_DEFAULTS = {
        "description": "",
        "notes": "",
        "wiki_entry": "",
        "card_image": "",
        "design_image": "",
        "card_image_front": "",
        "card_image_side": "",
        "card_image_top": "",
        "image_path": "",
        "image": "",
        "tags": [],
        "start_year": None,
        "end_year": None,
        "derived_from": [],
        "parents": [],
        "related": [],
        "offspring": [],
        "placeholders": [],
        "entry_status": "",
        "media_layers": {},
    }
    IDEA_DEFAULTS = {
        "description": "",
        "notes": "",
        "wiki_entry": "",
        "tags": [],
        "start_year": None,
        "end_year": None,
        "derived_from": [],
        "parents": [],
        "related": [],
        "offspring": [],
        "placeholders": [],
        "entry_status": "",
    }
    LEGACY_IDEA_FIELDS = {
        "idea_class",
        "related_entities",
        "parent_entity",
        "source",
        "decision_status",
        "card_image",
        "design_image",
        "card_image_front",
        "card_image_side",
        "card_image_top",
        "image_path",
        "image",
        "derived_from_ideas",
        "parent_ideas",
        "related_ideas",
        "media_layers",
    }
    CORE_RELATION_RENAMES = {
        "derived_from_ideas": "derived_from",
        "parent_ideas": "parents",
        "related_ideas": "related",
    }

    def __init__(self, entries_directory=None, auto_save_normalized=False):

        if entries_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            entries_directory = project_root / "entries"

        self.entries_directory = Path(entries_directory)
        self.auto_save_normalized = auto_save_normalized

        self.datasets = {}
        self.entities = {}
        self.entity_aliases = {}
        self.edges = {}
        self._dataset_file_records = []

        self.refresh()

    # --------------------------------------------------

    def _is_blank_value(self, value):
        return value is None or value == "" or value == []

    def _copy_missing_fields(self, target, source, fields):
        for field in fields:
            if field not in source:
                continue
            if field not in target or self._is_blank_value(target.get(field)):
                target[field] = source.get(field)

    def _converted_system_location_class(self, entity):
        system_role = entity.get("system_role")
        if system_role == "star_system":
            return entity.get("system_class") or "star_system"
        if system_role == "orbital_body":
            return entity.get("body_class") or "orbital_body"
        return entity.get("system_class") or entity.get("body_class") or "system"

    def _convert_system_entity_to_location(self, entity):
        converted = dict(entity)
        converted["_legacy_dataset"] = converted.get("_dataset", "systems")
        converted["_dataset"] = "locations"
        converted["type"] = "location"
        if not converted.get("location_class"):
            converted["location_class"] = self._converted_system_location_class(entity)
        if not converted.get("location_role"):
            converted["location_role"] = entity.get("system_role") or "system"
        return converted

    def _fold_system_entities_into_locations(self):
        """
        Present legacy systems.yaml rows as location-class entries.

        Orbital bodies with an explicit location_entity are merged into that
        canonical location so planets do not appear twice in the repository
        browser. Bodies without a map/location anchor remain visible as
        location entries using their legacy id.
        """
        system_entities = self.datasets.get("systems")
        if not system_entities:
            return

        location_entities = self.datasets.setdefault("locations", [])
        location_by_id = {
            entity.get("id"): entity
            for entity in location_entities
            if isinstance(entity, dict) and entity.get("id")
        }

        system_fields = [
            "system_role",
            "system_class",
            "star_system",
            "body_class",
            "parent_body",
            "location_entity",
            "mass_kg",
            "radius_m",
            "semi_major_axis_m",
            "eccentricity",
            "inclination_deg",
            "longitude_of_ascending_node_deg",
            "argument_of_periapsis_deg",
            "mean_anomaly_deg_at_epoch",
            "display_color",
        ]

        for system_entity in list(system_entities):
            if not isinstance(system_entity, dict):
                continue

            system_id = system_entity.get("id")
            converted = self._convert_system_entity_to_location(system_entity)
            canonical_id = system_entity.get("location_entity")

            if canonical_id and canonical_id in location_by_id:
                canonical = location_by_id[canonical_id]
                self._copy_missing_fields(canonical, converted, system_fields)
                if not canonical.get("location_class"):
                    canonical["location_class"] = converted.get("location_class")
                if not canonical.get("location_role"):
                    canonical["location_role"] = converted.get("location_role")
                if not canonical.get("derived_from_system_body") and system_id:
                    canonical["derived_from_system_body"] = system_id
                if system_id:
                    canonical["legacy_system_entity_id"] = system_id
                    self.entity_aliases[system_id] = canonical_id
                continue

            if converted.get("id") in location_by_id:
                canonical = location_by_id[converted["id"]]
                self._copy_missing_fields(canonical, converted, system_fields)
                if not canonical.get("location_class"):
                    canonical["location_class"] = converted.get("location_class")
                if not canonical.get("location_role"):
                    canonical["location_role"] = converted.get("location_role")
                continue

            location_entities.append(converted)
            if converted.get("id"):
                location_by_id[converted["id"]] = converted

        self.datasets.pop("systems", None)

    def _ensure_standard_relations(self, entity, dataset_name=None):
        changed = False

        is_species = dataset_name == "species" or entity.get("type") == "species"
        if is_species:
            pretty_name = str(entity.get("pretty_name") or "").strip()
            legacy_name = str(entity.get("name") or "").strip()

            if "common_name" not in entity:
                if " - " in pretty_name:
                    entity["common_name"] = pretty_name.split(" - ", 1)[0].strip()
                elif pretty_name and pretty_name != entity.get("id"):
                    entity["common_name"] = pretty_name
                else:
                    entity["common_name"] = ""
                changed = True

            if "binomial_name" not in entity:
                if legacy_name:
                    entity["binomial_name"] = legacy_name
                elif " - " in pretty_name:
                    entity["binomial_name"] = pretty_name.split(" - ", 1)[1].strip()
                else:
                    entity["binomial_name"] = ""
                changed = True

        if not is_species and "pretty_name" not in entity:
            entity["pretty_name"] = entity.get("name") or entity.get("id") or ""
            changed = True

        if not is_species and "name" not in entity:
            entity["name"] = entity.get("pretty_name") or entity.get("id") or ""
            changed = True

        for old_field, new_field in self.CORE_RELATION_RENAMES.items():
            if old_field not in entity:
                continue
            old_value = entity.get(old_field)
            new_value = entity.get(new_field)
            if new_value in (None, "", []):
                entity[new_field] = old_value
            elif isinstance(new_value, list) and isinstance(old_value, list):
                for item in old_value:
                    if item not in new_value:
                        new_value.append(item)
            entity.pop(old_field, None)
            changed = True

        is_idea = dataset_name == "ideas" or entity.get("type") == "idea"
        defaults = self.IDEA_DEFAULTS if is_idea else self.CORE_DEFAULTS

        for field, default_value in defaults.items():
            if field not in entity:
                if isinstance(default_value, list):
                    entity[field] = list(default_value)
                elif isinstance(default_value, dict):
                    entity[field] = dict(default_value)
                else:
                    entity[field] = default_value
                changed = True

        if "child_ideas" in entity:
            entity.pop("child_ideas", None)
            changed = True

        if is_idea:
            for field in self.LEGACY_IDEA_FIELDS:
                if field in entity:
                    entity.pop(field, None)
                    changed = True

        return changed

    def _serializable_data(self, data):
        cleaned = []

        for entity in data:
            if not isinstance(entity, dict):
                cleaned.append(entity)
                continue

            cleaned.append({
                key: value
                for key, value in entity.items()
                if not str(key).startswith("_")
            })

        return cleaned

    def _save_dataset_file(self, file, data):
        data = self._serializable_data(data)

        if file.suffix.lower() in (".yaml", ".yml"):
            with file.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
            return

        with file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def load_datasets(self):
        """
        Load all entity datasets from the entries directory.

        Behavior
        --------
        * Recurses through subdirectories under entries/
        * Keeps top-level file behavior compatible with the old loader
        * Treats files inside entries/locations/ as one logical dataset named
          'locations' so location entries can be split across multiple files
          without breaking existing world queries
        """
        self.datasets = {}
        self.entity_aliases = {}
        self._dataset_file_records = []

        if not self.entries_directory.exists():
            logger.warning("Entries path does not exist: %s", self.entries_directory)
            return

        files = sorted(
            [
                p for p in self.entries_directory.rglob("*")
                if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".json")
            ]
        )

        for file in files:
            rel_parts = file.relative_to(self.entries_directory).parts

            # Compatibility rule:
            # entries/locations/*.yaml -> one logical dataset named "locations"
            if len(rel_parts) >= 2 and rel_parts[0] == "locations":
                dataset_name = "locations"
            else:
                dataset_name = file.stem

            try:
                if file.suffix.lower() in (".yaml", ".yml"):
                    with file.open("r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or []
                else:
                    with file.open("r", encoding="utf-8") as f:
                        data = json.load(f) or []

                if not isinstance(data, list):
                    logger.warning("Dataset file is not a list: %s", file)
                    continue

                changed = False
                for entity in data:
                    if isinstance(entity, dict):
                        changed = self._ensure_standard_relations(entity, dataset_name=dataset_name) or changed

                self._dataset_file_records.append({
                    "file": file,
                    "data": data,
                    "changed": changed,
                })

                if dataset_name not in self.datasets:
                    self.datasets[dataset_name] = []

                for entity in data:
                    if isinstance(entity, dict):
                        entity["_dataset"] = dataset_name
                        self.datasets[dataset_name].append(entity)

                logger.debug(
                    "Loaded dataset %s from %s | entities=%d",
                    dataset_name,
                    file,
                    len(data),
                )

            except Exception as exc:
                logger.exception("Failed to load dataset from %s: %s", file, exc)

        self._fold_system_entities_into_locations()

    # --------------------------------------------------

    def _normalize_parent_relations(self, entity):
        parent_ideas = entity.get("parents", entity.get("parent_ideas", []))
        parent_ids = []

        if isinstance(parent_ideas, str):
            parent_ids.append(parent_ideas)
        elif isinstance(parent_ideas, list):
            parent_ids.extend(
                parent_id
                for parent_id in parent_ideas
                if isinstance(parent_id, str)
            )

        parent_entity = entity.get("parent_entity")
        if isinstance(parent_entity, str):
            if entity.get("type") == "idea":
                parent_ids.append(parent_entity)

        normalized = []
        for parent_id in parent_ids:
            if parent_id in self.entities and parent_id not in normalized:
                normalized.append(parent_id)

        return normalized

    def _build_offspring_tree(self, entity_id, children_by_parent, ancestry=None):
        ancestry = set(ancestry or [])
        if entity_id in ancestry:
            return []

        next_ancestry = set(ancestry)
        next_ancestry.add(entity_id)
        nodes = []

        for child_id in children_by_parent.get(entity_id, []):
            node = {"id": child_id}
            child_offspring = self._build_offspring_tree(
                child_id,
                children_by_parent,
                ancestry=next_ancestry,
            )
            if child_offspring:
                node["offspring"] = child_offspring
            nodes.append(node)

        return nodes

    def populate_offspring(self):
        children_by_parent = {}

        for entity_id, entity in self.entities.items():
            for parent_id in self._normalize_parent_relations(entity):
                children_by_parent.setdefault(parent_id, [])
                if entity_id not in children_by_parent[parent_id]:
                    children_by_parent[parent_id].append(entity_id)

        changed_entities = set()

        for entity_id, entity in self.entities.items():
            offspring = self._build_offspring_tree(entity_id, children_by_parent)
            if entity.get("offspring") != offspring:
                entity["offspring"] = offspring
                changed_entities.add(entity_id)

        return changed_entities

    def save_changed_dataset_files(self, changed_entity_ids=None):
        changed_entity_ids = set(changed_entity_ids or [])

        for record in self._dataset_file_records:
            changed = record.get("changed", False)

            if not changed:
                for entity in record["data"]:
                    if isinstance(entity, dict) and entity.get("id") in changed_entity_ids:
                        changed = True
                        break

            if changed:
                self._save_dataset_file(record["file"], record["data"])

    # --------------------------------------------------

    def build_entity_index(self):

        self.entities = {}

        for dataset in self.datasets.values():
            for entity in dataset:
                if not isinstance(entity, dict):
                    continue

                entity_id = entity.get("id")
                if not entity_id:
                    continue

                self.entities[entity_id] = entity

        logger.info("Total entities loaded: %s", len(self.entities))

    # --------------------------------------------------

    def build_reference_graph(self):

        self.edges = {}

        for entity_id, entity in self.entities.items():

            self.edges[entity_id] = []

            for value in entity.values():

                if isinstance(value, str):

                    if value in self.entities:
                        self.edges[entity_id].append(value)

                elif isinstance(value, list):

                    for item in value:

                        if isinstance(item, str) and item in self.entities:
                            self.edges[entity_id].append(item)

    # --------------------------------------------------

    def refresh(self, auto_save_normalized=None):
        """
        Reload repository entities and rebuild runtime indexes.

        Normalization still happens in memory so UI/runtime code can rely on
        standard fields. Writing those normalization changes back to disk is
        opt-in, because constructing or refreshing a world model should not
        mutate repository files by surprise.
        """
        if auto_save_normalized is None:
            auto_save_normalized = self.auto_save_normalized

        self.load_datasets()
        self.build_entity_index()
        changed_entity_ids = self.populate_offspring()
        if auto_save_normalized:
            self.save_changed_dataset_files(changed_entity_ids)
        self.build_reference_graph()

    # --------------------------------------------------

    def get(self, entity_id):
        if entity_id in self.entities:
            return self.entities.get(entity_id)

        canonical_id = self.entity_aliases.get(entity_id)
        if canonical_id:
            return self.entities.get(canonical_id)

        return None

    def get_dataset(self, dataset_name):

        return self.datasets.get(dataset_name, [])

    def get_connections(self, entity_id):

        return self.edges.get(entity_id, [])

    # --------------------------------------------------

    def print_summary(self):

        print("\nIndex_0 Database Summary\n")

        for dataset, data in self.datasets.items():
            print(f"{dataset}: {len(data)} entities")

        print(f"\nTotal entities: {len(self.entities)}")
