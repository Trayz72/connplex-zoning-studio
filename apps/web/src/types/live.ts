// Types for the real zoning-engine pipeline (the only pipeline in the app —
// the earlier pre-baked demo dataset and its /canvas, /placeholder pages and
// components/zoning/* have been removed).

export interface Obstacle {
  id: string;
  source_handle: string;
  layer: string;
  dxftype: string;
  area_sqft: number;
  points_ft: number[][];
  classification: 'COLUMN' | 'WALL' | 'DOOR' | 'WINDOW' | 'STAIRCASE' | 'WASHROOM_FIXTURE' | 'FURNITURE' | 'UNCLASSIFIED_OBSTACLE';
  confidence: 'high' | 'medium' | 'low';
  status: 'PROPOSED' | 'CONFIRMED' | 'IGNORED';
}

export interface TextLabel {
  text: string;
  position_ft: [number, number];
}

export interface Boundary {
  source_handle: string;
  layer: string;
  source: 'explicit' | 'reconstructed';
  area_sqft: number;
  points_ft: number[][];
  bounding_box_ft: { min_x: number; min_y: number; max_x: number; max_y: number };
  confidence: 'high' | 'medium' | 'low';
  /** Set when this boundary needs a second look before confirming — e.g.
   * reconstructed from discrete wall segments rather than one explicit
   * closed polyline, or implausibly large (almost always a sheet-border/
   * title-block frame mistaken for the real floor outline). Was already
   * computed by the backend but never actually rendered anywhere. */
  note: string | null;
  status: 'PROPOSED' | 'CONFIRMED';
}

/** The actual underlying CAD drawing (raw lines/circles/text near this region),
 * separate from the interpreted boundary/obstacles — rendered as a light
 * backdrop so the architect can see the real source drawing under the
 * generated zoning, the way a real CAD viewer does. Not every entity in the
 * file, just what falls within this region's bounding box, to keep payload
 * size sane on large drawings. */
export interface RawGeometry {
  lines: [[number, number], [number, number]][];
  circles: { center: [number, number]; radius: number }[];
  texts: { text: string; position: [number, number] }[];
  truncated: boolean;
}

export interface GeometryRegion {
  region_id: string;
  boundary: Boundary;
  obstacles: Obstacle[];
  text_labels: TextLabel[];
  raw_geometry?: RawGeometry;
}

export interface GeometryResult {
  schema_version: string;
  source_filename: string;
  conversion_note: string | null;
  units: { insunits_code: number; detected_unit: string; feet_per_drawing_unit: number | null; needs_user_confirmation: boolean };
  extraction_method: string;
  total_entities_scanned: number;
  total_closed_shapes_found: number;
  region_count: number;
  regions: GeometryRegion[];
  unclassified_text_count: number;
  uploaded_filename?: string;
  uploaded_at?: string;
}

export interface Requirements {
  property_type: 'EXISTING_BUILDING' | 'OPEN_LAND';
  max_auditoriums: number;
  franchise_tier_id: string | null;
  support_zone_area_overrides_sqft: Record<string, number>;
  clear_height_ft: number | null;
  /** Where the main entrance is, in the same ft coordinate space as the
   * confirmed boundary. Optional and architect-marked — nothing in CAD
   * extraction detects doors/entrances today, so this is real user input,
   * not a derived value. Used only to place Foyer/F&B/Washroom zones per
   * the SOP's entry-sightline rules (spec M6); when null, that placement
   * logic is skipped rather than guessing where the entrance is. */
  entry_point_ft: [number, number] | null;
}

export interface SeatEstimate {
  status: string;
  seat_count: number;
  rows: number;
  seats_per_row: number;
  seat_type_used?: string;
  seat_breakdown?: { LOUNGER: number; SOFA_SLIDER: number; DUO_LOUNGER: number; PREMIUM_RECLINER: number };
  // Present when a confirmed structural column was allowed to fall inside
  // this room (see layout_engine.py's two-tier placement) — seat_count above
  // is already discounted for it; this explains why and asks for a manual
  // seat-plan check around the column position.
  note?: string;
}

