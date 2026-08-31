import React from 'react';
import { FloorRegionData } from '../../types/zoning';

interface FloorNavigatorProps {
  floors: FloorRegionData[];
  selectedFloorId: string;
  onSelectFloor: (floor: FloorRegionData) => void;
}

export const FloorNavigator: React.FC<FloorNavigatorProps> = ({
  floors,
  selectedFloorId,
  onSelectFloor
}) => {
  const readyFloors = floors.filter(f => !f.is_blocked);
  const blockedFloors = floors.filter(f => f.is_blocked);

  return (
    <div style={{ width: '260px', background: '#161b22', borderRight: '1px solid #30363d', display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto' }}>
      
      {/* Navigator Header */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Floor Plans
        </div>
        <div style={{ fontSize: '0.82rem', color: '#f0f6fc', fontWeight: 600 }}>
          Dhule Cinema Complex
        </div>
      </div>

      {/* Decision-Ready Section */}
      <div style={{ padding: '12px 8px 6px 8px' }}>
        <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#238636', textTransform: 'uppercase', padding: '0 8px 6px 8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#238636' }}></span>
          Decision-Ready Floors ({readyFloors.length})
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {readyFloors.map((fl) => {
            const isSelected = fl.region_id === selectedFloorId;
            return (
              <button
                key={fl.region_id}
                onClick={() => onSelectFloor(fl)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: isSelected ? '1px solid #388bfd' : '1px solid transparent',
                  background: isSelected ? 'rgba(56, 139, 253, 0.12)' : 'transparent',
                  color: isSelected ? '#58a6ff' : '#f0f6fc',
                  cursor: 'pointer',
                  transition: 'background 0.15s'
                }}
              >
                <div style={{ fontSize: '0.85rem', fontWeight: isSelected ? 700 : 500 }}>
                  {fl.plan_region.replace(' FLOOR PLAN', '')}
                </div>
                <div style={{ fontSize: '0.72rem', color: isSelected ? '#79c0ff' : '#8b949e', marginTop: '2px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>Candidate C · {fl.m5_preferred_score}</span>
                  {fl.has_review_required && (
                    <span style={{ color: '#d29922', fontSize: '0.68rem', fontWeight: 700, background: 'rgba(210, 153, 34, 0.15)', padding: '1px 4px', borderRadius: '3px' }}>
                      ⚠ Review Req
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Blocked Regions Section */}
      <div style={{ padding: '12px 8px 16px 8px', borderTop: '1px solid #21262d', marginTop: '8px' }}>
        <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#f85149', textTransform: 'uppercase', padding: '0 8px 6px 8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#f85149' }}></span>
          Blocked Regions ({blockedFloors.length})
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {blockedFloors.map((fl) => {
            const isSelected = fl.region_id === selectedFloorId;
            return (
              <button
                key={fl.region_id}
                onClick={() => onSelectFloor(fl)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: isSelected ? '1px solid #f85149' : '1px solid transparent',
                  background: isSelected ? 'rgba(248, 81, 73, 0.12)' : 'transparent',
                  color: isSelected ? '#ff7b72' : '#8b949e',
                  cursor: 'pointer',
                  opacity: isSelected ? 1 : 0.8
                }}
              >
                <div style={{ fontSize: '0.82rem', fontWeight: 500 }}>
                  {fl.plan_region.length > 24 ? fl.plan_region.slice(0, 22) + '...' : fl.plan_region}
                </div>
                <div style={{ fontSize: '0.68rem', color: '#f85149', marginTop: '2px' }}>
                  BLOCKED — No boundary
                </div>
              </button>
            );
          })}
        </div>
      </div>

    </div>
  );
};
