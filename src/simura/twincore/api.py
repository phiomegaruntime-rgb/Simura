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
from ..space import (
    FloorPlan,
    PLAN_PARAMS,
    PLAN_TYPES,
    PlanError,
    ambient_for,
    build_provider as build_plan_provider,
    detect_format,
    lighting_targets,
    summary as plan_summary,
    task_grid,
    weather_spec as plan_weather_spec,
)
from ..space.occupancy import OCCUPANCY
from ..space.routing import DEFAULT_SLACK_FRAC, DEFAULT_TRAY_HEIGHT_M, route as route_cable
from ..explain import (
    coverage,
    define,
    get_card,
    list_cards,
    list_domains,
    list_terms,
    render_all,
)
from ..explain.battery import (
    explain_frame as explain_battery_frame,
    explain_pack as explain_battery_pack,
    imbalance_from_pack as explain_battery_imbalance,
)
from ..explain.levels import DEFAULT_LEVEL, LEVEL_INFO
from ..explain.lights import (
    efficacy as explain_lamp_efficacy,
    explain_installation as explain_light_installation,
    output as explain_lamp_output,
)
from ..explain.domains import DEFAULT_DOMAIN
from ..explain.wires import explain_run as explain_wire_run
from ..fleet import build_fleet
from ..library import (
    KINDS as LIBRARY_KINDS,
    Decision as LibraryDecision,
    Entry as LibraryEntry,
    InMemoryLibrary,
    LibraryError,
    Note as LibraryNote,
    bundled_entries,
    change_coverage,
    diff_specs,
    explain_changes,
    fork as fork_entry,
    SiteError,
    apply_site,
    new_entry as new_library_entry,
    promote as promote_entry,
    restore_site,
    revise as revise_entry,
    summarize as summarize_changes,
)
from ..lights import (
    LightSpec,
    build_layout,
    build_light,
    catalog_options as light_catalog_options,
    evaluate_installation,
    recommend_lamp,
)
from ..lights.lamp import Light
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
    build_wire,
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


# ---------------------------------------------------------------------------
# Space -- a building imported as a 2D layout (Component 20)
# ---------------------------------------------------------------------------
#
# Every route here is **pure compute**, like /api/wires/* and /api/lights/*: no
# broker, no database, nothing stored server-side. The client holds the plan and
# posts it back, which is what makes a floor plan an artifact rather than a
# session -- it can be saved to a file, checked into a repository, carried in a
# library entry, or kept in the browser, and none of those need this server to
# still be running.
#
# The one thing that cannot work that way is the import itself, because it needs
# the file. So `POST /api/space/import` takes an upload and hands back the plan;
# after that the server is out of the loop.


def _plan_from_body(body: dict[str, Any]) -> FloorPlan:
    """The plan a request is about: an inline document, or a spec to build one."""
    payload = body.get("plan")
    if isinstance(payload, dict) and ("spaces" in payload or "walls" in payload):
        try:
            return FloorPlan.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"not a floor plan: {exc}"
            ) from None

    spec = body.get("space") or body.get("source")
    if isinstance(spec, dict):
        try:
            provider = build_plan_provider(
                {"type": spec.get("type", "none"), **(spec.get("params") or {})}
            )
        except PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if provider is None:
            raise HTTPException(status_code=400, detail="no building in this request")
        try:
            return provider.plan()
        except PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    raise HTTPException(
        status_code=400,
        detail="send a 'plan' document or a 'space' spec of {type, params}",
    )


@router.get("/api/space/options")
async def space_options() -> dict[str, Any]:
    """What kinds of building file can be imported, and what each one takes.

    Serves the import form the same way ``/api/builder/options`` serves the
    builder form: the list lives in the code that implements it, so a new format
    is a one-file change rather than two lists that drift.
    """
    from ..space.providers import ifc_full_available

    return {
        "types": list(PLAN_TYPES),
        "params": PLAN_PARAMS,
        "occupancies": list(OCCUPANCY),
        "ifc_full_available": ifc_full_available(),
        "routing_defaults": {
            "tray_height_m": DEFAULT_TRAY_HEIGHT_M,
            "slack_frac": DEFAULT_SLACK_FRAC,
        },
    }


@router.post("/api/space/import")
async def space_import(
    request: Request,
    file: UploadFile = File(...),
    format: str = Form(""),
    wall_layers: str = Form(""),
    room_layers: str = Form(""),
    scale: float = Form(0.0),
) -> dict[str, Any]:
    """Import a building file and return the floor plan it becomes.

    The format is detected from the filename and then from the contents, so a
    mislabelled export still lands; pass ``format`` to override. The DXF options
    are here because a drawing with an unusual layer convention is otherwise
    unimportable, and telling the importer the convention is the honest fix.

    The response carries the plan **and** its fidelity record. A caller showing
    the plan without showing what was assumed is showing half the answer.
    """
    settings = request.app.state.settings
    max_bytes = int(getattr(settings, "validation_max_upload_mb", 32) * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {max_bytes / 1024 / 1024:g} MB limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    filename = file.filename or "upload"
    try:
        kind = format or detect_format(filename, data)
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    params: dict[str, Any] = {"data": data, "name": filename, "path": filename}
    if kind == "dxf":
        if wall_layers:
            params["wall_layers"] = wall_layers
        if room_layers:
            params["room_layers"] = room_layers
        if scale:
            params["scale"] = scale
    if kind == "ifc_full":
        # ifcopenshell reads from disk, so an upload has to land somewhere first.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
        try:
            tmp.write(data)
            tmp.close()
            params = {"path": tmp.name, "name": filename}
            plan = await asyncio.to_thread(_build_plan, kind, params)
        finally:
            os.unlink(tmp.name)
        return {"plan": plan.to_dict(), "summary": plan_summary(plan)}

    # Parsing a large model is CPU-bound; keep it off the event loop.
    plan = await asyncio.to_thread(_build_plan, kind, params)
    return {"plan": plan.to_dict(), "summary": plan_summary(plan)}


def _build_plan(kind: str, params: dict[str, Any]) -> FloorPlan:
    try:
        provider = build_plan_provider({"type": kind, **params})
        if provider is None:
            raise PlanError(f"nothing to import as '{kind}'")
        return provider.plan()
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=400, detail=f"could not read the building: {exc}"
        ) from None


