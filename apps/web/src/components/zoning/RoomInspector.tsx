import React from 'react';
import { RoomData } from '../../types/zoning';

interface RoomInspectorProps {
  room: RoomData | null;
  onClose: () => void;
}

export const RoomInspector: React.FC<RoomInspectorProps> = ({ room, onClose }) => {
  if (!room) {
    return (
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '16px', marginBottom: '16px', textAlign: 'center', color: '#8b949e', fontSize: '0.8rem' }}>
        <div style={{ fontSize: '1.4rem', marginBottom: '6px' }}>🔍</div>
        Click any room on the plan canvas to inspect dimensions, programmatic compliance, and structural clearance.
      </div>
    );
  }

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      
      {/* Inspector Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div>
          <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
            Room Inspector
          </div>
          <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#f0f6fc' }}>
            {room.display_name}
          </div>
        </div>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#8b949e', fontSize: '1.1rem', cursor: 'pointer' }}>×</button>
      </div>

      {/* Metric Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
        <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>Allocated Area</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#f0f6fc' }}>{room.area_sqft} <span style={{ fontSize: '0.75rem', fontWeight: 500 }}>sq ft</span></div>
          <div style={{ fontSize: '0.68rem', color: '#3fb950' }}>Min: {room.min_area_sqft} sq ft</div>
        </div>

        <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>Dimensions</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#f0f6fc' }}>{room.width_ft} × {room.depth_ft} <span style={{ fontSize: '0.75rem', fontWeight: 500 }}>ft</span></div>
          <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>Aspect: {(room.width_ft / room.depth_ft).toFixed(2)}</div>
        </div>
      </div>

      {/* Detail Attributes */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
          <span style={{ color: '#8b949e' }}>Validation Status:</span>
          <span style={{ fontWeight: 700, color: room.status === 'VALID' ? '#3fb950' : '#d29922' }}>
            {room.status}
          </span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
          <span style={{ color: '#8b949e' }}>Adjacency Interface:</span>
          <span style={{ color: '#f0f6fc', textAlign: 'right', maxWidth: '60%' }}>{room.adjacency}</span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
          <span style={{ color: '#8b949e' }}>Structural Clearance:</span>
          <span style={{ color: '#3fb950', fontWeight: 600 }}>{room.structural_clearance}</span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
          <span style={{ color: '#8b949e' }}>Source Layout:</span>
          <span style={{ color: '#8b949e' }}>{room.source}</span>
        </div>

        {room.seat_count !== undefined && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderTop: '1px solid #21262d' }}>
              <span style={{ color: '#8b949e' }}>Estimated Seats:</span>
              <span style={{ fontWeight: 700, color: '#58a6ff' }}>{room.seat_count} (Sofa Slider)</span>
            </div>
            {room.preset_fit && (
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                <span style={{ color: '#8b949e' }}>SOP Preset Fit:</span>
                <span style={{ color: room.preset_fit.matches_preset ? '#3fb950' : '#d29922', textAlign: 'right' }}>
                  {room.preset_fit.matches_preset || room.preset_fit.status.replace(/_/g, ' ')}
                </span>
              </div>
            )}
          </>
        )}
      </div>

    </div>
  );
};
