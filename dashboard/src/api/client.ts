import type {
  BuilderOptions,
  CreateSystemPayload,
  DatasetSpec,
  FaultSpec,
  FleetResponse,
  InstallationAssessment,
  LampRecommendation,
  LayoutResult,
  LightCatalog,
  LightFaultInput,
  LightOperateResponse,
  LightSimulationResult,
  LightSpecInput,
  LightStandardSpec,
  LightUploadOptions,
  LightValidationReport,
  LiveDaylightReport,
  NetworkResult,
  PreviewResult,
  Recommendation,
  SpectrumResponse,
  RunAssessment,
  SystemInfo,
  SystemSpec,
  TrendPoint,
  UploadOptions,
  ValidationReport,
  WeatherInput,
  WeatherSample,
  WireCatalog,
  WireFaultInput,
  WireStandardSpec,
  WireUploadOptions,
  WireValidationReport,
} from "./types";

// Same-origin in prod (nginx) and dev (Vite proxy), so no base URL is needed.

export async function fetchSystems(): Promise<SystemInfo[]> {
  const res = await fetch("/api/systems");
  if (!res.ok) throw new Error(`GET /api/systems failed: ${res.status}`);
  return res.json();
}

/** Whole-fleet rollup: one status row per system + a summary. */
export async function fetchFleet(): Promise<FleetResponse> {
  const res = await fetch("/api/fleet");
  if (!res.ok) throw new Error(`GET /api/fleet failed: ${res.status}`);
  return res.json();
}

// ---- system lifecycle (Component 10) ----

async function jsonOrThrow(res: Response, what: string) {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    } catch {
      /* keep status */
    }
    throw new Error(`${what}: ${detail}`);
  }
  return res.json();
}

/** Create a twin-core simulation or register a real-time system. */
export async function createSystem(payload: CreateSystemPayload) {
  const res = await fetch("/api/systems", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return jsonOrThrow(res, "create system");
}

async function control(systemId: string, action: "start" | "pause" | "resume") {
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}/${action}`, {
    method: "POST",
  });
  return jsonOrThrow(res, `${action} system`);
}

export const startSystem = (id: string) => control(id, "start");
export const pauseSystem = (id: string) => control(id, "pause");
export const resumeSystem = (id: string) => control(id, "resume");

/** Purge a system (stop its sim, delete registry row + all history). */
export async function deleteSystem(systemId: string) {
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}`, { method: "DELETE" });
  return jsonOrThrow(res, "delete system");
}

interface HistoryPoint {
  bucket: string;
  pack_soc: number | null;
  max_temp_c: number | null;
  pack_power_w: number | null;
  pack_voltage_v: number | null;
  voltage_imbalance_v: number | null;
}

interface HistoryResponse {
  points: HistoryPoint[];
}

/** The catalog of open battery datasets available to select and validate against. */
export async function fetchDatasets(): Promise<DatasetSpec[]> {
  const res = await fetch("/api/validation/datasets");
  if (!res.ok) throw new Error(`GET /api/validation/datasets failed: ${res.status}`);
  return res.json();
}

/**
 * Run the in-browser validation demonstration. The server validates the bundled
 * synthetic sample (it can't reach the user's local download) and says so via
 * `data_source`/`sample_dataset_id`.
 */
export async function runValidation(
  datasetId: string,
  fit = true
): Promise<ValidationReport> {
  const res = await fetch("/api/validation/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, fit }),
  });
  if (!res.ok) throw new Error(`POST /api/validation/run failed: ${res.status}`);
  return res.json();
}

/**
 * Validate the model against the user's own uploaded dataset file. Sends
 * multipart form data; the browser sets the boundary, so no Content-Type here.
 */
export async function uploadValidation(
  file: File,
  opts: UploadOptions = {}
): Promise<ValidationReport> {
  const form = new FormData();
  form.append("file", file);
  form.append("fit", String(opts.fit ?? true));
  if (opts.datasetId) form.append("dataset_id", opts.datasetId);
  if (opts.chemistry) form.append("chemistry", opts.chemistry);
  if (opts.timeCol) form.append("time_col", opts.timeCol);
  if (opts.currentCol) form.append("current_col", opts.currentCol);
  if (opts.voltageCol) form.append("voltage_col", opts.voltageCol);
  if (opts.tempCol) form.append("temp_col", opts.tempCol);
  if (opts.dischargePositive != null)
    form.append("discharge_positive", String(opts.dischargePositive));
  if (opts.currentScale != null) form.append("current_scale", String(opts.currentScale));
  if (opts.nominalCapacityAh != null)
    form.append("nominal_capacity_ah", String(opts.nominalCapacityAh));

  const res = await fetch("/api/validation/upload", { method: "POST", body: form });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status */
    }
    throw new Error(`Upload failed: ${detail}`);
  }
  return res.json();
}

