import React, { useState } from 'react';
import { FloorRegionData, CandidateData, HumanReviewDecision } from '../../types/zoning';

interface DecisionPanelProps {
  floor: FloorRegionData;
  candidate: CandidateData | null;
  onRecordDecision: (decision: HumanReviewDecision) => void;
}

export const DecisionPanel: React.FC<DecisionPanelProps> = ({ floor, candidate, onRecordDecision }) => {
  const [reviewerName, setReviewerName] = useState('');
  const [reviewerRole, setReviewerRole] = useState('Design Reviewer');
  const [comment, setComment] = useState('');
  const [recordedDecision, setRecordedDecision] = useState<HumanReviewDecision | null>(null);

  if (floor.is_blocked || !candidate) return null;

  const handleSubmit = (decisionType: HumanReviewDecision['decision']) => {
    if (!reviewerName.trim()) {
      alert('Please provide your name as the reviewer before recording a decision.');
      return;
    }

    const dec: HumanReviewDecision = {
      region_id: floor.region_id,
      candidate_id: candidate.candidate_id,
      reviewer_name: reviewerName.trim(),
      reviewer_role: reviewerRole,
      decision: decisionType,
      comment: comment.trim() || 'Reviewed computational candidate.',
      timestamp: new Date().toISOString()
    };

    setRecordedDecision(dec);
    onRecordDecision(dec);
  };

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px' }}>
      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', marginBottom: '8px' }}>
        Human Architect Review Decision (M6/M8)
      </div>

      {recordedDecision ? (
        <div style={{ background: '#0d1117', border: '1px solid #238636', borderRadius: '6px', padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#3fb950' }}>
              ✓ Decision Recorded: {recordedDecision.decision}
            </span>
            <span style={{ fontSize: '0.7rem', color: '#8b949e' }}>
              {new Date(recordedDecision.timestamp).toLocaleTimeString()}
            </span>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#f0f6fc' }}>
            Reviewer: <strong>{recordedDecision.reviewer_name}</strong> ({recordedDecision.reviewer_role})
          </div>
          {recordedDecision.comment && (
            <div style={{ fontSize: '0.72rem', color: '#8b949e', marginTop: '4px', fontStyle: 'italic' }}>
              "{recordedDecision.comment}"
            </div>
          )}
          <button
            onClick={() => setRecordedDecision(null)}
            className="btn btn-secondary"
            style={{ fontSize: '0.7rem', padding: '2px 8px', marginTop: '8px' }}
          >
            Update Decision
          </button>
        </div>
      ) : (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '8px', marginBottom: '8px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.7rem', color: '#8b949e', marginBottom: '2px' }}>
                Reviewer Name *
              </label>
              <input
                type="text"
                placeholder="e.g. Tanishq S."
                value={reviewerName}
                onChange={e => setReviewerName(e.target.value)}
                style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.78rem' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.7rem', color: '#8b949e', marginBottom: '2px' }}>
                Role
              </label>
              <input
                type="text"
                value={reviewerRole}
                onChange={e => setReviewerRole(e.target.value)}
                style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.78rem' }}
              />
            </div>
          </div>

          <div style={{ marginBottom: '10px' }}>
            <label style={{ display: 'block', fontSize: '0.7rem', color: '#8b949e', marginBottom: '2px' }}>
              Review Notes / Architectural Remarks
            </label>
            <textarea
              rows={2}
              placeholder="Enter architectural rationale or site coordination remarks..."
              value={comment}
              onChange={e => setComment(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.75rem', resize: 'vertical' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '8px' }}>
            <button
              onClick={() => handleSubmit('ACCEPT')}
              className="btn btn-primary"
              style={{ fontSize: '0.75rem', padding: '5px' }}
            >
              [ ACCEPT FOR DESIGN ]
            </button>
            <button
              onClick={() => handleSubmit('REQUEST_REVISION')}
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '5px' }}
            >
              [ REQUEST REVISION ]
            </button>
            <button
              onClick={() => handleSubmit('REQUEST_FIELD_VERIFICATION')}
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '5px', color: '#d29922' }}
            >
              [ FIELD VERIFICATION ]
            </button>
            <button
              onClick={() => handleSubmit('REJECT')}
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '5px', color: '#f85149' }}
            >
              [ REJECT ]
            </button>
          </div>

          <div style={{ fontSize: '0.65rem', color: '#8b949e', lineHeight: 1.4 }}>
            <strong>Note:</strong> Acceptance certifies human review for downstream planning only. Does NOT constitute statutory architectural approval, code compliance, or structural certification.
          </div>
        </div>
      )}
    </div>
  );
};
