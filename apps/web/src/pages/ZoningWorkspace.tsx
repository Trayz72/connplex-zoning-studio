import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link, Navigate } from 'react-router-dom';
import { getProject, Project } from '../api';
import * as engine from '../services/zoningEngineApi';
import { ValidationRejectedError } from '../services/zoningEngineApi';
import { GeometryResult, GeometryRegion, Requirements, EditableLayout, LiveRoom, LiveCandidate, ValidationError, SelectableSeatType, SeatConfig } from '../types/live';
import { UploadStep } from '../components/workspace/UploadStep';
import { BoundaryStudio } from '../components/workspace/BoundaryStudio';
import { GeometryReviewStep } from '../components/workspace/GeometryReviewStep';
import { RequirementsStep } from '../components/workspace/RequirementsStep';
import { RunStep } from '../components/workspace/RunStep';
import { EditableCanvas } from '../components/workspace/EditableCanvas';
import { ExportPanel } from '../components/workspace/ExportPanel';
import { SeatConfigPanel } from '../components/workspace/SeatConfigPanel';
import { RoomDimensionEditor } from '../components/workspace/RoomDimensionEditor';
import { ThemeToggle } from '../components/ThemeToggle';

type Step = 'LOADING' | 'UPLOAD' | 'BOUNDARY_STUDIO' | 'GEOMETRY_REVIEW' | 'REQUIREMENTS' | 'RUN' | 'EDIT';

const STEP_LABEL: Record<Step, string> = {
  LOADING: 'Loading', UPLOAD: 'Upload', BOUNDARY_STUDIO: 'Select Boundary', GEOMETRY_REVIEW: 'Geometry Review',
  REQUIREMENTS: 'Requirements', RUN: 'Run', EDIT: 'Edit'
};

// The real wizard order, LOADING excluded — used both to render the
// stepper left-to-right and to know which steps count as "already visited"
// (see maxStepIndex) so a completed step can be revisited without also
// making an unreached one clickable, which would just 404 on missing state.
const STEP_ORDER: Step[] = ['UPLOAD', 'BOUNDARY_STUDIO', 'GEOMETRY_REVIEW', 'REQUIREMENTS', 'RUN', 'EDIT'];

// Placement itself is entirely server-side now (see zoningEngineApi.addZone /
// layout_engine.place_single_zone) — the backend finds a real, collision-free,
// entry-aware position using the same scan-and-fit machinery auto-layout
// itself uses for screens, so this list only needs a type + label, no
// client-guessed size or position.
const ROOM_TYPE_TEMPLATES: { type: string; label: string }[] = [
  { type: 'AUDITORIUM', label: 'Screen' },
  { type: 'FOYER', label: 'Foyer' },
  { type: 'FNB', label: 'F&B / Concession' },
  { type: 'WASHROOM', label: 'Washroom' },
  { type: 'BOX_OFFICE', label: 'Box Office' },
  { type: 'BOH', label: 'Back-of-House' }
];

const FEAS_COLOR: Record<string, string> = {
  FEASIBLE: 'var(--success)', CONDITIONALLY_FEASIBLE: 'var(--warning)', NOT_FEASIBLE: 'var(--danger)', INSUFFICIENT_DATA: 'var(--text-tertiary)'
};

