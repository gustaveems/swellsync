# 🌊 SwellSync — Surf & Sail Session Logger

A single-process Python web application for logging surf and sailing sessions
against a directory of favorite spots. SQLite-backed, server-rendered, and
deliberately free of external services.

## Features

* **Spot Directory (Domain 1)** — full CRUD catalog of spots with ideal wind
  direction and ideal swell height.
* **Session Tracker (Domain 2)** — full CRUD log of water sessions: date,
  duration, 1–5 rating, gear, notes, always attached to a spot.
  Future-dated entries are rejected — the log records what already happened.
* **Cross-domain stats** — per-spot and global totals/averages computed by
  pure functions in `domain_logic.py`.
* **Epic-sessions filter** — quality view of sessions rated ≥ 4, filterable
  on the sessions page ("Epic only").
* **Rating distribution** — 1–5 star-count bars on every spot page.
* **Health probe** — `GET /healthz` returns live status, DB check, and
  entity counts.
* **Spot search** — `GET /spots?q=` matches a case-insensitive substring of a
  spot's name or location; `%` and `_` are escaped so they match literally.
* **CSV export** — `GET /sessions/export.csv` downloads the session log as a
  CSV attachment, honouring the same spot, epic and sort parameters.
* **Sortable log** — `?sort=date|oldest|duration|rating` on the session list;
  keys resolve through a whitelist, so the value never reaches the SQL.
* **Security headers** — every response carries `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy` (no CSP —
  see Design notes).
* **First-boot seed** — `seed.json` loads four reference spots and six demo
  sessions onto an empty database and only then (§7.11), so restarts never
  duplicate it and the app is useful the moment it starts.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.9+ locally; `python:3.12-slim` in the container |
| Framework | Flask 3 (microframework, Jinja2 templates) |
| Storage | SQLite (single file, auto-created) |
| Tests | pytest + pytest-cov |

Direct dependencies: **3** (`flask`, `pytest`, `pytest-cov`) — see
`requirements.txt`.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:8000**. The app binds to `0.0.0.0`, so it is
reachable from other machines on your LAN at `http://<your-ip>:$PORT`.

### Run with Docker

The `Dockerfile` is the course-provided template with its four `TODO` slots
filled — `python:3.12-slim`, a pinned `pip install`, an explicit source
`COPY`, and `CMD ["python", "app.py"]`. Build and run it with a named volume
for the SQLite file:

```bash
docker build -t swellsync .
docker run --rm -p 8000:8000 -v swellsync-data:/data swellsync
```

The container sets `DATA_DIR=/data`, so the database lives on the volume and
survives `docker rm`. Move the port with `-e PORT=9000 -p 9000:9000`. Verify
the full contract with the provided checker (its row-count step needs a host
`python3` ≥ 3.12):

```bash
run.sh /path/to/swellsync
```

## Troubleshooting

