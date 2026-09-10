import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GeometryResult, FullRawGeometry, RawClosedShape } from '../../types/live';
import * as engine from '../../services/zoningEngineApi';
import { ArrowRightIcon, RefreshIcon, WarningIcon, DownloadIcon, CheckIcon } from '../Icons';

interface CleaningStudioProps {
  projectId: string;
  geometry: GeometryResult;
  /** The project's own intake-form Carpet Area / Floor-Shop-No, when
   * available — drives the Net Usage Area match/mismatch callout on each
   * selected boundary (see zoningEngineApi.ts's previewClean). Optional:
   * a project with no carpet area on file just skips the check silently,
   * same as everywhere else this form data feeds a boundary check. */
  carpetAreaSqft?: number | null;
  floorShopHint?: string | null;
  /** Called once the backend has exported a clean DXF/DWG and re-run
   * extraction against it — the returned GeometryResult is the same shape
   * a normal upload produces, so the caller hands it straight to
   * BoundaryStudio exactly like after uploadCad. */
  onCleaned: (geometry: GeometryResult) => void;
  /** The uploaded file is already clean enough (an architect's own file,
   * not a messy sales handoff) — skip straight to boundary selection on the
   * raw upload, unchanged. */
  onSkip: () => void;
  onStartOver: () => void;
}

type Tool = 'browse' | 'label' | 'shapes';

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 4000;

// --- Pan/zoom/hit-testing helpers -----------------------------------------
// Deliberately the same approach as BoundaryStudio.tsx's own spatial index
// (not imported from it — these are small private helpers there, not a
// shared module): a real file can carry tens of thousands of closed shapes,
// and a plain per-pointer-move linear scan measured as audibly janky against
// one. A shared `utils/canvasGeometry.ts` extraction would be the cleaner
// long-term home for this if a third canvas needs it.

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

interface SpatialIndex {
  cellSize: number;
  minX: number;
  minY: number;
  shapeCells: Map<string, RawClosedShape[]>;
}

function cellRange(minV: number, maxV: number, origin: number, cellSize: number): [number, number] {
  return [Math.floor((minV - origin) / cellSize), Math.floor((maxV - origin) / cellSize)];
}

function buildSpatialIndex(raw: FullRawGeometry, bbox: { minX: number; minY: number; width: number; height: number }): SpatialIndex {
  const cellSize = Math.max(bbox.width, bbox.height) / 60 || 1;
  const shapeCells = new Map<string, RawClosedShape[]>();
  for (const s of raw.closed_shapes) {
    const xs = s.points_ft.map(p => p[0]);
    const ys = s.points_ft.map(p => p[1]);
    const [cx0, cx1] = cellRange(Math.min(...xs), Math.max(...xs), bbox.minX, cellSize);
    const [cy0, cy1] = cellRange(Math.min(...ys), Math.max(...ys), bbox.minY, cellSize);
    for (let cx = cx0; cx <= cx1; cx++) {
      for (let cy = cy0; cy <= cy1; cy++) {
        const key = `${cx},${cy}`;
        let bucket = shapeCells.get(key);
        if (!bucket) { bucket = []; shapeCells.set(key, bucket); }
        bucket.push(s);
      }
    }
  }
  return { cellSize, minX: bbox.minX, minY: bbox.minY, shapeCells };
}

function queryNearbyShapes(p: [number, number], index: SpatialIndex): RawClosedShape[] {
  const cx = Math.floor((p[0] - index.minX) / index.cellSize);
  const cy = Math.floor((p[1] - index.minY) / index.cellSize);
  const seen = new Set<RawClosedShape>();
  const out: RawClosedShape[] = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const bucket = index.shapeCells.get(`${cx + dx},${cy + dy}`);
      if (!bucket) continue;
      for (const item of bucket) {
        if (!seen.has(item)) { seen.add(item); out.push(item); }
      }
    }
  }
  return out;
}

