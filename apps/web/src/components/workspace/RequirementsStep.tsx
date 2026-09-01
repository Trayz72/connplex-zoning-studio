import React, { useEffect, useState } from 'react';
import { Requirements, FranchiseTier } from '../../types/live';
import { getFranchiseTiers } from '../../services/zoningEngineApi';

interface RequirementsStepProps {
  initial: Requirements | null;
  /** Raw intake text, e.g. "10ft", "3.5m", "10'-0\"" — parsed as a starting
   * suggestion only; the architect confirms/edits the real number below. */
  clearHeightHint?: string | null;
  /** The confirmed boundary, for the entry-point picker below — real
   * geometry, not a placeholder shape. */
  boundaryPointsFt?: number[][] | null;
  onSubmit: (req: Requirements) => void;
}

/** Click-to-mark the main entrance on the real confirmed boundary outline.
 * Nothing in CAD extraction detects doors, so this is the one honest way to
 * get this data point: ask the person who actually knows where the
 * entrance is, rather than guess (e.g. "assume it's the boundary's
 * longest edge" or some other plausible-sounding but unverified rule the
 * project's own anti-hallucination principle rules out). */
const EntryPointPicker: React.FC<{
  boundaryPointsFt: number[][];
  value: [number, number] | null;
  onChange: (pt: [number, number] | null) => void;
}> = ({ boundaryPointsFt, value, onChange }) => {
  const xs = boundaryPointsFt.map(p => p[0]);
  const ys = boundaryPointsFt.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = maxX - minX || 1, h = maxY - minY || 1;
  const pad = Math.max(w, h) * 0.06;
  const viewBox = `${minX - pad} ${minY - pad} ${w + pad * 2} ${h + pad * 2}`;

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const local = pt.matrixTransform(ctm.inverse());
    onChange([Math.round(local.x * 10) / 10, Math.round(local.y * 10) / 10]);
  };

  return (
    <div>
      <svg
        viewBox={viewBox}
        style={{ width: '100%', height: '220px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', cursor: 'crosshair' }}
        onClick={handleClick}
      >
        <polygon
          points={boundaryPointsFt.map(p => p.join(',')).join(' ')}
          fill="var(--bg-secondary)" stroke="var(--border-strong)" strokeWidth={w * 0.004}
        />
        {value && (
          <circle cx={value[0]} cy={value[1]} r={w * 0.018} fill="var(--brand-strong)" stroke="var(--bg-primary)" strokeWidth={w * 0.003} />
        )}
      </svg>
      <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px', display: 'flex', justifyContent: 'space-between' }}>
        <span>{value ? `Marked at (${value[0]}, ${value[1]}) ft — click again to move it` : 'Click the floor plate to mark the main entrance'}</span>
        {value && <a href="#" onClick={(e) => { e.preventDefault(); onChange(null); }}>Clear</a>}
      </div>
    </div>
  );
};

/** Best-effort parse of a free-text clear-height field into feet. Never
 * silently trusted — always shown as an editable, confirmable number, not
 * applied straight to a feasibility rule. Returns null if it can't make sense
 * of the text rather than guessing a wrong unit. */
