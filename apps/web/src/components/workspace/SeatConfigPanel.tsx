import React, { useState, useEffect } from 'react';
import { LiveRoom, SelectableSeatType, SeatConfig } from '../../types/live';

interface SeatConfigPanelProps {
  room: LiveRoom;
  seatTypes: SelectableSeatType[];
  onApply: (seatConfig: SeatConfig) => void;
  applying: boolean;
  /** When true, skip the outer card wrapper — used when the parent already
   * provides one (e.g. alongside RoomDimensionEditor in the same card). */
  embedded?: boolean;
}

export const SeatConfigPanel: React.FC<SeatConfigPanelProps> = ({ room, seatTypes, onApply, applying, embedded }) => {
  const existing = room.seat_config;
  const [primary, setPrimary] = useState(existing?.primary_seat_type_id || 'SLIDER_SOFA');
  const [secondary, setSecondary] = useState<string>(existing?.secondary_seat_type_id || '');
  const [ratio, setRatio] = useState(existing?.primary_ratio_pct ?? 100);

  useEffect(() => {
    setPrimary(existing?.primary_seat_type_id || 'SLIDER_SOFA');
    setSecondary(existing?.secondary_seat_type_id || '');
    setRatio(existing?.primary_ratio_pct ?? 100);
  }, [room.room_id]);

  if (!room.room_type.startsWith('AUDITORIUM')) return null;

  const primaryType = seatTypes.find(t => t.id === primary);
  const secondaryType = seatTypes.find(t => t.id === secondary);

  const apply = () => {
    onApply({
      primary_seat_type_id: primary,
      secondary_seat_type_id: secondary || null,
      primary_ratio_pct: secondary ? ratio : 100
    });
  };

  const selectStyle: React.CSSProperties = {
    width: '100%', padding: '4px 6px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
    color: 'var(--text-primary)', borderRadius: '4px', fontSize: '0.75rem'
  };

  const content = (
    <>
      <div className="panel-label" style={{ marginBottom: '8px' }}>
        {room.display_name}
      </div>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)', marginBottom: '4px' }}>
        {room.area_sqft} sqft ({room.width_ft} × {room.depth_ft} ft)
      </div>
      {room.seat_estimate && (
        <div style={{ fontSize: '0.82rem', color: 'var(--text-primary)', fontWeight: 700, marginBottom: '8px' }}>
          {room.seat_estimate.seat_count} seats ({room.seat_estimate.rows} rows × {room.seat_estimate.seats_per_row}/row)
        </div>
      )}
      {room.preset_fit && (
        <div style={{ fontSize: '0.7rem', color: room.preset_fit.matches_preset ? 'var(--success)' : 'var(--warning)', marginBottom: '10px' }}>
          {room.preset_fit.matches_preset ? `Meets ${room.preset_fit.matches_preset} preset` : room.preset_fit.status.replace(/_/g, ' ')}
        </div>
      )}

      <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
        <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', marginBottom: '6px' }}>Seat Configuration</div>
        <label style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '3px' }}>Seat Type</label>
        <select style={selectStyle} value={primary} onChange={(e) => setPrimary(e.target.value)}>
          {seatTypes.map(t => <option key={t.id} value={t.id}>{t.name} ({t.category})</option>)}
        </select>

        <label style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-tertiary)', margin: '8px 0 3px' }}>
          Mix with a second type (optional)
        </label>
        <select style={selectStyle} value={secondary} onChange={(e) => setSecondary(e.target.value)}>
          <option value="">— None (single type) —</option>
          {seatTypes.filter(t => t.id !== primary).map(t => <option key={t.id} value={t.id}>{t.name} ({t.category})</option>)}
        </select>

        {secondary && (
          <div style={{ marginTop: '8px' }}>
            <label style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '3px' }}>
              Mix ratio — front rows {primaryType?.name} {ratio}% / back rows {secondaryType?.name} {100 - ratio}%
            </label>
            <input
              type="range" min={0} max={100} step={5} value={ratio}
              onChange={(e) => setRatio(parseInt(e.target.value, 10))}
              style={{ width: '100%' }}
            />
            <div style={{ fontSize: '0.62rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>
              Rows nearest the screen get {primaryType?.name}; the remaining depth gets {secondaryType?.name}.
            </div>
          </div>
        )}

        <button className="btn btn-primary" style={{ width: '100%', fontSize: '0.78rem', marginTop: '10px' }} disabled={applying} onClick={apply}>
          {applying ? 'Applying…' : 'Apply Seat Configuration'}
        </button>
      </div>
    </>
  );

  if (embedded) return content;

  return (
    <div className="panel" style={{ marginBottom: '16px' }}>
      {content}
    </div>
  );
};
