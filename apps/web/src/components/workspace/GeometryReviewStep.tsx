import React, { useEffect, useState } from 'react';
import { GeometryResult, GeometryRegion } from '../../types/live';
import { EditableCanvas } from './EditableCanvas';
import { ArrowLeftIcon, ArrowRightIcon, RefreshIcon, WarningIcon, CheckIcon } from '../Icons';

interface GeometryReviewStepProps {
  geometry: GeometryResult;
  onConfirmed: (regions: GeometryRegion[], selectedRegionId: string) => void;
  onStartOver: () => void;
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

export const GeometryReviewStep: React.FC<GeometryReviewStepProps> = ({ geometry, onConfirmed, onStartOver }) => {
  const [regions, setRegions] = useState<GeometryRegion[]>(() => geometry.regions.map(preConfirmObstacles));
  const [activeRegionId, setActiveRegionId] = useState<string>(geometry.regions[0]?.region_id || '');
  const [showCadLinework, setShowCadLinework] = useState(true);
  const [manualOverride, setManualOverride] = useState(false);
  const [autoFired, setAutoFired] = useState(false);

  const activeRegion = regions.find(r => r.region_id === activeRegionId);

  // A boundary with no `note` is one the extractor itself has no reason to
  // doubt (a plausible size, and either an explicit closed polyline or a
  // wall-hinted reconstruction) — `note` is populated specifically to flag
  // the cases that need a second look (see cad_extraction.py). A boundary
  // that carries a note — an implausible size, or a reconstruction with no
  // wall-layer evidence behind it — always stops here for a human, in every
  // mode; that gate is never skipped.
  const boundaryIsClean = !!activeRegion && !activeRegion.boundary.note;
  const autoMode = boundaryIsClean && !manualOverride;

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
    return (
      <div style={{ padding: '3rem', textAlign: 'center' }}>
        <div style={{ color: 'var(--danger)', marginBottom: '1.25rem' }}>
          No candidate floor-plan regions were found in this file (no closed polyline above the minimum boundary
          area was detected). Try a cleaner export, or a file with an explicit closed wall/boundary polyline.
        </div>
        <button className="btn btn-primary" onClick={onStartOver}>
          <ArrowLeftIcon size={14} /> Upload a Different File
        </button>
      </div>
    );
  }

  const pendingObstacles = activeRegion.obstacles.filter(o => o.status === 'PROPOSED').length;
  const canProceed = activeRegion.boundary.status === 'CONFIRMED' && pendingObstacles === 0;

  const obstacleTally: Record<string, number> = {};
  for (const o of activeRegion.obstacles) {
    obstacleTally[o.classification] = (obstacleTally[o.classification] || 0) + 1;
  }

  const regionSwitcher = regions.length > 1 && (
    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'center' }}>
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
          <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '3px 8px' }} onClick={onStartOver}>
            <RefreshIcon size={13} /> Replace CAD File
          </button>
        </div>
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

      <div style={{ width: '360px', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div className="panel-label">
              Detected Obstacles ({activeRegion.obstacles.length})
            </div>
            <button className="btn btn-secondary" style={{ fontSize: '0.68rem', padding: '2px 6px' }} onClick={confirmAllHighConfidenceColumns}>
              Confirm all high-confidence columns
            </button>
          </div>

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
