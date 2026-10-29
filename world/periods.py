from world.year_utils import parse_year


TOP_LEVEL_PERIOD_IDS = (
    "period_postmodernist",
    "period_race_for_sol",
    "period_ggo_hegemony",
    "period_planetary",
    "period_trifecta_dominion",
    "period_intersector_assembly",
)


PERIOD_SCHEMA_ENTITY = {
    "id": "schema_period",
    "_dataset": "schemas",
    "type": "schema",
    "name": "period",
    "pretty_name": "Period",
    "schema": "period",
    "extends": "entity_core",
    "fields": {
        "period_class": {"type": "string", "section": "Period"},
        "year": {"type": "number", "section": "Period", "optional": True},
        "parent_periods": {
            "type": "entity_list",
            "target": "period",
            "section": "Relations",
            "optional": True,
        },
        "scope_parent": {
            "type": "entity",
            "target": "entity_core",
            "section": "Relations",
            "optional": True,
        },
        "contained_periods": {
            "type": "entity_list",
            "target": "period",
            "section": "Relations",
            "optional": True,
        },
        "contained_events": {
            "type": "entity_list",
            "target": "event",
            "section": "Relations",
            "optional": True,
        },
    },
}


def event_anchor_year(entity):
    if not isinstance(entity, dict):
        return None
    for field_name in ("year", "year_number", "effective_year", "start_year"):
        year = parse_year(entity.get(field_name))
        if year is not None:
            return year
    return None


