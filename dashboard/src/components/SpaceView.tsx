import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchExampleBuilding,
  fetchSpaceOptions,
  importBuilding,
  planAmbient,
  planLighting,
  planRoute,
  planWeather,
} from "../api/client";
import type {
  CableRoute,
  FloorPlan,
  LightingTarget,
  PlanSpace,
  SpaceContext,
  SpaceLightingResponse,
  SpaceOptions,
} from "../api/types";
import StatTile from "./StatTile";
import { NumField, ProblemList, Row, Section, TextField } from "./formkit";

// The Building view: import a BIM model, draw the plan, and show what the
// import could not read *beside* it.
//
// That adjacency is the whole information architecture of this screen. A plan
// on its own looks authoritative — clean polygons, round numbers — and the one
// thing a reader cannot see in it is which of those numbers came out of the file
// and which the importer supplied. So the fidelity panel is not behind a tab or
// a "details" disclosure: it sits next to the drawing, and rooms that rest on an
// assumption are marked in the drawing itself.
//
// Everything below the plan is a coupling: the weather the model's coordinates
// imply, the lighting design every room needs, and the cable length between two
// points somebody clicks.

type Tool = "inspect" | "route";

const OCCUPANCY_FILL: Record<string, string> = {
  office: "rgba(57,135,229,0.20)",
  classroom: "rgba(57,135,229,0.20)",
  drawing_office: "rgba(57,135,229,0.20)",
  corridor: "rgba(255,255,255,0.05)",
  lobby: "rgba(255,255,255,0.07)",
  storage: "rgba(237,161,0,0.16)",
  workshop: "rgba(237,161,0,0.16)",
  warehouse_aisle: "rgba(237,161,0,0.16)",
  kitchen: "rgba(236,131,90,0.16)",
  car_park: "rgba(137,135,129,0.14)",
  unknown: "rgba(208,59,59,0.14)",
};

