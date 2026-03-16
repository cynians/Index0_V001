from tools.entity_loader import EntityLoader
from tools.relationship_graph import TouchDegrees
from tools.schema_loader import SchemaLoader


class WorldModel:
    """
    Central world interface used by UI systems.

    Combines:
    - entity loader
    - touch graph
    - registry manager

    Provides query functions used by:
    - canvas
    - timeline
    - editor
    """

    def __init__(self):

        self.loader = EntityLoader()
        self.schemas = SchemaLoader()
        self.touch_degrees = TouchDegrees(self.loader, self.schemas)

    # ----------------------------------
    # Entity Access
    # ----------------------------------

    def get_entity(self, entity_id):
        return self.loader.get(entity_id)

    def get_dataset(self, dataset):
        return self.loader.get_dataset(dataset)

    # ----------------------------------
    # Graph / Touch Access
    # ----------------------------------

    def get_neighbors(self, entity_id):
        return self.touch_degrees.get_neighbors(entity_id)

    def get_relationships(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_touches(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_incoming_touches(self, entity_id):
        return self.touch_degrees.get_incoming_touches(entity_id)

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
        self.touch_degrees.refresh()

    # --------------------------------------------------
    # World validation
    # --------------------------------------------------

    def validate_world(self):

        print("\nWorld Validation\n")

        errors = []

        for entity_id, entity in self.loader.entities.items():

            entity_type = entity.get("type")

            schema = self.schemas.get_schema(entity_type)

            if not schema:
                errors.append(
                    f"{entity_id}: unknown schema '{entity_type}'"
                )
                continue

            fields = schema.get("fields", {})

            for field, spec in fields.items():

                if field not in entity:
                    continue

                value = entity[field]
                field_type = spec.get("type")

                # --------------------------------------------------
                # entity reference
                # --------------------------------------------------

                if field_type == "entity":

                    if value not in self.loader.entities:
                        errors.append(
                            f"{entity_id}.{field} → missing entity '{value}'"
                        )

                # --------------------------------------------------
                # entity list reference
                # --------------------------------------------------

                elif field_type == "entity_list":

                    if not isinstance(value, list):
                        errors.append(
                            f"{entity_id}.{field} should be a list"
                        )
                        continue

                    for target in value:

                        if target not in self.loader.entities:
                            errors.append(
                                f"{entity_id}.{field} → missing entity '{target}'"
                            )

        # --------------------------------------------------
        # Results
        # --------------------------------------------------

        if not errors:

            print("No problems detected.")

        else:

            print("Problems found:\n")

            for e in errors:
                print(" -", e)

        print()



    # --------------------------------------------------
    # Explain entity
    # --------------------------------------------------

    def explain(self, entity_id):

        entity = self.loader.get(entity_id)

        if not entity:
            print("Entity not found:", entity_id)
            return

        entity_type = entity.get("type")

        print(f"\n{entity_id} ({entity_type})\n")

        # --------------------------------------------------
        # Outgoing
        # --------------------------------------------------

        outgoing = self.touch_degrees.get_touches(entity_id)

        if outgoing:

            print("Outgoing relations\n")

            relations = {}

            for touch in outgoing:

                relations.setdefault(
                    touch["relation"], []
                ).append(touch["target"])

            for relation, targets in relations.items():

                print(f"  {relation}")

                for t in targets:
                    print("   -", t)

        else:

            print("No outgoing relations\n")

        # --------------------------------------------------
        # Incoming
        # --------------------------------------------------

        incoming = self.touch_degrees.get_incoming_touches(entity_id)

        if incoming:

            print("\nIncoming relations\n")

            relations = {}

            for touch in incoming:

                relations.setdefault(
                    touch["relation"], []
                ).append(touch["source"])

            for relation, sources in relations.items():

                print(f"  {relation}")

                for s in sources:
                    print("   -", s)

        else:

            print("\nNo incoming relations")

        print()

    # --------------------------------------------------
    # Multi-hop graph query
    # --------------------------------------------------

    def query(self, start_entity, depth=2):

        if start_entity not in self.loader.entities:
            print("Unknown entity:", start_entity)
            return

        visited = set()
        frontier = [(start_entity, 0)]

        print()

        while frontier:

            current, level = frontier.pop(0)

            if current in visited:
                continue

            visited.add(current)

            indent = "  " * level
            print(f"{indent}{current}")

            if level >= depth:
                continue

            touches = self.touch_degrees.get_touches(current)

            for touch in touches:

                target = touch["target"]

                relation = touch["relation"]

                indent_rel = "  " * (level + 1)

                print(f"{indent_rel}└ {relation}")

                frontier.append((target, level + 1))