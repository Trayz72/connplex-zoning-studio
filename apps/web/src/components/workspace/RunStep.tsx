import React, { useState } from 'react';
import { runZoning, selectCandidate } from '../../services/zoningEngineApi';
import { ZoningRunResult, LiveCandidate, EditableLayout } from '../../types/live';

interface RunStepProps {
  projectId: string;
  regionId: string;
  onLayoutReady: (layout: EditableLayout) => void;
}

const FEAS_COLOR: Record<string, string> = {
  FEASIBLE: '#3fb950', CONDITIONALLY_FEASIBLE: '#d29922', NOT_FEASIBLE: '#f85149', INSUFFICIENT_DATA: '#8b949e'
};

export const RunStep: React.FC<RunStepProps> = ({ projectId, regionId, onLayoutReady }) => {
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<ZoningRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);

  const doRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const result = await runZoning(projectId, regionId);
      setRun(result);
    } catch (e: any) {
      setError(e.message || 'Zoning run failed.');
    } finally {
      setRunning(false);
    }
  };

  const pick = async (candidate: LiveCandidate) => {
    setSelecting(candidate.candidate_id);
    try {
      const layout = await selectCandidate(projectId, candidate.candidate_id);
      onLayoutReady(layout);
    } catch (e: any) {
      setError(e.message || 'Could not select candidate.');
    } finally {
      setSelecting(null);
    }
  };

  if (!run) {
    return (
      <div style={{ maxWidth: '520px', margin: '4rem auto', textAlign: 'center' }}>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 700, color: '#f0f6fc', marginBottom: '0.75rem' }}>Run Auto-Layout</h2>
        <p style={{ fontSize: '0.85rem', color: '#8b949e', marginBottom: '1.5rem' }}>
          Generates real candidate layouts against your confirmed geometry — a greedy packer places auditoriums
          (largest-fitting preset first) then support zones in whatever usable space remains, avoiding every
          confirmed obstacle.
        </p>
        {error && <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}
        <button className="btn btn-primary" style={{ padding: '0.6rem 2rem' }} disabled={running} onClick={doRun}>
          {running ? 'Running…' : 'Run Zoning'}
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '1100px', margin: '0 auto' }}>
      <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f0f6fc', marginBottom: '1rem' }}>
        {run.candidates.length} Candidate Layout{run.candidates.length !== 1 ? 's' : ''}
      </h2>
      {run.unresolved_obstacle_count > 0 && (
        <div className="alert-box" style={{ marginBottom: '1rem', color: '#d29922', border: '1px solid #d29922' }}>
          Note: {run.unresolved_obstacle_count} detected obstacle(s) were not resolved and were excluded from placement constraints.
        </div>
      )}
      {error && <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${run.candidates.length}, 1fr)`, gap: '16px' }}>
        {run.candidates.map(c => (
          <div key={c.candidate_id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '16px' }}>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f0f6fc' }}>{c.strategy_label}</div>
            <div style={{ fontSize: '0.75rem', color: FEAS_COLOR[c.feasibility.feasibility_result], fontWeight: 700, margin: '6px 0' }}>
              {c.feasibility.feasibility_result.replace(/_/g, ' ')}
            </div>
            <div style={{ fontSize: '0.85rem', color: '#f0f6fc', marginBottom: '4px' }}>{c.screen_count} screens · {c.total_seats} total seats</div>
            <div style={{ fontSize: '0.78rem', color: '#8b949e', marginBottom: '10px' }}>{c.seats_per_screen} seats/screen · {c.circulation_area_sqft} sqft circulation</div>

            <div style={{ fontSize: '0.72rem', color: '#8b949e', marginBottom: '10px' }}>
              {c.rooms.map(r => (
                <div key={r.room_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.display_name}</span>
                  <span>{r.area_sqft} sqft{r.seat_estimate ? ` / ${r.seat_estimate.seat_count} seats` : ''}</span>
                </div>
              ))}
            </div>

            {c.warnings.length > 0 && (
              <div style={{ fontSize: '0.68rem', color: '#d29922', marginBottom: '10px' }}>
                {c.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}

            <button className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem' }} disabled={!!selecting} onClick={() => pick(c)}>
              {selecting === c.candidate_id ? 'Selecting…' : 'Use This Layout →'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
