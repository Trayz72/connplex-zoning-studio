import React, { useState } from 'react';

interface FloorData {
  region_id: string;
  name: string;
  is_blocked: boolean;
  m5_candidate_id: string | null;
  m5_score: number | null;
  computational_status: string;
  review_status: string;
  rooms: { [key: string]: { name: string; area: number; width: number; depth: number } };
  circulation_sqft: number;
}

const FLOORS: FloorData[] = [
  {
    region_id: 'dhule-first-floor',
    name: 'First Floor Plan',
    is_blocked: false,
    m5_candidate_id: 'dhule-first-floor-candidate-c',
    m5_score: 90.28,
    computational_status: 'DECISION_READY',
    review_status: 'NOT_REVIEWED',
    rooms: {
      AUDITORIUM_1: { name: 'Auditorium 1 (Screen 1)', area: 744.0, width: 31.0, depth: 24.0 },
      AUDITORIUM_2: { name: 'Auditorium 2 (Screen 2)', area: 798.0, width: 28.5, depth: 28.0 },
      FOYER_CONCESSION: { name: 'Foyer & Concession Lounge', area: 355.6, width: 12.7, depth: 28.0 },
      PROJECTION_ROOM: { name: 'Projection Booth', area: 130.5, width: 29.0, depth: 4.5 },
      RESTROOMS: { name: 'Restrooms Core', area: 109.35, width: 8.1, depth: 13.5 },
      MANAGER_OFFICE: { name: 'Manager & Staff Office', area: 60.0, width: 6.0, depth: 10.0 },
    },
    circulation_sqft: 824.20
  },
  {
    region_id: 'dhule-second-floor',
    name: 'Second Floor Plan',
    is_blocked: false,
    m5_candidate_id: 'dhule-second-floor-candidate-c',
    m5_score: 90.27,
    computational_status: 'DECISION_READY',
    review_status: 'NOT_REVIEWED',
    rooms: {
      AUDITORIUM_1: { name: 'Auditorium 1 (Screen 1)', area: 744.0, width: 31.0, depth: 24.0 },
      AUDITORIUM_2: { name: 'Auditorium 2 (Screen 2)', area: 798.0, width: 28.5, depth: 28.0 },
      FOYER_CONCESSION: { name: 'Foyer & Concession Lounge', area: 355.6, width: 12.7, depth: 28.0 },
      PROJECTION_ROOM: { name: 'Projection Booth', area: 130.5, width: 29.0, depth: 4.5 },
      RESTROOMS: { name: 'Restrooms Core', area: 109.35, width: 8.1, depth: 13.5 },
      MANAGER_OFFICE: { name: 'Manager & Staff Office', area: 60.0, width: 6.0, depth: 10.0 },
    },
    circulation_sqft: 824.20
  },
  {
    region_id: 'dhule-third-floor',
    name: 'Third Floor Plan',
    is_blocked: false,
    m5_candidate_id: 'dhule-third-floor-candidate-c',
    m5_score: 90.27,
    computational_status: 'DECISION_READY',
    review_status: 'NOT_REVIEWED',
    rooms: {
      AUDITORIUM_1: { name: 'Auditorium 1 (Screen 1)', area: 744.0, width: 31.0, depth: 24.0 },
      AUDITORIUM_2: { name: 'Auditorium 2 (Screen 2)', area: 798.0, width: 28.5, depth: 28.0 },
      FOYER_CONCESSION: { name: 'Foyer & Concession Lounge', area: 355.6, width: 12.7, depth: 28.0 },
      PROJECTION_ROOM: { name: 'Projection Booth', area: 130.5, width: 29.0, depth: 4.5 },
      RESTROOMS: { name: 'Restrooms Core', area: 109.35, width: 8.1, depth: 13.5 },
      MANAGER_OFFICE: { name: 'Manager & Staff Office', area: 60.0, width: 6.0, depth: 10.0 },
    },
    circulation_sqft: 824.20
  },
  {
    region_id: 'dhule-fourth-floor',
    name: 'Fourth Floor Plan',
    is_blocked: false,
    m5_candidate_id: 'dhule-fourth-floor-candidate-c',
    m5_score: 85.24,
    computational_status: 'VALID_REVIEW_REQUIRED',
    review_status: 'REVIEW_REQUIRED',
    rooms: {
      AUDITORIUM_1: { name: 'Auditorium 1 (Screen 1)', area: 744.0, width: 31.0, depth: 24.0 },
      AUDITORIUM_2: { name: 'Auditorium 2 (Screen 2)', area: 798.0, width: 28.5, depth: 28.0 },
      FOYER_CONCESSION: { name: 'Foyer & Concession Lounge', area: 355.6, width: 12.7, depth: 28.0 },
      PROJECTION_ROOM: { name: 'Projection Booth', area: 130.5, width: 29.0, depth: 4.5 },
      RESTROOMS: { name: 'Restrooms Core (Review Req)', area: 109.35, width: 8.1, depth: 13.5 },
      MANAGER_OFFICE: { name: 'Manager Office (Review Req)', area: 60.0, width: 6.0, depth: 10.0 },
    },
    circulation_sqft: 824.20
  },
  {
    region_id: 'dhule-basement',
    name: 'Basement Floor Plan',
    is_blocked: true,
    m5_candidate_id: null,
    m5_score: null,
    computational_status: 'BLOCKED_NO_VERIFIED_BOUNDARY',
    review_status: 'BLOCKED',
    rooms: {},
    circulation_sqft: 0
  }
];

