/**
 * Shared domain types. Mirrors the orchard-server (FastAPI) schemas.
 * Descriptive fields (`species`, `variety`) are free text - stored as typed,
 * no enums, no coercion. Irrigation zones live in Rachio (read-only).
 */

/**
 * Irrigation zones come from the grower's Rachio account. They are
 * **read-only** here — every setting is edited in the official Rachio app.
 * Shapes mirror `app/services/rachio.py` (serialized snake_case).
 */
export interface RachioCustom {
  name?: string;
  [key: string]: unknown;
}

export interface RachioZone {
  id: string;
  name: string;
  enabled: boolean;
  zone_number: number;
  custom_nozzle: RachioCustom | null;
  custom_soil: RachioCustom | null;
  custom_slope: RachioCustom | null;
  custom_crop: RachioCustom | null; // vegetation type
  custom_shade: RachioCustom | null; // sun exposure
  /** Local grower label (not stored in Rachio). */
  label?: string | null;
  /** Label if set, otherwise `Zone {zone_number}`. */
  display_name?: string | null;
  [key: string]: unknown;
}

export interface RachioDevice {
  id: string;
  name: string;
  status: string;
  model: string | null;
  zones: RachioZone[];
  [key: string]: unknown;
}

export interface ZoneDetail {
  device_id: string;
  device_name: string;
  zone: RachioZone;
}

export interface Tree {
  tree_id: number;
  species: string;
  variety: string;
  /** Rachio zone id (free text; not validated). */
  zone_id: string | null;
  planted_date: string | null;
  additional_context: string | null;
  notes: string | null;
  /** Canopy dimensions (metres) - drive Care Plan resource/time scaling. */
  height_m: number | null;
  canopy_spread_m: number | null;
  /** Whole-tree drip delivery (gal/hour) and the soil area the emitters wet (m2) - irrigation solver. */
  estimated_gph: number | null;
  wetted_area_m2: number | null;
  expected_flowering_month: number | null;
  expected_harvest_month: number | null;
  expected_dormancy_month: number | null;
  expected_flowering_months: number[];
  expected_harvest_months: number[];
  expected_dormancy_months: number[];
  /** True when the tree has at least one care-plan template (list endpoint only). */
  has_care_plan: boolean;
  age_days: number | null;
  age_years: number | null;
  zone_label?: string | null;
  zone_display_name?: string | null;
}

export interface TreeInput {
  species: string;
  variety: string;
  zone_id?: string | null;
  planted_date?: string | null;
  additional_context?: string | null;
  notes?: string | null;
  height_m?: number | null;
  canopy_spread_m?: number | null;
  estimated_gph?: number | null;
  wetted_area_m2?: number | null;
  expected_flowering_month?: number | null;
  expected_harvest_month?: number | null;
  expected_dormancy_month?: number | null;
  expected_flowering_months?: number[];
  expected_harvest_months?: number[];
  expected_dormancy_months?: number[];
}

export type TreePatch = Partial<TreeInput>;

// -- Phase 4: Foreman JIT scheduling --------------------------------------

export type ScheduleStep = "need_time" | "need_resources" | "done";

export interface ScheduleTask {
  id: number;
  tree_id: number;
  action_type: string;
  estimated_minutes: number | null;
  priority_score: number;
  effective_score: number | null;
  required_resources: string[];
  escalated: boolean;
  drop_reason: string | null;
  tree_species?: string | null;
  tree_variety?: string | null;
  template_category?: string | null;
  last_completed?: string | null;
}

export interface ScheduleEscalation {
  task_id: number;
  action_type: string;
  days_late: number;
  multiplier: number;
  reason: string;
}

export interface ScheduleState {
  thread_id: string;
  step: ScheduleStep;
  available_minutes: number | null;
  required_resources: string[];
  proposed_tasks: ScheduleTask[];
  dropped_tasks: ScheduleTask[];
  escalations: ScheduleEscalation[];
  summary: string | null;
  warnings: string[];
}

