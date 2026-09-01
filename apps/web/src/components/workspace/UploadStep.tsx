import React, { useState } from 'react';
import { uploadCad } from '../../services/zoningEngineApi';
import { GeometryResult } from '../../types/live';
import { UploadIcon } from '../Icons';

interface UploadStepProps {
  projectId: string;
  onUploaded: (geometry: GeometryResult) => void;
}

export const UploadStep: React.FC<UploadStepProps> = ({ projectId, onUploaded }) => {
  const [dragActive, setDragActive] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [status, setStatus] = useState<'IDLE' | 'UPLOADING' | 'EXTRACTING' | 'ERROR'>('IDLE');
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

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
    setProgress(0);
    try {
      const geometry = await uploadCad(projectId, file, (pct) => {
        setProgress(pct);
        if (pct >= 100) setStatus('EXTRACTING');
      });
      onUploaded(geometry);
    } catch (e: any) {
      setStatus('ERROR');
      setError(e.message || 'Upload failed.');
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
