import React, { useMemo, useRef, useState, useCallback } from 'react';
import { LiveRoom, Obstacle } from '../../types/live';

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
}

const ROOM_COLORS: Record<string, string> = {
  AUDITORIUM: '#4a7fd6', FOYER: '#4fae5a', FNB: '#c99a3b', WASHROOM: '#9a5fc9',
  BOX_OFFICE: '#d65f8f', BOH: '#8a8a8a'
};

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

type DragMode = { type: 'move' | 'resize'; roomId: string; corner?: 'nw' | 'ne' | 'sw' | 'se'; startX: number; startY: number; startRoom: LiveRoom } | null;

export const EditableCanvas: React.FC<EditableCanvasProps> = ({
  boundaryPointsFt, obstacles, rooms, selectedRoomId, onSelectRoom, onLiveChange, onCommit, snapToGridFt
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<DragMode>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoom[]>(rooms);
  const [zoom, setZoom] = useState(1);
  const [collision, setCollision] = useState(false);

  React.useEffect(() => { setLiveRooms(rooms); }, [rooms]);

  const bbox = useMemo(() => {
    const allPts = [...boundaryPointsFt, ...obstacles.flatMap(o => o.points_ft)];
    const b = polygonBounds(allPts.length ? allPts : [[0, 0], [100, 100]]);
    const pad = Math.max((b.maxX - b.minX), (b.maxY - b.minY)) * 0.06 + 3;
    return { minX: b.minX - pad, minY: b.minY - pad, width: (b.maxX - b.minX) + 2 * pad, height: (b.maxY - b.minY) + 2 * pad };
  }, [boundaryPointsFt, obstacles]);

  const viewBox = `${bbox.minX} ${bbox.minY} ${bbox.width / zoom} ${bbox.height / zoom}`;

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

  const handlePointerDown = (e: React.PointerEvent, room: LiveRoom, mode: 'move' | 'resize', corner?: 'nw' | 'ne' | 'sw' | 'se') => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    const { x, y } = screenToUser(e.clientX, e.clientY);
    onSelectRoom(room.room_id);
    setDrag({ type: mode, roomId: room.room_id, corner, startX: x, startY: y, startRoom: room });
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const { x, y } = screenToUser(e.clientX, e.clientY);
    const dx = snap(x - drag.startX, snapToGridFt);
    const dy = snap(y - drag.startY, snapToGridFt);

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
          let nx = ox, ny = oy, nw = ow, nh = oh;
          if (drag.corner === 'se') { nw = Math.max(snap(ow + dx, snapToGridFt), snapToGridFt || 1); nh = Math.max(snap(oh + dy, snapToGridFt), snapToGridFt || 1); }
          if (drag.corner === 'ne') { nw = Math.max(snap(ow + dx, snapToGridFt), snapToGridFt || 1); nh = Math.max(snap(oh - dy, snapToGridFt), snapToGridFt || 1); ny = oy + (oh - nh); }
          if (drag.corner === 'sw') { nw = Math.max(snap(ow - dx, snapToGridFt), snapToGridFt || 1); nh = Math.max(snap(oh + dy, snapToGridFt), snapToGridFt || 1); nx = ox + (ow - nw); }
          if (drag.corner === 'nw') { nw = Math.max(snap(ow - dx, snapToGridFt), snapToGridFt || 1); nh = Math.max(snap(oh - dy, snapToGridFt), snapToGridFt || 1); nx = ox + (ow - nw); ny = oy + (oh - nh); }
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
    if (drag) {
      onCommit(liveRooms);
    }
    setDrag(null);
    setCollision(false);
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0a0d12', border: '1px solid #30363d', borderRadius: '8px', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', zIndex: 10, margin: '10px', display: 'flex', gap: '4px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(z => Math.min(z * 1.25, 4))}>[ + ]</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(z => Math.max(z / 1.25, 0.5))}>[ − ]</button>
        <button className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '3px 8px' }} onClick={() => setZoom(1)}>[ Reset ]</button>
        {collision && (
          <span style={{ background: 'rgba(248,81,73,0.2)', border: '1px solid #f85149', color: '#ff7b72', fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px' }}>
            ⚠ Overlap / out of bounds — will be rejected on release
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
          const b = polygonBounds(room.geometry_points_ft);
          const w = b.maxX - b.minX, h = b.maxY - b.minY;
          const fontSize = Math.max(Math.min(w, h) * 0.09, 0.6);
          return (
            <g key={room.room_id} onPointerDown={(e) => handlePointerDown(e, room, 'move')} style={{ cursor: 'move' }}>
              <polygon
                points={room.geometry_points_ft.map(p => p.join(',')).join(' ')}
                fill={roomColor(room.room_type)}
                fillOpacity={isSelected ? 0.75 : 0.5}
                stroke={isSelected ? '#ffffff' : roomColor(room.room_type)}
                strokeWidth={isSelected ? 0.3 : 0.12}
              />
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2} textAnchor="middle" fontSize={fontSize} fill="#ffffff" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.display_name}
              </text>
              <text x={(b.minX + b.maxX) / 2} y={(b.minY + b.maxY) / 2 + fontSize * 1.3} textAnchor="middle" fontSize={fontSize * 0.8} fill="#e6edf3" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {room.area_sqft} sqft{room.seat_estimate?.seat_count ? ` / ${room.seat_estimate.seat_count} seats` : ''}
              </text>

              {isSelected && (['nw', 'ne', 'sw', 'se'] as const).map(corner => {
                const hx = corner.includes('w') ? b.minX : b.maxX;
                const hy = corner.includes('n') ? b.minY : b.maxY;
                const handleSize = Math.max(bbox.width * 0.012, 0.4);
                return (
                  <rect
                    key={corner}
                    x={hx - handleSize / 2} y={hy - handleSize / 2} width={handleSize} height={handleSize}
                    fill="#ffffff" stroke="#000000" strokeWidth={0.05}
                    style={{ cursor: `${corner}-resize` }}
                    onPointerDown={(e) => handlePointerDown(e, room, 'resize', corner)}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
};