export default function SpaceView() {
  const [options, setOptions] = useState<SpaceOptions | null>(null);
  const [plan, setPlan] = useState<FloorPlan | null>(null);
  const [levelId, setLevelId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // DXF only: a drawing whose layers follow an unusual convention is otherwise
  // unimportable, and naming the convention is the honest fix.
  const [wallLayers, setWallLayers] = useState("");
  const [roomLayers, setRoomLayers] = useState("");

  const [tool, setTool] = useState<Tool>("inspect");
  const [selected, setSelected] = useState<PlanSpace | null>(null);
  const [ambient, setAmbient] = useState<SpaceContext | null>(null);
  const [lighting, setLighting] = useState<SpaceLightingResponse | null>(null);
  const [weatherFromModel, setWeatherFromModel] = useState<{
    located: boolean;
    weather: { type: string; params: Record<string, unknown> } | null;
  } | null>(null);

  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [route, setRoute] = useState<CableRoute | null>(null);
  const [wireType, setWireType] = useState("cu-10-thhn90");
  const [currentA, setCurrentA] = useState(25);
  const [routeWire, setRouteWire] = useState<Record<string, number> | null>(null);
  const [hottest, setHottest] = useState<number | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchSpaceOptions().then(setOptions).catch(() => setOptions(null));
  }, []);

  const run = (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    fn()
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setBusy(false));
  };

  const adopt = (next: FloorPlan) => {
    setPlan(next);
    setLevelId(next.levels[0]?.id ?? "");
    setSelected(null);
    setAmbient(null);
    setLighting(null);
    setRoute(null);
    setRoutePoints([]);
    setRouteWire(null);
    // The weather the model implies is asked for immediately, because it is the
    // coupling somebody would otherwise never think to look for.
    planWeather(next)
      .then((w) => setWeatherFromModel({ located: w.located, weather: w.weather }))
      .catch(() => setWeatherFromModel(null));
  };

  const onFile = (file: File | null) => {
    if (!file) return;
    run(async () => {
      const { plan: imported } = await importBuilding(file, {
        wallLayers: wallLayers || undefined,
        roomLayers: roomLayers || undefined,
      });
      adopt(imported);
    });
  };

  // The example goes through the same server-side provider the tests use, and
  // comes back with a fidelity record that reads "nothing was assumed" -- which
  // is the control case that gives the warning meaning on a real model.
  const loadExample = () =>
    run(async () => {
      adopt(await fetchExampleBuilding(4, 2));
    });

  const selectSpace = (space: PlanSpace) => {
    setSelected(space);
    if (!plan) return;
    planAmbient(plan, space.id)
      .then((r) => setAmbient(r.space))
      .catch(() => setAmbient(null));
  };

  const designBuilding = () => {
    if (!plan) return;
    run(async () => {
      setLighting(await planLighting(plan, { levelId, recommend: true }));
    });
  };

  const onPlanClick = (x: number, y: number) => {
    if (!plan) return;
    if (tool === "route") {
      const next: [number, number][] = routePoints.length >= 2 ? [[x, y]] : [...routePoints, [x, y]];
      setRoutePoints(next);
      if (next.length === 2) {
        run(async () => {
          const res = await planRoute(plan, next[0], next[1], {
            startLevel: levelId,
            endLevel: levelId,
            wireType,
            currentA,
          });
          setRoute(res.route);
          setHottest(res.hottest_ambient_c);
          setRouteWire(res.wire as unknown as Record<string, number> | null);
        });
      }
      return;
    }
    const hit = spaces.find((s) => pointInPolygon([x, y], s.polygon));
    if (hit) selectSpace(hit);
  };

  const spaces = useMemo(
    () => (plan?.spaces ?? []).filter((s) => !levelId || s.level_id === levelId),
    [plan, levelId],
  );
  const walls = useMemo(
    () => (plan?.walls ?? []).filter((w) => !levelId || w.level_id === levelId),
    [plan, levelId],
  );

  if (!options) return <div className="text-muted">Loading building formats…</div>;

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Import a building"
        action={busy ? <span className="text-xs text-muted">working…</span> : undefined}
      >
        <p className="text-xs text-ink-secondary max-w-3xl">
          An IFC model, a gbXML energy model, or an ASCII DXF floor plan. Everything is
          parsed in the browser's own server — no plug-in, no cloud service, and nothing
          stored: the plan comes back to you and stays here.
        </p>
        <Row>
          <input
            ref={fileInput}
            type="file"
            accept=".ifc,.xml,.gbxml,.dxf,.json,.step,.stp"
            className="text-xs text-ink-secondary file:mr-3 file:rounded-md file:border-0 file:bg-series file:px-3 file:py-1.5 file:text-sm file:text-white"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          <button
            className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink"
            disabled={busy}
            onClick={loadExample}
          >
            Use an example building
          </button>
        </Row>
        <Row>
          <TextField label="DXF wall layers" value={wallLayers} onChange={setWallLayers} />
          <TextField label="DXF room layers" value={roomLayers} onChange={setRoomLayers} />
          <span className="text-xs text-muted max-w-md">
            Only for a drawing whose layers this doesn't recognise. Comma-separated, matched
            anywhere in the layer name.
          </span>
        </Row>
        {err && <div className="text-sm text-critical">{err}</div>}
      </Section>

      {plan && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* The drawing */}
            <div className="lg:col-span-3">
              <Section
                title={plan.name || "Floor plan"}
                action={
                  <div className="flex items-center gap-2">
                    {plan.levels.length > 1 && (
                      <select
                        value={levelId}
                        onChange={(e) => setLevelId(e.target.value)}
                        className="bg-surface-2 border border-hairline rounded-md px-2 py-1 text-ink text-xs"
                      >
                        {plan.levels.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.name || l.id}
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      className={`rounded-md px-2 py-1 text-xs border ${
                        tool === "inspect"
                          ? "border-series text-series"
                          : "border-hairline text-muted"
                      }`}
                      onClick={() => setTool("inspect")}
                    >
                      Inspect
                    </button>
                    <button
                      className={`rounded-md px-2 py-1 text-xs border ${
                        tool === "route"
                          ? "border-series text-series"
                          : "border-hairline text-muted"
                      }`}
                      onClick={() => {
                        setTool("route");
                        setRoutePoints([]);
                        setRoute(null);
                      }}
                    >
                      Route a cable
                    </button>
                  </div>
                }
              >
                <PlanDrawing
                  spaces={spaces}
                  walls={walls}
                  selected={selected}
                  routePoints={routePoints}
                  route={route}
                  onClick={onPlanClick}
                />
                <div className="flex flex-wrap gap-4 text-xs text-muted">
                  <span>{spaces.length} rooms</span>
                  <span>{plan.floor_area_m2.toFixed(0)} m²</span>
                  <span>drawn in {plan.source_units}</span>
                  {plan.georeference.latitude != null && (
                    <span>
                      {plan.georeference.latitude.toFixed(4)},{" "}
                      {plan.georeference.longitude?.toFixed(4)} · true north{" "}
                      {plan.georeference.north_deg.toFixed(0)}°
                    </span>
                  )}
                  <span className="text-warning">
                    ▧ hatched = a value in this room was assumed
                  </span>
                </div>
                {tool === "route" && (
                  <p className="text-xs text-ink-secondary">
                    Click two points. The run is traced through the rooms and the doorways
                    that join them — a cable goes through doors, not through walls.
                  </p>
                )}
              </Section>
            </div>

            {/* What the import could not read */}
            <div className="lg:col-span-2 flex flex-col gap-4">
              <FidelityPanel plan={plan} />
              {weatherFromModel && <WeatherPanel located={weatherFromModel.located} weather={weatherFromModel.weather} />}
            </div>
          </div>

          {selected && <RoomPanel space={selected} ambient={ambient} />}

          {route && (
            <RoutePanel
              route={route}
              hottest={hottest}
              wire={routeWire}
              wireType={wireType}
              currentA={currentA}
              onWireType={setWireType}
              onCurrent={setCurrentA}
            />
          )}

          <Section
            title="Light the whole building"
            action={
              <button
                className="rounded-md bg-series px-3 py-1.5 text-sm text-white disabled:opacity-50"
                disabled={busy}
                onClick={designBuilding}
              >
                Design every room
              </button>
            }
          >
            <p className="text-xs text-ink-secondary max-w-3xl">
              Every room becomes a lighting problem with its real extents and the
              illuminance its use calls for. A room that cannot honestly be designed as
              read is still listed, with the reason — so the total says “38 of 41 rooms”
              rather than quietly covering 38.
            </p>
            {lighting && <LightingTable lighting={lighting} />}
          </Section>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The drawing
// ---------------------------------------------------------------------------

function PlanDrawing({
  spaces,
  walls,
  selected,
  routePoints,
  route,
  onClick,
}: {
  spaces: PlanSpace[];
  walls: { id: string; axis: [number, number][]; thickness_m: number; exterior: boolean }[];
  selected: PlanSpace | null;
  routePoints: [number, number][];
  route: CableRoute | null;
  onClick: (x: number, y: number) => void;
}) {
  const bounds = useMemo(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const s of spaces) for (const [x, y] of s.polygon) (xs.push(x), ys.push(y));
    for (const w of walls) for (const [x, y] of w.axis) (xs.push(x), ys.push(y));
    if (!xs.length) return { minX: 0, minY: 0, w: 10, h: 10 };
    const pad = 1.0;
    const minX = Math.min(...xs) - pad;
    const minY = Math.min(...ys) - pad;
    return {
      minX,
      minY,
      w: Math.max(1, Math.max(...xs) + pad - minX),
      h: Math.max(1, Math.max(...ys) + pad - minY),
    };
  }, [spaces, walls]);

  const svgRef = useRef<SVGSVGElement>(null);

  // The y axis is flipped so north is up: a plan drawn with +y increasing
  // downward reads as a mirror image of the building to anybody who knows it.
  const flip = (y: number) => bounds.minY + bounds.h - (y - bounds.minY) + bounds.minY - bounds.minY;

  const toPlan = (evt: React.MouseEvent<SVGSVGElement>): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const rect = svg.getBoundingClientRect();
    const fx = (evt.clientX - rect.left) / rect.width;
    const fy = (evt.clientY - rect.top) / rect.height;
    return [bounds.minX + fx * bounds.w, bounds.minY + (1 - fy) * bounds.h];
  };

  const path = (poly: [number, number][]) =>
    poly.map(([x, y]) => `${x},${flip(y)}`).join(" ");

  return (
    <svg
      ref={svgRef}
      viewBox={`${bounds.minX} ${bounds.minY} ${bounds.w} ${bounds.h}`}
      className="w-full rounded-md bg-plane border border-hairline cursor-crosshair"
      style={{ aspectRatio: `${bounds.w} / ${bounds.h}`, maxHeight: "60vh" }}
      onClick={(e) => {
        const [x, y] = toPlan(e);
        onClick(x, y);
      }}
    >
      <defs>
        {/* Hatching marks a room carrying an assumed value. It is a second
            channel alongside the room's colour, so it reads for someone who
            cannot separate the fills. */}
        <pattern
          id="assumed"
          width="0.6"
          height="0.6"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="0.6" stroke="rgba(250,178,25,0.45)" strokeWidth="0.08" />
        </pattern>
      </defs>

      {spaces.map((s) => (
        <g key={s.id}>
          <polygon
            points={path(s.polygon)}
            fill={OCCUPANCY_FILL[s.occupancy] ?? OCCUPANCY_FILL.unknown}
            stroke={selected?.id === s.id ? "#3987e5" : "rgba(255,255,255,0.18)"}
            strokeWidth={selected?.id === s.id ? 0.14 : 0.05}
          />
          {s.inferred.length > 0 && (
            <polygon points={path(s.polygon)} fill="url(#assumed)" stroke="none" />
          )}
          <text
            x={s.centroid[0]}
            y={flip(s.centroid[1])}
            textAnchor="middle"
            fill="#c3c2b7"
            style={{ fontSize: Math.min(0.7, Math.sqrt(s.area_m2) / 7) }}
          >
            {s.name || s.id}
          </text>
        </g>
      ))}

      {walls.map((w) => (
        <polyline
          key={w.id}
          points={path(w.axis)}
          fill="none"
          stroke={w.exterior ? "#ffffff" : "#898781"}
          strokeWidth={Math.max(0.08, w.thickness_m)}
          strokeLinecap="square"
        />
      ))}

      {route?.path?.length ? (
        <polyline
          points={path(route.path as [number, number][])}
          fill="none"
          stroke="#eda100"
          strokeWidth={0.12}
          strokeDasharray="0.4 0.25"
        />
      ) : null}

      {routePoints.map(([x, y], i) => (
        <circle key={i} cx={x} cy={flip(y)} r={0.22} fill="#eda100" />
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// What the import could not read
// ---------------------------------------------------------------------------

function FidelityPanel({ plan }: { plan: FloorPlan }) {
  const f = plan.fidelity;
  const [open, setOpen] = useState(true);

  return (
    <Section
      title="What the import could not read"
      action={
        <button className="text-xs text-muted hover:text-ink" onClick={() => setOpen(!open)}>
          {open ? "hide" : "show"}
        </button>
      }
    >
      <p className="text-sm text-ink-secondary">{f.summary}</p>
      <div className="flex gap-3">
        <StatTile label="Understood" value={`${(f.coverage * 100).toFixed(0)}%`} />
        <StatTile label="Assumed" value={String(f.inferences.length)} />
        <StatTile
          label="Skipped"
          value={String(f.skipped.reduce((n, s) => n + s.count, 0))}
        />
      </div>

      {f.complete && (
        <p className="text-xs text-good">
          Nothing was assumed — every number in this plan came out of the file.
        </p>
      )}

      {open && (
        <div className="flex flex-col gap-3 max-h-96 overflow-y-auto pr-1">
          {f.inferences.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-ink mb-1">
                Values the importer supplied
              </div>
              <ul className="flex flex-col gap-1.5">
                {f.inferences.map((i, n) => (
                  <li key={n} className="text-xs">
                    <span
                      className={`inline-block rounded px-1 mr-1 ${
                        i.provenance === "default"
                          ? "bg-critical/20 text-critical"
                          : "bg-warning/20 text-warning"
                      }`}
                    >
                      {i.provenance === "default" ? "default" : "derived"}
                    </span>
                    <span className="text-ink-secondary">
                      {i.subject}.{i.field} = {String(i.value)}
                    </span>
                    <div className="text-muted pl-1">{i.basis}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {f.skipped.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-ink mb-1">
                What it did not turn into geometry
              </div>
              <ul className="flex flex-col gap-1 text-xs text-ink-secondary">
                {f.skipped.map((s, n) => (
                  <li key={n}>
                    <span className="text-muted">{s.count}×</span> {s.entity}
                    <div className="text-muted pl-1">{s.reason}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {f.warnings.map((w, n) => (
            <div key={n} className="text-xs text-critical">
              ! {w}
            </div>
          ))}

          {f.source_sha256 && (
            <div className="text-[11px] text-muted">
              source sha256 {f.source_sha256.slice(0, 16)}… — this plan can always be
              traced back to the exact file it came from.
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

function WeatherPanel({
  located,
  weather,
}: {
  located: boolean;
  weather: { type: string; params: Record<string, unknown> } | null;
}) {
  return (
    <Section title="Where on Earth this is">
      {located && weather ? (
        <>
          <p className="text-xs text-ink-secondary">
            The model carries its own coordinates, so the weather source is configured
            from the building rather than typed in. Paste this into a system's spec:
          </p>
          <pre className="text-[11px] text-ink-secondary bg-surface-2 rounded-md p-2 overflow-x-auto">
{JSON.stringify({ weather }, null, 2)}
          </pre>
        </>
      ) : (
        <p className="text-xs text-ink-secondary">
          This model carries no coordinates, so no weather source can be built from it.
          That is a fact about the file, not a failure — set one by hand instead.
        </p>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// One room
// ---------------------------------------------------------------------------

function RoomPanel({ space, ambient }: { space: PlanSpace; ambient: SpaceContext | null }) {
  return (
    <Section title={space.name || space.id}>
      <div className="flex flex-wrap gap-3">
        <StatTile label="Use" value={space.occupancy.replace(/_/g, " ")} />
        <StatTile label="Area" value={`${space.area_m2.toFixed(1)} m²`} />
        <StatTile
          label="Extents"
          value={`${space.length_m.toFixed(1)} × ${space.width_m.toFixed(1)} m`}
        />
        <StatTile label="Ceiling" value={`${space.height_m.toFixed(2)} m`} />
        {ambient && <StatTile label="Ambient" value={`${ambient.ambient_c.toFixed(1)} °C`} />}
      </div>

      {!space.rectangular && (
        <p className="text-xs text-warning">
          This room is not a rectangle. Its {space.length_m.toFixed(1)} ×{" "}
          {space.width_m.toFixed(1)} m is a best-fit rectangle of{" "}
          {(space.length_m * space.width_m).toFixed(1)} m² against the room's actual{" "}
          {space.area_m2.toFixed(1)} m² — the lumen method needs a rectangle, so anything
          derived from those two numbers is an approximation of a shape it is not.
        </p>
      )}

      {space.inferred.length > 0 && (
        <p className="text-xs text-warning">
          Assumed for this room: {space.inferred.join(", ")}. See “what the import could
          not read” for the basis of each.
        </p>
      )}

      {ambient && (
        <div className="text-xs text-ink-secondary">
          <span className={ambient.indoor ? "text-good" : "text-series-warm"}>
            {ambient.indoor ? "Indoors" : "Exposed"}
          </span>{" "}
          — {ambient.basis}
          {!ambient.stated && (
            <div className="text-warning mt-1">
              The model never said whether this room is conditioned, so the weather is
              applied unshielded. Hiding the coupling behind a guess would be worse: a
              battery that quietly stops responding to a heatwave is harder to notice
              than one that responds to weather it should have been shielded from.
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// A cable run
// ---------------------------------------------------------------------------

function RoutePanel({
  route,
  hottest,
  wire,
  wireType,
  currentA,
  onWireType,
  onCurrent,
}: {
  route: CableRoute;
  hottest: number | null;
  wire: Record<string, number> | null;
  wireType: string;
  currentA: number;
  onWireType: (v: string) => void;
  onCurrent: (v: number) => void;
}) {
  return (
    <Section title="The cable is as long as the building makes it">
      <div className="flex flex-wrap gap-3">
        <StatTile label="Run" value={`${route.length_m.toFixed(2)} m`} />
        <StatTile label="Horizontal" value={`${route.horizontal_m.toFixed(1)} m`} />
        <StatTile label="Vertical" value={`${route.vertical_m.toFixed(1)} m`} />
        <StatTile label="Slack" value={`${route.slack_m.toFixed(1)} m`} />
        {hottest != null && <StatTile label="Rated for" value={`${hottest.toFixed(0)} °C`} />}
      </div>

      <table className="w-full text-xs">
        <tbody>
          {route.legs.map((leg, i) => (
            <tr key={i} className="border-b border-hairline/50">
              <td className="py-1 text-muted w-24">{leg.kind}</td>
              <td className="py-1 tnums text-ink w-24">{leg.length_m.toFixed(2)} m</td>
              <td className="py-1 text-ink-secondary">{leg.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-muted">
        The legs are shown because a computed length is only worth having if somebody can
        check where the metres went.
      </p>

      <Row>
        <TextField label="Wire type" value={wireType} onChange={onWireType} />
        <NumField label="Current (A)" value={currentA} step={1} onChange={onCurrent} />
      </Row>

      {wire && (
        <div className="flex flex-wrap gap-3">
          <StatTile label="Voltage drop" value={`${Number(wire.voltage_drop_v).toFixed(2)} V`} />
          <StatTile label="Drop" value={`${Number(wire.voltage_drop_pct).toFixed(1)} %`} />
          <StatTile label="Loss" value={`${Number(wire.power_loss_w).toFixed(1)} W`} />
          <StatTile
            label="Conductor"
            value={`${Number(wire.steady_state_temp_c).toFixed(0)} °C`}
          />
        </div>
      )}

      <ProblemList problems={route.problems} okText="Traced through the building's own doorways." />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// The whole building, lit
// ---------------------------------------------------------------------------

function LightingTable({ lighting }: { lighting: SpaceLightingResponse }) {
  const rows = lighting.rooms ?? [];
  return (
    <div className="flex flex-col gap-3">
      {lighting.building && (
        <div className="flex flex-wrap gap-3">
          <StatTile label="Installed" value={`${lighting.building.power_w.toFixed(0)} W`} />
          <StatTile
            label="Density"
            value={`${lighting.building.power_density_w_per_m2.toFixed(1)} W/m²`}
          />
          <StatTile label="Rooms designed" value={String(lighting.building.designed)} />
          {lighting.undesignable > 0 && (
            <StatTile label="Not as read" value={String(lighting.undesignable)} />
          )}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted">
            <tr>
              <th className="text-left py-1">Room</th>
              <th className="text-right py-1">Target</th>
              <th className="text-left py-1 pl-3">Lamp</th>
              <th className="text-right py-1">n</th>
              <th className="text-right py-1">W/m²</th>
              <th className="text-left py-1 pl-3">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const a = row.recommendation.assessment;
              return (
                <tr key={row.space_id} className="border-b border-hairline/50 align-top">
                  <td className="py-1 text-ink">{row.name}</td>
                  <td className="py-1 text-right tnums text-ink-secondary">
                    {a ? `${a.target_lux.toFixed(0)} lx` : "—"}
                  </td>
                  <td className="py-1 pl-3 text-ink-secondary">
                    {row.recommendation.lamp_type?.name ?? "—"}
                  </td>
                  <td className="py-1 text-right tnums text-ink-secondary">
                    {row.recommendation.n_luminaires}
                  </td>
                  <td className="py-1 text-right tnums text-ink-secondary">
                    {a ? a.power_density_w_per_m2.toFixed(1) : "—"}
                  </td>
                  <td className="py-1 pl-3">
                    {row.recommendation.ok ? (
                      <span className="text-good">ok</span>
                    ) : (
                      <span className="text-warning">
                        {a?.problems?.[0] ?? row.recommendation.rationale}
                      </span>
                    )}
                    {row.target.problems.map((p, i) => (
                      <div key={i} className="text-muted">
                        ! {p}
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** Ray casting, so a click can find the room it landed in without a round trip. */
function pointInPolygon([x, y]: [number, number], poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
