import React, { useState } from 'react';
import { CadUploadState, ProcessingStep } from '../../types/zoning';
import { formatBytes, INITIAL_PROCESSING_STEPS } from '../../services/cadService';

interface CadUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadSuccess: (uploadState: CadUploadState) => void;
}

export const CadUploadModal: React.FC<CadUploadModalProps> = ({ isOpen, onClose, onUploadSuccess }) => {
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState<CadUploadState>({
    file: null,
    status: 'IDLE',
    currentStepIndex: 0,
    steps: INITIAL_PROCESSING_STEPS,
    errorMessage: null,
    isDemoData: false
  });

  if (!isOpen) return null;

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const processFile = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.dwg')) {
      setUploadState(prev => ({
        ...prev,
        status: 'ERROR',
        file: {
          name: file.name,
          size: file.size,
          formattedSize: formatBytes(file.size)
        },
        errorMessage: 'Invalid file format. Please upload an AutoCAD DWG (.dwg) drawing file.'
      }));
      return;
    }

    const isRefCad = file.name.toLowerCase().includes('dhule') || file.name.toLowerCase().includes('theater');

    setUploadState({
      file: {
        name: file.name,
        size: file.size,
        formattedSize: formatBytes(file.size)
      },
      status: 'UPLOADING',
      currentStepIndex: 0,
      steps: INITIAL_PROCESSING_STEPS.map((s: ProcessingStep) => ({ ...s, status: 'PENDING' as const })),
      errorMessage: null,
      isDemoData: !isRefCad
    });

    // Run progressive pipeline steps
    setTimeout(() => {
      setUploadState(prev => ({ ...prev, status: 'PROCESSING' }));
      simulateProcessing(0, isRefCad);
    }, 600);
  };

  const simulateProcessing = (stepIndex: number, isRefCad: boolean) => {
    if (stepIndex >= INITIAL_PROCESSING_STEPS.length) {
      setUploadState(prev => ({
        ...prev,
        status: 'SUCCESS',
        steps: prev.steps.map(s => ({ ...s, status: 'COMPLETE' }))
      }));
      return;
    }

    setUploadState(prev => {
      const nextSteps = [...prev.steps];
      if (stepIndex > 0) nextSteps[stepIndex - 1].status = 'COMPLETE';
      nextSteps[stepIndex].status = 'RUNNING';
      return {
        ...prev,
        currentStepIndex: stepIndex,
        steps: nextSteps
      };
    });

    setTimeout(() => {
      simulateProcessing(stepIndex + 1, isRefCad);
    }, 450);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const handleUseDemo = () => {
    const mockFile = new File(['mock content'], '1022_MARUTI_NANDAN_DHULE_ZONING.dwg', { type: 'application/octet-stream' });
    processFile(mockFile);
  };

  const handleConfirm = () => {
    onUploadSuccess(uploadState);
    onClose();
  };

  const handleReset = () => {
    setUploadState({
      file: null,
      status: 'IDLE',
      currentStepIndex: 0,
      steps: INITIAL_PROCESSING_STEPS,
      errorMessage: null,
      isDemoData: false
    });
  };

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(13,17,23,0.85)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000, padding: '1rem' }}>
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', maxWidth: '580px', width: '100%', padding: '1.75rem', boxShadow: '0 20px 40px rgba(0,0,0,0.5)' }}>
        
        {/* Modal Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#f0f6fc' }}>CAD Drawing Upload</h3>
            <p style={{ fontSize: '0.8rem', color: '#8b949e' }}>Upload an architectural DWG file for zoning extraction and multi-candidate generation.</p>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#8b949e', fontSize: '1.4rem', cursor: 'pointer' }}>×</button>
        </div>

        {/* Upload Box */}
        {uploadState.status === 'IDLE' && (
          <div>
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              style={{
                border: `2px dashed ${dragActive ? '#2f81f7' : '#30363d'}`,
                borderRadius: '8px',
                padding: '2.5rem 1.5rem',
                textAlign: 'center',
                background: dragActive ? 'rgba(47,129,247,0.08)' : '#0d1117',
                transition: 'all 0.2s',
                marginBottom: '1rem'
              }}
            >
              <div style={{ fontSize: '2.2rem', marginBottom: '0.75rem' }}>📐</div>
              <p style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f0f6fc', marginBottom: '0.25rem' }}>
                Drag &amp; drop AutoCAD drawing here
              </p>
              <p style={{ fontSize: '0.8rem', color: '#8b949e', marginBottom: '1.25rem' }}>
                Supported format: <strong>.DWG</strong>
              </p>

              <label className="btn btn-primary" style={{ cursor: 'pointer', padding: '0.45rem 1.25rem', fontSize: '0.85rem' }}>
                [ Choose DWG ]
                <input type="file" accept=".dwg" onChange={handleChange} style={{ display: 'none' }} />
              </label>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '0.5rem', borderTop: '1px solid #21262d' }}>
              <span style={{ fontSize: '0.78rem', color: '#8b949e' }}>Need reference CAD data?</span>
              <button onClick={handleUseDemo} className="btn btn-secondary" style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem' }}>
                Load Reference DWG (Dhule Complex)
              </button>
            </div>
          </div>
        )}

        {/* Processing State */}
        {(uploadState.status === 'UPLOADING' || uploadState.status === 'PROCESSING') && (
          <div>
            <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '0.8rem 1rem', marginBottom: '1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f0f6fc' }}>{uploadState.file?.name}</div>
                <div style={{ fontSize: '0.75rem', color: '#8b949e' }}>{uploadState.file?.formattedSize}</div>
              </div>
              <span style={{ fontSize: '0.75rem', color: '#2f81f7', fontWeight: 600 }}>Processing...</span>
            </div>

            <div style={{ marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#f0f6fc', marginBottom: '0.5rem' }}>Processing Pipeline:</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                {uploadState.steps.map((step) => {
                  let icon = '○';
                  let color = '#8b949e';
                  if (step.status === 'COMPLETE') {
                    icon = '✓';
                    color = '#238636';
                  } else if (step.status === 'RUNNING') {
                    icon = '⏳';
                    color = '#2f81f7';
                  }
                  return (
                    <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.82rem', color }}>
                      <span style={{ width: '16px', fontWeight: 700 }}>{icon}</span>
                      <span>{step.label}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Success State */}
        {uploadState.status === 'SUCCESS' && (
          <div>
            <div style={{ background: 'rgba(35, 134, 54, 0.15)', border: '1px solid #238636', borderRadius: '6px', padding: '0.85rem 1rem', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#3fb950' }}>✓ Processing Complete</span>
                <span style={{ fontSize: '0.75rem', color: '#8b949e' }}>{uploadState.file?.formattedSize}</span>
              </div>
              <div style={{ fontSize: '0.8rem', color: '#f0f6fc', marginTop: '0.25rem' }}>{uploadState.file?.name}</div>
            </div>

            <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '0.75rem 1rem', marginBottom: '1.25rem', fontSize: '0.8rem' }}>
              <div style={{ color: '#8b949e', marginBottom: '0.25rem' }}>Pipeline Extraction Summary:</div>
              <div style={{ color: '#f0f6fc' }}>• 8 Plan regions identified (4 zoning-ready, 4 blocked)</div>
              <div style={{ color: '#f0f6fc' }}>• 4 multi-objective layout candidates generated</div>
              <div style={{ color: '#f0f6fc' }}>• Preferred candidate: <strong>Candidate C (Adjacency-Optimized)</strong></div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
              <button onClick={handleReset} className="btn btn-secondary" style={{ fontSize: '0.85rem' }}>
                Replace / Upload Another
              </button>
              <button onClick={handleConfirm} className="btn btn-primary" style={{ fontSize: '0.85rem', padding: '0.45rem 1.5rem' }}>
                [ View Plan ]
              </button>
            </div>
          </div>
        )}

        {/* Error State */}
        {uploadState.status === 'ERROR' && (
          <div>
            <div style={{ background: 'rgba(248, 81, 73, 0.15)', border: '1px solid #f85149', borderRadius: '6px', padding: '1rem', marginBottom: '1.25rem' }}>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#f85149', marginBottom: '0.25rem' }}>✕ Upload Error</div>
              <div style={{ fontSize: '0.82rem', color: '#f0f6fc' }}>{uploadState.errorMessage}</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button onClick={handleReset} className="btn btn-secondary" style={{ fontSize: '0.85rem' }}>
                Try Again
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};
