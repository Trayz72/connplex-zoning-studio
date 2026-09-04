import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GeometryResult, GeometryRegion, RawClosedShape, RawSegment, FullRawGeometry } from '../../types/live';
import * as engine from '../../services/zoningEngineApi';
import { ArrowRightIcon, RefreshIcon, WarningIcon } from '../Icons';
import { EntryExitPicker } from './EntryExitPicker';

interface BoundaryStudioProps {
  projectId: string;
  geometry: GeometryResult;
  onGeometryUpdated: (geometry: GeometryResult) => void;
  /** entryPointFt/exitPointsFt are optional: undefined means "not touched
   * on this screen" (ZoningWorkspace keeps whatever it already had), so a
   * caller that hasn't reached the entry/exit sub-step yet (there isn't
   * one — see PendingChoice below, every path through this component now
   * goes through it) never accidentally clears previously-marked points. */
  onBoundaryChosen: (geometry: GeometryResult, regionId: string, entryPointFt?: [number, number] | null, exitPointsFt?: [number, number][]) => void;
  onStartOver: () => void;
}

/** A boundary the architect has picked (auto-detected, shape-clicked,
 * wall-traced, or hand-drawn) but not yet finalized — see the render branch
 * below this replaces every direct onBoundaryChosen call with, so entry/exit
 * marking always happens right after a boundary is chosen and before
 * advancing to Geometry Review, regardless of which of the four selection
 * paths got there. */
interface PendingChoice {
  geometry: GeometryResult;
  regionId: string;
}

type Tool = 'browse' | 'shape' | 'walls' | 'draw';

/** A sub-portion of a single wall line, dragged out by hand instead of
 * picking the whole pre-computed segment — see the drag interaction in
 * onBgPointerDown/Move/Up and PARTIAL_WALL_MIN_DRAG_FT below. */
interface PartialWall {
  id: string;
  sourceLineId: number;
  a: [number, number];
  b: [number, number];
}

const UNIT_OPTIONS = ['Feet', 'Inches', 'Meters', 'Centimeters', 'Millimeters'];
// A real single floor plate essentially never legitimately produces more
// than a handful of candidate boundary regions -- found via a real case
// where confirming a file at "Feet" instead of the (correctly) suggested
// "Inches" scaled every dimension 12x (area 144x), pushing hundreds of
// small real objects (columns, hatch fills) over the boundary-candidate
// area threshold and producing 537 bogus "regions". The existing oversized-
// single-boundary check (backend MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT) didn't
// catch this at all -- that case's largest region was ~463,000 sqft,
// comfortably under its 500,000 sqft cutoff, even though the dataset was
// obviously wrong. This is a distinct, real signal: too MANY regions, not
// one too-large region.
const IMPLAUSIBLE_REGION_COUNT = 20;
// Below this drag distance (in feet, real-world scale — not screen pixels,
// so it behaves the same at any zoom level), a pointerdown-drag-pointerup
// on a wall line is treated as a plain click (toggle the whole segment)
// rather than a deliberate partial-segment selection.
const PARTIAL_WALL_MIN_DRAG_FT = 0.75;
// A real drawing can span thousands of feet (this file's own extent is
// ~1,514 x 807ft) while an individual detail worth clicking precisely — a
// curve fragment, a tight wall junction — can be under a foot, so the
// zoom range needs several more orders of magnitude of headroom than a
// typical map/image viewer. 40x (the previous cap) meant "zoomed all the
// way in" on a 1,500ft-wide drawing still showed ~37ft across — nowhere
// near enough to click a single wall precisely.
const MIN_ZOOM = 0.05;
const MAX_ZOOM = 4000;

function distPointToSegment(p: [number, number], a: [number, number], b: [number, number]): number {
  const [px, py] = p, [ax, ay] = a, [bx, by] = b;
  const dx = bx - ax, dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq > 0 ? ((px - ax) * dx + (py - ay) * dy) / lenSq : 0;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx, cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

/** Closest point to `p` on the segment a-b, clamped to the segment's own
 * extent (not the infinite line) — used to turn a drag gesture into a real
 * sub-portion of a specific wall for partial-segment selection. */
function projectPointOnSegment(p: [number, number], a: [number, number], b: [number, number]): [number, number] {
  const [px, py] = p, [ax, ay] = a, [bx, by] = b;
  const dx = bx - ax, dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq > 0 ? ((px - ax) * dx + (py - ay) * dy) / lenSq : 0;
  t = Math.max(0, Math.min(1, t));
  return [ax + t * dx, ay + t * dy];
}

function distPointToPolygonBoundary(p: [number, number], points: number[][]): number {
  let best = Infinity;
  for (let i = 0; i < points.length; i++) {
    const a = points[i] as [number, number];
    const b = points[(i + 1) % points.length] as [number, number];
    best = Math.min(best, distPointToSegment(p, a, b));
  }
  return best;
}

function pointInPolygon(p: [number, number], points: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i][0], yi = points[i][1];
    const xj = points[j][0], yj = points[j][1];
    const intersect = (yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function shoelaceArea(points: number[][]): number {
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

/** Uniform grid spatial index over every closed shape and line segment, so
 * hover/click hit-testing only scans the handful of items near the cursor
 * instead of linear-scanning the whole drawing. Necessary at real scale —
 * measured directly against a real ~21,000-shape / 25,000-line file: every
 * hover event took 16-32ms (audibly janky) with a plain linear scan, versus
 * sub-millisecond with this index. Built once per upload (useMemo keyed on
 * `raw`), not per pointer move. */
interface SpatialIndex {
  cellSize: number;
  minX: number;
  minY: number;
  shapeCells: Map<string, RawClosedShape[]>;
  segmentCells: Map<string, RawSegment[]>;
}

function cellRange(minV: number, maxV: number, origin: number, cellSize: number): [number, number] {
  return [Math.floor((minV - origin) / cellSize), Math.floor((maxV - origin) / cellSize)];
}

function buildSpatialIndex(raw: FullRawGeometry, bbox: { minX: number; minY: number; width: number; height: number }): SpatialIndex {
  // ~60x60 grid regardless of drawing size/aspect — a fixed cell budget
  // rather than a fixed cell size, since real files range from a single
  // small room to a multi-thousand-foot multi-tenant complex.
  const cellSize = Math.max(bbox.width, bbox.height) / 60 || 1;
  const shapeCells = new Map<string, RawClosedShape[]>();
  const segmentCells = new Map<string, RawSegment[]>();

  const addToCells = <T,>(map: Map<string, T[]>, minx: number, miny: number, maxx: number, maxy: number, item: T) => {
    const [cx0, cx1] = cellRange(minx, maxx, bbox.minX, cellSize);
    const [cy0, cy1] = cellRange(miny, maxy, bbox.minY, cellSize);
    for (let cx = cx0; cx <= cx1; cx++) {
      for (let cy = cy0; cy <= cy1; cy++) {
        const key = `${cx},${cy}`;
        let bucket = map.get(key);
        if (!bucket) { bucket = []; map.set(key, bucket); }
        bucket.push(item);
      }
    }
  };

  for (const s of raw.closed_shapes) {
    const xs = s.points_ft.map(p => p[0]);
    const ys = s.points_ft.map(p => p[1]);
    addToCells(shapeCells, Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys), s);
  }
  for (const ln of raw.lines) {
    addToCells(
      segmentCells,
      Math.min(ln.a[0], ln.b[0]), Math.min(ln.a[1], ln.b[1]),
      Math.max(ln.a[0], ln.b[0]), Math.max(ln.a[1], ln.b[1]),
      ln
    );
  }

  return { cellSize, minX: bbox.minX, minY: bbox.minY, shapeCells, segmentCells };
}

/** Every item registered in the 3x3 cell neighborhood around `p` (a fixed
 * radius in cells, not feet — cheap and always covers `p +/- tolerance` for
 * any realistic tolerance relative to the grid's own cell size). Dedupes
 * since a large shape/segment can be registered in multiple cells. */
function queryNearby<T>(map: Map<string, T[]>, p: [number, number], index: SpatialIndex): T[] {
  const cx = Math.floor((p[0] - index.minX) / index.cellSize);
  const cy = Math.floor((p[1] - index.minY) / index.cellSize);
  const seen = new Set<T>();
  const out: T[] = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const bucket = map.get(`${cx + dx},${cy + dy}`);
      if (!bucket) continue;
      for (const item of bucket) {
        if (!seen.has(item)) { seen.add(item); out.push(item); }
      }
    }
  }
  return out;
}

