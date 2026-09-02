import { Router } from 'express';
import crypto from 'crypto';
import db from '../db.js';
import { INTAKE_REQUIRED_FIELDS, computeIsIntakeComplete } from '../utils/intake.js';
import { requireAuth } from '../middleware.js';

const router = Router();

// Every route below requires a real session — previously this file resolved
// identity itself and silently fell back to "the first user in the
// database" when no session cookie was present, so every one of these
// endpoints (including list/read of every project) was reachable with zero
// authentication. That was a bug, not an intentional single-tenant
// simplification: fixed by requiring requireAuth on the whole router.
router.use(requireAuth);

function generateNextProjectCode() {
  const rows = db.prepare('SELECT project_code FROM projects').all();
  let maxCode = 1000;
  for (const row of rows) {
    const num = parseInt(row.project_code, 10);
    if (!isNaN(num) && num > maxCode) {
      maxCode = num;
    }
  }
  return String(maxCode + 1);
}

function formatProject(row) {
  if (!row) return null;
  return {
    ...row,
    is_intake_complete: Boolean(row.is_intake_complete)
  };
}

// GET /projects - list projects, optionally filtered (spec M10: dashboard
// search/filter by city, state, status; franchise tier is deliberately not
// included here — it's captured per-region in the zoning-engine's
// requirements step, not stored on the Project record at all today, so
// filtering by it from this endpoint would mean querying a second service
// per row rather than a real, honest filter).
router.get('/', (req, res) => {
  const { q, city, state, status } = req.query;
  const clauses = [];
  const params = [];

  // Cross-tenant scoping: a non-admin only ever sees their own projects.
  // Previously every query here was unscoped by user, so any authenticated
  // account (even a brand-new one) could list/read/edit/delete every other
  // client's projects.
  if (!req.user.is_admin) {
    clauses.push('created_by = ?');
    params.push(req.user.id);
  }

  if (q && typeof q === 'string' && q.trim()) {
    clauses.push('(property_name LIKE ? OR client_name LIKE ? OR project_code LIKE ?)');
    const like = `%${q.trim()}%`;
    params.push(like, like, like);
  }
  if (city && typeof city === 'string') {
    clauses.push('city = ?');
    params.push(city);
  }
  if (state && typeof state === 'string') {
    clauses.push('state = ?');
    params.push(state);
  }
  if (status && typeof status === 'string') {
    clauses.push('property_status = ?');
    params.push(status);
  }

  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';
  const rows = db.prepare(`SELECT * FROM projects ${where} ORDER BY created_at DESC`).all(...params);
  return res.json(rows.map(formatProject));
});

// GET /projects/filters - distinct values actually present, so the
// dashboard's filter dropdowns reflect real data instead of a hardcoded
// guess at what cities/states exist. Must stay above GET /:id or Express
// would try to treat "filters" as a project id.
router.get('/filters', (req, res) => {
  const cities = db.prepare('SELECT DISTINCT city FROM projects WHERE city IS NOT NULL AND city != \'\' ORDER BY city').all().map(r => r.city);
  const states = db.prepare('SELECT DISTINCT state FROM projects WHERE state IS NOT NULL AND state != \'\' ORDER BY state').all().map(r => r.state);
  const statuses = db.prepare('SELECT DISTINCT property_status FROM projects WHERE property_status IS NOT NULL AND property_status != \'\' ORDER BY property_status').all().map(r => r.property_status);
  return res.json({ cities, states, statuses });
});

// POST /projects - create a project
router.post('/', (req, res) => {
  const userId = req.user.id;

  const id = crypto.randomUUID();
  const project_code = generateNextProjectCode();
  const created_at = new Date().toISOString();
  const body = req.body || {};

  const projectData = {
    property_name: body.property_name || null,
    client_name: body.client_name || null,
    client_mobile: body.client_mobile || null,
    client_email: body.client_email || null,
    google_location: body.google_location || null,
    city: body.city || null,
    state: body.state || null,
    property_source: body.property_source || null,
    floor_shop_no: body.floor_shop_no || null,
    property_status: body.property_status || null,
    beam_bottom_clear_height: body.beam_bottom_clear_height || null,
    property_type: body.property_type || null
  };

  const is_intake_complete = computeIsIntakeComplete(projectData);

  const stmt = db.prepare(`
    INSERT INTO projects (
      id,
      project_code,
      property_name,
      client_name,
      client_mobile,
      client_email,
      google_location,
      city,
      state,
      property_source,
      floor_shop_no,
      property_status,
      beam_bottom_clear_height,
      property_type,
      is_intake_complete,
      created_at,
      created_by
    ) VALUES (
      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
  `);

  stmt.run(
    id,
    project_code,
    projectData.property_name,
    projectData.client_name,
    projectData.client_mobile,
    projectData.client_email,
    projectData.google_location,
    projectData.city,
    projectData.state,
    projectData.property_source,
    projectData.floor_shop_no,
    projectData.property_status,
    projectData.beam_bottom_clear_height,
    projectData.property_type,
    is_intake_complete,
    created_at,
    userId
  );

  const created = db.prepare('SELECT * FROM projects WHERE id = ?').get(id);
  return res.status(201).json(formatProject(created));
});

// GET /projects/:id - get one project
router.get('/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id);
  if (!row || (!req.user.is_admin && row.created_by !== req.user.id)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  return res.json(formatProject(row));
});

// PATCH /projects/:id - update intake fields
router.patch('/:id', (req, res) => {
  const existing = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id);
  if (!existing || (!req.user.is_admin && existing.created_by !== req.user.id)) {
    return res.status(404).json({ error: 'Project not found' });
  }

  const body = req.body || {};
  const updatedData = { ...existing };

  for (const field of INTAKE_REQUIRED_FIELDS) {
    if (field in body) {
      updatedData[field] = body[field] !== undefined ? body[field] : null;
    }
  }

  const is_intake_complete = computeIsIntakeComplete(updatedData);

  const stmt = db.prepare(`
    UPDATE projects SET
      property_name = ?,
      client_name = ?,
      client_mobile = ?,
      client_email = ?,
      google_location = ?,
      city = ?,
      state = ?,
      property_source = ?,
      floor_shop_no = ?,
      property_status = ?,
      beam_bottom_clear_height = ?,
      property_type = ?,
      is_intake_complete = ?
    WHERE id = ?
  `);

  stmt.run(
    updatedData.property_name,
    updatedData.client_name,
    updatedData.client_mobile,
    updatedData.client_email,
    updatedData.google_location,
    updatedData.city,
    updatedData.state,
    updatedData.property_source,
    updatedData.floor_shop_no,
    updatedData.property_status,
    updatedData.beam_bottom_clear_height,
    updatedData.property_type,
    is_intake_complete,
    req.params.id
  );

  const updated = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id);
  return res.json(formatProject(updated));
});

// DELETE /projects/:id - permanently remove a project and its intake record
router.delete('/:id', (req, res) => {
  const existing = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id);
  if (!existing || (!req.user.is_admin && existing.created_by !== req.user.id)) {
    return res.status(404).json({ error: 'Project not found' });
  }
  db.prepare('DELETE FROM floors WHERE project_id = ?').run(req.params.id);
  db.prepare('DELETE FROM projects WHERE id = ?').run(req.params.id);
  return res.status(204).end();
});

export default router;
