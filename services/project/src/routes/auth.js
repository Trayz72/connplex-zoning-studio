import { Router } from 'express';
import crypto from 'crypto';
import bcrypt from 'bcryptjs';
import db from '../db.js';

const router = Router();

/** Emails are case-insensitive everywhere real users type them (autofill,
 * phones capitalizing the first letter, copy-pasting from an email client
 * signature). Without this, "Jane@Firm.com" at registration and
 * "jane@firm.com" at login were silently treated as two different accounts
 * — a real bug, found by testing registration/login with mixed casing, not
 * a hypothetical: it reproduces every time and is a very plausible cause of
 * "why can't I log in" for anyone who typed their email differently the
 * second time. */
function normalizeEmail(email) {
  return typeof email === 'string' ? email.trim().toLowerCase() : email;
}

// Real account creation — before this, the only way to get a login was the
// seed.js CLI script, i.e. exactly one shared demo account existed. A real
// architecture team needs their own accounts (their own audit trail via
// projects.created_by, their own session).
router.post('/register', (req, res) => {
  const email = normalizeEmail(req.body?.email);
  const { password } = req.body || {};
  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }
  if (password.length < 8) {
    return res.status(400).json({ error: 'Password must be at least 8 characters' });
  }
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) {
    return res.status(409).json({ error: 'An account with this email already exists' });
  }

  const id = crypto.randomUUID();
  const password_hash = bcrypt.hashSync(password, 10);
  const created_at = new Date().toISOString();
  db.prepare('INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)')
    .run(id, email, password_hash, created_at);

  res.cookie('session_user_id', id, {
    httpOnly: true,
    sameSite: 'lax',
    maxAge: 7 * 24 * 60 * 60 * 1000
  });

  return res.status(201).json({ user: { id, email, is_admin: false, created_at } });
});

router.post('/login', (req, res) => {
  const email = normalizeEmail(req.body?.email);
  const { password } = req.body || {};
  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
  if (!user) {
    return res.status(401).json({ error: 'Invalid email or password' });
  }

  const isMatch = bcrypt.compareSync(password, user.password_hash);
  if (!isMatch) {
    return res.status(401).json({ error: 'Invalid email or password' });
  }

  res.cookie('session_user_id', user.id, {
    httpOnly: true,
    sameSite: 'lax',
    maxAge: 7 * 24 * 60 * 60 * 1000
  });

  return res.json({
    user: {
      id: user.id,
      email: user.email,
      is_admin: Boolean(user.is_admin),
      created_at: user.created_at
    }
  });
});

router.post('/logout', (req, res) => {
  res.clearCookie('session_user_id');
  return res.json({ message: 'Logged out successfully' });
});

// GET /auth/me — the frontend's only reliable way to know "am I actually
// logged in" (previously nothing checked this: every page rendered
// regardless of session state, and the API silently treated an anonymous
// request as the first user in the database — see requireAuth in
// middleware.js for the fix on the API side).
router.get('/me', (req, res) => {
  const userId = req.cookies && req.cookies.session_user_id;
  if (!userId) {
    return res.status(401).json({ error: 'Not logged in' });
  }
  const user = db.prepare('SELECT id, email, is_admin, created_at FROM users WHERE id = ?').get(userId);
  if (!user) {
    res.clearCookie('session_user_id');
    return res.status(401).json({ error: 'Not logged in' });
  }
  return res.json({ user: { ...user, is_admin: Boolean(user.is_admin) } });
});

export default router;
