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
  /** Set only when AI-assisted classification (see ai_obstacle_classify.py)
   * refined this obstacle's classification or pre-ignored it as likely
   * non-physical annotation — always reversible, never a substitute for the
   * architect's own Confirm/Ignore. */
  ai_note?: string;
}

export interface TextLabel {
  text: string;
  position_ft: [number, number];
}

export interface Boundary {
  source_handle: string;
  layer: string;
  // 'manual-shape' | 'manual-walls' | 'manual-draw' too — a boundary the
  // architect defined directly (build_manual_region in cad_extraction.py),
  // not just what the automatic pass produced. Was typed as only the two
  // automatic values, which happened to still compile everywhere manual
  // boundaries actually flow through (TS widens a literal-union mismatch to
  // an error only where the narrower type is read against, not just passed
  // around) but was quietly wrong.
  source: 'explicit' | 'reconstructed' | 'manual-shape' | 'manual-walls' | 'manual-draw';
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

/** One line segment from the entire drawing, in feet — the raw material for
 * the "select lines to assume as walls" boundary-definition tool. `id` is
 * stable within one geometry.json (positional), used to reference specific
 * segments when tracing a boundary from a selection of them. */
export interface RawSegment {
  id: number;
  a: [number, number];
  b: [number, number];
  layer: string;
  /** "annotation" = a dimension extension line or leader callout. "sheet" =
   * a line on a drafting-sheet-artifact layer (viewport frame, plot margin,
   * title block, area-calculation callout — never real architecture, see
   * cad_extraction.py's NON_PHYSICAL_LAYER_HINTS). Both are real content,
   * rendered for completeness, but never a real wall — the backend already
   * excludes both from boundary/obstacle detection and wall-network
   * reconstruction. "geometry" is everything else. Lets the viewer visually
   * tell drawing from documentation/sheet noise. */
  category: 'geometry' | 'annotation' | 'sheet';
  /** Shared id for every fragment ezdxf's flattening broke one continuous
   * curved entity (ARC/SPLINE/full-sweep ELLIPSE) into — a real 90-degree
   * ARC on a real file flattened into 66 individually-tiny straight
   * fragments, making pixel-precise clicking on each one to select a
   * curved wall genuinely impractical. Null for LINE/LWPOLYLINE/POLYLINE
   * fragments, which stay individually selectable (see BoundaryStudio's
   * Shift+drag partial-select). BoundaryStudio selects/hovers every
   * fragment sharing a curve_group together as one unit. */
  curve_group: string | null;
}

/** Every closed shape found anywhere in the drawing (not just the ones the
 * automatic heuristic chose as boundary candidates) — the raw material for
 * the "click a closed shape" boundary-definition tool. */
export interface RawClosedShape {
  id: string;
  handle: string;
  layer: string;
  dxftype: string;
  source: string;
  area_sqft: number;
  points_ft: number[][];
}

/** The ENTIRE drawing, uncropped — distinct from each region's own cropped
 * `raw_geometry` (which only covers that region's bounding box). Feeds the
 * boundary-selection tool that runs before any region even exists. */
export interface FullRawGeometry {
  lines: RawSegment[];
  circles: { center: [number, number]; radius: number; layer: string }[];
  texts: { text: string; position: [number, number] }[];
  closed_shapes: RawClosedShape[];
  bounds_ft: { min_x: number; min_y: number; max_x: number; max_y: number };
  truncated: boolean;
}

export interface GeometryUnits {
  insunits_code: number;
  detected_unit: string;
  feet_per_drawing_unit: number | null;
  needs_user_confirmation: boolean;
  suggested_unit?: string | null;
  suggested_unit_reason?: string | null;
}

export interface GeometryResult {
  schema_version: string;
  source_filename: string;
  conversion_note: string | null;
  /** Set only when the DXF wasn't fully spec-compliant and ezdxf's
   * fault-tolerant recovery reader had to step in (see
   * cad_extraction.py's _read_dxf_with_recovery) — a real, specific
   * "geometry near the affected entities may be incomplete, review
   * carefully" warning, computed on every upload but not previously shown
   * anywhere in the UI. */
  recovery_note: string | null;
  units: GeometryUnits;
  extraction_method: string;
  total_entities_scanned: number;
  total_closed_shapes_found: number;
  region_count: number;
  regions: GeometryRegion[];
  full_raw_geometry?: FullRawGeometry;
  unclassified_text_count: number;
  uploaded_filename?: string;
  uploaded_at?: string;
  // The whole drawing's own linework, independent of whether any region was
  // auto-detected — lets "draw your own boundary" show real CAD backdrop
  // even when region_count is 0. Falls back to per-region raw_geometry when
  // absent (older stored geometry.json from before this field existed).
  raw_geometry?: RawGeometry | null;
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
   * logic is skipped rather than guessing where the entrance is. Now
   * captured at boundary-selection time (BoundaryStudio's EntryExitPicker),
   * not this step — still lives here since it's a real business input
   * alongside the rest of Requirements, not CAD-derived geometry. */
  entry_point_ft: [number, number] | null;
  /** Zero or more marked fire/emergency exit points, same coordinate space
   * and same "architect-marked, never guessed" reasoning as entry_point_ft.
   * Feeds layout_engine's entry-to-exit placement direction and its
   * explicit cross-movement warning (SOP §4.4/§9: "no cross-movement
   * between entry/exit flows"). */
  exit_points_ft: [number, number][] | null;
  /** Real screen width, architect-entered — unlocks the SOP's first-row
   * legibility rule (§4.4/§9: first-row distance >= screen width). When
   * set, seat_engine.estimate_seats() uses it (if larger) as the effective
   * front setback instead of the bare 3ft screen-to-wall minimum, so
   * seat-packing satisfies the rule by construction. Null when not yet
   * captured — the rule then reports INSUFFICIENT_DATA rather than a guess. */
  screen_width_ft: number | null;
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
  // The effective screen-to-first-row setback actually used to pack this
  // room's seats — either the bare SCREEN_TO_BACK_WALL_MIN_FT norm, or
  // screen_width_ft (Requirements) when that's larger. Feeds the
  // first-row-distance feasibility check server-side; also useful directly
  // as "how far back does row 1 start."
  first_row_distance_ft?: number;
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

export interface FranchiseTier {
  id: string;
  name: string;
  area_min_sqft: number;
  area_max_sqft: number;
  min_screens: number;
  max_screens: number;
}

export interface SeatConfig {
  primary_seat_type_id: string;
  secondary_seat_type_id: string | null;
  primary_ratio_pct: number;
}

/** One entry/exit door on a room's wall — currently only set on
 * auto-placed/AI-proposed AUDITORIUM rooms (layout_engine.py's
 * _doors_for_screen_wall), derived from screen_wall below, not
 * independently placed. offset_ft is measured along `wall` from its start
 * corner — (origin_ft.x, origin_ft.y) for a min_y/max_y wall, in the
 * direction of increasing X; (origin_ft.x, origin_ft.y) for a min_x/max_x
 * wall, in the direction of increasing Y. See EditableCanvas.tsx's door
 * rendering for the geometry this maps to. */
export interface RoomDoor {
  kind: 'ENTRY' | 'EXIT';
  wall: 'min_x' | 'max_x' | 'min_y' | 'max_y';
  offset_ft: number;
  width_ft: number;
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
  // Which of this room's own edges is the screen wall — geometry-relative,
  // never a compass direction (see layout_engine.py's
  // _screen_wall_for_rect for why). Auditoriums only; defaults to 'min_y'
  // server-side when unset, matching this app's original hardcoded
  // assumption, so older stored layouts render identically to before this
  // field existed.
  screen_wall?: 'min_x' | 'max_x' | 'min_y' | 'max_y';
  doors?: RoomDoor[];
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
