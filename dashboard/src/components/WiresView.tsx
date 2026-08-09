import { useEffect, useState } from "react";
import { evaluateWire, fetchWireCatalog, recommendWire } from "../api/client";
import type { RunAssessment, Recommendation, WireCatalog } from "../api/types";
import StatTile from "./StatTile";
import { NumField, ProblemList, Row, Section, SelectField, Toggle } from "./formkit";

// Wires view: a wiring planner over simura.wires. Pick a wire and a load and
// check it (ampacity / voltage drop / temperature), or let the catalog size the
// smallest adequate gauge. Below, the selectable wire catalog.
export default function WiresView() {
  const [catalog, setCatalog] = useState<WireCatalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [material, setMaterial] = useState("copper");
  const [awg, setAwg] = useState(12);
  const [insulation, setInsulation] = useState("THHN-90");
  const [length, setLength] = useState(20);
  const [current, setCurrent] = useState(15);
  const [voltage, setVoltage] = useState(12);
  const [maxDrop, setMaxDrop] = useState(3);
  const [ambient, setAmbient] = useState(25);
  const [roundTrip, setRoundTrip] = useState(true);

  const [assessment, setAssessment] = useState<RunAssessment | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchWireCatalog()
      .then(setCatalog)
      .catch((e) => setLoadError(String(e)));
  }, []);

  if (loadError) return <div className="text-sm text-critical">Couldn't load wire catalog: {loadError}</div>;
  if (!catalog) return <div className="text-muted">Loading wires…</div>;

  const run = (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    fn().catch((e) => setErr(String(e?.message ?? e))).finally(() => setBusy(false));
  };

  const evaluate = () =>
    run(async () => {
      setRec(null);
      const a = await evaluateWire({
        spec: { material, awg, length_m: length, insulation, ambient_temp_c: ambient },
        current_a: current,
        system_voltage_v: voltage,
        max_drop_pct: maxDrop,
        round_trip: roundTrip,
      });
      setAssessment(a);
    });

  const recommend = () =>
    run(async () => {
      setAssessment(null);
      const r = await recommendWire({
        current_a: current,
        length_m: length,
        system_voltage_v: voltage,
        max_drop_pct: maxDrop,
        material,
        ambient_c: ambient,
        round_trip: roundTrip,
      });
      setRec(r);
    });

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Wiring planner</h2>
        <p className="text-sm text-ink-secondary mt-1 max-w-3xl">
          Physics-based wire sizing over <span className="text-ink">simura.wires</span>. Describe a
          run and a load, then <span className="text-ink">check</span> it against ampacity, voltage
          drop and the insulation's temperature rating — or let the catalog{" "}
          <span className="text-ink">recommend</span> the smallest adequate gauge. Round-trip counts
          both conductors of a two-wire DC circuit.
        </p>
      </div>

      <Section title="Run & load">
        <Row>
          <SelectField label="Material" value={material} options={catalog.materials} onChange={setMaterial} />
          <NumField label="Gauge (AWG)" value={awg} step={1} onChange={(v) => setAwg(Math.round(v))} />
          <SelectField label="Insulation" value={insulation} options={catalog.insulations} onChange={setInsulation} />
          <NumField label="Length (m)" value={length} step={1} onChange={setLength} />
        </Row>
        <Row>
          <NumField label="Current (A)" value={current} step={1} onChange={setCurrent} />
          <NumField label="System V" value={voltage} step={1} onChange={setVoltage} />
          <NumField label="Max drop %" value={maxDrop} step={0.5} onChange={setMaxDrop} />
          <NumField label="Ambient °C" value={ambient} step={1} onChange={setAmbient} />
          <Toggle label="Round-trip (2 conductors)" checked={roundTrip} onChange={setRoundTrip} />
        </Row>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={evaluate}
            disabled={busy}
            className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
          >
            {busy ? "…" : "Check this wire"}
          </button>
          <button
            type="button"
            onClick={recommend}
            disabled={busy}
            className="rounded-md border border-series px-3 py-1.5 text-sm font-medium text-series hover:bg-surface-2 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50"
            title="Smallest catalog gauge of this material that satisfies the constraints"
          >
            Recommend a gauge
          </button>
          {err && <span className="text-sm text-critical">{err}</span>}
        </div>
      </Section>

      {assessment && <AssessmentPanel a={assessment} />}
      {rec && <RecommendPanel rec={rec} onUse={(w) => { setMaterial(w.material); setAwg(w.awg); setInsulation(w.insulation); }} />}

      <CatalogTable catalog={catalog} />
    </div>
  );
}

