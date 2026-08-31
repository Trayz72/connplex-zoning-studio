import React from 'react';
import { CandidateData } from '../../types/zoning';

interface CandidatePanelProps {
  candidates: CandidateData[];
  selectedCandidateId: string;
  onSelectCandidate: (candidate: CandidateData) => void;
  onOpenCompare: () => void;
}

export const CandidatePanel: React.FC<CandidatePanelProps> = ({
  candidates,
  selectedCandidateId,
  onSelectCandidate,
  onOpenCompare
}) => {
  const activeCandidate = candidates.find(c => c.candidate_id === selectedCandidateId) || candidates[0];

  if (!activeCandidate) return null;

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '12px 16px', marginBottom: '16px' }}>
      
      {/* Header & Compare Button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
          Zoning Candidates ({candidates.length})
        </div>
        <button
          onClick={onOpenCompare}
          className="btn btn-secondary"
          style={{ fontSize: '0.75rem', padding: '3px 8px' }}
        >
          [ ☷ Compare Candidates ]
        </button>
      </div>

      {/* Candidate Tabs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px', marginBottom: '12px' }}>
        {candidates.map((cand) => {
          const isSelected = cand.candidate_id === selectedCandidateId;
          return (
            <button
              key={cand.candidate_id}
              onClick={() => onSelectCandidate(cand)}
              style={{
                padding: '6px 8px',
                borderRadius: '6px',
                border: isSelected ? '2px solid #388bfd' : '1px solid #30363d',
                background: isSelected ? 'rgba(56, 139, 253, 0.15)' : '#0d1117',
                color: isSelected ? '#58a6ff' : '#f0f6fc',
                textAlign: 'center',
                cursor: 'pointer',
                transition: 'all 0.15s'
              }}
            >
              <div style={{ fontSize: '0.82rem', fontWeight: 700 }}>
                {cand.candidate_label.replace('Candidate ', 'Cand ')}
              </div>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: isSelected ? '#79c0ff' : '#8b949e' }}>
                {cand.total_score.toFixed(1)}
              </div>
            </button>
          );
        })}
      </div>

      {/* Active Candidate Details Card */}
      <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '10px 12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
          <div>
            <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#f0f6fc' }}>
              {activeCandidate.candidate_label}
            </div>
            <div style={{ fontSize: '0.75rem', color: '#8b949e' }}>
              {activeCandidate.strategy}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#58a6ff' }}>
              {activeCandidate.total_score.toFixed(2)}
            </div>
            <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>/ 100 points</div>
          </div>
        </div>

        {activeCandidate.is_preferred && (
          <div style={{ display: 'inline-block', background: 'rgba(35, 134, 54, 0.2)', border: '1px solid #238636', color: '#3fb950', fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '4px', marginBottom: '8px' }}>
            ★ PREFERRED COMPUTATIONAL CANDIDATE
          </div>
        )}

        {activeCandidate.total_seats !== undefined && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '6px 8px', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.72rem', color: '#8b949e' }}>Total Seats ({activeCandidate.screen_count} screens)</span>
            <span style={{ fontSize: '0.85rem', fontWeight: 800, color: '#58a6ff' }}>
              {activeCandidate.total_seats} <span style={{ fontSize: '0.65rem', fontWeight: 500, color: '#8b949e' }}>({activeCandidate.seats_per_screen}/screen)</span>
            </span>
          </div>
        )}

        {/* Metric Bars (seat-aware weighting, M8) */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '0.72rem', color: '#8b949e', marginTop: '4px' }}>
          {activeCandidate.score_breakdown.seats !== undefined && (
            <div>Seats: <strong style={{ color: '#58a6ff' }}>{activeCandidate.score_breakdown.seats}</strong> / 30</div>
          )}
          <div>Area Eff: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.area_efficiency}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 20 : 25}</div>
          <div>Circulation: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.circulation_quality}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 15 : 20}</div>
          <div>Adjacency: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.adjacency_satisfaction}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 15 : 20}</div>
          <div>Proportions: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.room_proportions}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 8 : 15}</div>
          <div>Clearance: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.structural_clearance}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 7 : 10}</div>
          <div>Simplicity: <strong style={{ color: '#f0f6fc' }}>{activeCandidate.score_breakdown.layout_simplicity}</strong> / {activeCandidate.score_breakdown.seats !== undefined ? 5 : 10}</div>
        </div>
      </div>

    </div>
  );
};
