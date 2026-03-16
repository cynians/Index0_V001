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

        self.datasets = {}

        files = list(self.entries_directory.glob("*.json"))
        files += list(self.entries_directory.glob("*.yaml"))
        files += list(self.entries_directory.glob("*.yml"))

        for file in files:

            dataset_name = file.stem

            try:

                if file.suffix == ".json":
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                else:
                    with open(file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)

                if not isinstance(data, list):

                    logger.warning(
                        "Dataset %s is not a list of entities",
                        dataset_name
                    )

                    continue

                dataset_dict = {}

                for entity in data:

                    if not isinstance(entity, dict):
                        continue

                    entity_id = entity.get("id")

                    if not entity_id:
                        logger.warning(
                            "Entity without id in dataset %s",
                            dataset_name
                        )
                        continue

                    entity["_dataset"] = dataset_name
                    dataset_dict[entity_id] = entity

                self.datasets[dataset_name] = dataset_dict

                logger.info(
                    "Loaded dataset %s | %s entities",
                    dataset_name,
                    len(dataset_dict)
                )

            except Exception:

                logger.exception(
                    "Failed loading dataset: %s",
                    file
                )

    # --------------------------------------------------

    def build_entity_index(self):

        self.entities = {}

        for dataset in self.datasets.values():

            for entity_id, entity in dataset.items():

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

        return self.datasets.get(dataset_name, {})

    def get_connections(self, entity_id):

        return self.edges.get(entity_id, [])

    # --------------------------------------------------

    def print_summary(self):

        print("\nIndex_0 Database Summary\n")

        for dataset, data in self.datasets.items():
            print(f"{dataset}: {len(data)} entities")

        print(f"\nTotal entities: {len(self.entities)}")