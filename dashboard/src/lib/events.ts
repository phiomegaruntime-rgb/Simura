// Client-side fault timeline: emit an event whenever a health category changes
// level, so the operator sees "temperature -> warning at 12:04:31", not a wall
// of numbers.

import type { AnomalyReport, AssessmentReport, PackTelemetry } from "../api/types";
import {
  anomalyLevel,
  faultLabel,
  imbalanceLevel,
  Level,
  LEVEL_LABEL,
  safetyLevel,
  tempLevel,
} from "./status";

export interface TwinEvent {
  id: number;
  time: number; // wall-clock ms
  category: "temperature" | "imbalance" | "anomaly" | "diagnosis" | "safety";
  level: Level;
  message: string;
}

export interface EventTracker {
  temp: Level;
  imbalance: Level;
  anomaly: Level;
  fault: string;
  safety: string;
  nextId: number;
}

export function newTracker(): EventTracker {
  return { temp: "good", imbalance: "good", anomaly: "good", fault: "none", safety: "nominal", nextId: 1 };
}

/** Emit events when the diagnosis or safety state changes. */
export function deriveAssessmentEvents(
  tracker: EventTracker,
  report: AssessmentReport,
  timeMs: number
): TwinEvent[] {
  const events: TwinEvent[] = [];
  const d = report.diagnosis;

  if (d.fault_type !== tracker.fault && d.fault_type !== "none") {
    events.push({
      id: tracker.nextId++,
      time: timeMs,
      category: "diagnosis",
      level: safetyLevel(report.safety_state) === "good" ? "warning" : safetyLevel(report.safety_state),
      message: `Diagnosis: ${faultLabel(d.fault_type)} at module ${d.cell_series} · slot ${d.cell_parallel} (${(d.confidence * 100).toFixed(0)}% confidence)`,
    });
  }
  tracker.fault = d.fault_type;

  if (report.safety_state !== tracker.safety) {
    if (report.safety_state === "alarm") {
      events.push({
        id: tracker.nextId++,
        time: timeMs,
        category: "safety",
        level: "critical",
        message: "SAFETY ALARM: thermal-runaway conditions detected",
      });
    } else if (report.safety_state === "nominal" && tracker.safety === "alarm") {
      events.push({
        id: tracker.nextId++,
        time: timeMs,
        category: "safety",
        level: "good",
        message: "Safety alarm cleared",
      });
    }
    tracker.safety = report.safety_state;
  }
  return events;
}

/** Emit an event when the pack's worst anomaly level changes. */
export function deriveAnomalyEvents(
  tracker: EventTracker,
  report: AnomalyReport,
  timeMs: number
): TwinEvent[] {
  const level = anomalyLevel(report.max_score);
  if (level === tracker.anomaly) return [];
  tracker.anomaly = level;
  const cell = `module ${report.worst_series} · slot ${report.worst_parallel}`;
  return [
    {
      id: tracker.nextId++,
      time: timeMs,
      category: "anomaly",
      level,
      message:
        level === "good"
          ? `Anomaly cleared (${cell})`
          : `Anomaly ${LEVEL_LABEL[level]}: ${cell} — ${report.worst_driver} (score ${report.max_score.toFixed(1)})`,
    },
  ];
}

/** Compare a new frame against tracked levels; return any newly-crossed events. */
export function deriveEvents(
  tracker: EventTracker,
  tel: PackTelemetry,
  timeMs: number
): TwinEvent[] {
  const events: TwinEvent[] = [];

  const t = tempLevel(tel.max_temp_c);
  if (t !== tracker.temp) {
    events.push({
      id: tracker.nextId++,
      time: timeMs,
      category: "temperature",
      level: t,
      message:
        t === "good"
          ? `Temperature recovered to ${LEVEL_LABEL[t]} (${tel.max_temp_c.toFixed(1)} °C)`
          : `Temperature ${LEVEL_LABEL[t]}: max cell ${tel.max_temp_c.toFixed(1)} °C`,
    });
    tracker.temp = t;
  }

  const im = imbalanceLevel(tel.voltage_imbalance_v);
  if (im !== tracker.imbalance) {
    events.push({
      id: tracker.nextId++,
      time: timeMs,
      category: "imbalance",
      level: im,
      message:
        im === "good"
          ? `Cell balance recovered (${(tel.voltage_imbalance_v * 1000).toFixed(0)} mV spread)`
          : `Cell imbalance ${LEVEL_LABEL[im]}: ${(tel.voltage_imbalance_v * 1000).toFixed(0)} mV spread`,
    });
    tracker.imbalance = im;
  }

  return events;
}
