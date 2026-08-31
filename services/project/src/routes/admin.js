import { Router } from 'express';
import db from '../db.js';
import { requireAuth, requireAdmin } from '../middleware.js';

const router = Router();
router.use(requireAuth, requireAdmin);

// GET /admin/users - every account, with how many projects each created
router.get('/users', (req, res) => {
  const rows = db.prepare(`
    SELECT u.id, u.email, u.is_admin, u.created_at,
           (SELECT COUNT(*) FROM projects p WHERE p.created_by = u.id) AS project_count
    FROM users u
    ORDER BY u.created_at ASC
  `).all();
  return res.json(rows.map((r) => ({ ...r, is_admin: Boolean(r.is_admin) })));
});

// PATCH /admin/users/:id - promote/demote admin status
router.patch('/users/:id', (req, res) => {
  const target = db.prepare('SELECT * FROM users WHERE id = ?').get(req.params.id);
  if (!target) {
    return res.status(404).json({ error: 'User not found' });
  }
  const { is_admin } = req.body || {};
  if (typeof is_admin !== 'boolean') {
    return res.status(400).json({ error: 'is_admin (boolean) is required' });
  }
  if (!is_admin && target.id === req.user.id) {
    const adminCount = db.prepare('SELECT COUNT(*) AS n FROM users WHERE is_admin = 1').get().n;
    if (adminCount <= 1) {
      return res.status(409).json({ error: "Can't remove the last admin — promote another account first." });
    }
  }
  db.prepare('UPDATE users SET is_admin = ? WHERE id = ?').run(is_admin ? 1 : 0, target.id);
  const updated = db.prepare('SELECT id, email, is_admin, created_at FROM users WHERE id = ?').get(target.id);
  return res.json({ ...updated, is_admin: Boolean(updated.is_admin) });
});

// DELETE /admin/users/:id - remove an account
router.delete('/users/:id', (req, res) => {
  if (req.params.id === req.user.id) {
    return res.status(400).json({ error: "You can't delete your own account while logged in as it." });
  }
  const target = db.prepare('SELECT * FROM users WHERE id = ?').get(req.params.id);
  if (!target) {
    return res.status(404).json({ error: 'User not found' });
  }
  const projectCount = db.prepare('SELECT COUNT(*) AS n FROM projects WHERE created_by = ?').get(target.id).n;
  if (projectCount > 0) {
    return res.status(409).json({
      error: `This user created ${projectCount} project(s). Delete or reassign those first — deleting the account ` +
        `now would either fail or silently orphan real project data, neither of which this does silently.`
    });
  }
  db.prepare('DELETE FROM users WHERE id = ?').run(target.id);
  return res.status(204).end();
});

export default router;
