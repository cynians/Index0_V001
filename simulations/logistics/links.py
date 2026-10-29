"""
Links: a way between two places in one domain, with what it asks of a vehicle
(docs/logistics_simulation_concept_v001.md section 3.1). Links are derived,
never authored one by one.
"""
from dataclasses import dataclass, field


INTERPLANETARY = "interplanetary"
ORBITAL = "orbital"

# Leaving every planet's protection needs deep-space shielding; staying in a
# planet's neighbourhood (moon to moon) needs orbital shielding.
SHIELDING_BY_DOMAIN = {INTERPLANETARY: "deep_space", ORBITAL: "orbital"}


@dataclass(frozen=True)
class Link:
    domain: str
    origin_id: str
    target_id: str
    depart_t: float
    arrive_t: float
    requirements: dict = field(default_factory=dict, hash=False)

    @property
    def duration_s(self):
        return self.arrive_t - self.depart_t


def link_from_transfer_window(window, domain=INTERPLANETARY):
    """
    A link from a transfer window: its headline delta-v (escape from and
    capture into low orbits), life support for the whole flight, and the
    shielding its domain calls for.
    """
    return Link(
        domain=domain,
        origin_id=window.leg.origin_id,
        target_id=window.leg.target_id,
        depart_t=window.leg.depart_t,
        arrive_t=window.leg.arrive_t,
        requirements={
            "delta_v_m_s": window.total_dv,
            "shielding_class": SHIELDING_BY_DOMAIN[domain],
            "life_support_s": window.leg.tof,
        },
    )
