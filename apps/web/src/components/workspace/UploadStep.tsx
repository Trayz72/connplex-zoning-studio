import React, { useState } from 'react';
import { uploadCad, aiScanCad } from '../../services/zoningEngineApi';
import { GeometryResult } from '../../types/live';
import { UploadIcon, RefreshIcon, WarningIcon } from '../Icons';

interface UploadStepProps {
  projectId: string;
  onUploaded: (geometry: GeometryResult) => void;
}

export const UploadStep: React.FC<UploadStepProps> = ({ projectId, onUploaded }) => {
  const [dragActive, setDragActive] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [status, setStatus] = useState<'IDLE' | 'UPLOADING' | 'EXTRACTING' | 'ERROR' | 'NO_REGIONS'>('IDLE');
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [aiScanning, setAiScanning] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const process = async (file: File) => {
    const ext = file.name.toLowerCase().split('.').pop();
    if (ext !== 'dwg' && ext !== 'dxf') {
      setStatus('ERROR');
      setError('Only .dwg and .dxf files are supported.');
      return;
    }
    setFileName(file.name);
    setStatus('UPLOADING');
    setError(null);
    setAiError(null);
    setProgress(0);
    try {
      const geometry = await uploadCad(projectId, file, (pct) => {
        setProgress(pct);
        if (pct >= 100) setStatus('EXTRACTING');
      });
      if (geometry.region_count === 0) {
        // Don't auto-advance into a Geometry Review step with nothing to
        // review — offer the AI scan right here instead, since this is
        // exactly the situation it exists for.
        setStatus('NO_REGIONS');
      } else {
        onUploaded(geometry);
      }
    } catch (e: any) {
      setStatus('ERROR');
      setError(e.message || 'Upload failed.');
    }
  };

  const runAiScan = async () => {
    setAiScanning(true);
    setAiError(null);
    try {
      const geometry = await aiScanCad(projectId);
      if (geometry.region_count === 0) {
        setAiError(
          (geometry.conversion_note || 'The AI scan tried alternative layers but still found no usable floor boundary in this file.')
        );
      } else {
        onUploaded(geometry);
      }
    } catch (e: any) {
      setAiError(e.message || 'AI CAD scan failed.');
    } finally {
      setAiScanning(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false);
    if (e.dataTransfer.files?.[0]) process(e.dataTransfer.files[0]);
  };

  return (
    <div style={{ maxWidth: '620px', margin: '3rem auto', padding: '0 1rem' }}>
      <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>Upload CAD Drawing</h2>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
        Upload a .dwg or .dxf floor plate. It's parsed for real — boundary and structural obstacle detection run
        against the file you provide, not a demo dataset. You'll review and confirm what was detected next.
      </p>

      <div
        onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
        onDrop={handleDrop}
        style={{
          border: `1px dashed ${dragActive ? 'var(--text-tertiary)' : 'var(--border-color)'}`,
          borderRadius: 'var(--radius-md)', padding: '3rem 1.5rem', textAlign: 'center',
          background: dragActive ? 'var(--bg-raised)' : 'var(--bg-secondary)', transition: 'background-color 0.15s, border-color 0.15s'
        }}
      >
        {status === 'IDLE' || status === 'ERROR' ? (
          <>
            <UploadIcon size={26} className="text-tertiary" />
            <p style={{ fontSize: '0.95rem', fontWeight: 500, color: 'var(--text-primary)', margin: '0.9rem 0 1.1rem' }}>Drag &amp; drop a DWG/DXF file here</p>
            <label className="btn btn-primary" style={{ cursor: 'pointer', padding: '0.5rem 1.5rem' }}>
              Choose File
              <input type="file" accept=".dwg,.dxf" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && process(e.target.files[0])} />
            </label>
            {error && <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>{error}</div>}
          </>
        ) : status === 'NO_REGIONS' ? (
          <div>
            <WarningIcon size={22} className="text-tertiary" />
            <div style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--text-primary)', margin: '0.75rem 0 0.4rem' }}>{fileName}</div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1.1rem', maxWidth: '440px', marginLeft: 'auto', marginRight: 'auto' }}>
              The standard scan found no usable floor boundary in this file — common on real drawings where the
              wall/floor geometry is buried among dimension, hatch, or furniture layers. Try the AI scan: it looks
              at the file's actual layers and picks which one(s) are most likely the real boundary, then re-runs
              extraction against just those.
            </p>
            <button className="btn btn-primary" style={{ padding: '0.5rem 1.5rem', marginBottom: '0.75rem' }} disabled={aiScanning} onClick={runAiScan}>
              {aiScanning ? <><RefreshIcon size={14} /> Scanning with AI… (~15-30s)</> : <><RefreshIcon size={14} /> Scan with AI</>}
            </button>
            <div>
              <label className="btn btn-secondary" style={{ cursor: 'pointer', padding: '0.4rem 1.2rem', fontSize: '0.8rem' }}>
                Try a Different File
                <input type="file" accept=".dwg,.dxf" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && process(e.target.files[0])} />
              </label>
            </div>
            {aiError && <div className="alert-box alert-error" style={{ marginTop: '1rem', textAlign: 'left' }}>{aiError}</div>}
          </div>
        ) : (
          <div>
            <div style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--text-primary)', marginBottom: '1rem' }}>{fileName}</div>
            <div style={{ background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', height: '4px', overflow: 'hidden', marginBottom: '0.75rem' }}>
              <div style={{ background: 'var(--brand-strong)', height: '100%', width: `${progress}%`, transition: 'width 0.15s' }} />
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              {status === 'UPLOADING' ? `Uploading… ${progress}%` : 'Converting (if DWG) and extracting geometry…'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
