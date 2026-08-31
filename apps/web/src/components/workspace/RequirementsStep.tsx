import React, { useState } from 'react';
import { Requirements } from '../../types/live';

interface RequirementsStepProps {
  initial: Requirements | null;
  /** Raw intake text, e.g. "10ft", "3.5m", "10'-0\"" — parsed as a starting
   * suggestion only; the architect confirms/edits the real number below. */
  clearHeightHint?: string | null;
  onSubmit: (req: Requirements) => void;
}

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

export const RequirementsStep: React.FC<RequirementsStepProps> = ({ initial, clearHeightHint, onSubmit }) => {
  const [req, setReq] = useState<Requirements>(initial || {
    property_type: 'EXISTING_BUILDING', max_auditoriums: 4, franchise_tier_id: null,
    support_zone_area_overrides_sqft: {}, clear_height_ft: parseClearHeightToFeet(clearHeightHint)
  });

  return (
    <div style={{ maxWidth: '560px', margin: '3rem auto', padding: '0 1rem' }}>
      <h2 style={{ fontSize: '1.3rem', fontWeight: 700, color: '#f0f6fc', marginBottom: '0.5rem' }}>Zoning Requirements</h2>
      <p style={{ fontSize: '0.85rem', color: '#8b949e', marginBottom: '1.5rem' }}>
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
        <div style={{ fontSize: '0.72rem', color: '#8b949e', marginTop: '4px' }}>
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
        <div style={{ fontSize: '0.72rem', color: '#8b949e', marginTop: '4px' }}>
          {clearHeightHint
            ? `Auto-suggested from intake ("${clearHeightHint}") — confirm or correct it; this number, not the free-text intake field, drives the feasibility check.`
            : 'Not captured at intake — enter it directly, or leave blank to keep the clear-height rule unevaluable.'}
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: '1.5rem' }}>
        <label>Franchise Tier (optional — sets the foyer:screen ratio target)</label>
        <select className="form-control" value={req.franchise_tier_id || ''} onChange={(e) => setReq({ ...req, franchise_tier_id: e.target.value || null })}>
          <option value="">None / not yet decided</option>
          <option value="EXPRESS">Express (2,500–7,000 sqft, 2–4 screens)</option>
          <option value="SIGNATURE">Signature (6,000–8,000 sqft, 3–4 screens)</option>
          <option value="LUXURIANCE">Luxuriance (8,000–10,000 sqft, 3–6 screens)</option>
        </select>
      </div>

      <button className="btn btn-primary" style={{ width: '100%', padding: '0.6rem' }} onClick={() => onSubmit(req)}>
        Save Requirements &amp; Continue →
      </button>
    </div>
  );
};
