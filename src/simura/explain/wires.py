"""Explaining a wire run: where the resistance, the drop and the heat come from.

The conductor model is where the two attribution shapes sit side by side most
clearly. Its heat balance **adds** — ohmic loss and absorbed sun against
convective cooling, the same equation the battery has. Its resistance
**multiplies** — material, size, length and temperature, each scaling the
answer. Both are decomposed here from :mod:`simura.wires.wire` directly.

A note on the multiplicative ones. "How much does length contribute to
resistance?" has no answer until you say *compared to what*, so these
attributions state their reference conductor explicitly and carry it in the
operating point: **one metre of one square millimetre of annealed copper at
20 °C**. Every factor is then a real, checkable multiple against that, and the
product of the factors times the reference is the actual resistance — which the
attribution machinery verifies by construction, because it computes the total
from the factors rather than being told it.
"""

from __future__ import annotations

from .attribution import Attribution, Term, additive, multiplicative

# The reference conductor every multiplicative wire attribution is stated
# against: 1 m of 1 mm^2 annealed copper at 20 C.
REF_LENGTH_M = 1.0
REF_AREA_MM2 = 1.0
REF_TEMP_C = 20.0


def _wire(spec_or_wire):
    """Accept a ``WireSpec`` or an already-built ``Wire``."""
    from ..wires.wire import Wire, WireSpec

    if isinstance(spec_or_wire, WireSpec):
        return Wire(spec_or_wire)
    return spec_or_wire


def _reference_ohm() -> float:
    from ..wires.catalog import material_for

    copper = material_for("copper")
    return copper.resistivity_at(REF_TEMP_C) * REF_LENGTH_M / (REF_AREA_MM2 * 1e-6)


def _resistance_factors(wire, at_temp_c: float) -> list[Term]:
    """The four factors that turn the reference conductor into this one."""
    from ..wires.catalog import material_for

    copper = material_for("copper")
    rho20_ref = copper.resistivity_at(REF_TEMP_C)
    rho20 = wire.material.resistivity_at(REF_TEMP_C)
    # The temperature factor is the material's own resistivity ratio, so it
    # picks up each material's temperature coefficient rather than a shared one.
    temp_factor = wire.material.resistivity_at(at_temp_c) / rho20 if rho20 > 0 else 1.0

    return [
        Term(
            key="material",
            label=f"Material ({wire.material.name})",
            value=rho20 / rho20_ref,
            unit="×",
            symbol="ρ₂₀ / ρ₂₀,copper",
            why="How much worse (or better) this metal conducts than copper. "
            "Aluminium is about 1.6× the resistance of copper for the same "
            "cross-section — which is why the same job takes a bigger aluminium "
            "cable.",
        ),
        Term(
            key="area",
            label=f"Cross-section ({wire.area_mm2:.3g} mm²)",
            value=REF_AREA_MM2 / wire.area_mm2,
            unit="×",
            symbol="A_ref / A",
            why="Resistance is inversely proportional to how much metal the "
            "current has to share. Doubling the cross-section halves it.",
        ),
        Term(
            key="length",
            label=f"Run length ({wire.length_m:.4g} m)",
            value=wire.length_m / REF_LENGTH_M,
            unit="×",
            symbol="L / L_ref",
            why="Directly proportional: every extra metre is extra resistance, "
            "and on a long low-voltage run this is usually the factor that "
            "decides the gauge.",
        ),
        Term(
            key="temperature",
            label=f"Temperature ({at_temp_c:.1f} °C)",
            value=temp_factor,
            unit="×",
            symbol="1 + α·(T − 20)",
            why="Metals conduct worse when hot. It is a modest factor at ordinary "
            "temperatures — but it feeds back, because a more resistive cable "
            "wastes more power and gets hotter still.",
        ),
    ]


