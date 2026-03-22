class TouchDegrees:
    """
    Touch graph for Index_0.

    Converts entity references into typed relations so the
    database behaves like a semantic knowledge graph.

    If schemas are available, only declared relationship fields
    are followed. Otherwise a fallback scan is used.
    """

    def __init__(self, entity_loader, schema_loader=None):

        self.loader = entity_loader
        self.schemas = schema_loader

        self.touches = {}
        self.reverse_touches = {}

        self.ignore_fields = {
            "id",
            "pretty_name",
            "type",
            "tags",
            "start_year",
            "end_year"
        }

        self.build_touches()

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _normalize(self, text):

        if not isinstance(text, str):
            return None

        return text.lower().replace(" ", "_")

    def _resolve_entity(self, value):

        if value in self.loader.entities:
            return value

        normalized = self._normalize(value)

        if normalized in self.loader.entities:
            return normalized

        return None

    # --------------------------------------------------
    # Schema helpers
    # --------------------------------------------------

    def _get_schema_fields(self, entity):

        if not self.schemas:
            return None

        entity_type = entity.get("type")

        if not entity_type:
            return None

        schema = self.schemas.get_schema(entity_type)

        if not schema:
            return None

        return schema.get("fields", {})

    # --------------------------------------------------
    # Touch builder
    # --------------------------------------------------

    def build_touches(self):

        self.touches = {}
        self.reverse_touches = {}

        for entity_id, entity in self.loader.entities.items():

            self.touches[entity_id] = []

            schema_fields = self._get_schema_fields(entity)

            # --------------------------------------------------
            # SCHEMA MODE
            # --------------------------------------------------

            if schema_fields:

                for field, spec in schema_fields.items():

                    value = entity.get(field)

                    if not value:
                        continue

                    field_type = spec.get("type")

                    if field_type == "entity":

                        target = self._resolve_entity(value)

                        if target:
                            self._add_touch(entity_id, target, field)

                    elif field_type == "entity_list":

                        for item in value:

                            target = self._resolve_entity(item)

                            if target:
                                self._add_touch(entity_id, target, field)

            # --------------------------------------------------
            # FALLBACK MODE
            # --------------------------------------------------

            else:

                for field, value in entity.items():

                    if field in self.ignore_fields:
                        continue

                    if isinstance(value, str):

                        target = self._resolve_entity(value)

                        if target:
                            self._add_touch(entity_id, target, field)

                    elif isinstance(value, list):

                        for item in value:

                            if isinstance(item, str):

                                target = self._resolve_entity(item)

                                if target:
                                    self._add_touch(entity_id, target, field)

    # --------------------------------------------------
    # Touch insertion
    # --------------------------------------------------

    def _add_touch(self, source, target, relation):

        if source == target:
            return

        touch = {
            "target": target,
            "relation": relation
        }

        self.touches.setdefault(source, []).append(touch)

        reverse_touch = {
            "source": source,
            "relation": relation
        }

        self.reverse_touches.setdefault(target, []).append(reverse_touch)

    # --------------------------------------------------
    # Public queries
    # --------------------------------------------------

    def get_touches(self, entity_id):
        return self.touches.get(entity_id, [])

    def get_incoming_touches(self, entity_id):
        return self.reverse_touches.get(entity_id, [])

    def get_neighbors(self, entity_id):

        neighbors = set()

        for touch in self.get_touches(entity_id):
            neighbors.add(touch["target"])

        for touch in self.get_incoming_touches(entity_id):
            neighbors.add(touch["source"])

        return list(neighbors)

    # --------------------------------------------------

    def refresh(self):

        self.build_touches()

    # --------------------------------------------------

    def print_entity_touches(self, entity_id):

        print(f"\nTouches for {entity_id}\n")

        for touch in self.get_touches(entity_id):

            print(f"{entity_id} --{touch['relation']}--> {touch['target']}")

        for touch in self.get_incoming_touches(entity_id):

            print(f"{touch['source']} --{touch['relation']}--> {entity_id}")