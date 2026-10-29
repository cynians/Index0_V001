"""Derive personality words' Big Five positions from Goldberg's 100 markers.

Source: Goldberg (1992), "The development of markers for the Big-Five
factor structure", Psychological Assessment 4(1), 26-42. Self-ratings of his
100 unipolar adjective markers by 554 participants of the Personality,
Motivation and Cognition Laboratory (Northwestern) ship as the dataset
``big5.100.adjectives`` in the R package psychTools (GPL >= 2), with the
words in ``bfi.adjectives.dictionary`` and scoring keys in
``big5.adjectives.keys``. Download ``psychTools_<version>.tar.gz`` from
CRAN and pass its path; only those three data files are read, nothing in
the package runs.

Method: pairwise-complete correlations, principal axis factoring with five
factors, varimax rotation; each factor is named and oriented by the
package's own keys (Emotional stability reversed to neuroticism). A word
names an axis where its loading is at least ``SALIENT``; its position
there is ``0.5 + 0.5 x loading``.

Every marker becomes a personality word (tag entity, ``tag_class:
personality``) carrying its position, all five loadings and its source.
Words the game needs that are not markers (Cruel, Obedient, Pacifist, ...)
take the mean loadings of named nearest markers, recorded in
``position_from``. Dry run by default; ``--apply`` writes, merging over
stored entities. See docs/person_personality_concept_v001.md section 8.
"""

import argparse
import copy
import gzip
import io
import json
import math
import struct
import sys
import tarfile
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
AXES = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
SALIENT = 0.30
SOURCE = "Goldberg 1992 Big-Five markers; psychTools big5.100.adjectives (n=554), PAF + varimax"
PERSONALITY_COLORS = {"primary_color": "#b58ad0", "secondary_color": "#2e2238"}

# Words the game uses that are not among the 100 markers, from their nearest
# markers ("-" reverses a marker). Judgement, recorded on each word.
COMPOSED = {
    "Curious": ["-Uninquisitive", "Intellectual"],
    "Conventional": ["Unimaginative", "Uncreative"],
    "Orderly": ["Organized", "Neat", "Systematic"],
    "Dutiful": ["Conscientious", "Prompt", "Thorough"],
    "Disciplined": ["Efficient", "Systematic"],
    "Impulsive": ["Unrestrained", "Haphazard"],
    "Ambitious": ["Assertive", "Efficient"],
    "Sociable": ["Extraverted"],
    "Brave": ["Bold", "Daring"],
    "Cowardly": ["Timid", "Fearful"],
    "Merciful": ["Sympathetic", "Kind"],
    "Trusting": ["Trustful"],
    "Loyal": ["Cooperative", "-Undependable"],
    "Obedient": ["Cooperative", "Prompt"],
    "Rebellious": ["Uncooperative", "Unrestrained"],
    "Greedy": ["Selfish", "Uncharitable"],
    "Suspicious": ["Distrustful"],
    "Vengeful": ["Harsh", "Irritable"],
    "Callous": ["Unsympathetic", "Cold"],
    "Cruel": ["Unkind", "Harsh", "Cold"],
    "Sadistic": ["Unkind", "Harsh", "Unsympathetic"],
    "Calm": ["Relaxed", "Imperturbable"],
    "Volatile": ["Temperamental", "Moody"],
    "Pacifist": ["Kind", "Cooperative"],
}
EXCLUSIONS = {"Pacifist": ["Violence"]}
DATA_FILES = ("big5.100.adjectives", "bfi.adjectives.dictionary", "big5.adjectives.keys")


# ---- reading R's serialized data (gzip + XDR), enough for data frames and lists

