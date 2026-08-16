// Mirrors the twin core's telemetry contract (simura.sim.telemetry).

export interface CellTelemetry {
  series_index: number;
  parallel_index: number;
  voltage_v: number;
  current_a: number;
  temp_c: number;
  soc: number;
}

// Environmental conditions a frame ran under (simura.weather.WeatherSample).
export interface WeatherSample {
  timestamp: number;
  air_temp_c: number;
  wind_speed_ms: number;
  solar_w_m2: number;
  humidity_frac: number | null;
  source: string;
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
  weather?: WeatherSample | null; // present only when a weather source is attached
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

// Fleet rollup (simura.fleet) — one status row per system + a summary.
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

// Validation catalog + report (simura.validate).
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

// ---- System builder (simura.builder) ----
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

export interface WeatherSpec {
  type: string; // none | static | synthetic | csv | open_meteo
  params: Record<string, number | string>;
}

// Mirrors simura.builder.spec.SystemSpec (flat cell/pack/sim fields).
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
  weather: WeatherSpec;
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
  weather_types: string[];
  weather_params: Record<string, Record<string, number | string>>;
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
  weather_type: string;
  min_ambient_c: number | null;
  max_ambient_c: number | null;
  max_solar_w_m2: number | null;
  sparkline: {
    t: number[];
    soc: number[];
    max_temp: number[];
    voltage: number[];
    power: number[];
    ambient?: number[];
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

// ---- Wires (simura.wires) ----

export interface WireType {
  id: string;
  name: string;
  material: string;
  awg: number;
  area_mm2: number;
  insulation: string;
  temp_rating_c: number;
  ampacity_a: number;
  notes: string;
}

export interface WireCatalog {
  materials: string[];
  insulations: string[];
  wire_types: WireType[];
  fault_types: string[];
}

// ---- Wire network (simura.wires.network) ----

// A fault injected into one cable run: `{type, ...params}`, as the API takes it.
export interface WireFaultInput {
  type: string;
  [param: string]: number | string;
}

// simura.wires.network.SegmentResult
export interface SegmentResult {
  id: string;
  from_node: string;
  to_node: string;
  current_a: number;
  voltage_drop_v: number;
  power_loss_w: number;
  temp_c: number;
  resistance_ohm: number;
  ampacity_a: number;
  ampacity_utilization: number;
  over_ampacity: boolean;
  over_temp: boolean;
  temp_rating_c: number;
  leakage_a: number;
  faulted: boolean;
}

// simura.wires.network.NetworkResult
export interface NetworkResult {
  node_voltages: Record<string, number>;
  segments: SegmentResult[];
  total_loss_w: number;
  worst_segment: string | null;
  problems: string[];
}

// A single instant's weather, as the planner accepts it.
export interface WeatherInput {
  air_temp_c: number;
  wind_speed_ms?: number;
  solar_w_m2?: number;
}

// simura.wires.planning.RunAssessment
export interface RunAssessment {
  resistance_ohm: number;
  voltage_drop_v: number;
  voltage_drop_pct: number | null;
  power_loss_w: number;
  steady_state_temp_c: number;
  ampacity_a: number;
  ampacity_utilization: number;
  temp_rating_c: number;
  ambient_temp_c: number | null;   // ambient used (set when weather-driven)
  problems: string[];
}

// simura.wires.planning.Recommendation
export interface Recommendation {
  wire_type: WireType | null;
  assessment: RunAssessment | null;
  rationale: string;
  ok: boolean;
}

// ---- Wire validation (simura.wires.validation) ----

// simura.wires.validation.standards.WireStandardSpec (as returned by the API)
export interface WireStandardSpec {
  id: string;
  name: string;
  institution: string;
  material: string;
  ref_temp_c: number;
  quantity: string;
  unit: string;
  license: string;
  license_url: string;
  citation: string;
  homepage_url: string;
  what_it_validates: string[];
  notes: string;
  n_points: number;
}

export interface WireValidationMetrics {
  rmse_pct: number;
  mae_pct: number;
  max_abs_pct: number;
  mean_bias_pct: number;
}

// simura.wires.validation.engine.WireValidationReport
export interface WireValidationReport {
  standard_id: string;
  material: string;
  ref_temp_c: number;
  n_points: number;
  quantity: string;
  unit: string;
  data_source: string;
  metrics: WireValidationMetrics;
  overlay: {
    awg: number[];
    area_mm2: number[];
    published_ohm_per_km: number[];
    model_ohm_per_km: number[];
    error_pct: number[];
  };
  notes: string;
  // Echoed by POST /api/wires/validation/upload.
  filename?: string;
}

// Options for a user-supplied resistance-CSV validation.
export interface WireUploadOptions {
  material?: string;
  awgCol?: string;
  resistanceCol?: string;
  refTempC?: number;
  resistanceUnit?: string;
}

// ---- Lights (simura.lights) ----

// simura.lights.catalog.LightTechnology, as returned by /api/lights/catalog.
export interface LightTechnology {
  key: string;
  name: string;
  family: string;
  spectrum_kind: string;
  radiant_efficiency: number;
  envelope_transmission: number;
  control_gear_loss_frac: number;
  design_filament_k: number;
  optimum_ambient_c: number | null;
  flux_temp_coeff_per_k: number;
  warmup_s: number;
  restrike_s: number;
  dimmable: boolean;
  min_dim_frac: number;
  rated_life_h: number;
  l70_h: number;
  cri: number;
  notes: string;
}

// simura.lights.catalog.LampType, as returned by /api/lights/catalog.
export interface LampType {
  id: string;
  name: string;
  technology: string;
  family: string;
  rated_power_w: number;
  rated_flux_lm: number;
  published_efficacy_lm_per_w: number;
  beam_angle_deg: number;
  color_temp_k: number;
  base: string;
  notes: string;
}

export interface LightCatalog {
  families: string[];
  technologies: LightTechnology[];
  lamp_types: LampType[];
  fault_types: string[];
  profile_types: string[];
  control_types: string[];
  tasks: Record<string, number>;
}

// A light source's spec, as the API accepts it.
export interface LightSpecInput {
  lamp_type?: string;
  technology?: string;
  power_w?: number;
  beam_angle_deg?: number;
  ambient_temp_c?: number;
  operating_hours_h?: number;
  dirt_depreciation_frac?: number;
}

export interface LightFaultInput {
  type: string;
  start_s?: number;
  end_s?: number;
  [param: string]: number | string | undefined;
}

// simura.lights.photometry.RoomLighting
export interface RoomLighting {
  average_lux: number;
  total_flux_lm: number;
  room_index: number;
  utilisation_factor: number;
  light_loss_factor: number;
  power_w: number;
  power_density_w_per_m2: number;
  efficacy_lm_per_w: number;
  lux_per_w_per_m2: number;
}

// simura.lights.planning.InstallationAssessment
export interface InstallationAssessment {
  lamp_id: string | null;
  n_luminaires: number;
  target_lux: number;
  maintained_lux: number;
  initial_lux: number;
  flux_per_luminaire_lm: number;
  power_w: number;
  power_density_w_per_m2: number;
  efficacy_lm_per_w: number;
  color_temp_k: number;
  cri: number;
  room: RoomLighting;
  lumen_maintenance: number;
  ambient_temp_c: number | null;
  annual_energy_kwh: number | null;
  problems: string[];
}

export interface LampAlternative {
  lamp_id: string;
  name: string;
  family: string;
  n_luminaires: number;
  power_w: number;
  power_density_w_per_m2: number;
  maintained_lux: number;
  annual_energy_kwh: number | null;
  efficacy_lm_per_w: number;
  color_temp_k: number;
  cri: number;
  ok: boolean;
  problems: string[];
}

// simura.lights.planning.Recommendation
export interface LampRecommendation {
  lamp_type: LampType | null;
  n_luminaires: number;
  assessment: InstallationAssessment | null;
  rationale: string;
  ok: boolean;
  alternatives: LampAlternative[];
}

// simura.lights.lamp.OperatingPoint
export interface LightOperatingPoint {
  input_power_w: number;
  source_power_w: number;
  current_a: number;
  voltage_v: number;
  radiant_power_w: number;
  luminous_flux_lm: number;
  efficacy_lm_per_w: number;
  ler_lm_per_w: number;
  color_temp_k: number;
  source_temp_c: number;
  visible_fraction: number;
  lumen_maintenance: number;
  warmup_frac: number;
  lit: boolean;
}

// POST /api/lights/spectrum
export interface SpectrumResponse {
  wavelength_nm: number[];
  relative_power: number[];
  operating_point: LightOperatingPoint;
  chromaticity: { x: number; y: number };
  spectral_coverage: number;
  published_cri: number;
  technology: LightTechnology;
  published_flux_lm: number;
}

// simura.lights.layout.LuminaireResult
export interface LuminaireResult {
  id: string;
  x_m: number;
  y_m: number;
  height_m: number;
  lit: boolean;
  input_power_w: number;
  luminous_flux_lm: number;
  efficacy_lm_per_w: number;
  color_temp_k: number;
  source_temp_c: number;
  lumen_maintenance: number;
  peak_lux_below: number;
}

// simura.lights.layout.LayoutResult
export interface LayoutResult {
  average_lux: number;
  min_lux: number;
  max_lux: number;
  uniformity: number;
  diversity: number;
  total_power_w: number;
  power_density_w_per_m2: number;
  area_m2: number;
  grid: number[][];
  grid_x_m: number[];
  grid_y_m: number[];
  luminaires: LuminaireResult[];
  direct_average_lux: number;
  indirect_lux: number;
  daylight_lux: number;
  target_lux: number;
  problems: string[];
}

// simura.lights.telemetry.LightTelemetry
export interface LightTelemetry {
  time_s: number;
  drive: number;
  lit: boolean;
  input_power_w: number;
  current_a: number;
  voltage_v: number;
  luminous_flux_lm: number;
  efficacy_lm_per_w: number;
  radiant_power_w: number;
  color_temp_k: number;
  source_temp_c: number;
  illuminance_lux: number;
  lumen_maintenance: number;
  warmup_frac: number;
  operating_hours_h: number;
  switch_cycles: number;
  over_temp: boolean;
  below_target: boolean;
  weather?: WeatherSample | null;
  daylight_lux?: number | null;
}

// POST /api/lights/simulate
export interface LightSimulationResult {
  frames: LightTelemetry[];
  summary: {
    n_frames: number;
    energy_kwh: number;
    lamp_hours: number;
    switch_cycles: number;
    final_flux_lm: number;
    final_source_temp_c: number;
  };
}

// ---- Light validation (simura.lights.validation) ----

// simura.lights.validation.standards.LightStandardSpec (as returned by the API)
export interface LightStandardSpec {
  id: string;
  name: string;
  institution: string;
  quantity: string;
  unit: string;
  x_label: string;
  x_unit: string;
  license: string;
  license_url: string;
  citation: string;
  homepage_url: string;
  what_it_validates: string[];
  notes: string;
  n_points: number;
}

export interface LightValidationMetrics {
  rmse: number;
  mae: number;
  max_abs: number;
  mean_bias: number;
  rmse_pct: number;
  mae_pct: number;
  max_abs_pct: number;
  mean_bias_pct: number;
}

// simura.lights.validation.engine.LightValidationReport
export interface LightValidationReport {
  standard_id: string;
  quantity: string;
  n_points: number;
  unit: string;
  x_label: string;
  x_unit: string;
  data_source: string;
  metrics: LightValidationMetrics;
  overlay: {
    x: number[];
    key: string[];
    published: number[];
    model: number[];
    error: number[];
    error_pct: number[];
  };
  notes: string;
  filename?: string;
}

// simura.lights.validation.live.LiveDaylightReport — the one reference that is
// different every time you run it.
export interface LiveDaylightReport {
  latitude: number;
  longitude: number;
  source: string;
  n_hours: number;
  n_clear_hours: number;
  window_start: number;
  window_end: number;
  metrics: Record<string, number>;
  overlay: {
    timestamp: number[];
    elevation_deg: number[];
    measured_lux: number[];
    model_lux: number[];
    clearness_index: number[];
  };
  envelope_violations: number;
  notes: string;
}

// Options for a user-supplied photometric-CSV validation.
export interface LightUploadOptions {
  quantity?: string;
  xCol?: string;
  valueCol?: string;
  keyCol?: string;
}

// simura.lights.lamp.SupplyPoint, as POST /api/lights/operate returns it —
// what a lamp does on a supply that is not at its rated voltage.
export interface LightOperateResult {
  supply_voltage_v: number;
  nominal_voltage_v: number;
  voltage_ratio: number;
  /** Current drawn FROM the supply. Not point.current_a for anything with gear. */
  supply_current_a: number;
  /** Is there a driver or ballast in front of it? */
  regulated: boolean;
  /** Gear below its minimum input voltage: out, with no dimming on the way down. */
  dropped_out: boolean;
  over_voltage: boolean;
  point: LightOperatingPoint;
  illuminance_lux: number;
  beam_angle_deg: number;
  cri: number;
  family: string;
  technology: string;
}

export interface LightOperateResponse {
  lights: Record<string, LightOperateResult>;
  daylight_lux: number;
}
