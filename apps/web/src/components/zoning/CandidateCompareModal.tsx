import React from 'react';
import { CandidateData } from '../../types/zoning';

interface CandidateCompareModalProps {
  isOpen: boolean;
  onClose: () => void;
  candidates: CandidateData[];
  selectedCandidateId: string;
  onSelectCandidate: (candidate: CandidateData) => void;
}

export const CandidateCompareModal: React.FC<CandidateCompareModalProps> = ({
  isOpen,
  onClose,
  candidates,
  selectedCandidateId,
  onSelectCandidate
}) => {
  if (!isOpen) return null;

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(13,17,23,0.85)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000, padding: '1rem' }}>
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '10px', maxWidth: '1150px', width: '100%', maxHeight: '90vh', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 40px rgba(0,0,0,0.5)' }}>
        
        {/* Modal Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #30363d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f0f6fc' }}>
              Multi-Candidate Optimization Comparison
            </h3>
            <p style={{ fontSize: '0.8rem', color: '#8b949e' }}>
              Compare all {candidates.length} deterministic layout candidates, ranked by seat-aware objective score (M8).
            </p>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#8b949e', fontSize: '1.4rem', cursor: 'pointer' }}>×</button>
        </div>

        {/* 4 Candidate Cards Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {candidates.map((cand) => {
            const isSelected = cand.candidate_id === selectedCandidateId;
            return (
              <div
                key={cand.candidate_id}
                style={{
                  background: isSelected ? 'rgba(56, 139, 253, 0.08)' : '#0d1117',
                  border: isSelected ? '2px solid #388bfd' : '1px solid #30363d',
                  borderRadius: '8px',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between'
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                    <div>
                      <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#f0f6fc' }}>
                        {cand.candidate_label}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: '#8b949e' }}>
                        {cand.strategy}
                      </div>
                    </div>
                    <div style={{ fontSize: '1.15rem', fontWeight: 800, color: cand.is_preferred ? '#3fb950' : '#58a6ff' }}>
                      {cand.total_score.toFixed(1)}
                    </div>
                  </div>

                  {cand.is_preferred && (
                    <div style={{ background: 'rgba(35, 134, 54, 0.2)', border: '1px solid #238636', color: '#3fb950', fontSize: '0.65rem', fontWeight: 700, padding: '2px 4px', borderRadius: '3px', marginBottom: '8px', textAlign: 'center' }}>
                      ★ PREFERRED CANDIDATE
                    </div>
                  )}

                  {/* SVG Thumbnail Preview */}
                  <div style={{ background: '#0a0d12', border: '1px solid #21262d', borderRadius: '6px', overflow: 'hidden', marginBottom: '10px', height: '180px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <img
                      src={cand.svg_url}
                      alt={cand.candidate_label}
                      style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    />
                  </div>

                  {/* Detailed Metric List */}
                  <div style={{ fontSize: '0.72rem', display: 'flex', flexDirection: 'column', gap: '3px', color: '#8b949e', marginBottom: '10px' }}>
                    {cand.total_seats !== undefined && (
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Total Seats:</span>
                        <strong style={{ color: '#58a6ff' }}>{cand.total_seats} ({cand.seats_per_screen}/screen)</strong>
                      </div>
                    )}
                    {cand.score_breakdown.seats !== undefined && (
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Seats Score (30):</span>
                        <strong style={{ color: '#58a6ff' }}>{cand.score_breakdown.seats}</strong>
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Area Efficiency ({cand.score_breakdown.seats !== undefined ? 20 : 25}):</span>
                      <strong style={{ color: '#f0f6fc' }}>{cand.score_breakdown.area_efficiency}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Circulation ({cand.score_breakdown.seats !== undefined ? 15 : 20}):</span>
                      <strong style={{ color: '#f0f6fc' }}>{cand.score_breakdown.circulation_quality}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Adjacency ({cand.score_breakdown.seats !== undefined ? 15 : 20}):</span>
                      <strong style={{ color: cand.is_preferred ? '#3fb950' : '#f0f6fc' }}>{cand.score_breakdown.adjacency_satisfaction}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Proportions ({cand.score_breakdown.seats !== undefined ? 8 : 15}):</span>
                      <strong style={{ color: '#f0f6fc' }}>{cand.score_breakdown.room_proportions}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Clearance ({cand.score_breakdown.seats !== undefined ? 7 : 10}):</span>
                      <strong style={{ color: '#f0f6fc' }}>{cand.score_breakdown.structural_clearance}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Simplicity ({cand.score_breakdown.seats !== undefined ? 5 : 10}):</span>
                      <strong style={{ color: '#f0f6fc' }}>{cand.score_breakdown.layout_simplicity}</strong>
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => { onSelectCandidate(cand); onClose(); }}
                  className={isSelected ? 'btn btn-primary' : 'btn btn-secondary'}
                  style={{ width: '100%', fontSize: '0.8rem', padding: '5px' }}
                >
                  {isSelected ? '✓ Currently Active' : 'Select Candidate'}
                </button>
              </div>
            );
          })}
        </div>

        {/* Modal Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid #30363d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: '0.72rem', color: '#8b949e' }}>
            Candidate scores reflect seat-aware multi-criteria optimization weights (M8): seat count is now the largest single scored factor.
          </div>
          <button onClick={onClose} className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '4px 12px' }}>
            Close
          </button>
        </div>

      </div>
    </div>
  );
};
