import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { getProject, updateProject, Project } from '../api';

export const ProjectIntakePage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Form fields
  const [formData, setFormData] = useState({
    property_name: '',
    client_name: '',
    client_mobile: '',
    client_email: '',
    google_location: '',
    city: '',
    state: '',
    property_source: '',
    floor_shop_no: '',
    property_status: '',
    beam_bottom_clear_height: '',
    property_type: ''
  });

  const loadProject = async () => {
    if (!id) return;
    try {
      setLoading(true);
      const data = await getProject(id);
      setProject(data);
      setFormData({
        property_name: data.property_name || '',
        client_name: data.client_name || '',
        client_mobile: data.client_mobile || '',
        client_email: data.client_email || '',
        google_location: data.google_location || '',
        city: data.city || '',
        state: data.state || '',
        property_source: data.property_source || '',
        floor_shop_no: data.floor_shop_no || '',
        property_status: data.property_status || '',
        beam_bottom_clear_height: data.beam_bottom_clear_height || '',
        property_type: data.property_type || ''
      });
    } catch (err: any) {
      setError(err.message || 'Failed to load project');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProject();
  }, [id]);

  const handleChange = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setSaveSuccess(false);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setError(null);
    setSaving(true);
    setSaveSuccess(false);

    try {
      const updated = await updateProject(id, formData);
      setProject(updated);
      setSaveSuccess(true);
    } catch (err: any) {
      setError(err.message || 'Failed to save intake fields');
    } finally {
      setSaving(false);
    }
  };

  const handleGoToCanvas = () => {
    if (project?.is_intake_complete) {
      navigate(`/projects/${id}/canvas`);
    }
  };

  if (loading) {
    return (
      <div className="app-container">
        <main className="main-content">
          <p style={{ color: 'var(--text-secondary)' }}>Loading project intake form...</p>
        </main>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="app-container">
        <main className="main-content">
          <div className="alert-box alert-error">Project not found</div>
          <Link to="/projects" className="btn btn-secondary">Back to Projects</Link>
        </main>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          <Link to="/projects" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            ← All Projects
          </Link>
        </div>
      </header>

      <main className="main-content">
        <div className="intake-header">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
              <span className="project-code-badge">Project #{project.project_code}</span>
              <h1 style={{ fontSize: '1.6rem', fontWeight: 700 }}>
                {project.property_name || 'New Project Intake'}
              </h1>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              Fill in all property details to unlock the zoning canvas
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div className="tooltip-wrapper">
              <button
                id="go-to-canvas-btn"
                type="button"
                onClick={handleGoToCanvas}
                disabled={!project.is_intake_complete}
                className="btn btn-primary"
                title={!project.is_intake_complete ? 'Complete all intake fields first' : 'Go to Zoning Canvas'}
              >
                Go to Zoning Canvas
              </button>
              {!project.is_intake_complete && (
                <span className="tooltip-text">Complete all intake fields first</span>
              )}
            </div>
          </div>
        </div>

        <div className="intake-status-bar">
          <div>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginRight: '0.5rem' }}>Status:</span>
            <span
              id="intake-status-text"
              className={`badge ${project.is_intake_complete ? 'badge-complete' : 'badge-incomplete'}`}
              style={{ fontSize: '0.9rem', padding: '0.35rem 0.75rem' }}
            >
              Intake complete: {project.is_intake_complete ? 'Yes' : 'No'}
            </span>
          </div>

          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Project Code: <strong style={{ color: 'var(--text-primary)' }}>{project.project_code}</strong>
          </div>
        </div>

        {error && <div className="alert-box alert-error">{error}</div>}
        {saveSuccess && <div className="alert-box alert-success">Intake fields saved successfully!</div>}

        <form onSubmit={handleSave}>
          <div className="intake-grid">
            <div className="form-group">
              <label htmlFor="property_name">Property Name *</label>
              <input
                id="property_name"
                name="property_name"
                type="text"
                className="form-control"
                value={formData.property_name}
                onChange={(e) => handleChange('property_name', e.target.value)}
                placeholder="e.g. Connplex Tower"
              />
            </div>

            <div className="form-group">
              <label htmlFor="client_name">Client Name *</label>
              <input
                id="client_name"
                name="client_name"
                type="text"
                className="form-control"
                value={formData.client_name}
                onChange={(e) => handleChange('client_name', e.target.value)}
                placeholder="e.g. John Doe"
              />
            </div>

            <div className="form-group">
              <label htmlFor="client_mobile">Client Mobile *</label>
              <input
                id="client_mobile"
                name="client_mobile"
                type="text"
                className="form-control"
                value={formData.client_mobile}
                onChange={(e) => handleChange('client_mobile', e.target.value)}
                placeholder="e.g. +91 9876543210"
              />
            </div>

            <div className="form-group">
              <label htmlFor="client_email">Client Email *</label>
              <input
                id="client_email"
                name="client_email"
                type="text"
                className="form-control"
                value={formData.client_email}
                onChange={(e) => handleChange('client_email', e.target.value)}
                placeholder="e.g. client@example.com"
              />
            </div>

            <div className="form-group">
              <label htmlFor="google_location">Google Location *</label>
              <input
                id="google_location"
                name="google_location"
                type="text"
                className="form-control"
                value={formData.google_location}
                onChange={(e) => handleChange('google_location', e.target.value)}
                placeholder="e.g. https://maps.google.com/..."
              />
            </div>

            <div className="form-group">
              <label htmlFor="city">City *</label>
              <input
                id="city"
                name="city"
                type="text"
                className="form-control"
                value={formData.city}
                onChange={(e) => handleChange('city', e.target.value)}
                placeholder="e.g. Mumbai"
              />
            </div>

            <div className="form-group">
              <label htmlFor="state">State *</label>
              <input
                id="state"
                name="state"
                type="text"
                className="form-control"
                value={formData.state}
                onChange={(e) => handleChange('state', e.target.value)}
                placeholder="e.g. Maharashtra"
              />
            </div>

            <div className="form-group">
              <label htmlFor="property_source">Property Source *</label>
              <select
                id="property_source"
                name="property_source"
                className="form-control"
                value={formData.property_source}
                onChange={(e) => handleChange('property_source', e.target.value)}
              >
                <option value="">Select source</option>
                <option value="Broker">Broker</option>
                <option value="Direct">Direct</option>
                <option value="Developer">Developer</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="floor_shop_no">Floor / Shop No *</label>
              <input
                id="floor_shop_no"
                name="floor_shop_no"
                type="text"
                className="form-control"
                value={formData.floor_shop_no}
                onChange={(e) => handleChange('floor_shop_no', e.target.value)}
                placeholder="e.g. 2nd Floor, Unit 201"
              />
            </div>

            <div className="form-group">
              <label htmlFor="property_status">Property Status *</label>
              <select
                id="property_status"
                name="property_status"
                className="form-control"
                value={formData.property_status}
                onChange={(e) => handleChange('property_status', e.target.value)}
              >
                <option value="">Select status</option>
                <option value="Under Construction">Under Construction</option>
                <option value="Ready">Ready</option>
                <option value="Shell">Shell</option>
                <option value="Bare">Bare</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="beam_bottom_clear_height">Beam Bottom Clear Height *</label>
              <input
                id="beam_bottom_clear_height"
                name="beam_bottom_clear_height"
                type="text"
                className="form-control"
                value={formData.beam_bottom_clear_height}
                onChange={(e) => handleChange('beam_bottom_clear_height', e.target.value)}
                placeholder="e.g. 3.5m"
              />
            </div>

            <div className="form-group">
              <label htmlFor="property_type">Property Type *</label>
              <select
                id="property_type"
                name="property_type"
                className="form-control"
                value={formData.property_type}
                onChange={(e) => handleChange('property_type', e.target.value)}
              >
                <option value="">Select type</option>
                <option value="Existing Building">Existing Building</option>
                <option value="Bare Shell">Bare Shell</option>
                <option value="Open Land">Open Land</option>
              </select>
            </div>
          </div>

          <div className="form-actions">
            <Link to="/projects" className="btn btn-secondary">
              Back to Projects
            </Link>
            <button
              id="save-intake-btn"
              type="submit"
              disabled={saving}
              className="btn btn-primary"
            >
              {saving ? 'Saving...' : 'Save Intake Details'}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
};
