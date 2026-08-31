import type {
  BuilderOptions,
  CreateSystemPayload,
  DatasetSpec,
  ExplainLenses,
  ExplainLevel,
  ExplainResponse,
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
  CableRoute,
  FloorPlan,
  LightingTarget,
  PlanSummary,
  SpaceContext,
  SpaceLightingResponse,
  SpaceOptions,
  SpaceRouteResponse,
  PlanSpace,
  LayoutResult as SpaceLayoutResult,
  WireCatalog,
  WireFaultInput,
  WireStandardSpec,
  WireUploadOptions,
  GlossaryEntry,
  LibraryDetail,
  LibraryListResponse,
  LibraryChange,
  LibraryTrace,
  LibraryTreeNode,
  ModelCard,
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

// ---- Component 16: the "get familiar" layer ----
//
// The reference calls (cards, glossary, lenses) are immutable for the life of a
// build, so each is fetched once and memoised: a tooltip must not cost a round
// trip, and a card browser must not refetch on every keystroke.

let lensesCache: Promise<ExplainLenses> | null = null;
let glossaryCache: Promise<GlossaryEntry[]> | null = null;
let cardsCache: Promise<ModelCard[]> | null = null;

/** Who is reading, and how deep — both pickers in one call. */
export function fetchLenses(): Promise<ExplainLenses> {
  lensesCache ??= fetch("/api/explain/lenses").then((r) => jsonOrThrow(r, "load lenses"));
  return lensesCache;
}

/** Every glossary entry, for tooltips. Aliases are resolved client-side. */
export function fetchGlossary(): Promise<GlossaryEntry[]> {
  glossaryCache ??= fetch("/api/explain/glossary").then((r) => jsonOrThrow(r, "load glossary"));
  return glossaryCache;
}

/** Every plain-language model card. */
export function fetchCards(): Promise<ModelCard[]> {
  cardsCache ??= fetch("/api/explain/cards").then((r) => jsonOrThrow(r, "load model cards"));
  return cardsCache;
}

/** Explain what a live twin is doing and why, in one domain's terms. */
export async function explainSystem(
  systemId: string,
  domain: string,
  level: ExplainLevel,
  cell?: { series: number; parallel: number },
): Promise<ExplainResponse> {
  const q = new URLSearchParams({ domain, level });
  if (cell) {
    q.set("series", String(cell.series));
    q.set("parallel", String(cell.parallel));
  }
  const res = await fetch(`/api/systems/${encodeURIComponent(systemId)}/explain?${q}`);
  return jsonOrThrow(res, "explain system");
}

/** Explain a wire run — same body as `evaluateRun`, plus a lens. */
export async function explainWireRun(body: Record<string, unknown>): Promise<ExplainResponse> {
  const res = await fetch("/api/explain/wires", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "explain wire run");
}

/** Explain a lighting design — same body as `evaluateInstallation`, plus a lens. */
export async function explainLighting(body: Record<string, unknown>): Promise<ExplainResponse> {
  const res = await fetch("/api/explain/lights", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "explain lighting");
}

/**
 * Explain one luminaire on the supply it has actually got.
 *
 * Takes one entry of `operateLights`'s body, because that is the shape a caller
 * solving a *site* already has — as opposed to `explainLighting`, which explains
 * a *room* designed by the lumen method. Returns two attributions: why the
 * fitting is producing less than its rating, and what each watt bought.
 */
export async function explainLamp(body: Record<string, unknown>): Promise<ExplainResponse> {
  const res = await fetch("/api/explain/lamp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, "explain lamp");
}

// ---- the system library (Component 17) ----

/** Saved systems, with a one-line computed diff on every row. */
export async function fetchLibrary(params: {
  kind?: string;
  tag?: string;
  q?: string;
} = {}): Promise<LibraryListResponse> {
  const q = new URLSearchParams();
  if (params.kind) q.set("kind", params.kind);
  if (params.tag) q.set("tag", params.tag);
  if (params.q) q.set("q", params.q);
  const res = await fetch(`/api/library?${q}`);
  return jsonOrThrow(res, "load library");
}

/** One entry with its lineage, its diff from its parent, and what it inherits. */
export async function fetchLibraryEntry(entryId: string): Promise<LibraryDetail> {
  const res = await fetch(`/api/library/${encodeURIComponent(entryId)}`);
  return jsonOrThrow(res, "load library entry");
}

/** How this system got here: every step from the root, and the reason for it. */
export async function fetchLibraryTrace(entryId: string): Promise<LibraryTrace> {
  const res = await fetch(`/api/library/${encodeURIComponent(entryId)}/trace`);
  return jsonOrThrow(res, "load lineage");
}

export async function fetchLibraryTree(): Promise<LibraryTreeNode[]> {
  const res = await fetch("/api/library/tree");
  return jsonOrThrow(res, "load lineage tree");
}

async function libraryPost<T>(path: string, body: unknown, what: string): Promise<T> {
  const res = await fetch(`/api/library${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return jsonOrThrow(res, what);
}

/**
 * What two specs differ in, in plain language. Pure compute — no library, no
 * database — so the builder can show what an edit would change before anything
 * is saved.
 */
export async function diffSpecs(
  before: Partial<SystemSpec>,
  after: Partial<SystemSpec>,
): Promise<{ changes: LibraryChange[]; summary: string; count: number }> {
  return libraryPost("/diff", { before, after }, "diff specs");
}

export const saveToLibrary = (body: {
  spec: SystemSpec;
  name?: string;
  kind?: string;
  summary?: string;
  author?: string;
  tags?: string[];
}) => libraryPost<LibraryDetail>("", body, "save to library");

/** Start a new system from an existing one. The server refuses a fork with no reason. */
export const forkEntry = (
  entryId: string,
  body: { name: string; because: string; spec?: SystemSpec; author?: string; summary?: string },
) => libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/fork`, body, "fork entry");

/** The next version of the same design. Also refuses to run without a reason. */
export const reviseEntry = (
  entryId: string,
  body: { spec: SystemSpec; because: string; author?: string; name?: string },
) => libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/revise`, body, "revise entry");

export const promoteEntry = (
  entryId: string,
  body: { because: string; name?: string; author?: string },
) => libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/promote`, body, "promote entry");

export const addLibraryNote = (
  entryId: string,
  body: { text: string; kind?: string; author?: string },
) => libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/notes`, body, "add note");

export const addLibraryDecision = (
  entryId: string,
  body: { question: string; because: string; params?: string[]; rejected?: string[]; author?: string },
) => libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/decisions`, body, "record decision");

export const setLibraryValidated = (entryId: string, validated: boolean) =>
  libraryPost<LibraryDetail>(`/${encodeURIComponent(entryId)}/validated`, { validated }, "set validated");

/**
 * Run a saved system, remembering which entry it came from.
 *
 * `site` is for a caller that has a place of its own — the 3D sandbox stands a
 * rack in the world's weather and wires it to the world's loads, and neither is
 * part of the design. Only `weather`, `profile` and `duration_s` are accepted;
 * anything else is refused, because what runs has to be the design the entry
 * records. Hand the same field names back to `captureSystem` and the diff comes
 * out clean.
 */
export const instantiateEntry = (
  entryId: string,
  body: {
    system_id?: string;
    name?: string;
    autostart?: boolean;
    site?: Partial<Pick<SystemSpec, "weather" | "profile" | "duration_s">>;
  } = {},
) =>
  libraryPost<{ system_id: string; run_state: string; entry_id: string; site: string[] }>(
    `/${encodeURIComponent(entryId)}/instantiate`,
    body,
    "run saved system",
  );

/**
 * Save a running system back — as the next version of the entry it came from.
 *
 * `site` names the fields the caller supplied itself; they are taken back off
 * before the entry is recorded, so what is saved differs from its parent by what
 * somebody *did* to the system rather than by where it was standing.
 */
export const captureSystem = (body: {
  system_id: string;
  because?: string;
  name?: string;
  summary?: string;
  author?: string;
  site?: string[];
}) => libraryPost<LibraryDetail>("/capture", body, "capture system");

export const seedLibrary = () => libraryPost<{ added: string[] }>("/seed", {}, "seed library");

export async function deleteLibraryEntry(entryId: string) {
  const res = await fetch(`/api/library/${encodeURIComponent(entryId)}`, { method: "DELETE" });
  return jsonOrThrow(res, "delete entry");
}


// ---------------------------------------------------------------------------
// The building — /api/space/* (Component 20)
// ---------------------------------------------------------------------------
//
// Every call below except the upload is pure compute: the browser holds the
// plan and posts it back. That is why there is no `fetchPlan(id)` here and no
// plan id to remember — a floor plan is a document this app owns, not a session
// on the server, so it survives a restart of the twin core and can be saved to
// a file or carried in a library entry unchanged.

export const fetchSpaceOptions = async (): Promise<SpaceOptions> =>
  jsonOrThrow(await fetch("/api/space/options"), "space options");

/**
 * Import a building file. Sends multipart form data; the browser sets the
 * boundary, so no Content-Type here.
 *
 * The DXF options exist because a drawing whose layers follow an unusual
 * convention is otherwise unimportable, and telling the importer the convention
 * is the honest fix rather than guessing harder.
 */
export async function importBuilding(
  file: File,
  opts: { format?: string; wallLayers?: string; roomLayers?: string; scale?: number } = {},
): Promise<{ plan: FloorPlan; summary: PlanSummary }> {
  const form = new FormData();
  form.append("file", file);
  if (opts.format) form.append("format", opts.format);
  if (opts.wallLayers) form.append("wall_layers", opts.wallLayers);
  if (opts.roomLayers) form.append("room_layers", opts.roomLayers);
  if (opts.scale) form.append("scale", String(opts.scale));
  const res = await fetch("/api/space/import", { method: "POST", body: form });
  return jsonOrThrow(res, "import building");
}

async function spacePost<T>(path: string, body: unknown, what: string): Promise<T> {
  const res = await fetch(`/api/space${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res, what);
}

/** Build a plan from a server-side source and get the document back. */
export const fetchPlan = async (
  space: { type: string; params?: Record<string, unknown> },
): Promise<FloorPlan> =>
  (await spacePost<{ plan: FloorPlan; summary: PlanSummary }>("/plan", { space }, "build plan"))
    .plan;

/**
 * A generated example building, so the view has something to show before anybody
 * has a model.
 *
 * It comes back with a fidelity record that reads "nothing was assumed" — the
 * control case, and what gives the warning any meaning on a real model.
 */
export const fetchExampleBuilding = (rooms = 4, levels = 1) =>
  fetchPlan({ type: "rect", params: { rooms, levels } });

export const planSummary = (plan: FloorPlan) =>
  spacePost<PlanSummary>("/summary", { plan }, "plan summary");

export const planLighting = (
  plan: FloorPlan,
  opts: { levelId?: string; recommend?: boolean; family?: string } = {},
) =>
  spacePost<SpaceLightingResponse>(
    "/lighting",
    { plan, level_id: opts.levelId, recommend: opts.recommend, family: opts.family },
    "lighting for the building",
  );

/**
 * Solve an illuminance field over one room's REAL outline.
 *
 * Distinct from `solveLayout` (/api/lights/layout), which lights a rectangle.
 * In an L-shaped room the two disagree substantially and this one is right:
 * grid points outside the room come back as `null`, because a point in the
 * notch is not dark floor — it is not floor. Never render a null as zero lux.
 */
export const planRoomLayout = (
  plan: FloorPlan,
  spaceId: string,
  luminaires: { id?: string; x_m: number; y_m: number; height_m?: number; lamp?: unknown }[],
  opts: { gridN?: number; targetLux?: number; weather?: WeatherInput } = {},
) =>
  spacePost<{
    space_id: string;
    name: string;
    rectangular: boolean;
    inferred: string[];
    layout: SpaceLayoutResult;
  }>(
    "/layout",
    {
      plan,
      space_id: spaceId,
      luminaires,
      grid_n: opts.gridN,
      target_lux: opts.targetLux,
      weather: opts.weather,
    },
    "light this room",
  );

export const planRoute = (
  plan: FloorPlan,
  start: [number, number],
  end: [number, number],
  opts: {
    startLevel?: string;
    endLevel?: string;
    wireType?: string;
    currentA?: number;
    systemVoltageV?: number;
    weather?: WeatherInput;
  } = {},
) =>
  spacePost<SpaceRouteResponse>(
    "/route",
    {
      plan,
      start,
      end,
      start_level: opts.startLevel,
      end_level: opts.endLevel,
      wire_type: opts.wireType,
      current_a: opts.currentA,
      system_voltage_v: opts.systemVoltageV,
      weather: opts.weather,
    },
    "route a cable",
  );

export const planAmbient = (plan: FloorPlan, spaceId: string, weather?: WeatherInput) =>
  spacePost<{ plan_id: string; space: SpaceContext }>(
    "/ambient",
    { plan, space_id: spaceId, weather },
    "ambient in this room",
  );

/** Which room a point falls in. `space: null` means outdoors — a real answer. */
export const planSpaceAt = (plan: FloorPlan, x: number, y: number, levelId?: string) =>
  spacePost<{ plan_id: string; space: PlanSpace | null }>(
    "/at",
    { plan, x_m: x, y_m: y, level_id: levelId },
    "which room is this",
  );

/**
 * The weather source the model's own coordinates imply.
 *
 * `located: false` is not a failure — it means the file carries no coordinates,
 * and the caller should keep whatever weather it had rather than be handed
 * 0, 0 in the Gulf of Guinea.
 */
export const planWeather = (plan: FloorPlan) =>
  spacePost<{
    plan_id: string;
    located: boolean;
    weather: { type: string; params: Record<string, unknown> } | null;
    north_deg?: number;
  }>("/weather", { plan }, "weather for this building");

