import React, { useMemo, useRef, useState, useCallback, useEffect } from 'react';
import { LiveRoom, Obstacle, RoomDoor } from '../../types/live';
import { RawGeometry } from '../../types/live';

interface EditableCanvasProps {
  boundaryPointsFt: number[][];
  obstacles: Obstacle[];
  rooms: LiveRoom[];
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string | null) => void;
  /** Called continuously while dragging/resizing, for live visual feedback only — not persisted. */
  onLiveChange: (rooms: LiveRoom[]) => void;
  /** Called once, at the end of a drag/resize/add/delete, to persist to the server. */
  onCommit: (rooms: LiveRoom[]) => void;
  snapToGridFt: number;
  rawGeometry?: RawGeometry | null;
  showCadLinework?: boolean;
  /** Draws actual per-seat row marks inside each auditorium (from its
   * seat_estimate.rows/seats_per_row — the same real row-packing count
   * seat_engine.py already computes, just visualized) instead of only the
   * "N sqft / N seats" text label. Off by default — real per-row detail is
   * denser and can clutter a small/zoomed-out room, so it's an explicit
   * opt-in, not the default presentation. */
  showSeatRows?: boolean;
  /** When true, clicking the canvas traces a boundary polygon instead of
   * selecting/dragging rooms — for "draw your own boundary" when auto-
   * detection found the wrong region, or none at all. */
  drawMode?: boolean;
  onDrawComplete?: (points: number[][]) => void;
  /** Delete/Backspace with a room selected — mirrors the toolbar's "Delete Selected" button. */
  onDeleteSelected?: () => void;
}

// Deliberately no per-room-type color coding — every room renders as a
// plain neutral box, distinguished only by its label and selection state.
// A working CAD drawing reads room identity from its label, not an
// arbitrary color an architect has to memorize; color here was an
// editing-convenience decoration, not information.
const ROOM_NEUTRAL = 'var(--text-secondary)';

const HANDLE_SCREEN_PX = 9;       // visible handle size, constant on screen regardless of zoom
const HANDLE_HIT_SCREEN_PX = 26;  // invisible hit-area, much larger than the visible mark — this is the actual fix

