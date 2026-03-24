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

    def refresh(self):
        self.loader.refresh()
        self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)