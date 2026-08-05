// Sequential color ramps for the cell heatmap.
//
// On a dark surface a magnitude ramp runs low = recedes into the surface -> high
// = bright, so the eye is drawn to the hot/extreme cells. Temperature uses a warm
// (amber -> red) ramp so an overheating cell literally glows; voltage and SoC use
// the design system's blue sequential hue. Exact values are always shown on hover,
// so color never carries meaning alone.

type RGB = [number, number, number];

function hexToRgb(hex: string): RGB {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function rgbToHex([r, g, b]: RGB): string {
  const c = (n: number) => Math.round(n).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Interpolate through an ordered list of hex stops; `t` in [0, 1]. */
export function rampColor(stops: string[], t: number): string {
  const clamped = Math.min(1, Math.max(0, t));
  const scaled = clamped * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(scaled));
  const local = scaled - i;
  const a = hexToRgb(stops[i]);
  const b = hexToRgb(stops[i + 1]);
  return rgbToHex([
    lerp(a[0], b[0], local),
    lerp(a[1], b[1], local),
    lerp(a[2], b[2], local),
  ]);
}

// Ramp stops (evenly spaced across the domain).
//
// Temperature runs over an absolute 20–60 °C scale, so the stops are weighted to
// stay calm/neutral through the healthy band (≈20–40 °C) and only bloom into
// amber → red as a cell approaches its safe limit. Voltage/SoC use the design
// system's blue sequential hue over their (relative) range.
export const RAMPS = {
  temp: ["#232322", "#232322", "#3a2f14", "#8a5a12", "#eda100", "#d03b3b"],
  voltage: ["#14243a", "#256abf", "#86b6ef"],
  soc: ["#14243a", "#256abf", "#86b6ef"],
  // Anomaly score uses a distinct violet ramp so it never reads as temperature.
  anomaly: ["#232322", "#2f2352", "#4a3aa7", "#9085e9"],
} as const;

export type MetricKey = keyof typeof RAMPS;

export const METRIC_LABEL: Record<MetricKey, string> = {
  temp: "Temperature (°C)",
  voltage: "Voltage (V)",
  soc: "State of charge",
  anomaly: "Anomaly score (σ)",
};