export const ZoningWorkspace: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [step, setStep] = useState<Step>('LOADING');
  // How far this project has actually gotten — a step already visited can be
  // revisited (a real "Back" affordance, see the stepper/Back button below),
  // but nothing past that: an unreached step has no state to show yet
  // (e.g. clicking "5. Run" before requirements exist would just render an
  // empty RunStep). Tracked separately from `step` itself since going back
  // must not un-mark a later step as reached — that's what makes it safe to
  // navigate forward again without re-doing everything.
  const [maxStepIndex, setMaxStepIndex] = useState(0);
  const goToStep = useCallback((s: Step) => {
    const idx = STEP_ORDER.indexOf(s);
    if (idx >= 0) setMaxStepIndex(prev => Math.max(prev, idx));
    setStep(s);
  }, []);
  const stepIndex = STEP_ORDER.indexOf(step);
  const goBack = () => { if (stepIndex > 0) goToStep(STEP_ORDER[stepIndex - 1]); };
  const [geometry, setGeometry] = useState<GeometryResult | null>(null);
  const [regionId, setRegionId] = useState<string>('');
  const [reviewRegionId, setReviewRegionId] = useState<string | undefined>(undefined);
  const [requirements, setRequirements] = useState<Requirements | null>(null);
  // Marked at boundary-selection time (BoundaryStudio's entry/exit
  // sub-step), before a real Requirements object necessarily exists yet —
  // held here and merged into RequirementsStep's own default state rather
  // than forced into a premature Requirements object, since building one
  // correctly also needs the intake clear-height hint RequirementsStep
  // already owns (see its own default-state construction).
  const [entryPointFt, setEntryPointFt] = useState<[number, number] | null>(null);
  const [exitPointsFt, setExitPointsFt] = useState<[number, number][] | null>(null);
  const [layout, setLayout] = useState<EditableLayout | null>(null);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [snapFt, setSnapFt] = useState(1);
  const [showCadLinework, setShowCadLinework] = useState(true);
  const [saving, setSaving] = useState(false);
  const [seatTypes, setSeatTypes] = useState<SelectableSeatType[]>([]);
  const [applyingSeatConfig, setApplyingSeatConfig] = useState(false);
  const [alternateCandidates, setAlternateCandidates] = useState<LiveCandidate[]>([]);
  const [switchingStrategy, setSwitchingStrategy] = useState(false);

  useEffect(() => {
    engine.getSeatTypes().then(setSeatTypes).catch(() => {});
  }, []);

  // The auto-run flow (RunStep) picks the higher-seat-count strategy without
  // asking, so the architect who never touches anything still gets a real
  // layout — but the choice of *strategy* (max seats/screen vs max screen
  // count) is a real tradeoff, not a fact, so it stays switchable here as an
  // optional action rather than being locked in.
  useEffect(() => {
    if (step !== 'EDIT' || !id) return;
    engine.getLatestRun(id).then(run => setAlternateCandidates(run?.candidates || [])).catch(() => {});
  }, [step, id]);

  const switchStrategy = async (candidateId: string) => {
    if (!id) return;
    setSwitchingStrategy(true);
    try {
      const l = await engine.selectCandidate(id, candidateId);
      setLayout(l);
      setSelectedRoomId(null);
    } catch {
      // Best-effort — the current layout stays exactly as it was if this fails.
    } finally {
      setSwitchingStrategy(false);
    }
  };

  useEffect(() => {
    if (!id) return;
    (async () => {
      const proj = await getProject(id).catch(() => null);
      setProject(proj);

      const geo = await engine.getGeometry(id).catch(() => null);
      if (!geo) { goToStep('UPLOAD'); return; }
      setGeometry(geo);

      const confirmedRegion = geo.regions.find(r => r.boundary.status === 'CONFIRMED');
      if (!confirmedRegion) { goToStep('BOUNDARY_STUDIO'); return; }
      setRegionId(confirmedRegion.region_id);

      const req = await engine.getRequirements(id).catch(() => null);
      if (!req) { goToStep('REQUIREMENTS'); return; }
      setRequirements(req);

      const existingLayout = await engine.getLayout(id).catch(() => null);
      if (existingLayout) { setLayout(existingLayout); goToStep('EDIT'); return; }

      goToStep('RUN');
    })();
  }, [id]);

  const handleUploaded = (geo: GeometryResult) => {
    setGeometry(geo);
    goToStep('BOUNDARY_STUDIO');
  };

  const handleStartOver = () => {
    setGeometry(null);
    setReviewRegionId(undefined);
    goToStep('UPLOAD');
  };

  const handleBoundaryChosen = (
    geo: GeometryResult, chosenRegionId: string,
    entryPt?: [number, number] | null, exitPts?: [number, number][]
  ) => {
    setGeometry(geo);
    setReviewRegionId(chosenRegionId);
    if (entryPt !== undefined) setEntryPointFt(entryPt);
    if (exitPts !== undefined) setExitPointsFt(exitPts.length ? exitPts : null);
    goToStep('GEOMETRY_REVIEW');
  };

  const handleGeometryConfirmed = async (regions: GeometryRegion[], selectedRegionId: string) => {
    if (!id) return;
    const updated = await engine.updateGeometry(id, regions);
    setGeometry(updated);
    setRegionId(selectedRegionId);
    goToStep('REQUIREMENTS');
  };

  const handleRequirementsSubmit = async (req: Requirements) => {
    if (!id) return;
    const saved = await engine.setRequirements(id, req);
    setRequirements(saved);
    goToStep('RUN');
  };

  const handleLayoutReady = (l: EditableLayout) => {
    setLayout(l);
    setSelectedRoomId(null);
    goToStep('EDIT');
  };

  const persistLayout = useCallback(async (rooms: LiveRoom[]) => {
    if (!id || !layout) return;
    setSaving(true);
    setValidationErrors([]);
    try {
      const updated = await engine.updateLayout(id, {
        rooms, boundary_points_ft: layout.boundary_points_ft, obstacles: layout.obstacles, circulation_area_sqft: null as any
      });
      setLayout(updated);
    } catch (e: any) {
      if (e instanceof ValidationRejectedError) {
        setValidationErrors(e.errors);
      } else {
        setValidationErrors([{ room_id: '', issue: 'ERROR', message: e.message || 'Could not save layout.' }]);
      }
      // The server rejected the edit, so `layout` (the last-known-good state) is
      // unchanged — but force a new array reference so EditableCanvas's reset
      // effect fires and the dragged room visually snaps back rather than being
      // left in the invalid position it was dropped at.
      setLayout(prev => prev ? { ...prev, rooms: [...prev.rooms] } : prev);
    } finally {
      setSaving(false);
    }
  }, [id, layout]);

  // Placement is entirely server-side (engine.addZone -> place_single_zone) —
  // this used to drop the new room at a fixed boundary corner with no
  // collision awareness at all, which the backend's own validation then
  // silently rejected almost every time (that corner is normally already
  // occupied), making "Add zone" look broken. The server now finds a real,
  // collision-free, entry-aware position using the same machinery
  // auto-layout itself uses for screens.
  const addZone = async (template: typeof ROOM_TYPE_TEMPLATES[number]) => {
    if (!id || !layout) return;
    setSaving(true);
    setValidationErrors([]);
    try {
      const updated = await engine.addZone(id, template.type);
      setLayout(updated);
    } catch (e: any) {
      setValidationErrors([{ room_id: '', issue: 'ERROR', message: e.message || `Could not add ${template.label}.` }]);
    } finally {
      setSaving(false);
    }
  };

  const deleteSelected = () => {
    if (!layout || !selectedRoomId) return;
    persistLayout(layout.rooms.filter(r => r.room_id !== selectedRoomId));
    setSelectedRoomId(null);
  };

  const applySeatConfig = async (seatConfig: SeatConfig) => {
    if (!layout || !selectedRoomId) return;
    setApplyingSeatConfig(true);
    const rooms = layout.rooms.map(r => r.room_id === selectedRoomId ? { ...r, seat_config: seatConfig } : r);
    await persistLayout(rooms);
    setApplyingSeatConfig(false);
  };

  const [applyingDimensions, setApplyingDimensions] = useState(false);
  const applyDimensions = async (updates: { origin_ft: [number, number]; width_ft: number; depth_ft: number }) => {
    if (!layout || !selectedRoomId) return;
    setApplyingDimensions(true);
    const [x, y] = updates.origin_ft;
    const { width_ft: w, depth_ft: d } = updates;
    const rooms = layout.rooms.map(r => r.room_id === selectedRoomId ? {
      ...r,
      origin_ft: updates.origin_ft,
      width_ft: w,
      depth_ft: d,
      area_sqft: Math.round(w * d * 100) / 100,
      geometry_points_ft: [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]
    } : r);
    await persistLayout(rooms);
    setApplyingDimensions(false);
  };

  const selectedRoom = layout?.rooms.find(r => r.room_id === selectedRoomId) || null;

  if (step === 'LOADING') {
    return <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-tertiary)' }}>Loading workspace…</div>;
  }

  // The intake page already disables "Go to Zoning Canvas" until every
  // mandatory field is filled, but that was only ever a UI nicety — nothing
  // stopped a direct URL to /studio on an incomplete project. Verified this
  // directly: a fresh project with is_intake_complete=false loaded the full
  // upload/zoning workspace with no gate at all. This contradicts the
  // spec's own M0 acceptance criterion ("cannot reach the canvas route with
  // incomplete intake data"), so enforce it here too, not just as a
  // disabled button.
  if (project && !project.is_intake_complete && id) {
    return <Navigate to={`/projects/${id}/intake`} replace />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-primary)', color: 'var(--text-primary)', overflow: 'hidden' }}>
      <header style={{ height: '52px', background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Link to="/projects" style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-primary)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span className="brand-mark">CZ</span>
            Connplex Zoning Studio
          </Link>
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-tertiary)' }}>{project?.property_name || 'Project'}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {stepIndex > 0 && (
            <button
              className="btn btn-secondary" style={{ fontSize: '0.72rem', padding: '0.32rem 0.7rem' }}
              onClick={goBack} title={`Back to ${STEP_LABEL[STEP_ORDER[stepIndex - 1]]}`}
            >
              ← Back
            </button>
          )}
          <div style={{ display: 'flex', gap: '2px', fontSize: 'var(--text-xs)' }}>
            {STEP_ORDER.map((s, i) => {
              const reached = i <= maxStepIndex;
              const isCurrent = step === s;
              // A step already visited is a real link back to it (the
              // stepper doubles as breadcrumb navigation, not just a
              // progress indicator) — one not yet reached stays plain text,
              // since clicking it would just render a step with no state to
              // show yet (e.g. Requirements before a boundary is confirmed).
              return (
                <button
                  key={s}
                  disabled={!reached || isCurrent}
                  onClick={() => reached && goToStep(s)}
                  title={reached && !isCurrent ? `Back to ${STEP_LABEL[s]}` : undefined}
                  style={{
                    padding: '4px 10px', borderRadius: 'var(--radius-sm)', fontWeight: isCurrent ? 600 : 400,
                    background: isCurrent ? 'var(--bg-raised)' : 'transparent',
                    color: isCurrent ? 'var(--text-primary)' : reached ? 'var(--text-secondary)' : 'var(--text-tertiary)',
                    border: 'none', font: 'inherit', fontSize: 'inherit',
                    cursor: reached && !isCurrent ? 'pointer' : 'default',
                    opacity: reached ? 1 : 0.6
                  }}
                >
                  {i + 1}. {STEP_LABEL[s]}
                </button>
              );
            })}
          </div>
          <ThemeToggle />
        </div>
      </header>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {step === 'UPLOAD' && id && <UploadStep projectId={id} onUploaded={handleUploaded} />}
        {step === 'BOUNDARY_STUDIO' && id && geometry && (
          <BoundaryStudio
            projectId={id}
            geometry={geometry}
            onGeometryUpdated={setGeometry}
            onBoundaryChosen={handleBoundaryChosen}
            onStartOver={handleStartOver}
          />
        )}
        {step === 'GEOMETRY_REVIEW' && geometry && id && (
          <GeometryReviewStep projectId={id} geometry={geometry} onConfirmed={handleGeometryConfirmed} onStartOver={handleStartOver} initialRegionId={reviewRegionId} />
        )}
        {step === 'REQUIREMENTS' && (
          <RequirementsStep
            initial={requirements}
            clearHeightHint={project?.beam_bottom_clear_height}
            boundaryPointsFt={geometry?.regions.find(r => r.region_id === regionId)?.boundary.points_ft}
            initialEntryPointFt={entryPointFt}
            initialExitPointsFt={exitPointsFt}
            onSubmit={handleRequirementsSubmit}
          />
        )}
        {step === 'RUN' && id && <RunStep projectId={id} regionId={regionId} onLayoutReady={handleLayoutReady} />}

        {step === 'EDIT' && layout && (
          <div style={{ display: 'flex', height: '100%' }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '8px', gap: '8px' }}>
              <div className="toolbar">
                <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-tertiary)', fontWeight: 500 }}>Add zone:</span>
                {ROOM_TYPE_TEMPLATES.map(t => (
                  <button key={t.type} className="btn btn-secondary btn-sm" disabled={saving} onClick={() => addZone(t)}>+ {t.label}</button>
                ))}
                {selectedRoomId && <button className="btn btn-danger btn-sm" disabled={saving} onClick={deleteSelected}>Delete Selected</button>}
                <label className="checkbox-label" style={{ marginLeft: 'auto' }}>
                  <input type="checkbox" checked={showCadLinework} onChange={(e) => setShowCadLinework(e.target.checked)} />
                  CAD linework
                </label>
                <label className="checkbox-label" style={{ cursor: 'default' }}>
                  Snap:
                  <select className="select-control" value={snapFt} onChange={(e) => setSnapFt(parseFloat(e.target.value))}>
                    <option value={0}>Off</option>
                    <option value={0.5}>0.5 ft</option>
                    <option value={1}>1 ft</option>
                    <option value={2}>2 ft</option>
                  </select>
                </label>
                {saving && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>Saving…</span>}
              </div>

              {validationErrors.length > 0 && (
                <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: '6px', padding: '8px 10px', fontSize: '0.72rem', color: 'var(--danger)' }}>
                  {validationErrors.map((e, i) => <div key={i}>{e.message}</div>)}
                </div>
              )}

              <EditableCanvas
                boundaryPointsFt={layout.boundary_points_ft}
                obstacles={layout.obstacles}
                rooms={layout.rooms}
                selectedRoomId={selectedRoomId}
                onSelectRoom={setSelectedRoomId}
                onLiveChange={() => {}}
                onCommit={persistLayout}
                snapToGridFt={snapFt}
                rawGeometry={geometry?.regions.find(r => r.region_id === layout.region_id)?.raw_geometry}
                showCadLinework={showCadLinework}
                onDeleteSelected={deleteSelected}
              />
            </div>

            <div style={{ width: '360px', borderLeft: '1px solid var(--border-color)', padding: '12px', overflowY: 'auto' }}>
              {alternateCandidates.length > 1 && (
                <div className="panel" style={{ marginBottom: '16px' }}>
                  <div className="panel-label" style={{ marginBottom: '8px' }}>Layout Strategy</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {alternateCandidates.map(c => (
                      <button
                        key={c.candidate_id}
                        className={c.candidate_id === layout.source_candidate_id ? 'btn btn-primary' : 'btn btn-secondary'}
                        disabled={switchingStrategy}
                        style={{ fontSize: '0.72rem', padding: '6px 8px', textAlign: 'left' }}
                        onClick={() => c.candidate_id !== layout.source_candidate_id && switchStrategy(c.candidate_id)}
                      >
                        {c.strategy_label} — {c.screen_count} screens, {c.total_seats} seats
                      </button>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.66rem', color: 'var(--text-tertiary)', marginTop: '6px' }}>
                    Switching discards manual edits made on the current layout and starts from that strategy's generated rooms.
                  </div>
                </div>
              )}

              <div className="panel" style={{ marginBottom: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }} className="panel-label">
                  <span>Feasibility</span>
                  <span style={{ color: FEAS_COLOR[layout.feasibility.feasibility_result] }}>{layout.feasibility.feasibility_result.replace(/_/g, ' ')}</span>
                </div>
                {layout.feasibility.rule_results.map(rr => (
                  <div key={rr.rule_id} style={{ fontSize: '0.7rem', color: rr.result === 'FAIL' ? 'var(--danger)' : 'var(--text-secondary)', padding: '2px 0' }}>
                    {rr.message}
                  </div>
                ))}
              </div>

              {(layout.warnings.length > 0 || layout.rooms.some(r => r.obstacle_note || r.seat_estimate?.note)) && (
                <div className="panel" style={{ borderColor: 'rgba(201,154,58,0.35)', marginBottom: '16px' }}>
                  <div className="panel-label" style={{ color: 'var(--warning)', marginBottom: '8px' }}>Warnings &amp; Notes</div>
                  {layout.warnings.map((w, i) => (
                    <div key={`w${i}`} style={{ fontSize: '0.7rem', color: 'var(--warning)', padding: '5px 0', borderBottom: '1px solid var(--border-color)' }}>{w}</div>
                  ))}
                  {layout.rooms.filter(r => r.obstacle_note || r.seat_estimate?.note).map(r => (
                    <div key={r.room_id} style={{ fontSize: '0.7rem', color: 'var(--warning)', padding: '5px 0', borderBottom: '1px solid var(--border-color)' }}>
                      <strong>{r.display_name}:</strong> {r.obstacle_note || r.seat_estimate?.note}
                    </div>
                  ))}
                </div>
              )}

              {selectedRoom && selectedRoom.room_type.startsWith('AUDITORIUM') && seatTypes.length > 0 && (
                <div className="panel" style={{ marginBottom: '16px' }}>
                  <SeatConfigPanel room={selectedRoom} seatTypes={seatTypes} onApply={applySeatConfig} applying={applyingSeatConfig} embedded />
                  <RoomDimensionEditor room={selectedRoom} onApply={applyDimensions} applying={applyingDimensions} />
                </div>
              )}
              {selectedRoom && !selectedRoom.room_type.startsWith('AUDITORIUM') && (
                <div className="panel" style={{ marginBottom: '16px' }}>
                  <div className="panel-label" style={{ marginBottom: '8px' }}>{selectedRoom.display_name}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)' }} className="font-mono">{selectedRoom.area_sqft} sqft ({selectedRoom.width_ft} × {selectedRoom.depth_ft} ft)</div>
                  <RoomDimensionEditor room={selectedRoom} onApply={applyDimensions} applying={applyingDimensions} />
                </div>
              )}

              <div className="panel" style={{ marginBottom: '16px' }}>
                <div className="panel-label" style={{ marginBottom: '8px' }}>Area &amp; Seat Chart</div>
                <table className="font-mono" style={{ width: '100%', fontSize: '0.66rem', borderCollapse: 'collapse' }}>
                  <tbody>
                    {layout.area_seat_chart.screen_rows.map(r => (
                      <tr key={r.location}><td>{r.location}</td><td style={{ textAlign: 'right' }}>{r.area_sqft} sqft</td><td style={{ textAlign: 'right' }}>{r.total_seats} seats</td></tr>
                    ))}
                    <tr style={{ fontWeight: 700 }}>
                      <td>{layout.area_seat_chart.total_screen_row.location}</td>
                      <td style={{ textAlign: 'right' }}>{layout.area_seat_chart.total_screen_row.area_sqft}</td>
                      <td style={{ textAlign: 'right' }}>{layout.area_seat_chart.total_screen_row.total_seats}</td>
                    </tr>
                    <tr><td title={layout.area_seat_chart.foyer_row.location}>{layout.area_seat_chart.foyer_row.location.split(' (')[0]}</td><td style={{ textAlign: 'right' }}>{layout.area_seat_chart.foyer_row.area_sqft}</td><td /></tr>
                    <tr><td>{layout.area_seat_chart.exit_passage_row.location}</td><td style={{ textAlign: 'right' }}>{layout.area_seat_chart.exit_passage_row.area_sqft}</td><td /></tr>
                    <tr style={{ fontWeight: 700, color: 'var(--success)' }}>
                      <td>{layout.area_seat_chart.grand_total_row.location}</td>
                      <td style={{ textAlign: 'right' }}>{layout.area_seat_chart.grand_total_row.area_sqft}</td>
                      <td style={{ textAlign: 'right' }}>{layout.area_seat_chart.grand_total_row.total_seats}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {project && (
                <ExportPanel
                  projectId={id!}
                  projectMeta={{
                    property_name: project.property_name, project_code: project.project_code,
                    client_name: project.client_name, client_by: project.client_name, city: project.city, state: project.state,
                    floor_shop_no: project.floor_shop_no, beam_bottom_clear_height: project.beam_bottom_clear_height,
                    drawn_by: 'AR. ZONING ENGINE (AUTO)', checked_by: 'PENDING ARCHITECT REVIEW'
                  }}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
