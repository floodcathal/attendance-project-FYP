<h1 align="center">Smart Campus Attendance &amp; Room Occupancy Platform</h1>

<p align="center">
  QR-based attendance tracking with enterprise SSO, role-based access control<br>
  and real-time occupancy analytics — built as a containerised cloud platform.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
  <img src="https://img.shields.io/badge/Node--RED-ingest%20%26%20API-8F0000?logo=nodered&logoColor=white" alt="Node-RED">
  <img src="https://img.shields.io/badge/InfluxDB-2.7-22ADF6?logo=influxdb&logoColor=white" alt="InfluxDB">
  <img src="https://img.shields.io/badge/Grafana-dashboards-F46800?logo=grafana&logoColor=white" alt="Grafana">
  <img src="https://img.shields.io/badge/Prometheus-metrics-E6522C?logo=prometheus&logoColor=white" alt="Prometheus">
  <img src="https://img.shields.io/badge/Microsoft-Entra%20ID%20SSO-0078D4?logo=microsoftazure&logoColor=white" alt="Entra ID">
  <img src="https://img.shields.io/badge/Cloudflare-Zero%20Trust-F38020?logo=cloudflare&logoColor=white" alt="Cloudflare">
</p>

---

**Final year project — BSc (Hons) Cloud Computing, TU Dublin.**
Cathal Flood · C22312211 · April 2026

---

## The problem

TU Dublin still runs attendance on paper. Room occupancy is measured by asking cleaning
staff to walk a floor at the start and end of each semester, count heads once an hour, and
type the numbers into a spreadsheet against each room's capacity. In some buildings the
only signal that a room was used at all is whether its lights were switched on.

That approach is slow, error-prone and impossible to query. It also can't catch the most
common form of attendance fraud — a student signing in a friend who isn't there. And
because the data never becomes analysable, it can't feed the things institutions actually
want it for: fire-safety headcounts, over-occupancy policy, timetable optimisation, and
early identification of students who have stopped showing up.

This project replaces that with a system where a student scans the QR code on a room door,
is authenticated against the institution's identity provider, and the event lands in a
time-series database that drives live dashboards within seconds.

Requirements were shaped by a conversation with a TU Dublin building manager about how
occupancy management actually works day to day, rather than assumed.

## What it does

- **Scan to check in / out.** Mobile-first web scanner reads a room QR code, derives
  building and floor, and submits a check-in or check-out event.
- **Identity comes from the IdP, not the form.** The student ID is extracted from the
  authenticated SSO session and injected server-side as a read-only field — a student
  can't check in on behalf of someone else.
- **Live occupancy.** Grafana shows current headcount per room, utilisation against
  capacity, and historical trends by building, floor and hour.
- **Role-appropriate data.** Four permission tiers, enforced at query level, so a student
  sees only their own attendance while a department head sees their whole building.
- **Operational visibility.** Prometheus scrapes the ingest API for throughput, validation
  failures and fraud flags.

## Architecture

```
                          Student's phone
                                │  scans room QR
                                ▼
                    ┌───────────────────────┐
                    │   Cloudflare Access   │  Zero Trust gateway
                    │   + Entra ID (SSO)    │  OAuth 2.0 + MFA, domain-restricted
                    └───────────┬───────────┘
                                │  identity headers injected
                                ▼
                    ┌───────────────────────┐
                    │  Cloudflare Worker    │  extracts student ID from the
                    │  (edge)               │  verified email claim and injects
                    └───────────┬───────────┘  it as a read-only field
                                ▼
                    ┌───────────────────────┐
                    │  nginx  (scanner)     │  serves the app and reverse-proxies
                    │  same-origin proxy    │  /attendance/submit → Node-RED
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │      Node-RED         │  4-layer validation pipeline,
                    │   ingest + REST API   │  event shaping, /metrics endpoint
                    └───┬───────────────┬───┘
                        │               │
          line protocol │               │ scrape /metrics
                        ▼               ▼
              ┌──────────────┐   ┌──────────────┐
              │  InfluxDB    │   │  Prometheus  │  service health,
              │  2.7 (TSDB)  │   │              │  counters, throughput
              │  + Flux tasks│   └───────┬──────┘
              └───────┬──────┘           │
                      └────────┬─────────┘
                               ▼
                    ┌───────────────────────┐
                    │       Grafana         │  Entra ID SSO, 4 role tiers,
                    │   RBAC dashboards     │  query-level data filtering
                    └───────────────────────┘
```

