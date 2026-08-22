"""Explaining a lighting design: where the light comes from, and where it goes.

Lighting is the component where the explanation matters most, because the
outcome is invisible to intuition. Nobody can look at a room and tell you it is
at 340 lux instead of 500, and nobody can look at a lamp and tell you which of
four independent factors is costing them the light. Both are decompositions,
and both are here.

The efficacy decomposition is the one to read first, because its reference is
not a convention — it is a constant. **683 lm/W is the most light any watt of
radiation can possibly be**, at the wavelength the eye is most sensitive to. So
a lamp's efficacy is that ceiling, multiplied by three fractions it fails to
keep: what its spectrum gives up by not being entirely at 555 nm, what it gives
up by not turning all its electricity into radiation, and what the driver takes
before any of it starts. Every lamp in the catalog is the same three fractions
with different values, which is exactly why one model spans a fifteen-fold range
of efficacy without a single special case.
"""

from __future__ import annotations

from typing import Any, Sequence

from .attribution import Attribution, Term, additive, multiplicative

# Luminous efficacy of radiation at 555 nm: the physical ceiling.
MAX_EFFICACY_LM_PER_W = 683.0

# What "rated" means for a luminaire: nominal supply, bench temperature, a new
# clean lamp, nothing wrong with it. Every real fitting is this multiplied by a
# series of things that went less than perfectly.
RATED_AMBIENT_C = 25.0


def efficacy(point, spec=None) -> Attribution:
    """Why this lamp gets the light per watt that it does.

    ``point`` is a :class:`~simura.lights.lamp.OperatingPoint` — whatever
    :meth:`Light.operating_point` returned. Three fractions of a physical
    ceiling, and they are independent enough that improving one says nothing
    about the others: a filament's spectrum factor is dreadful and its radiant
    efficiency is excellent, and an LED is the other way round.
    """
    p_in = point.input_power_w
    p_src = point.source_power_w
    radiant = point.radiant_power_w
    ler = point.ler_lm_per_w

    spectrum_factor = ler / MAX_EFFICACY_LM_PER_W
    radiant_factor = radiant / p_src if p_src > 0 else 0.0
    gear_factor = p_src / p_in if p_in > 0 else 0.0
    # Everything standing between the spectrum and the room: the envelope, dirt
    # on it, the lamp's depreciation, and any fault. Taken as the ratio the lamp
    # model itself produced rather than reassembled from its inputs, so the four
    # factors multiply back to exactly the efficacy the model reports.
    optical_factor = (
        point.luminous_flux_lm / (radiant * ler) if radiant > 0 and ler > 0 else 0.0
    )

    return multiplicative(
        key="lamp.efficacy",
        label="Light per watt",
        unit="lm/W",
        equation="efficacy = 683 · (LER/683) · (P_radiant/P_source) · (P_source/P_input) · optical",
        base=MAX_EFFICACY_LM_PER_W,
        terms=[
            Term(
                key="spectrum",
                label="Spectrum",
                value=spectrum_factor,
                unit="×",
                symbol="LER / 683",
                why="How much of this source's radiation lands where the eye can "
                "use it. A filament radiates most of its power as infrared and "
                "keeps very little of this; a sodium lamp sits almost exactly on "
                "the eye's peak and keeps nearly all of it — and renders no colour "
                "at all as the price.",
            ),
            Term(
                key="radiant",
                label="Radiant efficiency",
                value=radiant_factor,
                unit="×",
                symbol="P_radiant / P_source",
                why="The share of the source's power that leaves as radiation of "
                "any wavelength rather than as plain heat. Filaments are "
                "surprisingly good at this — their problem is entirely the "
                "previous factor.",
            ),
            Term(
                key="gear",
                label="Control gear",
                value=gear_factor,
                unit="×",
                symbol="P_source / P_input",
                why="What the driver or ballast keeps for itself before the light "
                "source sees any power. Small, but it counts against the fixture "
                "even though lamp-only figures quietly ignore it.",
            ),
            Term(
                key="optical",
                label="Envelope, dirt and age",
                value=optical_factor,
                unit="×",
                symbol="Φ / (P_radiant·LER)",
                why="Everything between the spectrum and the room: light stopped "
                "by the glass or lens, by dirt on it, and by however much the "
                "lamp has already depreciated. Unlike the other three, most of "
                "this is recoverable by maintenance.",
            ),
        ],
        card="lights.spectrum",
        operating_point={
            "input_power_w": p_in,
            "source_power_w": p_src,
            "radiant_power_w": radiant,
            "luminous_flux_lm": point.luminous_flux_lm,
            "efficacy_lm_per_w": point.efficacy_lm_per_w,
            "ler_lm_per_w": point.ler_lm_per_w,
            "color_temp_k": point.color_temp_k,
            "source_temp_c": point.source_temp_c,
        },
    )


