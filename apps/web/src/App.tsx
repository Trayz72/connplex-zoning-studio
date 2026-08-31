import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { ProjectIntakePage } from './pages/ProjectIntakePage';
import { ZoningWorkspace } from './pages/ZoningWorkspace';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:id/intake" element={<ProjectIntakePage />} />
        <Route path="/projects/:id/studio" element={<ZoningWorkspace />} />
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
    </BrowserRouter>
  );
};
