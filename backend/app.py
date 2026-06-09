from __future__ import annotations

import json
import math
import os
import csv
import psycopg
import re
import unicodedata
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import threading
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
DATABASE_URL = os.getenv("DATABASE_URL")
SCHEMA_PATH = ROOT / "db" / "schema_postgres.sql"
RED_AFA_SEED_PATH = ROOT / "db" / "red_afa_seed.csv"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8788"))
WEATHER_REFRESH_MINUTES = int(os.getenv("WEATHER_REFRESH_MINUTES", "15"))
RED_AFA_SOURCE_FILE = "RED_AFA_coordenadas_maps.xlsx"
USER_LOCATION_SOURCES = {
    "Ubicacion corregida por usuario",
    "Coordenada editada manualmente",
    "Limite dibujado por usuario",
}

GRAINS = {
    "Maiz": {"safe_humidity": 14.1, "density": 0.72},
    "Trigo": {"safe_humidity": 14.0, "density": 0.78},
    "Soja": {"safe_humidity": 12.9, "density": 0.75},
    "Girasol": {"safe_humidity": 8.0, "density": 0.42},
    "Sorgo": {"safe_humidity": 15.6, "density": 0.72},
}

SITES = [
    ("afa-arrecifes", "CCP Arrecifes", "Buenos Aires", "Arrecifes", "Arrecifes", -34.0639, -60.1036),
    ("afa-pergamino", "CCP Pergamino", "Buenos Aires", "Pergamino", "Pergamino", -33.8899, -60.5736),
    ("afa-rojas", "CCP Rojas", "Buenos Aires", "Rojas", "Rojas", -34.1953, -60.7350),
    ("afa-marcos-juarez", "CCP Marcos Juarez", "Cordoba", "Marcos Juarez", "Marcos Juarez", -32.6978, -62.1067),
    ("afa-arteaga", "CCP Arteaga", "Santa Fe", "Caseros", "Arteaga", -33.0903, -61.7922),
    ("afa-bigand", "CCP Bigand", "Santa Fe", "Caseros", "Bigand", -33.3731, -61.1842),
    ("afa-bombal", "CCP Bombal", "Santa Fe", "Constitucion", "Bombal", -33.4569, -61.3203),
    ("afa-canada-gomez", "CCP Canada de Gomez", "Santa Fe", "Iriondo", "Canada de Gomez", -32.8164, -61.3949),
    ("afa-canada-rosquin", "CCP Canada Rosquin", "Santa Fe", "San Martin", "Canada Rosquin", -32.0572, -61.6006),
    ("afa-casilda", "CCP Casilda", "Santa Fe", "Caseros", "Casilda", -33.0442, -61.1681),
    ("afa-chovet", "CCP Chovet", "Santa Fe", "General Lopez", "Chovet", -33.6000, -61.6000),
    ("afa-firmat", "CCP Firmat", "Santa Fe", "General Lopez", "Firmat", -33.4594, -61.4831),
    ("afa-humboldt", "CCP Humboldt", "Santa Fe", "Las Colonias", "Humboldt", -31.4008, -61.0817),
    ("afa-jb-molina", "CCP J. B. Molina", "Santa Fe", "Constitucion", "Juan B. Molina", -33.4939, -60.5125),
    ("afa-las-rosas", "CCP Las Rosas", "Santa Fe", "Belgrano", "Las Rosas", -32.4769, -61.5800),
    ("afa-los-cardos", "CCP Los Cardos", "Santa Fe", "San Martin", "Los Cardos", -32.3231, -61.6300),
    ("afa-maciel", "CCP Maciel", "Santa Fe", "San Jeronimo", "Maciel", -32.4539, -60.8878),
    ("afa-maggiolo", "CCP Maggiolo", "Santa Fe", "General Lopez", "Maggiolo", -33.7197, -62.2458),
    ("afa-maria-juana", "CCP Maria Juana", "Santa Fe", "Castellanos", "Maria Juana", -31.6742, -61.7511),
    ("afa-montes-oca", "CCP Montes de Oca", "Santa Fe", "Belgrano", "Montes de Oca", -32.5678, -61.7669),
    ("afa-salto-grande", "CCP Salto Grande", "Santa Fe", "Iriondo", "Salto Grande", -32.6678, -61.0875),
    ("afa-san-martin-escobas", "CCP S. M. de las Escobas", "Santa Fe", "San Martin", "San Martin de las Escobas", -31.8569, -61.5669),
    ("afa-serodino", "CCP Serodino", "Santa Fe", "Iriondo", "Serodino", -32.6050, -60.9475),
    ("afa-tortugas", "CCP Tortugas", "Santa Fe", "Belgrano", "Tortugas", -32.7478, -61.8219),
    ("afa-totoras", "CCP Totoras", "Santa Fe", "Iriondo", "Totoras", -32.5844, -61.1683),
    ("afa-villa-eloisa", "CCP Villa Eloisa", "Santa Fe", "Iriondo", "Villa Eloisa", -32.9622, -61.5589),
]


class PgConnection:
    def __init__(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required. Configure PostgreSQL before starting AFA Silo Trace.")
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        self.conn.close()

    def execute(self, sql: str, params: tuple | list | None = None):
        return self.conn.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql: str, params):
        with self.conn.cursor() as cur:
            cur.executemany(sql.replace("?", "%s"), params)
            return cur

    def executescript(self, sql: str):
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                self.conn.execute(statement)

    def commit(self):
        self.conn.commit()


def connect() -> PgConnection:
    return PgConnection()


def seeded(seed: int):
    n = seed

    def next_value() -> float:
        nonlocal n
        n = (n * 9301 + 49297) % 233280
        return n / 233280

    return next_value


