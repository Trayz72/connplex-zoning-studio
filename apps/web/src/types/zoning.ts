export interface ScoreBreakdown {
  area_efficiency: number;
  circulation_quality: number;
  adjacency_satisfaction: number;
  room_proportions: number;
  structural_clearance: number;
  layout_simplicity: number;
  uncertainty_penalty: number;
  seats?: number;
}

export interface SeatBreakdown {
  LOUNGER: number;
  SOFA_SLIDER: number;
  DUO_LOUNGER: number;
  PREMIUM_RECLINER: number;
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
  source_section?: string;
  message: string;
}

export interface FeasibilityData {
  region_id: string;
  feasibility_result: 'FEASIBLE' | 'CONDITIONALLY_FEASIBLE' | 'NOT_FEASIBLE' | 'INSUFFICIENT_DATA';
  measurements?: Record<string, number>;
  hard_fail_count?: number;
  warning_count?: number;
  insufficient_data_count?: number;
  rule_results: FeasibilityRuleResult[];
  reason?: string;
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
  region_id: string;
  screen_rows: AreaSeatChartRow[];
  total_screen_row: AreaSeatChartRow;
  foyer_row: { location: string; area_sqft: number; note: string };
  exit_passage_row: { location: string; area_sqft: number };
  grand_total_row: AreaSeatChartRow;
}

export interface RoomData {
  room_id: string;
  room_type: string;
  display_name: string;
  area_sqft: number;
  width_ft: number;
  depth_ft: number;
  min_area_sqft: number;
  min_dimensions: string;
  status: 'VALID' | 'REVIEW_REQUIRED' | 'INVALID';
  adjacency: string;
  structural_clearance: string;
  source: string;
  centroid?: [number, number];
  bounds?: [number, number, number, number];
  seat_count?: number;
  seat_breakdown?: SeatBreakdown;
  seat_estimate_status?: string;
  preset_fit?: { matches_preset: string | null; status: string };
}

export interface CandidateData {
  candidate_id: string;
  candidate_label: string;
  strategy: string;
  total_score: number;
  score_breakdown: ScoreBreakdown;
  is_preferred: boolean;
  status: string;
  svg_url: string;
  rooms: RoomData[];
  circulation_area_sqft: number;
  total_room_area_sqft: number;
  total_allocated_sqft: number;
  total_seats?: number;
  screen_count?: number;
  seats_per_screen?: number;
}

export interface FloorRegionData {
  region_id: string;
  plan_region: string;
  document: string;
  decision_status: 'DECISION_READY' | 'VALID_REVIEW_REQUIRED' | 'BLOCKED_NO_VERIFIED_BOUNDARY';
  is_blocked: boolean;
  m5_preferred_candidate_id: string | null;
  m5_preferred_score: number | null;
  candidates: CandidateData[];
  selected_candidate_id: string;
  preferred_svg_url: string;
  decision_svg_url: string;
  review_svg_url: string;
  rooms: RoomData[];
  blocker_message?: string;
  has_review_required: boolean;
  uncertainty_penalty: number;
  feasibility?: FeasibilityData;
  area_seat_chart?: AreaSeatChart;
}

export interface LayerVisibility {
  cadLinework: boolean;
  verifiedBoundary: boolean;
  generatedRooms: boolean;
  circulation: boolean;
  columns: boolean;
  hardObstructions: boolean;
  uncertainGeometry: boolean;
  reviewRequired: boolean;
  dimensions: boolean;
  provenance: boolean;
}

export interface ProcessingStep {
  id: string;
  label: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED';
}

export interface CadUploadState {
  file: {
    name: string;
    size: number;
    formattedSize: string;
  } | null;
  status: 'IDLE' | 'UPLOADING' | 'PROCESSING' | 'SUCCESS' | 'ERROR';
  currentStepIndex: number;
  steps: ProcessingStep[];
  errorMessage: string | null;
  isDemoData: boolean;
}

export interface RevisionItem {
  revision_id: string;
  region_id: string;
  source_candidate_id: string;
  revision_type: string;
  target_room: string;
  score_before: number;
  score_after: number;
  score_delta: number;
  room_area_before: number;
  room_area_after: number;
  area_delta: number;
  comment: string;
  status: 'VALIDATED' | 'VALIDATION_FAILED';
  validation_error?: string;
}

export interface HumanReviewDecision {
  region_id: string;
  candidate_id: string;
  reviewer_name: string;
  reviewer_role: string;
  decision: 'PENDING_REVIEW' | 'ACCEPT' | 'REJECT' | 'REQUEST_REVISION' | 'REQUEST_FIELD_VERIFICATION';
  comment: string;
  timestamp: string;
}
