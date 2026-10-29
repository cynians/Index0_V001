"""
Delta-v budget by the rocket equation (docs/space_spacecraft_navigation_v001.md
section 3). Vacuum figures; no staging yet.
"""
from dataclasses import dataclass
import math


G0 = 9.80665


@dataclass(frozen=True)
class Engine:
    thrust_n: float
    specific_impulse_s: float


@dataclass(frozen=True)
class PropulsionState:
    """What a craft can burn: everything but propellant, the propellant on board, its engines."""
    dry_mass_kg: float
    propellant_kg: float
    engines: tuple

    @property
    def wet_mass_kg(self):
        return self.dry_mass_kg + self.propellant_kg

    @property
    def thrust_n(self):
        return sum(engine.thrust_n for engine in self.engines)

    @property
    def specific_impulse_s(self):
        """Engines firing together: total thrust over total propellant flow."""
        flow = sum(engine.thrust_n / engine.specific_impulse_s for engine in self.engines if engine.specific_impulse_s > 0)
        return self.thrust_n / flow if flow > 0 else 0.0

    @property
    def exhaust_velocity_m_s(self):
        return self.specific_impulse_s * G0

    def delta_v_m_s(self):
        if self.dry_mass_kg <= 0.0 or self.exhaust_velocity_m_s <= 0.0:
            return 0.0
        return self.exhaust_velocity_m_s * math.log(self.wet_mass_kg / self.dry_mass_kg)

    def propellant_for(self, delta_v_m_s):
        """Propellant a burn of delta_v uses, starting from the current mass."""
        if self.exhaust_velocity_m_s <= 0.0:
            return math.inf
        return self.wet_mass_kg * (1.0 - math.exp(-delta_v_m_s / self.exhaust_velocity_m_s))

    def burn_time_s(self, delta_v_m_s):
        if self.thrust_n <= 0.0:
            return math.inf
        return self.propellant_for(delta_v_m_s) * self.exhaust_velocity_m_s / self.thrust_n

    def after_burn(self, delta_v_m_s):
        return PropulsionState(
            dry_mass_kg=self.dry_mass_kg,
            propellant_kg=max(0.0, self.propellant_kg - self.propellant_for(delta_v_m_s)),
            engines=self.engines,
        )
