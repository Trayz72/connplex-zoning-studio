import crypto from 'crypto';
import bcrypt from 'bcryptjs';
import db from './src/db.js';

function main() {
  const email = process.argv[2] || 'test@connplex.com';
  const password = process.argv[3] || 'password123';

  const existingStmt = db.prepare('SELECT * FROM users WHERE email = ?');
  const existing = existingStmt.get(email);
  if (existing) {
    console.log(`User already exists: ${email} (ID: ${existing.id})`);
    db.close();
    return;
  }

  const id = crypto.randomUUID();
  const password_hash = bcrypt.hashSync(password, 10);
  const created_at = new Date().toISOString();

  const insertStmt = db.prepare('INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)');
  insertStmt.run(id, email, password_hash, created_at);

  console.log(`User created successfully:`);
  console.log(`ID: ${id}`);
  console.log(`Email: ${email}`);
  db.close();
}

main();
