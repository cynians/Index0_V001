def find_link_seed(text, cursor):
    text = str(text or "")
    cursor = max(0, min(len(text), int(cursor)))

    start = cursor
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in {"_", "-"}):
        start -= 1

    end = cursor
    while end < len(text) and (text[end].isalnum() or text[end] in {"_", "-"}):
        end += 1

    query = text[start:end].strip()
    if not query:
        start = cursor
        end = cursor
    return query, start, end


def choose_link_target(matches, selected_index, query):
    matches = list(matches or [])
    if matches:
        selected_index = max(0, min(int(selected_index or 0), len(matches) - 1))
        return matches[selected_index].get("id")
    return str(query or "").strip() or None


def insert_wiki_link(text, target, replace_range=None, cursor=None):
    text = str(text or "")
    target = str(target or "").strip()
    if not target:
        return None

    cursor = len(text) if cursor is None else max(0, min(len(text), int(cursor)))
    try:
        replace_start, replace_end = replace_range
    except (TypeError, ValueError):
        replace_start, replace_end = cursor, cursor

    replace_start = max(0, min(len(text), int(replace_start)))
    replace_end = max(replace_start, min(len(text), int(replace_end)))
    before = text[:replace_start]
    after = text[replace_end:]
    insertion = f"[[{target}]]"
    leading_space = " " if before and not before.endswith((" ", "\n")) else ""
    trailing_space = (
        " "
        if after and not after.startswith((" ", "\n", ".", ",", ";", ":", ")", "]"))
        else ""
    )
    updated_text = f"{before}{leading_space}{insertion}{trailing_space}{after}"
    updated_cursor = len(before) + len(leading_space) + len(insertion) + len(trailing_space)
    return updated_text, updated_cursor


def build_entity_link_matches(
        entities,
        query,
        display_label,
        coerce_year,
        limit=12,
):
    normalized_query = str(query or "").strip().lower()
    matches = []

    for entity in entities:
        entity_id = entity.get("id")
        if not entity_id:
            continue

        pretty_name = display_label(entity, entity_id)
        haystack = " ".join(
            [
                str(pretty_name),
                str(entity_id),
                str(entity.get("common_name", "")),
                str(entity.get("binomial_name", "")),
                str(entity.get("name", "")),
            ]
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue

        matches.append(
            {
                "id": entity_id,
                "pretty_name": str(pretty_name),
                "dataset": entity.get("_dataset", ""),
                "entity_type": entity.get("type", "entity"),
                "start_year": coerce_year(
                    entity.get("start_year")
                    if entity.get("start_year") is not None
                    else entity.get("year")
                ),
                "end_year": coerce_year(entity.get("end_year")),
            }
        )

    matches.sort(key=lambda item: (item["pretty_name"].lower(), item["id"]))
    return matches[:limit]
