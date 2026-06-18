import re


def format_yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if "\n" in text:
        lines = text.splitlines()
        if not lines:
            return "''"
        return "|\n" + "\n".join(f"    {line}" for line in lines)

    if text == "":
        return "''"

    needs_quote = (
        text.strip() != text
        or text.lower() in {"null", "none", "true", "false", "yes", "no"}
        or any(ch in text for ch in [":", "#", "{", "}", "[", "]", ","])
    )
    if needs_quote:
        return "'" + text.replace("'", "''") + "'"
    return text


def format_yaml_value_lines(key, value, prefix):
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{key}: []"]

        lines = [f"{prefix}{key}:"]
        for item in value:
            if isinstance(item, dict):
                item_keys = list(item.keys())
                if not item_keys:
                    lines.append("  - {}")
                    continue

                first_key = item_keys[0]
                lines.append(f"  - {first_key}: {format_yaml_scalar(item.get(first_key))}")
                for child_key in item_keys[1:]:
                    child_value = item.get(child_key)
                    if isinstance(child_value, list):
                        if not child_value:
                            lines.append(f"    {child_key}: []")
                        else:
                            lines.append(f"    {child_key}:")
                            for child_item in child_value:
                                if isinstance(child_item, dict):
                                    nested_keys = list(child_item.keys())
                                    if not nested_keys:
                                        lines.append("      - {}")
                                        continue
                                    nested_first = nested_keys[0]
                                    lines.append(
                                        f"      - {nested_first}: "
                                        f"{format_yaml_scalar(child_item.get(nested_first))}"
                                    )
                                    for nested_key in nested_keys[1:]:
                                        lines.append(
                                            f"        {nested_key}: "
                                            f"{format_yaml_scalar(child_item.get(nested_key))}"
                                        )
                                else:
                                    lines.append(f"      - {format_yaml_scalar(child_item)}")
                        continue
                    if isinstance(child_value, dict):
                        if not child_value:
                            lines.append(f"    {child_key}: {{}}")
                        else:
                            lines.append(f"    {child_key}:")
                            for nested_key, nested_value in child_value.items():
                                lines.append(
                                    f"      {nested_key}: {format_yaml_scalar(nested_value)}"
                                )
                        continue
                    lines.append(f"    {child_key}: {format_yaml_scalar(child_value)}")
            else:
                lines.append(f"  - {format_yaml_scalar(item)}")
        return lines

    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{key}: {{}}"]

        lines = [f"{prefix}{key}:"]
        for child_key, child_value in value.items():
            if isinstance(child_value, list):
                if not child_value:
                    lines.append(f"    {child_key}: []")
                else:
                    lines.append(f"    {child_key}:")
                    for item in child_value:
                        lines.append(f"      - {format_yaml_scalar(item)}")
                continue
            lines.append(f"    {child_key}: {format_yaml_scalar(child_value)}")
        return lines

    return [f"{prefix}{key}: {format_yaml_scalar(value)}"]


def format_yaml_entity_block(entity, ordered_keys):
    keys = [key for key in ordered_keys if key in entity]
    keys.extend(key for key in entity if key not in keys and not key.startswith("_"))

    lines = []
    for index, key in enumerate(keys):
        prefix = "- " if index == 0 else "  "
        lines.extend(format_yaml_value_lines(key, entity.get(key), prefix))
    return "\n".join(lines).rstrip() + "\n"


def find_yaml_entity_block(text, entity_id):
    start_pattern = rf"(?m)^- id: {re.escape(str(entity_id))}\s*$"
    start_match = re.search(start_pattern, text)
    if not start_match:
        return None

    next_match = re.search(r"(?m)^- id: ", text[start_match.end():])
    block_end = start_match.end() + next_match.start() if next_match else len(text)
    return start_match.start(), block_end
