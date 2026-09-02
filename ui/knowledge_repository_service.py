import copy
import json
import os


class KnowledgeRepositoryService:
    def __init__(self, host):
        object.__setattr__(self, "host", host)

    def __getattr__(self, name):
        return getattr(self.host, name)

    def __setattr__(self, name, value):
        setattr(self.host, name, value)

    def _load_card_drafts(self):
        try:
            with open(self.DRAFT_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}
        drafts = data.get("drafts", data)
        return drafts if isinstance(drafts, dict) else {}

    def _write_card_drafts(self):
        draft_path = str(self.DRAFT_CACHE_PATH)
        os.makedirs(os.path.dirname(draft_path), exist_ok=True)
        payload = {"drafts": self.card_drafts}
        temporary_path = f"{draft_path}.{os.getpid()}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, draft_path)

    def _entity_for_card(self, card):
        if card is None:
            return None

        card_view = card.get("card_view")
        if card_view is not None:
            entity = getattr(card_view, "entity", None)
            if entity is not None:
                return entity

        if self.world_model is not None:
            return self.world_model.get_entity(card.get("entity_id"))
        return None

    def _draft_entity_snapshot(self, entity):
        if not isinstance(entity, dict):
            return {}
        return {key: value for key, value in entity.items() if not key.startswith("_")}

    def _replace_entity_id_reference_value(self, value, old_entity_id, new_entity_id):
        if isinstance(value, str):
            if value.strip() == old_entity_id:
                return new_entity_id, True
            return value, False

        if isinstance(value, list):
            changed = False
            replaced = []
            for item in value:
                new_item, item_changed = self._replace_entity_id_reference_value(
                    item,
                    old_entity_id,
                    new_entity_id,
                )
                replaced.append(new_item)
                changed = changed or item_changed
            return replaced, changed

        if isinstance(value, dict):
            changed = False
            replaced = {}
            for key, item in value.items():
                new_key = new_entity_id if isinstance(key, str) and key.strip() == old_entity_id else key
                new_item, item_changed = self._replace_entity_id_reference_value(
                    item,
                    old_entity_id,
                    new_entity_id,
                )
                replaced[new_key] = new_item
                changed = changed or item_changed or new_key != key
            return replaced, changed

        return value, False

    def _replace_entity_references(self, entity, old_entity_id, new_entity_id):
        if not isinstance(entity, dict) or not old_entity_id or not new_entity_id:
            return False

        changed = False
        for field_key, value in list(entity.items()):
            if field_key in {"id", "_dataset"}:
                continue
            new_value, value_changed = self._replace_entity_id_reference_value(
                value,
                old_entity_id,
                new_entity_id,
            )
            if value_changed:
                entity[field_key] = new_value
                changed = True
        return changed

    def _replace_draft_references(self, old_entity_id, new_entity_id):
        changed = False
        for draft in self.card_drafts.values():
            if not isinstance(draft, dict):
                continue
            draft_entity = draft.get("entity")
            if self._replace_entity_references(draft_entity, old_entity_id, new_entity_id):
                changed = True
        if changed:
            self.host._write_card_drafts()
        return changed

    def _rewrite_entity_id_references(self, old_entity_id, new_entity_id, renamed_entity_id=None):
        if (
            self.world_model is None
            or not old_entity_id
            or not new_entity_id
            or old_entity_id == new_entity_id
        ):
            return []

        changed_entities = []
        for entity in list(self.world_model.loader.entities.values()):
            if not isinstance(entity, dict):
                continue
            if self._replace_entity_references(entity, old_entity_id, new_entity_id):
                changed_entities.append(entity)

        self._replace_draft_references(old_entity_id, new_entity_id)

        changed_ids = {str(entity.get("id")) for entity in changed_entities if entity.get("id")}
        for card in self.cards:
            card_entity = self._entity_for_card(card)
            if isinstance(card_entity, dict) and str(card_entity.get("id")) in changed_ids:
                card["subtitle"] = self._card_subtitle_for_entity(card_entity)
                if card.get("is_draft_entity", False):
                    self.host._save_card_draft(card)

        for entity in changed_entities:
            entity_id = str(entity.get("id") or "")
            if entity_id:
                card = self._find_card_by_entity_id(entity_id)
                if card is not None and card.get("is_draft_entity", False):
                    continue
                self.host._persist_entity_to_repository(entity)

        if hasattr(self.world_model, "touch_degrees"):
            self.world_model.touch_degrees.refresh()
        if hasattr(self.world_model.loader, "build_reference_graph"):
            self.world_model.loader.build_reference_graph()

        return changed_entities

    def _save_card_draft(self, card):
        self._sync_species_identity(card)
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or not entity.get("id"):
            return False

        entity_id = str(entity["id"])
        id_change = card.get("pending_entity_id_change")
        if isinstance(id_change, dict):
            old_entity_id = id_change.get("old")
            if old_entity_id and old_entity_id != entity_id:
                self.card_drafts.pop(old_entity_id, None)
                if self.world_model is not None:
                    self.world_model.loader.entities.pop(old_entity_id, None)
                    self.world_model.loader.entities[entity_id] = entity
                card["entity_id"] = entity_id
                card.pop("pending_entity_id_change", None)

        active_field = card.get("active_edit_field")
        draft = dict(self.card_drafts.get(entity_id, {}))
        draft["entity"] = self._draft_entity_snapshot(entity)
        draft["dataset"] = entity.get("_dataset", entity.get("type", ""))
        draft["is_new_entry"] = bool(card.get("is_draft_entity", False) or draft.get("is_new_entry", False))

        edit_buffers = dict(draft.get("edit_buffers", {}))
        if active_field:
            edit_buffers[active_field] = {
                "text": card.get("edit_buffer", ""),
                "cursor": int(card.get("edit_cursor", 0)),
            }
        card["draft_edit_buffers"] = edit_buffers
        draft["edit_buffers"] = edit_buffers
        self.card_drafts[entity_id] = draft
        card["has_unsaved_draft"] = True
        self.host._write_card_drafts()
        return True

    def _remove_card_draft(self, entity_id):
        if not entity_id or entity_id not in self.card_drafts:
            return False
        del self.card_drafts[entity_id]
        for card in self.cards:
            if str(card.get("entity_id") or "") == str(entity_id):
                card["has_unsaved_draft"] = False
        self.host._write_card_drafts()
        return True

    def _apply_cached_draft_to_card(self, card):
        entity_id = card.get("entity_id")
        draft = self.card_drafts.get(entity_id)
        if not isinstance(draft, dict):
            return False

        draft_entity = draft.get("entity")
        entity = self._entity_for_card(card)
        if isinstance(entity, dict) and isinstance(draft_entity, dict):
            runtime_values = {
                key: value
                for key, value in entity.items()
                if str(key).startswith("_")
            }
            entity.clear()
            entity.update(runtime_values)
            entity.update(copy.deepcopy(draft_entity))
            entity["id"] = str(entity_id)

        edit_buffers = draft.get("edit_buffers", {})
        card["draft_edit_buffers"] = edit_buffers if isinstance(edit_buffers, dict) else {}
        card["is_draft_entity"] = bool(draft.get("is_new_entry", False))
        card["has_unsaved_draft"] = True
        return True

    def _hydrate_draft_entities(self, world_model):
        if world_model is None:
            return

        for entity_id, draft in self.card_drafts.items():
            if not isinstance(draft, dict) or not draft.get("is_new_entry", False):
                continue
            if world_model.get_entity(entity_id) is not None:
                continue

            entity = dict(draft.get("entity", {}))
            if not entity:
                continue
            entity["id"] = entity_id
            dataset_name = draft.get("dataset") or entity.get("type")
            if dataset_name == "ideas":
                for field_key in self.LEGACY_IDEA_FIELDS:
                    entity.pop(field_key, None)
            if dataset_name:
                entity["_dataset"] = dataset_name
                world_model.loader.datasets.setdefault(dataset_name, []).append(entity)
            world_model.loader.entities[entity_id] = entity

    def _persist_entity_to_repository(self, entity, previous_entity_id=None):
        if not isinstance(entity, dict):
            return False

        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        persisted = loader.persist_entity(entity, previous_entity_id=previous_entity_id)
        if persisted:
            mark_changed = getattr(self.world_model, "mark_repository_changed", None)
            if callable(mark_changed):
                mark_changed()
            else:
                self.world_model.repository_revision = getattr(self.world_model, "repository_revision", 0) + 1
        return persisted

    def _sync_bidirectional_relations(self, persist=True):
        if self.world_model is None or getattr(self.world_model, "loader", None) is None:
            return set()

        loader = self.world_model.loader
        entities = getattr(loader, "entities", {}) or {}
        changed_entity_ids = set()

        def relation_ids(value):
            if value is None:
                return []
            if isinstance(value, str):
                value = value.strip()
                return [value] if value else []
            if isinstance(value, dict):
                candidate = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
                return [str(candidate)] if candidate else []
            if isinstance(value, (list, tuple, set)):
                ids = []
                for item in value:
                    ids.extend(relation_ids(item))
                return ids
            return []

        def is_location(entity):
            return isinstance(entity, dict) and (
                entity.get("_dataset") == "locations"
                or entity.get("type") == "location"
            )

        def set_unique_list(entity, key, values):
            normalized = []
            entity_id = str(entity.get("id") or "")
            for value in values or []:
                value = str(value or "").strip()
                if value and value != entity_id and value not in normalized:
                    normalized.append(value)
            if not normalized and key not in entity:
                return
            if entity.get(key) == normalized:
                return
            if hasattr(loader, "set_literal"):
                changed_entity_ids.update(loader.set_literal(entity_id, key, normalized, persist=False))
            else:
                entity[key] = normalized
                changed_entity_ids.add(entity_id)

        for entity_id, entity in list(entities.items()):
            if not is_location(entity):
                continue

            for field_key in ("neighbours", "overlaps"):
                current_ids = relation_ids(entity.get(field_key))
                set_unique_list(entity, field_key, current_ids)
                for target_id in current_ids:
                    target = entities.get(target_id)
                    if not is_location(target):
                        continue
                    reciprocal = relation_ids(target.get(field_key))
                    if entity_id not in reciprocal:
                        if hasattr(loader, "set_relation"):
                            changed_entity_ids.update(
                                loader.set_relation(
                                    entity_id,
                                    field_key,
                                    target_id,
                                    reciprocal_field=field_key,
                                    persist=False,
                                )
                            )
                        else:
                            reciprocal.append(entity_id)
                            set_unique_list(target, field_key, reciprocal)

            constituent_ids = relation_ids(entity.get("constituents"))
            set_unique_list(entity, "constituents", constituent_ids)
            for child_id in constituent_ids:
                child = entities.get(child_id)
                if not is_location(child):
                    continue
                parents = relation_ids(child.get("parents"))
                if entity_id not in parents:
                    if hasattr(loader, "set_relation"):
                        changed_entity_ids.update(
                            loader.set_relation(child_id, "parents", entity_id, persist=False)
                        )
                    else:
                        parents.append(entity_id)
                        child["parents"] = parents
                        changed_entity_ids.add(child_id)
                if not child.get("parent_location"):
                    if hasattr(loader, "set_literal"):
                        changed_entity_ids.update(
                            loader.set_literal(child_id, "parent_location", entity_id, persist=False)
                        )
                    else:
                        child["parent_location"] = entity_id
                        changed_entity_ids.add(child_id)

        if hasattr(loader, "populate_offspring"):
            changed_entity_ids.update(loader.populate_offspring())

        if changed_entity_ids and persist:
            if hasattr(loader, "save_changed_dataset_files"):
                loader.save_changed_dataset_files(changed_entity_ids)
                failed_persist_ids = []
            else:
                failed_persist_ids = []
                for entity_id in sorted(changed_entity_ids):
                    entity = entities.get(entity_id)
                    if isinstance(entity, dict):
                        try:
                            self.host._persist_entity_to_repository(entity)
                        except OSError:
                            failed_persist_ids.append(entity_id)
            if failed_persist_ids:
                self.relation_link_status = (
                    "Relation sync skipped repository writes for "
                    + ", ".join(failed_persist_ids[:3])
                    + ("..." if len(failed_persist_ids) > 3 else "")
                )
        if changed_entity_ids:
            self.relation_tree_neighbor_cache = {}
            self.canvas_relation_edges = []
            if hasattr(loader, "build_reference_graph"):
                loader.build_reference_graph()
            mark_changed = getattr(self.world_model, "mark_repository_changed", None)
            if callable(mark_changed):
                mark_changed()
            else:
                self.world_model.repository_revision = getattr(self.world_model, "repository_revision", 0) + 1
            self._refresh_timeline_items()

        return changed_entity_ids

    def _persist_card_entity(self, card):
        if card is None:
            return False

        self._sync_species_identity(card)
        self._sync_card_wiki_mentions(card)
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False
        self._sync_stellar_class_profile(card, entity)
        card.pop("last_committed_field", None)

        id_change = card.get("pending_entity_id_change")
        previous_entity_id = None
        if isinstance(id_change, dict):
            previous_entity_id = id_change.get("old") or None

        current_entity_id = str(card.get("entity_id") or entity.get("id") or "")
        if previous_entity_id or not str(entity.get("id") or "").strip():
            normalized_entity_id = self._normalize_entity_id_for_save(
                entity,
                current_id=previous_entity_id or current_entity_id,
            )
            if normalized_entity_id and normalized_entity_id != str(entity.get("id") or ""):
                previous_entity_id = previous_entity_id or current_entity_id
                entity["id"] = normalized_entity_id
                card["pending_entity_id_change"] = {
                    "old": previous_entity_id,
                    "new": normalized_entity_id,
                }

        persisted = self.host._persist_entity_to_repository(entity, previous_entity_id=previous_entity_id)
        if persisted and isinstance(entity, dict):
            self.relation_tree_neighbor_cache = {}
            self.canvas_relation_edges = []
            new_entity_id = str(entity.get("id"))
            old_entity_id = previous_entity_id

            if old_entity_id and old_entity_id != new_entity_id:
                if self.world_model is not None:
                    self.world_model.loader.entities.pop(old_entity_id, None)
                    self.world_model.loader.entities[new_entity_id] = entity

                card["entity_id"] = new_entity_id
                self.selected_entity_id = new_entity_id
                self.active_card_drag_id = new_entity_id if self.active_card_drag_id == old_entity_id else self.active_card_drag_id
                self.active_card_resize_id = new_entity_id if self.active_card_resize_id == old_entity_id else self.active_card_resize_id
                self._rewrite_entity_id_references(
                    old_entity_id,
                    new_entity_id,
                    renamed_entity_id=new_entity_id,
                )
                self._remove_card_draft(old_entity_id)

            card.pop("pending_entity_id_change", None)
            card["is_draft_entity"] = False
            remaining_buffers = card.get("draft_edit_buffers", {})
            if isinstance(remaining_buffers, dict) and remaining_buffers:
                entity_id = str(entity.get("id"))
                draft = dict(self.card_drafts.get(entity_id, {}))
                draft["entity"] = self._draft_entity_snapshot(entity)
                draft["dataset"] = entity.get("_dataset", entity.get("type", ""))
                draft["is_new_entry"] = False
                draft["edit_buffers"] = remaining_buffers
                self.card_drafts[entity_id] = draft
                self.host._write_card_drafts()
            else:
                card["draft_edit_buffers"] = {}
                self._remove_card_draft(entity.get("id"))
        return persisted

    def _persist_card_palette(self, card):
        entity = self._entity_for_card(card)
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        fast_persist = getattr(loader, "persist_entity_palette", None)
        if isinstance(entity, dict) and callable(fast_persist) and fast_persist(entity):
            mark_changed = getattr(self.world_model, "mark_repository_changed", None)
            if callable(mark_changed):
                mark_changed()
            else:
                self.world_model.repository_revision = getattr(self.world_model, "repository_revision", 0) + 1
            self._refresh_material_catalog_if_needed(entity)
            return True
        persisted = self._persist_card_entity(card)
        if persisted:
            self._refresh_material_catalog_if_needed(entity)
        return persisted

    def _refresh_material_catalog_if_needed(self, entity):
        # natural_materials.MATERIAL_BY_ID is a process-local cache built
        # once at WorldModel construction; a material color edited from its
        # card would otherwise not show up on the map until an app restart.
        if self.world_model is None or self._dataset_name_for_entity(entity) != "materials":
            return
        get_by_dataset = getattr(self.world_model, "get_entities_by_dataset", None)
        if not callable(get_by_dataset):
            return
        from simulations.world_gen.natural_materials import configure_material_catalog

        configure_material_catalog(get_by_dataset("materials"))

    def _remove_entity_from_dataset_index(self, dataset_name, entity_id, entity_obj):
        if self.world_model is None or not dataset_name:
            return
        dataset = self.world_model.loader.datasets.get(dataset_name, [])
        self.world_model.loader.datasets[dataset_name] = [
            item
            for item in dataset
            if item is not entity_obj and item.get("id") != entity_id
        ]

    def _dataset_name_for_entity(self, entity):
        if not isinstance(entity, dict):
            return ""
        dataset_name = str(entity.get("_dataset") or "").strip()
        if dataset_name:
            return dataset_name

        entity_id = str(entity.get("id") or "").strip()
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        datasets = getattr(loader, "datasets", None)
        if entity_id and isinstance(datasets, dict):
            for candidate_name, dataset in datasets.items():
                if any(item is entity or (isinstance(item, dict) and item.get("id") == entity_id) for item in dataset or []):
                    return candidate_name

        entity_type = str(entity.get("type") or "").strip()
        if entity_type.endswith("s"):
            return entity_type
        if entity_type:
            plural_guess = f"{entity_type}s"
            if isinstance(datasets, dict) and plural_guess in datasets:
                return plural_guess
            return entity_type
        return ""

    def _remove_entity_from_repository(self, dataset_name, entity_id):
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is None or not hasattr(loader, "remove_entity"):
            return False
        return loader.remove_entity(entity_id, dataset_name=dataset_name)

    @staticmethod
    def _value_has_direct_entity_reference(value, entity_id):
        if isinstance(value, str):
            return value.strip() == entity_id
        if isinstance(value, dict):
            return any(
                str(value.get(key) or "").strip() == entity_id
                for key in ("id", "entity_id", "location_id", "target")
            )
        if isinstance(value, (list, tuple, set)):
            return any(
                KnowledgeRepositoryService._value_has_direct_entity_reference(
                    item,
                    entity_id,
                )
                for item in value
            )
        return False

    @classmethod
    def _without_direct_entity_reference(cls, value, entity_id):
        if isinstance(value, str):
            return ("", True) if value.strip() == entity_id else (value, False)
        if isinstance(value, list):
            filtered = [
                item
                for item in value
                if not cls._value_has_direct_entity_reference(item, entity_id)
            ]
            return filtered, len(filtered) != len(value)
        if isinstance(value, tuple):
            filtered = tuple(
                item
                for item in value
                if not cls._value_has_direct_entity_reference(item, entity_id)
            )
            return filtered, len(filtered) != len(value)
        if isinstance(value, set):
            filtered = {
                item
                for item in value
                if not cls._value_has_direct_entity_reference(item, entity_id)
            }
            return filtered, len(filtered) != len(value)
        if isinstance(value, dict) and cls._value_has_direct_entity_reference(
            value,
            entity_id,
        ):
            return {}, True
        return value, False

    def _capture_incoming_entity_references(self, entity_id):
        references = {}
        world_model = self.world_model
        touch_degrees = getattr(world_model, "touch_degrees", None)
        incoming = (
            touch_degrees.get_incoming_touches(entity_id)
            if touch_degrees is not None
            and hasattr(touch_degrees, "get_incoming_touches")
            else []
        )
        for touch in incoming or []:
            source_id = str(touch.get("source") or "").strip()
            field_name = str(touch.get("relation") or "").strip()
            if source_id:
                references.setdefault(source_id, set())
                if field_name:
                    references[source_id].add(field_name)

        loader = getattr(world_model, "loader", None)
        for source_id, targets in (getattr(loader, "edges", {}) or {}).items():
            if entity_id in (targets or []):
                references.setdefault(str(source_id), set())
        return references

    def _remove_incoming_entity_references(self, entity_id, references):
        world_model = self.world_model
        loader = getattr(world_model, "loader", None)
        entities = getattr(loader, "entities", {}) if loader is not None else {}

        for source_id, field_names in (references or {}).items():
            source = entities.get(source_id)
            if not isinstance(source, dict):
                continue

            candidate_fields = set(field_names or [])
            if not candidate_fields:
                candidate_fields.update(
                    field_name
                    for field_name, value in source.items()
                    if self._value_has_direct_entity_reference(value, entity_id)
                )
            candidate_fields.add("offspring")

            for field_name in candidate_fields:
                if field_name not in source:
                    continue
                updated, changed = self._without_direct_entity_reference(
                    source.get(field_name),
                    entity_id,
                )
                if changed:
                    source[field_name] = updated

        if loader is not None and isinstance(getattr(loader, "edges", None), dict):
            loader.edges.pop(entity_id, None)
            for source_id in references or {}:
                loader.edges[source_id] = [
                    target_id
                    for target_id in loader.edges.get(source_id, [])
                    if target_id != entity_id
                ]

        touch_degrees = getattr(world_model, "touch_degrees", None)
        remove_touch_entity = getattr(touch_degrees, "remove_entity", None)
        if callable(remove_touch_entity):
            remove_touch_entity(entity_id)
        elif touch_degrees is not None and hasattr(touch_degrees, "refresh"):
            touch_degrees.refresh()

        if hasattr(world_model, "repository_revision"):
            world_model.repository_revision += 1

    def _delete_card_entry(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        entity_id = str(entity.get("id") or card.get("entity_id") or "").strip()
        dataset_name = self._dataset_name_for_entity(entity)
        if not entity_id or not dataset_name:
            return False
        incoming_references = self._capture_incoming_entity_references(entity_id)

        removed = False
        if card.get("is_draft_entity", False):
            removed = True
        else:
            removed = self._remove_entity_from_repository(dataset_name, entity_id)
            if not removed:
                loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
                loader_entities = getattr(loader, "entities", {}) if loader is not None else {}
                removed = (
                    entity_id in loader_entities
                    or entity_id in self.card_drafts
                    or any(open_card is card for open_card in self.cards)
                )
                if not removed:
                    return False

        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is not None:
            self._remove_entity_from_dataset_index(dataset_name, entity_id, entity)
            if getattr(loader, "entities", None) is not None:
                loader.entities.pop(entity_id, None)
            aliases = getattr(loader, "entity_aliases", None)
            if isinstance(aliases, dict):
                aliases.pop(entity_id, None)
                for alias, target in list(aliases.items()):
                    if target == entity_id:
                        aliases.pop(alias, None)

        self._remove_card_draft(entity_id)
        self.cards = [open_card for open_card in self.cards if open_card is not card]
        self._ensure_keep_card_open(excluded_entity_ids={entity_id})
        if self.selected_entity_id == entity_id:
            self.selected_entity_id = self.cards[-1].get("entity_id") if self.cards else None
        if self.active_card_drag_id == entity_id:
            self.active_card_drag_id = None
        if self.active_card_resize_id == entity_id:
            self.active_card_resize_id = None
        if self.canvas_relation_link_source_id == entity_id:
            self._clear_canvas_relation_link()
        if (
            self.relation_link_target is not None
            and self.relation_link_target.get("source_entity_id") == entity_id
        ):
            self.relation_link_target = None
            self.relation_link_status = ""

        if not card.get("is_draft_entity", False) and self.world_model is not None:
            self._remove_incoming_entity_references(
                entity_id,
                incoming_references,
            )

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return removed