function parseClearHeightToFeet(text: string | null | undefined): number | null {
  if (!text) return null;
  const s = text.trim().toLowerCase();

  // feet'-inches" notation (e.g. 10'-0", 10' 6", 10'6) — the SOP's own stated
  // convention ("ALL DIMENSIONS ARE IN FEET-INCH") and the most likely real
  // input, so it's matched explicitly rather than falling through to the
  // generic digit-strip path below, which would misread the apostrophe/quote
  // punctuation as part of the number (verified: that bug produced 8.33 for
  // "10'-0\"" instead of the correct 10).
  const feetInches = s.match(/^(\d+(?:\.\d+)?)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*"?$/);
  if (feetInches) {
    const feet = parseFloat(feetInches[1]);
    const inches = feetInches[2] ? parseFloat(feetInches[2]) : 0;
    return Math.round((feet + inches / 12) * 100) / 100;
  }

  const num = parseFloat(s.replace(/[^\d.]/g, ''));
  if (isNaN(num)) return null;
  if (s.includes('m') && !s.includes('mm') && !s.includes('ft') && !s.includes("'")) return Math.round(num * 3.28084 * 100) / 100;
  if (s.includes('mm')) return Math.round(num * 0.00328084 * 100) / 100;
  if (s.includes('in') || s.includes('"')) return Math.round((num / 12) * 100) / 100;
  return num; // ft, ', or a bare number — feet is the common default in these documents
}

export const RequirementsStep: React.FC<RequirementsStepProps> = ({ initial, clearHeightHint, boundaryPointsFt, onSubmit }) => {
  const [req, setReq] = useState<Requirements>(initial || {
    property_type: 'EXISTING_BUILDING', max_auditoriums: 4, franchise_tier_id: null,
    support_zone_area_overrides_sqft: {}, clear_height_ft: parseClearHeightToFeet(clearHeightHint),
    entry_point_ft: null
  });
  // Real registry data, not hardcoded text — the tier dropdown previously had
  // static area/screen ranges typed directly into the JSX that had drifted
  // out of sync with rules_registry_v1.json (Express showed as 2,500-7,000
  // sqft; the registry actually says 5,000-7,000).
  const [tiers, setTiers] = useState<FranchiseTier[]>([]);
  useEffect(() => {
    getFranchiseTiers().then(setTiers).catch(() => {});
  }, []);

  return (
    <div style={{ maxWidth: '560px', margin: '3rem auto', padding: '0 1rem' }}>
      <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>Zoning Requirements</h2>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
        These drive the auto-layout generator and which viability rules apply — nothing here is hardcoded in the
        engine, it's all read from the versioned rules registry.
      </p>

      <div className="form-group" style={{ marginBottom: '1rem' }}>
        <label>Property Type *</label>
        <select className="form-control" value={req.property_type} onChange={(e) => setReq({ ...req, property_type: e.target.value as any })}>
          <option value="EXISTING_BUILDING">Existing Building / Bare Shell</option>
          <option value="OPEN_LAND">Open Land (standalone)</option>
        </select>
      </div>

      <div className="form-group" style={{ marginBottom: '1rem' }}>
        <label>Maximum Auditoriums to Attempt</label>
        <input
          type="number" min={1} max={6} className="form-control" value={req.max_auditoriums}
          onChange={(e) => setReq({ ...req, max_auditoriums: parseInt(e.target.value, 10) || 1 })}
        />
        <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
          Phase-1 product scope supports 1–4 auditoriums per SOP; the generator will place up to this many if the
          floor plate has room, and stop early (with a note) if it doesn't.
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: '1rem' }}>
        <label>Clear Height (ft) — feeds the 10 ft minimum viability check</label>
        <input
          type="number" step={0.1} min={0} className="form-control"
          value={req.clear_height_ft ?? ''}
          onChange={(e) => setReq({ ...req, clear_height_ft: e.target.value === '' ? null : parseFloat(e.target.value) })}
          placeholder="e.g. 10"
        />
        <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
          {clearHeightHint
            ? `Auto-suggested from intake ("${clearHeightHint}") — confirm or correct it; this number, not the free-text intake field, drives the feasibility check.`
            : 'Not captured at intake — enter it directly, or leave blank to keep the clear-height rule unevaluable.'}
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: '1.5rem' }}>
        <label>Franchise Tier (optional — sets the foyer:screen ratio target)</label>
        <select className="form-control" value={req.franchise_tier_id || ''} onChange={(e) => setReq({ ...req, franchise_tier_id: e.target.value || null })}>
          <option value="">None / not yet decided</option>
          {tiers.map(t => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.area_min_sqft.toLocaleString()}–{t.area_max_sqft.toLocaleString()} sqft, {t.min_screens}–{t.max_screens} screens)
            </option>
          ))}
        </select>
      </div>

      {boundaryPointsFt && boundaryPointsFt.length >= 3 && (
        <div className="form-group" style={{ marginBottom: '1.5rem' }}>
          <label>Main Entrance (optional — enables entry-facing placement of Foyer/F&amp;B/Washrooms)</label>
          <EntryPointPicker
            boundaryPointsFt={boundaryPointsFt}
            value={req.entry_point_ft}
            onChange={(pt) => setReq({ ...req, entry_point_ft: pt })}
          />
          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
            Nothing in the uploaded CAD file identifies doors, so this isn't detected automatically. Leave unmarked
            to skip the SOP's entry-sightline placement rules (F&amp;B visible from entry, washrooms hidden from foyer
            sightline) rather than guess at a location.
          </div>
        </div>
      )}

      <button className="btn btn-primary" style={{ width: '100%', padding: '0.6rem' }} onClick={() => onSubmit(req)}>
        Save Requirements &amp; Continue
      </button>
    </div>
  );
};