def canonical_lookup(value: str | None) -> str:
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\bj b molina\b", "juan bautista molina", normalized)
    normalized = re.sub(r"\bjuan b molina\b", "juan bautista molina", normalized)
    normalized = re.sub(r"\b(de|del|la|las|el|los)\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def canonical_site_key(town: str | None, province: str | None) -> tuple[str, str]:
    return canonical_lookup(town), canonical_lookup(province)


def is_red_afa_source(source_file: str | None) -> bool:
    return (source_file or "").lower() == RED_AFA_SOURCE_FILE.lower()


def classify_silo(grain: str, humidity: float, temp: float, safe_days: int) -> str:
    limit = GRAINS[grain]["safe_humidity"]
    if humidity > limit + 2.8 or temp > 29 or safe_days < 10:
        return "Critico"
    if humidity > limit + 1.4 or temp > 26 or safe_days < 25:
        return "Riesgo"
    if humidity > limit or temp > 23.5 or safe_days < 45:
        return "Atencion"
    return "Normal"


def silo_capacity_m3(diameter_m: float, height_m: float) -> int:
    radius = diameter_m / 2
    return round(math.pi * radius * radius * height_m)


def dew_point(temp: float, humidity: float) -> float:
    a = 17.27
    b = 237.7
    alpha = ((a * temp) / (b + temp)) + math.log(max(humidity, 1) / 100)
    return round((b * alpha) / (a - alpha), 1)


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        site_count = conn.execute("SELECT COUNT(*) AS count FROM sites").fetchone()["count"]
        if site_count:
            dependency_count = conn.execute("SELECT COUNT(*) AS count FROM dependencies").fetchone()["count"]
            if dependency_count == 0:
                seed_dependencies(conn)
            seed_red_afa(conn)
            seed_users(conn)
            return
        seed_demo(conn)
        seed_dependencies(conn)
        seed_red_afa(conn)
        seed_users(conn)


def seed_users(conn) -> None:
    users = [
        ("user-admin", "Administrador Nacional", "admin@afa.demo", "admin123", "admin", None, 1),
        ("user-arrecifes", "Operador CCP Arrecifes", "arrecifes@afa.demo", "arrecifes123", "ccp", "afa-arrecifes", 1),
    ]
    conn.executemany(
        """
        INSERT INTO users (id, name, email, password, role, site_id, active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        users,
    )
    conn.execute("UPDATE users SET scope_type = 'national', scope_value = NULL WHERE id = 'user-admin'")
    conn.execute("UPDATE users SET scope_type = 'site', scope_value = 'afa-arrecifes' WHERE id = 'user-arrecifes'")
    conn.execute("UPDATE users SET can_view = 1, can_edit_sites = 1, can_edit_silos = 1, can_manage_users = 1, can_export_reports = 1 WHERE id = 'user-admin'")
    conn.execute("UPDATE users SET can_view = 1, can_edit_sites = 0, can_edit_silos = 1, can_manage_users = 0, can_export_reports = 1 WHERE id = 'user-arrecifes'")
    conn.commit()


def seed_dependencies(conn) -> None:
    demo_rows = [
        ("dep-maciel-aldao", "afa-maciel", "Sub-Centro", "Santa Fe", "San Lorenzo", "Aldao", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Sub-centro asociado informado en ficha Maciel."),
        ("dep-maciel-carrizales", "afa-maciel", "Sub-Centro", "Santa Fe", "Iriondo", "Carrizales", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Sub-centro asociado informado en ficha Maciel."),
        ("dep-maciel-metan", "afa-maciel", "Sub-Centro", "Salta", "Metan", "Metan", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Sub-centro asociado informado en ficha Maciel."),
        ("dep-maciel-7-abril", "afa-maciel", "Sub-Centro", "Tucuman", "Burruyacu", "7 de Abril", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Sub-centro asociado informado en ficha Maciel."),
        ("dep-maciel-cuatro-bocas", "afa-maciel", "Oficina", "Santiago del Estero", "Banda", "Cuatro Bocas", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Oficina asociada informada en ficha Maciel."),
        ("dep-maciel-urdinarrain", "afa-maciel", "Oficina", "Entre Rios", "Gualeguaychu", "Urdinarrain", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Oficina asociada informada en ficha Maciel."),
        ("dep-maciel-bandera", "afa-maciel", "Oficina", "Santiago del Estero", "Belgrano", "Bandera", None, "Maciel", "https://www.afascl.coop", "Oficial AFA", None, None, "Pendiente georreferenciar", 0, 0, "Oficina asociada informada en ficha Maciel."),
    ]
    conn.executemany(
        """
        INSERT INTO dependencies (
          id, parent_site_id, site_type, province, department, town, published_address,
          ccp_associated, source_url, source_status, lat, lng, location_source,
          silo_count, capacity_m3, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        demo_rows,
    )
    conn.commit()


def choose_site_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            int(row.get("silo_count") or 0) > 0 or bool(row.get("boundary_geojson")),
            is_red_afa_source(row.get("source_file")),
            int(row.get("silo_count") or 0),
            bool(row.get("plant_number")),
            not str(row.get("id", "")).startswith("red-afa-"),
        ),
        reverse=True,
    )[0]


def find_red_afa_site(conn, town: str, province: str) -> dict | None:
    target_key = canonical_site_key(town, province)
    rows = conn.execute(
        """
        SELECT s.id, s.town, s.province, s.source_file, s.plant_number, s.boundary_geojson,
          (SELECT COUNT(*) FROM silos si WHERE si.site_id = s.id) AS silo_count
        FROM sites s
        """
    ).fetchall()
    candidates = [
        dict(row) for row in rows
        if canonical_site_key(row["town"], row["province"]) == target_key
    ]
    return choose_site_candidate(candidates)


def apply_red_afa_site_data(conn, site_id: str, row: dict, lat: float | None, lng: float | None) -> None:
    town = row["loc_sucursal"].strip()
    province = row["loc_prov"].strip()
    department = row.get("loc_partido") or None
    address = row.get("suc_domicilio") or None
    region = row.get("loc_region") or "RED AFA"
    phone = row.get("suc_tel") or None
    email = row.get("suc_correo") or None
    coord_maps = row.get("coord_maps") or (f"{lat},{lng}" if lat is not None and lng is not None else None)
    maps_url = row.get("link_maps") or None
    directions_url = row.get("link_como_llegar") or None
    conn.execute(
        """
        UPDATE sites
        SET name = ?,
            province = ?,
            department = COALESCE(?, department),
            town = ?,
            lat = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN lat ELSE COALESCE(?, lat) END,
            lng = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN lng ELSE COALESCE(?, lng) END,
            plant_number = COALESCE(?, plant_number),
            address = COALESCE(?, address),
            registry_status = ?,
            location_source = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN location_source ELSE ? END,
            region = ?,
            phone = ?,
            email = ?,
            coord_maps = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN coord_maps ELSE ? END,
            maps_url = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN maps_url ELSE ? END,
            directions_url = CASE WHEN location_source IN ('Ubicacion corregida por usuario', 'Coordenada editada manualmente', 'Limite dibujado por usuario') THEN directions_url ELSE ? END,
            original_lat = ?,
            original_lng = ?,
            source_file = ?,
            updated_at = now()
        WHERE id = ?
        """,
        (
            f"AFA {town}",
            province,
            department,
            town,
            lat,
            lng,
            row.get("loc_cp") or None,
            address,
            RED_AFA_SOURCE_FILE,
            "Google Maps georreferenciado",
            region,
            phone,
            email,
            coord_maps,
            maps_url,
            directions_url,
            row.get("suc_lat") or None,
            row.get("suc_lng") or None,
            RED_AFA_SOURCE_FILE,
            site_id,
        ),
    )


def move_silos_to_site(conn, old_site_id: str, new_site_id: str) -> None:
    silos = conn.execute("SELECT id, code FROM silos WHERE site_id = ? ORDER BY code", (old_site_id,)).fetchall()
    for silo in silos:
        code = silo["code"]
        candidate = code
        suffix = 2
        while conn.execute(
            "SELECT 1 FROM silos WHERE site_id = ? AND code = ? LIMIT 1",
            (new_site_id, candidate),
        ).fetchone():
            candidate = f"{code}-{suffix}"
            suffix += 1
        conn.execute("UPDATE silos SET site_id = ?, code = ? WHERE id = ?", (new_site_id, candidate, silo["id"]))


