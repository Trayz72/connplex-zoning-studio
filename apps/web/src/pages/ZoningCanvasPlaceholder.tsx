import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ReviewRevisionWorkflow } from './ReviewRevisionWorkflow';

export const ZoningCanvasPlaceholder: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<'review' | 'canvas'>('review');

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          <button
            onClick={() => setActiveTab('review')}
            className={`btn ${activeTab === 'review' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}
          >
            Review &amp; Revision (M6/M7)
          </button>
          <button
            onClick={() => setActiveTab('canvas')}
            className={`btn ${activeTab === 'canvas' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}
          >
            Canvas Editor
          </button>
          {id && (
            <Link to={`/projects/${id}/intake`} className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
              ← Back to Intake
            </Link>
          )}
          <Link to="/projects" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            All Projects
          </Link>
        </div>
      </header>

      {activeTab === 'review' ? (
        <main className="main-content" style={{ padding: '1rem 0' }}>
          <ReviewRevisionWorkflow />
        </main>
      ) : (
        <main className="main-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
          <div style={{
            textAlign: 'center',
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '8px',
            padding: '3rem 2rem',
            maxWidth: '500px',
            width: '100%'
          }}>
            <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', color: 'var(--text-primary)' }}>
              Zoning canvas coming later
            </h2>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
              This placeholder indicates the zoning canvas editor module, which will be implemented in a subsequent milestone.
            </p>
            {id && (
              <Link to={`/projects/${id}/intake`} className="btn btn-primary">
                Return to Project Intake
              </Link>
            )}
          </div>
        </main>
      )}
    </div>
  );
};
