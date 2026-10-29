"""
One vocabulary for what a link asks of a vehicle and what a vehicle can do
(docs/logistics_simulation_concept_v001.md sections 3.2 and 3.3).

A requirement and a capability use the same term, so checking a vehicle
against a link is a comparison per term. The terms are code, like the
component port resource types; the values are ontology facts on links,
designs and vehicles. Space terms only so far; other domains add theirs.
"""
from dataclasses import dataclass


AT_LEAST = "at_least"   # the vehicle's value must reach the requirement
RANKED = "ranked"       # the vehicle's class must rank at or above the required one
FLAG = "flag"           # the vehicle must have it


@dataclass(frozen=True)
class Term:
    key: str
    kind: str
    label: str
    unit: str = ""
    ranks: tuple = ()


TERMS = {term.key: term for term in (
    Term("delta_v_m_s", AT_LEAST, "delta-v", "m/s"),
    Term("shielding_class", RANKED, "shielding", ranks=("none", "orbital", "deep_space")),
    Term("life_support_s", AT_LEAST, "life support", "s"),
    Term("atmosphere_entry", FLAG, "atmosphere entry"),
    Term("docking", FLAG, "docking"),
)}


@dataclass(frozen=True)
class Shortfall:
    """A requirement a profile does not meet; `has` is None when the profile does not know."""
    key: str
    needed: object
    has: object

    @property
    def unknown(self):
        return self.has is None


def shortfalls(profile, requirements):
    """Every requirement the profile misses or cannot show, in the requirements' order."""
    missing = []
    for key, needed in requirements.items():
        term = TERMS[key]
        has = profile.get(key)
        if has is None:
            missing.append(Shortfall(key, needed, None))
        elif term.kind == AT_LEAST and has < needed:
            missing.append(Shortfall(key, needed, has))
        elif term.kind == RANKED and term.ranks.index(has) < term.ranks.index(needed):
            missing.append(Shortfall(key, needed, has))
        elif term.kind == FLAG and needed and not has:
            missing.append(Shortfall(key, needed, has))
    return missing


def is_eligible(profile, requirements):
    return not shortfalls(profile, requirements)


def stronger_rank(key, first, second):
    """The higher-ranked of two classes of a ranked term; None counts as lowest."""
    ranks = TERMS[key].ranks
    if first is None:
        return second
    if second is None:
        return first
    return first if ranks.index(first) >= ranks.index(second) else second
