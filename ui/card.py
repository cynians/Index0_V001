import os

import pygame

from engine.scaler import ScaleHelper
from ui.card_wiki import CardWikiRenderer
from world.schema_loader import SchemaLoader


class EntityCard:
    """
    Reusable renderer + interaction helper for one repository entity card.
    """

    HEADER_H = 50
    TAB_H = 24
    SECTION_HEADER_H = 22
    IMAGE_TOP = 86
    IMAGE_H = 110
    MEDIA_IMAGE_H = 176
    LAUNCH_H = 24
    RESIZE_HANDLE = 14
    RESIZE_BORDER = 6
    TEXT_LINE_H = 16
    IMAGE_TEXT_LINE_H = 18
    SECTION_GAP = 4
    TABLE_ROW_PAD_Y = 3
    TABLE_COLUMN_GAP = 14
    TABLE_MIN_KEY_W = 96
    TABLE_MAX_KEY_W = 260
    TABLE_MIN_VALUE_W = 120
    STANDARD_RELATION_FIELDS = [
        "derived_from",
        "parents",
        "related",
        "offspring",
        "placeholders",
    ]
    CORE_RELATION_FIELDS = set(STANDARD_RELATION_FIELDS)
    IDEA_GENERIC_FIELDS = {
        "id",
        "pretty_name",
        "name",
        "type",
        "description",
        "notes",
        "wiki_entry",
        "tags",
        "start_year",
        "end_year",
        "derived_from",
        "parents",
        "related",
        "offspring",
        "placeholders",
        "entry_status",
    }

    SECTION_ORDER = [
        "Identity",
        "Classification",
        "Dimensions / Scale",
        "Temporal",
        "Relations",
        "State / Layout",
        "Metadata",
    ]

    TAB_ORDER = ["general", "overview", "temporal", "relations", "state", "media"]
    DATASET_TAB_ORDER = {
        "ideas": ["general", "overview", "temporal", "relations"],
        "components": ["general", "overview", "temporal", "relations", "operational", "media"],
    }
    TAB_LABELS = {
        "general": "General",
        "overview": "Overview",
        "temporal": "Temporal",
        "relations": "Relations",
        "state": "State",
        "operational": "Operational",
        "media": "Media",
    }
    TAB_SECTIONS = {
        "general": [],
        "overview": ["Identity", "Classification", "Dimensions / Scale", "Metadata"],
        "temporal": ["Temporal"],
        "relations": ["Relations"],
        "state": ["State / Layout"],
        "operational": ["Operational"],
        "media": [],
    }
    TEMPORAL_FIELDS = {
        "year",
        "year_number",
        "start_year",
        "end_year",
        "effective_year",
        "start_event",
        "end_event",
        "end_condition",
        "era",
        "mean_anomaly_deg_at_epoch",
    }
    SCHEMA_LOADER = SchemaLoader()

    def __init__(self, entity, dataset_name=None, world_model=None):
        self.entity = entity or {}
        self.dataset_name = dataset_name or self.entity.get("_dataset", self.entity.get("type", "entity"))
        self.world_model = world_model
        self.active_tab = "general"
        self.collapsed_sections = {
            "Identity": False,
            "Classification": False,
            "Dimensions / Scale": False,
            "Temporal": False,
            "Relations": not self._is_idea_card(),
            "State / Layout": True,
            "Metadata": False,
        }

    def _is_idea_card(self):
        return self.dataset_name == "ideas" or self.entity.get("type") == "idea"

    def _is_component_card(self):
        return self.dataset_name == "components" or self.entity.get("type") in {"component", "assembly"}

    def _is_species_card(self):
        return self.dataset_name == "species" or self.entity.get("type") == "species"

    def _species_name_parts(self):
        common_name = str(self.entity.get("common_name") or "").strip()
        binomial_name = str(self.entity.get("binomial_name") or "").strip()

        if not common_name:
            pretty_name = str(self.entity.get("pretty_name") or "").strip()
            if " - " in pretty_name:
                common_name = pretty_name.split(" - ", 1)[0].strip()
            elif pretty_name and pretty_name != self.entity.get("id"):
                common_name = pretty_name

        if not binomial_name:
            legacy_name = str(self.entity.get("name") or "").strip()
            if legacy_name and legacy_name != common_name:
                binomial_name = legacy_name
            else:
                pretty_name = str(self.entity.get("pretty_name") or "").strip()
                if " - " in pretty_name:
                    binomial_name = pretty_name.split(" - ", 1)[1].strip()

        return common_name, binomial_name

    def _title_edit_field(self):
        return "common_name" if self._is_species_card() else "name"

    def _tab_order(self):
        if self._is_idea_card():
            return self.DATASET_TAB_ORDER["ideas"]
        if self._is_component_card():
            return self.DATASET_TAB_ORDER["components"]
        return self.DATASET_TAB_ORDER.get(self.dataset_name, self.TAB_ORDER)

    def toggle_section(self, section_name):
        if section_name in self.collapsed_sections:
            self.collapsed_sections[section_name] = not self.collapsed_sections[section_name]

    def set_active_tab(self, tab_name):
        if tab_name in self._tab_order():
            self.active_tab = tab_name

    def _visible_sections(self):
        return self.TAB_SECTIONS.get(self.active_tab, self.TAB_SECTIONS["general"])

    def _is_media_mode(self):
        return self.active_tab == "media"

    def _is_general_mode(self):
        return self.active_tab == "general"

    def _uses_image_block(self):
        return not self._is_general_mode() and not self._is_idea_card()

    def _field_spec(self, field_key):
        return self._normalize_field_spec(self._get_schema_field_specs().get(field_key, {}))

    def _normalize_field_spec(self, spec):
        if isinstance(spec, dict):
            return spec
        if isinstance(spec, str):
            return {"type": spec}
        return {}

    def is_relation_edit_field(self, field_key):
        spec = self._field_spec(field_key)
        field_type = str(spec.get("type", "")).lower()
        target = str(spec.get("target", "")).strip()
        if target:
            return True
        return "entity" in field_type or field_type in {"idea", "idea_list"}

    def _relation_field_allows_many(self, field_key):
        field_type = str(self._field_spec(field_key).get("type", "")).lower()
        return "list" in field_type

    def _relation_field_target(self, field_key):
        spec = self._field_spec(field_key)
        target = str(spec.get("target", "")).strip()
        if target:
            return target

        field_type = str(spec.get("type", "")).strip().lower()
        if field_type.endswith("_list"):
            inferred = field_type[:-len("_list")]
            if inferred and inferred not in {"string", "number", "object", "dict"}:
                return inferred
        if field_type in {"idea", "ideas"}:
            return "ideas"
        return ""

    def _relation_reference_values(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [str(value)]
        if isinstance(value, list):
            refs = []
            for item in value:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        refs.append(stripped)
                elif isinstance(item, (int, float)) and not isinstance(item, bool):
                    refs.append(str(item))
                elif isinstance(item, dict) and item.get("id"):
                    refs.append(str(item["id"]).strip())
            return [ref for ref in refs if ref]
        return []

    def _relation_entity_exists(self, entity_id):
        if not entity_id or self.world_model is None:
            return False
        return self.world_model.get_entity(entity_id) is not None

    def _relation_chip_label(self, item):
        prefix = ""
        if item.get("kind") == "missing":
            prefix = "? "
        elif item.get("kind") == "create":
            prefix = "+ "
        return f"{prefix}{item.get('label', '')}".strip()

    def _relation_target_label(self, target):
        normalized = str(target or "").strip().lower()
        if not normalized or normalized in {"entity", "entity_core", "core", "any"}:
            return "Entry"
        return normalized.replace("_", " ")

    def _ellipsize_text(self, text, font, max_width):
        text = str(text or "")
        if font is None or font.size(text)[0] <= max_width:
            return text

        suffix = "..."
        suffix_w = font.size(suffix)[0]
        available_w = max(0, max_width - suffix_w)
        trimmed = text
        while trimmed and font.size(trimmed)[0] > available_w:
            trimmed = trimmed[:-1]
        return f"{trimmed}{suffix}" if trimmed else suffix

    def _relation_chip_items(self, field_key, value, edit_mode=False):
        target = self._relation_field_target(field_key)
        refs = self._relation_reference_values(value)
        if refs:
            items = [
                {
                    "kind": "existing" if self._relation_entity_exists(ref) else "missing",
                    "field_key": field_key,
                    "entity_id": ref,
                    "target": target,
                    "label": ref,
                }
                for ref in refs
            ]
            if edit_mode:
                items.append(
                    {
                        "kind": "link_existing",
                        "field_key": field_key,
                        "entity_id": "",
                        "target": target,
                        "label": "Link existing",
                    }
                )
            return items

        if not edit_mode:
            return []

        return [
            {
                "kind": "create",
                "field_key": field_key,
                "entity_id": "",
                "target": target,
                "label": f"Create {self._relation_target_label(target)}",
            },
            {
                "kind": "link_existing",
                "field_key": field_key,
                "entity_id": "",
                "target": target,
                "label": "Link existing",
            },
        ]

    def _layout_relation_chips(self, field_key, value, font, value_x, value_y, value_w, edit_mode=False):
        items = self._relation_chip_items(field_key, value, edit_mode=edit_mode)
        if not items:
            return [], 0

        line_h = self._table_line_height(font)
        chip_h = max(18, line_h + 4)
        chip_gap = 5
        x = value_x + 2
        y = value_y + self.TABLE_ROW_PAD_Y
        max_right = value_x + max(24, value_w) - 2
        chips = []

        for item in items:
            label = self._relation_chip_label(item)
            has_remove_button = edit_mode and item.get("kind") in {"existing", "missing"}
            remove_w = 18 if has_remove_button else 0
            chip_w = min(max(46, font.size(label)[0] + 16 + remove_w), max(46, value_w - 4))
            if x > value_x + 2 and x + chip_w > max_right:
                x = value_x + 2
                y += chip_h + chip_gap

            rect = pygame.Rect(x, y, chip_w, chip_h)
            chip = dict(item)
            chip["rect"] = rect
            chip["display_label"] = label
            if has_remove_button:
                remove_size = max(12, min(16, chip_h - 4))
                chip["remove_rect"] = pygame.Rect(
                    rect.right - remove_size - 3,
                    rect.y + (rect.height - remove_size) // 2,
                    remove_size,
                    remove_size,
                )
            chips.append(chip)
            x = rect.right + chip_gap

        content_h = chips[-1]["rect"].bottom - value_y + self.TABLE_ROW_PAD_Y if chips else 0
        return chips, content_h

    def _image_block_height(self):
        if self._is_media_mode():
            return self.MEDIA_IMAGE_H
        return self.IMAGE_H

    def _media_field_keys(self):
        media_keys = {
            "card_image",
            "design_image",
            "image_path",
            "image",
        }

        for role_info in ScaleHelper.suggest_media_canvases(self.entity):
            role = role_info.get("role")
            if role:
                media_keys.add(self._role_field_name(role))

        return media_keys

    def _role_field_name(self, role_name):
        role_name = (role_name or "card").lower()
        if role_name == "card":
            return "card_image"
        return f"card_image_{role_name}"

    def _resolve_role_image_reference(self, role_name):
        field_name = self._role_field_name(role_name)
        value = self.entity.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _get_general_wiki_text(self, card=None):
        if card is not None and card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry":
            return card.get("edit_buffer", "")

        if card is not None:
            draft_buffer = card.get("draft_edit_buffers", {}).get("wiki_entry")
            if isinstance(draft_buffer, dict) and "text" in draft_buffer:
                return str(draft_buffer.get("text", ""))

        wiki_text = self.entity.get("wiki_entry")
        if isinstance(wiki_text, str) and wiki_text.strip():
            return wiki_text

        fallback_parts = []
        description = self.entity.get("description")
        notes = self.entity.get("notes")
        image_ref = self._resolve_image_reference()

        if description:
            fallback_parts.append(str(description).strip())
        if image_ref:
            fallback_parts.append(f"![Primary image]({image_ref})")
        if notes:
            fallback_parts.append(str(notes).strip())

        return "\n\n".join(part for part in fallback_parts if part)

    def _resolve_wiki_link_label(self, entity_ref):
        if self.world_model is None:
            return entity_ref

        entity = self.world_model.get_entity(entity_ref)
        if entity is None:
            return entity_ref

        if entity.get("_dataset") == "species" or entity.get("type") == "species":
            common_name = str(entity.get("common_name") or "").strip()
            binomial_name = str(entity.get("binomial_name") or "").strip()
            pretty_name = str(entity.get("pretty_name") or "").strip()
            legacy_name = str(entity.get("name") or "").strip()
            if not common_name and " - " in pretty_name:
                common_name = pretty_name.split(" - ", 1)[0].strip()
            elif not common_name and pretty_name:
                common_name = pretty_name
            if not binomial_name and legacy_name:
                binomial_name = legacy_name
            elif not binomial_name and " - " in pretty_name:
                binomial_name = pretty_name.split(" - ", 1)[1].strip()
            if common_name and binomial_name:
                return f"{common_name} - {binomial_name}"
            if common_name:
                return common_name
            if binomial_name:
                return binomial_name

        return entity.get("pretty_name") or entity.get("name") or entity_ref

    def _schema_name_candidates(self):
        candidates = []
        entity_type = self.entity.get("type")
        dataset_name = self.dataset_name

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

        return candidates

    def _resolve_schema(self):
        for schema_name in self._schema_name_candidates():
            schema = self.SCHEMA_LOADER.get_schema(schema_name)
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

        combined = {}
        extends_name = schema.get("extends")
        if extends_name:
            parent_schema = self.SCHEMA_LOADER.get_schema(extends_name)
            combined.update(self._collect_schema_fields(parent_schema, seen=seen))

        combined.update(schema.get("fields", {}))
        return combined

    def _get_schema_field_specs(self):
        schema = self._resolve_schema()
        field_specs = self._collect_schema_fields(schema)
        if self._is_idea_card():
            return {
                key: value
                for key, value in field_specs.items()
                if key in self.IDEA_GENERIC_FIELDS
            }
        return field_specs

    def _is_scalar_schema_type(self, field_type):
        return field_type in {None, "string", "number", "text"}

    def _is_temporal_field(self, field_key, spec=None):
        if field_key in self.TEMPORAL_FIELDS:
            return True

        if isinstance(spec, dict) and str(spec.get("section", "")).lower() == "temporal":
            return True

        key = str(field_key or "").lower()
        temporal_suffixes = (
            "_year",
            "_years",
            "_time",
            "_date",
            "_duration",
            "_period",
            "_era",
            "_epoch",
        )
        temporal_prefixes = ("year_", "era_")
        temporal_rate_suffixes = ("_per_hour", "_per_day", "_per_year")

        if key.endswith(temporal_suffixes) or key.startswith(temporal_prefixes):
            return True
        if key.endswith(temporal_rate_suffixes) or "_at_epoch" in key:
            return True
        return False

    def _is_field_editable(self, field_key, value, schema_field_specs):
        if field_key in {"name", "common_name"}:
            return True

        spec = self._normalize_field_spec(schema_field_specs.get(field_key, {}))
        field_type = spec.get("type")

        if field_type in {"entity", "entity_list"}:
            return value is None or isinstance(value, (str, list))

        if value is None:
            return self._is_scalar_schema_type(field_type)

        if field_type is not None and not self._is_scalar_schema_type(field_type):
            return False

        return isinstance(value, (str, int, float)) and not isinstance(value, bool)

    def _sectioned_fields(self):
        entity = self.entity
        schema_field_specs = self._get_schema_field_specs()
        schema_field_order = list(schema_field_specs.keys())

        if self._is_species_card():
            common_name, binomial_name = self._species_name_parts()
            identity = [
                ("common_name", common_name),
                ("binomial_name", binomial_name),
                ("id", entity.get("id")),
                ("type", entity.get("type")),
                ("dataset", entity.get("_dataset")),
            ]
        else:
            identity = [
                ("id", entity.get("id")),
                ("pretty_name", entity.get("pretty_name")),
                ("name", entity.get("name")),
                ("type", entity.get("type")),
                ("dataset", entity.get("_dataset")),
            ]

        classification_keys = [
            "vehicle_class",
            "component_class",
            "idea_class",
            "location_class",
            "system_role",
            "system_class",
            "body_class",
        ]
        classification = []
        for key in classification_keys:
            if key in entity or key in schema_field_specs:
                classification.append((key, entity.get(key)))

        dims = [
            ("dimension_x_m", entity.get("dimension_x_m")),
            ("dimension_y_m", entity.get("dimension_y_m")),
            ("dimension_z_m", entity.get("dimension_z_m")),
            ("mass_kg", entity.get("mass_kg")),
            ("power_kw", entity.get("power_kw")),
        ]
        dims = [(key, value) for key, value in dims if key in entity or key in schema_field_specs]
        overview_dims = [] if self._is_component_card() else dims

        relation_values = []
        state_values = []
        metadata_values = []
        operational_values = []
        temporal_values = []

        media_keys = self._media_field_keys()

        component_operational_keys = {
            "dimension_x_m",
            "dimension_y_m",
            "dimension_z_m",
            "mass_kg",
            "power_kw",
            "install_contexts",
            "functional_roles",
            "satisfies_categories",
            "operational_groups",
            "subsystem_labels",
            "descriptive_capabilities",
            "maintenance_notes",
        }

        handled_keys = {
            "id", "pretty_name", "name", "common_name", "binomial_name", "type", "_dataset",
            "vehicle_class", "component_class", "idea_class", "location_class",
            "system_role", "system_class", "body_class",
            "dimension_x_m", "dimension_y_m", "dimension_z_m",
            "mass_kg", "power_kw",
        }

        ordered_keys = []
        for key in schema_field_order:
            if key not in handled_keys:
                ordered_keys.append(key)

        for key in self.STANDARD_RELATION_FIELDS:
            if key not in handled_keys and key not in ordered_keys:
                ordered_keys.append(key)

        for key in entity.keys():
            if key in handled_keys or key in ordered_keys:
                continue
            ordered_keys.append(key)

        for key in ordered_keys:
            value = entity.get(key)

            if key in {
                "id", "pretty_name", "name", "common_name", "binomial_name", "type", "_dataset",
                "vehicle_class", "component_class", "idea_class", "location_class",
                "system_role", "system_class", "body_class",
                "dimension_x_m", "dimension_y_m", "dimension_z_m",
                "mass_kg", "power_kw",
            }:
                continue

            spec = self._normalize_field_spec(schema_field_specs.get(key, {}))
            section_name = str(spec.get("section", "")).lower()

            if self._is_temporal_field(key, spec):
                temporal_values.append((key, value))
                continue

            if section_name == "relations" or key in self.STANDARD_RELATION_FIELDS:
                relation_values.append((key, value))
                continue

            if self._is_component_card() and key in component_operational_keys:
                operational_values.append((key, value))
                continue

            if self._is_component_card() and key in media_keys:
                continue

            if key in {"description", "notes", "tags", "entry_status"}:
                metadata_values.append((key, value))
                continue

            if key in media_keys:
                metadata_values.append((key, value))
                continue

            if isinstance(value, list):
                state_values.append((key, value))
                continue

            if isinstance(value, dict):
                state_values.append((key, value))
                continue

            field_type = spec.get("type")

            if field_type in {"entity", "entity_list"}:
                state_values.append((key, value))
                continue

            if field_type in {"dict", "object", "object_list"}:
                state_values.append((key, value))
                continue

            metadata_values.append((key, value))

        return {
            "Identity": identity,
            "Classification": classification,
            "Dimensions / Scale": overview_dims,
            "Temporal": temporal_values,
            "Relations": relation_values,
            "State / Layout": state_values,
            "Metadata": metadata_values,
            "Operational": dims + operational_values if self._is_component_card() else operational_values,
        }

    def _format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            if value and all(isinstance(item, dict) and "id" in item for item in value):
                return "\n".join(self._format_offspring_node(item) for item in value)
            return "\n".join(f"- {item}" for item in value) if value else "[]"
        return str(value)

    def _format_offspring_node(self, node, depth=0):
        node_id = str(node.get("id", ""))
        indent = "  " * depth
        lines = [f"{indent}- {node_id}"]

        for child in node.get("offspring", []) or []:
            if isinstance(child, dict):
                lines.append(self._format_offspring_node(child, depth=depth + 1))
            else:
                lines.append(f"{'  ' * (depth + 1)}- {child}")

        return "\n".join(lines)

    def _is_scalar_editable_value(self, value):
        return value is None or isinstance(value, (str, int, float))

    def _serialize_edit_value(self, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return str(value)

    def _initial_edit_buffer(self, field_key, value):
        if field_key == "wiki_entry" and not (isinstance(value, str) and value.strip()):
            description = self.entity.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
            fallback_text = self._get_general_wiki_text()
            if fallback_text and fallback_text != CardWikiRenderer.EMPTY_HINT:
                return fallback_text
        return self._serialize_edit_value(value)

    def _clamp_edit_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = int(card.get("edit_cursor", len(buffer_text)))
        cursor = max(0, min(len(buffer_text), cursor))
        card["edit_cursor"] = cursor
        return cursor

    def _set_edit_cursor(self, card, cursor):
        buffer_text = card.get("edit_buffer", "")
        card["edit_cursor"] = max(0, min(len(buffer_text), int(cursor)))

    def _insert_edit_text(self, card, text):
        if not text:
            return False

        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"] = buffer_text[:cursor] + text + buffer_text[cursor:]
        card["edit_cursor"] = cursor + len(text)
        return True

    def _delete_before_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        if cursor <= 0:
            return True
        card["edit_buffer"] = buffer_text[:cursor - 1] + buffer_text[cursor:]
        card["edit_cursor"] = cursor - 1
        return True

    def _delete_after_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        if cursor >= len(buffer_text):
            return True
        card["edit_buffer"] = buffer_text[:cursor] + buffer_text[cursor + 1:]
        card["edit_cursor"] = cursor
        return True

    def _word_start_before_cursor(self, buffer_text, cursor):
        cursor = max(0, min(len(buffer_text), int(cursor)))
        index = cursor
        while index > 0 and buffer_text[index - 1].isspace():
            index -= 1
        while index > 0 and (buffer_text[index - 1].isalnum() or buffer_text[index - 1] in {"_", "-"}):
            index -= 1
        return index

    def _word_end_after_cursor(self, buffer_text, cursor):
        cursor = max(0, min(len(buffer_text), int(cursor)))
        index = cursor
        while index < len(buffer_text) and buffer_text[index].isspace():
            index += 1
        while index < len(buffer_text) and (buffer_text[index].isalnum() or buffer_text[index] in {"_", "-"}):
            index += 1
        return index

    def _delete_word_before_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        start = self._word_start_before_cursor(buffer_text, cursor)
        card["edit_buffer"] = buffer_text[:start] + buffer_text[cursor:]
        card["edit_cursor"] = start
        return True

    def _delete_word_after_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        end = self._word_end_after_cursor(buffer_text, cursor)
        card["edit_buffer"] = buffer_text[:cursor] + buffer_text[end:]
        card["edit_cursor"] = cursor
        return True

    def _line_start_before_cursor(self, buffer_text, cursor):
        cursor = max(0, min(len(buffer_text), int(cursor)))
        return buffer_text.rfind("\n", 0, cursor) + 1

    def _line_end_after_cursor(self, buffer_text, cursor):
        cursor = max(0, min(len(buffer_text), int(cursor)))
        line_end = buffer_text.find("\n", cursor)
        return len(buffer_text) if line_end == -1 else line_end

    def _parse_edit_lines(self, buffer_text):
        lines = []
        for raw_line in str(buffer_text or "").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("-"):
                stripped = stripped[1:].strip()
            if stripped:
                lines.append(stripped)
        return lines

    def _coerce_edit_buffer(self, field_key, original_value, buffer_text):
        text = str(buffer_text or "")
        field_type = self._field_spec(field_key).get("type")

        if field_type == "entity_list" or isinstance(original_value, list):
            return self._parse_edit_lines(text)

        if field_type == "entity":
            lines = self._parse_edit_lines(text)
            return lines[0] if lines else None

        if isinstance(original_value, int) and not isinstance(original_value, bool):
            try:
                return int(text)
            except ValueError:
                return original_value

        if isinstance(original_value, float):
            try:
                return float(text)
            except ValueError:
                return original_value

        lowered = text.strip().lower()
        if original_value is None:
            if lowered in {"", "none", "null"}:
                return None
            try:
                if "." in text:
                    return float(text)
                return int(text)
            except ValueError:
                return text

        return text

    def toggle_edit_mode(self, card):
        currently_enabled = bool(card.get("is_edit_mode", False))
        if currently_enabled and card.get("active_edit_field"):
            field_key = card.get("active_edit_field")
            draft_buffers = card.setdefault("draft_edit_buffers", {})
            draft_buffers[field_key] = {
                "text": card.get("edit_buffer", ""),
                "cursor": int(card.get("edit_cursor", 0)),
            }
            card["last_edit_action"] = "draft"

        card["is_edit_mode"] = not currently_enabled

        if not card["is_edit_mode"]:
            card["active_edit_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None
            card["edit_cursor"] = 0

    def _editable_field_order(self, card):
        seen = set()
        fields = []
        for field_key, _ in card.get("editable_field_hitboxes", []):
            if field_key in seen:
                continue
            seen.add(field_key)
            fields.append(field_key)
        return fields

    def _cycle_edit_field(self, card, direction=1):
        field_order = self._editable_field_order(card)
        if not field_order:
            return False

        active_field = card.get("active_edit_field")
        if active_field not in field_order:
            target_index = 0 if direction >= 0 else len(field_order) - 1
        else:
            current_index = field_order.index(active_field)
            target_index = (current_index + direction) % len(field_order)

        return self.begin_edit_field(card, field_order[target_index])

    def begin_edit_field(self, card, field_key):
        if not card.get("is_edit_mode", False):
            return False

        value = self.entity.get(field_key)
        schema_field_specs = self._get_schema_field_specs()
        if not self._is_field_editable(field_key, value, schema_field_specs):
            return False

        active_field = card.get("active_edit_field")
        if active_field and active_field != field_key:
            self.commit_edit_field(card)
        elif active_field == field_key:
            return True

        card["active_edit_field"] = field_key
        card["edit_original_value"] = value
        draft_buffer = card.get("draft_edit_buffers", {}).get(field_key)
        if isinstance(draft_buffer, dict) and "text" in draft_buffer:
            card["edit_buffer"] = str(draft_buffer.get("text", ""))
            card["edit_cursor"] = int(draft_buffer.get("cursor", len(card["edit_buffer"])))
            self._clamp_edit_cursor(card)
            return True

        card["edit_buffer"] = self._initial_edit_buffer(field_key, value)
        card["edit_cursor"] = len(card["edit_buffer"])
        return True

    def commit_edit_field(self, card):
        field_key = card.get("active_edit_field")
        if not field_key:
            return False

        original_value = card.get("edit_original_value", self.entity.get(field_key))
        new_value = self._coerce_edit_buffer(field_key, original_value, card.get("edit_buffer", ""))
        self.entity[field_key] = new_value
        if field_key == "id":
            card["pending_entity_id_change"] = {
                "old": str(original_value or ""),
                "new": str(new_value or ""),
            }

        if self._is_species_card() and field_key in {"common_name", "binomial_name", "id"}:
            common_name, binomial_name = self._species_name_parts()
            card["title"] = common_name or binomial_name or self.entity.get("id", "Unknown Species")
        elif field_key in {"name", "pretty_name", "id"}:
            card["title"] = str(new_value or self.entity.get("id", "unknown"))

        draft_buffers = card.get("draft_edit_buffers")
        if isinstance(draft_buffers, dict):
            draft_buffers.pop(field_key, None)
        card["active_edit_field"] = None
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        card["edit_cursor"] = 0
        card["last_edit_action"] = "commit"
        return True

    def cancel_edit_field(self, card):
        if not card.get("active_edit_field"):
            return False

        card["last_edit_action"] = "cancel"
        card["active_edit_field"] = None
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        card["edit_cursor"] = 0
        return True

    def handle_keydown(self, card, event):
        if not card.get("is_edit_mode", False):
            return False

        active_field = card.get("active_edit_field")
        if not active_field:
            if event.key == pygame.K_TAB:
                direction = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
                return self._cycle_edit_field(card, direction=direction)
            if event.key == pygame.K_ESCAPE:
                card["last_edit_action"] = "cancel"
                card["is_edit_mode"] = False
                return True
            return False

        if active_field == "wiki_entry":
            if event.key == pygame.K_s and (event.mod & pygame.KMOD_CTRL):
                return self.commit_edit_field(card)

            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT):
                    return self.commit_edit_field(card)
                self._insert_edit_text(card, "\n")
                card["last_edit_action"] = "draft"
                return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.commit_edit_field(card)

        if event.key == pygame.K_ESCAPE:
            return self.cancel_edit_field(card)

        if event.key == pygame.K_TAB:
            direction = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
            self.commit_edit_field(card)
            return self._cycle_edit_field(card, direction=direction)

        if event.key == pygame.K_LEFT:
            cursor = self._clamp_edit_cursor(card)
            if event.mod & pygame.KMOD_CTRL:
                self._set_edit_cursor(card, self._word_start_before_cursor(card.get("edit_buffer", ""), cursor))
            else:
                self._set_edit_cursor(card, cursor - 1)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_RIGHT:
            cursor = self._clamp_edit_cursor(card)
            if event.mod & pygame.KMOD_CTRL:
                self._set_edit_cursor(card, self._word_end_after_cursor(card.get("edit_buffer", ""), cursor))
            else:
                self._set_edit_cursor(card, cursor + 1)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_HOME:
            if active_field == "wiki_entry" and not (event.mod & pygame.KMOD_CTRL):
                self._set_edit_cursor(card, self._line_start_before_cursor(card.get("edit_buffer", ""), self._clamp_edit_cursor(card)))
            else:
                self._set_edit_cursor(card, 0)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_END:
            if active_field == "wiki_entry" and not (event.mod & pygame.KMOD_CTRL):
                self._set_edit_cursor(card, self._line_end_after_cursor(card.get("edit_buffer", ""), self._clamp_edit_cursor(card)))
            else:
                self._set_edit_cursor(card, len(card.get("edit_buffer", "")))
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_BACKSPACE:
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_before_cursor(card)
            else:
                self._delete_before_cursor(card)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_DELETE:
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_after_cursor(card)
            else:
                self._delete_after_cursor(card)
            card["last_edit_action"] = "draft"
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self._insert_edit_text(card, text)
            card["last_edit_action"] = "draft"
            return True

        return False

    def insert_relation_reference(self, card, entity_id):
        field_key = card.get("active_edit_field")
        if not field_key or not self.is_relation_edit_field(field_key):
            return False

        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return False

        if self._relation_field_allows_many(field_key):
            existing = self._parse_edit_lines(card.get("edit_buffer", ""))
            if entity_id not in existing:
                existing.append(entity_id)
            card["edit_buffer"] = "\n".join(existing)
        else:
            card["edit_buffer"] = entity_id
        card["edit_cursor"] = len(card["edit_buffer"])

        return True

    def set_edit_cursor_from_pos(self, card, field_key, mouse_pos, font):
        if field_key != "wiki_entry":
            return False

        general_rect = card.get("general_content_rect")
        if general_rect is None or font is None:
            return False

        if card.get("active_edit_field") != field_key:
            self.begin_edit_field(card, field_key)

        buffer_text = card.get("edit_buffer", "")
        inner_rect = general_rect.inflate(-10, -10)
        lines = CardWikiRenderer.wrap_edit_lines(buffer_text, font, inner_rect.width)
        if not lines:
            self._set_edit_cursor(card, 0)
            return True

        scroll_y = max(0, int(card.get("scroll_y", 0) or 0))
        line_index = int((mouse_pos[1] - inner_rect.y + scroll_y) // max(1, font.get_linesize()))
        line_index = max(0, min(len(lines) - 1, line_index))
        line_info = lines[line_index]
        line_text = line_info["text"]
        rel_x = max(0, mouse_pos[0] - inner_rect.x)

        best_offset = 0
        best_distance = None
        for offset in range(len(line_text) + 1):
            width = font.size(line_text[:offset])[0]
            distance = abs(width - rel_x)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_offset = offset

        self._set_edit_cursor(card, line_info["start"] + best_offset)
        return True

    def _wrap_text_lines(self, text, font, max_width):
        """
        Wrap text into multiple rendered lines that fit the given width.
        Preserves explicit newline breaks.
        """
        if text is None:
            return [""]

        max_width = max(20, int(max_width))
        wrapped_lines = []

        for paragraph in str(text).splitlines() or [""]:
            words = paragraph.split(" ")

            if not words:
                wrapped_lines.append("")
                continue

            current_line = ""
            for word in words:
                candidate = word if not current_line else f"{current_line} {word}"

                if font.size(candidate)[0] <= max_width:
                    current_line = candidate
                    continue

                if current_line:
                    wrapped_lines.append(current_line)
                    current_line = word
                else:
                    split_word = word
                    while split_word:
                        chunk = split_word
                        while chunk and font.size(chunk)[0] > max_width:
                            chunk = chunk[:-1]

                        if not chunk:
                            break

                        wrapped_lines.append(chunk)
                        split_word = split_word[len(chunk):]

                    current_line = ""

            if current_line or paragraph == "":
                wrapped_lines.append(current_line)

        return wrapped_lines or [""]

    def _resolve_image_reference(self):
        """
        Resolve the active preview image using shared fallback order.

        Preferred order:
        1. card_image
        2. design_image
        3. card_image_front
        4. card_image_side
        5. card_image_top
        6. any other role-specific card image fields suggested for the entity
        7. image_path
        8. image
        """
        explicit_order = [
            "card_image",
            "design_image",
            "card_image_front",
            "card_image_side",
            "card_image_top",
        ]

        seen = set()

        for key in explicit_order:
            seen.add(key)
            value = self.entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for role_info in ScaleHelper.suggest_media_canvases(self.entity):
            role = role_info.get("role")
            if not role:
                continue

            field_name = self._role_field_name(role)
            if field_name in seen:
                continue

            seen.add(field_name)
            value = self.entity.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("image_path", "image"):
            value = self.entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _load_card_image_surface(self, image_path):
        if not image_path:
            return None

        normalized_path = os.path.normpath(image_path)

        candidate_paths = [normalized_path]
        if not os.path.isabs(normalized_path):
            candidate_paths.append(os.path.normpath(os.path.join(os.getcwd(), normalized_path)))

        for candidate in candidate_paths:
            if not os.path.exists(candidate):
                continue
            try:
                return pygame.image.load(candidate).convert_alpha()
            except Exception:
                return None

        return None

    def _get_table_column_widths(self, font, rect, section_map):
        available_w = max(180, rect.width - 24)
        max_key_w = self.TABLE_MIN_KEY_W

        if font is not None:
            for section_name in self._visible_sections():
                for key, _ in section_map.get(section_name, []):
                    max_key_w = max(max_key_w, font.size(f"{key}:")[0] + 14)

        max_key_for_card = max(
            self.TABLE_MIN_KEY_W,
            min(self.TABLE_MAX_KEY_W, int(available_w * 0.58), available_w - self.TABLE_MIN_VALUE_W - self.TABLE_COLUMN_GAP),
        )
        key_w = max(self.TABLE_MIN_KEY_W, min(max_key_for_card, max_key_w))
        value_w = max(self.TABLE_MIN_VALUE_W, available_w - key_w - self.TABLE_COLUMN_GAP)
        return key_w, value_w

    def _table_line_height(self, font):
        if font is None:
            return self.TEXT_LINE_H
        return max(self.TEXT_LINE_H, int(font.get_linesize()))

    def _measure_table_row(self, font, key, value, key_column_w, value_column_w):
        rendered_key = f"{key}:"
        key_lines = self._wrap_text_lines(rendered_key, font, max(20, key_column_w - 12))
        rendered_value = self._format_value(value)
        wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)
        content_h = max(1, len(key_lines), len(wrapped_lines)) * self._table_line_height(font)
        row_h = content_h + self.TABLE_ROW_PAD_Y * 2
        return key_lines, wrapped_lines, row_h

    def layout_card(self, card, rect):
        section_hitboxes = []
        tab_hitboxes = []
        media_import_hitboxes = []
        editable_field_hitboxes = []
        content_editable_field_hitboxes = []
        relation_hitboxes = []
        field_rows = []
        general_content_rect = None
        schema_field_specs = self._get_schema_field_specs()

        tab_y = rect.y + self.HEADER_H + 6
        tab_x = rect.x + 12
        tab_gap = 6
        tab_widths = {
            "general": 70,
            "overview": 78,
            "temporal": 82,
            "relations": 76,
            "state": 54,
            "operational": 92,
            "media": 54,
        }
        tab_order = self._tab_order()
        available_tab_w = max(120, rect.width - 24)
        total_tab_w = sum(tab_widths[name] for name in tab_order) + tab_gap * max(0, len(tab_order) - 1)
        if total_tab_w > available_tab_w:
            tab_gap = 4
            available_for_tabs = available_tab_w - tab_gap * max(0, len(tab_order) - 1)
            base_total = sum(tab_widths[name] for name in tab_order)
            scale = max(0.55, available_for_tabs / max(1, base_total))
            for tab_name in tab_order:
                tab_widths[tab_name] = max(44, int(tab_widths[tab_name] * scale))

        for tab_name in tab_order:
            tab_rect = pygame.Rect(tab_x, tab_y, tab_widths[tab_name], self.TAB_H)
            tab_hitboxes.append((tab_name, tab_rect))
            tab_x = tab_rect.right + tab_gap

        close_rect = pygame.Rect(rect.right - 24, rect.y + 12, 18, 18)
        edit_toggle_rect = pygame.Rect(rect.right - 48, rect.y + 12, 20, 20)
        idea_button_rect = pygame.Rect(rect.right - 72, rect.y + 12, 20, 20)
        title_edit_rect = pygame.Rect(rect.x + 10, rect.y + 7, max(40, rect.width - 120), 20)
        type_label_rect = pygame.Rect(rect.x + 10, rect.y + 28, max(40, rect.width - 120), 18)
        if card.get("is_edit_mode", False):
            editable_field_hitboxes.append((self._title_edit_field(), title_edit_rect))

        image_rect = pygame.Rect(
            rect.x + 12,
            rect.y + self.IMAGE_TOP,
            rect.width - 24,
            self._image_block_height(),
        )

        if self._is_media_mode():
            row_y = image_rect.y + 104
            button_w = 68
            button_h = 18
            row_gap = 20
            button_x = image_rect.right - button_w - 10

            for media_info in ScaleHelper.suggest_media_canvases(self.entity):
                role_name = media_info["role"]
                button_rect = pygame.Rect(button_x, row_y - 1, button_w, button_h)
                media_import_hitboxes.append((role_name, button_rect))
                row_y += row_gap

        current_y = image_rect.bottom + 12
        content_left = rect.x + 12
        content_right = rect.right - 12
        text_width = content_right - content_left
        top_content_y = tab_y + self.TAB_H + 10
        if not self._uses_image_block():
            current_y = top_content_y

        handle_bottom = rect.bottom - 8
        resize_handle_rect = pygame.Rect(
            rect.right - 18,
            handle_bottom - self.RESIZE_HANDLE,
            self.RESIZE_HANDLE,
            self.RESIZE_HANDLE,
        )
        launch_rect = pygame.Rect(
            rect.x + 12,
            resize_handle_rect.y - 8 - self.LAUNCH_H,
            rect.width - 24,
            self.LAUNCH_H,
        )
        center_y = launch_rect.y - 14
        left_x = rect.x + 20
        right_x = rect.right - 20
        timeline_y = center_y - 10
        timeline_label_y = max(top_content_y + 8, timeline_y - 18)
        content_viewport_top = image_rect.y if self._uses_image_block() else top_content_y
        content_viewport_bottom = max(content_viewport_top + 40, timeline_label_y - 10)
        content_viewport_rect = pygame.Rect(
            content_left,
            content_viewport_top,
            text_width,
            max(24, content_viewport_bottom - content_viewport_top),
        )

        section_map = self._sectioned_fields()
        key_column_w, value_column_w = self._get_table_column_widths(card["layout_font"], rect, section_map)
        value_column_x = content_left + key_column_w + self.TABLE_COLUMN_GAP

        if self._is_general_mode():
            image_rect = None
            general_bottom = timeline_label_y - 10
            general_height = max(40, general_bottom - top_content_y)
            general_content_rect = pygame.Rect(content_left, top_content_y, text_width, general_height)
            if card.get("is_edit_mode", False):
                editable_field_hitboxes.append(("wiki_entry", general_content_rect))
            wiki_text = self._get_general_wiki_text(card)
            if card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry":
                inner_w = max(20, general_content_rect.width - 20)
                content_h = len(CardWikiRenderer.wrap_edit_lines(wiki_text, card["layout_font"], inner_w)) * self._table_line_height(card["layout_font"]) + 20
            else:
                content_h = CardWikiRenderer.measure_content(
                    wiki_text,
                    card["layout_font"],
                    general_content_rect,
                    resolve_link_label=self._resolve_wiki_link_label,
                )
            content_end_y = general_content_rect.y + content_h
        else:
            content_end_y = current_y

            for section_name in self._visible_sections():
                section_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
                section_hitboxes.append((section_name, section_rect))
                current_y += self.SECTION_HEADER_H + self.SECTION_GAP

                if not self.collapsed_sections.get(section_name, False):
                    for key, value in section_map.get(section_name, []):
                        measure_value = card.get("edit_buffer", "") if card.get("active_edit_field") == key else value
                        key_lines, wrapped_lines, row_h = self._measure_table_row(
                            card["layout_font"],
                            key,
                            measure_value,
                            key_column_w,
                            value_column_w,
                        )
                        relation_chips = []
                        if self.is_relation_edit_field(key) and card.get("active_edit_field") != key:
                            relation_chips, relation_content_h = self._layout_relation_chips(
                                key,
                                value,
                                card["layout_font"],
                                value_column_x,
                                current_y,
                                value_column_w,
                                edit_mode=bool(card.get("is_edit_mode", False)),
                            )
                            row_h = max(row_h, relation_content_h)

                        row_rect = pygame.Rect(content_left, current_y, text_width, row_h)
                        key_rect = pygame.Rect(content_left, current_y, key_column_w, row_h)
                        value_rect = pygame.Rect(value_column_x, current_y, value_column_w, row_h)

                        if card.get("is_edit_mode", False) and self._is_field_editable(key, value, schema_field_specs):
                            content_editable_field_hitboxes.append((key, row_rect))

                        field_rows.append(
                            {
                                "section": section_name,
                                "key": key,
                                "row_rect": row_rect,
                                "key_rect": key_rect,
                                "value_rect": value_rect,
                                "key_lines": key_lines,
                                "wrapped_lines": wrapped_lines,
                                "relation_chips": relation_chips,
                            }
                        )

                        current_y = row_rect.bottom + self.SECTION_GAP

                    current_y += self.SECTION_GAP

            content_end_y = current_y

        scroll_max_y = max(0, int(content_end_y - content_viewport_rect.bottom))
        scroll_y = max(0, min(scroll_max_y, int(card.get("scroll_y", 0) or 0)))
        card["scroll_y"] = scroll_y
        card["scroll_max_y"] = scroll_max_y
        card["content_viewport_rect"] = content_viewport_rect

        section_draw_rects = []
        if not self._is_general_mode() and scroll_y:
            if image_rect is not None:
                image_rect = image_rect.move(0, -scroll_y)

            media_import_hitboxes = [
                (role_name, button_rect.move(0, -scroll_y).clip(content_viewport_rect))
                for role_name, button_rect in media_import_hitboxes
                if button_rect.move(0, -scroll_y).colliderect(content_viewport_rect)
            ]

            shifted_section_hitboxes = []
            for section_name, section_rect in section_hitboxes:
                shifted_rect = section_rect.move(0, -scroll_y)
                section_draw_rects.append((section_name, shifted_rect))
                clipped_rect = shifted_rect.clip(content_viewport_rect)
                if clipped_rect.height > 0:
                    shifted_section_hitboxes.append((section_name, clipped_rect))
            section_hitboxes = shifted_section_hitboxes

            for row in field_rows:
                for rect_key in ("row_rect", "key_rect", "value_rect"):
                    row[rect_key] = row[rect_key].move(0, -scroll_y)
                for chip in row.get("relation_chips", []):
                    chip["rect"] = chip["rect"].move(0, -scroll_y)
                    if chip.get("remove_rect") is not None:
                        chip["remove_rect"] = chip["remove_rect"].move(0, -scroll_y)

            for field_key, field_rect in content_editable_field_hitboxes:
                shifted_rect = field_rect.move(0, -scroll_y)
                clipped_rect = shifted_rect.clip(content_viewport_rect)
                if clipped_rect.height > 0:
                    editable_field_hitboxes.append((field_key, clipped_rect))
        elif not self._is_general_mode():
            section_draw_rects = list(section_hitboxes)
            media_import_hitboxes = [
                (role_name, button_rect.clip(content_viewport_rect))
                for role_name, button_rect in media_import_hitboxes
                if button_rect.colliderect(content_viewport_rect)
            ]
            section_hitboxes = [
                (section_name, section_rect.clip(content_viewport_rect))
                for section_name, section_rect in section_hitboxes
                if section_rect.colliderect(content_viewport_rect)
            ]
            for field_key, field_rect in content_editable_field_hitboxes:
                clipped_rect = field_rect.clip(content_viewport_rect)
                if clipped_rect.height > 0:
                    editable_field_hitboxes.append((field_key, clipped_rect))

        if not self._is_general_mode():
            for row in field_rows:
                for chip in row.get("relation_chips", []):
                    chip_rect = chip.get("rect")
                    if chip_rect is None or not chip_rect.colliderect(content_viewport_rect):
                        continue
                    relation_hitboxes.append((chip, chip_rect.clip(content_viewport_rect)))

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            frac = 0.5 if len(years) == 1 else index / (len(years) - 1)
            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

        header_drag_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H)
        corner_resize_hitboxes = [
            ("top_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("top_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
        ]
        edge_resize_hitboxes = [
            ("left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("right", pygame.Rect(rect.right - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("top", pygame.Rect(rect.x, rect.y - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
            ("bottom", pygame.Rect(rect.x, rect.bottom - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
        ]
        resize_hitboxes = corner_resize_hitboxes + edge_resize_hitboxes
        corner_handle_size = max(8, min(12, self.RESIZE_HANDLE))
        corner_handle_rects = [
            pygame.Rect(rect.x, rect.y, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.right - corner_handle_size, rect.y, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.x, rect.bottom - corner_handle_size, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.right - corner_handle_size, rect.bottom - corner_handle_size, corner_handle_size, corner_handle_size),
        ]

        final_rect = pygame.Rect(rect.x, rect.y, rect.width, rect.height)

        card["rect"] = final_rect
        card["tab_hitboxes"] = tab_hitboxes
        card["image_rect"] = image_rect
        card["general_content_rect"] = general_content_rect
        card["timeline_label_y"] = timeline_label_y
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["corner_handle_rects"] = corner_handle_rects
        card["section_hitboxes"] = section_hitboxes
        card["section_draw_rects"] = section_draw_rects
        card["media_import_hitboxes"] = media_import_hitboxes
        card["editable_field_hitboxes"] = editable_field_hitboxes
        card["relation_hitboxes"] = relation_hitboxes
        card["field_rows"] = field_rows
        card["resize_hitboxes"] = resize_hitboxes
        card["edit_toggle_rect"] = edit_toggle_rect
        card["idea_button_rect"] = idea_button_rect
        card["close_rect"] = close_rect
        card["title_edit_rect"] = title_edit_rect
        card["type_label_rect"] = type_label_rect
        card["year_hitboxes"] = [
            (year, pygame.Rect(year_x - 12, center_y - 12, 24, 48))
            for year, year_x in year_positions
        ]

    def get_minimum_height(self, card, font):
        """
        Estimate the minimum card height needed for currently visible content,
        including wrapped text.
        """
        section_map = self._sectioned_fields()

        if self._is_general_mode():
            content_rect = pygame.Rect(0, 0, int(card.get("canvas_w", 420)) - 24, 0)
            general_h = CardWikiRenderer.measure_content(
                self._get_general_wiki_text(card),
                font,
                content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
            )
            timeline_label_y = self.HEADER_H + self.TAB_H + 20 + general_h + 8
            timeline_y = timeline_label_y + 18
            center_y = timeline_y + 10
            launch_top = center_y + 24
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(320, resize_bottom + 8)

        current_y = self.IMAGE_TOP + self._image_block_height() + 12
        if not self._uses_image_block():
            current_y = self.HEADER_H + self.TAB_H + 20
        probe_rect = pygame.Rect(0, 0, int(card.get("canvas_w", 420)), 0)
        key_column_w, value_column_w = self._get_table_column_widths(font, probe_rect, section_map)

        for section_name in self._visible_sections():
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP

            if not self.collapsed_sections.get(section_name, False):
                for key, value in section_map.get(section_name, []):
                    _, _, row_h = self._measure_table_row(font, key, value, key_column_w, value_column_w)
                    current_y += row_h + self.SECTION_GAP

                current_y += self.SECTION_GAP

        timeline_label_y = current_y + 8
        timeline_y = timeline_label_y + 18
        center_y = timeline_y + 10
        launch_top = center_y + 24
        resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE

        return max(260, resize_bottom + 8)

    def draw_card(self, screen, font, card):
        rect = card["rect"]

        pygame.draw.rect(screen, (28, 30, 38), rect)
        pygame.draw.rect(screen, (170, 170, 170), rect, 1)

        header_rect = card["header_drag_rect"]
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(
            screen,
            (110, 110, 120),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        title_text = card.get("title", "")
        if card.get("is_edit_mode", False):
            title_edit_rect = card.get("title_edit_rect")
            title_active = card.get("active_edit_field") == self._title_edit_field()
            if title_edit_rect is not None:
                title_fill = (48, 54, 68) if title_active else (38, 43, 56)
                title_border = (182, 202, 236) if title_active else (92, 104, 128)
                pygame.draw.rect(screen, title_fill, title_edit_rect)
                pygame.draw.rect(screen, title_border, title_edit_rect, 1)
            if title_active:
                title_text = card.get("edit_buffer", "")

        title_surface = font.render(title_text, True, (245, 245, 245))
        subtitle_surface = font.render(card["subtitle"], True, (170, 170, 170))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        type_label_rect = card.get("type_label_rect")
        if type_label_rect is not None and self._is_idea_card():
            hover_pos = pygame.mouse.get_pos()
            if type_label_rect.collidepoint(hover_pos):
                pygame.draw.rect(screen, (42, 48, 62), type_label_rect)
                pygame.draw.rect(screen, (130, 150, 190), type_label_rect, 1)
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 30))

        edit_toggle_rect = card.get("edit_toggle_rect")
        idea_button_rect = card.get("idea_button_rect")
        close_rect = card.get("close_rect")
        if idea_button_rect is not None:
            pygame.draw.rect(screen, (52, 60, 48), idea_button_rect)
            pygame.draw.rect(screen, (150, 176, 132), idea_button_rect, 1)
            idea_text = font.render("I", True, (230, 244, 218))
            idea_text_rect = idea_text.get_rect(center=idea_button_rect.center)
            screen.blit(idea_text, idea_text_rect)

        if edit_toggle_rect is not None:
            edit_enabled = bool(card.get("is_edit_mode", False))
            edit_fill = (70, 96, 140) if edit_enabled else (46, 50, 60)
            edit_border = (210, 220, 240) if edit_enabled else (140, 140, 150)
            edit_text_color = (245, 245, 245) if edit_enabled else (210, 210, 210)

            pygame.draw.rect(screen, edit_fill, edit_toggle_rect)
            pygame.draw.rect(screen, edit_border, edit_toggle_rect, 1)
            edit_text = font.render("E", True, edit_text_color)
            edit_text_rect = edit_text.get_rect(center=edit_toggle_rect.center)
            screen.blit(edit_text, edit_text_rect)

        if close_rect is not None:
            pygame.draw.rect(screen, (58, 44, 48), close_rect)
            pygame.draw.rect(screen, (178, 132, 140), close_rect, 1)
            close_text = font.render("X", True, (244, 218, 222))
            close_text_rect = close_text.get_rect(center=close_rect.center)
            screen.blit(close_text, close_text_rect)

        if card.get("is_edit_mode", False):
            active_field = card.get("active_edit_field")
            if active_field:
                if active_field in self.TEMPORAL_FIELDS:
                    edit_status = f"Editing {active_field} | Click timeline to set | Enter save | Esc cancel"
                elif active_field == "wiki_entry":
                    edit_status = "Editing wiki_entry | Enter newline | Ctrl+Enter save | Ctrl+L link"
                elif self.is_relation_edit_field(active_field):
                    edit_status = f"Editing {active_field} | Search relations | Enter insert | Ctrl+Enter save"
                else:
                    edit_status = f"Editing {active_field} | Enter save | Esc cancel | Tab next"
            else:
                edit_status = "Edit mode | Click a highlighted row or press Tab to begin"
            status_surface = font.render(edit_status, True, (190, 205, 230))
            status_x = rect.right - 44 - status_surface.get_width()
            status_x = max(rect.x + 150, status_x)
            screen.blit(status_surface, (status_x, rect.y + 30))

        self._draw_tabs(screen, font, card)
        if self._is_general_mode():
            self._draw_general_content(screen, font, card)
        else:
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                if self._uses_image_block():
                    self._draw_image_block(screen, font, card)
                self._draw_sections(screen, font, card)
            finally:
                screen.set_clip(previous_clip)

        timeline_label_y = card.get("timeline_label_y", card["timeline_y"] - 18)
        timeline_y = card["timeline_y"]
        left_x = rect.x + 20
        right_x = rect.right - 20
        center_y = timeline_y + 10

        years = card.get("years", [])
        if len(years) >= 2:
            timeline_label = f"Range: {years[0]}-{years[-1]}"
        elif len(years) == 1:
            timeline_label = f"Year: {years[0]}"
        else:
            timeline_label = "Year: 0"

        timeline_label_surface = font.render(timeline_label, True, (200, 200, 200))
        screen.blit(timeline_label_surface, (rect.x + 12, timeline_label_y))

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)

        for year, hitbox in card["year_hitboxes"]:
            marker_rect = pygame.Rect(hitbox.centerx - 5, center_y - 5, 10, 10)
            selected = year == card["selected_year"]

            fill = (210, 210, 210) if selected else (70, 70, 70)
            border = (240, 240, 240) if selected else (170, 170, 170)
            pygame.draw.rect(screen, fill, marker_rect)
            pygame.draw.rect(screen, border, marker_rect, 1)

            year_surface = font.render(str(year), True, (230, 230, 230))
            year_rect = year_surface.get_rect(center=(hitbox.centerx, center_y + 22))
            screen.blit(year_surface, year_rect)

        launch_rect = card["launch_rect"]
        pygame.draw.rect(screen, (55, 55, 55), launch_rect)
        pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
        launch_text = font.render(f"Launch [{card['selected_year']}]", True, (245, 245, 245))
        launch_text_rect = launch_text.get_rect(center=launch_rect.center)
        screen.blit(launch_text, launch_text_rect)

        for handle_rect in card.get("corner_handle_rects", []):
            pygame.draw.rect(screen, (105, 112, 126), handle_rect)
            pygame.draw.rect(screen, (220, 224, 232), handle_rect, 1)

        handle_rect = card["resize_handle_rect"]
        pygame.draw.rect(screen, (120, 120, 120), handle_rect)
        pygame.draw.rect(screen, (220, 220, 220), handle_rect, 1)

    def _draw_tabs(self, screen, font, card):
        for tab_name, tab_rect in card.get("tab_hitboxes", []):
            selected = tab_name == self.active_tab
            fill = (58, 64, 78) if selected else (36, 40, 50)
            border = (200, 200, 210) if selected else (110, 110, 120)
            text_color = (245, 245, 245) if selected else (195, 195, 195)

            pygame.draw.rect(screen, fill, tab_rect)
            pygame.draw.rect(screen, border, tab_rect, 1)

            label = self.TAB_LABELS.get(tab_name, tab_name.title())
            abbreviations = {
                "general": "Gen",
                "overview": "Over",
                "temporal": "Temp",
                "relations": "Rel",
                "state": "State",
                "operational": "Ops",
                "media": "Media",
            }
            if font.size(label)[0] > tab_rect.width - 8:
                label = abbreviations.get(tab_name, label[:4])
            text_surface = font.render(label, True, text_color)
            text_rect = text_surface.get_rect(center=tab_rect.center)
            screen.blit(text_surface, text_rect)

    def _draw_scaled_preview(self, screen, image_surface, target_rect):
        inner_rect = target_rect.inflate(-8, -8)
        src_w = max(1, image_surface.get_width())
        src_h = max(1, image_surface.get_height())
        scale = min(inner_rect.width / src_w, inner_rect.height / src_h)

        target_w = max(1, int(src_w * scale))
        target_h = max(1, int(src_h * scale))
        scaled = pygame.transform.smoothscale(image_surface, (target_w, target_h))
        scaled_rect = scaled.get_rect(center=inner_rect.center)
        screen.blit(scaled, scaled_rect)

    def _draw_media_block(self, screen, font, card, image_rect):
        preview_rect = pygame.Rect(image_rect.x + 8, image_rect.y + 8, image_rect.width - 16, 88)
        pygame.draw.rect(screen, (32, 34, 44), preview_rect)
        pygame.draw.rect(screen, (100, 100, 110), preview_rect, 1)

        image_ref = self._resolve_image_reference()
        image_surface = self._load_card_image_surface(image_ref)

        if image_surface is not None:
            self._draw_scaled_preview(screen, image_surface, preview_rect)
            label_text = "Preview image"
        else:
            no_image = font.render("No active preview image", True, (195, 195, 195))
            no_image_rect = no_image.get_rect(center=preview_rect.center)
            screen.blit(no_image, no_image_rect)
            label_text = ScaleHelper.format_dimensions_label(self.entity)

        label_surface = font.render(label_text, True, (195, 195, 195))
        screen.blit(label_surface, (preview_rect.x + 6, preview_rect.y + 6))

        divider_y = image_rect.y + 102
        pygame.draw.line(screen, (90, 90, 100), (image_rect.x + 8, divider_y), (image_rect.right - 8, divider_y), 1)

        row_y = divider_y + 8
        text_x = image_rect.x + 10

        buttons_by_role = {role_name: rect for role_name, rect in card.get("media_import_hitboxes", [])}

        for media_info in ScaleHelper.suggest_media_canvases(self.entity):
            role_name = media_info["role"]
            width_px = media_info["width"]
            height_px = media_info["height"]
            role_ref = self._resolve_role_image_reference(role_name)
            status = "set" if role_ref else "empty"

            line = f"{role_name.title()}: {width_px} x {height_px} [{status}]"
            surf = font.render(line, True, (195, 195, 195))
            screen.blit(surf, (text_x, row_y))

            button_rect = buttons_by_role.get(role_name)
            if button_rect is not None:
                pygame.draw.rect(screen, (58, 64, 78), button_rect)
                pygame.draw.rect(screen, (200, 200, 210), button_rect, 1)
                button_text = font.render("Import", True, (245, 245, 245))
                button_text_rect = button_text.get_rect(center=button_rect.center)
                screen.blit(button_text, button_text_rect)

            row_y += 20

    def _draw_image_block(self, screen, font, card):
        if self._is_general_mode():
            return

        image_rect = card["image_rect"]
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)

        if self._is_media_mode():
            self._draw_media_block(screen, font, card, image_rect)
            return

        image_ref = self._resolve_image_reference()
        image_surface = self._load_card_image_surface(image_ref)

        if image_surface is not None:
            self._draw_scaled_preview(screen, image_surface, image_rect)
            return

        dims_label = ScaleHelper.format_dimensions_label(self.entity)
        current_y = image_rect.y + 8

        if ScaleHelper.suggest_default_media_roles(self.entity):
            lines = [
                "No image",
                dims_label,
            ]

            for line in lines:
                surf = font.render(line, True, (195, 195, 195))
                screen.blit(surf, (image_rect.x + 10, current_y))
                current_y += self.IMAGE_TEXT_LINE_H

            for media_info in ScaleHelper.suggest_media_canvases(self.entity):
                role_name = media_info["role"].title()
                width_px = media_info["width"]
                height_px = media_info["height"]
                line = f"{role_name}: {width_px} x {height_px}"
                surf = font.render(line, True, (195, 195, 195))
                screen.blit(surf, (image_rect.x + 10, current_y))
                current_y += self.IMAGE_TEXT_LINE_H

            footer = font.render("Open Media tab to import views", True, (195, 195, 195))
            screen.blit(footer, (image_rect.x + 10, current_y))
            return

        canvas = ScaleHelper.suggest_canvas_from_dimensions(self.entity)
        lines = [
            "No image",
            dims_label,
            f"Suggested canvas: {canvas['width']} x {canvas['height']}",
            "Import image later",
        ]

        for line in lines:
            surf = font.render(line, True, (195, 195, 195))
            screen.blit(surf, (image_rect.x + 10, current_y))
            current_y += self.IMAGE_TEXT_LINE_H

    def _draw_sections(self, screen, font, card):
        if self._is_general_mode():
            return

        card["relation_picker_hitboxes"] = []
        editable_hitboxes = {
            field_key: field_rect
            for field_key, field_rect in card.get("editable_field_hitboxes", [])
        }
        rows_by_section = {}
        for row in card.get("field_rows", []):
            rows_by_section.setdefault(row["section"], []).append(row)
        active_relation_anchor = None
        section_draw_rects = card.get("section_draw_rects", card.get("section_hitboxes", []))

        for section_name in self._visible_sections():
            header_rect = next((rect for name, rect in section_draw_rects if name == section_name), None)
            if header_rect is None:
                continue

            pygame.draw.rect(screen, (36, 40, 50), header_rect)
            pygame.draw.rect(screen, (110, 110, 120), header_rect, 1)

            expanded = not self.collapsed_sections.get(section_name, False)
            marker = "v" if expanded else ">"
            header_text = font.render(f"{marker} {section_name}", True, (235, 235, 235))
            screen.blit(header_text, (header_rect.x + 8, header_rect.y + 3))

            current_y = header_rect.bottom + 4

            if not expanded:
                continue

            for row_index, row in enumerate(rows_by_section.get(section_name, [])):
                key = row["key"]
                row_rect = row["row_rect"]
                is_active_field = key == card.get("active_edit_field")
                is_relation_link_target = key == card.get("active_relation_link_field")
                is_editable = key in editable_hitboxes

                row_fill = (33, 36, 46) if row_index % 2 == 0 else (29, 32, 42)
                row_border = (78, 84, 100)
                if is_editable:
                    row_fill = (42, 47, 58)
                if is_relation_link_target:
                    row_fill = (36, 50, 70)
                    row_border = (126, 166, 224)
                if is_active_field:
                    row_fill = (54, 62, 76)
                    row_border = (180, 200, 240)

                pygame.draw.rect(screen, row_fill, row_rect)
                pygame.draw.rect(screen, row_border, row_rect, 1)
                pygame.draw.line(
                    screen,
                    (88, 94, 112),
                    (row["key_rect"].right + self.TABLE_COLUMN_GAP // 2, row_rect.y + 1),
                    (row["key_rect"].right + self.TABLE_COLUMN_GAP // 2, row_rect.bottom - 1),
                    1,
                )

                key_lines = row.get("key_lines") or [f"{key}:"]
                key_y = row_rect.y + self.TABLE_ROW_PAD_Y
                line_h = self._table_line_height(font)
                key_text_max_w = 0
                for key_line in key_lines:
                    key_surface = font.render(key_line, True, (210, 210, 210))
                    key_text_max_w = max(key_text_max_w, key_surface.get_width())
                    screen.blit(key_surface, (row["key_rect"].x + 6, key_y))
                    key_y += line_h

                if is_editable and not is_active_field:
                    hint_label = "timeline" if key in self.TEMPORAL_FIELDS else "editable"
                    hint_surface = font.render(hint_label, True, (130, 150, 185))
                    hint_x = row["key_rect"].right - hint_surface.get_width() - 6
                    key_text_right = row["key_rect"].x + 6 + key_text_max_w
                    if len(key_lines) == 1 and hint_x > key_text_right + 8:
                        screen.blit(hint_surface, (hint_x, row_rect.y + self.TABLE_ROW_PAD_Y))

                if is_active_field and card.get("is_edit_mode", False):
                    wrapped_lines = self._wrap_text_lines(
                        card.get("edit_buffer", ""),
                        font,
                        row["value_rect"].width,
                    )
                    value_color = (245, 245, 245)
                else:
                    value_color = (215, 225, 245) if is_editable else (180, 180, 180)
                    wrapped_lines = row["wrapped_lines"]

                relation_chips = row.get("relation_chips", [])
                if relation_chips and not is_active_field:
                    for chip in relation_chips:
                        chip_rect = chip["rect"]
                        kind = chip.get("kind")
                        if kind == "existing":
                            chip_fill = (38, 58, 54)
                            chip_border = (122, 190, 170)
                            chip_text_color = (222, 244, 236)
                        elif kind == "missing":
                            chip_fill = (64, 48, 38)
                            chip_border = (218, 152, 104)
                            chip_text_color = (250, 222, 190)
                        elif kind == "link_existing":
                            chip_fill = (42, 62, 92) if is_relation_link_target else (34, 44, 64)
                            chip_border = (178, 206, 244) if is_relation_link_target else (124, 154, 210)
                            chip_text_color = (218, 230, 250)
                        else:
                            chip_fill = (44, 48, 56)
                            chip_border = (132, 142, 160)
                            chip_text_color = (204, 214, 228)

                        pygame.draw.rect(screen, chip_fill, chip_rect)
                        pygame.draw.rect(screen, chip_border, chip_rect, 1)
                        remove_rect = chip.get("remove_rect")
                        text_max_w = chip_rect.width - 10
                        if remove_rect is not None:
                            text_max_w = max(12, remove_rect.x - chip_rect.x - 10)
                        label = self._ellipsize_text(
                            chip.get("display_label", ""),
                            font,
                            text_max_w,
                        )
                        chip_surface = font.render(label, True, chip_text_color)
                        screen.blit(chip_surface, (chip_rect.x + 6, chip_rect.y + max(2, (chip_rect.height - line_h) // 2)))
                        if remove_rect is not None:
                            pygame.draw.rect(screen, chip_border, remove_rect, 1)
                            remove_surface = font.render("x", True, chip_text_color)
                            remove_text_rect = remove_surface.get_rect(center=remove_rect.center)
                            screen.blit(remove_surface, remove_text_rect)
                else:
                    line_y = row_rect.y + self.TABLE_ROW_PAD_Y
                    for line in wrapped_lines:
                        val_surface = font.render(line, True, value_color)
                        screen.blit(val_surface, (row["value_rect"].x + 2, line_y))
                        line_y += line_h

                if is_active_field and card.get("relation_picker_open", False):
                    active_relation_anchor = row["value_rect"]

        if active_relation_anchor is not None:
            self._draw_relation_picker(screen, font, card, active_relation_anchor)

    def _draw_general_content(self, screen, font, card):
        general_rect = card.get("general_content_rect")
        if general_rect is None:
            return

        is_editing = card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry"
        wiki_text = self._get_general_wiki_text(card)
        CardWikiRenderer.draw_content(
            screen,
            font,
            general_rect,
            wiki_text,
            is_editing=is_editing,
            resolve_link_label=self._resolve_wiki_link_label,
            cursor_index=card.get("edit_cursor", 0),
            scroll_y=card.get("scroll_y", 0),
        )

        if card.get("wiki_link_picker_open", False):
            self._draw_wiki_link_picker(screen, font, card, general_rect)

    def _draw_wiki_link_picker(self, screen, font, card, general_rect):
        matches = card.get("wiki_link_matches", [])
        picker_w = min(360, general_rect.width - 16)
        picker_h = 66 + min(6, len(matches)) * 42
        picker_rect = pygame.Rect(
            general_rect.x + 12,
            general_rect.y + 12,
            picker_w,
            picker_h,
        )
        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (186, 194, 210), picker_rect, 1)

        title_surface = font.render("Insert Entry Link", True, (244, 244, 244))
        screen.blit(title_surface, (picker_rect.x + 10, picker_rect.y + 8))

        query_rect = pygame.Rect(picker_rect.x + 10, picker_rect.y + 28, picker_rect.width - 20, 24)
        pygame.draw.rect(screen, (36, 42, 56), query_rect)
        pygame.draw.rect(screen, (126, 136, 154), query_rect, 1)
        query_text = card.get("wiki_link_query", "")
        query_surface = font.render(query_text or "Search entries...", True, (232, 232, 232) if query_text else (156, 164, 178))
        screen.blit(query_surface, (query_rect.x + 8, query_rect.y + 4))

        selected_index = card.get("wiki_link_selected_index", 0)
        row_y = query_rect.bottom + 8
        for index, match in enumerate(matches[:6]):
            row_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 36)
            fill = (54, 64, 82) if index == selected_index else (30, 34, 44)
            border = (194, 206, 228) if index == selected_index else (88, 96, 112)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, border, row_rect, 1)

            primary = f"{match['pretty_name']} | {match['id']}"
            start_text = "" if match["start_year"] is None else str(match["start_year"])
            end_text = "" if match["end_year"] is None else str(match["end_year"])
            secondary = f"{start_text} | {end_text}"

            primary_surface = font.render(primary, True, (242, 242, 242))
            secondary_surface = font.render(secondary, True, (186, 194, 208))
            screen.blit(primary_surface, (row_rect.x + 8, row_rect.y + 3))
            screen.blit(secondary_surface, (row_rect.x + 8, row_rect.y + 18))
            row_y += 40

    def _draw_relation_picker(self, screen, font, card, anchor_rect):
        matches = card.get("relation_picker_matches", [])
        picker_w = min(380, max(220, anchor_rect.width))
        picker_h = 66 + min(6, len(matches)) * 42
        picker_rect = pygame.Rect(anchor_rect.x, anchor_rect.bottom + 6, picker_w, picker_h)
        card["relation_picker_hitboxes"] = []

        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (186, 194, 210), picker_rect, 1)

        title_surface = font.render("Select Relation", True, (244, 244, 244))
        screen.blit(title_surface, (picker_rect.x + 10, picker_rect.y + 8))

        query_rect = pygame.Rect(picker_rect.x + 10, picker_rect.y + 28, picker_rect.width - 20, 24)
        pygame.draw.rect(screen, (36, 42, 56), query_rect)
        pygame.draw.rect(screen, (126, 136, 154), query_rect, 1)
        query_text = card.get("relation_picker_query", "")
        query_surface = font.render(
            query_text or "Search entries...",
            True,
            (232, 232, 232) if query_text else (156, 164, 178),
        )
        screen.blit(query_surface, (query_rect.x + 8, query_rect.y + 4))

        selected_index = card.get("relation_picker_selected_index", 0)
        row_y = query_rect.bottom + 8
        for index, match in enumerate(matches[:6]):
            row_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 36)
            fill = (54, 64, 82) if index == selected_index else (30, 34, 44)
            border = (194, 206, 228) if index == selected_index else (88, 96, 112)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, border, row_rect, 1)
            card["relation_picker_hitboxes"].append((index, row_rect))

            primary = f"{match['pretty_name']} | {match['id']}"
            dataset = match.get("dataset", "")
            secondary = f"{dataset} | {match.get('entity_type', 'entity')}"

            primary_surface = font.render(primary, True, (242, 242, 242))
            secondary_surface = font.render(secondary, True, (186, 194, 208))
            screen.blit(primary_surface, (row_rect.x + 8, row_rect.y + 3))
            screen.blit(secondary_surface, (row_rect.x + 8, row_rect.y + 18))
            row_y += 40