def resistance(spec_or_wire, at_temp_c: float | None = None) -> Attribution:
    """Why this conductor has the resistance it has."""
    wire = _wire(spec_or_wire)
    t = wire.temp_c if at_temp_c is None else at_temp_c
    return multiplicative(
        key="wire.resistance",
        label="Conductor resistance",
        unit="Ω",
        equation="R = ρ₂₀·[1 + α·(T − 20)]·L / A  (relative to 1 m of 1 mm² copper at 20 °C)",
        base=_reference_ohm(),
        terms=_resistance_factors(wire, t),
        card="wires.resistance",
        operating_point={
            "reference_ohm": _reference_ohm(),
            "length_m": wire.length_m,
            "area_mm2": wire.area_mm2,
            "temp_c": t,
        },
    )


def voltage_drop(
    spec_or_wire,
    current_a: float,
    system_voltage_v: float | None = None,
    round_trip: bool = False,
    at_temp_c: float | None = None,
) -> Attribution:
    """Why the load is not getting the voltage the source is sending.

    The full chain, not just the resistance: the same four conductor factors,
    plus the current flowing and whether the return conductor counts. This is
    the one attribution that answers the question people actually arrive with —
    *which of my choices is costing me the voltage* — and the ranking usually
    surprises them, because length beats gauge far more often than not.
    """
    wire = _wire(spec_or_wire)
    t = wire.temp_c if at_temp_c is None else at_temp_c
    conductors = 2 if round_trip else 1

    terms = _resistance_factors(wire, t)
    terms.append(
        Term(
            key="current",
            label=f"Current ({current_a:.4g} A)",
            value=abs(current_a),
            unit="×",
            symbol="I",
            why="Voltage drop is directly proportional to current, so a drop that "
            "is fine at half load is twice as bad at full load.",
        )
    )
    if conductors != 1:
        terms.append(
            Term(
                key="return",
                label="Return conductor",
                value=float(conductors),
                unit="×",
                symbol="×2",
                why="Current has to come back. On a two-wire circuit you pay the "
                "drop twice, once in each direction — the single most commonly "
                "forgotten factor of two in wiring.",
            )
        )

    op: dict[str, float] = {
        "reference_ohm": _reference_ohm(),
        "current_a": current_a,
        "conductors": float(conductors),
        "temp_c": t,
        "resistance_ohm": wire.resistance_ohm(t) * conductors,
    }
    if system_voltage_v:
        drop = abs(current_a) * wire.resistance_ohm(t) * conductors
        op["system_voltage_v"] = system_voltage_v
        op["drop_pct"] = 100.0 * drop / system_voltage_v

    return multiplicative(
        key="wire.voltage_drop",
        label="Voltage drop",
        unit="V",
        equation="ΔV = I·R·n  (relative to 1 A through 1 m of 1 mm² copper at 20 °C)",
        base=_reference_ohm(),
        terms=terms,
        card="wires.drop",
        operating_point=op,
    )


def heat_balance(
    spec_or_wire,
    current_a: float,
    at_temp_c: float | None = None,
    ambient_c: float | None = None,
    solar_w: float = 0.0,
    cooling_mult: float = 1.0,
) -> Attribution:
    """Why the conductor sits at the temperature it does.

    The same shape as the battery's heat balance, which is the point: a cable
    and a cell are the same thermal problem with different coefficients, and
    saying so once is more useful than explaining each from scratch.
    """
    wire = _wire(spec_or_wire)
    amb = wire.ambient_c if ambient_c is None else ambient_c
    t = (
        wire.steady_state_temp_c(current_a, amb, cooling_mult, solar_w)
        if at_temp_c is None
        else at_temp_c
    )
    k = wire.k_cool * cooling_mult
    ohmic = current_a * current_a * wire.resistance_ohm(t)
    cooling = -k * (t - amb)

    terms = [
        Term(
            key="ohmic",
            label="Resistive heating",
            value=ohmic,
            unit="W",
            symbol="I²·R(T)",
            why="The power the cable wastes, which all becomes heat in the cable. "
            "It rises with the square of current, and again slightly as the cable "
            "warms and its resistance climbs.",
        ),
        Term(
            key="cooling",
            label="Cooling to air",
            value=cooling,
            unit="W",
            symbol="−k·(T − T_ambient)",
            why="Heat convected away, in proportion to how far above the "
            "surrounding air the conductor already is.",
        ),
    ]
    if solar_w:
        terms.insert(
            1,
            Term(
                key="solar",
                label="Absorbed sunlight",
                value=solar_w,
                unit="W",
                symbol="Q_solar",
                why="Sun landing on the cable, which heats it whether or not it is "
                "carrying any current at all.",
            ),
        )

    return additive(
        key="wire.heat_balance",
        label="Conductor heat balance",
        unit="W",
        equation="I²·R(T) + Q_solar = k·(T − T_ambient)",
        terms=terms,
        card="wires.thermal",
        operating_point={
            "current_a": current_a,
            "temp_c": t,
            "ambient_c": amb,
            "rise_c": t - amb,
            "k_cool_w_per_k": k,
            "resistance_ohm": wire.resistance_ohm(t),
        },
    )