Everything runs as containers on a single `occupancy-net` bridge network — see
[`docker-compose.yml`](docker-compose.yml). Cloudflare Tunnel provides HTTPS ingress with
**no inbound ports open on the host**.

## Engineering decisions

The parts of this project worth talking through.

### Identity is server-side, or it's theatre

The first prototype trusted whatever student ID was typed into the form, which solves
nothing — the fraud case that matters is a present student checking in an absent friend.

The fix was to stop asking. A Cloudflare Worker runs at the edge, reads the authenticated
email from the SSO headers Cloudflare injects, regex-matches the student ID out of it
(`C12345678@…`), and rewrites the HTML response to pre-fill the field as read-only before
it reaches the browser. Tampering via devtools is reverted before submission, and the value
is re-checked server-side. The ID originates from a verified session, so the form is no
longer a trust boundary.

### Four-layer validation on ingest

Every submission passes through, in order:

| Layer | Does |
|---|---|
| 1 — Input validation | Field whitelist, type enforcement, length caps |
| 2 — Schema validation | AJV against JSON Schema; student ID regex `C[0-9]{8}` |
| 3 — Sanitisation | HTML entity encoding (XSS), parameterised queries (injection) |
| 4 — Rate limiting | Per-IP request counting with automatic cleanup |

Results are in [`tests/`](tests) — oversized payloads, prototype pollution, type coercion,
unexpected fields and field-length abuse were each tested explicitly.

### RBAC enforced at the query, not the UI

Hiding a dashboard is not access control. Four institutional roles map onto Grafana roles
via OAuth email-pattern matching, and **every panel query carries its own filter**:

| Role | Grafana role | Data visible |
|---|---|---|
| Student | Viewer | Own records only, via `${__user.login}` in the query |
| Lecturer | Editor | Filtered to their own rooms |
| Department Head | Editor | Filtered to their building |
| Admin | Admin | Everything |

Folder permissions handle navigation; the `${__user.login}` filter is what stops a student
pasting another student's dashboard URL and reading their data.

### Killing CORS with topology instead of headers

Adding SSO broke the scanner: separate subdomains meant cross-origin requests, and the
custom identity headers Cloudflare injects don't survive a standard preflight. Four hours
went into header-level fixes — Cloudflare's CORS config (paid plan only), Node-RED response
headers (failed against SSO headers), OPTIONS bypass (not on the free tier).

The working answer was architectural: have nginx serve the scanner *and* reverse-proxy
`/attendance/submit` to Node-RED over the internal Docker network, then switch the client to
relative URLs. Every request is now same-origin, so CORS never applies. No plan upgrade,
fewer moving parts. See [`scanner/nginx.conf`](scanner/nginx.conf).

### Three-tier retention: 95% less storage

Raw events are useful for weeks; trends are useful for years. Scheduled Flux tasks
([`influxdb/tasks/`](influxdb/tasks)) roll data down automatically:

| Tier | Measurement | Granularity | Retention | 5-year size |
|---|---|---|---|---|
| Raw | `attendance_events` | Per event | 90 days | 450 MB |
| Hourly | `attendance_hourly` | Count per room/hour | 1 year | 37 MB |
| Daily | `attendance_daily` | Count per room/day | Indefinite | 9 MB |

**496 MB versus 9.1 GB** for keeping raw events alone — a 95% reduction, with faster
dashboards as a side effect since trend panels hit pre-aggregated data.

### A monitoring bug worth the detour

The total check-in counter kept going *down*. Cause: Pushgateway is built for batch jobs and
**replaces** the pushed value rather than incrementing it, so counter semantics were wrong by
design for a long-running service.

Replaced it with a custom `/metrics` endpoint in Node-RED emitting Prometheus exposition
format, scraped every 10s — monotonic counters for check-ins, check-outs, validation errors
and fraud flags. One container fewer, and correct data.

### Locked out of Entra ID

