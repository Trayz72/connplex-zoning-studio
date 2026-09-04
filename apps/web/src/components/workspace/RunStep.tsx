import React, { useEffect, useRef, useState } from 'react';
import { runZoning, runAiZoning, selectCandidate } from '../../services/zoningEngineApi';
import { ZoningRunResult, LiveCandidate, EditableLayout } from '../../types/live';
import { ArrowRightIcon, WarningIcon, RefreshIcon } from '../Icons';

interface RunStepProps {
  projectId: string;
  regionId: string;
  onLayoutReady: (layout: EditableLayout) => void;
}

const FEAS_COLOR: Record<string, string> = {
  FEASIBLE: 'var(--success)', CONDITIONALLY_FEASIBLE: 'var(--warning)', NOT_FEASIBLE: 'var(--danger)', INSUFFICIENT_DATA: 'var(--text-tertiary)'
};

const AUTO_SELECT_MS = 1600;

/** The same choice the backend itself already makes when it writes the
 * initial layout after a run (main.py's run_zoning: `max(candidates, key=
 * lambda c: c["total_seats"])`) — kept in sync here so what the architect
 * sees auto-selected matches what's actually on disk if they never look. */
function bestCandidate(candidates: LiveCandidate[]): LiveCandidate {
  return candidates.reduce((best, c) => (c.total_seats > best.total_seats ? c : best));
}

const AI_REASONING_PREFIX = 'AI reasoning: ';

/** ai_zoning_engine.py packs Claude's own explanation into warnings[0] as a
 * plain string (backend has no separate "reasoning" field on the candidate
 * shape) — split it out so it renders as an explanation, not a warning icon. */
function aiReasoning(c: LiveCandidate): string | null {
  const w = c.warnings.find(w => w.startsWith(AI_REASONING_PREFIX));
  return w ? w.slice(AI_REASONING_PREFIX.length) : null;
}

function realWarnings(c: LiveCandidate): string[] {
  return c.warnings.filter(w => !w.startsWith(AI_REASONING_PREFIX));
}

export const RunStep: React.FC<RunStepProps> = ({ projectId, regionId, onLayoutReady }) => {
  const [run, setRun] = useState<ZoningRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [autoFired, setAutoFired] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const startedRef = useRef(false);

  const generateAi = async () => {
    // Cancel the pending deterministic auto-select — a 30-40s AI call would
    // otherwise lose the race and the page would already be on step 5 by the
    // time it resolves, same as pick() does for a manual candidate choice.
    setAutoFired(true);
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await runAiZoning(projectId, regionId);
      setRun(result);
    } catch (e: any) {
      setAiError(e.message || 'AI-assisted layout generation failed.');
    } finally {
      setAiLoading(false);
    }
  };

  const pick = async (candidate: LiveCandidate) => {
    setAutoFired(true);
    setSelecting(candidate.candidate_id);
    try {
      const layout = await selectCandidate(projectId, candidate.candidate_id);
      onLayoutReady(layout);
    } catch (e: any) {
      setError(e.message || 'Could not select candidate.');
      setSelecting(null);
    }
  };

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const result = await runZoning(projectId, regionId);
        setRun(result);
      } catch (e: any) {
        setError(e.message || 'Zoning run failed.');
      }
    })();
  }, [projectId, regionId]);

  useEffect(() => {
    if (!run || run.candidates.length === 0 || autoFired) return;
    const best = bestCandidate(run.candidates);
    const t = setTimeout(() => pick(best), AUTO_SELECT_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, autoFired]);

  if (error) {
    return (
      <div style={{ maxWidth: '520px', margin: '4rem auto', textAlign: 'center' }}>
        <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>{error}</div>
      </div>
    );
  }

  if (!run) {
    return (
      <div style={{ maxWidth: '520px', margin: '4rem auto', textAlign: 'center' }}>
        <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.75rem' }}>Generating Zoning Layout</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Placing screens (largest-fitting preset first, biased toward the marked entrance) while avoiding every
          confirmed obstacle — Foyer, F&amp;B, Washroom, Box Office, and Back-of-House are added afterward from
          the Edit step's "Add zone" toolbar.
        </p>
      </div>
    );
  }

  const best = bestCandidate(run.candidates);

  const hasAiCandidate = run.candidates.some(c => c.strategy === 'AI_ASSISTED');

  return (
    <div style={{ padding: '1.5rem', maxWidth: '1100px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '0.25rem' }}>
        <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: 'var(--text-primary)' }}>
          {run.candidates.length} Candidate Layout{run.candidates.length !== 1 ? 's' : ''}
        </h2>
        {!hasAiCandidate && (
          <button className="btn btn-secondary" style={{ fontSize: '0.78rem', flex: '0 0 auto' }} disabled={aiLoading} onClick={generateAi}>
            {aiLoading ? <><RefreshIcon size={13} /> Generating with Claude… (~30s)</> : <><RefreshIcon size={13} /> Generate AI-Assisted Layout</>}
          </button>
        )}
      </div>
      {aiError && (
        <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>{aiError}</div>
      )}
      {!autoFired && (
        <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Auto-selecting "{best.strategy_label}" ({best.total_seats} seats) shortly — pick a different one below if you'd rather use it.
        </p>
      )}
      {run.unresolved_obstacle_count > 0 && (
        <div className="alert-box" style={{ marginBottom: '1rem', color: 'var(--warning)', border: '1px solid var(--warning)' }}>
          Note: {run.unresolved_obstacle_count} detected obstacle(s) were not resolved and were excluded from placement constraints.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${run.candidates.length}, 1fr)`, gap: '16px' }}>
        {run.candidates.map(c => (
          <div
            key={c.candidate_id}
            className="panel"
            style={{
              padding: '16px',
              borderColor: c.candidate_id === best.candidate_id && !autoFired ? 'var(--border-strong)' : undefined
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{c.strategy_label}</div>
              {c.strategy === 'AI_ASSISTED' && (
                <span className="badge" style={{ fontSize: '0.62rem', padding: '1px 7px', color: 'var(--brand-strong)', border: '1px solid var(--brand-strong)' }}>CLAUDE</span>
              )}
            </div>
            <div style={{ fontSize: '0.75rem', color: FEAS_COLOR[c.feasibility.feasibility_result], fontWeight: 600, margin: '6px 0' }}>
              {c.feasibility.feasibility_result.replace(/_/g, ' ')}
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: '4px' }} className="font-mono">{c.screen_count} screens · {c.total_seats} total seats</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '10px' }} className="font-mono">{c.seats_per_screen} seats/screen · {c.circulation_area_sqft} sqft circulation</div>

            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '10px' }}>
              {c.rooms.map(r => (
                <div key={r.room_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.display_name}</span>
                  <span className="font-mono">{r.area_sqft} sqft{r.seat_estimate ? ` / ${r.seat_estimate.seat_count} seats` : ''}</span>
                </div>
              ))}
            </div>

            {aiReasoning(c) && (
              <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '10px', fontStyle: 'italic' }}>
                "{aiReasoning(c)}"
              </div>
            )}

            {realWarnings(c).length > 0 && (
              <div style={{ fontSize: '0.68rem', color: 'var(--warning)', marginBottom: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {realWarnings(c).map((w, i) => (
                  <div key={i} style={{ display: 'flex', gap: '5px' }}>
                    <WarningIcon size={12} style={{ flex: '0 0 auto', marginTop: '2px' }} />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            )}

            <button className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem' }} disabled={!!selecting} onClick={() => pick(c)}>
              {selecting === c.candidate_id ? 'Selecting…' : <>Use This Layout <ArrowRightIcon size={14} /></>}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
