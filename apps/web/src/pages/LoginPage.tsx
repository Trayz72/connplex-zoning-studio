import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register } from '../api';

export const LoginPage: React.FC = () => {
  const [mode, setMode] = useState<'SIGN_IN' | 'CREATE_ACCOUNT'>('SIGN_IN');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === 'SIGN_IN') {
        await login(email, password);
      } else {
        await register(email, password);
      }
      navigate('/projects');
    } catch (err: any) {
      setError(err.message || (mode === 'SIGN_IN' ? 'Login failed' : 'Registration failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>Connplex Zoning Studio</h1>
        <p className="subtitle">
          {mode === 'SIGN_IN' ? 'Sign in to access your projects' : 'Create an account for your architecture team'}
        </p>

        {error && <div className="alert-box alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              className="form-control"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              required
              minLength={mode === 'CREATE_ACCOUNT' ? 8 : undefined}
              className="form-control"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
            {mode === 'CREATE_ACCOUNT' && (
              <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                At least 8 characters.
              </div>
            )}
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', marginTop: '0.5rem' }}
            disabled={loading}
          >
            {loading ? (mode === 'SIGN_IN' ? 'Signing in...' : 'Creating account...') : (mode === 'SIGN_IN' ? 'Sign In' : 'Create Account')}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          {mode === 'SIGN_IN' ? (
            <>
              New to Connplex Zoning Studio?{' '}
              <a href="#" onClick={(e) => { e.preventDefault(); setMode('CREATE_ACCOUNT'); setError(null); }}>
                Create an account
              </a>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <a href="#" onClick={(e) => { e.preventDefault(); setMode('SIGN_IN'); setError(null); }}>
                Sign in
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
