# SwellSync — Architecture Decision Records

Five decisions that shaped this application. Each entry records the context
that forced a choice, the decision itself, and what it costs us.

---

## ADR-001 — Backend: Python 3 with the Flask microframework

**Status:** Accepted — 2026-10-05

**Context:** The assignment requires a single-process web application, started
with one command, persisting to SQLite, rendering server-side HTML, and keeping
third-party dependencies under six packages. Candidates: Flask (WSGI
microframework), FastAPI (ASGI, needs uvicorn), Django (batteries-included,
far heavier than needed).

**Decision:** Python 3 + Flask. Flask bundles Jinja2 templating and a
development WSGI server, so `python app.py` alone boots the whole product.
Direct dependencies land at three: `flask`, `pytest`, `pytest-cov`. The app is
built through an application-factory function (`create_app`) so the test suite
can instantiate isolated instances with throwaway data directories.

**Consequences:**
* (+) One file to read, one command to run, one dependency manifest — matches
  every hard constraint in the assignment.
* (+) Jinja2 auto-escaping ships for free, keeping templates safe by default.
* (−) The built-in Werkzeug server is a development server; a production
  deployment would front it with a WSGI server — an operational concern, not a
  code change (and out of scope for Assignment 1).
* (−) Synchronous request handling is fine for a single-user logger but would
  need revisiting under real concurrency.

---

## ADR-001a — Amendment (2026-10-08): containerized via the provided template

**Status:** Accepted — 2026-10-08

A later reading of the assignment brief (github.com/ami232/sdd-assignment-1)
clarified §7: the app must ship runnable in a container, using a *provided*
Dockerfile template — not a self-authored one, which §1 still prohibits. This
does not change ADR-001's framework decision, only how it is packaged, so it
is recorded here as an amendment rather than a new ADR (the log keeps exactly
five decisions).

**Decision:** copy the template to the repo root and fill its four `TODO`
slots — `python:3.12-slim`, pinned `pip install`, an explicit source `COPY`,
and `CMD ["python", "app.py"]`, the same single command as the direct run. No
build args, no extra stages, `docker-compose` and CI still out of scope.

**Consequences:**
* (+) The `0.0.0.0` bind and `$PORT`/`$DATA_DIR` reading required here were
  already enforced by ADR-001's runtime choice — nothing in the app code had
  to change to satisfy the contract.
