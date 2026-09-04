import React from 'react';

interface EntryExitMarkersProps {
  entryPointFt: [number, number] | null | undefined;
  exitPointsFt: [number, number][] | null | undefined;
  markerR: number;
}

/** The building's own main entrance ("IN") / exit ("E1", "E2"...) markers —
 * one shared visual convention (brand-color circle for entry, danger-color
 * circle for exits) reused by EntryExitPicker.tsx's own click-to-mark
 * boundary view and EditableCanvas.tsx's Edit-step floor plan, so the same
 * marker means the same thing everywhere in the app. Distinct from a
 * room's own door glyphs — this is the building's entrance, not a room
 * opening. */
export const EntryExitMarkers: React.FC<EntryExitMarkersProps> = ({ entryPointFt, exitPointsFt, markerR }) => (
  <g pointerEvents="none">
    {(exitPointsFt ?? []).map((p, i) => (
      <g key={`exit-${i}`}>
        <circle cx={p[0]} cy={p[1]} r={markerR} fill="var(--danger)" stroke="var(--bg-primary)" strokeWidth={markerR * 0.16} />
        <text x={p[0]} y={p[1] - markerR * 1.6} textAnchor="middle" fontSize={markerR * 1.3} fontWeight={700} fill="var(--danger)">E{i + 1}</text>
      </g>
    ))}
    {entryPointFt && (
      <g>
        <circle cx={entryPointFt[0]} cy={entryPointFt[1]} r={markerR * 1.15} fill="var(--brand-strong)" stroke="var(--bg-primary)" strokeWidth={markerR * 0.16} />
        <text x={entryPointFt[0]} y={entryPointFt[1] - markerR * 1.9} textAnchor="middle" fontSize={markerR * 1.3} fontWeight={700} fill="var(--brand-strong)">IN</text>
      </g>
    )}
  </g>
);
