"""Turn a :class:`~simura.builder.spec.SystemSpec` into a live simulator.

All the physics is the existing :mod:`simura.sim` -- this module only maps the
serializable spec onto the simulator's objects (config, load profile, faults) and
swaps in the chemistry's OCV curve. Keeping this mapping in one place means the
offline preview, the publisher's ``--spec`` mode, and any future caller build the
*same* system from the *same* description.
"""

from __future__ import annotations

from dataclasses import replace

from ..sim import (
    CellParams,
    ChargeDischargeCycle,
    ConstantCurrent,
    ConstantPower,
    CoolingFault,
    EnvironmentCoupling,
    Fault,
    InternalShort,
    LoadProfile,
    PackConfig,
    ResistanceGrowth,
    SensorDrift,
    SimConfig,
    Simulator,
    ThermalRunaway,
    make_ocv,
    ocv_table_for,
    sinusoidal,
)
from ..weather import SyntheticProvider, build_provider
from .spec import FaultSpec, ProfileSpec, SpaceSpec, SystemSpec, WeatherSpec

# Coupling-coefficient keys a WeatherSpec may override (all optional).
COUPLING_KEYS = (
    "wind_cooling_gain",
    "max_cooling_mult",
    "solar_absorptivity",
    "exposed_area_m2_per_cell",
    "shading_frac",
)

# Registries used both to build objects and to describe the options to the UI.
PROFILE_TYPES = ("constant_current", "constant_power", "cycle", "sinusoidal")
FAULT_TYPES = (
    "internal_short",
    "resistance_growth",
    "cooling_fault",
    "thermal_runaway",
    "sensor_drift",
)


def build_cell_params(spec: SystemSpec) -> CellParams:
    return CellParams(
        capacity_ah=spec.capacity_ah,
        r0_ohm=spec.r0_ohm,
        r1_ohm=spec.r1_ohm,
        c1_farad=spec.c1_farad,
        coulombic_eff=spec.coulombic_eff,
        thermal_capacity_j_per_k=spec.thermal_capacity_j_per_k,
        cooling_conductance_w_per_k=spec.cooling_conductance_w_per_k,
        v_min=spec.v_min,
        v_max=spec.v_max,
        temp_max_c=spec.temp_max_c,
    )


def build_pack_config(spec: SystemSpec) -> PackConfig:
    return PackConfig(
        series=spec.series,
        parallel=spec.parallel,
        cell=build_cell_params(spec),
        capacity_spread=spec.capacity_spread,
        resistance_spread=spec.resistance_spread,
        initial_soc=spec.initial_soc,
        initial_soc_spread=spec.initial_soc_spread,
        ambient_temp_c=spec.ambient_temp_c,
        seed=spec.seed,
    )


def build_sim_config(spec: SystemSpec) -> SimConfig:
    return SimConfig(dt_s=spec.dt_s, duration_s=spec.duration_s)


def build_profile(profile: ProfileSpec) -> LoadProfile:
    p = profile.params
    t = profile.type
    if t == "constant_current":
        return ConstantCurrent(float(p.get("amps", 10.0)))
    if t == "constant_power":
        return ConstantPower(float(p.get("watts", 1000.0)))
    if t == "cycle":
        return ChargeDischargeCycle(
            discharge_a=float(p.get("discharge_a", 20.0)),
            charge_a=float(p.get("charge_a", 15.0)),
            discharge_s=float(p.get("discharge_s", 1200.0)),
            charge_s=float(p.get("charge_s", 1200.0)),
            rest_s=float(p.get("rest_s", 300.0)),
        )
    if t == "sinusoidal":
        return sinusoidal(
            float(p.get("mean_a", 10.0)),
            float(p.get("amplitude_a", 5.0)),
            float(p.get("period_s", 600.0)),
        )
    raise ValueError(f"unknown profile type '{t}' (use one of {', '.join(PROFILE_TYPES)})")


def build_fault(fault: FaultSpec) -> Fault:
    cell = (fault.series, fault.parallel)
    p = fault.params
    kw = {"cell": cell, "start_s": fault.start_s}
    if "end_s" in p:
        kw["end_s"] = float(p["end_s"])
    t = fault.type
    if t == "internal_short":
        return InternalShort(r_short_ohm=float(p.get("r_short_ohm", 2.0)), **kw)
    if t == "resistance_growth":
        return ResistanceGrowth(multiplier=float(p.get("multiplier", 3.0)), **kw)
    if t == "cooling_fault":
        return CoolingFault(effectiveness=float(p.get("effectiveness", 0.2)), **kw)
    if t == "thermal_runaway":
        return ThermalRunaway(
            trigger_c=float(p.get("trigger_c", 70.0)),
            scale_w=float(p.get("scale_w", 5.0)),
            temp_slope_c=float(p.get("temp_slope_c", 15.0)),
            **kw,
        )
    if t == "sensor_drift":
        return SensorDrift(
            signal=str(p.get("signal", "voltage")),
            rate_per_s=float(p.get("rate_per_s", 0.0)),
            offset=float(p.get("offset", 0.0)),
            **kw,
        )
    raise ValueError(f"unknown fault type '{t}' (use one of {', '.join(FAULT_TYPES)})")


