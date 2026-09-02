import React, { useEffect, useState } from 'react';
import { GeometryResult, GeometryRegion } from '../../types/live';
import { EditableCanvas } from './EditableCanvas';
import * as engine from '../../services/zoningEngineApi';
import { ArrowLeftIcon, ArrowRightIcon, RefreshIcon, WarningIcon, CheckIcon } from '../Icons';

interface GeometryReviewStepProps {
  projectId: string;
  geometry: GeometryResult;
  onConfirmed: (regions: GeometryRegion[], selectedRegionId: string) => void;
  onStartOver: () => void;
  /** Which region to land on — set when arriving from BoundaryStudio (either
   * an auto-detected region picked directly, or one just created manually).
   * Falls back to the first region when not given. */
  initialRegionId?: string;
}

const CONF_COLOR: Record<string, string> = { high: 'var(--success)', medium: 'var(--warning)', low: 'var(--danger)' };
const AUTO_ADVANCE_MS = 1600;

/** Every detected obstacle is pre-confirmed (i.e. treated as real and
 * avoided) rather than left pending for an individual click. This is the
 * conservative direction, not a shortcut: a shape that turns out to be
 * nothing costs a little usable area, while silently ignoring a real one
 * risks a room drawn on top of an actual wall or column. Nothing here is
 * hidden — every item below is still visible with its evidence and can be
 * un-confirmed or ignored individually; this only changes what happens if
 * nobody touches it. */
function preConfirmObstacles(region: GeometryRegion): GeometryRegion {
  return {
    ...region,
    obstacles: region.obstacles.map(o => (o.status === 'PROPOSED' ? { ...o, status: 'CONFIRMED' as const } : o))
  };
}

function polygonAreaSqft(points: number[][]): number {
  // Shoelace formula — points_ft is already in real feet, same convention
  // every other area_sqft in this app uses.
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.round(Math.abs(sum) / 2 * 100) / 100;
}

function boundingBox(points: number[][]) {
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  return { min_x: Math.min(...xs), min_y: Math.min(...ys), max_x: Math.max(...xs), max_y: Math.max(...ys) };
}