// ---- System builder ----

/** Enumerations + a default spec for the builder form. */
export async function fetchBuilderOptions(): Promise<BuilderOptions> {
  const res = await fetch("/api/builder/options");
  if (!res.ok) throw new Error(`GET /api/builder/options failed: ${res.status}`);
  return res.json();
}

export interface PreviewError {
  errors: string[];
}

/**
 * Run a user's system spec offline. Resolves with the preview summary, or rejects
 * with a `{ errors }` object when the spec is invalid (HTTP 400).
 */
export async function previewSpec(spec: SystemSpec): Promise<PreviewResult> {
  const res = await fetch("/api/builder/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    const errors = body?.detail?.errors ?? ["invalid spec"];
    return Promise.reject({ errors } as PreviewError);
  }
  if (!res.ok) throw new Error(`POST /api/builder/preview failed: ${res.status}`);
  return res.json();
}

// ---- Weather places (geocoding) ----

export interface Place {
  name: string;
  latitude: number;
  longitude: number;
  country: string;
  admin1: string;
  timezone: string;
  elevation_m: number | null;
  label: string;
}

/**
 * Look up places by name, for pointing a live weather source at one.
 *
 * Proxied through the twin core rather than called from the browser, so the
 * dashboard keeps talking to exactly one origin. A failed lookup is an empty
 * list, never an exception — a site still runs on coordinates.
 */
export async function searchPlaces(query: string): Promise<Place[]> {
  const res = await fetch(`/api/weather/places?q=${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json();
}

/**
 * Evaluate a weather spec right now, with no system involved.
 *
 * A site needs to know what day it is in before it has anything to put in it —
 * and while a rack's telemetry carries the same thing, that only answers once a
 * rack exists and is streaming. Same providers, same answer, no prerequisites.
 */
export async function fetchWeatherSample(
  spec: { type: string; params: Record<string, number> }
): Promise<WeatherSample | null> {
  const res = await fetch("/api/weather/sample", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return body.weather ?? null;
}

// ---- Wires (Component 12) ----

/** The selectable wire catalog + materials/insulations for the Wires view. */
export async function fetchWireCatalog(): Promise<WireCatalog> {
  const res = await fetch("/api/wires/catalog");
  if (!res.ok) throw new Error(`GET /api/wires/catalog failed: ${res.status}`);
  return res.json();
}

export interface WireEvalBody {
  spec: { material?: string; awg?: number; length_m?: number; insulation?: string; ambient_temp_c?: number };
  current_a: number;
  system_voltage_v?: number;
  max_drop_pct?: number;
  round_trip?: boolean;
  weather?: WeatherInput;
}

/** Check one wire run against ampacity / voltage drop / temperature. */
export async function evaluateWire(body: WireEvalBody): Promise<RunAssessment> {
  const res = await fetch("/api/wires/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "evaluate wire");
}

export interface RecommendBody {
  current_a: number;
  length_m: number;
  system_voltage_v?: number;
  max_drop_pct?: number;
  material?: string;
  ambient_c?: number;
  round_trip?: boolean;
  weather?: WeatherInput;
}

/** Size the smallest catalog wire that satisfies the constraints. */
export async function recommendWire(body: RecommendBody): Promise<Recommendation> {
  const res = await fetch("/api/wires/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "recommend wire");
}

export interface NetworkBody {
  nodes: { id: string; voltage?: number; load_a?: number }[];
  segments: {
    id: string;
    from: string;
    to: string;
    wire: Record<string, unknown>;
    faults?: WireFaultInput[];
  }[];
  elapsed_s?: number;
}

/**
 * Solve a multi-node wire network by nodal analysis.
 *
 * Pure compute — no broker, no database — so a client can re-solve on every edit
 * and get the answer back within a frame or two.
 */
export async function solveNetwork(body: NetworkBody): Promise<NetworkResult> {
  const res = await fetch("/api/wires/network", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "solve network");
}

// ---- Live fault injection ----

export interface InjectFaultBody {
  type: string;
  series?: number;
  parallel?: number;
  params?: Record<string, number>;
}

/** Break a running pack: inject a fault effective on its next timestep. */
export async function injectFault(systemId: string, body: InjectFaultBody) {
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}/faults`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "inject fault");
}

/** The faults currently on a running pack, in the order they were applied. */
export async function fetchFaults(systemId: string): Promise<FaultSpec[]> {
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}/faults`);
  const body = await jsonOrThrow(res, "list faults");
  return body.faults ?? [];
}

/**
 * Repair one fault by its position in that list — a maintenance action rather
 * than starting the pack over.
 */
export async function removeFault(systemId: string, index: number) {
  const res = await fetch(
    `/api/systems/${encodeURIComponent(systemId)}/faults/${index}`,
    { method: "DELETE" }
  );
  return jsonOrThrow(res, "remove fault");
}

/** Repair a running pack: drop every fault on it. */
export async function clearFaults(systemId: string) {
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}/faults`, {
    method: "DELETE",
  });
  return jsonOrThrow(res, "clear faults");
}