export const ReviewRevisionWorkflow: React.FC = () => {
  const [selectedFloor, setSelectedFloor] = useState<FloorData>(FLOORS[0]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [revisionType, setRevisionType] = useState('INCREASE_ROOM_AREA');
  const [selectedRoom, setSelectedRoom] = useState('AUDITORIUM_2');
  const [paramValue, setParamValue] = useState('820.4');
  const [comment, setComment] = useState('Increase Auditorium 2 capacity to accommodate larger screen seating layout.');
  const [submittedRevision, setSubmittedRevision] = useState<any>(null);

  const handleOpenModal = () => {
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
  };

  const handleGenerateRevision = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFloor.is_blocked) {
      alert('Cannot generate revisions for blocked regions without verified exterior boundaries.');
      return;
    }

    const val = parseFloat(paramValue) || 820.0;
    const oldArea = selectedFloor.rooms[selectedRoom]?.area || 798.0;
    const areaDelta = val - oldArea;
    const scoreDelta = revisionType === 'INCREASE_ROOM_AREA' ? -0.04 : 0.00;
    const newScore = (selectedFloor.m5_score || 90.0) + scoreDelta;

    const revResult = {
      revision_id: `${selectedFloor.region_id}-rev-user`,
      region_id: selectedFloor.region_id,
      source_candidate_id: selectedFloor.m5_candidate_id,
      revision_type: revisionType,
      target_room: selectedRoom,
      score_before: selectedFloor.m5_score,
      score_after: parseFloat(newScore.toFixed(2)),
      score_delta: parseFloat(scoreDelta.toFixed(2)),
      room_area_before: oldArea,
      room_area_after: val,
      area_delta: parseFloat(areaDelta.toFixed(2)),
      comment,
      status: 'VALIDATED'
    };

    setSubmittedRevision(revResult);
    setIsModalOpen(false);
  };

  return (
    <div style={{ width: '100%', maxWidth: '1200px', margin: '0 auto', padding: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Architect Review &amp; Controlled Revision Workbench (M6/M7)
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Human-in-the-loop review interface over frozen M5 computational candidates. Original geometry remains immutable.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={handleOpenModal}
            disabled={selectedFloor.is_blocked}
            className="btn btn-primary"
            style={{ fontSize: '0.9rem', padding: '0.5rem 1.25rem' }}
          >
            [Request Revision]
          </button>
        </div>
      </div>

      {/* Notice Banner */}
      <div style={{ background: 'rgba(56, 139, 253, 0.1)', border: '1px solid var(--accent-color)', borderRadius: '6px', padding: '0.75rem 1rem', marginBottom: '1.5rem', fontSize: '0.82rem', color: 'var(--text-primary)' }}>
        <strong>Computational Decision-Support Notice:</strong> Revisions represent algorithmic candidate designs and do NOT constitute statutory architectural approval, certified code compliance, or structural engineering clearance.
      </div>

      {/* Region Selector Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', overflowX: 'auto', paddingBottom: '0.5rem' }}>
        {FLOORS.map(f => (
          <button
            key={f.region_id}
            onClick={() => { setSelectedFloor(f); setSubmittedRevision(null); }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: selectedFloor.region_id === f.region_id ? '2px solid var(--accent-color)' : '1px solid var(--border-color)',
              background: selectedFloor.region_id === f.region_id ? 'var(--bg-card)' : 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.85rem'
            }}
          >
            {f.name} {f.is_blocked ? '(BLOCKED)' : `(Score: ${f.m5_score})`}
          </button>
        ))}
      </div>

      {/* Main Floor Details Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Left: Original Candidate Overview */}
        <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Original Candidate (M5 Baseline)</h3>
            <span style={{ fontSize: '0.8rem', padding: '0.2rem 0.6rem', borderRadius: '4px', background: selectedFloor.is_blocked ? 'var(--danger-color)' : 'var(--success-bg)', color: selectedFloor.is_blocked ? '#fff' : 'var(--success-color)', fontWeight: 700 }}>
              {selectedFloor.computational_status}
            </span>
          </div>

          <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            <div><strong>Candidate ID:</strong> {selectedFloor.m5_candidate_id || 'None (Boundary Unverified)'}</div>
            <div><strong>Computational Score:</strong> {selectedFloor.m5_score !== null ? `${selectedFloor.m5_score} / 100` : 'N/A'}</div>
            <div><strong>Human Review Status:</strong> {selectedFloor.review_status}</div>
          </div>

          {selectedFloor.is_blocked ? (
            <div style={{ padding: '1.5rem', textAlign: 'center', background: 'rgba(248, 81, 73, 0.1)', border: '1px solid var(--danger-color)', borderRadius: '6px', color: 'var(--danger-color)' }}>
              <strong>Zoning Prohibited:</strong> Verified exterior boundary required before zoning review or revision generation.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '0.4rem' }}>Room</th>
                  <th style={{ padding: '0.4rem' }}>Area (sqft)</th>
                  <th style={{ padding: '0.4rem' }}>Dimensions</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(selectedFloor.rooms).map(([k, rm]) => (
                  <tr key={k} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '0.4rem' }}>{rm.name}</td>
                    <td style={{ padding: '0.4rem', fontWeight: 600 }}>{rm.area}</td>
                    <td style={{ padding: '0.4rem' }}>{rm.width} x {rm.depth} ft</td>
                  </tr>
                ))}
                <tr>
                  <td style={{ padding: '0.4rem', color: 'var(--accent-color)', fontWeight: 600 }}>Circulation Network</td>
                  <td style={{ padding: '0.4rem', fontWeight: 600 }}>{selectedFloor.circulation_sqft}</td>
                  <td style={{ padding: '0.4rem' }}>Min 2.0 / Concourse 5.5 ft</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>

        {/* Right: Revision Comparison & Delta Display */}
        <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.25rem' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>
            Revised Candidate (M7 Overlay)
          </h3>

          {submittedRevision ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', background: 'rgba(35, 134, 54, 0.15)', padding: '0.6rem 0.8rem', borderRadius: '6px' }}>
                <span style={{ fontWeight: 700, color: 'var(--success-color)', fontSize: '0.85rem' }}>
                  ✓ Revision Validated: {submittedRevision.revision_id}
                </span>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Status: PENDING_REVIEW</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem', fontSize: '0.85rem' }}>
                <div style={{ background: 'var(--bg-card)', padding: '0.75rem', borderRadius: '6px' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Score Delta</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, color: submittedRevision.score_delta >= 0 ? 'var(--success-color)' : 'var(--warning-color)' }}>
                    {submittedRevision.score_delta >= 0 ? `+${submittedRevision.score_delta}` : submittedRevision.score_delta} pts
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {submittedRevision.score_before} → {submittedRevision.score_after}
                  </div>
                </div>

                <div style={{ background: 'var(--bg-card)', padding: '0.75rem', borderRadius: '6px' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Area Delta ({submittedRevision.target_room})</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent-color)' }}>
                    {submittedRevision.area_delta >= 0 ? `+${submittedRevision.area_delta}` : submittedRevision.area_delta} sqft
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {submittedRevision.room_area_before} → {submittedRevision.room_area_after} sqft
                  </div>
                </div>
              </div>

              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                <strong>Reviewer Comment:</strong> <em>"{submittedRevision.comment}"</em>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button onClick={() => setSubmittedRevision(null)} className="btn btn-secondary" style={{ fontSize: '0.8rem' }}>
                  [Return to Review]
                </button>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              No revision requested for this floor yet.<br />
              Click <strong>[Request Revision]</strong> to configure structured geometric changes.
            </div>
          )}
        </div>
      </div>

      {/* Revision Request Modal Dialog */}
      {isModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '1rem' }}>
          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px', maxWidth: '540px', width: '100%', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '1rem' }}>
              Request Controlled Zoning Revision
            </h3>
            <form onSubmit={handleGenerateRevision}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                  Floor Region
                </label>
                <input
                  type="text"
                  disabled
                  value={selectedFloor.name}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '4px' }}
                />
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                  Revision Type
                </label>
                <select
                  value={revisionType}
                  onChange={(e) => setRevisionType(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '4px' }}
                >
                  <option value="INCREASE_ROOM_AREA">A. INCREASE_ROOM_AREA</option>
                  <option value="DECREASE_ROOM_AREA">B. DECREASE_ROOM_AREA</option>
                  <option value="MOVE_ROOM">C. MOVE_ROOM</option>
                  <option value="CHANGE_ROOM_ADJACENCY">D. CHANGE_ROOM_ADJACENCY</option>
                  <option value="INCREASE_CIRCULATION">E. INCREASE_CIRCULATION</option>
                  <option value="REDUCE_CIRCULATION">F. REDUCE_CIRCULATION</option>
                  <option value="CHANGE_ROOM_PROPORTION">G. CHANGE_ROOM_PROPORTION</option>
                  <option value="REVIEW_UNCERTAIN_GEOMETRY">H. REVIEW_UNCERTAIN_GEOMETRY</option>
                </select>
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                  Affected Room / Entity
                </label>
                <select
                  value={selectedRoom}
                  onChange={(e) => setSelectedRoom(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '4px' }}
                >
                  <option value="AUDITORIUM_2">AUDITORIUM_2 (Screen 2)</option>
                  <option value="AUDITORIUM_1">AUDITORIUM_1 (Screen 1)</option>
                  <option value="FOYER_CONCESSION">FOYER_CONCESSION</option>
                  <option value="PROJECTION_ROOM">PROJECTION_ROOM</option>
                  <option value="RESTROOMS">RESTROOMS</option>
                  <option value="MANAGER_OFFICE">MANAGER_OFFICE</option>
                </select>
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                  Structured Parameter (Target Area sqft / Delta ft)
                </label>
                <input
                  type="text"
                  value={paramValue}
                  onChange={(e) => setParamValue(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '4px' }}
                />
              </div>

              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
                  Reviewer Comment
                </label>
                <textarea
                  rows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', borderRadius: '4px', resize: 'vertical' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button type="button" onClick={handleCloseModal} className="btn btn-secondary">
                  [Cancel]
                </button>
                <button type="submit" className="btn btn-primary">
                  [Generate Revision]
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
