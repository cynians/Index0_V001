"""
Interplanetary calendar.

A year is the Julian year (365.25 days of 86 400 s), split into 1000 cycles
grouped into 10 months of 100 cycles. Months and cycles count from 1, like
days of a month. Year 2000 starts at J2000 (2000-01-01 12:00), the epoch of
the orbit elements, so time is kept as seconds since that epoch.

The short form is the year to three decimals, the thousandths that have
passed: 2026.826 is Year 2026, Month 9, Cycle 27.

Local time on a planet is a separate system, not this one.
"""
from dataclasses import dataclass
import math


EPOCH_YEAR = 2000
YEAR_SECONDS = 365.25 * 86_400.0
CYCLES_PER_YEAR = 1000
CYCLES_PER_MONTH = 100
CYCLE_SECONDS = YEAR_SECONDS / CYCLES_PER_YEAR

# Seconds that sit a hair below a cycle boundary after a float round trip
# still belong to the cycle that starts there.
_BOUNDARY_TOLERANCE_CYCLES = 1e-6


@dataclass(frozen=True)
class InterplanetaryDate:
    year: int
    month: int
    cycle: int
    cycle_of_year: int
    cycle_fraction: float

    @property
    def year_fraction(self):
        return (self.cycle_of_year + self.cycle_fraction) / CYCLES_PER_YEAR

    @property
    def month_fraction(self):
        return (self.cycle - 1 + self.cycle_fraction) / CYCLES_PER_MONTH

    def short_label(self):
        return f"{self.year}.{self.cycle_of_year:03d}"

    def long_label(self):
        return f"Year {self.year}, Month {self.month}, Cycle {self.cycle}"


def year_start_seconds(year):
    return (float(year) - EPOCH_YEAR) * YEAR_SECONDS


def date_from_seconds(seconds_since_epoch):
    total_cycles = float(seconds_since_epoch) / CYCLE_SECONDS
    whole_cycles = math.floor(total_cycles + _BOUNDARY_TOLERANCE_CYCLES)
    year_offset, cycle_of_year = divmod(whole_cycles, CYCLES_PER_YEAR)
    month_index, cycle_index = divmod(cycle_of_year, CYCLES_PER_MONTH)
    return InterplanetaryDate(
        year=EPOCH_YEAR + int(year_offset),
        month=int(month_index) + 1,
        cycle=int(cycle_index) + 1,
        cycle_of_year=int(cycle_of_year),
        cycle_fraction=min(1.0, max(0.0, total_cycles - whole_cycles)),
    )


def seconds_from_date(year, month=1, cycle=1):
    cycles = (int(year) - EPOCH_YEAR) * CYCLES_PER_YEAR + (int(month) - 1) * CYCLES_PER_MONTH + (int(cycle) - 1)
    return cycles * CYCLE_SECONDS


def duration_cycles(seconds):
    return float(seconds) / CYCLE_SECONDS