export interface ReportResult {
  marked: number[];
  note: string;
}

export type TaskStatus = "pending" | "completed" | "deferred" | "skipped";

export interface TaskRead {
  id: number;
  tree_id: number;
  template_id: number | null;
  action_type: string;
  status: TaskStatus;
  priority_score: number;
  scheduled_date: string | null;
  frequency_days: number | null;
  estimated_minutes: number | null;
  required_resources: string[];
  created_at: string;
  completed_at: string | null;
  window_closes_on?: string | null;
  out_of_season?: boolean;
  last_completed?: string | null;
  tree_species?: string | null;
  tree_variety?: string | null;
}

// -- Care Plan engine ---------------------------------------------------

export type CareCategory =
  | "fertilize" | "mulch" | "prune" | "scout" | "spray"
  | "irrigation" | "weed" | "stake" | "soil_test" | "other";
export type RateClass = "light" | "standard" | "heavy";

export type BiologicalAnchor = "flowering" | "harvest" | "dormancy";

export interface ResourceLine {
  name: string;
  quantity: number;
  unit: string;
}

export interface TemplateBlock {
  category: CareCategory;
  min_gap_days: number;
}

export interface TaskTemplate {
  id: number;
  tree_id: number;
  name: string;
  category: CareCategory;
  rate_class: RateClass;
  interval_days: number;
  estimated_minutes: number;
  priority_score: number;
  required_resources: string[];
  resource_plan: ResourceLine[];
  baseline_question: string | null;
  anchor_date: string | null;
  valid_months: number[];
  biological_anchor: BiologicalAnchor | null;
  anchor_offset_days: number | null;
  blocks: TemplateBlock[];
  source_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface BaselineQuestion {
  template_id: number;
  name: string;
  question: string;
}

export interface TreePhenology {
  flowering_month: number | null;
  harvest_month: number | null;
  dormancy_month: number | null;
  flowering_months: number[];
  harvest_months: number[];
  dormancy_months: number[];
}

export interface CarePlan {
  tree_id: number;
  templates: TaskTemplate[];
  baseline_questions: BaselineQuestion[];
  pending_task_count: number;
  generated: boolean;
  phenology: TreePhenology;
}

export type TaskTemplatePatch = Partial<{
  name: string;
  category: CareCategory;
  rate_class: RateClass;
  interval_days: number;
  estimated_minutes: number;
  priority_score: number;
  required_resources: string[];
  valid_months: number[];
  biological_anchor: BiologicalAnchor | null;
  anchor_offset_days: number | null;
}>;

export interface InboxTask extends TaskRead {
  template_name: string | null;
  template_category: CareCategory | null;
  template_resource_plan: ResourceLine[];
  tree_species: string;
  tree_variety: string;
  window_closes_on: string | null;
  last_completed: string | null;
}

export interface ExecutedTask {
  id: number;
  tree_id: number;
  tree_species: string;
  tree_variety: string;
  template_id: number | null;
  task_id: number | null;
  action_type: string;
  category: string | null;
  outcome: "completed" | "skipped";
  scheduled_date: string | null;
  executed_at: string;
  estimated_minutes: number | null;
  required_resources: string[];
}

// -- Irrigation workflow (Phase 3) -------------------------------------

export interface ZoneConfig {
  zone_id: string;
  baseline_minutes: number;
  supervised: boolean;
  tree_count: number;
  label?: string | null;
  display_name?: string | null;
  zone_number?: number | null;
}

export interface SupervisorConfig {
  supervisor_frequency_hours: number;
  auto_approve_skips: boolean;
}

export interface IrrigationOverview {
  supervisor: SupervisorConfig;
  zones: ZoneConfig[];
  pending_proposals: number;
  demo_enabled?: boolean;
}

export type IrrigationActionType =
  | "skip_schedule"
  | "pass_no_action"
  | "adjust_duration"
  | "start_zone_watering";

export interface DemoScenario {
  id: string;
  title: string;
  expected_action: IrrigationActionType;
  summary: string;
  detail: string;
}

export interface DemoCatalog {
  enabled: boolean;
  active_scenario_id: string | null;
  scenarios: DemoScenario[];
}

export interface DemoApplyResult {
  scenario_id: string;
  expected_action: IrrigationActionType;
  on_date: string;
  zone_ids: string[];
  trees_pinned: number;
  message: string;
}

export interface SensorPinRead {
  sensor_id: string;
  label: string | null;
  vwc_pct: number;
  overridden: boolean;
  source: string;
}

export interface SensorTreeRead {
  tree_id: number;
  species: string;
  variety: string;
  growth_stage: string;
  target_vwc: number;
  current_vwc: number | null;
  moisture_gap: number;
  deficit_score: number;
  moisture_resolved_via: string;
  notes: string[];
  sensors: SensorPinRead[];
}

export interface SensorZoneRead {
  zone_id: string;
  last_watered_date: string | null;
  last_watered_source: "rachio" | "demo" | "none" | string;
  deficit_score: number;
  baseline_minutes: number;
  trees: SensorTreeRead[];
  label?: string | null;
  display_name?: string | null;
  zone_number?: number | null;
}

export interface SensorSnapshot {
  demo_enabled: boolean;
  for_date: string;
  rain_24h_mm: number;
  rain_overridden: boolean;
  rain_source: string;
  forecast_rain_24h_mm: number;
  forecast_available: boolean;
  forecast_overridden: boolean;
  forecast_source: string;
  forecast_error: string | null;
  active_scenario_id: string | null;
  pins_active: boolean;
  zones: SensorZoneRead[];
}

export interface SensorOverridesIn {
  rain_24h_mm?: number;
  forecast_rain_24h_mm?: number;
  for_date?: string;
  clear?: string[];
  moisture?: Array<{
    tree_id?: number;
    sensor_id?: string;
    vwc_pct?: number;
    clear?: boolean;
  }>;
  last_watered?: Array<{
    zone_id: string;
    last_watered_date: string | null;
  }>;
}

export interface SupervisorDecision {
  action: IrrigationActionType;
  days: number;
  duration_minutes: number;
  reason: string;
}

export interface SolverTreeOutcome {
  tree_id: number;
  species: string;
  delivered_gal: number;
  post_vwc: number;
  penalty: number;
}

export interface ZoneSolution {
  recommended_minutes: number;
  pulses: number;
  baseline_minutes: number;
  delta_minutes: number;
  total_penalty: number;
  per_tree: SolverTreeOutcome[];
  candidates_considered: number;
  rationale: string;
  thoughts: { candidate: string; penalty: number }[];
}

export type ProposalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "executed"
  | "no_action"
  | "error";

export interface SupervisorProposal {
  thread_id: string;
  zone_id: string;
  label?: string | null;
  display_name?: string | null;
  zone_number?: number | null;
  for_date: string;
  status: ProposalStatus;
  action: IrrigationActionType;
  summary: string;
  decision: SupervisorDecision | null;
  solution: ZoneSolution | null;
  deficit_score: number | null;
  result: Record<string, unknown> | null;
  created_at: string;
  resolved_at: string | null;
}

export interface SupervisorRunResult {
  ran_at: string;
  for_date: string;
  proposals: SupervisorProposal[];
}

export type SourceType = "file" | "text";

export interface Source {
  id: number;
  name: string;
  source_type: SourceType;
  file_path: string | null;
  upload_date: string;
}

export interface SourceDetail extends Source {
  raw_content: string;
}

/** Shape of a 4xx body returned by the FastAPI error handlers. */
export interface ApiErrorBody {
  detail: string;
  /** Present on 422 DomainValidationError - the offending field name. */
  field?: string;
}
