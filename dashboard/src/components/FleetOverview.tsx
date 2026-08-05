import { useState } from "react";
import {
  createSystem,
  deleteSystem,
  pauseSystem,
  resumeSystem,
  startSystem,
} from "../api/client";
import type { FleetResponse, FleetSystem } from "../api/types";
import type { Level } from "../lib/status";
import { LEVEL_COLOR, LEVEL_ICON, LEVEL_LABEL, faultLabel } from "../lib/status";

interface Props {
  fleet: FleetResponse | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
  onBuild: () => void;
}

// Fleet overview: every system rolled up to one status at a glance, worst-first,
// with lifecycle controls (Component 10). Clicking a card drills into its live
// dashboard; the action row starts/pauses/resumes/deletes it.
export default function FleetOverview({ fleet, onSelect, onRefresh, onBuild }: Props) {
  const [showNew, setShowNew] = useState(false);

  if (!fleet) {
    return <div className="flex-1 flex items-center justify-center text-muted">Loading fleet…</div>;
  }

  const { summary } = fleet;
  const order: Level[] = ["critical", "serious", "warning", "good"];

  return (
    <div className="flex flex-col gap-4">
      {/* Summary strip */}
      <div className="rounded-lg bg-surface border border-hairline px-5 py-4 flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">Systems</div>
          <div className="text-2xl font-semibold text-ink tnums">
            {summary.total}
            <span className="text-sm text-ink-secondary font-normal"> · {summary.live} live</span>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {order.map((lvl) => (
            <StatusCount key={lvl} level={lvl} count={summary.counts[lvl] ?? 0} />
          ))}
        </div>
        <div className="ml-auto flex items-center gap-4">
          {summary.alarms > 0 && (
            <div className="flex items-center gap-2 text-critical">
              <span
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold"
                style={{ backgroundColor: LEVEL_COLOR.critical, color: "#0d0d0d" }}
              >
                {LEVEL_ICON.critical}
              </span>
              <span className="text-sm font-medium">
                {summary.alarms} safety {summary.alarms === 1 ? "alarm" : "alarms"}
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowNew(true)}
            className="rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90 focus:outline-none focus:ring-1 focus:ring-series"
          >
            + New system
          </button>
        </div>
      </div>

      {fleet.systems.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-muted py-16">
          No systems yet. Use <span className="text-ink mx-1">+ New system</span> to add one.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {fleet.systems.map((s) => (
            <SystemCard key={s.system_id} sys={s} onSelect={onSelect} onRefresh={onRefresh} />
          ))}
        </div>
      )}

      {showNew && (
        <NewSystemModal
          onClose={() => setShowNew(false)}
          onRefresh={onRefresh}
          onBuild={() => {
            setShowNew(false);
            onBuild();
          }}
        />
      )}
    </div>
  );
}

function StatusCount({ level, count }: { level: Level; count: number }) {
  const dim = count === 0;
  return (
    <div className="flex items-center gap-1.5 text-sm" style={{ opacity: dim ? 0.4 : 1 }}>
      <span
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold"
        style={{ backgroundColor: LEVEL_COLOR[level], color: "#0d0d0d" }}
      >
        {LEVEL_ICON[level]}
      </span>
      <span className="tnums text-ink">{count}</span>
      <span className="text-muted">{LEVEL_LABEL[level]}</span>
    </div>
  );
}

