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
        "derived_from_ideas": [],
        "parent_ideas": [],
        "related_ideas": [],
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
        "parent_ideas": [],
        "related_ideas": [],
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
        "media_layers",
    }

    def __init__(self, entries_directory=None, auto_save_normalized=False):

        if entries_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            entries_directory = project_root / "entries"

        self.entries_directory = Path(entries_directory)
        self.auto_save_normalized = auto_save_normalized

        self.datasets = {}
        self.entities = {}
        self.edges = {}
        self._dataset_file_records = []

        self.refresh()

    # --------------------------------------------------

    def _ensure_standard_relations(self, entity, dataset_name=None):
        changed = False

        if "pretty_name" not in entity:
            entity["pretty_name"] = entity.get("name") or entity.get("id") or ""
            changed = True

        if "name" not in entity:
            entity["name"] = entity.get("pretty_name") or entity.get("id") or ""
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

    # --------------------------------------------------

    def _normalize_parent_ideas(self, entity):
        parent_ideas = entity.get("parent_ideas", [])
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
            for parent_id in self._normalize_parent_ideas(entity):
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

        return self.entities.get(entity_id)

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