def dedupe_red_afa_sites(conn, rows: list[dict]) -> None:
    official_by_key = {
        canonical_site_key(row["loc_sucursal"].strip(), row["loc_prov"].strip()): row
        for row in rows
        if row.get("loc_sucursal") and row.get("loc_prov")
    }
    sites = conn.execute(
        """
        SELECT s.id, s.town, s.province, s.source_file, s.plant_number, s.boundary_geojson,
          (SELECT COUNT(*) FROM silos si WHERE si.site_id = s.id) AS silo_count
        FROM sites s
        """
    ).fetchall()
    groups: dict[tuple[str, str], list[dict]] = {}
    for site in sites:
        key = canonical_site_key(site["town"], site["province"])
        if key in official_by_key:
            groups.setdefault(key, []).append(dict(site))
    for key, candidates in groups.items():
        if len(candidates) < 2:
            continue
        preferred = choose_site_candidate(candidates)
        if not preferred:
            continue
        preferred_id = preferred["id"]
        official_row = official_by_key[key]
        lat = float(official_row["lat_decimal"]) if official_row.get("lat_decimal") else None
        lng = float(official_row["long_decimal"]) if official_row.get("long_decimal") else None
        apply_red_afa_site_data(conn, preferred_id, official_row, lat, lng)
        for duplicate in candidates:
            duplicate_id = duplicate["id"]
            if duplicate_id == preferred_id:
                continue
            move_silos_to_site(conn, duplicate_id, preferred_id)
            if not preferred.get("boundary_geojson") and duplicate.get("boundary_geojson"):
                conn.execute(
                    "UPDATE sites SET boundary_geojson = COALESCE(boundary_geojson, ?) WHERE id = ?",
                    (duplicate["boundary_geojson"], preferred_id),
                )
            conn.execute("UPDATE dependencies SET parent_site_id = ? WHERE parent_site_id = ?", (preferred_id, duplicate_id))
            conn.execute("UPDATE users SET site_id = ? WHERE site_id = ?", (preferred_id, duplicate_id))
            conn.execute(
                "UPDATE users SET scope_value = ? WHERE scope_type = 'site' AND scope_value = ?",
                (preferred_id, duplicate_id),
            )
            conn.execute("UPDATE audit_log SET site_id = ? WHERE site_id = ?", (preferred_id, duplicate_id))
            conn.execute("DELETE FROM weather_forecasts WHERE site_id = ?", (duplicate_id,))
            conn.execute("DELETE FROM weather WHERE site_id = ?", (duplicate_id,))
            conn.execute("DELETE FROM sites WHERE id = ?", (duplicate_id,))


