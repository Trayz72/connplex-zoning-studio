export interface CurrentUser {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
}

export interface AdminUser extends CurrentUser {
  project_count: number;
}

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

/** Throws if there's no valid session — the one source of truth the frontend
 * has for "am I actually logged in" (nothing checked this before; every page
 * rendered regardless of session state). */
export async function getCurrentUser(): Promise<CurrentUser> {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' });
  if (!res.ok) {
    throw new Error('Not logged in');
  }
  const data = await res.json();
  return data.user;
}

export async function getUsers(): Promise<AdminUser[]> {
  const res = await fetch(`${API_BASE}/admin/users`, { credentials: 'include' });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Failed to load users' }));
    throw new Error(error.error || 'Failed to load users');
  }
  return res.json();
}

export async function setUserAdmin(id: string, isAdmin: boolean): Promise<AdminUser> {
  const res = await fetch(`${API_BASE}/admin/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ is_admin: isAdmin })
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Failed to update user' }));
    throw new Error(error.error || 'Failed to update user');
  }
  return res.json();
}

export async function deleteUser(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/admin/users/${id}`, {
    method: 'DELETE',
    credentials: 'include'
  });
  if (!res.ok && res.status !== 404) {
    const error = await res.json().catch(() => ({ error: 'Failed to delete user' }));
    throw new Error(error.error || 'Failed to delete user');
  }
}

export interface ProjectFilters {
  q?: string;
  city?: string;
  state?: string;
  status?: string;
}

export async function getProjects(filters?: ProjectFilters): Promise<Project[]> {
  const params = new URLSearchParams();
  if (filters?.q) params.set('q', filters.q);
  if (filters?.city) params.set('city', filters.city);
  if (filters?.state) params.set('state', filters.state);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/projects${qs ? `?${qs}` : ''}`, {
    credentials: 'include'
  });
  if (!res.ok) {
    throw new Error('Failed to fetch projects');
  }
  return res.json();
}

export interface ProjectFilterOptions {
  cities: string[];
  states: string[];
  statuses: string[];
}

export async function getProjectFilterOptions(): Promise<ProjectFilterOptions> {
  const res = await fetch(`${API_BASE}/projects/filters`, { credentials: 'include' });
  if (!res.ok) {
    throw new Error('Failed to fetch filter options');
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

export const RULES_CATEGORIES = ['seat_types', 'auditorium_presets', 'franchise_tiers', 'planning_norms', 'viability_rules'] as const;
export type RulesCategory = typeof RULES_CATEGORIES[number];

export interface RulesRegistry {
  schema_version: string;
  title: string;
  description: string;
  generated: string;
  sources: any[];
  seat_types: any[];
  auditorium_presets: any[];
  franchise_tiers: any[];
  planning_norms: any[];
  viability_rules: any[];
  not_evaluable_today: string[];
}

export async function getRulesConfig(): Promise<RulesRegistry> {
  const res = await fetch(`${API_BASE}/admin/rules-config`, { credentials: 'include' });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Failed to load rules config' }));
    throw new Error(error.error || 'Failed to load rules config');
  }
  return res.json();
}

export async function saveRulesCategory(category: RulesCategory, items: any[]): Promise<RulesRegistry> {
  const res = await fetch(`${API_BASE}/admin/rules-config/${category}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ items })
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Failed to save' }));
    throw new Error(error.error || 'Failed to save');
  }
  return res.json();
}
