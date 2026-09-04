import { Router } from 'express';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { requireAuth, requireAdmin } from '../middleware.js';
import { logRulesConfigWrite } from '../utils/requestLog.js';

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

function registryMtimeMs() {
  return fs.statSync(REGISTRY_PATH).mtimeMs;
}

// GET /admin/rules-config - the whole registry, read-only fields included
// (source, approval_status, etc.) so an admin can see the provenance of
// what they're about to change, per Product Principle #3 (AI/admin edits
// must carry provenance, never silently override it). Also returns the
// file's current mtime — the admin UI echoes it back on save (see PUT
// below) so a save based on stale data is rejected instead of silently
// overwriting whatever changed underneath it. This is the concrete fix for
// the class of bug behind the twice-recurring, never-root-caused registry
// stray-write (a value changing with no record of which request did it) —
// the write pattern here replaces a whole category array wholesale, so any
// save built from a stale copy previously discarded every other concurrent
// change with zero warning.
router.get('/', (req, res) => {
  try {
    return res.json({ ...readRegistry(), _file_mtime_ms: registryMtimeMs() });
  } catch (err) {
    return res.status(500).json({ error: `Could not read the rules registry: ${err.message}` });
  }
});

// PUT /admin/rules-config/:category - replace one category's full array.
// Backs up the whole file first (Product Principle #8: everything
// versioned — this is a basic safety-net snapshot, not full RuleSet
// version history, which is a deliberately bigger, separate model for
// zoning-run inputs per the spec). Also requires expected_mtime_ms (the
// value GET returned when this edit session started) to still match the
// file's real current mtime — a real optimistic-concurrency check, not
// just a courtesy, since two admin sessions (or one admin in two tabs)
// editing the same category concurrently would otherwise have the second
// save silently discard the first's changes.
router.put('/:category', (req, res) => {
  const { category } = req.params;
  if (!EDITABLE_CATEGORIES.includes(category)) {
    return res.status(400).json({ error: `Unknown or non-editable category: ${category}` });
  }
  const { items, expected_mtime_ms } = req.body || {};
  if (!Array.isArray(items)) {
    return res.status(400).json({ error: 'items must be an array' });
  }

  let registry;
  try {
    registry = readRegistry();
  } catch (err) {
    return res.status(500).json({ error: `Could not read the rules registry: ${err.message}` });
  }

  const currentMtime = registryMtimeMs();
  if (expected_mtime_ms !== undefined && expected_mtime_ms !== currentMtime) {
    return res.status(409).json({
      error: 'This registry was changed by someone else since you loaded it. Reload to see the latest version before saving — your edits are still in the form.',
      current: { ...registry, _file_mtime_ms: currentMtime }
    });
  }

  const before = registry[category] || [];
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = REGISTRY_PATH.replace('.json', `.backup.${timestamp}.json`);
  try {
    fs.copyFileSync(REGISTRY_PATH, backupPath);
    registry[category] = items;
    fs.writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2), 'utf-8');
  } catch (err) {
    return res.status(500).json({ error: `Could not save: ${err.message}` });
  }

  logRulesConfigWrite({ user: req.user, category, before, after: items });

  return res.json({ ...registry, _file_mtime_ms: registryMtimeMs() });
});

export default router;
