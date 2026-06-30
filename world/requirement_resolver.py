class RequirementResolver:
    """Generic entity requirement checks with a production-focused subsection."""

    def __init__(self, world_model):
        self.world_model = world_model

    def _entity(self, entity_id):
        if self.world_model is None or not entity_id:
            return None
        entity = self.world_model.get_entity(entity_id)
        return entity if isinstance(entity, dict) else None

    def _relation_ids(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, dict):
            for key in ("id", "entity_id", "target", "location_id"):
                candidate = str(value.get(key) or "").strip()
                if candidate:
                    return [candidate]
            return []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []

    def _string_values(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [value.strip().lower()] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            values = []
            for item in value:
                text = str(item or "").strip().lower()
                if text and text not in values:
                    values.append(text)
            return values
        return [str(value).strip().lower()] if str(value).strip() else []

    def _entity_tags(self, entity):
        if not isinstance(entity, dict):
            return set()
        return set(self._string_values(entity.get("tags")))

    def _entities_for_field(self, entity, field_key):
        return [
            candidate
            for candidate_id in self._relation_ids((entity or {}).get(field_key))
            for candidate in [self._entity(candidate_id)]
            if isinstance(candidate, dict)
        ]

    def _has_entity_with_tag(self, entities, required_tag):
        required = str(required_tag or "").strip().lower()
        if not required:
            return False
        return any(required in self._entity_tags(entity) for entity in entities)

    def _technology_requirements(self, technology, site):
        site_tags = self._entity_tags(site)
        site_conditions = set(self._string_values((site or {}).get("site_conditions")))
        site_conditions.update(site_tags)
        assigned_vehicles = self._entities_for_field(site, "assigned_vehicles")
        assigned_items = self._entities_for_field(site, "assigned_items")
        assigned_components = self._entities_for_field(site, "assigned_components")
        active_technology_ids = set(self._relation_ids((site or {}).get("active_production_technologies")))

        checks = []
        for tag in self._string_values(technology.get("required_site_tags")):
            checks.append({
                "kind": "site_tag",
                "label": f"Site tag: {tag}",
                "satisfied": tag in site_tags or tag in site_conditions,
            })
        for condition in self._string_values(technology.get("required_site_conditions")):
            checks.append({
                "kind": "site_condition",
                "label": f"Site condition: {condition}",
                "satisfied": condition in site_conditions,
            })
        for vehicle_tag in self._string_values(technology.get("required_vehicle_tags")):
            checks.append({
                "kind": "vehicle_tag",
                "label": f"Vehicle tag: {vehicle_tag}",
                "satisfied": self._has_entity_with_tag(assigned_vehicles, vehicle_tag),
            })
        for item_tag in self._string_values(technology.get("required_item_tags")):
            checks.append({
                "kind": "item_tag",
                "label": f"Item tag: {item_tag}",
                "satisfied": self._has_entity_with_tag(assigned_items, item_tag),
            })
        for component_tag in self._string_values(technology.get("required_component_tags")):
            checks.append({
                "kind": "component_tag",
                "label": f"Component tag: {component_tag}",
                "satisfied": self._has_entity_with_tag(assigned_components, component_tag),
            })
        for required_id in self._relation_ids(technology.get("required_technologies")):
            required = self._entity(required_id)
            label = (required or {}).get("name") or (required or {}).get("pretty_name") or required_id
            checks.append({
                "kind": "technology",
                "label": f"Technology: {label}",
                "entity_id": required_id,
                "satisfied": required_id in active_technology_ids,
            })
        return checks

    def production_site_report(self, site):
        if not isinstance(site, dict):
            return []
        reports = []
        for technology_id in self._relation_ids(site.get("active_production_technologies")):
            technology = self._entity(technology_id)
            if not isinstance(technology, dict):
                continue
            checks = self._technology_requirements(technology, site)
            reports.append({
                "technology_id": technology_id,
                "technology": technology,
                "label": technology.get("name") or technology.get("pretty_name") or technology_id,
                "checks": checks,
                "complete": all(check.get("satisfied") for check in checks) if checks else True,
            })
        return reports

    def site_report(self, site):
        return {
            "production": self.production_site_report(site),
        }
