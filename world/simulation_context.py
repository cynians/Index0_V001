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

    def get_active_locations(self):
        """
        Minimal first version:
        returns ALL active locations.

        Later:
        restrict to subtree of root_entity_id.
        """
        return self.world_model.get_active_locations(self.year)

    # --------------------------------------------------
    # Future extension hooks
    # --------------------------------------------------

    def get_entities_by_type(self, entity_type):
        return [
            e for e in self.get_active_entities()
            if e.get("type") == entity_type
        ]