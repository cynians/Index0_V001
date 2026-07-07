from world.world_model import WorldModel
from world.year_utils import parse_year


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
        through the location parent chain.
        """
        if not entity:
            return False

        entity_id = entity.get("id")
        if entity_id == self.root_entity_id:
            return True

        visited = set()
        current_parent_id = self._structural_parent_location_id(entity)

        while current_parent_id:
            if current_parent_id in visited:
                return False

            if current_parent_id == self.root_entity_id:
                return True

            visited.add(current_parent_id)

            parent_entity = self.world_model.get_entity(current_parent_id)
            if not parent_entity:
                return False

            current_parent_id = self._structural_parent_location_id(parent_entity)

        return False

    def _relation_ids(self, value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, dict):
            entity_id = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
            return [entity_id] if entity_id else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

    def _structural_parent_location_id(self, entity):
        if not isinstance(entity, dict):
            return None

        entity_id = entity.get("id")
        for field_key in ("parent_location", "parent_entity", "parent_body", "parents"):
            for parent_id in self._relation_ids(entity.get(field_key)):
                parent = self.world_model.get_entity(parent_id)
                if parent_id and parent_id != entity_id and self._is_location_entity(parent):
                    return parent_id

        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        for candidate_id, candidate in entities.items():
            if candidate_id == entity_id or not self._is_location_entity(candidate):
                continue
            if entity_id in self._relation_ids(candidate.get("constituents")):
                return candidate_id

        return None

    def _all_location_entities(self):
        if hasattr(self.world_model, "get_dataset"):
            locations = self.world_model.get_dataset("locations")
            if locations:
                return list(locations)

        loader = getattr(self.world_model, "loader", None)
        datasets = getattr(loader, "datasets", {}) or {}
        if datasets.get("locations"):
            return list(datasets.get("locations") or [])

        return self.world_model.get_active_locations(self.year)

    def _location_is_active_for_map(self, entity):
        start = parse_year(entity.get("start_year"))
        end = parse_year(entity.get("end_year"))

        if start is None and end is None:
            return True
        if start is None:
            return False
        if int(self.year) < start:
            return False
        if end is not None and int(self.year) > end:
            return False
        return True

    def get_active_locations(self):
        """
        Return active location entities restricted to the root subtree.
        """
        location_entities = self._all_location_entities()

        return [
            entity for entity in location_entities
            if self._is_location_entity(entity)
            and self._location_is_active_for_map(entity)
            and self._is_in_root_subtree(entity)
        ]

    # --------------------------------------------------
    # Future extension hooks
    # --------------------------------------------------

    def get_entities_by_type(self, entity_type):
        return [
            e for e in self.get_active_entities()
            if e.get("type") == entity_type
        ]
