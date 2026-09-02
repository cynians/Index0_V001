import unittest

from world.ownership_resolver import OwnershipResolver


class _Loader:
    def __init__(self, entities):
        self.entities = dict(entities)


class _BaseWorldModel:
    """Mimics the real WorldModel: entities live under .loader.entities, no
    top-level .entities attribute."""

    def __init__(self, entities):
        self.loader = _Loader(entities)

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)


class _OverlayWorldModel:
    """Mimics simulations.person.site_simulation.RuntimeWorldOverlay: a
    top-level .entities dict of its own provisional records, plus a .loader
    borrowed from the base world model."""

    def __init__(self, base, overlay_entities=None):
        self.base = base
        self.entities = dict(overlay_entities or {})
        self.loader = base.loader

    def get_entity(self, entity_id):
        return self.entities.get(entity_id) or self.base.get_entity(entity_id)


class OwnershipResolverEntitiesTests(unittest.TestCase):
    def _claim(self, asset_id, owner_id):
        return {
            "id": f"ownership_{asset_id}",
            "type": "ownership",
            "owned_assets": [asset_id],
            "owner_entities": [owner_id],
            "use_policy": "private",
        }

    def test_sees_base_ontology_entities_through_empty_overlay(self):
        # Regression: OwnershipResolver._entities() used to return early on
        # the overlay's own (often empty) entities dict and never reach the
        # real ontology data in loader.entities, so every ownership check
        # silently saw zero entities inside SiteSimulation.
        base = _BaseWorldModel({
            "ownership_asset_a": self._claim("asset_a", "person_owner"),
        })
        overlay = _OverlayWorldModel(base, overlay_entities={})
        resolver = OwnershipResolver(overlay)

        claims = resolver.claims_for_asset("asset_a")
        self.assertEqual(1, len(claims))
        self.assertFalse(resolver.can_use("person_stranger", "asset_a"))
        self.assertTrue(resolver.can_use("person_owner", "asset_a"))

    def test_overlay_entities_win_on_id_collision(self):
        base = _BaseWorldModel({
            "ownership_asset_a": self._claim("asset_a", "person_base_owner"),
        })
        overlay = _OverlayWorldModel(base, overlay_entities={
            "ownership_asset_a": self._claim("asset_a", "person_overlay_owner"),
        })
        resolver = OwnershipResolver(overlay)

        claims = resolver.claims_for_asset("asset_a")
        self.assertEqual(1, len(claims))
        self.assertTrue(resolver.can_use("person_overlay_owner", "asset_a"))
        self.assertFalse(resolver.can_use("person_base_owner", "asset_a"))

    def test_merges_overlay_only_entities_with_base(self):
        base = _BaseWorldModel({
            "ownership_asset_a": self._claim("asset_a", "person_owner"),
        })
        overlay = _OverlayWorldModel(base, overlay_entities={
            "ownership_asset_b": self._claim("asset_b", "person_overlay_owner"),
        })
        resolver = OwnershipResolver(overlay)

        self.assertEqual(1, len(resolver.claims_for_asset("asset_a")))
        self.assertEqual(1, len(resolver.claims_for_asset("asset_b")))


if __name__ == "__main__":
    unittest.main()
