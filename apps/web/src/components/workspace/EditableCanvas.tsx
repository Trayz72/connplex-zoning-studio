import React, { useMemo, useRef, useState, useCallback, useEffect } from 'react';
import { LiveRoom, Obstacle } from '../../types/live';
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
  /** When true, clicking the canvas traces a boundary polygon instead of
   * selecting/dragging rooms — for "draw your own boundary" when auto-
   * detection found the wrong region, or none at all. */
  drawMode?: boolean;
  onDrawComplete?: (points: number[][]) => void;
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
  rawGeometry, showCadLinework = true, drawMode = false, onDrawComplete
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragMode>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoom[]>(rooms);
  const [zoom, setZoom] = useState(1);
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
  const viewBox = `${bbox.minX} ${bbox.minY} ${viewBoxWidth} ${bbox.height / zoom}`;

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
    if (!drag) return;
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
  };

  const CLOSE_HIT_FT_MULT = HANDLE_HIT_SCREEN_PX; // reuse the same generous click-target sizing as room handles

  const handleBackgroundClick = (e: React.PointerEvent) => {
    if (!drawMode) {
      onSelectRoom(null);
      return;
    }
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
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 10px' }} onClick={() => setZoom(1)}>Reset</button>
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
        style={{ flex: 1, width: '100%', touchAction: 'none', cursor: drawMode ? 'crosshair' : drag ? 'grabbing' : 'default' }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerDown={handleBackgroundClick}
      >
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
                fill={ROOM_NEUTRAL}
                fillOpacity={isSelected ? 0.32 : isHovered ? 0.24 : 0.16}
                stroke={isSelected ? '#ffffff' : ROOM_NEUTRAL}
                strokeWidth={isSelected ? ftPerHandlePx(1.5) : ftPerHandlePx(1)}
              />
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2} textAnchor="middle" fontSize={fontSize} fontWeight={600} fill="#ffffff" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.display_name}
              </text>
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2 + fontSize * 1.3} textAnchor="middle" fontSize={fontSize * 0.8} fill="#d8d8db" style={{ pointerEvents: 'none', userSelect: 'none' }}>
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
                      fill={isHandleHovered ? 'var(--brand-strong)' : '#ffffff'}
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
      <div style={{ position: 'absolute', bottom: '8px', right: '10px', fontSize: '0.68rem', color: 'var(--text-tertiary)', background: 'rgba(0,0,0,0.55)', padding: '2px 6px', borderRadius: 'var(--radius-sm)' }}>
        Drag a room to move it · drag a white handle to resize · use the exact-size fields in the sidebar for precise dimensions
      </div>
    </div>
  );
};
