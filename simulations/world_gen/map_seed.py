import hashlib


def resolved_map_seed(seed=None, planet_id="", system_id=""):
    seed = seed if isinstance(seed, dict) else {}
    explicit = str(seed.get("map_seed") or "").strip()
    if explicit and explicit.lower() != "auto":
        return explicit

    parts = [
        str(system_id or seed.get("star_system") or seed.get("parent_system_id") or "system").strip(),
        str(planet_id or seed.get("planet_id") or seed.get("id") or "planet").strip(),
    ]
    return ":".join(part or "auto" for part in parts)


def seed_unit(seed_text, salt=""):
    payload = f"{seed_text}|{salt}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], "big")
    return value / float((1 << 64) - 1)


def seed_range(seed_text, salt, low, high):
    return float(low) + (float(high) - float(low)) * seed_unit(seed_text, salt)