* (+) Proven by the provided checker: all checks pass, including idempotent
  seeding and the `PORT=9123` override (see the README's §7 evidence).
* (−) The build context must be curated (`.dockerignore`, explicit `COPY`) so
  `.git`, `.venv`, local `*.db`, and tests never enter the image.

## ADR-001b — Amendment (2026-10-09): runtime hardening, CSP deliberately omitted

**Status:** Superseded by ADR-001c on 2026-10-11 (the headers stand; the CSP
omission no longer does)

**Context:** The evaluation plan penalised the earlier project for rendering
unsanitised input with `innerHTML`. SwellSync already avoids that class of bug:
every value reaches HTML through Jinja2 autoescaping, and no JavaScript string
is built from user data. A reviewer could reasonably ask what else protects the
app in transit.

**Decision:** add four response-wide headers through `after_request` —
`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` denying camera/mic/
geolocation. **Do not** add a Content-Security-Policy. The templates still use a
few inline event handlers (`onsubmit` confirms, `onchange` filter submits) and
an inline `style=` on the rating bars, so a strict policy would break the UI,
while a policy relaxed with `'unsafe-inline'` would advertise protection it does
not provide.

**Consequences:**
* (+) The realistic browser-side risks for a local single-user app are reduced
  without touching behaviour.
* (+) Headers land on error pages too, since `after_request` runs for them.
* (−) CSP is genuinely absent, not deferred quietly — recorded here and in the
  README's design notes so it reads as a decision, and so the follow-up is
  explicit: move the inline handlers into `static/` first, then add CSP.
* (−) Still no CSRF token (ADR-001's simplification stands); POST-only writes
  and a local threat model are the current mitigation.

## ADR-001c — Amendment (2026-10-11): CSP enforced after extracting inline JS

**Status:** Accepted — 2026-10-11

**Context:** ADR-001b declined a CSP because one would have been theatre: the
templates carried six inline event handlers (three delete confirms, three auto-
submitting filters), so `script-src` could only be satisfied by
`'unsafe-inline'`, which permits exactly the injected-script class of bug the
policy exists to stop. The same reasoning that made the omission correct also
made it the right thing to remove as soon as it was cheap: the handlers were
three call sites, not an architecture.

**Decision:** move all behaviour into `static/js/app.js`, loaded `defer` from
the same origin, driven by `data-confirm` and `data-autosubmit` attributes.
Emit
`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'self'; base-uri 'self'; object-src 'none'`.
Replace the `data:` URI favicon with `static/img/favicon.svg` so `img-src`
needs no exception. Where a behaviour was an enhancement, keep the page usable
without it: the filter form gains a `<noscript>` Apply button.

**Consequences:**
* (+) `script-src 'self'` with no inline escape hatch — the directive that
  actually mitigates injected scripts is enforceable, and the autoescaping
  story in ADR-001b is now backed by a second, independent control.
* (−) One documented exception remains: `style-src 'unsafe-inline'`, because
  the rating-distribution bars write their width from data into a `style`
  attribute. Inline styles cannot execute script, so the trade is asymmetric;
  quantising the widths into fixed classes would remove it at a real cost in
  chart fidelity. Deliberately not worth it, and stated rather than hidden.
* (−) Deleting now requires JS to prompt at all. The button still works without
  it — it deletes without asking — so this is a genuine small regression in
  guardrails, mitigated by writes being POST-only.
* (+) Testable: the suite asserts against *rendered* HTML that no `on*=` handler
  survives anywhere, and parses the policy directive by directive to pin
  `script-src 'self'` and the single `style-src` escalation. A handler
  reintroduced in a shared macro fails the build.

## ADR-002 — Domain scoping and the independence seam

**Status:** Accepted — 2026-10-05

**Context:** The assignment defines two feature domains — Spot Directory
(catalog) and Session Tracker (activity) — and demands a seam: Domain 1 must
know nothing about sessions; Domain 2 may reference spots only as an external
key; any business logic that spans both domains must live in a dedicated
domain-utility module.

**Decision:**
1. `app.py` is laid out in labeled sections. The **Domain 1** routes
   (`/spots`, `/spots/<id>/edit`, `/spots/<id>/delete`) execute SQL against the
   `spots` table only — the word `sessions` never appears in their queries.
   Spot deletion does not check for child sessions; it simply attempts the
   `DELETE` and lets the SQLite foreign key raise, which the route catches.
   Referential integrity belongs to the database, not to cross-domain reads.
2. The **Domain 2** routes (`/sessions`, `/sessions/<id>/edit`,
   `/sessions/<id>/delete`) touch `spots` only through `spot_id` (insert/update
   parameter) and a read-only name join for display.
3. `domain_logic.py` is the dedicated domain-utility module: pure functions, no
   Flask and no SQL. Per-spot and global statistics (`calculate_spot_stats`)
   and the quality filter (`filter_ideal_sessions`) live there, so the math is
   shared instead of duplicated in templates or routes.
4. The dashboard (`/`) and spot detail (`/spots/<id>`) are explicitly labeled
   *composition views*: they read across the seam and delegate every
   computation to `domain_logic`.

**Consequences:**
* (+) The seam is visible in the code structure and enforced by the database
  (foreign key + `PRAGMA foreign_keys = ON`), not just by convention.
* (+) Cross-domain math is unit-testable without a server or database.
* (−) Composition views duplicate a small amount of wiring (fetch rows →
  convert to dicts → call pure functions), an acceptable price for isolation.

---

## ADR-003 — SQLite schema: one relational file with enforced integrity

**Status:** Superseded by [007] — 2026-11-18 (storage moves to SQL Server, one database per service)

**Context:** Storage must be pure SQLite in a configurable location, created
automatically at startup with no migrations or prompts. Sessions belong to
spots, and the schema in the assignment specifies `sessions.spot_id` as the
foreign key.

**Decision:** Two tables in one file at `$DATA_DIR/swellsync.db`
(default `./data/swellsync.db`):
* `spots` — `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `name` NOT NULL,
  `location` NOT NULL, `ideal_wind_dir` TEXT, `ideal_swell_ft` REAL,
  `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP).
* `sessions` — `id` (PK AUTOINCREMENT), `spot_id` INTEGER NOT NULL with
  `FOREIGN KEY (spot_id) REFERENCES spots (id)`, `date` TEXT NOT NULL (ISO
  `YYYY-MM-DD`, defaulted to today by the application), `duration_mins`
  INTEGER NOT NULL with `CHECK (duration_mins > 0)`, `wave_or_wind_rating`
  INTEGER with `CHECK (… BETWEEN 1 AND 5)`, `gear_used` TEXT, `notes` TEXT,
  `created_at`.
* Supporting details: `PRAGMA foreign_keys = ON` on every connection (SQLite
  ships with enforcement off), `ON DELETE NO ACTION` (default) so spots with
  logged sessions cannot be silently destroyed, indexes on
  `sessions(spot_id)` and `sessions(date)`, and idempotent
  `CREATE TABLE IF NOT EXISTS` executed by `init_db()` at startup.

**Consequences:**
* (+) Zero services to operate; the database is one portable file whose
  location is a single environment variable.
* (+) The engine itself rejects orphan sessions and out-of-range ratings, so
  the pure validators and the storage layer defend the same invariants.
* (−) SQLite's dynamic typing means `CHECK` constraints and application-level
  validation must work together; one write at a time is fine here but would
  cap write throughput in a multi-user system.

---

## ADR-003a — Amendment (2026-10-10): user-supplied query values never reach SQL

**Status:** Accepted — 2026-10-10

**Context:** Search (`?q=`) and sorting (`?sort=`) put a browser's query string
into a `SELECT`. Concatenating either value would be textbook injection, and
even a parameterised `LIKE` has a subtler trap: `%` and `_` are wildcards, so a
user typing a literal percent would silently widen their own search to every
row.

**Decision:**
* The search term is **bound as a parameter**, never concatenated, and is first
  escaped by `_like_pattern()` for `%`, `_` and the `ESCAPE` character itself
  (`'!'`), which makes those characters match literally.
* Sorting cannot be parameterised at all (identifiers and `ORDER BY` clauses are
  not values), so the request selects a key from the `SESSION_SORTS` whitelist
  map. Unknown or hostile values fall through to the default ordering; nothing
  the user sends is ever interpolated into the statement.

**Consequences:**
* (+) Both features are safe by construction rather than by validation, and the
  rule is easy to keep: values bind, fragments map.
* (+) Both behaviours are pinned by tests, including a deliberately
  injection-shaped `?sort=` that must leave the data intact and fall back to the
  default order, and `?q=%25` which must not return every spot.
* (−) Sorting is limited to the four whitelisted orders; arbitrary column
  sorting would mean editing the map, which is the intended cost.

## ADR-004 — Testing strategy: pure business logic first

**Status:** Accepted — 2026-10-05

**Context:** The assignment requires automated pytest coverage of core
business logic at ≥ 70%, plus tests of the SQLite CRUD actions, while the
application itself is a thin layer of routes over two tables.

**Decision:** Three tiers, in priority order:
1. **Pure-function tests (the graded tier).** `domain_logic.py` is exercised
   with plain dicts and lists — no Flask app, no database — covering the happy
   paths, boundaries (rating exactly 4, duration 0), and malformed inputs
   (non-numeric duration, impossible calendar dates like `2026-02-30`).
   Coverage is measured with the exact required command
   `pytest --cov=domain_logic test_app.py`; the module is small and fully
   exercised, so the measured figure is ~100%.
2. **CRUD tests through the test client.** Each test boots `create_app()`
   against a pytest `tmp_path` data directory, drives the routes with the
   Flask test client, and verifies persisted rows by opening the SQLite file
   directly — the assertions do not depend on rendered HTML. Foreign-key and
   CHECK-constraint enforcement are additionally tested at the engine level.
3. **Smoke assertions on rendered pages** (status codes, key strings) for the
   composition views, including the custom 404 page.

Explicitly out of scope: browser/E2E tests and JavaScript tests.

**Consequences:**
* (+) The whole suite runs in about two seconds (103 tests, ~1.6 s measured
   2026-10-11); failures in the logic tier point
   straight at a function, not at a page.
* (+) Framework glue stays thin by construction — anything worth testing
   heavily was pushed into `domain_logic.py`.
* (−) Template regressions (broken layout, missing CSS) are only caught when
   a key string disappears; visual regressions are invisible to the suite.

---

## ADR-005 — Omitted feature: external weather API sync and live tide webhooks

**Status:** Accepted (deliberate omission) — 2026-10-05

**Context:** The obvious "real" feature for a session logger is automatic
condition capture: pulling observed wind/swell from an external weather API
when a session is logged, and receiving live tide webhooks to warn about
window timing. A grader (or user) may ask why it is absent.

**Decision:** Omit both, deliberately. They would require: an outbound API
dependency with a key to manage, network-failure and rate-limit handling, a
webhook receiver with its own endpoint security, and — for "live" updates —
a scheduler or background worker. Every one of those cuts against the
assignment's hard constraints (single process, no background services, no
external message brokers) and against deterministic, offline-capable tests.
Condition capture instead happens the way surfers actually do it: the user
types what they observed into the session's `gear_used`/`notes` fields.

