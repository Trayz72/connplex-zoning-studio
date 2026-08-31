import { DatabaseSync } from 'node:sqlite';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const dbPath = path.resolve(__dirname, '../data.sqlite');
const schemaPath = path.resolve(__dirname, '../schema.sql');

const db = new DatabaseSync(dbPath);
db.exec('PRAGMA journal_mode = WAL;');
db.exec('PRAGMA foreign_keys = ON;');

const schemaSql = fs.readFileSync(schemaPath, 'utf8');
db.exec(schemaSql);

// Lightweight migration: `is_admin` was added after the initial schema, and
// SQLite has no `ADD COLUMN IF NOT EXISTS`, so check first rather than let
// a second server start crash on "duplicate column name".
const userColumns = db.prepare("PRAGMA table_info(users)").all();
if (!userColumns.some((c) => c.name === 'is_admin')) {
  db.exec('ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0');
}

// The very first account (the seeded test@connplex.com in every environment
// so far) becomes admin automatically, the way most self-hosted tools
// bootstrap their first admin — otherwise nobody could ever reach the admin
// panel on a fresh database. Only applies if no admin exists yet at all, so
// it never overrides an admin who was deliberately demoted later.
const hasAdmin = db.prepare('SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1').get();
if (!hasAdmin) {
  const firstUser = db.prepare('SELECT id FROM users ORDER BY created_at ASC LIMIT 1').get();
  if (firstUser) {
    db.prepare('UPDATE users SET is_admin = 1 WHERE id = ?').run(firstUser.id);
  }
}

export default db;