// Floors/towers on a real multi-floor file are very commonly drawn overlaid
// at identical modelspace coordinates (confirmed on a real file: the same
// 369,490 sqft "Wall" outline appeared 6 times identically, one per floor) —
// with no way to isolate one floor, Search by Label and Select Boundaries
// both collide with every other floor's geometry sitting on top of it. Real
// evidence of a grouping signal already present in layer names: AutoCAD's
// XREF-binding convention names a bound layer "XREFNAME$0$ORIGINALLAYERNAME"
// (confirmed on another real file: "TOWER 2 UP TO PODIUM PLAN$0$...COLUMN
// NAME") — grouping on the part before the first "$0$" recovers that real
// tower/floor grouping for free. A plain layer name (no "$0$") is its own
// group of one.
function layerGroupName(layer: string): string {
  const idx = layer.indexOf('$0$');
  return idx >= 0 ? layer.slice(0, idx) : layer;
}

// Sort-order convenience only (never an auto-selected default — this app's
// own "never silently resolve uncertainty" principle) so a group that's
// plausibly a specific floor/tower is easier to find first when manually
// isolating one.
const FLOOR_NAME_TOKENS = [
  'ground', 'first', '1st', 'second', '2nd', 'third', '3rd', 'fourth', '4th',
  'basement', 'podium', 'mezzanine', 'tower', 'floor', 'ug', 'lg',
];

interface LayerGroup {
  name: string;
  layers: string[];
  shapeCount: number;
  lineCount: number;
}

const CLASSIFICATION_LABEL: Record<string, string> = {
  COLUMN: 'column', DUCT: 'duct', WALL: 'wall', DOOR: 'door', WINDOW: 'window',
  STAIRCASE: 'staircase', WASHROOM_FIXTURE: 'washroom fixture', FURNITURE: 'furniture',
  UNCLASSIFIED_OBSTACLE: 'unclassified item',
};

function classificationCounts(byClass: Record<string, number>): string {
  const entries = Object.entries(byClass);
  if (entries.length === 0) return 'none';
  return entries.map(([cls, n]) => `${n} ${CLASSIFICATION_LABEL[cls] || cls}${n === 1 ? '' : 's'}`).join(', ');
}