**Consequences:**
* (+) The application has no secrets, no network dependencies, and a test
  suite that never flakes on a third-party outage.
* (+) The domain seam stays clean — nothing in either domain needs to know
  about HTTP clients.
* (−) Sessions lack machine-readable observed conditions (wind speed, swell
  height at log time); any analytics on "how good was it really" is limited to
  the 1–5 human rating.
* (→) If added later, the right shape is a new `weather.py` module behind a
  narrow interface, called from the Session Tracker after validation, never
  from the Spot Directory.

## ADR-006 — The split: where the seam is, what crosses it, and whether ADR-002 held

**Status:** Accepted — 2026-11-18

**Context:** Assignment 2 requires one service per feature domain, each in its
own container with its own database. ADR-002 already located the seam: Domain 1
(spots) never reads `sessions`, and Domain 2 (sessions) references spots only by
`spot_id`. The split has to put that seam on the network.

**Decision:**
1. The seam stays where ADR-002 drew it. `services/spots` owns the `spots` table
   and `services/sessions` owns the `sessions` table. Each service has its own
   Dockerfile, its own `requirements.txt`, and its own migrations.
2. Two HTTP calls cross the seam, and nothing else:
   * `sessions` → `spots`: `GET /spots` to show spot names in the session list,
     and `GET /spots/{id}` before a session is created or updated.
   * `spots` → `sessions`: `GET /sessions?spot={id}` before a spot is deleted, so
     a spot that still has sessions is refused with 409.
