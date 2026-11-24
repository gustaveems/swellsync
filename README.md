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
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and a
  `Content-Security-Policy` that locks scripts to this origin (see Design
  notes).
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

## Assignment 2: the split system (Docker Compose)

The monolith above is split into two services along the seam in ADR-002. Each
service has its own container, its own database and its own migrations:

| Container | Role | Local URL |
|---|---|---|
| `services/spots` | Spot Directory (domain 1) | http://localhost:8001 |
| `services/sessions` | Session Tracker (domain 2) | http://localhost:8002 |
| `ui/` (stock `nginx:1.27-alpine`, not a service) | Static pages that call both services | http://localhost:8080 |
| `sqlserver` + one-off `db-init` | SQL Server 2022, one database and login per service | — |

Run the whole system with one command from a clean clone:

```bash
cp .env.example .env        # then set the three passwords in .env (never commit .env)
docker compose up --build
```

On Apple Silicon, enable Rosetta in Docker Desktop (the SQL Server image is amd64).

Run a single service on its own (it needs a reachable SQL Server and its
`DATABASE_URL`, and the spots service needs `SESSIONS_URL` to delete spots):

```bash
docker compose up -d sqlserver db-init
docker compose up --build spots
```

Each service exposes `GET /health` (its own database only: `200` ok, `503`
otherwise). Stopping one service leaves the other working: with spots stopped,
the session list still loads with a notice, and creating a session returns `503`.

**Live URL:** https://gamsoulasieu2024ui.z1.web.core.windows.net

The UI is a Storage static website. It calls the two services, which run as Azure
Container Apps in `rg-gamsoulas-ieu2024` (`gamsoulas-ieu2024-spots` and
`gamsoulas-ieu2024-sessions`) with serverless Azure SQL databases (ADR-008).

**Status:** the service split, Dockerfiles, compose stack and image CI are in
place. Each service has unit tests with a 70% coverage gate, a cross-seam
integration suite, and contract checks for the OpenAPI documents and
`system.yaml` (`.github/workflows/ci.yml`, see ADR-009). The services and the UI
are deployed. The automated deploy workflow (`cd.yml`) is not yet wired to Azure
credentials.

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

Measured output from the committed tree (2026-10-11):

```text
103 passed in 1.59s
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

### Service tests (Assignment 2)

Each service has its own unit tests, and `tests/integration` runs the two real
apps against each other over HTTP. The databases are in-memory fakes in
`tests/support`, so these tests need no SQL Server. The compose stack is what
proves the SQL itself.

Install the tools once:

```bash
pip install flask==3.1.3 pymssql==2.3.13 -r services/spots/requirements-dev.txt -r services/sessions/requirements-dev.txt
```

Run each suite with coverage of the service code only (`.coveragerc` leaves out the tests):

```bash
cd services/spots && pytest --cov=. --cov-config=../../.coveragerc
```

```bash
cd services/sessions && pytest --cov=. --cov-config=../../.coveragerc
```

```bash
pytest tests/integration
```

Measured on 2026-11-19 (`app.py`, `db.py` and `domain_logic.py` together):
spots **76%**, sessions **76%**. Both are above the 70% target.

### Merge gate (CI on `main`)

A merge to `main` needs five checks to pass. They are the `ci` workflow jobs
(`.github/workflows/ci.yml`), and the `Main` ruleset requires them by name:

- `lint`
- `unit tests spots`
- `unit tests sessions`
- `cross-seam integration`
- `contracts (OpenAPI and system.yaml)`

`tests/contracts/test_ci_workflow.py` fails when a job name in `ci.yml` no
longer matches this list, so renaming a job also means updating the ruleset.
The decision is in ADR-009.

## Azure setup (initial setup, Assignment 2)

The system runs in the student's own Azure for Students subscription, following
the course guide. Every command used to set it up is below. Passwords are never
written here or in the repository: the setup generates them into a local file
with owner-only permissions, and the pipeline reads them from GitHub secrets.

Region: `norwayeast` for everything except the SQL server. Norway East refused to
create a SQL server on this subscription, so the server is `germanywestcentral`
(the guide allows the server in a different region).

### 1. Sign in, select the subscription, register providers

```bash
az login --allow-no-subscriptions
az account set --subscription <subscription-id>
az policy assignment list --query "[?contains(displayName,'Allowed resource deployment regions')]"
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register -n "$p"
done
az group create -n rg-gamsoulas-ieu2024 -l norwayeast
```

### 2. UI: storage account with a static website

```bash
az storage account create -g rg-gamsoulas-ieu2024 -n gamsoulasieu2024ui -l norwayeast \
  --sku Standard_LRS --kind StorageV2 --allow-blob-public-access true
