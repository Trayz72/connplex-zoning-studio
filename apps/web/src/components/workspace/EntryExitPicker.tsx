import React, { useState } from 'react';
import { EntryExitMarkers } from './EntryExitMarkers';

interface EntryExitPickerProps {
  boundaryPointsFt: number[][];
  entryValue: [number, number] | null;
  onEntryChange: (pt: [number, number] | null) => void;
  exitValues: [number, number][];
  onExitChange: (pts: [number, number][]) => void;
  /** Fixed pixel height for the SVG — callers embed this at different sizes
   * (a compact review widget vs. the primary full-width capture step). */
  height?: number;
}

/** Click-to-mark the main entrance and zero or more exits on the real
 * confirmed boundary outline. Nothing in CAD extraction detects doors, so
 * this is the one honest way to get this data: ask the person who actually
 * knows where the entrance/exits are, rather than guess at a plausible-
 * sounding rule (e.g. "assume the longest edge") the project's own
 * anti-hallucination principle rules out. Both are optional — SOP-required
 * architecturally, but not something this v1 gates progress on, same
 * "advisory, never a silent blocker" stance as everything else here (see
 * layout_engine.py's own honest-skip behavior when neither is marked). */
export const EntryExitPicker: React.FC<EntryExitPickerProps> = ({
  boundaryPointsFt, entryValue, onEntryChange, exitValues, onExitChange, height = 260,
}) => {
  const [mode, setMode] = useState<'entry' | 'exit'>(entryValue ? 'exit' : 'entry');

  const xs = boundaryPointsFt.map(p => p[0]);
  const ys = boundaryPointsFt.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = maxX - minX || 1, h = maxY - minY || 1;
  const pad = Math.max(w, h) * 0.06;
  const viewBox = `${minX - pad} ${minY - pad} ${w + pad * 2} ${h + pad * 2}`;
  const markerR = Math.max(w, h) * 0.018;

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const local = pt.matrixTransform(ctm.inverse());
    const clicked: [number, number] = [Math.round(local.x * 10) / 10, Math.round(local.y * 10) / 10];
    if (mode === 'entry') {
      onEntryChange(clicked);
    } else {
      onExitChange([...exitValues, clicked]);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: '6px', marginBottom: '8px' }}>
        <button
          type="button"
          className={mode === 'entry' ? 'btn btn-primary' : 'btn btn-secondary'}
          style={{ fontSize: '0.74rem', padding: '5px 10px' }}
          onClick={() => setMode('entry')}
        >
          Mark Main Entrance
        </button>
        <button
          type="button"
          className={mode === 'exit' ? 'btn btn-primary' : 'btn btn-secondary'}
          style={{ fontSize: '0.74rem', padding: '5px 10px' }}
          onClick={() => setMode('exit')}
        >
          Add Exit Point
        </button>
      </div>

      <svg
        viewBox={viewBox}
        style={{ width: '100%', height: `${height}px`, background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', cursor: 'crosshair' }}
        onClick={handleClick}
      >
        <polygon
          points={boundaryPointsFt.map(p => p.join(',')).join(' ')}
          fill="var(--bg-secondary)" stroke="var(--border-strong)" strokeWidth={w * 0.004}
        />
        <EntryExitMarkers entryPointFt={entryValue} exitPointsFt={exitValues} markerR={markerR} />
      </svg>

      <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '6px' }}>
        {mode === 'entry'
          ? (entryValue ? `Entrance marked at (${entryValue[0]}, ${entryValue[1]}) ft — click the plan again to move it.` : 'Click the floor plate to mark the main entrance.')
          : 'Click the floor plate to add an exit point — click again to add more.'}
      </div>

      {(entryValue || exitValues.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
          {entryValue && (
            <span style={{ fontSize: '0.7rem', background: 'var(--bg-raised)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              Entrance ({entryValue[0]}, {entryValue[1]})
              <a href="#" onClick={(e) => { e.preventDefault(); onEntryChange(null); }} style={{ color: 'var(--danger)' }}>Clear</a>
            </span>
          )}
          {exitValues.map((p, i) => (
            <span key={i} style={{ fontSize: '0.7rem', background: 'var(--bg-raised)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              Exit {i + 1} ({p[0]}, {p[1]})
              <a href="#" onClick={(e) => { e.preventDefault(); onExitChange(exitValues.filter((_, j) => j !== i)); }} style={{ color: 'var(--danger)' }}>Remove</a>
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
