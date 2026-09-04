import React, { useEffect, useState } from 'react';
import { exportPdf, exportCad, getExportHistory, ExportHistoryEntry } from '../../services/zoningEngineApi';
import { DownloadIcon } from '../Icons';

interface ExportPanelProps {
  projectId: string;
  projectMeta: Record<string, any>;
}

const FORMAT_LABEL: Record<string, string> = { pdf: 'PDF', dxf: 'DXF', dwg: 'DWG' };
// Both are real, separately-delivered sheet types Connplex actually produces
// per project (confirmed against real client reference PDFs) — same floor
// plan and Area & Seat Chart, but "Net Usage Area" calls out the total net
// usable area directly on the drawing instead of the room-by-room breakdown
// emphasis. Previously only "Zoning Layout" was reachable from this panel
// even though the backend already supported passing either.
const SHEET_TYPES = ['Zoning Layout', 'Net Usage Area'];

export const ExportPanel: React.FC<ExportPanelProps> = ({ projectId, projectMeta }) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remarks, setRemarks] = useState('');
  const [sheetType, setSheetType] = useState(SHEET_TYPES[0]);
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
    <div className="panel" style={{ padding: '14px 16px', marginBottom: '16px' }}>
      <div className="panel-label" style={{ marginBottom: '8px' }}>Export</div>
      {error && <div className="alert-box alert-error" style={{ marginBottom: '8px', fontSize: '0.75rem' }}>{error}</div>}

      <label style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '3px' }}>
        Sheet type (PDF only)
      </label>
      <select
        value={sheetType}
        onChange={(e) => setSheetType(e.target.value)}
        className="form-control"
        style={{ marginBottom: '8px', padding: '5px 8px', fontSize: '0.75rem' }}
      >
        {SHEET_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
      </select>

      <label style={{ display: 'block', fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '3px' }}>
        Remarks for this revision (optional)
      </label>
      <input
        type="text"
        value={remarks}
        onChange={(e) => setRemarks(e.target.value)}
        placeholder="e.g. Revised after client walkthrough"
        className="form-control"
        style={{ marginBottom: '8px', padding: '5px 8px', fontSize: '0.75rem' }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem', justifyContent: 'flex-start' }} disabled={!!busy}
          onClick={() => run('pdf', () => exportPdf(projectId, metaWithRemarks, sheetType))}>
          <DownloadIcon size={14} /> {busy === 'pdf' ? 'Generating PDF…' : `Export PDF (${sheetType})`}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem', justifyContent: 'flex-start' }} disabled={!!busy}
          onClick={() => run('dxf', () => exportCad(projectId, metaWithRemarks, 'dxf'))}>
          <DownloadIcon size={14} /> {busy === 'dxf' ? 'Generating DXF…' : 'Export DXF (editable)'}
        </button>
        <button className="btn btn-secondary" style={{ fontSize: '0.78rem', justifyContent: 'flex-start' }} disabled={!!busy}
          onClick={() => run('dwg', () => exportCad(projectId, metaWithRemarks, 'dwg'))}>
          <DownloadIcon size={14} /> {busy === 'dwg' ? 'Converting to DWG…' : 'Export DWG (AutoCAD)'}
        </button>
      </div>
      <div style={{ fontSize: '0.62rem', color: 'var(--text-tertiary)', marginTop: '8px', lineHeight: 1.4 }}>
        Every export bumps the revision (R0, R1, R2…) and uses a generic sheet template.
      </div>

      {history.length > 0 && (
        <div style={{ marginTop: '14px', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
          <div className="panel-label" style={{ marginBottom: '6px' }}>
            Export History ({history.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
            {history.map((h, i) => (
              <div key={i} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '6px 8px', fontSize: '0.68rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                  <span className="font-mono" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{h.revision}</span>
                  <span style={{ color: 'var(--text-tertiary)' }}>{new Date(h.generated_at).toLocaleString()}</span>
                </div>
                <div style={{ color: 'var(--text-primary)' }}>
                  {h.sheet_type} — <span style={{ textTransform: 'uppercase' }}>{FORMAT_LABEL[h.format] || h.format}</span>
                </div>
                <div style={{ color: 'var(--text-tertiary)', marginTop: '2px' }}>
                  Drawn by: {h.drawn_by} · Checked by: {h.checked_by}
                </div>
                {h.remarks && <div style={{ color: 'var(--warning)', marginTop: '2px', fontStyle: 'italic' }}>"{h.remarks}"</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