def ampacity_margin(
    spec_or_wire, current_a: float, ambient_c: float | None = None
) -> Attribution:
    """How much current headroom is left, and what ate the rest of it.

    Three additive terms that sum to the margin: the conductor's rated capacity,
    what the ambient derating takes away, and what the load takes away. It makes
    the two ways a cable runs out of headroom directly comparable — and on a hot
    day the derating is often the larger of the two, which is the finding people
    do not expect.
    """
    wire = _wire(spec_or_wire)
    amb = wire.ambient_c if ambient_c is None else ambient_c
    rated = wire.ampacity_a
    derated = wire.derated_ampacity_a(amb)
    lost = derated - rated  # negative when the ambient is above the reference

    return additive(
        key="wire.ampacity_margin",
        label="Current headroom",
        unit="A",
        equation="margin = I_rated + (I_derated − I_rated) − I_load",
        terms=[
            Term(
                key="rated",
                label="Rated ampacity",
                value=rated,
                unit="A",
                symbol="I_rated",
                why="What this conductor and insulation are rated to carry "
                "continuously, at the reference ambient of 30 °C.",
            ),
            Term(
                key="derating",
                label="Ambient derating",
                value=lost,
                unit="A",
                symbol="I_derated − I_rated",
                why="Capacity lost (or gained) because the surroundings are hotter "
                "(or cooler) than the reference. Less headroom to the insulation's "
                "limit means less current allowed.",
            ),
            Term(
                key="load",
                label="Load current",
                value=-abs(current_a),
                unit="A",
                symbol="−I_load",
                why="What the circuit is actually drawing, spending the headroom.",
            ),
        ],
        card="wires.ampacity",
        operating_point={
            "current_a": current_a,
            "ambient_c": amb,
            "rated_a": rated,
            "derated_a": derated,
            "utilisation": abs(current_a) / derated if derated > 0 else float("inf"),
            "temp_rating_c": wire.temp_rating_c,
        },
    )


def explain_run(
    spec_or_wire,
    current_a: float,
    system_voltage_v: float | None = None,
    round_trip: bool = False,
    ambient_c: float | None = None,
    solar_w: float = 0.0,
    at_temp_c: float | None = None,
) -> list[Attribution]:
    """Every wire attribution for one run, evaluated at one temperature.

    By default that temperature is the one the thermal attribution settles at,
    so the drop reported here is the drop the cable will actually have when warm
    rather than the flattering cold-resistance figure.

    ``at_temp_c`` pins it instead. That matters for a caller who has *already*
    solved the temperature elsewhere — a whole-network solve, where the answer
    reflects the rest of the circuit, the weather and any faults. Letting this
    function re-derive its own would put an explanation next to a number it
    disagrees with, which is a worse failure than being slightly wrong: the
    reader has no way to tell which of the two to believe.
    """
    wire = _wire(spec_or_wire)
    amb = wire.ambient_c if ambient_c is None else ambient_c
    t = (
        wire.steady_state_temp_c(current_a, amb, 1.0, solar_w)
        if at_temp_c is None
        else float(at_temp_c)
    )
    return [
        voltage_drop(wire, current_a, system_voltage_v, round_trip, at_temp_c=t),
        ampacity_margin(wire, current_a, ambient_c=amb),
        heat_balance(wire, current_a, at_temp_c=t, ambient_c=amb, solar_w=solar_w),
        resistance(wire, at_temp_c=t),
    ]