az storage blob service-properties update --account-name gamsoulasieu2024ui \
  --static-website --index-document index.html --404-document 404.html --auth-mode login
```

### 3. Pipeline identity (OIDC, no service principal)

IE accounts can't create service principals, so the pipeline uses a user-assigned
managed identity with federated credentials.

```bash
az identity create -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-github -l norwayeast
az role assignment create --assignee-object-id <principalId> --assignee-principal-type ServicePrincipal \
  --role Contributor --scope /subscriptions/<subscription-id>/resourceGroups/rg-gamsoulas-ieu2024
az identity federated-credential create -g rg-gamsoulas-ieu2024 --identity-name gamsoulas-ieu2024-github \
  -n github-main-name --issuer https://token.actions.githubusercontent.com \
  --audiences api://AzureADTokenExchange --subject "repo:gustaveems/swellsync:ref:refs/heads/main"
az identity federated-credential create -g rg-gamsoulas-ieu2024 --identity-name gamsoulas-ieu2024-github \
  -n github-main-ids --issuer https://token.actions.githubusercontent.com \
  --audiences api://AzureADTokenExchange \
  --subject "repo:gustaveems@<owner-id>/swellsync@<repo-id>:ref:refs/heads/main"
```

GitHub sends the subject with names or with numeric IDs depending on the repository
settings, so both forms are registered. The owner and repository IDs come from
`gh api repos/gustaveems/swellsync`.

### 4. Logs and the Container Apps environment

```bash
az monitor log-analytics workspace create -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-logs -l norwayeast
az containerapp env create -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-env -l norwayeast \
  --logs-workspace-id <workspace-customer-id> --logs-workspace-key <workspace-shared-key>
```

### 5. SQL server and one serverless database per service

The free offer is used: it fixes the auto-pause at 60 minutes and the size at 32 GB,
so `--auto-pause-delay` and `--max-size` are not passed.

```bash
az sql server create -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-sql2 -l germanywestcentral \
  -u swellsyncadmin -p "$SQL_ADMIN_PASSWORD"
az sql server firewall-rule create -g rg-gamsoulas-ieu2024 -s gamsoulas-ieu2024-sql2 \
  -n AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
for db in spots sessions; do
  az sql db create -g rg-gamsoulas-ieu2024 -s gamsoulas-ieu2024-sql2 -n "gamsoulas-ieu2024-$db-db" \
    --edition GeneralPurpose --family Gen5 --compute-model Serverless --capacity 1 --min-capacity 0.5 \
    --use-free-limit true --free-limit-exhaustion-behavior AutoPause --backup-storage-redundancy Local
done
```

Each service then gets its own contained user, which can reach only its own
database and run migrations. Open the server firewall to your own IP for the
setup, run the script, and close the firewall again. Running it again is safe,
and it is how a password is rotated (then update that app's `db-url` secret):

```bash
export SQL_ADMIN_PASSWORD=... SPOTS_DB_PASSWORD=... SESSIONS_DB_PASSWORD=...
python scripts/azure/create_sql_users.py \
  --server gamsoulas-ieu2024-sql2.database.windows.net --admin swellsyncadmin
```

The script runs this in each database (not in `master`). The first setup ran it by
hand:

```sql
CREATE USER [spots_app] WITH PASSWORD = '<generated, not written here>';
ALTER ROLE db_ddladmin ADD MEMBER [spots_app];
ALTER ROLE db_datareader ADD MEMBER [spots_app];
ALTER ROLE db_datawriter ADD MEMBER [spots_app];
```

The same for `sessions_app` in `gamsoulas-ieu2024-sessions-db`.

### 6. Container Apps: placeholder first, then the real image

Both apps start on the course placeholder image, then the deploy replaces it.

```bash
az containerapp create -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-spots --environment gamsoulas-ieu2024-env \
  --image mcr.microsoft.com/k8se/quickstart:latest --target-port 80 --ingress external \
  --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
