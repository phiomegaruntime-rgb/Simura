"""HTTP + WebSocket API for the twin core.

REST for state and history; a WebSocket per system for the live stream. Handlers
read shared objects (store, live state, ws manager) off ``app.state``, wired up
in :mod:`simura.twincore.main`.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from ..builder import (
    FaultSpec,
    SpecError,
    SystemSpec,
    builder_options,
    preview,
    validate_spec,
)
from ..fleet import build_fleet
from ..lights import (
    LightSpec,
    build_layout,
    catalog_options as light_catalog_options,
    evaluate_installation,
    recommend_lamp,
)
from ..lights.validation import (
    get_standard as get_light_standard,
    list_standards as list_light_standards,
    load_upload_csv as load_light_upload_csv,
    validate_daylight_live,
    validate_reference as validate_light_reference,
)
from ..wires import (
    WireSpec,
    build_network,
    catalog_options,
    evaluate_run,
    recommend_gauge,
)
from ..wires.validation import (
    get_standard,
    list_standards,
    load_upload_csv,
    validate_reference,
)
from ..weather import WeatherSample, build_provider, search_places
from ..validate import (
    get_dataset,
    list_datasets,
    load_sample,
    load_upload,
    synthetic_for,
    validate_run,
)
from .auth import extract_key, is_authorized
from .state import LatestState, WebSocketManager
from .store import TimescaleStore

# REST routes are guarded by the API-key dependency at include time. The
# WebSocket lives on its own router (HTTP dependencies don't apply cleanly to
# WS handshakes) and does its own key check inside the handler.
router = APIRouter()
ws_router = APIRouter()


class ValidationRunRequest(BaseModel):
    """Body for POST /api/validation/run."""

    dataset_id: str = "demo-synthetic"
    fit: bool = True


class WireValidationRunRequest(BaseModel):
    """Body for POST /api/wires/validation/run."""

    standard_id: str = "copper-annealed-20c"


class LightValidationRunRequest(BaseModel):
    """Body for POST /api/lights/validation/run."""

    standard_id: str = "lamp-efficacy-published"


class LightLiveValidationRequest(BaseModel):
    """Body for POST /api/lights/validation/live.

    The one validation in the project that reaches the network: it checks the
    daylight model against measured irradiance over a real place, right now.
    """

    latitude: float = 51.5074
    longitude: float = -0.1278
    hours: int = 48


class CreateSystemRequest(BaseModel):
    """Body for POST /api/systems (create a simulation or register a real-time feed)."""

    source: str = "simulation"          # "simulation" | "realtime"
    system_id: Optional[str] = None
    name: Optional[str] = None
    spec: Optional[dict[str, Any]] = None
    speed: Optional[float] = None
    autostart: bool = True


class InjectFaultRequest(BaseModel):
    """Body for POST /api/systems/{id}/faults (break a running pack)."""

    type: str = "internal_short"
    series: int = 0
    parallel: int = 0
    params: dict[str, float] = {}


def _store(request: Request) -> TimescaleStore:
    return request.app.state.store


def _live(request: Request) -> LatestState:
    return request.app.state.live


def _anomaly_live(request: Request) -> LatestState:
    return request.app.state.anomaly_live


def _assessment_live(request: Request) -> LatestState:
    return request.app.state.assessment_live


def _ws_manager(request: Request) -> WebSocketManager:
    return request.app.state.ws_manager


def _sim_manager(request: Request):
    return request.app.state.sim_manager


def _enrich_lifecycle(systems: list[dict[str, Any]], sim_manager) -> list[dict[str, Any]]:
    """Overlay the SimManager's live run-state onto the registry rows."""
    live_states = sim_manager.states()
    for s in systems:
        if s["system_id"] in live_states:
            s["run_state"] = live_states[s["system_id"]]
    return systems


@router.get("/api/fleet")
async def fleet(request: Request) -> dict[str, Any]:
    """Whole-fleet rollup: one status row per system plus a summary.

    Aggregates the registry with the live telemetry/anomaly/assessment caches so
    an operator sees every pack at once, worst-first. All logic lives in the pure
    :func:`simura.fleet.build_fleet`; this handler is just wiring.
    """
    settings = request.app.state.settings
    systems = _enrich_lifecycle(await _store(request).list_systems(), _sim_manager(request))
    return build_fleet(
        systems,
        _live(request).as_dict(),
        _anomaly_live(request).as_dict(),
        _assessment_live(request).as_dict(),
        now=datetime.now(timezone.utc),
        stale_after_s=settings.fleet_stale_after_s,
    )


@router.get("/api/validation/datasets")
async def validation_datasets() -> list[dict[str, Any]]:
    """The catalog of open battery datasets the user can select and validate against.

    Pure metadata (no data is shipped); the dashboard renders these as selectable
    cards. See :mod:`simura.validate.catalog`.
    """
    return [d.to_dict() for d in list_datasets()]