function SystemCard({
  sys,
  onSelect,
  onRefresh,
}: {
  sys: FleetSystem;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const level = sys.status as Level;
  const color = LEVEL_COLOR[level];
  const fault = sys.fault_type && sys.fault_type !== "none" ? faultLabel(sys.fault_type) : null;
  const isSim = sys.source === "simulation";

  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const act = (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    fn()
      .then(() => onRefresh())
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div
      className="text-left rounded-lg bg-surface border px-4 py-3 flex flex-col gap-3"
      style={{ borderColor: `${color}55` }}
    >
      <button
        type="button"
        onClick={() => onSelect(sys.system_id)}
        className="text-left flex items-start justify-between gap-2 focus:outline-none focus:ring-1 focus:ring-series rounded"
      >
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink truncate">{sys.name || sys.system_id}</div>
          <div className="text-xs text-muted truncate">{sys.system_id}</div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0" style={{ color }}>
          <span
            className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold"
            style={{ backgroundColor: color, color: "#0d0d0d" }}
          >
            {LEVEL_ICON[level]}
          </span>
          <span className="text-xs font-medium">{LEVEL_LABEL[level]}</span>
        </div>
      </button>

      <SourceBadge sys={sys} />

      <div className="text-xs text-ink-secondary leading-snug min-h-[2rem]">{sys.status_reason}</div>

      <div className="grid grid-cols-4 gap-2 pt-1 border-t border-hairline">
        <Metric label="SoC" value={fmt(sys.pack_soc, (v) => (v * 100).toFixed(0), "%")} />
        <Metric
          label="Temp"
          value={fmt(sys.max_temp_c, (v) => v.toFixed(1), "°")}
          color={sys.max_temp_c != null && sys.max_temp_c >= 45 ? color : undefined}
        />
        <Metric label="Anom" value={fmt(sys.anomaly_score, (v) => v.toFixed(1), "σ")} />
        <Metric label="SoH" value={fmt(sys.pack_soh, (v) => (v * 100).toFixed(0), "%")} />
      </div>

      {fault && <div className="text-xs text-muted truncate">{fault}</div>}

      {/* Lifecycle actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-hairline flex-wrap">
        {isSim ? (
          <>
            {sys.run_state === "running" ? (
              <ActionBtn label="Pause" disabled={busy} onClick={() => act(() => pauseSystem(sys.system_id))} />
            ) : (
              <ActionBtn
                label={sys.run_state === "paused" ? "Resume" : "Start"}
                primary
                disabled={busy}
                onClick={() =>
                  act(() =>
                    sys.run_state === "paused" ? resumeSystem(sys.system_id) : startSystem(sys.system_id)
                  )
                }
              />
            )}
          </>
        ) : (
          <span className="text-[11px] text-muted mr-auto">external feed · view only</span>
        )}

        {confirming ? (
          <span className="flex items-center gap-1.5 ml-auto">
            <span className="text-[11px] text-critical">Delete + purge history?</span>
            <ActionBtn label="Yes" danger disabled={busy} onClick={() => act(() => deleteSystem(sys.system_id))} />
            <ActionBtn label="No" disabled={busy} onClick={() => setConfirming(false)} />
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy}
            className={`text-xs text-critical hover:underline disabled:opacity-50 ${isSim ? "ml-auto" : ""}`}
          >
            Delete
          </button>
        )}
      </div>
      {err && <div className="text-[11px] text-critical">{err}</div>}
    </div>
  );
}

function SourceBadge({ sys }: { sys: FleetSystem }) {
  const isSim = sys.source === "simulation";
  const color = isSim ? "#9085e9" : "#3987e5";
  const label = isSim ? "SIM" : "LIVE";
  const runLabel =
    isSim && sys.run_state ? sys.run_state : sys.live ? "streaming" : "offline";
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span
        className="font-semibold uppercase tracking-wide rounded px-1.5 py-0.5"
        style={{ backgroundColor: `${color}22`, color }}
      >
        {label}
      </span>
      <span className="text-muted">
        {runLabel}
        {sys.live ? "" : isSim && sys.run_state === "running" ? " · starting…" : ""}
      </span>
      <span className="ml-auto flex items-center gap-1.5">
        <span
          className={`h-2 w-2 rounded-full ${sys.live ? "bg-good" : "bg-muted"}`}
          style={sys.live ? { boxShadow: "0 0 6px #0ca30c" } : undefined}
        />
        <span className={sys.live ? "text-good" : "text-muted"}>{sys.live ? "Live" : "Offline"}</span>
      </span>
    </div>
  );
}

function ActionBtn({
  label,
  onClick,
  disabled,
  primary,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
}) {
  const base = "text-xs rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-series disabled:opacity-50";
  const style = danger
    ? "bg-critical text-plane hover:opacity-90"
    : primary
      ? "bg-series text-plane hover:opacity-90"
      : "border border-hairline text-ink-secondary hover:text-ink hover:bg-surface-2";
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${style}`}>
      {label}
    </button>
  );
}

function NewSystemModal({
  onClose,
  onRefresh,
  onBuild,
}: {
  onClose: () => void;
  onRefresh: () => void;
  onBuild: () => void;
}) {
  const [systemId, setSystemId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const registerRealtime = () => {
    if (!systemId.trim()) {
      setErr("Enter a system id");
      return;
    }
    setBusy(true);
    setErr(null);
    createSystem({ source: "realtime", system_id: systemId.trim(), name: name.trim() || undefined })
      .then(() => {
        onRefresh();
        onClose();
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg bg-surface border border-hairline p-5 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-ink">Add a system</h3>
          <button type="button" onClick={onClose} className="text-muted hover:text-ink text-sm">
            ✕
          </button>
        </div>

        {/* Simulation */}
        <div className="rounded-md bg-surface-2 border border-hairline p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] font-semibold uppercase rounded px-1.5 py-0.5"
              style={{ backgroundColor: "#9085e922", color: "#9085e9" }}
            >
              SIM
            </span>
            <span className="text-sm font-medium text-ink">Simulation (twin-core run)</span>
          </div>
          <p className="text-xs text-ink-secondary">
            Design a battery system on the Build tab, preview it, then <span className="text-ink">Start in
            fleet</span> — the twin core runs it and you control start/pause/resume here.
          </p>
          <button
            type="button"
            onClick={onBuild}
            className="self-start rounded-md bg-series px-3 py-1.5 text-sm font-medium text-plane hover:opacity-90"
          >
            Build a simulation →
          </button>
        </div>

        {/* Real-time */}
        <div className="rounded-md bg-surface-2 border border-hairline p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] font-semibold uppercase rounded px-1.5 py-0.5"
              style={{ backgroundColor: "#3987e522", color: "#3987e5" }}
            >
              LIVE
            </span>
            <span className="text-sm font-medium text-ink">Real-time feed</span>
          </div>
          <p className="text-xs text-ink-secondary">
            Register a system id to expect from an external source (a publisher, a connector, or a
            real BMS). It goes live when data arrives on that id.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-ink-secondary">
              System ID
              <input
                value={systemId}
                onChange={(e) => setSystemId(e.target.value)}
                placeholder="bess-03"
                className="bg-surface border border-hairline rounded-md px-2 py-1 text-ink text-sm w-40 focus:outline-none focus:ring-1 focus:ring-series"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-secondary">
              Name (optional)
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Rack C"
                className="bg-surface border border-hairline rounded-md px-2 py-1 text-ink text-sm w-40 focus:outline-none focus:ring-1 focus:ring-series"
              />
            </label>
            <button
              type="button"
              onClick={registerRealtime}
              disabled={busy}
              className="rounded-md border border-hairline px-3 py-1.5 text-sm text-ink-secondary hover:text-ink hover:bg-surface disabled:opacity-50"
            >
              {busy ? "Registering…" : "Register"}
            </button>
          </div>
        </div>

        {err && <div className="text-sm text-critical">{err}</div>}
      </div>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className="text-sm tnums" style={{ color: color ?? undefined }}>
        {value}
      </span>
    </div>
  );
}

function fmt(v: number | null, f: (v: number) => string, unit = ""): string {
  return v == null ? "—" : `${f(v)}${unit}`;
}