# the sessions app is created the same way with its own name
```

The connection string is a secret, read through `secretref`. The other service's
URL and the UI's origin are plain variables:

```bash
az containerapp secret set -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-spots \
  --secrets "db-url=mssql://spots_app:<url-encoded-password>@gamsoulas-ieu2024-sql2.database.windows.net:1433/gamsoulas-ieu2024-spots-db"
az containerapp update -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-spots \
  --image ghcr.io/gustaveems/swellsync-spots:<commit-sha> \
  --set-env-vars "PORT=8000" "DATABASE_URL=secretref:db-url" \
    "SESSIONS_URL=https://gamsoulas-ieu2024-sessions.<environment-domain>" \
    "ALLOWED_ORIGIN=https://gamsoulasieu2024ui.z1.web.core.windows.net" "APP_VERSION=<commit-sha>"
az containerapp ingress update -g rg-gamsoulas-ieu2024 -n gamsoulas-ieu2024-spots --target-port 8000 --type external
```

CORS is handled in the services, not in Container Apps (the ingress CORS setting
rejects the browser's JSON preflight). Each service reads `ALLOWED_ORIGIN` and
allows the `Content-Type` header.

### 7. UI upload

The UI is uploaded with `config.js` pointing at the two Container Apps. The deploy
job does this on every push to `main` (see `.github/workflows/cd.yml`).

### 8. GitHub secrets and variables

Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
`SPOTS_DB_PASSWORD`, `SESSIONS_DB_PASSWORD`. Variables: `PREFIX`,
`RESOURCE_GROUP`, `UI_STORAGE`. Set them with `gh secret set` and `gh variable set`.

### Problems met during setup

- **Failed SQL server name.** A failed create in Norway East reserved
  `gamsoulas-ieu2024-sql` there, so the server was recreated under `-sql2`.
- **Empty password in the connection string.** The setup password was read into a
  shell variable that wasn't exported, so the first connection strings had an
  empty password and the services failed with error 18456 at boot. The fix was to
  export the value (`set -a`) before building the strings and restart the
  revisions.
- **Subscription on the wrong account.** The first sign-in showed only the IE
  subscription. The Azure for Students subscription was on another account, and
  the sign-in had to be repeated with `--allow-no-subscriptions`.

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
├── ADR.md                 # 5 decisions, plus dated amendments (ADR-001a/b/c, 003a)
├── AI_USAGE.md            # AI assistance log (syllabus requirement)
├── REPORT.md              # SDLC report: model, SMART goals, architecture + schema
├── README.md              # this file
├── templates/             # Jinja2 templates (server-rendered UI)
│   ├── base.html, _macros.html, index.html, 404.html
│   ├── spots.html, spot_detail.html, spot_edit.html
│   └── sessions.html, session_edit.html
└── static/                # served by Flask itself — no bundler
    ├── css/style.css      # single hand-written stylesheet
    ├── js/app.js          # the only JavaScript: confirms + filter auto-submit
    └── img/favicon.svg    # a real file, so img-src needs no data: exception
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
  is the course's shared template with its four `TODO` slots filled. Assignment 2
  adds the split services and `docker-compose.yml` (see above). Out of scope:
  Terraform/Bicep, Redis/RabbitMQ/Celery.
* **Domain seam.** Domain 1 (spots) code never queries `sessions`; Domain 2
  references spots only by `spot_id`; all cross-domain math lives in
  `domain_logic.py`. See `ADR-002`.
* **Simplification, stated plainly:** there is no CSRF token on forms and the
  Flask dev server is used as the runtime — both acceptable for a local,
  single-user course assignment, and both flagged as future hardening.
* **CSP is enforced, and says so.** `script-src 'self'` with no `'unsafe-inline'`
  — the five inline handlers that used to make a real policy impossible now
  live in `static/js/app.js`, keyed off `data-confirm` / `data-autosubmit`. The
  one exception is `style-src 'unsafe-inline'`, because the rating bars set
  their width from data; inline styles cannot run scripts, so the trade is
  asymmetric and documented rather than hidden. Filter controls also keep a
  `<noscript>` Apply button, since auto-submit is an enhancement. See `ADR-001c`.
* **User input never becomes SQL.** Search terms are bound as parameters with
  `%`/`_` escaped; sorting selects a key from a fixed whitelist. See
  `ADR-003a`.

## §7 container contract — verification evidence

Output of the course-provided `run.sh` contract checker against this
repository, re-run on 2026-10-11 after the Content-Security-Policy refactor
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
