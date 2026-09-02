"""Author the Job and Employment production model into the ontology.

This is a one-way ontology authoring utility.  Runtime code reads these
definitions from the ontology; this module is not a parallel entity registry.
"""

from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


JOB_FIELDS = {
    "job_class": {"type": "string", "section": "Classification", "optional": True},
    "job_subtype": {"type": "string", "section": "Classification", "optional": True},
    "parent_job": {"type": "entity", "target": "jobs", "section": "Relations", "optional": True},
    "job_doctrine": {"type": "text", "section": "Doctrine", "optional": True},
    "job_criticality": {
        "type": "number", "section": "Doctrine", "optional": True,
        "description": (
            "0-1 base weight for how seriously this job is normally taken, independent of "
            "who holds it or who employs them -- combines with the employer's "
            "employer_discipline_level and the worker's own personality when a duty task "
            "tied to this job is scored (see PersonSimulation._score_task)."
        ),
    },
    "intended_beneficiaries": {"type": "string_list", "section": "Doctrine", "optional": True},
    "output_allocation_doctrine": {"type": "text", "section": "Doctrine", "optional": True},
    "ownership_doctrine": {"type": "text", "section": "Doctrine", "optional": True},
    "exchange_doctrine": {"type": "text", "section": "Doctrine", "optional": True},
    "associated_producers": {"type": "entity_list", "target": "producers", "section": "Organization", "optional": True},
    "associated_institutions": {"type": "entity_list", "target": "institutions", "section": "Organization", "optional": True},
    "associated_factions": {"type": "entity_list", "target": "factions", "section": "Organization", "optional": True},
    "associated_locations": {"type": "entity_list", "target": "locations", "section": "Organization", "optional": True},
    "supported_outputs": {"type": "entity_list", "target": ["items", "components", "vehicles", "materials"], "section": "Production", "optional": True},
    "supported_tasks": {"type": "entity_list", "target": "tasks", "section": "Production", "optional": True},
    "unlock_technologies": {"type": "entity_list", "target": "technologies", "section": "Unlocks", "optional": True},
    "unlock_cultural_aspects": {"type": "entity_list", "target": "cultural_aspects", "section": "Unlocks", "optional": True},
    "unlock_production_outputs": {"type": "entity_list", "target": ["items", "components", "vehicles", "materials"], "section": "Unlocks", "optional": True},
    "required_institutions": {"type": "entity_list", "target": "institutions", "section": "Unlocks", "optional": True},
    "required_site_conditions": {"type": "string_list", "section": "Unlocks", "optional": True},
    "typical_workflow_notes": {"type": "text", "section": "Workflow", "optional": True},
}


EMPLOYMENT_FIELDS = {
    "employment_class": {"type": "string", "section": "Classification", "optional": True},
    "job": {"type": "entity", "target": "jobs", "section": "Employment", "optional": False},
    "employers": {"type": "entity_list", "target": ["producers", "institutions", "factions"], "section": "Employment", "optional": True},
    "employed_people": {"type": "entity_list", "target": ["people", "person"], "section": "Workforce", "optional": True},
    "employed_pops": {"type": "entity_list", "target": "pops", "section": "Workforce", "optional": True},
    "workforce_headcount": {"type": "number", "section": "Workforce", "optional": True},
    "pop_workforce_fraction": {"type": "number", "section": "Workforce", "optional": True},
    "production_context": {"type": "entity", "target": "producers", "section": "Production", "optional": True},
    "production_line_id": {"type": "string", "section": "Production", "optional": True},
    "work_location": {"type": "entity", "target": "locations", "section": "Production", "optional": True},
    "employed_technologies": {"type": "entity_list", "target": "technologies", "section": "Workflow", "optional": True},
    "assigned_vehicles": {"type": "entity_list", "target": "vehicles", "section": "Workflow", "optional": True},
    "assigned_items": {"type": "entity_list", "target": "items", "section": "Workflow", "optional": True},
    "assigned_components": {"type": "entity_list", "target": "components", "section": "Workflow", "optional": True},
}


SCHEMA_EXTENSIONS = {
    "producer": {
        "production_lines": {"type": "dict_list", "section": "Production", "optional": True},
        "production_jobs": {"type": "entity_list", "target": "jobs", "section": "Production", "optional": True},
        "production_technologies": {"type": "entity_list", "target": "technologies", "section": "Production", "optional": True},
        "employer_discipline_level": {
            "type": "number", "section": "Production", "optional": True,
            "description": (
                "0-1 baseline for how strictly this employer enforces compliance/indoctrination "
                "-- feeds the coercion input of a duty task's decision score alongside the "
                "worker's own personality, not a substitute for it."
            ),
        },
        # Derived, never hand-authored: computed from every person's
        # is_employed_by by EntityLoader.populate_employment_rosters(),
        # the same way locations' offspring is derived from parent_location.
        "employed_people": {"type": "entity_list", "target": "people", "section": "Workforce", "optional": True},
        "associated_cultural_aspects": {"type": "entity_list", "target": "cultural_aspects", "section": "Relations", "optional": True},
    },
    "person": {
        "is_employed_by": {"type": "entity_list", "target": ["producers", "institutions", "factions"], "section": "Employment", "optional": True},
        "is_employed_as": {"type": "entity", "target": "jobs", "section": "Employment", "optional": True},
        "is_employed_at": {"type": "entity", "target": "locations", "section": "Employment", "optional": True},
    },
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    changes = []
    for schema_name, fields in SCHEMA_EXTENSIONS.items():
        schema = schemas[schema_name]
        schema["fields"] = {**(schema.get("fields") or {}), **fields}
        changes.append(schema)

    changes.extend([
        {
            "id": "schema_job", "_dataset": "schemas", "type": "schema",
            "name": "job", "pretty_name": "Job", "schema": "job",
            "extends": "entity_core", "fields": JOB_FIELDS,
        },
        {
            "id": "schema_employment", "_dataset": "schemas", "type": "schema",
            "name": "employment", "pretty_name": "Employment", "schema": "employment",
            "extends": "entity_core", "fields": EMPLOYMENT_FIELDS,
        },
        {
            "id": "job_farmer", "_dataset": "jobs", "type": "job",
            "name": "Farmer", "pretty_name": "Farmer", "job_class": "agriculture",
            "job_doctrine": "Cultivates organisms or managed ecosystems to produce food and agricultural materials.",
            "wiki_entry": "A broad job family. Its doctrinal subtypes describe how agricultural output is organized and used; employed technologies describe the local workflow.",
        },
        {
            "id": "job_subsistence_farmer", "_dataset": "jobs", "type": "job",
            "name": "Subsistence Farmer", "pretty_name": "Subsistence Farmer",
            "job_class": "agriculture", "job_subtype": "subsistence", "parent_job": "job_farmer",
            "job_doctrine": "Agricultural work organized primarily to sustain the worker, household, expedition, or local community.",
            "intended_beneficiaries": ["worker household", "local community"],
            "output_allocation_doctrine": "Reserve production for direct consumption and local continuity before allowing surplus to enter exchange.",
            "exchange_doctrine": "Only output beyond subsistence and reserve needs is normally sold, taxed, gifted, or traded.",
            "wiki_entry": "This doctrine is independent of technological era: it can describe a medieval peasant using oxen and ploughs or a far-future colony pioneer using autonomous agriculture.",
        },
    ])
    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} Job/Employment ontology entities")


if __name__ == "__main__":
    main()