@router.post("/api/space/plan")
async def space_plan(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Build a plan from a spec and return the **document**, not a rollup.

    The counterpart of ``/api/space/import`` for a source that is not an upload:
    a plan already on the server's disk, or the generated example building. The
    client keeps what comes back and posts it to every other route, so this is
    the only call it makes about that building.

    ``/api/space/summary`` answers the same request with a rollup instead, for a
    caller that wants the headline without carrying the geometry.
    """
    plan = _plan_from_body(body)
    return {"plan": plan.to_dict(), "summary": plan_summary(plan)}


@router.post("/api/space/summary")
async def space_summary(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The rollup for a plan: rooms, area, where it is, and what was assumed."""
    return plan_summary(_plan_from_body(body))


@router.post("/api/space/lighting")
async def space_lighting(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Every room in the plan as a lighting-design problem, optionally solved.

    With ``recommend: true`` each room is run through
    :func:`simura.lights.planning.recommend_lamp` and the building is totalled --
    which is the coupling that scales: one import gives a per-room design for a
    whole building and the installed power that implies.

    A room that cannot honestly be designed is still returned, with its reason,
    so the rollup reports "38 of 41 rooms designed" rather than silently covering
    38.
    """
    plan = _plan_from_body(body)
    level_id = body.get("level_id") or None
    targets = lighting_targets(plan, level_id=level_id)
    out: dict[str, Any] = {
        "plan_id": plan.id,
        "targets": [t.to_dict() for t in targets],
        "undesignable": sum(1 for t in targets if not t.designable),
    }

    if not body.get("recommend"):
        return out

    from ..lights.planning import recommend_lamp

    family = body.get("family") or None
    rooms: list[dict[str, Any]] = []
    total_w = 0.0
    total_area = 0.0
    for target in targets:
        result = await asyncio.to_thread(
            recommend_lamp, family=family, **target.kwargs()
        )
        assessment = result.assessment
        if assessment is not None:
            total_w += assessment.power_w
            total_area += target.area_m2
        rooms.append(
            {
                "space_id": target.space_id,
                "name": target.name,
                "target": target.to_dict(),
                "recommendation": result.to_dict(),
            }
        )

    out["rooms"] = rooms
    out["building"] = {
        "power_w": round(total_w, 1),
        "floor_area_m2": round(total_area, 1),
        "power_density_w_per_m2": round(total_w / total_area, 2) if total_area else 0.0,
        "designed": len(rooms),
    }
    return out


@router.post("/api/space/layout")
async def space_layout(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Solve an illuminance field over **one room's real outline**.

    The difference from ``/api/lights/layout`` is the shape. That route lights a
    rectangle; this one lights the room the building actually has, masking every
    grid point that falls outside it. In an L-shaped room the two disagree
    substantially, and this one is right: a point in the notch is not dark floor,
    it is not floor.

    Luminaire positions are in **plan coordinates**, the same frame the room's
    polygon is in, so a fitting can be placed by clicking the plan.
    """
    plan = _plan_from_body(body)
    space_id = str(body.get("space_id", ""))
    space = plan.space(space_id)
    if space is None:
        raise HTTPException(status_code=404, detail=f"no room '{space_id}' in this plan")

    from ..lights.config import build_fault as build_light_fault
    from ..lights.lamp import LightSpec
    from ..lights.layout import Layout

    length, width, _ = space.extents()
    workplane = float(body.get("workplane_height_m", 0.8))
    layout = Layout(
        length_m=length,
        width_m=width,
        workplane_height_m=workplane,
        grid_n=int(body.get("grid_n", 11)),
        outline=list(space.polygon),
    )
    for i, item in enumerate(body.get("luminaires") or []):
        layout.add(
            id=str(item.get("id") or f"L{i + 1}"),
            x_m=float(item.get("x_m", 0.0)),
            y_m=float(item.get("y_m", 0.0)),
            height_m=float(item.get("height_m", space.height_m)),
            spec=LightSpec.from_dict(item.get("lamp") or {"lamp_type": "led-15-e27"}),
            drive=float(item.get("drive", 1.0)),
            faults=[build_light_fault(f) for f in (item.get("faults") or [])],
        )

    weather = body.get("weather")
    sample = None
    if isinstance(weather, dict) and weather:
        from ..weather import WeatherSample

        sample = WeatherSample.from_dict({"timestamp": time.time(), **weather})

    try:
        result = layout.solve(
            elapsed_s=float(body.get("elapsed_s", 0.0)),
            target_lux=float(body.get("target_lux", 0.0)),
            min_uniformity=float(body.get("min_uniformity", 0.0)),
            weather=sample,
            ceiling_reflectance=space.ceiling_reflectance,
            wall_reflectance=space.wall_reflectance,
            floor_reflectance=space.floor_reflectance,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "space_id": space.id,
        "name": space.name,
        "rectangular": space.rectangular(),
        "inferred": list(space.inferred),
        "layout": result.to_dict(),
    }


@router.post("/api/space/route")
async def space_route(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Trace a cable run through the building, and price it as a conductor.

    Returns the run with its legs visible, and -- when a ``wire_type`` is given --
    the ``simura.wires`` assessment of that run at that length, derated for the
    hottest room it passes through. A conductor is rated by its worst metre, not
    its average, which is the reason a route has to know which rooms it crossed.
    """
    plan = _plan_from_body(body)

    def point(value: Any, name: str) -> tuple[float, float]:
        if isinstance(value, dict):
            return (float(value.get("x_m", 0.0)), float(value.get("y_m", 0.0)))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (float(value[0]), float(value[1]))
        raise HTTPException(
            status_code=400, detail=f"'{name}' must be [x, y] in metres"
        )

    result = route_cable(
        plan,
        point(body.get("start"), "start"),
        point(body.get("end"), "end"),
        start_level=body.get("start_level") or None,
        end_level=body.get("end_level") or None,
        tray_height_m=float(body.get("tray_height_m", DEFAULT_TRAY_HEIGHT_M)),
        equipment_height_m=float(body.get("equipment_height_m", 0.0)),
        slack_frac=float(body.get("slack_frac", DEFAULT_SLACK_FRAC)),
    )

    out: dict[str, Any] = {"plan_id": plan.id, "route": result.to_dict()}

    sample = None
    weather = body.get("weather")
    if isinstance(weather, dict) and weather:
        from ..weather import WeatherSample

        sample = WeatherSample.from_dict({"timestamp": time.time(), **weather})
    ambient = result.hottest_ambient(plan, sample)
    out["hottest_ambient_c"] = ambient

    wire_type = body.get("wire_type")
    if wire_type:
        from ..wires import WireSpec, evaluate_run

        spec = WireSpec(**result.wire_kwargs(str(wire_type), ambient or 25.0))
        try:
            assessment = evaluate_run(
                spec,
                current_a=float(body.get("current_a", 0.0)),
                system_voltage_v=float(body.get("system_voltage_v", 48.0)),
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        out["wire"] = assessment.to_dict()
        out["wire_spec"] = result.wire_kwargs(str(wire_type), ambient or 25.0)

    return out


@router.post("/api/space/ambient")
async def space_ambient(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """What the environment is in one room, and **why** it is that.

    The battery coupling in one call: a conditioned room holds its setpoint and
    excludes the sun; an unconditioned one takes the weather in full; a room the
    model says nothing about is treated as outdoor and says so. The ``basis`` is
    the sentence to show next to the number.
    """
    plan = _plan_from_body(body)
    space_id = str(body.get("space_id", ""))

    sample = None
    weather = body.get("weather")
    if isinstance(weather, dict) and weather:
        from ..weather import WeatherSample

        sample = WeatherSample.from_dict({"timestamp": time.time(), **weather})

    context = ambient_for(
        plan,
        space_id,
        sample,
        indoor_setpoint_c=float(body.get("indoor_setpoint_c", 21.0)),
    )
    if context is None:
        raise HTTPException(status_code=404, detail=f"no room '{space_id}' in this plan")
    return {"plan_id": plan.id, "space": context.to_dict()}


@router.post("/api/space/at")
async def space_at_point(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Which room a point falls in -- how a placed thing learns where it stands.

    The 3D world's whole use of this component: a rack is put down somewhere, and
    this says which room that is, which is what gives it an ambient and a name
    without anybody typing one. ``{"space": null}`` when the point is outdoors or
    outside the model, which is a real answer and not an error.
    """
    plan = _plan_from_body(body)
    x = float(body.get("x_m", 0.0))
    y = float(body.get("y_m", 0.0))
    space = plan.space_at((x, y), body.get("level_id") or None)
    return {
        "plan_id": plan.id,
        "space": space.to_dict() if space is not None else None,
    }


@router.post("/api/space/weather")
async def space_weather(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The weather source the model's own coordinates imply.

    The join the whole component was built around: a georeferenced model already
    knows the latitude and longitude ``simura.weather`` needs, so importing a
    building configures the sky over it with nothing typed in. ``null`` when the
    model carries no coordinates -- a fact about the file, not a failure, and the
    caller keeps whatever weather it had rather than being handed 0, 0.
    """
    plan = _plan_from_body(body)
    spec = plan_weather_spec(plan, mode=str(body.get("mode", "forecast")))
    if spec is None:
        return {"plan_id": plan.id, "weather": None, "located": False}
    kind = spec.pop("type")
    return {
        "plan_id": plan.id,
        "located": True,
        "weather": {"type": kind, "params": spec},
        "north_deg": plan.georeference.north_deg,
    }


@router.post("/api/space/grid")
async def space_grid(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """The task-area sample points inside one room, for a client-side field."""
    plan = _plan_from_body(body)
    points = task_grid(
        plan,
        str(body.get("space_id", "")),
        spacing_m=float(body.get("spacing_m", 0.5)),
        inset_m=body.get("inset_m"),
    )
    return {"space_id": body.get("space_id"), "points": [[x, y] for x, y in points]}


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


# ==========================================================================
# Component 16 -- the "get familiar" layer (simura.explain)
#
# Two kinds of route. The reference ones (cards, glossary, lenses, coverage)
# are static and cacheable. The explaining ones decompose something: either a
# payload the caller supplies (pure compute, no DB, no broker -- the same shape
# the wires and lights routes already have), or the live twin, which is the one
# route here that reaches into running state.
# ==========================================================================


@router.get("/api/explain/cards")
async def explain_cards(
    component: str = Query("", description="batteries | wires | lights | twin"),
) -> list[dict[str, Any]]:
    """Plain-language model cards, optionally narrowed to one component."""
    try:
        cards = list_cards(component or None)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return [c.to_dict() for c in cards]


@router.get("/api/explain/cards/{card_id}")
async def explain_card(card_id: str) -> dict[str, Any]:
    try:
        return get_card(card_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/api/explain/glossary")
async def explain_glossary(
    term: str = Query("", description="look up one term (or any of its aliases)"),
) -> Any:
    """The whole glossary, or one entry when ``term`` is given."""
    if term:
        entry = define(term)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no glossary entry for {term!r}")
        return entry.to_dict()
    return [e.to_dict() for e in list_terms()]


@router.get("/api/explain/lenses")
async def explain_lenses() -> dict[str, Any]:
    """The two knobs a reader has: whose vocabulary, and how deep.

    Served together because a picker needs both, and one round trip is the
    difference between the control appearing with the page and appearing after
    it.
    """
    return {
        "domains": [d.to_dict() for d in list_domains()],
        "levels": [lv.to_dict() for lv in LEVEL_INFO],
        "default_domain": DEFAULT_DOMAIN,
        "default_level": DEFAULT_LEVEL,
    }


@router.get("/api/explain/coverage")
async def explain_coverage() -> dict[str, Any]:
    """Which parameters in the code have a plain-language card, and which do not.

    Exposed deliberately. The claim this component makes is that the prose
    cannot drift from the model, and a claim like that should be checkable from
    outside rather than only in a test file.
    """
    return coverage()


def _rendered(attributions, domain: str | None, level: str | None) -> dict[str, Any]:
    """Render a list of attributions, or 400 on a bad lens."""
    try:
        explanations = render_all(attributions, domain or None, level or None)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "domain": explanations[0].domain if explanations else (domain or DEFAULT_DOMAIN),
        "level": explanations[0].level if explanations else (level or DEFAULT_LEVEL),
        "explanations": [e.to_dict() for e in explanations],
        "attributions": [a.to_dict() for a in attributions],
    }


@router.post("/api/explain/battery")
async def explain_battery(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explain a telemetry frame you already have.

    ``{"frame": {...PackTelemetry}, "spec": {...SystemSpec}, "series"?, "parallel"?,
    "domain"?, "level"?}``. Pure compute -- nothing here touches the store or the
    broker, so it works against a frame from anywhere, including one a client
    captured minutes ago.
    """
    frame = body.get("frame")
    if not isinstance(frame, dict) or not frame.get("cells"):
        raise HTTPException(status_code=400, detail="body needs a 'frame' with cells")
    try:
        spec = SystemSpec.from_dict(body.get("spec") or {})
        atts = explain_battery_frame(
            frame, spec, body.get("series"), body.get("parallel")
        )
    except (IndexError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _rendered(atts, body.get("domain"), body.get("level"))


@router.post("/api/explain/wires")
async def explain_wires_route(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explain a wire run.

    Takes the same body as :func:`wires_evaluate` -- ``{spec: {...WireSpec},
    current_a, system_voltage_v?, round_trip?, ...}`` -- so a caller that has
    just run the check can ask for the explanation of it unchanged.

    ``at_temp_c`` pins the conductor temperature instead of letting this route
    re-derive it. A caller that solved a whole network already has a temperature
    that accounts for the rest of the circuit, the weather and any faults;
    without this the explanation would sit next to a number it quietly disagrees
    with.
    """
    try:
        spec = build_wire(body.get("spec", body.get("wire", {})))
        atts = explain_wire_run(
            spec,
            current_a=float(body.get("current_a", 0.0)),
            system_voltage_v=(
                float(body["system_voltage_v"]) if body.get("system_voltage_v") else None
            ),
            round_trip=bool(body.get("round_trip", False)),
            ambient_c=(float(body["ambient_c"]) if body.get("ambient_c") is not None else None),
            solar_w=float(body.get("solar_w", 0.0)),
            at_temp_c=(float(body["at_temp_c"]) if body.get("at_temp_c") is not None else None),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _rendered(atts, body.get("domain"), body.get("level"))


@router.post("/api/explain/lamp")
async def explain_lamp_route(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explain one luminaire running on the supply it has actually got.

    Takes one entry of :func:`lights_operate`'s body -- ``{spec: {...LightSpec},
    supply_voltage_v?, drive?, ambient_c?, elapsed_s?, faults?, weather?}`` --
    because that is the shape a caller solving a *site* already has, as opposed
    to :func:`explain_lights_route`, which explains a *room* designed by the
    lumen method.

    Two attributions come back. ``lamp.output`` answers the question a fitting
    in a real installation poses -- it is rated for so many lumens and is
    producing fewer, so which of dimming, supply voltage, ambient, wear and
    faults is responsible -- by re-running the lamp model with one condition
    changed at a time. ``lamp.efficacy`` answers the other half: of the light it
    is producing, how much did each watt buy.
    """
    from ..lights.config import build_fault as build_light_fault
    from ..lights.faults import accumulate as accumulate_light_faults
    from ..lights.environment import LightEnvironmentCoupling

    try:
        spec = build_light(body.get("spec", body.get("lamp", {})))
        light = Light(spec)
        light.time_lit_s = 1e9          # a settled fitting, not a warming one

        ambient_c = body.get("ambient_c")
        weather = _weather_from_body(body)
        if weather is not None and ambient_c is None:
            ambient_c = LightEnvironmentCoupling(
                **(body.get("coupling") or {})
            ).apply(weather).ambient_c
        supply_v = float(body.get("supply_voltage_v", light.supply_voltage_v))
        drive = float(body.get("drive", 1.0))
        elapsed_s = float(body.get("elapsed_s", 0.0))
        faults = [build_light_fault(f) for f in body.get("faults", [])]

        effect = accumulate_light_faults(faults, light, elapsed_s) if faults else None
        point = light.at_supply(
            supply_v,
            drive=drive,
            ambient_c=ambient_c,
            effect=effect,
        ).point
        atts = [
            explain_lamp_output(
                spec,
                supply_voltage_v=supply_v,
                drive=drive,
                ambient_c=ambient_c,
                faults=faults,
                elapsed_s=elapsed_s,
            ),
            explain_lamp_efficacy(point),
        ]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _rendered(atts, body.get("domain"), body.get("level"))


@router.post("/api/explain/lights")
async def explain_lights_route(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explain a lighting design.

    Takes the same body as :func:`lights_evaluate` -- ``{spec: {...LightSpec},
    n_luminaires, length_m, width_m, ...}`` -- so a caller that has just run the
    check can ask for the explanation of it unchanged.
    """
    try:
        spec = build_light(body.get("spec", body.get("lamp", {})))
        assessment = evaluate_installation(
            spec,
            n_luminaires=int(body.get("n_luminaires", 1)),
            length_m=float(body.get("length_m", 8.0)),
            width_m=float(body.get("width_m", 6.0)),
            mounting_height_m=float(body.get("mounting_height_m", 2.5)),
            task=str(body.get("task", "office")),
            target_lux=(float(body["target_lux"]) if body.get("target_lux") else None),
            maintenance_hours=float(body.get("maintenance_hours", 0.0)),
            dirt_frac=float(body.get("dirt_frac", 0.1)),
        )
        lamp = Light(spec)
        lamp.time_lit_s = 1e9          # judge a warmed-up lamp, not a cold one
        atts = explain_light_installation(assessment, point=lamp.operating_point())
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _rendered(atts, body.get("domain"), body.get("level"))


@router.get("/api/systems/{system_id}/explain")
async def explain_system(
    system_id: str,
    request: Request,
    domain: str = Query("", description="whose vocabulary to use"),
    level: str = Query("", description="overview | working | physics"),
    series: int | None = Query(None, description="which cell; defaults to the hottest"),
    parallel: int | None = Query(None),
) -> dict[str, Any]:
    """Explain what a live twin is doing and why, grounded in its own model.

    Two paths, and the response says which one it took. When the twin core is
    *running* the simulation it can read the solver's state directly, including
    the fault and weather coefficients telemetry cannot carry -- that answer is
    exact. For a real-time feed, or a simulation that is registered but stopped,
    the operating point is inferred from the latest frame instead, and every
    attribution comes back marked inexact with the reason attached.
    """
    mgr = _sim_manager(request)
    simulator = mgr.simulator(system_id)

    if simulator is not None:
        atts = list(explain_battery_pack(simulator, series, parallel))
        source = "model"
        if simulator.pack.shape[0] * simulator.pack.shape[1] >= 2:
            atts.append(explain_battery_imbalance(simulator.pack))
    else:
        envelope = _live(request).get(system_id)
        frame = (envelope or {}).get("telemetry")
        if not frame:
            raise HTTPException(
                status_code=404, detail=f"no live telemetry for system '{system_id}'"
            )
        stored = await _store(request).get_system(system_id)
        spec = SystemSpec.from_dict((stored or {}).get("spec") or {})
        try:
            atts = explain_battery_frame(frame, spec, series, parallel)
        except (IndexError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        source = "telemetry"

    out = _rendered(atts, domain or None, level or None)
    out["system_id"] = system_id
    out["source"] = source
    out["exact"] = all(a.exact for a in atts)
    return out


# ==========================================================================
# Component 17: the system library -- memory that survives the project
# ==========================================================================
#
# These routes are persistence and HTTP only. Every rule -- what a fork is, when
# a reason is required, how a diff reads, where a lineage goes -- lives in
# ``simura.library`` and is applied here by loading the stored rows into that
# package's own in-memory library, calling its functions, and writing the result
# back. The twin core does not get a second, subtly different idea of what a
# saved system is.


class SaveEntryRequest(BaseModel):
    """Body for POST /api/library -- save a system into the library."""

    spec: dict[str, Any]
    name: Optional[str] = None
    kind: str = "system"
    summary: str = ""
    author: str = ""
    tags: list[str] = []
    validated: bool = False
    notes: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []


class ForkRequest(BaseModel):
    """Body for POST /api/library/{id}/fork. ``because`` is required by the model."""

    name: str
    because: str
    spec: Optional[dict[str, Any]] = None
    author: str = ""
    summary: str = ""
    tags: Optional[list[str]] = None
    rejected: list[str] = []


class ReviseRequest(BaseModel):
    """Body for POST /api/library/{id}/revise -- the next version of one design."""

    spec: dict[str, Any]
    because: str
    author: str = ""
    name: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    rejected: list[str] = []


class PromoteRequest(BaseModel):
    """Body for POST /api/library/{id}/promote -- make a system a starting point."""

    because: str
    name: Optional[str] = None
    author: str = ""
    summary: Optional[str] = None
    tags: Optional[list[str]] = None


class NoteRequest(BaseModel):
    text: str
    kind: str = "note"  # note | gotcha | result
    author: str = ""


class DecisionRequest(BaseModel):
    question: str
    because: str
    choice: str = ""
    params: list[str] = []
    rejected: list[str] = []
    author: str = ""


class InstantiateRequest(BaseModel):
    """Body for POST /api/library/{id}/instantiate -- run a saved system.

    ``site`` is how a caller with a place of its own -- the 3D sandbox, which
    stands a rack in the world's weather and wires it to the world's loads --
    runs somebody else's design without pretending its weather is part of that
    design. Only the fields in :data:`simura.library.SITE_FIELDS` are accepted;
    anything else is a 400, because the whole point of instantiating *this entry*
    is that what runs is the design the entry records.
    """

    system_id: Optional[str] = None
    name: Optional[str] = None
    speed: Optional[float] = None
    autostart: bool = True
    site: dict[str, Any] = {}


class CaptureRequest(BaseModel):
    """Body for POST /api/library/capture -- save a *running* system.

    ``because`` is only required when the system was started from a library
    entry and has since drifted from it: that capture is the next version of a
    design somebody else may be reading, and a new version with no reason is the
    thing this component exists to stop.
    """

    system_id: str
    name: Optional[str] = None
    because: str = ""
    summary: str = ""
    author: str = ""
    tags: list[str] = []
    notes: list[dict[str, Any]] = []
    site: list[str] = []
    """Which spec fields the caller supplied itself (see the instantiate route).
    They are taken back off before the entry is recorded, so a system captured
    out of a sandbox differs from its parent by what somebody *did* to it rather
    than by where it was standing."""


async def _library(request: Request) -> InMemoryLibrary:
    """The stored library, as the library package's own object.

    Loaded whole. Lineage is a walk over entries, so a page of them would answer
    "how did this get here" with part of the story -- and a library is documents
    somebody wrote, which is not a table that grows the way telemetry does.
    """
    return InMemoryLibrary.from_dicts(await _store(request).library_list())


async def _persist(request: Request, entry: LibraryEntry) -> dict[str, Any]:
    """Write a newly-built entry, and return it with its context attached."""
    await _store(request).library_save(entry.to_dict())
    return await _entry_detail(request, entry.entry_id)


def _row(library: InMemoryLibrary, entry: LibraryEntry) -> dict[str, Any]:
    """A list row: the entry, plus the two things a list has to show.

    ``change_summary`` is computed from the specs on every read rather than
    stored, which is the whole design decision in one field: a row can say how
    it differs from its parent and be right about it a year later.
    """
    parent = library.get(entry.parent_id) if entry.parent_id else None
    out = entry.to_dict()
    out["child_count"] = len(library.children(entry.entry_id))
    out["change_summary"] = (
        summarize_changes(diff_specs(parent.spec, entry.spec)) if parent else ""
    )
    return out


async def _entry_detail(request: Request, entry_id: str) -> dict[str, Any]:
    library = await _library(request)
    entry = library.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    parent = library.get(entry.parent_id) if entry.parent_id else None
    changes = diff_specs(parent.spec, entry.spec) if parent else []
    return {
        "entry": entry.to_dict(),
        "parent": parent.to_dict() if parent else None,
        # What changed from the parent, each paired with the reason that
        # accounts for it -- or with nothing, which is itself the finding.
        "changes": [c.to_dict() for c in explain_changes(changes, entry.decisions)],
        "coverage": change_coverage(changes, entry.decisions),
        "ancestry": [e.to_dict() for e in library.ancestry(entry_id)],
        "children": [_row(library, c) for c in library.children(entry_id)],
        "inherited": library.inherited_context(entry_id),
    }


@router.get("/api/library")
async def library_list_entries(
    request: Request,
    kind: str = Query("", description="system | template"),
    tag: str = Query(""),
    q: str = Query("", description="search names, notes and reasons"),
) -> dict[str, Any]:
    """The library: saved systems, newest lineage context included."""
    if kind and kind not in LIBRARY_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {LIBRARY_KINDS}")
    library = await _library(request)
    entries = library.list(kind=kind or None, tag=tag or None, query=q)
    return {
        "entries": [_row(library, e) for e in entries],
        "summary": library.summary(),
    }


@router.get("/api/library/tree")
async def library_tree(request: Request) -> list[dict[str, Any]]:
    """The whole library as lineage trees, one per root."""
    return (await _library(request)).tree()


@router.post("/api/library/diff")
async def library_diff(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Diff two specs. Pure compute -- no library, no database.

    Takes the same spec shape the builder and ``POST /api/systems`` take, so the
    dashboard can show what a form edit would change before anything is saved.
    """
    changes = diff_specs(body.get("before") or {}, body.get("after") or {})
    return {
        "changes": [c.to_dict() for c in changes],
        "summary": summarize_changes(changes),
        "count": len(changes),
    }


@router.post("/api/library/seed")
async def library_seed(request: Request) -> dict[str, Any]:
    """Add the bundled starter systems that are not already present."""
    store = _store(request)
    existing = {row["entry_id"] for row in await store.library_list()}
    added = [e for e in bundled_entries() if e.entry_id not in existing]
    for entry in added:
        await store.library_save(entry.to_dict())
    return {"added": [e.entry_id for e in added]}


@router.post("/api/library/capture")
async def library_capture(body: CaptureRequest, request: Request) -> dict[str, Any]:
    """Save a registered system into the library, with where it came from.

    If the system was started from a library entry, this is filed as the *next
    version* of that entry rather than as a new root: the loop from library to
    running twin and back is the one that makes the library accumulate instead
    of collecting unrelated snapshots. A drifted system captured this way needs
    a reason, exactly as any other revision does.
    """
    stored = await _store(request).get_system(body.system_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"no system '{body.system_id}'")
    spec = stored.get("spec")
    if not spec:
        raise HTTPException(
            status_code=409,
            detail=f"system '{body.system_id}' has no spec to save "
            "(real-time feeds are a stream, not a design)",
        )

    library = await _library(request)
    origin = library.get(stored.get("library_entry_id")) if stored.get("library_entry_id") else None
    notes = [LibraryNote.from_dict(n) for n in body.notes]
    try:
        # The caller's own site comes back off first: a rack captured out of the
        # world should differ from the design it came from by what somebody did
        # to it, not by the weather it happened to be standing in.
        spec = restore_site(spec, origin.spec if origin else None, body.site)
        if origin is not None:
            if not diff_specs(origin.spec, spec):
                # Nothing has changed, so there is no new version to record.
                return await _entry_detail(request, origin.entry_id)
            entry = revise_entry(
                origin,
                spec,
                because=body.because,
                author=body.author,
                name=body.name or origin.name,
                summary=body.summary or None,
                tags=body.tags or None,
            )
        else:
            entry = new_library_entry(
                spec,
                name=body.name or stored.get("name") or body.system_id,
                source="twin",
                source_system_id=body.system_id,
                author=body.author,
                summary=body.summary,
                tags=body.tags,
            )
        for note in notes:
            entry = entry.with_note(note)
    except SiteError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None

    await _store(request).library_save(entry.to_dict())
    await _store(request).create_system(
        body.system_id,
        stored.get("name"),
        stored.get("source") or "simulation",
        spec,
        stored.get("run_state") or "running",
        entry.entry_id,
    )
    return await _entry_detail(request, entry.entry_id)


@router.get("/api/library/{entry_id}")
async def library_get_entry(entry_id: str, request: Request) -> dict[str, Any]:
    """One entry, with its lineage, its diff from its parent, and what it inherits."""
    return await _entry_detail(request, entry_id)


@router.get("/api/library/{entry_id}/trace")
async def library_trace(entry_id: str, request: Request) -> dict[str, Any]:
    """How this system got here: every step from the root, and the reason for it."""
    library = await _library(request)
    if library.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    return library.trace(entry_id)


@router.post("/api/library")
async def library_save_entry(body: SaveEntryRequest, request: Request) -> dict[str, Any]:
    """Save a system into the library as a new root entry."""
    try:
        entry = new_library_entry(
            body.spec,
            name=body.name,
            kind=body.kind,
            author=body.author,
            summary=body.summary,
            tags=body.tags,
            validated=body.validated,
            notes=[LibraryNote.from_dict(n) for n in body.notes],
            decisions=[LibraryDecision.from_dict(d) for d in body.decisions],
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return await _persist(request, entry)


@router.post("/api/library/{entry_id}/fork")
async def library_fork(entry_id: str, body: ForkRequest, request: Request) -> dict[str, Any]:
    """Start a new system from an existing one. A fork without a reason is a 400."""
    library = await _library(request)
    parent = library.get(entry_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    try:
        entry = fork_entry(
            parent,
            body.spec,
            name=body.name,
            because=body.because,
            author=body.author,
            summary=body.summary,
            tags=body.tags,
            rejected=body.rejected,
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return await _persist(request, entry)


@router.post("/api/library/{entry_id}/revise")
async def library_revise_entry(
    entry_id: str, body: ReviseRequest, request: Request
) -> dict[str, Any]:
    """The next version of the same design. A revision without a reason is a 400."""
    library = await _library(request)
    parent = library.get(entry_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    try:
        entry = revise_entry(
            parent,
            body.spec,
            because=body.because,
            author=body.author,
            name=body.name,
            summary=body.summary,
            tags=body.tags,
            rejected=body.rejected,
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return await _persist(request, entry)


@router.post("/api/library/{entry_id}/promote")
async def library_promote(entry_id: str, body: PromoteRequest, request: Request) -> dict[str, Any]:
    """Promote a system into a template, carrying its notes and reasons with it."""
    library = await _library(request)
    entry = library.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    try:
        template = promote_entry(
            entry,
            because=body.because,
            name=body.name,
            author=body.author,
            summary=body.summary,
            tags=body.tags,
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    return await _persist(request, template)


@router.post("/api/library/{entry_id}/notes")
async def library_add_note(entry_id: str, body: NoteRequest, request: Request) -> dict[str, Any]:
    """Leave what you learned on the system you learned it on."""
    library = await _library(request)
    if library.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="a note needs some text")
    await _store(request).library_add_note(
        entry_id, LibraryNote(text=body.text, kind=body.kind, author=body.author).to_dict()
    )
    return await _entry_detail(request, entry_id)


@router.post("/api/library/{entry_id}/decisions")
async def library_add_decision(
    entry_id: str, body: DecisionRequest, request: Request
) -> dict[str, Any]:
    """Record why a number is the number it is, bound to the fields it justifies.

    ``params`` is what makes this more than a comment: a decision bound to the
    spec keys it covers is what stops those keys being reported as changes
    nobody explained.
    """
    library = await _library(request)
    if library.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    if not body.because.strip():
        raise HTTPException(status_code=400, detail="a decision needs a 'because'")
    await _store(request).library_add_decision(
        entry_id,
        LibraryDecision(
            question=body.question,
            choice=body.choice,
            because=body.because,
            params=tuple(body.params),
            rejected=tuple(body.rejected),
            author=body.author,
        ).to_dict(),
    )
    return await _entry_detail(request, entry_id)


@router.post("/api/library/{entry_id}/validated")
async def library_set_validated(
    entry_id: str, request: Request, body: dict[str, Any] = Body(default={})
) -> dict[str, Any]:
    """Mark that a human has checked this against something real.

    Never inferred: a spec that runs is not a spec that is right, and the only
    thing this flag can honestly mean is that somebody says so.
    """
    library = await _library(request)
    if library.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    await _store(request).library_set_validated(entry_id, bool(body.get("validated", True)))
    return await _entry_detail(request, entry_id)


@router.delete("/api/library/{entry_id}")
async def library_delete(entry_id: str, request: Request) -> dict[str, Any]:
    """Delete one entry. Its forks survive, pointing at an id that is gone."""
    deleted = await _store(request).library_delete(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")
    return {"deleted": True, "entry_id": entry_id}


@router.post("/api/library/{entry_id}/instantiate")
async def library_instantiate(
    entry_id: str, body: InstantiateRequest, request: Request
) -> dict[str, Any]:
    """Run a saved system as a live twin, remembering which entry it came from.

    The link back is the point: a system started from the library can later be
    captured as the *next version* of the design it came from, rather than as an
    unrelated spec that happens to look similar.
    """
    library = await _library(request)
    entry = library.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no library entry '{entry_id}'")

    try:
        spec = SystemSpec.from_dict(apply_site(entry.spec, body.site))
    except SiteError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from None
    if body.system_id:
        spec.system_id = body.system_id
    if body.name:
        spec.name = body.name
    existing = await _store(request).get_system(spec.system_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"system '{spec.system_id}' already exists; pass a 'system_id' "
            "to run this entry alongside it",
        )
    started = await _start_simulation(
        request, spec, body.name, body.autostart, body.speed, entry_id
    )
    started["entry_id"] = entry_id
    # Reported back so the caller can hand the same list to `capture` and get an
    # honest diff, rather than having to remember what it overrode.
    started["site"] = sorted(k for k, v in body.site.items() if v is not None)
    return started


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

    if body.source == "simulation":
        if not body.spec:
            raise HTTPException(status_code=400, detail="a simulation needs a 'spec'")
        spec = SystemSpec.from_dict(body.spec)
        if body.system_id:
            spec.system_id = body.system_id
        return await _start_simulation(request, spec, body.name, body.autostart, body.speed)

    if body.source == "realtime":
        if not body.system_id:
            raise HTTPException(status_code=400, detail="a real-time system needs a 'system_id'")
        await store.create_system(body.system_id, body.name, "realtime", None, "running")
        return {"system_id": body.system_id, "source": "realtime", "run_state": "running"}

    raise HTTPException(status_code=400, detail="source must be 'simulation' or 'realtime'")


async def _start_simulation(
    request: Request,
    spec: SystemSpec,
    name: str | None,
    autostart: bool,
    speed: float | None,
    library_entry_id: str | None = None,
) -> dict[str, Any]:
    """Validate, register and (optionally) start a twin-core simulation.

    Shared by ``POST /api/systems`` and the library's instantiate route so that
    running a saved system is the same act as running a built one -- the only
    difference being that the library path remembers which entry it came from.
    """
    store = _store(request)
    mgr = _sim_manager(request)
    errors = validate_spec(spec)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    run_state = "running" if autostart else "stopped"
    await store.create_system(
        spec.system_id, name or spec.name, "simulation", spec.to_dict(), run_state,
        library_entry_id,
    )
    mgr.create(spec, speed=speed or request.app.state.settings.sim_default_speed)
    if autostart:
        run_state = await mgr.start(spec.system_id)
    return {"system_id": spec.system_id, "source": "simulation", "run_state": run_state}


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


async def _persist_spec(request: Request, system_id: str) -> None:
    """Write a managed simulation's *current* spec back to the registry.

    Injecting or repairing a fault changes the spec — that is what makes a fault
    survive the run loop's duration rollover — but it changed it only in memory.
    The registry column claiming to hold the system's spec then held the one it
    was created with, which is wrong in two ways that matter: restarting the twin
    core rebuilt the pack from the stale spec and silently repaired it, and
    ``POST /api/library/capture`` saw a rack nobody had ever broken.
    """
    spec = _sim_manager(request).spec(system_id)
    if spec is None:
        return
    stored = await _store(request).get_system(system_id)
    await _store(request).create_system(
        system_id,
        (stored or {}).get("name"),
        "simulation",
        spec.to_dict(),
        (stored or {}).get("run_state") or "running",
        (stored or {}).get("library_entry_id"),
    )


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
    await _persist_spec(request, system_id)
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
    await _persist_spec(request, system_id)
    return {"system_id": system_id, "removed": asdict(removed)}


@router.delete("/api/systems/{system_id}/faults")
async def clear_faults(system_id: str, request: Request) -> dict[str, Any]:
    """Repair a system: drop every injected/declared fault from the running sim."""
    mgr = _require_sim(request, system_id)
    cleared = await mgr.clear_faults(system_id)
    await _persist_spec(request, system_id)
    return {"system_id": system_id, "cleared": cleared}


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
