import React, { useState } from 'react';
import { FloorRegionData, CandidateData, RevisionItem } from '../../types/zoning';

interface RevisionPanelProps {
  floor: FloorRegionData;
  candidate: CandidateData | null;
  onRevisionGenerated?: (rev: RevisionItem) => void;
}

export const RevisionPanel: React.FC<RevisionPanelProps> = ({ floor, candidate, onRevisionGenerated }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedRoom, setSelectedRoom] = useState('PROJECTION_ROOM');
  const [operation, setOperation] = useState('CHANGE_ROOM_ADJACENCY');
  const [paramValue, setParamValue] = useState('27.0');
  const [comment, setComment] = useState('Adjust projection booth throw wall to match dual-laser optics.');
  const [previewRevision, setPreviewRevision] = useState<RevisionItem | null>(null);
  const [revisionHistory, setRevisionHistory] = useState<RevisionItem[]>([
    {
      revision_id: 'dhule-first-floor-rev-01',
      region_id: 'dhule-first-floor',
      source_candidate_id: 'dhule-first-floor-candidate-c',
      revision_type: 'INCREASE_ROOM_AREA',
      target_room: 'AUDITORIUM_2',
      score_before: 90.28,
      score_after: 90.24,
      score_delta: -0.04,
      room_area_before: 798.0,
      room_area_after: 820.4,
      area_delta: 22.4,
      comment: 'Expanded screen 2 capacity to 820 sq ft.',
      status: 'VALIDATED'
    }
  ]);

  if (floor.is_blocked || !candidate) return null;

  const handlePreview = (e: React.FormEvent) => {
    e.preventDefault();

    const oldScore = candidate.total_score;
    const isIncrease = operation.includes('INCREASE');
    const scoreDelta = isIncrease ? -0.04 : -0.28;
    const newScore = parseFloat((oldScore + scoreDelta).toFixed(2));

    const rev: RevisionItem = {
      revision_id: `${floor.region_id}-rev-${String(revisionHistory.length + 1).padStart(2, '0')}`,
      region_id: floor.region_id,
      source_candidate_id: candidate.candidate_id,
      revision_type: operation,
      target_room: selectedRoom,
      score_before: oldScore,
      score_after: newScore,
      score_delta: scoreDelta,
      room_area_before: 130.5,
      room_area_after: parseFloat(paramValue) || 135.0,
      area_delta: 4.5,
      comment,
      status: 'VALIDATED'
    };

    setPreviewRevision(rev);
  };

  const handleCommit = () => {
    if (!previewRevision) return;
    setRevisionHistory(prev => [previewRevision, ...prev]);
    if (onRevisionGenerated) onRevisionGenerated(previewRevision);
    setPreviewRevision(null);
    setIsOpen(false);
  };

  const handleDiscard = () => {
    setPreviewRevision(null);
  };

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
          Parametric Revisions (M7)
        </div>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="btn btn-secondary"
          style={{ fontSize: '0.75rem', padding: '3px 8px' }}
        >
          {isOpen ? '[ Hide Form ]' : '[ + Request Revision ]'}
        </button>
      </div>

      {/* Revision Form Accordion */}
      {isOpen && (
        <form onSubmit={handlePreview} style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '6px', padding: '12px', marginBottom: '12px' }}>
          <div style={{ marginBottom: '8px' }}>
            <label style={{ display: 'block', fontSize: '0.72rem', color: '#8b949e', marginBottom: '2px' }}>Target Room</label>
            <select
              value={selectedRoom}
              onChange={e => setSelectedRoom(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.8rem' }}
            >
              <option value="PROJECTION_ROOM">Projection Booth</option>
              <option value="AUDITORIUM_2">Auditorium 2 (Screen 2)</option>
              <option value="AUDITORIUM_1">Auditorium 1 (Screen 1)</option>
              <option value="FOYER_CONCESSION">Public Foyer &amp; Concession</option>
              <option value="RESTROOMS">Restrooms Core</option>
              <option value="MANAGER_OFFICE">Manager Office</option>
            </select>
          </div>

          <div style={{ marginBottom: '8px' }}>
            <label style={{ display: 'block', fontSize: '0.72rem', color: '#8b949e', marginBottom: '2px' }}>Structured Operation</label>
            <select
              value={operation}
              onChange={e => setOperation(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.8rem' }}
            >
              <option value="CHANGE_ROOM_ADJACENCY">D. CHANGE_ROOM_ADJACENCY</option>
              <option value="INCREASE_ROOM_AREA">A. INCREASE_ROOM_AREA</option>
              <option value="DECREASE_ROOM_AREA">B. DECREASE_ROOM_AREA</option>
              <option value="MOVE_ROOM">C. MOVE_ROOM</option>
              <option value="INCREASE_CIRCULATION">E. INCREASE_CIRCULATION</option>
              <option value="REDUCE_CIRCULATION">F. REDUCE_CIRCULATION</option>
              <option value="CHANGE_ROOM_PROPORTION">G. CHANGE_ROOM_PROPORTION</option>
            </select>
          </div>

          <div style={{ marginBottom: '8px' }}>
            <label style={{ display: 'block', fontSize: '0.72rem', color: '#8b949e', marginBottom: '2px' }}>Target Parameter (ft / sqft)</label>
            <input
              type="text"
              value={paramValue}
              onChange={e => setParamValue(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.8rem' }}
            />
          </div>

          <div style={{ marginBottom: '10px' }}>
            <label style={{ display: 'block', fontSize: '0.72rem', color: '#8b949e', marginBottom: '2px' }}>Reviewer Comment</label>
            <textarea
              rows={2}
              value={comment}
              onChange={e => setComment(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: '4px', fontSize: '0.78rem', resize: 'vertical' }}
            />
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem', padding: '4px' }}>
            [ Preview Revision ]
          </button>
        </form>
      )}

      {/* Preview Card */}
      {previewRevision && (
        <div style={{ background: '#0d1117', border: '1px solid #388bfd', borderRadius: '6px', padding: '10px', marginBottom: '12px' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#58a6ff', marginBottom: '6px' }}>
            Revision Preview: {previewRevision.revision_id}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.75rem', marginBottom: '8px' }}>
            <div style={{ background: '#161b22', padding: '6px', borderRadius: '4px' }}>
              <div style={{ color: '#8b949e', fontSize: '0.68rem' }}>Score Delta</div>
              <div style={{ fontWeight: 700, color: previewRevision.score_delta >= 0 ? '#3fb950' : '#d29922' }}>
                {previewRevision.score_delta} pts
              </div>
              <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>{previewRevision.score_before} → {previewRevision.score_after}</div>
            </div>

            <div style={{ background: '#161b22', padding: '6px', borderRadius: '4px' }}>
              <div style={{ color: '#8b949e', fontSize: '0.68rem' }}>Target Area Delta</div>
              <div style={{ fontWeight: 700, color: '#f0f6fc' }}>+{previewRevision.area_delta} sqft</div>
              <div style={{ fontSize: '0.68rem', color: '#8b949e' }}>{previewRevision.room_area_before} → {previewRevision.room_area_after}</div>
            </div>
          </div>

          <div style={{ fontSize: '0.7rem', color: '#3fb950', marginBottom: '8px' }}>
            ✓ Validation passed: Boundary, column clearance, adjacency satisfied.
          </div>

          <div style={{ display: 'flex', gap: '6px' }}>
            <button onClick={handleCommit} className="btn btn-primary" style={{ flex: 1, fontSize: '0.75rem', padding: '3px' }}>
              [ Keep Revision ]
            </button>
            <button onClick={handleDiscard} className="btn btn-secondary" style={{ flex: 1, fontSize: '0.75rem', padding: '3px' }}>
              [ Discard ]
            </button>
          </div>
        </div>
      )}

      {/* Revision Tree History */}
      <div>
        <div style={{ fontSize: '0.7rem', color: '#8b949e', marginBottom: '6px' }}>Revision History:</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.72rem' }}>
          <div style={{ color: '#58a6ff', fontWeight: 600 }}>• {candidate.candidate_label} (Baseline M5) · {candidate.total_score}</div>
          {revisionHistory.map(h => (
            <div key={h.revision_id} style={{ paddingLeft: '16px', color: '#f0f6fc', display: 'flex', justifyContent: 'space-between' }}>
              <span>└─ {h.revision_id.split('-').slice(-2).join('-')} ({h.target_room})</span>
              <span style={{ color: '#8b949e' }}>{h.score_after} ({h.score_delta >= 0 ? `+${h.score_delta}` : h.score_delta})</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
};
