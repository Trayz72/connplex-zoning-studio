import React, { useEffect, useState } from 'react';
import { Requirements, FranchiseTier } from '../../types/live';
import { getFranchiseTiers } from '../../services/zoningEngineApi';
import { EntryExitPicker } from './EntryExitPicker';

interface RequirementsStepProps {
  initial: Requirements | null;
  /** Raw intake text, e.g. "10ft", "3.5m", "10'-0\"" — parsed as a starting
   * suggestion only; the architect confirms/edits the real number below. */
  clearHeightHint?: string | null;
  /** The confirmed boundary, for the entry-point picker below — real
   * geometry, not a placeholder shape. */
  boundaryPointsFt?: number[][] | null;
  /** Marked in BoundaryStudio's entry/exit sub-step, right after the
   * boundary was chosen — used only to seed this step's local state when
   * `initial` itself is null (a brand-new Requirements object); once
   * `initial` exists (e.g. returning to this step after already saving
   * once), its own entry_point_ft/exit_points_ft take precedence. */
  initialEntryPointFt?: [number, number] | null;
  initialExitPointsFt?: [number, number][] | null;
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

export const RequirementsStep: React.FC<RequirementsStepProps> = ({
  initial, clearHeightHint, boundaryPointsFt, initialEntryPointFt, initialExitPointsFt, onSubmit
}) => {
  const [req, setReq] = useState<Requirements>(initial || {
    property_type: 'EXISTING_BUILDING', max_auditoriums: 4, franchise_tier_id: null,
    support_zone_area_overrides_sqft: {}, clear_height_ft: parseClearHeightToFeet(clearHeightHint),
    entry_point_ft: initialEntryPointFt ?? null, exit_points_ft: initialExitPointsFt ?? null,
    screen_width_ft: null
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
        These drive the auto-layout generator and which viability rules apply.
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
          The generator places up to this many, stopping early if the floor plate runs out of room.
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: '1rem' }}>
        <label>Clear Height (ft)</label>
        <input
          type="number" step={0.1} min={0} className="form-control"
          value={req.clear_height_ft ?? ''}
          onChange={(e) => setReq({ ...req, clear_height_ft: e.target.value === '' ? null : parseFloat(e.target.value) })}
          placeholder="e.g. 10"
        />
        <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
          {clearHeightHint
            ? `Auto-suggested from intake ("${clearHeightHint}") — confirm or correct it.`
            : 'Not captured at intake — enter it, or leave blank.'}
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: '1rem' }}>
        <label>Screen Width (ft)</label>
        <input
          type="number" step={0.5} min={0} className="form-control"
          value={req.screen_width_ft ?? ''}
          onChange={(e) => setReq({ ...req, screen_width_ft: e.target.value === '' ? null : parseFloat(e.target.value) })}
          placeholder="e.g. 30"
        />
        <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
          Unlocks the SOP's first-row legibility check (first-row distance must be at least the screen width) — leave
          blank to skip it.
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
          <label>Entrance &amp; Exits (optional)</label>
          <EntryExitPicker
            boundaryPointsFt={boundaryPointsFt}
            entryValue={req.entry_point_ft}
            onEntryChange={(pt) => setReq({ ...req, entry_point_ft: pt })}
            exitValues={req.exit_points_ft || []}
            onExitChange={(pts) => setReq({ ...req, exit_points_ft: pts.length ? pts : null })}
            height={220}
          />
          <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
            Usually already marked in "Select Boundary" — adjust here if needed. Leave unmarked to skip entry-aware placement.
          </div>
        </div>
      )}

      <button className="btn btn-primary" style={{ width: '100%', padding: '0.6rem' }} onClick={() => onSubmit(req)}>
        Save Requirements &amp; Continue
      </button>
    </div>
  );
};
