import json
from pathlib import Path
import logging


logger = logging.getLogger(__name__)


class EntityLoader:
    """
    Global entity loader for Index_0.
    """

    def __init__(self, entries_directory=None):

        if entries_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            entries_directory = project_root / "entries"

        self.entries_directory = Path(entries_directory)

        logger.debug("EntityLoader entries directory: %s", self.entries_directory)

        self.datasets = {}
        self.entities = {}
        self.edges = {}

        self.load_datasets()
        self.build_entity_index()
        self.build_reference_graph()

    # --------------------------------------------------

    def load_datasets(self):

        self.datasets = {}

        if not self.entries_directory.exists():
            logger.warning("Entries directory not found: %s", self.entries_directory)
            return

        files = list(self.entries_directory.glob("*.json"))

        logger.debug("Entry files discovered: %s", [f.name for f in files])

        for file in files:

            dataset_name = file.stem

            try:
                with open(file, "r", encoding="utf-8") as f:
                    self.datasets[dataset_name] = json.load(f)

                logger.debug(
                    "Loaded dataset %s | entities=%s",
                    dataset_name,
                    len(self.datasets[dataset_name])
                )

            except Exception as e:
                logger.exception("Failed loading %s", file)

    # --------------------------------------------------

    def build_entity_index(self):

        self.entities = {}

        for dataset_name, dataset in self.datasets.items():

            for entity_id, entity in dataset.items():

                entity["_dataset"] = dataset_name
                self.entities[entity_id] = entity

        logger.debug("Entity index built | count=%s", len(self.entities))

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

    def get(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return self.datasets.get(dataset_name, {})

    def get_connections(self, entity_id):
        return self.edges.get(entity_id, [])

    # --------------------------------------------------

    def refresh(self):

        self.load_datasets()
        self.build_entity_index()
        self.build_reference_graph()

    # --------------------------------------------------

    def print_summary(self):

        print("\nIndex_0 Database Summary\n")

        for dataset, data in self.datasets.items():
            print(f"{dataset}: {len(data)} entities")

        print(f"\nTotal entities: {len(self.entities)}")