export interface PresetFit {
  matches_preset: string | null;
  status: string;
  shortfall_vs_smallest_preset_sqft?: number;
}

export interface SelectableSeatType {
  id: string;
  name: string;
  category: string;
  chart_column: string;
  seat_width_ft: number;
  row_step_ft: number;
}

export interface SeatConfig {
  primary_seat_type_id: string;
  secondary_seat_type_id: string | null;
  primary_ratio_pct: number;
}

export interface LiveRoom {
  room_id: string;
  room_type: string;
  display_name: string;
  area_sqft: number;
  width_ft: number;
  depth_ft: number;
  origin_ft: [number, number];
  geometry_points_ft: number[][];
  preset_id?: string;
  preset_name?: string;
  seat_estimate?: SeatEstimate;
  seat_config?: SeatConfig;
  preset_fit?: PresetFit;
  area_basis_note?: string;
  shrink_note?: string;
  // Present when this room (support zone) was allowed to enclose a confirmed
  // structural column — see layout_engine.py's two-tier placement. Auditoriums
  // carry the equivalent note on seat_estimate.note instead, since there it's
  // tied to the seat-count discount.
  obstacle_note?: string;
}

export interface FeasibilityRuleResult {
  rule_id: string;
  result: 'PASS' | 'FAIL' | 'INSUFFICIENT_DATA';
  severity: 'HARD' | 'SOFT' | 'WARNING';
  metric: string;
  measured_value: number | null;
  threshold: number | string;
  unit?: string;
  source: string;
  message: string;
}

export interface Feasibility {
  feasibility_result: 'FEASIBLE' | 'CONDITIONALLY_FEASIBLE' | 'NOT_FEASIBLE' | 'INSUFFICIENT_DATA';
  measurements: Record<string, number>;
  hard_fail_count: number;
  warning_count: number;
  insufficient_data_count: number;
  rule_results: FeasibilityRuleResult[];
}

export interface AreaSeatChartRow {
  location: string;
  area_sqft: number;
  lounger: number;
  sofa_slider: number;
  duo_lounger: number;
  premium_recliner: number;
  total_seats: number;
}

export interface AreaSeatChart {
  screen_rows: AreaSeatChartRow[];
  total_screen_row: AreaSeatChartRow;
  foyer_row: { location: string; area_sqft: number; components: { location: string; area_sqft: number }[] };
  exit_passage_row: { location: string; area_sqft: number };
  grand_total_row: AreaSeatChartRow;
}

export interface LiveCandidate {
  candidate_id: string;
  strategy: string;
  strategy_label: string;
  rooms: LiveRoom[];
  circulation_area_sqft: number;
  usable_area_sqft: number;
  boundary_area_sqft: number;
  total_seats: number;
  screen_count: number;
  seats_per_screen: number;
  warnings: string[];
  feasibility: Feasibility;
  area_seat_chart: AreaSeatChart;
}

export interface ZoningRunResult {
  run_id: string;
  region_id: string;
  requirements: Requirements;
  unresolved_obstacle_count: number;
  candidates: LiveCandidate[];
  created_at: string;
}

export interface EditableLayout {
  region_id: string;
  source_candidate_id: string;
  boundary_points_ft: number[][];
  obstacles: Obstacle[];
  rooms: LiveRoom[];
  circulation_area_sqft: number;
  // Algorithm-level notes from when this layout was generated (unmarked
  // entrance, undersized auditorium presets, low utilization w/ real cause,
  // etc.) — carried forward as-is across manual edits, not recomputed.
  warnings: string[];
  revision: string;
  updated_at: string;
  feasibility: Feasibility;
  area_seat_chart: AreaSeatChart;
  total_seats: number;
  screen_count: number;
}

export interface ValidationError {
  room_id: string;
  issue: string;
  message: string;
}