def seed_red_afa(conn) -> None:
    if not RED_AFA_SEED_PATH.exists():
        return
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with RED_AFA_SEED_PATH.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        town = row["loc_sucursal"].strip()
        province = row["loc_prov"].strip()
        if not town or not province:
            continue
        lat = float(row["lat_decimal"]) if row.get("lat_decimal") else None
        lng = float(row["long_decimal"]) if row.get("long_decimal") else None
        department = row.get("loc_partido") or None
        address = row.get("suc_domicilio") or None
        region = row.get("loc_region") or "RED AFA"
        phone = row.get("suc_tel") or None
        email = row.get("suc_correo") or None
        coord_maps = row.get("coord_maps") or (f"{lat},{lng}" if lat is not None and lng is not None else None)
        maps_url = row.get("link_maps") or None
        directions_url = row.get("link_como_llegar") or None
        source_file = row.get("source_status") or RED_AFA_SOURCE_FILE
        existing = find_red_afa_site(conn, town, province)
        if existing:
            site_id = existing["id"]
            apply_red_afa_site_data(conn, site_id, row, lat, lng)
        else:
            site_id = f"red-afa-{slugify(town)}-{slugify(province)}"
            conn.execute(
                """
                INSERT INTO sites (
                  id, name, province, department, town, lat, lng, cuit, plant_number,
                  registry_status, address, location_source, region, phone, email,
                  coord_maps, maps_url, directions_url, original_lat, original_lng, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    site_id,
                    f"AFA {town}",
                    province,
                    department,
                    town,
                    lat,
                    lng,
                    None,
                    row.get("loc_cp") or None,
                    RED_AFA_SOURCE_FILE,
                    address,
                    "Google Maps georreferenciado",
                    region,
                    phone,
                    email,
                    coord_maps,
                    maps_url,
                    directions_url,
                    row.get("suc_lat") or None,
                    row.get("suc_lng") or None,
                    RED_AFA_SOURCE_FILE,
                ),
            )
            has_weather = conn.execute("SELECT 1 FROM weather WHERE site_id = ? LIMIT 1", (site_id,)).fetchone()
            if not has_weather:
                temp = 20.0
                humidity = 65.0
                conn.execute(
                    """
                    INSERT INTO weather (
                      site_id, recorded_at, external_temperature, external_humidity,
                      dew_point, wind_kmh, pressure_hpa, rain_mm
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (site_id, now, temp, humidity, dew_point(temp, humidity), 8.0, 1013.0, 0.0),
                )

        source_url = row.get("dist_web") or ""
        if source_url and not source_url.startswith(("http://", "https://")):
            source_url = f"https://{source_url}"
        notes = " | ".join(
            value for value in [
                f"CP {row.get('loc_cp')}" if row.get("loc_cp") else "",
                f"Tel {row.get('suc_tel')}" if row.get("suc_tel") else "",
                f"Correo {row.get('suc_correo')}" if row.get("suc_correo") else "",
                f"Maps {maps_url}" if maps_url else "",
            ] if value
        )
        dependency_id = f"red-afa-{slugify(town)}-{slugify(province)}"
        conn.execute(
            """
            INSERT INTO dependencies (
              id, parent_site_id, site_type, province, department, town, published_address,
              ccp_associated, source_url, source_status, lat, lng, location_source,
              silo_count, capacity_m3, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              parent_site_id = excluded.parent_site_id,
              province = excluded.province,
              department = excluded.department,
              published_address = excluded.published_address,
              ccp_associated = excluded.ccp_associated,
              source_url = excluded.source_url,
              source_status = excluded.source_status,
              lat = excluded.lat,
              lng = excluded.lng,
              location_source = excluded.location_source,
              notes = excluded.notes
            """,
            (
                dependency_id,
                site_id,
                "Sitio AFA",
                province,
                department,
                town,
                address,
                region,
                source_url,
                source_file,
                lat,
                lng,
                "Google Maps georreferenciado",
                0,
                0,
                notes,
            ),
        )
    dedupe_red_afa_sites(conn, rows)
    conn.commit()


def seed_demo(conn) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn.executemany(
        """
        INSERT INTO sites (
          id, name, province, department, town, lat, lng, cuit, plant_number,
          registry_status, address, location_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (*site, None, None, "Pendiente SISA/ARCA", None, "Centro localidad")
            for site in SITES
        ],
    )

    grain_names = list(GRAINS)
    producers = ["Asociado AFA 1024", "Productor asociado 247", "Lote integrado cooperativo", "Remitente trazado 581"]

    for site_index, site in enumerate(SITES):
        site_id, _name, province, _department, town, lat, lng = site
        random = seeded(site_index + 71)
        weather_temp = round(12 + random() * 20, 1)
        weather_humidity = round(50 + random() * 36, 1)
        conn.execute(
            """
            INSERT INTO weather (
              site_id, recorded_at, external_temperature, external_humidity,
              dew_point, wind_kmh, pressure_hpa, rain_mm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_id,
                now.isoformat(),
                weather_temp,
                weather_humidity,
                dew_point(weather_temp, weather_humidity),
                round(4 + random() * 24, 1),
                round(1006 + random() * 22, 1),
                round(random() * 4.5, 1),
            ),
        )

        count = 5 + int(random() * 5)
        for idx in range(count):
            grain = grain_names[(idx + site_index) % len(grain_names)]
            limit = GRAINS[grain]["safe_humidity"]
            humidity = round(limit + (random() * 5.2) - 1.1, 1)
            temp = round(15 + random() * 16, 1)
            internal_humidity = round(48 + random() * 26, 1)
            diameter = round(15 + random() * 16, 1)
            height = round(14 + random() * 16, 1)
            capacity = silo_capacity_m3(diameter, height)
            fill = round(52 + random() * 43)
            volume = round(capacity * fill / 100)
            density = GRAINS[grain]["density"]
            tons = round(volume * density)
            days_stored = 12 + round(random() * 118)
            safe_days = max(0, round(150 - days_stored - max(0, humidity - limit) * 18 - max(0, temp - 22) * 3))
            motor_on = humidity > limit + 0.8 or temp > 25.5
            status = classify_silo(grain, humidity, temp, safe_days)
            angle = (idx / count) * math.pi * 2
            radius = 0.010 + random() * 0.010
            code_prefix = town[:3].upper().replace(" ", "")
            silo_id = f"{site_id}-s{idx + 1:02d}"
            conn.execute(
                """
                INSERT INTO silos (
                  id, site_id, code, grain, campaign, producer, origin, capacity_m3,
                  diameter_m, height_m, density_t_m3, loaded_at, mode, lat, lng
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    silo_id,
                    site_id,
                    f"S-{code_prefix}-{idx + 1:02d}",
                    grain,
                    "2025/26" if idx % 2 else "2024/25",
                    producers[idx % len(producers)],
                    f"{town}, {province}",
                    capacity,
                    diameter,
                    height,
                    density,
                    (now - timedelta(days=days_stored)).date().isoformat(),
                    "Automatico" if motor_on and random() > 0.35 else "Manual",
                    lat + math.sin(angle) * radius,
                    lng + math.cos(angle) * radius,
                ),
            )
            for reading_idx in range(12):
                drift = (reading_idx - 11) * 0.04
                recorded_at = now - timedelta(hours=(11 - reading_idx) * 2)
                conn.execute(
                    """
                    INSERT INTO telemetry (
                      silo_id, recorded_at, grain_humidity, grain_temperature,
                      internal_humidity, internal_temperature, fill_percent, motor_on,
                      status, safe_days, volume_m3, estimated_tons
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        silo_id,
                        recorded_at.isoformat(),
                        round(humidity + drift, 1),
                        round(temp + drift * 1.6, 1),
                        round(internal_humidity + drift * 1.8, 1),
                        round(temp - 1.8 + drift, 1),
                        fill,
                        int(motor_on),
                        status,
                        safe_days,
                        volume,
                        tons,
                    ),
                )
    conn.commit()


def latest_sites() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            WITH latest_telemetry AS (
              SELECT t.*
              FROM telemetry t
              JOIN (
                SELECT silo_id, MAX(recorded_at) AS max_recorded_at
                FROM telemetry
                GROUP BY silo_id
              ) latest ON latest.silo_id = t.silo_id AND latest.max_recorded_at = t.recorded_at
            ),
            latest_weather AS (
              SELECT w.*
              FROM weather w
              JOIN (
                SELECT site_id, MAX(recorded_at) AS max_recorded_at
                FROM weather
                GROUP BY site_id
              ) latest ON latest.site_id = w.site_id AND latest.max_recorded_at = w.recorded_at
            )
            SELECT
              s.id AS site_id, s.name, s.province, s.department, s.town, s.lat AS site_lat, s.lng AS site_lng,
              s.cuit, s.plant_number, s.registry_status, s.address, s.location_source,
              s.region, s.phone, s.email, s.coord_maps, s.maps_url, s.directions_url,
              s.original_lat, s.original_lng, s.source_file, s.boundary_geojson,
              w.recorded_at AS weather_recorded_at, w.external_temperature, w.external_humidity,
              w.dew_point, w.wind_kmh, w.pressure_hpa, w.rain_mm,
              si.id AS silo_id, si.code, si.grain, si.campaign, si.producer, si.origin,
              si.capacity_m3, si.diameter_m, si.height_m, si.density_t_m3, si.loaded_at, si.mode, si.lat AS silo_lat, si.lng AS silo_lng,
              lt.recorded_at AS telemetry_recorded_at, lt.grain_humidity, lt.grain_temperature,
              lt.internal_humidity, lt.internal_temperature, lt.fill_percent, lt.motor_on,
              lt.status, lt.safe_days, lt.volume_m3, lt.estimated_tons
            FROM sites s
            LEFT JOIN latest_weather w ON w.site_id = s.id
            LEFT JOIN silos si ON si.site_id = s.id
            LEFT JOIN latest_telemetry lt ON lt.silo_id = si.id
            ORDER BY s.province, s.town, si.code
            """
        ).fetchall()

    by_site: dict[str, dict] = {}
    for row in rows:
        site = by_site.setdefault(
            row["site_id"],
            {
                "id": row["site_id"],
                "name": row["name"],
                "province": row["province"],
                "department": row["department"],
                "town": row["town"],
                "lat": row["site_lat"],
                "lng": row["site_lng"],
                "cuit": row["cuit"],
                "plantNumber": row["plant_number"],
                "registryStatus": row["registry_status"],
                "address": row["address"],
                "locationSource": row["location_source"],
                "region": row["region"],
                "phone": row["phone"],
                "email": row["email"],
                "coordMaps": row["coord_maps"],
                "mapsUrl": row["maps_url"],
                "directionsUrl": row["directions_url"],
                "originalLat": row["original_lat"],
                "originalLng": row["original_lng"],
                "sourceFile": row["source_file"],
                "boundary": json.loads(row["boundary_geojson"]) if row["boundary_geojson"] else None,
                "weather": {
                    "recordedAt": row["weather_recorded_at"],
                    "externalTemperature": row["external_temperature"],
                    "externalHumidity": row["external_humidity"],
                    "dewPoint": row["dew_point"],
                    "windKmh": row["wind_kmh"],
                    "pressureHpa": row["pressure_hpa"],
                    "rainMm": row["rain_mm"],
                },
                "silos": [],
            },
        )
        if row["silo_id"]:
            site["silos"].append(
                {
                    "id": row["silo_id"],
                    "code": row["code"],
                    "grain": row["grain"],
                    "campaign": row["campaign"],
                    "producer": row["producer"],
                    "origin": row["origin"],
                    "capacity": row["capacity_m3"],
                    "diameter": row["diameter_m"],
                    "height": row["height_m"],
                    "density": row["density_t_m3"],
                    "loadedAt": row["loaded_at"],
                    "mode": row["mode"],
                    "lat": row["silo_lat"],
                    "lng": row["silo_lng"],
                    "recordedAt": row["telemetry_recorded_at"],
                    "humidity": row["grain_humidity"],
                    "temp": row["grain_temperature"],
                    "internalHumidity": row["internal_humidity"],
                    "internalTemp": row["internal_temperature"],
                    "fill": row["fill_percent"],
                    "motorOn": bool(row["motor_on"]),
                    "status": row["status"],
                    "safeDays": row["safe_days"],
                    "volume": row["volume_m3"],
                    "tons": row["estimated_tons"],
                }
            )
    with connect() as conn:
        counts = conn.execute(
            "SELECT parent_site_id, COUNT(*) AS total FROM dependencies WHERE parent_site_id IS NOT NULL GROUP BY parent_site_id"
        ).fetchall()
    for row in counts:
        if row["parent_site_id"] in by_site:
            by_site[row["parent_site_id"]]["dependencyCount"] = row["total"]
    for site in by_site.values():
        site.setdefault("dependencyCount", 0)
    return list(by_site.values())


def list_dependencies() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT d.*, s.name AS parent_name
            FROM dependencies d
            LEFT JOIN sites s ON s.id = d.parent_site_id
            ORDER BY d.ccp_associated, d.province, d.town
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "parentSiteId": row["parent_site_id"],
            "parentName": row["parent_name"],
            "siteType": row["site_type"],
            "province": row["province"],
            "department": row["department"],
            "town": row["town"],
            "publishedAddress": row["published_address"],
            "ccpAssociated": row["ccp_associated"],
            "sourceUrl": row["source_url"],
            "sourceStatus": row["source_status"],
            "lat": row["lat"],
            "lng": row["lng"],
            "locationSource": row["location_source"],
            "siloCount": row["silo_count"],
            "capacityM3": row["capacity_m3"],
            "notes": row["notes"],
        }
        for row in rows
    ]


def insert_dependency(payload: dict) -> dict:
    required = ["site_type", "province", "town", "ccp_associated"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    dependency_id = payload.get("id") or f"dep-{slugify(payload['ccp_associated'])}-{slugify(payload['town'])}-{round(datetime.now().timestamp())}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO dependencies (
              id, parent_site_id, site_type, province, department, town, published_address,
              ccp_associated, source_url, source_status, lat, lng, location_source,
              silo_count, capacity_m3, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dependency_id,
                payload.get("parent_site_id"),
                payload["site_type"],
                payload["province"],
                payload.get("department"),
                payload["town"],
                payload.get("published_address"),
                payload["ccp_associated"],
                payload.get("source_url"),
                payload.get("source_status", "Carga manual demo"),
                payload.get("lat"),
                payload.get("lng"),
                payload.get("location_source", "Carga manual"),
                int(payload.get("silo_count", 0) or 0),
                int(payload.get("capacity_m3", 0) or 0),
                payload.get("notes"),
            ),
        )
        conn.commit()
    return {"ok": True, "dependencyId": dependency_id}


def public_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "siteId": row["site_id"],
        "scopeType": row["scope_type"],
        "scopeValue": row["scope_value"],
        "active": bool(row["active"]),
        "permissions": {
            "view": bool(row.get("can_view", 1)),
            "editSites": bool(row.get("can_edit_sites", 0)),
            "editSilos": bool(row.get("can_edit_silos", 0)),
            "manageUsers": bool(row.get("can_manage_users", 0)),
            "exportReports": bool(row.get("can_export_reports", 1)),
        },
    }


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def write_audit(
    conn,
    action: str,
    entity_type: str,
    entity_id: str,
    site_id: str | None,
    before_data: dict | None,
    after_data: dict | None,
    actor: dict | None = None,
) -> None:
    actor = actor or {}
    conn.execute(
        """
        INSERT INTO audit_log (
          actor_user_id, actor_email, action, entity_type, entity_id,
          site_id, before_data, after_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor.get("userId") or actor.get("actor_user_id"),
            actor.get("email") or actor.get("actor_email"),
            action,
            entity_type,
            entity_id,
            site_id,
            Jsonb(json_safe(before_data)) if before_data is not None else None,
            Jsonb(json_safe(after_data)) if after_data is not None else None,
        ),
    )


