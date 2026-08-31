import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import { LoginPage } from './pages/LoginPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { ProjectIntakePage } from './pages/ProjectIntakePage';
import { ZoningWorkspace } from './pages/ZoningWorkspace';
import { AdminPage } from './pages/AdminPage';
import { AdminRulesPage } from './pages/AdminRulesPage';

/** Every route past /login needs this — previously nothing checked session
 * state client-side at all, so /projects, /projects/:id/studio etc. rendered
 * (and made API calls that used to silently succeed as an anonymous "first
 * user") whether or not anyone was actually logged in. */
const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', color: 'var(--text-secondary)' }}>
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/projects" element={<RequireAuth><ProjectsPage /></RequireAuth>} />
          <Route path="/projects/:id/intake" element={<RequireAuth><ProjectIntakePage /></RequireAuth>} />
          <Route path="/projects/:id/studio" element={<RequireAuth><ZoningWorkspace /></RequireAuth>} />
          <Route path="/admin" element={<RequireAuth><AdminPage /></RequireAuth>} />
          <Route path="/admin/rules" element={<RequireAuth><AdminRulesPage /></RequireAuth>} />
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};
