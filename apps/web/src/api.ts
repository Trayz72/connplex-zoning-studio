export interface Project {
  id: string;
  project_code: string;
  property_name: string | null;
  client_name: string | null;
  client_mobile: string | null;
  client_email: string | null;
  google_location: string | null;
  city: string | null;
  state: string | null;
  property_source: string | null;
  floor_shop_no: string | null;
  property_status: string | null;
  beam_bottom_clear_height: string | null;
  property_type: string | null;
  is_intake_complete: boolean;
  created_at: string;
  created_by: string;
}

// Namespaced under /api/pm ("project management") so it can never collide with a
// frontend route. It used to be a bare '' prefix hitting /auth and /projects
// directly — but /projects/:id/studio, /projects/:id/intake, and
// /projects/:id/canvas are also real frontend routes with the same prefix, so a
// hard refresh or a shared link on any of those pages was being caught by the
// dev-server proxy and sent to this backend instead of the SPA (confirmed via a
// direct curl test — a 500/proxy error, not Vite's own history-API fallback).
export const API_BASE = '/api/pm';

export async function login(email: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Login failed' }));
    throw new Error(error.error || 'Login failed');
  }
  return res.json();
}

export async function register(email: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Registration failed' }));
    throw new Error(error.error || 'Registration failed');
  }
  return res.json();
}

export async function logout() {
  const res = await fetch(`${API_BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include'
  });
  return res.json();
}

export async function getProjects(): Promise<Project[]> {
  const res = await fetch(`${API_BASE}/projects`, {
    credentials: 'include'
  });
  if (!res.ok) {
    throw new Error('Failed to fetch projects');
  }
  return res.json();
}

export async function getProject(id: string): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects/${id}`, {
    credentials: 'include'
  });
  if (!res.ok) {
    throw new Error('Failed to fetch project');
  }
  return res.json();
}

export async function createProject(): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({})
  });
  if (!res.ok) {
    throw new Error('Failed to create project');
  }
  return res.json();
}

export async function updateProject(id: string, data: Partial<Project>): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data)
  });
  if (!res.ok) {
    throw new Error('Failed to update project');
  }
  return res.json();
}

export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${id}`, {
    method: 'DELETE',
    credentials: 'include'
  });
  if (!res.ok && res.status !== 404) {
    throw new Error('Failed to delete project');
  }
}
