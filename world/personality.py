"""Personality: a Big Five distribution from birth, narrowed by personality words.

On each of the five axes (0-1) a person is a distribution, not a point: a
mean and a spread. At birth the mean is drawn around the population mean
from the person's ``birth_seed`` (else their id; deterministic, the draw
itself never stored, until a birth model with parents and genetics exists)
and the spread is the population's. A person whose ``parents`` name people
is drawn around their parents instead: each known parent pulls the birth
mean by HERITABILITY / 2 of their distance from the population mean (their
own personality, words included, their parents' pull included), and the
spread narrows by what the parents explain. An unknown parent counts as the
population. An authored ``big_five_<axis>`` score is a birth mean known
more precisely; it ignores the parents.

Personality words are tag entities with ``tag_class: personality`` and a
``big_five`` position naming only the axes the word speaks to. Each of a
person's words (``personality_adjectives``) is evidence about the axes it
names, itself a distribution around the word's position. Birth and words
combine by their precision: the mean moves toward the words as far as the
words are surer than the birth estimate, and the spread narrows with every
word. Decisions are checked against the whole distribution.

Words and decisions can exclude each other outright. A word's
``excludes_actions`` (Pacifist excludes Violence) and an action tag's
``excluded_by_traits`` take a decision out of the person's consideration.
Action tags (``tag_class: action``) nest through ``parents`` (Torture is
Violence). An action tag's ``trait_profiles`` say who does it and who
refuses: ``{"for": [[words], ...], "against": [[words], ...]}``.

See docs/person_personality_concept_v001.md.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from world.entity_references import entity_reference_ids
from world.tag_rows import lookup_key


AXES = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
WORDS_FIELD = "personality_adjectives"
SEED_FIELD = "birth_seed"
TAG_DATASET = "tags"
POPULATION_MEAN = 0.5
POPULATION_SD = 0.15
# How sure each source is about an axis, as a spread on the 0-1 scale.
BIRTH_SPREAD = POPULATION_SD
AUTHORED_SPREAD = 0.08
WORD_SPREAD = 0.12
CHARACTER_WEIGHT = 120.0
# Share of Big Five differences that runs in families: about 40% in twin
# and family studies (Vukasovic and Bratko 2015, meta-analysis), used here
# as the child-on-midparent slope.
HERITABILITY = 0.4
PERSON_DATASETS = ("people", "person")
# How many generations up the parents' pull is followed.
ANCESTOR_DEPTH = 4


@dataclass(frozen=True)
class AxisValue:
    axis: str
    baseline: float
    baseline_spread: float
    # "authored" or "birth"
    baseline_source: str
    # the combined distribution
    value: float
    spread: float
    # (label, position) of each word that speaks to this axis
    words: tuple
    # (label, value) of each parent whose personality the birth draw leaned toward
    parents: tuple = ()


def _tag_index(world_model, tag_class):
    getter = getattr(world_model, "get_dataset", None)
    index = {}
    for entity in (getter(TAG_DATASET) if callable(getter) else None) or []:
        if not isinstance(entity, dict) or str(entity.get("tag_class") or "").strip().lower() != tag_class:
            continue
        keys = {lookup_key(entity.get(field)) for field in ("id", "name", "pretty_name")}
        keys.update(key[4:] for key in list(keys) if key.startswith("tag_"))
        for key in keys - {""}:
            index.setdefault(key, entity)
    return index


def trait_index(world_model):
    return _tag_index(world_model, "personality")


def action_index(world_model):
    return _tag_index(world_model, "action")


def label(entity):
    return str(entity.get("pretty_name") or entity.get("name") or entity.get("id"))


def _number(value):
    """A 0-1 score; authored scores may also be written as percentages (72 means 0.72)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 < number <= 100.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def birth_baseline(person_id, axis, mean=POPULATION_MEAN, spread=POPULATION_SD):
    """A deterministic draw from a seed around a mean: the population's, or one leaning to the parents."""
    digest = hashlib.sha256(f"{person_id}:{axis}".encode("utf-8")).digest()
    first = (int.from_bytes(digest[:8], "big") + 1) / (2 ** 64 + 1)
    second = int.from_bytes(digest[8:16], "big") / 2 ** 64
    normal = math.sqrt(-2.0 * math.log(first)) * math.cos(math.tau * second)
    return max(0.02, min(0.98, mean + spread * normal))


