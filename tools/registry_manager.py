import json
from pathlib import Path


class RegistryManager:
    """
    Dynamic registry builder for Index_0.

    Registries are constructed automatically from the entry database.
    They are rebuilt at startup and can be refreshed on demand.

    This avoids the need for static registry files and ensures that
    classification systems always reflect the actual dataset.
    """

    CLASSIFICATION_FIELDS = {
        "vehicles": "vehicle_class",
        "factions": "faction_class",
        "technology": "technology_class",
        "production": "production_class",
        "events": "event_class",
        "people": "person_class",
        "locations": "type"
    }

    def __init__(self, entries_directory="entries"):
        self.entries_directory = Path(entries_directory)

        self.entries = {}
        self.registries = {}

        self.load_entries()
        self.build_registries()

    # --------------------------------------------------
    # Entry Loading
    # --------------------------------------------------

    def load_entries(self):
        """
        Loads all JSON entry files from the entries directory.
        """

        self.entries = {}

        for file in self.entries_directory.glob("*.json"):

            key = file.stem

            with open(file, "r", encoding="utf-8") as f:
                try:
                    self.entries[key] = json.load(f)
                except Exception as e:
                    print(f"Failed loading {file}: {e}")

    # --------------------------------------------------
    # Registry Builder
    # --------------------------------------------------

    def build_registries(self):
        """
        Scans entry datasets and constructs classification registries.
        """

        self.registries = {}

        for dataset, field in self.CLASSIFICATION_FIELDS.items():

            registry = set()

            entries = self.entries.get(dataset, {})

            for entry in entries.values():

                value = entry.get(field)

                if value:
                    registry.add(value)

            self.registries[dataset] = sorted(list(registry))

    # --------------------------------------------------
    # Public Access
    # --------------------------------------------------

    def get_registry(self, dataset):
        """
        Returns registry for a given dataset.

        Example:
        registry_manager.get_registry("vehicles")
        """

        return self.registries.get(dataset, [])

    # --------------------------------------------------
    # Refresh
    # --------------------------------------------------

    def refresh(self):
        """
        Reloads entries and rebuilds registries.
        Call this when entries are modified.
        """

        self.load_entries()
        self.build_registries()

    # --------------------------------------------------
    # Debug Helper
    # --------------------------------------------------

    def print_registries(self):
        """
        Prints all registries to console.
        """

        for key, values in self.registries.items():

            print(f"\n{key.upper()} REGISTRY")

            for v in values:
                print(f"  - {v}")