Security Defaults enforced MFA on the tenant's only admin account, but completing MFA
enrolment required portal access that account no longer had — a genuine deadlock. Recovery
was via Azure CLI device-code login, creating a second Global Administrator through the
Microsoft Graph API, then disabling Security Defaults from that account.

Lesson taken: create the break-glass admin account *immediately* after standing up a tenant,
not once you need it.

## Results

Measured across the three iterations:

| | Result | Target |
|---|---|---|
| API response @ 500 concurrent (Apache Bench) | **320 ms**, zero errors, zero timeouts | < 500 ms |
| API response after optimisation | **120 ms** | — |
| Sustained throughput | **50 req/s** | — |
| Attendance submission | **< 200 ms** | — |
| Authentication round trip | **< 500 ms** | < 500 ms |
| Dashboard reflects a scan | **3–5 s** | < 5 s |
| QR scan success across lighting conditions | **97%** | > 95% |
| Invalid input rejected | **100%** | 100% |
| XSS / injection attempts blocked | **100%** | 100% |
| Storage vs raw-only | **−95%** | — |
| Running cost | **€0** (€10 once for the domain) | — |

Tested on iOS (Safari, Chrome) and Android (Chrome, Firefox); iOS 12+ / Android 8+.

## Design trade-offs

| Chose | Over | Because |
|---|---|---|
| Node-RED stack | ThingsBoard, AWS IoT Core | Custom validation logic exceeded what ThingsBoard's rule engine could express |
| Docker Compose | Kubernetes | Single server handles the validated 500-user load; K8s complexity unjustified at this scale |
| bcrypt cost factor 10 | Lower cost factor | 120 ms hashing is imperceptible for human-initiated check-ins and meets OWASP guidance |
| Custom `/metrics` | Pushgateway | Correct counter semantics for a long-running service |
| Same-origin nginx proxy | CORS headers | Removes the problem class instead of configuring around it |

The stack was narrowed from **9 containers to 6** across iterations, dropping ThingsBoard,
PostgreSQL and Pushgateway once each had been evaluated and found unnecessary.

## Running it

Requires Docker and Docker Compose.

```bash
git clone https://github.com/<your-username>/attendance-project.git
cd attendance-project
cp .env.example .env    # fill in your own values
docker compose up -d
```

| Service | URL |
|---|---|
| Scanner | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Node-RED | http://localhost:1880 |
| InfluxDB | http://localhost:8086 |
| Prometheus | http://localhost:9090 |

Seed the dashboards with six weeks of synthetic data — 500 students across 48 rooms in 4
buildings, weighted to a realistic timetable curve with reduced weekend traffic:

```bash
pip install requests
python scripts/generate_data.py
```

SSO needs your own Entra ID app registration: set the `AZURE_*` variables in `.env` and
register `<your-grafana-url>/login/generic_oauth` as a redirect URI. Without it the stack
runs on local Grafana auth.

## Repository layout

```
docker-compose.yml          full stack definition
scanner/                    QR scanner + generator, nginx same-origin proxy
  ├─ index.html             mobile check-in interface
  ├─ qr-scanner-sso.html    SSO-authenticated scanner
  ├─ qr-generator.html      printable room QR codes
  └─ nginx.conf             static serving + /attendance/submit reverse proxy
nodered-data/final.json     Node-RED ingest flows
influxdb/tasks/             Flux downsampling + utilisation tasks
grafana/                    Grafana config, Entra ID SSO, provisioning
prometheus.yml              scrape configuration
scripts/generate_data.py    synthetic data generator
tests/                      input-validation test results
screenshots/                running system
thingsboard/                evaluated as an alternative platform, not adopted
```

## Future work

**Short term** — native iOS/Android app with offline check-in and push notifications;
automated email/Slack alerting for capacity warnings and fraud flags.
**Medium term** — predictive attendance modelling and per-building heat maps.
**Long term** — Kubernetes for multi-campus scale-out and high availability; student
information system integration.

## Notes

Credentials are supplied entirely through environment variables — see
[`.env.example`](.env.example). The bulk Entra ID import of synthetic test accounts and the
Prometheus TSDB volume are deliberately excluded from version control.
