// Mirrors the twin core's telemetry contract (celltwin.sim.telemetry).

export interface CellTelemetry {
  series_index: number;
  parallel_index: number;
  voltage_v: number;
  current_a: number;
  temp_c: number;
  soc: number;
}

export interface PackTelemetry {
  time_s: number;
  pack_voltage_v: number;
  pack_current_a: number;
  pack_power_w: number;
  pack_soc: number;
  max_temp_c: number;
  min_cell_voltage_v: number;
  max_cell_voltage_v: number;
  voltage_imbalance_v: number;
  cells: CellTelemetry[];
}

// The MQTT envelope, as delivered over the WebSocket.
export interface TelemetryEnvelope {
  system_id: string;
  timestamp: string;
  telemetry: PackTelemetry;
}

export interface CellAnomaly {
  series_index: number;
  parallel_index: number;
  score: number;
  level: string; // good | warning | serious | critical
  driver: string;
  temp_z: number;
  volt_z: number;
  soc_z: number;
}

export interface AnomalyReport {
  time_s: number;
  max_score: number;
  flagged_count: number;
  worst_series: number;
  worst_parallel: number;
  worst_driver: string;
  cells: CellAnomaly[];
}

export interface AnomalyEnvelope {
  system_id: string;
  timestamp: string;
  anomaly: AnomalyReport;
}

export interface CellHealth {
  series_index: number;
  parallel_index: number;
  soh: number;
  dcir_ohm: number;
  r_ratio_peer: number;
  heating_rate_c_per_min: number;
  time_to_critical_s: number | null;
}

export interface Diagnosis {
  fault_type: string;
  confidence: number;
  cell_series: number;
  cell_parallel: number;
  rationale: string;
}

export interface AssessmentReport {
  time_s: number;
  pack_soh: number;
  worst_cell_soh: number;
  diagnosis: Diagnosis;
  safety_state: string; // nominal | warning | alarm
  min_time_to_critical_s: number | null;
  cells: CellHealth[];
}

export interface AssessmentEnvelope {
  system_id: string;
  timestamp: string;
  assessment: AssessmentReport;
}

export interface SystemInfo {
  system_id: string;
  name: string | null;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  live: boolean;
}

// Fleet rollup (celltwin.fleet) — one status row per system + a summary.
export interface FleetSystem {
  system_id: string;
  name: string | null;
  source: "simulation" | "realtime";
  run_state: "running" | "paused" | "stopped";
  live: boolean;
  age_s: number | null;
  updated_at: string | null;
  pack_soc: number | null;
  pack_power_w: number | null;
  max_temp_c: number | null;
  voltage_imbalance_v: number | null;
  anomaly_score: number | null;
  flagged_count: number | null;
  worst_cell: string | null;
  pack_soh: number | null;
  fault_type: string | null;
  confidence: number | null;
  safety_state: string | null;
  min_time_to_critical_s: number | null;
  status: string; // good | warning | serious | critical
  status_reason: string;
}

export interface FleetSummary {
  total: number;
  live: number;
  counts: Record<string, number>; // by status level
  worst_status: string;
  worst_system: string | null;
  total_power_w: number;
  alarms: number;
}

export interface FleetResponse {
  summary: FleetSummary;
  systems: FleetSystem[];
}

// A single point on the trend charts, unified on wall-clock time (ms).
export interface TrendPoint {
  t: number;
  soc: number;
  maxTemp: number;
  power: number;
  voltage: number;
  imbalance: number;
}

export interface AnomalyPoint {
  t: number;
  maxScore: number;
}

// Validation catalog + report (celltwin.validate).
export interface DatasetSpec {
  id: string;
  name: string;
  institution: string;
  chemistry: string;
  cell_format: string;
  license: string;
  license_url: string;
  citation: string;
  homepage_url: string;
  download_url: string;
  loader: string;
  what_it_validates: string[];
  sample: string | null;
  synthetic: boolean;
  notes: string;
}

export interface ValidationMetrics {
  rmse: number;
  mae: number;
  max_abs_err: number;
  mean_bias: number;
}

export interface ValidationReport {
  dataset_id: string;
  cell_id: string;
  chemistry: string;
  n_samples: number;
  duration_s: number;
  data_source: string;
  params: Record<string, number>;
  metrics: ValidationMetrics;
  overlay: {
    t: number[];
    v_measured: number[];
    v_model: number[];
    v_model_fitted?: number[];
  };
  fitted: { r0_ohm: number; soc0: number; metrics: ValidationMetrics } | null;
  notes: string;
  ocv_curve: string; // which chemistry OCV curve was used (NMC/LFP/LCO/NCA)
  // Echoed by POST /api/validation/run so the UI can be honest about what ran.
  requested_dataset_id?: string | null;
  sample_dataset_id?: string;
  // Echoed by POST /api/validation/upload.
  filename?: string;
}

// ---- System builder (celltwin.builder) ----
export interface ProfileSpec {
  type: string;
  params: Record<string, number>;
}

export interface FaultSpec {
  type: string;
  series: number;
  parallel: number;
  start_s: number;
  params: Record<string, number | string>;
}

// Mirrors celltwin.builder.spec.SystemSpec (flat cell/pack/sim fields).
export interface SystemSpec {
  system_id: string;
  name: string;
  chemistry: string;
  capacity_ah: number;
  r0_ohm: number;
  r1_ohm: number;
  c1_farad: number;
  coulombic_eff: number;
  thermal_capacity_j_per_k: number;
  cooling_conductance_w_per_k: number;
  v_min: number;
  v_max: number;
  temp_max_c: number;
  series: number;
  parallel: number;
  capacity_spread: number;
  resistance_spread: number;
  initial_soc: number;
  initial_soc_spread: number;
  ambient_temp_c: number;
  seed: number;
  dt_s: number;
  duration_s: number;
  profile: ProfileSpec;
  faults: FaultSpec[];
}

export interface CreateSystemPayload {
  source: "simulation" | "realtime";
  system_id?: string;
  name?: string;
  spec?: SystemSpec;
  speed?: number;
  autostart?: boolean;
}

export interface BuilderOptions {
  chemistries: string[];
  profile_types: string[];
  profile_params: Record<string, Record<string, number>>;
  fault_types: string[];
  fault_params: Record<string, Record<string, number>>;
  sensor_signals: string[];
  default_spec: SystemSpec;
}

export interface PreviewResult {
  system_id: string;
  name: string;
  chemistry: string;
  n_steps: number;
  duration_s: number;
  final_soc: number;
  min_soc: number;
  min_pack_voltage_v: number;
  max_pack_voltage_v: number;
  peak_temp_c: number;
  max_imbalance_v: number;
  energy_throughput_wh: number;
  peak_power_w: number;
  temp_limit_c: number;
  temp_limit_exceeded: boolean;
  time_to_limit_s: number | null;
  series_len: number;
  parallel_len: number;
  sparkline: {
    t: number[];
    soc: number[];
    max_temp: number[];
    voltage: number[];
    power: number[];
  };
}

// Options for a user-data upload validation.
export interface UploadOptions {
  datasetId?: string;
  chemistry?: string;
  fit?: boolean;
  timeCol?: string;
  currentCol?: string;
  voltageCol?: string;
  tempCol?: string;
  dischargePositive?: boolean;
  currentScale?: number;
  nominalCapacityAh?: number;
}
