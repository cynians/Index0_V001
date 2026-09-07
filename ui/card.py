import os
import colorsys
import re
import time

import pygame

from engine.scaler import ScaleHelper
from engine.performance_debug import performance_debug
from ui.card_location import CardLocationMixin
from ui.card_phylogeny import CardPhylogenyMixin
from ui.card_production import CardProductionMixin
from ui.card_site import CardSiteMixin
from ui.card_simulation import CardSimulationMixin
from ui.card_task import CardTaskMixin
from ui.card_wiki import CardWikiRenderer
from ui.text_editing import TextEditing
from world.schema_loader import SchemaLoader
from world.plant_growth_catalog import (
    PLANT_GROWTH_BEHAVIOUR_FIELD,
    PLANT_GROWTH_FORM_FIELD,
    PLANT_LIFESPAN_FIELD,
    PLANT_LIFE_CYCLE_FIELD,
    canonical_controlled_plant_value,
    controlled_plant_field_display_label,
    controlled_plant_field_rows,
)
from world.plant_traits import (
    PLANT_LEGACY_FIELDS,
    PLANT_TRAIT_DROPDOWN_FIELDS,
    PLANT_TRAIT_FIELDS,
)
from world.species_inheritance import (
    INFERENCE_CONFLICTS_KEY,
    INFERRED_FIELDS_KEY,
    is_inheritable_species_field,
    resolve_species_field,
)
from world.year_utils import parse_year
from simulations.space.stellar import STELLAR_CLASS_HELP, is_valid_stellar_class

try:
    from app.launch_affordance_resolver import LaunchAffordanceResolver
except ImportError:
    from launch_affordance_resolver import LaunchAffordanceResolver


