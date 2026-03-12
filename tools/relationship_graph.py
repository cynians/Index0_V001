class RelationshipGraph:
    """
    Relationship graph for Index_0.

    Converts entity references into typed relationships
    so the database behaves like a semantic knowledge graph.
    """

    def __init__(self, entity_loader):

        self.loader = entity_loader

        # forward edges
        self.edges = {}

        # reverse edges
        self.reverse_edges = {}

        self.build_relationships()

    # --------------------------------------------------
    # Relationship builder
    # --------------------------------------------------

    def build_relationships(self):

        self.edges = {}
        self.reverse_edges = {}

        for entity_id, entity in self.loader.entities.items():

            self.edges[entity_id] = []

            for field, value in entity.items():

                if isinstance(value, str):

                    if value in self.loader.entities:
                        self._add_edge(entity_id, value, field)

                elif isinstance(value, list):

                    for item in value:

                        if isinstance(item, str) and item in self.loader.entities:
                            self._add_edge(entity_id, item, field)

    # --------------------------------------------------
    # Edge insertion
    # --------------------------------------------------

    def _add_edge(self, source, target, relation):

        edge = {
            "target": target,
            "relation": relation
        }

        self.edges[source].append(edge)

        reverse = {
            "source": source,
            "relation": relation
        }

        self.reverse_edges.setdefault(target, []).append(reverse)

    # --------------------------------------------------
    # Public queries
    # --------------------------------------------------

    def get_edges(self, entity_id):
        """
        Returns all outgoing relationships.
        """
        return self.edges.get(entity_id, [])

    def get_incoming(self, entity_id):
        """
        Returns all incoming relationships.
        """
        return self.reverse_edges.get(entity_id, [])

    def get_neighbors(self, entity_id):
        """
        Returns all connected entities.
        """
        neighbors = set()

        for edge in self.get_edges(entity_id):
            neighbors.add(edge["target"])

        for edge in self.get_incoming(entity_id):
            neighbors.add(edge["source"])

        return list(neighbors)

    # --------------------------------------------------
    # Refresh
    # --------------------------------------------------

    def refresh(self):

        self.build_relationships()

    # --------------------------------------------------
    # Debug
    # --------------------------------------------------

    def print_entity_relationships(self, entity_id):

        print(f"\nRelationships for {entity_id}\n")

        for edge in self.get_edges(entity_id):

            print(
                f"{entity_id} --{edge['relation']}--> {edge['target']}"
            )

        for edge in self.get_incoming(entity_id):

            print(
                f"{edge['source']} --{edge['relation']}--> {entity_id}"
            )