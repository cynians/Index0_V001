"""Ontology-backed ownership and use-access checks for corporal assets."""


class OwnershipResolver:
    """Resolve whether a person may use an owned vehicle, item, building, or site."""

    def __init__(self, world_model):
        self.world_model = world_model

    @staticmethod
    def _ids(value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple, set)):
            return [item for item in value if isinstance(item, str) and item]
        return []

    def _entity(self, entity_id):
        getter = getattr(self.world_model, "get_entity", None)
        return getter(entity_id) if callable(getter) and entity_id else None

    def _entities(self):
        # Merge base ontology entities with any overlay (e.g. SiteSimulation's
        # RuntimeWorldOverlay) rather than returning early on the overlay
        # dict alone -- an overlay's .entities is only its own provisional
        # records, never the full ontology, so short-circuiting there made
        # every ownership check inside SiteSimulation silently see zero
        # entities. Overlay entries win on id collisions, matching
        # RuntimeWorldOverlay.get_entity()'s own precedence.
        merged = {}
        loader = getattr(self.world_model, "loader", None)
        base_entities = getattr(loader, "entities", None)
        if isinstance(base_entities, dict):
            merged.update(base_entities)
        overlay_entities = getattr(self.world_model, "entities", None)
        if isinstance(overlay_entities, dict):
            merged.update(overlay_entities)
        return merged.values()

    def claims_for_asset(self, asset_id):
        asset = self._entity(asset_id) or {}
        claim_ids = set(self._ids(asset.get("ownership_records")))
        claims = []
        for entity in self._entities():
            if not isinstance(entity, dict):
                continue
            entity_type = str(entity.get("type") or entity.get("_dataset") or "").casefold()
            if entity_type not in {"ownership", "ownerships"}:
                continue
            if entity.get("id") in claim_ids or asset_id in self._ids(entity.get("owned_assets")):
                claims.append(entity)
        return claims

    def _person_access_subjects(self, person_id):
        subjects = {person_id}
        person = self._entity(person_id) or {}
        for field_name in (
            "affiliated_factions",
            "affiliated_institutions",
            "associated_producers",
            # Employment is a plain relationship field on the person (see
            # docs/conceptual_layer_overview_v006.txt section 22) rather than
            # a mediating employment entity -- is_employed_by already lists
            # the employer(s) directly.
            "is_employed_by",
        ):
            subjects.update(self._ids(person.get(field_name)))
        return subjects

    def access_report(self, person_id, asset_id):
        claims = self.claims_for_asset(asset_id)
        if not claims:
            return {
                "allowed": True,
                "reason": "unowned or no ownership restriction",
                "asset_id": asset_id,
                "claim_id": None,
            }

        subjects = self._person_access_subjects(person_id)
        for claim in claims:
            policy = str(claim.get("use_policy") or "private").strip().casefold()
            owners = set(self._ids(claim.get("owner_entities")))
            permitted = set(self._ids(claim.get("permitted_users")))
            if policy == "public" or subjects & (owners | permitted):
                return {
                    "allowed": True,
                    "reason": "owner or authorized user" if policy != "public" else "public use",
                    "asset_id": asset_id,
                    "claim_id": claim.get("id"),
                }
        return {
            "allowed": False,
            "reason": "owned by another party without use permission",
            "asset_id": asset_id,
            "claim_id": claims[0].get("id"),
        }

    def can_use(self, person_id, asset_id):
        return self.access_report(person_id, asset_id)["allowed"]
