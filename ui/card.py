import os
import colorsys

import pygame

from engine.scaler import ScaleHelper
from ui.card_wiki import CardWikiRenderer
from ui.text_editing import TextEditing
from world.schema_loader import SchemaLoader
from simulations.space.stellar import STELLAR_CLASS_HELP, is_valid_stellar_class
from simulations.phylogeny.clade_graph import (
    clade_label,
    find_clade_matches,
    get_clade_entities,
    is_species_entity,
    phylogeny_graph_context,
)


class EntityCard:
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    """
    Reusable renderer + interaction helper for one repository entity card.
    """

    HEADER_H = 50
    TAB_H = 24
    SECTION_HEADER_H = 22
    IMAGE_TOP = 86
    IMAGE_H = 110
    MEDIA_IMAGE_H = 244
    LAUNCH_H = 24
    TIMELINE_TO_LAUNCH_GAP = 58
    RELATED_TIMELINE_OFFSET_Y = 34
    RELATED_TIMELINE_LABEL_LIMIT = 5
    TOOLBELT_W = 148
    CARD_COLOR_DEFAULT = "#1c1e26"
    CARD_COLOR_SLIDERS = [("h", "H"), ("s", "S"), ("v", "B")]
    CARD_COLOR_ROLES = [
        ("body", "Body"),
        ("header", "Banner"),
        ("wiki", "Wiki"),
    ]
    RESIZE_HANDLE = 14
    RESIZE_BORDER = 6
    TEXT_LINE_H = 16
    IMAGE_TEXT_LINE_H = 18
    PHYLOGENY_PARENT_PANEL_H = 230
    SECTION_GAP = 4
    TABLE_ROW_PAD_Y = 3
    TABLE_COLUMN_GAP = 14
    TABLE_MIN_KEY_W = 96
    TABLE_MAX_KEY_W = 260
    TABLE_MIN_VALUE_W = 120
    STANDARD_RELATION_FIELDS = [
        "parents",
        "related",
        "offspring",
    ]
    CORE_RELATION_FIELDS = set(STANDARD_RELATION_FIELDS)
    IDEA_GENERIC_FIELDS = {
        "id",
        "pretty_name",
        "name",
        "type",
        "idea_class",
        "wiki_entry",
        "three_word_description",
        "description",
        "date",
        "media_path",
        "card_color",
        "card_header_color",
        "wiki_field_colors",
        "tags",
        "start_year",
        "start_event",
        "end_year",
        "end_event",
        "parents",
        "related",
        "offspring",
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

    SUBTAB_H = 22
    TAB_ORDER = ["general", "overview", "temporal", "relations", "state", "simulation", "media"]
    DATASET_TAB_ORDER = {
        "ideas": ["general", "overview", "temporal", "relations", "media"],
        "cladistics": ["general", "overview", "phylogeny", "relations", "temporal", "media"],
        "species": ["general", "overview", "phylogeny", "relations", "temporal", "media"],
        "components": ["general", "overview", "temporal", "relations", "operational", "simulation", "media"],
    }
    TAB_LABELS = {
        "general": "General",
        "overview": "Overview",
        "temporal": "Temporal",
        "relations": "Relations",
        "phylogeny": "Phylogeny",
        "state": "State",
        "simulation": "Simulation",
        "operational": "Operational",
        "media": "Media",
    }
    SIMULATION_SUBTAB_ORDER = ["orbital", "map", "world_gen"]
    SIMULATION_SUBTAB_LABELS = {
        "orbital": "Orbital",
        "map": "Map Sim",
        "world_gen": "World Gen",
    }
    TAB_SECTIONS = {
        "general": [],
        "overview": ["Identity", "Classification", "Dimensions / Scale", "Metadata"],
        "temporal": ["Temporal"],
        "relations": ["Relations"],
        "state": ["State / Layout"],
        "operational": ["Operational"],
        "simulation": [],
        "media": ["Media"],
    }
    SIMULATION_SUBTAB_SECTIONS = {
        "orbital": ["Simulation / Orbital"],
        "map": ["Simulation / Map Sim"],
        "world_gen": ["Simulation / World Gen"],
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
    }
    MEDIA_FIELDS = {
        "media_path",
        "card_image",
        "card_image_front",
        "card_image_side",
        "card_image_top",
        "image_path",
        "map_image_path",
        "media_layers",
    }
    SPACE_SIM_FIELDS = {
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
    }
    MAP_SIM_FIELDS = {
        "coords",
        "bounds",
        "geometry",
        "layer_kind",
        "parent_entity",
        "owner_entity",
        "coverage_mode",
        "resolution_m_per_pixel",
        "draw_order",
        "map_projection",
        "map_status",
        "map_canvas_width_px",
        "map_canvas_height_px",
    }
    WORLD_GEN_SIM_FIELDS = {
        "world_gen_seed",
        "crust_composition",
        "derived_planet_physics",
        "atmosphere_model",
        "atmosphere_summary",
        "interior_regime_model",
        "surface_process_model",
        "terrain_seed_model",
        "tectonic_model",
        "crater_model",
        "heightmap_model",
        "map_generation_recipe",
        "map_layers",
        "environment_summary",
        "geology_summary",
        "hydrology_summary",
        "ecology_summary",
    }
    TOOLBELT_TOOL_DEFINITIONS = [
        {
            "match": {"person", "people"},
            "tools": [
                {
                    "id": "person_add_parent",
                    "label": "Add Parent",
                    "description": "Create a person and link them as a parent.",
                    "target_dataset": "people",
                    "prompt_label": "Parent Person",
                },
                {
                    "id": "person_add_child",
                    "label": "Add Child",
                    "description": "Create a person with this card as a parent.",
                    "target_dataset": "people",
                    "prompt_label": "Child Person",
                },
            ],
        },
        {
            "match": {"producer", "producers"},
            "tools": [
                {
                    "id": "producer_add_product_item",
                    "label": "Add Product",
                    "description": "Create an item and add it to produced_items.",
                    "target_dataset": "items",
                    "prompt_label": "Product Item",
                },
                {
                    "id": "producer_add_product_vehicle",
                    "label": "Add Vehicle",
                    "description": "Create a vehicle and add it to produced_vehicles.",
                    "target_dataset": "vehicles",
                    "prompt_label": "Vehicle Product",
                },
                {
                    "id": "producer_add_product_component",
                    "label": "Add Component",
                    "description": "Create a component and add it to produced_components.",
                    "target_dataset": "components",
                    "prompt_label": "Component Product",
                },
            ],
        },
        {
            "match": {"star_system", "stellar_system"},
            "tools": [
                {
                    "id": "stellar_world_gen",
                    "label": "World Gen",
                    "description": "Start planetary orbit generation in this star system.",
                    "action_id": "knowledge_launch_world_gen",
                },
                {
                    "id": "stellar_define_neighbourhood",
                    "label": "Define Neighbourhood",
                    "description": "Link another star system with a light-year distance.",
                    "action_id": "knowledge_define_stellar_neighbourhood",
                },
            ],
        },
        {
            "match": {"location", "locations"},
            "tools": [
                {
                    "id": "location_place_on_parent",
                    "label": "Place on Parent",
                    "description": "Open parent map placement for this location.",
                    "action_id": "knowledge_place_location_on_parent",
                    "requires": "surface_location",
                },
                {
                    "id": "planet_world_gen",
                    "label": "World Gen",
                    "description": "Start empty planetary generation for an unmapped planet.",
                    "action_id": "knowledge_launch_world_gen",
                    "requires": "planet_without_map",
                },
            ],
        },
    ]
    SCHEMA_LOADER = SchemaLoader()

    def __init__(self, entity, dataset_name=None, world_model=None):
        self.entity = entity or {}
        self.dataset_name = dataset_name or self.entity.get("_dataset", self.entity.get("type", "entity"))
        self.world_model = world_model
        self.active_tab = "general"
        self.active_simulation_subtab = "orbital"
        self.collapsed_sections = {
            "Identity": False,
            "Classification": False,
            "Dimensions / Scale": False,
            "Temporal": False,
            "Relations": False,
            "State / Layout": True,
            "Metadata": False,
            "Media": False,
            "Simulation / Orbital": False,
            "Simulation / Map Sim": False,
            "Simulation / World Gen": False,
            "Phylogeny Parents": False,
            "Phylogeny Children": False,
            "Members": False,
        }

    def _is_idea_card(self):
        return self.dataset_name == "ideas" or self.entity.get("type") == "idea"

    def _is_task_card(self):
        return self.dataset_name == "tasks" or self.entity.get("type") == "task"

    def _is_component_card(self):
        return self.dataset_name == "components" or self.entity.get("type") in {"component", "assembly"}

    def _is_species_card(self):
        return self.dataset_name == "species" or self.entity.get("type") == "species"

    def _is_cladistics_card(self):
        return self.dataset_name == "cladistics" or self.entity.get("type") == "cladistics"

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
            order = self.DATASET_TAB_ORDER["components"]
        else:
            order = self.DATASET_TAB_ORDER.get(self.dataset_name, self.TAB_ORDER)
        if self._has_simulation_fields():
            return order
        return [tab_name for tab_name in order if tab_name != "simulation"]

    def toggle_section(self, section_name):
        if section_name in self.collapsed_sections:
            self.collapsed_sections[section_name] = not self.collapsed_sections[section_name]

    def set_active_tab(self, tab_name):
        if tab_name in self._tab_order():
            self.active_tab = tab_name
            if tab_name == "simulation":
                self.active_simulation_subtab = self._default_simulation_subtab()

    def set_active_subtab(self, tab_name, subtab_name):
        if tab_name == "simulation" and subtab_name in self.SIMULATION_SUBTAB_ORDER:
            self.active_tab = tab_name
            self.active_simulation_subtab = subtab_name
            return True
        return False

    def _has_simulation_fields(self):
        keys = set(self.entity.keys()) | set(self._get_schema_field_specs().keys())
        simulation_keys = self.SPACE_SIM_FIELDS | self.MAP_SIM_FIELDS | self.WORLD_GEN_SIM_FIELDS
        return bool(keys & simulation_keys)

    def _active_subtab_order(self):
        if self.active_tab == "simulation":
            return self.SIMULATION_SUBTAB_ORDER
        return []

    def _default_simulation_subtab(self):
        keys = set(self.entity.keys())
        if keys & (self.SPACE_SIM_FIELDS | {"mass_kg"}) and self._is_space_sim_context():
            return "orbital"
        if keys & self.MAP_SIM_FIELDS:
            return "map"
        if keys & self.WORLD_GEN_SIM_FIELDS:
            return "world_gen"
        return self.active_simulation_subtab if self.active_simulation_subtab in self.SIMULATION_SUBTAB_ORDER else "orbital"

    def _visible_sections(self):
        if self.active_tab == "simulation":
            return self.SIMULATION_SUBTAB_SECTIONS.get(
                self.active_simulation_subtab,
                self.SIMULATION_SUBTAB_SECTIONS["orbital"],
            )
        return self.TAB_SECTIONS.get(self.active_tab, self.TAB_SECTIONS["general"])

    def _is_media_mode(self):
        return self.active_tab == "media"

    def _is_phylogeny_mode(self):
        return self.active_tab == "phylogeny" and (self._is_cladistics_card() or self._is_species_card())

    def _is_temporal_mode(self):
        return self.active_tab == "temporal"

    def _is_general_mode(self):
        return self.active_tab == "general"

    def _uses_image_block(self):
        return self._is_media_mode() or self._is_temporal_mode()

    def _field_spec(self, field_key):
        return self._normalize_field_spec(self._get_schema_field_specs().get(field_key, {}))

    def _normalize_field_spec(self, spec):
        if isinstance(spec, dict):
            return spec
        if isinstance(spec, str):
            return {"type": spec}
        return {}

    def is_relation_edit_field(self, field_key):
        if field_key in self.CORE_RELATION_FIELDS:
            return True
        spec = self._field_spec(field_key)
        field_type = str(spec.get("type", "")).lower()
        target = str(spec.get("target", "")).strip()
        if target:
            return True
        return "entity" in field_type or field_type in {"idea", "idea_list"}

    def _relation_field_allows_many(self, field_key):
        if field_key in self.CORE_RELATION_FIELDS:
            return True
        field_type = str(self._field_spec(field_key).get("type", "")).lower()
        return "list" in field_type

    def _relation_field_target(self, field_key):
        if field_key in self.CORE_RELATION_FIELDS:
            return "entity_core"
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

    def _relation_chip_colors(self, item, is_relation_link_target=False):
        kind = item.get("kind") if isinstance(item, dict) else ""
        if kind == "existing":
            palette = self._relation_chip_palette(item)
            if palette is not None:
                return palette["fill"], palette["border"], palette["text"]
            return (38, 58, 54), (122, 190, 170), (222, 244, 236)

        if kind == "missing":
            return (64, 48, 38), (218, 152, 104), (250, 222, 190)
        if kind == "link_existing":
            if is_relation_link_target:
                return (42, 62, 92), (178, 206, 244), (218, 230, 250)
            return (34, 44, 64), (124, 154, 210), (218, 230, 250)
        return (44, 48, 56), (132, 142, 160), (204, 214, 228)

    def _relation_chip_palette(self, item, is_relation_link_target=False):
        kind = item.get("kind") if isinstance(item, dict) else ""
        if kind != "existing":
            fill, border, text = self._relation_chip_colors(item, is_relation_link_target=is_relation_link_target)
            return {"fill": fill, "border": border, "text": text, "band": None}
        if self.world_model is None:
            return None
        return self._entity_link_palette(self.world_model.get_entity(item.get("entity_id")))

    def _entity_card_color(self, entity_or_id, fallback=None):
        entity = entity_or_id
        if isinstance(entity_or_id, str) and self.world_model is not None:
            entity = self.world_model.get_entity(entity_or_id)
        if not isinstance(entity, dict):
            return fallback
        color_value = entity.get("card_color") or entity.get("wiki_link_color")
        if not color_value:
            return fallback
        return self._coerce_hex_color(color_value, fallback=fallback)

    def _coerce_color_value(self, value, fallback=None):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in value[:3])
            except (TypeError, ValueError):
                return fallback
        return self._coerce_hex_color(value, fallback=fallback)

    def _entity_wiki_band_color(self, entity):
        colors = entity.get("wiki_field_colors") if isinstance(entity, dict) else None
        if not isinstance(colors, dict):
            return None
        value = colors.get("default")
        if not value:
            for candidate in colors.values():
                if candidate:
                    value = candidate
                    break
        return self._coerce_color_value(value, fallback=None)

    def _entity_link_palette(self, entity_or_id, fallback_body=(38, 58, 54)):
        entity = entity_or_id
        if isinstance(entity_or_id, str) and self.world_model is not None:
            entity = self.world_model.get_entity(entity_or_id)
        if not isinstance(entity, dict):
            return None

        body = self._coerce_color_value(
            entity.get("card_color") or entity.get("wiki_link_color") or entity.get("display_color"),
            fallback=fallback_body,
        )
        if body is None:
            return None
        header = self._coerce_color_value(entity.get("card_header_color"), fallback=None)
        band = self._entity_wiki_band_color(entity)

        fill = self._mix_color(body, (18, 22, 30), 0.62)
        border_source = header if header is not None else body
        border = self._mix_color(border_source, (234, 240, 250), 0.28)
        text = self._readable_text_color(fill, light=(238, 244, 252), dark=(20, 24, 32))
        band_color = band if band is not None else (header if header is not None else None)
        return {
            "fill": fill,
            "border": border,
            "text": text,
            "band": band_color,
            "body": body,
            "header": header,
            "wiki": band,
        }

    def _phylogeny_row_colors(self, row, muted=False):
        if row.get("summary"):
            return (30, 34, 44), (76, 86, 106), (178, 188, 204)

        palette = self._phylogeny_row_palette(row, muted=muted)
        if palette is not None:
            return palette["fill"], palette["border"], palette["text"]

        if row.get("highlight"):
            return (58, 66, 88), (190, 210, 246), (244, 246, 250)
        if row.get("neighbor"):
            return (46, 54, 42), (164, 188, 124), (226, 238, 202)
        if row.get("species"):
            return (38, 42, 50), (118, 132, 156), (210, 220, 236)
        return (32, 36, 46), (72, 82, 100), (184, 192, 208) if muted else (216, 224, 238)

    def _phylogeny_row_palette(self, row, muted=False):
        if row.get("summary"):
            return {"fill": (30, 34, 44), "border": (76, 86, 106), "text": (178, 188, 204), "band": None}

        palette = self._entity_link_palette(row.get("id"), fallback_body=None)
        if palette is None and isinstance(row.get("entity"), dict):
            palette = self._entity_link_palette(row.get("entity"), fallback_body=None)
        if palette is not None:
            base = palette["body"]
            fill = self._mix_color(base, (18, 22, 30), 0.60)
            border_source = palette["header"] if palette.get("header") is not None else base
            border = self._mix_color(border_source, (234, 240, 250), 0.26)
            if row.get("highlight"):
                fill = self._mix_color(base, (58, 66, 88), 0.35)
                border = self._mix_color(border_source, (244, 246, 250), 0.12)
            elif row.get("neighbor"):
                fill = self._mix_color(base, (46, 54, 42), 0.35)
                border = self._mix_color(border_source, (230, 242, 204), 0.24)
            text = self._readable_text_color(fill, light=(238, 244, 252), dark=(20, 24, 32))
            if muted:
                text = self._mix_color(text, fill, 0.18)
            palette.update({"fill": fill, "border": border, "text": text})
            return palette
        return None

    def _relation_target_label(self, target):
        normalized = str(target or "").strip().lower()
        if not normalized or normalized in {"entity", "entity_core", "core", "any"}:
            return "Entry"
        return normalized.replace("_", " ")

    def _normalize_toolbelt_token(self, value):
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _toolbelt_match_tokens(self):
        tokens = set()
        for value in (self.dataset_name, self.entity.get("_dataset"), self.entity.get("type")):
            token = self._normalize_toolbelt_token(value)
            if token:
                tokens.add(token)

        for key, value in self.entity.items():
            if key.endswith("_class") or key in {"system_role", "body_class", "location_role"}:
                token = self._normalize_toolbelt_token(value)
                if token:
                    tokens.add(token)
        return tokens

    def _toolbelt_items(self):
        match_tokens = self._toolbelt_match_tokens()
        tools = [
            {
                "id": "card_color",
                "kind": "color_picker",
                "label": "Card Color",
                "description": "Card background color.",
            }
        ]
        seen_ids = {"card_color"}

        for definition in self.TOOLBELT_TOOL_DEFINITIONS:
            definition_matches = {
                self._normalize_toolbelt_token(value)
                for value in definition.get("match", set())
            }
            if not match_tokens & definition_matches:
                continue

            for tool in definition.get("tools", []):
                tool_id = tool.get("id")
                if not tool_id or tool_id in seen_ids:
                    continue
                if not self._toolbelt_tool_is_available(tool):
                    continue
                tools.append(dict(tool))
                seen_ids.add(tool_id)

        return tools

    def _toolbelt_tool_is_available(self, tool):
        requirement = tool.get("requires")
        if not requirement:
            return True

        if requirement == "surface_location":
            location_class = str(self.entity.get("location_class") or "").strip().lower()
            return location_class not in {
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

        if requirement == "planet_without_map":
            if self.entity.get("location_class") != "planet":
                return False
            map_fields = (
                "map_canvas_width_px",
                "map_canvas_height_px",
            )
            return not any(bool(self.entity.get(field)) for field in map_fields)

        return True

    def _uses_toolbelt(self, card):
        return bool(card.get("is_edit_mode", False) and self._toolbelt_items())

    def _active_color_role(self, card=None):
        role = str((card or {}).get("active_color_role") or "body").strip().lower()
        if role not in {item[0] for item in self.CARD_COLOR_ROLES}:
            return "body"
        return role

    def _active_wiki_section_id(self, card=None):
        section_id = str((card or {}).get("active_wiki_section_id") or "").strip()
        return section_id or None

    def _wiki_field_colors(self):
        colors = self.entity.get("wiki_field_colors")
        return colors if isinstance(colors, dict) else {}

    def _card_color_hex(self, role="body", section_id=None):
        role = str(role or "body").strip().lower()
        if role == "header":
            value = str(self.entity.get("card_header_color") or "").strip()
            if value:
                return value
            return self._card_color_hex("body")
        if role == "wiki":
            section_id = str(section_id or "").strip()
            colors = self._wiki_field_colors()
            value = str(colors.get(section_id) or colors.get("default") or "").strip()
            if value:
                return value
            return "#222632"

        value = str(self.entity.get("card_color") or "").strip()
        legacy_value = str(self.entity.get("wiki_link_color") or "").strip()
        if value:
            return value
        if legacy_value:
            return legacy_value
        return self.CARD_COLOR_DEFAULT

    @staticmethod
    def _coerce_hex_color(value, fallback=(54, 95, 158)):
        text = str(value or "").strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (
                    int(text[1:3], 16),
                    int(text[3:5], 16),
                    int(text[5:7], 16),
                )
            except ValueError:
                pass
        return fallback

    @staticmethod
    def _rgb_to_hex(color):
        try:
            red, green, blue = [max(0, min(255, int(part))) for part in color[:3]]
        except (TypeError, ValueError):
            red, green, blue = (28, 30, 38)
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _card_hsv(self, role="body", section_id=None):
        red, green, blue = self._card_background_color(role=role, section_id=section_id)
        return colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)

    @staticmethod
    def _hsv_to_rgb(hue, saturation, brightness):
        red, green, blue = colorsys.hsv_to_rgb(
            max(0.0, min(1.0, hue)),
            max(0.0, min(1.0, saturation)),
            max(0.0, min(1.0, brightness)),
        )
        return (int(round(red * 255)), int(round(green * 255)), int(round(blue * 255)))

    @staticmethod
    def _mix_color(color, target, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        return tuple(
            max(0, min(255, int(round(color[index] * (1.0 - ratio) + target[index] * ratio))))
            for index in range(3)
        )

    def _card_background_color(self, role="body", section_id=None):
        return self._coerce_hex_color(self._card_color_hex(role=role, section_id=section_id), fallback=(28, 30, 38))

    @staticmethod
    def _readable_text_color(background, light=(246, 248, 252), dark=(20, 24, 32)):
        try:
            red, green, blue = [float(part) for part in background[:3]]
        except (TypeError, ValueError):
            return light
        luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
        return dark if luminance >= 0.58 else light

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
                items.append(
                    {
                        "kind": "note",
                        "field_key": field_key,
                        "entity_id": "",
                        "target": "ideas",
                        "label": "Add Note",
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
            {
                "kind": "note",
                "field_key": field_key,
                "entity_id": "",
                "target": "ideas",
                "label": "Add Note",
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
        return set(self.MEDIA_FIELDS)

    def _is_space_sim_context(self):
        return bool(
            self.entity.get("system_role")
            or self.entity.get("body_class")
            or self.entity.get("star_system")
            or self.entity.get("parent_body")
            or self.entity.get("derived_from_system_body")
            or self.entity.get("location_class") in {"star_system", "star", "planet", "moon"}
            or self.dataset_name == "systems"
        )

    def _simulation_section_for_key(self, key):
        if key in self.SPACE_SIM_FIELDS:
            return "Simulation / Orbital"
        if key == "mass_kg" and self._is_space_sim_context():
            return "Simulation / Orbital"
        if key in self.MAP_SIM_FIELDS:
            return "Simulation / Map Sim"
        if key in self.WORLD_GEN_SIM_FIELDS:
            return "Simulation / World Gen"
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

        return ""

    def _task_is_finished(self):
        return str(self.entity.get("entry_status") or "").strip().lower() in {
            "finished",
            "complete",
            "completed",
            "done",
        }

    def _task_checklist_items(self):
        raw_items = self.entity.get("checklist")
        if not isinstance(raw_items, list):
            return []

        items = []
        for item in raw_items:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or item.get("name") or "").strip()
                done = bool(item.get("done", item.get("checked", False)))
            else:
                text = str(item or "").strip()
                done = False
            if text:
                items.append({"text": text, "done": done})
        return items

    def _task_checklist_completion(self):
        items = self._task_checklist_items()
        if not items:
            return 0
        done_count = sum(1 for item in items if item.get("done"))
        return int(round((done_count / len(items)) * 100))

    def _measure_task_checklist_height(self, font, width, card=None):
        if not self._is_task_card():
            return 0

        line_h = self._table_line_height(font)
        items = self._task_checklist_items()
        input_active = bool(card and card.get("task_checklist_input_active"))
        height = line_h + 8
        height += 24
        height += 4
        height += max(1, len(items)) * (line_h + 6)
        height += 8
        height += 26 if input_active else 22
        return max(92, height)

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

    def _resolve_wiki_link_color(self, entity_ref):
        if self.world_model is None:
            return None

        entity = self.world_model.get_entity(entity_ref)
        if not isinstance(entity, dict):
            return None

        palette = self._entity_link_palette(entity, fallback_body=None)
        if palette is None:
            return None
        return palette["fill"]

    def _resolve_wiki_link_palette(self, entity_ref):
        if self.world_model is None:
            return None
        return self._entity_link_palette(self.world_model.get_entity(entity_ref), fallback_body=None)

    def _coerce_timeline_year(self, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in {"none", "null"}:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    def _entity_timeline_range(self, entity):
        if not isinstance(entity, dict):
            return None

        start_year = self._coerce_timeline_year(entity.get("start_year"))
        end_year = self._coerce_timeline_year(entity.get("end_year"))
        point_year = self._coerce_timeline_year(entity.get("year"))
        if point_year is None:
            point_year = self._coerce_timeline_year(entity.get("year_number"))
        if point_year is None:
            point_year = self._coerce_timeline_year(entity.get("effective_year"))

        if start_year is not None and end_year is not None:
            return (min(start_year, end_year), max(start_year, end_year))
        if start_year is not None:
            return (start_year, start_year)
        if point_year is not None:
            return (point_year, point_year)
        return None

    def _card_timeline_range(self, card):
        years = [
            self._coerce_timeline_year(year)
            for year in card.get("years", [])
        ]
        years = [year for year in years if year is not None]
        if not years:
            return None
        return (min(years), max(years))

    def _timeline_duration_label(self, years):
        timeline_range = self._card_timeline_range({"years": years})
        if timeline_range is None:
            return None
        duration = abs(timeline_range[1] - timeline_range[0])
        unit = "year" if duration == 1 else "years"
        return f"{duration} {unit}"

    def _collect_relation_refs_from_value(self, value):
        refs = []
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                refs.append(stripped)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            refs.append(str(value))
        elif isinstance(value, dict):
            entity_id = value.get("id")
            if entity_id:
                refs.append(str(entity_id).strip())
            for child in value.get("offspring", []) or []:
                refs.extend(self._collect_relation_refs_from_value(child))
        elif isinstance(value, list):
            for item in value:
                refs.extend(self._collect_relation_refs_from_value(item))
        return [ref for ref in refs if ref]

    def _related_timeline_entries(self, card):
        if self.world_model is None:
            return []

        card_range = self._card_timeline_range(card)
        if card_range is None:
            return []

        start, end = card_range
        own_id = str(self.entity.get("id") or card.get("entity_id") or "")
        refs = []
        for field_key in self.STANDARD_RELATION_FIELDS:
            refs.extend(self._collect_relation_refs_from_value(self.entity.get(field_key)))

        entries = []
        seen = set()
        for ref in refs:
            if not ref or ref == own_id or ref in seen:
                continue
            seen.add(ref)
            entity = self.world_model.get_entity(ref)
            entity_range = self._entity_timeline_range(entity)
            if entity_range is None:
                continue
            entity_start, entity_end = entity_range
            if entity_start < start or entity_end > end:
                continue
            entries.append(
                {
                    "entity_id": ref,
                    "label": self._resolve_wiki_link_label(ref),
                    "start_year": entity_start,
                    "end_year": entity_end,
                    "is_point": entity_start == entity_end,
                }
            )

        entries.sort(key=lambda item: (item["start_year"], item["end_year"], item["label"]))
        return entries

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
        if self._simulation_section_for_key(field_key):
            return False

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
        if self._is_space_sim_context():
            dims = [(key, value) for key, value in dims if key != "mass_kg"]
        overview_dims = [] if self._is_component_card() else dims

        relation_values = []
        state_values = []
        metadata_values = []
        operational_values = []
        temporal_values = []
        media_values = []
        space_sim_values = []
        map_sim_values = []
        world_gen_sim_values = []

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
            "card_color", "card_header_color", "wiki_field_colors", "wiki_link_color",
        }
        handled_keys.update(key for key, _ in classification)
        handled_keys.update(key for key, _ in overview_dims)

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
            }:
                continue

            spec = self._normalize_field_spec(schema_field_specs.get(key, {}))
            section_name = str(spec.get("section", "")).lower()

            if key in {"description", "notes"}:
                continue

            if key in media_keys:
                media_values.append((key, value))
                continue

            simulation_section = self._simulation_section_for_key(key)
            if simulation_section == "Simulation / Orbital":
                space_sim_values.append((key, value))
                continue
            if simulation_section == "Simulation / Map Sim":
                map_sim_values.append((key, value))
                continue
            if simulation_section == "Simulation / World Gen":
                world_gen_sim_values.append((key, value))
                continue

            if self._is_temporal_field(key, spec):
                temporal_values.append((key, value))
                continue

            if section_name == "relations" or key in self.STANDARD_RELATION_FIELDS:
                relation_values.append((key, value))
                continue

            if self._is_component_card() and key in component_operational_keys:
                operational_values.append((key, value))
                continue

            if key in {"tags", "entry_status"}:
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

        sections = {
            "Identity": identity,
            "Classification": classification,
            "Dimensions / Scale": overview_dims,
            "Temporal": temporal_values,
            "Relations": relation_values,
            "State / Layout": state_values,
            "Metadata": metadata_values,
            "Media": media_values,
            "Simulation / Orbital": space_sim_values,
            "Simulation / Map Sim": map_sim_values,
            "Simulation / World Gen": world_gen_sim_values,
            "Operational": dims + operational_values if self._is_component_card() else operational_values,
        }
        sections["Simulation / Space Sim"] = space_sim_values
        return sections

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
            fallback_text = self._get_general_wiki_text()
            if fallback_text and fallback_text != CardWikiRenderer.EMPTY_HINT:
                return fallback_text
        return self._serialize_edit_value(value)

    def _clamp_edit_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = int(card.get("edit_cursor", len(buffer_text)))
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        card["edit_cursor"] = cursor
        return cursor

    def _set_edit_cursor(self, card, cursor):
        buffer_text = card.get("edit_buffer", "")
        card["edit_cursor"] = TextEditing.clamp_cursor(buffer_text, cursor)

    def _insert_edit_text(self, card, text):
        if not text:
            return False

        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.insert_text(
            buffer_text,
            cursor,
            text,
        )
        return True

    def _delete_before_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_before_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _delete_after_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_after_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _word_start_before_cursor(self, buffer_text, cursor):
        return TextEditing.word_start_before_cursor(buffer_text, cursor)

    def _word_end_after_cursor(self, buffer_text, cursor):
        return TextEditing.word_end_after_cursor(buffer_text, cursor)

    def _delete_word_before_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_word_before_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _delete_word_after_cursor(self, card):
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_word_after_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _line_start_before_cursor(self, buffer_text, cursor):
        return TextEditing.line_start_before_cursor(buffer_text, cursor)

    def _line_end_after_cursor(self, buffer_text, cursor):
        return TextEditing.line_end_after_cursor(buffer_text, cursor)

    def _wiki_edit_lines(self, card):
        general_rect = card.get("general_content_rect")
        font = card.get("layout_font")
        if general_rect is None or font is None:
            return []

        inner_rect = general_rect.inflate(-10, -10)
        return CardWikiRenderer.wrap_edit_lines(
            card.get("edit_buffer", ""),
            font,
            inner_rect.width,
        )

    def _wiki_cursor_row_and_column(self, card, lines=None):
        lines = lines or self._wiki_edit_lines(card)
        if not lines:
            return None, 0

        cursor = self._clamp_edit_cursor(card)
        font = card.get("layout_font")
        for index, line_info in enumerate(lines):
            line_start = line_info["start"]
            line_end = line_info["end"]
            if line_start <= cursor <= line_end:
                offset = max(0, min(len(line_info["text"]), cursor - line_start))
                column_x = font.size(line_info["text"][:offset])[0] if font is not None else offset
                return index, column_x

        last_index = len(lines) - 1
        line_info = lines[last_index]
        return last_index, font.size(line_info["text"])[0] if font is not None else len(line_info["text"])

    def _wiki_cursor_for_row_column(self, card, line_info, column_x):
        font = card.get("layout_font")
        line_text = line_info.get("text", "")
        if font is None:
            return line_info["start"] + max(0, min(len(line_text), int(column_x)))

        best_offset = 0
        best_distance = None
        for offset in range(len(line_text) + 1):
            width = font.size(line_text[:offset])[0]
            distance = abs(width - column_x)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_offset = offset
        return line_info["start"] + best_offset

    def _move_wiki_cursor_row(self, card, direction):
        lines = self._wiki_edit_lines(card)
        if not lines:
            return False

        current_row, current_column = self._wiki_cursor_row_and_column(card, lines=lines)
        if current_row is None:
            return False

        preferred_column = card.get("edit_preferred_column_x")
        if preferred_column is None:
            preferred_column = current_column

        target_row = max(0, min(len(lines) - 1, current_row + direction))
        if target_row == current_row:
            return True

        self._set_edit_cursor(card, self._wiki_cursor_for_row_column(card, lines[target_row], preferred_column))
        card["edit_preferred_column_x"] = preferred_column
        return True

    def _clear_edit_preferred_column(self, card):
        card.pop("edit_preferred_column_x", None)

    def _parse_edit_lines(self, buffer_text):
        return TextEditing.parse_lines(buffer_text)

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
            card["delete_confirm_active"] = False
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
        self._clear_edit_preferred_column(card)
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
        if field_key in {"star_class", "spectral_class"} and str(new_value or "").strip():
            if not is_valid_stellar_class(new_value):
                card["edit_validation_message"] = f"Invalid stellar class. {STELLAR_CLASS_HELP}"
                card["last_edit_action"] = "invalid"
                return True

        card.pop("edit_validation_message", None)
        self.entity[field_key] = new_value
        if field_key == "name" and not self._is_species_card():
            self.entity["pretty_name"] = new_value
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
        self._clear_edit_preferred_column(card)
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = field_key
        return True

    def cancel_edit_field(self, card):
        if not card.get("active_edit_field"):
            return False

        card["last_edit_action"] = "cancel"
        card.pop("edit_validation_message", None)
        card["active_edit_field"] = None
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        card["edit_cursor"] = 0
        self._clear_edit_preferred_column(card)
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
                self._clear_edit_preferred_column(card)
                self._insert_edit_text(card, "\n")
                card["last_edit_action"] = "draft"
                return True

            if event.key == pygame.K_UP:
                self._move_wiki_cursor_row(card, -1)
                card["last_edit_action"] = "draft"
                return True

            if event.key == pygame.K_DOWN:
                self._move_wiki_cursor_row(card, 1)
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
            self._clear_edit_preferred_column(card)
            cursor = self._clamp_edit_cursor(card)
            if event.mod & pygame.KMOD_CTRL:
                self._set_edit_cursor(card, self._word_start_before_cursor(card.get("edit_buffer", ""), cursor))
            else:
                self._set_edit_cursor(card, cursor - 1)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_RIGHT:
            self._clear_edit_preferred_column(card)
            cursor = self._clamp_edit_cursor(card)
            if event.mod & pygame.KMOD_CTRL:
                self._set_edit_cursor(card, self._word_end_after_cursor(card.get("edit_buffer", ""), cursor))
            else:
                self._set_edit_cursor(card, cursor + 1)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_HOME:
            self._clear_edit_preferred_column(card)
            if active_field == "wiki_entry" and not (event.mod & pygame.KMOD_CTRL):
                self._set_edit_cursor(card, self._line_start_before_cursor(card.get("edit_buffer", ""), self._clamp_edit_cursor(card)))
            else:
                self._set_edit_cursor(card, 0)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_END:
            self._clear_edit_preferred_column(card)
            if active_field == "wiki_entry" and not (event.mod & pygame.KMOD_CTRL):
                self._set_edit_cursor(card, self._line_end_after_cursor(card.get("edit_buffer", ""), self._clamp_edit_cursor(card)))
            else:
                self._set_edit_cursor(card, len(card.get("edit_buffer", "")))
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_BACKSPACE:
            self._clear_edit_preferred_column(card)
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_before_cursor(card)
            else:
                self._delete_before_cursor(card)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_DELETE:
            self._clear_edit_preferred_column(card)
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_after_cursor(card)
            else:
                self._delete_after_cursor(card)
            card["last_edit_action"] = "draft"
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self._clear_edit_preferred_column(card)
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
        self._clear_edit_preferred_column(card)
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
        value = self.entity.get("media_path")
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _resolve_card_icon_reference(self):
        for key in ("media_path", "card_image", "card_image_front", "image_path", "map_image_path"):
            value = self.entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for illustration in self._media_illustrations():
            value = self._illustration_media_path(illustration)
            if value:
                return value
        return None

    def _load_card_image_surface(self, image_path):
        if not image_path:
            return None

        normalized_path = os.path.normpath(image_path)

        candidate_paths = [normalized_path]
        if not os.path.isabs(normalized_path):
            candidate_paths.append(os.path.normpath(os.path.join(os.getcwd(), normalized_path)))
            candidate_paths.append(os.path.normpath(os.path.join(self.PROJECT_ROOT, normalized_path)))

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
        rendered_key = f"{self._field_display_label(key)}:"
        key_lines = self._wrap_text_lines(rendered_key, font, max(20, key_column_w - 12))
        rendered_value = self._format_value(value)
        wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)
        content_h = max(1, len(key_lines), len(wrapped_lines)) * self._table_line_height(font)
        row_h = content_h + self.TABLE_ROW_PAD_Y * 2
        return key_lines, wrapped_lines, row_h

    def _field_display_label(self, field_key):
        labels = {
            "start_year": "start year",
            "end_year": "end year",
            "start_event": "  related event",
            "end_event": "  related event",
        }
        return labels.get(field_key, str(field_key or ""))

    def _entity_display_label(self, entity):
        if not isinstance(entity, dict):
            return ""
        for key in ("pretty_name", "name", "id"):
            value = entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _is_illustration_entity(self, entity):
        if not isinstance(entity, dict):
            return False
        return (
            str(entity.get("type") or "").strip().lower() == "idea"
            and str(entity.get("idea_class") or "").strip().lower() == "illustration"
        )

    def _media_illustrations(self):
        parent_id = str(self.entity.get("id") or "").strip()
        if not parent_id or self.world_model is None:
            return []

        get_entities = getattr(self.world_model, "get_entities_by_dataset", None)
        if not callable(get_entities):
            return []

        ideas = get_entities("ideas")
        illustrations = []
        for idea in ideas:
            if not self._is_illustration_entity(idea):
                continue
            if parent_id not in self._relation_reference_values(idea.get("parents")):
                continue
            illustrations.append(idea)

        def sort_key(idea):
            date_value = str(idea.get("date") or "").strip()
            label = self._entity_display_label(idea).lower()
            return (date_value, label)

        return sorted(illustrations, key=sort_key)

    def _illustration_media_path(self, illustration):
        if not isinstance(illustration, dict):
            return ""
        value = illustration.get("media_path")
        return value.strip() if isinstance(value, str) else ""

    def _phylogeny_line_height(self, font):
        return max(16, int(font.get_linesize())) if font is not None else 18

    def _phylogeny_children_count(self, entity_id):
        world_model = self.world_model
        clades = get_clade_entities(world_model)
        entity = clades.get(entity_id)
        if not isinstance(entity, dict):
            return 0
        children = entity.get("offspring") or []
        if isinstance(children, str):
            return 1 if children.strip() else 0
        if isinstance(children, list):
            return len(children)
        return 0

    def _layout_phylogeny_tree_rows(self, root, font, x, y, max_width, depth=0, rows=None):
        rows = rows if rows is not None else []
        if not isinstance(root, dict):
            return rows, y

        line_h = self._phylogeny_line_height(font)
        row_h = line_h + 8
        indent = depth * 18
        label = str(root.get("label") or root.get("id") or "Unknown")
        row_rect = pygame.Rect(x + indent, y, max(40, max_width - indent), row_h)
        rows.append(
            {
                "id": root.get("id"),
                "label": label,
                "rect": row_rect,
                "depth": depth,
                "highlight": bool(root.get("highlight")),
                "neighbor": bool(root.get("neighbor")),
                "species": bool(root.get("species")),
            }
        )
        y = row_rect.bottom + 3
        for child in root.get("children", []) or []:
            rows, y = self._layout_phylogeny_tree_rows(child, font, x, y, max_width, depth + 1, rows)
        return rows, y

    def _summarized_phylogeny_chain_ids(self, chain_ids, top_count=3, tail_count=5):
        chain_ids = [str(chain_id) for chain_id in chain_ids if chain_id]
        if len(chain_ids) <= top_count + tail_count + 1:
            return [(chain_id, False) for chain_id in chain_ids]

        top_ids = chain_ids[:top_count]
        tail_ids = chain_ids[-tail_count:]
        return (
            [(chain_id, False) for chain_id in top_ids]
            + [(None, True)]
            + [(chain_id, False) for chain_id in tail_ids]
        )

    def _layout_phylogeny_chain_rows(self, graph, entity_id, font, x, y, max_width):
        line_h = self._phylogeny_line_height(font)
        row_h = max(18, line_h + 2)
        row_gap = 1
        rows = []
        chain_ids = graph.ancestor_chain(entity_id)
        if not chain_ids and entity_id in graph.phylogeny_entities:
            chain_ids = [entity_id]

        for display_depth, (chain_id, is_summary) in enumerate(self._summarized_phylogeny_chain_ids(chain_ids)):
            indent = display_depth * 14
            row_rect = pygame.Rect(x + indent, y, max(40, max_width - indent), row_h)
            if is_summary:
                rows.append(
                    {
                        "id": None,
                        "label": "(...)",
                        "rect": row_rect,
                        "depth": display_depth,
                        "summary": True,
                    }
                )
            else:
                entity = graph.phylogeny_entities.get(chain_id)
                rows.append(
                    {
                        "id": chain_id,
                        "label": clade_label(entity, chain_id),
                        "rect": row_rect,
                        "depth": display_depth,
                        "highlight": chain_id == entity_id,
                        "species": bool(is_species_entity(entity)),
                    }
                )
            y = row_rect.bottom + row_gap
        return rows, y

    def _clip_phylogeny_rect_to_panel(self, rect, panel_rect):
        if rect is None or panel_rect is None or not rect.colliderect(panel_rect):
            return None
        clipped = rect.clip(panel_rect)
        if clipped.width <= 0 or clipped.height <= 0:
            return None
        return clipped

    def _shift_clip_phylogeny_row(self, row, scroll_y, panel_rect):
        row_rect = row.get("rect")
        if row_rect is None:
            return None
        shifted_rect = row_rect.move(0, -scroll_y)
        clipped_rect = self._clip_phylogeny_rect_to_panel(shifted_rect, panel_rect)
        if clipped_rect is None:
            return None
        visible_row = dict(row)
        visible_row["rect"] = clipped_rect
        return visible_row

    def _shift_clip_phylogeny_match_rows(self, rows, scroll_y, panel_rect):
        visible_rows = []
        for row in rows:
            shifted = self._shift_clip_phylogeny_row(row, scroll_y, panel_rect)
            if shifted is not None:
                visible_rows.append(shifted)
        return visible_rows

    def _layout_phylogeny_content(self, card, content_left, current_y, text_width):
        font = card.get("layout_font")
        line_h = self._phylogeny_line_height(font)
        entity_id = str(self.entity.get("id") or "")
        is_clade = self._is_cladistics_card()
        section_h = self.SECTION_HEADER_H
        graph = phylogeny_graph_context(self.world_model)

        parent_section_rect = pygame.Rect(content_left, current_y, text_width, section_h)
        current_y = parent_section_rect.bottom + self.SECTION_GAP

        input_rect = None
        match_rows = []
        child_input_rect = None
        child_match_rows = []
        parent_tree_rows = []
        member_rows = []
        local_node_hitboxes = []
        parent_panel_rect = None
        parent_panel_content_rect = None
        parent_target_id = entity_id
        child_target_id = entity_id if is_clade else ""
        child_sibling_id = ""

        if not self.collapsed_sections.get("Phylogeny Parents", False):
            parent_panel_rect = pygame.Rect(
                content_left + 4,
                current_y,
                max(80, text_width - 8),
                self.PHYLOGENY_PARENT_PANEL_H,
            )
            parent_panel_content_rect = parent_panel_rect.inflate(-14, -14)
            panel_content_y = parent_panel_content_rect.y

            input_rect = pygame.Rect(
                parent_panel_content_rect.x,
                panel_content_y,
                parent_panel_content_rect.width,
                26,
            )
            panel_content_y = input_rect.bottom + 5

            query = str(card.get("phylogeny_parent_query") or "").strip()
            matches = card.get("phylogeny_parent_matches")
            if matches is None:
                matches = find_clade_matches(self.world_model, query)
                card["phylogeny_parent_matches"] = matches

            if query:
                if matches:
                    for index, match in enumerate(matches[:4]):
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        match_rows.append({"index": index, "entity": match, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4
                else:
                    row_rect = pygame.Rect(
                        parent_panel_content_rect.x,
                        panel_content_y,
                        parent_panel_content_rect.width,
                        28,
                    )
                    match_rows.append({"index": "create", "entity": None, "rect": row_rect})
                    panel_content_y = row_rect.bottom + 4

            tree = graph.context_tree(entity_id)
            if tree is not None:
                parent_tree_rows, panel_content_y = self._layout_phylogeny_chain_rows(
                    graph,
                    entity_id,
                    font,
                    parent_panel_content_rect.x,
                    panel_content_y + 4,
                    parent_panel_content_rect.width,
                )
            else:
                panel_content_y += line_h + 8

            if parent_tree_rows:
                parent_target_id = str(parent_tree_rows[0].get("id") or entity_id)
                child_target_id = ""
                bottom_entry_id = ""
                for row in reversed(parent_tree_rows):
                    if row.get("summary"):
                        continue
                    row_id = str(row.get("id") or "").strip()
                    if row_id:
                        bottom_entry_id = row_id
                        break
                if bottom_entry_id:
                    child_sibling_id = bottom_entry_id
                    for candidate_parent_id in graph.parents_by_child.get(bottom_entry_id, []):
                        if candidate_parent_id in graph.clades:
                            child_target_id = candidate_parent_id
                            break

            if is_clade and child_target_id:
                child_input_rect = pygame.Rect(
                    parent_panel_content_rect.x,
                    panel_content_y + 2,
                    parent_panel_content_rect.width,
                    26,
                )
                panel_content_y = child_input_rect.bottom + 5

                child_query = str(card.get("phylogeny_child_query") or "").strip()
                child_matches = card.get("phylogeny_child_matches")
                if child_matches is None:
                    child_matches = find_clade_matches(self.world_model, child_query)
                    card["phylogeny_child_matches"] = child_matches

                if child_query:
                    excluded_child_match_ids = {
                        entity_id,
                        str(child_target_id or "").strip(),
                        str(child_sibling_id or "").strip(),
                    }
                    visible_child_matches = [
                        (index, match)
                        for index, match in enumerate(child_matches)
                        if str(match.get("id") or "").strip() not in excluded_child_match_ids
                    ]
                    for index, match in visible_child_matches[:5]:
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        child_match_rows.append({"index": index, "entity": match, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4
                    if not child_match_rows:
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        child_match_rows.append({"index": "create", "entity": None, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4

            parent_content_h = max(0, panel_content_y - parent_panel_content_rect.y)
            parent_visible_h = max(1, parent_panel_content_rect.height)
            parent_scroll_max = max(0, int(parent_content_h - parent_visible_h))
            parent_scroll_y = max(0, min(parent_scroll_max, int(card.get("phylogeny_parent_scroll_y", 0) or 0)))
            card["phylogeny_parent_scroll_y"] = parent_scroll_y
            card["phylogeny_parent_scroll_max_y"] = parent_scroll_max

            input_rect = self._clip_phylogeny_rect_to_panel(input_rect.move(0, -parent_scroll_y), parent_panel_content_rect)
            child_input_rect = (
                self._clip_phylogeny_rect_to_panel(child_input_rect.move(0, -parent_scroll_y), parent_panel_content_rect)
                if child_input_rect is not None
                else None
            )
            match_rows = self._shift_clip_phylogeny_match_rows(match_rows, parent_scroll_y, parent_panel_content_rect)
            child_match_rows = self._shift_clip_phylogeny_match_rows(child_match_rows, parent_scroll_y, parent_panel_content_rect)
            parent_tree_rows = [
                visible_row
                for row in parent_tree_rows
                for visible_row in [self._shift_clip_phylogeny_row(row, parent_scroll_y, parent_panel_content_rect)]
                if visible_row is not None
            ]
            current_y = parent_panel_rect.bottom + 8
        else:
            card["phylogeny_parent_scroll_y"] = 0
            card["phylogeny_parent_scroll_max_y"] = 0

        current_y += 8
        members_section_rect = pygame.Rect(content_left, current_y, text_width, section_h)
        current_y = members_section_rect.bottom + self.SECTION_GAP

        if not self.collapsed_sections.get("Members", False):
            if is_clade:
                limit = max(1, int(card.get("phylogeny_clade_member_limit", 3) or 3))
                member_ids = graph.distant_species_members(entity_id, limit=limit)
            else:
                limit = max(1, int(card.get("phylogeny_species_relative_limit", 4) or 4))
                member_ids = graph.closest_species_relatives(entity_id, limit=limit)

            for member_id in member_ids:
                member = graph.phylogeny_entities.get(member_id)
                distance = graph.graph_distance(entity_id, member_id, max_depth=64)
                row_rect = pygame.Rect(content_left + 10, current_y + 3, text_width - 20, line_h + 10)
                label = clade_label(member, member_id)
                member_rows.append(
                    {
                        "id": member_id,
                        "label": label,
                        "distance_label": f"{distance} steps" if distance is not None else "?",
                        "rect": row_rect,
                        "depth": 0,
                        "species": True,
                    }
                )
                local_node_hitboxes.append((member_id, row_rect))
                current_y = row_rect.bottom + 3
            if not member_ids:
                current_y += line_h + 10

        card["phylogeny_parent_section_rect"] = parent_section_rect
        card["phylogeny_parent_panel_rect"] = parent_panel_rect
        card["phylogeny_parent_panel_content_rect"] = parent_panel_content_rect
        card["phylogeny_child_section_rect"] = None
        card["phylogeny_diagram_section_rect"] = members_section_rect
        card["phylogeny_parent_input_rect"] = input_rect
        card["phylogeny_child_input_rect"] = child_input_rect
        card["phylogeny_parent_match_rows"] = match_rows
        card["phylogeny_child_match_rows"] = child_match_rows
        card["phylogeny_parent_tree_rows"] = parent_tree_rows
        card["phylogeny_local_tree_rows"] = member_rows
        card["phylogeny_node_hitboxes"] = local_node_hitboxes
        card["phylogeny_members_label"] = "Members" if is_clade else "Relatives"
        card["phylogeny_parent_target_id"] = parent_target_id
        card["phylogeny_child_target_id"] = child_target_id
        card["phylogeny_child_sibling_id"] = child_sibling_id
        return current_y

    def layout_card(self, card, rect):
        section_hitboxes = []
        tab_hitboxes = []
        subtab_hitboxes = []
        media_import_hitboxes = []
        media_pixel_art_hitboxes = []
        media_add_illustration_rect = None
        media_illustration_rows = []
        media_illustration_link_hitboxes = []
        media_content_end_y = None
        editable_field_hitboxes = []
        content_editable_field_hitboxes = []
        relation_hitboxes = []
        wiki_link_hitboxes = []
        wiki_section_hitboxes = []
        toolbelt_hitboxes = []
        toolbelt_rows = []
        toolbelt_rect = None
        field_rows = []
        general_content_rect = None
        task_checklist_rect = None
        task_finish_checkbox_rect = None
        task_checklist_hitboxes = []
        task_checklist_input_rect = None
        schema_field_specs = self._get_schema_field_specs()

        tab_y = rect.y + self.HEADER_H + 6
        tab_x = rect.x + 12
        tab_gap = 6
        tab_widths = {
            "general": 70,
            "overview": 78,
            "temporal": 82,
            "relations": 76,
            "phylogeny": 86,
            "state": 54,
            "simulation": 92,
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

        tabs_bottom_y = tab_y + self.TAB_H
        subtab_order = self._active_subtab_order()
        if subtab_order:
            subtab_y = tabs_bottom_y + 5
            subtab_x = rect.x + 12
            subtab_gap = 5
            subtab_widths = {
                "orbital": 86,
                "map": 72,
                "world_gen": 82,
            }
            available_subtab_w = max(120, rect.width - 24)
            total_subtab_w = sum(subtab_widths[name] for name in subtab_order) + subtab_gap * max(0, len(subtab_order) - 1)
            if total_subtab_w > available_subtab_w:
                subtab_gap = 4
                available_for_subtabs = available_subtab_w - subtab_gap * max(0, len(subtab_order) - 1)
                base_total = sum(subtab_widths[name] for name in subtab_order)
                scale = max(0.58, available_for_subtabs / max(1, base_total))
                for subtab_name in subtab_order:
                    subtab_widths[subtab_name] = max(48, int(subtab_widths[subtab_name] * scale))

            for subtab_name in subtab_order:
                subtab_rect = pygame.Rect(subtab_x, subtab_y, subtab_widths[subtab_name], self.SUBTAB_H)
                subtab_hitboxes.append(("simulation", subtab_name, subtab_rect))
                subtab_x = subtab_rect.right + subtab_gap
            tabs_bottom_y = subtab_y + self.SUBTAB_H

        close_rect = pygame.Rect(rect.right - 24, rect.y + 12, 18, 18)
        edit_toggle_rect = pygame.Rect(rect.right - 48, rect.y + 12, 20, 20)
        idea_button_rect = pygame.Rect(rect.right - 72, rect.y + 12, 20, 20)
        relation_tree_rect = None
        time_anchor_rect = None
        delete_rect = None
        header_reserved_w = 120
        if card.get("is_edit_mode", False):
            time_anchor_rect = pygame.Rect(rect.right - 96, rect.y + 12, 20, 20)
            delete_rect = pygame.Rect(rect.right - 120, rect.y + 12, 20, 20)
            header_reserved_w = 168
        else:
            relation_tree_rect = pygame.Rect(rect.right - 96, rect.y + 12, 20, 20)
            header_reserved_w = 144

        header_icon_ref = self._resolve_card_icon_reference()
        header_icon_rect = pygame.Rect(rect.x + 10, rect.y + 8, 34, 34) if header_icon_ref else None
        title_x = rect.x + (52 if header_icon_ref else 10)
        title_edit_rect = pygame.Rect(title_x, rect.y + 7, max(40, rect.right - header_reserved_w - title_x), 20)
        type_label_rect = pygame.Rect(title_x, rect.y + 28, max(40, rect.right - header_reserved_w - title_x), 18)
        if card.get("is_edit_mode", False):
            editable_field_hitboxes.append((self._title_edit_field(), title_edit_rect))

        image_rect = pygame.Rect(
            rect.x + 12,
            tabs_bottom_y + 6,
            rect.width - 24,
            self._image_block_height(),
        )

        if self._is_media_mode():
            media_add_illustration_rect = pygame.Rect(image_rect.right - 148, image_rect.y + 8, 136, 24)
            row_y = image_rect.y + 44
            row_h = 58
            row_gap = 8
            button_w = 92
            button_h = 22
            for illustration in self._media_illustrations():
                row_rect = pygame.Rect(image_rect.x + 8, row_y, image_rect.width - 16, row_h)
                pixel_rect = pygame.Rect(row_rect.right - button_w - 8, row_rect.y + 18, button_w, button_h)
                import_rect = pygame.Rect(pixel_rect.x - button_w - 6, row_rect.y + 18, button_w, button_h)
                title_rect = pygame.Rect(row_rect.x + 60, row_rect.y + 6, max(40, row_rect.width - 264), self.TEXT_LINE_H + 4)
                illustration_id = str(illustration.get("id") or "").strip()
                if illustration_id and not self._illustration_media_path(illustration):
                    media_import_hitboxes.append((illustration_id, import_rect))
                if illustration_id:
                    media_illustration_link_hitboxes.append((illustration_id, title_rect))
                    media_pixel_art_hitboxes.append((illustration_id, pixel_rect))
                media_illustration_rows.append(
                    {
                        "id": illustration_id,
                        "entity": illustration,
                        "row_rect": row_rect,
                        "import_rect": import_rect,
                        "pixel_rect": pixel_rect,
                        "title_rect": title_rect,
                    }
                )
                row_y = row_rect.bottom + row_gap
            media_content_end_y = row_y

        current_y = image_rect.bottom + 12
        content_left = rect.x + 12
        content_right = rect.right - 12
        text_width = content_right - content_left
        top_content_y = tabs_bottom_y + 10
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
        center_y = launch_rect.y - self.TIMELINE_TO_LAUNCH_GAP
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
            if self._is_task_card():
                checklist_h = min(
                    general_height - 44,
                    self._measure_task_checklist_height(card["layout_font"], text_width, card),
                )
                checklist_h = max(92, checklist_h)
                wiki_h = max(44, general_height - checklist_h - 8)
                general_content_rect = pygame.Rect(content_left, top_content_y, text_width, wiki_h)
                task_checklist_rect = pygame.Rect(content_left, general_content_rect.bottom + 8, text_width, checklist_h)
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
            if task_checklist_rect is not None:
                content_end_y = max(content_end_y, task_checklist_rect.bottom)
                line_h = self._table_line_height(card["layout_font"])
                checkbox_size = 14
                task_finish_checkbox_rect = pygame.Rect(
                    task_checklist_rect.x + 4,
                    task_checklist_rect.y + 4,
                    checkbox_size,
                    checkbox_size,
                )
                row_y = task_checklist_rect.y + line_h + 34
                for item_index, _ in enumerate(self._task_checklist_items()):
                    checkbox_rect = pygame.Rect(
                        task_checklist_rect.x + 18,
                        row_y + 1,
                        checkbox_size,
                        checkbox_size,
                    )
                    task_checklist_hitboxes.append((item_index, checkbox_rect))
                    row_y += line_h + 6
                task_checklist_input_rect = pygame.Rect(
                    task_checklist_rect.x + 18,
                    max(row_y + 4, task_checklist_rect.bottom - 24),
                    task_checklist_rect.width - 36,
                    22,
                )
        elif self._is_phylogeny_mode():
            image_rect = None
            content_end_y = self._layout_phylogeny_content(card, content_left, current_y, text_width)
            section_hitboxes.extend(
                [
                    ("Phylogeny Parents", card["phylogeny_parent_section_rect"]),
                ]
            )
            if card.get("phylogeny_child_section_rect") is not None:
                section_hitboxes.append(("Phylogeny Children", card["phylogeny_child_section_rect"]))
            section_hitboxes.append(("Members", card["phylogeny_diagram_section_rect"]))
        else:
            for key, value in (
                ("phylogeny_parent_section_rect", None),
                ("phylogeny_parent_panel_rect", None),
                ("phylogeny_parent_panel_content_rect", None),
                ("phylogeny_child_section_rect", None),
                ("phylogeny_diagram_section_rect", None),
                ("phylogeny_parent_input_rect", None),
                ("phylogeny_child_input_rect", None),
                ("phylogeny_parent_match_rows", []),
                ("phylogeny_child_match_rows", []),
                ("phylogeny_parent_tree_rows", []),
                ("phylogeny_local_tree_rows", []),
                ("phylogeny_node_hitboxes", []),
            ):
                card[key] = value
            content_end_y = current_y
            if media_content_end_y is not None:
                content_end_y = max(content_end_y, media_content_end_y + 8)
            if media_content_end_y is not None:
                content_end_y = max(content_end_y, media_content_end_y + 8)

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

        if (
            self._is_general_mode()
            and general_content_rect is not None
            and not (card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry")
        ):
            wiki_link_hitboxes = CardWikiRenderer.link_hitboxes(
                self._get_general_wiki_text(card),
                card["layout_font"],
                general_content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
                scroll_y=scroll_y,
            )
            wiki_section_hitboxes = CardWikiRenderer.section_hitboxes(
                self._get_general_wiki_text(card),
                card["layout_font"],
                general_content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
                scroll_y=scroll_y,
            )

        section_draw_rects = []
        if not self._is_general_mode() and scroll_y:
            if image_rect is not None:
                image_rect = image_rect.move(0, -scroll_y)

            media_import_hitboxes = [
                (illustration_id, button_rect.move(0, -scroll_y).clip(content_viewport_rect))
                for illustration_id, button_rect in media_import_hitboxes
                if button_rect.move(0, -scroll_y).colliderect(content_viewport_rect)
            ]
            media_pixel_art_hitboxes = [
                (illustration_id, button_rect.move(0, -scroll_y).clip(content_viewport_rect))
                for illustration_id, button_rect in media_pixel_art_hitboxes
                if button_rect.move(0, -scroll_y).colliderect(content_viewport_rect)
            ]
            if media_add_illustration_rect is not None:
                shifted_add_rect = media_add_illustration_rect.move(0, -scroll_y)
                media_add_illustration_rect = (
                    shifted_add_rect.clip(content_viewport_rect)
                    if shifted_add_rect.colliderect(content_viewport_rect)
                    else None
                )
            for row in media_illustration_rows:
                for rect_key in ("row_rect", "import_rect", "title_rect"):
                    row[rect_key] = row[rect_key].move(0, -scroll_y)
            media_illustration_link_hitboxes = [
                (illustration_id, title_rect.move(0, -scroll_y).clip(content_viewport_rect))
                for illustration_id, title_rect in media_illustration_link_hitboxes
                if title_rect.move(0, -scroll_y).colliderect(content_viewport_rect)
            ]
            if self._is_phylogeny_mode():
                for rect_key in (
                    "phylogeny_parent_section_rect",
                    "phylogeny_parent_panel_rect",
                    "phylogeny_parent_panel_content_rect",
                    "phylogeny_child_section_rect",
                    "phylogeny_diagram_section_rect",
                    "phylogeny_parent_input_rect",
                    "phylogeny_child_input_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        shifted_rect = rect_value.move(0, -scroll_y)
                        card[rect_key] = (
                            shifted_rect.clip(content_viewport_rect)
                            if shifted_rect.colliderect(content_viewport_rect)
                            else None
                        )
                for collection_key in (
                    "phylogeny_parent_match_rows",
                    "phylogeny_child_match_rows",
                    "phylogeny_parent_tree_rows",
                    "phylogeny_local_tree_rows",
                ):
                    visible_rows = []
                    for row in card.get(collection_key, []):
                        row_rect = row.get("rect")
                        if row_rect is not None:
                            shifted_rect = row_rect.move(0, -scroll_y)
                            if not shifted_rect.colliderect(content_viewport_rect):
                                continue
                            row["rect"] = shifted_rect.clip(content_viewport_rect)
                        visible_rows.append(row)
                    card[collection_key] = visible_rows
                card["phylogeny_node_hitboxes"] = [
                    (clade_id, node_rect.move(0, -scroll_y).clip(content_viewport_rect))
                    for clade_id, node_rect in card.get("phylogeny_node_hitboxes", [])
                    if node_rect.move(0, -scroll_y).colliderect(content_viewport_rect)
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
                (illustration_id, button_rect.clip(content_viewport_rect))
                for illustration_id, button_rect in media_import_hitboxes
                if button_rect.colliderect(content_viewport_rect)
            ]
            media_pixel_art_hitboxes = [
                (illustration_id, button_rect.clip(content_viewport_rect))
                for illustration_id, button_rect in media_pixel_art_hitboxes
                if button_rect.colliderect(content_viewport_rect)
            ]
            if media_add_illustration_rect is not None:
                media_add_illustration_rect = (
                    media_add_illustration_rect.clip(content_viewport_rect)
                    if media_add_illustration_rect.colliderect(content_viewport_rect)
                    else None
                )
            media_illustration_link_hitboxes = [
                (illustration_id, title_rect.clip(content_viewport_rect))
                for illustration_id, title_rect in media_illustration_link_hitboxes
                if title_rect.colliderect(content_viewport_rect)
            ]
            if self._is_phylogeny_mode():
                for rect_key in (
                    "phylogeny_parent_section_rect",
                    "phylogeny_parent_panel_rect",
                    "phylogeny_parent_panel_content_rect",
                    "phylogeny_child_section_rect",
                    "phylogeny_diagram_section_rect",
                    "phylogeny_parent_input_rect",
                    "phylogeny_child_input_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        card[rect_key] = (
                            rect_value.clip(content_viewport_rect)
                            if rect_value.colliderect(content_viewport_rect)
                            else None
                        )
                card["phylogeny_node_hitboxes"] = [
                    (clade_id, node_rect.clip(content_viewport_rect))
                    for clade_id, node_rect in card.get("phylogeny_node_hitboxes", [])
                    if node_rect.colliderect(content_viewport_rect)
                ]
                for collection_key in (
                    "phylogeny_parent_match_rows",
                    "phylogeny_child_match_rows",
                    "phylogeny_parent_tree_rows",
                    "phylogeny_local_tree_rows",
                ):
                    visible_rows = []
                    for row in card.get(collection_key, []):
                        row_rect = row.get("rect")
                        if row_rect is not None:
                            if not row_rect.colliderect(content_viewport_rect):
                                continue
                            row["rect"] = row_rect.clip(content_viewport_rect)
                        visible_rows.append(row)
                    card[collection_key] = visible_rows
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

        if self._uses_toolbelt(card):
            toolbelt_rect = pygame.Rect(final_rect.right, final_rect.y, self.TOOLBELT_W, final_rect.height)
            tool_y = toolbelt_rect.y + 38
            tool_inner_x = toolbelt_rect.x + 8
            tool_inner_w = toolbelt_rect.width - 16
            line_h = self._table_line_height(card["layout_font"])
            for tool in self._toolbelt_items():
                if tool.get("kind") == "color_picker":
                    row_h = 128
                    row_rect = pygame.Rect(tool_inner_x, tool_y, tool_inner_w, row_h)
                    preview_rect = pygame.Rect(row_rect.x + 6, row_rect.y + 46, 28, 28)
                    role_rects = []
                    role_x = row_rect.x + 6
                    role_y = row_rect.y + 24
                    role_gap = 4
                    role_w = max(30, (row_rect.width - 12 - role_gap * 2) // 3)
                    for role_id, role_label in self.CARD_COLOR_ROLES:
                        role_rect = pygame.Rect(role_x, role_y, role_w, 18)
                        role_info = dict(tool)
                        role_info["control"] = "role"
                        role_info["role"] = role_id
                        role_rects.append({"role": role_id, "label": role_label, "rect": role_rect})
                        toolbelt_hitboxes.append((role_info, role_rect))
                        role_x = role_rect.right + role_gap
                    slider_rects = []
                    slider_x = row_rect.x + 28
                    slider_w = row_rect.width - 36
                    for slider_index, (channel, label) in enumerate(self.CARD_COLOR_SLIDERS):
                        slider_rect = pygame.Rect(
                            slider_x,
                            row_rect.y + 78 + slider_index * 15,
                            slider_w,
                            10,
                        )
                        slider_info = dict(tool)
                        slider_info["control"] = "slider"
                        slider_info["channel"] = channel
                        slider_info["slider_rect"] = slider_rect
                        slider_rects.append({"channel": channel, "label": label, "rect": slider_rect})
                        toolbelt_hitboxes.append((slider_info, slider_rect.inflate(6, 8)))

                    toolbelt_rows.append(
                        {
                            "tool": tool,
                            "row_rect": row_rect,
                            "button_rect": None,
                            "preview_rect": preview_rect,
                            "role_rects": role_rects,
                            "slider_rects": slider_rects,
                            "description_lines": [],
                        }
                    )
                    tool_y = row_rect.bottom + 8
                    continue

                description_lines = self._wrap_text_lines(
                    tool.get("description", ""),
                    card["layout_font"],
                    tool_inner_w,
                )[:2]
                row_h = max(48, 28 + len(description_lines) * line_h)
                row_rect = pygame.Rect(tool_inner_x, tool_y, tool_inner_w, row_h)
                button_rect = pygame.Rect(row_rect.x, row_rect.y, row_rect.width, 24)
                toolbelt_rows.append(
                    {
                        "tool": tool,
                        "row_rect": row_rect,
                        "button_rect": button_rect,
                        "description_lines": description_lines,
                    }
                )
                toolbelt_hitboxes.append((tool, row_rect))
                tool_y = row_rect.bottom + 8

        card["rect"] = final_rect
        card["toolbelt_rect"] = toolbelt_rect
        card["toolbelt_rows"] = toolbelt_rows
        card["tab_hitboxes"] = tab_hitboxes
        card["subtab_hitboxes"] = subtab_hitboxes
        card["image_rect"] = image_rect
        card["general_content_rect"] = general_content_rect
        card["task_checklist_rect"] = task_checklist_rect
        card["task_finish_checkbox_rect"] = task_finish_checkbox_rect
        card["task_checklist_hitboxes"] = task_checklist_hitboxes
        card["task_checklist_input_rect"] = task_checklist_input_rect
        card["timeline_label_y"] = timeline_label_y
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["corner_handle_rects"] = corner_handle_rects
        card["section_hitboxes"] = section_hitboxes
        card["section_draw_rects"] = section_draw_rects
        card["media_import_hitboxes"] = media_import_hitboxes
        card["media_pixel_art_hitboxes"] = media_pixel_art_hitboxes
        card["media_add_illustration_rect"] = media_add_illustration_rect
        card["media_illustration_rows"] = media_illustration_rows
        card["media_illustration_link_hitboxes"] = media_illustration_link_hitboxes
        card["editable_field_hitboxes"] = editable_field_hitboxes
        card["relation_hitboxes"] = relation_hitboxes
        card["wiki_link_hitboxes"] = wiki_link_hitboxes
        card["wiki_section_hitboxes"] = wiki_section_hitboxes
        card["toolbelt_hitboxes"] = toolbelt_hitboxes
        card["field_rows"] = field_rows
        card["resize_hitboxes"] = resize_hitboxes
        card["edit_toggle_rect"] = edit_toggle_rect
        card["idea_button_rect"] = idea_button_rect
        card["relation_tree_rect"] = relation_tree_rect
        card["header_icon_ref"] = header_icon_ref
        card["header_icon_rect"] = header_icon_rect
        card["time_anchor_rect"] = time_anchor_rect
        card["delete_rect"] = delete_rect
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
            if self._is_task_card():
                general_h += 8 + self._measure_task_checklist_height(
                    font,
                    content_rect.width,
                    card,
                )
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            timeline_label_y = tabs_bottom_y + 10 + general_h + 8
            timeline_y = timeline_label_y + 18
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(320, resize_bottom + 8)

        if self._is_phylogeny_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            current_y = tabs_bottom_y + 10
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP
            if not self.collapsed_sections.get("Phylogeny Parents", False):
                current_y += self.PHYLOGENY_PARENT_PANEL_H + 16
            else:
                current_y += 8
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP
            if not self.collapsed_sections.get("Members", False):
                line_h = self._phylogeny_line_height(font)
                limit_key = "phylogeny_clade_member_limit" if self._is_cladistics_card() else "phylogeny_species_relative_limit"
                visible_rows = max(1, int(card.get(limit_key, 3 if self._is_cladistics_card() else 4) or 1))
                current_y += visible_rows * (line_h + 13)
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(360, resize_bottom + 8)

        tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
        if self._active_subtab_order():
            tabs_bottom_y += 5 + self.SUBTAB_H

        current_y = tabs_bottom_y + 6 + self._image_block_height() + 12
        if not self._uses_image_block():
            current_y = tabs_bottom_y + 10
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
        launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
        resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE

        return max(260, resize_bottom + 8)

    def draw_card(self, screen, font, card):
        rect = card["rect"]
        card_color = self._card_background_color("body")
        card_header_color = self._card_background_color("header")
        card_border_color = self._mix_color(card_color, (226, 232, 244), 0.62)
        body_text_color = self._readable_text_color(card_color)
        body_muted_color = self._mix_color(body_text_color, card_color, 0.32)
        header_text_color = self._readable_text_color(card_header_color)
        header_muted_color = self._mix_color(header_text_color, card_header_color, 0.35)

        pygame.draw.rect(screen, card_color, rect)
        pygame.draw.rect(screen, card_border_color, rect, 1)

        header_rect = card["header_drag_rect"]
        pygame.draw.rect(screen, card_header_color, header_rect)
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

        title_x = rect.x + 12
        subtitle_x = rect.x + 12
        icon_rect = card.get("header_icon_rect")
        icon_ref = card.get("header_icon_ref")
        if icon_rect is not None and icon_ref:
            pygame.draw.rect(screen, (18, 20, 26), icon_rect)
            pygame.draw.rect(screen, self._mix_color(header_text_color, card_header_color, 0.45), icon_rect, 1)
            icon_surface = self._load_card_image_surface(icon_ref)
            if icon_surface is not None:
                self._draw_scaled_preview(screen, icon_surface, icon_rect.inflate(4, 4))
            title_x = icon_rect.right + 8
            subtitle_x = icon_rect.right + 8

        type_label_rect = card.get("type_label_rect")
        title_max_w = max(30, rect.right - 156 - title_x)
        if type_label_rect is not None:
            title_max_w = max(30, type_label_rect.right - title_x)
        title_surface = font.render(self._ellipsize_text(title_text, font, title_max_w), True, header_text_color)
        subtitle_max_w = title_max_w
        subtitle_surface = font.render(
            self._ellipsize_text(card["subtitle"], font, subtitle_max_w),
            True,
            header_muted_color,
        )
        screen.blit(title_surface, (title_x, rect.y + 10))
        if type_label_rect is not None:
            hover_pos = pygame.mouse.get_pos()
            if type_label_rect.collidepoint(hover_pos):
                pygame.draw.rect(screen, (42, 48, 62), type_label_rect)
                pygame.draw.rect(screen, (130, 150, 190), type_label_rect, 1)
        screen.blit(subtitle_surface, (subtitle_x, rect.y + 30))

        edit_toggle_rect = card.get("edit_toggle_rect")
        idea_button_rect = card.get("idea_button_rect")
        relation_tree_rect = card.get("relation_tree_rect")
        time_anchor_rect = card.get("time_anchor_rect")
        delete_rect = card.get("delete_rect")
        close_rect = card.get("close_rect")
        if idea_button_rect is not None:
            pygame.draw.rect(screen, (52, 60, 48), idea_button_rect)
            pygame.draw.rect(screen, (150, 176, 132), idea_button_rect, 1)
            idea_text = font.render("I", True, (230, 244, 218))
            idea_text_rect = idea_text.get_rect(center=idea_button_rect.center)
            screen.blit(idea_text, idea_text_rect)

        if relation_tree_rect is not None:
            pygame.draw.rect(screen, (52, 56, 68), relation_tree_rect)
            pygame.draw.rect(screen, (160, 168, 196), relation_tree_rect, 1)
            relation_text = font.render("A", True, (232, 236, 252))
            relation_text_rect = relation_text.get_rect(center=relation_tree_rect.center)
            screen.blit(relation_text, relation_text_rect)

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

        if time_anchor_rect is not None:
            anchor_active = bool(card.get("timeline_reanchor_active", False))
            anchor_fill = (112, 88, 42) if anchor_active else (52, 50, 42)
            anchor_border = (232, 210, 148) if anchor_active else (156, 146, 112)
            pygame.draw.rect(screen, anchor_fill, time_anchor_rect)
            pygame.draw.rect(screen, anchor_border, time_anchor_rect, 1)
            anchor_text = font.render("T", True, (244, 232, 190))
            anchor_text_rect = anchor_text.get_rect(center=time_anchor_rect.center)
            screen.blit(anchor_text, anchor_text_rect)

        if delete_rect is not None:
            delete_confirm = bool(card.get("delete_confirm_active", False))
            delete_fill = (118, 42, 48) if delete_confirm else (64, 42, 46)
            delete_border = (246, 166, 176) if delete_confirm else (178, 116, 124)
            pygame.draw.rect(screen, delete_fill, delete_rect)
            pygame.draw.rect(screen, delete_border, delete_rect, 1)
            delete_text = font.render("!" if delete_confirm else "D", True, (255, 226, 230))
            delete_text_rect = delete_text.get_rect(center=delete_rect.center)
            screen.blit(delete_text, delete_text_rect)

        if close_rect is not None:
            pygame.draw.rect(screen, (58, 44, 48), close_rect)
            pygame.draw.rect(screen, (178, 132, 140), close_rect, 1)
            close_text = font.render("X", True, (244, 218, 222))
            close_text_rect = close_text.get_rect(center=close_rect.center)
            screen.blit(close_text, close_text_rect)

        if card.get("is_edit_mode", False):
            active_field = card.get("active_edit_field")
            if card.get("delete_confirm_active", False):
                edit_status = "Confirm delete | Click ! again to remove this entry | Esc cancel"
            elif card.get("timeline_reanchor_active", False):
                edit_status = "Reanchoring card | Click timeline to set | Esc cancel"
            elif active_field:
                validation_message = str(card.get("edit_validation_message") or "")
                if validation_message:
                    edit_status = validation_message
                elif active_field in self.TEMPORAL_FIELDS:
                    edit_status = f"Editing {active_field} | Click timeline to set | Enter save | Esc cancel"
                elif active_field == "wiki_entry":
                    edit_status = "Editing wiki_entry | Enter newline | Ctrl+Enter save | Ctrl+L link"
                elif self.is_relation_edit_field(active_field):
                    edit_status = f"Editing {active_field} | Search relations | Enter insert | Ctrl+Enter save"
                elif active_field in {"star_class", "spectral_class"}:
                    edit_status = STELLAR_CLASS_HELP
                else:
                    edit_status = f"Editing {active_field} | Enter save | Esc cancel | Tab next"
            else:
                edit_status = "Edit mode | Click a highlighted row, or T then timeline to reanchor"
            status_surface = font.render(edit_status, True, header_muted_color)
            status_x = rect.right - 44 - status_surface.get_width()
            status_x = max(rect.x + 150, status_x)
            screen.blit(status_surface, (status_x, rect.y + 30))

        self._draw_tabs(screen, font, card)
        self._draw_subtabs(screen, font, card)
        if self._is_general_mode():
            self._draw_general_content(screen, font, card)
        elif self._is_phylogeny_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_phylogeny_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
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
        launch_rect = card["launch_rect"]
        font_h = max(1, font.get_linesize())
        timeline_room_h = max(0, launch_rect.y - timeline_label_y)
        compact_timeline = rect.width < 320 or timeline_room_h < 62

        years = card.get("years", [])
        if len(years) >= 2:
            duration_label = self._timeline_duration_label(years)
            timeline_label = f"Range: {years[0]}-{years[-1]}"
            if duration_label:
                timeline_label += f" ({duration_label})"
        elif len(years) == 1:
            timeline_label = f"Year: {years[0]}"
        else:
            timeline_label = "Year: missing"

        label_fits_above_line = timeline_label_y + font_h <= center_y - 4
        if label_fits_above_line and rect.width >= 180:
            timeline_label = self._ellipsize_text(timeline_label, font, rect.width - 24)
            timeline_label_surface = font.render(timeline_label, True, body_text_color)
            screen.blit(timeline_label_surface, (rect.x + 12, timeline_label_y))

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)

        year_label_rects = []
        year_label_y = center_y + 22
        show_year_labels = (
            not compact_timeline
            and year_label_y + font_h <= launch_rect.y - 4
            and rect.width >= 260
        )
        selected_year = card.get("selected_year")
        for year, hitbox in card["year_hitboxes"]:
            marker_rect = pygame.Rect(hitbox.centerx - 5, center_y - 5, 10, 10)
            selected = year == selected_year

            fill = (210, 210, 210) if selected else (70, 70, 70)
            border = (240, 240, 240) if selected else (170, 170, 170)
            pygame.draw.rect(screen, fill, marker_rect)
            pygame.draw.rect(screen, border, marker_rect, 1)

            if show_year_labels:
                year_surface = font.render(str(year), True, body_text_color)
                year_rect = year_surface.get_rect(center=(hitbox.centerx, year_label_y))
                year_rect.x = max(rect.x + 12, min(year_rect.x, rect.right - 12 - year_rect.width))
                if not any(year_rect.inflate(8, 0).colliderect(existing) for existing in year_label_rects):
                    screen.blit(year_surface, year_rect)
                    year_label_rects.append(year_rect)

        related_entries = self._related_timeline_entries(card)
        card_range = self._card_timeline_range(card)
        show_related_timeline = (
            not compact_timeline
            and center_y + self.RELATED_TIMELINE_OFFSET_Y + font_h + 8 <= launch_rect.y
            and rect.width >= 300
        )
        if show_related_timeline and related_entries and card_range is not None:
            range_start, range_end = card_range
            range_span = max(1, range_end - range_start)

            def related_year_x(year):
                if range_end == range_start:
                    return (left_x + right_x) // 2
                ratio = (year - range_start) / float(range_span)
                ratio = max(0.0, min(1.0, ratio))
                return left_x + int(round((right_x - left_x) * ratio))

            related_y = center_y + self.RELATED_TIMELINE_OFFSET_Y
            pygame.draw.line(screen, (86, 96, 122), (left_x, related_y), (right_x, related_y), 1)

            label_rects = []
            visible_related = related_entries[:self.RELATED_TIMELINE_LABEL_LIMIT]
            for entry in visible_related:
                x1 = related_year_x(entry["start_year"])
                x2 = related_year_x(entry["end_year"])
                if entry["is_point"]:
                    pygame.draw.circle(screen, (196, 172, 112), (x1, related_y), 3)
                else:
                    bar_rect = pygame.Rect(min(x1, x2), related_y - 3, max(6, abs(x2 - x1)), 6)
                    pygame.draw.rect(screen, (166, 136, 92), bar_rect)
                    pygame.draw.rect(screen, (218, 192, 132), bar_rect, 1)

                label = self._ellipsize_text(entry["label"], font, 82)
                label_surface = font.render(label, True, (214, 198, 150))
                label_x = max(left_x, min(x1 - label_surface.get_width() // 2, right_x - label_surface.get_width()))
                label_rect = pygame.Rect(label_x, related_y + 5, label_surface.get_width(), label_surface.get_height())
                if any(label_rect.inflate(4, 0).colliderect(existing) for existing in label_rects):
                    continue
                screen.blit(label_surface, label_rect)
                label_rects.append(label_rect)

            hidden_count = len(related_entries) - len(visible_related)
            if hidden_count > 0:
                more_surface = font.render(f"+{hidden_count}", True, (214, 198, 150))
                screen.blit(more_surface, (right_x - more_surface.get_width(), related_y + 5))

        pygame.draw.rect(screen, (55, 55, 55), launch_rect)
        pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
        launch_label = f"Launch [{selected_year}]" if selected_year is not None else "Launch"
        launch_text = font.render(launch_label, True, (245, 245, 245))
        launch_text_rect = launch_text.get_rect(center=launch_rect.center)
        screen.blit(launch_text, launch_text_rect)
        self._draw_toolbelt(screen, font, card)

    def _draw_toolbelt(self, screen, font, card):
        toolbelt_rect = card.get("toolbelt_rect")
        if toolbelt_rect is None:
            return

        pygame.draw.rect(screen, (24, 28, 36), toolbelt_rect)
        pygame.draw.rect(screen, (128, 144, 168), toolbelt_rect, 1)
        pygame.draw.line(
            screen,
            (86, 98, 118),
            (toolbelt_rect.x, toolbelt_rect.y + 1),
            (toolbelt_rect.x, toolbelt_rect.bottom - 1),
            1,
        )

        title_surface = font.render("Toolbox", True, (236, 240, 248))
        screen.blit(title_surface, (toolbelt_rect.x + 8, toolbelt_rect.y + 10))

        for row in card.get("toolbelt_rows", []):
            row_rect = row.get("row_rect")
            button_rect = row.get("button_rect")
            if row_rect is None:
                continue

            pygame.draw.rect(screen, (32, 38, 50), row_rect)
            pygame.draw.rect(screen, (82, 98, 124), row_rect, 1)

            tool = row.get("tool", {})
            if tool.get("kind") == "color_picker":
                label = self._ellipsize_text(tool.get("label", "Color"), font, row_rect.width - 12)
                label_surface = font.render(label, True, (230, 236, 246))
                screen.blit(label_surface, (row_rect.x + 6, row_rect.y + 5))
                active_role = self._active_color_role(card)
                active_section_id = self._active_wiki_section_id(card) if active_role == "wiki" else None
                current_color = self._card_background_color(role=active_role, section_id=active_section_id)
                hue, saturation, brightness = self._card_hsv(role=active_role, section_id=active_section_id)
                for role in row.get("role_rects", []):
                    role_rect = role.get("rect")
                    if role_rect is None:
                        continue
                    selected = role.get("role") == active_role
                    fill = (64, 84, 122) if selected else (34, 40, 52)
                    border = (218, 226, 244) if selected else (92, 104, 126)
                    pygame.draw.rect(screen, fill, role_rect)
                    pygame.draw.rect(screen, border, role_rect, 1)
                    role_label = self._ellipsize_text(role.get("label", ""), font, role_rect.width - 6)
                    role_surface = font.render(role_label, True, (242, 246, 252) if selected else (178, 188, 204))
                    screen.blit(role_surface, role_surface.get_rect(center=role_rect.center))
                preview_rect = row.get("preview_rect")
                if preview_rect is not None:
                    pygame.draw.rect(screen, current_color, preview_rect)
                    pygame.draw.rect(screen, (218, 226, 240), preview_rect, 1)
                hex_label = self._rgb_to_hex(current_color)
                hex_surface = font.render(hex_label, True, (176, 186, 204))
                screen.blit(hex_surface, (row_rect.x + 40, row_rect.y + 30))
                if active_role == "wiki" and active_section_id:
                    target_label = self._ellipsize_text(active_section_id.replace("_", " "), font, row_rect.width - 44)
                    target_surface = font.render(target_label, True, (156, 166, 184))
                    screen.blit(target_surface, (row_rect.x + 40, row_rect.y + 47))

                values = {"h": hue, "s": saturation, "v": brightness}
                for slider in row.get("slider_rects", []):
                    slider_rect = slider.get("rect")
                    channel = slider.get("channel")
                    if slider_rect is None or channel not in values:
                        continue
                    label_surface = font.render(slider.get("label", channel).upper(), True, (204, 212, 228))
                    screen.blit(label_surface, (row_rect.x + 8, slider_rect.y - 3))
                    self._draw_color_slider_track(screen, slider_rect, channel, hue, saturation, brightness)
                    pygame.draw.rect(screen, (28, 32, 42), slider_rect, 1)
                    knob_x = int(slider_rect.x + values[channel] * max(0, slider_rect.width - 1))
                    knob_rect = pygame.Rect(knob_x - 2, slider_rect.y - 3, 5, slider_rect.height + 6)
                    pygame.draw.rect(screen, (244, 248, 255), knob_rect)
                    pygame.draw.rect(screen, (36, 42, 54), knob_rect, 1)
                continue

            if button_rect is None:
                continue

            pygame.draw.rect(screen, (46, 70, 96), button_rect)
            pygame.draw.rect(screen, (158, 190, 230), button_rect, 1)
            label = self._ellipsize_text(tool.get("label", "Create"), font, button_rect.width - 12)
            label_surface = font.render(label, True, (238, 246, 255))
            screen.blit(label_surface, label_surface.get_rect(center=button_rect.center))

            line_y = button_rect.bottom + 4
            line_h = self._table_line_height(font)
            for line in row.get("description_lines", []):
                description_surface = font.render(line, True, (164, 174, 194))
                screen.blit(description_surface, (row_rect.x + 4, line_y))
                line_y += line_h

    def _draw_color_slider_track(self, screen, rect, channel, hue, saturation, brightness):
        width = max(1, rect.width)
        for offset in range(width):
            value = offset / max(1, width - 1)
            if channel == "h":
                color = self._hsv_to_rgb(value, 1.0, 1.0)
            elif channel == "s":
                color = self._hsv_to_rgb(hue, value, max(0.25, brightness))
            else:
                color = self._hsv_to_rgb(hue, saturation, value)
            pygame.draw.line(screen, color, (rect.x + offset, rect.y), (rect.x + offset, rect.bottom - 1))

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
                "phylogeny": "Phylo",
                "state": "State",
                "simulation": "Sim",
                "operational": "Ops",
                "media": "Media",
            }
            if font.size(label)[0] > tab_rect.width - 8:
                label = abbreviations.get(tab_name, label[:4])
            text_surface = font.render(label, True, text_color)
            text_rect = text_surface.get_rect(center=tab_rect.center)
            screen.blit(text_surface, text_rect)

    def _draw_subtabs(self, screen, font, card):
        for tab_name, subtab_name, subtab_rect in card.get("subtab_hitboxes", []):
            if tab_name != self.active_tab:
                continue

            selected = tab_name == "simulation" and subtab_name == self.active_simulation_subtab
            fill = (50, 58, 72) if selected else (32, 36, 46)
            border = (184, 194, 214) if selected else (92, 102, 122)
            text_color = (240, 244, 250) if selected else (176, 184, 198)

            pygame.draw.rect(screen, fill, subtab_rect)
            pygame.draw.rect(screen, border, subtab_rect, 1)

            label = self.SIMULATION_SUBTAB_LABELS.get(subtab_name, subtab_name.title())
            if font.size(label)[0] > subtab_rect.width - 8:
                abbreviations = {
                    "space": "Space",
                    "map": "Map",
                    "world_gen": "World",
                }
                label = abbreviations.get(subtab_name, label[:5])
            text_surface = font.render(label, True, text_color)
            screen.blit(text_surface, text_surface.get_rect(center=subtab_rect.center))

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
        header_y = image_rect.y + 8
        title_surface = font.render("Illustrations", True, (232, 234, 240))
        screen.blit(title_surface, (image_rect.x + 10, header_y + 4))

        add_rect = card.get("media_add_illustration_rect")
        if add_rect is not None:
            mouse_pos = pygame.mouse.get_pos()
            fill = (64, 80, 114) if add_rect.collidepoint(mouse_pos) else (52, 62, 84)
            pygame.draw.rect(screen, fill, add_rect)
            pygame.draw.rect(screen, (184, 196, 220), add_rect, 1)
            add_text = font.render("Add Illustration", True, (245, 245, 245))
            screen.blit(add_text, add_text.get_rect(center=add_rect.center))

        rows = card.get("media_illustration_rows", [])
        if not rows:
            empty_rect = pygame.Rect(image_rect.x + 8, image_rect.y + 46, image_rect.width - 16, 58)
            pygame.draw.rect(screen, (34, 37, 48), empty_rect)
            pygame.draw.rect(screen, (88, 94, 112), empty_rect, 1)
            empty_text = font.render("No illustration ideas yet", True, (174, 182, 198))
            screen.blit(empty_text, (empty_rect.x + 10, empty_rect.y + 20))
            return

        import_buttons = {
            illustration_id: button_rect
            for illustration_id, button_rect in card.get("media_import_hitboxes", [])
        }
        pixel_buttons = {
            illustration_id: button_rect
            for illustration_id, button_rect in card.get("media_pixel_art_hitboxes", [])
        }

        for row in rows:
            row_rect = row.get("row_rect")
            illustration = row.get("entity")
            if row_rect is None or not isinstance(illustration, dict):
                continue
            if not row_rect.colliderect(image_rect):
                continue

            pygame.draw.rect(screen, (34, 37, 48), row_rect)
            pygame.draw.rect(screen, (82, 88, 106), row_rect, 1)

            thumb_rect = pygame.Rect(row_rect.x + 8, row_rect.y + 8, 42, row_rect.height - 16)
            pygame.draw.rect(screen, (26, 28, 36), thumb_rect)
            pygame.draw.rect(screen, (96, 104, 124), thumb_rect, 1)

            image_ref = self._illustration_media_path(illustration)
            image_surface = self._load_card_image_surface(image_ref)
            if image_surface is not None:
                self._draw_scaled_preview(screen, image_surface, thumb_rect)
            else:
                placeholder = font.render("empty", True, (136, 146, 166))
                screen.blit(placeholder, placeholder.get_rect(center=thumb_rect.center))

            text_x = thumb_rect.right + 10
            text_w = max(40, row_rect.width - 264)
            label = self._entity_display_label(illustration) or "Untitled Illustration"
            date = str(illustration.get("date") or "").strip()
            label_line = label if not date else f"{label} ({date})"
            title_rect = row.get("title_rect")
            title_hovered = title_rect is not None and title_rect.collidepoint(pygame.mouse.get_pos())
            label_color = (204, 224, 255) if title_hovered else (232, 234, 240)
            label_surface = font.render(label_line, True, label_color)
            screen.blit(label_surface, (text_x, row_rect.y + 8))
            if title_hovered:
                underline_y = row_rect.y + 8 + label_surface.get_height()
                pygame.draw.line(
                    screen,
                    label_color,
                    (text_x, underline_y),
                    (min(text_x + label_surface.get_width(), row_rect.right - 10), underline_y),
                    1,
                )

            description = str(illustration.get("description") or "").strip()
            for line_index, line in enumerate(self._wrap_text_lines(description or "No description", font, text_w)[:2]):
                color = (178, 186, 202) if description else (136, 146, 166)
                line_surface = font.render(line, True, color)
                screen.blit(line_surface, (text_x, row_rect.y + 28 + line_index * self.TEXT_LINE_H))

            button_rect = import_buttons.get(row.get("id"))
            if button_rect is not None:
                pygame.draw.rect(screen, (58, 64, 78), button_rect)
                pygame.draw.rect(screen, (200, 200, 210), button_rect, 1)
                button_text = font.render("Import image", True, (245, 245, 245))
                screen.blit(button_text, button_text.get_rect(center=button_rect.center))

            pixel_rect = pixel_buttons.get(row.get("id"))
            if pixel_rect is not None:
                mouse_pos = pygame.mouse.get_pos()
                fill = (66, 78, 104) if pixel_rect.collidepoint(mouse_pos) else (52, 58, 78)
                pygame.draw.rect(screen, fill, pixel_rect)
                pygame.draw.rect(screen, (186, 202, 232), pixel_rect, 1)
                pixel_text = font.render("Pixel Art", True, (245, 245, 245))
                screen.blit(pixel_text, pixel_text.get_rect(center=pixel_rect.center))

    def _draw_temporal_wiki_block(self, screen, font, card, image_rect):
        pygame.draw.rect(screen, (32, 35, 44), image_rect)
        pygame.draw.rect(screen, (92, 100, 120), image_rect, 1)
        inner_rect = image_rect.inflate(-12, -10)
        wiki_text = self._get_general_wiki_text(card)
        CardWikiRenderer.draw_content(
            screen,
            font,
            inner_rect,
            wiki_text,
            is_editing=False,
            resolve_link_label=self._resolve_wiki_link_label,
            resolve_link_color=self._resolve_wiki_link_color,
            resolve_link_palette=self._resolve_wiki_link_palette,
            section_colors=self._wiki_field_colors(),
            cursor_index=0,
            scroll_y=0,
        )

    def _draw_image_block(self, screen, font, card):
        if self._is_general_mode():
            return

        image_rect = card["image_rect"]
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)

        if self._is_media_mode():
            self._draw_media_block(screen, font, card, image_rect)
            return

        if self._is_temporal_mode():
            self._draw_temporal_wiki_block(screen, font, card, image_rect)
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

    def _draw_phylogeny_section_header(self, screen, font, rect, label, expanded):
        if rect is None:
            return
        pygame.draw.rect(screen, (36, 40, 50), rect)
        pygame.draw.rect(screen, (110, 110, 120), rect, 1)
        marker = "v" if expanded else ">"
        screen.blit(font.render(f"{marker} {label}", True, (235, 235, 235)), (rect.x + 8, rect.y + 3))

    def _draw_phylogeny_rows(self, screen, font, rows, muted=False):
        line_h = self._phylogeny_line_height(font)
        for row in rows:
            row_rect = row.get("rect")
            if row_rect is None:
                continue
            palette = self._phylogeny_row_palette(row, muted=muted)
            if palette is None:
                fill, border, text_color = self._phylogeny_row_colors(row, muted=muted)
                band = None
            else:
                fill, border, text_color = palette["fill"], palette["border"], palette["text"]
                band = palette.get("band")
            pygame.draw.rect(screen, fill, row_rect)
            if band is not None:
                band_rect = pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height)
                pygame.draw.rect(screen, band, band_rect)
            pygame.draw.rect(screen, border, row_rect, 1)
            text_x = row_rect.x + (11 if band is not None else 8)
            available_w = row_rect.right - text_x - 8
            distance_label = str(row.get("distance_label") or "").strip()
            if distance_label:
                badge_w = min(64, max(42, row_rect.width // 3))
                badge_rect = pygame.Rect(row_rect.x + 5, row_rect.y + 4, badge_w, max(14, row_rect.height - 8))
                pygame.draw.rect(screen, (24, 28, 36), badge_rect)
                pygame.draw.rect(screen, (132, 148, 174), badge_rect, 1)
                badge_text = self._ellipsize_text(distance_label, font, badge_rect.width - 8)
                badge_surface = font.render(badge_text, True, (232, 238, 248))
                screen.blit(badge_surface, badge_surface.get_rect(center=badge_rect.center))
                text_x = badge_rect.right + 8
                available_w = max(20, row_rect.right - text_x - 8)
            label = self._ellipsize_text(str(row.get("label") or row.get("id") or ""), font, available_w)
            screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + max(3, (row_rect.height - line_h) // 2)))

    def _draw_phylogeny_parent_scrollbar(self, screen, card):
        panel_rect = card.get("phylogeny_parent_panel_rect")
        content_rect = card.get("phylogeny_parent_panel_content_rect")
        max_scroll = max(0, int(card.get("phylogeny_parent_scroll_max_y", 0) or 0))
        if panel_rect is None or content_rect is None or max_scroll <= 0:
            return

        track_rect = pygame.Rect(panel_rect.right - 7, content_rect.y, 3, content_rect.height)
        pygame.draw.rect(screen, (44, 50, 62), track_rect)
        visible_h = max(1, content_rect.height)
        content_h = visible_h + max_scroll
        thumb_h = max(18, int(round(track_rect.height * visible_h / max(1, content_h))))
        scroll_y = max(0, min(max_scroll, int(card.get("phylogeny_parent_scroll_y", 0) or 0)))
        thumb_y = track_rect.y + int(round((track_rect.height - thumb_h) * scroll_y / max(1, max_scroll)))
        pygame.draw.rect(screen, (132, 146, 170), pygame.Rect(track_rect.x, thumb_y, track_rect.width, thumb_h))

    def _draw_phylogeny_content(self, screen, font, card):
        parent_expanded = not self.collapsed_sections.get("Phylogeny Parents", False)
        diagram_expanded = not self.collapsed_sections.get("Members", False)
        self._draw_phylogeny_section_header(
            screen,
            font,
            card.get("phylogeny_parent_section_rect"),
            "Phylogeny Parents",
            parent_expanded,
        )

        panel_rect = card.get("phylogeny_parent_panel_rect")
        panel_content_rect = card.get("phylogeny_parent_panel_content_rect")
        previous_clip = screen.get_clip()
        if parent_expanded and panel_rect is not None:
            pygame.draw.rect(screen, (24, 28, 36), panel_rect)
            pygame.draw.rect(screen, (94, 108, 132), panel_rect, 1)
            if panel_content_rect is not None:
                screen.set_clip(previous_clip.clip(panel_content_rect))

        input_rect = card.get("phylogeny_parent_input_rect")
        try:
            if parent_expanded and input_rect is not None:
                active = bool(card.get("phylogeny_parent_input_active"))
                fill = (40, 48, 64) if active else (30, 35, 44)
                border = (184, 204, 236) if active else (92, 104, 126)
                pygame.draw.rect(screen, fill, input_rect)
                pygame.draw.rect(screen, border, input_rect, 1)
                query = str(card.get("phylogeny_parent_query") or "")
                target = self.world_model.get_entity(card.get("phylogeny_parent_target_id")) if self.world_model is not None else None
                target_label = clade_label(target, card.get("phylogeny_parent_target_id"))
                placeholder = f"+ parent of {target_label}..."
                text = query or placeholder
                color = (238, 240, 246) if query else (144, 154, 172)
                text = self._ellipsize_text(text, font, input_rect.width - 14)
                screen.blit(font.render(text, True, color), (input_rect.x + 7, input_rect.y + 4))

                for row in card.get("phylogeny_parent_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    selected = row.get("index") == card.get("phylogeny_parent_selected_index", 0)
                    is_create = row.get("index") == "create"
                    row_palette = self._phylogeny_row_palette(
                        {
                            "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                            "entity": row.get("entity"),
                            "highlight": selected,
                        }
                    )
                    if row_palette is None:
                        fill, border, text_color = self._phylogeny_row_colors(
                            {
                                "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                                "entity": row.get("entity"),
                                "highlight": selected,
                            }
                        )
                        band = None
                    else:
                        fill, border, text_color = row_palette["fill"], row_palette["border"], row_palette["text"]
                        band = row_palette.get("band")
                    if is_create:
                        fill = (48, 58, 42) if selected else (36, 44, 34)
                        border = (168, 196, 128)
                        text_color = (238, 242, 246)
                        band = None
                    pygame.draw.rect(screen, fill, row_rect)
                    if band is not None:
                        pygame.draw.rect(screen, band, pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height))
                    pygame.draw.rect(screen, border, row_rect, 1)
                    if is_create:
                        label = f"Create clade: {query}"
                    else:
                        label = clade_label(row.get("entity"), "")
                    text_x = row_rect.x + (11 if band is not None else 7)
                    label = self._ellipsize_text(label, font, row_rect.right - text_x - 7)
                    screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + 6))

            if parent_expanded:
                self._draw_phylogeny_rows(screen, font, card.get("phylogeny_parent_tree_rows", []))
                status = str(card.get("phylogeny_status") or "").strip()
                if status and input_rect is not None:
                    status_surface = font.render(status, True, (220, 196, 132))
                    screen.blit(status_surface, (input_rect.x, input_rect.bottom + 2))

            child_input_rect = card.get("phylogeny_child_input_rect")
            if parent_expanded and child_input_rect is not None:
                active = bool(card.get("phylogeny_child_input_active"))
                fill = (40, 48, 64) if active else (30, 35, 44)
                border = (184, 204, 236) if active else (92, 104, 126)
                pygame.draw.rect(screen, fill, child_input_rect)
                pygame.draw.rect(screen, border, child_input_rect, 1)
                query = str(card.get("phylogeny_child_query") or "")
                sibling = self.world_model.get_entity(card.get("phylogeny_child_sibling_id")) if self.world_model is not None else None
                sibling_label = clade_label(sibling, card.get("phylogeny_child_sibling_id"))
                placeholder = f"+ sister of {sibling_label}..."
                text = self._ellipsize_text(query or placeholder, font, child_input_rect.width - 14)
                color = (238, 240, 246) if query else (144, 154, 172)
                screen.blit(font.render(text, True, color), (child_input_rect.x + 7, child_input_rect.y + 4))

                for row in card.get("phylogeny_child_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    selected = row.get("index") == card.get("phylogeny_child_selected_index", 0)
                    is_create = row.get("index") == "create"
                    row_palette = self._phylogeny_row_palette(
                        {
                            "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                            "entity": row.get("entity"),
                            "highlight": selected,
                        }
                    )
                    if row_palette is None:
                        fill, border, text_color = self._phylogeny_row_colors(
                            {
                                "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                                "entity": row.get("entity"),
                                "highlight": selected,
                            }
                        )
                        band = None
                    else:
                        fill, border, text_color = row_palette["fill"], row_palette["border"], row_palette["text"]
                        band = row_palette.get("band")
                    if is_create:
                        fill = (48, 58, 42) if selected else (36, 44, 34)
                        border = (168, 196, 128)
                        text_color = (238, 242, 246)
                        band = None
                    pygame.draw.rect(screen, fill, row_rect)
                    if band is not None:
                        pygame.draw.rect(screen, band, pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height))
                    pygame.draw.rect(screen, border, row_rect, 1)
                    if is_create:
                        label = f"Create clade: {query}"
                    else:
                        entity = row.get("entity")
                        label = clade_label(entity, "")
                    text_x = row_rect.x + (11 if band is not None else 7)
                    label = self._ellipsize_text(label, font, row_rect.right - text_x - 7)
                    screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + 6))
        finally:
            screen.set_clip(previous_clip)

        if parent_expanded:
            self._draw_phylogeny_parent_scrollbar(screen, card)

        self._draw_phylogeny_section_header(
            screen,
            font,
            card.get("phylogeny_diagram_section_rect"),
            card.get("phylogeny_members_label", "Members"),
            diagram_expanded,
        )
        if diagram_expanded:
            rows = card.get("phylogeny_local_tree_rows", [])
            if rows:
                self._draw_phylogeny_rows(screen, font, rows)
            else:
                rect = card.get("phylogeny_diagram_section_rect")
                if rect is not None:
                    screen.blit(font.render("No species entries found yet", True, (150, 160, 178)), (rect.x + 8, rect.bottom + 8))

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
                        chip_fill, chip_border, chip_text_color = self._relation_chip_colors(
                            chip,
                            is_relation_link_target=is_relation_link_target,
                        )
                        chip_palette = self._relation_chip_palette(
                            chip,
                            is_relation_link_target=is_relation_link_target,
                        )
                        chip_band = chip_palette.get("band") if chip_palette is not None else None

                        pygame.draw.rect(screen, chip_fill, chip_rect)
                        if chip_band is not None:
                            pygame.draw.rect(screen, chip_band, pygame.Rect(chip_rect.x, chip_rect.y, min(5, chip_rect.width), chip_rect.height))
                        pygame.draw.rect(screen, chip_border, chip_rect, 1)
                        remove_rect = chip.get("remove_rect")
                        text_max_w = chip_rect.width - 10
                        text_x = chip_rect.x + (11 if chip_band is not None else 6)
                        if remove_rect is not None:
                            text_max_w = max(12, remove_rect.x - text_x - 4)
                        else:
                            text_max_w = max(12, chip_rect.right - text_x - 4)
                        label = self._ellipsize_text(
                            chip.get("display_label", ""),
                            font,
                            text_max_w,
                        )
                        chip_surface = font.render(label, True, chip_text_color)
                        screen.blit(chip_surface, (text_x, chip_rect.y + max(2, (chip_rect.height - line_h) // 2)))
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
            resolve_link_color=self._resolve_wiki_link_color,
            resolve_link_palette=self._resolve_wiki_link_palette,
            section_colors=self._wiki_field_colors(),
            cursor_index=card.get("edit_cursor", 0),
            scroll_y=card.get("scroll_y", 0),
        )

        if card.get("wiki_link_picker_open", False):
            self._draw_wiki_link_picker(screen, font, card, general_rect)

        self._draw_task_checklist(screen, font, card)

    def _draw_checkbox(self, screen, font, rect, checked):
        pygame.draw.rect(screen, (24, 28, 36), rect)
        pygame.draw.rect(screen, (202, 208, 222), rect, 1)
        if checked:
            mark = font.render("x", True, (236, 240, 248))
            screen.blit(mark, mark.get_rect(center=rect.center))

    def _draw_task_checklist(self, screen, font, card):
        checklist_rect = card.get("task_checklist_rect")
        if checklist_rect is None or not self._is_task_card():
            return

        pygame.draw.rect(screen, (26, 30, 40), checklist_rect)
        pygame.draw.rect(screen, (92, 102, 124), checklist_rect, 1)

        line_h = self._table_line_height(font)
        text_x = checklist_rect.x + 24
        finish_rect = card.get("task_finish_checkbox_rect")
        finished = self._task_is_finished()
        if finish_rect is not None:
            self._draw_checkbox(screen, font, finish_rect, finished)
        finish_text = font.render("Finish Task", True, (236, 238, 244))
        screen.blit(finish_text, (text_x, checklist_rect.y + 2))

        completion = self._task_checklist_completion()
        header_y = checklist_rect.y + line_h + 8
        header_text = font.render(f"[Checklist] ({completion}% Complete)", True, (202, 210, 226))
        screen.blit(header_text, (checklist_rect.x + 4, header_y))

        items = self._task_checklist_items()
        row_y = header_y + line_h + 8
        checkbox_by_index = {
            index: rect
            for index, rect in card.get("task_checklist_hitboxes", [])
        }
        if items:
            for index, item in enumerate(items):
                checkbox_rect = checkbox_by_index.get(index)
                if checkbox_rect is not None:
                    self._draw_checkbox(screen, font, checkbox_rect, bool(item.get("done")))
                text_color = (178, 188, 206) if item.get("done") else (232, 234, 240)
                label = self._ellipsize_text(
                    item.get("text", ""),
                    font,
                    checklist_rect.width - 58,
                )
                item_surface = font.render(label, True, text_color)
                screen.blit(item_surface, (checklist_rect.x + 40, row_y))
                row_y += line_h + 6
        else:
            empty_surface = font.render("No checklist items", True, (142, 152, 170))
            screen.blit(empty_surface, (checklist_rect.x + 18, row_y))
            row_y += line_h + 6

        input_rect = card.get("task_checklist_input_rect")
        if input_rect is None:
            return

        input_active = bool(card.get("task_checklist_input_active"))
        fill = (40, 48, 64) if input_active else (30, 34, 44)
        border = (180, 202, 236) if input_active else (88, 98, 118)
        pygame.draw.rect(screen, fill, input_rect)
        pygame.draw.rect(screen, border, input_rect, 1)
        buffer_text = str(card.get("task_checklist_input_buffer") or "")
        placeholder = "Add checklist item..."
        text_color = (238, 238, 238) if buffer_text else (138, 148, 166)
        visible_text = buffer_text or placeholder
        visible_text = self._ellipsize_text(visible_text, font, input_rect.width - 14)
        input_surface = font.render(visible_text, True, text_color)
        screen.blit(input_surface, (input_rect.x + 6, input_rect.y + 3))

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
        picker_h = 100 + min(6, len(matches)) * 42
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
        note_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 28)
        pygame.draw.rect(screen, (44, 50, 64), note_rect)
        pygame.draw.rect(screen, (128, 144, 176), note_rect, 1)
        card["relation_picker_hitboxes"].append(("note", note_rect))
        note_surface = font.render("Add Note", True, (236, 240, 248))
        screen.blit(note_surface, (note_rect.x + 8, note_rect.y + 6))
        row_y += 34
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