def actor_from_payload(payload: dict) -> dict:
    return {
        "userId": payload.get("actor_user_id") or payload.get("user_id"),
        "email": payload.get("actor_email") or payload.get("email_actor"),
    }


def login_user(payload: dict) -> dict:
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, email, role, site_id, scope_type, scope_value, active,
              can_view, can_edit_sites, can_edit_silos, can_manage_users, can_export_reports
            FROM users
            WHERE lower(email) = ? AND password = ? AND active = 1
            """,
            (email, password),
        ).fetchone()
    if not row:
        raise ValueError("Credenciales invalidas")
    return {"ok": True, "user": public_user(row)}


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, email, role, site_id, scope_type, scope_value, active,
              can_view, can_edit_sites, can_edit_silos, can_manage_users, can_export_reports
            FROM users
            ORDER BY role, name
            """
        ).fetchall()
    return [public_user(row) for row in rows]


def insert_user(payload: dict) -> dict:
    required = ["name", "email", "password", "role"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    user_id = payload.get("id") or f"user-{slugify(payload['email'])}"
    scope_type = payload.get("scope_type") or ("national" if payload["role"] == "admin" else "site")
    scope_value = payload.get("scope_value") or payload.get("site_id")
    site_id = payload.get("site_id") or (scope_value if scope_type == "site" else None)
    if scope_type == "national":
        scope_value = None
        site_id = None
    if scope_type in {"province", "site"} and not scope_value:
        raise ValueError("Debe elegir el alcance del usuario")
    is_admin = payload["role"] == "admin"
    can_view = int(payload.get("can_view", 1))
    can_edit_sites = int(payload.get("can_edit_sites", 1 if is_admin else 0))
    can_edit_silos = int(payload.get("can_edit_silos", 1 if is_admin else 1))
    can_manage_users = int(payload.get("can_manage_users", 1 if is_admin else 0))
    can_export_reports = int(payload.get("can_export_reports", 1))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users (
              id, name, email, password, role, site_id, scope_type, scope_value, active,
              can_view, can_edit_sites, can_edit_silos, can_manage_users, can_export_reports
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["email"].strip().lower(),
                payload["password"],
                payload["role"],
                site_id,
                scope_type,
                scope_value,
                int(payload.get("active", 1)),
                can_view,
                can_edit_sites,
                can_edit_silos,
                can_manage_users,
                can_export_reports,
            ),
        )
        conn.commit()
    return {"ok": True, "userId": user_id}


def normalize_user_payload(payload: dict, current: dict | None = None) -> dict:
    role = payload.get("role") or (current.get("role") if current else None)
    scope_type = payload.get("scope_type") or (current.get("scope_type") if current else None) or ("national" if role == "admin" else "site")
    scope_value = payload.get("scope_value") if "scope_value" in payload else (current.get("scope_value") if current else None)
    site_id = payload.get("site_id") if "site_id" in payload else (current.get("site_id") if current else None)
    if scope_type == "site":
        site_id = site_id or scope_value
        scope_value = scope_value or site_id
    if scope_type == "province":
        site_id = None
    if scope_type == "national":
        scope_value = None
        site_id = None
    if scope_type in {"province", "site"} and not scope_value:
        raise ValueError("Debe elegir el alcance del usuario")
    is_admin = role == "admin"
    return {
        "role": role,
        "scope_type": scope_type,
        "scope_value": scope_value,
        "site_id": site_id,
        "can_view": int(payload.get("can_view", current.get("can_view", 1) if current else 1)),
        "can_edit_sites": int(payload.get("can_edit_sites", current.get("can_edit_sites", 1 if is_admin else 0) if current else (1 if is_admin else 0))),
        "can_edit_silos": int(payload.get("can_edit_silos", current.get("can_edit_silos", 1) if current else 1)),
        "can_manage_users": int(payload.get("can_manage_users", current.get("can_manage_users", 1 if is_admin else 0) if current else (1 if is_admin else 0))),
        "can_export_reports": int(payload.get("can_export_reports", current.get("can_export_reports", 1) if current else 1)),
        "active": int(payload.get("active", current.get("active", 1) if current else 1)),
    }


