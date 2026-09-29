"""Author the pop system: location/cultural/employment pops as overlapping
statistical views on a shared population, plus static demographic fields.

Core idea (see conversation record, not yet in conceptual_layer_overview_v006.txt):
a pop's population_count is durable ground truth only for "root" pops
(location/cultural). An employment pop never adds population -- it is a
labeled recruitment cut of one or more source pops, authored as exact
per-source counts in source_allocations. Its own population_count is
derived (sum of source_allocations) by PopSimulation, never hand-authored,
so a person is never implied to exist twice: being "one of the 324 German
factory workers" means 324 of the (already-counted) German cultural pop's
members also carry that employment label, not 324 additional people.

Employment pops can nest via parent_pop the same way jobs nest via
parent_job -- a general category pop (e.g. "Factory Workers") can have a
site/employer-specific child (e.g. "Factory Workers at Factory X").

This is a one-way ontology authoring utility, following the same pattern as
the other tools/author_*.py scripts.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


POP_SCHEMA_FIELDS = {
    "pop_type": {
        "type": "string", "section": "Classification", "optional": True,
        "description": "location | cultural | employment. Controls whether population_count is authored ground truth (location/cultural) or derived from source_allocations (employment).",
    },
    "parent_pop": {
        "type": "entity", "target": "pops", "section": "Classification", "optional": True,
        "description": "Category nesting (e.g. a site-specific employment pop's parent is the general job-category pop), mirroring job.parent_job. Not a recruitment source -- see source_allocations for that.",
    },
    "employer": {
        "type": "entity", "target": ["producers", "institutions"], "section": "Employment", "optional": True,
        "description": "For an employment pop: which employer this pop's members work for.",
    },
    "source_allocations": {
        "type": "object_list", "section": "Employment", "optional": True,
        "description": "For an employment (or otherwise derived) pop: [{source_pop, count}] -- exact headcount recruited from each source pop. This pop's own population_count is the sum, never independently authored.",
    },
    "age_distribution": {
        "type": "object", "section": "Demographics", "optional": True,
        "description": "Static bell-curve parameterization: {mean_age, stddev, min_age, max_age}. No dynamics (aging/births/deaths) yet -- see growth_rate_stub.",
    },
    "sex_ratio": {
        "type": "number", "section": "Demographics", "optional": True,
        "description": "Fraction female, 0-1.",
    },
    "growth_rate_stub": {
        "type": "number", "section": "Demographics", "optional": True,
        "description": "Placeholder for future time-evolving dynamics (births/deaths/migration/employment turnover). Not read by any runtime code yet -- deliberately inert, like PersonSimulation.habits.",
    },
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    pops_by_id = {
        entity["id"]: entity
        for entity in datasets.get("pops", [])
        if isinstance(entity, dict) and entity.get("id")
    }
    changes = []

    pop_schema = schemas.get("pop")
    if pop_schema is not None:
        pop_schema["fields"] = {**(pop_schema.get("fields") or {}), **POP_SCHEMA_FIELDS}
        changes.append(pop_schema)

    village_demographics = {
        "age_distribution": {"mean_age": 38, "stddev": 14, "min_age": 4, "max_age": 82},
        "sex_ratio": 0.51,
        "growth_rate_stub": 0.0,
    }
    changes.append({
        # apply_changes fully replaces stored properties, so carry the
        # pop's existing authored fields (population_count, culture,
        # home_location, resident representatives, etc.) forward rather
        # than patching a bare partial dict.
        **pops_by_id.get("pop_lumber_neighbor_village", {
            "id": "pop_lumber_neighbor_village", "_dataset": "pops", "type": "pop",
        }),
        "pop_type": "location",
        **village_demographics,
    })

    changes.extend([
        {
            "id": "pop_factory_workers", "_dataset": "pops", "type": "pop",
            "name": "Factory Workers", "pretty_name": "Factory Workers",
            "pop_type": "employment",
            "wiki_entry": "General employment-category pop: workers at any lumber-processing factory. Site-specific factory workforces (see pop_lumber_factory_workers) nest under this as parent_pop.",
        },
        {
            "id": "pop_lumber_factory_workers", "_dataset": "pops", "type": "pop",
            "name": "Lumber Test Factory Workers", "pretty_name": "Lumber Test Factory Workers",
            "pop_type": "employment",
            "parent_pop": "pop_factory_workers",
            "employer": "producer_lumber_test_factory",
            # Recruited from the existing village pop -- these people are
            # already counted in pop_lumber_neighbor_village's 30; this pop
            # labels 12 of them as factory workers, it does not add 12 more.
            "source_allocations": [
                {"source_pop": "pop_lumber_neighbor_village", "count": 12},
            ],
            "age_distribution": {"mean_age": 34, "stddev": 10, "min_age": 18, "max_age": 60},
            "sex_ratio": 0.42,
            "growth_rate_stub": 0.0,
            "wiki_entry": "Working-age slice of the North Road Village pop employed at the lumber test factory. See job_lumber_site_laborer/job_lumber_site_overseer for the specific roles.",
        },
    ])
    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} pop system ontology entities")


if __name__ == "__main__":
    main()
