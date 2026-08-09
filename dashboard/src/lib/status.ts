// Health status derivation. Status colors are reserved and always paired with a
// label + icon, never carried by color alone.

export type Level = "good" | "warning" | "serious" | "critical";

export const LEVEL_ORDER: Record<Level, number> = {
  good: 0,
  warning: 1,
  serious: 2,
  critical: 3,
};

export const LEVEL_COLOR: Record<Level, string> = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

export const LEVEL_ICON: Record<Level, string> = {
  good: "✓",
  warning: "!",
  serious: "▲",
  critical: "✕",
};

export const LEVEL_LABEL: Record<Level, string> = {
  good: "Healthy",
  warning: "Warning",
  serious: "Serious",
  critical: "Critical",
};

// Thresholds (Celsius / volts). Cell safe max is 60 C in the default config.
export function tempLevel(maxTempC: number): Level {
  if (maxTempC >= 58) return "critical";
  if (maxTempC >= 52) return "serious";
  if (maxTempC >= 45) return "warning";
  return "good";
}

export function imbalanceLevel(imbalanceV: number): Level {
  if (imbalanceV >= 0.12) return "serious";
  if (imbalanceV >= 0.07) return "warning";
  return "good";
}

// Anomaly-score thresholds mirror the detector's (simura.detect.engine).
export function anomalyLevel(score: number): Level {
  if (score >= 6) return "critical";
  if (score >= 4.5) return "serious";
  if (score >= 3) return "warning";
  return "good";
}

// Safety state (from the assessment) mapped to a display level.
export function safetyLevel(state: string): Level {
  if (state === "alarm") return "critical";
  if (state === "warning") return "warning";
  return "good";
}

// Human-readable fault-type labels.
export const FAULT_LABEL: Record<string, string> = {
  none: "No fault",
  unknown: "Unclassified anomaly",
  internal_short: "Internal short",
  cooling_fault: "Cooling fault",
  resistance_growth: "Resistance growth",
  sensor_fault: "Sensor fault",
  thermal_runaway: "Thermal runaway",
};

export function faultLabel(fault: string): string {
  return FAULT_LABEL[fault] ?? fault;
}

export function worst(...levels: Level[]): Level {
  return levels.reduce((a, b) => (LEVEL_ORDER[b] > LEVEL_ORDER[a] ? b : a), "good");
}