def update_user(user_id: str, payload: dict) -> dict:
    if user_id == "user-admin":
        raise ValueError("El administrador principal no se puede editar")
    with connect() as conn:
        current = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not current:
            raise KeyError("User not found")
        normalized = normalize_user_payload(payload, current)
        conn.execute(
            """
            UPDATE users SET
              name = ?, email = ?, password = ?, role = ?, site_id = ?,
              scope_type = ?, scope_value = ?, active = ?,
              can_view = ?, can_edit_sites = ?, can_edit_silos = ?,
              can_manage_users = ?, can_export_reports = ?, updated_at = now()
            WHERE id = ?
            """,
            (
                payload.get("name", current["name"]),
                payload.get("email", current["email"]).strip().lower(),
                payload.get("password", current["password"]),
                normalized["role"],
                normalized["site_id"],
                normalized["scope_type"],
                normalized["scope_value"],
                normalized["active"],
                normalized["can_view"],
                normalized["can_edit_sites"],
                normalized["can_edit_silos"],
                normalized["can_manage_users"],
                normalized["can_export_reports"],
                user_id,
            ),
        )
        write_audit(conn, "update", "user", user_id, normalized["site_id"], dict(current), {**payload, **normalized}, actor_from_payload(payload))
        conn.commit()
    return {"ok": True, "userId": user_id}


def delete_user(user_id: str) -> dict:
    if user_id == "user-admin":
        raise ValueError("El administrador principal no se puede eliminar")
    with connect() as conn:
        current = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not current:
            raise KeyError("User not found")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        write_audit(conn, "delete", "user", user_id, current["site_id"], dict(current), None, {})
        conn.commit()
    return {"ok": True, "userId": user_id}