def inherited_birth(parent_values):
    """Birth mean and spread on an axis from the parents' (value, spread) there; none known gives the population."""
    pull = HERITABILITY / 2
    mean = POPULATION_MEAN + sum(pull * (value - POPULATION_MEAN) for value, _spread in parent_values)
    variance = POPULATION_SD ** 2 * (1 - len(parent_values) * pull ** 2)
    variance += sum((pull * spread) ** 2 for _value, spread in parent_values)
    return mean, math.sqrt(variance)


def parent_people(person, world_model):
    """The people among a person's ``parents``, two at most."""
    getter = getattr(world_model, "get_entity", None)
    if not callable(getter):
        return []
    found = []
    for reference in entity_reference_ids((person or {}).get("parents")):
        entity = getter(reference)
        if isinstance(entity, dict) and (entity.get("type") == "person" or entity.get("_dataset") in PERSON_DATASETS):
            found.append(entity)
    return found[:2]


def combine(mean, spread, evidence):
    """Combine a distribution with evidence positions, each with WORD_SPREAD, by precision."""
    precision = 1.0 / spread ** 2 + len(evidence) / WORD_SPREAD ** 2
    weighted = mean / spread ** 2 + sum(evidence) / WORD_SPREAD ** 2
    return weighted / precision, precision ** -0.5


def birth_seed(person):
    """What a person's birth draw is made from: their birth seed, else their id."""
    person = person or {}
    return str(person.get(SEED_FIELD) or person.get("id") or "")


def authored_baseline(person, axis):
    nested = person.get("big_five") or person.get("personality_big_five") or {}
    if isinstance(nested, dict) and _number(nested.get(axis)) is not None:
        return _number(nested.get(axis))
    for field_name in (f"big_five_{axis}", f"personality_{axis}"):
        if _number(person.get(field_name)) is not None:
            return _number(person.get(field_name))
    return None


def person_words(person):
    raw = (person or {}).get(WORDS_FIELD) or []
    return [str(word).strip() for word in (raw if isinstance(raw, (list, tuple)) else [raw]) if str(word).strip()]


def person_traits(person, index):
    """The person's words that are known personality terms, and those that are not."""
    known, unknown = [], []
    for word in person_words(person):
        trait = index.get(lookup_key(word))
        (known if trait is not None else unknown).append(trait if trait is not None else word)
    return known, unknown


def position(trait):
    raw = trait.get("big_five") or {}
    return {axis: _number(raw.get(axis)) for axis in AXES if isinstance(raw, dict) and _number(raw.get(axis)) is not None}


def personality(person, world_model=None, index=None, _lineage=()):
    """Each axis: the birth (or authored) distribution, the words on it, and the distribution they combine to."""
    person = person or {}
    index = trait_index(world_model) if index is None else index
    traits, _unknown = person_traits(person, index)
    lineage = _lineage + (person.get("id"),)
    parents = [
        (label(parent), personality(parent, world_model, index, lineage))
        for parent in (parent_people(person, world_model) if len(lineage) <= ANCESTOR_DEPTH else [])
        if parent.get("id") not in lineage
    ]
    result = {}
    for axis in AXES:
        baseline, baseline_spread, source = authored_baseline(person, axis), AUTHORED_SPREAD, "authored"
        if baseline is None:
            mean, baseline_spread = inherited_birth([(values[axis].value, values[axis].spread) for _name, values in parents])
            baseline = birth_baseline(birth_seed(person), axis, mean, baseline_spread)
            source = "inherited" if parents else "birth"
        words = tuple((label(trait), position(trait)[axis]) for trait in traits if axis in position(trait))
        value, spread = combine(baseline, baseline_spread, [place for _name, place in words])
        result[axis] = AxisValue(axis, baseline, baseline_spread, source, value, spread, words,
                                 tuple((name, values[axis].value) for name, values in parents))
    return result