3. The dashboard and spot detail are composition views in the browser. The
   static UI calls both services and combines the answers, so the server-side
   cross-seam flow is the session list and session writes.
4. Every outbound call has a 2-second timeout (`SPOTS_TIMEOUT_S`,
   `SESSIONS_TIMEOUT_S`). When the list cannot get spot names, it returns the
   sessions with `spot_name` null and a `notice`. When a write needs a spot
   check and the spots service does not answer, the write fails with 503 and
   nothing is stored.
5. `domain_logic.py` is copied into both services. Each service stays
   self-contained and deployable on its own, at the cost of two copies of the
   validation and statistics code.

**Consequences:**
* (+) ADR-002 held. Domain 1 code still never queries `sessions`, and Domain 2
  still touches spots only through `spot_id` and an HTTP lookup.
* (−) ADR-002 said spot deletion would rely on the database foreign key. That
  no longer works across the seam, so deletion now asks the sessions service
  first. That makes the spots service depend on sessions for one endpoint. The
  dependency is one-way at boot (neither service needs the other to start), so
  compose does not need a cycle in `depends_on`.
* (−) Two copies of `domain_logic.py` can drift apart. A shared package would fix
  this, but would couple the two images at build time.
* (→) If the seam moved again, the candidates would be the sessions-to-spots
  name lookup (cache it) or the spot-delete check (move it into the sessions
  service as a "soft delete" flag). Neither is needed at the current size.

## ADR-006a — Amendment (2026-11-22): the spot path parameter is `spot_id`

**Status:** Accepted — 2026-11-22

**Context:** Decision 2 of ADR-006 wrote the spot lookup as `GET /spots/{id}`.
The OpenAPI document for spots, `system.yaml`, and the contract test all use
`{spot_id}`. The contract test found the mismatch in `system.yaml` on 2026-11-20.

