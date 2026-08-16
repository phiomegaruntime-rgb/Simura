import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  evaluateLighting,
  fetchLightCatalog,
  fetchSpectrum,
  recommendLamp,
  solveLayout,
} from "../api/client";
import type {
  InstallationAssessment,
  LampRecommendation,
  LayoutResult,
  LightCatalog,
  LampType,
  SpectrumResponse,
} from "../api/types";
import StatTile from "./StatTile";
import { NumField, ProblemList, Row, Section, SelectField, Toggle } from "./formkit";

// Lights view: a lighting designer over simura.lights. Describe a space and a
// task, then check a chosen lamp, let the catalog recommend one, and see where
// the light actually falls. Below, the lamp's own spectrum — which is where its
// efficacy comes from, and the reason two lamps of the same wattage differ.
export default function LightsView() {
  const [catalog, setCatalog] = useState<LightCatalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // The space and the task.
  const [lampId, setLampId] = useState("led-15-e27");
  const [task, setTask] = useState("office");
  const [length, setLength] = useState(10);
  const [width, setWidth] = useState(8);
  const [height, setHeight] = useState(2.25);
  const [count, setCount] = useState(24);
  const [maintenanceHours, setMaintenanceHours] = useState(8000);
  const [family, setFamily] = useState("any");

  // Optional weather: ambient moves output in opposite directions by technology.
  const [weatherOn, setWeatherOn] = useState(false);
  const [airTemp, setAirTemp] = useState(5);
  const [wind, setWind] = useState(0);
  const [solar, setSolar] = useState(0);

  const [assessment, setAssessment] = useState<InstallationAssessment | null>(null);
  const [rec, setRec] = useState<LampRecommendation | null>(null);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [spectrum, setSpectrum] = useState<SpectrumResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchLightCatalog()
      .then(setCatalog)
      .catch((e) => setLoadError(String(e)));
  }, []);

  // The spectrum follows whichever lamp is selected — it is context, not a result,
  // so it loads on selection rather than waiting for a button.
  useEffect(() => {
    if (!catalog) return;
    fetchSpectrum({ lamp_type: lampId })
      .then(setSpectrum)
      .catch(() => setSpectrum(null));
  }, [lampId, catalog]);

  if (loadError)
    return <div className="text-sm text-critical">Couldn't load the lamp catalog: {loadError}</div>;
  if (!catalog) return <div className="text-muted">Loading lights…</div>;

  const run = (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    fn()
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setBusy(false));
  };

  const weatherBody = () =>
    weatherOn ? { air_temp_c: airTemp, wind_speed_ms: wind, solar_w_m2: solar } : undefined;

  const room = () => ({
    length_m: length,
    width_m: width,
    mounting_height_m: height,
    task,
    weather: weatherBody(),
  });

  const check = () =>
    run(async () => {
      setRec(null);
      setAssessment(
        await evaluateLighting({
          spec: { lamp_type: lampId },
          n_luminaires: count,
          maintenance_hours: maintenanceHours,
          ...room(),
        })
      );
    });

  const recommend = () =>
    run(async () => {
      setAssessment(null);
      const r = await recommendLamp({
        ...room(),
        family: family === "any" ? null : family,
        maintenance_hours: maintenanceHours,
      });
      setRec(r);
      if (r.lamp_type) {
        setLampId(r.lamp_type.id);
        setCount(r.n_luminaires);
      }
    });

  // Lay the fittings out on the most even grid that holds `count` of them, which
  // is what a designer would draw before adjusting anything by hand.
  const solveField = () =>
    run(async () => {
      const cols = Math.max(1, Math.round(Math.sqrt((count * length) / width)));
      const rows = Math.max(1, Math.ceil(count / cols));
      setLayout(
        await solveLayout({
          length_m: length,
          width_m: width,
          grid: {
            rows,
            cols,
            height_m: height + 0.75, // the planner's height is above the workplane
            lamp: { lamp_type: lampId },
          },
          target_lux: catalog.tasks[task] ?? 500,
          min_uniformity: 0.6,
          weather: weatherBody(),
        })
      );
    });

  const lampIds = catalog.lamp_types.map((l) => l.id);
  const selected = catalog.lamp_types.find((l) => l.id === lampId) ?? null;
  const targetLux = catalog.tasks[task] ?? 500;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Lighting planner</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Physics-based lighting design over <span className="text-ink">simura.lights</span>. Every
          lamp's efficacy is computed from the spectrum it actually radiates — Planck's law and the
          CIE observer — so a dimmed filament loses far more light than power, a cold fluorescent
          tube goes dim while a cold LED gets brighter, and warm white costs a few percent against
          cool white. Describe a space and <span className="text-ink">check</span> a lamp against
          it, let the catalog <span className="text-ink">recommend</span> one, or{" "}
          <span className="text-ink">solve the field</span> to see where the light lands.
        </p>
      </div>

      <Section title="Space & task">
        <Row>
          <SelectField
            label="Task"
            value={task}
            options={Object.keys(catalog.tasks)}
            onChange={setTask}
          />
          <NumField label="Length (m)" value={length} step={0.5} onChange={setLength} />
          <NumField label="Width (m)" value={width} step={0.5} onChange={setWidth} />
          <NumField
            label="Height above desk (m)"
            value={height}
            step={0.25}
            onChange={setHeight}
          />
          <span className="text-xs text-muted pb-2">
            target <span className="text-ink tnums">{targetLux.toFixed(0)}</span> lux
          </span>
        </Row>
        <Row>
          <SelectField label="Lamp" value={lampId} options={lampIds} onChange={setLampId} />
          <NumField
            label="Luminaires"
            value={count}
            step={1}
            onChange={(v) => setCount(Math.max(1, Math.round(v)))}
          />
          <NumField
            label="Aged (hours)"
            value={maintenanceHours}
            step={1000}
            onChange={setMaintenanceHours}
          />
          <SelectField
            label="Restrict to"
            value={family}
            options={["any", ...catalog.families]}
            onChange={setFamily}
          />
        </Row>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={check}
            disabled={busy}
            className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
          >
            {busy ? "…" : "Check this design"}
          </button>
          <button
            type="button"
            onClick={recommend}
            disabled={busy}
            className="rounded-md border border-series px-3 py-1.5 text-sm font-medium text-series hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
            title="The catalog lamp that meets the target at the lowest installed power"
          >
            Recommend a lamp
          </button>
          <button
            type="button"
            onClick={solveField}
            disabled={busy}
            className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
            title="Solve the illuminance field on a regular grid of fittings"
          >
            Solve the field
          </button>
          {err && <span className="text-sm text-critical">{err}</span>}
        </div>
        <p className="text-xs text-muted">
          <span className="text-ink-secondary">Aged</span> runs the check at the end of a
          maintenance cycle rather than on day one — lamps depreciate and luminaires collect dirt,
          and a design that only just clears its target when new will not clear it in three years.
        </p>
      </Section>

      <Section title="Weather (optional)">
        <p className="text-xs text-muted -mt-1 max-w-3xl">
          Design for a specific place. Ambient temperature moves light output in{" "}
          <span className="text-ink">opposite directions</span> depending on the technology: a
          fluorescent tube loses more than half its output near freezing because ambient sets its
          mercury vapour pressure, while an LED gets brighter as its junction cools. Wind cools an
          outdoor fitting; sun both warms its housing and lights the space for free.
        </p>
        <Row>
          <Toggle label="Apply weather" checked={weatherOn} onChange={setWeatherOn} />
          {weatherOn && (
            <>
              <NumField label="Ambient °C" value={airTemp} step={1} onChange={setAirTemp} />
              <NumField label="Wind (m/s)" value={wind} step={0.5} onChange={setWind} />
              <NumField label="Solar (W/m²)" value={solar} step={50} onChange={setSolar} />
            </>
          )}
        </Row>
      </Section>

      {assessment && <AssessmentPanel a={assessment} />}
      {rec && <RecommendPanel rec={rec} />}
      {layout && <LayoutPanel layout={layout} />}

      {spectrum && selected && <SpectrumPanel spectrum={spectrum} lamp={selected} />}

      <LampCatalogTable catalog={catalog} selected={lampId} onSelect={setLampId} />
    </div>
  );
}

