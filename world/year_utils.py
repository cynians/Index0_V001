import re


MYA_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*mya\s*(?:ago)?\s*$", re.IGNORECASE)


def parse_year(value):
    """
    Normalize repository/UI year values.

    MYA values are years ago, so 9MYA is stored as -9000000.
    """
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

        match = MYA_RE.match(stripped)
        if match:
            return -int(float(match.group(1)) * 1_000_000)

        try:
            return int(float(stripped))
        except ValueError:
            return None

    return None