**Decision:** The seam call is `GET /spots/{spot_id}`. The meaning is unchanged:
`sessions` asks `spots` for one spot before a session is written. The name is
the one the document uses, so the record and the contract agree.

**Consequences:**
* (+) The written decision matches the document the contract test checks.
* (−) None for behaviour. Only the name in the record changed.

## ADR-007 — Data and migrations: SQL Server, one database per service, forward-only

**Status:** Accepted — 2026-11-18

**Context:** Storage moves from one SQLite file to one serverless SQL Server
database per service (ADR-003 is superseded). Assignment 2 requires versioned
migrations that run on startup, record what was applied, and never drop data.

**Decision:**
1. Migrations are numbered SQL files, `services/<name>/migrations/NNN_*.sql`,
   applied by a small runner (`db.py`) in filename order. Each file runs in its
   own transaction and is recorded in a `schema_migrations` table, so a second
   boot applies nothing. `GO` lines separate T-SQL batches.
2. A single replica runs the migrations at startup (ADR-008 sets max replicas
   to 1), so two boots cannot migrate at once.
3. Seed data is loaded only when the table is empty, so a restart never
   duplicates it.
4. Data does not move from the old SQLite file. The local stack starts from the
   seed file, which contains the demo spots and sessions. A real SQLite file
   would need an export-and-import step, and none is written, so this is a
   known limit: the old data is not carried over.
5. Recovery plan for a bad migration in production:
   * Migrations are forward-only. A bad one is fixed by a new numbered file, and
     applied migrations are never edited.
   * Before a deploy that includes a migration, the Azure SQL database has
     automatic point-in-time restore, which can return the database to a time
     before the migration.
   * To roll back the code, redeploy the previous image by its commit SHA. The
     older image still runs against the restored schema.

**Consequences:**
* (+) The runner has no dependency beyond `pymssql`, and each migration is
  reviewable in one file.
* (+) Pinning images to commit SHAs makes "which code ran against which schema"
  traceable.
* (−) Referential integrity lost at the seam. `sessions.spot_id` has no foreign
  key. The check happens in code on create and update, and in the spot delete
  path. A race is possible: a spot could be deleted between the check and the
  insert. The window is small for one user, and the risk is accepted.
* (−) No down-migrations. Recovery is restore plus redeploy, which is slower than
  a script but safe.
* (→) If the team grows, the migration runner should take an advisory lock so
  that several replicas cannot run it at the same time.

## ADR-008 — Hosting: serverless containers and serverless databases on Azure

**Status:** Accepted — 2026-11-22. Deployed to the student's own Azure for Students
subscription. The first deploy from `main` is pending the GitHub secrets and the
merge to `main` (see the README, Azure setup).

**Context:** ADR-006 split the system into two services with a seam between
them, and ADR-007 put each service on its own SQL Server database. Assignment 2
asks for a hosted system with a public URL, deployed by the course guide. The
workload is a single user, so the hosting should cost little while idle and
should not need an always-on server. ADR-007 assumes one replica per service, so
migrations never run twice at once.

The first deployment was made in the IE group subscription, in `rg-sdd-3b`, with a
Static Web App for the UI and a service principal planned for the pipeline. The
course guide places individual work in the student's own subscription and forbids
service principals for IE accounts. That deployment was not the one submitted, and
the decisions below replace it.

**Decision:**
1. Each service runs as an Azure Container App in one environment,
   `gamsoulas-ieu2024-env`, in `norwayeast`. The apps are
   `gamsoulas-ieu2024-spots` and `gamsoulas-ieu2024-sessions`.
2. Images come from GHCR, tagged with the commit SHA by the `images` workflow
   and built without provenance, so Azure can pull the public packages. A deploy
   names the SHA it runs, so a rollback is a redeploy of an earlier SHA.
3. Each service has its own serverless Azure SQL database on the free offer, on
   the server `gamsoulas-ieu2024-sql2`. The server is in `germanywestcentral`,
   because Norway East refused to create a SQL server on this subscription. Each
   service connects as its own contained user, which can reach only its database
   and run migrations. The first connection after a pause can fail with error
   40613, so `db.py` retries with backoff for about a minute (ADR-007).
