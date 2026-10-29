"""Optional authored growth envelopes for surface organisms.

These are design coefficients, not inferred survival limits. Gas response uses
partial pressure, so changing total pressure or composition has real effects.
Missing or malformed inputs are explicitly unresolved; zero is a known limit.
"""
import math

ATMOSPHERE_RESPONSE_VERSION = 1
ENVELOPE_KEYS = {'pressure_bar', 'co2_partial_pressure_bar', 'oxygen_partial_pressure_bar', 'temperature_c'}


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def validate_atmospheric_tolerance(value):
    if not isinstance(value, dict) or not value:
        raise ValueError('atmospheric_tolerance requires growth envelopes')
    for key, row in value.items():
        if key == 'status':
            continue
        if key not in ENVELOPE_KEYS or not isinstance(row, list) or len(row) != 4:
            raise ValueError('Atmospheric envelopes require four ordered endpoints')
        numbers = [finite_number(v) if isinstance(v, (int, float)) else None for v in row]
        if any(v is None for v in numbers) or numbers != sorted(numbers) or not numbers[0] < numbers[1] <= numbers[2] < numbers[3]:
            raise ValueError('Atmospheric endpoints must be finite: min < optimum min <= optimum max < max')
        lower, upper = (-273.15, 200.) if key == 'temperature_c' else (0., 100.)
        if not lower <= numbers[0] < numbers[3] <= upper:
            raise ValueError('Atmospheric endpoints outside supported physical bounds')
    if not ENVELOPE_KEYS.intersection(value):
        raise ValueError('No atmospheric growth envelope supplied')


def envelope_score(value, endpoints):
    lo, opt_lo, opt_hi, hi = endpoints
    return max(0., min(1., (value-lo)/(opt_lo-lo), (hi-value)/(hi-opt_hi)))


def atmosphere_response(profile, environment):
    envelope = profile.get('atmospheric_tolerance')
    if not envelope:
        return {'atmospheric_activity': 1., 'atmospheric_response_status': 'unresolved_no_authored_envelope'}
    validate_atmospheric_tolerance(envelope)
    atmosphere = environment.get('atmosphere_model')
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    pressure = finite_number(atmosphere.get('surface_pressure_bar'))
    if pressure is not None and pressure < 0:
        pressure = None
    fractions = None
    composition = atmosphere.get('composition')
    if isinstance(composition, list) and composition:
        gases = {}
        for row in composition:
            number = finite_number(row.get('fraction')) if isinstance(row, dict) else None
            if number is None or number < 0 or not row.get('molecule'):
                break
            molecule = str(row['molecule'])
            gases[molecule] = gases.get(molecule, 0.) + number
        else:
            total = sum(gases.values())
            if math.isfinite(total) and total > 0:
                fractions = {k: v/total for k, v in gases.items()}
    temperature = finite_number(environment.get('temperature_k'))
    if temperature is not None and temperature <= 0:
        temperature = None
    if 'temperature_k' in environment.get('runtime_default_fields', ()):
        temperature = None
    inputs = {'pressure_bar': pressure, 'temperature_c': temperature-273.15 if temperature is not None else None}
    for molecule, key in [('CO2', 'co2_partial_pressure_bar'), ('O2', 'oxygen_partial_pressure_bar')]:
        inputs[key] = (0. if pressure == 0 else pressure*fractions.get(molecule, 0.)
                       if pressure is not None and fractions is not None else None)
    scores = {k: envelope_score(inputs[k], envelope[k]) for k in sorted(ENVELOPE_KEYS.intersection(envelope)) if inputs[k] is not None}
    unknown = sorted(k for k in ENVELOPE_KEYS.intersection(envelope) if inputs[k] is None)
    activity = min(scores.values(), default=1.)
    return {'atmospheric_activity': round(activity, 6), 'atmospheric_scores': scores,
            'atmospheric_inputs': inputs, 'atmospheric_unresolved_fields': unknown,
            'atmospheric_limiting_factor': min(scores, key=scores.get) if scores else None,
            'atmospheric_response_status': 'partially_resolved' if unknown else 'authored_growth_envelope',
            'atmospheric_response_version': ATMOSPHERE_RESPONSE_VERSION}


def atmosphere_treatments():
    """Shared explicit diagnostic fixtures, never inferred world atmospheres."""
    def air(pressure, co2, oxygen):
        return {'surface_pressure_bar': pressure, 'composition': [
            {'molecule': 'CO2', 'fraction': co2}, {'molecule': 'O2', 'fraction': oxygen},
            {'molecule': 'N2', 'fraction': 1-co2-oxygen}]}
    earth = air(1., .0004, .21)
    base = {'temperature_k': 293.15, 'light_availability': 1., 'thallus_hydration': 1.}
    return [(label, {**base, 'atmosphere_model': atmosphere, 'thallus_hydration': hydration})
            for label, atmosphere, hydration in [
                ('Earth-like | wet', earth, 1.), ('Thin CO2-rich | wet', air(.15, .5, .02), 1.),
                ('Dense CO2-rich | wet', air(2., .1, .05), 1.), ('Earth-like | dry', earth, 0.),
                ('Vacuum | wet control', air(0., .0004, .21), 1.)]]
