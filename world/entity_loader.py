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

    def __init__(self, entries_directory=None):

        if entries_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            entries_directory = project_root / "entries"

        self.entries_directory = Path(entries_directory)

        self.datasets = {}
        self.entities = {}
        self.edges = {}

        self.refresh()

    # --------------------------------------------------

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

    def refresh(self):

        self.load_datasets()
        self.build_entity_index()
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