class _RReader:
    NA_INTEGER = -2147483648

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.refs = []

    def _take(self, n):
        chunk = self.data[self.pos:self.pos + n]
        if len(chunk) != n:
            raise ValueError("unexpected end of R data")
        self.pos += n
        return chunk

    def _int(self):
        return struct.unpack(">i", self._take(4))[0]

    def read(self):
        if self._take(5) not in (b"RDX2\n", b"RDX3\n") or self._take(2) != b"X\n":
            raise ValueError("not an XDR .rda file")
        version = self._int()
        self._int()
        self._int()
        if version == 3:
            self._take(self._int())
        top = self._item()
        return {tag: _plain(value) for tag, value in top["pairlist"]}

    def _item(self):
        flags = self._int()
        kind, has_attr, has_tag = flags & 0xFF, bool(flags & 512), bool(flags & 1024)
        if kind in (254, 253, 252, 251, 250, 242, 241):
            return None
        if kind == 255:
            index = flags >> 8 or self._int()
            return self.refs[index - 1]
        if kind == 1:
            name = self._item()
            self.refs.append(name)
            return name
        if kind in (2, 6, 17):
            entries = []
            while True:
                if has_attr:
                    self._item()
                tag = self._item() if has_tag else None
                entries.append((tag, self._item()))
                flags = self._int()
                kind, has_attr, has_tag = flags & 0xFF, bool(flags & 512), bool(flags & 1024)
                if kind not in (2, 6, 17):
                    self.pos -= 4
                    break
            self._item()
            return {"pairlist": entries}
        if kind == 9:
            length = self._int()
            return None if length == -1 else self._take(length).decode("utf-8", "replace")
        if kind in (10, 13):
            values = [self._int() for _ in range(self._int())]
            return self._vector([None if value == self.NA_INTEGER else value for value in values], has_attr)
        if kind == 14:
            values = [struct.unpack(">d", self._take(8))[0] for _ in range(self._int())]
            return self._vector([None if math.isnan(value) else value for value in values], has_attr)
        if kind in (16, 19, 20):
            return self._vector([self._item() for _ in range(self._int())], has_attr)
        if kind == 238:
            info, state = self._item(), self._item()
            self._item()
            klass = info["pairlist"][0][1] if isinstance(info, dict) else None
            values = state.get("values") if isinstance(state, dict) else state
            if klass == "compact_intseq" and isinstance(values, list) and len(values) == 3:
                n, start, step = (int(value) for value in values)
                return {"values": [start + step * i for i in range(n)], "attributes": {}}
            return state
        raise ValueError(f"unsupported R type {kind}")

    def _vector(self, values, has_attr):
        attributes = {}
        if has_attr:
            for tag, value in (self._item() or {}).get("pairlist", []):
                attributes[tag] = value
        return {"values": values, "attributes": attributes}


def _plain(obj):
    if isinstance(obj, dict) and "values" in obj:
        names = obj["attributes"].get("names")
        names = names["values"] if isinstance(names, dict) else names
        values = [_plain(value) for value in obj["values"]]
        return dict(zip(map(str, names), values)) if names and len(names) == len(values) else values
    return obj


def read_psychtools(tarball):
    objects = {}
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name).name
            if name.endswith(".rda") and name[:-4].lower() in {item.lower() for item in DATA_FILES}:
                raw = gzip.decompress(archive.extractfile(member).read())
                objects.update(_RReader(raw).read())
    missing = [name for name in DATA_FILES if name not in objects]
    if missing:
        raise SystemExit(f"{tarball} lacks {missing}")
    return objects


# ---- factor analysis

def _varimax(loadings, iterations=500, tol=1e-8):
    p, _k = loadings.shape
    rotation = np.eye(loadings.shape[1])
    last = 0.0
    for _ in range(iterations):
        rotated = loadings @ rotation
        u, s, vt = np.linalg.svd(
            loadings.T @ (rotated ** 3 - rotated @ np.diag((rotated ** 2).sum(axis=0)) / p)
        )
        rotation = u @ vt
        if s.sum() < last * (1 + tol):
            break
        last = s.sum()
    return loadings @ rotation


def marker_loadings(objects):
    """{word: {axis: loading}} for the 100 markers."""
    data = objects["big5.100.adjectives"]
    words = objects["bfi.adjectives.dictionary"]["Item"]  # in V1..V100 order
    keys = objects["big5.adjectives.keys"]
    items = [f"V{n}" for n in range(1, 101)]
    ratings = np.array([[np.nan if value is None else float(value) for value in data[item]] for item in items]).T
    count = ratings.shape[1]
    correlation = np.eye(count)
    for i in range(count):
        for j in range(i + 1, count):
            both = ~np.isnan(ratings[:, i]) & ~np.isnan(ratings[:, j])
            correlation[i, j] = correlation[j, i] = np.corrcoef(ratings[both, i], ratings[both, j])[0, 1]
    communalities = 1 - 1 / np.diag(np.linalg.inv(correlation))
    for _ in range(500):
        reduced = correlation.copy()
        np.fill_diagonal(reduced, communalities)
        values, vectors = np.linalg.eigh(reduced)
        order = np.argsort(values)[::-1][:5]
        loadings = vectors[:, order] * np.sqrt(np.maximum(values[order], 0))
        updated = (loadings ** 2).sum(axis=1)
        if np.max(np.abs(updated - communalities)) < 1e-7:
            break
        communalities = updated
    rotated = _varimax(loadings)
    index = {item: n for n, item in enumerate(items)}
    axes = {}
    for name, keyed in keys.items():
        signs = [(-1 if item.startswith("-") else 1, index[item.lstrip("-")]) for item in keyed]
        scores = [sum(sign * rotated[row, factor] for sign, row in signs) for factor in range(5)]
        factor = int(np.argmax(np.abs(scores)))
        axes[name.lower()] = rotated[:, factor] * (1 if scores[factor] > 0 else -1)
    if sorted(axes) != sorted(AXES):
        raise SystemExit(f"factors did not match the five axes: {sorted(axes)}")
    return {words[n]: {axis: float(axes[axis][n]) for axis in AXES} for n in range(len(items))}