def telemetry_history(silo_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT recorded_at, grain_humidity, grain_temperature, internal_humidity,
              internal_temperature, fill_percent, motor_on, status, safe_days,
              volume_m3, estimated_tons
            FROM telemetry
            WHERE silo_id = ?
            ORDER BY recorded_at ASC
            """,
            (silo_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-").replace("--", "-")


def insert_site(payload: dict) -> dict:
    required = ["name", "province", "department", "town", "lat", "lng"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    site_id = payload.get("id") or f"site-{slugify(payload['town'])}-{round(datetime.now().timestamp())}"
    with connect() as conn:
      conn.execute(
          """
          INSERT INTO sites (
            id, name, province, department, town, lat, lng, cuit, plant_number,
            registry_status, address, location_source
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              site_id,
              payload["name"],
              payload["province"],
              payload["department"],
              payload["town"],
              float(payload["lat"]),
              float(payload["lng"]),
              payload.get("cuit"),
              payload.get("plant_number"),
              payload.get("registry_status", "Alta manual demo"),
              payload.get("address"),
              payload.get("location_source", "Manual"),
          ),
      )
      temp = float(payload.get("external_temperature", 20))
      humidity = float(payload.get("external_humidity", 65))
      conn.execute(
          """
          INSERT INTO weather (
            site_id, recorded_at, external_temperature, external_humidity,
            dew_point, wind_kmh, pressure_hpa, rain_mm
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              site_id,
              datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              temp,
              humidity,
              dew_point(temp, humidity),
              float(payload.get("wind_kmh", 8)),
              float(payload.get("pressure_hpa", 1013)),
              float(payload.get("rain_mm", 0)),
          ),
      )
      conn.commit()
    return {"ok": True, "siteId": site_id}


def update_site_location(site_id: str, payload: dict) -> dict:
    required = ["lat", "lng"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    lat = float(payload["lat"])
    lng = float(payload["lng"])
    source = payload.get("location_source", "Relevamiento satelital")
    coord_maps = f"{lat:.7f},{lng:.7f}"
    maps_url = f"https://www.google.com/maps/search/?api=1&query={lat:.7f},{lng:.7f}"
    directions_url = f"https://www.google.com/maps/dir/?api=1&destination={lat:.7f},{lng:.7f}"
    with connect() as conn:
        before = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        cur = conn.execute(
            """
            UPDATE sites
            SET lat = ?, lng = ?, location_source = ?, coord_maps = ?,
              maps_url = ?, directions_url = ?, updated_at = now()
            WHERE id = ?
            """,
            (lat, lng, source, coord_maps, maps_url, directions_url, site_id),
        )
        if cur.rowcount == 0:
            raise KeyError("Site not found")
        write_audit(
            conn,
            "update_location",
            "site",
            site_id,
            site_id,
            dict(before) if before else None,
            {"lat": lat, "lng": lng, "locationSource": source, "coordMaps": coord_maps},
            actor_from_payload(payload),
        )
        conn.commit()
    return {
        "ok": True,
        "siteId": site_id,
        "lat": lat,
        "lng": lng,
        "locationSource": source,
        "coordMaps": coord_maps,
        "mapsUrl": maps_url,
        "directionsUrl": directions_url,
    }


def update_site_metadata(site_id: str, payload: dict) -> dict:
    allowed = ["name", "province", "department", "town", "address", "region", "phone", "email"]
    fields = [key for key in allowed if key in payload]
    if not fields:
        raise ValueError("No hay campos para actualizar")
    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = [payload[field] for field in fields]
    values.append(site_id)
    with connect() as conn:
        before = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        cur = conn.execute(f"UPDATE sites SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            raise KeyError("Site not found")
        write_audit(conn, "update_metadata", "site", site_id, site_id, dict(before) if before else None, {field: payload[field] for field in fields}, actor_from_payload(payload))
        conn.commit()
    return {"ok": True, "siteId": site_id}


def update_site_boundary(site_id: str, payload: dict) -> dict:
    points = payload.get("boundary")
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("El limite necesita al menos 3 puntos")
    normalized = []
    for point in points:
        normalized.append({"lat": float(point["lat"]), "lng": float(point["lng"])})
    with connect() as conn:
        before = conn.execute("SELECT id, boundary_geojson FROM sites WHERE id = ?", (site_id,)).fetchone()
        cur = conn.execute(
            "UPDATE sites SET boundary_geojson = ?, location_source = ? WHERE id = ?",
            (json.dumps(normalized), "Limite dibujado por usuario", site_id),
        )
        if cur.rowcount == 0:
            raise KeyError("Site not found")
        write_audit(conn, "update_boundary", "site", site_id, site_id, dict(before) if before else None, {"boundary": normalized}, actor_from_payload(payload))
        conn.commit()
    return {"ok": True, "siteId": site_id, "boundary": normalized}


def insert_silo(site_id: str, payload: dict) -> dict:
    required = ["code", "grain", "diameter_m", "height_m", "lat", "lng"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    grain = payload["grain"]
    if grain not in GRAINS:
        raise ValueError("Invalid grain")
    diameter = float(payload["diameter_m"])
    height = float(payload["height_m"])
    capacity = silo_capacity_m3(diameter, height)
    fill = float(payload.get("fill_percent", 65))
    volume = round(capacity * fill / 100)
    density = GRAINS[grain]["density"]
    tons = round(volume * density)
    humidity = float(payload.get("grain_humidity", GRAINS[grain]["safe_humidity"]))
    temp = float(payload.get("grain_temperature", 20))
    safe_days = int(payload.get("safe_days", max(0, round(150 - max(0, humidity - GRAINS[grain]["safe_humidity"]) * 18 - max(0, temp - 22) * 3))))
    status = classify_silo(grain, humidity, temp, safe_days)
    motor_on = int(humidity > GRAINS[grain]["safe_humidity"] + 0.8 or temp > 25.5)
    silo_id = payload.get("id") or f"{site_id}-{slugify(payload['code'])}"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with connect() as conn:
        site = conn.execute("SELECT town, province FROM sites WHERE id = ?", (site_id,)).fetchone()
        if not site:
            raise KeyError("Site not found")
        conn.execute(
            """
            INSERT INTO silos (
              id, site_id, code, grain, campaign, producer, origin, capacity_m3,
              diameter_m, height_m, density_t_m3, loaded_at, mode, lat, lng
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                silo_id,
                site_id,
                payload["code"],
                grain,
                payload.get("campaign", "2025/26"),
                payload.get("producer", "Productor / lote demo"),
                payload.get("origin", f"{site['town']}, {site['province']}"),
                capacity,
                diameter,
                height,
                density,
                payload.get("loaded_at", now.date().isoformat()),
                payload.get("mode", "Manual"),
                float(payload["lat"]),
                float(payload["lng"]),
            ),
        )
        conn.execute(
            """
            INSERT INTO telemetry (
              silo_id, recorded_at, grain_humidity, grain_temperature,
              internal_humidity, internal_temperature, fill_percent, motor_on,
              status, safe_days, volume_m3, estimated_tons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                silo_id,
                now.isoformat(),
                humidity,
                temp,
                float(payload.get("internal_humidity", 58)),
                float(payload.get("internal_temperature", temp - 1)),
                fill,
                motor_on,
                status,
                safe_days,
                volume,
                tons,
            ),
        )
        write_audit(
            conn,
            "create",
            "silo",
            silo_id,
            site_id,
            None,
            {"code": payload["code"], "lat": float(payload["lat"]), "lng": float(payload["lng"]), "diameter": diameter, "height": height},
            actor_from_payload(payload),
        )
        conn.commit()
    return {"ok": True, "siloId": silo_id, "capacityM3": capacity, "estimatedTons": tons}


def update_silo(silo_id: str, payload: dict) -> dict:
    with connect() as conn:
        current = conn.execute("SELECT * FROM silos WHERE id = ?", (silo_id,)).fetchone()
        if not current:
            raise KeyError("Silo not found")
        before = dict(current)
    data = {**payload, "id": silo_id}
    with connect() as conn:
        silo = conn.execute("SELECT site_id FROM silos WHERE id = ?", (silo_id,)).fetchone()
        site_id = silo["site_id"]
        conn.execute("DELETE FROM telemetry WHERE silo_id = ?", (silo_id,))
        conn.execute("DELETE FROM silos WHERE id = ?", (silo_id,))
        write_audit(conn, "update", "silo", silo_id, site_id, before, data, actor_from_payload(payload))
        conn.commit()
    result = insert_silo(site_id, data)
    return {"ok": True, "siloId": result["siloId"]}


def delete_silo(silo_id: str) -> dict:
    with connect() as conn:
        before = conn.execute("SELECT * FROM silos WHERE id = ?", (silo_id,)).fetchone()
        conn.execute("DELETE FROM telemetry WHERE silo_id = ?", (silo_id,))
        cur = conn.execute("DELETE FROM silos WHERE id = ?", (silo_id,))
        if cur.rowcount == 0:
            raise KeyError("Silo not found")
        write_audit(conn, "delete", "silo", silo_id, before["site_id"] if before else None, dict(before) if before else None, None, {})
        conn.commit()
    return {"ok": True, "siloId": silo_id}


def insert_telemetry(silo_id: str, payload: dict) -> dict:
    required = ["grain_humidity", "grain_temperature", "internal_humidity", "internal_temperature", "fill_percent"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    with connect() as conn:
        silo = conn.execute("SELECT grain, capacity_m3, density_t_m3 FROM silos WHERE id = ?", (silo_id,)).fetchone()
        if not silo:
            raise KeyError("Silo not found")
        grain = silo["grain"]
        fill = float(payload["fill_percent"])
        volume = round(silo["capacity_m3"] * fill / 100)
        tons = round(volume * silo["density_t_m3"])
        humidity = float(payload["grain_humidity"])
        temp = float(payload["grain_temperature"])
        safe_days = int(payload.get("safe_days", max(0, round(150 - max(0, humidity - GRAINS[grain]["safe_humidity"]) * 18 - max(0, temp - 22) * 3))))
        status = payload.get("status") or classify_silo(grain, humidity, temp, safe_days)
        motor_on = int(bool(payload.get("motor_on", humidity > GRAINS[grain]["safe_humidity"] + 0.8 or temp > 25.5)))
        recorded_at = payload.get("recorded_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            """
            INSERT INTO telemetry (
              silo_id, recorded_at, grain_humidity, grain_temperature,
              internal_humidity, internal_temperature, fill_percent, motor_on,
              status, safe_days, volume_m3, estimated_tons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                silo_id,
                recorded_at,
                humidity,
                temp,
                float(payload["internal_humidity"]),
                float(payload["internal_temperature"]),
                fill,
                motor_on,
                status,
                safe_days,
                volume,
                tons,
            ),
        )
        conn.commit()
    return {"ok": True, "siloId": silo_id, "recordedAt": recorded_at}


