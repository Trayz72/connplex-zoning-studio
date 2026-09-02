import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getProjects, getProjectFilterOptions, createProject, deleteProject, logout, Project, ProjectFilterOptions } from '../api';
import { deleteProjectData } from '../services/zoningEngineApi';
import { useAuth } from '../AuthContext';
import { EmptyIcon, TrashIcon } from '../components/Icons';
import { ThemeToggle } from '../components/ThemeToggle';

export const ProjectsPage: React.FC = () => {
  const { user, refresh } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [cityFilter, setCityFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [filterOptions, setFilterOptions] = useState<ProjectFilterOptions>({ cities: [], states: [], statuses: [] });
  const navigate = useNavigate();

  const fetchProjectsList = async () => {
    try {
      const data = await getProjects({ q: search, city: cityFilter, state: stateFilter, status: statusFilter });
      setProjects(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  // Debounce the free-text search so we're not firing a request per
  // keystroke; dropdown filters apply immediately since they're discrete.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    fetchProjectsList();
  }, [search, cityFilter, stateFilter, statusFilter]);

  useEffect(() => {
    getProjectFilterOptions().then(setFilterOptions).catch(() => {});
  }, [projects.length]);

  const hasActiveFilters = Boolean(search || cityFilter || stateFilter || statusFilter);
  const clearFilters = () => {
    setSearchInput(''); setSearch(''); setCityFilter(''); setStateFilter(''); setStatusFilter('');
  };

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
            <>
              <Link to="/admin/rules" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
                Rules &amp; Config
              </Link>
              <Link to="/admin" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
                Manage Users
              </Link>
            </>
          )}
          <ThemeToggle />
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

        <div className="filter-bar">
          <input
            type="text"
            className="form-control"
            placeholder="Search by property, client, or project #…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            style={{ flex: '1 1 240px', minWidth: 0 }}
          />
          <select className="form-control" value={cityFilter} onChange={(e) => setCityFilter(e.target.value)} style={{ flex: '0 1 160px' }}>
            <option value="">All cities</option>
            {filterOptions.cities.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className="form-control" value={stateFilter} onChange={(e) => setStateFilter(e.target.value)} style={{ flex: '0 1 160px' }}>
            <option value="">All states</option>
            {filterOptions.states.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="form-control" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ flex: '0 1 180px' }}>
            <option value="">All statuses</option>
            {filterOptions.statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          {hasActiveFilters && (
            <button className="btn btn-secondary" style={{ fontSize: '0.82rem' }} onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>

        {error && <div className="alert-box alert-error">{error}</div>}

        {loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading projects…</p>
        ) : projects.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true"><EmptyIcon /></div>
            {hasActiveFilters ? (
              <>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>No projects match these filters.</p>
                <button onClick={clearFilters} className="btn btn-secondary">Clear filters</button>
              </>
            ) : (
              <>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>No projects created yet.</p>
                <button onClick={handleCreateProject} className="btn btn-primary">
                  Create Your First Project
                </button>
              </>
            )}
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
                      <TrashIcon />
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