class EntityCard(CardLocationMixin, CardPhylogenyMixin, CardProductionMixin, CardSiteMixin, CardSimulationMixin, CardTaskMixin):
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    IMAGE_SURFACE_CACHE = {}
    SCALED_PREVIEW_CACHE = {}
    COLOR_SLIDER_SURFACE_CACHE = {}
    MAX_IMAGE_CACHE_ITEMS = 128
    MAX_COLOR_SLIDER_CACHE_ITEMS = 256
    """
    Reusable renderer + interaction helper for one repository entity card.
    """

    HEADER_H = 66
    TAB_H = 24
    SECTION_HEADER_H = 22
    IMAGE_TOP = 86
    IMAGE_H = 110
    MEDIA_IMAGE_H = 244
    PLANT_ASSET_QUICK_ACTIONS = (
        ("leaf", "Leaf"),
        ("stem", "Stem"),
        ("branch", "Branch"),
        ("flower", "Flower"),
        ("fruit", "Fruit"),
    )
    LAUNCH_H = 24
    # Reserve a full line for the related-period timeline below the main
    # timeline.  The previous 58px gap was shorter than a normal font line,
    # so this row was hidden until dragging temporarily separated it from the
    # launch controls.
    TIMELINE_TO_LAUNCH_GAP = 72
    RELATED_TIMELINE_OFFSET_Y = 34
    RELATED_TIMELINE_LABEL_LIMIT = 5
    TOOLBELT_W = 148
    CARD_COLOR_DEFAULT = "#1c1e26"
    CARD_COLOR_SLIDERS = [("h", "H"), ("s", "S"), ("v", "B")]
    CARD_COLOR_ROLES = [
        ("body", "Body"),
        ("header", "Banner"),
        ("wiki", "Wiki"),
        ("wiki_alt", "Wiki B"),
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
    LOCATION_TOPOLOGY_FIELDS = ["parents", "neighbours", "constituents", "overlaps"]
    LOCATION_TOPOLOGY_LABELS = {
        "parents": "Location Parents",
        "neighbours": "Neighbours",
        "constituents": "Constituents",
        "overlaps": "Overlaps",
    }
    LOCATION_TOPOLOGY_HELP = {
        "parents": "Larger locations containing this location.",
        "neighbours": "Adjacent locations.",
        "constituents": "Locations contained by this location.",
        "overlaps": "Locations sharing territory without full containment.",
    }
    LOCATION_TOPOLOGY_EDITABLE_FIELDS = {"parents", "neighbours", "constituents", "overlaps"}
    LOCATION_TOPOLOGY_SYMMETRIC_FIELDS = {"neighbours", "overlaps"}
    LOCATION_TOPOLOGY_FIELD_PREFIX = "location_topology:"
    TIMELINE_SNAPSHOT_FIELD = "timeline_snapshot_entry"
    BIOSPHERE_ROSTER_SECTION_FIELDS = {
        "biosphere_species_collection",
        "biosphere_location",
        "biosphere_scale",
        "biosphere_area_target_m2",
        "biosphere_area_m2",
        "biosphere_width_m",
        "biosphere_height_m",
        "biosphere_map_size_m",
        "biosphere_shape",
        "microfauna_species",
        "small_animal_species",
        "medium_animal_species",
        "large_animal_species",
        "megafauna_species",
        "sessile_life_species",
        "plant_species",
    }
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
        "snapshot_year",
        "end_year",
        "temporal_periods",
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
        "Class Relations",
        "Biosphere Species Roster",
        "Simulation / Plant Ecology",
        "Simulation / Data",
        "Metadata",
    ]

    SUBTAB_H = 22
    TAB_ORDER = ["general", "overview", "temporal", "location", "relations", "simulation", "media"]
    DATASET_TAB_ORDER = {
        "ideas": ["general", "overview", "temporal", "location", "relations", "media"],
        "cladistics": ["general", "overview", "phylogeny", "relations", "temporal", "location", "media"],
        "species": ["general", "overview", "phylogeny", "relations", "temporal", "location", "simulation", "media"],
        "components": ["general", "overview", "temporal", "location", "relations", "operational", "simulation", "media"],
        "producers": ["general", "overview", "production", "temporal", "location", "relations", "media"],
        "jobs": ["general", "overview", "temporal", "location", "relations", "media"],
        "employments": ["general", "overview", "temporal", "location", "relations", "media"],
    }
    TAB_LABELS = {
        "general": "General",
        "overview": "Overview",
        "production": "Production",
        "site": "Site",
        "temporal": "Temporal",
        "location": "Location",
        "relations": "Relations",
        "extant": "Extant",
        "phylogeny": "Phylogeny",
        "simulation": "Simulation",
        "operational": "Operational",
        "media": "Media",
    }
    SIMULATION_SUBTAB_ORDER = ["orbital", "map", "world_gen", "materials", "plant_ecology", "data"]
    PERSON_SIMULATION_SUBTAB_ORDER = ["quotes", "data"]
    SIMULATION_SUBTAB_LABELS = {
        "orbital": "Orbital",
        "map": "Map Sim",
        "world_gen": "World Gen",
        "materials": "Materials",
        "plant_ecology": "Plant Eco",
        "quotes": "Quotes",
        "data": "Data",
    }
    PERSON_QUOTE_FIELD = "person_quotes"
    PERSON_CONVERSATION_FIELD = "person_conversations"
    PERSON_QUOTE_TEXT_FIELD = "person_quote_draft_quote"
    PERSON_QUOTE_DATE_FIELD = "person_quote_draft_date"
    PERSON_QUOTE_CONTEXT_FIELD = "person_quote_draft_context"
    PERSON_CONVERSATION_SPEAKER_FIELD = "person_conversation_draft_speaker"
    PERSON_CONVERSATION_DATE_FIELD = "person_conversation_draft_date"
    PERSON_CONVERSATION_MESSAGE_FIELD = "person_conversation_draft_message"
    PERSON_QUOTE_INPUT_FIELDS = (
        PERSON_QUOTE_TEXT_FIELD,
        PERSON_QUOTE_DATE_FIELD,
        PERSON_QUOTE_CONTEXT_FIELD,
        PERSON_CONVERSATION_SPEAKER_FIELD,
        PERSON_CONVERSATION_DATE_FIELD,
        PERSON_CONVERSATION_MESSAGE_FIELD,
    )
    PERSON_QUOTE_FIELD_LABELS = {
        PERSON_QUOTE_TEXT_FIELD: "Quote",
        PERSON_QUOTE_DATE_FIELD: "Date",
        PERSON_QUOTE_CONTEXT_FIELD: "Context",
        PERSON_CONVERSATION_SPEAKER_FIELD: "Speaker",
        PERSON_CONVERSATION_DATE_FIELD: "Date",
        PERSON_CONVERSATION_MESSAGE_FIELD: "Message",
    }
    TAB_SECTIONS = {
        "general": [],
        "overview": ["Identity", "Classification", "Dimensions / Scale", "Metadata"],
        "production": [],
        "temporal": ["Temporal"],
        "location": [],
        "relations": ["Relations", "Class Relations", "Biosphere Species Roster"],
        "extant": [],
        "operational": ["Operational"],
        "simulation": [],
        "media": ["Media"],
    }
    SIMULATION_SUBTAB_SECTIONS = {
        "orbital": ["Simulation / Orbital"],
        "map": ["Simulation / Map Sim"],
        "world_gen": ["Simulation / World Gen"],
        "materials": ["Simulation / Materials"],
        "plant_ecology": ["Simulation / Plant Ecology"],
        "data": ["Simulation / Data"],
    }
    TEMPORAL_FIELDS = {
        "year",
        "year_number",
        "start_year",
        "end_year",
        "snapshot_year",
        "effective_year",
        "temporal_periods",
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
    MATERIAL_SIM_FIELDS = {
        "natural_material_model",
        "natural_materials",
        "materials_summary",
        "material_heatmap_model",
        "surface_palette",
        "atmospheric_material_model",
        "atmospheric_materials",
        "primary_material",
        "secondary_materials",
        "primary_atmospheric_material",
        "secondary_atmospheric_materials",
        "natural_distribution_role",
        "worldgen_participation",
        "minimum_map_detail_level",
        "distribution_scale",
        "formation_category",
        "formation_process",
        "spatial_representation",
        "formation_requirements",
        "formation_contract_status",
    }
    PLANT_ECOLOGY_SIM_FIELDS = PLANT_TRAIT_FIELDS | {
        "plant_blueprint_ref",
        "plant_growth_snapshot_ref",
    }
    TOOLBELT_TOOL_DEFINITIONS = [
        {
            "match": {"materials", "material"},
            "tools": [
                {
                    "id": "material_map_color",
                    "kind": "color_picker",
                    "color_field": "geological_map_color",
                    "label": "Map Color",
                    "description": "Color used for this material on the Materials/Regions map layers.",
                },
            ],
        },
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
                {
                    "id": "person_character_editor",
                    "kind": "jump_to_character_tab",
                    "label": "Character Editor",
                    "description": "Jump to personality, knowledge, and motivation fields.",
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
                    "label": "Choose / Place Parent",
                    "description": "Choose a parent if needed, then open its map for placement.",
                    "action_id": "knowledge_place_location_on_parent",
                    "requires": "surface_location",
                },
            ],
        },
        {
            "match": {"species"},
            "tools": [
                {
                    "id": "species_visual_editor",
                    "label": "Species Editor",
                    "description": "Paste a temporary plant photo and tune live fields against mature side/top previews.",
                    "action_id": "launch_species_editor",
                    "requires": "plant_species",
                },
                {
                    "id": "species_sim_lab",
                    "label": "Species Sim Lab",
                    "description": "Open the individual, growth gallery, and forest diagnostic views.",
                    "action_id": "launch_species_sim",
                    "requires": "plant_species",
                },
                {
                    "id": "plant_asset_leaf",
                    "kind": "plant_asset_creator",
                    "asset_role": "leaf",
                    "label": "Create Leaf Sprite",
                    "description": "Create or reopen this species' reusable leaf module in Pixel Studio.",
                    "requires": "plant_species",
                },
                {
                    "id": "plant_asset_stem",
                    "kind": "plant_asset_creator",
                    "asset_role": "stem",
                    "label": "Create Stem Sprite",
                    "description": "Create or reopen the reusable stem section for this species.",
                    "requires": "plant_species",
                },
                {
                    "id": "plant_asset_branch",
                    "kind": "plant_asset_creator",
                    "asset_role": "branch",
                    "label": "Create Branch Sprite",
                    "description": "Create or reopen the reusable branch section for this species.",
                    "requires": "plant_species",
                },
                {
                    "id": "plant_asset_flower",
                    "kind": "plant_asset_creator",
                    "asset_role": "flower",
                    "label": "Create Flower Sprite",
                    "description": "Create or reopen this species' reusable flower module.",
                    "requires": "plant_species",
                },
                {
                    "id": "plant_asset_fruit",
                    "kind": "plant_asset_creator",
                    "asset_role": "fruit",
                    "label": "Create Fruit Sprite",
                    "description": "Create or reopen this species' reusable fruit module.",
                    "requires": "plant_species",
                },
            ],
        },
    ]
    # Bound to WorldModel.schemas for normal cards. Keep the standalone
    # fallback lazy so importing this module does not decode the repository.
    SCHEMA_LOADER = None
    LAUNCH_AFFORDANCE_RESOLVER = LaunchAffordanceResolver()

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
            "Class Relations": False,
            "Biosphere Species Roster": False,
            "Simulation / Data": True,
            "Metadata": False,
            "Media": False,
            "Simulation / Orbital": False,
            "Simulation / Map Sim": False,
            "Simulation / World Gen": False,
            "Simulation / Materials": False,
            "Simulation / Data": False,
            "Phylogeny Parents": False,
            "Phylogeny Children": False,
            "Members": False,
        }

    def _is_idea_card(self):
        return self.dataset_name == "ideas" or self.entity.get("type") == "idea"

    def _is_person_card(self):
        return self.dataset_name in {"people", "persons"} or self.entity.get("type") == "person"

    def _is_period_card(self):
        return self.dataset_name == "periods" or self.entity.get("type") == "period"

    def _title_edit_field(self):
        return "common_name" if self._is_species_card() else "name"

    def _header_description_edit_field(self):
        return "three_word_description"

    def _header_description_text(self):
        return str(self.entity.get("three_word_description") or "").strip()

    def _tag_values(self):
        values = []
        for value in self.entity.get("tags") or []:
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)
        return values

    def _known_tag_values(self):
        tags = set()
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) if self.world_model is not None else {}
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            for value in entity.get("tags") or []:
                text = str(value or "").strip()
                if text:
                    tags.add(text)
            if entity.get("_dataset") == "tags" or entity.get("type") == "tag":
                label = str(entity.get("name") or entity.get("pretty_name") or entity.get("id") or "").strip()
                if label:
                    tags.add(label)
        return sorted(tags, key=lambda value: value.lower())

    def _tag_lookup_key(self, value):
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _tag_entity_for_value(self, tag_value):
        tag_key = self._tag_lookup_key(tag_value)
        if not tag_key:
            return None
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) if self.world_model is not None else {}
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            if entity.get("_dataset") != "tags" and entity.get("type") != "tag":
                continue
            candidates = {
                self._tag_lookup_key(entity.get("id")),
                self._tag_lookup_key(entity.get("name")),
                self._tag_lookup_key(entity.get("pretty_name")),
                self._tag_lookup_key(entity.get("common_name")),
            }
            expanded = set(candidates)
            expanded.update(value[4:] for value in candidates if value.startswith("tag_"))
            if tag_key in expanded:
                return entity
        return None

    def _tag_chip_colors(self, tag_value):
        tag_entity = self._tag_entity_for_value(tag_value)
        if not isinstance(tag_entity, dict):
            return (38, 52, 60), (102, 152, 166), (224, 238, 240)
        fill = self._coerce_hex_color(tag_entity.get("secondary_color"), fallback=(38, 52, 60))
        border = self._coerce_hex_color(tag_entity.get("primary_color"), fallback=(102, 152, 166))
        text = self._readable_text_color(fill)
        return fill, border, text

    def _tag_suggestions(self, query, limit=6):
        query = str(query or "").strip().lower()
        query_terms = [term for term in query.split() if term]
        current_tags = {tag.lower() for tag in self._tag_values()}
        suggestions = []
        for tag in self._known_tag_values():
            tag_l = tag.lower()
            if tag_l in current_tags:
                continue
            if query_terms and not all(term in tag_l for term in query_terms):
                continue
            suggestions.append(tag)
            if len(suggestions) >= limit:
                break
        return suggestions

    def _tag_search_query(self, card):
        return str(card.get("edit_buffer") or "").strip()

    def _tag_search_matches(self, card, limit=6):
        query = self._tag_search_query(card)
        return self._tag_suggestions(query, limit=limit)

    def _add_tag_value(self, card, tag_value):
        tag_value = str(tag_value or "").strip()
        if not tag_value:
            return False
        tags = self._tag_values()
        if tag_value.lower() not in {tag.lower() for tag in tags}:
            tags.append(tag_value)
            self.entity["tags"] = tags
        card["edit_buffer"] = ""
        card["edit_cursor"] = 0
        card["tag_selected_index"] = 0
        card["tag_keyboard_selection_active"] = False
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "tags"
        return True

    def confirm_tag_search(self, card):
        matches = self._tag_search_matches(card, limit=6)
        query = self._tag_search_query(card)
        tag_value = ""
        exact_match = next(
            (
                match for match in matches
                if self._tag_lookup_key(match) == self._tag_lookup_key(query)
            ),
            None,
        )
        if exact_match:
            tag_value = exact_match
        elif query and not card.get("tag_keyboard_selection_active"):
            tag_value = query
        elif matches:
            index = max(0, min(int(card.get("tag_selected_index", 0) or 0), len(matches) - 1))
            tag_value = matches[index]
        elif query:
            tag_value = query
        return self._add_tag_value(card, tag_value)

    def remove_tag_value(self, card, tag_value):
        tag_value = str(tag_value or "").strip()
        if not tag_value:
            return False
        tags = [tag for tag in self._tag_values() if tag.lower() != tag_value.lower()]
        self.entity["tags"] = tags
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "tags"
        return True

    def _tab_order(self):
        if self._is_idea_card():
            return self.DATASET_TAB_ORDER["ideas"]
        if self._is_component_card():
            order = self.DATASET_TAB_ORDER["components"]
        else:
            order = self.DATASET_TAB_ORDER.get(self.dataset_name, self.TAB_ORDER)
        if self._is_period_card() and "extant" not in order:
            insert_index = order.index("relations") if "relations" in order else len(order)
            order = list(order[:insert_index]) + ["extant"] + list(order[insert_index:])
        if self._is_site_card() and "site" not in order:
            insert_index = order.index("overview") + 1 if "overview" in order else 1
            order = list(order[:insert_index]) + ["site"] + list(order[insert_index:])
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
        allowed_subtabs = (
            self.PERSON_SIMULATION_SUBTAB_ORDER
            if self._is_person_card()
            else self.SIMULATION_SUBTAB_ORDER
        )
        if tab_name == "simulation" and subtab_name in allowed_subtabs:
            self.active_tab = tab_name
            self.active_simulation_subtab = subtab_name
            return True
        return False

    def _is_media_mode(self):
        return self.active_tab == "media"

    def _is_temporal_mode(self):
        return self.active_tab == "temporal"

    def _is_general_mode(self):
        return self.active_tab == "general"

    def _is_extant_mode(self):
        return self.active_tab == "extant" and self._is_period_card()

    def _period_extant_range(self):
        start_year = self._coerce_timeline_year(self.entity.get("start_year"))
        end_year = self._coerce_timeline_year(self.entity.get("end_year"))
        point_year = self._coerce_timeline_year(self.entity.get("year"))
        if start_year is None:
            start_year = point_year
        if end_year is None and point_year is not None:
            end_year = point_year
        if start_year is None:
            return None
        if end_year is None:
            end_year = start_year
        return min(start_year, end_year), max(start_year, end_year)

    def _period_scope_parent_ids(self):
        parent_ids = self._relation_entity_ids(self.entity.get("scope_parent"))
        for parent_id in self._relation_entity_ids(self.entity.get("parents")):
            parent = self.world_model.get_entity(parent_id) if self.world_model is not None else None
            if isinstance(parent, dict) and parent.get("type") != "period" and parent.get("_dataset") != "periods":
                if parent_id not in parent_ids:
                    parent_ids.append(parent_id)
        return parent_ids

    def _period_scope_entity_ids(self):
        if self.world_model is None:
            return set()
        scope_ids = set(self._period_scope_parent_ids())
        if not scope_ids:
            return set()

        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        allowed_ids = set()

        visited_offspring = set()

        def add_offspring(nodes):
            for node in nodes or []:
                if isinstance(node, str):
                    entity_id = node
                    children = []
                elif isinstance(node, dict):
                    entity_id = str(node.get("id") or node.get("entity_id") or "").strip()
                    children = node.get("offspring") or []
                else:
                    continue
                if not entity_id or entity_id in visited_offspring:
                    continue
                visited_offspring.add(entity_id)
                if entity_id and entity_id not in scope_ids:
                    allowed_ids.add(entity_id)
                add_offspring(children)

        for scope_id in scope_ids:
            scope = entities.get(scope_id)
            if isinstance(scope, dict):
                add_offspring(scope.get("offspring") or [])
            get_neighbors = getattr(self.world_model, "get_neighbors", None)
            if callable(get_neighbors):
                allowed_ids.update(
                    entity_id
                    for entity_id in get_neighbors(scope_id)
                    if entity_id not in scope_ids
                )

        # Keep scoped cards useful even when offspring has not yet been
        # materialized after an edit.
        for entity_id, candidate in entities.items():
            if not isinstance(candidate, dict) or entity_id in scope_ids:
                continue
            if scope_ids.intersection(self._relation_entity_ids(candidate.get("parents"))):
                allowed_ids.add(entity_id)
        return allowed_ids

    def _entity_is_extant_in_period(self, entity, period_range):
        if not isinstance(entity, dict) or period_range is None:
            return False
        period_start, period_end = period_range
        start_year = self._coerce_timeline_year(entity.get("start_year"))
        end_year = self._coerce_timeline_year(entity.get("end_year"))
        point_year = self._coerce_timeline_year(entity.get("year"))
        if point_year is None:
            point_year = self._coerce_timeline_year(entity.get("year_number"))
        if point_year is None:
            point_year = self._coerce_timeline_year(entity.get("effective_year"))

        if start_year is not None and end_year is not None:
            entity_start, entity_end = min(start_year, end_year), max(start_year, end_year)
            return entity_start <= period_end and entity_end >= period_start
        if start_year is not None:
            return start_year <= period_end
        if end_year is not None:
            return end_year >= period_start
        if point_year is not None:
            return period_start <= point_year <= period_end
        return False

    def _extant_entries(self):
        if self.world_model is None:
            return []
        period_range = self._period_extant_range()
        if period_range is None:
            return []
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        scoped_ids = self._period_scope_entity_ids()
        is_scoped = bool(self._period_scope_parent_ids())
        rows = []
        for entity_id, entity in entities.items():
            if not isinstance(entity, dict) or entity_id == self.entity.get("id"):
                continue
            dataset_name = str(entity.get("_dataset") or entity.get("type") or "entries")
            if dataset_name in {"schemas", "periods"} or entity.get("type") in {"schema", "period"}:
                continue
            if is_scoped and entity_id not in scoped_ids:
                continue
            if not self._entity_is_extant_in_period(entity, period_range):
                continue
            rows.append(entity)
        rows.sort(
            key=lambda entity: (
                str(entity.get("_dataset") or entity.get("type") or "entries").lower(),
                self._entity_display_label(entity).lower(),
                str(entity.get("id") or ""),
            )
        )
        return rows

    def _uses_image_block(self):
        return self._is_media_mode() or self._is_temporal_mode()

    def _relation_entity_ids(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        if isinstance(value, dict):
            candidate = value.get("id") or value.get("entity_id") or value.get("target") or value.get("location_id")
            return [str(candidate)] if candidate else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                ids.extend(self._relation_entity_ids(item))
            return ids
        return []

    def _entity_label_for_id(self, entity_id):
        entity_id = str(entity_id or "").strip()
        entity = self.world_model.get_entity(entity_id) if self.world_model is not None and entity_id else None
        if isinstance(entity, dict):
            return self._entity_display_label(entity)
        return entity_id

    def _field_spec(self, field_key):
        return self._normalize_field_spec(self._get_schema_field_specs().get(field_key, {}))

    def _normalize_field_spec(self, spec):
        if isinstance(spec, dict):
            return spec
        if isinstance(spec, str):
            return {"type": spec}
        return {}

    def is_relation_edit_field(self, field_key):
        if self.is_location_topology_relation_field(field_key):
            return True
        if field_key in {"biosphere_species_collection", "biosphere_location"}:
            return True
        if field_key in self.CORE_RELATION_FIELDS:
            return True
        spec = self._field_spec(field_key)
        field_type = str(spec.get("type", "")).lower()
        target = str(spec.get("target", "")).strip()
        if target:
            return True
        return "entity" in field_type or field_type in {"idea", "idea_list"}

    def _relation_field_allows_many(self, field_key):
        if self.is_location_topology_relation_field(field_key):
            return True
        if field_key in self.CORE_RELATION_FIELDS:
            return True
        field_type = str(self._field_spec(field_key).get("type", "")).lower()
        return "list" in field_type

    def _relation_field_target(self, field_key):
        if self.is_location_topology_relation_field(field_key):
            return "locations"
        if field_key == "biosphere_species_collection":
            return "collections"
        if field_key == "biosphere_location":
            return "locations"
        if field_key in self.CORE_RELATION_FIELDS:
            return "entity_core"
        spec = self._field_spec(field_key)
        target = spec.get("target", "")
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

    def _relation_target_options(self, target):
        if isinstance(target, (list, tuple, set)):
            return [
                str(candidate).strip()
                for candidate in target
                if str(candidate).strip()
            ]

        target_text = str(target or "").strip()
        if not target_text:
            return []

        for delimiter in ("|", ","):
            if delimiter in target_text:
                return [
                    candidate.strip()
                    for candidate in target_text.split(delimiter)
                    if candidate.strip()
                ]

        return [target_text]

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

    def _relation_target_label(self, target):
        options = self._relation_target_options(target)
        if len(options) > 1:
            labels = [option.replace("_", " ") for option in options]
            if len(labels) == 2:
                return " or ".join(labels)
            return f"{', '.join(labels[:-1])}, or {labels[-1]}"

        normalized = str(options[0] if options else "").strip().lower()
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

    def _launch_mode_options(self):
        return self.LAUNCH_AFFORDANCE_RESOLVER.options_for_entity(
            self.entity, getattr(self.world_model, "plant_catalogue", None))

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

        if requirement == "plant_species":
            from simulations.species.plant_assets import is_plant_species_entity
            return is_plant_species_entity(self.entity, getattr(self.world_model,"plant_catalogue",None))

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

    def _card_color_hex(self, role="body", section_id=None, color_field=None):
        if color_field:
            value = str(self.entity.get(color_field) or "").strip()
            return value if value else "#7a7e7c"
        role = str(role or "body").strip().lower()
        if role == "header":
            value = str(self.entity.get("card_header_color") or "").strip()
            if value:
                return value
            return self._card_color_hex("body")
        if role in {"wiki", "wiki_alt"}:
            section_id = str(section_id or "").strip()
            colors = self._wiki_field_colors()
            color_key = "alternate" if role == "wiki_alt" else section_id
            value = str(colors.get(color_key) or colors.get("default") or "").strip()
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

    def _card_hsv(self, role="body", section_id=None, color_field=None):
        red, green, blue = self._card_background_color(role=role, section_id=section_id, color_field=color_field)
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

    def _card_background_color(self, role="body", section_id=None, color_field=None):
        return self._coerce_hex_color(
            self._card_color_hex(role=role, section_id=section_id, color_field=color_field),
            fallback=(28, 30, 38),
        )

    def _card_button_palette(self, index=0, selected=False):
        role = "wiki" if int(index or 0) % 2 == 0 else "wiki_alt"
        fill = self._card_background_color(role=role)
        text_color = self._readable_text_color(fill)
        if selected:
            fill = self._mix_color(fill, text_color, 0.16)
            text_color = self._readable_text_color(fill)
            border = self._mix_color(fill, text_color, 0.58)
        else:
            border = self._mix_color(fill, text_color, 0.34)
        return fill, border, text_color

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

    def _working_year_wiki_stub(self, card=None):
        if card is None:
            return ""
        year_range = self._timeline_snapshot_range(card)
        if year_range is None:
            return ""
        start_year, end_year = year_range
        title = str(card.get("title") or self._location_display_label(self.entity, fallback=self.entity.get("id"))).strip()
        if not title:
            return ""
        if start_year == end_year:
            return f"{title} in the Year {start_year}"
        return f"{title} in the Period {start_year} - {end_year}"

    def _timeline_snapshot_range(self, card=None):
        if card is None:
            return None
        # The card's launch/lifespan year is not an active wiki-history filter.
        # Dated overview text follows the repository working year, or an
        # explicitly selected history chip. With neither, all entries display.
        year_range = card.get("working_year_range") or card.get("active_timeline_snapshot_range")
        if not isinstance(year_range, (list, tuple)) or len(year_range) != 2:
            return None
        try:
            start_year = int(year_range[0])
            end_year = int(year_range[1])
        except (TypeError, ValueError):
            return None
        if end_year < start_year:
            start_year, end_year = end_year, start_year
        return start_year, end_year

    def _timeline_snapshot_draft_key(self, card=None, year_range=None):
        if year_range is None:
            year_range = self._timeline_snapshot_range(card)
        if not isinstance(year_range, (list, tuple)) or len(year_range) != 2:
            return self.TIMELINE_SNAPSHOT_FIELD
        try:
            start_year = int(year_range[0])
            end_year = int(year_range[1])
        except (TypeError, ValueError):
            return self.TIMELINE_SNAPSHOT_FIELD
        if end_year < start_year:
            start_year, end_year = end_year, start_year
        return f"{self.TIMELINE_SNAPSHOT_FIELD}:{start_year}:{end_year}"

    def _timeline_snapshot_draft_buffer(self, card=None, year_range=None):
        if card is None:
            return None
        draft_buffers = card.get("draft_edit_buffers")
        if not isinstance(draft_buffers, dict):
            return None
        draft_key = self._timeline_snapshot_draft_key(card, year_range=year_range)
        draft = draft_buffers.get(draft_key)
        if isinstance(draft, dict) and "text" in draft:
            return draft
        legacy_draft = draft_buffers.get(self.TIMELINE_SNAPSHOT_FIELD)
        if isinstance(legacy_draft, dict) and "text" in legacy_draft:
            return legacy_draft
        return None

    def _has_timeline_snapshot_draft(self, card=None, year_range=None):
        return self._timeline_snapshot_draft_buffer(card, year_range=year_range) is not None

    def _load_timeline_snapshot_edit_buffer(self, card):
        year_range = self._timeline_snapshot_range(card)
        draft_key = self._timeline_snapshot_draft_key(card, year_range=year_range)
        card["active_timeline_snapshot_draft_key"] = draft_key
        card["timeline_snapshot_edit_range"] = year_range
        draft_buffer = self._timeline_snapshot_draft_buffer(card, year_range=year_range)
        if isinstance(draft_buffer, dict) and "text" in draft_buffer:
            card["edit_buffer"] = str(draft_buffer.get("text", ""))
            card["edit_cursor"] = int(draft_buffer.get("cursor", len(card["edit_buffer"])))
            self._clamp_edit_cursor(card)
            return True

        card["edit_buffer"] = self._saved_timeline_snapshot_text(card)
        card["edit_cursor"] = len(card["edit_buffer"])
        return True

    def _sync_timeline_snapshot_edit_range(self, card):
        if not isinstance(card, dict):
            return False
        if card.get("active_edit_field") != self.TIMELINE_SNAPSHOT_FIELD:
            return False
        current_key = self._timeline_snapshot_draft_key(card)
        active_key = card.get("active_timeline_snapshot_draft_key") or current_key
        if active_key == current_key:
            return False

        draft_buffers = card.setdefault("draft_edit_buffers", {})
        draft_buffers[active_key] = {
            "text": card.get("edit_buffer", ""),
            "cursor": int(card.get("edit_cursor", 0)),
        }
        self._load_timeline_snapshot_edit_buffer(card)
        card["last_edit_action"] = "draft"
        return True

    def _timeline_snapshot_entries(self):
        raw_entries = self.entity.get("timeline_snapshots")
        if isinstance(raw_entries, dict):
            entries = []
            for key, value in raw_entries.items():
                parts = str(key).split("-", 1)
                try:
                    start_year = int(parts[0])
                    end_year = int(parts[1]) if len(parts) > 1 else start_year
                except (TypeError, ValueError):
                    continue
                entries.append({"start_year": start_year, "end_year": end_year, "wiki_entry": str(value or "")})
            return entries
        if isinstance(raw_entries, list):
            return [entry for entry in raw_entries if isinstance(entry, dict)]
        return []

    def _timeline_snapshot_display_entries(self, card=None):
        entries = []
        for entry in self._timeline_snapshot_entries():
            try:
                start_year = int(entry.get("start_year"))
                end_year = int(entry.get("end_year", start_year))
            except (TypeError, ValueError):
                continue
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            entries.append(
                {
                    "start_year": start_year,
                    "end_year": end_year,
                    "wiki_entry": str(entry.get("wiki_entry") or ""),
                }
            )
        entries.sort(key=lambda item: (item["start_year"], item["end_year"]))

        active_range = self._timeline_snapshot_range(card)
        if active_range is None:
            return entries

        start_year, end_year = active_range
        text = self._timeline_snapshot_text(card)
        return [{
            "start_year": start_year,
            "end_year": end_year,
            "wiki_entry": text,
            "active": True,
        }]

    @staticmethod
    def _timeline_snapshot_period_label(entry):
        start_year = int(entry.get("start_year", 0))
        end_year = int(entry.get("end_year", start_year))
        return str(start_year) if start_year == end_year else f"{start_year}–{end_year}"

    def _measure_timeline_snapshot_blocks_height(self, card, font, width):
        blocks = self._timeline_snapshot_display_entries(card)
        if not blocks:
            return 0
        content_rect = pygame.Rect(0, 0, max(20, int(width) - 12), 0)
        total = 6
        for block in blocks:
            content_height = CardWikiRenderer.measure_content(
                block.get("wiki_entry", ""),
                font,
                content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
            )
            total += 22 + max(24, content_height) + 8
        return total

    def _timeline_snapshot_timeline_entries(self):
        entries = []
        seen = set()
        for entry in self._timeline_snapshot_entries():
            try:
                start_year = int(entry.get("start_year"))
                end_year = int(entry.get("end_year", start_year))
            except (TypeError, ValueError):
                continue
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            key = (start_year, end_year)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"start_year": start_year, "end_year": end_year})
        return sorted(entries, key=lambda item: (item["start_year"], item["end_year"]))

    def _timeline_snapshot_chip_lane_count(self, card, font, width):
        entries = self._timeline_snapshot_timeline_entries()
        if not entries or font is None:
            return 0
        available = max(48, int(width) - 40)
        lanes = 1
        used = 0
        for entry in entries:
            chip_w = max(44, font.size(self._timeline_snapshot_period_label(entry))[0] + 16)
            required = chip_w if used == 0 else chip_w + 5
            if used and used + required > available:
                lanes += 1
                used = chip_w
            else:
                used += required
        return lanes

    def _timeline_snapshot_text(self, card=None):
        if card is not None:
            self._sync_timeline_snapshot_edit_range(card)
        if card is not None and card.get("is_edit_mode", False) and card.get("active_edit_field") == self.TIMELINE_SNAPSHOT_FIELD:
            return card.get("edit_buffer", "")
        if card is not None:
            draft_buffer = self._timeline_snapshot_draft_buffer(card)
            if isinstance(draft_buffer, dict) and "text" in draft_buffer:
                return str(draft_buffer.get("text", ""))
        return self._saved_timeline_snapshot_text(card)

    def _saved_timeline_snapshot_text(self, card=None):
        year_range = self._timeline_snapshot_range(card)
        if year_range is None:
            return ""
        start_year, end_year = year_range
        for entry in self._timeline_snapshot_entries():
            try:
                entry_start = int(entry.get("start_year"))
                entry_end = int(entry.get("end_year", entry_start))
            except (TypeError, ValueError):
                continue
            if entry_start == start_year and entry_end == end_year:
                text = str(entry.get("wiki_entry") or "")
                return text if text.strip() else self._working_year_wiki_stub(card)
        return self._working_year_wiki_stub(card)

    def _set_timeline_snapshot_text(self, card, text):
        year_range = self._timeline_snapshot_range(card)
        if year_range is None:
            return False
        start_year, end_year = year_range
        entries = []
        replaced = False
        for entry in self._timeline_snapshot_entries():
            try:
                entry_start = int(entry.get("start_year"))
                entry_end = int(entry.get("end_year", entry_start))
            except (TypeError, ValueError):
                continue
            normalized = dict(entry)
            if entry_start == start_year and entry_end == end_year:
                normalized["start_year"] = start_year
                normalized["end_year"] = end_year
                normalized["wiki_entry"] = str(text or "")
                replaced = True
            entries.append(normalized)
        if not replaced:
            entries.append(
                {
                    "start_year": start_year,
                    "end_year": end_year,
                    "wiki_entry": str(text or ""),
                }
            )
        self.entity["timeline_snapshots"] = entries
        return True

    def _snapshot_link_refs(self, text):
        refs = []
        for match in re.finditer(r"\[\[([^\]]+)\]\]", str(text or "")):
            ref = match.group(1).split("|", 1)[0].strip()
            if ref:
                refs.append(ref)
        return refs

    def _apply_snapshot_year_to_mentions(self, snapshot_year, text):
        try:
            snapshot_year = int(snapshot_year)
        except (TypeError, ValueError):
            return False

        touched = False
        self.entity["snapshot_year"] = snapshot_year
        touched = True
        if self.world_model is None:
            return touched

        own_id = str(self.entity.get("id") or "").strip()
        for ref in self._snapshot_link_refs(text):
            if ref == own_id:
                continue
            linked_entity = self.world_model.get_entity(ref)
            if isinstance(linked_entity, dict):
                linked_entity["snapshot_year"] = snapshot_year
                touched = True
        return touched

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

    def _entity_existence_period(self):
        """Return the explicit inclusive lifespan, never an inferred point year."""
        start_year = self._coerce_timeline_year(self.entity.get("start_year"))
        end_year = self._coerce_timeline_year(self.entity.get("end_year"))
        if start_year is None or end_year is None:
            return None
        return (min(start_year, end_year), max(start_year, end_year))

    def _card_timeline_range(self, card):
        years = [
            self._coerce_timeline_year(year)
            for year in card.get("years", [])
        ]
        years = [year for year in years if year is not None]
        for entry in self._timeline_snapshot_timeline_entries():
            years.extend((entry["start_year"], entry["end_year"]))
        if not years:
            for period in self._temporal_period_entries():
                for key in ("start_year", "end_year"):
                    year = self._coerce_period_year(period.get(key))
                    if year is not None:
                        years.append(year)
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

    def _timeline_year_commentaries(self):
        commentaries = {}
        for field_key, year_key, label in (
            ("start_commentary", "start_year", "Start"),
            ("start_event", "start_year", "Start"),
            ("end_commentary", "end_year", "End"),
            ("end_event", "end_year", "End"),
        ):
            text = str(self.entity.get(field_key) or "").strip()
            year = self._coerce_timeline_year(self.entity.get(year_key))
            if not text or year is None:
                continue
            rendered = f"{label}: {text}"
            commentaries.setdefault(year, [])
            if rendered not in commentaries[year]:
                commentaries[year].append(rendered)
        return commentaries

    def _temporal_period_timeline_entries(self, card=None):
        card_range = self._card_timeline_range(card or {})
        entries = []
        for period in self._temporal_period_entries():
            start_year = self._coerce_period_year(period.get("start_year"))
            end_year = self._coerce_period_year(period.get("end_year"))
            if start_year is None and end_year is None:
                continue
            if start_year is None:
                start_year = end_year
            if end_year is None:
                end_year = start_year
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            if card_range is not None and (end_year < card_range[0] or start_year > card_range[1]):
                continue
            entry = {
                "label": str(period.get("label") or "Period"),
                "start_year": start_year,
                "end_year": end_year,
                "commentary": str(period.get("commentary") or "").strip(),
            }
            predecessor = str(period.get("predecessor") or "").strip()
            successor = str(period.get("successor") or "").strip()
            if predecessor:
                entry["predecessor"] = predecessor
            if successor:
                entry["successor"] = successor
            entries.append(entry)
        entries.sort(key=lambda entry: (entry["start_year"], entry["end_year"], entry["label"].lower()))
        return entries

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

    def _active_schema_loader(self):
        shared_loader = getattr(self.world_model, "schemas", None) if self.world_model is not None else None
        if shared_loader is not None:
            return shared_loader
        if EntityCard.SCHEMA_LOADER is None:
            EntityCard.SCHEMA_LOADER = SchemaLoader()
        return EntityCard.SCHEMA_LOADER

    def _resolve_schema(self):
        schema_loader = self._active_schema_loader()
        for schema_name in self._schema_name_candidates():
            schema = schema_loader.get_schema(schema_name)
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
        extends_value = schema.get("extends")
        extends_names = (
            list(extends_value)
            if isinstance(extends_value, (list, tuple, set))
            else [extends_value]
        )
        for extends_name in extends_names:
            if not extends_name:
                continue
            parent_schema = self._active_schema_loader().get_schema(str(extends_name))
            combined.update(self._collect_schema_fields(parent_schema, seen=set(seen)))

        mixins_value = schema.get("mixins") or []
        mixin_names = (
            list(mixins_value)
            if isinstance(mixins_value, (list, tuple, set))
            else [mixins_value]
        )
        for mixin_name in mixin_names:
            if not mixin_name:
                continue
            mixin_schema = self._active_schema_loader().get_schema(str(mixin_name))
            combined.update(self._collect_schema_fields(mixin_schema, seen=set(seen)))

        combined.update(schema.get("fields", {}))
        return combined

    def _get_schema_field_specs(self):
        schema = self._resolve_schema()
        field_specs = self._collect_schema_fields(schema)
        entity_mixins = self.entity.get("schema_mixins") or []
        if not isinstance(entity_mixins, (list, tuple, set)):
            entity_mixins = [entity_mixins]
        for mixin_name in entity_mixins:
            if not mixin_name:
                continue
            mixin_schema = self._active_schema_loader().get_schema(str(mixin_name))
            field_specs.update(self._collect_schema_fields(mixin_schema))
        if self._is_idea_card():
            return {
                key: value
                for key, value in field_specs.items()
                if key in self.IDEA_GENERIC_FIELDS
            }
        return field_specs

    def _is_scalar_schema_type(self, field_type):
        return field_type in {None, "string", "number", "text"}

    def _is_controlled_choice_field(self, field_key):
        return self._is_species_card() and field_key in ({
            PLANT_GROWTH_FORM_FIELD,
            PLANT_GROWTH_BEHAVIOUR_FIELD,
            PLANT_LIFESPAN_FIELD,
            PLANT_LIFE_CYCLE_FIELD,
        } | PLANT_TRAIT_DROPDOWN_FIELDS)

    def controlled_choice_rows(self, field_key):
        if not self._is_controlled_choice_field(field_key):
            return []
        return controlled_plant_field_rows(field_key)

    def controlled_choice_display_label(self, field_key, value):
        if self._is_controlled_choice_field(field_key):
            return controlled_plant_field_display_label(field_key, value)
        return str(value or "")

    def _species_field_resolution(self, field_key, value=None):
        if value is None:
            value = self.entity.get(field_key)
        if not is_inheritable_species_field(field_key):
            return {"value": value, "provenance": "authored"}
        inferred = self.entity.get(INFERRED_FIELDS_KEY)
        if isinstance(inferred, dict) and field_key in inferred:
            marker = inferred.get(field_key) or {}
            return {
                "value": value,
                "provenance": "inferred",
                "source_ids": marker.get("source_ids", []) if isinstance(marker, dict) else [],
            }
        if not self._is_species_card():
            return {"value": value, "provenance": "authored"}
        if self.world_model is None or not getattr(self.world_model, "loader", None):
            return {"value": value, "provenance": "authored" if value not in (None, "", [], {}) else "unknown"}
        return resolve_species_field(self.world_model.loader, self.entity, field_key)

    def _species_field_value(self, field_key, value=None):
        resolution = self._species_field_resolution(field_key, value)
        resolved_value = resolution.get("value")
        return resolved_value, resolution.get("provenance", "unknown"), resolution.get("source_ids", [])

    def select_controlled_choice(self, card, choice_index):
        field_key = card.get("active_edit_field")
        if not self._is_controlled_choice_field(field_key):
            return False
        choices = self.controlled_choice_rows(field_key)
        if not isinstance(choice_index, int) or not (0 <= choice_index < len(choices)):
            return False
        choice = choices[choice_index]
        if choice.get("kind") == "heading":
            return False
        card["choice_picker_selected_index"] = choice_index
        card["choice_picker_value"] = choice["value"]
        card["edit_buffer"] = choice["value"]
        card["last_edit_action"] = "draft"
        return True

    def _is_temporal_field(self, field_key, spec=None):
        if self._simulation_section_for_key(field_key):
            return False

        if field_key in {"start_event", "end_event", "temporal_periods"}:
            return True

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

    def _is_year_value_field(self, field_key):
        key = str(field_key or "").lower()
        return key in {"year", "year_number", "start_year", "end_year", "effective_year"} or key.endswith("_year")

    def _is_field_editable(self, field_key, value, schema_field_specs):
        if field_key == self.TIMELINE_SNAPSHOT_FIELD:
            return True
        if field_key == "temporal_periods":
            return True
        if field_key in {"name", "common_name"}:
            return True

        spec = self._normalize_field_spec(schema_field_specs.get(field_key, {}))
        field_type = spec.get("type")

        if field_type in {"entity", "entity_list", "string_list"}:
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
            "collection_class",
            "idea_class",
            "location_class",
        ]
        classification = []
        for key in classification_keys:
            if key in entity or key in schema_field_specs:
                classification.append((key, entity.get(key)))

        dims = [
            ("dimension_length_m", entity.get("dimension_length_m")),
            ("dimension_height_m", entity.get("dimension_height_m")),
            ("dimension_width_m", entity.get("dimension_width_m")),
            ("mass_kg", entity.get("mass_kg")),
            ("power_kw", entity.get("power_kw")),
        ]
        dims = [(key, value) for key, value in dims if key in entity or key in schema_field_specs]
        if self._is_space_sim_context():
            dims = [(key, value) for key, value in dims if key != "mass_kg"]
        overview_dims = [] if self._is_component_card() else dims

        relation_values = []
        class_relation_values = []
        state_values = []
        metadata_values = []
        operational_values = []
        temporal_values = []
        media_values = []
        space_sim_values = []
        map_sim_values = []
        world_gen_sim_values = []
        material_sim_values = []
        plant_ecology_sim_values = []
        biosphere_roster_values = []

        media_keys = self._media_field_keys()

        component_operational_keys = {
            "dimension_length_m",
            "dimension_height_m",
            "dimension_width_m",
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
            INFERRED_FIELDS_KEY, INFERENCE_CONFLICTS_KEY,
            self.PERSON_QUOTE_FIELD,
            self.PERSON_CONVERSATION_FIELD,
        }
        handled_keys.update(PLANT_LEGACY_FIELDS)
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
            raw_value = entity.get(key)
            value, _, _ = self._species_field_value(key, raw_value)

            if key in {
                "id", "pretty_name", "name", "common_name", "binomial_name", "type", "_dataset",
            }:
                continue

            if not self._is_location_field_relevant(key):
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
            if simulation_section == "Simulation / Materials":
                material_sim_values.append((key, value))
                continue
            if simulation_section == "Simulation / Plant Ecology":
                plant_ecology_sim_values.append((key, value))
                continue

            if self._is_temporal_field(key, spec):
                temporal_values.append((key, value))
                continue

            if section_name == "class relations":
                class_relation_values.append((key, value))
                continue

            if section_name == "biosphere species roster":
                biosphere_roster_values.append((key, value))
                continue

            if key in self.BIOSPHERE_ROSTER_SECTION_FIELDS:
                biosphere_roster_values.append((key, value))
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
            "Class Relations": class_relation_values,
            "Biosphere Species Roster": biosphere_roster_values,
            "Simulation / Data": state_values,
            "Metadata": metadata_values,
            "Media": media_values,
            "Simulation / Orbital": space_sim_values,
            "Simulation / Map Sim": map_sim_values,
            "Simulation / World Gen": world_gen_sim_values,
            "Simulation / Materials": material_sim_values,
            "Simulation / Plant Ecology": plant_ecology_sim_values,
            "Operational": dims + operational_values if self._is_component_card() else operational_values,
        }
        sections["Simulation / Space Sim"] = space_sim_values
        return sections

    def _is_temporal_period_entry(self, value):
        return isinstance(value, dict) and (
            "label" in value
            or "start_year" in value
            or "end_year" in value
            or "commentary" in value
        )

    def _coerce_period_year(self, value):
        if value in (None, ""):
            return None
        parsed = parse_year(value)
        if parsed is not None:
            return parsed
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_temporal_period(self, value):
        if not isinstance(value, dict):
            return None
        label = str(value.get("label") or value.get("name") or value.get("phase") or "Period").strip()
        start_year = self._coerce_period_year(value.get("start_year") if value.get("start_year") is not None else value.get("start"))
        end_year = self._coerce_period_year(value.get("end_year") if value.get("end_year") is not None else value.get("end"))
        commentary = str(value.get("commentary") or value.get("note") or value.get("description") or "").strip()
        if not label and start_year is None and end_year is None and not commentary:
            return None
        normalized = {"label": label or "Period"}
        if start_year is not None:
            normalized["start_year"] = start_year
        if end_year is not None:
            normalized["end_year"] = end_year
        if commentary:
            normalized["commentary"] = commentary
        predecessor = str(value.get("predecessor") or value.get("predecessor_id") or value.get("previous") or "").strip()
        successor = str(value.get("successor") or value.get("successor_id") or value.get("next") or "").strip()
        if predecessor:
            normalized["predecessor"] = predecessor
        if successor:
            normalized["successor"] = successor
        return normalized

    def _temporal_period_entries(self):
        entries = []
        for raw_entry in self.entity.get("temporal_periods") or []:
            entry = self._normalize_temporal_period(raw_entry)
            if entry is not None:
                entries.append(entry)
        return entries

    def _format_temporal_period_line(self, entry):
        entry = self._normalize_temporal_period(entry) or {"label": "Period"}
        label = str(entry.get("label") or "Period").strip()
        start_year = entry.get("start_year")
        end_year = entry.get("end_year")
        commentary = str(entry.get("commentary") or "").strip()
        descriptor = commentary or label or "Period"
        parts = [
            descriptor,
            "" if start_year is None else str(start_year),
            "" if end_year is None else str(end_year),
        ]
        predecessor = str(entry.get("predecessor") or "").strip()
        successor = str(entry.get("successor") or "").strip()
        if predecessor:
            parts.append(f"predecessor={predecessor}")
        if successor:
            parts.append(f"successor={successor}")
        return " | ".join(parts)

    def _split_temporal_period_line(self, text):
        parts = []
        current = []
        bracket_depth = 0
        index = 0
        text = str(text or "")
        while index < len(text):
            if text.startswith("[[", index):
                bracket_depth += 1
                current.append("[[")
                index += 2
                continue
            if text.startswith("]]", index) and bracket_depth:
                bracket_depth -= 1
                current.append("]]")
                index += 2
                continue
            character = text[index]
            if character == "|" and bracket_depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(character)
            index += 1
        parts.append("".join(current).strip())
        return parts

    def _parse_temporal_period_line(self, line):
        text = str(line or "").strip()
        if not text:
            return None
        parts = self._split_temporal_period_line(text)
        head = parts[0]
        commentary = " | ".join(part for part in parts[1:] if part).strip()

        label = ""
        date_text = ""
        predecessor = ""
        successor = ""
        if len(parts) >= 3:
            label = "Period"
            commentary = head
            start_year = self._coerce_period_year(parts[1])
            end_year = self._coerce_period_year(parts[2])
            for extra in parts[3:]:
                key, _, value = extra.partition("=")
                key = key.strip().lower()
                value = value.strip()
                if key in {"predecessor", "previous", "prev"}:
                    predecessor = value
                elif key in {"successor", "next"}:
                    successor = value
            entry = {"label": label}
            if start_year is not None:
                entry["start_year"] = start_year
            if end_year is not None:
                entry["end_year"] = end_year
            if commentary:
                entry["commentary"] = commentary
            if predecessor:
                entry["predecessor"] = predecessor
            if successor:
                entry["successor"] = successor
            return entry

        if ":" in head:
            label, date_text = [part.strip() for part in head.split(":", 1)]
        elif len(parts) >= 2:
            label = head
            date_text = parts[1]
            commentary = " | ".join(part for part in parts[2:] if part).strip()
        else:
            label = head

        start_year = None
        end_year = None
        normalized_date = date_text.replace("to", "-")
        if normalized_date:
            if normalized_date.lower().startswith("until "):
                end_year = self._coerce_period_year(normalized_date[6:].strip())
            elif "-" in normalized_date:
                start_text, end_text = [part.strip() for part in normalized_date.split("-", 1)]
                start_year = self._coerce_period_year(start_text)
                end_year = self._coerce_period_year(end_text)
            else:
                start_year = self._coerce_period_year(normalized_date)
                end_year = start_year

        entry = {"label": label or "Period"}
        if start_year is not None:
            entry["start_year"] = start_year
        if end_year is not None:
            entry["end_year"] = end_year
        if commentary:
            entry["commentary"] = commentary
        if predecessor:
            entry["predecessor"] = predecessor
        if successor:
            entry["successor"] = successor
        return entry

    def _parse_temporal_periods(self, buffer_text):
        entries = []
        for line in str(buffer_text or "").splitlines():
            entry = self._parse_temporal_period_line(line)
            if entry is not None:
                entries.append(entry)
        return entries

    def timeline_year_from_period_click(self, card, mouse_x):
        context = card.get("temporal_period_click_context")
        if not isinstance(context, dict):
            return None
        try:
            left_x = int(context["left_x"])
            right_x = int(context["right_x"])
            start_year = int(context["start_year"])
            end_year = int(context["end_year"])
        except (KeyError, TypeError, ValueError):
            return None
        if right_x <= left_x:
            return start_year
        ratio = (int(mouse_x) - left_x) / float(right_x - left_x)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(start_year + ratio * (end_year - start_year)))

    def handle_temporal_period_timeline_click(self, card, mouse_pos):
        if not isinstance(card, dict) or not card.get("is_edit_mode", False):
            return None
        click_rect = card.get("temporal_period_click_rect")
        if click_rect is None or not click_rect.collidepoint(mouse_pos):
            return None

        clicked_year = self.timeline_year_from_period_click(card, mouse_pos[0])
        if clicked_year is None:
            return None

        pending_start = card.get("pending_temporal_period_start")
        if pending_start is None:
            card["pending_temporal_period_start"] = clicked_year
            card["timeline_period_status"] = f"Period start {clicked_year}"
            return "pending"

        try:
            start_year = int(pending_start)
        except (TypeError, ValueError):
            start_year = clicked_year
        end_year = clicked_year
        if end_year < start_year:
            start_year, end_year = end_year, start_year

        periods = self._temporal_period_entries()
        period_index = len(periods) + 1
        periods.append(
            {
                "label": f"Period {period_index}",
                "start_year": start_year,
                "end_year": end_year,
            }
        )
        self.entity["temporal_periods"] = periods
        card.pop("pending_temporal_period_start", None)
        card["timeline_period_status"] = f"Added Period {period_index}: {start_year}-{end_year}"
        if card.get("active_edit_field") == "temporal_periods":
            card["edit_buffer"] = self._format_value(periods)
            card["edit_cursor"] = len(card["edit_buffer"])
        card["last_edit_action"] = "commit"
        return "commit"

    def _format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            if value and all(isinstance(item, dict) and self._is_temporal_period_entry(item) for item in value):
                return "\n".join(self._format_temporal_period_line(item) for item in value)
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
            if value and all(isinstance(item, dict) and self._is_temporal_period_entry(item) for item in value):
                return "\n".join(self._format_temporal_period_line(item) for item in value)
            return "\n".join(str(item) for item in value)
        return str(value)

    def _initial_edit_buffer(self, field_key, value):
        if field_key == "tags":
            return ""
        if field_key == self.TIMELINE_SNAPSHOT_FIELD:
            return self._timeline_snapshot_text(value if isinstance(value, dict) else None)
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

    def _edit_selection_range(self, card):
        if "edit_selection_anchor" not in card:
            return None
        buffer_text = card.get("edit_buffer", "")
        anchor = TextEditing.clamp_cursor(buffer_text, card.get("edit_selection_anchor", 0))
        cursor = TextEditing.clamp_cursor(buffer_text, card.get("edit_cursor", anchor))
        if anchor == cursor:
            return None
        return (min(anchor, cursor), max(anchor, cursor))

    def _clear_edit_selection(self, card):
        card.pop("edit_selection_anchor", None)

    def _set_edit_selection(self, card, anchor, cursor):
        buffer_text = card.get("edit_buffer", "")
        anchor = TextEditing.clamp_cursor(buffer_text, anchor)
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        card["edit_cursor"] = cursor
        if anchor == cursor:
            self._clear_edit_selection(card)
        else:
            card["edit_selection_anchor"] = anchor

    def _delete_edit_selection(self, card):
        selection = self._edit_selection_range(card)
        if selection is None:
            return False
        start, end = selection
        buffer_text = card.get("edit_buffer", "")
        card["edit_buffer"] = buffer_text[:start] + buffer_text[end:]
        card["edit_cursor"] = start
        self._clear_edit_selection(card)
        return True

    def _set_edit_cursor(self, card, cursor):
        buffer_text = card.get("edit_buffer", "")
        card["edit_cursor"] = TextEditing.clamp_cursor(buffer_text, cursor)
        self._clear_edit_selection(card)

    def _insert_edit_text(self, card, text):
        if not text:
            return False

        self._delete_edit_selection(card)
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.insert_text(
            buffer_text,
            cursor,
            text,
        )
        return True

    def _delete_before_cursor(self, card):
        if self._delete_edit_selection(card):
            return True
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_before_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _delete_after_cursor(self, card):
        if self._delete_edit_selection(card):
            return True
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
        if self._delete_edit_selection(card):
            return True
        buffer_text = card.get("edit_buffer", "")
        cursor = self._clamp_edit_cursor(card)
        card["edit_buffer"], card["edit_cursor"] = TextEditing.delete_word_before_cursor(
            buffer_text,
            cursor,
        )
        return True

    def _delete_word_after_cursor(self, card):
        if self._delete_edit_selection(card):
            return True
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
        active_field = card.get("active_edit_field")
        if self._is_person_quote_wiki_field(active_field):
            general_rect = (card.get("person_quote_input_rects") or {}).get(active_field)
        else:
            general_rect = (
                card.get("timeline_snapshot_rect")
                if active_field == self.TIMELINE_SNAPSHOT_FIELD
                else card.get("general_content_rect")
            )
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

        if field_key == "temporal_periods":
            return self._parse_temporal_periods(text)

        if self._is_year_value_field(field_key):
            parsed_year = parse_year(text)
            if parsed_year is not None:
                return parsed_year
            if text.strip().lower() in {"", "none", "null"}:
                return None
            if isinstance(original_value, (int, float)) and not isinstance(original_value, bool):
                return original_value

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
            draft_key = field_key
            if field_key == self.TIMELINE_SNAPSHOT_FIELD:
                draft_key = card.get("active_timeline_snapshot_draft_key") or self._timeline_snapshot_draft_key(card)
            draft_buffers = card.setdefault("draft_edit_buffers", {})
            draft_buffers[draft_key] = {
                "text": card.get("edit_buffer", ""),
                "cursor": int(card.get("edit_cursor", 0)),
            }
            card["last_edit_action"] = "draft"

        card["is_edit_mode"] = not currently_enabled

        if not card["is_edit_mode"]:
            card["delete_confirm_active"] = False
            card["active_edit_field"] = None
            card["person_quote_active_field"] = None
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

    def _stash_active_edit_draft(self, card):
        field_key = card.get("active_edit_field")
        if not field_key:
            return False
        draft_key = field_key
        if field_key == self.TIMELINE_SNAPSHOT_FIELD:
            draft_key = card.get("active_timeline_snapshot_draft_key") or self._timeline_snapshot_draft_key(card)
        draft_buffers = card.setdefault("draft_edit_buffers", {})
        draft_buffers[draft_key] = {
            "text": card.get("edit_buffer", ""),
            "cursor": int(card.get("edit_cursor", 0)),
        }
        card["last_edit_action"] = "draft"
        return True

    def begin_edit_field(self, card, field_key):
        if not card.get("is_edit_mode", False):
            return False

        value = card if field_key == self.TIMELINE_SNAPSHOT_FIELD else self.entity.get(field_key)
        if field_key != self.TIMELINE_SNAPSHOT_FIELD:
            value = self._species_field_resolution(field_key, value).get("value")
        schema_field_specs = self._get_schema_field_specs()
        if not self._is_field_editable(field_key, value, schema_field_specs):
            return False

        active_field = card.get("active_edit_field")
        if active_field and active_field != field_key:
            self._stash_active_edit_draft(card)
        elif active_field == field_key:
            if field_key == self.TIMELINE_SNAPSHOT_FIELD:
                self._sync_timeline_snapshot_edit_range(card)
            return True

        card["active_edit_field"] = field_key
        card["edit_original_value"] = value
        card["choice_picker_open"] = self._is_controlled_choice_field(field_key)
        card["choice_picker_hitboxes"] = []
        card["choice_picker_value"] = value if self._is_controlled_choice_field(field_key) else None
        if field_key == "tags":
            card["tag_selected_index"] = 0
        self._clear_edit_preferred_column(card)
        if field_key == self.TIMELINE_SNAPSHOT_FIELD:
            return self._load_timeline_snapshot_edit_buffer(card)
        draft_buffer = card.get("draft_edit_buffers", {}).get(field_key)
        if isinstance(draft_buffer, dict) and "text" in draft_buffer:
            card["edit_buffer"] = str(draft_buffer.get("text", ""))
            card["edit_cursor"] = int(draft_buffer.get("cursor", len(card["edit_buffer"])))
            self._clamp_edit_cursor(card)
            return True

        card["edit_buffer"] = self._initial_edit_buffer(field_key, value)
        if self._is_controlled_choice_field(field_key):
            canonical = canonical_controlled_plant_value(field_key, value)
            card["edit_buffer"] = canonical
            choice_rows = self.controlled_choice_rows(field_key)
            card["choice_picker_selected_index"] = next(
                (
                    index
                    for index, row in enumerate(choice_rows)
                    if row.get("kind") != "heading" and row.get("value") == canonical
                ),
                next(
                    (
                        index
                        for index, row in enumerate(choice_rows)
                        if row.get("kind") != "heading"
                    ),
                    0,
                ),
            )
        card["edit_cursor"] = len(card["edit_buffer"])
        return True

    def commit_edit_field(self, card):
        field_key = card.get("active_edit_field")
        if not field_key:
            return False

        if self._is_person_quote_virtual_field(field_key):
            self._sync_active_person_quote_edit_buffer(card)
            card["active_edit_field"] = None
            card["person_quote_active_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None
            card["edit_cursor"] = 0
            self._clear_edit_preferred_column(card)
            card["last_edit_action"] = None
            return True

        if field_key == "tags":
            draft_buffers = card.get("draft_edit_buffers")
            if isinstance(draft_buffers, dict):
                draft_buffers.pop(field_key, None)
            card["active_edit_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None
            card["edit_cursor"] = 0
            card.pop("active_timeline_snapshot_draft_key", None)
            card.pop("timeline_snapshot_edit_range", None)
            card["tag_selected_index"] = 0
            self._clear_edit_preferred_column(card)
            card["last_edit_action"] = "commit"
            card["last_committed_field"] = "tags"
            return True

        if field_key == self.TIMELINE_SNAPSHOT_FIELD:
            self._sync_timeline_snapshot_edit_range(card)
            self._set_timeline_snapshot_text(card, card.get("edit_buffer", ""))
            draft_buffers = card.get("draft_edit_buffers")
            if isinstance(draft_buffers, dict):
                draft_buffers.pop(field_key, None)
                draft_buffers.pop(card.get("active_timeline_snapshot_draft_key") or self._timeline_snapshot_draft_key(card), None)
            card["active_edit_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None
            card["edit_cursor"] = 0
            card.pop("active_timeline_snapshot_draft_key", None)
            card.pop("timeline_snapshot_edit_range", None)
            self._clear_edit_preferred_column(card)
            card["last_edit_action"] = "commit"
            card["last_committed_field"] = "timeline_snapshots"
            return True

        original_value = card.get("edit_original_value", self.entity.get(field_key))
        if self._is_controlled_choice_field(field_key):
            new_value = card.get("choice_picker_value") or original_value
        else:
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
        card["choice_picker_open"] = False
        card["choice_picker_hitboxes"] = []
        card.pop("choice_picker_value", None)
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

        if self._is_person_quote_virtual_field(card.get("active_edit_field")):
            card["last_edit_action"] = "cancel"
            card["active_edit_field"] = None
            card["person_quote_active_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None
            card["edit_cursor"] = 0
            self._clear_edit_preferred_column(card)
            return True

        card["last_edit_action"] = "cancel"
        card.pop("edit_validation_message", None)
        card["active_edit_field"] = None
        card["choice_picker_open"] = False
        card["choice_picker_hitboxes"] = []
        card.pop("choice_picker_value", None)
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        card["edit_cursor"] = 0
        card.pop("active_timeline_snapshot_draft_key", None)
        card.pop("timeline_snapshot_edit_range", None)
        self._clear_edit_preferred_column(card)
        return True

    def handle_keydown(self, card, event):
        if not card.get("is_edit_mode", False):
            return False

        if self._handle_person_quote_keydown(card, event):
            return True

        if self._handle_production_keydown(card, event):
            return True

        if self._handle_location_keydown(card, event):
            return True

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

        if self._is_controlled_choice_field(active_field) and card.get("choice_picker_open", False):
            choice_rows = self.controlled_choice_rows(active_field)
            choice_indices = [
                index for index, row in enumerate(choice_rows) if row.get("kind") != "heading"
            ]
            if not choice_indices:
                return True
            selected_index = int(card.get("choice_picker_selected_index", choice_indices[0]))
            if selected_index not in choice_indices:
                selected_index = choice_indices[0]
            current_choice = choice_indices.index(selected_index)
            if event.key == pygame.K_UP:
                card["choice_picker_selected_index"] = choice_indices[max(0, current_choice - 1)]
                return True
            if event.key == pygame.K_DOWN:
                card["choice_picker_selected_index"] = choice_indices[min(len(choice_indices) - 1, current_choice + 1)]
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.select_controlled_choice(card, card["choice_picker_selected_index"]):
                    self.commit_edit_field(card)
                return True
            if event.key == pygame.K_ESCAPE:
                return self.cancel_edit_field(card)
            return True

        if event.key == pygame.K_a and (event.mod & pygame.KMOD_CTRL):
            self._clear_edit_preferred_column(card)
            self._set_edit_selection(card, 0, len(card.get("edit_buffer", "")))
            card["last_edit_action"] = "draft"
            return True

        if active_field in {"wiki_entry", self.TIMELINE_SNAPSHOT_FIELD} or self._is_person_quote_wiki_field(active_field):
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

        if active_field == "tags":
            matches = self._tag_search_matches(card, limit=6)
            if event.key == pygame.K_UP and matches:
                card["tag_selected_index"] = max(0, int(card.get("tag_selected_index", 0) or 0) - 1)
                card["tag_keyboard_selection_active"] = True
                return True
            if event.key == pygame.K_DOWN and matches:
                card["tag_selected_index"] = min(len(matches) - 1, int(card.get("tag_selected_index", 0) or 0) + 1)
                card["tag_keyboard_selection_active"] = True
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self.confirm_tag_search(card)

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
            if active_field in {"wiki_entry", self.TIMELINE_SNAPSHOT_FIELD} and not (event.mod & pygame.KMOD_CTRL):
                self._set_edit_cursor(card, self._line_start_before_cursor(card.get("edit_buffer", ""), self._clamp_edit_cursor(card)))
            else:
                self._set_edit_cursor(card, 0)
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_END:
            self._clear_edit_preferred_column(card)
            if active_field in {"wiki_entry", self.TIMELINE_SNAPSHOT_FIELD} and not (event.mod & pygame.KMOD_CTRL):
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
            if active_field == "tags":
                card["tag_selected_index"] = 0
                card["tag_keyboard_selection_active"] = False
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_DELETE:
            self._clear_edit_preferred_column(card)
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_after_cursor(card)
            else:
                self._delete_after_cursor(card)
            if active_field == "tags":
                card["tag_selected_index"] = 0
                card["tag_keyboard_selection_active"] = False
            card["last_edit_action"] = "draft"
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self._clear_edit_preferred_column(card)
            self._insert_edit_text(card, text)
            if active_field == "tags":
                card["tag_selected_index"] = 0
                card["tag_keyboard_selection_active"] = False
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

        topology_field = self._location_topology_field_from_virtual(field_key)
        if topology_field:
            return self.add_location_topology_relation(card, topology_field, entity_id)

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
        if field_key not in {"wiki_entry", self.TIMELINE_SNAPSHOT_FIELD} and not self._is_person_quote_wiki_field(field_key):
            return False

        if self._is_person_quote_wiki_field(field_key):
            general_rect = (card.get("person_quote_input_rects") or {}).get(field_key)
        else:
            general_rect = (
                card.get("timeline_snapshot_rect")
                if field_key == self.TIMELINE_SNAPSHOT_FIELD
                else card.get("general_content_rect")
            )
        if general_rect is None or font is None:
            return False

        if card.get("active_edit_field") != field_key:
            if self._is_person_quote_virtual_field(field_key):
                self._set_person_quote_active_field(card, field_key)
            else:
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

    def edit_cursor_from_pos(self, card, field_key, mouse_pos, font):
        if field_key not in {"wiki_entry", self.TIMELINE_SNAPSHOT_FIELD} and not self._is_person_quote_wiki_field(field_key):
            return None

        if self._is_person_quote_wiki_field(field_key):
            general_rect = (card.get("person_quote_input_rects") or {}).get(field_key)
        else:
            general_rect = (
                card.get("timeline_snapshot_rect")
                if field_key == self.TIMELINE_SNAPSHOT_FIELD
                else card.get("general_content_rect")
            )
        if general_rect is None or font is None:
            return None

        buffer_text = card.get("edit_buffer", "")
        inner_rect = general_rect.inflate(-10, -10)
        lines = CardWikiRenderer.wrap_edit_lines(buffer_text, font, inner_rect.width)
        if not lines:
            return 0

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
        return line_info["start"] + best_offset

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
            cache_path = os.path.abspath(candidate)
            try:
                cache_key = (cache_path, os.path.getmtime(cache_path))
            except OSError:
                continue
            if cache_key in self.IMAGE_SURFACE_CACHE:
                return self.IMAGE_SURFACE_CACHE[cache_key]
            try:
                surface = pygame.image.load(candidate).convert_alpha()
            except Exception:
                return None
            if len(self.IMAGE_SURFACE_CACHE) >= self.MAX_IMAGE_CACHE_ITEMS:
                self.IMAGE_SURFACE_CACHE.clear()
                self.SCALED_PREVIEW_CACHE.clear()
            self.IMAGE_SURFACE_CACHE[cache_key] = surface
            return surface

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

    def _is_material_model_field(self, field_key):
        return field_key in {"natural_material_model", "atmospheric_material_model"}

    def _material_model_items(self, model, max_items=12):
        if not isinstance(model, dict):
            return []
        items = [item for item in model.get("likely_materials") or [] if isinstance(item, dict)]
        return items[:max(0, int(max_items))]

    def _material_item_color(self, item):
        raw_color = item.get("display_color") or item.get("band_color")
        if not isinstance(raw_color, (list, tuple)) or len(raw_color) < 3:
            return (156, 156, 148)
        try:
            return tuple(max(0, min(255, int(component))) for component in raw_color[:3])
        except (TypeError, ValueError):
            return (156, 156, 148)

    def _material_item_line(self, item):
        name = str(item.get("name") or item.get("material_id") or "material").strip()
        formula = str(item.get("chemical_formula") or item.get("molecule") or "").strip()
        if item.get("percent") is not None:
            try:
                measure = f"{float(item.get('percent')):.1f}%"
            except (TypeError, ValueError):
                measure = ""
        else:
            occurrence = str(item.get("occurrence") or "possible").strip()
            try:
                measure = f"{occurrence} {float(item.get('confidence', 0.0)) * 100:.0f}%"
            except (TypeError, ValueError):
                measure = occurrence
        representation = str(item.get("spatial_representation") or "").strip()
        if representation:
            representation = representation.replace("_", " ")
        parts = [
            part for part in (name, measure, representation, formula) if part
        ]
        return " | ".join(parts)

    def _format_table_value(self, key, value):
        if self._is_material_model_field(key) and isinstance(value, dict):
            items = self._material_model_items(value)
            if not items:
                return str(value.get("status") or "No inferred materials")
            return "\n".join(self._material_item_line(item) for item in items)
        if key == "materials_summary" and isinstance(value, dict):
            lines = []
            if value.get("status"):
                lines.append(f"status: {value.get('status')}")
            if value.get("catalog_version"):
                lines.append(f"catalog: {value.get('catalog_version')}")
            if value.get("likely_material_count") is not None:
                lines.append(f"likely materials: {value.get('likely_material_count')}")
            if value.get("heatmap_status"):
                lines.append(f"heatmap: {value.get('heatmap_status')}")
            if value.get("dominant_materials"):
                lines.append("dominant: " + ", ".join(str(item) for item in value.get("dominant_materials") or []))
            return "\n".join(lines) if lines else self._format_value(value)
        if key == "material_heatmap_model" and isinstance(value, dict):
            layers = value.get("layers") or []
            composite = value.get("composite_layer") or {}
            storage = value.get("bundle_path") or composite.get("bundle_path") or composite.get("image_path", "")
            return "\n".join([
                f"status: {value.get('status', '')}",
                f"layers: {len(layers)}",
                f"storage: {storage}",
            ]).strip()
        return self._format_value(value)

    def _measure_table_row(self, font, key, value, key_column_w, value_column_w):
        rendered_key = f"{self._field_display_label(key)}:"
        key_lines = self._wrap_text_lines(rendered_key, font, max(20, key_column_w - 12))
        rendered_value = (
            self.controlled_choice_display_label(key, value)
            if self._is_controlled_choice_field(key)
            else self._format_table_value(key, value)
        )
        wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)
        if self._is_material_model_field(key) and isinstance(value, dict):
            item_count = max(1, len(self._material_model_items(value)))
            content_h = max(len(key_lines), item_count) * self._table_line_height(font)
        else:
            content_h = max(1, len(key_lines), len(wrapped_lines)) * self._table_line_height(font)
        row_h = content_h + self.TABLE_ROW_PAD_Y * 2
        return key_lines, wrapped_lines, row_h

    def _field_display_label(self, field_key):
        labels = {
            "start_year": "start year",
            "end_year": "end year",
            "start_event": "  commentary",
            "end_event": "  commentary",
            "snapshot_year": "snapshot year",
            "temporal_periods": "periods",
            "plant_growth_form": "growth form",
            "plant_growth_behaviour": "growth behaviour",
            "plant_lifespan": "life-cycle behaviour",
            "plant_life_cycle": "life-cycle behaviour",
            "plant_life_form": "Raunkiær life form",
            "plant_woodiness": "woodiness",
            "mature_height": "mature height",
            "mature_height_class": "mature height class",
            "growth_rate": "growth rate",
            "maturity_rate": "maturity rate",
            "longevity_class": "longevity class",
            "leaf_phenology": "leaf phenology",
            "leaf_size_class": "leaf size class",
            "leaf_structure": "leaf structure",
            "leaf_arrangement": "leaf arrangement",
            "leaf_attachment_pattern": "leaf attachment",
            "leaf_clustering": "leaf clustering",
            "succulence": "succulence",
            "root_architecture": "root architecture",
            "root_depth_class": "root depth class",
            "belowground_storage": "belowground storage",
            "max_root_depth": "maximum root depth",
            "reproductive_mode": "reproductive mode",
            "pollination": "pollination",
            "dispersal": "dispersal",
            "seed_size_class": "seed size class",
            "clonal_spread": "clonal spread",
            "resprouting": "resprouting",
            "regeneration_strategy": "regeneration strategy",
            "nitrogen_fixation": "nitrogen fixation",
            "nutrition_mode": "nutrition mode",
            "mycorrhizal_type": "mycorrhizal type",
            "shade_tolerance": "shade tolerance",
            "moisture_preference": "moisture preference",
            "waterlogging_tolerance": "waterlogging tolerance",
            "temperature_range": "temperature range",
            "frost_tolerance": "frost tolerance",
            "soil_ph_range": "soil pH range",
            "salinity_tolerance": "salinity tolerance",
            "plant_root_module_ref": "root sprite",
            "plant_stem_module_ref": "stem sprite",
            "plant_branch_module_ref": "branch sprite",
            "plant_leaf_module_ref": "leaf sprite",
            "plant_flower_module_ref": "flower sprite",
            "plant_fruit_module_ref": "fruit sprite",
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

    def _is_person_quotes_mode(self):
        return (
            self.active_tab == "simulation"
            and self._is_person_card()
            and self.active_simulation_subtab == "quotes"
        )

    def _person_quote_entries(self):
        entries = []
        for raw_entry in self.entity.get(self.PERSON_QUOTE_FIELD) or []:
            if not isinstance(raw_entry, dict):
                continue
            quote = str(raw_entry.get("quote") or raw_entry.get("text") or "").strip()
            date = str(raw_entry.get("date") or raw_entry.get("year") or "").strip()
            context = str(raw_entry.get("context") or raw_entry.get("commentary") or "").strip()
            if not quote and not date and not context:
                continue
            entry = {"quote": quote, "date": date, "context": context}
            if raw_entry.get("id"):
                entry["id"] = str(raw_entry.get("id"))
            entries.append(entry)
        return entries

    def _person_conversation_entries(self):
        entries = []
        for raw_entry in self.entity.get(self.PERSON_CONVERSATION_FIELD) or []:
            if not isinstance(raw_entry, dict):
                continue
            speaker = str(raw_entry.get("speaker") or raw_entry.get("person") or raw_entry.get("name") or "").strip()
            message = str(raw_entry.get("message") or raw_entry.get("text") or raw_entry.get("quote") or "").strip()
            date = str(raw_entry.get("date") or raw_entry.get("year") or "").strip()
            if not speaker and not message and not date:
                continue
            entry = {"speaker": speaker, "message": message, "date": date}
            if raw_entry.get("id"):
                entry["id"] = str(raw_entry.get("id"))
            entries.append(entry)
        return entries

    def _person_quote_capture_mode(self, card):
        mode = str(card.get("person_quote_capture_mode") or "quotes").strip().lower() if isinstance(card, dict) else "quotes"
        return "conversations" if mode == "conversations" else "quotes"

    def _set_person_quote_capture_mode(self, card, mode):
        mode = "conversations" if str(mode or "").strip().lower() == "conversations" else "quotes"
        self._sync_active_person_quote_edit_buffer(card)
        card["person_quote_capture_mode"] = mode
        card["active_edit_field"] = None
        card["person_quote_active_field"] = None
        card["edit_buffer"] = ""
        card["edit_cursor"] = 0
        return True

    def _person_quote_capture_fields(self, card):
        if self._person_quote_capture_mode(card) == "conversations":
            return (
                self.PERSON_CONVERSATION_SPEAKER_FIELD,
                self.PERSON_CONVERSATION_DATE_FIELD,
                self.PERSON_CONVERSATION_MESSAGE_FIELD,
            )
        return (
            self.PERSON_QUOTE_TEXT_FIELD,
            self.PERSON_QUOTE_DATE_FIELD,
            self.PERSON_QUOTE_CONTEXT_FIELD,
        )

    def _default_person_quote_date(self, card):
        selected_year = card.get("selected_year") if isinstance(card, dict) else None
        if selected_year not in (None, ""):
            return str(selected_year)
        working_range = card.get("working_year_range") if isinstance(card, dict) else None
        if isinstance(working_range, (list, tuple)) and working_range:
            start_year = working_range[0]
            end_year = working_range[1] if len(working_range) > 1 else start_year
            if start_year not in (None, ""):
                if end_year not in (None, "", start_year):
                    return f"{start_year}-{end_year}"
                return str(start_year)
        return ""

    def _person_quote_buffers(self, card):
        buffers = card.setdefault("person_quote_buffers", {})
        if "quote" not in buffers:
            buffers["quote"] = ""
        if "date" not in buffers:
            buffers["date"] = self._default_person_quote_date(card)
        if "context" not in buffers:
            buffers["context"] = ""
        if "conversation_speaker" not in buffers:
            buffers["conversation_speaker"] = self._entity_display_label(self.entity)
        if "conversation_date" not in buffers:
            buffers["conversation_date"] = self._default_person_quote_date(card)
        if "conversation_message" not in buffers:
            buffers["conversation_message"] = ""
        return buffers

    def _person_quote_buffer_key(self, field_key):
        return {
            self.PERSON_QUOTE_TEXT_FIELD: "quote",
            self.PERSON_QUOTE_DATE_FIELD: "date",
            self.PERSON_QUOTE_CONTEXT_FIELD: "context",
            self.PERSON_CONVERSATION_SPEAKER_FIELD: "conversation_speaker",
            self.PERSON_CONVERSATION_DATE_FIELD: "conversation_date",
            self.PERSON_CONVERSATION_MESSAGE_FIELD: "conversation_message",
            "quote": "quote",
            "date": "date",
            "context": "context",
            "speaker": "conversation_speaker",
            "message": "conversation_message",
        }.get(field_key, "")

    def _is_person_quote_virtual_field(self, field_key):
        return field_key in self.PERSON_QUOTE_INPUT_FIELDS

    def _is_person_quote_wiki_field(self, field_key):
        return field_key in {
            self.PERSON_QUOTE_TEXT_FIELD,
            self.PERSON_QUOTE_CONTEXT_FIELD,
            self.PERSON_CONVERSATION_MESSAGE_FIELD,
        }

    def _person_quote_buffer_text(self, card, field_key):
        buffer_key = self._person_quote_buffer_key(field_key)
        if not buffer_key:
            return ""
        if card.get("active_edit_field") == field_key:
            return str(card.get("edit_buffer") or "")
        return str(self._person_quote_buffers(card).get(buffer_key, ""))

    def _set_person_quote_buffer_text(self, card, field_key, text):
        buffers = self._person_quote_buffers(card)
        buffer_key = self._person_quote_buffer_key(field_key)
        if not buffer_key:
            return
        buffers[buffer_key] = str(text or "")

    def _sync_active_person_quote_edit_buffer(self, card):
        field_key = card.get("active_edit_field")
        if not self._is_person_quote_virtual_field(field_key):
            return False
        self._set_person_quote_buffer_text(card, field_key, card.get("edit_buffer", ""))
        return True

    def _set_person_quote_active_field(self, card, field_key):
        field_key = {
            "quote": self.PERSON_QUOTE_TEXT_FIELD,
            "date": self.PERSON_QUOTE_DATE_FIELD,
            "context": self.PERSON_QUOTE_CONTEXT_FIELD,
            "speaker": self.PERSON_CONVERSATION_SPEAKER_FIELD,
            "message": self.PERSON_CONVERSATION_MESSAGE_FIELD,
        }.get(field_key, field_key)
        if field_key not in self.PERSON_QUOTE_INPUT_FIELDS:
            return False
        self._sync_active_person_quote_edit_buffer(card)
        self._person_quote_buffers(card)
        target_text = self._person_quote_buffer_text(card, field_key)
        card["person_quote_active_field"] = field_key
        card["active_edit_field"] = field_key
        card["edit_original_value"] = target_text
        card["edit_buffer"] = target_text
        card["edit_cursor"] = len(card["edit_buffer"])
        card["edit_selection_anchor"] = card["edit_cursor"]
        card["edit_selection_cursor"] = card["edit_cursor"]
        card.pop("edit_validation_message", None)
        return True

    def _cycle_person_quote_field(self, card, direction=1):
        active_field = card.get("active_edit_field") or card.get("person_quote_active_field")
        field_order = self._person_quote_capture_fields(card)
        if active_field not in field_order:
            target_index = 0 if direction >= 0 else len(field_order) - 1
        else:
            target_index = (field_order.index(active_field) + direction) % len(field_order)
        return self._set_person_quote_active_field(card, field_order[target_index])

    def add_person_quote_from_buffers(self, card):
        self._sync_active_person_quote_edit_buffer(card)
        buffers = self._person_quote_buffers(card)
        quote = str(buffers.get("quote") or "").strip()
        date = str(buffers.get("date") or "").strip()
        context = str(buffers.get("context") or "").strip()
        if not quote:
            card["person_quote_status"] = "Quote text required"
            return False

        entries = self._person_quote_entries()
        entry = {"quote": quote}
        if date:
            entry["date"] = date
        if context:
            entry["context"] = context
        entries.append(entry)
        self.entity[self.PERSON_QUOTE_FIELD] = entries

        buffers["quote"] = ""
        buffers["context"] = ""
        if not date:
            buffers["date"] = self._default_person_quote_date(card)
        card["person_quote_active_field"] = self.PERSON_QUOTE_TEXT_FIELD
        card["active_edit_field"] = self.PERSON_QUOTE_TEXT_FIELD
        card["edit_buffer"] = ""
        card["edit_cursor"] = 0
        card["edit_original_value"] = ""
        card["person_quote_status"] = "Quote added"
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = self.PERSON_QUOTE_FIELD
        return True

    def add_person_conversation_from_buffers(self, card):
        self._sync_active_person_quote_edit_buffer(card)
        buffers = self._person_quote_buffers(card)
        speaker = str(buffers.get("conversation_speaker") or "").strip()
        date = str(buffers.get("conversation_date") or "").strip()
        message = str(buffers.get("conversation_message") or "").strip()
        if not message:
            card["person_quote_status"] = "Message text required"
            return False

        entries = self._person_conversation_entries()
        entry = {"message": message}
        if speaker:
            entry["speaker"] = speaker
        if date:
            entry["date"] = date
        entries.append(entry)
        self.entity[self.PERSON_CONVERSATION_FIELD] = entries

        buffers["conversation_message"] = ""
        if not date:
            buffers["conversation_date"] = self._default_person_quote_date(card)
        card["person_quote_active_field"] = self.PERSON_CONVERSATION_MESSAGE_FIELD
        card["active_edit_field"] = self.PERSON_CONVERSATION_MESSAGE_FIELD
        card["edit_buffer"] = ""
        card["edit_cursor"] = 0
        card["edit_original_value"] = ""
        card["person_quote_status"] = "Message added"
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = self.PERSON_CONVERSATION_FIELD
        return True

    def add_person_quote_or_conversation_from_buffers(self, card):
        if self._person_quote_capture_mode(card) == "conversations":
            return self.add_person_conversation_from_buffers(card)
        return self.add_person_quote_from_buffers(card)

    def remove_person_quote_at_index(self, card, quote_index):
        entries = self._person_quote_entries()
        try:
            quote_index = int(quote_index)
        except (TypeError, ValueError):
            return False
        if quote_index < 0 or quote_index >= len(entries):
            return False
        entries.pop(quote_index)
        self.entity[self.PERSON_QUOTE_FIELD] = entries
        card["person_quote_status"] = "Quote removed"
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = self.PERSON_QUOTE_FIELD
        return True

    def remove_person_conversation_at_index(self, card, message_index):
        entries = self._person_conversation_entries()
        try:
            message_index = int(message_index)
        except (TypeError, ValueError):
            return False
        if message_index < 0 or message_index >= len(entries):
            return False
        entries.pop(message_index)
        self.entity[self.PERSON_CONVERSATION_FIELD] = entries
        card["person_quote_status"] = "Message removed"
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = self.PERSON_CONVERSATION_FIELD
        return True

    def _measure_person_quotes_height(self, font, width, card):
        line_h = self._table_line_height(font)
        total_h = self.SECTION_HEADER_H + self.SECTION_GAP + 34
        if card.get("is_edit_mode", False):
            if self._person_quote_capture_mode(card) == "conversations":
                total_h += line_h + 30 + 6 + line_h + 92 + 10
            else:
                total_h += line_h + 88 + 6 + line_h + 30 + 6 + line_h + 82 + 10
        entries = self._person_conversation_entries() if self._person_quote_capture_mode(card) == "conversations" else self._person_quote_entries()
        if not entries:
            total_h += 42
        elif self._person_quote_capture_mode(card) == "conversations":
            bubble_w = max(80, int(width * 0.74))
            for entry in entries:
                message_lines = self._wrap_text_lines(entry.get("message", ""), font, bubble_w - 18)[:5]
                total_h += max(48, 24 + len(message_lines) * line_h + 12) + 8
        else:
            text_w = max(40, width - 22)
            for entry in reversed(entries):
                quote_lines = self._wrap_text_lines(entry.get("quote", ""), font, text_w)[:4]
                context = str(entry.get("context") or "").strip()
                context_lines = self._wrap_text_lines(context, font, text_w)[:2] if context else []
                total_h += max(54, 22 + len(quote_lines) * line_h + len(context_lines) * line_h + 12) + 8
        return total_h

    def _layout_person_quotes_content(self, card, x, y, width):
        font = card["layout_font"]
        line_h = self._table_line_height(font)
        section_rect = pygame.Rect(x, y, width, self.SECTION_HEADER_H)
        card["person_quote_section_rect"] = section_rect
        y = section_rect.bottom + self.SECTION_GAP + 6
        card["person_quote_mode_hitboxes"] = []

        mode_y = y
        mode_w = max(82, min(128, (width - 8) // 2))
        quote_mode_rect = pygame.Rect(x, mode_y, mode_w, 24)
        conversation_mode_rect = pygame.Rect(quote_mode_rect.right + 8, mode_y, mode_w + 20, 24)
        card["person_quote_mode_hitboxes"] = [
            ("quotes", quote_mode_rect),
            ("conversations", conversation_mode_rect),
        ]
        y = quote_mode_rect.bottom + 10

        card["person_quote_input_rects"] = {}
        card["person_quote_add_rect"] = None
        mode = self._person_quote_capture_mode(card)
        if card.get("is_edit_mode", False) and mode == "conversations":
            add_w = 92
            speaker_w = max(120, min(180, (width - add_w - 24) // 2))
            date_w = 104
            speaker_rect = pygame.Rect(x, y + line_h, speaker_w, 24)
            date_rect = pygame.Rect(speaker_rect.right + 8, y + line_h, date_w, 24)
            add_rect = pygame.Rect(x + width - add_w, y + line_h, add_w, 24)
            y = speaker_rect.bottom + 6
            message_rect = pygame.Rect(x, y + line_h, width, 92)
            y = message_rect.bottom + 10
            card["person_quote_input_rects"] = {
                self.PERSON_CONVERSATION_SPEAKER_FIELD: speaker_rect,
                self.PERSON_CONVERSATION_DATE_FIELD: date_rect,
                self.PERSON_CONVERSATION_MESSAGE_FIELD: message_rect,
            }
            card["person_quote_add_rect"] = add_rect
        elif card.get("is_edit_mode", False):
            quote_rect = pygame.Rect(x, y + line_h, width, 88)
            y = quote_rect.bottom + 6
            add_w = 72
            date_rect = pygame.Rect(x, y + line_h, 98, 24)
            add_rect = pygame.Rect(x + width - add_w, y + line_h, add_w, 24)
            y = date_rect.bottom + 6
            context_rect = pygame.Rect(x, y + line_h, width, 82)
            y = context_rect.bottom + 10
            card["person_quote_input_rects"] = {
                self.PERSON_QUOTE_TEXT_FIELD: quote_rect,
                self.PERSON_QUOTE_DATE_FIELD: date_rect,
                self.PERSON_QUOTE_CONTEXT_FIELD: context_rect,
            }
            card["person_quote_add_rect"] = add_rect

        rows = []
        entries = self._person_conversation_entries() if mode == "conversations" else self._person_quote_entries()
        if not entries:
            empty_rect = pygame.Rect(x, y, width, 42)
            card["person_quote_empty_rect"] = empty_rect
            y = empty_rect.bottom + 8
        elif mode == "conversations":
            card["person_quote_empty_rect"] = None
            person_name = self._entity_display_label(self.entity).strip().lower()
            for message_index, entry in enumerate(entries):
                bubble_w = max(80, int(width * 0.74))
                speaker = str(entry.get("speaker") or "").strip()
                mine = bool(speaker and speaker.lower() == person_name)
                bubble_x = x + width - bubble_w if mine else x
                message_lines = self._wrap_text_lines(entry.get("message", ""), font, bubble_w - 18)[:5]
                row_h = max(48, 24 + len(message_lines) * line_h + 12)
                row_rect = pygame.Rect(bubble_x, y, bubble_w, row_h)
                remove_rect = None
                if card.get("is_edit_mode", False):
                    remove_rect = pygame.Rect(row_rect.right - 24, row_rect.y + 6, 18, 18)
                rows.append(
                    {
                        "mode": "conversation",
                        "index": message_index,
                        "entry": entry,
                        "rect": row_rect,
                        "message_lines": message_lines,
                        "remove_rect": remove_rect,
                        "mine": mine,
                    }
                )
                y = row_rect.bottom + 8
        else:
            card["person_quote_empty_rect"] = None
            for quote_index, entry in reversed(list(enumerate(entries))):
                text_w = width - 22
                if card.get("is_edit_mode", False):
                    text_w -= 28
                quote_lines = self._wrap_text_lines(entry.get("quote", ""), font, max(40, text_w))[:4]
                context = str(entry.get("context") or "").strip()
                context_lines = self._wrap_text_lines(context, font, max(40, text_w))[:2] if context else []
                row_h = max(54, 22 + len(quote_lines) * line_h + len(context_lines) * line_h + 12)
                row_rect = pygame.Rect(x, y, width, row_h)
                remove_rect = None
                if card.get("is_edit_mode", False):
                    remove_rect = pygame.Rect(row_rect.right - 24, row_rect.y + 6, 18, 18)
                rows.append(
                    {
                        "mode": "quote",
                        "index": quote_index,
                        "entry": entry,
                        "rect": row_rect,
                        "quote_lines": quote_lines,
                        "context_lines": context_lines,
                        "remove_rect": remove_rect,
                    }
                )
                y = row_rect.bottom + 8
        card["person_quote_rows"] = rows
        return y

    def _draw_person_quote_text_input(self, screen, font, card, field_key, rect, placeholder):
        active = card.get("active_edit_field") == field_key
        fill = (48, 54, 68) if active else (36, 41, 54)
        border = (182, 202, 236) if active else (90, 104, 128)
        text = self._person_quote_buffer_text(card, field_key)
        if self._is_person_quote_wiki_field(field_key):
            CardWikiRenderer.draw_content(
                screen,
                font,
                rect,
                text or placeholder,
                is_editing=active,
                resolve_link_label=self._resolve_wiki_link_label,
                resolve_link_color=self._resolve_wiki_link_color,
                resolve_link_palette=self._resolve_wiki_link_palette,
                section_colors=self._wiki_field_colors(),
                cursor_index=card.get("edit_cursor", 0),
                scroll_y=0,
                selection_range=self._edit_selection_range(card),
            )
            if not text and not active:
                overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                overlay.fill((24, 28, 38, 72))
                screen.blit(overlay, rect)
            return

        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)
        display = text if text else placeholder
        color = (238, 242, 250) if text else (136, 146, 166)
        screen.blit(
            font.render(self._ellipsize_text(display, font, rect.width - 12), True, color),
            (rect.x + 6, rect.y + 5),
        )
        if active:
            cursor = TextEditing.clamp_cursor(text, card.get("edit_cursor", len(text)))
            cursor_text = text[:cursor]
            cursor_x = rect.x + 6 + min(rect.width - 14, font.size(cursor_text)[0])
            pygame.draw.line(screen, (238, 242, 250), (cursor_x, rect.y + 5), (cursor_x, rect.y + rect.height - 6), 1)

    def _draw_person_quotes_content(self, screen, font, card):
        section_rect = card.get("person_quote_section_rect")
        if section_rect is None:
            return
        pygame.draw.rect(screen, (36, 40, 50), section_rect)
        pygame.draw.rect(screen, (110, 110, 120), section_rect, 1)
        count = len(self._person_quote_entries())
        conversation_count = len(self._person_conversation_entries())
        mode = self._person_quote_capture_mode(card)
        title = "Quotes" if mode == "quotes" else "Conversations"
        if mode == "quotes" and count == 1:
            title = "Quotes (1)"
        elif mode == "quotes" and count > 1:
            title = f"Quotes ({count})"
        elif mode == "conversations":
            title = f"Conversations ({conversation_count})" if conversation_count else "Conversations"
        screen.blit(font.render(title, True, (235, 235, 235)), (section_rect.x + 8, section_rect.y + 3))

        for mode_id, mode_rect in card.get("person_quote_mode_hitboxes", []):
            selected = mode_id == mode
            fill = (66, 82, 108) if selected else (42, 48, 62)
            border = (184, 202, 232) if selected else (94, 108, 132)
            pygame.draw.rect(screen, fill, mode_rect)
            pygame.draw.rect(screen, border, mode_rect, 1)
            label = "Quotes" if mode_id == "quotes" else "Conversations"
            label_surface = font.render(self._ellipsize_text(label, font, mode_rect.width - 10), True, (238, 242, 250))
            screen.blit(label_surface, label_surface.get_rect(center=mode_rect.center))

        if card.get("is_edit_mode", False):
            label_y = section_rect.bottom + self.SECTION_GAP + 6
            input_rects = card.get("person_quote_input_rects") or {}
            if mode == "conversations":
                speaker_rect = input_rects.get(self.PERSON_CONVERSATION_SPEAKER_FIELD)
                date_rect = input_rects.get(self.PERSON_CONVERSATION_DATE_FIELD)
                message_rect = input_rects.get(self.PERSON_CONVERSATION_MESSAGE_FIELD)
                if speaker_rect is not None:
                    screen.blit(font.render("Speaker", True, (184, 196, 216)), (speaker_rect.x, speaker_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_CONVERSATION_SPEAKER_FIELD, speaker_rect, "Speaker")
                if date_rect is not None:
                    screen.blit(font.render("Date", True, (184, 196, 216)), (date_rect.x, date_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_CONVERSATION_DATE_FIELD, date_rect, "Date")
                if message_rect is not None:
                    screen.blit(font.render("Message", True, (184, 196, 216)), (message_rect.x, message_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_CONVERSATION_MESSAGE_FIELD, message_rect, "Type message")
            else:
                quote_rect = input_rects.get(self.PERSON_QUOTE_TEXT_FIELD)
                date_rect = input_rects.get(self.PERSON_QUOTE_DATE_FIELD)
                context_rect = input_rects.get(self.PERSON_QUOTE_CONTEXT_FIELD)
                if quote_rect is not None:
                    screen.blit(font.render("Quote", True, (184, 196, 216)), (quote_rect.x, quote_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_QUOTE_TEXT_FIELD, quote_rect, "Type quote")
                if date_rect is not None:
                    screen.blit(font.render("Date", True, (184, 196, 216)), (date_rect.x, date_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_QUOTE_DATE_FIELD, date_rect, "Date")
                if context_rect is not None:
                    screen.blit(font.render("Context", True, (184, 196, 216)), (context_rect.x, context_rect.y - self._table_line_height(font)))
                    self._draw_person_quote_text_input(screen, font, card, self.PERSON_QUOTE_CONTEXT_FIELD, context_rect, "Commentary")

            add_rect = card.get("person_quote_add_rect")
            if add_rect is not None:
                hovered = add_rect.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(screen, (66, 82, 108) if hovered else (52, 62, 84), add_rect)
                pygame.draw.rect(screen, (184, 202, 232), add_rect, 1)
                add_surface = font.render("+ Add", True, (244, 246, 252))
                screen.blit(add_surface, add_surface.get_rect(center=add_rect.center))

        empty_rect = card.get("person_quote_empty_rect")
        if empty_rect is not None:
            pygame.draw.rect(screen, (32, 36, 46), empty_rect)
            pygame.draw.rect(screen, (82, 90, 108), empty_rect, 1)
            empty_text = font.render("No quotes recorded", True, (146, 156, 176))
            screen.blit(empty_text, empty_text.get_rect(center=empty_rect.center))

        for row in card.get("person_quote_rows", []):
            row_rect = row.get("rect")
            entry = row.get("entry") or {}
            if row_rect is None:
                continue
            if row.get("mode") == "conversation":
                fill = (42, 62, 78) if row.get("mine") else (36, 42, 54)
                border = (108, 146, 168) if row.get("mine") else (82, 94, 116)
                pygame.draw.rect(screen, fill, row_rect)
                pygame.draw.rect(screen, border, row_rect, 1)
                speaker = str(entry.get("speaker") or "Speaker").strip()
                date = str(entry.get("date") or "").strip()
                meta = speaker if not date else f"{speaker} | {date}"
                screen.blit(font.render(self._ellipsize_text(meta, font, row_rect.width - 40), True, (174, 194, 218)), (row_rect.x + 10, row_rect.y + 6))
                message_y = row_rect.y + 24
                for line in row.get("message_lines") or []:
                    screen.blit(font.render(line, True, (236, 240, 246)), (row_rect.x + 10, message_y))
                    message_y += self._table_line_height(font)
                remove_rect = row.get("remove_rect")
                if remove_rect is not None:
                    pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                    pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                    remove_surface = font.render("x", True, (250, 220, 224))
                    screen.blit(remove_surface, remove_surface.get_rect(center=remove_rect.center))
                continue

            pygame.draw.rect(screen, (32, 36, 46), row_rect)
            pygame.draw.rect(screen, (82, 90, 108), row_rect, 1)
            date = str(entry.get("date") or "").strip()
            if date:
                date_surface = font.render(date, True, (168, 184, 214))
                screen.blit(date_surface, (row_rect.x + 10, row_rect.y + 6))
            quote_y = row_rect.y + 22
            for line in row.get("quote_lines") or []:
                screen.blit(font.render(line, True, (232, 236, 244)), (row_rect.x + 10, quote_y))
                quote_y += self._table_line_height(font)
            for line in row.get("context_lines") or []:
                screen.blit(font.render(line, True, (166, 176, 194)), (row_rect.x + 10, quote_y))
                quote_y += self._table_line_height(font)
            remove_rect = row.get("remove_rect")
            if remove_rect is not None:
                pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                remove_surface = font.render("x", True, (250, 220, 224))
                screen.blit(remove_surface, remove_surface.get_rect(center=remove_rect.center))

    def handle_person_quotes_click(self, card, mouse_pos):
        if not self._is_person_quotes_mode() or not card.get("is_edit_mode", False):
            return False
        for mode_id, mode_rect in card.get("person_quote_mode_hitboxes", []):
            if mode_rect is not None and mode_rect.collidepoint(mouse_pos):
                return self._set_person_quote_capture_mode(card, mode_id)
        for field_key, input_rect in (card.get("person_quote_input_rects") or {}).items():
            if input_rect is not None and input_rect.collidepoint(mouse_pos):
                if not self._set_person_quote_active_field(card, field_key):
                    return False
                if self._is_person_quote_wiki_field(field_key):
                    self.set_edit_cursor_from_pos(card, field_key, mouse_pos, card.get("layout_font"))
                return True

        add_rect = card.get("person_quote_add_rect")
        if add_rect is not None and add_rect.collidepoint(mouse_pos):
            return self.add_person_quote_or_conversation_from_buffers(card) or True

        for row in card.get("person_quote_rows", []):
            remove_rect = row.get("remove_rect")
            if remove_rect is not None and remove_rect.collidepoint(mouse_pos):
                if row.get("mode") == "conversation":
                    return self.remove_person_conversation_at_index(card, row.get("index"))
                return self.remove_person_quote_at_index(card, row.get("index"))
        return False

    def _handle_person_quote_keydown(self, card, event):
        if not self._is_person_quotes_mode() or not card.get("is_edit_mode", False):
            return False

        active_field = card.get("active_edit_field") or card.get("person_quote_active_field")
        if active_field not in self.PERSON_QUOTE_INPUT_FIELDS:
            if event.key == pygame.K_TAB:
                return self._cycle_person_quote_field(card, direction=-1 if (event.mod & pygame.KMOD_SHIFT) else 1)
            if event.key == pygame.K_ESCAPE:
                card["last_edit_action"] = "cancel"
                card["is_edit_mode"] = False
                return True
            return False

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and (event.mod & pygame.KMOD_CTRL):
            return self.add_person_quote_or_conversation_from_buffers(card) or True

        if event.key == pygame.K_ESCAPE:
            self._sync_active_person_quote_edit_buffer(card)
            card["person_quote_active_field"] = None
            card["active_edit_field"] = None
            card["edit_buffer"] = ""
            card["edit_cursor"] = 0
            return True

        if event.key == pygame.K_TAB:
            return self._cycle_person_quote_field(card, direction=-1 if (event.mod & pygame.KMOD_SHIFT) else 1)

        return False

    def _layout_extant_content(self, card, content_left, current_y, content_width):
        rows = []
        scope_labels = [
            self._entity_label_for_id(entity_id)
            for entity_id in self._period_scope_parent_ids()
        ]
        scope_text = (
            "Scope: " + ", ".join(scope_labels)
            if scope_labels
            else "Scope: all repository entries with overlapping dates"
        )
        summary_rect = pygame.Rect(content_left, current_y, content_width, 30)
        rows.append({"kind": "summary", "text": scope_text, "rect": summary_rect})
        current_y = summary_rect.bottom + 8

        grouped = {}
        for entity in self._extant_entries():
            dataset_name = str(entity.get("_dataset") or entity.get("type") or "entries")
            grouped.setdefault(dataset_name, []).append(entity)

        for dataset_name in sorted(grouped, key=lambda value: value.lower()):
            entries = grouped[dataset_name]
            header_rect = pygame.Rect(content_left, current_y, content_width, 24)
            rows.append({
                "kind": "header",
                "text": f"{dataset_name.replace('_', ' ').title()} ({len(entries)})",
                "rect": header_rect,
            })
            current_y = header_rect.bottom + 3
            for entity in entries:
                entity_id = str(entity.get("id") or "")
                row_rect = pygame.Rect(content_left, current_y, content_width, 28)
                entity_range = self._entity_timeline_range(entity)
                if entity_range is None:
                    temporal_label = ""
                elif entity_range[0] == entity_range[1]:
                    temporal_label = str(entity_range[0])
                else:
                    temporal_label = f"{entity_range[0]}–{entity_range[1]}"
                rows.append({
                    "kind": "entity",
                    "entity": entity,
                    "entity_id": entity_id,
                    "text": self._entity_display_label(entity),
                    "temporal_label": temporal_label,
                    "rect": row_rect,
                    "relation_info": {
                        "kind": "existing",
                        "entity_id": entity_id,
                        "field_key": "extant",
                    },
                })
                current_y = row_rect.bottom + 3
            current_y += 6

        if not grouped:
            empty_rect = pygame.Rect(content_left, current_y, content_width, 34)
            rows.append({
                "kind": "empty",
                "text": "No temporally defined entries are extant in this period.",
                "rect": empty_rect,
            })
            current_y = empty_rect.bottom + 6
        card["extant_rows"] = rows
        return current_y

    def _draw_extant_content(self, screen, font, card):
        line_h = self._table_line_height(font)
        for index, row in enumerate(card.get("extant_rows", [])):
            rect = row.get("rect")
            if rect is None or rect.width <= 0 or rect.height <= 0:
                continue
            kind = row.get("kind")
            if kind == "summary":
                pygame.draw.rect(screen, (28, 38, 50), rect)
                pygame.draw.rect(screen, (92, 126, 158), rect, 1)
                color = (190, 212, 232)
                text_x = rect.x + 8
            elif kind == "header":
                pygame.draw.rect(screen, (36, 40, 50), rect)
                pygame.draw.rect(screen, (90, 96, 112), rect, 1)
                color = (224, 228, 238)
                text_x = rect.x + 8
            elif kind == "entity":
                fill = (34, 38, 48) if index % 2 == 0 else (29, 33, 43)
                pygame.draw.rect(screen, fill, rect)
                pygame.draw.rect(screen, (72, 82, 102), rect, 1)
                color = (216, 226, 242)
                text_x = rect.x + 10
                temporal_label = row.get("temporal_label", "")
                if temporal_label:
                    temporal_surface = font.render(temporal_label, True, (154, 172, 198))
                    screen.blit(
                        temporal_surface,
                        (
                            rect.right - temporal_surface.get_width() - 8,
                            rect.y + max(2, (rect.height - line_h) // 2),
                        ),
                    )
                    text_right = rect.right - temporal_surface.get_width() - 16
                else:
                    text_right = rect.right - 8
                label = self._ellipsize_text(row.get("text", ""), font, max(20, text_right - text_x))
                screen.blit(font.render(label, True, color), (text_x, rect.y + max(2, (rect.height - line_h) // 2)))
                continue
            else:
                pygame.draw.rect(screen, (28, 31, 40), rect)
                pygame.draw.rect(screen, (68, 72, 86), rect, 1)
                color = (154, 164, 182)
                text_x = rect.x + 8
            label = self._ellipsize_text(row.get("text", ""), font, max(20, rect.width - 16))
            screen.blit(font.render(label, True, color), (text_x, rect.y + max(2, (rect.height - line_h) // 2)))

    def layout_card(self, card, rect):
        section_hitboxes = []
        tab_hitboxes = []
        subtab_hitboxes = []
        media_import_hitboxes = []
        media_pixel_art_hitboxes = []
        media_asset_quick_hitboxes = []
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
        tag_bar_rect = None
        timeline_snapshot_rect = None
        timeline_snapshot_chip_hitboxes = []
        task_checklist_rect = None
        task_finish_checkbox_rect = None
        task_checklist_hitboxes = []
        task_checklist_input_rect = None
        person_quote_section_rect = None
        person_quote_input_rects = {}
        person_quote_mode_hitboxes = []
        person_quote_add_rect = None
        person_quote_rows = []
        person_quote_empty_rect = None
        card["extant_rows"] = []
        schema_field_specs = self._get_schema_field_specs()

        tab_y = rect.y + self.HEADER_H + 6
        tab_x = rect.x + 12
        tab_gap = 6
        tab_widths = {
            "general": 70,
            "overview": 78,
            "production": 94,
            "site": 58,
            "temporal": 82,
            "location": 82,
            "relations": 76,
            "extant": 68,
            "phylogeny": 86,
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
                "materials": 82,
                "plant_ecology": 82,
                "quotes": 72,
                "data": 58,
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
        template_button_rect = None
        relation_tree_rect = None
        time_anchor_rect = None
        delete_rect = None
        header_reserved_w = 120
        if card.get("is_edit_mode", False):
            time_anchor_rect = pygame.Rect(rect.right - 96, rect.y + 12, 20, 20)
            delete_rect = pygame.Rect(rect.right - 120, rect.y + 12, 20, 20)
            template_button_rect = pygame.Rect(rect.right - 144, rect.y + 12, 20, 20)
            header_reserved_w = 192
        else:
            relation_tree_rect = pygame.Rect(rect.right - 96, rect.y + 12, 20, 20)
            header_reserved_w = 144

        header_icon_ref = self._resolve_card_icon_reference()
        header_icon_rect = pygame.Rect(rect.x + 10, rect.y + 8, 34, 34) if header_icon_ref else None
        title_x = rect.x + (52 if header_icon_ref else 10)
        title_edit_rect = pygame.Rect(title_x, rect.y + 7, max(40, rect.right - header_reserved_w - title_x), 20)
        header_description = self._header_description_text()
        description_visible = bool(header_description) or bool(card.get("is_edit_mode", False))
        header_description_rect = pygame.Rect(title_x, rect.y + 27, max(40, rect.right - header_reserved_w - title_x), 18)
        type_label_y = rect.y + (46 if description_visible else 30)
        type_label_rect = pygame.Rect(title_x, type_label_y, max(40, rect.right - header_reserved_w - title_x), 18)
        if card.get("is_edit_mode", False):
            editable_field_hitboxes.append((self._title_edit_field(), title_edit_rect))
            editable_field_hitboxes.append((self._header_description_edit_field(), header_description_rect))

        image_rect = pygame.Rect(
            rect.x + 12,
            tabs_bottom_y + 6,
            rect.width - 24,
            self._image_block_height(),
        )

        if self._is_media_mode():
            media_add_illustration_rect = pygame.Rect(image_rect.right - 148, image_rect.y + 8, 136, 24)
            row_y = image_rect.y + 44
            if card.get("is_edit_mode", False) and self._toolbelt_tool_is_available({"requires": "plant_species"}):
                quick_y = image_rect.y + 42
                quick_x = image_rect.x + 8
                quick_gap = 5
                quick_w = max(52, (image_rect.width - 16 - quick_gap * (len(self.PLANT_ASSET_QUICK_ACTIONS) - 1)) // len(self.PLANT_ASSET_QUICK_ACTIONS))
                for asset_role, label in self.PLANT_ASSET_QUICK_ACTIONS:
                    quick_rect = pygame.Rect(quick_x, quick_y, quick_w, 22)
                    media_asset_quick_hitboxes.append((asset_role, quick_rect))
                    quick_x = quick_rect.right + quick_gap
                row_y = quick_y + 30
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
        launch_mode_options = self._launch_mode_options()
        launch_mode_hitboxes = []
        if len(launch_mode_options) > 1:
            segment_gap = 2
            segment_count = len(launch_mode_options)
            segment_w = max(1, (launch_rect.width - segment_gap * (segment_count - 1)) // segment_count)
            segment_x = launch_rect.x
            for option_index, option in enumerate(launch_mode_options):
                segment_right = (
                    launch_rect.right
                    if option_index == segment_count - 1
                    else segment_x + segment_w
                )
                segment_rect = pygame.Rect(segment_x, launch_rect.y, max(1, segment_right - segment_x), launch_rect.height)
                launch_mode_hitboxes.append((option, segment_rect))
                segment_x = segment_rect.right + segment_gap
        center_y = launch_rect.y - self.TIMELINE_TO_LAUNCH_GAP
        left_x = rect.x + 20
        right_x = rect.right - 20
        timeline_y = center_y - 10
        snapshot_timeline_lane_count = self._timeline_snapshot_chip_lane_count(
            card, card["layout_font"], rect.width,
        )
        snapshot_timeline_lane_height = snapshot_timeline_lane_count * 23
        timeline_label_y = max(
            top_content_y + 8,
            timeline_y - 18 - snapshot_timeline_lane_height,
        )
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
            tag_bar_h = 34
            if card.get("is_edit_mode", False) and card.get("active_edit_field") == "tags":
                tag_bar_h = 92
            tag_bar_rect = pygame.Rect(content_left, top_content_y, text_width, tag_bar_h)
            if card.get("is_edit_mode", False):
                editable_field_hitboxes.append(("tags", tag_bar_rect))
            wiki_top_y = tag_bar_rect.bottom + 8
            general_height = max(40, general_bottom - wiki_top_y)
            snapshot_active = self._timeline_snapshot_range(card) is not None
            snapshot_blocks = self._timeline_snapshot_display_entries(card)
            snapshot_visible = snapshot_active or bool(snapshot_blocks)
            general_content_rect = pygame.Rect(content_left, wiki_top_y, text_width, general_height)
            if self._is_task_card():
                checklist_h = min(
                    general_height - 44,
                    self._measure_task_checklist_height(card["layout_font"], text_width, card),
                )
                checklist_h = max(92, checklist_h)
                wiki_h = max(44, general_height - checklist_h - 8)
                general_content_rect = pygame.Rect(content_left, wiki_top_y, text_width, wiki_h)
                task_checklist_rect = pygame.Rect(content_left, general_content_rect.bottom + 8, text_width, checklist_h)
            elif snapshot_visible:
                desired_snapshot_h = self._measure_timeline_snapshot_blocks_height(
                    card, card["layout_font"], text_width,
                )
                snapshot_h = max(
                    58,
                    min(max(58, general_height - 44), max(58, desired_snapshot_h)),
                )
                wiki_h = max(44, general_height - snapshot_h - 8)
                general_content_rect = pygame.Rect(content_left, wiki_top_y, text_width, wiki_h)
                timeline_snapshot_rect = pygame.Rect(content_left, general_content_rect.bottom + 8, text_width, snapshot_h)
            if card.get("is_edit_mode", False):
                editable_field_hitboxes.append(("wiki_entry", general_content_rect))
                if timeline_snapshot_rect is not None and snapshot_active:
                    editable_field_hitboxes.append((self.TIMELINE_SNAPSHOT_FIELD, timeline_snapshot_rect))
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
            if timeline_snapshot_rect is not None:
                snapshot_h = self._measure_timeline_snapshot_blocks_height(
                    card, card["layout_font"], timeline_snapshot_rect.width,
                )
                content_end_y = max(content_end_y, timeline_snapshot_rect.y + snapshot_h)
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
        elif self._is_extant_mode():
            image_rect = None
            content_end_y = self._layout_extant_content(
                card,
                content_left,
                current_y,
                text_width,
            )
        elif self._is_person_quotes_mode():
            image_rect = None
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
                ("phylogeny_child_tree_rows", []),
                ("phylogeny_local_tree_rows", []),
                ("phylogeny_node_hitboxes", []),
            ):
                card[key] = value
            content_end_y = self._layout_person_quotes_content(card, content_left, current_y, text_width)
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
        elif self._is_production_mode():
            image_rect = None
            content_end_y = self._layout_production_content(card, content_left, current_y, text_width)
        elif self._is_site_mode():
            image_rect = None
            content_end_y = self._layout_site_content(card, content_left, current_y, text_width)
            if card.get("is_edit_mode", False):
                content_editable_field_hitboxes.extend(card.get("site_editable_field_hitboxes", []))
        elif self._is_location_mode():
            image_rect = None
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
                ("phylogeny_child_tree_rows", []),
                ("phylogeny_local_tree_rows", []),
                ("phylogeny_node_hitboxes", []),
            ):
                card[key] = value
            content_end_y = self._layout_location_content(card, content_left, current_y, text_width)
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

                        _, provenance, inference_source_ids = self._species_field_value(key, value)
                        field_rows.append(
                            {
                                "section": section_name,
                                "key": key,
                                "value": value,
                                "inferred": provenance == "inferred",
                                "inference_source_ids": inference_source_ids,
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
            media_asset_quick_hitboxes = [
                (asset_role, button_rect.move(0, -scroll_y).clip(content_viewport_rect))
                for asset_role, button_rect in media_asset_quick_hitboxes
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
            if self._is_extant_mode():
                visible_rows = []
                for row in card.get("extant_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    shifted_rect = row_rect.move(0, -scroll_y)
                    if not shifted_rect.colliderect(content_viewport_rect):
                        continue
                    row["rect"] = shifted_rect.clip(content_viewport_rect)
                    visible_rows.append(row)
                card["extant_rows"] = visible_rows
            elif self._is_phylogeny_mode():
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
                    "phylogeny_child_tree_rows",
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
            elif self._is_location_mode():
                for rect_key in (
                    "location_section_rect",
                    "location_mode_rect",
                    "location_query_rect",
                    "location_start_rect",
                    "location_end_rect",
                    "location_add_rect",
                    "location_topology_place_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        shifted_rect = rect_value.move(0, -scroll_y)
                        card[rect_key] = (
                            shifted_rect.clip(content_viewport_rect)
                            if shifted_rect.colliderect(content_viewport_rect)
                            else None
                        )
                visible_rows = []
                for row in card.get("location_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is not None:
                        shifted_rect = row_rect.move(0, -scroll_y)
                        if not shifted_rect.colliderect(content_viewport_rect):
                            continue
                        row["rect"] = shifted_rect.clip(content_viewport_rect)
                    remove_rect = row.get("remove_rect")
                    if remove_rect is not None:
                        shifted_remove = remove_rect.move(0, -scroll_y)
                        row["remove_rect"] = (
                            shifted_remove.clip(content_viewport_rect)
                            if shifted_remove.colliderect(content_viewport_rect)
                            else None
                        )
                    visible_rows.append(row)
                card["location_rows"] = visible_rows
                visible_matches = []
                for row in card.get("location_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is not None:
                        shifted_rect = row_rect.move(0, -scroll_y)
                        if not shifted_rect.colliderect(content_viewport_rect):
                            continue
                        row["rect"] = shifted_rect.clip(content_viewport_rect)
                    visible_matches.append(row)
                card["location_match_rows"] = visible_matches
                card["location_topology_section_rects"] = {
                    field_key: shifted_rect.clip(content_viewport_rect)
                    for field_key, section_rect in (card.get("location_topology_section_rects") or {}).items()
                    for shifted_rect in [section_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                }
                card["location_topology_input_rects"] = {
                    field_key: shifted_rect.clip(content_viewport_rect)
                    for field_key, input_rect in (card.get("location_topology_input_rects") or {}).items()
                    for shifted_rect in [input_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                }
                card["location_topology_add_rects"] = {
                    field_key: shifted_rect.clip(content_viewport_rect)
                    for field_key, add_rect in (card.get("location_topology_add_rects") or {}).items()
                    for shifted_rect in [add_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                }
                visible_topology_rows = []
                for row in card.get("location_topology_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is not None:
                        shifted_rect = row_rect.move(0, -scroll_y)
                        if not shifted_rect.colliderect(content_viewport_rect):
                            continue
                        row["rect"] = shifted_rect.clip(content_viewport_rect)
                    remove_rect = row.get("remove_rect")
                    if remove_rect is not None:
                        shifted_remove = remove_rect.move(0, -scroll_y)
                        row["remove_rect"] = (
                            shifted_remove.clip(content_viewport_rect)
                            if shifted_remove.colliderect(content_viewport_rect)
                            else None
                        )
                    visible_topology_rows.append(row)
                card["location_topology_rows"] = visible_topology_rows
                visible_topology_matches = []
                for row in card.get("location_topology_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is not None:
                        shifted_rect = row_rect.move(0, -scroll_y)
                        if not shifted_rect.colliderect(content_viewport_rect):
                            continue
                        row["rect"] = shifted_rect.clip(content_viewport_rect)
                    visible_topology_matches.append(row)
                card["location_topology_match_rows"] = visible_topology_matches
            elif self._is_production_mode():
                for rect_key in (
                    "production_section_rect",
                    "production_group_toggle_rect",
                    "production_product_input_rect",
                    "production_product_add_rect",
                    "production_empty_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        shifted_rect = rect_value.move(0, -scroll_y)
                        card[rect_key] = (
                            shifted_rect.clip(content_viewport_rect)
                            if shifted_rect.colliderect(content_viewport_rect)
                            else None
                        )
                visible_rows = []
                for row in card.get("production_line_rows", []):
                    shifted_row = dict(row)
                    keep = False
                    for rect_key in (
                        "section_rect",
                        "location_rect",
                        "rate_rect",
                        "period_rect",
                        "start_year_rect",
                        "end_year_rect",
                        "requirements_rect",
                        "job_rect",
                        "technology_rect",
                        "employment_rect",
                        "remove_rect",
                    ):
                        rect_value = row.get(rect_key)
                        if rect_value is None:
                            shifted_row[rect_key] = None
                            continue
                        shifted_rect = rect_value.move(0, -scroll_y)
                        if shifted_rect.colliderect(content_viewport_rect):
                            shifted_row[rect_key] = shifted_rect.clip(content_viewport_rect)
                            keep = True
                        else:
                            shifted_row[rect_key] = None
                    shifted_chips = []
                    for chip in row.get("requirement_chips", []):
                        chip_rect = chip.get("rect")
                        if chip_rect is None:
                            continue
                        shifted_chip_rect = chip_rect.move(0, -scroll_y)
                        if not shifted_chip_rect.colliderect(content_viewport_rect):
                            continue
                        shifted_chip = dict(chip)
                        shifted_chip["rect"] = shifted_chip_rect.clip(content_viewport_rect)
                        shifted_chips.append(shifted_chip)
                    shifted_row["requirement_chips"] = shifted_chips
                    if keep or shifted_chips:
                        visible_rows.append(shifted_row)
                card["production_line_rows"] = visible_rows
                card["production_site_group_rows"] = [
                    {**row, "rect": shifted_rect.clip(content_viewport_rect)}
                    for row in card.get("production_site_group_rows", [])
                    for rect_value in [row.get("rect")]
                    if rect_value is not None
                    for shifted_rect in [rect_value.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                ]
                card["production_hitboxes"] = [
                    {**info, "rect": shifted_rect.clip(content_viewport_rect)}
                    for info in card.get("production_hitboxes", [])
                    for rect_value in [info.get("rect")]
                    if rect_value is not None
                    for shifted_rect in [rect_value.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                ]
                card["production_match_rows"] = [
                    {**row, "rect": shifted_rect.clip(content_viewport_rect)}
                    for row in card.get("production_match_rows", [])
                    for rect_value in [row.get("rect")]
                    if rect_value is not None
                    for shifted_rect in [rect_value.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                ]
            elif self._is_site_mode():
                card["site_section_rects"] = {
                    label: shifted_rect.clip(content_viewport_rect)
                    for label, section_rect in (card.get("site_section_rects") or {}).items()
                    for shifted_rect in [section_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                }
                visible_rows = []
                for row in card.get("site_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    shifted_rect = row_rect.move(0, -scroll_y)
                    if not shifted_rect.colliderect(content_viewport_rect):
                        continue
                    shifted_row = dict(row)
                    shifted_row["rect"] = shifted_rect.clip(content_viewport_rect)
                    visible_rows.append(shifted_row)
                card["site_rows"] = visible_rows
            elif self._is_person_quotes_mode():
                for rect_key in ("person_quote_section_rect", "person_quote_add_rect", "person_quote_empty_rect"):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        shifted_rect = rect_value.move(0, -scroll_y)
                        card[rect_key] = (
                            shifted_rect.clip(content_viewport_rect)
                            if shifted_rect.colliderect(content_viewport_rect)
                            else None
                        )
                card["person_quote_input_rects"] = {
                    field_key: shifted_rect.clip(content_viewport_rect)
                    for field_key, input_rect in (card.get("person_quote_input_rects") or {}).items()
                    for shifted_rect in [input_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                }
                card["person_quote_mode_hitboxes"] = [
                    (mode_id, shifted_rect.clip(content_viewport_rect))
                    for mode_id, mode_rect in card.get("person_quote_mode_hitboxes", [])
                    for shifted_rect in [mode_rect.move(0, -scroll_y)]
                    if shifted_rect.colliderect(content_viewport_rect)
                ]
                visible_rows = []
                for row in card.get("person_quote_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    shifted_rect = row_rect.move(0, -scroll_y)
                    if not shifted_rect.colliderect(content_viewport_rect):
                        continue
                    shifted_row = dict(row)
                    shifted_row["rect"] = shifted_rect.clip(content_viewport_rect)
                    remove_rect = row.get("remove_rect")
                    if remove_rect is not None:
                        shifted_remove = remove_rect.move(0, -scroll_y)
                        shifted_row["remove_rect"] = (
                            shifted_remove.clip(content_viewport_rect)
                            if shifted_remove.colliderect(content_viewport_rect)
                            else None
                        )
                    visible_rows.append(shifted_row)
                card["person_quote_rows"] = visible_rows

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
            media_asset_quick_hitboxes = [
                (asset_role, button_rect.clip(content_viewport_rect))
                for asset_role, button_rect in media_asset_quick_hitboxes
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
            elif self._is_location_mode():
                for rect_key in (
                    "location_section_rect",
                    "location_mode_rect",
                    "location_query_rect",
                    "location_start_rect",
                    "location_end_rect",
                    "location_add_rect",
                    "location_topology_place_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        card[rect_key] = (
                            rect_value.clip(content_viewport_rect)
                            if rect_value.colliderect(content_viewport_rect)
                            else None
                        )
                card["location_rows"] = [
                    row
                    for row in card.get("location_rows", [])
                    if row.get("rect") is None or row["rect"].colliderect(content_viewport_rect)
                ]
                card["location_match_rows"] = [
                    row
                    for row in card.get("location_match_rows", [])
                    if row.get("rect") is None or row["rect"].colliderect(content_viewport_rect)
                ]
                card["location_topology_section_rects"] = {
                    field_key: section_rect.clip(content_viewport_rect)
                    for field_key, section_rect in (card.get("location_topology_section_rects") or {}).items()
                    if section_rect.colliderect(content_viewport_rect)
                }
                card["location_topology_input_rects"] = {
                    field_key: input_rect.clip(content_viewport_rect)
                    for field_key, input_rect in (card.get("location_topology_input_rects") or {}).items()
                    if input_rect.colliderect(content_viewport_rect)
                }
                card["location_topology_add_rects"] = {
                    field_key: add_rect.clip(content_viewport_rect)
                    for field_key, add_rect in (card.get("location_topology_add_rects") or {}).items()
                    if add_rect.colliderect(content_viewport_rect)
                }
                card["location_topology_rows"] = [
                    row
                    for row in card.get("location_topology_rows", [])
                    if row.get("rect") is None or row["rect"].colliderect(content_viewport_rect)
                ]
                card["location_topology_match_rows"] = [
                    row
                    for row in card.get("location_topology_match_rows", [])
                    if row.get("rect") is None or row["rect"].colliderect(content_viewport_rect)
                ]
            elif self._is_production_mode():
                for rect_key in (
                    "production_section_rect",
                    "production_group_toggle_rect",
                    "production_product_input_rect",
                    "production_product_add_rect",
                    "production_empty_rect",
                ):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        card[rect_key] = (
                            rect_value.clip(content_viewport_rect)
                            if rect_value.colliderect(content_viewport_rect)
                            else None
                        )
                card["production_line_rows"] = [
                    row
                    for row in card.get("production_line_rows", [])
                    if any(
                        row.get(rect_key) is not None and row[rect_key].colliderect(content_viewport_rect)
                        for rect_key in (
                            "section_rect",
                            "location_rect",
                            "rate_rect",
                            "period_rect",
                            "start_year_rect",
                            "end_year_rect",
                            "requirements_rect",
                            "job_rect",
                            "technology_rect",
                            "employment_rect",
                        )
                    )
                ]
                card["production_site_group_rows"] = [
                    {**row, "rect": row["rect"].clip(content_viewport_rect)}
                    for row in card.get("production_site_group_rows", [])
                    if row.get("rect") is not None and row["rect"].colliderect(content_viewport_rect)
                ]
                card["production_hitboxes"] = [
                    {**info, "rect": info["rect"].clip(content_viewport_rect)}
                    for info in card.get("production_hitboxes", [])
                    if info.get("rect") is not None and info["rect"].colliderect(content_viewport_rect)
                ]
                card["production_match_rows"] = [
                    {**row, "rect": row["rect"].clip(content_viewport_rect)}
                    for row in card.get("production_match_rows", [])
                    if row.get("rect") is not None and row["rect"].colliderect(content_viewport_rect)
                ]
            elif self._is_site_mode():
                card["site_section_rects"] = {
                    label: section_rect.clip(content_viewport_rect)
                    for label, section_rect in (card.get("site_section_rects") or {}).items()
                    if section_rect is not None and section_rect.colliderect(content_viewport_rect)
                }
                card["site_rows"] = [
                    {**row, "rect": row["rect"].clip(content_viewport_rect)}
                    for row in card.get("site_rows", [])
                    if row.get("rect") is not None and row["rect"].colliderect(content_viewport_rect)
                ]
            elif self._is_person_quotes_mode():
                for rect_key in ("person_quote_section_rect", "person_quote_add_rect", "person_quote_empty_rect"):
                    rect_value = card.get(rect_key)
                    if rect_value is not None:
                        card[rect_key] = (
                            rect_value.clip(content_viewport_rect)
                            if rect_value.colliderect(content_viewport_rect)
                            else None
                        )
                card["person_quote_input_rects"] = {
                    field_key: input_rect.clip(content_viewport_rect)
                    for field_key, input_rect in (card.get("person_quote_input_rects") or {}).items()
                    if input_rect is not None and input_rect.colliderect(content_viewport_rect)
                }
                card["person_quote_mode_hitboxes"] = [
                    (mode_id, mode_rect.clip(content_viewport_rect))
                    for mode_id, mode_rect in card.get("person_quote_mode_hitboxes", [])
                    if mode_rect is not None and mode_rect.colliderect(content_viewport_rect)
                ]
                card["person_quote_rows"] = [
                    {
                        **row,
                        "rect": row["rect"].clip(content_viewport_rect),
                        "remove_rect": (
                            row["remove_rect"].clip(content_viewport_rect)
                            if row.get("remove_rect") is not None
                            and row["remove_rect"].colliderect(content_viewport_rect)
                            else None
                        ),
                    }
                    for row in card.get("person_quote_rows", [])
                    if row.get("rect") is not None and row["rect"].colliderect(content_viewport_rect)
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

        if self._is_extant_mode():
            for row in card.get("extant_rows", []):
                relation_info = row.get("relation_info")
                row_rect = row.get("rect")
                if relation_info is None or row_rect is None or not row_rect.colliderect(content_viewport_rect):
                    continue
                relation_hitboxes.append((relation_info, row_rect.clip(content_viewport_rect)))
        elif not self._is_general_mode():
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
                if tool.get("kind") == "color_picker" and tool.get("color_field"):
                    # A single domain-data color field (e.g. a material's map
                    # color) has no body/header/wiki roles to switch between --
                    # a shorter row with just the swatch and H/S/V sliders.
                    row_h = 92
                    row_rect = pygame.Rect(tool_inner_x, tool_y, tool_inner_w, row_h)
                    preview_rect = pygame.Rect(row_rect.x + 6, row_rect.y + 24, 28, 28)
                    slider_rects = []
                    slider_x = row_rect.x + 28
                    slider_w = row_rect.width - 36
                    for slider_index, (channel, label) in enumerate(self.CARD_COLOR_SLIDERS):
                        slider_rect = pygame.Rect(
                            slider_x,
                            row_rect.y + 56 + slider_index * 15,
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
                            "role_rects": [],
                            "slider_rects": slider_rects,
                            "description_lines": [],
                        }
                    )
                    tool_y = row_rect.bottom + 8
                    continue

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
        card["tag_bar_rect"] = tag_bar_rect
        card["tag_chip_hitboxes"] = []
        card["tag_suggestion_hitboxes"] = []
        card["tag_remove_hitboxes"] = []
        card["timeline_snapshot_rect"] = timeline_snapshot_rect
        card["timeline_snapshot_chip_hitboxes"] = timeline_snapshot_chip_hitboxes
        card["task_checklist_rect"] = task_checklist_rect
        card["task_finish_checkbox_rect"] = task_finish_checkbox_rect
        card["task_checklist_hitboxes"] = task_checklist_hitboxes
        card["task_checklist_input_rect"] = task_checklist_input_rect
        if not self._is_person_quotes_mode():
            card["person_quote_section_rect"] = person_quote_section_rect
            card["person_quote_input_rects"] = person_quote_input_rects
            card["person_quote_mode_hitboxes"] = person_quote_mode_hitboxes
            card["person_quote_add_rect"] = person_quote_add_rect
            card["person_quote_rows"] = person_quote_rows
            card["person_quote_empty_rect"] = person_quote_empty_rect
        card["timeline_label_y"] = timeline_label_y
        card["snapshot_timeline_lane_count"] = snapshot_timeline_lane_count
        card["snapshot_timeline_lane_height"] = snapshot_timeline_lane_height
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["launch_mode_hitboxes"] = launch_mode_hitboxes
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["corner_handle_rects"] = corner_handle_rects
        card["section_hitboxes"] = section_hitboxes
        card["section_draw_rects"] = section_draw_rects
        card["media_import_hitboxes"] = media_import_hitboxes
        card["media_pixel_art_hitboxes"] = media_pixel_art_hitboxes
        card["media_asset_quick_hitboxes"] = media_asset_quick_hitboxes
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
        card["template_button_rect"] = template_button_rect
        card["relation_tree_rect"] = relation_tree_rect
        card["header_icon_ref"] = header_icon_ref
        card["header_icon_rect"] = header_icon_rect
        card["time_anchor_rect"] = time_anchor_rect
        card["delete_rect"] = delete_rect
        card["close_rect"] = close_rect
        card["title_edit_rect"] = title_edit_rect
        card["header_description_rect"] = header_description_rect
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
        timeline_chip_h = self._timeline_snapshot_chip_lane_count(
            card, font, int(card.get("canvas_w", 420)),
        ) * 23

        if self._is_general_mode():
            content_rect = pygame.Rect(0, 0, int(card.get("canvas_w", 420)) - 24, 0)
            general_h = CardWikiRenderer.measure_content(
                self._get_general_wiki_text(card),
                font,
                content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
            )
            if self._timeline_snapshot_display_entries(card):
                general_h += 8 + max(
                    58,
                    self._measure_timeline_snapshot_blocks_height(
                        card, font, content_rect.width,
                    ),
                )
            if self._is_task_card():
                general_h += 8 + self._measure_task_checklist_height(
                    font,
                    content_rect.width,
                    card,
                )
            tag_bar_h = 92 if card.get("is_edit_mode", False) and card.get("active_edit_field") == "tags" else 34
            general_h += tag_bar_h + 8
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            timeline_label_y = tabs_bottom_y + 10 + general_h + 8
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(320, resize_bottom + 8)

        if self._is_extant_mode():
            entries = self._extant_entries()
            visible_entry_count = min(10, len(entries))
            group_count = min(
                6,
                len({
                    str(entity.get("_dataset") or entity.get("type") or "entries")
                    for entity in entries
                }),
            )
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            current_y = tabs_bottom_y + 10 + 38 + group_count * 33 + visible_entry_count * 31
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(380, min(620, resize_bottom + 8))

        if self._is_phylogeny_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            current_y = tabs_bottom_y + 10
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP
            if not self.collapsed_sections.get("Phylogeny Parents", False):
                current_y += self.PHYLOGENY_PARENT_PANEL_H + 16
            else:
                current_y += 8

            current_y += self.SECTION_HEADER_H + self.SECTION_GAP
            if not self.collapsed_sections.get("Phylogeny Children", False):
                line_h = self._phylogeny_line_height(font)
                visible_children = max(
                    1,
                    self._phylogeny_children_count(
                        str(self.entity.get("id") or "")
                    ),
                )
                current_y += visible_children * (line_h + 13)

            current_y += self.SECTION_HEADER_H + self.SECTION_GAP
            if not self.collapsed_sections.get("Members", False):
                line_h = self._phylogeny_line_height(font)
                limit_key = "phylogeny_clade_member_limit" if self._is_cladistics_card() else "phylogeny_species_relative_limit"
                visible_rows = max(1, int(card.get(limit_key, 3 if self._is_cladistics_card() else 4) or 1))
                current_y += visible_rows * (line_h + 13)
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(360, resize_bottom + 8)

        if self._is_location_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            if self._is_location_card():
                topology_rows = sum(max(1, len(self._location_topology_ids(self.entity, field_key))) for field_key in self.LOCATION_TOPOLOGY_FIELDS)
                input_h = 34 * len(self.LOCATION_TOPOLOGY_EDITABLE_FIELDS) if card.get("is_edit_mode", False) else 0
                current_y = tabs_bottom_y + 10 + len(self.LOCATION_TOPOLOGY_FIELDS) * (self.SECTION_HEADER_H + self.SECTION_GAP + 10)
                current_y += topology_rows * 40 + input_h
            else:
                entries_h = max(34, len(self._location_history_entries()) * 44)
                input_h = 86 if card.get("is_edit_mode", False) else 0
                current_y = tabs_bottom_y + 10 + self.SECTION_HEADER_H + self.SECTION_GAP + 4 + 24 + 6 + entries_h + input_h
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(340, resize_bottom + 8)

        if self._is_production_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            current_y = tabs_bottom_y + 10 + self.SECTION_HEADER_H + self.SECTION_GAP + 6
            if card.get("is_edit_mode", False):
                current_y += 24 + 4
                if card.get("production_input_active") and card.get("production_active_field") == "product":
                    current_y += min(5, len(card.get("production_matches") or [])) * 24
                current_y += 8
            lines = self._production_lines()
            if not lines:
                current_y += 34 + 8
            else:
                for line_index, line in enumerate(lines):
                    current_y += 30 + 4 + 26 + 4 + 24 + 4 + 24 + 4 + 24 + 8
                    requirement_count = len(self._production_requirement_items(line.get("product_id")))
                    if requirement_count:
                        current_y += max(1, (requirement_count + 1) // 2) * 24 + 8
                    if (
                        card.get("production_input_active")
                        and card.get("production_active_line") == line_index
                        and card.get("production_active_field") == "location"
                    ):
                        current_y += min(5, len(card.get("production_matches") or [])) * 24 + 4
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(360, resize_bottom + 8)

        if self._is_site_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            reports = (self._site_requirement_report() or {}).get("production", [])
            operator_count = max(1, len(self._relation_entity_ids(self.entity.get("operated_by"))))
            condition_count = len(self.entity.get("site_conditions") or [])
            requirement_count = sum(max(1, len(report.get("checks") or [])) + 1 for report in reports)
            row_count = 2 + operator_count + condition_count + max(1, requirement_count)
            current_y = tabs_bottom_y + 10 + 2 * (self.SECTION_HEADER_H + self.SECTION_GAP + 4) + row_count * 30
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(340, resize_bottom + 8)

        if self._is_person_quotes_mode():
            tabs_bottom_y = self.HEADER_H + 6 + self.TAB_H
            if self._active_subtab_order():
                tabs_bottom_y += 5 + self.SUBTAB_H
            content_w = max(120, int(card.get("canvas_w", 420)) - 24)
            current_y = tabs_bottom_y + 10 + self._measure_person_quotes_height(font, content_w, card)
            timeline_label_y = current_y + 12
            timeline_y = timeline_label_y + 18 + timeline_chip_h
            center_y = timeline_y + 10
            launch_top = center_y + self.TIMELINE_TO_LAUNCH_GAP
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(340, resize_bottom + 8)

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
        timeline_y = timeline_label_y + 18 + timeline_chip_h
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

        # header_drag_rect is intentionally cleared by
        # ui_manager.scrub_floating_card_hitboxes() every frame the floating
        # entity card is open (it doubles as a drag-hitbox that feature
        # deliberately disables) -- draw must not assume it survives that
        # scrub, since scrub runs after relayout and before this call.
        header_rect = card.get("header_drag_rect") or pygame.Rect(
            rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H,
        )
        pygame.draw.rect(screen, card_header_color, header_rect)
        pygame.draw.line(
            screen,
            (110, 110, 120),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        title_text = card.get("title", "")
        header_description = self._header_description_text()
        if card.get("is_edit_mode", False):
            title_edit_rect = card.get("title_edit_rect")
            description_edit_rect = card.get("header_description_rect")
            title_active = card.get("active_edit_field") == self._title_edit_field()
            description_active = card.get("active_edit_field") == self._header_description_edit_field()
            if title_edit_rect is not None:
                title_fill = (48, 54, 68) if title_active else (38, 43, 56)
                title_border = (182, 202, 236) if title_active else (92, 104, 128)
                pygame.draw.rect(screen, title_fill, title_edit_rect)
                pygame.draw.rect(screen, title_border, title_edit_rect, 1)
            if description_edit_rect is not None:
                description_fill = (48, 54, 68) if description_active else (36, 41, 54)
                description_border = (182, 202, 236) if description_active else (82, 94, 118)
                pygame.draw.rect(screen, description_fill, description_edit_rect)
                pygame.draw.rect(screen, description_border, description_edit_rect, 1)
            if title_active:
                title_text = card.get("edit_buffer", "")
            if description_active:
                header_description = card.get("edit_buffer", "")

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
        if card.get("has_unsaved_draft") and not card.get("is_edit_mode", False):
            title_text = f"{title_text}  • UNSAVED"
        title_surface = font.render(self._ellipsize_text(title_text, font, title_max_w), True, header_text_color)
        subtitle_max_w = title_max_w
        description_surface = None
        if header_description or card.get("is_edit_mode", False):
            description_text = header_description or "description"
            description_surface = font.render(
                self._ellipsize_text(description_text, font, subtitle_max_w),
                True,
                header_muted_color if header_description else self._mix_color(header_muted_color, card_header_color, 0.45),
            )
        subtitle_surface = font.render(
            self._ellipsize_text(card["subtitle"], font, subtitle_max_w),
            True,
            header_muted_color,
        )
        screen.blit(title_surface, (title_x, rect.y + 10))
        if description_surface is not None:
            screen.blit(description_surface, (subtitle_x, rect.y + 29))
        if type_label_rect is not None:
            hover_pos = pygame.mouse.get_pos()
            if card.get("is_edit_mode", False) and type_label_rect.collidepoint(hover_pos):
                pygame.draw.rect(screen, (42, 48, 62), type_label_rect)
                pygame.draw.rect(screen, (130, 150, 190), type_label_rect, 1)
        subtitle_y = rect.y + (47 if (header_description or card.get("is_edit_mode", False)) else 30)
        screen.blit(subtitle_surface, (subtitle_x, subtitle_y))

        edit_toggle_rect = card.get("edit_toggle_rect")
        idea_button_rect = card.get("idea_button_rect")
        template_button_rect = card.get("template_button_rect")
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

        if template_button_rect is not None:
            pygame.draw.rect(screen, (54, 50, 66), template_button_rect)
            pygame.draw.rect(screen, (176, 160, 210), template_button_rect, 1)
            template_text = font.render("T", True, (238, 230, 255))
            template_text_rect = template_text.get_rect(center=template_button_rect.center)
            screen.blit(template_text, template_text_rect)

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
            active_quote_field = card.get("person_quote_active_field")
            if card.get("delete_confirm_active", False):
                edit_status = "Confirm delete | Click ! again to remove this entry | Esc cancel"
            elif card.get("timeline_reanchor_active", False):
                edit_status = "Reanchoring card | Click timeline to set | Esc cancel"
            elif self._is_person_quotes_mode() and active_quote_field:
                quote_field_label = self.PERSON_QUOTE_FIELD_LABELS.get(active_quote_field, "Quote")
                if self._is_person_quote_wiki_field(active_quote_field):
                    edit_status = f"Editing {quote_field_label} | Enter newline | Ctrl+Enter add | Tab next"
                else:
                    edit_status = f"Editing {quote_field_label} | Ctrl+Enter add | Tab next | Esc blur"
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
        elif self._is_extant_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_extant_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
        elif self._is_person_quotes_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_person_quotes_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
        elif self._is_phylogeny_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_phylogeny_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
        elif self._is_location_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_location_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
        elif self._is_production_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_production_content(screen, font, card)
            finally:
                screen.set_clip(previous_clip)
        elif self._is_site_mode():
            content_clip = card.get("content_viewport_rect")
            previous_clip = screen.get_clip()
            if content_clip is not None:
                screen.set_clip(previous_clip.clip(content_clip))
            try:
                self._draw_site_content(screen, font, card)
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

        existence_period = self._entity_existence_period()
        random_year_rect = None
        if existence_period is not None and rect.width >= 140:
            button_w = max(20, font.size("R")[0] + 12)
            random_year_rect = pygame.Rect(
                rect.right - 12 - button_w,
                timeline_label_y - 1,
                button_w,
                font_h + 2,
            )
        card["random_year_rect"] = random_year_rect

        label_fits_above_line = timeline_label_y + font_h <= center_y - 4
        if label_fits_above_line and rect.width >= 180:
            label_right = random_year_rect.x - 6 if random_year_rect is not None else rect.right - 12
            timeline_label = self._ellipsize_text(
                timeline_label,
                font,
                max(20, label_right - (rect.x + 12)),
            )
            timeline_label_surface = font.render(timeline_label, True, body_text_color)
            screen.blit(timeline_label_surface, (rect.x + 12, timeline_label_y))
        if random_year_rect is not None:
            pygame.draw.rect(screen, (38, 47, 64), random_year_rect)
            pygame.draw.rect(screen, (132, 156, 194), random_year_rect, 1)
            random_surface = font.render("R", True, (226, 236, 250))
            screen.blit(random_surface, random_surface.get_rect(center=random_year_rect.center))

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)
        card["timeline_snapshot_timeline_hitboxes"] = []
        snapshot_timeline_entries = self._timeline_snapshot_timeline_entries()
        card_range = self._card_timeline_range(card)
        if snapshot_timeline_entries and card_range is not None:
            range_start, range_end = card_range
            range_span = max(1, range_end - range_start)
            chip_x = left_x
            chip_y = timeline_label_y + font_h + 3
            chip_h = 19
            lane_step = 23
            active_range = card.get("working_year_range")
            if isinstance(active_range, (list, tuple)) and len(active_range) == 2:
                try:
                    active_range = (int(active_range[0]), int(active_range[1]))
                except (TypeError, ValueError):
                    active_range = None
            else:
                active_range = None

            for entry in snapshot_timeline_entries:
                period_label = self._timeline_snapshot_period_label(entry)
                chip_w = max(44, font.size(period_label)[0] + 16)
                if chip_x > left_x and chip_x + chip_w > right_x:
                    chip_x = left_x
                    chip_y += lane_step
                chip_rect = pygame.Rect(chip_x, chip_y, min(chip_w, right_x - left_x), chip_h)
                point_year = (entry["start_year"] + entry["end_year"]) / 2.0
                ratio = max(0.0, min(1.0, (point_year - range_start) / float(range_span)))
                marker_x = left_x + int(round((right_x - left_x) * ratio))
                selected = active_range == (entry["start_year"], entry["end_year"])
                fill = (68, 92, 130) if selected else (38, 47, 64)
                border = (190, 218, 250) if selected else (112, 136, 170)
                text_color = (244, 248, 255) if selected else (206, 220, 240)
                pygame.draw.line(
                    screen,
                    border,
                    (chip_rect.centerx, chip_rect.bottom),
                    (marker_x, center_y - 2),
                    1,
                )
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                chip_surface = font.render(period_label, True, text_color)
                screen.blit(chip_surface, chip_surface.get_rect(center=chip_rect.center))
                pygame.draw.rect(screen, fill, pygame.Rect(marker_x - 3, center_y - 3, 7, 7))
                pygame.draw.rect(screen, border, pygame.Rect(marker_x - 3, center_y - 3, 7, 7), 1)
                card["timeline_snapshot_timeline_hitboxes"].append({
                    "start_year": entry["start_year"],
                    "end_year": entry["end_year"],
                    "rect": chip_rect,
                })
                chip_x = chip_rect.right + 5

        year_label_rects = []
        year_label_y = center_y + 22
        show_year_labels = (
            not compact_timeline
            and year_label_y + font_h <= launch_rect.y - 4
            and rect.width >= 260
        )
        selected_year = card.get("selected_year")
        year_commentaries = self._timeline_year_commentaries()
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

            if show_year_labels and year in year_commentaries:
                note = " / ".join(year_commentaries[year])
                note_surface = font.render(self._ellipsize_text(note, font, 130), True, (198, 214, 238))
                note_x = max(left_x, min(hitbox.centerx - note_surface.get_width() // 2, right_x - note_surface.get_width()))
                note_y = year_label_y + font_h
                note_rect = pygame.Rect(note_x, note_y, note_surface.get_width(), note_surface.get_height())
                if note_rect.bottom <= launch_rect.y - 4 and not any(note_rect.inflate(4, 0).colliderect(existing) for existing in year_label_rects):
                    screen.blit(note_surface, note_rect)
                    year_label_rects.append(note_rect)

        temporal_periods = self._temporal_period_timeline_entries(card)
        related_entries = self._related_timeline_entries(card)
        card_range = self._card_timeline_range(card)
        card["temporal_period_hitboxes"] = []
        card["temporal_period_click_rect"] = None
        card["temporal_period_click_context"] = None
        show_bottom_timeline = (
            not compact_timeline
            and center_y + self.RELATED_TIMELINE_OFFSET_Y + font_h + 8 <= launch_rect.y
            and rect.width >= 300
        )
        if show_bottom_timeline and card_range is not None and (temporal_periods or card.get("is_edit_mode", False)):
            range_start, range_end = card_range
            range_span = max(1, range_end - range_start)

            def related_year_x(year):
                if range_end == range_start:
                    return (left_x + right_x) // 2
                ratio = (year - range_start) / float(range_span)
                ratio = max(0.0, min(1.0, ratio))
                return left_x + int(round((right_x - left_x) * ratio))

            related_y = center_y + self.RELATED_TIMELINE_OFFSET_Y
            card["temporal_period_click_rect"] = pygame.Rect(left_x, related_y - 10, max(1, right_x - left_x), max(24, font_h + 18))
            card["temporal_period_click_context"] = {
                "left_x": left_x,
                "right_x": right_x,
                "start_year": range_start,
                "end_year": range_end,
            }
            pygame.draw.line(screen, (66, 88, 108), (left_x, related_y), (right_x, related_y), 1)
            pending_start = card.get("pending_temporal_period_start")
            if pending_start is not None:
                pending_x = related_year_x(self._coerce_timeline_year(pending_start) or range_start)
                pygame.draw.line(screen, (232, 210, 148), (pending_x, related_y - 8), (pending_x, related_y + 8), 2)
                pending_label = font.render("period start", True, (232, 210, 148))
                screen.blit(pending_label, (max(left_x, min(pending_x + 4, right_x - pending_label.get_width())), related_y - font_h - 2))

            label_rects = []
            visible_periods = temporal_periods[:self.RELATED_TIMELINE_LABEL_LIMIT]
            for lane, entry in enumerate(visible_periods[:2]):
                x1 = related_year_x(entry["start_year"])
                x2 = related_year_x(entry["end_year"])
                band_y = related_y + lane * (font_h + 4)
                bar_rect = pygame.Rect(min(x1, x2), band_y - 3, max(6, abs(x2 - x1)), 7)
                card["temporal_period_hitboxes"].append((entry, bar_rect.inflate(4, 8)))
                pygame.draw.rect(screen, (72, 106, 134), bar_rect)
                pygame.draw.rect(screen, (132, 184, 214), bar_rect, 1)
                label = entry.get("commentary") or entry["label"]
                label_surface = font.render(self._ellipsize_text(label, font, max(140, rect.width // 2)), True, (184, 220, 238))
                label_x = max(left_x, min(bar_rect.centerx - label_surface.get_width() // 2, right_x - label_surface.get_width()))
                label_rect = pygame.Rect(label_x, band_y + 4, label_surface.get_width(), label_surface.get_height())
                if label_rect.bottom <= launch_rect.y - 4 and not any(label_rect.inflate(4, 0).colliderect(existing) for existing in label_rects):
                    screen.blit(label_surface, label_rect)
                    label_rects.append(label_rect)
                endpoint_labels = [
                    (entry.get("predecessor"), x1, "|_"),
                    (entry.get("successor"), x2, "_|"),
                ]
                for endpoint_id, endpoint_x, marker in endpoint_labels:
                    endpoint_id = str(endpoint_id or "").strip()
                    if not endpoint_id:
                        continue
                    endpoint_text = self._ellipsize_text(f"{marker} {endpoint_id}", font, 92)
                    endpoint_surface = font.render(endpoint_text, True, (198, 214, 238))
                    endpoint_x = max(left_x, min(endpoint_x - endpoint_surface.get_width() // 2, right_x - endpoint_surface.get_width()))
                    endpoint_rect = pygame.Rect(endpoint_x, band_y + font_h + 4, endpoint_surface.get_width(), endpoint_surface.get_height())
                    if endpoint_rect.bottom <= launch_rect.y - 4 and not any(endpoint_rect.inflate(4, 0).colliderect(existing) for existing in label_rects):
                        screen.blit(endpoint_surface, endpoint_rect)
                        label_rects.append(endpoint_rect)
            if not temporal_periods and card.get("is_edit_mode", False):
                hint = str(card.get("timeline_period_status") or "click start, click end to add period")
                hint_surface = font.render(self._ellipsize_text(hint, font, max(80, right_x - left_x)), True, (132, 184, 214))
                screen.blit(hint_surface, (left_x, related_y + 5))

        if show_bottom_timeline and related_entries and card_range is not None and not temporal_periods and not card.get("is_edit_mode", False):
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

        launch_mode_hitboxes = card.get("launch_mode_hitboxes", [])
        if launch_mode_hitboxes:
            mouse_pos = pygame.mouse.get_pos()
            for option, mode_rect in launch_mode_hitboxes:
                hovered = mode_rect.collidepoint(mouse_pos)
                fill = (70, 82, 104) if hovered else (52, 58, 72)
                pygame.draw.rect(screen, fill, mode_rect)
                pygame.draw.rect(screen, (176, 190, 216), mode_rect, 1)
                launch_label = self._ellipsize_text(option.get("label", "Open"), font, mode_rect.width - 8)
                launch_text = font.render(launch_label, True, (245, 245, 245))
                launch_text_rect = launch_text.get_rect(center=mode_rect.center)
                screen.blit(launch_text, launch_text_rect)
        else:
            pygame.draw.rect(screen, (55, 55, 55), launch_rect)
            pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
            launch_options = self._launch_mode_options()
            launch_label = str(launch_options[0].get("label") or "Launch") if len(launch_options) == 1 else "Launch"
            if launch_label == "Launch" and selected_year is not None:
                launch_label = f"Launch [{selected_year}]"
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
            if tool.get("kind") == "color_picker" and tool.get("color_field"):
                color_field = tool.get("color_field")
                label = self._ellipsize_text(tool.get("label", "Color"), font, row_rect.width - 12)
                label_surface = font.render(label, True, (230, 236, 246))
                screen.blit(label_surface, (row_rect.x + 6, row_rect.y + 5))
                current_color = self._card_background_color(color_field=color_field)
                hue, saturation, brightness = self._card_hsv(color_field=color_field)
                preview_rect = row.get("preview_rect")
                if preview_rect is not None:
                    pygame.draw.rect(screen, current_color, preview_rect)
                    pygame.draw.rect(screen, (218, 226, 240), preview_rect, 1)
                hex_label = self._rgb_to_hex(current_color)
                hex_surface = font.render(hex_label, True, (176, 186, 204))
                screen.blit(hex_surface, (row_rect.x + 40, row_rect.y + 30))

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
        timing_started = time.perf_counter() if performance_debug.enabled else None
        width = max(1, rect.width)
        height = max(1, rect.height)
        if channel == "h":
            dependencies = ()
        elif channel == "s":
            dependencies = (round(float(hue), 6), round(max(0.25, float(brightness)), 6))
        else:
            dependencies = (round(float(hue), 6), round(float(saturation), 6))
        cache_key = (width, height, channel, dependencies)
        track = self.COLOR_SLIDER_SURFACE_CACHE.get(cache_key)
        if track is not None:
            screen.blit(track, rect.topleft)
            if timing_started is not None:
                performance_debug.record(
                    "color.gradient",
                    (time.perf_counter() - timing_started) * 1000.0,
                    f"channel={channel} cache=hit",
                )
            return

        track = pygame.Surface((width, height))
        for offset in range(width):
            value = offset / max(1, width - 1)
            if channel == "h":
                color = self._hsv_to_rgb(value, 1.0, 1.0)
            elif channel == "s":
                color = self._hsv_to_rgb(hue, value, max(0.25, brightness))
            else:
                color = self._hsv_to_rgb(hue, saturation, value)
            pygame.draw.line(track, color, (offset, 0), (offset, height - 1))

        self.COLOR_SLIDER_SURFACE_CACHE[cache_key] = track
        while len(self.COLOR_SLIDER_SURFACE_CACHE) > self.MAX_COLOR_SLIDER_CACHE_ITEMS:
            self.COLOR_SLIDER_SURFACE_CACHE.pop(next(iter(self.COLOR_SLIDER_SURFACE_CACHE)))
        screen.blit(track, rect.topleft)
        if timing_started is not None:
            performance_debug.record(
                "color.gradient",
                (time.perf_counter() - timing_started) * 1000.0,
                f"channel={channel} cache=miss width={width}",
            )

    def _draw_tabs(self, screen, font, card):
        for tab_index, (tab_name, tab_rect) in enumerate(card.get("tab_hitboxes", [])):
            selected = tab_name == self.active_tab
            fill, border, text_color = self._card_button_palette(tab_index, selected=selected)

            pygame.draw.rect(screen, fill, tab_rect)
            pygame.draw.rect(screen, border, tab_rect, 1)

            label = self.TAB_LABELS.get(tab_name, tab_name.title())
            abbreviations = {
                "general": "Gen",
                "overview": "Over",
                "temporal": "Temp",
                "location": "Loc",
                "relations": "Rel",
                "phylogeny": "Phylo",
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
        for subtab_index, (tab_name, subtab_name, subtab_rect) in enumerate(card.get("subtab_hitboxes", [])):
            if tab_name != self.active_tab:
                continue

            selected = tab_name == "simulation" and subtab_name == self.active_simulation_subtab
            fill, border, text_color = self._card_button_palette(subtab_index, selected=selected)

            pygame.draw.rect(screen, fill, subtab_rect)
            pygame.draw.rect(screen, border, subtab_rect, 1)

            label = self.SIMULATION_SUBTAB_LABELS.get(subtab_name, subtab_name.title())
            if font.size(label)[0] > subtab_rect.width - 8:
                abbreviations = {
                    "space": "Space",
                    "map": "Map",
                    "world_gen": "World",
                    "materials": "Mat",
                    "plant_ecology": "Plant",
                    "quotes": "Quote",
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
        cache_key = (id(image_surface), target_w, target_h)
        scaled = self.SCALED_PREVIEW_CACHE.get(cache_key)
        if scaled is None:
            if len(self.SCALED_PREVIEW_CACHE) >= self.MAX_IMAGE_CACHE_ITEMS:
                self.SCALED_PREVIEW_CACHE.clear()
            scaled = pygame.transform.smoothscale(image_surface, (target_w, target_h))
            self.SCALED_PREVIEW_CACHE[cache_key] = scaled
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

        quick_buttons = {
            asset_role: button_rect
            for asset_role, button_rect in card.get("media_asset_quick_hitboxes", [])
        }
        if quick_buttons:
            quick_labels = dict(self.PLANT_ASSET_QUICK_ACTIONS)
            for asset_role, button_rect in quick_buttons.items():
                hovered = button_rect.collidepoint(pygame.mouse.get_pos())
                fill = (68, 88, 120) if hovered else (48, 60, 82)
                pygame.draw.rect(screen, fill, button_rect)
                pygame.draw.rect(screen, (166, 190, 224), button_rect, 1)
                label = font.render(quick_labels.get(asset_role, asset_role.title()), True, (242, 246, 252))
                screen.blit(label, label.get_rect(center=button_rect.center))

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

    def _draw_material_model_value(self, screen, font, value_rect, model):
        items = self._material_model_items(model)
        line_h = self._table_line_height(font)
        current_y = value_rect.y + self.TABLE_ROW_PAD_Y
        swatch_size = max(8, min(12, line_h - 4))

        if not items:
            label = str(model.get("status") or "No inferred materials")
            surface = font.render(self._ellipsize_text(label, font, value_rect.width - 4), True, (180, 180, 180))
            screen.blit(surface, (value_rect.x + 2, current_y))
            return

        for item in items:
            if current_y + line_h > value_rect.bottom:
                break
            swatch_rect = pygame.Rect(
                value_rect.x + 2,
                current_y + max(1, (line_h - swatch_size) // 2),
                swatch_size,
                swatch_size,
            )
            pygame.draw.rect(screen, self._material_item_color(item), swatch_rect)
            pygame.draw.rect(screen, (224, 224, 216), swatch_rect, 1)
            label = self._material_item_line(item)
            text_x = swatch_rect.right + 7
            text_max_w = max(20, value_rect.right - text_x - 4)
            text_surface = font.render(
                self._ellipsize_text(label, font, text_max_w),
                True,
                (210, 218, 232),
            )
            screen.blit(text_surface, (text_x, current_y))
            current_y += line_h

    def _draw_sections(self, screen, font, card):
        if self._is_general_mode():
            return

        card["relation_picker_hitboxes"] = []
        card["choice_picker_hitboxes"] = []
        editable_hitboxes = {
            field_key: field_rect
            for field_key, field_rect in card.get("editable_field_hitboxes", [])
        }
        rows_by_section = {}
        for row in card.get("field_rows", []):
            rows_by_section.setdefault(row["section"], []).append(row)
        active_relation_anchor = None
        active_choice_anchor = None
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
                value = row.get("value")
                row_rect = row["row_rect"]
                is_inferred = bool(row.get("inferred", False))
                is_active_field = key == card.get("active_edit_field")
                is_relation_link_target = key == card.get("active_relation_link_field")
                is_editable = key in editable_hitboxes

                row_fill = (33, 36, 46) if row_index % 2 == 0 else (29, 32, 42)
                row_border = (78, 84, 100)
                if is_editable:
                    row_fill = (42, 47, 58)
                if is_inferred:
                    row_fill = (37, 55, 56)
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
                    hint_label = "inferred" if is_inferred else ("timeline" if key in self.TEMPORAL_FIELDS else "editable")
                    hint_color = (136, 204, 190) if is_inferred else (130, 150, 185)
                    hint_surface = font.render(hint_label, True, hint_color)
                    hint_x = row["key_rect"].right - hint_surface.get_width() - 6
                    key_text_right = row["key_rect"].x + 6 + key_text_max_w
                    if len(key_lines) == 1 and hint_x > key_text_right + 8:
                        screen.blit(hint_surface, (hint_x, row_rect.y + self.TABLE_ROW_PAD_Y))

                if is_active_field and card.get("is_edit_mode", False):
                    active_value = card.get("edit_buffer", "")
                    if self._is_controlled_choice_field(key):
                        active_value = self.controlled_choice_display_label(
                            key,
                            card.get("choice_picker_value") or active_value,
                        ) + "  v"
                    wrapped_lines = self._wrap_text_lines(
                        active_value,
                        font,
                        row["value_rect"].width,
                    )
                    value_color = (245, 245, 245)
                else:
                    if is_inferred:
                        value_color = (178, 224, 207)
                    else:
                        value_color = (215, 225, 245) if is_editable else (180, 180, 180)
                    wrapped_lines = row["wrapped_lines"]

                relation_chips = row.get("relation_chips", [])
                if self._is_material_model_field(key) and isinstance(value, dict) and not is_active_field:
                    self._draw_material_model_value(screen, font, row["value_rect"], value)
                elif relation_chips and not is_active_field:
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
                if is_active_field and card.get("choice_picker_open", False):
                    active_choice_anchor = row["value_rect"]

        if active_relation_anchor is not None:
            self._draw_relation_picker(screen, font, card, active_relation_anchor)
        if active_choice_anchor is not None:
            self._draw_controlled_choice_picker(screen, font, card, active_choice_anchor)

    def _draw_general_content(self, screen, font, card):
        self._draw_tag_bar(screen, font, card)
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
            selection_range=self._edit_selection_range(card),
        )

        snapshot_rect = card.get("timeline_snapshot_rect")
        if snapshot_rect is not None:
            card["timeline_snapshot_chip_hitboxes"] = []
            snapshot_editing = (
                card.get("is_edit_mode", False)
                and card.get("active_edit_field") == self.TIMELINE_SNAPSHOT_FIELD
            )
            has_snapshot_draft = self._has_timeline_snapshot_draft(card)
            label_fill = (40, 52, 76) if has_snapshot_draft or snapshot_editing else (30, 36, 50)
            border_color = (178, 202, 244) if has_snapshot_draft or snapshot_editing else (88, 104, 132)
            pygame.draw.rect(screen, (25, 31, 43), snapshot_rect)
            pygame.draw.rect(screen, border_color, snapshot_rect, 1)
            blocks = self._timeline_snapshot_display_entries(card)
            previous_clip = screen.get_clip()
            screen.set_clip(previous_clip.clip(snapshot_rect.inflate(-1, -1)))
            try:
                block_y = snapshot_rect.y + 5
                for block in blocks:
                    period_label = self._timeline_snapshot_period_label(block)
                    chip_w = min(
                        snapshot_rect.width - 16,
                        max(48, font.size(period_label)[0] + 18),
                    )
                    chip_rect = pygame.Rect(snapshot_rect.x + 7, block_y, chip_w, 20)
                    pygame.draw.rect(screen, label_fill, chip_rect)
                    pygame.draw.rect(screen, border_color, chip_rect, 1)
                    chip_surface = font.render(
                        period_label,
                        True,
                        (236, 242, 255) if block.get("active") else (205, 220, 242),
                    )
                    screen.blit(chip_surface, chip_surface.get_rect(center=chip_rect.center))
                    card["timeline_snapshot_chip_hitboxes"].append({
                        "start_year": block["start_year"],
                        "end_year": block["end_year"],
                        "rect": chip_rect,
                    })

                    if block.get("active"):
                        heading = self._working_year_wiki_stub(card) or "Year-bound overview"
                    else:
                        heading = "Year-bound overview"
                    if has_snapshot_draft and block.get("active") and not snapshot_editing:
                        heading = f"{heading} (draft)"
                    heading_x = chip_rect.right + 7
                    heading_surface = font.render(
                        self._ellipsize_text(heading, font, max(20, snapshot_rect.right - heading_x - 6)),
                        True,
                        (190, 202, 224),
                    )
                    screen.blit(heading_surface, (heading_x, block_y + 2))

                    content_y = chip_rect.bottom + 3
                    measured_h = CardWikiRenderer.measure_content(
                        block.get("wiki_entry", ""),
                        font,
                        pygame.Rect(snapshot_rect.x + 4, content_y, snapshot_rect.width - 8, 0),
                        resolve_link_label=self._resolve_wiki_link_label,
                    )
                    content_h = max(24, measured_h)
                    content_rect = pygame.Rect(
                        snapshot_rect.x + 3,
                        content_y,
                        snapshot_rect.width - 6,
                        content_h,
                    )
                    CardWikiRenderer.draw_content(
                        screen,
                        font,
                        content_rect,
                        block.get("wiki_entry", ""),
                        is_editing=bool(snapshot_editing and block.get("active")),
                        resolve_link_label=self._resolve_wiki_link_label,
                        resolve_link_color=self._resolve_wiki_link_color,
                        resolve_link_palette=self._resolve_wiki_link_palette,
                        section_colors=self._wiki_field_colors(),
                        cursor_index=card.get("edit_cursor", 0),
                        scroll_y=0,
                        selection_range=self._edit_selection_range(card),
                    )
                    block_y = content_rect.bottom + 8
            finally:
                screen.set_clip(previous_clip)

        if card.get("wiki_link_picker_open", False):
            self._draw_wiki_link_picker(screen, font, card, general_rect)

        self._draw_task_checklist(screen, font, card)

    def _draw_tag_bar(self, screen, font, card):
        rect = card.get("tag_bar_rect")
        if rect is None:
            return
        card["tag_chip_hitboxes"] = []
        card["tag_suggestion_hitboxes"] = []
        card["tag_remove_hitboxes"] = []
        active = card.get("is_edit_mode", False) and card.get("active_edit_field") == "tags"
        pygame.draw.rect(screen, (28, 32, 42) if not active else (36, 42, 56), rect)
        pygame.draw.rect(screen, (86, 98, 122) if not active else (174, 194, 228), rect, 1)

        label_surface = font.render("Tags", True, (184, 196, 216))
        screen.blit(label_surface, (rect.x + 8, rect.y + 8))
        chip_x = rect.x + 52
        chip_y = rect.y + 6
        chip_right = rect.right - 8
        tags = self._tag_values()
        if not tags and not active:
            muted = font.render("none", True, (126, 136, 154))
            screen.blit(muted, (chip_x, rect.y + 8))
            return

        if active:
            for tag in tags:
                label = self._ellipsize_text(tag, font, 104)
                chip_w = min(132, max(48, font.size(label)[0] + 30))
                if chip_x + chip_w > chip_right:
                    break
                chip_rect = pygame.Rect(chip_x, chip_y, chip_w, 22)
                remove_rect = pygame.Rect(chip_rect.right - 20, chip_rect.y + 3, 16, 16)
                card["tag_chip_hitboxes"].append({"tag": tag, "rect": chip_rect})
                card["tag_remove_hitboxes"].append({"tag": tag, "rect": remove_rect})
                fill, border, text_color = self._tag_chip_colors(tag)
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                screen.blit(font.render(label, True, text_color), (chip_rect.x + 7, chip_rect.y + 3))
                pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                remove_surface = font.render("x", True, (250, 220, 224))
                screen.blit(remove_surface, remove_surface.get_rect(center=remove_rect.center))
                chip_x = chip_rect.right + 6

            input_text = self._tag_search_query(card)
            input_rect = pygame.Rect(rect.x + 52, rect.y + 34, max(80, chip_right - rect.x - 52), 24)
            pygame.draw.rect(screen, (24, 28, 38), input_rect)
            pygame.draw.rect(screen, (116, 136, 176), input_rect, 1)
            display = self._ellipsize_text(input_text or "Search tag, Enter to add", font, input_rect.width - 12)
            color = (236, 240, 248) if input_text else (130, 140, 158)
            screen.blit(font.render(display, True, color), (input_rect.x + 6, input_rect.y + 5))
            suggestion_x = input_rect.x
            suggestion_y = input_rect.bottom + 6
            selected_index = int(card.get("tag_selected_index", 0) or 0)
            for index, suggestion in enumerate(self._tag_search_matches(card, limit=5)):
                label = self._ellipsize_text(suggestion, font, 110)
                chip_w = min(122, max(46, font.size(label)[0] + 14))
                if suggestion_x + chip_w > chip_right:
                    break
                chip_rect = pygame.Rect(suggestion_x, suggestion_y, chip_w, 22)
                card["tag_suggestion_hitboxes"].append({"tag": suggestion, "rect": chip_rect})
                selected = index == selected_index
                pygame.draw.rect(screen, (54, 66, 86) if selected else (42, 50, 64), chip_rect)
                pygame.draw.rect(screen, (168, 194, 232) if selected else (112, 132, 166), chip_rect, 1)
                screen.blit(font.render(label, True, (218, 226, 240)), (chip_rect.x + 7, chip_rect.y + 3))
                suggestion_x = chip_rect.right + 6
            return

        for tag in tags:
            label = self._ellipsize_text(tag, font, 120)
            chip_w = min(134, max(42, font.size(label)[0] + 14))
            if chip_x + chip_w > chip_right:
                overflow = font.render("+", True, (188, 198, 216))
                screen.blit(overflow, (chip_x, chip_y + 3))
                break
            chip_rect = pygame.Rect(chip_x, chip_y, chip_w, 22)
            card["tag_chip_hitboxes"].append({"tag": tag, "rect": chip_rect})
            fill, border, text_color = self._tag_chip_colors(tag)
            pygame.draw.rect(screen, fill, chip_rect)
            pygame.draw.rect(screen, border, chip_rect, 1)
            screen.blit(font.render(label, True, text_color), (chip_rect.x + 7, chip_rect.y + 3))
            chip_x = chip_rect.right + 6

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
        screen_rect = screen.get_rect()
        picker_rect.x = max(8, min(picker_rect.x, screen_rect.right - picker_rect.width - 8))
        if picker_rect.bottom > screen_rect.bottom - 8:
            picker_rect.y = max(8, anchor_rect.y - picker_rect.height - 6)
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
        picker_target = card.get("relation_picker_target")
        action_key = "create_target" if picker_target else "note"
        action_label = f"Create {self._relation_target_label(picker_target)}" if picker_target else "Add Note"
        card["relation_picker_hitboxes"].append((action_key, note_rect))
        note_surface = font.render(action_label, True, (236, 240, 248))
        screen.blit(note_surface, (note_rect.x + 8, note_rect.y + 6))
        row_y += 34
        for index, match in enumerate(matches[:6]):
            row_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 36)
            fill = (54, 64, 82) if index == selected_index else (30, 34, 44)
            border = (194, 206, 228) if index == selected_index else (88, 96, 112)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, border, row_rect, 1)
            card["relation_picker_hitboxes"].append((index, row_rect))

            primary = str(match["pretty_name"])
            dataset = match.get("dataset", "")
            scope_label = match.get("scope_label", "")
            secondary = " | ".join(
                part for part in (scope_label, dataset, match.get("entity_type", "entity")) if part
            )

            primary_surface = font.render(primary, True, (242, 242, 242))
            secondary_surface = font.render(secondary, True, (186, 194, 208))
            screen.blit(primary_surface, (row_rect.x + 8, row_rect.y + 3))
            screen.blit(secondary_surface, (row_rect.x + 8, row_rect.y + 18))
            row_y += 40

    def _draw_controlled_choice_picker(self, screen, font, card, anchor_rect):
        """Draw the nested plant-growth vocabulary as a compact dropdown."""

        field_key = card.get("active_edit_field")
        rows = card.get("card_view", self).controlled_choice_rows(field_key)
        if not rows:
            return

        picker_w = min(420, max(300, anchor_rect.width))
        picker_h = 30 + len(rows) * 28 + 12
        picker_rect = pygame.Rect(anchor_rect.x, anchor_rect.bottom + 6, picker_w, picker_h)
        screen_rect = screen.get_rect()
        picker_rect.x = max(8, min(picker_rect.x, screen_rect.right - picker_rect.width - 8))
        if picker_rect.bottom > screen_rect.bottom - 8:
            picker_rect.y = max(8, anchor_rect.y - picker_rect.height - 6)

        card["choice_picker_hitboxes"] = []
        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (186, 194, 210), picker_rect, 1)

        title_text = self._ellipsize_text(
            " / ".join(
                str(row.get("label", ""))
                for row in rows
                if row.get("kind") == "heading"
            ),
            font,
            picker_rect.width - 20,
        )
        title = font.render(title_text, True, (244, 244, 244))
        screen.blit(title, (picker_rect.x + 10, picker_rect.y + 7))

        selected_index = int(card.get("choice_picker_selected_index", -1))
        row_y = picker_rect.y + 30
        for index, row in enumerate(rows):
            row_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 26)
            if row.get("kind") == "heading":
                pygame.draw.rect(screen, (36, 42, 56), row_rect)
                label = "  " * int(row.get("depth", 0)) + str(row.get("label", ""))
                label_surface = font.render(label, True, (170, 190, 220))
                screen.blit(label_surface, (row_rect.x + 6, row_rect.y + 4))
            else:
                selected = index == selected_index
                pygame.draw.rect(screen, (54, 64, 82) if selected else (30, 34, 44), row_rect)
                pygame.draw.rect(screen, (194, 206, 228) if selected else (88, 96, 112), row_rect, 1)
                label_surface = font.render(str(row.get("label", "")), True, (242, 242, 242))
                screen.blit(label_surface, (row_rect.x + 14, row_rect.y + 4))
                card["choice_picker_hitboxes"].append((index, row_rect))
            row_y += 28
