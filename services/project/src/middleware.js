import db from './db.js';
import { CLEAR_COOKIE_OPTIONS } from './cookieOptions.js';

/** The only place a request's identity should be resolved from. Previously
 * `projects.js` had its own copy of this that silently fell back to "the
 * first user ever created" whenever no session cookie was present — meaning
 * every project-CRUD endpoint was reachable with zero authentication. That
 * was a real bug, not a documented design choice: fixed here by requiring an
 * actual valid session and rejecting with 401 otherwise. */
export function requireAuth(req, res, next) {
  const userId = req.cookies && req.cookies.session_user_id;
  if (!userId) {
    return res.status(401).json({ error: 'Not logged in' });
  }
  const user = db.prepare('SELECT id, email, is_admin FROM users WHERE id = ?').get(userId);
  if (!user) {
    res.clearCookie('session_user_id', CLEAR_COOKIE_OPTIONS);
    return res.status(401).json({ error: 'Not logged in' });
  }
  req.user = { ...user, is_admin: Boolean(user.is_admin) };
  next();
}

/** Must run after requireAuth. */
export function requireAdmin(req, res, next) {
  if (!req.user || !req.user.is_admin) {
    return res.status(403).json({ error: 'Admin access required' });
  }
  next();
}
