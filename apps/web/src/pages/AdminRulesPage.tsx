import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getRulesConfig, saveRulesCategory, RulesRegistry, RulesCategory, RULES_CATEGORIES, RulesConfigConflictError } from '../api';
import { BlockedIcon, TrashIcon } from '../components/Icons';
import { ThemeToggle } from '../components/ThemeToggle';

const CATEGORY_LABEL: Record<RulesCategory, string> = {
  seat_types: 'Seat Types',
  auditorium_presets: 'Auditorium Presets',
  franchise_tiers: 'Franchise Tiers',
  planning_norms: 'Planning Norms',
  viability_rules: 'Viability Rules'
};

const PK_FIELD: Record<RulesCategory, string> = {
  seat_types: 'id', auditorium_presets: 'id', franchise_tiers: 'id', planning_norms: 'id', viability_rules: 'rule_id'
};

// A few summary columns per category, just for the collapsed row — everything
// is visible (and editable) in the expanded raw-JSON view regardless.
const SUMMARY_FIELDS: Record<RulesCategory, string[]> = {
  seat_types: ['name', 'category', 'width_in_before_slide'],
  auditorium_presets: ['name', 'target_seats', 'min_area_sqft'],
  franchise_tiers: ['name', 'foyer_to_screen_ratio'],
  planning_norms: ['value', 'unit', 'description'],
  viability_rules: ['metric', 'operator', 'threshold', 'severity']
};

const APPROVAL_COLOR: Record<string, string> = {
  SOURCE_BACKED: 'var(--success)', DECIDED: 'var(--success)', ENGINEERING_ASSUMPTION: 'var(--warning)', PROPOSED: 'var(--text-tertiary)'
};

function newBlankRecord(category: RulesCategory): any {
  const pk = PK_FIELD[category];
  return { [pk]: '', approval_status: 'PROPOSED', source: 'ADMIN_UI_MANUAL_ENTRY' };
}

