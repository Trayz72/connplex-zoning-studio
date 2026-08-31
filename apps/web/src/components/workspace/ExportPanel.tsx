import React, { useState } from 'react';
import { exportPdf, exportCad } from '../../services/zoningEngineApi';

interface ExportPanelProps {
  projectId: string;
  projectMeta: Record<string, any>;
}

export const ExportPanel: React.FC<ExportPanelProps> = ({ projectId, projectMeta }) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e: any) {
      setError(e.message || 'Export failed.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', marginBottom: '8px' }}>Export</div>
      {error && <div className="alert-box alert-error" style={{ marginBottom: '8px', fontSize: '0.75rem' }}>{error}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('pdf', () => exportPdf(projectId, projectMeta))}>
          {busy === 'pdf' ? 'Generating PDF…' : '⬇ Export PDF (Zoning Report)'}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('dxf', () => exportCad(projectId, projectMeta, 'dxf'))}>
          {busy === 'dxf' ? 'Generating DXF…' : '⬇ Export DXF (editable)'}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('dwg', () => exportCad(projectId, projectMeta, 'dwg'))}>
          {busy === 'dwg' ? 'Converting to DWG…' : '⬇ Export DWG (AutoCAD)'}
        </button>
      </div>
      <div style={{ fontSize: '0.62rem', color: '#8b949e', marginTop: '8px', lineHeight: 1.4 }}>
        Every export bumps the revision (R0 → R1 → …). PDF/DXF reproduce the required content (title block, floor
        plan, Area &amp; Seat Chart, legend, revisions) using a generic template — not a byte-for-byte copy of
        Connplex's proprietary sheet artwork.
      </div>
    </div>
  );
};
