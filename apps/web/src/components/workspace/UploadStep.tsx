import React, { useState } from 'react';
import { uploadCad } from '../../services/zoningEngineApi';
import { GeometryResult } from '../../types/live';

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
      <h2 style={{ fontSize: '1.3rem', fontWeight: 700, color: '#f0f6fc', marginBottom: '0.5rem' }}>Upload CAD Drawing</h2>
      <p style={{ fontSize: '0.85rem', color: '#8b949e', marginBottom: '1.5rem' }}>
        Upload a .dwg or .dxf floor plate. It's parsed for real — boundary and structural obstacle detection run
        against the file you provide, not a demo dataset. You'll review and confirm what was detected next.
      </p>

      <div
        onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
        onDrop={handleDrop}
        style={{
          border: `2px dashed ${dragActive ? '#2f81f7' : '#30363d'}`,
          borderRadius: '8px', padding: '3rem 1.5rem', textAlign: 'center',
          background: dragActive ? 'rgba(47,129,247,0.08)' : '#161b22'
        }}
      >
        {status === 'IDLE' || status === 'ERROR' ? (
          <>
            <div style={{ fontSize: '2.2rem', marginBottom: '0.75rem' }}>📐</div>
            <p style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f0f6fc', marginBottom: '1rem' }}>Drag &amp; drop a DWG/DXF file here</p>
            <label className="btn btn-primary" style={{ cursor: 'pointer', padding: '0.5rem 1.5rem' }}>
              [ Choose File ]
              <input type="file" accept=".dwg,.dxf" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && process(e.target.files[0])} />
            </label>
            {error && <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>{error}</div>}
          </>
        ) : (
          <div>
            <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f0f6fc', marginBottom: '1rem' }}>{fileName}</div>
            <div style={{ background: '#0d1117', borderRadius: '6px', height: '10px', overflow: 'hidden', marginBottom: '0.75rem' }}>
              <div style={{ background: '#2f81f7', height: '100%', width: `${progress}%`, transition: 'width 0.15s' }} />
            </div>
            <div style={{ fontSize: '0.8rem', color: '#8b949e' }}>
              {status === 'UPLOADING' ? `Uploading… ${progress}%` : 'Converting (if DWG) and extracting geometry…'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
