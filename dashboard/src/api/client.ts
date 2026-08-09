import type {
  BuilderOptions,
  CreateSystemPayload,
  DatasetSpec,
  FleetResponse,
  PreviewResult,
  Recommendation,
  RunAssessment,
  SystemInfo,
  SystemSpec,
  TrendPoint,
  UploadOptions,
  ValidationReport,
  WireCatalog,
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
