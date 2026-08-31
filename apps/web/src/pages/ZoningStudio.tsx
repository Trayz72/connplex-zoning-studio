import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { FloorRegionData, CandidateData, RoomData, LayerVisibility, CadUploadState } from '../types/zoning';
import { fetchZoningStudioData } from '../services/cadService';
import { FloorNavigator } from '../components/zoning/FloorNavigator';
import { ZoningCanvas } from '../components/zoning/ZoningCanvas';
import { CandidatePanel } from '../components/zoning/CandidatePanel';
import { RoomInspector } from '../components/zoning/RoomInspector';
import { ValidationPanel } from '../components/zoning/ValidationPanel';
import { RevisionPanel } from '../components/zoning/RevisionPanel';
import { DecisionPanel } from '../components/zoning/DecisionPanel';
import { CadUploadModal } from '../components/zoning/CadUploadModal';
import { CandidateCompareModal } from '../components/zoning/CandidateCompareModal';
import { AreaSeatChartPanel } from '../components/zoning/AreaSeatChartPanel';

export const ZoningStudio: React.FC = () => {
  const { id } = useParams<{ id: string }>();

  const [floors, setFloors] = useState<FloorRegionData[]>([]);
  const [selectedFloorId, setSelectedFloorId] = useState<string>('dhule-first-floor');
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>('');
  const [selectedRoom, setSelectedRoom] = useState<RoomData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Modals
  const [isUploadOpen, setIsUploadOpen] = useState<boolean>(false);
  const [isCompareOpen, setIsCompareOpen] = useState<boolean>(false);

  // Upload State
  const [cadState, setCadState] = useState<CadUploadState>({
    file: {
      name: '1022_MARUTI_NANDAN_DHULE_ZONING.dwg',
      size: 4404019,
      formattedSize: '4.2 MB'
    },
    status: 'SUCCESS',
    currentStepIndex: 7,
    steps: [],
    errorMessage: null,
    isDemoData: false
  });

  // Layer Toggles
  const [layers, setLayers] = useState<LayerVisibility>({
    cadLinework: true,
    verifiedBoundary: true,
    generatedRooms: true,
    circulation: true,
    columns: true,
    hardObstructions: true,
    uncertainGeometry: true,
    reviewRequired: true,
    dimensions: false,
    provenance: false
  });

  useEffect(() => {
    fetchZoningStudioData()
      .then((data) => {
        setFloors(data);
        if (data.length > 0) {
          const ready = data.find(f => !f.is_blocked) || data[0];
          setSelectedFloorId(ready.region_id);
          setSelectedCandidateId(ready.selected_candidate_id);
          if (ready.rooms && ready.rooms.length > 0) {
            setSelectedRoom(ready.rooms[0]);
          }
        }
        setIsLoading(false);
      })
      .catch((err) => {
        setLoadError(err.message || 'Failed to load CAD and zoning records.');
        setIsLoading(false);
      });
  }, []);

  const activeFloor = floors.find(f => f.region_id === selectedFloorId) || floors[0];
  const activeCandidate = activeFloor?.candidates?.find(c => c.candidate_id === selectedCandidateId) || activeFloor?.candidates?.[0] || null;

  const handleSelectFloor = (floor: FloorRegionData) => {
    setSelectedFloorId(floor.region_id);
    if (!floor.is_blocked && floor.candidates.length > 0) {
      setSelectedCandidateId(floor.selected_candidate_id || floor.candidates[0].candidate_id);
      setSelectedRoom(floor.rooms[0] || null);
    } else {
      setSelectedCandidateId('');
      setSelectedRoom(null);
    }
  };

  const handleSelectCandidate = (candidate: CandidateData) => {
    setSelectedCandidateId(candidate.candidate_id);
    if (candidate.rooms && candidate.rooms.length > 0) {
      setSelectedRoom(candidate.rooms[0]);
    }
  };

  const toggleLayer = (layerKey: keyof LayerVisibility) => {
    setLayers(prev => ({ ...prev, [layerKey]: !prev[layerKey] }));
  };

  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#0d1117', color: '#f0f6fc' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>📐</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>Loading CAD &amp; Zoning Studio...</div>
        <div style={{ fontSize: '0.8rem', color: '#8b949e', marginTop: '0.5rem' }}>Loading multi-region geometry and candidate layouts</div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#0d1117', color: '#f85149', padding: '2rem' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>✕</div>
        <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>Unable to Load Zoning Studio</div>
        <div style={{ fontSize: '0.85rem', color: '#f0f6fc', marginTop: '0.5rem', maxWidth: '500px', textAlign: 'center' }}>{loadError}</div>
        <button onClick={() => window.location.reload()} className="btn btn-primary" style={{ marginTop: '1.5rem' }}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0d1117', color: '#f0f6fc', overflow: 'hidden' }}>
      
      {/* 1. Project Header Bar */}
      <header style={{ height: '52px', background: '#161b22', borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px', zIndex: 100 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link to="/projects" style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f0f6fc', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🏢</span> Connplex Zoning Studio
          </Link>
          <div style={{ height: '18px', width: '1px', background: '#30363d' }}></div>
          <span style={{ fontSize: '0.82rem', color: '#8b949e' }}>Project #{id ? id.slice(0, 8) : '1022'}</span>
          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#f0f6fc' }}>Dhule Cinema Hub</span>
        </div>

        {/* Center: CAD Drawing Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '4px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: cadState.status === 'SUCCESS' ? '#238636' : '#d29922' }}></span>
            <span>{cadState.file ? cadState.file.name : 'No Drawing Uploaded'}</span>
            <span style={{ color: '#8b949e' }}>({cadState.file ? cadState.file.formattedSize : ''})</span>
          </div>

          <button
            onClick={() => setIsUploadOpen(true)}
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '4px 10px' }}
          >
            [ Upload / Replace DWG ]
          </button>
        </div>

        {/* Right Navigation Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {id && (
            <Link to={`/projects/${id}/intake`} className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '4px 10px' }}>
              ← Project Intake
            </Link>
          )}
          <Link to="/projects" className="btn btn-secondary" style={{ fontSize: '0.75rem', padding: '4px 10px' }}>
            All Projects
          </Link>
        </div>
      </header>

      {/* 2. Main Studio Workspace Layout */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        
        {/* Left Navigator (Floors & Plans) */}
        <FloorNavigator
          floors={floors}
          selectedFloorId={selectedFloorId}
          onSelectFloor={handleSelectFloor}
        />

        {/* Center: Canvas Workspace + Layers Toolbar */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '8px', gap: '8px' }}>
          
          {/* Top Layer Control Bar */}
          <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '6px', padding: '6px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
              Layer Controls:
            </div>
            <div style={{ display: 'flex', gap: '10px', fontSize: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.cadLinework} onChange={() => toggleLayer('cadLinework')} />
                <span>CAD Linework</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.verifiedBoundary} onChange={() => toggleLayer('verifiedBoundary')} />
                <span style={{ color: '#3fb950' }}>Verified Boundary</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.generatedRooms} onChange={() => toggleLayer('generatedRooms')} />
                <span style={{ color: '#58a6ff' }}>Rooms</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.circulation} onChange={() => toggleLayer('circulation')} />
                <span style={{ color: '#e2e8f0' }}>Circulation</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.columns} onChange={() => toggleLayer('columns')} />
                <span style={{ color: '#f85149' }}>Columns</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.uncertainGeometry} onChange={() => toggleLayer('uncertainGeometry')} />
                <span style={{ color: '#d29922' }}>Uncertain Geometries</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={layers.dimensions} onChange={() => toggleLayer('dimensions')} />
                <span>Dimensions</span>
              </label>
            </div>
          </div>

          {/* Central Interactive Zoning Canvas */}
          <ZoningCanvas
            floor={activeFloor}
            candidate={activeCandidate}
            selectedRoom={selectedRoom}
            onSelectRoom={setSelectedRoom}
            layers={layers}
          />
        </div>

        {/* Right Sidebar: Contextual Inspector & Action Panels */}
        <div style={{ width: '380px', background: '#161b22', borderLeft: '1px solid #30363d', display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto', padding: '12px' }}>
          
          {/* Candidate Selection & Scores */}
          {!activeFloor.is_blocked && activeFloor.candidates.length > 0 && (
            <CandidatePanel
              candidates={activeFloor.candidates}
              selectedCandidateId={selectedCandidateId}
              onSelectCandidate={handleSelectCandidate}
              onOpenCompare={() => setIsCompareOpen(true)}
            />
          )}

          {/* Room Inspector */}
          {!activeFloor.is_blocked && (
            <RoomInspector
              room={selectedRoom}
              onClose={() => setSelectedRoom(null)}
            />
          )}

          {/* Area & Seat Chart (M8) */}
          {!activeFloor.is_blocked && (
            <AreaSeatChartPanel chart={activeFloor.area_seat_chart} />
          )}

          {/* Automated Validation Panel */}
          <ValidationPanel
            hasReviewRequired={activeFloor.has_review_required}
            feasibility={activeFloor.feasibility}
          />

          {/* Parametric Revision Workflow (M7) */}
          {!activeFloor.is_blocked && (
            <RevisionPanel
              floor={activeFloor}
              candidate={activeCandidate}
            />
          )}

          {/* Human Review Decision Workflow (M6/M8) */}
          {!activeFloor.is_blocked && (
            <DecisionPanel
              floor={activeFloor}
              candidate={activeCandidate}
              onRecordDecision={(dec) => {
                alert(`Human review decision recorded: [${dec.decision}] by ${dec.reviewer_name}`);
              }}
            />
          )}

        </div>

      </div>

      {/* Upload Modal Dialog */}
      <CadUploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={(newState) => {
          setCadState(newState);
        }}
      />

      {/* Multi-Candidate Side-by-Side Comparison Modal */}
      {!activeFloor.is_blocked && (
        <CandidateCompareModal
          isOpen={isCompareOpen}
          onClose={() => setIsCompareOpen(false)}
          candidates={activeFloor.candidates}
          selectedCandidateId={selectedCandidateId}
          onSelectCandidate={handleSelectCandidate}
        />
      )}

    </div>
  );
};