function AssessmentPanel({ a }: { a: RunAssessment }) {
  const tempLevel = a.steady_state_temp_c > a.temp_rating_c ? "critical" : "good";
  const ampLevel = a.ampacity_utilization > 1 ? "critical" : a.ampacity_utilization > 0.8 ? "warning" : "good";
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-ink">Assessment</h3>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatTile label="Resistance" value={(a.resistance_ohm * 1000).toFixed(1)} unit="mΩ" />
        <StatTile
          label="Voltage drop"
          value={a.voltage_drop_pct != null ? a.voltage_drop_pct.toFixed(1) : a.voltage_drop_v.toFixed(2)}
          unit={a.voltage_drop_pct != null ? "%" : "V"}
        />
        <StatTile label="Power loss" value={a.power_loss_w.toFixed(1)} unit="W" />
        <StatTile label="Conductor temp" value={a.steady_state_temp_c.toFixed(0)} unit="°C" level={tempLevel} />
        <StatTile label="Ampacity" value={(a.ampacity_utilization * 100).toFixed(0)} unit="%" level={ampLevel} />
      </div>
      <ProblemList problems={a.problems} okText="Within ampacity, voltage-drop and temperature limits." />
    </div>
  );
}

function RecommendPanel({
  rec,
  onUse,
}: {
  rec: Recommendation;
  onUse: (w: NonNullable<Recommendation["wire_type"]>) => void;
}) {
  return (
    <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-ink">Recommendation</h3>
      {rec.wire_type ? (
        <div className="flex flex-wrap items-center gap-3">
          <span
            className="text-sm font-medium px-2 py-1 rounded-md"
            style={{ backgroundColor: rec.ok ? "#0ca30c22" : "#c0392b22", color: rec.ok ? "#7fd97f" : "#eab0a6" }}
          >
            {rec.wire_type.id}
          </span>
          <span className="text-sm text-ink">{rec.wire_type.name}</span>
          <button
            type="button"
            onClick={() => onUse(rec.wire_type!)}
            className="text-xs rounded border border-hairline px-2 py-1 text-ink-secondary hover:text-ink hover:bg-surface-2"
          >
            Use in planner
          </button>
        </div>
      ) : null}
      <p className={`text-sm ${rec.ok ? "text-ink-secondary" : "text-critical"}`}>{rec.rationale}</p>
    </div>
  );
}

function CatalogTable({ catalog }: { catalog: WireCatalog }) {
  return (
    <Section title={`Wire catalog (${catalog.wire_types.length})`}>
      <p className="text-xs text-muted -mt-1">
        Reference single-conductor free-air ampacity — size real wiring against the applicable code.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left tnums">
          <thead className="text-xs uppercase text-muted border-b border-hairline">
            <tr>
              <th className="py-2 pr-4">ID</th>
              <th className="py-2 pr-4">Material</th>
              <th className="py-2 pr-4 text-right">AWG</th>
              <th className="py-2 pr-4 text-right">mm²</th>
              <th className="py-2 pr-4">Insulation</th>
              <th className="py-2 pr-4 text-right">Rating °C</th>
              <th className="py-2 pr-4 text-right">Ampacity A</th>
              <th className="py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {catalog.wire_types.map((w) => (
              <tr key={w.id} className="border-b border-hairline/50">
                <td className="py-1.5 pr-4 text-ink">{w.id}</td>
                <td className="py-1.5 pr-4 text-ink-secondary">{w.material}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{w.awg <= 0 ? `${1 - w.awg}/0` : w.awg}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{w.area_mm2.toFixed(2)}</td>
                <td className="py-1.5 pr-4 text-ink-secondary">{w.insulation}</td>
                <td className="py-1.5 pr-4 text-right text-ink-secondary">{w.temp_rating_c.toFixed(0)}</td>
                <td className="py-1.5 pr-4 text-right text-ink">{w.ampacity_a.toFixed(0)}</td>
                <td className="py-1.5 text-muted">{w.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