@router.post("/api/validation/run")
async def validation_run(body: ValidationRunRequest) -> dict[str, Any]:
    """Run an in-browser *demonstration* of the validation pipeline.

    The browser can't reach the user's local dataset download, so this endpoint
    always validates a bundled **synthetic** sample and says so
    (``data_source == "bundled-synthetic-demo"``). The sample is chosen to match
    the selected dataset's chemistry (e.g. an LFP dataset validates against the
    LFP synthetic sample and the LFP OCV curve). Real datasets are validated by
    the user via the CLI with their own file; the dashboard surfaces that command.
    """
    try:
        spec = get_dataset(body.dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    ref_spec = spec if spec.sample else synthetic_for(spec.chemistry)
    ref = load_sample(ref_spec)
    report = validate_run(ref, fit=body.fit, data_source="bundled-synthetic-demo")
    result = report.to_dict()
    # Be explicit about what was actually validated vs what the user selected.
    result["requested_dataset_id"] = body.dataset_id
    result["sample_dataset_id"] = ref.dataset_id
    return result


@router.post("/api/validation/upload")
async def validation_upload(
    request: Request,
    file: UploadFile = File(...),
    dataset_id: str = Form(""),
    chemistry: str = Form(""),
    fit: bool = Form(True),
    time_col: str = Form("time_s"),
    current_col: str = Form("current_a"),
    voltage_col: str = Form("voltage_v"),
    temp_col: str = Form(""),
    discharge_positive: bool = Form(True),
    current_scale: float = Form(1.0),
    nominal_capacity_ah: float = Form(5.0),
) -> dict[str, Any]:
    """Validate the model against the user's **own** uploaded dataset file.

    This is the real thing (not the synthetic demo): the browser uploads a file,
    the server parses it with the matching loader (a format-specific one when
    ``dataset_id`` names such a dataset, else the generic CSV loader with the
    given column mapping), replays it through the model, and returns the report
    with ``data_source == "user-upload"``. ``.mat`` files need SciPy on the server
    (``pip install simura[validate]``).
    """
    settings = request.app.state.settings
    max_bytes = int(settings.validation_max_upload_mb * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {settings.validation_max_upload_mb:g} MB limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    suffix = Path(file.filename or "upload").suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        try:
            ref = load_upload(
                tmp.name,
                dataset_id=dataset_id or None,
                chemistry=chemistry or None,
                time_col=time_col,
                current_col=current_col,
                voltage_col=voltage_col,
                temp_col=temp_col or None,
                discharge_positive=discharge_positive,
                current_scale=current_scale,
                nominal_capacity_ah=nominal_capacity_ah,
            )
        except ModuleNotFoundError as exc:  # scipy missing for a .mat upload
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (ValueError, KeyError, StopIteration) as exc:
            raise HTTPException(
                status_code=400, detail=f"could not parse dataset: {exc}"
            ) from None

        report = validate_run(ref, chemistry=chemistry or None, fit=fit, data_source="user-upload")
        result = report.to_dict()
        result["filename"] = file.filename
        result["requested_dataset_id"] = dataset_id or None
        return result
    finally:
        os.unlink(tmp.name)


@router.get("/api/builder/options")
async def builder_options_endpoint() -> dict[str, Any]:
    """Enumerations + a default spec for the dashboard's system-builder form."""
    return builder_options()


@router.post("/api/builder/validate")
async def builder_validate(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate a user's system spec; returns the list of problems (empty == valid)."""
    errors = validate_spec(SystemSpec.from_dict(spec))
    return {"valid": not errors, "errors": errors}


@router.post("/api/builder/preview")
async def builder_preview(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Run a user's system spec offline and return a summary + sparklines.

    Pure compute (no MQTT, no DB). Returns 400 with the validation errors if the
    spec is invalid, so the dashboard can point at exactly what to fix.
    """
    try:
        result = preview(SystemSpec.from_dict(spec))
    except SpecError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors}) from None
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return result.to_dict()


@router.get("/api/weather/places")
async def weather_places(q: str = Query("", max_length=120)) -> list[dict[str, Any]]:
    """Look up places by name, for pointing a live weather source at one.

    Nobody thinks in latitude and longitude, and the result carries the **IANA
    timezone** — which is what lets a caller show a local clock and answer "is it
    morning or evening there?". Proxied rather than called from the browser so the
    dashboard keeps talking to exactly one origin.

    A lookup failure is an empty list, not a 500: a site still runs on
    coordinates, it just can't name them.
    """
    try:
        places = await asyncio.to_thread(search_places, q)
    except Exception:  # network hiccup, or Open-Meteo having a bad day
        return []
    return [p.to_dict() for p in places]


# Built providers, keyed by their spec. A live source caches its fetched window
# inside the provider, so rebuilding one per request would re-fetch on every poll.
_weather_providers: dict[str, Any] = {}


@router.post("/api/weather/sample")
async def weather_sample(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Evaluate a weather spec **right now** -- ``{type, params}`` in, one sample out.

    A caller needs the conditions its site is in before it has anything to put
    there; reading them off a running rack's telemetry only works once a rack
    exists and is streaming. This answers the same question with no system at all,
    from the same :mod:`simura.weather` providers, so a site with one battery and
    a site with none are in the same weather.

    Returns ``{"weather": null}`` for ``type: "none"``.
    """
    spec = {"type": str(body.get("type", "none")), **(body.get("params") or {})}
    if spec["type"] in ("", "none"):
        return {"weather": None}

    key = json.dumps(spec, sort_keys=True, default=str)
    provider = _weather_providers.get(key)
    if provider is None:
        try:
            provider = build_provider(spec)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
        if provider is None:
            return {"weather": None}
        if len(_weather_providers) > 32:
            _weather_providers.clear()  # a sandbox, not a server farm
        _weather_providers[key] = provider

    # A live provider's first call fetches over HTTP; keep that off the event loop.
    sample = await asyncio.to_thread(provider.at, time.time())
    return {"weather": sample.to_dict()}


@router.get("/api/wires/catalog")
async def wires_catalog() -> dict[str, Any]:
    """Materials, insulations, and the selectable wire catalog (for the Wires view)."""
    return catalog_options()


def _weather_from_body(body: dict[str, Any]) -> WeatherSample | None:
    """Build a WeatherSample from an optional ``weather`` object on a planner body.

    The planner only needs one instant's conditions, so we take a plain
    ``{air_temp_c, wind_speed_ms?, solar_w_m2?}`` and stamp it with a placeholder
    timestamp/source. Returns ``None`` when no weather is supplied.
    """
    w = body.get("weather")
    if not w:
        return None
    return WeatherSample(
        timestamp=0.0,
        air_temp_c=float(w["air_temp_c"]),
        wind_speed_ms=float(w.get("wind_speed_ms", 0.0)),
        solar_w_m2=float(w.get("solar_w_m2", 0.0)),
        source="planner",
    )


@router.post("/api/wires/evaluate")
async def wires_evaluate(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Check one wire run against ampacity / voltage drop / temperature.

    Body: ``{spec: {...WireSpec}, current_a, system_voltage_v?, max_drop_pct?,
    round_trip?, weather?: {air_temp_c, wind_speed_ms?, solar_w_m2?}}``. When
    ``weather`` is present the check is done for that day's conditions (ambient
    derates the ampacity; wind and sun move the predicted conductor temperature).
    """
    try:
        spec = WireSpec.from_dict(body.get("spec", {}))
        assessment = evaluate_run(
            spec,
            current_a=float(body.get("current_a", 0.0)),
            system_voltage_v=body.get("system_voltage_v"),
            max_drop_pct=float(body.get("max_drop_pct", 3.0)),
            round_trip=bool(body.get("round_trip", True)),
            weather=_weather_from_body(body),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return assessment.to_dict()


@router.post("/api/wires/recommend")
async def wires_recommend(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Size the smallest catalog wire that satisfies the constraints.

    Accepts an optional ``weather`` object (see ``/api/wires/evaluate``); when
    present the gauge is sized for that day's conditions.
    """
    try:
        rec = recommend_gauge(
            current_a=float(body["current_a"]),
            length_m=float(body["length_m"]),
            system_voltage_v=body.get("system_voltage_v"),
            max_drop_pct=float(body.get("max_drop_pct", 3.0)),
            material=str(body.get("material", "copper")),
            ambient_c=float(body.get("ambient_c", 25.0)),
            round_trip=bool(body.get("round_trip", True)),
            weather=_weather_from_body(body),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return rec.to_dict()


@router.post("/api/wires/network")
async def wires_network(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Solve a multi-node wire network (nodes + segments).

    A segment may carry ``faults`` (``[{type, ...params}]``, see
    :data:`simura.wires.WIRE_FAULT_TYPES`); the fault is folded into the solve, so
    the whole network re-settles around the bad run rather than just that run
    getting hot. ``elapsed_s`` is how long those faults have been active, which
    matters for the ones that develop over time (corrosion).

    An optional ``weather`` object (``{air_temp_c, wind_speed_ms?, solar_w_m2?}``,
    the same shape ``/api/wires/evaluate`` takes) solves the whole network for that
    day's conditions: ambient derates every segment's ampacity, wind cools, sun
    heats.
    """
    try:
        result = build_network(body).solve(
            elapsed_s=float(body.get("elapsed_s", 0.0)),
            weather=_weather_from_body(body),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return result.to_dict()


@router.get("/api/wires/validation/standards")
async def wires_validation_standards() -> list[dict[str, Any]]:
    """The catalog of published conductor standards the wire model can be checked against.

    Pure metadata (the reference tables are bundled and computed offline); the
    dashboard renders these as selectable cards. See
    :mod:`simura.wires.validation.standards`.
    """
    return [s.to_dict() for s in list_standards()]


@router.post("/api/wires/validation/run")
async def wires_validation_run(body: WireValidationRunRequest) -> dict[str, Any]:
    """Validate the wire model against one bundled reference standard.

    Replays every gauge in the standard through Simura's own ``Wire`` and
    reports the per-gauge percent error against the published DC resistance.
    """
    try:
        standard = get_standard(body.standard_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return validate_reference(standard.reference()).to_dict()


@router.post("/api/wires/validation/upload")
async def wires_validation_upload(
    request: Request,
    file: UploadFile = File(...),
    material: str = Form("copper"),
    awg_col: str = Form("awg"),
    resistance_col: str = Form("resistance_ohm_per_km"),
    ref_temp_c: float = Form(20.0),
    resistance_unit: str = Form("ohm/km"),
) -> dict[str, Any]:
    """Validate the wire model against the user's **own** measured-resistance CSV.

    The browser uploads a CSV with an AWG column and a DC-resistance column; the
    server parses it, replays each gauge through the model, and returns the report
    with ``data_source == "user-upload"``.
    """
    settings = request.app.state.settings
    max_bytes = int(settings.validation_max_upload_mb * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {settings.validation_max_upload_mb:g} MB limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    suffix = Path(file.filename or "upload").suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        try:
            ref = load_upload_csv(
                tmp.name,
                material=material,
                awg_col=awg_col,
                resistance_col=resistance_col,
                ref_temp_c=ref_temp_c,
                resistance_unit=resistance_unit,
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"could not parse CSV: {exc}") from None
        result = validate_reference(ref).to_dict()
        result["filename"] = file.filename
        return result
    finally:
        os.unlink(tmp.name)


@router.get("/api/lights/catalog")
async def lights_catalog() -> dict[str, Any]:
    """Technologies, lamps, faults, profiles, controls and lux targets.

    Everything a Lights UI needs to build its forms, in one call. Pure compute --
    no broker, no database.
    """
    return light_catalog_options()


@router.post("/api/lights/evaluate")
async def lights_evaluate(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Check one lighting design against illuminance, colour and installed power.

    Body: ``{spec: {...LightSpec}, n_luminaires, length_m, width_m,
    mounting_height_m?, task?, target_lux?, maintenance_hours?, dirt_frac?,
    reflectances?, annual_hours?, weather?: {air_temp_c, wind_speed_ms?,
    solar_w_m2?}}``.

    With ``weather`` the check is done for that day's conditions -- which moves the
    answer in opposite directions by technology, since a cold fluorescent tube
    loses output where a cold LED gains it.
    """
    try:
        spec = LightSpec.from_dict(body.get("spec", {}))
        assessment = evaluate_installation(
            spec,
            n_luminaires=int(body.get("n_luminaires", 1)),
            length_m=float(body.get("length_m", 8.0)),
            width_m=float(body.get("width_m", 6.0)),
            mounting_height_m=float(body.get("mounting_height_m", 2.5)),
            task=str(body.get("task", "office")),
            target_lux=body.get("target_lux"),
            ceiling_reflectance=float(body.get("ceiling_reflectance", 0.7)),
            wall_reflectance=float(body.get("wall_reflectance", 0.5)),
            floor_reflectance=float(body.get("floor_reflectance", 0.2)),
            maintenance_hours=float(body.get("maintenance_hours", 0.0)),
            dirt_frac=float(body.get("dirt_frac", 0.1)),
            annual_hours=float(body.get("annual_hours", 2500.0)),
            weather=_weather_from_body(body),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return assessment.to_dict()


@router.post("/api/lights/recommend")
async def lights_recommend(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Pick the catalog lamp that meets the target at the lowest installed power.

    Returns the winner plus the ranked alternatives, so the trade between
    technologies is visible rather than asserted. Accepts an optional ``family``
    to ask what the best filament or discharge answer would have been, and the
    same ``weather`` object as ``/api/lights/evaluate``.
    """
    try:
        rec = recommend_lamp(
            length_m=float(body["length_m"]),
            width_m=float(body["width_m"]),
            mounting_height_m=float(body.get("mounting_height_m", 2.5)),
            task=str(body.get("task", "office")),
            target_lux=body.get("target_lux"),
            family=body.get("family"),
            ceiling_reflectance=float(body.get("ceiling_reflectance", 0.7)),
            wall_reflectance=float(body.get("wall_reflectance", 0.5)),
            floor_reflectance=float(body.get("floor_reflectance", 0.2)),
            maintenance_hours=float(body.get("maintenance_hours", 8000.0)),
            dirt_frac=float(body.get("dirt_frac", 0.1)),
            annual_hours=float(body.get("annual_hours", 2500.0)),
            weather=_weather_from_body(body),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return rec.to_dict()


@router.post("/api/lights/layout")
async def lights_layout(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Solve the illuminance field for a room full of luminaires.

    Body: ``{length_m, width_m, workplane_height_m?, grid_n?, grid?: {rows, cols,
    height_m, lamp}, luminaires?: [{id, x_m, y_m, height_m, lamp, drive?,
    faults?}], target_lux?, min_uniformity?, elapsed_s?, weather?}``.

    A luminaire may carry ``faults`` (``[{type, ...params}]``, see
    :data:`simura.lights.LIGHT_FAULT_TYPES`), so a single failed or fouled fitting
    can be dropped into a working layout and the dark patch it leaves measured.
    ``elapsed_s`` is how long those faults have been active, which matters for the
    ones that develop over time.
    """
    try:
        layout = build_layout(body)
        result = layout.solve(
            elapsed_s=float(body.get("elapsed_s", 0.0)),
            target_lux=float(body.get("target_lux", 0.0)),
            min_uniformity=float(body.get("min_uniformity", 0.0)),
            weather=_weather_from_body(body),
            include_interreflection=bool(body.get("include_interreflection", True)),
            ceiling_reflectance=float(body.get("ceiling_reflectance", 0.7)),
            wall_reflectance=float(body.get("wall_reflectance", 0.5)),
            floor_reflectance=float(body.get("floor_reflectance", 0.2)),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return result.to_dict()


@router.post("/api/lights/spectrum")
async def lights_spectrum(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """One lamp's spectral power distribution and everything derived from it.

    Body: ``{spec: {...LightSpec}, drive?, ambient_c?, bin_nm?}``. Returns the SPD
    on a coarsened wavelength grid (``bin_nm``, 5 nm by default -- the full 1 nm
    grid is 471 points and no chart needs that) alongside the operating point, so
    a UI can show *why* a lamp has the efficacy it has.
    """
    from ..lights.spectrum import WAVELENGTHS_NM
    from ..lights.lamp import Light

    try:
        light = Light(LightSpec.from_dict(body.get("spec", {})))
        light.time_lit_s = 1e9              # report a warmed-up lamp
        point = light.operating_point(
            float(body.get("drive", 1.0)), body.get("ambient_c")
        )
        spd = light.spectrum()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None

    step = max(1, int(body.get("bin_nm", 5)))
    peak = max(spd.values) or 1.0
    wavelengths = [WAVELENGTHS_NM[i] for i in range(0, len(WAVELENGTHS_NM), step)]
    relative = [round(spd.values[i] / peak, 5) for i in range(0, len(spd.values), step)]
    x, y = spd.chromaticity()

    return {
        "wavelength_nm": wavelengths,
        "relative_power": relative,
        "operating_point": point.to_dict(),
        "chromaticity": {"x": round(x, 5), "y": round(y, 5)},
        "spectral_coverage": round(spd.spectral_coverage(), 4),
        "published_cri": light.tech.cri,
        "technology": light.tech.to_dict(),
        "published_flux_lm": light.published_flux_lm,
    }


@router.post("/api/lights/simulate")
async def lights_simulate(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Run one luminaire through time and return the frames.

    Body: ``{spec, profile?: {type, ...}, control?: {type, ...}, faults?: [...],
    weather?: {type, ...provider params}, dt_s?, duration_s?, mounting_height_m?,
    target_lux?, coupling?}``.

    Unlike the planner's single operating point, this shows the things that only
    exist in time: a discharge lamp's warm-up, an LED's thermal settle, a
    photocell following the sun, a fault developing. ``weather`` here is a full
    *provider* spec (the same shape ``/api/weather/sample`` takes), not one
    sample, because the run needs conditions that move.
    """
    from ..lights.config import build_control, build_coupling, build_fault, build_profile
    from ..lights.profiles import ConstantDrive
    from ..lights.simulator import LightSimConfig, LightSimulator

    try:
        dt_s = max(float(body.get("dt_s", 10.0)), 1e-3)
        duration_s = float(body.get("duration_s", 3600.0))
        # A sandbox, not a batch job: cap the frame count so a stray request
        # cannot ask the twin core for a million timesteps.
        if duration_s / dt_s > 20000:
            raise ValueError("too many steps: raise dt_s or lower duration_s (20000 max)")

        profile_spec = body.get("profile")
        sim = LightSimulator(
            spec=LightSpec.from_dict(body.get("spec", {})),
            sim_config=LightSimConfig(
                dt_s=dt_s,
                duration_s=duration_s,
                mounting_height_m=float(body.get("mounting_height_m", 3.0)),
                target_lux=float(body.get("target_lux", 0.0)),
                hours_per_second=float(body.get("hours_per_second", 0.0)),
            ),
            profile=build_profile(profile_spec) if profile_spec else ConstantDrive(1.0),
            faults=[build_fault(f) for f in body.get("faults", [])],
            weather=build_provider(body.get("weather") or {}),
            coupling=build_coupling(body.get("coupling") or {}),
            control=build_control(body.get("control") or {}),
            weather_epoch0=body.get("weather_epoch0"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None

    # A live weather provider's first call fetches over HTTP, and the run itself
    # is pure CPU; keep both off the event loop.
    try:
        frames = await asyncio.to_thread(sim.run_to_list)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None

    energy_kwh = sum(f.input_power_w for f in frames) * dt_s / 3_600_000.0
    return {
        "frames": [f.to_dict() for f in frames],
        "summary": {
            "n_frames": len(frames),
            "energy_kwh": round(energy_kwh, 6),
            "lamp_hours": round(frames[-1].operating_hours_h, 4) if frames else 0.0,
            "switch_cycles": frames[-1].switch_cycles if frames else 0.0,
            "final_flux_lm": frames[-1].luminous_flux_lm if frames else 0.0,
            "final_source_temp_c": frames[-1].source_temp_c if frames else 0.0,
        },
    }


@router.post("/api/lights/operate")
async def lights_operate(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Solve many luminaires at once, each against the voltage it actually has.

    Body: ``{lights: [{id, spec, supply_voltage_v, drive?, height_m?, faults?}],
    ambient_c?, elapsed_s?, weather?}``.

    One call for a whole site, the same way ``/api/wires/network`` solves a whole
    network — a site with twenty fittings should not need twenty round trips.

    The interesting part is what comes back for a lamp whose supply has sagged,
    because it depends on whether the lamp has control gear:

    * a **filament** dims steeply and reddens, while its current barely moves;
    * a **driver or ballast** holds output flat and draws *more* current as the
      voltage falls, then drops out entirely below its minimum input.

    Callers that also solve an electrical network should expect to iterate: the
    current a regulated lamp draws depends on the voltage it gets, which depends
    on the current it draws. Two passes is normally enough.
    """
    from ..lights.faults import accumulate
    from ..lights.config import build_fault as build_light_fault
    from ..lights.lamp import Light
    from ..lights.photometry import point_illuminance_lux

    entries = body.get("lights") or []
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="'lights' must be a list")
    if len(entries) > 256:
        raise HTTPException(status_code=400, detail="too many lights (256 max)")

    ambient_c = body.get("ambient_c")
    elapsed_s = float(body.get("elapsed_s", 0.0))
    weather = _weather_from_body(body)
    daylight_lux = 0.0
    if weather is not None:
        from ..lights.environment import LightEnvironmentCoupling

        env = LightEnvironmentCoupling(**(body.get("coupling") or {})).apply(weather)
        ambient_c = env.ambient_c if ambient_c is None else ambient_c
        daylight_lux = env.daylight_lux

    results: dict[str, Any] = {}
    for entry in entries:
        try:
            spec = LightSpec.from_dict(entry.get("spec", {}))
            light = Light(spec)
            # A luminaire solved from a network is a settled one: the transient is
            # the simulator's business, not the site's.
            light.time_lit_s = 1e9
            effect = accumulate(
                [build_light_fault(f) for f in entry.get("faults", [])], light, elapsed_s
            )
            supply = light.at_supply(
                float(entry.get("supply_voltage_v", light.supply_voltage_v)),
                drive=float(entry.get("drive", 1.0)),
                ambient_c=ambient_c,
                effect=effect,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None

        height = float(entry.get("height_m", 0.0))
        lux = (
            point_illuminance_lux(supply.point.luminous_flux_lm, light.beam_angle_deg, height)
            if height > 0
            else 0.0
        )
        result = supply.to_dict()
        result["illuminance_lux"] = round(lux, 2)
        result["beam_angle_deg"] = light.beam_angle_deg
        result["cri"] = light.tech.cri
        result["family"] = light.tech.family
        result["technology"] = light.tech.key
        results[str(entry.get("id", ""))] = result

    return {"lights": results, "daylight_lux": round(daylight_lux, 2)}


@router.get("/api/lights/validation/standards")
async def lights_validation_standards() -> list[dict[str, Any]]:
    """The catalog of published references the lighting model can be checked against.

    Pure metadata (the reference tables are bundled and computed offline); the
    dashboard renders these as selectable cards. See
    :mod:`simura.lights.validation.standards`.
    """
    return [s.to_dict() for s in list_light_standards()]


@router.post("/api/lights/validation/run")
async def lights_validation_run(body: LightValidationRunRequest) -> dict[str, Any]:
    """Validate the lighting model against one bundled reference standard."""
    try:
        standard = get_light_standard(body.standard_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return validate_light_reference(standard.reference()).to_dict()


@router.post("/api/lights/validation/live")
async def lights_validation_live(body: LightLiveValidationRequest) -> dict[str, Any]:
    """Validate the daylight model against **live** measured irradiance.

    The only validation in the project whose reference data does not ship with it:
    it fetches the last ``hours`` of real shortwave radiation for a real place from
    Open-Meteo and checks the clear-sky daylight model against it. Judge the result
    on the clear-hour metrics -- the all-hours error measures the weather.
    """
    if not (-90.0 <= body.latitude <= 90.0 and -180.0 <= body.longitude <= 180.0):
        raise HTTPException(status_code=400, detail="latitude/longitude out of range")
    if not 6 <= body.hours <= 240:
        raise HTTPException(status_code=400, detail="hours must be between 6 and 240")
    try:
        report = await asyncio.to_thread(
            validate_daylight_live, body.latitude, body.longitude, body.hours
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:            # network failure, upstream outage
        raise HTTPException(
            status_code=502, detail=f"could not reach the weather source: {exc}"
        ) from None
    return report.to_dict()


@router.post("/api/lights/validation/upload")
async def lights_validation_upload(
    request: Request,
    file: UploadFile = File(...),
    quantity: str = Form("luminous_efficacy"),
    x_col: str = Form("x"),
    value_col: str = Form("value"),
    key_col: str = Form(""),
) -> dict[str, Any]:
    """Validate the lighting model against the user's **own** measurements.

    The browser uploads a CSV; the server parses it, replays each point through
    the model, and returns the report with ``data_source == "user-upload"``.
    """
    settings = request.app.state.settings
    max_bytes = int(settings.validation_max_upload_mb * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {settings.validation_max_upload_mb:g} MB limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    suffix = Path(file.filename or "upload").suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        try:
            ref = load_light_upload_csv(
                tmp.name,
                quantity=quantity,
                x_col=x_col,
                value_col=value_col,
                key_col=key_col or None,
            )
            result = validate_light_reference(ref).to_dict()
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"could not parse CSV: {exc}") from None
        result["filename"] = file.filename
        return result
    finally:
        os.unlink(tmp.name)


@router.get("/api/systems")
async def list_systems(request: Request) -> list[dict[str, Any]]:
    """Registered systems (the twin registry), annotated with live status."""
    systems = _enrich_lifecycle(await _store(request).list_systems(), _sim_manager(request))
    live = _live(request)
    live_ids = set(live.system_ids())
    for s in systems:
        s["live"] = s["system_id"] in live_ids
    return systems


@router.post("/api/systems")
async def create_system(body: CreateSystemRequest, request: Request) -> dict[str, Any]:
    """Create a system: a twin-core-run **simulation** or a **real-time** feed.

    A simulation is built from a Component-9 ``spec`` and run by the twin core
    (controllable via start/pause/resume). A real-time system just registers an id
    the twin core will show once an external source publishes to it.
    """
    store = _store(request)
    mgr = _sim_manager(request)
    settings = request.app.state.settings

    if body.source == "simulation":
        if not body.spec:
            raise HTTPException(status_code=400, detail="a simulation needs a 'spec'")
        spec = SystemSpec.from_dict(body.spec)
        if body.system_id:
            spec.system_id = body.system_id
        errors = validate_spec(spec)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})
        run_state = "running" if body.autostart else "stopped"
        await store.create_system(
            spec.system_id, body.name or spec.name, "simulation", spec.to_dict(), run_state
        )
        mgr.create(spec, speed=body.speed or settings.sim_default_speed)
        if body.autostart:
            run_state = await mgr.start(spec.system_id)
        return {"system_id": spec.system_id, "source": "simulation", "run_state": run_state}

    if body.source == "realtime":
        if not body.system_id:
            raise HTTPException(status_code=400, detail="a real-time system needs a 'system_id'")
        await store.create_system(body.system_id, body.name, "realtime", None, "running")
        return {"system_id": body.system_id, "source": "realtime", "run_state": "running"}

    raise HTTPException(status_code=400, detail="source must be 'simulation' or 'realtime'")


async def _control(request: Request, system_id: str, action: str) -> dict[str, Any]:
    """Shared start/pause/resume handler: sims only, else 409."""
    mgr = _sim_manager(request)
    if not mgr.is_managed(system_id):
        raise HTTPException(
            status_code=409,
            detail=f"system '{system_id}' is not a twin-core simulation "
            "(real-time feeds can't be paused/resumed)",
        )
    run_state = await getattr(mgr, action)(system_id)
    await _store(request).set_run_state(system_id, run_state)
    return {"system_id": system_id, "run_state": run_state}


@router.post("/api/systems/{system_id}/start")
async def start_system(system_id: str, request: Request) -> dict[str, Any]:
    return await _control(request, system_id, "start")


@router.post("/api/systems/{system_id}/pause")
async def pause_system(system_id: str, request: Request) -> dict[str, Any]:
    return await _control(request, system_id, "pause")


@router.post("/api/systems/{system_id}/resume")
async def resume_system(system_id: str, request: Request) -> dict[str, Any]:
    return await _control(request, system_id, "resume")


@router.post("/api/systems/{system_id}/faults")
async def inject_fault(
    system_id: str, body: InjectFaultRequest, request: Request
) -> dict[str, Any]:
    """Inject a fault into a **running** simulation, effective on the next timestep.

    Faults were previously spec-time only, so breaking a pack meant rebuilding it
    from t=0. This degrades the pack from wherever it already is -- which is what
    lets an operator tool walk up to a live system and break it. The fault is also appended to the system's spec, so it persists across the
    sim's own duration rollover. Real-time feeds can't be faulted (409).
    """
    mgr = _require_sim(request, system_id)
    try:
        applied = await mgr.inject_fault(
            system_id,
            FaultSpec(
                type=body.type,
                series=body.series,
                parallel=body.parallel,
                params=dict(body.params),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return {"system_id": system_id, "injected": asdict(applied)}


def _require_sim(request: Request, system_id: str):
    """The SimManager, or 409 if this id isn't a twin-core simulation."""
    mgr = _sim_manager(request)
    if not mgr.is_managed(system_id):
        raise HTTPException(
            status_code=409,
            detail=f"system '{system_id}' is not a twin-core simulation "
            "(faults only apply to simulations)",
        )
    return mgr


@router.get("/api/systems/{system_id}/faults")
async def list_faults(system_id: str, request: Request) -> dict[str, Any]:
    """Every fault currently on a simulation, in the order they were applied.

    A fault's position in this list is its handle for ``DELETE .../faults/{index}``.
    """
    mgr = _require_sim(request, system_id)
    return {
        "system_id": system_id,
        "faults": [asdict(f) for f in mgr.faults(system_id)],
    }


@router.delete("/api/systems/{system_id}/faults/{index}")
async def remove_fault(system_id: str, index: int, request: Request) -> dict[str, Any]:
    """Remove one fault by its position -- repair a cell without repairing the pack."""
    mgr = _require_sim(request, system_id)
    try:
        removed = await mgr.remove_fault(system_id, index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"errors": [str(exc)]}) from None
    return {"system_id": system_id, "removed": asdict(removed)}


@router.delete("/api/systems/{system_id}/faults")
async def clear_faults(system_id: str, request: Request) -> dict[str, Any]:
    """Repair a system: drop every injected/declared fault from the running sim."""
    mgr = _require_sim(request, system_id)
    return {"system_id": system_id, "cleared": await mgr.clear_faults(system_id)}


@router.delete("/api/systems/{system_id}")
async def delete_system(system_id: str, request: Request) -> dict[str, Any]:
    """Purge a system: stop its sim (if any), clear retained config, delete history."""
    mgr = _sim_manager(request)
    if mgr.is_managed(system_id):
        await mgr.remove(system_id)
    await _store(request).delete_system(system_id)
    _live(request).remove(system_id)
    _anomaly_live(request).remove(system_id)
    _assessment_live(request).remove(system_id)
    return {"deleted": True, "system_id": system_id}


@router.get("/api/systems/{system_id}/state")
async def system_state(system_id: str, request: Request) -> dict[str, Any]:
    """Latest known telemetry frame -- from memory if live, else from the DB."""
    live = _live(request).get(system_id)
    if live is not None:
        return {"source": "live", **live}

    pack = await _store(request).latest_pack(system_id)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"no telemetry for system '{system_id}'")
    cells = await _store(request).latest_cells(system_id)
    return {"source": "store", "system_id": system_id, "pack": pack, "cells": cells}


@router.get("/api/systems/{system_id}/cells")
async def system_cells(system_id: str, request: Request) -> list[dict[str, Any]]:
    """Latest per-cell telemetry (voltage/current/temp/SoC for every cell)."""
    cells = await _store(request).latest_cells(system_id)
    if not cells:
        raise HTTPException(status_code=404, detail=f"no cell data for system '{system_id}'")
    return cells


@router.get("/api/systems/{system_id}/history")
async def system_history(
    system_id: str,
    request: Request,
    minutes: float = Query(60.0, gt=0, description="look-back window in minutes"),
    bucket_s: Optional[int] = Query(
        None, ge=1, description="downsample bucket size in seconds (omit for raw)"
    ),
) -> dict[str, Any]:
    """Pack-level history over the last ``minutes``, optionally downsampled."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    rows = await _store(request).pack_history(system_id, start, end, bucket_s)
    return {
        "system_id": system_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bucket_s": bucket_s,
        "points": rows,
    }


@router.get("/api/systems/{system_id}/anomaly")
async def system_anomaly(system_id: str, request: Request) -> dict[str, Any]:
    """Latest full anomaly report (per-cell scores) from the live cache."""
    report = _anomaly_live(request).get(system_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"no anomaly data for system '{system_id}'")
    return report


@router.get("/api/systems/{system_id}/anomaly/history")
async def system_anomaly_history(
    system_id: str,
    request: Request,
    minutes: float = Query(60.0, gt=0, description="look-back window in minutes"),
    bucket_s: Optional[int] = Query(None, ge=1, description="downsample bucket size in seconds"),
) -> dict[str, Any]:
    """Anomaly score history (max score per bucket) over the last ``minutes``."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    rows = await _store(request).anomaly_history(system_id, start, end, bucket_s)
    return {"system_id": system_id, "bucket_s": bucket_s, "points": rows}


@router.get("/api/systems/{system_id}/assessment")
async def system_assessment(system_id: str, request: Request) -> dict[str, Any]:
    """Latest full assessment (diagnosis, per-cell SoH, RUL, safety) from cache."""
    report = _assessment_live(request).get(system_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"no assessment for system '{system_id}'")
    return report


@router.get("/api/systems/{system_id}/assessment/history")
async def system_assessment_history(
    system_id: str,
    request: Request,
    minutes: float = Query(60.0, gt=0, description="look-back window in minutes"),
    bucket_s: Optional[int] = Query(None, ge=1, description="downsample bucket size in seconds"),
) -> dict[str, Any]:
    """State-of-health history over the last ``minutes``, optionally downsampled."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    rows = await _store(request).assessment_history(system_id, start, end, bucket_s)
    return {"system_id": system_id, "bucket_s": bucket_s, "points": rows}


@ws_router.websocket("/ws/systems/{system_id}")
async def system_stream(websocket: WebSocket, system_id: str) -> None:
    """Live telemetry stream for one system.

    Sends the current frame immediately on connect (so a new client isn't blank),
    then one message per frame as the ingest loop broadcasts them.
    """
    settings = websocket.app.state.settings
    provided = extract_key(websocket.headers, websocket.query_params)
    if not is_authorized(settings.api_key, provided):
        # 1008 = policy violation. Accept first so the client sees the close code.
        await websocket.accept()
        await websocket.close(code=1008)
        return

    manager: WebSocketManager = websocket.app.state.ws_manager
    live: LatestState = websocket.app.state.live
    anomaly_live: LatestState = websocket.app.state.anomaly_live
    assessment_live: LatestState = websocket.app.state.assessment_live
    await manager.connect(system_id, websocket)
    try:
        current = live.get(system_id)
        if current is not None:
            await websocket.send_json(current)
        current_anomaly = anomaly_live.get(system_id)
        if current_anomaly is not None:
            await websocket.send_json(current_anomaly)
        current_assessment = assessment_live.get(system_id)
        if current_assessment is not None:
            await websocket.send_json(current_assessment)
        while True:
            # We don't expect client messages; this keeps the socket open and
            # detects disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(system_id, websocket)