def insert_weather(site_id: str, payload: dict) -> dict:
    required = ["external_temperature", "external_humidity", "wind_kmh", "pressure_hpa", "rain_mm"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing fields: {', '.join(missing)}")
    temp = float(payload["external_temperature"])
    humidity = float(payload["external_humidity"])
    recorded_at = payload.get("recorded_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM sites WHERE id = ?", (site_id,)).fetchone()
        if not exists:
            raise KeyError("Site not found")
        conn.execute(
            """
            INSERT INTO weather (
              site_id, recorded_at, external_temperature, external_humidity,
              dew_point, wind_kmh, pressure_hpa, rain_mm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_id,
                recorded_at,
                temp,
                humidity,
                float(payload.get("dew_point", dew_point(temp, humidity))),
                float(payload["wind_kmh"]),
                float(payload["pressure_hpa"]),
                float(payload["rain_mm"]),
            ),
        )
        conn.commit()
    return {"ok": True, "siteId": site_id, "recordedAt": recorded_at}


def open_meteo_series(site_id: str) -> dict:
    with connect() as conn:
        site = conn.execute("SELECT id, name, town, province, lat, lng FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not site:
        raise KeyError("Site not found")
    params = urlencode(
        {
            "latitude": site["lat"],
            "longitude": site["lng"],
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "dew_point_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                    "pressure_msl",
                ]
            ),
            "past_days": 2,
            "forecast_days": 3,
            "timezone": "auto",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    rows = []
    for idx, time_value in enumerate(times):
        rows.append(
            {
                "time": time_value,
                "temperature": hourly.get("temperature_2m", [None] * len(times))[idx],
                "humidity": hourly.get("relative_humidity_2m", [None] * len(times))[idx],
                "dewPoint": hourly.get("dew_point_2m", [None] * len(times))[idx],
                "rain": hourly.get("precipitation", [None] * len(times))[idx],
                "wind": hourly.get("wind_speed_10m", [None] * len(times))[idx],
                "gusts": hourly.get("wind_gusts_10m", [None] * len(times))[idx],
                "pressure": hourly.get("pressure_msl", [None] * len(times))[idx],
            }
        )
    return {
        "site": {
            "id": site["id"],
            "name": site["name"],
            "town": site["town"],
            "province": site["province"],
            "lat": site["lat"],
            "lng": site["lng"],
        },
        "source": "Open-Meteo Forecast API",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "timezone": payload.get("timezone"),
        "series": rows,
    }


def persist_weather_series(site_id: str) -> dict:
    payload = open_meteo_series(site_id)
    series = payload["series"]
    now = datetime.now(timezone.utc)
    current_rows = [row for row in series if parse_weather_time(row["time"]) <= now]
    latest = current_rows[-1] if current_rows else (series[0] if series else None)
    with connect() as conn:
        if latest:
            conn.execute(
                """
                INSERT INTO weather (
                  site_id, recorded_at, external_temperature, external_humidity,
                  dew_point, wind_kmh, pressure_hpa, rain_mm, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, recorded_at, source) DO UPDATE SET
                  external_temperature = EXCLUDED.external_temperature,
                  external_humidity = EXCLUDED.external_humidity,
                  dew_point = EXCLUDED.dew_point,
                  wind_kmh = EXCLUDED.wind_kmh,
                  pressure_hpa = EXCLUDED.pressure_hpa,
                  rain_mm = EXCLUDED.rain_mm
                """,
                (
                    site_id,
                    latest["time"],
                    latest["temperature"] or 0,
                    latest["humidity"] or 0,
                    latest["dewPoint"] or 0,
                    latest["wind"] or 0,
                    latest["pressure"] or 0,
                    latest["rain"] or 0,
                    "Open-Meteo",
                ),
            )
        for row in series:
            if parse_weather_time(row["time"]) < now:
                continue
            conn.execute(
                """
                INSERT INTO weather_forecasts (
                  site_id, forecast_for, external_temperature, external_humidity,
                  dew_point, wind_kmh, wind_gust_kmh, pressure_hpa, rain_mm, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, forecast_for, source) DO UPDATE SET
                  fetched_at = now(),
                  external_temperature = EXCLUDED.external_temperature,
                  external_humidity = EXCLUDED.external_humidity,
                  dew_point = EXCLUDED.dew_point,
                  wind_kmh = EXCLUDED.wind_kmh,
                  wind_gust_kmh = EXCLUDED.wind_gust_kmh,
                  pressure_hpa = EXCLUDED.pressure_hpa,
                  rain_mm = EXCLUDED.rain_mm
                """,
                (
                    site_id,
                    row["time"],
                    row["temperature"],
                    row["humidity"],
                    row["dewPoint"],
                    row["wind"],
                    row["gusts"],
                    row["pressure"],
                    row["rain"],
                    "Open-Meteo",
                ),
            )
        conn.commit()
    return {"siteId": site_id, "points": len(series), "source": payload["source"]}


def refresh_weather_all_sites(limit: int | None = None) -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT id FROM sites ORDER BY province, town").fetchall()
    refreshed = []
    errors = []
    for row in rows[:limit] if limit else rows:
        try:
            refreshed.append(persist_weather_series(row["id"]))
        except Exception as exc:
            errors.append({"siteId": row["id"], "error": str(exc)})
    return {"ok": True, "refreshed": len(refreshed), "errors": errors[:12]}


def start_weather_scheduler() -> None:
    def worker():
        while True:
            try:
                refresh_weather_all_sites()
            except Exception as exc:
                print(f"weather refresh failed: {exc}")
            time.sleep(max(1, WEATHER_REFRESH_MINUTES) * 60)

    thread = threading.Thread(target=worker, name="weather-refresh", daemon=True)
    thread.start()


def parse_weather_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "db": "postgresql", "weatherRefreshMinutes": WEATHER_REFRESH_MINUTES, "generatedAt": datetime.now(timezone.utc).isoformat()})
            return
        if parsed.path == "/api/sites":
            self.send_json({"sites": latest_sites()})
            return
        if parsed.path == "/api/dependencies":
            self.send_json({"dependencies": list_dependencies()})
            return
        if parsed.path == "/api/users":
            self.send_json({"users": list_users()})
            return
        if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/weather-series"):
            try:
                self.send_json(open_meteo_series(parsed.path.split("/")[3]))
            except KeyError as exc:
                self.send_json({"error": str(exc)}, status=404)
            except Exception as exc:
                self.send_json({"error": "Weather provider unavailable", "detail": str(exc)}, status=502)
            return
        if parsed.path.startswith("/api/silos/") and parsed.path.endswith("/telemetry"):
            silo_id = parsed.path.split("/")[3]
            self.send_json({"siloId": silo_id, "telemetry": telemetry_history(silo_id)})
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/sites":
                self.send_json(insert_site(payload), status=201)
                return
            if parsed.path == "/api/dependencies":
                self.send_json(insert_dependency(payload), status=201)
                return
            if parsed.path == "/api/login":
                self.send_json(login_user(payload))
                return
            if parsed.path == "/api/weather/refresh":
                self.send_json(refresh_weather_all_sites(limit=payload.get("limit")))
                return
            if parsed.path == "/api/users":
                self.send_json(insert_user(payload), status=201)
                return
            if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/silos"):
                self.send_json(insert_silo(parsed.path.split("/")[3], payload), status=201)
                return
            if parsed.path.startswith("/api/silos/") and parsed.path.endswith("/telemetry"):
                self.send_json(insert_telemetry(parsed.path.split("/")[3], payload), status=201)
                return
            if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/weather"):
                self.send_json(insert_weather(parsed.path.split("/")[3], payload), status=201)
                return
            self.send_json({"error": "Not found"}, status=404)
        except KeyError as exc:
            self.send_json({"error": str(exc)}, status=404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/location"):
                self.send_json(update_site_location(parsed.path.split("/")[3], payload))
                return
            if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/metadata"):
                self.send_json(update_site_metadata(parsed.path.split("/")[3], payload))
                return
            if parsed.path.startswith("/api/sites/") and parsed.path.endswith("/boundary"):
                self.send_json(update_site_boundary(parsed.path.split("/")[3], payload))
                return
            if parsed.path.startswith("/api/users/"):
                self.send_json(update_user(parsed.path.split("/")[3], payload))
                return
            if parsed.path.startswith("/api/silos/"):
                self.send_json(update_silo(parsed.path.split("/")[3], payload))
                return
            self.send_json({"error": "Not found"}, status=404)
        except KeyError as exc:
            self.send_json({"error": str(exc)}, status=404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/users/"):
                self.send_json(delete_user(parsed.path.split("/")[3]))
                return
            if parsed.path.startswith("/api/silos/"):
                self.send_json(delete_silo(parsed.path.split("/")[3]))
                return
            self.send_json({"error": "Not found"}, status=404)
        except KeyError as exc:
            self.send_json({"error": str(exc)}, status=404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_db()
    start_weather_scheduler()
    print(f"AFA Silo Trace running at http://127.0.0.1:{PORT} with PostgreSQL and {WEATHER_REFRESH_MINUTES} min weather refresh")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
