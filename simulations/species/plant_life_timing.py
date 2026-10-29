"""How long a plant takes to grow up and how long it lives, in real time.

Species Sim grows a body on a developmental clock sized for its age slider:
a tree is "mature" after a few months of it, and every perennial reads as
senescent a year later.  A landscape that is built over decades needs real
time instead.

A species may author both figures (``maturity_age`` and ``longevity``, in
years).  Where it does not, they are derived from the classes it does author:
growth form, ``maturity_rate``, ``longevity_class`` and the life cycle.  The
fallbacks are generic placements, labelled as such, not measurements.

Maturity is full size.  A woody plant sets seed long before it gets there:
an oak bears acorns at forty and is still gaining height at a hundred.  Its
reproductive age (``reproductive_days``) is kept apart, and a generic woody
plant reaches full size only a share of the way through its life.

The body itself keeps Species Sim's developmental clock: ``developmental_days``
maps an organism's real age onto it, so a forty-year oak is drawn as the body
Species Sim calls mature.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


DAYS_PER_YEAR = 365.25

# Years to regular reproduction at a "moderate" maturity rate; for all but
# woody forms that is also full size.  Only forms that take years: herbs,
# grasses, crusts and mosses mature within the season or two their
# developmental clock already gives them.
MATURITY_YEARS_BY_FORM = {
    "tree": 20.0, "shrub": 5.0, "subshrub": 3.0, "succulent": 6.0, "fern": 3.0, "vine": 4.0,
}
MATURITY_RATE_FACTOR = {"rapid": 0.35, "very_fast": 0.35, "fast": 0.6, "moderate": 1.0, "slow": 2.0}

# Years an individual lives at a "moderate" longevity class.
LIFESPAN_YEARS_BY_FORM = {
    "tree": 150.0, "shrub": 30.0, "subshrub": 12.0, "succulent": 40.0, "fern": 25.0, "vine": 30.0,
    "lichen": 40.0, "moss": 10.0, "graminoid": 8.0, "forb": 6.0, "aquatic": 10.0,
}
LONGEVITY_FACTOR = {"very_short": 0.25, "short": 0.5, "moderate": 1.0, "long": 2.0, "very_long": 4.0}
SHORT_LIVED_PERENNIAL_YEARS = 6.0

# A woody plant without an authored figure stands full-grown this share of the way through its life, and
# never before it sets seed: an oak of 600 years at 120, a birch of 150 at 30 to 40.  A generic placement
# (height growth levels off at a fifth to a third of a tree's life), not a measurement.
FULL_SIZE_SHARE_OF_LIFE = {"tree": 0.2, "shrub": 0.2, "vine": 0.2}

# An individual declines over the last fifth of its adult life.
SENESCENCE_SHARE = 0.8
# A life cycle that ends with reproduction already runs in real days.
TERMINAL_LIFE_CYCLES = frozenset({"ephemeral", "annual", "biennial"})


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _authored_years(value, keys):
    """A year count from an authored trait: a number, or the first of ``keys`` in a dict."""
    if isinstance(value, dict):
        for key in keys:
            number = _positive(value.get(key))
            if number is not None:
                return number
        return None
    if isinstance(value, bool):
        return None
    return _positive(value)


def _key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def describe_span(days):
    """A span in the unit a person would use: weeks, months or years."""
    if days is None:
        return "unresolved"
    years = float(days) / DAYS_PER_YEAR
    if years >= 1.5:
        return f"{years:.0f} years"
    if years >= 0.95:
        return "1 year"
    months = years * 12.0
    if months >= 1.5:
        return f"{months:.0f} months"
    return f"{max(1.0, float(days) / 7.0):.0f} weeks"


def life_timing_lines(maturity_days, maturity_source, lifespan_days, lifespan_source, seed_days=None):
    """Short lines for a species card: the figures, and whether each is authored or generic."""
    kind = lambda source: "authored" if source == "authored" else "generic"
    lines = [f"Full size: about {describe_span(maturity_days)} ({kind(maturity_source)})"]
    if seed_days is not None and maturity_days is not None and seed_days < 0.95 * maturity_days:
        lines.append(f"Sets seed: from about {describe_span(seed_days)} ({kind(maturity_source)})")
    lines.append(f"Lifespan: about {describe_span(lifespan_days)} ({kind(lifespan_source)})")
    return lines


@dataclass(frozen=True)
class PlantLifeTiming:
    """A species' life in real days, and the developmental clock it maps onto."""

    life_cycle: str
    # Real days to full size.
    maturity_days: float
    lifespan_days: float
    senescence_start_days: float
    maturity_source: str
    lifespan_source: str
    # Species Sim's own landmarks, in developmental days.
    developmental_maturity_days: float
    developmental_senescence_days: float
    developmental_end_days: float
    # False for a cycle that ends with reproduction: its developmental clock is real time.
    real_clock: bool = True
    # Real days to regular reproduction; ``None`` when that is full size.
    reproductive_days: float = None

    @property
    def seed_days(self):
        """Real days to regular reproduction: full size, or earlier for a woody plant."""
        return self.maturity_days if self.reproductive_days is None else min(self.maturity_days, self.reproductive_days)

    def developmental_days(self, real_age_days):
        """The developmental age of a body that has lived ``real_age_days``."""
        age = max(0.0, float(real_age_days))
        if not self.real_clock:
            return age
        grown, old, end = self.developmental_maturity_days, self.developmental_senescence_days, self.developmental_end_days
        if age <= self.maturity_days:
            return grown * age / self.maturity_days
        if age <= self.senescence_start_days:
            share = (age - self.maturity_days) / max(1e-9, self.senescence_start_days - self.maturity_days)
            return grown + (old - grown) * share
        if age < self.lifespan_days:
            share = (age - self.senescence_start_days) / max(1e-9, self.lifespan_days - self.senescence_start_days)
            return old + (end - old) * share
        return end

    def life_history_profile(self, developmental_profile):
        """Species Sim's life-history profile with its timings in real days."""
        profile = dict(developmental_profile or {})
        if not self.real_clock:
            return profile
        # The adult phase begins when the plant sets seed, not when it stops growing.
        profile.update({
            "maturity_days": self.seed_days,
            "reproductive_start_days": self.seed_days,
            "senescence_start_days": self.senescence_start_days,
            "age_limit_days": self.lifespan_days,
            "timing_source": f"{self.maturity_source}; {self.lifespan_source}",
        })
        return profile

    def summary_lines(self):
        return life_timing_lines(self.maturity_days, self.maturity_source, self.lifespan_days, self.lifespan_source,
                                 self.seed_days)


