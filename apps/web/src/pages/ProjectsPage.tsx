import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getProjects, createProject, deleteProject, logout, Project } from '../api';
import { deleteProjectData } from '../services/zoningEngineApi';
import { useAuth } from '../AuthContext';

export const ProjectsPage: React.FC = () => {
  const { user, refresh } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
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

  const handleDeleteProject = async (id: string) => {
    setDeletingId(id);
    setError(null);
    try {
      await deleteProject(id);
      await deleteProjectData(id);
      setProjects(prev => prev.filter(p => p.id !== id));
    } catch (err: any) {
      setError(err.message || 'Failed to delete project');
    } finally {
      setDeletingId(null);
      setConfirmingDeleteId(null);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // fall through — clear local auth state and navigate away regardless
    }
    await refresh();
    navigate('/login');
  };

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          <span className="brand-mark">CZ</span>
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          {user && (
            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              {user.email}{user.is_admin && <span className="admin-tag">Admin</span>}
            </span>
          )}
          {user?.is_admin && (
            <Link to="/admin" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
              Manage Users
            </Link>
          )}
          <button onClick={handleLogout} className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            Log Out
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="page-header">
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700 }}>Projects</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              {loading ? 'Manage property intake and zoning plans' :
                `${projects.length} project${projects.length === 1 ? '' : 's'} — manage property intake and zoning plans`}
            </p>
          </div>
          <button
            onClick={handleCreateProject}
            disabled={creating}
            className="btn btn-primary"
            id="create-project-btn"
          >
            {creating ? 'Creating…' : '+ Create New Project'}
          </button>
        </div>

        {error && <div className="alert-box alert-error">{error}</div>}

        {loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading projects…</p>
        ) : projects.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true">⬚</div>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>No projects created yet.</p>
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
                    <span className="project-code-badge">#{project.project_code}</span>
                    <span className={`badge ${project.is_intake_complete ? 'badge-complete' : 'badge-incomplete'}`}>
                      {project.is_intake_complete ? 'Intake complete' : 'Intake pending'}
                    </span>
                  </div>
                  <h2 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: '0.6rem' }}>
                    {project.property_name || 'Untitled Property'}
                  </h2>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                    <strong style={{ color: 'var(--text-primary)' }}>Client:</strong> {project.client_name || '—'}
                  </p>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    <strong style={{ color: 'var(--text-primary)' }}>Location:</strong> {project.city ? `${project.city}, ${project.state || ''}` : '—'}
                  </p>
                </div>

                {confirmingDeleteId === project.id ? (
                  <div className="project-card-confirm">
                    <span>Delete this project? This can't be undone.</span>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        className="btn btn-danger"
                        style={{ flex: 1 }}
                        disabled={deletingId === project.id}
                        onClick={() => handleDeleteProject(project.id)}
                      >
                        {deletingId === project.id ? 'Deleting…' : 'Delete'}
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ flex: 1 }}
                        disabled={deletingId === project.id}
                        onClick={() => setConfirmingDeleteId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ marginTop: '1.25rem', display: 'flex', gap: '0.5rem' }}>
                    <Link
                      to={`/projects/${project.id}/intake`}
                      className="btn btn-secondary"
                      style={{ flex: 1, textAlign: 'center' }}
                    >
                      Open
                    </Link>
                    <button
                      className="btn btn-icon-danger"
                      title="Delete project"
                      aria-label="Delete project"
                      onClick={() => setConfirmingDeleteId(project.id)}
                    >
                      🗑
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};
