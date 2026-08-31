CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  project_code TEXT UNIQUE NOT NULL,
  property_name TEXT,
  client_name TEXT,
  client_mobile TEXT,
  client_email TEXT,
  google_location TEXT,
  city TEXT,
  state TEXT,
  property_source TEXT,
  floor_shop_no TEXT,
  property_status TEXT,
  beam_bottom_clear_height TEXT,
  property_type TEXT,
  is_intake_complete INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS floors (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  floor_label TEXT,
  floor_height TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id)
);
