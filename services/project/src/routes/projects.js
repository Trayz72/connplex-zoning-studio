import { Router } from 'express';
import crypto from 'crypto';
import db from '../db.js';
import { INTAKE_REQUIRED_FIELDS, computeIsIntakeComplete } from '../utils/intake.js';

const router = Router();

function getAuthenticatedUserId(req) {
  if (req.cookies && req.cookies.session_user_id) {
    const user = db.prepare('SELECT id FROM users WHERE id = ?').get(req.cookies.session_user_id);
    if (user) return user.id;
  }
  const headerUserId = req.headers['x-user-id'];
  if (headerUserId) {
    const user = db.prepare('SELECT id FROM users WHERE id = ?').get(headerUserId);
    if (user) return user.id;
  }
  const firstUser = db.prepare('SELECT id FROM users ORDER BY created_at ASC LIMIT 1').get();
  if (firstUser) return firstUser.id;
  return null;
}

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

// GET /projects - list projects
router.get('/', (req, res) => {
  const rows = db.prepare('SELECT * FROM projects ORDER BY created_at DESC').all();
  return res.json(rows.map(formatProject));
});

// POST /projects - create a project
router.post('/', (req, res) => {
  const userId = getAuthenticatedUserId(req);
  if (!userId) {
    return res.status(401).json({ error: 'Unauthorized. Please log in first.' });
  }

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
  if (!row) {
    return res.status(404).json({ error: 'Project not found' });
  }
  return res.json(formatProject(row));
});

// PATCH /projects/:id - update intake fields
router.patch('/:id', (req, res) => {
  const existing = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id);
  if (!existing) {
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

export default router;
