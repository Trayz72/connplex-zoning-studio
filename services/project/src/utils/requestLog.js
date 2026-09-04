import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

/** Real request/write logging — this service had none at all before, which
 * is exactly why a real, recurring data-integrity incident (the rules
 * registry's 60_SEAT.min_area_sqft silently changing value twice across
 * earlier sessions) was caught via `git status` showing an unexpected diff
 * both times but could never be root-caused: there was no record of which
 * request, from which user, actually wrote it. Two logs, both plain JSONL
 * (one JSON object per line) so they're greppable without any tooling:
 *   - requests.log: every request this service handles (method, path,
 *     status, duration, who) — general-purpose, cheap, always on.
 *   - rules-config-writes.log: a full before/after snapshot of the specific
 *     category array on every successful registry write — the audit trail
 *     the admin UI's "replace this whole category" write pattern needs,
 *     since a bug or a stale client submitting an old copy of unrelated
 *     records would otherwise silently overwrite them with no trace. */
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_DIR = path.resolve(__dirname, '../../logs');

function ensureLogDir() {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
}

function appendLine(filename, obj) {
  ensureLogDir();
  fs.appendFileSync(path.join(LOG_DIR, filename), JSON.stringify(obj) + '\n', 'utf-8');
}

/** Express middleware: logs every request once it finishes, including the
 * real outcome (status code), not just that it arrived. */
export function requestLogger(req, res, next) {
  const start = Date.now();
  res.on('finish', () => {
    appendLine('requests.log', {
      ts: new Date().toISOString(),
      method: req.method,
      path: req.originalUrl,
      status: res.statusCode,
      duration_ms: Date.now() - start,
      user: req.user ? { id: req.user.id, email: req.user.email } : null
    });
  });
  next();
}

export function logRulesConfigWrite({ user, category, before, after }) {
  appendLine('rules-config-writes.log', {
    ts: new Date().toISOString(),
    user: user ? { id: user.id, email: user.email } : null,
    category,
    before_count: before.length,
    after_count: after.length,
    before,
    after
  });
}
