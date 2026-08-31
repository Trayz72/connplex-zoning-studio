import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getUsers, setUserAdmin, deleteUser, AdminUser } from '../api';
import { useAuth } from '../AuthContext';

export const AdminPage: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err: any) {
      if (err.message && err.message.includes('Admin')) {
        setForbidden(true);
      } else {
        setError(err.message || 'Failed to load users');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleToggleAdmin = async (u: AdminUser) => {
    setBusyId(u.id);
    setError(null);
    try {
      const updated = await setUserAdmin(u.id, !u.is_admin);
      setUsers(prev => prev.map(x => x.id === updated.id ? { ...x, is_admin: updated.is_admin } : x));
    } catch (err: any) {
      setError(err.message || 'Failed to update user');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await deleteUser(id);
      setUsers(prev => prev.filter(x => x.id !== id));
    } catch (err: any) {
      setError(err.message || 'Failed to delete user');
    } finally {
      setBusyId(null);
      setConfirmingDeleteId(null);
    }
  };

  return (
    <div className="app-container">
      <header className="navbar">
        <Link to="/projects" className="brand">
          <span className="brand-mark">CZ</span>
          Connplex Zoning Studio
        </Link>
        <div className="nav-links">
          <Link to="/admin/rules" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            Rules &amp; Config
          </Link>
          <Link to="/projects" className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            ← All Projects
          </Link>
        </div>
      </header>

      <main className="main-content">
        <div className="page-header">
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700 }}>User Management</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              {loading ? 'Loading accounts…' : forbidden ? 'Access restricted' : `${users.length} account${users.length === 1 ? '' : 's'}`}
            </p>
          </div>
        </div>

        {error && <div className="alert-box alert-error">{error}</div>}

        {forbidden ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true">⛔</div>
            <p style={{ color: 'var(--text-secondary)' }}>
              Your account doesn't have admin access. Ask an existing admin to promote you from this same page.
            </p>
          </div>
        ) : loading ? (
          <p style={{ color: 'var(--text-secondary)' }}>Loading…</p>
        ) : (
          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '10px', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Projects</th>
                    <th>Joined</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.id}>
                      <td style={{ color: 'var(--text-primary)' }}>
                        {u.email}
                        {u.id === currentUser?.id && (
                          <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}> (you)</span>
                        )}
                      </td>
                      <td>
                        {u.is_admin
                          ? <span className="admin-tag" style={{ marginLeft: 0 }}>Admin</span>
                          : <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Member</span>}
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>{u.project_count}</td>
                      <td style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td>
                        {confirmingDeleteId === u.id ? (
                          <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.72rem', color: '#ff7b72' }}>Delete this account?</span>
                            <button
                              className="btn btn-danger"
                              style={{ fontSize: '0.72rem', padding: '0.3rem 0.6rem' }}
                              disabled={busyId === u.id}
                              onClick={() => handleDelete(u.id)}
                            >
                              {busyId === u.id ? 'Deleting…' : 'Confirm'}
                            </button>
                            <button
                              className="btn btn-secondary"
                              style={{ fontSize: '0.72rem', padding: '0.3rem 0.6rem' }}
                              disabled={busyId === u.id}
                              onClick={() => setConfirmingDeleteId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                            <button
                              className="btn btn-secondary"
                              style={{ fontSize: '0.72rem', padding: '0.3rem 0.6rem' }}
                              disabled={busyId === u.id}
                              onClick={() => handleToggleAdmin(u)}
                            >
                              {u.is_admin ? 'Revoke admin' : 'Make admin'}
                            </button>
                            <button
                              className="btn btn-icon-danger"
                              title="Delete account"
                              aria-label="Delete account"
                              disabled={busyId === u.id || u.id === currentUser?.id}
                              onClick={() => setConfirmingDeleteId(u.id)}
                            >
                              🗑
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