def output(
    spec,
    supply_voltage_v: float | None = None,
    drive: float = 1.0,
    ambient_c: float | None = None,
    faults: Sequence[Any] = (),
    elapsed_s: float = 0.0,
) -> Attribution:
    """Why this luminaire is not producing the light it is rated for.

    The question a fitting in a real installation actually poses. It is rated at
    some number of lumens; it is producing fewer; **which of the five things
    that could be responsible is responsible, and by how much?**

    Every factor is obtained by *re-running the lamp model* with exactly one
    condition changed, in a chain that starts at the rated point and ends at the
    real one:

    ``rated → drive → supply → ambient → age and dirt → faults``

    Each factor is the ratio of two consecutive runs, so the product telescopes
    to the true ratio of actual output to rated output — exactly, by
    construction, with no residual and nothing modelled twice. Nothing here
    asserts that a filament suffers on a sagging supply and a driven LED does
    not; both lamps go through the identical five runs and the numbers come out
    different because the lamp model is different.

    **The order is part of the answer.** These effects are not independent — a
    lamp that is already hot loses a different amount to a voltage sag than a
    cold one — so each factor is *conditional on the ones before it*. The chain
    runs outward from the electrical cause to the physical condition of the
    fitting because that is the order in which someone would act on it.
    """
    from ..lights.faults import accumulate
    from ..lights.lamp import Light, LightSpec

    base = spec.to_dict() if hasattr(spec, "to_dict") else dict(spec)
    nominal_v = Light(LightSpec.from_dict(base)).supply_voltage_v
    supply_v = nominal_v if supply_voltage_v is None else float(supply_voltage_v)
    amb = RATED_AMBIENT_C if ambient_c is None else float(ambient_c)
    # The as-new, as-clean version of this same lamp.
    fresh = {**base, "operating_hours_h": 0.0, "switch_cycles": 0.0,
             "dirt_depreciation_frac": 0.0}

    def flux(spec_dict: dict, volts: float, level: float, ambient: float, faulted: bool) -> float:
        light = Light(LightSpec.from_dict(spec_dict))
        light.time_lit_s = 1e9          # a settled fitting, not a warming one
        effect = (
            accumulate(list(faults), light, elapsed_s)
            if faulted and faults
            else None
        )
        return light.at_supply(
            volts, drive=level, ambient_c=ambient, effect=effect
        ).point.luminous_flux_lm

    # The chain. Each entry changes exactly one thing from the one above it.
    rated = flux(fresh, nominal_v, 1.0, RATED_AMBIENT_C, False)
    after_drive = flux(fresh, nominal_v, drive, RATED_AMBIENT_C, False)
    after_supply = flux(fresh, supply_v, drive, RATED_AMBIENT_C, False)
    after_ambient = flux(fresh, supply_v, drive, amb, False)
    after_wear = flux(base, supply_v, drive, amb, False)
    actual = flux(base, supply_v, drive, amb, True)

    def ratio(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator > 0 else 0.0

    terms = [
        Term(
            key="dimming",
            label="Dimming",
            value=ratio(after_drive, rated),
            unit="×",
            symbol="drive",
            why="How far the fitting has been dimmed on purpose. Worth separating "
            "from everything else, because it is the only one of these that "
            "somebody chose.",
        ),
        Term(
            key="supply",
            label=f"Supply voltage ({supply_v:.1f} V of {nominal_v:.0f} V)",
            value=ratio(after_supply, after_drive),
            unit="×",
            symbol="V / V_nominal",
            why="What the voltage actually arriving costs in light. A filament "
            "loses far more than proportionally — it runs cooler, so it radiates "
            "less and shifts what is left into the infrared — while anything with "
            "a driver holds flat and simply draws more current, until it drops "
            "out entirely.",
        ),
        Term(
            key="ambient",
            label=f"Ambient temperature ({amb:.1f} °C)",
            value=ratio(after_ambient, after_supply),
            unit="×",
            symbol="f(T_ambient)",
            why="Technologies respond in opposite directions here: an LED loses "
            "output as its junction warms, and a fluorescent lamp gains it up to "
            "about 25 °C as its vapour pressure climbs to the optimum.",
        ),
        Term(
            key="maintenance",
            label="Age and dirt",
            value=ratio(after_wear, after_ambient),
            unit="×",
            symbol="LMF · (1 − dirt)",
            why="Lumens the lamp has lost to its hours and switch cycles, and "
            "light stopped by whatever has settled on the lens. The second half "
            "is the only loss on this list that a cloth fixes.",
        ),
    ]
    if faults:
        terms.append(
            Term(
                key="faults",
                label="Faults",
                value=ratio(actual, after_wear),
                unit="×",
                symbol="fault effect",
                why="What is broken, over and above ordinary wear — a failed "
                "driver, a lost heatsink, a degraded phosphor.",
            )
        )

    return multiplicative(
        key="lamp.output",
        label="Light output against rating",
        unit="lm",
        equation="Φ = Φ_rated · drive · f(V) · f(T) · maintenance · faults",
        base=rated,
        terms=terms,
        card="lights.lamp",
        operating_point={
            "rated_flux_lm": rated,
            "actual_flux_lm": actual,
            "fraction_of_rated": ratio(actual, rated),
            "supply_voltage_v": supply_v,
            "nominal_voltage_v": nominal_v,
            "ambient_c": amb,
            "drive": drive,
        },
    )


def illuminance(assessment) -> Attribution:
    """Where the installed lumens went before reaching the working plane.

    ``assessment`` is an
    :class:`~simura.lights.planning.InstallationAssessment`. The base is the
    illuminance you would have if every installed lumen landed on the working
    plane and none were ever lost — a real, computable ceiling, not a convention
    — and the factors are the four ways an installation fails to achieve it.

    All four are in (0, 1], so their shares are reference-free and directly
    comparable. That comparison is the useful part: "clean the fittings" and
    "buy brighter lamps" are answers to different rankings, and the ranking is
    computed, not guessed.
    """
    room = assessment.room
    # The room's floor area is not carried on the result, so recover it by
    # inverting the lumen method the result came from: E = Φ·UF·LLF/A.
    if room.power_density_w_per_m2 > 0 and room.power_w > 0:
        area = room.power_w / room.power_density_w_per_m2
    elif room.average_lux > 0:
        area = room.total_flux_lm * room.utilisation_factor * room.light_loss_factor / room.average_lux
    else:
        area = 1.0

    # The flux on the assessment is already aged, so dividing it back out gives
    # the day-one installed lumens — which is the only base against which lamp
    # depreciation is a *factor* rather than something already silently applied.
    maint = assessment.lumen_maintenance
    new_flux_lm = room.total_flux_lm / maint if maint > 0 else room.total_flux_lm
    installed_lux = new_flux_lm / area if area > 0 else 0.0

    return multiplicative(
        key="room.illuminance",
        label="Light on the working plane",
        unit="lux",
        equation="E_avg = (N·Φ_new / A) · LMF · UF · LLF",
        base=installed_lux,
        terms=[
            Term(
                key="lumen_maintenance",
                label="Lamp depreciation",
                value=maint,
                unit="×",
                symbol="LMF",
                why="Light the lamps have already lost to age. The only cure is "
                "replacing them, which is why installations are designed for the "
                "end of the maintenance cycle rather than for day one.",
            ),
            Term(
                key="utilisation",
                label="Reaching the plane",
                value=room.utilisation_factor,
                unit="×",
                symbol="UF",
                why="The share of the lamps' light that lands on the working plane "
                "rather than on walls, ceiling or floor. It is a property of the "
                "room, not the fitting — the same luminaire is far more effective "
                "in a wide bright room than a tall dark one.",
            ),
            Term(
                key="light_loss",
                label="Dirt and failed lamps",
                value=room.light_loss_factor,
                unit="×",
                symbol="LLF",
                why="Light stopped by whatever has settled on the lens and housing, "
                "and by the lamps that are simply out. The least glamorous loss in "
                "lighting, and the only one a person with a cloth can fully undo.",
            ),
        ],
        card="lights.lumen_method",
        operating_point={
            "installed_flux_lm": room.total_flux_lm,
            "area_m2": area,
            "n_luminaires": float(assessment.n_luminaires),
            "maintained_lux": assessment.maintained_lux,
            "target_lux": assessment.target_lux,
            "room_index": room.room_index,
            "power_density_w_per_m2": room.power_density_w_per_m2,
            "shortfall_lux": assessment.target_lux - assessment.maintained_lux,
        },
    )


def field_split(layout_result) -> Attribution:
    """The two (or three) ways light arrives at a point on the plane.

    ``layout_result`` is a :class:`~simura.lights.layout.LayoutResult`. Direct
    light comes straight from the fittings and is what makes a room uneven;
    bounced light arrives from everywhere and is what makes it comfortable.
    Daylight, when the model has any, is a third — and on a bright day it is
    routinely the largest, which is the entire argument for daylight harvesting.
    """
    terms = [
        Term(
            key="direct",
            label="Straight from the fittings",
            value=layout_result.direct_average_lux,
            unit="lux",
            symbol="Σ I·cos θ / d²",
            why="Light that travels from a luminaire to the plane without "
            "bouncing. It falls off with the square of distance, so it is strong "
            "under each fitting and weak between them — this is the component "
            "that creates unevenness.",
        ),
        Term(
            key="interreflected",
            label="Bounced off the room",
            value=layout_result.indirect_lux,
            unit="lux",
            symbol="E_indirect",
            why="Light that missed the plane, hit a wall or ceiling, and came "
            "back. It arrives from every direction at once, so it fills in the "
            "gaps the direct component leaves — a dark room is uncomfortable "
            "mostly because it has none of this.",
        ),
    ]
    if layout_result.daylight_lux:
        terms.append(
            Term(
                key="daylight",
                label="Daylight",
                value=layout_result.daylight_lux,
                unit="lux",
                symbol="E_daylight",
                why="Light through the windows, which costs nothing and is "
                "frequently larger than everything the electric installation "
                "provides.",
            )
        )

    return additive(
        key="room.field_split",
        label="Where the light comes from",
        unit="lux",
        equation="E = E_direct + E_interreflected + E_daylight",
        terms=terms,
        card="lights.field",
        operating_point={
            "average_lux": layout_result.average_lux,
            "min_lux": layout_result.min_lux,
            "max_lux": layout_result.max_lux,
            "uniformity": layout_result.uniformity,
            "area_m2": layout_result.area_m2,
        },
    )


def uniformity(layout_result) -> Attribution:
    """How far the dimmest spot falls below the average, and what is holding it up.

    Reported as the gap the average hides: average minus minimum, split into the
    direct component's contribution to the shortfall and the bounced
    component's. The bounced part contributes nothing to unevenness by
    construction — it is uniform — which is precisely the finding: **the only
    thing that can be uneven is the direct light**, so raising uniformity means
    changing spacing or mounting height, never changing lamps.
    """
    avg = layout_result.average_lux
    lo = layout_result.min_lux
    indirect = layout_result.indirect_lux
    direct_avg = layout_result.direct_average_lux
    direct_min = max(lo - indirect - layout_result.daylight_lux, 0.0)

    return additive(
        key="room.uniformity",
        label="How far the dimmest spot falls short",
        unit="lux",
        equation="E_avg − E_min = (E_direct,avg − E_direct,min) + (uniform terms → 0)",
        terms=[
            Term(
                key="direct_variation",
                label="Uneven direct light",
                value=direct_avg - direct_min,
                unit="lux",
                symbol="ΔE_direct",
                why="The whole of the shortfall. Direct light falls off with "
                "distance, so points between and beside the fittings get less of "
                "it — closer spacing or a lower mounting height is the only cure.",
            ),
            Term(
                key="uniform_terms",
                label="Bounced and daylight",
                value=0.0,
                unit="lux",
                symbol="0",
                why="These arrive equally everywhere, so they raise the whole "
                "field and contribute nothing to the unevenness. They improve the "
                "uniformity *ratio* by lifting the floor, without making the "
                "direct light any more even.",
            ),
        ],
        card="lights.field",
        operating_point={
            "average_lux": avg,
            "min_lux": lo,
            "max_lux": layout_result.max_lux,
            "uniformity": layout_result.uniformity,
            "diversity": layout_result.diversity,
        },
    )


def explain_installation(assessment, layout_result=None, point=None) -> list[Attribution]:
    """Every lighting attribution available, from whichever inputs are to hand.

    All three arguments come from different calls (``evaluate_installation``,
    ``build_layout(...).solve()``, ``Light.operating_point()``), and a caller
    rarely has all of them — so each contributes what it can and none is
    required beyond the assessment.
    """
    out: list[Attribution] = [illuminance(assessment)]
    if point is not None:
        out.append(efficacy(point))
    if layout_result is not None:
        out.append(field_split(layout_result))
        out.append(uniformity(layout_result))
    return out
