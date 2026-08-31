import React, { useEffect, useState } from 'react';
import { exportPdf, exportCad, getExportHistory, ExportHistoryEntry } from '../../services/zoningEngineApi';

interface ExportPanelProps {
  projectId: string;
  projectMeta: Record<string, any>;
}

const FORMAT_LABEL: Record<string, string> = { pdf: 'PDF', dxf: 'DXF', dwg: 'DWG' };

export const ExportPanel: React.FC<ExportPanelProps> = ({ projectId, projectMeta }) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remarks, setRemarks] = useState('');
  const [history, setHistory] = useState<ExportHistoryEntry[]>([]);

  const loadHistory = () => {
    getExportHistory(projectId).then(setHistory).catch(() => {});
  };

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      loadHistory();
    } catch (e: any) {
      setError(e.message || 'Export failed.');
    } finally {
      setBusy(null);
    }
  };

  const metaWithRemarks = { ...projectMeta, remarks };

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', marginBottom: '8px' }}>Export</div>
      {error && <div className="alert-box alert-error" style={{ marginBottom: '8px', fontSize: '0.75rem' }}>{error}</div>}

      <label style={{ display: 'block', fontSize: '0.68rem', color: '#8b949e', marginBottom: '3px' }}>
        Remarks for this revision (optional)
      </label>
      <input
        type="text"
        value={remarks}
        onChange={(e) => setRemarks(e.target.value)}
        placeholder="e.g. Revised after client walkthrough"
        style={{
          width: '100%', padding: '5px 8px', marginBottom: '8px', background: '#0d1117', border: '1px solid #30363d',
          color: '#f0f6fc', borderRadius: '4px', fontSize: '0.75rem'
        }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('pdf', () => exportPdf(projectId, metaWithRemarks))}>
          {busy === 'pdf' ? 'Generating PDF…' : '⬇ Export PDF (Zoning Report)'}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('dxf', () => exportCad(projectId, metaWithRemarks, 'dxf'))}>
          {busy === 'dxf' ? 'Generating DXF…' : '⬇ Export DXF (editable)'}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem' }} disabled={!!busy}
          onClick={() => run('dwg', () => exportCad(projectId, metaWithRemarks, 'dwg'))}>
          {busy === 'dwg' ? 'Converting to DWG…' : '⬇ Export DWG (AutoCAD)'}
        </button>
      </div>
      <div style={{ fontSize: '0.62rem', color: '#8b949e', marginTop: '8px', lineHeight: 1.4 }}>
        Every export bumps the revision (R0 → R1 → …). PDF/DXF reproduce the required content (title block, floor
        plan, Area &amp; Seat Chart, legend, revisions) using a generic template — not a byte-for-byte copy of
        Connplex's proprietary sheet artwork.
      </div>

      {history.length > 0 && (
        <div style={{ marginTop: '14px', borderTop: '1px solid #21262d', paddingTop: '10px' }}>
          <div style={{ fontSize: '0.68rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', marginBottom: '6px' }}>
            Export History ({history.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
            {history.map((h, i) => (
              <div key={i} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: '5px', padding: '6px 8px', fontSize: '0.68rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                  <span style={{ color: '#58a6ff', fontWeight: 700 }}>{h.revision}</span>
                  <span style={{ color: '#8b949e' }}>{new Date(h.generated_at).toLocaleString()}</span>
                </div>
                <div style={{ color: '#e6edf3' }}>
                  {h.sheet_type} — <span style={{ textTransform: 'uppercase' }}>{FORMAT_LABEL[h.format] || h.format}</span>
                </div>
                <div style={{ color: '#8b949e', marginTop: '2px' }}>
                  Drawn by: {h.drawn_by} · Checked by: {h.checked_by}
                </div>
                {h.remarks && <div style={{ color: '#d29922', marginTop: '2px', fontStyle: 'italic' }}>"{h.remarks}"</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