**Port 8000 is taken / you see JSON instead of the dashboard.** Another
local service may be listening on `127.0.0.1:8000` — on macOS a
loopback-specific listener answers every `localhost` request even when
SwellSync binds the wildcard `0.0.0.0:8000`. Find the holder and either
stop it or move SwellSync to a free port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN   # who holds the port
PORT=8001 python app.py            # run on another port instead
```

**Starting over with an empty log.** Stop the app, delete
`$DATA_DIR/swellsync.db` (default `./data/swellsync.db`), and restart —
the schema is recreated automatically on boot.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port the server binds on `0.0.0.0`. |
| `DATA_DIR` | `./data` (container: `/data`) | Directory holding `swellsync.db` (file and folder are created on startup; never any manual migration). |
| `SECRET_KEY` | `swellsync-dev-secret` | Signs flash messages. Set a real random value if you expose the app beyond localhost. |
| `FLASK_DEBUG` | *(off)* | Set to `1` to enable the Werkzeug auto-reloader during development. |

## Testing

The exact coverage command required by the assignment:

```bash
pytest --cov=domain_logic test_app.py
```

Measured output from the committed tree (2026-10-10):

```text
95 passed in 2.07s
---------- coverage: platform darwin, python 3.9.6 ----------
Name              Stmts   Miss  Cover
-------------------------------------
domain_logic.py     130      0   100%
-------------------------------------
```

`domain_logic.py` is pure Python (no Flask, no SQL), and the suite exercises
all of its branches, so measured business-logic coverage is **100%** — well
above the required 70%. A plain run without coverage:

```bash
pytest -v
```

The suite also drives the SQLite CRUD paths end-to-end through the Flask test
client against a temporary `DATA_DIR`, and asserts engine-level foreign-key
and CHECK-constraint enforcement.

## Project structure

```
swellsync/
├── app.py                 # Flask app: routes, DB bootstrap, env config, seed loader
├── domain_logic.py        # Pure business logic (stats, filter, validation)
├── test_app.py            # pytest suite (logic + CRUD + seeding)
├── requirements.txt       # 3 direct dependencies (pinned)
├── seed.json              # reference spots + demo sessions, loaded when empty
├── Dockerfile             # course-provided template, 4 TODO slots filled
├── .dockerignore          # trims the build context
├── ADR.md                 # 5 architecture decision records
├── AI_USAGE.md            # AI assistance log (syllabus requirement)
├── README.md              # this file
├── templates/             # Jinja2 templates (server-rendered UI)
│   ├── base.html, _macros.html, index.html, 404.html
│   ├── spots.html, spot_detail.html, spot_edit.html
│   └── sessions.html, session_edit.html
└── static/css/style.css   # single hand-written stylesheet (no build step)
```

## Database schema (auto-created at startup)

* `spots` — `id`, `name` (NOT NULL), `location` (NOT NULL),
  `ideal_wind_dir`, `ideal_swell_ft`, `created_at`.
* `sessions` — `id`, `spot_id` (FK → `spots.id`, enforced via
  `PRAGMA foreign_keys = ON`), `date` (ISO `YYYY-MM-DD`, defaults to today),
  `duration_mins` (NOT NULL, `CHECK > 0`), `wave_or_wind_rating`
  (`CHECK 1–5`), `gear_used`, `notes`, `created_at`.

Deleting a spot that still has sessions is blocked by the foreign key — the
app surfaces a friendly error instead of silently destroying history.

## Design notes

* **Single process, single command.** `python app.py` is the entire runtime;
  there is no worker, no broker, no separate frontend build.
* **Container = the provided template, not self-authored.** The `Dockerfile`
  is the course's shared template with its four `TODO` slots filled; writing
  real Docker orchestration is Assignment 2. Still absent (out of scope):
  `docker-compose.yml`, GitHub Actions, Terraform/Bicep, Redis/RabbitMQ/Celery.
* **Domain seam.** Domain 1 (spots) code never queries `sessions`; Domain 2
  references spots only by `spot_id`; all cross-domain math lives in
  `domain_logic.py`. See `ADR-002`.
* **Simplification, stated plainly:** there is no CSRF token on forms and the
  Flask dev server is used as the runtime — both acceptable for a local,
  single-user course assignment, and both flagged as future hardening.

## §7 container contract — verification evidence

Output of the course-provided `run.sh` contract checker against this
repository, re-run on 2026-10-10 after the search and sort features landed
(identical to the first green run on 2026-10-08). The `ALL CHECKS PASSED`
line includes §7.11 idempotent seeding — `row counts unchanged across
restart: sessions=6 spots=4` — which is only reported on a host with
`python3` ≥ 3.12.

```text
=== SDD Assignment 1 contract check ===
Repository: /Users/alain/swellsync

==> Repository shape
  PASS  one Dockerfile, one manifest (requirements.txt)

==> Build from a clean context, no build args
  PASS  image built
  PASS  image size 172 MB

==> Start on PORT=8000 and reach it from the host
  PASS  HTTP 200 from http://localhost:8000/

==> SQLite file under DATA_DIR
  PASS  found in /data: swellsync.db

==> Data persists, and a second boot does not re-seed
  PASS  volume at /data persists
  PASS  row counts unchanged across restart: sessions=6 spots=4

==> PORT override is honoured (not hardcoded)
  PASS  HTTP 200 from http://localhost:9123/

=== ALL CHECKS PASSED ===
```

## AI disclosure (mandatory syllabus statement)

> This project was produced with AI assistance. The application code, test
> suite, container, and documentation were drafted with Qwen Code (an AI
> coding assistant) across 2026-10-05 → 2026-10-08, working from the
> Assignment 1 specification. The output was reviewed, tested, and is the
> submitting student's responsibility. A per-interaction log — prompts,
> dispositions, and what changed — is maintained in `AI_USAGE.md`.
