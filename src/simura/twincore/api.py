"""HTTP + WebSocket API for the twin core.

REST for state and history; a WebSocket per system for the live stream. Handlers
read shared objects (store, live state, ws manager) off ``app.state``, wired up
in :mod:`simura.twincore.main`.
"""

from __future__ import annotations

import os
import tempfile

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

from ..builder import SpecError, SystemSpec, builder_options, preview, validate_spec
from ..fleet import build_fleet
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
from ..weather import WeatherSample
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


class CreateSystemRequest(BaseModel):
    """Body for POST /api/systems (create a simulation or register a real-time feed)."""

    source: str = "simulation"          # "simulation" | "realtime"
    system_id: Optional[str] = None
    name: Optional[str] = None
    spec: Optional[dict[str, Any]] = None
    speed: Optional[float] = None
    autostart: bool = True


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
    """Solve a multi-node wire network (nodes + segments)."""
    try:
        result = build_network(body).solve()
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
