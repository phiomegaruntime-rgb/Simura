import { useEffect, useMemo, useState } from "react";
import { fetchFleet, fetchSystems } from "./api/client";
import { useTelemetry } from "./api/useTelemetry";
import type { CellAnomaly, FleetResponse, SystemInfo } from "./api/types";
import TopBar from "./components/TopBar";
import HomeView from "./components/HomeView";
import FleetOverview from "./components/FleetOverview";
import ValidationView from "./components/ValidationView";
import BuildView from "./components/BuildView";
import WiresView from "./components/WiresView";
import WiresValidationView from "./components/WiresValidationView";
import LightsView from "./components/LightsView";
import LightsValidationView from "./components/LightsValidationView";
import Footer from "./components/Footer";
import HealthBanner from "./components/HealthBanner";
import StatTile from "./components/StatTile";
import CellHeatmap from "./components/CellHeatmap";
import TrendChart from "./components/TrendChart";
import EventLog from "./components/EventLog";
import AnomalyPanel from "./components/AnomalyPanel";
import DiagnosisCard from "./components/DiagnosisCard";
import { anomalyLevel, faultLabel, imbalanceLevel, safetyLevel, tempLevel, worst } from "./lib/status";
import type { View } from "./lib/sections";

export default function App() {
  const [view, setView] = useState<View>("home");
  const [systems, setSystems] = useState<SystemInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [fleet, setFleet] = useState<FleetResponse | null>(null);

  // The registry (with per-system config) backs the detail-view selector.
  useEffect(() => {
    let active = true;
    const load = () =>
      fetchSystems()
        .then((s) => {
          if (!active) return;
          setSystems(s);
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  // Fleet rollup, polled while the overview is showing.
  const refreshFleet = () =>
    fetchFleet()
      .then(setFleet)
      .catch(() => {});
  useEffect(() => {
    if (view !== "fleet") return;
    let active = true;
    const load = () =>
      fetchFleet()
        .then((f) => {
          if (active) setFleet(f);
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [view]);

  const openSystem = (id: string) => {
    setSelected(id);
    setView("system");
  };

  const { connected, latest, series, events, anomaly, anomalySeries, assessment } =
    useTelemetry(selected);
  const tel = latest?.telemetry ?? null;

  const selectedSystem = systems.find((s) => s.system_id === selected) ?? null;
  const [nSeries, nParallel] = useMemo(() => {
    const pack = (selectedSystem?.config as any)?.pack;
    if (pack?.series && pack?.parallel) return [pack.series, pack.parallel] as const;
    if (tel?.cells?.length) {
      return [
        Math.max(...tel.cells.map((c) => c.series_index)) + 1,
        Math.max(...tel.cells.map((c) => c.parallel_index)) + 1,
      ] as const;
    }
    return [0, 0] as const;
  }, [selectedSystem, tel]);

  const anomalyMap = useMemo(() => {
    const m = new Map<string, CellAnomaly>();
    for (const c of anomaly?.cells ?? []) m.set(`${c.series_index}-${c.parallel_index}`, c);
    return m;
  }, [anomaly]);

  const anomLevel = anomaly ? anomalyLevel(anomaly.max_score) : "good";
  const safeLevel = assessment ? safetyLevel(assessment.safety_state) : "good";
  const diag = assessment?.diagnosis;
  const level = tel
    ? worst(tempLevel(tel.max_temp_c), imbalanceLevel(tel.voltage_imbalance_v), anomLevel, safeLevel)
    : "good";
  const reason = tel
    ? assessment?.safety_state === "alarm"
      ? `SAFETY ALARM — thermal-runaway conditions at module ${diag?.cell_series} · slot ${diag?.cell_parallel}`
      : diag && diag.fault_type !== "none"
        ? `${faultLabel(diag.fault_type)} at module ${diag.cell_series} · slot ${diag.cell_parallel} (${(diag.confidence * 100).toFixed(0)}% confidence)`
        : anomaly && anomLevel !== "good"
          ? `Early warning: module ${anomaly.worst_series} · slot ${anomaly.worst_parallel} deviating on ${anomaly.worst_driver} (${anomaly.max_score.toFixed(1)} σ)`
          : "All cells within nominal temperature, balance, and peer behavior."
    : "Waiting for telemetry…";

  return (
    <div className="min-h-full flex flex-col bg-plane">
      <TopBar
        view={view}
        systems={systems}
        selected={selected}
        onHome={() => setView("home")}
        onNavigate={(v) => setView(v)}
        connected={connected}
      />

      <main className="flex-1 p-6 flex flex-col gap-4 w-full mx-auto max-w-[1400px]">
        {view === "home" ? (
          <HomeView onOpen={(v) => setView(v)} />
        ) : view === "build" ? (
          <BuildView
            onStarted={() => {
              refreshFleet();
              setView("fleet");
            }}
          />
        ) : view === "wires" ? (
          <WiresView />
        ) : view === "wiresvalidation" ? (
          <WiresValidationView />
        ) : view === "lights" ? (
          <LightsView />
        ) : view === "lightsvalidation" ? (
          <LightsValidationView />
        ) : view === "validation" ? (
          <ValidationView />
        ) : view === "fleet" ? (
          <FleetOverview
            fleet={fleet}
            onSelect={openSystem}
            onRefresh={refreshFleet}
            onBuild={() => setView("build")}
          />
        ) : !tel ? (
          <div className="flex-1 flex items-center justify-center text-muted">
            {selected ? "Connecting to telemetry stream…" : "No systems registered yet."}
          </div>
        ) : (
          <>
            <HealthBanner level={level} reason={reason} simTimeS={tel.time_s} />

            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
              <StatTile label="Pack voltage" value={tel.pack_voltage_v.toFixed(1)} unit="V" />
              <StatTile label="Pack power" value={(tel.pack_power_w / 1000).toFixed(2)} unit="kW" />
              <StatTile label="State of charge" value={(tel.pack_soc * 100).toFixed(1)} unit="%" />
              <StatTile
                label="Max cell temp"
                value={tel.max_temp_c.toFixed(1)}
                unit="°C"
                level={tempLevel(tel.max_temp_c)}
              />
              <StatTile
                label="Anomaly score"
                value={anomaly ? anomaly.max_score.toFixed(1) : "—"}
                unit="σ"
                level={anomLevel}
              />
            </div>

            {tel.weather && (
              <div className="rounded-lg bg-surface border border-hairline px-4 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
                <span className="text-xs uppercase tracking-wide text-muted">Weather</span>
                <span className="text-ink-secondary">
                  Ambient <span className="text-ink tnums">{tel.weather.air_temp_c.toFixed(1)} °C</span>
                </span>
                <span className="text-ink-secondary">
                  Wind <span className="text-ink tnums">{tel.weather.wind_speed_ms.toFixed(1)} m/s</span>
                </span>
                <span className="text-ink-secondary">
                  Solar <span className="text-ink tnums">{tel.weather.solar_w_m2.toFixed(0)} W/m²</span>
                </span>
                {tel.weather.humidity_frac != null && (
                  <span className="text-ink-secondary">
                    Humidity <span className="text-ink tnums">{(tel.weather.humidity_frac * 100).toFixed(0)} %</span>
                  </span>
                )}
                <span className="text-xs text-muted ml-auto">source: {tel.weather.source}</span>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2">
                <CellHeatmap
                  cells={tel.cells}
                  series={nSeries}
                  parallel={nParallel}
                  anomalies={anomalyMap}
                />
              </div>
              <div className="lg:col-span-1 flex flex-col gap-4">
                <DiagnosisCard report={assessment} />
                <AnomalyPanel report={anomaly} />
                <EventLog events={events} />
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <TrendChart
                title="State of charge"
                data={series}
                dataKey="soc"
                color="#3987e5"
                unit="%"
                domain={[0, 100]}
                precision={0}
              />
              <TrendChart
                title="Max cell temperature"
                data={series}
                dataKey="maxTemp"
                color="#eda100"
                unit="°C"
                domain={["auto", "auto"]}
                precision={1}
              />
              <TrendChart
                title="Anomaly score"
                data={anomalySeries}
                dataKey="maxScore"
                color="#9085e9"
                unit="σ"
                domain={[0, "auto"]}
                precision={1}
              />
            </div>
          </>
        )}
      </main>

      <Footer />
    </div>
  );
}