export const AdminRulesPage: React.FC = () => {
  const [registry, setRegistry] = useState<RulesRegistry | null>(null);
  const [category, setCategory] = useState<RulesCategory>('seat_types');
  const [items, setItems] = useState<any[]>([]);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [draftJson, setDraftJson] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [conflict, setConflict] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getRulesConfig();
      setRegistry(data);
    } catch (err: any) {
      if (err.message && err.message.includes('Admin')) setForbidden(true);
      else setError(err.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (registry) setItems(registry[category] || []);
    setExpandedIndex(null);
  }, [registry, category]);

  const isDirty = registry ? JSON.stringify(items) !== JSON.stringify(registry[category] || []) : false;

  const expand = (i: number) => {
    setExpandedIndex(i);
    setDraftJson(JSON.stringify(items[i], null, 2));
    setJsonError(null);
  };

  const applyDraft = () => {
    try {
      const parsed = JSON.parse(draftJson);
      const next = [...items];
      next[expandedIndex!] = parsed;
      setItems(next);
      setExpandedIndex(null);
      setJsonError(null);
    } catch (e: any) {
      setJsonError('Invalid JSON: ' + e.message);
    }
  };

  const removeRow = (i: number) => {
    setItems(items.filter((_, idx) => idx !== i));
    setExpandedIndex(null);
  };

  const addRow = () => {
    const record = newBlankRecord(category);
    const next = [...items, record];
    setItems(next);
    setDraftJson(JSON.stringify(record, null, 2));
    setJsonError(null);
    setExpandedIndex(next.length - 1);
  };

  const handleSave = async () => {
    if (!registry) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await saveRulesCategory(category, items, registry._file_mtime_ms);
      setRegistry(updated);
      setSavedAt(Date.now());
      setConflict(false);
    } catch (err: any) {
      // Deliberately does NOT touch `registry`/`items` here even on a
      // conflict (RulesConfigConflictError) — registry drives the
      // items-sync effect below, so replacing it here would silently wipe
      // this session's own unsaved edit, the opposite of what the error
      // banner's "Reload" action (see below) is for: an explicit choice,
      // not an automatic one.
      setError(err.message || 'Failed to save');
      if (err instanceof RulesConfigConflictError) setConflict(true);
    } finally {
      setSaving(false);
    }
  };

  const discardChanges = () => {
    if (registry) setItems(registry[category] || []);
    setExpandedIndex(null);
  };

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          <span className="brand-mark">CZ</span>
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          <ThemeToggle />
          <Link to="/admin" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            User Management
          </Link>
          <Link to="/projects" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            All Projects
          </Link>
        </div>
      </header>

      <main className="main-content" style={{ maxWidth: '1300px' }}>
        <div className="page-header">
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700 }}>Rules &amp; Config Registry</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              Every business/architectural number the zoning engine uses — edit here instead of a code deploy.
              Changes apply to the next zoning run immediately, not retroactively to runs already generated.
            </p>
          </div>
        </div>

        {error && (
          <div className="alert-box alert-error" style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'space-between' }}>
            <span>{error}</span>
            {conflict && (
              <button className="btn btn-secondary btn-sm" onClick={() => { setConflict(false); setError(null); load(); }}>
                Reload
              </button>
            )}
          </div>
        )}
        {savedAt && !error && Date.now() - savedAt < 4000 && (
          <div className="alert-box alert-success">Saved. A backup of the previous version was written automatically.</div>
        )}

        {forbidden ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true"><BlockedIcon /></div>
            <p style={{ color: 'var(--text-secondary)' }}>Your account doesn't have admin access.</p>
          </div>
        ) : loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading…</p>
        ) : (
          <>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '1rem' }}>
              {RULES_CATEGORIES.map(c => (
                <button
                  key={c}
                  onClick={() => { if (!isDirty || confirm('Discard unsaved changes to this category?')) setCategory(c); }}
                  className={c === category ? 'btn btn-primary' : 'btn btn-secondary'}
                  style={{ fontSize: '0.8rem' }}
                >
                  {CATEGORY_LABEL[c]} ({(registry?.[c] || []).length})
                </button>
              ))}
            </div>

            <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '10px', overflow: 'hidden', marginBottom: '1rem' }}>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{PK_FIELD[category]}</th>
                      {SUMMARY_FIELDS[category].map(f => <th key={f}>{f}</th>)}
                      <th>Status</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, i) => (
                      <React.Fragment key={i}>
                        <tr>
                          <td style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--text-primary)' }}>{item[PK_FIELD[category]] || <em>(new)</em>}</td>
                          {SUMMARY_FIELDS[category].map(f => (
                            <td key={f} style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                              {item[f] !== undefined ? String(item[f]) : '—'}
                            </td>
                          ))}
                          <td>
                            {item.approval_status && (
                              <span style={{ fontSize: '0.68rem', fontWeight: 700, color: APPROVAL_COLOR[item.approval_status] || 'var(--text-secondary)' }}>
                                {item.approval_status}
                              </span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                              <button className="btn btn-secondary" style={{ fontSize: '0.72rem', padding: '0.3rem 0.6rem' }} onClick={() => expand(i)}>
                                Edit
                              </button>
                              <button className="btn btn-icon-danger" title="Remove" onClick={() => removeRow(i)}><TrashIcon /></button>
                            </div>
                          </td>
                        </tr>
                        {expandedIndex === i && (
                          <tr>
                            <td colSpan={SUMMARY_FIELDS[category].length + 3} style={{ background: 'var(--bg-primary)' }}>
                              <textarea
                                value={draftJson}
                                onChange={(e) => setDraftJson(e.target.value)}
                                spellCheck={false}
                                style={{
                                  width: '100%', minHeight: '180px', fontFamily: 'monospace', fontSize: '0.78rem',
                                  background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', padding: '8px'
                                }}
                              />
                              {jsonError && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '4px' }}>{jsonError}</div>}
                              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '6px' }}>
                                <button className="btn btn-primary" style={{ fontSize: '0.75rem' }} onClick={applyDraft}>Apply to record</button>
                                <button className="btn btn-secondary" style={{ fontSize: '0.75rem' }} onClick={() => setExpandedIndex(null)}>Cancel</button>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                    {items.length === 0 && (
                      <tr><td colSpan={SUMMARY_FIELDS[category].length + 3} style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem' }}>No records in this category.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
              <button className="btn btn-secondary" style={{ fontSize: '0.82rem' }} onClick={addRow}>+ Add Record</button>
              <button className="btn btn-primary" style={{ fontSize: '0.82rem' }} disabled={!isDirty || saving} onClick={handleSave}>
                {saving ? 'Saving…' : isDirty ? `Save ${CATEGORY_LABEL[category]}` : 'No changes'}
              </button>
              {isDirty && (
                <button className="btn btn-secondary" style={{ fontSize: '0.82rem' }} onClick={discardChanges}>
                  Discard changes
                </button>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
};
