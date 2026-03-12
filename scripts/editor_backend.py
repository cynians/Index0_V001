import json
from pathlib import Path


class EditorBackend:

    def __init__(self):

        self.data = {}

        self.entries_dir = Path(__file__).resolve().parent.parent / "entries"

        self.relationship_cache = {}
        self.reverse_relationship_cache = {}

        # fields that should automatically create graph edges
        self.relationship_fields = {
            "parent",
            "parent_faction",
            "faction",
            "location",
            "headquarters",
            "territories",
            "members",
            "participants",
            "factions",
            "related_events",
            "habitats",
            "diet",
            "predators",
            "prey",
            "satellite_ids",
            "planets",
            "neighbours",

            # orbital object relations
            "orbit_parent",
            "origin_event",
            "related_objects"
        }

    # -------------------------------------------------
    # LOAD DATA
    # -------------------------------------------------

    def load_entries(self):

        if not self.entries_dir.exists():
            return

        for file in self.entries_dir.glob("*.json"):

            category = file.stem

            try:

                text = file.read_text(encoding="utf-8").strip()

                if not text:
                    self.data[category] = {}
                    continue

                entries = json.loads(text)

            except Exception as e:

                print(f"Skipping {file.name}: {e}")
                entries = {}

            self.data[category] = entries

        self.build_relationship_cache()

    # -------------------------------------------------
    # BUILD RELATIONSHIP GRAPH
    # -------------------------------------------------

    def build_relationship_cache(self):

        self.relationship_cache = {}
        self.reverse_relationship_cache = {}

        for category, entries in self.data.items():

            for entry_id, entry in entries.items():

                if entry_id not in self.relationship_cache:
                    self.relationship_cache[entry_id] = {}

                for field, value in entry.items():

                    if field not in self.relationship_fields:
                        continue

                    targets = []

                    # single object reference
                    if isinstance(value, str):

                        targets.append(value)

                    # list reference
                    elif isinstance(value, list):

                        for item in value:

                            if isinstance(item, str):
                                targets.append(item)

                            elif isinstance(item, dict) and "id" in item:
                                targets.append(item["id"])

                    # store relationships
                    if not targets:
                        continue

                    self.relationship_cache[entry_id].setdefault(
                        field, []
                    ).extend(targets)

                    for target in targets:

                        self.reverse_relationship_cache.setdefault(
                            target, []
                        ).append((entry_id, field))

    # -------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------

    def get_categories(self):

        return list(self.data.keys())

    def get_entries(self, category):

        return self.data.get(category, {})

    def get_entry(self, category, entry_id):

        return self.data[category][entry_id]

    def resolve_entity_state(self, category, entry_id, year):

        entry = self.data[category][entry_id]

        state = dict(entry)

        capsule_fields = {
            "people": "person_years",
            "locations": "market_years",
            "factions": "faction_years",
            "species": "species_years",
            "vehicles": "vehicle_years"
        }

        capsule_field = capsule_fields.get(category)

        if not capsule_field:
            state["_capsule_outdated"] = False
            return state

        capsules = entry.get(capsule_field)

        if not capsules:
            state["_capsule_outdated"] = False
            return state

        year = int(year)

        available_years = []

        for y in capsules.keys():
            try:
                available_years.append(int(y))
            except:
                pass

        if not available_years:
            state["_capsule_outdated"] = False
            return state

        # exact match
        if str(year) in capsules:
            capsule = capsules[str(year)]
            outdated = False

        else:
            earlier = [y for y in available_years if y <= year]

            if not earlier:
                state["_capsule_outdated"] = False
                return state

            nearest = max(earlier)
            capsule = capsules[str(nearest)]
            outdated = True

        for key, value in capsule.items():
            state[key] = value

        state["_capsule_outdated"] = outdated

        return state

    def add_entry(self, category, entry_id):

        new_entry = {
            "id": entry_id,
            "name": "New Entry",
            "type": "",
            "parent": None
        }

        self.data[category][entry_id] = new_entry

        return new_entry

    # -------------------------------------------------
    # SAVE
    # -------------------------------------------------

    def save_entries(self):

        for category, entries in self.data.items():

            file_path = self.entries_dir / f"{category}.json"

            with open(file_path, "w", encoding="utf-8") as f:

                json.dump(entries, f, indent=2)