// ---- Wire validation (against published standards) ----

/** The catalog of published conductor standards the model can be validated against. */
export async function fetchWireStandards(): Promise<WireStandardSpec[]> {
  const res = await fetch("/api/wires/validation/standards");
  if (!res.ok) throw new Error(`GET /api/wires/validation/standards failed: ${res.status}`);
  return res.json();
}

/**
 * Validate the wire model against one bundled reference standard: replay each
 * gauge through simura.wires and compare predicted DC resistance to the
 * published table.
 */
export async function runWireValidation(standardId: string): Promise<WireValidationReport> {
  const res = await fetch("/api/wires/validation/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ standard_id: standardId }),
  });
  if (!res.ok) throw new Error(`POST /api/wires/validation/run failed: ${res.status}`);
  return res.json();
}

/**
 * Validate the wire model against the user's own measured-resistance CSV. Sends
 * multipart form data; the browser sets the boundary, so no Content-Type here.
 */
export async function uploadWireValidation(
  file: File,
  opts: WireUploadOptions = {}
): Promise<WireValidationReport> {
  const form = new FormData();
  form.append("file", file);
  if (opts.material) form.append("material", opts.material);
  if (opts.awgCol) form.append("awg_col", opts.awgCol);
  if (opts.resistanceCol) form.append("resistance_col", opts.resistanceCol);
  if (opts.refTempC != null) form.append("ref_temp_c", String(opts.refTempC));
  if (opts.resistanceUnit) form.append("resistance_unit", opts.resistanceUnit);

  const res = await fetch("/api/wires/validation/upload", { method: "POST", body: form });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status */
    }
    throw new Error(`Upload failed: ${detail}`);
  }
  return res.json();
}

/** Seed the trend charts with recent history, downsampled to keep it light. */
export async function fetchHistory(
  systemId: string,
  minutes = 30,
  bucketS = 5
): Promise<TrendPoint[]> {
  const res = await fetch(
    `/api/systems/${encodeURIComponent(systemId)}/history?minutes=${minutes}&bucket_s=${bucketS}`
  );
  if (!res.ok) throw new Error(`GET history failed: ${res.status}`);
  const data: HistoryResponse = await res.json();
  return data.points
    .filter((p) => p.pack_soc != null)
    .map((p) => ({
      t: new Date(p.bucket).getTime(),
      soc: (p.pack_soc ?? 0) * 100,
      maxTemp: p.max_temp_c ?? 0,
      power: p.pack_power_w ?? 0,
      voltage: p.pack_voltage_v ?? 0,
      imbalance: p.voltage_imbalance_v ?? 0,
    }));
}

// ---- Lights (Component 14) ----

/** Technologies, lamps, faults, profiles, controls and lux targets, in one call. */
export async function fetchLightCatalog(): Promise<LightCatalog> {
  const res = await fetch("/api/lights/catalog");
  if (!res.ok) throw new Error(`GET /api/lights/catalog failed: ${res.status}`);
  return res.json();
}

export interface LightEvalBody {
  spec: LightSpecInput;
  n_luminaires: number;
  length_m: number;
  width_m: number;
  mounting_height_m?: number;
  task?: string;
  target_lux?: number;
  maintenance_hours?: number;
  dirt_frac?: number;
  ceiling_reflectance?: number;
  wall_reflectance?: number;
  floor_reflectance?: number;
  annual_hours?: number;
  weather?: WeatherInput;
}

