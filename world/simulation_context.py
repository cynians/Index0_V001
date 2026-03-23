from world.world_model import WorldModel


class SimulationContext:
    """
    Defines the active simulation scope.

    Responsibilities:
    * define time (year)
    * define root entity (e.g. planet, region)
    * provide filtered entity access for simulations

    This decouples simulations from raw WorldModel access.
    """

    def __init__(self, year, root_entity_id, world_model=None):
        self.year = year
        self.root_entity_id = root_entity_id
        self.world_model = world_model or WorldModel()

    # --------------------------------------------------
    # Core access
    # --------------------------------------------------

    def get_root_entity(self):
        return self.world_model.get_entity(self.root_entity_id)

    def get_active_entities(self):
        return self.world_model.get_active_entities(self.year)

    def _is_in_root_subtree(self, entity):
        """
        Return True if the entity is the root entity or a descendant of it
        through the parent_location chain.
        """
        if not entity:
            return False

        entity_id = entity.get("id")
        if entity_id == self.root_entity_id:
            return True

        visited = set()
        current_parent_id = entity.get("parent_location")

        while current_parent_id:
            if current_parent_id in visited:
                return False

            if current_parent_id == self.root_entity_id:
                return True

            visited.add(current_parent_id)

            parent_entity = self.world_model.get_entity(current_parent_id)
            if not parent_entity:
                return False

            current_parent_id = parent_entity.get("parent_location")

        return False

    def get_active_locations(self):
        """
        Return active location entities restricted to the root subtree.
        """
        active_locations = self.world_model.get_active_locations(self.year)

        return [
            entity for entity in active_locations
            if self._is_in_root_subtree(entity)
        ]

    # --------------------------------------------------
    # Future extension hooks
    # --------------------------------------------------

    def get_entities_by_type(self, entity_type):
        return [
            e for e in self.get_active_entities()
            if e.get("type") == entity_type
        ]