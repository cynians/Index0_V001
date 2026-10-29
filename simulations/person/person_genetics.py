"""Versioned, compact genotype strings for person appearance.

The first format deliberately reserves most loci.  That gives Person Editor a
stable one-string contract now without pretending that three skin swatches are
a complete model of human genetics.

A child's genome comes from their parents' (inherit_person_dna): each body
locus stands for many genes, so the child lands around the parents' mean,
scattered by SEGREGATION_SD; skin tone the same on its three steps; every
reserved locus is copied from one parent or the other. With one parent
known, the unknown one counts as the population mean.
"""

from __future__ import annotations

import base64
import hashlib
import random
import zlib


DNA_PREFIX = "I0DNA1_"
DNA_VERSION = 1
GENOME_BYTES = 24

SKIN_TONES = (
    {"id": "light", "label": "Light", "color": (224, 184, 150)},
    {"id": "medium", "label": "Medium", "color": (174, 119, 82)},
    {"id": "deep", "label": "Deep", "color": (92, 58, 42)},
)

# Byte offsets within the reserved genome payload. The codec keeps these
# normalized; the renderer maps them into bounded visual proportions.
BODY_TRAITS = (
    {"id": "stature", "label": "Stature", "locus": 0},
    {"id": "leg_length", "label": "Leg length", "locus": 1},
    {"id": "arm_length", "label": "Arm length", "locus": 2},
    {"id": "torso_width", "label": "Torso width", "locus": 3},
    {"id": "shoulder_width", "label": "Shoulder width", "locus": 4},
    {"id": "head_size", "label": "Head size", "locus": 5},
)


def _tone_index(tone_id):
    tone_id = str(tone_id or "").strip().casefold()
    return next((index for index, tone in enumerate(SKIN_TONES) if tone["id"] == tone_id), 1)


def _encode_body(body):
    checksum = zlib.crc32(body).to_bytes(4, "big")
    return DNA_PREFIX + base64.urlsafe_b64encode(body + checksum).decode("ascii").rstrip("=")


def create_person_dna(seed, skin_tone_id="medium"):
    """Create deterministic v1 DNA for a person or editor seed."""
    genome = hashlib.sha256(str(seed or "person").encode("utf-8")).digest()[:GENOME_BYTES]
    body = bytes((DNA_VERSION, _tone_index(skin_tone_id))) + genome
    return _encode_body(body)


def decode_person_dna(value):
    """Decode a v1 string, returning an explicit validity/status record."""
    text = str(value or "").strip()
    fallback = {**SKIN_TONES[1]}
    fallback_shape = {trait["id"]: 0.5 for trait in BODY_TRAITS}
    if not text:
        return {"valid": False, "status": "missing", "skin_tone": fallback, "body_shape": fallback_shape}
    if not text.startswith(DNA_PREFIX):
        return {"valid": False, "status": "unknown_format", "skin_tone": fallback, "body_shape": fallback_shape}
    encoded = text[len(DNA_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError):
        return {"valid": False, "status": "invalid_encoding", "skin_tone": fallback, "body_shape": fallback_shape}
    expected_length = 2 + GENOME_BYTES + 4
    if len(raw) != expected_length:
        return {"valid": False, "status": "invalid_length", "skin_tone": fallback, "body_shape": fallback_shape}
    body, checksum = raw[:-4], raw[-4:]
    if zlib.crc32(body).to_bytes(4, "big") != checksum:
        return {"valid": False, "status": "checksum_mismatch", "skin_tone": fallback, "body_shape": fallback_shape}
    if body[0] != DNA_VERSION:
        return {"valid": False, "status": "unsupported_version", "skin_tone": fallback, "body_shape": fallback_shape}
    tone_index = body[1]
    if tone_index >= len(SKIN_TONES):
        return {"valid": False, "status": "unknown_skin_locus", "skin_tone": fallback, "body_shape": fallback_shape}
    reserved_loci = body[2:]
    return {
        "valid": True,
        "status": "ok",
        "version": body[0],
        "skin_tone": {**SKIN_TONES[tone_index]},
        "reserved_loci": reserved_loci,
        "body_shape": {
            trait["id"]: reserved_loci[trait["locus"]] / 255.0
            for trait in BODY_TRAITS
        },
    }


def set_skin_tone(value, skin_tone_id, seed="person"):
    """Change only the skin-tone locus, preserving all other v1 loci."""
    decoded = decode_person_dna(value)
    if not decoded["valid"]:
        return create_person_dna(seed, skin_tone_id)
    body = bytes((DNA_VERSION, _tone_index(skin_tone_id))) + decoded["reserved_loci"]
    return _encode_body(body)


def set_body_trait(value, trait_id, normalized_value, seed="person"):
    """Change one morphology locus while preserving every other locus."""
    trait = next((entry for entry in BODY_TRAITS if entry["id"] == trait_id), None)
    if trait is None:
        return value
    decoded = decode_person_dna(value)
    if not decoded["valid"]:
        decoded = decode_person_dna(create_person_dna(seed))
    try:
        normalized = max(0.0, min(1.0, float(normalized_value)))
    except (TypeError, ValueError):
        normalized = 0.5
    loci = bytearray(decoded["reserved_loci"])
    loci[trait["locus"]] = round(normalized * 255)
    body = bytes((DNA_VERSION, _tone_index(decoded["skin_tone"]["id"]))) + bytes(loci)
    return _encode_body(body)


# How far a child's body locus falls from the parents' mean (0-1 scale).
SEGREGATION_SD = 0.12
# The same on the skin tone steps (0, 1, 2).
TONE_SEGREGATION_SD = 0.45


def inherit_person_dna(parent_dnas, seed):
    """A child's v1 DNA from one or two parents' DNA strings; any invalid one is left out."""
    parents = [decoded for decoded in (decode_person_dna(value) for value in parent_dnas or []) if decoded["valid"]][:2]
    if not parents:
        return create_person_dna(seed)
    rng = random.Random(hashlib.sha256(f"inherit:{seed}".encode("utf-8")).digest())
    body_loci = {trait["locus"] for trait in BODY_TRAITS}
    loci = bytearray(GENOME_BYTES)
    for locus in range(GENOME_BYTES):
        values = [decoded["reserved_loci"][locus] for decoded in parents]
        if locus in body_loci:
            mean = sum(values) / len(values) / 255.0
            if len(parents) == 1:
                mean = (mean + 0.5) / 2
            loci[locus] = round(max(0.0, min(1.0, rng.gauss(mean, SEGREGATION_SD))) * 255)
        elif len(parents) == 2:
            loci[locus] = rng.choice(values)
        else:
            loci[locus] = values[0] if rng.random() < 0.5 else rng.randrange(256)
    tones = [_tone_index(decoded["skin_tone"]["id"]) for decoded in parents]
    if len(tones) == 1:
        tones.append(_tone_index("medium"))
    tone = round(max(0.0, min(len(SKIN_TONES) - 1.0, rng.gauss(sum(tones) / 2, TONE_SEGREGATION_SD))))
    return _encode_body(bytes((DNA_VERSION, tone)) + bytes(loci))


def appearance_from_person(person):
    """Resolve renderer-safe appearance without persisting a guessed default."""
    person = person if isinstance(person, dict) else {}
    decoded = decode_person_dna(person.get("genetic_dna"))
    return {
        "dna_status": decoded["status"],
        "skin_tone_id": decoded["skin_tone"]["id"],
        "skin_tone_label": decoded["skin_tone"]["label"],
        "skin_color": tuple(decoded["skin_tone"]["color"]),
        "body_shape": dict(decoded["body_shape"]),
    }
