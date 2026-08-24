# Smart Campus Attendance & Room Occupancy Platform

Final year project — TU Dublin.

A containerised, end-to-end IoT and observability platform that replaces manual roll-call
with QR-based check-in, and turns the resulting event stream into live room-occupancy and
space-utilisation dashboards for lecturers and facilities staff.

Students scan a QR code on the door of a room. The scan is authenticated against the
university's Microsoft Entra ID (Azure AD) tenant, written to a time-series database as a
`check-in` / `check-out` event, and surfaced in Grafana within seconds — as live occupancy
per room, historical utilisation per building, and per-student attendance history.

---

## Architecture

```
   Student phone
        │  scans room QR
        ▼
┌──────────────────┐     HTTPS      ┌──────────────────┐
│  Scanner web app │ ─────────────► │ Cloudflare Tunnel│  no inbound ports opened
│  (nginx + JS)    │                │  + Zero Trust    │
└──────────────────┘                └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │     Node-RED     │  validation, auth check,
                                    │  ingest + API    │  event shaping, /metrics
                                    └───┬──────────┬───┘
                                        │          │
                          line protocol │          │ scrape
                                        ▼          ▼
                              ┌───────────┐   ┌────────────┐
                              │ InfluxDB  │   │ Prometheus │
                              │ 2.7 (TSDB)│   │ (svc health│
                              │ + tasks   │   │  + counters)│
                              └─────┬─────┘   └──────┬─────┘
                                    └────────┬───────┘
                                             ▼
                                    ┌──────────────────┐
                                    │     Grafana      │  Entra ID SSO,
                                    │   dashboards     │  role-mapped access
                                    └──────────────────┘
```

Every component runs as a Docker container on a single `occupancy-net` bridge network,
defined in [`docker-compose.yml`](docker-compose.yml).

## What each part does

| Component | Role |
|---|---|
| **Scanner web app** (`scanner/`) | Mobile-first QR scanner built on `html5-qrcode`. Parses building/floor/room from the scanned payload, collects student ID and check-in/check-out intent, posts to the ingest API. `qr-generator.html` produces the printable room codes. |
| **nginx** (`scanner/nginx.conf`) | Serves the static scanner and reverse-proxies `/attendance/submit` to Node-RED on the same origin, which sidesteps browser CORS entirely. |
| **Node-RED** (`nodered-data/`) | Ingest pipeline and HTTP API. Validates and sanitises the payload, enforces that the authenticated identity matches the submitted student ID, writes to InfluxDB, and exposes a `/metrics` endpoint for Prometheus. |
| **InfluxDB 2.7** (`influxdb/`) | Time-series store for `attendance_events`. Scheduled Flux tasks (`influxdb/tasks/`) downsample raw events into hourly and daily buckets and compute room-utilisation percentages against capacity. |
| **Prometheus** (`prometheus.yml`) | Scrapes Node-RED for service health and request counters — operational telemetry, as distinct from the attendance data itself. |
| **Grafana** (`grafana/`) | Dashboards, fronted by Microsoft Entra ID SSO. Grafana roles are derived from the email claim, so lecturers land as Editors and students as Viewers. |
| **Cloudflare Tunnel** | Publishes the scanner and Grafana over HTTPS without exposing any inbound port on the host. |

## Security design

Authentication and input validation were treated as first-class parts of the project
rather than an afterthought:

- **SSO, not self-declared identity.** Early iterations trusted the student ID typed into
  the form. The final design authenticates through Entra ID and cross-checks the
  authenticated principal against the submitted ID, so a student cannot check in a friend
  who is not present — the core proxy-attendance problem.
- **Role mapping from claims.** Grafana derives Admin / Editor / Viewer from the email
  claim via `role_attribute_path`, so authorisation follows the identity provider.
- **Layered input validation** at the ingest API. Results in [`tests/`](tests):
  oversized payloads, prototype pollution, type coercion, missing fields, unexpected
  fields and field-length abuse were tested explicitly.
- **No inbound ports.** All external access is via Cloudflare Tunnel.
- **No secrets in source.** All credentials are injected from environment variables —
  see [`.env.example`](.env.example).

## Running it locally

Requires Docker and Docker Compose.

```bash
git clone https://github.com/<your-username>/attendance-project.git
cd attendance-project
cp .env.example .env   # then fill in your own values
docker compose up -d
```

| Service | URL |
|---|---|
| Scanner | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Node-RED | http://localhost:1880 |
| InfluxDB | http://localhost:8086 |
| Prometheus | http://localhost:9090 |

To populate the dashboards with six weeks of realistic synthetic data — 500 students
across 48 rooms in 4 buildings, weighted to a plausible timetable curve with reduced
weekend traffic:

```bash
pip install requests
python scripts/generate_data.py
```

Entra ID SSO requires your own app registration; set `AZURE_*` in `.env` and add
`<your-grafana-url>/login/generic_oauth` as a redirect URI.

## Repository layout

```
docker-compose.yml       full stack definition
scanner/                 QR scanner + generator web app, nginx config
nodered-data/            Node-RED ingest flows (final.json)
influxdb/                InfluxDB compose + Flux downsampling tasks
grafana/                 Grafana config, SSO setup, provisioning
prometheus.yml           scrape configuration
scripts/generate_data.py synthetic data generator
tests/                   input-validation test results
screenshots/             running system
thingsboard/             evaluated as an alternative dashboard layer
```

## Notes

`students.csv` (a bulk Entra ID import of synthetic test accounts) and the Prometheus
TSDB volume are intentionally excluded from version control.
