import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GeometryResult, RawClosedShape, RawSegment, FullRawGeometry } from '../../types/live';
import * as engine from '../../services/zoningEngineApi';
import { ArrowRightIcon, RefreshIcon, WarningIcon } from '../Icons';

interface BoundaryStudioProps {
  projectId: string;
  geometry: GeometryResult;
  onGeometryUpdated: (geometry: GeometryResult) => void;
  onBoundaryChosen: (geometry: GeometryResult, regionId: string) => void;
  onStartOver: () => void;
}

type Tool = 'browse' | 'shape' | 'walls' | 'draw';

const UNIT_OPTIONS = ['Feet', 'Inches', 'Meters', 'Centimeters', 'Millimeters'];

function distPointToSegment(p: [number, number], a: [number, number], b: [number, number]): number {
  const [px, py] = p, [ax, ay] = a, [bx, by] = b;
  const dx = bx - ax, dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq > 0 ? ((px - ax) * dx + (py - ay) * dy) / lenSq : 0;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx, cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
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

export const BoundaryStudio: React.FC<BoundaryStudioProps> = ({ projectId, geometry, onGeometryUpdated, onBoundaryChosen, onStartOver }) => {
  const raw = geometry.full_raw_geometry;
  const svgRef = useRef<SVGSVGElement>(null);
  const [tool, setTool] = useState<Tool>('browse');
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredShapeId, setHoveredShapeId] = useState<string | null>(null);
  const [hoveredSegmentId, setHoveredSegmentId] = useState<number | null>(null);
  const [selectedWallIds, setSelectedWallIds] = useState<Set<number>>(new Set());
  const [drawPoints, setDrawPoints] = useState<number[][]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [tracing, setTracing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [selectedUnit, setSelectedUnit] = useState(geometry.units.suggested_unit || 'Feet');
  const [confirmingUnit, setConfirmingUnit] = useState(false);
  const [unitsDismissed, setUnitsDismissed] = useState(false);
  const [manualOverride, setManualOverride] = useState(false);
  const [autoFired, setAutoFired] = useState(false);

  const panStart = useRef<{ x: number; y: number; originX: number; originY: number } | null>(null);
  const movedRef = useRef(false);

  // Full end-to-end automation, matching the same "auto-advance on a clean
  // detection" pattern GeometryReviewStep already uses one step later: the
  // architect who never touches this screen should still land on a real,
  // reviewable layout — the manual tools below exist for when the automatic
  // candidate is wrong or missing, not as a required step. `regions` is
  // already sorted best-first by the backend, so [0] is the same "best
  // guess" a human would pick first. A boundary carrying a `note` (implausible
  // size, or reconstructed with no wall-layer evidence) never auto-advances —
  // same gate, same reasoning as Geometry Review's own auto mode.
  const bestRegion = geometry.regions[0];
  const boundaryIsClean = !!bestRegion && !bestRegion.boundary.note;
  const autoMode = boundaryIsClean && !manualOverride;
  const AUTO_ADVANCE_MS = 1800;

  useEffect(() => {
    if (!autoMode || autoFired) return;
    const t = setTimeout(() => {
      setAutoFired(true);
      onBoundaryChosen(geometry, bestRegion.region_id);
    }, AUTO_ADVANCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode, autoFired]);

  const bbox = useMemo(() => {
    const b = raw?.bounds_ft || { min_x: 0, min_y: 0, max_x: 100, max_y: 100 };
    const pad = Math.max(b.max_x - b.min_x, b.max_y - b.min_y) * 0.08 + 2;
    return { minX: b.min_x - pad, minY: b.min_y - pad, width: (b.max_x - b.min_x) + 2 * pad, height: (b.max_y - b.min_y) + 2 * pad };
  }, [raw]);

  const spatialIndex = useMemo(() => (raw ? buildSpatialIndex(raw, bbox) : null), [raw, bbox]);
  const annotationLineCount = useMemo(
    () => raw ? raw.lines.reduce((n, ln) => n + (ln.category === 'annotation' ? 1 : 0), 0) : 0,
    [raw]
  );

  const viewBoxWidth = bbox.width / zoom;
  const viewBoxHeight = bbox.height / zoom;
  const originX = bbox.minX + pan.x;
  const originY = bbox.minY + pan.y;
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
      // A dimension extension line or leader callout is never a real wall —
      // the backend already excludes these from its own wall-reconstruction
      // pass (see cad_extraction.py's annotation_ids), so tracing a boundary
      // through one here would trace something that was never structural.
      if (ln.category === 'annotation') continue;
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
      setHoveredSegmentId(nearestSegment(p)?.id ?? null);
    }
  };

  const handleClickAt = (p: [number, number]) => {
    setTraceError(null);
    if (tool === 'shape') {
      const hit = nearestShape(p);
      if (hit) setPreview({ points: hit.shape.points_ft, mode: 'shape', sourceHandle: hit.shape.handle });
    } else if (tool === 'walls') {
      const hit = nearestSegment(p);
      if (hit) {
        setSelectedWallIds(prev => {
          const next = new Set(prev);
          if (next.has(hit.id)) next.delete(hit.id); else next.add(hit.id);
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
    panStart.current = { x: e.clientX, y: e.clientY, originX, originY };
    movedRef.current = false;
  };

  const onBgPointerMove = (e: React.PointerEvent) => {
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
    setPan({
      x: (panStart.current.originX - bbox.minX) - dxPx * ftPerPxX,
      y: (panStart.current.originY - bbox.minY) - dyPx * ftPerPxY,
    });
  };

  const onBgPointerUp = (e: React.PointerEvent) => {
    if (!movedRef.current) {
      handleClickAt(screenToUser(e.clientX, e.clientY));
    }
    panStart.current = null;
    movedRef.current = false;
  };

  const runTrace = async () => {
    setTracing(true);
    setTraceError(null);
    try {
      const result = await engine.traceBoundary(projectId, Array.from(selectedWallIds));
      setPreview({ points: result.points_ft, mode: 'walls' });
    } catch (e: any) {
      setTraceError(e.message || 'Could not trace a closed boundary from these segments.');
    } finally {
      setTracing(false);
    }
  };

  const commitPreview = async () => {
    if (!preview) return;
    setCommitting(true);
    try {
      const updated = await engine.createManualRegion(projectId, preview.points, preview.mode, preview.sourceHandle);
      const newRegion = updated.regions[updated.regions.length - 1];
      onBoundaryChosen(updated, newRegion.region_id);
    } catch (e: any) {
      setTraceError(e.message || 'Could not create a region from this boundary.');
    } finally {
      setCommitting(false);
    }
  };

  const confirmUnit = async () => {
    setConfirmingUnit(true);
    try {
      const updated = await engine.confirmUnits(projectId, selectedUnit);
      onGeometryUpdated(updated);
      setUnitsDismissed(true);
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
    setHoveredShapeId(null);
    setHoveredSegmentId(null);
  };

  if (!raw) {
    return (
      <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        No raw geometry is available for this upload.
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
                    strokeOpacity={ln.category === 'annotation' ? 0.35 : 1}
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
              onClick={() => { setAutoFired(true); onBoundaryChosen(geometry, bestRegion.region_id); }}>
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
              value={selectedUnit}
              onChange={(e) => setSelectedUnit(e.target.value)}
              style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', padding: '3px 6px', fontSize: '0.74rem' }}
            >
              {UNIT_OPTIONS.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
            <button className="btn btn-primary" style={{ fontSize: '0.72rem', padding: '4px 10px', whiteSpace: 'nowrap' }} disabled={confirmingUnit} onClick={confirmUnit}>
              {confirmingUnit ? 'Applying…' : 'Confirm Unit'}
            </button>
            <button className="btn btn-secondary" style={{ fontSize: '0.72rem', padding: '4px 8px' }} onClick={() => setUnitsDismissed(true)}>Dismiss</button>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button className={tool === 'browse' ? 'btn btn-primary' : 'btn btn-secondary'} style={{ fontSize: '0.72rem', padding: '4px 10px' }} onClick={() => switchTool('browse')}>Browse</button>
            <button className={tool === 'shape' ? 'btn btn-primary' : 'btn btn-secondary'} style={{ fontSize: '0.72rem', padding: '4px 10px' }} onClick={() => switchTool('shape')}>Select Closed Shape</button>
            <button className={tool === 'walls' ? 'btn btn-primary' : 'btn btn-secondary'} style={{ fontSize: '0.72rem', padding: '4px 10px' }} onClick={() => switchTool('walls')}>Select Walls</button>
            <button className={tool === 'draw' ? 'btn btn-primary' : 'btn btn-secondary'} style={{ fontSize: '0.72rem', padding: '4px 10px' }} onClick={() => switchTool('draw')}>Draw Boundary</button>
          </div>
          <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }} onClick={onStartOver}>
            <RefreshIcon size={13} /> Replace CAD File
          </button>
        </div>

        <div style={{ flex: 1, position: 'relative', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', zIndex: 10, margin: '10px', display: 'flex', gap: '4px' }}>
            <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => setZoom(z => Math.min(z * 1.3, 40))}>+</button>
            <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => setZoom(z => Math.max(z / 1.3, 0.3))}>−</button>
            <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Reset</button>
            <span style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-tertiary)', fontSize: '0.68rem', padding: '3px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'center' }}>
              {raw.lines.length.toLocaleString()} lines · {raw.closed_shapes.length.toLocaleString()} shapes{raw.truncated ? ' (truncated)' : ''}
            </span>
            {annotationLineCount > 0 && (
              <span style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-tertiary)', fontSize: '0.68rem', padding: '3px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ display: 'inline-block', width: '14px', borderTop: '1.5px dashed var(--text-tertiary)', opacity: 0.5 }} />
                {annotationLineCount.toLocaleString()} dimension/leader lines (dimmed, not selectable as walls)
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
                  stroke={selectedWallIds.has(ln.id) ? 'var(--brand-strong)' : hoveredSegmentId === ln.id ? 'var(--warning)' : 'var(--text-tertiary)'}
                  strokeWidth={(selectedWallIds.has(ln.id) || hoveredSegmentId === ln.id) ? toleranceFt() * 0.12 : toleranceFt() * 0.04}
                  strokeOpacity={ln.category === 'annotation' ? 0.35 : 1}
                  strokeDasharray={ln.category === 'annotation' ? `${toleranceFt() * 0.3} ${toleranceFt() * 0.2}` : undefined}
                />
              ))}
              {raw.circles.map((c, i) => (
                <circle key={`c${i}`} cx={c.center[0]} cy={c.center[1]} r={c.radius} fill="none" stroke="var(--text-tertiary)" strokeWidth={toleranceFt() * 0.04} />
              ))}
            </g>

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
          {tool === 'walls' && 'click individual wall lines to select them, then trace a boundary from the selection'}
          {tool === 'draw' && 'click to place points, click near your first point to close the shape'}
          {tool === 'browse' && 'pick a tool above, or use one of the auto-detected candidates on the right'}
        </div>
      </div>

      <div style={{ width: '340px', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
        <div className="panel">
          <div className="panel-label" style={{ marginBottom: '8px' }}>Auto-Detected Candidates</div>
          {geometry.regions.length === 0 ? (
            <div style={{ fontSize: '0.74rem', color: 'var(--text-tertiary)' }}>
              No candidate boundary was found automatically — use one of the tools on the left to define one manually.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {geometry.regions.map((r, i) => (
                <button
                  key={r.region_id}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.72rem', padding: '6px 8px', textAlign: 'left', display: 'flex', justifyContent: 'space-between' }}
                  onClick={() => onBoundaryChosen(geometry, r.region_id)}
                >
                  <span>Region {i + 1} — {r.boundary.area_sqft.toLocaleString()} sqft</span>
                  <ArrowRightIcon size={13} />
                </button>
              ))}
            </div>
          )}
        </div>

        {tool === 'walls' && (
          <div className="panel">
            <div className="panel-label" style={{ marginBottom: '8px' }}>Selected Walls ({selectedWallIds.size})</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginBottom: '10px' }}>
              Click wall lines in the drawing to select them, then trace the boundary they enclose.
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-primary" style={{ fontSize: '0.74rem', flex: 1 }} disabled={selectedWallIds.size < 3 || tracing} onClick={runTrace}>
                {tracing ? 'Tracing…' : 'Trace Boundary'}
              </button>
              <button className="btn btn-secondary" style={{ fontSize: '0.74rem' }} onClick={() => setSelectedWallIds(new Set())}>Clear</button>
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
            {traceError}
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
