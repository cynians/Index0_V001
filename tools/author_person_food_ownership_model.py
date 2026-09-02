"""Author ownership, recipes, and the person-simulation kitchen fixture.

This is a one-way ontology authoring utility. Runtime code resolves these
entities from the ontology projection and does not maintain a parallel food,
recipe, component, technology, or ownership registry.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


RECIPE_FIELDS = {
    "recipe_class": {"type": "string", "section": "Classification", "optional": True},
    "parent_recipe": {"type": "entity", "target": "recipes", "section": "Relations", "optional": True},
    "input_items": {"type": "entity_list", "target": "items", "section": "Transformation", "optional": True},
    "input_materials": {"type": "entity_list", "target": "materials", "section": "Transformation", "optional": True},
    "output_items": {"type": "entity_list", "target": "items", "section": "Transformation", "optional": True},
    "input_requirements": {"type": "object_list", "section": "Transformation", "optional": True},
    "output_yields": {"type": "object_list", "section": "Transformation", "optional": True},
    "required_technologies": {"type": "entity_list", "target": "technologies", "section": "Requirements", "optional": True},
    "required_components": {"type": "entity_list", "target": "components", "section": "Requirements", "optional": True},
    "compatible_producer_classes": {"type": "string_list", "section": "Requirements", "optional": True},
    "production_steps": {"type": "object_list", "section": "Method", "optional": True},
    "preparation_duration_minutes": {"type": "number", "section": "Method", "optional": True},
    "yield_count": {"type": "number", "section": "Output", "optional": True},
}


OWNERSHIP_FIELDS = {
    "ownership_class": {"type": "string", "section": "Classification", "optional": True},
    "owner_entities": {"type": "entity_list", "target": ["people", "pops", "factions", "institutions", "producers"], "section": "Ownership", "optional": False},
    "owned_assets": {"type": "entity_list", "target": ["vehicles", "items", "locations"], "section": "Ownership", "optional": False},
    "use_policy": {"type": "string", "section": "Use Rights", "optional": True},
    "permitted_users": {"type": "entity_list", "target": ["people", "pops", "factions", "institutions", "producers"], "section": "Use Rights", "optional": True},
    "ownership_shares": {"type": "object_list", "section": "Ownership", "optional": True},
    "start_year": {"type": "number", "section": "Temporal", "optional": True},
    "end_year": {"type": "number", "section": "Temporal", "optional": True},
}


SCHEMA_EXTENSIONS = {
    "vehicle": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
    },
    "item": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
        "inventory_unit": {"type": "string", "section": "Inventory", "optional": True},
        "stackable": {"type": "boolean", "section": "Inventory", "optional": True},
        "consumable": {"type": "boolean", "section": "Food", "optional": True},
        "food_energy_kcal": {"type": "number", "section": "Food", "optional": True},
        "food_satiation": {"type": "number", "section": "Food", "optional": True},
    },
    "location": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
        "site_class": {"type": "string", "section": "Site", "optional": True},
        "building_class": {"type": "string", "section": "Site", "optional": True},
        "bounds": {"type": "object", "section": "Site Layout", "optional": True},
        "openings": {"type": "object_list", "section": "Site Layout", "optional": True},
        "layout_structures": {"type": "entity_list", "target": "locations", "section": "Site Layout", "optional": True},
        "resident_people": {"type": "entity_list", "target": "people", "section": "Site Layout", "optional": True},
        "present_pops": {"type": "entity_list", "target": "pops", "section": "Site Population", "optional": True},
        "authored_visitors": {"type": "entity_list", "target": "people", "section": "Site Population", "optional": True},
        "visitor_scenarios": {"type": "object_list", "section": "Site Population", "optional": True},
        "population_anchor": {"type": "object", "section": "Site Population", "optional": True},
        "site_landmarks": {"type": "object_list", "section": "Site Layout", "optional": True},
        "person_simulation_enabled": {"type": "boolean", "section": "Simulation", "optional": True},
        "map_coordinate_space": {"type": "string", "section": "Map Display", "optional": True},
        "simulation_points": {"type": "object_list", "section": "Site Layout", "optional": True},
        "terrain_zones": {"type": "object_list", "section": "Site Layout", "optional": True},
        "representational_layers": {"type": "string_list", "section": "Site Layout", "optional": True},
        "map_color": {"type": "string", "section": "Map Display", "optional": True},
    },
    "person": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
        "sex": {"type": "string", "section": "Identity", "optional": True},
        "simulation_site": {"type": "entity", "target": "locations", "section": "Simulation", "optional": True},
        "site_position": {"type": "object", "section": "Simulation", "optional": True},
        "residence": {"type": "entity", "target": "locations", "section": "Locations", "optional": True},
    },
    "pop": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "population_count": {"type": "number", "section": "Population", "optional": True},
        "representative_count": {"type": "number", "section": "Simulation", "optional": True},
        "representative_names": {"type": "string_list", "section": "Simulation", "optional": True},
        "culture": {"type": "entity", "target": "cultures", "section": "Culture", "optional": True},
        "home_location": {"type": "entity", "target": "locations", "section": "Locations", "optional": True},
    },
    "faction": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
    },
    "institution": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
    },
    "producer": {
        "ownership_records": {"type": "entity_list", "target": "ownerships", "section": "Ownership", "optional": True},
        "production_recipes": {"type": "entity_list", "target": "recipes", "section": "Production", "optional": True},
        "assigned_components": {"type": "entity_list", "target": "components", "section": "Production", "optional": True},
        "inventory_items": {"type": "object_list", "section": "Inventory", "optional": True},
    },
    "technology": {
        "parent_technology": {"type": "entity", "target": "technologies", "section": "Relations", "optional": True},
    },
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    changes = []
    for schema_name, fields in SCHEMA_EXTENSIONS.items():
        schema = schemas.get(schema_name)
        if not schema:
            continue
        schema["fields"] = {**(schema.get("fields") or {}), **fields}
        changes.append(schema)

    changes.extend([
        {
            "id": "schema_recipe", "_dataset": "schemas", "type": "schema",
            "name": "recipe", "pretty_name": "Recipe", "schema": "recipe",
            "extends": "entity_core", "fields": RECIPE_FIELDS,
        },
        {
            "id": "schema_ownership", "_dataset": "schemas", "type": "schema",
            "name": "ownership", "pretty_name": "Ownership", "schema": "ownership",
            "extends": "entity_core", "fields": OWNERSHIP_FIELDS,
        },
        {
            "id": "tech_cooking", "_dataset": "technologies", "type": "technology",
            "name": "Cooking", "pretty_name": "Cooking", "technology_class": "production workflow",
            "wiki_entry": "The controlled transformation of edible ingredients into food through a known method.",
        },
        {
            "id": "tech_electric_oven", "_dataset": "technologies", "type": "technology",
            "name": "Electric Oven Cooking", "pretty_name": "Electric Oven Cooking",
            "technology_class": "production workflow", "technology_subclass": "electric oven",
            "parent_technology": "tech_cooking", "required_technologies": ["tech_cooking"],
        },
        {
            "id": "component_kitchen_sink", "_dataset": "components", "type": "component",
            "name": "Kitchen Sink", "pretty_name": "Kitchen Sink", "component_class": "kitchen fixture",
        },
        {
            "id": "component_electric_oven", "_dataset": "components", "type": "component",
            "name": "Electric Oven", "pretty_name": "Electric Oven", "component_class": "cooking appliance",
            "associated_technologies": ["tech_electric_oven"],
        },
        {
            "id": "item_food_ingredients", "_dataset": "items", "type": "item",
            "name": "Meal Ingredients", "pretty_name": "Meal Ingredients", "item_class": "food ingredient",
            "consumable": False, "inventory_unit": "portion", "stackable": True,
            "ownership_records": ["ownership_person_test_ingredients"],
        },
        {
            "id": "item_cooked_meal", "_dataset": "items", "type": "item",
            "name": "Simple Cooked Meal", "pretty_name": "Simple Cooked Meal", "item_class": "prepared food",
            "consumable": True, "food_energy_kcal": 700, "food_satiation": 58,
            "inventory_unit": "meal", "stackable": True,
            "input_items": ["item_food_ingredients"], "produced_by": ["producer_person_test_kitchen"],
        },
        {
            "id": "recipe_simple_cooked_meal", "_dataset": "recipes", "type": "recipe",
            "name": "Simple Cooked Meal", "pretty_name": "Simple Cooked Meal Recipe",
            "recipe_class": "food preparation", "input_items": ["item_food_ingredients"],
            "output_items": ["item_cooked_meal"],
            "input_requirements": [{"item": "item_food_ingredients", "quantity": 1, "unit": "portion"}],
            "output_yields": [{"item": "item_cooked_meal", "quantity": 1, "unit": "meal"}],
            "required_technologies": ["tech_cooking", "tech_electric_oven"],
            "required_components": ["component_kitchen_sink", "component_electric_oven"],
            "compatible_producer_classes": ["kitchen"], "preparation_duration_minutes": 30,
            "yield_count": 1,
            "production_steps": [
                {"order": 1, "action": "clean and prepare ingredients", "component": "component_kitchen_sink"},
                {"order": 2, "action": "cook ingredients", "component": "component_electric_oven"},
                {"order": 3, "action": "serve cooked meal", "output": "item_cooked_meal"},
            ],
        },
        {
            "id": "institution_person_sim_lab", "_dataset": "institutions", "type": "institution",
            "name": "Lumber Test Site Cooperative", "pretty_name": "Lumber Test Site Cooperative",
            "ownership_records": ["ownership_lumber_test_site", "ownership_person_test_ingredients"],
        },
        {
            "id": "institution_test_city_council", "_dataset": "institutions", "type": "institution",
            "name": "Test City Council", "pretty_name": "Test City Council",
            "institution_class": "municipal government",
            "ownership_records": ["ownership_lumber_neighbor_village"],
        },
        {
            "id": "culture_lumber_neighbor_village", "_dataset": "cultures", "type": "culture",
            "name": "North Road Village Culture", "pretty_name": "North Road Village Culture",
            "culture_class": "rural regional culture",
        },
        {
            "id": "pop_lumber_neighbor_village", "_dataset": "pops", "type": "pop",
            "name": "North Road Villagers", "pretty_name": "North Road Villagers",
            "population_count": 30, "representative_count": 3,
            "representative_names": ["Alda Rill", "Bren Tarrow", "Cera Venn"],
            "culture": "culture_lumber_neighbor_village",
            "home_location": "location_lumber_neighbor_village",
            "affiliated_institutions": ["institution_test_city_council"],
        },
        {
            "id": "pop_test_city_population_1", "_dataset": "pops", "type": "pop",
            "name": "Test City Population 1", "pretty_name": "Test City Population 1",
            "population_count": 420,
            "affiliated_institutions": ["institution_test_city_council"],
        },
        {
            "id": "location_person_sim_lab", "_dataset": "locations", "type": "location",
            "name": "Person Simulation Test Map", "pretty_name": "Person Simulation Test Map",
            "location_class": "test map", "associated_locations": ["location_lumber_test_site"],
        },
        {
            "id": "location_lumber_test_site", "_dataset": "locations", "type": "location",
            "name": "Lumber Processing Test Site", "pretty_name": "Lumber Processing Test Site",
            "location_class": "site", "site_class": "industrial residential test site",
            "bounds": {"type": "bbox", "min_x": -70, "max_x": 75, "min_y": -90, "max_y": 55},
            "map_coordinate_space": "site_meters", "person_simulation_enabled": True,
            "layout_structures": [
                "location_lumber_test_barracks", "location_person_test_kitchen",
                "location_lumber_test_storage", "location_lumber_test_factory",
            ],
            "constituents": [
                "location_lumber_test_barracks", "location_person_test_kitchen",
                "location_lumber_test_storage", "location_lumber_test_factory",
                "location_lumber_neighbor_village", "location_lumber_east_road",
            ],
            "resident_people": [
                "person_lab_worker", "person_lumber_laborer_elias",
                "person_lumber_laborer_nia", "person_lumber_overseer_tomas",
            ],
            "present_pops": ["pop_lumber_neighbor_village"],
            "population_anchor": [25, -66],
            "authored_visitors": ["person_neighbor_elda_woodbuyer"],
            "visitor_scenarios": [
                {
                    "id": "horse_driver", "name": "Orin Pell", "person_class": "horse driver",
                    "source_pop": "pop_lumber_neighbor_village", "position": [55, 3],
                    "purpose": "drive the village buyer and timber cart", "simulation_detail": "full",
                    "materialize_on_entry": True,
                },
                {
                    "id": "city_inspector", "name": "Ilyra Sen", "person_class": "municipal inspector",
                    "source_pop": "pop_test_city_population_1", "institution": "institution_test_city_council",
                    "position": [51, 17], "purpose": "inspect a council-owned village supplier",
                    "simulation_detail": "full", "materialize_on_entry": True,
                },
                {
                    "id": "road_travellers", "names": ["Saro Kest", "Vela Dorn"],
                    "person_class": "traveller", "position": [56, 34], "count": 2,
                    "purpose": "travel north along the road", "simulation_detail": "lightweight",
                },
            ],
            "simulation_points": [
                {"id": "bed", "label": "Barracks Bed", "position": [14, -16], "asset_id": "location_lumber_test_barracks"},
                {"id": "kitchen", "label": "Kitchen", "position": [25, -6], "asset_id": "location_person_test_kitchen"},
                {"id": "food", "label": "Food Store", "position": [15, 15], "asset_id": "location_person_test_pantry"},
                {"id": "job", "label": "Factory Work", "position": [35, 10], "asset_id": "location_lumber_test_factory"},
                {"id": "target", "label": "Western Wood Lot", "position": [-29, 4], "asset_id": "location_lumber_test_woodlot"},
            ],
            "terrain_zones": [
                {"label": "Western Wild Terrain", "terrain_class": "woodland", "bounds": {"min_x": -70, "max_x": 0, "min_y": -90, "max_y": 55}, "color": "#334d3b"},
                {"label": "Northern Fields", "terrain_class": "open rural terrain", "bounds": {"min_x": 0, "max_x": 75, "min_y": -90, "max_y": -28}, "color": "#465744"},
                {"label": "Developed Yard", "terrain_class": "compacted ground", "bounds": {"min_x": 0, "max_x": 50, "min_y": -27, "max_y": 27}, "color": "#57554b"},
                {"label": "South Road Verge", "terrain_class": "rough grassland", "bounds": {"min_x": 0, "max_x": 75, "min_y": 28, "max_y": 55}, "color": "#3f513f"},
            ],
            "site_landmarks": [
                {"id": "east_road", "label": "East Road · logistics corridor placeholder", "landmark_class": "road", "bounds": {"min_x": 52, "max_x": 60, "min_y": -90, "max_y": 55}, "color": "#554f43"},
                {"id": "north_village", "label": "North Road Village · 30 inhabitants", "landmark_class": "village", "bounds": {"min_x": 7, "max_x": 45, "min_y": -84, "max_y": -48}, "color": "#625a49"},
            ],
            "representational_layers": ["heightmap", "true color"],
            "ownership_records": ["ownership_lumber_test_site"],
        },
        {
            "id": "location_lumber_east_road", "_dataset": "locations", "type": "location",
            "name": "East Road", "pretty_name": "East Road",
            "location_class": "infrastructure", "site_class": "road and logistics corridor",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 52, "max_x": 60, "min_y": -90, "max_y": 55},
            "map_color": "#786f5b", "wiki_entry": "Placeholder corridor for the future logistics simulation.",
        },
        {
            "id": "location_lumber_neighbor_village", "_dataset": "locations", "type": "location",
            "name": "North Road Village", "pretty_name": "North Road Village",
            "location_class": "village", "site_class": "rural settlement",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 7, "max_x": 45, "min_y": -84, "max_y": -48},
            "map_coordinate_space": "site_meters", "person_simulation_enabled": True,
            "resident_pops": ["pop_lumber_neighbor_village"],
            "associated_institutions": ["institution_test_city_council"],
            "ownership_records": ["ownership_lumber_neighbor_village"],
            "map_color": "#77664e",
        },
        {
            "id": "person_neighbor_elda_woodbuyer", "_dataset": "people", "type": "person",
            "name": "Elda Marr", "pretty_name": "Elda Marr",
            "person_class": "villager and household buyer", "sex": "female",
            "source_pop": "pop_lumber_neighbor_village",
            "associated_locations": ["location_lumber_neighbor_village", "location_lumber_test_site"],
            "simulation_site": "location_lumber_test_site", "site_position": [48, 0],
            "residence": "location_lumber_neighbor_village",
            "visit_purpose": "ask to buy wood for repairs to her house",
            "goals": ["wish_obtain_lumber_for_repairs"],
            "big_five_openness": 0.46, "big_five_conscientiousness": 0.73,
            "big_five_extraversion": 0.58, "big_five_agreeableness": 0.69,
            "big_five_neuroticism": 0.41,
        },
        {
            "id": "person_lab_worker", "_dataset": "people", "type": "person",
            "name": "Mara Voss", "pretty_name": "Mara Voss",
            "person_class": "worker", "sex": "female",
            "affiliated_institutions": ["institution_person_sim_lab"],
            "associated_locations": ["location_lumber_test_site", "location_person_test_kitchen"],
            "simulation_site": "location_lumber_test_site", "site_position": [25, -6],
            "residence": "location_lumber_test_barracks",
            "is_employed_by": ["producer_person_test_kitchen"],
            "is_employed_as": "job_lumber_site_cook",
            "is_employed_at": "location_person_test_kitchen",
            "wishes": ["wish_relax_after_shift"],
            "knowledge_records": [
                {"entity": "recipe_simple_cooked_meal", "interest": 0.86, "familiarity": 0.81, "source": "learned recipe"},
                {"entity": "location_lumber_test_barracks", "interest": 0.65, "familiarity": 0.95, "navigation_knowledge": "route", "source": "resident knowledge"},
                {"entity": "location_person_test_kitchen", "interest": 0.92, "familiarity": 1.0, "navigation_knowledge": "route", "source": "workplace knowledge"},
                {"entity": "location_person_test_pantry", "interest": 0.78, "familiarity": 0.9, "navigation_knowledge": "route", "source": "daily provisioning"},
                {"entity": "location_lumber_test_factory", "interest": 0.55, "familiarity": 0.35, "navigation_knowledge": "direction", "direction_hint": [1, 0.35], "source": "general site orientation"},
                {"entity": "location_lumber_test_woodlot", "interest": 0.45, "familiarity": 0.25, "navigation_knowledge": "direction", "direction_hint": [-1, 0], "source": "told it lies west"},
            ],
        },
        {
            "id": "location_person_test_kitchen", "_dataset": "locations", "type": "location",
            "name": "Barracks Kitchen", "pretty_name": "Barracks Kitchen",
            "location_class": "building", "site_class": "kitchen", "building_class": "attached kitchen",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 20, "max_x": 30, "min_y": -10, "max_y": -2},
            "openings": [
                {"side": "north", "center": 25, "width": 3, "opening_class": "interior doorway"},
                {"side": "south", "center": 25, "width": 2, "opening_class": "exterior door"},
            ],
            "map_color": "#6e6252", "ownership_records": ["ownership_lumber_test_site"],
            "operated_by": ["producer_person_test_kitchen"],
        },
        {
            "id": "location_lumber_test_barracks", "_dataset": "locations", "type": "location",
            "name": "Worker Barracks", "pretty_name": "Worker Barracks",
            "location_class": "building", "site_class": "residential building", "building_class": "barracks",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 8, "max_x": 30, "min_y": -22, "max_y": -10},
            "openings": [
                {"side": "west", "center": -16, "width": 3, "opening_class": "exterior door"},
                {"side": "south", "center": 25, "width": 3, "opening_class": "kitchen doorway"},
            ],
            "map_color": "#536271", "ownership_records": ["ownership_lumber_test_site"],
        },
        {
            "id": "location_lumber_test_storage", "_dataset": "locations", "type": "location",
            "name": "Lumber Storage Facility", "pretty_name": "Lumber Storage Facility",
            "location_class": "building", "site_class": "storage facility", "building_class": "warehouse",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 8, "max_x": 22, "min_y": 8, "max_y": 22},
            "openings": [{"side": "west", "center": 15, "width": 4, "opening_class": "loading door"}],
            "map_color": "#625a49", "ownership_records": ["ownership_lumber_test_site"],
        },
        {
            "id": "location_lumber_test_factory", "_dataset": "locations", "type": "location",
            "name": "Lumber Factory Hall", "pretty_name": "Lumber Factory Hall",
            "location_class": "building", "site_class": "factory site", "building_class": "factory hall",
            "parent_location": "location_lumber_test_site",
            "bounds": {"type": "bbox", "min_x": 26, "max_x": 44, "min_y": 2, "max_y": 20},
            "openings": [{"side": "west", "center": 10, "width": 4, "opening_class": "industrial doorway"}],
            "map_color": "#58616a", "ownership_records": ["ownership_lumber_test_site"],
            "operated_by": ["producer_lumber_test_factory"],
        },
        {
            "id": "location_lumber_test_woodlot", "_dataset": "locations", "type": "location",
            "name": "Western Wood Lot", "pretty_name": "Western Wood Lot",
            "location_class": "wild terrain", "site_class": "woodland resource area",
            "bounds": {"min_x": -44, "max_x": 0, "min_y": -27, "max_y": 27},
            "map_color": "#334d3b", "ownership_records": ["ownership_lumber_test_site"],
        },
        {
            "id": "location_person_test_pantry", "_dataset": "locations", "type": "location",
            "name": "Person Test Pantry", "pretty_name": "Person Test Pantry",
            "location_class": "storage site", "site_class": "food store",
            "inventory_items": [{"item": "item_food_ingredients", "quantity": 6, "unit": "portion"}],
            "associated_locations": ["location_lumber_test_storage"],
            "ownership_records": ["ownership_person_test_ingredients"],
        },
        {
            "id": "producer_person_test_kitchen", "_dataset": "producers", "type": "producer",
            "name": "Person Test Kitchen", "pretty_name": "Person Test Kitchen", "producer_class": "kitchen",
            "production_recipes": ["recipe_simple_cooked_meal"],
            "production_technologies": ["tech_cooking", "tech_electric_oven"],
            "assigned_components": ["component_kitchen_sink", "component_electric_oven"],
            "produced_items": ["item_cooked_meal"],
            "employer_discipline_level": 0.4,
            "production_lines": [{
                "line_id": "line_person_test_cooked_meal", "product_id": "item_cooked_meal",
                "location_id": "location_person_test_kitchen", "recipe_ids": ["recipe_simple_cooked_meal"],
                "employed_technology_ids": ["tech_cooking", "tech_electric_oven"],
                "assigned_component_ids": ["component_kitchen_sink", "component_electric_oven"],
                "job_ids": ["job_lumber_site_cook"],
                "rate_value": "", "rate_period": "week",
            }],
        },
        {
            "id": "producer_lumber_test_factory", "_dataset": "producers", "type": "producer",
            "name": "Lumber Test Factory", "pretty_name": "Lumber Test Factory",
            "producer_class": "lumber processing factory", "associated_locations": ["location_lumber_test_factory"],
            "production_jobs": ["job_lumber_site_laborer", "job_lumber_site_overseer"],
            "employer_discipline_level": 0.55,
            # employed_people is derived (EntityLoader.populate_employment_rosters())
            # from person.is_employed_by -- never authored here.
            "production_lines": [],
            "wiki_entry": "Test-site factory shell. Lumber intake, plank production, workshop output, and vehicle logistics will be authored as the workflow is expanded.",
        },
        {
            "id": "job_lumber_site_cook", "_dataset": "jobs", "type": "job",
            "name": "Site Cook", "pretty_name": "Site Cook", "job_class": "food service",
            "job_doctrine": "Maintains regular meals for the resident workforce from the barracks kitchen.",
            "job_criticality": 0.55,
            "associated_producers": ["producer_person_test_kitchen"],
            "associated_locations": ["location_person_test_kitchen"],
        },
        {
            "id": "job_lumber_site_laborer", "_dataset": "jobs", "type": "job",
            "name": "Lumber Laborer", "pretty_name": "Lumber Laborer", "job_class": "industrial labor",
            "job_doctrine": "Moves and processes lumber according to the active factory workflow and current allocations.",
            "job_criticality": 0.6,
            "associated_producers": ["producer_lumber_test_factory"],
            "associated_locations": ["location_lumber_test_storage", "location_lumber_test_factory"],
        },
        {
            "id": "job_lumber_site_overseer", "_dataset": "jobs", "type": "job",
            "name": "Site Overseer", "pretty_name": "Site Overseer", "job_class": "operations supervision",
            "job_doctrine": "Coordinates work allocation, storage movement, and site continuity without replacing the workers' autonomous decisions.",
            "job_criticality": 0.7,
            "associated_producers": ["producer_lumber_test_factory"],
            "associated_locations": ["location_lumber_test_site"],
        },
        {
            "id": "person_lumber_laborer_elias", "_dataset": "people", "type": "person",
            "name": "Elias Kern", "pretty_name": "Elias Kern", "person_class": "worker", "sex": "male",
            "affiliated_institutions": ["institution_person_sim_lab"],
            "associated_locations": ["location_lumber_test_site", "location_lumber_test_factory"],
            "simulation_site": "location_lumber_test_site", "site_position": [33, 12],
            "residence": "location_lumber_test_barracks",
            "is_employed_by": ["producer_lumber_test_factory"],
            "is_employed_as": "job_lumber_site_laborer",
            "is_employed_at": "location_lumber_test_factory",
            "knowledge_records": [
                {"entity": "location_lumber_test_factory", "familiarity": 0.95, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_storage", "familiarity": 0.9, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_woodlot", "familiarity": 0.8, "navigation_knowledge": "route"},
            ],
        },
        {
            "id": "person_lumber_laborer_nia", "_dataset": "people", "type": "person",
            "name": "Nia Vale", "pretty_name": "Nia Vale", "person_class": "worker", "sex": "female",
            "affiliated_institutions": ["institution_person_sim_lab"],
            "associated_locations": ["location_lumber_test_site", "location_lumber_test_storage"],
            "simulation_site": "location_lumber_test_site", "site_position": [17, 15],
            "residence": "location_lumber_test_barracks",
            "is_employed_by": ["producer_lumber_test_factory"],
            "is_employed_as": "job_lumber_site_laborer",
            "is_employed_at": "location_lumber_test_factory",
            "knowledge_records": [
                {"entity": "location_lumber_test_factory", "familiarity": 0.9, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_storage", "familiarity": 0.98, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_woodlot", "familiarity": 0.35, "navigation_knowledge": "direction", "direction_hint": [-1, 0]},
            ],
        },
        {
            "id": "person_lumber_overseer_tomas", "_dataset": "people", "type": "person",
            "name": "Tomas Rhee", "pretty_name": "Tomas Rhee", "person_class": "worker", "sex": "male",
            "affiliated_institutions": ["institution_person_sim_lab"],
            "associated_locations": ["location_lumber_test_site", "location_lumber_test_factory"],
            "simulation_site": "location_lumber_test_site", "site_position": [39, 8],
            "residence": "location_lumber_test_barracks",
            "is_employed_by": ["producer_lumber_test_factory"],
            "is_employed_as": "job_lumber_site_overseer",
            "is_employed_at": "location_lumber_test_site",
            "knowledge_records": [
                {"entity": "location_lumber_test_site", "familiarity": 0.98, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_factory", "familiarity": 0.98, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_storage", "familiarity": 0.95, "navigation_knowledge": "route"},
                {"entity": "location_lumber_test_woodlot", "familiarity": 0.9, "navigation_knowledge": "route"},
            ],
        },
        {
            "id": "ownership_person_test_kitchen", "_dataset": "ownerships", "type": "ownership",
            "name": "Person Test Kitchen Ownership", "ownership_class": "institutional",
            "owner_entities": ["institution_person_sim_lab"],
            "owned_assets": ["location_person_test_kitchen"],
            "use_policy": "institutional", "permitted_users": ["institution_person_sim_lab"],
        },
        {
            "id": "ownership_person_test_ingredients", "_dataset": "ownerships", "type": "ownership",
            "name": "Person Test Ingredients Ownership", "ownership_class": "institutional stores",
            "owner_entities": ["institution_person_sim_lab"],
            "owned_assets": ["item_food_ingredients", "location_person_test_pantry"],
            "use_policy": "institutional", "permitted_users": ["institution_person_sim_lab"],
        },
        {
            "id": "ownership_lumber_test_site", "_dataset": "ownerships", "type": "ownership",
            "name": "Lumber Test Site Ownership", "pretty_name": "Lumber Test Site Ownership",
            "ownership_class": "institutional site ownership",
            "owner_entities": ["institution_person_sim_lab"],
            "owned_assets": [
                "location_lumber_test_site", "location_lumber_test_barracks",
                "location_person_test_kitchen", "location_lumber_test_storage",
                "location_lumber_test_factory", "location_lumber_test_woodlot",
            ],
            "use_policy": "resident workforce and institutional operations",
            "permitted_users": ["institution_person_sim_lab", "producer_person_test_kitchen", "producer_lumber_test_factory"],
        },
        {
            "id": "ownership_lumber_neighbor_village", "_dataset": "ownerships", "type": "ownership",
            "name": "North Road Village Municipal Ownership",
            "pretty_name": "North Road Village Municipal Ownership",
            "ownership_class": "municipal settlement ownership",
            "owner_entities": ["institution_test_city_council"],
            "owned_assets": ["location_lumber_neighbor_village"],
            "use_policy": "municipal stewardship and inspection",
            "permitted_users": ["institution_test_city_council", "pop_lumber_neighbor_village"],
        },
    ])
    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} food/recipe/ownership ontology entities")


if __name__ == "__main__":
    main()
