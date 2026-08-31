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
}

// Same hue family per room type as ROOM_FILL in services/zoning-engine/export_pdf.py
// — saturated here for a dark canvas background, pastel there for a printed white
// page. Keep both in sync when either changes: before this fix they'd drifted
// into unrelated colors per room type (e.g. washrooms were purple on-screen but
// blue in the exported PDF), so the same room read as a different color depending
// on whether you were looking at the editor or the deliverable.
const ROOM_COLORS: Record<string, string> = {
  AUDITORIUM: '#7c6fd6',   // violet
  FOYER: '#3fb968',        // green
  FNB: '#d68a3f',          // amber
  WASHROOM: '#4a90d6',     // blue
  BOX_OFFICE: '#d65f96',   // magenta
  BOH: '#8a8a94'           // slate
};

const HANDLE_SCREEN_PX = 9;       // visible handle size, constant on screen regardless of zoom
const HANDLE_HIT_SCREEN_PX = 26;  // invisible hit-area, much larger than the visible mark — this is the actual fix

function roomColor(type: string): string {
  const key = type.startsWith('AUDITORIUM') ? 'AUDITORIUM' : type;
  return ROOM_COLORS[key] || '#6b7280';
}

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
  rawGeometry, showCadLinework = true
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragMode>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoom[]>(rooms);
  const [zoom, setZoom] = useState(1);
  const [pxPerFt, setPxPerFt] = useState(10);
  const [collision, setCollision] = useState(false);
  const [hoveredHandle, setHoveredHandle] = useState<string | null>(null);
  const [hoveredRoomId, setHoveredRoomId] = useState<string | null>(null);
  const moved = useRef(false);

  useEffect(() => { setLiveRooms(rooms); }, [rooms]);

  const bbox = useMemo(() => {
    const allPts = [...boundaryPointsFt, ...obstacles.flatMap(o => o.points_ft)];
    const b = polygonBounds(allPts.length ? allPts : [[0, 0], [100, 100]]);
    const pad = Math.max((b.maxX - b.minX), (b.maxY - b.minY)) * 0.06 + 3;
    return { minX: b.minX - pad, minY: b.minY - pad, width: (b.maxX - b.minX) + 2 * pad, height: (b.maxY - b.minY) + 2 * pad };
  }, [boundaryPointsFt, obstacles]);

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

  const draggedRoom = drag ? liveRooms.find(r => r.room_id === drag.roomId) : null;
  const gridLines = useMemo(() => {
    if (!snapToGridFt || snapToGridFt <= 0) return null;
    const lines: React.ReactNode[] = [];
    const startX = Math.floor(bbox.minX / snapToGridFt) * snapToGridFt;
    const startY = Math.floor(bbox.minY / snapToGridFt) * snapToGridFt;
    const maxLines = 400; // guard against pathologically small grid + large floor
    let count = 0;
    for (let x = startX; x <= bbox.minX + bbox.width && count < maxLines; x += snapToGridFt, count++) {
      lines.push(<line key={`gx${x}`} x1={x} y1={bbox.minY} x2={x} y2={bbox.minY + bbox.height} stroke="#1c2128" strokeWidth={0.03} />);
    }
    for (let y = startY; y <= bbox.minY + bbox.height && count < maxLines; y += snapToGridFt, count++) {
      lines.push(<line key={`gy${y}`} x1={bbox.minX} y1={y} x2={bbox.minX + bbox.width} y2={y} stroke="#1c2128" strokeWidth={0.03} />);
    }
    return lines;
  }, [bbox, snapToGridFt]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0a0d12', border: '1px solid #30363d', borderRadius: '8px', overflow: 'hidden', position: 'relative' }}>
      <div style={{ position: 'absolute', zIndex: 10, margin: '10px', display: 'flex', gap: '4px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(z => Math.min(z * 1.25, 8))}>[ + ]</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(z => Math.max(z / 1.25, 0.5))}>[ − ]</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(1)}>[ Reset ]</button>
        {collision && (
          <span style={{ background: 'rgba(248,81,73,0.2)', border: '1px solid #f85149', color: '#ff7b72', fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px' }}>
            ⚠ Overlap / out of bounds — will be rejected on release
          </span>
        )}
        {drag && draggedRoom && (
          <span style={{ background: 'rgba(56,139,253,0.2)', border: '1px solid #388bfd', color: '#79c0ff', fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', fontVariantNumeric: 'tabular-nums' }}>
            {draggedRoom.width_ft.toFixed(1)} × {draggedRoom.depth_ft.toFixed(1)} ft ({draggedRoom.area_sqft.toFixed(0)} sqft)
          </span>
        )}
      </div>
      <svg
        ref={svgRef}
        viewBox={viewBox}
        style={{ flex: 1, width: '100%', touchAction: 'none', cursor: drag ? 'grabbing' : 'default' }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onClick={() => onSelectRoom(null)}
      >
        <polygon points={boundaryPointsFt.map(p => p.join(',')).join(' ')} fill="#12161c" stroke="#e6edf3" strokeWidth={0.15} />
        {gridLines}

        {showCadLinework && rawGeometry && (
          <g opacity={0.35} pointerEvents="none">
            {rawGeometry.lines.map((l, i) => (
              <line key={`l${i}`} x1={l[0][0]} y1={l[0][1]} x2={l[1][0]} y2={l[1][1]} stroke="#5a6b7d" strokeWidth={0.06} />
            ))}
            {rawGeometry.circles.map((c, i) => (
              <circle key={`c${i}`} cx={c.center[0]} cy={c.center[1]} r={c.radius} fill="none" stroke="#5a6b7d" strokeWidth={0.06} />
            ))}
            {rawGeometry.texts.map((t, i) => (
              <text key={`t${i}`} x={t.position[0]} y={t.position[1]} fontSize={Math.max(bbox.width * 0.01, 0.8)} fill="#6e7f91" style={{ userSelect: 'none' }}>
                {t.text}
              </text>
            ))}
          </g>
        )}

        {obstacles.map(o => (
          <polygon
            key={o.id}
            points={o.points_ft.map(p => p.join(',')).join(' ')}
            fill={o.status === 'CONFIRMED' ? '#f85149' : o.status === 'IGNORED' ? 'transparent' : '#d29922'}
            fillOpacity={o.status === 'IGNORED' ? 0 : 0.55}
            stroke={o.status === 'IGNORED' ? '#8b949e' : '#f85149'}
            strokeOpacity={o.status === 'IGNORED' ? 0.3 : 0.8}
            strokeWidth={0.1}
          />
        ))}

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
                  fill="none" stroke="#388bfd" strokeWidth={ftPerHandlePx(4)} strokeOpacity={0.35}
                />
              )}
              <polygon
                points={room.geometry_points_ft.map(p => p.join(',')).join(' ')}
                fill={roomColor(room.room_type)}
                fillOpacity={isSelected ? 0.78 : isHovered ? 0.62 : 0.5}
                stroke={isSelected ? '#ffffff' : roomColor(room.room_type)}
                strokeWidth={isSelected ? ftPerHandlePx(1.5) : ftPerHandlePx(1)}
              />
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2} textAnchor="middle" fontSize={fontSize} fontWeight={600} fill="#ffffff" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.display_name}
              </text>
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2 + fontSize * 1.3} textAnchor="middle" fontSize={fontSize * 0.8} fill="#e6edf3" style={{ pointerEvents: 'none', userSelect: 'none' }}>
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
                      fill={isHandleHovered ? '#388bfd' : '#ffffff'}
                      stroke="#0d1117" strokeWidth={ftPerHandlePx(1.5)}
                      style={{ pointerEvents: 'none', transition: 'r 0.08s ease-out' }}
                    />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div style={{ position: 'absolute', bottom: '8px', right: '10px', fontSize: '0.68rem', color: '#8b949e', background: 'rgba(13,17,23,0.7)', padding: '2px 6px', borderRadius: '4px' }}>
        Drag a room to move it · drag a white handle to resize · use the exact-size fields in the sidebar for precise dimensions
      </div>
    </div>
  );
};
