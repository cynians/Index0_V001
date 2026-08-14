from world.periods import (
    TOP_LEVEL_PERIOD_IDS,
    century_entity_id,
    century_number_for_year,
    event_anchor_year,
    top_level_period_for_year,
    year_entity_id,
)


class KnowledgeBrowserModel:
    def __init__(self, host):
        object.__setattr__(self, "host", host)

    def __getattr__(self, name):
        return getattr(self.host, name)

    def __setattr__(self, name, value):
        setattr(self.host, name, value)

    def _is_expanded(self, entity_id, dataset_name="locations"):
        state = self.browser_tree_state.setdefault(dataset_name, {})
        if dataset_name == "locations":
            legacy_state = self.browser_tree_state.get("systems", {})
            if entity_id in legacy_state and entity_id not in state:
                state[entity_id] = legacy_state[entity_id]
        return state.get(entity_id, False)

    def _set_expanded(self, entity_id, expanded, dataset_name="locations"):
        self.browser_tree_state.setdefault(dataset_name, {})[entity_id] = expanded

    def _browser_dataset_filters(self):
        if self.world_model is None:
            return ["all", "schemas"]
        preferred = ["all", "schemas", "locations", "systems", "vehicles", "components", "events"]
        names = ["all"] + sorted(name for name in self.world_model.get_dataset_names() if name not in {"all", "production"})
        if "schemas" not in names:
            names.append("schemas")
        ordered = [name for name in preferred if name in names]
        ordered.extend(name for name in names if name not in ordered)
        return ordered

    def _format_browser_filter_label(self, filter_name):
        if filter_name == "all":
            return "All"
        return str(filter_name).replace("_", " ").title()

    def _query_matches_text(self, query, text):
        terms = [term for term in str(query or "").strip().lower().split() if term]
        if not terms:
            return True
        haystack = str(text or "").lower()
        return all(term in haystack for term in terms)

    def _entity_exists_during_browser_period(self, entity):
        if not self.browser_period_filter:
            return True
        if not isinstance(entity, dict):
            return False

        filter_start, filter_end = self.browser_period_filter
        start_year = self._coerce_card_year(entity.get("start_year"))
        end_year = self._coerce_card_year(entity.get("end_year"))

        if start_year is not None:
            if end_year is None:
                end_year = filter_end
            entity_start = min(start_year, end_year)
            entity_end = max(start_year, end_year)
            return entity_start <= filter_end and entity_end >= filter_start

        for point_key in ("year", "year_number", "effective_year"):
            point_year = self._coerce_card_year(entity.get(point_key))
            if point_year is not None:
                return filter_start <= point_year <= filter_end

        return False

    def _matches_browser_filters(self, entity, dataset_name):
        if entity is None:
            return False

        if not self._entity_exists_during_browser_period(entity):
            return False

        if self.browser_filter_dataset != "all" and dataset_name != self.browser_filter_dataset:
            return False

        if self.browser_filter_incomplete_only and not self._entity_missing_scalar_count(entity, dataset_name):
            return False

        query = self.browser_search_query.strip().lower()
        if query:
            haystack = " ".join(
                [
                    self._entity_display_label(entity),
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("id", "")),
                    str(entity.get("type", "")),
                ]
            ).lower()
            if not self._query_matches_text(query, haystack):
                return False

        return True

    def _matches_schema_browser_filters(self, schema_name, schema):
        if self.browser_period_filter and self.browser_filter_dataset != "schemas":
            return False

        if self.browser_filter_dataset not in {"all", "schemas"}:
            return False

        query = self.browser_search_query.strip().lower()
        if not query:
            return True

        fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
        haystack = " ".join(
            [
                str(schema_name),
                str(schema.get("schema", "")) if isinstance(schema, dict) else "",
                str(schema.get("extends", "")) if isinstance(schema, dict) else "",
                " ".join(str(field_name) for field_name in fields.keys()),
            ]
        ).lower()
        return self._query_matches_text(query, haystack)

    def _build_schema_browser_items(self):
        items = []

        for schema_name, schema in sorted(self.schema_loader.schemas.items()):
            if str(schema_name).strip().lower() == "production":
                continue
            if not self._matches_schema_browser_filters(schema_name, schema):
                continue

            field_count = len(schema.get("fields", {}) if isinstance(schema, dict) else {})
            items.append(
                {
                    "kind": "schema",
                    "entity_id": self._schema_card_id(schema_name),
                    "schema_name": schema_name,
                    "text": f"  {schema_name} [{field_count} fields]",
                    "missing_count": 0,
                    "is_incomplete": False,
                }
            )

        return items

    def _resolve_schema_for_entity(self, entity, dataset_name):
        candidates = []
        entity_type = entity.get("type")
        for name in (entity_type, dataset_name):
            if not name:
                continue
            normalized = str(name).strip().lower()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
            if normalized.endswith("s"):
                singular = normalized[:-1]
                if singular and singular not in candidates:
                    candidates.append(singular)
            else:
                plural = f"{normalized}s"
                if plural not in candidates:
                    candidates.append(plural)

        for candidate in candidates:
            schema = self.schema_loader.get_schema(candidate)
            if schema:
                return schema
        return None

    def _collect_schema_fields(self, schema, seen=None):
        if not schema:
            return {}
        if seen is None:
            seen = set()
        schema_name = schema.get("schema")
        if schema_name in seen:
            return {}
        if schema_name:
            seen.add(schema_name)
        fields = {}
        extends_name = schema.get("extends")
        if extends_name:
            fields.update(self._collect_schema_fields(self.schema_loader.get_schema(extends_name), seen=seen))
        fields.update(schema.get("fields", {}))
        return fields

    def _entity_missing_scalar_count(self, entity, dataset_name):
        schema = self._resolve_schema_for_entity(entity, dataset_name)
        field_specs = self._collect_schema_fields(schema)
        if dataset_name == "ideas":
            field_specs = {
                key: value
                for key, value in field_specs.items()
                if key in self.IDEA_GENERIC_FIELDS or key in {"id", "type"}
            }
        if dataset_name == "species":
            field_specs = {
                key: value
                for key, value in field_specs.items()
                if key not in {"pretty_name", "name"}
            }
        if dataset_name == "locations":
            field_specs = {
                key: value
                for key, value in field_specs.items()
                if self._is_location_field_relevant(entity, key)
            }
        missing = 0
        for field_key, spec in field_specs.items():
            if field_key in {
                "card_color",
                "card_header_color",
                "three_word_description",
                "wiki_field_colors",
                "wiki_link_color",
            }:
                continue
            field_type = spec.get("type")
            if field_type not in {None, "string", "number", "text"}:
                continue
            value = entity.get(field_key)
            if value is None:
                missing += 1
            elif isinstance(value, str) and not value.strip():
                missing += 1
        return missing

    def _is_location_field_relevant(self, entity, field_key):
        if not isinstance(entity, dict):
            return True

        class_key = str(
            entity.get("location_class")
            or entity.get("body_class")
            or ""
        ).strip().lower().replace(" ", "_").replace("-", "_")
        surface_classes = {
            "continent",
            "country",
            "state",
            "region",
            "city",
            "quarter",
            "site",
            "macro_site",
            "internal_passage",
            "island_chain",
            "atoll",
            "cluster",
        }
        orbital_classes = {
            "star_system",
            "stellar_system",
            "star",
            "planet",
            "moon",
            "dwarf_planet",
            "asteroid",
            "comet",
            "orbital_body",
        }
        building_only = {"building_class"}
        room_only = {"room_class", "floor_index", "floor_label", "room_number"}
        orbital_only = {
            "system_role",
            "system_class",
            "star_system",
            "body_class",
            "parent_body",
            "location_entity",
            "legacy_system_entity_id",
            "derived_from_system_body",
            "star_class",
            "spectral_class",
            "luminosity_solar",
            "habitable_zone_inner_au",
            "habitable_zone_outer_au",
            "stellar_neighbours",
            "radius_m",
            "semi_major_axis_m",
            "eccentricity",
            "inclination_deg",
            "longitude_of_ascending_node_deg",
            "argument_of_periapsis_deg",
            "mean_anomaly_deg_at_epoch",
            "display_color",
            "mass_kg",
        }

        if class_key in surface_classes:
            return field_key not in (building_only | room_only | orbital_only)
        if class_key == "building":
            return field_key not in (room_only | orbital_only)
        if class_key == "room":
            return field_key not in orbital_only
        if class_key in orbital_classes:
            return field_key not in (building_only | room_only)
        return field_key not in (building_only | room_only)

    def _location_tree_entity_matches(self, entity, dataset_name):
        if entity is None:
            return False

        if not self._entity_exists_during_browser_period(entity):
            return False

        is_system_like = bool(entity.get("system_role"))
        if self.browser_filter_dataset == "systems" and not is_system_like:
            return False

        if self.browser_filter_dataset not in {"all", "locations", "systems"}:
            return False

        if self.browser_filter_incomplete_only and not self._entity_missing_scalar_count(entity, dataset_name):
            return False

        query = self.browser_search_query.strip().lower()
        if query:
            haystack = " ".join(
                [
                    self._entity_display_label(entity),
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("id", "")),
                    str(entity.get("type", "")),
                    str(entity.get("system_role", "")),
                    str(entity.get("system_class", "")),
                    str(entity.get("body_class", "")),
                    str(entity.get("location_class", "")),
                    str(entity.get("location_role", "")),
                ]
            ).lower()
            if not self._query_matches_text(query, haystack):
                return False

        return True

    def _location_tree_auto_reveal_descendants(self):
        return bool(self.browser_search_query.strip() or self.browser_filter_incomplete_only)

    def _location_tree_item(self, entity, dataset_name, depth, expandable, expanded, meta_label=None):
        label = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
        entity_class = meta_label or self._entity_class_label(dataset_name, entity)
        missing_count = self._entity_missing_scalar_count(entity, dataset_name)
        return {
            "kind": "tree_entity",
            "entity_id": entity.get("id"),
            "dataset_name": dataset_name,
            "text": label,
            "meta_text": f"[{entity_class}]",
            "missing_count": missing_count,
            "is_incomplete": missing_count > 0,
            "depth": depth,
            "expandable": expandable,
            "expanded": expanded,
        }

    def _material_tree_entity_matches(self, entity):
        return self._matches_browser_filters(entity, "materials")

    def _material_tree_auto_reveal_descendants(self):
        return bool(self.browser_search_query.strip() or self.browser_filter_incomplete_only)

    def _material_hierarchy_sort_key(self, entity):
        label = self._entity_display_label(entity, fallback=entity.get("id", "")).lower()
        return (label, str(entity.get("id", "")))

    def _material_tree_item(self, entity, depth, expandable, expanded):
        return self._location_tree_item(
            entity,
            "materials",
            depth,
            expandable,
            expanded,
            meta_label=self._entity_class_label("materials", entity),
        )

    def _build_material_browser_items(self, world_model):
        """Build the canonical material taxonomy for the repository browser.

        Materials deliberately have one display parent: ``canonical_parent``
        when present, otherwise the first resolvable ``parents`` relation.
        Engineering properties remain tags, so the repository stays a readable
        tree rather than duplicating an alloy under several property branches.
        """
        if world_model is None:
            return []

        material_by_id = {
            str(entity.get("id")): entity
            for entity in world_model.get_entities_by_dataset("materials")
            if isinstance(entity, dict) and entity.get("id")
        }
        material_entities = list(material_by_id.values())
        children_by_parent = {}
        parent_id_by_child = {}

        def relation_values(value):
            if value is None:
                return []
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                candidate = value.get("id") or value.get("entity_id") or value.get("target")
                return [candidate] if candidate else []
            if isinstance(value, (list, tuple, set)):
                values = []
                for item in value:
                    values.extend(relation_values(item))
                return values
            return []

        def structural_parent_id(entity):
            entity_id = str(entity.get("id"))
            candidates = relation_values(entity.get("canonical_parent"))
            candidates.extend(relation_values(entity.get("parents")))
            for parent_id in candidates:
                parent_id = str(parent_id)
                if parent_id and parent_id != entity_id and parent_id in material_by_id:
                    return parent_id
            return None

        for entity in material_entities:
            entity_id = str(entity.get("id"))
            parent_id = structural_parent_id(entity)
            if parent_id:
                parent_id_by_child[entity_id] = parent_id
                children_by_parent.setdefault(parent_id, []).append(entity)

        for parent_id, child_list in children_by_parent.items():
            unique_children = {str(child.get("id")): child for child in child_list}
            child_list[:] = sorted(unique_children.values(), key=self._material_hierarchy_sort_key)

        def material_subtree_matches(entity, ancestry=None):
            ancestry = set(ancestry or ())
            entity_id = str(entity.get("id"))
            if not entity_id or entity_id in ancestry:
                return False
            ancestry.add(entity_id)
            if self._material_tree_entity_matches(entity):
                return True
            return any(
                material_subtree_matches(child, ancestry)
                for child in children_by_parent.get(entity_id, [])
            )

        auto_reveal = self._material_tree_auto_reveal_descendants()
        state = self.browser_tree_state.setdefault("materials", {})
        emitted_ids = set()
        items = []

        def add_material_subtree(entity, depth, ancestry=None):
            ancestry = set(ancestry or ())
            entity_id = str(entity.get("id"))
            if not entity_id or entity_id in emitted_ids or entity_id in ancestry:
                return
            ancestry.add(entity_id)

            children = children_by_parent.get(entity_id, [])
            descendant_match = any(material_subtree_matches(child) for child in children)
            if not self._material_tree_entity_matches(entity) and not descendant_match:
                return

            visible_children = [
                child for child in children
                if self._material_tree_entity_matches(child) or material_subtree_matches(child)
            ]
            expandable = bool(visible_children)
            # Show the complete taxonomy on first open.  Once the user toggles
            # a branch, its explicit state is preserved independently.
            expanded = state.get(entity_id, expandable)
            items.append(self._material_tree_item(entity, depth, expandable, expanded))
            emitted_ids.add(entity_id)

            if expandable and (expanded or (auto_reveal and descendant_match)):
                for child in visible_children:
                    add_material_subtree(child, depth + 1, ancestry)

        root_materials = sorted(
            [
                entity for entity in material_entities
                if str(entity.get("id")) not in parent_id_by_child
            ],
            key=self._material_hierarchy_sort_key,
        )

        reachable_ids = set()

        def collect_reachable(entity, ancestry=None):
            ancestry = set(ancestry or ())
            entity_id = str(entity.get("id"))
            if not entity_id or entity_id in ancestry or entity_id in reachable_ids:
                return
            ancestry.add(entity_id)
            reachable_ids.add(entity_id)
            for child in children_by_parent.get(entity_id, []):
                collect_reachable(child, ancestry)

        for material_entity in root_materials:
            collect_reachable(material_entity)
        for material_entity in root_materials:
            add_material_subtree(material_entity, 0)

        # Preserve access to malformed or cyclic legacy entries rather than
        # silently losing them from the repository.
        for material_entity in sorted(material_entities, key=self._material_hierarchy_sort_key):
            if (
                str(material_entity.get("id")) not in reachable_ids
                and str(material_entity.get("id")) not in emitted_ids
            ):
                add_material_subtree(material_entity, 0)

        return items

    def _canonical_location_class_key(self, entity):
        if not isinstance(entity, dict):
            return "entity"

        system_role = str(entity.get("system_role") or "").strip().lower()
        if system_role == "star_system":
            return "star_system"
        if system_role == "orbital_body":
            raw_class = entity.get("body_class") or entity.get("location_class") or "orbital_body"
        else:
            raw_class = (
                entity.get("location_class")
                or entity.get("system_class")
                or entity.get("body_class")
                or entity.get("type")
                or "entity"
            )

        class_key = str(raw_class or "entity").strip().lower().replace(" ", "_").replace("-", "_")
        class_aliases = {
            "stellar_system": "star_system",
            "starsystem": "star_system",
            "star_system": "star_system",
            "solar_system": "star_system",
            "orbital_body": "orbital_body",
            "celestial_body": "orbital_body",
        }
        return class_aliases.get(class_key, class_key)

    def _location_class_display_label(self, entity):
        class_key = self._canonical_location_class_key(entity)
        display_labels = {
            "star_system": "Star System",
            "orbital_body": "Orbital Body",
            "dwarf_planet": "Dwarf Planet",
            "island_chain": "Island Chain",
            "macro_site": "Macro Site",
            "internal_passage": "Internal Passage",
            "stellar_cluster": "Stellar Cluster",
            "galaxy_cluster": "Galaxy Cluster",
        }
        return display_labels.get(class_key, class_key.replace("_", " ").title())

    def _location_browser_domain(self, entity):
        system_role = str(entity.get("system_role") or "").strip().lower() if isinstance(entity, dict) else ""
        if system_role in {"star_system", "orbital_body"}:
            return "orbit"
        class_key = self._canonical_location_class_key(entity)
        if class_key in self.ORBIT_LOCATION_CLASS_KEYS:
            return "orbit"
        return "surface"

    def _location_browser_domain_label(self, domain):
        return "Orbit" if domain == "orbit" else "Surface"

    def _location_hierarchy_sort_key(self, entity):
        label = self._entity_display_label(entity, fallback=entity.get("id", "")).lower()
        return (label, str(entity.get("id", "")))

    def _is_sol_location(self, entity):
        if not isinstance(entity, dict):
            return False
        entity_id = str(entity.get("id") or "").strip().lower()
        label = self._entity_display_label(entity, fallback=entity_id).strip().lower()
        return entity_id in {"system_sol", "sol", "solar_system"} or label in {"sol", "sol system", "solar system"}

    def _is_star_system_location(self, entity):
        if not isinstance(entity, dict):
            return False
        role = str(entity.get("system_role") or entity.get("location_role") or "").strip().lower()
        return role == "star_system" or self._canonical_location_class_key(entity) in {"star_system", "stellar_system"}

    def _coerce_float(self, value):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _stellar_distance_to_sol(self, entity):
        if self._is_sol_location(entity):
            return 0.0
        entity_id = str(entity.get("id") or "").strip().lower() if isinstance(entity, dict) else ""

        def distance_from_rows(rows, target_ids):
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                return None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                target_id = str(row.get("system") or row.get("id") or row.get("entity_id") or "").strip().lower()
                if target_id not in target_ids:
                    continue
                distance = self._coerce_float(row.get("distance_ly") or row.get("distance"))
                if distance is not None:
                    return distance
            return None

        rows = entity.get("stellar_neighbours") if isinstance(entity, dict) else None
        own_distance = distance_from_rows(rows, {"system_sol", "sol", "solar_system"})
        if own_distance is not None:
            return own_distance

        sol = self.world_model.get_entity("system_sol") if self.world_model is not None else None
        if isinstance(sol, dict) and entity_id:
            return distance_from_rows(sol.get("stellar_neighbours"), {entity_id})
        return None

    def _orbital_distance_m(self, entity):
        if not isinstance(entity, dict):
            return None
        direct = self._coerce_float(entity.get("semi_major_axis_m"))
        if direct is not None:
            return direct
        periapsis = self._coerce_float(entity.get("periapsis_m") or entity.get("perihelion_m"))
        apoapsis = self._coerce_float(entity.get("apoapsis_m") or entity.get("aphelion_m"))
        if periapsis is not None and apoapsis is not None:
            return (periapsis + apoapsis) / 2.0
        return None

    def _location_hierarchy_sort_key_for_parent(self, entity, parent_entity=None):
        alpha_key = self._location_hierarchy_sort_key(entity)
        if self._is_star_system_location(entity):
            distance = self._stellar_distance_to_sol(entity)
            return (
                0 if self._is_sol_location(entity) else 1,
                0 if distance is not None else 1,
                distance if distance is not None else float("inf"),
                *alpha_key,
            )

        parent_is_orbit = self._location_browser_domain(parent_entity) == "orbit" if parent_entity is not None else False
        entity_is_orbit = self._location_browser_domain(entity) == "orbit"
        if parent_is_orbit or entity_is_orbit:
            distance = self._orbital_distance_m(entity)
            return (
                0 if distance is not None else 1,
                distance if distance is not None else float("inf"),
                *alpha_key,
            )

        return (2, *alpha_key)

    def _build_location_browser_items(self, world_model):
        items = []

        if world_model is None:
            return items

        raw_location_entities = world_model.get_entities_by_dataset("locations")
        location_by_id = {
            entity.get("id"): entity
            for entity in raw_location_entities
            if isinstance(entity, dict) and entity.get("id")
        }
        alias_to_location_id = {
            str(alias): str(canonical_id)
            for alias, canonical_id in getattr(world_model.loader, "entity_aliases", {}).items()
        }

        def canonical_location_id(entity_id):
            if not entity_id:
                return entity_id
            return alias_to_location_id.get(str(entity_id), str(entity_id))

        location_entities = list(location_by_id.values())
        children_by_parent = {}
        parent_id_by_child = {}

        def relation_values(value):
            if value is None:
                return []
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                candidate = value.get("id") or value.get("entity_id") or value.get("target")
                return [candidate] if candidate else []
            if isinstance(value, (list, tuple, set)):
                values = []
                for item in value:
                    values.extend(relation_values(item))
                return values
            return []

        def structural_parent_id(entity):
            entity_id = canonical_location_id(entity.get("id"))
            for field_key in ("parent_cluster", "parent_location", "parent_entity", "parent_body"):
                for parent_id in relation_values(entity.get(field_key)):
                    parent_id = canonical_location_id(parent_id)
                    if parent_id and parent_id != entity_id and parent_id in location_by_id:
                        return parent_id

            if entity.get("system_role") == "orbital_body":
                for parent_id in relation_values(entity.get("star_system")):
                    parent_id = canonical_location_id(parent_id)
                    if parent_id and parent_id != entity_id and parent_id in location_by_id:
                        return parent_id

            for parent_id in relation_values(entity.get("parents")):
                parent_id = canonical_location_id(parent_id)
                if parent_id and parent_id != entity_id and parent_id in location_by_id:
                    return parent_id

            return None

        for entity in location_entities:
            entity_id = canonical_location_id(entity.get("id"))
            if not entity_id:
                continue
            parent_id = structural_parent_id(entity)
            if parent_id:
                parent_id_by_child[entity_id] = parent_id
                children_by_parent.setdefault(parent_id, []).append(entity)

        for parent_entity in location_entities:
            parent_id = canonical_location_id(parent_entity.get("id"))
            if not parent_id:
                continue
            for child_field in ("children", "offspring"):
                for child_id in relation_values(parent_entity.get(child_field)):
                    child_id = canonical_location_id(child_id)
                    child_entity = location_by_id.get(child_id)
                    if not child_entity or child_id == parent_id:
                        continue
                    if child_id in parent_id_by_child:
                        continue
                    parent_id_by_child[child_id] = parent_id
                    children = children_by_parent.setdefault(parent_id, [])
                    if child_entity not in children:
                        children.append(child_entity)

        for parent_id, child_list in children_by_parent.items():
            unique_children = {}
            for child in child_list:
                child_id = canonical_location_id(child.get("id"))
                if child_id:
                    unique_children[child_id] = child
            parent_entity = location_by_id.get(parent_id)
            child_list[:] = sorted(
                unique_children.values(),
                key=lambda child: self._location_hierarchy_sort_key_for_parent(child, parent_entity),
            )

        auto_reveal = self._location_tree_auto_reveal_descendants()
        emitted_ids = set()

        def location_subtree_matches(location_entity, seen=None):
            if seen is None:
                seen = set()
            location_id = canonical_location_id(location_entity.get("id"))
            if not location_id or location_id in seen:
                return False
            seen.add(location_id)

            if self._location_tree_entity_matches(location_entity, "locations"):
                return True

            for child in children_by_parent.get(location_id, []):
                if location_subtree_matches(child, seen=seen):
                    return True
            return False

        def child_matches_for_display(child):
            return self._location_tree_entity_matches(child, "locations") or location_subtree_matches(child)

        def location_supports_orbit_surface_groups(location_entity):
            if self._location_browser_domain(location_entity) != "orbit":
                return False
            class_key = self._canonical_location_class_key(location_entity)
            return class_key not in {"cluster", "galaxy", "galaxy_cluster", "star_system", "stellar_cluster", "system"}

        def add_group_label(label, depth):
            items.append(
                {
                    "kind": "label",
                    "text": f"({label})",
                    "depth": depth,
                    "location_group": True,
                }
            )

        def add_location_subtree(location_entity, depth):
            location_id = canonical_location_id(location_entity.get("id"))
            if not location_id or location_id in emitted_ids:
                return

            children = children_by_parent.get(location_id, [])
            descendant_match = any(location_subtree_matches(child) for child in children)
            if not self._location_tree_entity_matches(location_entity, "locations") and not descendant_match:
                return

            visible_children = [child for child in children if child_matches_for_display(child)]
            expandable = len(visible_children) > 0
            expanded = self._is_expanded(location_id)
            items.append(
                self._location_tree_item(
                    location_entity,
                    "locations",
                    depth,
                    expandable,
                    expanded,
                    meta_label=self._location_class_display_label(location_entity),
                )
            )
            emitted_ids.add(location_id)

            if expandable and (expanded or (auto_reveal and descendant_match)):
                if location_supports_orbit_surface_groups(location_entity):
                    orbital_children = [
                        child for child in visible_children
                        if self._location_browser_domain(child) == "orbit"
                    ]
                    surface_children = [
                        child for child in visible_children
                        if self._location_browser_domain(child) == "surface"
                    ]
                    if orbital_children:
                        add_group_label("Orbit", depth + 1)
                        for child in orbital_children:
                            add_location_subtree(child, depth + 2)
                    if surface_children and self.browser_filter_dataset != "systems":
                        add_group_label("Surface", depth + 1)
                        for child in surface_children:
                            add_location_subtree(child, depth + 2)
                else:
                    for child in visible_children:
                        add_location_subtree(child, depth + 1)

        root_locations = sorted(
            [
                location for location in location_entities
                if canonical_location_id(location.get("id"))
                and canonical_location_id(location.get("id")) not in parent_id_by_child
            ],
            key=lambda location: self._location_hierarchy_sort_key_for_parent(location),
        )
        for location_entity in root_locations:
            add_location_subtree(location_entity, 0)

        return items

    def _dataset_display_label(self, dataset_name):
        return dataset_name.replace("_", " ").title()

    def _entity_class_label(self, dataset_name, entity):
        if dataset_name == "locations":
            return self._location_class_display_label(entity)
        if dataset_name == "vehicles":
            return entity.get("vehicle_class", entity.get("type", "entity"))
        if dataset_name == "components":
            return entity.get("component_class", entity.get("type", "entity"))
        if dataset_name == "ideas":
            return entity.get("idea_class", entity.get("type", "entity"))
        if dataset_name == "species":
            return entity.get("species_class", entity.get("type", "entity"))
        if dataset_name == "materials":
            return entity.get("material_subclass", entity.get("type", "material"))
        if dataset_name == "periods":
            return entity.get("period_class", entity.get("type", "period"))
        if dataset_name == "systems":
            if entity.get("system_role") == "star_system":
                return entity.get("system_class", entity.get("type", "entity"))
            if entity.get("system_role") == "orbital_body":
                return entity.get("body_class", entity.get("type", "entity"))
        return entity.get("type", "entity")

    def _event_tree_item(self, entity, depth, *, expandable=False, expanded=False, meta_label=None):
        dataset_name = entity.get("_dataset", "events")
        label = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
        entity_class = meta_label or self._entity_class_label(dataset_name, entity)
        missing_count = 0
        if dataset_name == "events":
            missing_count = self._entity_missing_scalar_count(entity, "events")
        return {
            "kind": "tree_entity",
            "entity_id": entity.get("id"),
            "dataset_name": dataset_name,
            "text": label,
            "meta_text": f"[{entity_class}]",
            "missing_count": missing_count,
            "is_incomplete": missing_count > 0,
            "depth": depth,
            "expandable": bool(expandable),
            "expanded": bool(expanded),
        }

    def _build_event_browser_items(self, world_model):
        """Build major period -> century -> year -> event repository rows."""
        events = [
            entity
            for entity in world_model.get_entities_by_dataset("events")
            if self._matches_browser_filters(entity, "events")
        ]
        events.sort(
            key=lambda entity: (
                event_anchor_year(entity) is None,
                event_anchor_year(entity) if event_anchor_year(entity) is not None else 0,
                self._entity_display_label(entity, fallback=entity.get("id", "")).lower(),
            )
        )

        scheduled = {}
        unscheduled = []
        for event in events:
            year = event_anchor_year(event)
            if year is None:
                unscheduled.append(event)
                continue
            period = top_level_period_for_year(year, world_model.MAJOR_PERIODS)
            period_id = str(period["entity_id"]) if period is not None else None
            century_number = century_number_for_year(year)
            scheduled.setdefault(period_id, {}).setdefault(century_number, {}).setdefault(year, []).append(event)

        state = self.browser_tree_state.setdefault("periods", {})
        auto_reveal = bool(self.browser_search_query.strip() or self.browser_period_filter)
        items = []

        def period_matches(entity):
            query = self.browser_search_query.strip()
            return not query or self._query_matches_text(
                query,
                " ".join(
                    (
                        self._entity_display_label(entity, fallback=entity.get("id", "")),
                        str(entity.get("period_class", "")),
                        str(entity.get("start_year", "")),
                        str(entity.get("end_year", "")),
                    )
                ),
            )

        def add_year_branch(period_id, century_number, years, depth):
            century = world_model.get_entity(century_entity_id(century_number))
            if not isinstance(century, dict):
                return
            century_children_match = bool(years)
            if not century_children_match and not period_matches(century):
                return
            century_id = str(century["id"])
            century_expanded = state.get(century_id, True)
            items.append(
                self._event_tree_item(
                    century,
                    depth,
                    expandable=bool(years),
                    expanded=century_expanded,
                    meta_label="Century",
                )
            )
            if not years or not (century_expanded or auto_reveal):
                return

            for year in sorted(years):
                year_period = world_model.get_entity(year_entity_id(year))
                if not isinstance(year_period, dict):
                    continue
                year_events = years[year]
                year_id = str(year_period["id"])
                year_expanded = state.get(year_id, True)
                items.append(
                    self._event_tree_item(
                        year_period,
                        depth + 1,
                        expandable=bool(year_events),
                        expanded=year_expanded,
                        meta_label="Year",
                    )
                )
                if year_events and (year_expanded or auto_reveal):
                    for event in year_events:
                        items.append(self._event_tree_item(event, depth + 2, meta_label="Event"))

        for period_id in TOP_LEVEL_PERIOD_IDS:
            period = world_model.get_entity(period_id)
            if not isinstance(period, dict):
                continue
            century_groups = scheduled.get(period_id, {})
            if (self.browser_search_query.strip() or self.browser_period_filter) and not century_groups and not period_matches(period):
                continue
            period_expanded = state.get(period_id, True)
            items.append(
                self._event_tree_item(
                    period,
                    0,
                    expandable=bool(century_groups),
                    expanded=period_expanded,
                    meta_label="Major Period",
                )
            )
            if century_groups and (period_expanded or auto_reveal):
                for century_number in sorted(century_groups):
                    add_year_branch(period_id, century_number, century_groups[century_number], 1)

        for century_number in sorted(scheduled.get(None, {})):
            add_year_branch(None, century_number, scheduled[None][century_number], 0)

        for event in unscheduled:
            items.append(self._event_tree_item(event, 0, meta_label="Unscheduled Event"))
        return items

    def _build_browser_items(self, world_model):
        items = [
            {"kind": "label", "text": "Grouping: hierarchy preview"},
            {"kind": "spacer"},
        ]

        if world_model is None:
            return items

        schema_items = self._build_schema_browser_items()
        if self.browser_filter_dataset == "schemas":
            items.append({"kind": "section", "text": "Schemas"})
            items.extend(schema_items)
            items.append({"kind": "spacer"})
            return items

        dataset_names = sorted(name for name in world_model.get_dataset_names() if name != "production")

        preferred_order = [
            "ideas",
            "locations",
            "vehicles",
            "components",
        ]
        ordered_names = [name for name in preferred_order if name in dataset_names]
        ordered_names += [name for name in dataset_names if name not in ordered_names]
        hide_empty_sections = bool(self.browser_search_query.strip())

        for dataset_name in ordered_names:
            if dataset_name == "systems":
                continue

            if dataset_name == "locations":
                if self.browser_filter_dataset not in {"all", "locations", "systems"}:
                    continue
                dataset_items = self._build_location_browser_items(world_model)
                if hide_empty_sections and not dataset_items:
                    continue
                items.append({"kind": "section", "text": "Locations / Systems"})
                items.extend(dataset_items)
                items.append({"kind": "spacer"})
                continue

            if dataset_name == "materials":
                if self.browser_filter_dataset not in {"all", "materials"}:
                    continue
                dataset_items = self._build_material_browser_items(world_model)
                if hide_empty_sections and not dataset_items:
                    continue
                items.append({"kind": "section", "text": "Materials"})
                items.extend(dataset_items)
                items.append({"kind": "spacer"})
                continue

            if dataset_name == "events":
                if self.browser_filter_dataset not in {"all", "events"}:
                    continue
                dataset_items = self._build_event_browser_items(world_model)
                if hide_empty_sections and not dataset_items:
                    continue
                items.append({"kind": "section", "text": "Events"})
                items.extend(dataset_items)
                items.append({"kind": "spacer"})
                continue

            # Periods are already the clickable hierarchy nodes in Events.
            # Keep a dedicated Periods filter for direct browsing without
            # duplicating every generated year in the default "All" view.
            if dataset_name == "periods" and self.browser_filter_dataset == "all":
                continue

            if self.browser_filter_dataset != "all" and dataset_name != self.browser_filter_dataset:
                continue

            dataset_items = []
            if dataset_name == "periods":
                entities = sorted(
                    world_model.get_entities_by_dataset(dataset_name),
                    key=lambda entity: (
                        self._coerce_card_year(entity.get("start_year")) is None,
                        self._coerce_card_year(entity.get("start_year")) or 0,
                        self._entity_display_label(entity, fallback=entity.get("id", "")).lower(),
                    ),
                )
            else:
                entities = sorted(
                    world_model.get_entities_by_dataset(dataset_name),
                    key=lambda entity: self._entity_display_label(entity, fallback=entity.get("id", "")).lower()
                )

            for entity in entities:
                if not self._matches_browser_filters(entity, dataset_name):
                    continue

                label = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
                entity_class = self._entity_class_label(dataset_name, entity)
                missing_count = self._entity_missing_scalar_count(entity, dataset_name)

                dataset_items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "dataset_name": dataset_name,
                        "text": f"  {label} [{entity_class}]",
                        "missing_count": missing_count,
                        "is_incomplete": missing_count > 0,
                    }
                )

            if hide_empty_sections and not dataset_items:
                continue

            items.append({"kind": "section", "text": self._dataset_display_label(dataset_name)})
            items.extend(dataset_items)
            items.append({"kind": "spacer"})

        if schema_items:
            items.append({"kind": "section", "text": "Schemas"})
            items.extend(schema_items)
            items.append({"kind": "spacer"})

        return items