export const GeometryReviewStep: React.FC<GeometryReviewStepProps> = ({ projectId, geometry, onConfirmed, onStartOver, initialRegionId }) => {
  const [regions, setRegions] = useState<GeometryRegion[]>(() => geometry.regions.map(preConfirmObstacles));
  const [activeRegionId, setActiveRegionId] = useState<string>(initialRegionId || geometry.regions[0]?.region_id || '');
  const [showCadLinework, setShowCadLinework] = useState(true);
  const [classifying, setClassifying] = useState(false);
  const [classifyNote, setClassifyNote] = useState<string | null>(null);

  // The AI-classify endpoint reads/writes the *persisted* geometry.json,
  // which never sees this screen's local confirm/ignore clicks until
  // onConfirmed runs — so its response is merged into local state obstacle
  // by obstacle (matched by stable id), touching only obstacles still
  // UNCLASSIFIED_OBSTACLE locally, rather than replacing `regions` wholesale
  // and silently discarding whatever the architect already did on this
  // screen. An obstacle AI left UNSURE (still UNCLASSIFIED_OBSTACLE in the
  // response) is left exactly as it was, honestly.
  const runAiClassify = async () => {
    setClassifying(true);
    setClassifyNote(null);
    try {
      const updated = await engine.aiClassifyGeometry(projectId);
      const byId = new Map<string, GeometryRegion['obstacles'][number]>();
      for (const r of updated.regions) {
        for (const o of r.obstacles) byId.set(o.id, o);
      }
      setRegions(prev => prev.map(r => ({
        ...r,
        obstacles: r.obstacles.map(o => {
          if (o.classification !== 'UNCLASSIFIED_OBSTACLE') return o;
          const aiResult = byId.get(o.id);
          if (!aiResult || aiResult.classification === 'UNCLASSIFIED_OBSTACLE') return o;
          return { ...o, classification: aiResult.classification, confidence: aiResult.confidence, status: aiResult.status, ai_note: aiResult.ai_note };
        })
      })));
      setClassifyNote((updated as any).ai_classification_note || 'AI classification applied.');
    } catch (e: any) {
      setClassifyNote(e.message || 'AI classification failed.');
    } finally {
      setClassifying(false);
    }
  };
  const [manualOverride, setManualOverride] = useState(false);
  const [autoFired, setAutoFired] = useState(false);
  const [drawingBoundary, setDrawingBoundary] = useState(regions.length === 0);

  const activeRegion = regions.find(r => r.region_id === activeRegionId);
  // The whole-drawing backdrop (present even when nothing was auto-detected)
  // falls back to whatever the currently-active detected region already had,
  // for older stored geometry from before this field existed.
  const backdropRawGeometry = geometry.raw_geometry ?? activeRegion?.raw_geometry ?? null;

  const handleManualBoundary = (points: number[][]) => {
    const newRegion: GeometryRegion = {
      region_id: `manual-${Date.now().toString(36)}`,
      boundary: {
        source_handle: 'manual', layer: 'manual', source: 'explicit',
        area_sqft: polygonAreaSqft(points), points_ft: points,
        bounding_box_ft: boundingBox(points), confidence: 'high', note: null, status: 'PROPOSED',
      },
      obstacles: [],
      text_labels: [],
      raw_geometry: backdropRawGeometry ?? undefined,
    };
    setRegions(prev => [...prev, newRegion]);
    setActiveRegionId(newRegion.region_id);
    setDrawingBoundary(false);
    setManualOverride(true); // a hand-drawn boundary always goes to the manual review screen, never auto-advances
  };

  // A boundary with no `note` is one the extractor itself has no reason to
  // doubt (a plausible size, and either an explicit closed polyline or a
  // wall-hinted reconstruction) — `note` is populated specifically to flag
  // the cases that need a second look (see cad_extraction.py). A boundary
  // that carries a note — an implausible size, or a reconstruction with no
  // wall-layer evidence behind it — always stops here for a human, in every
  // mode; that gate is never skipped.
  const boundaryIsClean = !!activeRegion && !activeRegion.boundary.note;
  // A hand-drawn boundary is never auto-advanced, full stop — checked
  // directly off the region id rather than through manualOverride, because
  // the effect below resets manualOverride on every activeRegionId change
  // (including the one handleManualBoundary itself triggers), which was
  // silently cancelling out setManualOverride(true) and letting a boundary
  // the user just hand-drew auto-confirm 1.6s later with no chance to
  // review it — found via a real click-through, not by inspection.
  const isHandDrawn = activeRegionId.startsWith('manual-');
  // Real bug found via a real upload (a file with no $INSUNITS set at all):
  // every area/distance the extractor reports is computed against an
  // assumed 1 drawing-unit = 1 ft scale when the real unit is unknown —
  // geometry.units.needs_user_confirmation is exactly the flag that says
  // so, but nothing here ever checked it, so a file like that could sail
  // through the "clean, no note" auto-advance path and get its (probably
  // wildly wrong-scale) boundary silently confirmed within 1.6s, before a
  // user could even look at what was detected. That reads as "the CAD file
  // isn't rendering" from the outside — it renders, but you're never shown
  // it before the app moves on.
  const unitsUnconfirmed = geometry.units.needs_user_confirmation;
  const autoMode = boundaryIsClean && !manualOverride && !isHandDrawn && !unitsUnconfirmed;

  useEffect(() => {
    setManualOverride(false);
    setAutoFired(false);
  }, [activeRegionId]);

  useEffect(() => {
    if (!autoMode || autoFired || !activeRegionId) return;
    const t = setTimeout(() => proceed(), AUTO_ADVANCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode, autoFired, activeRegionId]);

  const updateRegion = (updater: (r: GeometryRegion) => GeometryRegion) => {
    setRegions(prev => prev.map(r => (r.region_id === activeRegionId ? updater(r) : r)));
  };

  const confirmBoundary = () => updateRegion(r => ({ ...r, boundary: { ...r.boundary, status: 'CONFIRMED' } }));
  const setObstacleStatus = (obstacleId: string, status: 'CONFIRMED' | 'IGNORED') => {
    updateRegion(r => ({ ...r, obstacles: r.obstacles.map(o => (o.id === obstacleId ? { ...o, status } : o)) }));
  };
  const confirmAllHighConfidenceColumns = () => {
    updateRegion(r => ({
      ...r,
      obstacles: r.obstacles.map(o => (o.classification === 'COLUMN' && o.confidence === 'high' ? { ...o, status: 'CONFIRMED' } : o))
    }));
  };

  const proceed = () => {
    setAutoFired(true);
    const finalRegions = regions.map(r =>
      r.region_id === activeRegionId ? { ...r, boundary: { ...r.boundary, status: 'CONFIRMED' as const } } : r
    );
    onConfirmed(finalRegions, activeRegionId);
  };

  if (!activeRegion) {
    // No auto-detected region — not a dead end: the real CAD linework is
    // still there (geometry.raw_geometry covers the whole drawing precisely
    // for this case), so trace the boundary by hand directly over it instead
    // of forcing a re-upload.
    return (
      <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              No boundary was auto-detected in this file — trace it by hand over the real drawing below.
            </span>
            <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }} onClick={onStartOver}>
              <ArrowLeftIcon size={14} /> Upload a Different File
            </button>
          </div>
          <EditableCanvas
            boundaryPointsFt={[]}
            obstacles={[]}
            rooms={[]}
            selectedRoomId={null}
            onSelectRoom={() => {}}
            onLiveChange={() => {}}
            onCommit={() => {}}
            snapToGridFt={0}
            rawGeometry={backdropRawGeometry}
            showCadLinework
            drawMode
            onDrawComplete={handleManualBoundary}
          />
        </div>
        <div style={{ width: '360px' }}>
          <div className="panel" style={{ padding: '16px' }}>
            <div className="panel-label" style={{ marginBottom: '8px' }}>Draw the Floor Boundary</div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Click points along the real wall outline shown in the drawing, in order, tracing the boundary you want
              to zone. Click back near your first point (or press Enter) once you have at least 3 points to close
              it — Backspace undoes the last point, Escape clears and starts over.
            </p>
            {!backdropRawGeometry && (
              <div className="alert-box" style={{ marginTop: '10px', fontSize: '0.72rem' }}>
                This file has no recoverable linework at all to trace over — a re-export or a different file is the
                only option here.
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  const pendingObstacles = activeRegion.obstacles.filter(o => o.status === 'PROPOSED').length;
  const unclassifiedCount = activeRegion.obstacles.filter(o => o.classification === 'UNCLASSIFIED_OBSTACLE').length;
  const canProceed = activeRegion.boundary.status === 'CONFIRMED' && pendingObstacles === 0;

  const obstacleTally: Record<string, number> = {};
  for (const o of activeRegion.obstacles) {
    obstacleTally[o.classification] = (obstacleTally[o.classification] || 0) + 1;
  }

  // A real large multi-tenant file can legitimately produce dozens of
  // candidate regions (a real Vadodara-scale file: 100) — an unbounded
  // flex-wrap button row at that count floods the whole screen and crowds
  // out the floor plan itself (an earlier fix capped its height instead,
  // but a 100-item scrollable button list is still far more tedious to
  // search than a native dropdown). The button row is kept for the common
  // small-count case since it's a nicer, one-click switcher when there are
  // only a few.
  const regionSwitcher = regions.length > 1 && (
    regions.length > 8 ? (
      <select
        value={activeRegionId}
        onChange={(e) => setActiveRegionId(e.target.value)}
        style={{
          alignSelf: 'center', flex: '0 0 auto', background: 'var(--bg-raised)', color: 'var(--text-primary)',
          border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '5px 10px', fontSize: '0.75rem'
        }}
      >
        {regions.map((r, i) => (
          <option key={r.region_id} value={r.region_id}>
            Region {i + 1} · {r.boundary.area_sqft.toLocaleString()} sqft
          </option>
        ))}
      </select>
    ) : (
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'center', flex: '0 0 auto' }}>
        {regions.map(r => (
          <button
            key={r.region_id}
            onClick={() => setActiveRegionId(r.region_id)}
            className={r.region_id === activeRegionId ? 'btn btn-primary' : 'btn btn-secondary'}
            style={{ fontSize: '0.72rem', padding: '4px 10px' }}
          >
            Region {regions.indexOf(r) + 1} · {r.boundary.area_sqft.toLocaleString()} sqft
          </button>
        ))}
      </div>
    )
  );

  if (autoMode) {
    return (
      <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {regionSwitcher}
          <EditableCanvas
            boundaryPointsFt={activeRegion.boundary.points_ft}
            obstacles={activeRegion.obstacles}
            rooms={[]}
            selectedRoomId={null}
            onSelectRoom={() => {}}
            onLiveChange={() => {}}
            onCommit={() => {}}
            snapToGridFt={0}
            rawGeometry={activeRegion.raw_geometry}
            showCadLinework={showCadLinework}
          />
        </div>

        <div style={{ width: '360px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="panel" style={{ padding: '16px' }}>
            <div className="panel-label" style={{ marginBottom: '10px' }}>
              Detected Automatically
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: '4px' }} className="font-mono">
              Floor boundary — {activeRegion.boundary.area_sqft.toLocaleString()} sqft
            </div>
            <div style={{ fontSize: '0.72rem', color: CONF_COLOR[activeRegion.boundary.confidence], marginBottom: '14px' }}>
              Confidence: {activeRegion.boundary.confidence.toUpperCase()}
            </div>

            {activeRegion.obstacles.length > 0 ? (
              <>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)', marginBottom: '6px' }}>
                  {activeRegion.obstacles.length} obstacle{activeRegion.obstacles.length !== 1 ? 's' : ''} — will be avoided automatically
                </div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '14px', lineHeight: 1.7 }}>
                  {Object.entries(obstacleTally).map(([cls, n]) => (
                    <div key={cls}>{n}× {cls.replace(/_/g, ' ')}</div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>No obstacles detected inside this boundary.</div>
            )}

            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
              Generating your zoning layout automatically…
            </div>

            <button className="btn btn-primary" style={{ width: '100%', fontSize: '0.8rem', marginBottom: '8px' }} onClick={proceed}>
              Continue Now <ArrowRightIcon size={14} />
            </button>
            <button className="btn btn-secondary" style={{ width: '100%', fontSize: '0.75rem' }} onClick={() => setManualOverride(true)}>
              Review Detected Geometry Manually
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', height: '100%', gap: '12px', padding: '12px' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.72rem', color: 'var(--text-tertiary)', cursor: 'pointer' }}>
            <input type="checkbox" checked={showCadLinework} onChange={(e) => setShowCadLinework(e.target.checked)} />
            Show original CAD linework
            {activeRegion.raw_geometry?.truncated && (
              <span style={{ color: 'var(--warning)' }} title="This region has more entities than are shown — capped for performance.">
                (partial — capped for size)
              </span>
            )}
          </label>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }} onClick={() => setDrawingBoundary(v => !v)}>
              {drawingBoundary ? 'Cancel Drawing' : 'Draw Boundary Manually'}
            </button>
            <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }} onClick={onStartOver}>
              <RefreshIcon size={13} /> Replace CAD File
            </button>
          </div>
        </div>
        {drawingBoundary && (
          <div style={{ fontSize: '0.72rem', color: 'var(--brand-strong)' }}>
            Click points tracing the boundary you want instead — Enter or click near the first point to close, Esc to cancel.
          </div>
        )}
        {regionSwitcher}
        <EditableCanvas
          boundaryPointsFt={drawingBoundary ? [] : activeRegion.boundary.points_ft}
          obstacles={drawingBoundary ? [] : activeRegion.obstacles}
          rooms={[]}
          selectedRoomId={null}
          onSelectRoom={() => {}}
          onLiveChange={() => {}}
          onCommit={() => {}}
          snapToGridFt={0}
          rawGeometry={drawingBoundary ? backdropRawGeometry : activeRegion.raw_geometry}
          showCadLinework={showCadLinework}
          drawMode={drawingBoundary}
          onDrawComplete={handleManualBoundary}
        />
      </div>

      <div style={{ width: '360px', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
        {unitsUnconfirmed && (
          <div className="alert-box alert-error" style={{ fontSize: '0.75rem', lineHeight: 1.6 }}>
            <strong>This file doesn't specify real-world units</strong> ($INSUNITS is unset). Every area/distance
            below is computed assuming 1 drawing unit = 1 ft, which is very likely wrong — treat the numbers as
            unreliable until you've checked them against a known real dimension in the file (e.g. a labeled room
            size), and correct the file's units at the source (re-save/re-export with units set) if they're off.
          </div>
        )}
        {boundaryIsClean && (
          <div className="panel" style={{
            fontSize: '0.72rem', color: 'var(--text-tertiary)', padding: '8px 10px'
          }}>
            This geometry looked clean enough to proceed on its own. You asked to review it — nothing is confirmed
            until you confirm the boundary and resolve every obstacle below.
          </div>
        )}

        <div className="panel">
          <div className="panel-label" style={{ marginBottom: '8px' }}>Floor Boundary</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)', marginBottom: '4px' }} className="font-mono">
            {activeRegion.boundary.area_sqft.toLocaleString()} sqft — layer "{activeRegion.boundary.layer}"
          </div>
          <div style={{ fontSize: '0.72rem', color: CONF_COLOR[activeRegion.boundary.confidence], marginBottom: '10px' }}>
            Confidence: {activeRegion.boundary.confidence.toUpperCase()} (largest un-nested closed polyline{activeRegion.boundary.layer.toLowerCase().includes('wall') ? ', on a wall-hinted layer' : ''})
          </div>
          {activeRegion.boundary.note && (
            <div style={{
              display: 'flex', gap: '6px', fontSize: '0.72rem', color: 'var(--text-primary)', background: 'var(--danger-bg)',
              border: '1px solid rgba(209,109,100,0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', marginBottom: '10px'
            }}>
              <WarningIcon size={14} className="text-danger" style={{ flex: '0 0 auto', marginTop: '1px' }} />
              <span>{activeRegion.boundary.note}</span>
            </div>
          )}
          {activeRegion.boundary.status === 'CONFIRMED' ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: 'var(--success)', fontSize: '0.8rem', fontWeight: 600 }}>
              <CheckIcon size={14} /> Confirmed
            </span>
          ) : (
            <button className="btn btn-primary" style={{ fontSize: '0.78rem', width: '100%' }} onClick={confirmBoundary}>
              Confirm This Boundary
            </button>
          )}
        </div>

        <div className="panel" style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '6px' }}>
            <div className="panel-label">
              Detected Obstacles ({activeRegion.obstacles.length})
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {unclassifiedCount > 0 && (
                <button className="btn btn-secondary" style={{ fontSize: '0.68rem', padding: '2px 6px' }} disabled={classifying} onClick={runAiClassify}>
                  {classifying ? 'Classifying…' : `Classify ${unclassifiedCount} Unclassified with AI`}
                </button>
              )}
              <button className="btn btn-secondary" style={{ fontSize: '0.68rem', padding: '2px 6px' }} onClick={confirmAllHighConfidenceColumns}>
                Confirm all high-confidence columns
              </button>
            </div>
          </div>

          {classifyNote && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '8px', padding: '6px 8px', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
              {classifyNote}
            </div>
          )}

          {activeRegion.obstacles.length === 0 && <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>None detected inside this boundary.</div>}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {activeRegion.obstacles.map(o => (
              <div key={o.id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                  <span style={{ color: 'var(--text-primary)' }}>{o.classification.replace('_', ' ')}</span>
                  <span style={{ color: CONF_COLOR[o.confidence] }}>{o.confidence}</span>
                </div>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', marginBottom: '6px' }} className="font-mono">
                  {o.area_sqft} sqft · layer "{o.layer}" · handle {o.source_handle}
                </div>
                {o.ai_note && (
                  <div style={{ fontSize: '0.68rem', color: 'var(--brand-strong)', marginBottom: '6px', fontStyle: 'italic' }}>
                    {o.ai_note}
                  </div>
                )}
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    className={o.status === 'CONFIRMED' ? 'btn btn-primary' : 'btn btn-secondary'}
                    style={{ fontSize: '0.68rem', flex: 1, padding: '3px' }}
                    onClick={() => setObstacleStatus(o.id, 'CONFIRMED')}
                  >
                    {o.status === 'CONFIRMED' ? 'Confirmed' : 'Confirm'}
                  </button>
                  <button
                    className={o.status === 'IGNORED' ? 'btn btn-primary' : 'btn btn-secondary'}
                    style={{ fontSize: '0.68rem', flex: 1, padding: '3px' }}
                    onClick={() => setObstacleStatus(o.id, 'IGNORED')}
                  >
                    {o.status === 'IGNORED' ? 'Ignored' : 'Ignore'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <button
          className="btn btn-primary"
          disabled={!canProceed}
          title={!canProceed ? 'Confirm the boundary and resolve every obstacle (Confirm or Ignore) first' : ''}
          style={{ fontSize: '0.85rem', padding: '8px' }}
          onClick={() => onConfirmed(regions, activeRegionId)}
        >
          {canProceed ? <>Continue to Requirements <ArrowRightIcon size={14} /></> : `Resolve ${pendingObstacles} obstacle(s) + confirm boundary to continue`}
        </button>
      </div>
    </div>
  );
};