def build_faults(spec: SystemSpec) -> list[Fault]:
    return [build_fault(f) for f in spec.faults]


def build_weather(spec: SystemSpec, *, offline: bool = False):
    """Build the weather provider for a spec, or ``None`` for ``type="none"``.

    Delegates to :func:`simura.weather.build_provider`, so weather stays a
    declarative part of the spec and the physics core never imports a concrete
    provider. When ``offline=True`` (the offline preview), a live ``open_meteo``
    source is substituted with an equivalent :class:`SyntheticProvider` so the
    preview never makes a network call and stays reproducible.
    """
    w = getattr(spec, "weather", None)
    if w is None or w.type in (None, "", "none"):
        return None
    params = dict(w.params)
    if offline and w.type == "open_meteo":
        return SyntheticProvider(tz_offset_h=float(params.get("tz_offset_h", 0.0)))
    provider_spec = {"type": w.type, **params}
    return build_provider(provider_spec)


def build_coupling(spec: SystemSpec) -> EnvironmentCoupling:
    """Build the enclosure coupling, honouring any coefficient overrides in params."""
    params = dict(getattr(spec.weather, "params", {}) or {})
    overrides = {k: float(params[k]) for k in COUPLING_KEYS if k in params}
    return EnvironmentCoupling(**overrides)


def build_space(spec: SystemSpec):
    """Resolve the room the system stands in, or ``None``.

    Delegates to :mod:`simura.space` exactly as :func:`build_weather` delegates
    to :mod:`simura.weather`, so a building stays a declarative part of the spec
    and the physics core never imports an importer. Returns a
    :class:`~simura.space.couple.SpaceContext` -- the room, its ambient, and the
    *reason* for that ambient.

    Anything that goes wrong reading the model returns ``None`` rather than
    raising. A floor plan is context, not a dependency: a system whose building
    file has moved should still run, minus what the building was telling it.
    """
    s = getattr(spec, "space", None)
    if s is None or s.type in (None, "", "none") or not s.space_id:
        return None
    try:
        from ..space import ambient_for, build_provider as build_plan_provider

        provider = build_plan_provider({"type": s.type, **dict(s.params or {})})
        if provider is None:
            return None
        return ambient_for(provider.plan(), s.space_id)
    except Exception:
        return None


def build_simulator(
    spec: SystemSpec,
    *,
    weather_epoch0: float | None = None,
    offline_weather: bool = False,
) -> Simulator:
    """Construct a ready-to-run :class:`Simulator` for the spec.

    The pack's OCV curve is swapped to the spec's chemistry (NMC/LFP/LCO/NCA) and
    the reported cell voltage re-seeded, so a user's LFP system behaves like LFP.
    If the spec carries a weather source it is attached, so the pack's ambient,
    cooling, and solar heat load track real (or synthetic) conditions.
    ``weather_epoch0`` pins the wall-clock instant sim-time t=0 maps to (used by
    the offline preview for reproducibility); ``None`` means "now" at run time.
    """
    pack_config = build_pack_config(spec)
    weather = build_weather(spec, offline=offline_weather)

    # A building, if the spec names one. Standing indoors is not a modifier on
    # the weather -- it is the statement that the weather does not reach this
    # pack: no sun on the cabinet, no wind over it, and an ambient held at the
    # room's setpoint rather than the outside air. So the weather source is
    # dropped rather than damped, which is both the truthful model and the one
    # that needs no new coefficient nobody could justify.
    space = build_space(spec)
    if space is not None and space.indoor:
        pack_config = replace(pack_config, ambient_temp_c=space.ambient_c)
        weather = None

    sim = Simulator(
        pack_config=pack_config,
        sim_config=build_sim_config(spec),
        profile=build_profile(spec.profile),
        faults=build_faults(spec),
        weather=weather,
        coupling=build_coupling(spec),
        weather_epoch0=weather_epoch0,
    )
    sim.pack.ocv = make_ocv(ocv_table_for(spec.chemistry))
    sim.pack.cell_voltage_v = sim.pack.ocv(sim.pack.soc).copy()
    sim.pack.pack_voltage_v = float(
        sim.pack.cell_voltage_v.sum(axis=1).mean() * spec.series
    )
    return sim
