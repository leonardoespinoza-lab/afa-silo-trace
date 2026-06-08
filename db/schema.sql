PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sites (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  province TEXT NOT NULL,
  department TEXT NOT NULL,
  town TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  cuit TEXT,
  plant_number TEXT,
  registry_status TEXT DEFAULT 'Pendiente SISA/ARCA',
  address TEXT,
  location_source TEXT DEFAULT 'Centro localidad'
);

CREATE TABLE IF NOT EXISTS silos (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  grain TEXT NOT NULL,
  campaign TEXT NOT NULL,
  producer TEXT NOT NULL,
  origin TEXT NOT NULL,
  capacity_m3 INTEGER NOT NULL,
  diameter_m REAL NOT NULL DEFAULT 18,
  height_m REAL NOT NULL DEFAULT 18,
  density_t_m3 REAL NOT NULL,
  loaded_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dependencies (
  id TEXT PRIMARY KEY,
  parent_site_id TEXT REFERENCES sites(id) ON DELETE SET NULL,
  site_type TEXT NOT NULL,
  province TEXT NOT NULL,
  department TEXT,
  town TEXT NOT NULL,
  published_address TEXT,
  ccp_associated TEXT,
  source_url TEXT,
  source_status TEXT DEFAULT 'Oficial AFA',
  lat REAL,
  lng REAL,
  location_source TEXT DEFAULT 'Pendiente georreferenciar',
  silo_count INTEGER DEFAULT 0,
  capacity_m3 INTEGER DEFAULT 0,
  notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_dependencies_parent ON dependencies(parent_site_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_filters ON dependencies(site_type, province, town, ccp_associated);

CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  silo_id TEXT NOT NULL REFERENCES silos(id) ON DELETE CASCADE,
  recorded_at TEXT NOT NULL,
  grain_humidity REAL NOT NULL,
  grain_temperature REAL NOT NULL,
  internal_humidity REAL NOT NULL,
  internal_temperature REAL NOT NULL,
  fill_percent REAL NOT NULL,
  motor_on INTEGER NOT NULL,
  status TEXT NOT NULL,
  safe_days INTEGER NOT NULL,
  volume_m3 INTEGER NOT NULL,
  estimated_tons INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS weather (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  recorded_at TEXT NOT NULL,
  external_temperature REAL NOT NULL,
  external_humidity REAL NOT NULL,
  dew_point REAL NOT NULL,
  wind_kmh REAL NOT NULL,
  pressure_hpa REAL NOT NULL,
  rain_mm REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telemetry_silo_time ON telemetry(silo_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_site_time ON weather(site_id, recorded_at DESC);