POPULATION = {
    axis: AxisValue(axis, POPULATION_MEAN, POPULATION_SD, "population", POPULATION_MEAN, POPULATION_SD, ())
    for axis in AXES
}


def action_chain(action_tags, index):
    """The action tag entities a decision carries, each followed by what it is a kind of."""
    by_id = {entity.get("id"): entity for entity in index.values()}
    chain = []
    queue = [index.get(lookup_key(tag)) for tag in action_tags or []]
    while queue:
        action = queue.pop(0)
        if action is None or any(action is seen for seen in chain):
            continue
        chain.append(action)
        queue.extend(by_id.get(parent) for parent in entity_reference_ids(action.get("parents")))
    return chain


def exclusion(person, action_tags, world_model=None, traits=None, actions=None):
    """Why a decision is out of the person's consideration, e.g. 'Pacifist excludes Violence', or None."""
    traits = trait_index(world_model) if traits is None else traits
    actions = action_index(world_model) if actions is None else actions
    chain = action_chain(action_tags, actions)
    if not chain:
        return None
    chain_keys = {lookup_key(label(action)): action for action in chain}
    chain_keys.update({lookup_key(action.get("id")): action for action in chain})
    held, _unknown = person_traits(person, traits)
    for trait in held:
        for excluded in trait.get("excludes_actions") or []:
            action = chain_keys.get(lookup_key(excluded))
            if action is not None:
                return f"{label(trait)} excludes {label(action)}"
    held_keys = {lookup_key(label(trait)) for trait in held}
    for action in chain:
        for excluding in action.get("excluded_by_traits") or []:
            if lookup_key(excluding) in held_keys:
                return f"{label(action)} is excluded for the {excluding.lower()}"
    return None


def profile(words, traits):
    """The distribution a set of words describes, on the axes they name: {axis: (mean, spread)}."""
    places = {}
    for word in words or []:
        trait = traits.get(lookup_key(word))
        for axis, place in position(trait or {}).items():
            places.setdefault(axis, []).append(place)
    return {
        axis: (sum(values) / len(values), WORD_SPREAD / math.sqrt(len(values)))
        for axis, values in places.items()
    }


def fit(distribution, described):
    """How far a person's distribution overlaps a described one, 0-1, on the described axes only."""
    if not described:
        return 0.0
    terms = [
        (distribution[axis].value - mean) ** 2 / (2.0 * (distribution[axis].spread ** 2 + spread ** 2))
        for axis, (mean, spread) in described.items()
    ]
    return math.exp(-sum(terms) / len(terms))


def character(distribution, action_tags, world_model=None, traits=None, actions=None):
    """The character term of a decision: (value, explanation), or (0, '') when no carried action says who does it.

    A profile counts by how much better the person fits it than an average
    person of the population would: an average person gets nothing either way.
    """
    traits = trait_index(world_model) if traits is None else traits
    actions = action_index(world_model) if actions is None else actions
    best = {"for": None, "against": None}
    for action in action_chain(action_tags, actions):
        profiles = action.get("trait_profiles") or {}
        for side in best:
            for words in profiles.get(side) or []:
                described = profile(words, traits)
                if not described:
                    continue
                person_fit = fit(distribution, described)
                excess = person_fit - fit(POPULATION, described)
                if best[side] is None or excess > best[side][0]:
                    best[side] = (excess, person_fit, " and ".join(str(word) for word in words))
    if best["for"] is None and best["against"] is None:
        return 0.0, ""
    value = 0.0
    parts = []
    if best["for"] is not None:
        excess, person_fit, name = best["for"]
        value += CHARACTER_WEIGHT * excess
        parts.append(f"{'fits' if excess >= 0 else 'unlike'} {name} ({person_fit * 100:.0f}%)")
    if best["against"] is not None and best["against"][0] > 0.0:
        excess, person_fit, name = best["against"]
        value -= CHARACTER_WEIGHT * excess
        parts.append(f"{name} refuses ({person_fit * 100:.0f}%)")
    return value, "Character: " + "; ".join(parts)
