# 🌊 SwellSync — Surf & Sail Session Logger

A single-process Python web application for logging surf and sailing sessions
against a directory of favorite spots. SQLite-backed, server-rendered, and
deliberately free of external services.

## Features

* **Spot Directory (Domain 1)** — full CRUD catalog of spots with ideal wind
  direction and ideal swell height.
* **Session Tracker (Domain 2)** — full CRUD log of water sessions: date,
  duration, 1–5 rating, gear, notes, always attached to a spot.
* **Cross-domain stats** — per-spot and global totals/averages computed by
  pure functions in `domain_logic.py`.
* **Epic-sessions filter** — quality view of sessions rated ≥ 4.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.9+ |
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
| `DATA_DIR` | `./data` | Directory holding `swellsync.db` (file and folder are created on startup; never any manual migration). |
| `SECRET_KEY` | `swellsync-dev-secret` | Signs flash messages. Set a real random value if you expose the app beyond localhost. |
| `FLASK_DEBUG` | *(off)* | Set to `1` to enable the Werkzeug auto-reloader during development. |

## Testing

The exact coverage command required by the assignment:

```bash
pytest --cov=domain_logic test_app.py
```

Measured output from the committed tree (2026-10-06):

```text
60 passed in 1.00s
---------- coverage: platform darwin, python 3.9.6 ----------
Name              Stmts   Miss  Cover
-------------------------------------
domain_logic.py     121      0   100%
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
├── app.py                 # Flask app: routes, DB bootstrap, env config
├── domain_logic.py        # Pure business logic (stats, filter, validation)
├── test_app.py            # pytest suite (logic + CRUD)
├── requirements.txt       # 3 direct dependencies
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
* **Deliberately absent** (per assignment scope): `Dockerfile`,
  `docker-compose.yml`, GitHub Actions, Terraform/Bicep, Redis/RabbitMQ/Celery.
* **Domain seam.** Domain 1 (spots) code never queries `sessions`; Domain 2
  references spots only by `spot_id`; all cross-domain math lives in
  `domain_logic.py`. See `ADR-002`.
* **Simplification, stated plainly:** there is no CSRF token on forms and the
  Flask dev server is used as the runtime — both acceptable for a local,
  single-user course assignment, and both flagged as future hardening.

## AI disclosure (mandatory syllabus statement)

> This project was produced with AI assistance. The application code, test
> suite, and documentation were drafted with Qwen Code (an AI coding
> assistant) on 2026-10-05, working from the Assignment 1 specification.
> The output was reviewed, tested, and is the submitting student's
> responsibility. A per-interaction log — prompts, dispositions, and what
> changed — is maintained in `AI_USAGE.md`.