def resolve_plant_life_timing(entity, growth):
    """Real maturity and lifespan for a species entity and its blueprint ``growth`` data."""
    entity = entity or {}
    growth = growth or {}
    history = growth.get("life_history") if isinstance(growth.get("life_history"), dict) else {}
    life_cycle = _key(history.get("class")) or "perennial"
    developmental_maturity = max(1.0, float(growth.get("maturity_days", 90.0) or 90.0))
    developmental_senescence = max(developmental_maturity, float(history.get("senescence_start_days", developmental_maturity) or developmental_maturity))
    age_limit = _positive(history.get("age_limit_days"))
    developmental_end = max(
        developmental_senescence + 1.0,
        age_limit if age_limit is not None else developmental_senescence + max(365.0, float(history.get("cycle_days", 365.0) or 365.0)),
    )
    form = _key(entity.get("plant_growth_form")) or "forb"

    if life_cycle in TERMINAL_LIFE_CYCLES and age_limit is not None:
        label = f"{life_cycle} life cycle"
        return PlantLifeTiming(
            life_cycle=life_cycle, maturity_days=developmental_maturity, lifespan_days=age_limit,
            senescence_start_days=developmental_senescence, maturity_source=label, lifespan_source=label,
            developmental_maturity_days=developmental_maturity, developmental_senescence_days=developmental_senescence,
            developmental_end_days=developmental_end, real_clock=False,
        )

    authored_maturity = _authored_years(entity.get("maturity_age"), ("typical_years", "years", "min_years"))
    rate = _key(entity.get("maturity_rate"))
    if authored_maturity is not None:
        maturity_years, maturity_source = authored_maturity, "authored"
    elif form in MATURITY_YEARS_BY_FORM:
        factor = MATURITY_RATE_FACTOR.get(rate)
        maturity_years = MATURITY_YEARS_BY_FORM[form] * (factor if factor is not None else 1.0)
        maturity_source = f"generic for a {rate.replace('_', ' ') + '-maturing ' if factor is not None else ''}{form}"
    else:
        maturity_years = developmental_maturity / DAYS_PER_YEAR
        maturity_source = f"generic for a {form}"

    authored_lifespan = _authored_years(entity.get("longevity"), ("typical_years", "years", "max_years"))
    longevity = _key(entity.get("longevity_class"))
    factor = LONGEVITY_FACTOR.get(longevity)
    if authored_lifespan is not None:
        lifespan_years, lifespan_source = authored_lifespan, "authored"
    elif life_cycle == "short_lived_perennial":
        lifespan_years = max(2.0, min(12.0, SHORT_LIVED_PERENNIAL_YEARS * (factor if factor is not None else 1.0)))
        lifespan_source = "generic for a short-lived perennial"
    else:
        lifespan_years = LIFESPAN_YEARS_BY_FORM.get(form, LIFESPAN_YEARS_BY_FORM["forb"]) * (factor if factor is not None else 1.0)
        lifespan_source = f"generic for a {longevity.replace('_', ' ') + '-lived ' if factor is not None else ''}{form}"
    # An adult life has to exist, whatever two generic figures say together.
    # Respect authored longevity above maturity; only generic pairs need
    # the 50% adult reserve that would otherwise overwrite measured ages.
    lifespan_years = max(lifespan_years, maturity_years + 0.5,
                         maturity_years * 1.5 if authored_lifespan is None else 0.)

    reproductive_years = None
    share = FULL_SIZE_SHARE_OF_LIFE.get(form)
    if authored_maturity is None and share is not None and lifespan_years * share > maturity_years:
        # The generic figure above is when it sets seed; it goes on growing for decades.
        reproductive_years, maturity_years = maturity_years, lifespan_years * share
    maturity_days = max(1.0, maturity_years * DAYS_PER_YEAR)
    lifespan_days = lifespan_years * DAYS_PER_YEAR
    return PlantLifeTiming(
        life_cycle=life_cycle, maturity_days=maturity_days, lifespan_days=lifespan_days,
        senescence_start_days=maturity_days + (lifespan_days - maturity_days) * SENESCENCE_SHARE,
        maturity_source=maturity_source, lifespan_source=lifespan_source,
        developmental_maturity_days=developmental_maturity, developmental_senescence_days=developmental_senescence,
        developmental_end_days=developmental_end, real_clock=True,
        reproductive_days=None if reproductive_years is None else max(1.0, reproductive_years * DAYS_PER_YEAR),
    )
