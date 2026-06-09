CREATE TABLE IF NOT EXISTS sites (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  province TEXT NOT NULL,
  department TEXT NOT NULL,
  town TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  cuit TEXT,
  plant_number TEXT,
  registry_status TEXT DEFAULT 'Pendiente SISA/ARCA',
  address TEXT,
  location_source TEXT DEFAULT 'Centro localidad',
  region TEXT,
  phone TEXT,
  email TEXT,
  coord_maps TEXT,
  maps_url TEXT,
  directions_url TEXT,
  original_lat TEXT,
  original_lng TEXT,
  source_file TEXT,
  boundary_geojson TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
  diameter_m DOUBLE PRECISION NOT NULL DEFAULT 18,
  height_m DOUBLE PRECISION NOT NULL DEFAULT 18,
  density_t_m3 DOUBLE PRECISION NOT NULL,
  loaded_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (site_id, code)
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
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  location_source TEXT DEFAULT 'Pendiente georreferenciar',
  silo_count INTEGER DEFAULT 0,
  capacity_m3 INTEGER DEFAULT 0,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telemetry (
  id BIGSERIAL PRIMARY KEY,
  silo_id TEXT NOT NULL REFERENCES silos(id) ON DELETE CASCADE,
  recorded_at TIMESTAMPTZ NOT NULL,
  grain_humidity DOUBLE PRECISION NOT NULL,
  grain_temperature DOUBLE PRECISION NOT NULL,
  internal_humidity DOUBLE PRECISION NOT NULL,
  internal_temperature DOUBLE PRECISION NOT NULL,
  fill_percent DOUBLE PRECISION NOT NULL,
  motor_on INTEGER NOT NULL,
  status TEXT NOT NULL,
  safe_days INTEGER NOT NULL,
  volume_m3 INTEGER NOT NULL,
  estimated_tons INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS weather (
  id BIGSERIAL PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  recorded_at TIMESTAMPTZ NOT NULL,
  external_temperature DOUBLE PRECISION NOT NULL,
  external_humidity DOUBLE PRECISION NOT NULL,
  dew_point DOUBLE PRECISION NOT NULL,
  wind_kmh DOUBLE PRECISION NOT NULL,
  pressure_hpa DOUBLE PRECISION NOT NULL,
  rain_mm DOUBLE PRECISION NOT NULL,
  source TEXT NOT NULL DEFAULT 'Open-Meteo',
  UNIQUE (site_id, recorded_at, source)
);

CREATE TABLE IF NOT EXISTS weather_forecasts (
  id BIGSERIAL PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  forecast_for TIMESTAMPTZ NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  external_temperature DOUBLE PRECISION,
  external_humidity DOUBLE PRECISION,
  dew_point DOUBLE PRECISION,
  wind_kmh DOUBLE PRECISION,
  wind_gust_kmh DOUBLE PRECISION,
  pressure_hpa DOUBLE PRECISION,
  rain_mm DOUBLE PRECISION,
  source TEXT NOT NULL DEFAULT 'Open-Meteo',
  UNIQUE (site_id, forecast_for, source)
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL,
  role TEXT NOT NULL,
  site_id TEXT REFERENCES sites(id) ON DELETE SET NULL,
  active INTEGER NOT NULL DEFAULT 1,
  scope_type TEXT NOT NULL DEFAULT 'site',
  scope_value TEXT,
  can_view INTEGER NOT NULL DEFAULT 1,
  can_edit_sites INTEGER NOT NULL DEFAULT 0,
  can_edit_silos INTEGER NOT NULL DEFAULT 0,
  can_manage_users INTEGER NOT NULL DEFAULT 0,
  can_export_reports INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  actor_email TEXT,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  site_id TEXT REFERENCES sites(id) ON DELETE SET NULL,
  before_data JSONB,
  after_data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dependencies_parent ON dependencies(parent_site_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_filters ON dependencies(site_type, province, town, ccp_associated);
CREATE INDEX IF NOT EXISTS idx_telemetry_silo_time ON telemetry(silo_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_site_time ON weather(site_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_forecasts_site_time ON weather_forecasts(site_id, forecast_for DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_site_time ON audit_log(site_id, created_at DESC);
