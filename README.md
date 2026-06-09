# AFA Silo Trace Demo

Demo web para monitoreo, automatizacion y trazabilidad de silos de chapa en acopios AFA.

Incluye:

- Login inicial con roles demo.
- Dashboard operativo post-login con tarjetas de establecimientos, silos, capacidad, volumen, toneladas estimadas, alertas y clima externo.
- Menu lateral por modulos: Dashboard, Mapa, Sitios, Alertas y Usuarios.
- Cierre de sesion desde el header.
- Permisos por alcance configurable: toda la red nacional, una provincia o un establecimiento puntual.
- Alta de usuarios desde la interfaz de administracion.
- Base semilla `db/red_afa_seed.csv` generada desde `RED_AFA_coordenadas_maps.xlsx`: 130 sitios AFA con provincia, partido, localidad, region, domicilio, telefono/correo cuando existe, coordenadas decimales, coordenadas originales y links de Google Maps / como llegar.
- Soporte para establecimientos sin silos cargados: se muestran en mapa/filtros y permiten cargar el primer silo manualmente.
- Mapa interactivo de acopios y silos.
- Vista satelital por defecto para relevar plantas y silos fisicos.
- Filtros por provincia, departamento, localidad, grano y estado.
- Datos internos del silo: humedad, temperatura, volumen, toneladas, dias almacenados y dias seguros estimados.
- Datos climaticos externos por acopio: temperatura, humedad ambiente, punto de rocio, viento, presion y lluvia.
- Clima real al seleccionar sitio usando Open-Meteo por coordenada del establecimiento, sin API key.
- Herramientas de relevamiento en mapa: mover punto del establecimiento con guardado explicito, editar coordenadas, editar ficha, ubicar silo desde el modal de creacion y dibujar limite/poligono con deshacer/cancelar/guardar.
- Desglose por acopio con cada silo identificado.
- Representacion de silos como circunferencias sobre el mapa usando diametro en metros.
- Modo para ajustar la ubicacion real de la planta haciendo click sobre mapa satelital.
- Alta demo de acopios y silos desde la interfaz.
- Alta manual de dependencias publicadas por AFA: CCP, Sub-Centro, Oficina Comercial, Representante y Otro Centro.
- Filtros por tipo de sitio, provincia, departamento/localidad y CCP asociado, por ejemplo todos los sitios asociados a Maciel aunque esten en distintas provincias.
- Navegacion por establecimiento: primero se selecciona una planta/CCP y luego se inspeccionan sus silos.
- Menus desplegables para separar filtros avanzados, establecimientos y dependencias.
- Calculo automatico de capacidad del silo con diametro y altura: pi * radio^2 * altura.
- Backend con API REST.
- Base PostgreSQL obligatoria via `DATABASE_URL`.
- Auditoria de cambios para sitios/silos con actor de usuario cuando la UI envia el usuario activo.
- Tablas preparadas para pronostico climatico horario y mediciones externas.
- Refresco automatico de clima cada 15 minutos configurable con `WEATHER_REFRESH_MINUTES`.
- Certificado demo de conservacion de granos.

## Ejecutar local

```bash
python backend/app.py
```

Abrir:

```text
http://localhost:8788
```

Requiere PostgreSQL:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
WEATHER_REFRESH_MINUTES=15
```

Durante el arranque crea/actualiza el esquema PostgreSQL desde `db/schema_postgres.sql` e importa/actualiza la Red AFA desde `db/red_afa_seed.csv`, usando la coordenada exacta y el link de Maps de cada sitio.

Credenciales demo:

```text
Admin nacional
admin@afa.demo / admin123

Operador CCP Arrecifes
arrecifes@afa.demo / arrecifes123
```

## Despliegue rapido

### GitHub

Este proyecto esta pensado para vivir como repositorio independiente. Desde la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Initial AFA Silo Trace demo"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/afa-silo-trace.git
git push -u origin main
```

La base es PostgreSQL. No hay modo SQLite productivo ni archivo local de base.

### Railway

1. Crear un nuevo proyecto en Railway desde el repo de GitHub.
2. Agregar un servicio PostgreSQL en Railway.
3. Conectar la variable `DATABASE_URL` del PostgreSQL al servicio web.
4. Railway detecta el `Dockerfile` y usa `railway.json`.
5. Variables:

```text
PORT=8788
HOST=0.0.0.0
DATABASE_URL=${{Postgres.DATABASE_URL}}
WEATHER_REFRESH_MINUTES=15
```

6. El comando de arranque es:

```bash
python backend/app.py
```

### Docker

```bash
docker build -t afa-silo-trace-demo .
docker run -p 8788:8788 afa-silo-trace-demo
```

### Render / Heroku-like

Usar:

```bash
python backend/app.py
```

Variables:

```text
PORT=8788
HOST=0.0.0.0
```

## Estructura

```text
backend/
  app.py              API REST + servidor estatico
db/
  schema_postgres.sql Modelo relacional PostgreSQL productivo
  red_afa_seed.csv    Base AFA georreferenciada desde RED_AFA_coordenadas_maps.xlsx
frontend/
  index.html          App shell
  src/
    app.js            Logica de mapa, filtros y UI
    styles.css        Look & feel AFA fluor
```

## Endpoints principales

- `GET /api/health`
- `POST /api/login`
- `GET /api/users`
- `POST /api/users`
- `GET /api/sites`
- `GET /api/dependencies`
- `GET /api/silos/{silo_id}/telemetry`
- `POST /api/silos/{silo_id}/telemetry`
- `POST /api/sites/{site_id}/weather`
- `GET /api/sites/{site_id}/weather-series`
- `POST /api/weather/refresh`
- `POST /api/sites`
- `POST /api/dependencies`
- `POST /api/sites/{site_id}/silos`
- `PATCH /api/sites/{site_id}/location`
- `PATCH /api/sites/{site_id}/metadata`
- `PATCH /api/sites/{site_id}/boundary`

## Notas para demo

Las localidades de acopios son reales como base territorial inicial. Las coordenadas vienen de la base georreferenciada AFA cargada en `db/red_afa_seed.csv`. Los silos se guardan con centro real, diametro y altura relevados en mapa satelital.

Para una base productiva, el padron de acopios deberia conciliarse contra SISA/ARCA/RUCA: CUIT, numero de planta, estado registral, provincia/localidad y domicilio. Con esa base, el relevamiento fino se completa sobre imagen satelital: centro real de planta, limite del acopio, centro de cada silo, diametro y altura.

La siguiente etapa natural es completar sesiones seguras, permisos en frontend por accion, reportes PDF ejecutivos, y reemplazar/combinar clima Open-Meteo con estacion propia o telemetria MQTT/LoRaWAN/4G.
