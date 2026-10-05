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

**Status:** Accepted — 2026-10-05

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
* (+) The suite runs in well under a second; failures in the logic tier point
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
