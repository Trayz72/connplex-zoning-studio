import React, { useState } from 'react';
import { Requirements } from '../../types/live';

interface RequirementsStepProps {
  initial: Requirements | null;
  onSubmit: (req: Requirements) => void;
}

export const RequirementsStep: React.FC<RequirementsStepProps> = ({ initial, onSubmit }) => {
  const [req, setReq] = useState<Requirements>(initial || {
    property_type: 'EXISTING_BUILDING', max_auditoriums: 4, franchise_tier_id: null, support_zone_area_overrides_sqft: {}
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