/** Check one lighting design against illuminance, colour and installed power. */
export async function evaluateLighting(
  body: LightEvalBody
): Promise<InstallationAssessment> {
  const res = await fetch("/api/lights/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "evaluate lighting");
}

export interface LampRecommendBody {
  length_m: number;
  width_m: number;
  mounting_height_m?: number;
  task?: string;
  target_lux?: number;
  family?: string | null;
  maintenance_hours?: number;
  dirt_frac?: number;
  ceiling_reflectance?: number;
  wall_reflectance?: number;
  floor_reflectance?: number;
  annual_hours?: number;
  weather?: WeatherInput;
}

/**
 * Pick the catalog lamp that meets the target at the lowest installed power.
 *
 * Comes back with the ranked alternatives as well as the winner, because the
 * interesting part is the trade between technologies, not the answer alone.
 */
export async function recommendLamp(body: LampRecommendBody): Promise<LampRecommendation> {
  const res = await fetch("/api/lights/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "recommend lamp");
}

export interface LayoutBody {
  length_m: number;
  width_m: number;
  workplane_height_m?: number;
  grid_n?: number;
  grid?: { rows: number; cols: number; height_m: number; lamp: LightSpecInput; drive?: number };
  luminaires?: {
    id: string;
    x_m: number;
    y_m: number;
    height_m: number;
    lamp: LightSpecInput;
    drive?: number;
    faults?: LightFaultInput[];
  }[];
  target_lux?: number;
  min_uniformity?: number;
  elapsed_s?: number;
  include_interreflection?: boolean;
  weather?: WeatherInput;
}

/**
 * Solve the illuminance field over a room.
 *
 * Pure compute, like the wire network solve — no broker, no database — so a UI
 * can re-solve on every edit and get the grid back within a frame or two.
 */
export async function solveLayout(body: LayoutBody): Promise<LayoutResult> {
  const res = await fetch("/api/lights/layout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "solve layout");
}

/** One lamp's spectral power distribution, and everything derived from it. */
export async function fetchSpectrum(
  spec: LightSpecInput,
  drive = 1.0,
  ambientC?: number
): Promise<SpectrumResponse> {
  const res = await fetch("/api/lights/spectrum", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec, drive, ambient_c: ambientC }),
  });
  return jsonOrThrow(res, "fetch spectrum");
}

export interface LightSimulateBody {
  spec: LightSpecInput;
  profile?: { type: string; [param: string]: number | string };
  control?: { type: string; [param: string]: number | string };
  faults?: LightFaultInput[];
  weather?: { type: string; [param: string]: number | string };
  coupling?: Record<string, number | boolean>;
  dt_s?: number;
  duration_s?: number;
  mounting_height_m?: number;
  target_lux?: number;
  hours_per_second?: number;
  weather_epoch0?: number;
}

/** Run one luminaire through time — warm-up, thermal settle, controls, faults. */
export async function simulateLight(
  body: LightSimulateBody
): Promise<LightSimulationResult> {
  const res = await fetch("/api/lights/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "simulate light");
}

// ---- Light validation ----

/** The catalog of published references the lighting model can be checked against. */
export async function fetchLightStandards(): Promise<LightStandardSpec[]> {
  const res = await fetch("/api/lights/validation/standards");
  if (!res.ok) throw new Error(`GET /api/lights/validation/standards failed: ${res.status}`);
  return res.json();
}

/** Validate the lighting model against one bundled reference standard. */
export async function runLightValidation(
  standardId: string
): Promise<LightValidationReport> {
  const res = await fetch("/api/lights/validation/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ standard_id: standardId }),
  });
  return jsonOrThrow(res, "validate lighting model");
}

/**
 * Validate the daylight model against **live** measured irradiance.
 *
 * The one check in the dashboard whose reference data is different every time
 * it runs: it goes to Open-Meteo for the real sky over a real place. Slower than
 * the bundled standards, and it can fail if the network is down — which is why
 * the UI treats it separately rather than as a sixth card.
 */
export async function runLiveDaylightValidation(
  latitude: number,
  longitude: number,
  hours = 48
): Promise<LiveDaylightReport> {
  const res = await fetch("/api/lights/validation/live", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude, longitude, hours }),
  });
  return jsonOrThrow(res, "validate daylight live");
}

/** Validate the lighting model against the user's own measured CSV. */
export async function uploadLightValidation(
  file: File,
  opts: LightUploadOptions = {}
): Promise<LightValidationReport> {
  const form = new FormData();
  form.append("file", file);
  if (opts.quantity) form.append("quantity", opts.quantity);
  if (opts.xCol) form.append("x_col", opts.xCol);
  if (opts.valueCol) form.append("value_col", opts.valueCol);
  if (opts.keyCol) form.append("key_col", opts.keyCol);

  const res = await fetch("/api/lights/validation/upload", { method: "POST", body: form });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status */
    }
    throw new Error(`Upload failed: ${detail}`);
  }
  return res.json();
}

export interface LightOperateBody {
  lights: {
    id: string;
    spec: LightSpecInput;
    supply_voltage_v: number;
    drive?: number;
    height_m?: number;
    faults?: { type: string; [param: string]: number | string }[];
  }[];
  ambient_c?: number;
  elapsed_s?: number;
  weather?: WeatherInput;
}

/**
 * Solve many luminaires at once, each against the voltage it actually has.
 *
 * One call for a whole site, like `solveNetwork` — a site with twenty fittings
 * should not need twenty round trips. Pure compute, so it can run on
 * every edit alongside the wire solve it is coupled to.
 */
export async function operateLights(body: LightOperateBody): Promise<LightOperateResponse> {
  const res = await fetch("/api/lights/operate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "operate lights");
}
