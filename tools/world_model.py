from tools.entity_loader import EntityLoader
from tools.relationship_graph import RelationshipGraph


class WorldModel:
    """
    Central world interface used by UI systems.

    Combines:
    - entity loader
    - relationship graph
    - registry manager

    Provides query functions used by:
    - canvas
    - timeline
    - editor
    """

    def __init__(self):

        self.loader = EntityLoader()
        self.graph = RelationshipGraph(self.loader)

    # ----------------------------------
    # Entity Access
    # ----------------------------------

    def get_entity(self, entity_id):
        return self.loader.get(entity_id)

    def get_dataset(self, dataset):
        return self.loader.get_dataset(dataset)

    # ----------------------------------
    # Graph Access
    # ----------------------------------

    def get_neighbors(self, entity_id):
        return self.graph.get_neighbors(entity_id)

    def get_relationships(self, entity_id):
        return self.graph.get_edges(entity_id)

    # ----------------------------------
    # Timeline Queries
    # ----------------------------------

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

    # ----------------------------------
    # Refresh
    # ----------------------------------

    def refresh(self):

        self.loader.refresh()
        self.graph.refresh()