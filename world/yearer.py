"""
Yearer

Temporal resolver for Index_0.

Responsible for resolving the correct state of an entity
for a given year.

This module will later support:
- simulation diffs
- historical branching
- timeline stepping
"""


class Yearer:

    def __init__(self, entity_loader):
        """
        entity_loader : EntityLoader instance
        """
        self.loader = entity_loader

    # --------------------------------------------------
    # Year normalization
    # --------------------------------------------------

    def normalize_year(self, value):
        """
        Converts year values to integers when possible.

        Handles YAML values like:
        None
        "null"
        "2400"
        """

        if value in (None, "null"):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None

        return None

    # --------------------------------------------------
    # Resolve entity state for a year
    # --------------------------------------------------

    def resolve(self, entity_id, year):
        """
        Returns the entity if it exists during the given year.
        """

        entity = self.loader.get(entity_id)

        if not entity:
            return None

        start = self.normalize_year(entity.get("start_year"))
        end = self.normalize_year(entity.get("end_year"))

        if start is not None and year < start:
            return None

        if end is not None and year > end:
            return None

        return entity

    # --------------------------------------------------
    # Get all entities active in a year
    # --------------------------------------------------

    def entities_active(self, year):
        """
        Returns all entities active during the given year.
        """

        active = {}

        for entity_id, entity in self.loader.entities.items():

            start = self.normalize_year(entity.get("start_year"))
            end = self.normalize_year(entity.get("end_year"))

            if start is not None and year < start:
                continue

            if end is not None and year > end:
                continue

            active[entity_id] = entity

        return active

    # --------------------------------------------------
    # Debug helper
    # --------------------------------------------------

    def print_entity_state(self, entity_id, year):

        entity = self.resolve(entity_id, year)

        if entity:
            print(f"{entity_id} exists in {year}")
        else:
            print(f"{entity_id} does NOT exist in {year}")