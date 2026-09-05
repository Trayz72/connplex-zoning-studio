import React, { useState, useEffect } from 'react';
import { LiveRoom } from '../../types/live';

interface RoomNameEditorProps {
  room: LiveRoom;
  onApply: (displayName: string) => void;
  applying: boolean;
}

/** Every room's display_name arrives server-generated ("Screen 1
 * (Auditorium)", "Food & Beverage / Concession") — real, honest defaults,
 * but a client-facing sheet often wants the architect's own naming
 * ("IMAX", "Premium Screen"). Server-side, display_name is stored as
 * whatever the client sends (see main.py's update_layout — it's never
 * regenerated on an edit), so this is a plain rename, no backend change
 * needed. */
export const RoomNameEditor: React.FC<RoomNameEditorProps> = ({ room, onApply, applying }) => {
  const [name, setName] = useState(room.display_name);
  useEffect(() => { setName(room.display_name); }, [room.room_id, room.display_name]);
  const dirty = name.trim() !== '' && name.trim() !== room.display_name;

  return (
    <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
      <input
        type="text" value={name} onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && dirty) onApply(name); }}
        style={{
          flex: 1, padding: '4px 6px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
          color: 'var(--text-primary)', borderRadius: '4px', fontSize: '0.78rem', fontWeight: 600
        }}
      />
      <button
        className="btn btn-secondary btn-sm" disabled={!dirty || applying}
        style={{ opacity: dirty ? 1 : 0.5 }}
        onClick={() => onApply(name)}
      >
        {applying ? '…' : 'Rename'}
      </button>
    </div>
  );
};

interface RoomDimensionEditorProps {
  room: LiveRoom;
  onApply: (updates: { origin_ft: [number, number]; width_ft: number; depth_ft: number }) => void;
  applying: boolean;
}

/** Precise, reliable alternative to drag-resizing — professional CAD/design
 * tools always offer a numeric fallback because pixel-dragging can't guarantee
 * an exact dimension. Feeds the same PUT /layout validation as a drag, so a
 * value that would overlap something is rejected the same honest way. */
export const RoomDimensionEditor: React.FC<RoomDimensionEditorProps> = ({ room, onApply, applying }) => {
  const [x, setX] = useState(room.origin_ft[0]);
  const [y, setY] = useState(room.origin_ft[1]);
  const [w, setW] = useState(room.width_ft);
  const [d, setD] = useState(room.depth_ft);

  useEffect(() => {
    setX(room.origin_ft[0]); setY(room.origin_ft[1]); setW(room.width_ft); setD(room.depth_ft);
  }, [room.room_id, room.origin_ft[0], room.origin_ft[1], room.width_ft, room.depth_ft]);

  const dirty = x !== room.origin_ft[0] || y !== room.origin_ft[1] || w !== room.width_ft || d !== room.depth_ft;

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '4px 6px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
    color: 'var(--text-primary)', borderRadius: '4px', fontSize: '0.75rem'
  };

  return (
    <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '10px', marginTop: '10px' }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', marginBottom: '6px' }}>
        Exact Position &amp; Size (ft)
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '6px' }}>
        <div>
          <label style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>X</label>
          <input type="number" step={0.1} style={inputStyle} value={x} onChange={(e) => setX(parseFloat(e.target.value) || 0)} />
        </div>
        <div>
          <label style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>Y</label>
          <input type="number" step={0.1} style={inputStyle} value={y} onChange={(e) => setY(parseFloat(e.target.value) || 0)} />
        </div>
        <div>
          <label style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>Width</label>
          <input type="number" step={0.1} min={0.5} style={inputStyle} value={w} onChange={(e) => setW(parseFloat(e.target.value) || 0.5)} />
        </div>
        <div>
          <label style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>Depth</label>
          <input type="number" step={0.1} min={0.5} style={inputStyle} value={d} onChange={(e) => setD(parseFloat(e.target.value) || 0.5)} />
        </div>
      </div>
      <button
        className="btn btn-secondary"
        style={{ width: '100%', fontSize: '0.72rem', opacity: dirty ? 1 : 0.5 }}
        disabled={!dirty || applying}
        onClick={() => onApply({ origin_ft: [x, y], width_ft: w, depth_ft: d })}
      >
        {applying ? 'Applying…' : dirty ? `Apply (${(w * d).toFixed(0)} sqft)` : 'No changes'}
      </button>
    </div>
  );
};