type Preview = { points: number[][]; mode: 'shape' | 'walls' | 'draw'; sourceHandle?: string };

// Above this many candidates, listing every one as its own button (a real
// case produced 537 of them — a botched unit choice inflating hundreds of
// small real objects into boundary-sized candidates, see
// IMPLAUSIBLE_REGION_COUNT above) floods the whole sidebar and pushes the
// actual floor-plan view off-screen. Below it, the plain always-visible
// list is a nicer one-click switcher than hiding a handful of candidates
// behind an extra click.
const REGION_LIST_COMPACT_THRESHOLD = 8;

const RegionCandidateButton: React.FC<{ region: GeometryRegion; index: number; onChoose: (regionId: string) => void }> = ({ region, index, onChoose }) => (
  <button
    className="btn btn-secondary"
    style={{ fontSize: '0.72rem', padding: '6px 8px', textAlign: 'left', display: 'flex', justifyContent: 'space-between', width: '100%' }}
    onClick={() => onChoose(region.region_id)}
  >
    <span>Region {index + 1} — {region.boundary.area_sqft.toLocaleString()} sqft</span>
    <ArrowRightIcon size={13} />
  </button>
);

/** The auto-detected-candidates sidebar list — a plain list of buttons
 * below REGION_LIST_COMPACT_THRESHOLD (the common, real case), collapsed
 * behind a "Show all" toggle above it so an unusually large candidate set
 * doesn't push the actual floor-plan view off-screen. */
const RegionCandidateList: React.FC<{ geometry: GeometryResult; onChoose: (regionId: string) => void }> = ({ geometry, onChoose }) => {
  const [expanded, setExpanded] = useState(false);
  const regions = geometry.regions;

  if (regions.length <= REGION_LIST_COMPACT_THRESHOLD) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {regions.map((r, i) => <RegionCandidateButton key={r.region_id} region={r} index={i} onChoose={onChoose} />)}
      </div>
    );
  }

  const visibleCount = 5;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginBottom: '2px' }}>
        {regions.length} candidates found — unusually many for a real floor plate. Showing the {visibleCount} largest.
      </div>
      {regions.slice(0, visibleCount).map((r, i) => <RegionCandidateButton key={r.region_id} region={r} index={i} onChoose={onChoose} />)}
      {!expanded ? (
        <button className="btn btn-secondary" style={{ fontSize: '0.72rem', padding: '6px 8px' }} onClick={() => setExpanded(true)}>
          Show all {regions.length} candidates
        </button>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '280px', overflowY: 'auto', paddingRight: '2px' }}>
          {regions.slice(visibleCount).map((r, i) => (
            <RegionCandidateButton key={r.region_id} region={r} index={i + visibleCount} onChoose={onChoose} />
          ))}
        </div>
      )}
    </div>
  );
};