4. Maximum replicas is 1 for both services (ADR-007, decision 2).
5. The UI is a Storage static website on `gamsoulasieu2024ui`. The services allow
   its origin through `ALLOWED_ORIGIN`.
6. Deploys run only from `main`, after the CI and image workflows pass
   (`cd.yml`). The pipeline signs in with a user-assigned managed identity,
   `gamsoulas-ieu2024-github`, through OIDC federated credentials. No service
   principal and no Azure password is stored in GitHub.
7. Passwords for the contained users are generated locally and stored only as
   GitHub secrets. They are not written to the repository or the README.

**Consequences:**
* (+) Idle cost is close to zero: the database pauses on the free offer and the
  container scales to zero. That suits one user.
* (+) The pipeline holds no long-lived Azure secret, only federated trust for the
  `main` branch.
* (+) Each image can be traced to a commit, and a rollback is an image redeploy
  (ADR-007).
* (−) One replica per service means no horizontal scaling, and a deploy takes a
  service down briefly while the new revision starts.
* (−) A cold start after an idle period can take up to a minute, and the first
  request may return 503 "App port is not ready". The UI has to handle that
  (course guide, step 8).
* (−) The SQL server is in a different region from the rest, which adds a
  cross-region call from the services to the database.
* (−) The contained users are created by hand, following the README. There is no
  automated step for them yet.
* (→) If one service needs to scale out, the migration runner needs an advisory
  lock first (ADR-007, consequences).

## ADR-009 — Pipeline and testing gates: what CI must pass before a merge

**Status:** Accepted — 2026-11-20

**Context:** Assignment 2 requires a CI job that builds the images on every push
and pull request, and publishes only from main. The brief also asks for tests,
coverage, and checks that the documents describe the running system. Each
service now has unit tests (ADR-004), a cross-seam suite (ADR-006), OpenAPI
documents, and a `system.yaml`. Nothing yet stops a change that breaks one of
them. The image build only proves that the image compiles and runs.

**Decision:**
1. A `ci` workflow runs on every push and pull request, with four jobs:
   * `lint`: `ruff check` over `services/` and `tests/`, with the rules in `ruff.toml`.
   * `test`: one job per service (matrix). It runs the service's unit tests and
     fails below 70% coverage of the service code (`app.py`, `db.py`,
     `domain_logic.py`; the tests are excluded by `.coveragerc`).
   * `integration`: the cross-seam suite, where the two real apps call each
     other over HTTP.
   * `contracts`: each OpenAPI document must validate. Each running app must
     serve exactly the operations its document lists, in both directions. Every
     call in `system.yaml` must be documented by the service it calls.
2. The databases in tests are in-memory fakes. CI does not start SQL Server.
   The fakes reject any SQL they do not recognise, so a new query fails loudly.
3. The image workflow (`images.yml`) still builds on every event and pushes
   only from main. The publish step itself does not depend on `ci` in another
   file. The `Main` ruleset on `main` is active and requires the five `ci`
   checks by name (lint, both unit-test jobs, cross-seam integration, contracts).
   A red run blocks the merge. It was switched on 2026-11-21; before that the
   ruleset was disabled and targeted no branch. A test in `tests/contracts`
   fails if a check name in `ci.yml` drifts from the ruleset's list.
4. CI runs on Python 3.12 to match the container base image. Local runs have
   also passed on Python 3.9 and 3.13.

**Consequences:**
* (+) A change that breaks a route, a documented call or the seam is caught
  before merge. The contract check found one real mismatch on its first run.
* (+) Coverage is measured on the service code, not the tests, so the 70% floor
  means something.
* (−) Fakes do not prove the SQL works on SQL Server. The compose stack and the
  deployed health checks cover that, and a SQL Server job is deferred to the
  Azure stage.
* (−) The margin over the floor is small (76% against 70%). A large new module
  without tests will fail the gate, which is the intent, but it will be noticed.
* (−) The course's `system.schema.json` is not in the repo yet, so the schema
  check is skipped and shows as a skip in CI until it arrives.
* (→) If `ci` jobs ever run slower than a few minutes, the integration suite
  and the contract suite can move to a separate workflow with the same gates.
