from world.entity_loader import EntityLoader
from world.relationship_graph import TouchDegrees
from world.schema_loader import SchemaLoader
from world.yearer import Yearer


class WorldModel:
    """
    Central world interface used by UI systems.

    Combines:
    * entity loading
    * schema loading
    * relationship graph construction
    * year-based entity filtering
    """

    # Canonical macro-era bounds are deduced from the lore references in
    # text/ideas.txt. Some older notes in text/timeline.txt still use
    # superseded boundaries (for example 6013 vs 6034 for the start of the
    # Planetary Period), so the ideas reference is treated as the stronger
    # source here.
    MAJOR_PERIODS = [
        {
            "entity_id": "period_postmodernist",
            "label": "Postmodernist Period",
            "start_year": 2024,
            "end_year": 2090,
        },
        {
            "entity_id": "period_superpower_wars",
            "label": "Superpower Wars",
            "start_year": 2024,
            "end_year": 2090,
        },
        {
            "entity_id": "period_race_for_sol",
            "label": "Race for Sol",
            "start_year": 2090,
            "end_year": 2440,
        },
        {
            "entity_id": "period_ggo_hegemony",
            "label": "GGO Hegemony Period",
            "start_year": 2440,
            "end_year": 5954,
        },
        {
            "entity_id": "period_second_modernity_earth",
            "label": "Second Modernity (Earth)",
            "start_year": 5954,
            "end_year": 6034,
        },
        {
            "entity_id": "period_planetary",
            "label": "Planetary Period",
            "start_year": 6034,
            "end_year": 14195,
        },
        {
            "entity_id": "period_trifecta_dominion",
            "label": "Trifecta Dominion Period",
            "start_year": 14195,
            "end_year": 20219,
        },
        {
            "entity_id": "period_intersector_assembly",
            "label": "Intersector Assembly Period",
            "start_year": 20219,
            "end_year": 35101,
        },
    ]

    def __init__(self):
        self.loader = EntityLoader()
        self.schemas = SchemaLoader()
        self.touch_degrees = TouchDegrees(self.loader, self.schemas)
        self.graph = self.touch_degrees
        self.yearer = Yearer(self.loader)

    def get_entity(self, entity_id):
        return self.loader.get(entity_id)

    def get_dataset(self, dataset_name):
        return self.loader.get_dataset(dataset_name)

    def get_dataset_names(self):
        return list(self.loader.datasets.keys())

    def get_entities_by_dataset(self, dataset_name):
        dataset = self.loader.get_dataset(dataset_name)

        if isinstance(dataset, dict):
            return list(dataset.values())

        if isinstance(dataset, list):
            return dataset

        return []

    def get_entities_by_type(self, entity_type):
        return [
            entity
            for entity in self.loader.entities.values()
            if entity.get("type") == entity_type
        ]

    def get_neighbors(self, entity_id):
        return self.touch_degrees.get_neighbors(entity_id)

    def get_relationships(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_touches(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_incoming_touches(self, entity_id):
        return self.touch_degrees.get_incoming_touches(entity_id)

    def get_events(self):
        return self.loader.get_dataset("events")

    def get_events_in_range(self, start, end):
        events = []

        for event in self.get_events().values():
            year = event.get("year")

            if year is None:
                continue

            if start <= year <= end:
                events.append(event)

        return events

    def resolve_entity(self, entity_id, year):
        return self.yearer.resolve(entity_id, year)

    def entities_active(self, year):
        return self.yearer.entities_active(year)

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        active_entities = list(self.yearer.entities_active(year).values())

        if dataset_name is not None:
            active_entities = [
                entity
                for entity in active_entities
                if entity.get("_dataset") == dataset_name
            ]

        if entity_type is not None:
            active_entities = [
                entity
                for entity in active_entities
                if entity.get("type") == entity_type
            ]

        return active_entities

    def get_active_dataset(self, dataset_name, year):
        return self.get_active_entities(year, dataset_name=dataset_name)

    def get_active_locations(self, year):
        return self.get_active_entities(
            year,
            dataset_name="locations",
            entity_type="location"
        )

    def _get_major_period_timeline_items(self):
        items = []

        for period in self.MAJOR_PERIODS:
            items.append(
                {
                    "entity_id": period["entity_id"],
                    "label": period["label"],
                    "dataset": "timeline_periods",
                    "entity_type": "major_period",
                    "timeline_kind": "major_period",
                    "start_year": period["start_year"],
                    "end_year": period["end_year"],
                    "is_point": False,
                }
            )

        return items

    def get_timeline_items(self):
        """
        Collect repository entities that define temporal information.

        Returns a list of timeline-ready dictionaries with normalized years.
        Minimal prototype rules:
        * include any entity with start_year and/or end_year
        * if only one side exists, treat it as a point entry
        * keep output flat and UI-friendly
        """
        items = self._get_major_period_timeline_items()

        for entity_id, entity in self.loader.entities.items():
            start_year = self.yearer.normalize_year(entity.get("start_year"))
            end_year = self.yearer.normalize_year(entity.get("end_year"))

            if start_year is None and end_year is None:
                continue

            if start_year is None:
                start_year = end_year
            if end_year is None:
                end_year = start_year

            if start_year is None and end_year is None:
                continue

            dataset_name = entity.get("_dataset", entity.get("type", "entity"))
            label = entity.get("pretty_name") or entity.get("name") or entity_id

            items.append(
                {
                    "entity_id": entity_id,
                    "label": str(label),
                    "dataset": dataset_name,
                    "entity_type": entity.get("type", "entity"),
                    "start_year": start_year,
                    "end_year": end_year,
                    "is_point": start_year == end_year,
                }
            )

        return items

    def refresh(self):
        self.loader.refresh()
        self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
