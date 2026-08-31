import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getProjects, createProject, logout, Project } from '../api';

export const ProjectsPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const fetchProjectsList = async () => {
    try {
      const data = await getProjects();
      setProjects(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjectsList();
  }, []);

  const handleCreateProject = async () => {
    setCreating(true);
    try {
      const newProj = await createProject();
      navigate(`/projects/${newProj.id}/intake`);
    } catch (err: any) {
      setError(err.message || 'Failed to create project');
      setCreating(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
      navigate('/login');
    } catch {
      navigate('/login');
    }
  };

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          <button onClick={handleLogout} className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            Log Out
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="page-header">
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700 }}>Projects Dashboard</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              Manage property intake and zoning plans
            </p>
          </div>
          <button
            onClick={handleCreateProject}
            disabled={creating}
            className="btn btn-primary"
            id="create-project-btn"
          >
            {creating ? 'Creating...' : '+ Create New Project'}
          </button>
        </div>

        {error && <div className="alert-box alert-error">{error}</div>}

        {loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading projects...</p>
        ) : projects.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '3rem',
            background: 'var(--bg-secondary)',
            borderRadius: '8px',
            border: '1px solid var(--border-color)'
          }}>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>No projects created yet.</p>
            <button onClick={handleCreateProject} className="btn btn-primary">
              Create Your First Project
            </button>
          </div>
        ) : (
          <div className="project-grid">
            {projects.map((project) => (
              <div key={project.id} className="project-card">
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span className="project-code-badge">Project #{project.project_code}</span>
                    <span className={`badge ${project.is_intake_complete ? 'badge-complete' : 'badge-incomplete'}`}>
                      {project.is_intake_complete ? 'Intake complete: Yes' : 'Intake complete: No'}
                    </span>
                  </div>
                  <h2 style={{ fontSize: '1.2rem', marginBottom: '0.5rem' }}>
                    {project.property_name || 'Untitled Property'}
                  </h2>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                    <strong>Client:</strong> {project.client_name || '—'}
                  </p>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    <strong>Location:</strong> {project.city ? `${project.city}, ${project.state || ''}` : '—'}
                  </p>
                </div>
                <div style={{ marginTop: '1.25rem', display: 'flex', justifyContent: 'flex-end' }}>
                  <Link
                    to={`/projects/${project.id}/intake`}
                    className="btn btn-secondary"
                    style={{ width: '100%', textAlign: 'center' }}
                  >
                    Open Intake Form
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};
