"""Explaining a battery: the pack model's equations, decomposed where you are.

Every function here takes a cell's operating point and returns an
:class:`~simura.explain.attribution.Attribution` built from a term of the
*actual* governing equation in :mod:`simura.sim.pack`. There is no branch on
"the pack is overheating" and no stored sentence about high current — the terms
are evaluated and ranked, and whichever wins is what gets said.

Two ways in, and the difference between them is worth being explicit about:

:func:`operating_point_from_pack`
    Reads the live :class:`~simura.sim.pack.BatteryPack`. Every quantity is the
    one the solver is using, including each cell's own manufacturing spread.
    Exact.

:func:`operating_point_from_frame`
    All you have is telemetry — a voltage, a current, a temperature, a charge
    level — plus the spec that built the system. The internal states the
    equations need are recovered by **inverting the model**: the chemistry's
    curve gives the open-circuit voltage at the reported charge, and the
    terminal law then gives the polarisation voltage as what is left over. This
    is the honest thing to do with a measurement, and it is also the reason such
    an attribution is marked ``exact=False``: per-cell resistance spread is not
    observable from telemetry, so it lands in the polarisation term along with
    the polarisation. The caveat travels with the attribution and is printed at
    the physics level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .attribution import Attribution, Term, additive

# Recovering polarisation as a residual folds unobservable resistance spread
# into it; say so wherever that path is used.
_INFERRED_CAVEAT = (
    "Recovered from telemetry rather than read from the running model: the "
    "cell's own resistance is not observable in a telemetry frame, so the "
    "nominal value is used and any cell-to-cell difference lands in the "
    "polarisation term. Run this against a twin-core simulation for the exact "
    "split."
)

_INFERRED_THERMAL_CAVEAT = (
    _INFERRED_CAVEAT
    + " Fault heat in particular is invisible to telemetry — a real BMS could "
    "not report it either — so if the cell is sitting well above the "
    "equilibrium temperature this balance predicts, that gap is the size of the "
    "heat source this frame cannot see."
)


@dataclass(frozen=True)
class CellPoint:
    """One cell's state, in the terms the pack model's equations are written in."""

    series_index: int
    parallel_index: int
    current_a: float
    """Delivered current through the cell. Positive is discharge."""
    voltage_v: float
    temp_c: float
    soc: float
    ocv_v: float
    v_rc_v: float
    r0_ohm: float
    capacity_ah: float
    c_th_j_per_k: float
    k_cool_w_per_k: float
    ambient_c: float
    coulombic_eff: float = 0.99
    extra_current_a: float = 0.0
    """Parasitic fault current — drains the cell without leaving the terminals."""
    extra_heat_w: float = 0.0
    exact: bool = True

    @property
    def total_current_a(self) -> float:
        """What the cell is actually passing, parasitic paths included."""
        return self.current_a + self.extra_current_a

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def operating_point_from_pack(pack, series_index: int, parallel_index: int, effect=None) -> CellPoint:
    """Read one cell's exact operating point out of a live pack.

    ``effect`` is the :class:`~simura.sim.faults.FaultEffect` for the current
    step, if the caller has it; without it the fault channels read zero, which
    is right for an unfaulted pack and understates a faulted one.
    """
    s, p = series_index, parallel_index
    _bounds(pack.shape, s, p)
    cfg = pack.config
    r0 = float(pack.r0_nom[s, p])
    extra_i = 0.0
    extra_q = 0.0
    k_cool = float(pack.k_cool_nom[s, p])
    if effect is not None:
        r0 *= float(effect.resistance_mult[s, p])
        k_cool *= float(effect.cooling_mult[s, p])
        extra_i = float(effect.extra_current_a[s, p])
        extra_q = float(effect.extra_heat_w[s, p])
    return CellPoint(
        series_index=s,
        parallel_index=p,
        current_a=float(pack.cell_current_a[s, p]),
        voltage_v=float(pack.cell_voltage_v[s, p]),
        temp_c=float(pack.temp_c[s, p]),
        soc=float(pack.soc[s, p]),
        ocv_v=float(pack.ocv(pack.soc)[s, p]),
        v_rc_v=float(pack.v_rc[s, p]),
        r0_ohm=r0,
        capacity_ah=float(pack.capacity_ah[s, p]),
        c_th_j_per_k=float(pack.c_th[s, p]),
        k_cool_w_per_k=k_cool,
        ambient_c=float(pack.ambient_c),
        coulombic_eff=float(cfg.cell.coulombic_eff),
        extra_current_a=extra_i,
        extra_heat_w=extra_q,
        exact=True,
    )


def operating_point_from_frame(frame: dict, spec, series_index: int, parallel_index: int) -> CellPoint:
    """Recover a cell's operating point from a telemetry frame plus its spec.

    ``frame`` is a serialized :class:`~simura.sim.telemetry.PackTelemetry`
    (whatever came off the WebSocket or out of the store). The polarisation
    voltage is obtained by inverting the terminal law, which is exactly how you
    would do it by hand — and carries exactly the same caveat.
    """
    from ..sim.ocv import make_ocv, ocv_table_for

    cell = _cell_in_frame(frame, series_index, parallel_index)
    ocv_curve = make_ocv(ocv_table_for(getattr(spec, "chemistry", "NMC")))
    soc = float(cell["soc"])
    ocv = float(ocv_curve(soc))
    current = float(cell["current_a"])
    voltage = float(cell["voltage_v"])
    r0 = float(spec.r0_ohm)
    # V = OCV - I*R0 - V_rc, solved for the one unknown.
    v_rc = ocv - voltage - current * r0

    ambient = float(spec.ambient_temp_c)
    weather = frame.get("weather")
    if weather and weather.get("air_temp_c") is not None:
        ambient = float(weather["air_temp_c"])

    return CellPoint(
        series_index=series_index,
        parallel_index=parallel_index,
        current_a=current,
        voltage_v=voltage,
        temp_c=float(cell["temp_c"]),
        soc=soc,
        ocv_v=ocv,
        v_rc_v=v_rc,
        r0_ohm=r0,
        capacity_ah=float(spec.capacity_ah),
        c_th_j_per_k=float(spec.thermal_capacity_j_per_k),
        k_cool_w_per_k=float(spec.cooling_conductance_w_per_k),
        ambient_c=ambient,
        coulombic_eff=float(spec.coulombic_eff),
        exact=False,
    )


# -- attributions ----------------------------------------------------------


def heat_balance(point: CellPoint) -> Attribution:
    """Why this cell is at the temperature it is, and where it is going.

    The pack model's thermal equation, term by term. The sign of the total is
    the whole answer to "is it warming or cooling", and
    :attr:`~simura.explain.attribution.Attribution.balanced` is the answer to
    the more useful question, which is whether it has stopped moving.
    """
    i_tot = point.total_current_a
    ohmic = i_tot * i_tot * point.r0_ohm
    polar = point.current_a * point.v_rc_v
    fault = point.extra_heat_w
    cooling = -point.k_cool_w_per_k * (point.temp_c - point.ambient_c)

    terms = [
        Term(
            key="ohmic",
            label="Resistive heating",
            value=ohmic,
            unit="W",
            symbol="I²·R₀",
            why="Current forced through the cell's own resistance. It grows with "
            "the square of current, so twice the load is four times this heat.",
        ),
        Term(
            key="polarisation",
            label="Polarisation heating",
            value=polar,
            unit="W",
            symbol="I·V_rc",
            why="The slow part of the cell's internal loss, which builds over "
            "seconds after the load is applied.",
        ),
        Term(
            key="cooling",
            label="Cooling to surroundings",
            value=cooling,
            unit="W",
            symbol="−k·(T − T_amb)",
            why="Heat leaving the cell, in proportion to how far above its "
            "surroundings it already is. This is the term that grows as the cell "
            "warms, and it is why a healthy cell finds an equilibrium.",
        ),
    ]
    if fault != 0.0:
        terms.insert(
            2,
            Term(
                key="fault_heat",
                label="Fault heating",
                value=fault,
                unit="W",
                symbol="Q_fault",
                why="Heat from an injected fault, on top of everything the cell "
                "would be doing anyway.",
            ),
        )

    q_gen = ohmic + polar + fault
    equilibrium = (
        point.ambient_c + q_gen / point.k_cool_w_per_k
        if point.k_cool_w_per_k > 0
        else float("inf")
    )
    net = q_gen + cooling
    return additive(
        key="cell.heat_balance",
        label="Heat balance",
        unit="W",
        equation="C_th·dT/dt = I²·R₀ + I·V_rc + Q_fault − k·(T − T_ambient)",
        terms=terms,
        card="battery.thermal",
        operating_point={
            "series_index": float(point.series_index),
            "parallel_index": float(point.parallel_index),
            "current_a": point.current_a,
            "temp_c": point.temp_c,
            "ambient_c": point.ambient_c,
            "r0_ohm": point.r0_ohm,
            "k_cool_w_per_k": point.k_cool_w_per_k,
            "c_th_j_per_k": point.c_th_j_per_k,
            # The two numbers a reader wants next, and neither is a term:
            "rate_c_per_min": net / point.c_th_j_per_k * 60.0,
            "equilibrium_temp_c": equilibrium,
        },
        exact=point.exact,
        caveat=None if point.exact else _INFERRED_THERMAL_CAVEAT,
    )


def voltage_sag(point: CellPoint) -> Attribution:
    """Why the cell reads lower than its resting voltage, and which loss owns it.

    The decomposition is of the *sag*, not of the voltage. Decomposing the
    voltage itself would be true and useless: the open-circuit term is volts and
    the losses are millivolts, so it would report "the voltage is mostly the
    voltage" every single time. The sag is the part that has an interesting
    answer.
    """
    ohmic = point.current_a * point.r0_ohm
    polar = point.v_rc_v
    return additive(
        key="cell.voltage_sag",
        label="Voltage sag under load",
        unit="V",
        equation="OCV(SoC) − V = I·R₀ + V_rc",
        terms=[
            Term(
                key="ohmic_drop",
                label="Instant resistive drop",
                value=ohmic,
                unit="V",
                symbol="I·R₀",
                why="Appears the moment current flows and vanishes the moment it "
                "stops. Proportional to current.",
            ),
            Term(
                key="polarisation_drop",
                label="Polarisation drop",
                value=polar,
                unit="V",
                symbol="V_rc",
                why="Builds over seconds under load and decays over seconds at "
                "rest. It is why a cell keeps sagging after the load is steady.",
            ),
        ],
        card="battery.cell",
        operating_point={
            "series_index": float(point.series_index),
            "parallel_index": float(point.parallel_index),
            "ocv_v": point.ocv_v,
            "voltage_v": point.voltage_v,
            "current_a": point.current_a,
            "soc": point.soc,
            "r0_ohm": point.r0_ohm,
        },
        exact=point.exact,
        caveat=None if point.exact else _INFERRED_CAVEAT,
    )


def charge_rate(point: CellPoint) -> Attribution:
    """How fast this cell is emptying, and how much of that is going nowhere useful.

    Reported in percent per hour, because "0.000058 per second" is a true number
    nobody can act on. Splitting the load current from any parasitic current is
    the point: a cell draining faster than its neighbours while delivering the
    same current is the signature of an internal short.
    """
    # dSoC/dt = -eta*I/(Q*3600) per second; x3600 for per-hour, x100 for percent.
    per_hour = 100.0 * point.coulombic_eff / point.capacity_ah
    load = -point.current_a * per_hour
    parasitic = -point.extra_current_a * per_hour
    terms = [
        Term(
            key="load",
            label="Current to the load",
            value=load,
            unit="%/h",
            symbol="−η·I/(Q·3600)",
            why="Charge leaving the cell and doing the job it is there to do. "
            "Negative while discharging.",
        )
    ]
    if parasitic != 0.0:
        terms.append(
            Term(
                key="parasitic",
                label="Drain inside the cell",
                value=parasitic,
                unit="%/h",
                symbol="−η·I_fault/(Q·3600)",
                why="Charge draining through a fault path inside the cell. It "
                "never reaches the terminals, so nothing outside the cell sees it "
                "leave.",
            )
        )
    return additive(
        key="cell.charge_rate",
        label="Rate of charge change",
        unit="%/h",
        equation="dSoC/dt = −η·I_total / (Q·3600)",
        terms=terms,
        card="battery.cell",
        operating_point={
            "series_index": float(point.series_index),
            "parallel_index": float(point.parallel_index),
            "soc": point.soc,
            "capacity_ah": point.capacity_ah,
            "current_a": point.current_a,
        },
        exact=point.exact,
        caveat=None if point.exact else _INFERRED_CAVEAT,
    )


def imbalance(frame: dict, spec) -> Attribution:
    """Why the pack's cells are not at the same voltage.

    Compares the highest- and lowest-reading cells and splits the gap between
    them into the three things that can cause it: they hold different amounts of
    charge, they are carrying different currents through their resistance, or
    their slow polarisation states differ. The terms are the same terminal law
    as everywhere else, differenced.

    The three answers point at three different problems — an uneven pack, an
    uneven *load* within a parallel group, and a transient that has not settled
    — and telling them apart is most of what a balance investigation is.
    """
    from ..sim.ocv import make_ocv, ocv_table_for

    cells = frame.get("cells") or []
    if len(cells) < 2:
        raise ValueError("imbalance needs at least two cells in the frame")
    hi = max(cells, key=lambda c: c["voltage_v"])
    lo = min(cells, key=lambda c: c["voltage_v"])

    ocv_curve = make_ocv(ocv_table_for(getattr(spec, "chemistry", "NMC")))
    r0 = float(spec.r0_ohm)
    ocv_hi, ocv_lo = float(ocv_curve(hi["soc"])), float(ocv_curve(lo["soc"]))
    ir_hi, ir_lo = float(hi["current_a"]) * r0, float(lo["current_a"]) * r0
    # Polarisation as the residual of each cell's own terminal law.
    vrc_hi = ocv_hi - float(hi["voltage_v"]) - ir_hi
    vrc_lo = ocv_lo - float(lo["voltage_v"]) - ir_lo

    return additive(
        key="pack.imbalance",
        label="Voltage imbalance",
        unit="V",
        equation="ΔV = Δ OCV(SoC) − Δ(I·R₀) − Δ V_rc",
        terms=[
            Term(
                key="charge",
                label="Different charge levels",
                value=ocv_hi - ocv_lo,
                unit="V",
                symbol="ΔOCV",
                why="The two cells simply hold different amounts of charge. This "
                "is the kind of imbalance a balancing system exists to remove, "
                "and the only kind that persists at rest.",
            ),
            Term(
                key="resistive",
                label="Different current through resistance",
                value=-(ir_hi - ir_lo),
                unit="V",
                symbol="−Δ(I·R₀)",
                why="Within a parallel group current divides by conductance, so "
                "cells carrying more of it sag more. This part disappears the "
                "instant the load does.",
            ),
            Term(
                key="polarisation",
                label="Different polarisation state",
                value=-(vrc_hi - vrc_lo),
                unit="V",
                symbol="−ΔV_rc",
                why="One cell is further through its slow response than the other "
                "— usually because the load changed recently and they are settling "
                "at different rates.",
            ),
        ],
        card="battery.imbalance",
        operating_point={
            "highest_series": float(hi["series_index"]),
            "highest_parallel": float(hi["parallel_index"]),
            "lowest_series": float(lo["series_index"]),
            "lowest_parallel": float(lo["parallel_index"]),
            "highest_v": float(hi["voltage_v"]),
            "lowest_v": float(lo["voltage_v"]),
            "spread_v": float(hi["voltage_v"]) - float(lo["voltage_v"]),
        },
        exact=False,
        caveat=_INFERRED_CAVEAT,
    )


def imbalance_from_pack(pack) -> Attribution:
    """The same three-way split as :func:`imbalance`, read off a live pack.

    Every quantity the differencing needs — each cell's open-circuit voltage,
    its own resistance, its own polarisation state — is sitting in the solver's
    arrays, so this path has no residual and no caveat. It exists because
    imbalance is the one attribution a *telemetry* frame can only approximate:
    per-cell resistance spread is invisible from outside, and resistance spread
    is one of the three causes being told apart.
    """
    import numpy as np

    v = pack.cell_voltage_v
    hi_s, hi_p = divmod(int(np.argmax(v)), pack.shape[1])
    lo_s, lo_p = divmod(int(np.argmin(v)), pack.shape[1])

    ocv = pack.ocv(pack.soc)
    ir = pack.cell_current_a * pack.r0_nom
    vrc = pack.v_rc

    return additive(
        key="pack.imbalance",
        label="Voltage imbalance",
        unit="V",
        equation="ΔV = Δ OCV(SoC) − Δ(I·R₀) − Δ V_rc",
        terms=[
            Term(
                key="charge",
                label="Different charge levels",
                value=float(ocv[hi_s, hi_p] - ocv[lo_s, lo_p]),
                unit="V",
                symbol="ΔOCV",
                why="The two cells simply hold different amounts of charge. This "
                "is the kind of imbalance a balancing system exists to remove, "
                "and the only kind that persists at rest.",
            ),
            Term(
                key="resistive",
                label="Different current through resistance",
                value=float(-(ir[hi_s, hi_p] - ir[lo_s, lo_p])),
                unit="V",
                symbol="−Δ(I·R₀)",
                why="Within a parallel group current divides by conductance, so "
                "cells carrying more of it sag more — and because each cell has "
                "its own resistance, no two of them sag by the same amount. This "
                "part disappears the instant the load does.",
            ),
            Term(
                key="polarisation",
                label="Different polarisation state",
                value=float(-(vrc[hi_s, hi_p] - vrc[lo_s, lo_p])),
                unit="V",
                symbol="−ΔV_rc",
                why="One cell is further through its slow response than the other "
                "— usually because the load changed recently and they are settling "
                "at different rates.",
            ),
        ],
        card="battery.imbalance",
        operating_point={
            "highest_series": float(hi_s),
            "highest_parallel": float(hi_p),
            "lowest_series": float(lo_s),
            "lowest_parallel": float(lo_p),
            "highest_v": float(v[hi_s, hi_p]),
            "lowest_v": float(v[lo_s, lo_p]),
            "spread_v": float(v[hi_s, hi_p] - v[lo_s, lo_p]),
        },
    )


# -- picking the cell worth explaining ------------------------------------


def cell_of_interest(frame: dict) -> tuple[int, int]:
    """The cell an explanation should be about, if nobody said which.

    The hottest one. Not because temperature is the only thing that matters, but
    because it is the one quantity where being the outlier is *always*
    meaningful — a cell can lead on voltage for entirely healthy reasons, and
    cannot lead on temperature for any.
    """
    cells = frame.get("cells") or []
    if not cells:
        raise ValueError("frame carries no cells")
    hottest = max(cells, key=lambda c: c["temp_c"])
    return int(hottest["series_index"]), int(hottest["parallel_index"])


def explain_frame(frame: dict, spec, series_index: int | None = None,
                  parallel_index: int | None = None) -> list[Attribution]:
    """Every battery attribution available for one telemetry frame.

    Ordering here is the natural one — thermal, then electrical, then pack-wide.
    A domain lens reorders it (see :func:`simura.explain.domains.rank_for`);
    this function does not presume a reader.
    """
    if series_index is None or parallel_index is None:
        series_index, parallel_index = cell_of_interest(frame)
    point = operating_point_from_frame(frame, spec, series_index, parallel_index)
    out = [heat_balance(point), voltage_sag(point), charge_rate(point)]
    if len(frame.get("cells") or []) >= 2:
        out.append(imbalance(frame, spec))
    return out


def explain_pack(source, series_index: int | None = None,
                 parallel_index: int | None = None, effect=None) -> list[Attribution]:
    """Every battery attribution available for a live simulation, exactly.

    ``source`` is a :class:`~simura.sim.simulator.Simulator` or, if that is all
    you have, a bare :class:`~simura.sim.pack.BatteryPack`. **Prefer the
    simulator.** Fault and weather coefficients live on the effect the solver
    applied, not on the pack, and a pack alone cannot tell you a cell's fault
    current or the sun landing on it. Explaining a faulted pack without them
    does not merely lose detail — it reports the cell shedding heat it is in
    fact still making, which is worse than saying nothing. Passing the
    simulator picks the effect up automatically.
    """
    import numpy as np

    pack = getattr(source, "pack", source)
    if effect is None:
        effect = getattr(source, "effect", None)
    if series_index is None or parallel_index is None:
        idx = int(np.argmax(pack.temp_c))
        series_index, parallel_index = divmod(idx, pack.shape[1])
    point = operating_point_from_pack(pack, series_index, parallel_index, effect)
    out = [heat_balance(point), voltage_sag(point), charge_rate(point)]
    if pack.shape[0] * pack.shape[1] >= 2:
        out.append(imbalance_from_pack(pack))
    return out


# -- helpers ---------------------------------------------------------------


def _bounds(shape: tuple[int, int], s: int, p: int) -> None:
    if not (0 <= s < shape[0] and 0 <= p < shape[1]):
        raise IndexError(f"cell ({s}, {p}) is outside a {shape[0]}x{shape[1]} pack")


def _cell_in_frame(frame: dict, s: int, p: int) -> dict:
    for c in frame.get("cells") or []:
        if int(c["series_index"]) == s and int(c["parallel_index"]) == p:
            return c
    raise IndexError(f"cell ({s}, {p}) is not in this telemetry frame")