function AssessmentPanel({ a }: { a: InstallationAssessment }) {
  const luxLevel =
    a.maintained_lux < a.target_lux ? "critical" : a.maintained_lux > a.target_lux * 2 ? "warning" : "good";
  const depreciation = a.initial_lux > 0 ? a.maintained_lux / a.initial_lux : 1;
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink">Assessment</h3>
        {a.ambient_temp_c != null && (
          <span className="text-xs text-muted">
            at <span className="text-ink-secondary">{a.ambient_temp_c.toFixed(0)} °C</span> ambient
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatTile
          label="Maintained"
          value={a.maintained_lux.toFixed(0)}
          unit="lux"
          level={luxLevel}
        />
        <StatTile label="Installed power" value={a.power_density_w_per_m2.toFixed(1)} unit="W/m²" />
        <StatTile label="Efficacy" value={a.efficacy_lm_per_w.toFixed(0)} unit="lm/W" />
        <StatTile
          label="Colour"
          value={a.color_temp_k > 0 ? a.color_temp_k.toFixed(0) : "—"}
          unit={a.color_temp_k > 0 ? "K" : ""}
        />
        <StatTile
          label="Annual energy"
          value={a.annual_energy_kwh != null ? a.annual_energy_kwh.toFixed(0) : "—"}
          unit="kWh"
        />
      </div>
      <div className="text-xs text-muted flex flex-wrap gap-x-6 gap-y-1">
        <span>
          {a.n_luminaires} × {a.flux_per_luminaire_lm.toFixed(0)} lm · target{" "}
          {a.target_lux.toFixed(0)} lux · CRI {a.cri.toFixed(0)}
        </span>
        <span>
          room index {a.room.room_index.toFixed(2)} · utilisation{" "}
          {(a.room.utilisation_factor * 100).toFixed(0)}%
        </span>
        <span>
          new {a.initial_lux.toFixed(0)} lux → aged {a.maintained_lux.toFixed(0)} lux (
          {(depreciation * 100).toFixed(0)}% left)
        </span>
      </div>
      <ProblemList
        problems={a.problems}
        okText="Meets the illuminance target, the colour requirement and the installed-power guideline."
      />
    </div>
  );
}

function RecommendPanel({ rec }: { rec: LampRecommendation }) {
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-ink">Recommendation</h3>
      {rec.lamp_type && (
        <div className="flex flex-wrap items-center gap-3">
          <span
            className="text-sm font-medium px-2 py-1 rounded-md"
            style={{
              backgroundColor: rec.ok ? "#0ca30c22" : "#c0392b22",
              color: rec.ok ? "#7fd97f" : "#eab0a6",
            }}
          >
            {rec.n_luminaires} × {rec.lamp_type.id}
          </span>
          <span className="text-sm text-ink">{rec.lamp_type.name}</span>
        </div>
      )}
      <p className={`text-sm ${rec.ok ? "text-ink-secondary" : "text-critical"}`}>{rec.rationale}</p>

      {rec.alternatives.length > 0 && (
        <>
          <p className="text-xs text-muted pt-1 border-t border-hairline">
            Ranked by installed power. The cheapest lamp to buy is almost never the cheapest to run,
            and which technology wins depends on the space — a cold store rules out fluorescent, a
            gallery rules out sodium, and anywhere light must return instantly rules out every
            high-pressure discharge lamp.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left tnums">
              <thead className="text-xs uppercase text-muted border-b border-hairline">
                <tr>
                  <th className="py-2 pr-4">Lamp</th>
                  <th className="py-2 pr-4">Family</th>
                  <th className="py-2 pr-4 text-right">N</th>
                  <th className="py-2 pr-4 text-right">W/m²</th>
                  <th className="py-2 pr-4 text-right">Lux</th>
                  <th className="py-2 pr-4 text-right">lm/W</th>
                  <th className="py-2 pr-4 text-right">kWh/yr</th>
                  <th className="py-2 pr-4 text-right">CRI</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {rec.alternatives.map((alt) => (
                  <tr key={alt.lamp_id} className="border-b border-hairline/50">
                    <td className="py-1.5 pr-4 text-ink">{alt.lamp_id}</td>
                    <td className="py-1.5 pr-4 text-muted">{alt.family.replace("_", " ")}</td>
                    <td className="py-1.5 pr-4 text-right text-ink-secondary">
                      {alt.n_luminaires}
                    </td>
                    <td className="py-1.5 pr-4 text-right text-ink">
                      {alt.power_density_w_per_m2.toFixed(2)}
                    </td>
                    <td className="py-1.5 pr-4 text-right text-ink-secondary">
                      {alt.maintained_lux.toFixed(0)}
                    </td>
                    <td className="py-1.5 pr-4 text-right text-ink-secondary">
                      {alt.efficacy_lm_per_w.toFixed(0)}
                    </td>
                    <td className="py-1.5 pr-4 text-right text-ink-secondary">
                      {alt.annual_energy_kwh?.toFixed(0) ?? "—"}
                    </td>
                    <td className="py-1.5 pr-4 text-right text-ink-secondary">
                      {alt.cri.toFixed(0)}
                    </td>
                    <td className="py-1.5 text-xs">
                      {alt.ok ? (
                        <span className="text-good">✓</span>
                      ) : (
                        <span className="text-warning" title={alt.problems.join("; ")}>
                          {alt.problems.length} issue{alt.problems.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// Illuminance heatmap. Average illuminance hides the two failures that matter —
// dark patches between fittings, and pools of light under them — so the field is
// shown as a grid rather than reduced to one number.
function LayoutPanel({ layout }: { layout: LayoutResult }) {
  const uniformityLevel =
    layout.uniformity < 0.4 ? "critical" : layout.uniformity < 0.6 ? "warning" : "good";
  const span = Math.max(layout.max_lux, 1);

  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink">Illuminance field</h3>
        <span className="text-xs text-muted">
          {layout.luminaires.length} fittings over {layout.area_m2.toFixed(0)} m²
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatTile label="Average" value={layout.average_lux.toFixed(0)} unit="lux" />
        <StatTile label="Minimum" value={layout.min_lux.toFixed(0)} unit="lux" />
        <StatTile label="Maximum" value={layout.max_lux.toFixed(0)} unit="lux" />
        <StatTile
          label="Uniformity U₀"
          value={layout.uniformity.toFixed(2)}
          level={uniformityLevel}
        />
        <StatTile
          label="Installed power"
          value={layout.power_density_w_per_m2.toFixed(1)}
          unit="W/m²"
        />
      </div>

      <div
        className="grid gap-px rounded overflow-hidden border border-hairline"
        style={{ gridTemplateColumns: `repeat(${layout.grid_x_m.length}, minmax(0, 1fr))` }}
      >
        {layout.grid.flatMap((row, r) =>
          row.map((lux, c) => {
            const t = Math.max(0, Math.min(1, lux / span));
            return (
              <div
                key={`${r}-${c}`}
                title={`${lux.toFixed(0)} lux`}
                className="aspect-square flex items-center justify-center text-[10px] tnums"
                style={{
                  // A dark-to-warm ramp: unlit floor through to the brightest point.
                  backgroundColor: `rgb(${Math.round(20 + 235 * t)}, ${Math.round(
                    18 + 200 * t
                  )}, ${Math.round(16 + 120 * t)})`,
                  color: t > 0.55 ? "#1a1a18" : "#8a8880",
                }}
              >
                {lux.toFixed(0)}
              </div>
            );
          })
        )}
      </div>

      <div className="text-xs text-muted flex flex-wrap gap-x-6 gap-y-1">
        <span>
          direct {layout.direct_average_lux.toFixed(0)} lux + interreflected{" "}
          {layout.indirect_lux.toFixed(0)} lux
        </span>
        {layout.daylight_lux > 0 && <span>daylight {layout.daylight_lux.toFixed(0)} lux</span>}
        <span>diversity (min/max) {layout.diversity.toFixed(2)}</span>
      </div>

      <ProblemList
        problems={layout.problems}
        okText="Bright enough everywhere, and even enough for the task."
      />
    </div>
  );
}

// The spectrum is where a lamp's efficacy comes from, so it earns a chart. A
// filament's smooth Planck curve, an LED's blue spike under a phosphor hump, and
// a sodium lamp's single line are three completely different pictures — and they
// explain the three completely different numbers above them.
function SpectrumPanel({
  spectrum,
  lamp,
}: {
  spectrum: SpectrumResponse;
  lamp: LampType;
}) {
  const data = useMemo(
    () =>
      spectrum.wavelength_nm.map((nm, i) => ({
        nm,
        power: spectrum.relative_power[i],
        fill: wavelengthColor(nm),
      })),
    [spectrum]
  );
  const point = spectrum.operating_point;
  const predicted = point.luminous_flux_lm;
  const published = spectrum.published_flux_lm;
  const gap = published > 0 ? ((predicted - published) / published) * 100 : null;

  return (
    <Section title={`Spectrum — ${lamp.name}`}>
      <p className="text-xs text-muted -mt-1 max-w-3xl">
        {spectrum.technology.notes}
      </p>

      <div style={{ width: "100%", height: 200 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -14 }}>
            <defs>
              <linearGradient id="visible-spectrum" x1="0" y1="0" x2="1" y2="0">
                {/* The visible band, painted in its own colours: 360 nm at the
                    left edge through to 830 nm at the right. */}
                {[380, 440, 480, 510, 550, 580, 610, 660, 720].map((nm) => (
                  <stop
                    key={nm}
                    offset={`${((nm - 360) / (830 - 360)) * 100}%`}
                    stopColor={wavelengthColor(nm)}
                  />
                ))}
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#2c2c2a" vertical={false} />
            <XAxis
              dataKey="nm"
              type="number"
              domain={[380, 780]}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              tickFormatter={(v) => `${v}`}
              label={{
                value: "wavelength (nm)",
                position: "insideBottom",
                offset: -2,
                fill: "#898781",
                fontSize: 11,
              }}
            />
            <YAxis
              domain={[0, 1]}
              tick={{ fill: "#898781", fontSize: 11 }}
              stroke="#383835"
              width={44}
              tickFormatter={(v) => v.toFixed(1)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#232322",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#898781" }}
              itemStyle={{ color: "#ffffff" }}
              labelFormatter={(v) => `${v} nm`}
              formatter={(value: number) => [value.toFixed(3), "relative power"]}
            />
            <Area
              type="monotone"
              dataKey="power"
              stroke="#e8e6e0"
              strokeWidth={1}
              fill="url(#visible-spectrum)"
              fillOpacity={0.75}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatTile label="Predicted flux" value={predicted.toFixed(0)} unit="lm" />
        <StatTile label="Efficacy" value={point.efficacy_lm_per_w.toFixed(1)} unit="lm/W" />
        <StatTile
          label="Efficacy of radiation"
          value={point.ler_lm_per_w.toFixed(0)}
          unit="lm/W"
        />
        <StatTile
          label="Colour temp"
          value={point.color_temp_k > 0 ? point.color_temp_k.toFixed(0) : "—"}
          unit={point.color_temp_k > 0 ? "K" : ""}
        />
        <StatTile label="Source temp" value={point.source_temp_c.toFixed(0)} unit="°C" />
      </div>

      <p className="text-xs text-muted">
        <span className="text-ink-secondary">Efficacy of radiation</span> is the ceiling this
        spectrum could reach if every watt became light of exactly this colour — 683 lm/W for pure
        555 nm green, about 95 for a daylight blackbody, 15 for a 2800 K filament. The lamp's actual
        efficacy is that ceiling times the share of its input power that becomes radiation at all.
        {published > 0 && gap != null && (
          <>
            {" "}
            Predicted {predicted.toFixed(0)} lm against a published {published.toFixed(0)} lm —{" "}
            <span className={Math.abs(gap) > 15 ? "text-warning" : "text-ink-secondary"}>
              {gap >= 0 ? "+" : ""}
              {gap.toFixed(1)}%
            </span>
            . The catalog figure is never used to produce light; it is only ever compared against.
          </>
        )}
      </p>
    </Section>
  );
}

function LampCatalogTable({
  catalog,
  selected,
  onSelect,
}: {
  catalog: LightCatalog;
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <Section title={`Lamp catalog (${catalog.lamp_types.length})`}>
      <p className="text-xs text-muted -mt-1">
        Published manufacturer figures. Simura predicts its own flux from the physics and never
        consults these — which is exactly what the Validation tab measures.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left tnums">
          <thead className="text-xs uppercase text-muted border-b border-hairline">
            <tr>
              <th className="py-2 pr-4">ID</th>
              <th className="py-2 pr-4">Technology</th>
              <th className="py-2 pr-4">Family</th>
              <th className="py-2 pr-4 text-right">W</th>
              <th className="py-2 pr-4 text-right">lm</th>
              <th className="py-2 pr-4 text-right">lm/W</th>
              <th className="py-2 pr-4 text-right">CCT</th>
              <th className="py-2 pr-4 text-right">Beam</th>
              <th className="py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {catalog.lamp_types.map((l) => (
              <tr
                key={l.id}
                onClick={() => onSelect(l.id)}
                className={`border-b border-hairline/50 cursor-pointer hover:bg-surface-2 ${
                  l.id === selected ? "bg-surface-2" : ""
                }`}
              >
                <td className="py-1.5 pr-4 text-ink">{l.id}</td>
                <td className="py-1.5 pr-4 text-ink-secondary">{l.technology}</td>
                <td className="py-1.5 pr-4 text-muted">{l.family.replace("_", " ")}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">
                  {l.rated_power_w.toFixed(0)}
                </td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">
                  {l.rated_flux_lm.toFixed(0)}
                </td>
                <td className="py-1.5 pr-4 text-right text-ink">
                  {l.published_efficacy_lm_per_w.toFixed(0)}
                </td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">
                  {l.color_temp_k > 0 ? l.color_temp_k.toFixed(0) : "—"}
                </td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">
                  {l.beam_angle_deg.toFixed(0)}°
                </td>
                <td className="py-1.5 text-muted">{l.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// Approximate sRGB for a wavelength, so a spectrum chart is painted in the
// colours it describes. Dan Bruton's well-known piecewise approximation.
function wavelengthColor(nm: number): string {
  let r = 0;
  let g = 0;
  let b = 0;
  if (nm >= 380 && nm < 440) {
    r = -(nm - 440) / (440 - 380);
    b = 1;
  } else if (nm < 490) {
    g = (nm - 440) / (490 - 440);
    b = 1;
  } else if (nm < 510) {
    g = 1;
    b = -(nm - 510) / (510 - 490);
  } else if (nm < 580) {
    r = (nm - 510) / (580 - 510);
    g = 1;
  } else if (nm < 645) {
    r = 1;
    g = -(nm - 645) / (645 - 580);
  } else if (nm <= 780) {
    r = 1;
  }
  // Intensity falls off at the ends of the visible band, where the eye does too.
  let factor = 1;
  if (nm >= 380 && nm < 420) factor = 0.3 + (0.7 * (nm - 380)) / 40;
  else if (nm > 700 && nm <= 780) factor = 0.3 + (0.7 * (780 - nm)) / 80;
  else if (nm < 380 || nm > 780) factor = 0;

  const ch = (v: number) => Math.round(255 * Math.pow(Math.max(0, v) * factor, 0.8));
  return `rgb(${ch(r)}, ${ch(g)}, ${ch(b)})`;
}