export const BoundaryStudio: React.FC<BoundaryStudioProps> = ({ projectId, geometry, onGeometryUpdated, onBoundaryChosen, onStartOver }) => {
  const raw = geometry.full_raw_geometry;
  const svgRef = useRef<SVGSVGElement>(null);
  const [tool, setTool] = useState<Tool>('browse');
  const [zoom, setZoom] = useState(1);
  // The real (x, y) point, in feet, currently at the center of the
  // viewport — replaces an earlier top-left-anchored offset ("pan") that
  // had a real, reported bug: zooming via the +/- buttons shrank the
  // viewBox toward its own fixed top-left corner instead of the current
  // view's center, so the target the architect was trying to zoom into
  // drifted toward the bottom-right on every zoom step, requiring a
  // re-pan after almost every zoom and making "zoom into a specific spot"
  // feel broken. Center-anchoring the viewBox (see viewBox's own
  // computation below) fixes this for free: shrinking a range around its
  // own center just makes it smaller, it doesn't move.
  const [center, setCenter] = useState<{ x: number; y: number } | null>(null);
  const [hoveredShapeId, setHoveredShapeId] = useState<string | null>(null);
  // The full set of fragment ids to highlight on hover — just the one
  // nearest segment normally, or every fragment of a curve group when the
  // nearest segment belongs to one (see groupIdsFor/curveGroupMembers).
  const [hoveredSegmentIds, setHoveredSegmentIds] = useState<Set<number>>(new Set());
  const [selectedWallIds, setSelectedWallIds] = useState<Set<number>>(new Set());
  // A wall drawn as one long LINE entity often has only part of its length
  // actually on the boundary being defined -- click-and-drag along a wall
  // (see onBgPointerDown/Move/Up) selects just that sub-portion instead of
  // the whole pre-computed segment, added here rather than into
  // selectedWallIds since it isn't one of full_raw_geometry's segments at
  // all (see the backend's custom_segments param).
  const [partialWalls, setPartialWalls] = useState<PartialWall[]>([]);
  const [dragPreview, setDragPreview] = useState<{ lineId: number; a: [number, number]; b: [number, number] } | null>(null);
  const [drawPoints, setDrawPoints] = useState<number[][]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  // Real dangling-endpoint locations from a failed trace (see
  // BoundaryGapError) — drawn directly on the canvas so "there's a gap
  // somewhere" becomes "it's right here", instead of leaving the architect
  // to hunt through a large, dense drawing for it.
  const [gapPoints, setGapPoints] = useState<[number, number][]>([]);
  // Dangling endpoints paired into probable gaps with real distances (see
  // GapPair/gap_pairs_ft) — lets the trace-error panel offer a real
  // "close this gap" button per gap instead of leaving the architect to
  // manually hunt down and select the missing wall segment by hand.
  const [gapPairs, setGapPairs] = useState<engine.GapPair[]>([]);
  // Gaps the architect has explicitly clicked "close" on — a synthetic
  // straight connector, not real drawn geometry, so kept in its own array
  // (rendered in a visually distinct style, see the SVG below) rather than
  // merged into partialWalls, which are always real wall sub-segments.
  // Combined with partialWalls only at the traceBoundary call itself.
  const [closedGaps, setClosedGaps] = useState<engine.GapPair[]>([]);
  const [tracing, setTracing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [selectedUnit, setSelectedUnit] = useState(geometry.units.suggested_unit || 'Feet');
  const [confirmingUnit, setConfirmingUnit] = useState(false);
  const [unitsDismissed, setUnitsDismissed] = useState(false);
  const [manualOverride, setManualOverride] = useState(false);
  const [autoFired, setAutoFired] = useState(false);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice | null>(null);
  const [unitMismatchWarning, setUnitMismatchWarning] = useState<string | null>(null);
  const [pendingEntry, setPendingEntry] = useState<[number, number] | null>(null);
  const [pendingExits, setPendingExits] = useState<[number, number][]>([]);

  const panStart = useRef<{ x: number; y: number; centerX: number; centerY: number } | null>(null);
  const movedRef = useRef(false);
  const wallDragRef = useRef<{ lineId: number; lineA: [number, number]; lineB: [number, number] } | null>(null);

  // Full end-to-end automation, matching the same "auto-advance on a clean
  // detection" pattern GeometryReviewStep already uses one step later: the
  // architect who never touches this screen should still land on a real,
  // reviewable layout — the manual tools below exist for when the automatic
  // candidate is wrong or missing, not as a required step. `regions` is
  // already sorted best-first by the backend, so [0] is the same "best
  // guess" a human would pick first. A boundary carrying a `note` (implausible
  // size, or reconstructed with no wall-layer evidence) never auto-advances —
  // same gate, same reasoning as Geometry Review's own auto mode.
  //
  // Ambiguous units are an equally hard stop, checked independently of the
  // boundary's own note: a file with unspecified $INSUNITS can easily produce
  // a boundary that *looks* clean (a single, plausible explicit closed
  // polyline) at completely the wrong real-world scale — found on a real file
  // where this screen auto-advanced straight past the units-confirmation UI,
  // leaving the architect on Geometry Review with only a read-only warning
  // and no way to actually fix it (this component owns the real fix control,
  // the dropdown a few lines below).
  const bestRegion = geometry.regions[0];
  const boundaryIsClean = !!bestRegion && !bestRegion.boundary.note;
  const unitsConfirmed = !geometry.units.needs_user_confirmation || unitsDismissed;
  const autoMode = boundaryIsClean && unitsConfirmed && !manualOverride;
  const AUTO_ADVANCE_MS = 1800;

  useEffect(() => {
    if (!autoMode || autoFired) return;
    const t = setTimeout(() => {
      setAutoFired(true);
      setPendingChoice({ geometry, regionId: bestRegion.region_id });
    }, AUTO_ADVANCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode, autoFired]);

  const bbox = useMemo(() => {
    const b = raw?.bounds_ft || { min_x: 0, min_y: 0, max_x: 100, max_y: 100 };
    const pad = Math.max(b.max_x - b.min_x, b.max_y - b.min_y) * 0.08 + 2;
    return { minX: b.min_x - pad, minY: b.min_y - pad, width: (b.max_x - b.min_x) + 2 * pad, height: (b.max_y - b.min_y) + 2 * pad };
  }, [raw]);

  // Re-centers on a fresh drawing (a new upload, or CAD-file replacement —
  // bbox's identity changes only when `raw` itself changes, not on every
  // render) instead of leaving the view pointed at whatever the previous
  // file's coordinates happened to be.
  useEffect(() => {
    setCenter({ x: bbox.minX + bbox.width / 2, y: bbox.minY + bbox.height / 2 });
    setZoom(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bbox]);

  const spatialIndex = useMemo(() => (raw ? buildSpatialIndex(raw, bbox) : null), [raw, bbox]);
  const annotationLineCount = useMemo(
    () => raw ? raw.lines.reduce((n, ln) => n + (ln.category === 'annotation' ? 1 : 0), 0) : 0,
    [raw]
  );
  // "sheet" lines (viewport frames, plot margins, title blocks, area-callout
  // hatching) are real content — worth rendering so the drawing looks
  // complete — but not real architecture. Found via a real file where a
  // prominent, long diagonal MARGIN-layer line was the single most visually
  // confusing thing on screen: indistinguishable from a real wall, and
  // (before this) fully selectable as one in the Select Walls tool.
  const sheetLineCount = useMemo(
    () => raw ? raw.lines.reduce((n, ln) => n + (ln.category === 'sheet' ? 1 : 0), 0) : 0,
    [raw]
  );
  // Maps every fragment id belonging to a flattened curve (ARC/SPLINE/full
  // ELLIPSE — see cad_extraction.py's curve_group) to every other fragment
  // id of that same real curve, so clicking or hovering any one fragment
  // can act on the whole curve — a real 90-degree ARC on a real file
  // flattens into 66 individually tiny fragments, making per-fragment
  // clicking genuinely impractical, not just inconvenient.
  const curveGroupMembers = useMemo(() => {
    const map = new Map<string, number[]>();
    if (!raw) return map;
    for (const ln of raw.lines) {
      if (!ln.curve_group) continue;
      const arr = map.get(ln.curve_group);
      if (arr) arr.push(ln.id); else map.set(ln.curve_group, [ln.id]);
    }
    return map;
  }, [raw]);
  // "Selected Walls" count as a human would count them — one curve (however
  // many tiny fragments it flattened into) is one wall, not 66.
  const selectedUnitCount = useMemo(() => {
    if (!raw) return selectedWallIds.size;
    const seenGroups = new Set<string>();
    let count = 0;
    for (const id of selectedWallIds) {
      const group = raw.lines[id]?.curve_group;
      if (group) {
        if (seenGroups.has(group)) continue;
        seenGroups.add(group);
      }
      count++;
    }
    return count;
  }, [raw, selectedWallIds]);
  const groupIdsFor = useCallback((segmentId: number): number[] => {
    // full_raw_geometry.lines is built with id === its own array index
    // (cad_extraction.py appends with "id": len(lines)), so this is a
    // direct O(1) lookup, not a scan.
    const ln = raw?.lines[segmentId];
    if (!ln?.curve_group) return [segmentId];
    return curveGroupMembers.get(ln.curve_group) || [segmentId];
  }, [raw, curveGroupMembers]);

  const viewBoxWidth = bbox.width / zoom;
  const viewBoxHeight = bbox.height / zoom;
  const viewCenter = center || { x: bbox.minX + bbox.width / 2, y: bbox.minY + bbox.height / 2 };
  const originX = viewCenter.x - viewBoxWidth / 2;
  const originY = viewCenter.y - viewBoxHeight / 2;
  const viewBox = `${originX} ${originY} ${viewBoxWidth} ${viewBoxHeight}`;

  const screenToUser = useCallback((clientX: number, clientY: number): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return [0, 0];
    const userPt = pt.matrixTransform(ctm.inverse());
    return [userPt.x, userPt.y];
  }, []);

  // Zooms by `factor`, keeping whatever real point is currently under
  // (clientX, clientY) visually fixed on screen — the standard "zoom to
  // cursor" behavior every map/CAD/vector tool has, and the fix for
  // "zooming in and out isn't good enough, can't get to a specific part":
  // the +/- buttons (called with the viewport's own center, see their
  // onClick below) and the wheel handler both go through this, so there's
  // one real implementation of "zoom toward a point" instead of the
  // buttons silently drifting toward a fixed corner the way the earlier
  // top-left-anchored viewBox did.
  const zoomAtScreenPoint = useCallback((clientX: number, clientY: number, factor: number) => {
    const svg = svgRef.current;
    const rect = svg?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) {
      setZoom(z => Math.min(Math.max(z * factor, MIN_ZOOM), MAX_ZOOM));
      return;
    }
    const focusUser = screenToUser(clientX, clientY);
    const screenFracX = (clientX - rect.left) / rect.width;
    const screenFracY = (clientY - rect.top) / rect.height;
    setZoom(prevZoom => {
      const newZoom = Math.min(Math.max(prevZoom * factor, MIN_ZOOM), MAX_ZOOM);
      const newViewBoxWidth = bbox.width / newZoom;
      const newViewBoxHeight = bbox.height / newZoom;
      setCenter({
        x: focusUser[0] + newViewBoxWidth * (0.5 - screenFracX),
        y: focusUser[1] + newViewBoxHeight * (0.5 - screenFracY),
      });
      return newZoom;
    });
  }, [bbox, screenToUser]);

  // Mouse-wheel zoom, centered on the cursor — the single most expected
  // interaction for any pannable/zoomable canvas, and previously missing
  // entirely (only the tiny +/- buttons existed, 1.3x per click, with no
  // way to zoom without moving the mouse to the sidebar and back). A
  // native, non-passive listener (not React's onWheel prop, which React
  // attaches passively by default) so preventDefault() reliably stops the
  // page/pane from scrolling instead of zooming.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const factor = Math.exp(-e.deltaY * 0.0015);
      zoomAtScreenPoint(e.clientX, e.clientY, factor);
    };
    svg.addEventListener('wheel', handler, { passive: false });
    return () => svg.removeEventListener('wheel', handler);
    // pendingChoice/autoMode: the ref-bearing <svg> only exists in this
    // component's final ("main canvas") return branch — pendingChoice and
    // autoMode are two *separate* early returns above it with no <svg
    // ref={svgRef}> of their own, so svgRef.current is null (or a stale
    // node from before a branch switch) the whole time either is truthy.
    // Without depending on them here, landing back on the main canvas
    // after either screen left the listener attached to nothing, and wheel
    // zoom silently did nothing — found by testing the feature against
    // itself, not assumed to work from the code reading right.
  }, [zoomAtScreenPoint, pendingChoice, autoMode]);

  const toleranceFt = () => {
    const svg = svgRef.current;
    const widthPx = svg?.getBoundingClientRect().width || 800;
    return (viewBoxWidth / widthPx) * 9; // ~9 screen px hit tolerance regardless of zoom
  };

  const nearestShape = (p: [number, number]): { shape: RawClosedShape; dist: number } | null => {
    if (!raw || !spatialIndex) return null;
    const tol = toleranceFt();
    const candidates = queryNearby(spatialIndex.shapeCells, p, spatialIndex);
    let best: { shape: RawClosedShape; dist: number } | null = null;
    for (const s of candidates) {
      const d = distPointToPolygonBoundary(p, s.points_ft);
      if (d <= tol && (!best || d < best.dist)) best = { shape: s, dist: d };
    }
    if (best) return best;
    // Fall back to "smallest shape containing this point" — most clicks will
    // land inside a room/shape, not exactly on its outline. A shape whose
    // interior contains p must have a bounding box overlapping p's own grid
    // cell, so the same spatial query already covers this case.
    let smallest: RawClosedShape | null = null;
    for (const s of candidates) {
      if (pointInPolygon(p, s.points_ft) && (!smallest || s.area_sqft < smallest.area_sqft)) smallest = s;
    }
    return smallest ? { shape: smallest, dist: 0 } : null;
  };

  const nearestSegment = (p: [number, number]): { id: number; dist: number } | null => {
    if (!raw || !spatialIndex) return null;
    const tol = toleranceFt();
    const candidates = queryNearby(spatialIndex.segmentCells, p, spatialIndex);
    let best: { id: number; dist: number } | null = null;
    for (const ln of candidates) {
      // A dimension/leader line or a sheet-artifact line (viewport frame,
      // margin, title block) is never a real wall — the backend already
      // excludes both from its own wall-reconstruction pass (see
      // cad_extraction.py's annotation_ids / NON_PHYSICAL_LAYER_HINTS), so
      // tracing a boundary through one here would trace something that was
      // never structural.
      if (ln.category === 'annotation' || ln.category === 'sheet') continue;
      const d = distPointToSegment(p, ln.a, ln.b);
      if (d <= tol && (!best || d < best.dist)) best = { id: ln.id, dist: d };
    }
    return best;
  };

  const updateHover = (e: React.PointerEvent) => {
    const p = screenToUser(e.clientX, e.clientY);
    if (tool === 'shape') {
      setHoveredShapeId(nearestShape(p)?.shape.id || null);
    } else if (tool === 'walls') {
      const hit = nearestSegment(p);
      setHoveredSegmentIds(hit ? new Set(groupIdsFor(hit.id)) : new Set());
    }
  };

  const handleClickAt = (p: [number, number]) => {
    setTraceError(null);
    setGapPoints([]);
    if (tool === 'shape') {
      const hit = nearestShape(p);
      if (hit) setPreview({ points: hit.shape.points_ft, mode: 'shape', sourceHandle: hit.shape.handle });
    } else if (tool === 'walls') {
      const tol = toleranceFt();
      // A plain click that lands on an already-selected partial segment
      // removes it — the drag interaction (onBgPointerDown/Move/Up) is what
      // creates one, so a plain click here can only mean "undo that".
      const hitPartial = partialWalls.find(pw => distPointToSegment(p, pw.a, pw.b) <= tol);
      if (hitPartial) {
        setPartialWalls(prev => prev.filter(pw => pw.id !== hitPartial.id));
        return;
      }
      const hit = nearestSegment(p);
      if (hit) {
        // A curved entity's fragments are toggled as one unit (see
        // groupIdsFor) — clicking any one fragment of a real 90-degree ARC
        // that flattened into 66 tiny pieces selects/deselects the whole
        // real curve, not just the one fragment under the cursor.
        const groupIds = groupIdsFor(hit.id);
        const alreadySelected = selectedWallIds.has(hit.id);
        setSelectedWallIds(prev => {
          const next = new Set(prev);
          for (const id of groupIds) {
            if (alreadySelected) next.delete(id); else next.add(id);
          }
          return next;
        });
      }
    } else if (tool === 'draw') {
      if (drawPoints.length >= 3) {
        const tol = toleranceFt();
        const [fx, fy] = drawPoints[0];
        if (Math.hypot(p[0] - fx, p[1] - fy) <= tol) {
          setPreview({ points: drawPoints, mode: 'draw' });
          return;
        }
      }
      setDrawPoints(prev => [...prev, [p[0], p[1]]]);
    }
  };

  const onBgPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    movedRef.current = false;

    // Shift+drag right on a wall line, in Select Walls mode, means "select
    // part of this wall" (see onBgPointerMove/Up below). Gated on Shift
    // specifically so a *plain* drag always pans, with zero behavior change
    // from before this feature existed — found via testing that an
    // ungated version hijacked ordinary panning any time a pan gesture
    // happened to start on top of a wall line, which in a dense CAD
    // drawing is most of the canvas.
    if (tool === 'walls' && e.shiftKey) {
      const p = screenToUser(e.clientX, e.clientY);
      const hit = nearestSegment(p);
      const line = hit ? raw?.lines.find(l => l.id === hit.id) : null;
      if (line) {
        wallDragRef.current = { lineId: line.id, lineA: line.a, lineB: line.b };
        // The actual pointer-down position projected onto the line, not the
        // line's own fixed endpoint — using line.a here (an earlier version
        // of this code did) made the "drag distance" computed on pointerup
        // the distance from the line's *end* to wherever the click landed,
        // which is often large even for a perfectly stationary click on a
        // long wall, incorrectly registering plain clicks as partial-drags.
        const downProjected = projectPointOnSegment(p, line.a, line.b);
        setDragPreview({ lineId: line.id, a: downProjected, b: downProjected });
        return; // no panStart — this is a wall drag, not a pan
      }
    }
    panStart.current = { x: e.clientX, y: e.clientY, centerX: viewCenter.x, centerY: viewCenter.y };
  };

  const onBgPointerMove = (e: React.PointerEvent) => {
    if (wallDragRef.current) {
      const p = screenToUser(e.clientX, e.clientY);
      const { lineA, lineB } = wallDragRef.current;
      const projected = projectPointOnSegment(p, lineA, lineB);
      const start = dragPreview?.a || lineA;
      if (Math.hypot(projected[0] - start[0], projected[1] - start[1]) > 0.05) movedRef.current = true;
      setDragPreview(prev => (prev ? { ...prev, b: projected } : prev));
      return;
    }
    if (!panStart.current) {
      updateHover(e);
      return;
    }
    const dxPx = e.clientX - panStart.current.x;
    const dyPx = e.clientY - panStart.current.y;
    if (Math.abs(dxPx) > 4 || Math.abs(dyPx) > 4) movedRef.current = true;
    if (!movedRef.current) return;
    const svg = svgRef.current;
    const rect = svg?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return;
    const ftPerPxX = viewBoxWidth / rect.width;
    const ftPerPxY = viewBoxHeight / rect.height;
    setCenter({
      x: panStart.current.centerX - dxPx * ftPerPxX,
      y: panStart.current.centerY - dyPx * ftPerPxY,
    });
  };

  const onBgPointerUp = (e: React.PointerEvent) => {
    if (wallDragRef.current) {
      const p = screenToUser(e.clientX, e.clientY);
      const { lineId, lineA, lineB } = wallDragRef.current;
      const start = dragPreview?.a || lineA;
      const end = projectPointOnSegment(p, lineA, lineB);
      const dragDistFt = Math.hypot(end[0] - start[0], end[1] - start[1]);
      if (dragDistFt >= PARTIAL_WALL_MIN_DRAG_FT) {
        setPartialWalls(prev => [...prev, { id: `partial-${Date.now()}-${prev.length}`, sourceLineId: lineId, a: start, b: end }]);
        setGapPoints([]);
      } else {
        // Negligible drag on a wall line — treat it as the plain click it
        // effectively was (toggle the whole segment / remove a partial).
        handleClickAt(p);
      }
      wallDragRef.current = null;
      setDragPreview(null);
      movedRef.current = false;
      return;
    }
    if (!movedRef.current) {
      handleClickAt(screenToUser(e.clientX, e.clientY));
    }
    panStart.current = null;
    movedRef.current = false;
  };

  const runTrace = async () => {
    setTracing(true);
    setTraceError(null);
    setGapPoints([]);
    setGapPairs([]);
    try {
      const result = await engine.traceBoundary(
        projectId, Array.from(selectedWallIds),
        [...partialWalls.map(pw => [pw.a, pw.b] as [number, number][]), ...closedGaps.map(g => [g.a, g.b] as [number, number][])]
      );
      setPreview({ points: result.points_ft, mode: 'walls' });
    } catch (e: any) {
      setTraceError(e.message || 'Could not trace a closed boundary from these segments.');
      if (e instanceof engine.BoundaryGapError) {
        setGapPoints(e.gapPointsFt);
        // A gap already closed on a previous pass may still show up in a
        // fresh gap list if closing it revealed another real gap further
        // along — only offer "close" on ones not already bridged.
        setGapPairs(e.gapPairsFt.filter(p => !closedGaps.some(cg => cg.a[0] === p.a[0] && cg.a[1] === p.a[1] && cg.b[0] === p.b[0] && cg.b[1] === p.b[1])));
      }
    } finally {
      setTracing(false);
    }
  };

  const closeGap = async (pair: engine.GapPair) => {
    const updatedClosedGaps = [...closedGaps, pair];
    setClosedGaps(updatedClosedGaps);
    setGapPairs(prev => prev.filter(p => p !== pair));
    setTracing(true);
    setTraceError(null);
    setGapPoints([]);
    try {
      const result = await engine.traceBoundary(
        projectId, Array.from(selectedWallIds),
        [...partialWalls.map(pw => [pw.a, pw.b] as [number, number][]), ...updatedClosedGaps.map(g => [g.a, g.b] as [number, number][])]
      );
      setPreview({ points: result.points_ft, mode: 'walls' });
      setGapPairs([]);
    } catch (e: any) {
      setTraceError(e.message || 'Could not trace a closed boundary from these segments.');
      if (e instanceof engine.BoundaryGapError) {
        setGapPoints(e.gapPointsFt);
        setGapPairs(e.gapPairsFt.filter(p => !updatedClosedGaps.some(cg => cg.a[0] === p.a[0] && cg.a[1] === p.a[1] && cg.b[0] === p.b[0] && cg.b[1] === p.b[1])));
      }
    } finally {
      setTracing(false);
    }
  };

  const commitPreview = async () => {
    if (!preview) return;
    setCommitting(true);
    try {
      const updated = await engine.createManualRegion(projectId, preview.points, preview.mode, preview.sourceHandle, closedGaps.length);
      const newRegion = updated.regions[updated.regions.length - 1];
      setPendingChoice({ geometry: updated, regionId: newRegion.region_id });
    } catch (e: any) {
      setTraceError(e.message || 'Could not create a region from this boundary.');
    } finally {
      setCommitting(false);
    }
  };

  const confirmUnit = async (unitOverride?: string) => {
    const unit = unitOverride || selectedUnit;
    setConfirmingUnit(true);
    setUnitMismatchWarning(null);
    try {
      const updated = await engine.confirmUnits(projectId, unit);
      onGeometryUpdated(updated);
      setUnitsDismissed(true);
      const suggested = geometry.units.suggested_unit;
      if (suggested && unit !== suggested && updated.regions.length > IMPLAUSIBLE_REGION_COUNT) {
        setUnitMismatchWarning(
          `Confirming as ${unit} produced ${updated.regions.length} candidate regions — real floor plates essentially `
          + `never produce that many. This file's header evidence actually suggested ${suggested}; that's very `
          + `likely the real unit.`
        );
      }
    } catch {
      // Best-effort — geometry keeps its current (heuristic-default) scale if this fails.
    } finally {
      setConfirmingUnit(false);
    }
  };

  const switchTool = (t: Tool) => {
    setManualOverride(true);
    setTool(t);
    setPreview(null);
    setTraceError(null);
    setGapPoints([]);
    setHoveredShapeId(null);
    setHoveredSegmentIds(new Set());
  };

  if (!raw) {
    return (
      <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        No raw geometry is available for this upload.
      </div>
    );
  }

  // Every boundary-selection path (auto-detect, click-a-shape, trace-walls,
  // freehand-draw, or picking a candidate region) lands here before actually
  // advancing — the one honest place to ask "where's the entrance, and any
  // exits" against the real, now-committed boundary outline, instead of
  // asking again later on a smaller diagram in Requirements once the actual
  // shape being asked about is already several steps back. Both stay
  // optional (nothing here forces an answer — see EntryExitPicker's own
  // docstring), so this never blocks progress the way a hard-required field
  // would.
  if (pendingChoice) {
    const chosenRegion = pendingChoice.geometry.regions.find(r => r.region_id === pendingChoice.regionId);
    const boundaryPts = chosenRegion?.boundary.points_ft || [];
    return (
      <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div className="panel" style={{ padding: '16px' }}>
            <div className="panel-label" style={{ marginBottom: '4px' }}>Boundary Chosen</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)' }} className="font-mono">
              {chosenRegion?.boundary.area_sqft.toLocaleString()} sqft
            </div>
          </div>
          <div style={{ flex: 1, position: 'relative', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden', padding: '12px' }}>
            {boundaryPts.length >= 3 && (
              <EntryExitPicker
                boundaryPointsFt={boundaryPts}
                entryValue={pendingEntry}
                onEntryChange={setPendingEntry}
                exitValues={pendingExits}
                onExitChange={setPendingExits}
                height={480}
              />
            )}
          </div>
        </div>
        <div style={{ width: '320px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="panel" style={{ padding: '16px' }}>
            <div className="panel-label" style={{ marginBottom: '10px' }}>Mark Entrance &amp; Exits</div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              Nothing in the CAD file identifies doors, so this is the one honest way to get this data — mark the
              main entrance and any exits directly on the confirmed boundary. Both are optional: the generator
              still produces a real layout without them (see the warnings on the Edit screen if skipped), but
              marking them enables entry-facing placement of the Foyer/F&amp;B/Washrooms and the SOP's "no
              cross-movement between entry/exit flows" check (§4.4/§9).
            </div>
            <button
              className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem' }}
              onClick={() => {
                const geo = pendingChoice.geometry, regionId = pendingChoice.regionId;
                const entry = pendingEntry, exits = pendingExits;
                setPendingChoice(null);
                onBoundaryChosen(geo, regionId, entry, exits);
              }}
            >
              Continue to Geometry Review <ArrowRightIcon size={14} />
            </button>
            <button
              className="btn btn-secondary" style={{ width: '100%', fontSize: '0.74rem', marginTop: '8px' }}
              onClick={() => setPendingChoice(null)}
            >
              Back to Boundary Selection
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (autoMode) {
    return (
      <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ flex: 1, position: 'relative', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            <svg viewBox={viewBox} style={{ width: '100%', height: '100%' }}>
              <g opacity={0.5}>
                {raw.lines.map(ln => (
                  <line
                    key={ln.id} x1={ln.a[0]} y1={ln.a[1]} x2={ln.b[0]} y2={ln.b[1]}
                    stroke="var(--text-tertiary)" strokeWidth={toleranceFt() * 0.04}
                    strokeOpacity={ln.category === 'annotation' || ln.category === 'sheet' ? 0.35 : 1}
                  />
                ))}
              </g>
              <polygon
                points={bestRegion.boundary.points_ft.map(p => p.join(',')).join(' ')}
                fill="var(--success)" fillOpacity={0.18} stroke="var(--success)" strokeWidth={toleranceFt() * 0.15}
              />
            </svg>
          </div>
        </div>
        <div style={{ width: '340px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="panel" style={{ padding: '16px' }}>
            <div className="panel-label" style={{ marginBottom: '10px' }}>Detected Automatically</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: '4px' }} className="font-mono">
              Floor boundary — {bestRegion.boundary.area_sqft.toLocaleString()} sqft
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              {geometry.regions.length > 1 ? `Largest of ${geometry.regions.length} candidate regions found in this file.` : 'The only candidate region found in this file.'}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              Continuing to obstacle review automatically…
            </div>
            <button className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem', marginBottom: '8px' }}
              onClick={() => { setAutoFired(true); setPendingChoice({ geometry, regionId: bestRegion.region_id }); }}>
              Continue Now <ArrowRightIcon size={14} />
            </button>
            <button className="btn btn-secondary" style={{ width: '100%', fontSize: '0.75rem' }} onClick={() => setManualOverride(true)}>
              Choose a Different Boundary
            </button>
          </div>
        </div>
      </div>
    );
  }

  const previewArea = preview ? shoelaceArea(preview.points) : 0;

  return (
    <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {geometry.units.needs_user_confirmation && !unitsDismissed && (
          <div className="panel" style={{
            display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '10px 12px',
            border: '1px solid rgba(201,154,58,0.4)', background: 'var(--bg-secondary)'
          }}>
            <WarningIcon size={15} className="text-warning" style={{ flex: '0 0 auto', marginTop: '2px' }} />
            <div style={{ flex: 1, fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This file's drawing units aren't specified.{' '}
              {geometry.units.suggested_unit_reason || 'Confirm the real-world unit before trusting any measurement below.'}
            </div>
            <select
              className="select-control"
              value={selectedUnit}
              onChange={(e) => setSelectedUnit(e.target.value)}
            >
              {UNIT_OPTIONS.map(u => (
                <option key={u} value={u}>{u}{u === geometry.units.suggested_unit ? ' (suggested)' : ''}</option>
              ))}
            </select>
            <button className="btn btn-primary btn-sm" style={{ whiteSpace: 'nowrap' }} disabled={confirmingUnit} onClick={() => confirmUnit()}>
              {confirmingUnit ? 'Applying…' : 'Confirm Unit'}
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setUnitsDismissed(true)}>Dismiss</button>
          </div>
        )}

        {unitMismatchWarning && (
          <div className="panel" style={{
            display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '10px 12px',
            border: '1px solid rgba(209,109,100,0.5)', background: 'var(--bg-secondary)'
          }}>
            <WarningIcon size={15} className="text-danger" style={{ flex: '0 0 auto', marginTop: '2px' }} />
            <div style={{ flex: 1, fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {unitMismatchWarning}
            </div>
            <button
              className="btn btn-primary btn-sm" style={{ whiteSpace: 'nowrap' }}
              disabled={confirmingUnit}
              onClick={() => { setSelectedUnit(geometry.units.suggested_unit!); confirmUnit(geometry.units.suggested_unit!); }}
            >
              Use {geometry.units.suggested_unit} instead
            </button>
            <button className="btn btn-secondary btn-sm" style={{ whiteSpace: 'nowrap' }} onClick={() => setUnitMismatchWarning(null)}>
              Keep {selectedUnit}, this is correct
            </button>
          </div>
        )}

        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button className={`btn btn-sm ${tool === 'browse' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('browse')}>Browse</button>
            <button className={`btn btn-sm ${tool === 'shape' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('shape')}>Select Closed Shape</button>
            <button className={`btn btn-sm ${tool === 'walls' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('walls')}>Select Walls</button>
            <button className={`btn btn-sm ${tool === 'draw' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('draw')}>Draw Boundary</button>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onStartOver}>
            <RefreshIcon size={13} /> Replace CAD File
          </button>
        </div>

        <div style={{ flex: 1, position: 'relative', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', zIndex: 10, margin: '10px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => {
              const r = svgRef.current?.getBoundingClientRect();
              if (r) zoomAtScreenPoint(r.left + r.width / 2, r.top + r.height / 2, 1.5);
            }}>+</button>
            <button className="btn btn-secondary btn-sm" onClick={() => {
              const r = svgRef.current?.getBoundingClientRect();
              if (r) zoomAtScreenPoint(r.left + r.width / 2, r.top + r.height / 2, 1 / 1.5);
            }}>−</button>
            <button className="btn btn-secondary btn-sm" onClick={() => {
              setZoom(1);
              setCenter({ x: bbox.minX + bbox.width / 2, y: bbox.minY + bbox.height / 2 });
            }}>Reset</button>
            <span className="badge" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center' }}>
              {raw.lines.length.toLocaleString()} lines · {raw.closed_shapes.length.toLocaleString()} shapes{raw.truncated ? ' (truncated)' : ''}
            </span>
            {annotationLineCount > 0 && (
              <span className="badge" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ display: 'inline-block', width: '14px', borderTop: '1.5px dashed var(--text-tertiary)', opacity: 0.5 }} />
                {annotationLineCount.toLocaleString()} dimension/leader lines (dimmed, not selectable as walls)
              </span>
            )}
            {sheetLineCount > 0 && (
              <span className="badge" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ display: 'inline-block', width: '14px', borderTop: '1.5px dashed var(--text-tertiary)', opacity: 0.5 }} />
                {sheetLineCount.toLocaleString()} sheet frame/margin/title-block lines (dimmed, not selectable as walls)
              </span>
            )}
          </div>

          <svg
            ref={svgRef}
            viewBox={viewBox}
            style={{ width: '100%', height: '100%', touchAction: 'none', cursor: tool === 'draw' ? 'crosshair' : panStart.current && movedRef.current ? 'grabbing' : 'grab' }}
            onPointerDown={onBgPointerDown}
            onPointerMove={onBgPointerMove}
            onPointerUp={onBgPointerUp}
          >
            <g opacity={0.55}>
              {raw.lines.map(ln => (
                <line
                  key={ln.id}
                  x1={ln.a[0]} y1={ln.a[1]} x2={ln.b[0]} y2={ln.b[1]}
                  stroke={selectedWallIds.has(ln.id) ? 'var(--brand-strong)' : hoveredSegmentIds.has(ln.id) ? 'var(--warning)' : 'var(--text-tertiary)'}
                  strokeWidth={(selectedWallIds.has(ln.id) || hoveredSegmentIds.has(ln.id)) ? toleranceFt() * 0.12 : toleranceFt() * 0.04}
                  strokeOpacity={ln.category === 'annotation' || ln.category === 'sheet' ? 0.35 : 1}
                  strokeDasharray={ln.category === 'annotation' || ln.category === 'sheet' ? `${toleranceFt() * 0.3} ${toleranceFt() * 0.2}` : undefined}
                />
              ))}
              {raw.circles.map((c, i) => (
                <circle key={`c${i}`} cx={c.center[0]} cy={c.center[1]} r={c.radius} fill="none" stroke="var(--text-tertiary)" strokeWidth={toleranceFt() * 0.04} />
              ))}
            </g>

            {tool === 'walls' && partialWalls.map(pw => (
              <line
                key={pw.id}
                x1={pw.a[0]} y1={pw.a[1]} x2={pw.b[0]} y2={pw.b[1]}
                stroke="var(--brand-strong)" strokeWidth={toleranceFt() * 0.16} strokeLinecap="round"
              />
            ))}
            {tool === 'walls' && dragPreview && (
              <line
                x1={dragPreview.a[0]} y1={dragPreview.a[1]} x2={dragPreview.b[0]} y2={dragPreview.b[1]}
                stroke="var(--success)" strokeWidth={toleranceFt() * 0.16} strokeLinecap="round"
              />
            )}
            {tool === 'walls' && gapPoints.map((gp, i) => (
              <g key={`gap-${i}`}>
                <circle cx={gp[0]} cy={gp[1]} r={toleranceFt() * 1.4} fill="none" stroke="var(--danger)" strokeWidth={toleranceFt() * 0.12} />
                <circle cx={gp[0]} cy={gp[1]} r={toleranceFt() * 0.35} fill="var(--danger)" />
              </g>
            ))}
            {/* Dashed and a different color from both real selected walls
                (gold) and partial-wall drags (green/gold) on purpose — this
                line was never actually drawn in the source file, it's a
                straight-line assumption the architect explicitly confirmed
                to bridge a real gap. Stays visually distinct through to the
                boundary preview so it's never mistaken for real geometry. */}
            {tool === 'walls' && closedGaps.map((g, i) => (
              <line
                key={`closedgap-${i}`}
                x1={g.a[0]} y1={g.a[1]} x2={g.b[0]} y2={g.b[1]}
                stroke="var(--warning)" strokeWidth={toleranceFt() * 0.16} strokeLinecap="round"
                strokeDasharray={`${toleranceFt() * 0.5} ${toleranceFt() * 0.3}`}
              />
            ))}

            {tool === 'shape' && hoveredShapeId && (() => {
              const s = raw.closed_shapes.find(sh => sh.id === hoveredShapeId);
              return s ? <polygon points={s.points_ft.map(p => p.join(',')).join(' ')} fill="var(--brand-strong)" fillOpacity={0.18} stroke="var(--brand-strong)" strokeWidth={toleranceFt() * 0.1} /> : null;
            })()}

            {tool === 'draw' && drawPoints.length > 0 && (
              <>
                <polyline points={drawPoints.map(p => p.join(',')).join(' ')} fill="none" stroke="var(--brand-strong)" strokeWidth={toleranceFt() * 0.1} />
                {drawPoints.map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={toleranceFt() * 0.35} fill={i === 0 ? 'var(--warning)' : 'var(--brand-strong)'} />
                ))}
              </>
            )}

            {preview && (
              <polygon
                points={preview.points.map(p => p.join(',')).join(' ')}
                fill="var(--success)" fillOpacity={0.15}
                stroke="var(--success)" strokeWidth={toleranceFt() * 0.15} strokeDasharray={`${toleranceFt() * 0.4} ${toleranceFt() * 0.25}`}
              />
            )}
          </svg>
        </div>

        <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', textAlign: 'center' }}>
          Drag empty space to pan · {tool === 'shape' && 'click a closed outline (or inside a room) to select it as the boundary'}
          {tool === 'walls' && 'click a wall line to select it (Shift+drag to select just part of one), then trace a boundary from the selection'}
          {tool === 'draw' && 'click to place points, click near your first point to close the shape'}
          {tool === 'browse' && 'pick a tool above, or use one of the auto-detected candidates on the right'}
        </div>
      </div>

      <div style={{ width: '340px', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
        {/* recovery_note/conversion_note/extraction_method/entity counts are
            all computed on every upload (cad_extraction.py) but had no UI
            anywhere before this — recovery_note in particular is a real,
            specific data-quality warning ("this DXF wasn't fully
            spec-compliant, geometry near the affected entities may be
            incomplete") that was silently discarded on every response. */}
        {geometry.recovery_note && (
          <div className="panel" style={{ borderColor: 'rgba(201,154,58,0.4)' }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
              <WarningIcon size={14} className="text-warning" style={{ flex: '0 0 auto', marginTop: '2px' }} />
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {geometry.recovery_note}
              </div>
            </div>
          </div>
        )}
        <div className="panel">
          <div className="panel-label" style={{ marginBottom: '6px' }}>Source File</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <div className="font-mono" style={{ color: 'var(--text-primary)', wordBreak: 'break-all' }}>{geometry.source_filename}</div>
            {geometry.conversion_note && <div>{geometry.conversion_note}</div>}
            <div>{geometry.total_entities_scanned.toLocaleString()} entities scanned · {geometry.total_closed_shapes_found.toLocaleString()} closed shapes found</div>
            <div style={{ color: 'var(--text-tertiary)' }}>Extraction method: {geometry.extraction_method}</div>
          </div>
        </div>
        <div className="panel">
          <div className="panel-label" style={{ marginBottom: '8px' }}>Auto-Detected Candidates</div>
          {geometry.regions.length === 0 ? (
            <div style={{ fontSize: '0.74rem', color: 'var(--text-tertiary)' }}>
              No candidate boundary was found automatically — use one of the tools on the left to define one manually.
            </div>
          ) : (
            <RegionCandidateList geometry={geometry} onChoose={(regionId) => setPendingChoice({ geometry, regionId })} />
          )}
        </div>

        {tool === 'walls' && (
          <div className="panel">
            <div className="panel-label" style={{ marginBottom: '8px' }}>
              Selected Walls ({selectedUnitCount + partialWalls.length})
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginBottom: '10px' }}>
              Click a wall line to select the whole thing — a curved wall selects as one real curve, however many
              tiny fragments it's drawn from. Hold Shift and drag along a wall to select just part of it (e.g. half
              a long wall) — shown in green while dragging, gold once released. Click a selected partial again to
              remove it. Then trace the boundary they enclose.
            </div>
            {partialWalls.length > 0 && (
              <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginBottom: '10px' }}>
                {partialWalls.length} partial segment{partialWalls.length === 1 ? '' : 's'} selected.
              </div>
            )}
            {closedGaps.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.7rem', color: 'var(--warning)', marginBottom: '10px' }}>
                <span>
                  {closedGaps.length} gap{closedGaps.length === 1 ? '' : 's'} bridged with a straight line, not real
                  drawn geometry — verify against the file before confirming.
                </span>
                <button
                  className="btn btn-secondary" style={{ fontSize: '0.68rem', padding: '2px 6px', flexShrink: 0 }}
                  onClick={() => setClosedGaps([])}
                >
                  Undo all
                </button>
              </div>
            )}
            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                className="btn btn-primary" style={{ fontSize: '0.74rem', flex: 1 }}
                disabled={selectedWallIds.size + partialWalls.length < 3 || tracing}
                onClick={runTrace}
              >
                {tracing ? 'Tracing…' : 'Trace Boundary'}
              </button>
              <button
                className="btn btn-secondary" style={{ fontSize: '0.74rem' }}
                onClick={() => { setSelectedWallIds(new Set()); setPartialWalls([]); setGapPoints([]); setGapPairs([]); setClosedGaps([]); setTraceError(null); }}
              >
                Clear
              </button>
            </div>
          </div>
        )}

        {tool === 'draw' && (
          <div className="panel">
            <div className="panel-label" style={{ marginBottom: '8px' }}>Drawing ({drawPoints.length} points)</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-primary" style={{ fontSize: '0.74rem', flex: 1 }} disabled={drawPoints.length < 3}
                onClick={() => setPreview({ points: drawPoints, mode: 'draw' })}>
                Finish Shape
              </button>
              <button className="btn btn-secondary" style={{ fontSize: '0.74rem' }} onClick={() => setDrawPoints(prev => prev.slice(0, -1))} disabled={drawPoints.length === 0}>Undo</button>
              <button className="btn btn-secondary" style={{ fontSize: '0.74rem' }} onClick={() => setDrawPoints([])} disabled={drawPoints.length === 0}>Clear</button>
            </div>
          </div>
        )}

        {traceError && (
          <div style={{ fontSize: '0.72rem', color: 'var(--danger)', background: 'var(--danger-bg)', border: '1px solid rgba(209,109,100,0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
            <div style={{ marginBottom: gapPoints.length ? '8px' : 0 }}>{traceError}</div>
            {gapPoints.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: gapPairs.length ? '8px' : 0 }}>
                {gapPoints.map((gp, i) => (
                  <button
                    key={i}
                    className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }}
                    onClick={() => { setZoom(60); setCenter({ x: gp[0], y: gp[1] }); }}
                  >
                    Zoom to gap {gapPoints.length > 1 ? i + 1 : ''}
                  </button>
                ))}
              </div>
            )}
            {gapPairs.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {/* Each pair's own real distance is shown right on the button —
                    a 0.4ft gap and a 6ft gap look identical as two red dots on
                    the canvas, but only one of them is safe to bridge with a
                    single click; showing the number lets the architect judge
                    that instead of this UI silently deciding for them. */}
                {gapPairs.map((p, i) => (
                  <button
                    key={i}
                    className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '4px 8px', textAlign: 'left' }}
                    disabled={tracing}
                    onClick={() => closeGap(p)}
                  >
                    Close this gap ({p.distance_ft.toLocaleString(undefined, { maximumFractionDigits: 2 })} ft) — assumes a straight wall, verify before confirming
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {preview && (
          <div className="panel" style={{ borderColor: 'var(--success)' }}>
            <div className="panel-label" style={{ marginBottom: '8px', color: 'var(--success)' }}>Boundary Preview</div>
            <div className="font-mono" style={{ fontSize: '0.8rem', color: 'var(--text-primary)', marginBottom: '10px' }}>
              {previewArea.toLocaleString(undefined, { maximumFractionDigits: 0 })} sqft · {preview.points.length} points
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-primary" style={{ fontSize: '0.78rem', flex: 1 }} disabled={committing} onClick={commitPreview}>
                {committing ? 'Creating…' : 'Use This Boundary'}
              </button>
              <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} onClick={() => setPreview(null)}>Discard</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
