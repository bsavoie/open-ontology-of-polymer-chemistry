"""Small, audited unit profile for deterministic scientific admission.

The original spelling always remains in context.units. Unknown original units
are valid evidence, but no normalization is certified until their conversion is
added to this profile. This is intentionally not a general expression parser.
QUDT identifiers use the vocabulary's canonical http IRIs. Conversion definitions
follow https://qudt.org/vocab/unit/ (including affine Celsius temperatures).
"""
from dataclasses import dataclass
import math
import re

QUDT_UNIT = "http://qudt.org/vocab/unit/"
PROFILE_VERSION = "1"


@dataclass(frozen=True)
class Unit:
    name: str
    dimension: str
    multiplier: float
    offset: float = 0.0
    aliases: tuple = ()

    @property
    def iri(self):
        return QUDT_UNIT + self.name


# SI value = original value * multiplier + offset. Extend this explicit registry
# with reviewed definitions and conversion tests; never infer a prefix from text.
UNIT_DEFINITIONS = (
    Unit("PA", "pressure", 1.0, aliases=("Pa", "pascal", "pascals")),
    Unit("KiloPA", "pressure", 1e3, aliases=("kPa",)),
    Unit("MegaPA", "pressure", 1e6, aliases=("MPa", "N/mm2", "N/mm²")),
    Unit("GigaPA", "pressure", 1e9, aliases=("GPa",)),
    Unit("K", "temperature", 1.0, aliases=("K", "kelvin")),
    Unit("DEG_C", "temperature", 1.0, 273.15, ("°C", "degC", "Cel", "Celsius")),
    Unit("UNITLESS", "dimensionless", 1.0, aliases=("1", "dimensionless", "unitless", "mm/mm", "m/m")),
    Unit("PERCENT", "dimensionless", 0.01, aliases=("%", "percent")),
    Unit("M", "length", 1.0, aliases=("m",)),
    Unit("CentiM", "length", 0.01, aliases=("cm",)),
    Unit("MilliM", "length", 0.001, aliases=("mm",)),
    Unit("MicroM", "length", 1e-6, aliases=("µm", "μm", "um")),
    Unit("SEC", "time", 1.0, aliases=("s", "sec")),
    Unit("MIN", "time", 60.0, aliases=("min",)),
    Unit("HR", "time", 3600.0, aliases=("h", "hr")),
)
_UNITS = {key: unit for unit in UNIT_DEFINITIONS for key in (unit.iri, *unit.aliases)}

# Only unambiguous property names have a deterministic dimensional check. A
# newly named property is not guessed from partial matches and remains eligible
# for source review; conversions still require compatible registered units.
_PROPERTY_DIMENSIONS = {
    "tensile strength": "pressure", "tensile stress": "pressure",
    "yield strength": "pressure", "yield stress": "pressure",
    "tensile modulus": "pressure", "elastic modulus": "pressure",
    "youngs modulus": "pressure", "young s modulus": "pressure",
    "flexural strength": "pressure", "flexural modulus": "pressure",
    "compressive strength": "pressure", "shear modulus": "pressure",
    "pressure": "pressure", "temperature": "temperature",
    "glass transition temperature": "temperature", "melting temperature": "temperature",
    "strain": "dimensionless", "elongation": "dimensionless",
    "elongation at break": "dimensionless", "strain at break": "dimensionless",
    "thickness": "length", "length": "length", "width": "length",
    "time": "time", "duration": "time",
}


def is_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def get_unit(value):
    return _UNITS.get(value.strip()) if isinstance(value, str) else None


def canonical_unit_iri(value):
    unit = get_unit(value)
    return unit.iri if unit else None


def convert_value(value, source, target, quantity_kind=None):
    """Convert a scalar, rejecting unknown dimensions and ambiguous intervals.

    Temperature intervals must explicitly use quantityKind=temperature_difference;
    their offset is zero. Ordinary temperature values use the scale offset.
    """
    source_unit, target_unit = get_unit(source), get_unit(target)
    if not source_unit or not target_unit:
        raise ValueError("normalization requires registered source and target units")
    if source_unit.dimension != target_unit.dimension:
        raise ValueError("normalization units have incompatible dimensions")
    if not is_number(value):
        raise ValueError("normalization requires a finite original numeric value")
    interval = quantity_kind == "temperature_difference"
    result = ((value * source_unit.multiplier + (0 if interval else source_unit.offset))
              - (0 if interval else target_unit.offset)) / target_unit.multiplier
    if not math.isfinite(result):
        raise ValueError("normalization produced a non-finite value")
    return result


def quantity_errors(record):
    """Check original/normalized correspondence without changing any source data."""
    context = record.get("context", {})
    if not isinstance(context, dict):
        return []
    errors = []
    original_units = context.get("units")
    unit = get_unit(original_units)
    property_name = record.get("property") or context.get("property")
    if isinstance(property_name, str):
        dimension = _PROPERTY_DIMENSIONS.get(re.sub(r"[^a-z0-9]+", " ", property_name.lower()).strip())
        if dimension and unit and dimension != unit.dimension:
            errors.append("property and original units have incompatible dimensions")

    normalized_fields = {key for key in ("normalizedValue", "normalizedRange", "normalizedUnits") if key in context}
    if normalized_fields:
        if not {"normalizedValue", "normalizedRange"}.intersection(normalized_fields):
            errors.append("normalizedUnits requires a normalized value or range")
        for original_key, normalized_key in (("value", "normalizedValue"), ("range", "normalizedRange")):
            if normalized_key not in context:
                continue
            original, normalized = context.get(original_key), context[normalized_key]
            if normalized_key == "normalizedRange":
                valid = lambda v: isinstance(v, list) and len(v) == 2 and all(is_number(x) for x in v) and v[0] <= v[1]
                if not valid(original) or not valid(normalized):
                    errors.append("range normalization must retain ordered numeric original and normalized ranges")
                    continue
                pairs = zip(original, normalized)
            else:
                if not is_number(original) or not is_number(normalized):
                    errors.append("normalization must retain the original numeric value; a range cannot become a scalar by unit conversion")
                    continue
                pairs = [(original, normalized)]
            for value, actual in pairs:
                try:
                    expected = convert_value(value, original_units, context.get("normalizedUnits"), context.get("quantityKind"))
                except ValueError as exc:
                    errors.append(str(exc))
                    break
                # Numerical rounding only: experimental uncertainty must never
                # make an incorrect conversion acceptable.
                if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
                    errors.append("normalized value does not match the registered unit conversion")
                    break

    # Optional RDF-friendly QUDT quantity fields describe this same observation,
    # never an unrelated number or an unverified replacement for source values.
    if "unit" in record or "numericValue" in record:
        target = get_unit(record.get("unit"))
        if not target or record.get("unit") != target.iri:
            errors.append("unit must use a registered canonical QUDT unit IRI")
        if not is_number(record.get("numericValue")):
            errors.append("QUDT numericValue must be finite and accompanied by unit")
        if target and is_number(record.get("numericValue")):
            try:
                expected = convert_value(context.get("value"), original_units, target.iri, context.get("quantityKind"))
                if not math.isclose(record["numericValue"], expected, rel_tol=1e-9, abs_tol=1e-12):
                    errors.append("QUDT numericValue does not agree with the retained original quantity")
            except ValueError as exc:
                errors.append("QUDT quantity: " + str(exc))
    return errors
