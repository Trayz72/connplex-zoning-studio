import { Router } from 'express';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { requireAuth, requireAdmin } from '../middleware.js';

const router = Router();
router.use(requireAuth, requireAdmin);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Same file services/zoning-engine/rules_registry.py reads — this is the
// spec M2 admin UI's write path. zoning-engine has no auth model of its own
// by design, so it can only ever read this file, never expose a way to
// write it; this service is the one with real admin sessions, so the write
// path lives here. zoning-engine picks up a change on its very next request
// (rules_registry.py checks the file's mtime on every load, not a cache
// that only clears on restart).
const REGISTRY_PATH = path.resolve(__dirname, '../../../rules-config/registry/rules_registry_v1.json');

const EDITABLE_CATEGORIES = ['seat_types', 'auditorium_presets', 'franchise_tiers', 'planning_norms', 'viability_rules'];

function readRegistry() {
  return JSON.parse(fs.readFileSync(REGISTRY_PATH, 'utf-8'));
}

// GET /admin/rules-config - the whole registry, read-only fields included
// (source, approval_status, etc.) so an admin can see the provenance of
// what they're about to change, per Product Principle #3 (AI/admin edits
// must carry provenance, never silently override it).
router.get('/', (req, res) => {
  try {
    return res.json(readRegistry());
  } catch (err) {
    return res.status(500).json({ error: `Could not read the rules registry: ${err.message}` });
  }
});

// PUT /admin/rules-config/:category - replace one category's full array.
// Backs up the whole file first (Product Principle #8: everything
// versioned — this is a basic safety-net snapshot, not full RuleSet
// version history, which is a deliberately bigger, separate model for
// zoning-run inputs per the spec).
router.put('/:category', (req, res) => {
  const { category } = req.params;
  if (!EDITABLE_CATEGORIES.includes(category)) {
    return res.status(400).json({ error: `Unknown or non-editable category: ${category}` });
  }
  const { items } = req.body || {};
  if (!Array.isArray(items)) {
    return res.status(400).json({ error: 'items must be an array' });
  }

  let registry;
  try {
    registry = readRegistry();
  } catch (err) {
    return res.status(500).json({ error: `Could not read the rules registry: ${err.message}` });
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = REGISTRY_PATH.replace('.json', `.backup.${timestamp}.json`);
  try {
    fs.copyFileSync(REGISTRY_PATH, backupPath);
    registry[category] = items;
    fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2), 'utf-8');
  } catch (err) {
    return res.status(500).json({ error: `Could not save: ${err.message}` });
  }

  return res.json(registry);
});

export default router;