function polygonBounds(points: number[][]) {
  const xs = points.map(p => p[0]);
  const ys = points.map(p => p[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

function rectsOverlap(a: { minX: number; maxX: number; minY: number; maxY: number }, b: { minX: number; maxX: number; minY: number; maxY: number }) {
  return a.minX < b.maxX && a.maxX > b.minX && a.minY < b.maxY && a.maxY > b.minY;
}

// Which wall of a room's bounding box is the screen wall — geometry-relative
// (min_x/max_x/min_y/max_y), matching layout_engine.py's
// _screen_wall_for_rect exactly (never a compass direction; see that
// function's own docstring for why). `along` is the unit vector running
// along the wall (for spreading seats/door offsets across it), `inward` is
// the unit vector perpendicular to the wall, pointing into the room (for
// how far back the screen-wall indicator/seat rows/door leaves reach).
// Defaults to 'min_y' — this app's original hardcoded assumption — so a
// room with no screen_wall set (older stored layouts) renders exactly as
// before this field existed.
interface WallGeometry {
  wallStart: [number, number];
  wallEnd: [number, number];
  inward: [number, number];
  along: [number, number];
  wallLen: number;
  depthLen: number;
}

function wallGeometry(b: { minX: number; maxX: number; minY: number; maxY: number }, screenWall?: string): WallGeometry {
  const w = b.maxX - b.minX, h = b.maxY - b.minY;
  switch (screenWall) {
    case 'max_y':
      return { wallStart: [b.minX, b.maxY], wallEnd: [b.maxX, b.maxY], inward: [0, -1], along: [1, 0], wallLen: w, depthLen: h };
    case 'min_x':
      return { wallStart: [b.minX, b.minY], wallEnd: [b.minX, b.maxY], inward: [1, 0], along: [0, 1], wallLen: h, depthLen: w };
    case 'max_x':
      return { wallStart: [b.maxX, b.minY], wallEnd: [b.maxX, b.maxY], inward: [-1, 0], along: [0, 1], wallLen: h, depthLen: w };
    case 'min_y':
    default:
      return { wallStart: [b.minX, b.minY], wallEnd: [b.maxX, b.minY], inward: [0, 1], along: [1, 0], wallLen: w, depthLen: h };
  }
}

// Mirrors layout_engine.py's _doors_for_screen_wall/_door_glyph_points_ft
// geometry exactly — a door's {wall, offset_ft, width_ft} plus the room's
// own origin_ft/width_ft/depth_ft is enough to derive its real on-canvas
// position, no separate door coordinates are stored server-side.
const DOOR_INTERIOR_DIR: Record<string, [number, number]> = { min_y: [0, 1], max_y: [0, -1], min_x: [1, 0], max_x: [-1, 0] };

function doorGlyphPoints(room: LiveRoom, door: RoomDoor): { p1: [number, number]; leafEnd: [number, number] } {
  const [x, y] = room.origin_ft;
  const w = room.width_ft, h = room.depth_ft;
  const { wall, offset_ft: off, width_ft: dw } = door;
  let p1: [number, number];
  if (wall === 'min_y') p1 = [x + off, y];
  else if (wall === 'max_y') p1 = [x + off, y + h];
  else if (wall === 'min_x') p1 = [x, y + off];
  else p1 = [x + w, y + off];
  const [dx, dy] = DOOR_INTERIOR_DIR[wall] || [0, 0];
  return { p1, leafEnd: [p1[0] + dx * dw, p1[1] + dy * dw] };
}

function snap(v: number, grid: number) {
  return grid > 0 ? Math.round(v / grid) * grid : v;
}

type HandleId = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';
type DragMode = { type: 'move' | 'resize'; roomId: string; handle?: HandleId; startX: number; startY: number; startRoom: LiveRoom } | null;

const HANDLE_DEFS: { id: HandleId; cursor: string; fx: number; fy: number }[] = [
  { id: 'nw', cursor: 'nwse-resize', fx: 0, fy: 0 },
  { id: 'n', cursor: 'ns-resize', fx: 0.5, fy: 0 },
  { id: 'ne', cursor: 'nesw-resize', fx: 1, fy: 0 },
  { id: 'e', cursor: 'ew-resize', fx: 1, fy: 0.5 },
  { id: 'se', cursor: 'nwse-resize', fx: 1, fy: 1 },
  { id: 's', cursor: 'ns-resize', fx: 0.5, fy: 1 },
  { id: 'sw', cursor: 'nesw-resize', fx: 0, fy: 1 },
  { id: 'w', cursor: 'ew-resize', fx: 0, fy: 0.5 }
];

export const EditableCanvas: React.FC<EditableCanvasProps> = ({
  boundaryPointsFt, obstacles, rooms, selectedRoomId, onSelectRoom, onLiveChange, onCommit, snapToGridFt,
  rawGeometry, showCadLinework = true, showSeatRows = false, drawMode = false, onDrawComplete, onDeleteSelected
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragMode>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoom[]>(rooms);
  const [zoom, setZoom] = useState(1);
  // Panning offset, in the same feet units as bbox — added to bbox's own
  // minX/minY when building the viewBox (see viewBox below). Kept separate
  // from bbox itself so dragging/zooming the view never has to touch the
  // boundary/obstacle data the bbox is derived from.
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const bgDragRef = useRef<{ startClientX: number; startClientY: number; startPan: { x: number; y: number } } | null>(null);
  const [pxPerFt, setPxPerFt] = useState(10);
  const [collision, setCollision] = useState(false);
  const [hoveredHandle, setHoveredHandle] = useState<string | null>(null);
  const [hoveredRoomId, setHoveredRoomId] = useState<string | null>(null);
  const [drawPoints, setDrawPoints] = useState<number[][]>([]);
  const moved = useRef(false);

  useEffect(() => { setLiveRooms(rooms); }, [rooms]);
  useEffect(() => { setDrawPoints([]); }, [drawMode]);

  const bbox = useMemo(() => {
    // Deliberately excludes drawPoints — the user is tracing a boundary on
    // top of the already-visible backdrop (existing boundary/obstacles/raw
    // CAD linework), so the viewBox must stay anchored to that and never
    // reflow as points are added. Letting drawPoints influence it was a real
    // bug: each new point could shift the viewBox under the user's cursor,
    // making every click after the first land somewhere other than where
    // they visually aimed.
    const rawPts = rawGeometry ? rawGeometry.lines.flat() : [];
    const allPts = [...boundaryPointsFt, ...obstacles.flatMap(o => o.points_ft), ...(boundaryPointsFt.length ? [] : rawPts)];
    const b = polygonBounds(allPts.length ? allPts : [[0, 0], [100, 100]]);
    const pad = Math.max((b.maxX - b.minX), (b.maxY - b.minY)) * 0.06 + 3;
    return { minX: b.minX - pad, minY: b.minY - pad, width: (b.maxX - b.minX) + 2 * pad, height: (b.maxY - b.minY) + 2 * pad };
  }, [boundaryPointsFt, obstacles, rawGeometry]);

  const viewBoxWidth = bbox.width / zoom;
  const viewBoxHeight = bbox.height / zoom;
  const viewBox = `${bbox.minX + pan.x} ${bbox.minY + pan.y} ${viewBoxWidth} ${viewBoxHeight}`;

  // Recompute the actual screen-pixels-per-drawing-foot scale whenever the SVG's
  // rendered size or the viewBox changes, so handle hit-areas stay a constant,
  // reliably-clickable screen size instead of shrinking to a few px at typical
  // zoom (measured: ~7px before this fix on a 65ft-wide floor — too small to
  // hit reliably, which is exactly the reported "hard time resizing" problem).
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const update = () => {
      const rect = svg.getBoundingClientRect();
      if (rect.width > 0) setPxPerFt(rect.width / viewBoxWidth);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(svg);
    return () => ro.disconnect();
  }, [viewBoxWidth]);

  const ftPerHandlePx = (px: number) => px / Math.max(pxPerFt, 0.01);

  const screenToUser = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const userPt = pt.matrixTransform(ctm.inverse());
    return { x: userPt.x, y: userPt.y };
  }, []);

  const checkCollision = useCallback((room: LiveRoom, allRooms: LiveRoom[]): boolean => {
    const rb = polygonBounds(room.geometry_points_ft);
    const boundary = polygonBounds(boundaryPointsFt);
    if (rb.minX < boundary.minX - 0.05 || rb.maxX > boundary.maxX + 0.05 || rb.minY < boundary.minY - 0.05 || rb.maxY > boundary.maxY + 0.05) return true;
    for (const obs of obstacles) {
      if (obs.status !== 'CONFIRMED') continue;
      if (rectsOverlap(rb, polygonBounds(obs.points_ft))) return true;
    }
    for (const other of allRooms) {
      if (other.room_id === room.room_id) continue;
      if (rectsOverlap(rb, polygonBounds(other.geometry_points_ft))) return true;
    }
    return false;
  }, [boundaryPointsFt, obstacles]);

  const handlePointerDown = (e: React.PointerEvent, room: LiveRoom, mode: 'move' | 'resize', handle?: HandleId) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    const { x, y } = screenToUser(e.clientX, e.clientY);
    moved.current = false;
    onSelectRoom(room.room_id);
    setDrag({ type: mode, roomId: room.room_id, handle, startX: x, startY: y, startRoom: room });
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!drag) {
      if (bgDragRef.current) {
        const dxPx = e.clientX - bgDragRef.current.startClientX;
        const dyPx = e.clientY - bgDragRef.current.startClientY;
        const dxFt = dxPx / Math.max(pxPerFt, 0.01);
        const dyFt = dyPx / Math.max(pxPerFt, 0.01);
        // Dragging right/down should reveal content to the left/above (the
        // camera moves opposite the hand) so the content under the cursor
        // visually follows the drag, same as any map/canvas grab-to-pan.
        setPan({ x: bgDragRef.current.startPan.x - dxFt, y: bgDragRef.current.startPan.y - dyFt });
      }
      return;
    }
    const { x, y } = screenToUser(e.clientX, e.clientY);
    const dx = snap(x - drag.startX, snapToGridFt);
    const dy = snap(y - drag.startY, snapToGridFt);
    if (Math.abs(x - drag.startX) > 0.02 || Math.abs(y - drag.startY) > 0.02) moved.current = true;

    setLiveRooms(prev => {
      const next = prev.map(r => {
        if (r.room_id !== drag.roomId) return r;
        let updated: LiveRoom;
        if (drag.type === 'move') {
          const [ox, oy] = drag.startRoom.origin_ft;
          const nx = snap(ox + dx, snapToGridFt);
          const ny = snap(oy + dy, snapToGridFt);
          const w = drag.startRoom.width_ft, h = drag.startRoom.depth_ft;
          updated = {
            ...r, origin_ft: [nx, ny],
            geometry_points_ft: [[nx, ny], [nx + w, ny], [nx + w, ny + h], [nx, ny + h]]
          };
        } else {
          const [ox, oy] = drag.startRoom.origin_ft;
          const ow = drag.startRoom.width_ft, oh = drag.startRoom.depth_ft;
          const minSize = snapToGridFt || 1;
          let nx = ox, ny = oy, nw = ow, nh = oh;
          const h = drag.handle!;
          const touchesE = h === 'ne' || h === 'e' || h === 'se';
          const touchesW = h === 'nw' || h === 'w' || h === 'sw';
          const touchesN = h === 'nw' || h === 'n' || h === 'ne';
          const touchesS = h === 'sw' || h === 's' || h === 'se';
          if (touchesE) nw = Math.max(snap(ow + dx, snapToGridFt), minSize);
          if (touchesW) { nw = Math.max(snap(ow - dx, snapToGridFt), minSize); nx = ox + (ow - nw); }
          if (touchesS) nh = Math.max(snap(oh + dy, snapToGridFt), minSize);
          if (touchesN) { nh = Math.max(snap(oh - dy, snapToGridFt), minSize); ny = oy + (oh - nh); }
          updated = {
            ...r, origin_ft: [nx, ny], width_ft: nw, depth_ft: nh, area_sqft: Math.round(nw * nh * 100) / 100,
            geometry_points_ft: [[nx, ny], [nx + nw, ny], [nx + nw, ny + nh], [nx, ny + nh]]
          };
        }
        return updated;
      });
      const movedRoom = next.find(r => r.room_id === drag.roomId)!;
      setCollision(checkCollision(movedRoom, next));
      onLiveChange(next);
      return next;
    });
  };

  const handlePointerUp = () => {
    // Only commit (and hit the network) if something actually changed — a plain
    // click-to-select was firing a wasted PUT /layout on every click before.
    if (drag && moved.current) {
      onCommit(liveRooms);
    }
    setDrag(null);
    setCollision(false);
    moved.current = false;
    bgDragRef.current = null;
    setIsPanning(false);
  };

  const CLOSE_HIT_FT_MULT = HANDLE_HIT_SCREEN_PX; // reuse the same generous click-target sizing as room handles

  // Drawing a boundary needs precise, undeferred clicks (each one places a
  // point), so background panning is deliberately not offered in drawMode —
  // every pointerdown there goes straight to point-adding, same as before.
  const handleDrawClick = (e: React.PointerEvent) => {
    const { x, y } = screenToUser(e.clientX, e.clientY);
    if (drawPoints.length >= 3) {
      const [fx, fy] = drawPoints[0];
      const closeHitFt = ftPerHandlePx(CLOSE_HIT_FT_MULT);
      if (Math.hypot(x - fx, y - fy) <= closeHitFt) {
        onDrawComplete?.(drawPoints);
        setDrawPoints([]);
        return;
      }
    }
    setDrawPoints(prev => [...prev, [Math.round(x * 100) / 100, Math.round(y * 100) / 100]]);
  };

  // Outside drawMode, a pointerdown on empty background deselects immediately
  // (same as before) and — new — arms a grab-to-pan drag, so the canvas can
  // be panned freely instead of only zoomed via the +/- buttons.
  const handleBackgroundPointerDown = (e: React.PointerEvent) => {
    if (drawMode) {
      handleDrawClick(e);
      return;
    }
    onSelectRoom(null);
    (e.target as Element).setPointerCapture(e.pointerId);
    bgDragRef.current = { startClientX: e.clientX, startClientY: e.clientY, startPan: pan };
    setIsPanning(true);
  };

  // Mouse-wheel zoom centered on the cursor, not the viewBox's own corner —
  // keeps whatever the user is looking at under their cursor while zooming,
  // the way any map/canvas app behaves. Attached as a real, non-passive
  // native listener (not React's onWheel prop) — React attaches wheel
  // listeners as passive by default, which silently drops preventDefault
  // (and logs a console error) instead of stopping the page from also
  // scrolling underneath the canvas while zooming.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onNativeWheel = (e: WheelEvent) => {
      e.preventDefault();
      const { x: ux, y: uy } = screenToUser(e.clientX, e.clientY);
      const oldW = bbox.width / zoom, oldH = bbox.height / zoom;
      const fracX = oldW > 0 ? (ux - (bbox.minX + pan.x)) / oldW : 0.5;
      const fracY = oldH > 0 ? (uy - (bbox.minY + pan.y)) / oldH : 0.5;
      const newZoom = Math.min(Math.max(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 0.5), 8);
      const newW = bbox.width / newZoom, newH = bbox.height / newZoom;
      setZoom(newZoom);
      setPan({ x: ux - fracX * newW - bbox.minX, y: uy - fracY * newH - bbox.minY });
    };
    svg.addEventListener('wheel', onNativeWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onNativeWheel);
  }, [bbox, pan, zoom, screenToUser]);

  // Delete/Backspace deletes the selected room (mirrors the toolbar button);
  // Escape deselects. Skipped while drawMode owns these same keys (below),
  // and while focus is in a text field so typing in the sidebar isn't hijacked.
  useEffect(() => {
    if (drawMode) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable) return;
      if (!selectedRoomId) return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        onDeleteSelected?.();
      } else if (e.key === 'Escape') {
        onSelectRoom(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawMode, selectedRoomId, onDeleteSelected, onSelectRoom]);

  useEffect(() => {
    if (!drawMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawPoints([]);
      if (e.key === 'Enter' && drawPoints.length >= 3) {
        onDrawComplete?.(drawPoints);
        setDrawPoints([]);
      }
      if (e.key === 'Backspace') setDrawPoints(prev => prev.slice(0, -1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawMode, drawPoints, onDrawComplete]);

  const draggedRoom = drag ? liveRooms.find(r => r.room_id === drag.roomId) : null;
  const gridLines = useMemo(() => {
    if (!snapToGridFt || snapToGridFt <= 0) return null;
    const lines: React.ReactNode[] = [];
    const startX = Math.floor(bbox.minX / snapToGridFt) * snapToGridFt;
    const startY = Math.floor(bbox.minY / snapToGridFt) * snapToGridFt;
    const maxLines = 400; // guard against pathologically small grid + large floor
    let count = 0;
    for (let x = startX; x <= bbox.minX + bbox.width && count < maxLines; x += snapToGridFt, count++) {
      lines.push(<line key={`gx${x}`} x1={x} y1={bbox.minY} x2={x} y2={bbox.minY + bbox.height} stroke="var(--border-color)" strokeWidth={0.03} />);
    }
    for (let y = startY; y <= bbox.minY + bbox.height && count < maxLines; y += snapToGridFt, count++) {
      lines.push(<line key={`gy${y}`} x1={bbox.minX} y1={y} x2={bbox.minX + bbox.width} y2={y} stroke="var(--border-color)" strokeWidth={0.03} />);
    }
    return lines;
  }, [bbox, snapToGridFt]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', overflow: 'hidden', position: 'relative' }}>
      <div style={{ position: 'absolute', zIndex: 10, margin: '10px', display: 'flex', gap: '4px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => setZoom(z => Math.min(z * 1.25, 8))}>+</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => setZoom(z => Math.max(z / 1.25, 0.5))}>−</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Reset</button>
        {collision && (
          <span style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger)', color: 'var(--danger)', fontSize: '0.72rem', padding: '3px 8px', borderRadius: 'var(--radius-sm)' }}>
            Overlap / out of bounds — will be rejected on release
          </span>
        )}
        {drag && draggedRoom && (
          <span className="font-mono" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', color: 'var(--text-primary)', fontSize: '0.72rem', padding: '3px 8px', borderRadius: 'var(--radius-sm)', fontVariantNumeric: 'tabular-nums' }}>
            {draggedRoom.width_ft.toFixed(1)} × {draggedRoom.depth_ft.toFixed(1)} ft ({draggedRoom.area_sqft.toFixed(0)} sqft)
          </span>
        )}
        {drawMode && (
          <span style={{ background: 'var(--brand-strong)', color: 'var(--brand-ink)', fontSize: '0.72rem', fontWeight: 600, padding: '3px 8px', borderRadius: 'var(--radius-sm)' }}>
            {drawPoints.length === 0
              ? 'Click to place the first boundary point'
              : `${drawPoints.length} point${drawPoints.length !== 1 ? 's' : ''} — click near the first point (or press Enter) to close · Backspace to undo · Esc to clear`}
          </span>
        )}
      </div>
      <svg
        ref={svgRef}
        viewBox={viewBox}
        style={{ flex: 1, width: '100%', touchAction: 'none', userSelect: 'none', cursor: drawMode ? 'crosshair' : (drag || isPanning) ? 'grabbing' : 'grab' }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerDown={handleBackgroundPointerDown}
      >
        <defs>
          {/* Soft depth on placed rooms — constant screen size regardless of
             zoom, since it's built from ftPerHandlePx like every other
             on-screen-constant measurement in this file. Turns the flat
             wireframe fill into something that reads as a placed, physical
             object rather than a bare rectangle. */}
          <filter id="roomShadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy={ftPerHandlePx(1.5)} stdDeviation={ftPerHandlePx(1.5)} floodOpacity="0.28" />
          </filter>
        </defs>
        {boundaryPointsFt.length > 0 && (
          <polygon points={boundaryPointsFt.map(p => p.join(',')).join(' ')} fill="var(--bg-secondary)" stroke="var(--text-primary)" strokeWidth={0.15} />
        )}
        {gridLines}

        {showCadLinework && rawGeometry && (
          <g opacity={0.35} pointerEvents="none">
            {rawGeometry.lines.map((l, i) => (
              <line key={`l${i}`} x1={l[0][0]} y1={l[0][1]} x2={l[1][0]} y2={l[1][1]} stroke="var(--text-tertiary)" strokeWidth={0.06} />
            ))}
            {rawGeometry.circles.map((c, i) => (
              <circle key={`c${i}`} cx={c.center[0]} cy={c.center[1]} r={c.radius} fill="none" stroke="var(--text-tertiary)" strokeWidth={0.06} />
            ))}
            {rawGeometry.texts.map((t, i) => (
              <text key={`t${i}`} x={t.position[0]} y={t.position[1]} fontSize={Math.max(bbox.width * 0.01, 0.8)} fill="var(--text-tertiary)" style={{ userSelect: 'none' }}>
                {t.text}
              </text>
            ))}
          </g>
        )}

        {obstacles.map(o => (
          <polygon
            key={o.id}
            points={o.points_ft.map(p => p.join(',')).join(' ')}
            fill={o.status === 'CONFIRMED' ? 'var(--danger)' : o.status === 'IGNORED' ? 'transparent' : 'var(--warning)'}
            fillOpacity={o.status === 'IGNORED' ? 0 : 0.55}
            stroke={o.status === 'IGNORED' ? 'var(--text-tertiary)' : 'var(--danger)'}
            strokeOpacity={o.status === 'IGNORED' ? 0.3 : 0.8}
            strokeWidth={0.1}
          />
        ))}

        {drawMode && drawPoints.length > 0 && (
          <g pointerEvents="none">
            {drawPoints.length > 1 && (
              <polyline
                points={drawPoints.map(p => p.join(',')).join(' ')}
                fill="none" stroke="var(--brand-strong)" strokeWidth={ftPerHandlePx(2)}
              />
            )}
            {drawPoints.length >= 3 && (
              <line
                x1={drawPoints[drawPoints.length - 1][0]} y1={drawPoints[drawPoints.length - 1][1]}
                x2={drawPoints[0][0]} y2={drawPoints[0][1]}
                stroke="var(--brand-strong)" strokeWidth={ftPerHandlePx(2)} strokeDasharray={`${ftPerHandlePx(4)} ${ftPerHandlePx(4)}`}
              />
            )}
            {drawPoints.map((p, i) => (
              <circle key={i} cx={p[0]} cy={p[1]} r={ftPerHandlePx(i === 0 ? 7 : 5)} fill={i === 0 ? 'var(--brand-strong)' : 'var(--bg-primary)'} stroke="var(--brand-strong)" strokeWidth={ftPerHandlePx(1.5)} />
            ))}
          </g>
        )}

        {liveRooms.map(room => {
          const isSelected = room.room_id === selectedRoomId;
          const isHovered = room.room_id === hoveredRoomId;
          const isAuditorium = room.room_type.startsWith('AUDITORIUM');
          // Auditoriums get a warm, on-brand tint (they're the room every
          // reviewer looks at first); every other zone stays the plain
          // neutral box — a deliberate, minimal distinction, not a full
          // rainbow color-coded diagram (see ROOM_NEUTRAL's own comment for
          // why this file avoids that).
          const roomFill = isAuditorium ? 'var(--brand)' : ROOM_NEUTRAL;
          const b = polygonBounds(room.geometry_points_ft);
          const w = b.maxX - b.minX, h = b.maxY - b.minY;
          const fontSize = Math.max(Math.min(w, h) * 0.09, 0.6);
          const handleVisR = ftPerHandlePx(HANDLE_SCREEN_PX) / 2;
          const handleHitR = ftPerHandlePx(HANDLE_HIT_SCREEN_PX) / 2;
          return (
            <g
              key={room.room_id}
              onPointerDown={(e) => handlePointerDown(e, room, 'move')}
              onPointerEnter={() => setHoveredRoomId(room.room_id)}
              onPointerLeave={() => setHoveredRoomId(null)}
              style={{ cursor: 'move' }}
            >
              {isSelected && (
                <polygon
                  points={room.geometry_points_ft.map(p => p.join(',')).join(' ')}
                  fill="none" stroke="var(--brand-strong)" strokeWidth={ftPerHandlePx(4)} strokeOpacity={0.3}
                />
              )}
              <polygon
                points={room.geometry_points_ft.map(p => p.join(',')).join(' ')}
                fill={roomFill}
                fillOpacity={isSelected ? 0.32 : isHovered ? 0.24 : 0.16}
                stroke={isSelected ? 'var(--text-primary)' : roomFill}
                strokeWidth={isSelected ? ftPerHandlePx(1.5) : ftPerHandlePx(1)}
                filter="url(#roomShadow)"
                style={{ transition: 'fill-opacity 0.12s ease-out, stroke-width 0.12s ease-out' }}
              />
              {isAuditorium && (() => {
                // The screen wall: a bold line across whichever edge
                // room.screen_wall names (server-derived from the marked
                // entry point — see layout_engine.py's
                // _screen_wall_for_rect; defaults to the room's min_y edge,
                // this app's original hardcoded assumption, when unset),
                // plus a small arrow into the seating rows, so an
                // auditorium reads as a real theater — screen + sightline
                // direction — not an anonymous rectangle.
                const wg = wallGeometry(b, room.screen_wall);
                const midX = (wg.wallStart[0] + wg.wallEnd[0]) / 2;
                const midY = (wg.wallStart[1] + wg.wallEnd[1]) / 2;
                const inset = wg.wallLen * 0.08;
                const lx1 = wg.wallStart[0] + wg.along[0] * inset, ly1 = wg.wallStart[1] + wg.along[1] * inset;
                const lx2 = wg.wallEnd[0] - wg.along[0] * inset, ly2 = wg.wallEnd[1] - wg.along[1] * inset;
                const b1x = midX - wg.along[0] * ftPerHandlePx(5) + wg.inward[0] * ftPerHandlePx(4);
                const b1y = midY - wg.along[1] * ftPerHandlePx(5) + wg.inward[1] * ftPerHandlePx(4);
                const b2x = midX + wg.along[0] * ftPerHandlePx(5) + wg.inward[0] * ftPerHandlePx(4);
                const b2y = midY + wg.along[1] * ftPerHandlePx(5) + wg.inward[1] * ftPerHandlePx(4);
                const tipX = midX + wg.inward[0] * ftPerHandlePx(15);
                const tipY = midY + wg.inward[1] * ftPerHandlePx(15);
                return (
                  <g pointerEvents="none">
                    <line
                      x1={lx1} y1={ly1} x2={lx2} y2={ly2}
                      stroke="var(--brand-strong)" strokeWidth={ftPerHandlePx(3)} strokeLinecap="round"
                    />
                    <polygon
                      points={`${b1x},${b1y} ${b2x},${b2y} ${tipX},${tipY}`}
                      fill="var(--brand-strong)" fillOpacity={0.5}
                    />
                  </g>
                );
              })()}
              {isAuditorium && showSeatRows && room.seat_estimate && room.seat_estimate.rows > 0 && room.seat_estimate.seats_per_row > 0 && (
                // Real per-row seat marks from seat_estimate's own row/
                // seats-per-row counts (the same real row-packing
                // seat_engine.py computes) — evenly distributed within the
                // room rather than placed at each seat type's real
                // footprint, since that geometry isn't sent to the
                // frontend; still a real count, not a decorative pattern,
                // and split around a central gap the way every packed row
                // here already reserves a central aisle. Rows progress from
                // the screen wall inward (room.screen_wall — see above),
                // not always top-to-bottom.
                (() => {
                  const wg = wallGeometry(b, room.screen_wall);
                  const rows = room.seat_estimate.rows;
                  const perRow = room.seat_estimate.seats_per_row;
                  const depthLen = wg.depthLen, wallLen = wg.wallLen;
                  const nearMargin = depthLen * 0.18, farMargin = depthLen * 0.06;
                  const usableDepth = Math.max(depthLen - nearMargin - farMargin, 0);
                  const sideMargin = wallLen * 0.08;
                  const usableWall = Math.max(wallLen - 2 * sideMargin, 0);
                  const aisleFrac = 0.1;
                  const half = Math.ceil(perRow / 2);
                  const seatR = Math.min(ftPerHandlePx(2.5), usableWall / Math.max(perRow * 2.5, 1));
                  const [ox, oy] = wg.wallStart;
                  const marks: React.ReactNode[] = [];
                  for (let r = 0; r < rows; r++) {
                    const depthOff = nearMargin + (rows > 1 ? (r / (rows - 1)) * usableDepth : usableDepth / 2);
                    const rowBaseX = ox + wg.inward[0] * depthOff, rowBaseY = oy + wg.inward[1] * depthOff;
                    for (let s = 0; s < perRow; s++) {
                      const leftSide = s < half;
                      const idx = leftSide ? s : s - half;
                      const sideCount = leftSide ? half : perRow - half;
                      if (sideCount <= 0) continue;
                      const sideLen = usableWall * (0.5 - aisleFrac / 2);
                      const sideStart = leftSide ? sideMargin : sideMargin + usableWall * (0.5 + aisleFrac / 2);
                      const alongOff = sideCount > 1 ? sideStart + (idx / (sideCount - 1)) * sideLen : sideStart + sideLen / 2;
                      const sx = rowBaseX + wg.along[0] * alongOff, sy = rowBaseY + wg.along[1] * alongOff;
                      marks.push(
                        <rect
                          key={`${r}-${s}`}
                          x={sx - seatR} y={sy - seatR} width={seatR * 2} height={seatR * 2} rx={seatR * 0.35}
                          fill="var(--text-secondary)"
                        />
                      );
                    }
                  }
                  return <g pointerEvents="none" opacity={0.65}>{marks}</g>;
                })()
              )}
              {room.doors && room.doors.length > 0 && (
                <g pointerEvents="none">
                  {room.doors.map((door, i) => {
                    const { p1, leafEnd } = doorGlyphPoints(room, door);
                    return (
                      <line
                        key={i}
                        x1={p1[0]} y1={p1[1]} x2={leafEnd[0]} y2={leafEnd[1]}
                        stroke="var(--text-primary)" strokeWidth={ftPerHandlePx(1.5)} strokeLinecap="round"
                      />
                    );
                  })}
                </g>
              )}
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2} textAnchor="middle" fontSize={fontSize} fontWeight={600} fill="var(--text-primary)" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.display_name}
              </text>
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2 + fontSize * 1.3} textAnchor="middle" fontSize={fontSize * 0.8} fill="var(--text-secondary)" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.area_sqft} sqft{room.seat_estimate?.seat_count ? ` / ${room.seat_estimate.seat_count} seats` : ''}
              </text>

              {isSelected && HANDLE_DEFS.map(hd => {
                const hx = b.minX + hd.fx * w;
                const hy = b.minY + hd.fy * h;
                const isHandleHovered = hoveredHandle === `${room.room_id}-${hd.id}`;
                return (
                  <g key={hd.id}>
                    {/* Large invisible hit area — this is the actual fix for "hard to resize" */}
                    <circle
                      cx={hx} cy={hy} r={handleHitR}
                      fill="transparent"
                      style={{ cursor: hd.cursor }}
                      onPointerDown={(e) => handlePointerDown(e, room, 'resize', hd.id)}
                      onPointerEnter={() => setHoveredHandle(`${room.room_id}-${hd.id}`)}
                      onPointerLeave={() => setHoveredHandle(null)}
                    />
                    {/* Small visible mark, constant screen size regardless of zoom */}
                    <circle
                      cx={hx} cy={hy} r={isHandleHovered ? handleVisR * 1.6 : handleVisR}
                      fill={isHandleHovered ? 'var(--brand-strong)' : 'var(--text-primary)'}
                      stroke="var(--bg-primary)" strokeWidth={ftPerHandlePx(1.5)}
                      style={{ pointerEvents: 'none', transition: 'r 0.08s ease-out' }}
                    />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
};