export const CleaningStudio: React.FC<CleaningStudioProps> = ({ projectId, geometry, carpetAreaSqft, floorShopHint, onCleaned, onSkip, onStartOver }) => {
  const raw = geometry.full_raw_geometry;
  const formHints = { targetAreaSqft: carpetAreaSqft, labelHint: floorShopHint };
  const svgRef = useRef<SVGSVGElement>(null);
  const [tool, setTool] = useState<Tool>('browse');
  const [zoom, setZoom] = useState(1);
  const [center, setCenter] = useState<{ x: number; y: number } | null>(null);
  const [hoveredShapeId, setHoveredShapeId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set()); // RawClosedShape.handle
  const [labelQuery, setLabelQuery] = useState('');
  const [labelMatches, setLabelMatches] = useState<engine.CleanLabelMatch[]>([]);
  const [searching, setSearching] = useState(false);
  // Proactive, not a manual search like labelMatches above — runs once on
  // mount (see the effect below) so the salesperson sees a suggestion the
  // moment this screen loads, before they've clicked anything.
  const [areaMatches, setAreaMatches] = useState<engine.CleanAreaMatch[]>([]);
  const [areaSearchDone, setAreaSearchDone] = useState(false);
  const [preview, setPreview] = useState<engine.CleanRegionPreview[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState<'continue' | 'download' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadedNote, setDownloadedNote] = useState<string | null>(null);
  // Real layer names whose geometry/matches are currently hidden — empty by
  // default (everything visible), never a guessed starting subset.
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set());

  const panStart = useRef<{ x: number; y: number; centerX: number; centerY: number } | null>(null);
  const movedRef = useRef(false);

  const bbox = useMemo(() => {
    const b = raw?.bounds_ft || { min_x: 0, min_y: 0, max_x: 100, max_y: 100 };
    const pad = Math.max(b.max_x - b.min_x, b.max_y - b.min_y) * 0.08 + 2;
    return { minX: b.min_x - pad, minY: b.min_y - pad, width: (b.max_x - b.min_x) + 2 * pad, height: (b.max_y - b.min_y) + 2 * pad };
  }, [raw]);

  useEffect(() => {
    setCenter({ x: bbox.minX + bbox.width / 2, y: bbox.minY + bbox.height / 2 });
    setZoom(1);
  }, [bbox]);

  const spatialIndex = useMemo(() => (raw ? buildSpatialIndex(raw, bbox) : null), [raw, bbox]);
  const shapesByHandle = useMemo(() => {
    const map = new Map<string, RawClosedShape>();
    raw?.closed_shapes.forEach(s => map.set(s.handle, s));
    return map;
  }, [raw]);

  const layerGroups = useMemo((): LayerGroup[] => {
    const groups = new Map<string, { layers: Set<string>; shapeCount: number; lineCount: number }>();
    const ensure = (layer: string) => {
      const name = layerGroupName(layer);
      let g = groups.get(name);
      if (!g) { g = { layers: new Set(), shapeCount: 0, lineCount: 0 }; groups.set(name, g); }
      g.layers.add(layer);
      return g;
    };
    raw?.closed_shapes.forEach(s => { ensure(s.layer).shapeCount++; });
    raw?.lines.forEach(ln => { ensure(ln.layer).lineCount++; });
    return Array.from(groups.entries())
      .map(([name, g]) => ({ name, layers: Array.from(g.layers), shapeCount: g.shapeCount, lineCount: g.lineCount }))
      .sort((a, b) => {
        const aFloor = FLOOR_NAME_TOKENS.some(t => a.name.toLowerCase().includes(t));
        const bFloor = FLOOR_NAME_TOKENS.some(t => b.name.toLowerCase().includes(t));
        if (aFloor !== bFloor) return aFloor ? -1 : 1;
        return (b.shapeCount + b.lineCount) - (a.shapeCount + a.lineCount);
      });
  }, [raw]);

  const toggleLayerGroup = (group: LayerGroup) => {
    setHiddenLayers(prev => {
      const next = new Set(prev);
      const allHidden = group.layers.every(l => next.has(l));
      for (const l of group.layers) {
        if (allHidden) next.delete(l); else next.add(l);
      }
      return next;
    });
  };

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
  }, [zoomAtScreenPoint]);

  const toleranceFt = () => {
    const svg = svgRef.current;
    const widthPx = svg?.getBoundingClientRect().width || 800;
    return (viewBoxWidth / widthPx) * 9;
  };

  const nearestShape = (p: [number, number]): RawClosedShape | null => {
    if (!raw || !spatialIndex) return null;
    const tol = toleranceFt();
    const candidates = queryNearbyShapes(p, spatialIndex).filter(s => !hiddenLayers.has(s.layer));
    let best: { shape: RawClosedShape; dist: number } | null = null;
    for (const s of candidates) {
      const d = distPointToPolygonBoundary(p, s.points_ft);
      if (d <= tol && (!best || d < best.dist)) best = { shape: s, dist: d };
    }
    if (best) return best.shape;
    let smallest: RawClosedShape | null = null;
    for (const s of candidates) {
      if (pointInPolygon(p, s.points_ft) && (!smallest || s.area_sqft < smallest.area_sqft)) smallest = s;
    }
    return smallest;
  };

  // Label matches whose enclosing shape sits on a currently-hidden layer are
  // filtered out of the results list and the canvas markers below — a match
  // with no enclosing shape at all always stays (nothing to check against).
  const visibleLabelMatches = labelMatches.filter(m => {
    if (!m.shape_handle) return true;
    const s = shapesByHandle.get(m.shape_handle);
    return !s || !hiddenLayers.has(s.layer);
  });

  const toggleShape = (handle: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(handle)) next.delete(handle); else next.add(handle);
      return next;
    });
  };

  const updateHover = (e: React.PointerEvent) => {
    if (tool !== 'shapes') return;
    const p = screenToUser(e.clientX, e.clientY);
    setHoveredShapeId(nearestShape(p)?.id || null);
  };

  const handleClickAt = (p: [number, number]) => {
    if (tool === 'shapes') {
      const hit = nearestShape(p);
      if (hit) toggleShape(hit.handle);
    }
  };

  const onBgPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    movedRef.current = false;
    panStart.current = { x: e.clientX, y: e.clientY, centerX: viewCenter.x, centerY: viewCenter.y };
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
    setCenter({
      x: panStart.current.centerX - dxPx * ftPerPxX,
      y: panStart.current.centerY - dyPx * ftPerPxY,
    });
  };

  const onBgPointerUp = (e: React.PointerEvent) => {
    if (!movedRef.current) handleClickAt(screenToUser(e.clientX, e.clientY));
    panStart.current = null;
    movedRef.current = false;
  };

  // Proactive boundary suggestion, driven by the project's own intake
  // Carpet Area — runs exactly once, right when this screen loads, so the
  // salesperson sees a real suggestion before they've clicked or typed
  // anything (the whole point: "look for the proper area after CAD is
  // uploaded", not wait for a manual search). No carpet area on file just
  // means nothing to suggest, not an error.
  useEffect(() => {
    if (!carpetAreaSqft) { setAreaSearchDone(true); return; }
    let cancelled = false;
    engine.searchCleanArea(projectId, carpetAreaSqft)
      .then(matches => { if (!cancelled) { setAreaMatches(matches); setAreaSearchDone(true); } })
      .catch(() => { if (!cancelled) setAreaSearchDone(true); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live before/after preview, debounced — re-fetches whenever the selected
  // shape set changes. Read-only on the backend (clean/preview never writes
  // geometry.json), so there's nothing to undo if the user keeps clicking.
  useEffect(() => {
    if (selected.size === 0) { setPreview([]); return; }
    let cancelled = false;
    setPreviewing(true);
    const t = setTimeout(async () => {
      try {
        const regions = await engine.previewClean(projectId, Array.from(selected), formHints);
        if (!cancelled) { setPreview(regions); setError(null); }
      } catch (e: any) {
        if (!cancelled) setError(e.message || 'Could not preview this selection.');
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 350);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, projectId, carpetAreaSqft, floorShopHint]);

  const runLabelSearch = async () => {
    if (!labelQuery.trim()) { setLabelMatches([]); return; }
    setSearching(true);
    setError(null);
    try {
      setLabelMatches(await engine.searchCleanLabel(projectId, labelQuery));
    } catch (e: any) {
      setError(e.message || 'Label search failed.');
    } finally {
      setSearching(false);
    }
  };

  const handleConfirm = async (mode: 'continue' | 'download') => {
    setConfirming(mode);
    setError(null);
    setDownloadedNote(null);
    try {
      const updated = await engine.confirmClean(projectId, Array.from(selected));
      if (mode === 'continue') {
        onCleaned(updated);
        return;
      }
      await engine.downloadClean(projectId, 'dxf');
      setDownloadedNote('Clean DXF downloaded. Use "Clean & Continue" whenever you\'re ready to move into boundary review with this same selection.');
    } catch (e: any) {
      setError(e.message || 'Could not clean this file with the selected boundaries.');
    } finally {
      setConfirming(null);
    }
  };

  const switchTool = (t: Tool) => {
    setTool(t);
    setHoveredShapeId(null);
  };

  if (!raw) {
    return (
      <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-tertiary)' }}>
        No raw geometry is available for this upload.
      </div>
    );
  }

  const totalKept = preview.reduce((n, r) => n + r.kept_count, 0);
  const totalDropped = preview.reduce((n, r) => n + r.dropped_count, 0);

  return (
    <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button className={`btn btn-sm ${tool === 'browse' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('browse')}>Browse</button>
            <button className={`btn btn-sm ${tool === 'label' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('label')}>Search by Label</button>
            <button className={`btn btn-sm ${tool === 'shapes' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => switchTool('shapes')}>Select Boundaries</button>
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
            {selected.size > 0 && (
              <span className="badge" style={{ background: 'var(--bg-raised)', border: '1px solid var(--success)', color: 'var(--success)', display: 'flex', alignItems: 'center' }}>
                {selected.size} boundar{selected.size === 1 ? 'y' : 'ies'} selected
              </span>
            )}
          </div>

          <svg
            ref={svgRef}
            viewBox={viewBox}
            style={{ width: '100%', height: '100%', touchAction: 'none', cursor: panStart.current && movedRef.current ? 'grabbing' : tool === 'shapes' ? 'pointer' : 'grab' }}
            onPointerDown={onBgPointerDown}
            onPointerMove={onBgPointerMove}
            onPointerUp={onBgPointerUp}
          >
            <g opacity={0.5}>
              {raw.lines.filter(ln => !hiddenLayers.has(ln.layer)).map(ln => (
                <line
                  key={ln.id} x1={ln.a[0]} y1={ln.a[1]} x2={ln.b[0]} y2={ln.b[1]}
                  stroke="var(--text-tertiary)" strokeWidth={toleranceFt() * 0.04}
                  strokeOpacity={ln.category === 'annotation' || ln.category === 'sheet' ? 0.35 : 1}
                />
              ))}
              {raw.circles.map((c, i) => (
                <circle key={`c${i}`} cx={c.center[0]} cy={c.center[1]} r={c.radius} fill="none" stroke="var(--text-tertiary)" strokeWidth={toleranceFt() * 0.04} />
              ))}
            </g>

            {/* Every currently selected boundary, highlighted at once — the
                whole point of this stage is picking one-or-more, possibly
                disconnected, shapes in a single pass. */}
            {Array.from(selected).map(handle => {
              const s = shapesByHandle.get(handle);
              if (!s) return null;
              return (
                <polygon
                  key={handle}
                  points={s.points_ft.map(p => p.join(',')).join(' ')}
                  fill="var(--success)" fillOpacity={0.22} stroke="var(--success)" strokeWidth={toleranceFt() * 0.12}
                />
              );
            })}

            {tool === 'shapes' && hoveredShapeId && !Array.from(selected).some(h => shapesByHandle.get(h)?.id === hoveredShapeId) && (() => {
              const s = raw.closed_shapes.find(sh => sh.id === hoveredShapeId);
              return s ? (
                <polygon points={s.points_ft.map(p => p.join(',')).join(' ')} fill="var(--brand-strong)" fillOpacity={0.18} stroke="var(--brand-strong)" strokeWidth={toleranceFt() * 0.1} />
              ) : null;
            })()}

            {tool === 'label' && visibleLabelMatches.map((m, i) => (
              <g key={i}>
                <circle cx={m.position_ft[0]} cy={m.position_ft[1]} r={toleranceFt() * 0.6}
                  fill={m.shape_handle && selected.has(m.shape_handle) ? 'var(--success)' : 'var(--warning)'} />
              </g>
            ))}
          </svg>
        </div>

        <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', textAlign: 'center' }}>
          Drag empty space to pan · {tool === 'shapes' && 'click any closed outline (or inside a room) to add or remove it as a boundary to clean — pick as many as you need, they don\'t need to be connected'}
          {tool === 'label' && 'search for a room/space name on the right, then click a result to add its outline'}
          {tool === 'browse' && 'pick "Search by Label" or "Select Boundaries" to choose what to clean'}
        </div>
      </div>

      <div style={{ width: '360px', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
        <div className="panel">
          <div className="panel-label" style={{ marginBottom: '6px' }}>Source File</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <div className="font-mono" style={{ color: 'var(--text-primary)', wordBreak: 'break-all' }}>{geometry.source_filename}</div>
            <div>{geometry.total_entities_scanned.toLocaleString()} entities scanned · {geometry.total_closed_shapes_found.toLocaleString()} closed shapes found</div>
          </div>
        </div>

        {carpetAreaSqft ? (
          areaMatches.length > 0 ? (
            <div className="panel" style={{ borderColor: 'var(--success)' }}>
              <div className="panel-label" style={{ color: 'var(--success)', marginBottom: '6px' }}>
                Suggested by Carpet Area ({carpetAreaSqft.toLocaleString()} sqft)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {areaMatches.map(m => (
                  <button
                    key={m.shape_handle} className="btn btn-secondary"
                    style={{ fontSize: '0.72rem', padding: '6px 8px', textAlign: 'left', display: 'flex', justifyContent: 'space-between', gap: '8px' }}
                    disabled={selected.has(m.shape_handle)}
                    onClick={() => {
                      toggleShape(m.shape_handle);
                      setCenter({ x: (m.shape_bounding_box_ft.min_x + m.shape_bounding_box_ft.max_x) / 2, y: (m.shape_bounding_box_ft.min_y + m.shape_bounding_box_ft.max_y) / 2 });
                    }}
                  >
                    <span>{m.shape_area_sqft.toLocaleString()} sqft {m.rel_error_pct === 0 ? '(exact match)' : `(${m.rel_error_pct}% off)`}</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>{selected.has(m.shape_handle) ? 'Added ✓' : 'Add'}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : areaSearchDone ? (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>
              No boundary in this file closely matches your stated carpet area ({carpetAreaSqft.toLocaleString()} sqft) — select one manually below.
            </div>
          ) : null
        ) : null}

        <div className="panel" style={{ borderColor: 'rgba(120,140,180,0.35)' }}>
          <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Cleaning strips a selected area down to just its outline, columns, and ducts — everything else (internal
            walls, doors, windows, furniture, fixtures, unrelated items) is removed before this file reaches boundary
            review. Already have a clean file? <button className="btn btn-secondary btn-sm" style={{ marginLeft: '4px' }} onClick={onSkip}>Skip cleaning</button>
          </div>
        </div>

        {layerGroups.length > 1 && (
          <div className="panel">
            <div className="panel-label" style={{ marginBottom: '6px' }}>Layers</div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginBottom: '8px', lineHeight: 1.4 }}>
              Real multi-floor files often draw every floor on top of each other at the same spot. Hide layers that
              aren't the floor/area you're working on to stop them colliding on the canvas and in search results.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '220px', overflowY: 'auto' }}>
              {layerGroups.map(g => {
                const isHidden = g.layers.every(l => hiddenLayers.has(l));
                return (
                  <label
                    key={g.name}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem',
                      color: isHidden ? 'var(--text-tertiary)' : 'var(--text-secondary)', cursor: 'pointer',
                    }}
                  >
                    <input type="checkbox" checked={!isHidden} onChange={() => toggleLayerGroup(g)} />
                    <span style={{ flex: 1, wordBreak: 'break-all' }}>{g.name}</span>
                    <span style={{ color: 'var(--text-tertiary)', flexShrink: 0 }}>{g.shapeCount.toLocaleString()} shapes</span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {tool === 'label' && (
          <div className="panel">
            <div className="panel-label" style={{ marginBottom: '8px' }}>Search by Room / Space Label</div>
            <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
              <input
                type="text"
                className="form-control" style={{ flex: 1, fontSize: '0.8rem', padding: '5px 8px' }}
                placeholder="e.g. Screen 1, Suite 200"
                value={labelQuery}
                onChange={(e) => setLabelQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') runLabelSearch(); }}
              />
              <button className="btn btn-primary btn-sm" disabled={searching} onClick={runLabelSearch}>
                {searching ? 'Searching…' : 'Search'}
              </button>
            </div>
            {labelMatches.length > 0 && visibleLabelMatches.length < labelMatches.length && (
              <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '6px' }}>
                {labelMatches.length - visibleLabelMatches.length} match{labelMatches.length - visibleLabelMatches.length === 1 ? '' : 'es'} hidden by the layer filter below.
              </div>
            )}
            {visibleLabelMatches.length === 0 ? (
              <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>
                {labelMatches.length === 0
                  ? 'Type a name printed in the drawing (a room, screen, or unit label) and search.'
                  : 'All matches are on layers currently hidden by the layer filter below.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '260px', overflowY: 'auto' }}>
                {visibleLabelMatches.map((m, i) => (
                  <button
                    key={i}
                    className="btn btn-secondary"
                    style={{ fontSize: '0.72rem', padding: '6px 8px', textAlign: 'left', display: 'flex', justifyContent: 'space-between', gap: '8px' }}
                    disabled={!m.shape_handle}
                    onClick={() => {
                      if (m.shape_handle) {
                        toggleShape(m.shape_handle);
                        const s = shapesByHandle.get(m.shape_handle);
                        if (s) setCenter({ x: (m.shape_bounding_box_ft!.min_x + m.shape_bounding_box_ft!.max_x) / 2, y: (m.shape_bounding_box_ft!.min_y + m.shape_bounding_box_ft!.max_y) / 2 });
                      }
                    }}
                  >
                    <span>
                      "{m.text}"{m.shape_handle ? '' : ' — no enclosing outline found near this label'}
                    </span>
                    {m.shape_handle && (
                      <span style={{ color: 'var(--text-tertiary)', flexShrink: 0 }}>
                        {m.shape_area_sqft?.toLocaleString()} sqft{selected.has(m.shape_handle) ? ' ✓' : ''}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {selected.size > 0 && (
          <div className="panel" style={{ borderColor: 'var(--success)' }}>
            <div className="panel-label" style={{ marginBottom: '8px', color: 'var(--success)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Selected Boundaries ({selected.size})</span>
              <button className="btn btn-secondary btn-sm" style={{ fontSize: '0.68rem', padding: '2px 6px' }} onClick={() => setSelected(new Set())}>Clear all</button>
            </div>
            {previewing ? (
              <div style={{ fontSize: '0.74rem', color: 'var(--text-tertiary)' }}>Checking what this selection keeps…</div>
            ) : preview.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {preview.map((r, i) => (
                  <div key={r.region_id} style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    <div className="font-mono" style={{ color: 'var(--text-primary)' }}>
                      Boundary {i + 1} — Net Usage Area: {r.net_usage_area_sqft.toLocaleString()} sqft
                    </div>
                    {r.carpet_area_check && (
                      r.carpet_area_check.matches ? (
                        <div style={{
                          display: 'flex', gap: '6px', fontSize: '0.7rem', color: 'var(--text-primary)', background: 'var(--success-bg)',
                          border: '1px solid rgba(79,157,105,0.4)', borderRadius: 'var(--radius-sm)', padding: '6px 8px', margin: '4px 0'
                        }}>
                          <CheckIcon size={13} className="text-success" style={{ flex: '0 0 auto', marginTop: '1px' }} />
                          <span>{r.carpet_area_check.note}</span>
                        </div>
                      ) : (
                        <div style={{
                          display: 'flex', gap: '6px', fontSize: '0.7rem', color: 'var(--text-primary)', background: 'var(--warning-bg)',
                          border: '1px solid rgba(201,154,58,0.4)', borderRadius: 'var(--radius-sm)', padding: '6px 8px', margin: '4px 0'
                        }}>
                          <WarningIcon size={13} className="text-warning" style={{ flex: '0 0 auto', marginTop: '1px' }} />
                          <span>{r.carpet_area_check.note}</span>
                        </div>
                      )
                    )}
                    <div>Keeping: outline + {classificationCounts(r.kept_by_classification)}</div>
                    <div style={{ color: 'var(--text-tertiary)' }}>Removing: {classificationCounts(r.dropped_by_classification)}</div>
                  </div>
                ))}
                <div className="font-mono" style={{ fontSize: '0.76rem', color: 'var(--text-primary)', borderTop: '1px solid var(--border-color)', paddingTop: '8px' }}>
                  Total: keeping {totalKept}, removing {totalDropped}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {downloadedNote && (
          <div style={{ fontSize: '0.72rem', color: 'var(--success)', background: 'var(--bg-secondary)', border: '1px solid var(--success)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
            {downloadedNote}
          </div>
        )}

        {error && (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', fontSize: '0.72rem', color: 'var(--danger)', background: 'var(--danger-bg)', border: '1px solid rgba(209,109,100,0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
            <WarningIcon size={14} style={{ flex: '0 0 auto', marginTop: '1px' }} />
            <div>{error}</div>
          </div>
        )}

        <div className="panel">
          <button
            className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem', marginBottom: '8px' }}
            disabled={selected.size === 0 || !!confirming}
            onClick={() => handleConfirm('continue')}
          >
            {confirming === 'continue' ? 'Cleaning…' : 'Clean & Continue'} <ArrowRightIcon size={14} />
          </button>
          <button
            className="btn btn-secondary" style={{ width: '100%', fontSize: '0.74rem' }}
            disabled={selected.size === 0 || !!confirming}
            onClick={() => handleConfirm('download')}
          >
            <DownloadIcon size={13} /> {confirming === 'download' ? 'Cleaning…' : 'Download Clean File Only'}
          </button>
        </div>
      </div>
    </div>
  );
};