# ---- words

def _position(loadings):
    return {axis: round(0.5 + 0.5 * value, 3) for axis, value in loadings.items() if abs(value) >= SALIENT}


def _key(word):
    return "tag_trait_" + word.lower().replace("-", "_").replace(" ", "_")


def word_entities(markers):
    entities = []
    for word, loadings in markers.items():
        entities.append({
            "id": _key(word), "_dataset": "tags", "type": "tag",
            "name": word, "pretty_name": word, "tag_class": "personality",
            "big_five": _position(loadings),
            "big_five_loadings": {axis: round(value, 3) for axis, value in loadings.items()},
            "position_source": SOURCE,
            **PERSONALITY_COLORS,
        })
    for word, parts in COMPOSED.items():
        mean = {axis: 0.0 for axis in AXES}
        for part in parts:
            sign = -1.0 if part.startswith("-") else 1.0
            for axis, value in markers[part.lstrip("-")].items():
                mean[axis] += sign * value / len(parts)
        entity = {
            "id": _key(word), "_dataset": "tags", "type": "tag",
            "name": word, "pretty_name": word, "tag_class": "personality",
            "big_five": _position(mean),
            "big_five_loadings": {axis: round(value, 3) for axis, value in mean.items()},
            "position_source": f"mean of markers: {', '.join(parts)}",
            "position_from": list(parts),
            **PERSONALITY_COLORS,
        }
        if word in EXCLUSIONS:
            entity["excludes_actions"] = list(EXCLUSIONS[word])
        entities.append(entity)
    return entities


TAG_FIELDS = {
    "big_five_loadings": {
        "type": "dict", "section": "Personality", "optional": True,
        "description": "For a personality word: its loading on each Big Five factor (-1..1) in the source analysis.",
    },
    "position_source": {
        "type": "string", "section": "Personality", "optional": True,
        "description": "Where a personality word's position comes from.",
    },
    "position_from": {
        "type": "string_list", "section": "Personality", "optional": True,
        "description": "For a word that is not a measured marker: the markers its position is the mean of ('-' reverses).",
    },
}


def build_changes(datasets, markers):
    by_id = {
        entity.get("id"): entity
        for entities in datasets.values() if isinstance(entities, list)
        for entity in entities if isinstance(entity, dict)
    }
    schema = copy.deepcopy(next(entity for entity in datasets.get("schemas", [])
                                if str(entity.get("schema") or entity.get("name")) == "tags"))
    schema["fields"] = {**(schema.get("fields") or {}), **copy.deepcopy(TAG_FIELDS)}
    changes = [schema]
    for entity in word_entities(markers):
        existing = by_id.get(entity["id"])
        merged = {**copy.deepcopy(existing), **entity} if existing else entity
        if not entity.get("position_from"):
            merged.pop("position_from", None)
        changes.append(merged)
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tarball", type=Path, help="psychTools_<version>.tar.gz from CRAN")
    parser.add_argument("--apply", action="store_true", help="Write to the ontology store; default is a dry run")
    args = parser.parse_args(argv)

    markers = marker_loadings(read_psychtools(args.tarball))
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets(), markers)
    for change in changes[1:]:
        print(f"{change['name']:<16} {json.dumps(change['big_five'])}  ({change['position_source'][:40]})")
    if not args.apply:
        print(f"Dry run: {len(changes)} entities would be written")
        return
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} personality word entities")


if __name__ == "__main__":
    main()