def century_number_for_year(year):
    year = int(year)
    if year > 0:
        return ((year - 1) // 100) + 1
    if year < 0:
        return -((abs(year) - 1) // 100 + 1)
    return 0


def century_bounds(century_number):
    century_number = int(century_number)
    if century_number > 0:
        return (century_number - 1) * 100 + 1, century_number * 100
    if century_number < 0:
        magnitude = abs(century_number)
        return -(magnitude * 100), -((magnitude - 1) * 100 + 1)
    return 0, 0


def century_label(century_number):
    century_number = int(century_number)
    if century_number < 0:
        return f"Cen {abs(century_number)} BCE"
    return f"Cen {century_number}"


def century_entity_id(century_number):
    century_number = int(century_number)
    if century_number < 0:
        return f"period_century_bce_{abs(century_number)}"
    return f"period_century_{century_number}"


def year_entity_id(year):
    year = int(year)
    if year < 0:
        return f"period_year_bce_{abs(year)}"
    return f"period_year_{year}"


def top_level_periods(major_periods):
    by_id = {
        str(period.get("entity_id")): period
        for period in major_periods or []
        if isinstance(period, dict) and period.get("entity_id")
    }
    return [by_id[entity_id] for entity_id in TOP_LEVEL_PERIOD_IDS if entity_id in by_id]


def top_level_period_for_year(year, major_periods):
    year = int(year)
    periods = top_level_periods(major_periods)
    for index, period in enumerate(periods):
        start_year = int(period["start_year"])
        end_year = int(period["end_year"])
        is_last = index == len(periods) - 1
        if start_year <= year < end_year or (is_last and year == end_year):
            return period
    return None


def _ensure_dataset_entry(dataset, entity):
    entity_id = entity.get("id")
    for index, current in enumerate(dataset):
        if isinstance(current, dict) and current.get("id") == entity_id:
            dataset[index] = entity
            return
    dataset.append(entity)


def _upsert_generated_entity(entities, dataset, record):
    entity_id = record["id"]
    existing = entities.get(entity_id)
    if not isinstance(existing, dict):
        existing = dict(record)
        entities[entity_id] = existing
    else:
        for field_name, value in record.items():
            if field_name in {
                "id",
                "_dataset",
                "type",
                "name",
                "pretty_name",
                "period_class",
                "year",
                "start_year",
                "end_year",
                "parent_periods",
                "contained_periods",
                "contained_events",
                "period_reference_generated",
            }:
                existing[field_name] = value
    _ensure_dataset_entry(dataset, existing)
    return existing


def apply_period_reference_models(loader, major_periods):
    """Materialize canonical eras and event-derived century/year card entries."""
    entities = getattr(loader, "entities", None)
    datasets = getattr(loader, "datasets", None)
    if not isinstance(entities, dict) or not isinstance(datasets, dict):
        return False

    schemas = datasets.setdefault("schemas", [])
    schema = entities.get(PERIOD_SCHEMA_ENTITY["id"])
    if not isinstance(schema, dict):
        schema = {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in PERIOD_SCHEMA_ENTITY.items()
        }
        schema["fields"] = {
            key: dict(value)
            for key, value in PERIOD_SCHEMA_ENTITY["fields"].items()
        }
        entities[schema["id"]] = schema
    else:
        schema.setdefault("schema", "period")
        schema.setdefault("extends", "entity_core")
        fields = schema.setdefault("fields", {})
        for field_name, spec in PERIOD_SCHEMA_ENTITY["fields"].items():
            fields.setdefault(field_name, dict(spec))
    _ensure_dataset_entry(schemas, schema)

    periods_dataset = datasets.setdefault("periods", [])
    top_period_records = top_level_periods(major_periods)
    top_entities = {}
    for period in top_period_records:
        entity_id = str(period["entity_id"])
        top_entities[entity_id] = _upsert_generated_entity(
            entities,
            periods_dataset,
            {
                "id": entity_id,
                "_dataset": "periods",
                "type": "period",
                "name": period["label"],
                "pretty_name": period["label"],
                "period_class": "major_period",
                "start_year": int(period["start_year"]),
                "end_year": int(period["end_year"]),
                "parent_periods": [],
                "contained_periods": [],
                "contained_events": [],
                "period_reference_generated": True,
            },
        )

    events = [
        entity
        for entity in datasets.get("events", [])
        if isinstance(entity, dict) and entity.get("id")
    ]
    events_by_year = {}
    for event in events:
        year = event_anchor_year(event)
        if year is not None:
            events_by_year.setdefault(year, []).append(str(event["id"]))

    years_by_century = {}
    centuries_by_top_period = {entity_id: set() for entity_id in top_entities}
    for year in sorted(events_by_year):
        century_number = century_number_for_year(year)
        years_by_century.setdefault(century_number, []).append(year)
        top_period = top_level_period_for_year(year, major_periods)
        if top_period is not None:
            centuries_by_top_period[str(top_period["entity_id"])].add(century_number)

    for century_number, years in sorted(years_by_century.items()):
        century_id = century_entity_id(century_number)
        start_year, end_year = century_bounds(century_number)
        overlapping_top_ids = [
            str(period["entity_id"])
            for period in top_period_records
            if int(period["start_year"]) <= end_year and int(period["end_year"]) >= start_year
        ]
        year_ids = [year_entity_id(year) for year in sorted(years)]
        _upsert_generated_entity(
            entities,
            periods_dataset,
            {
                "id": century_id,
                "_dataset": "periods",
                "type": "period",
                "name": century_label(century_number),
                "pretty_name": century_label(century_number),
                "period_class": "century",
                "start_year": start_year,
                "end_year": end_year,
                "parent_periods": overlapping_top_ids,
                "contained_periods": year_ids,
                "contained_events": [],
                "period_reference_generated": True,
            },
        )

        for year in sorted(years):
            top_period = top_level_period_for_year(year, major_periods)
            parent_periods = [century_id]
            if top_period is not None:
                parent_periods.append(str(top_period["entity_id"]))
            _upsert_generated_entity(
                entities,
                periods_dataset,
                {
                    "id": year_entity_id(year),
                    "_dataset": "periods",
                    "type": "period",
                    "name": f"Year {year}",
                    "pretty_name": f"Year {year}",
                    "period_class": "year",
                    "year": year,
                    "start_year": year,
                    "end_year": year,
                    "parent_periods": parent_periods,
                    "contained_periods": [],
                    "contained_events": sorted(events_by_year[year]),
                    "period_reference_generated": True,
                },
            )

    for entity_id, century_numbers in centuries_by_top_period.items():
        top_entities[entity_id]["contained_periods"] = [
            century_entity_id(number)
            for number in sorted(century_numbers)
        ]

    return True
