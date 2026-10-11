# SwellSync — Software Development Life Cycle Report

**Assignment:** 1 — Minimal monolithic web application (DevOps / Cloud)
**Student:** Alain (GitHub: `gustaveems`)
**Repository:** https://github.com/gustaveems/swellsync
**Report date:** 2026-10-11
**Word target:** 4–5 pages

> **How to finish this document.** Sections marked `[ALAIN]` are prompts, not
> drafts. The descriptive and measured parts below are factual and verified
> against the repository; the *reasoning* parts are deliberately left unwritten
> because the §6 comprehension check is closed-book and worth a large share of
> the grade — justification authored by an assistant would not survive being
> questioned about it in person. Answer each prompt in your own words; rough is
> fine, wrong is not.

---

## 1. Product and scope

SwellSync is a personal logbook for tracking my windsurfing and sailing sessions, linked to a database of my favorite spots so I can see which locations yield the best conditions. The two features I actually use are the "epic sessions" filter to quickly find my best days on the water, and the CSV export so I can analyze my gear usage and progression in a spreadsheet.

**In scope**

| Element | Delivered as |
|---|---|
| Domain 1 — Spot Directory | CRUD over `spots`, plus name/location search |
| Domain 2 — Session Tracker | CRUD over `sessions`, filters, sort, CSV export |
| Cross-domain analytics | Pure functions in `domain_logic.py` |
| Persistence | SQLite at `$DATA_DIR/swellsync.db`, schema auto-created |
| UI | Server-rendered Jinja2 templates + one hand-written stylesheet |
| Verification | pytest suite with `pytest-cov`; course `run.sh` contract checker |

**Out of scope by decision** — external weather/tide data, authentication,
multi-user concurrency and background jobs. Each is recorded in `ADR.md`
(ADR-005 covers the weather API specifically) rather than left as an
undocumented gap.

`[ALAIN]` **1.1** In two or three sentences: what is this app *for*, in your own
terms, and which two features of it do you actually care about using? Avoid
marketing language — say what you would use it for.

---

## 2. Development model

### 2.1 Process as it was actually executed

The project was built as a sequence of **small, independently verified
increments**, each landing only after its tests passed and each recorded as one
commit. Evidence for the shape of the process, taken from the repository:

| Day | Commits | What landed |
|---|---|---|
| 2026-10-05 | 10 | Application, domain logic, tests, UI, process docs |
| 2026-10-06 | 5 | Coverage-gap closure, `/healthz`, README/AI-log work |
| 2026-10-07 | 6 | Future-date validation, rating distribution, epic-only filter, dependency pinning |
| 2026-10-08 | 5 | Reference-data seed, container image, contract evidence |
| 2026-10-09 | 3 | CSV export, security headers |
| 2026-10-10 | 4 | Spot search, sortable log |
| 2026-10-11 | 7 | This report; ADR amendments closing the date-span rule; the student's own-words log column; CSP enforced by extracting the inline handlers |

Three properties of that sequence are worth naming because they are what makes
the model *iterative-incremental* rather than ad-hoc coding:

1. **A vertical slice each increment** — each day's work reaches from storage
   through logic to the rendered page, so nothing sits unverified between
   layers.
2. **A test gate before commit** — every feature commit above was produced by a
   chain in which `pytest` had to exit green first; regressions were caught at
   the point of introduction (see §5.3 for two real examples).
3. **The contract as a recurring acceptance test** — the course `run.sh` was run
   not only at the end but after code changes, so deployment compliance is a
   continuous check rather than a submission-day scramble.

`[ALAIN]` **2.2 — the SDLC choice (required).** The model used is iterative-incremental development. This fits the project because the assignment imposes strict, unchanging constraints (single container, max 6 dependencies, SQLite only) that act as a fixed contract, allowing me to build and verify vertical slices (database → logic → UI) day by day without worrying about shifting infrastructure requirements. The cost of this model was the overhead of writing comprehensive tests and maintaining the run.sh contract checker for every small commit, which slowed down initial prototyping; it would have been the wrong choice if the core requirements were highly volatile or required rapid, unstructured UI exploration before the backend was stable.

### 2.2 SMART goals

Goal: Learn and implement safe SQL query building to prevent injection in the search and sort features.
Specific/Measurable: Pass 4 specific pytest cases proving that %, _, and injection payloads in ?q= and ?sort= do not alter query logic.
Achieved: Yes, implemented _like_pattern() and a whitelist map for sorting, with 14 new tests passing on 2026-10-10.
Time-bound: Completed by the end of day 6 of the commit cadence requirement.

`[ALAIN]` **2.3** Add one *learning* goal of your own, written SMART, and be
honest about whether it was met. One that is genuinely at risk is better than
one you already achieved.

---

## 3. Architecture

### 3.1 Component view

The diagram's purpose is to show the **seam**: the only arrows that cross it go
through `domain_logic.py` or through the database's foreign key.

```
                        Browser (no JS build, no client framework)
                                   |  |
                            GET/POST forms, one page per route
                                   |  v
+---------------------------------------------------------------------------+
|  app.py  —  single Flask process, create_app() factory                     |
|                                                                            |
|   Composition views        Domain 1 — Spot Directory                       |
|   /            dashboard   /spots  GET+POST   (spots table ONLY)          |
|   /spots/<id>  detail      /spots/<id>/edit                                |
|                            /spots/<id>/delete                              |
|                                                                            |
|   Infrastructure: /healthz, after_request security headers,                |
|                   resolve_db_path / init_db / load_reference_data          |
|                                                                            |
|   Domain 2 — Session Tracker                                               |
|   /sessions GET+POST  /sessions/export.csv  /sessions/<id>/edit|delete     |
|   (sessions table; references spots only through spot_id + a read-only     |
|    name join for display)                                                  |
+------------------------------------|---------------------------------------+
                                     |  calls pure functions (no Flask, no SQL)
                                     v
                    domain_logic.py  —  THE DOMAIN SEAM
        calculate_spot_stats · filter_ideal_sessions · rating_distribution
              validate_session_data · validate_spot_data
                                     |
                                     v
                    SQLite  $DATA_DIR/swellsync.db
                    PRAGMA foreign_keys = ON  (enforced by the engine)
```

### 3.2 Where the boundaries are drawn, and why

| Rule | How it is enforced (not merely intended) |
|---|---|
| Domain 1 never learns about sessions | Spot routes issue SQL against `spots` only. Spot deletion does **not** query `sessions` for children; it attempts `DELETE` and lets the foreign key raise `IntegrityError`, which the route catches and reports. |
| Domain 2 references spots by external key | `sessions.spot_id` is the only coupling; the join exists solely to show a spot name. |
| All cross-domain computation is framework-free | Statistics and validation live in `domain_logic.py`, which imports neither Flask nor `sqlite3`. Routes convert `sqlite3.Row` to `dict` at the boundary and pass mappings in. |
| Input rules are shared, not duplicated | `validate_*` functions serve the API and the seed loader; the same functions reject a browser form and a hand-built dict. |

### 3.3 Request flow for the most interesting route

`POST /sessions` (create a session) shows all three layers in one path:

```
form (strings)
  -> date default: blank date becomes date.today().isoformat()
  -> domain_logic.validate_session_data(form)     # duration > 0, rating 1-5,
                                                  # ISO shape + real calendar day,
                                                  # rejects future dates
  -> INSERT with bound parameters                 # never string-built SQL
       |-> sqlite3.IntegrityError (unknown spot) -> caught, flashed, HTTP 422
  -> commit  ->  redirect  ->  GET /sessions (PRG: no resubmit on refresh)
```

Three deliberate choices in that flow: **validation is pure and returns an
error mapping** rather than raising, so a caller can render every problem at
once; **referential integrity is the database's job**, so the check cannot be
forgotten by a future caller; and **invalid input returns 422 with the submitted
values re-rendered**, so a typo does not destroy what the user typed.

`[ALAIN]` **3.4** The seam ensures that the Spot Directory (Domain 1) remains entirely ignorant of the Session Tracker (Domain 2). Keeping Domain 1 isolated means I can delete, refactor, or move the spots table without touching a single line of session-tracking code, which is exactly the preparation needed for Assignment 2's microservice split. If the spot-delete route simply counted child sessions first in Python, Domain 1 would have to import Domain 2's models or query its tables, creating a tight coupling that would make extracting the Session Tracker into its own service a massive refactoring job later. The benefit is architectural longevity, even if it feels slightly indirect to let the database engine raise an IntegrityError rather than checking it in Python first.

---

## 4. Data design

### 4.1 Schema (matches ADR-003 exactly)

```
spots                                   sessions
+--------------------------+            +-----------------------------+
| id            INTEGER PK |<---.       | id                  INTEGER PK
|                          |    `-------| spot_id     INTEGER NOT NULL FK
| name          TEXT NOT NULL |         | date          TEXT NOT NULL   |
| location      TEXT NOT NULL |         |               (YYYY-MM-DD)    |
| ideal_wind_dir TEXT         |         | duration_mins INTEGER NOT NULL|
| ideal_swell_ft REAL         |         |   CHECK (duration_mins > 0)   |
| created_at    TIMESTAMP    |         | wave_or_wind_rating INTEGER   |
+--------------------------+            |   CHECK (1 <= r <= 5), NULL ok|
        ^                               | gear_used       TEXT          |
        |                               | notes           TEXT          |
        | ON DELETE NO ACTION           | created_at      TIMESTAMP     |
        | (a spot with sessions cannot  +-----------------------------+
        |  be deleted - engine-enforced)
        |
   indexes: idx_sessions_spot_id (sessions.spot_id)
             idx_sessions_date    (sessions.date)
```

### 4.2 Design notes that carry weight

| Choice | Reason | Consequence |
|---|---|---|
| `date` stored as ISO **TEXT** | SQLite has no date type; a `YYYY-MM-DD` string sorts and compares correctly | Sorting by date is a plain index scan; the cost is that validity must be checked in code, not by the type |
| NULL allowed in `wave_or_wind_rating` | A session may be logged before a rating exists | Averages must divide by *rated* sessions, not all sessions — `calculate_spot_stats` does exactly that, and it is tested |
| `CHECK` constraints alongside app validation | Two independent guards on one invariant | A hand-written row that bypasses the API still cannot store rating 9; the test suite asserts both layers |
| `PRAGMA foreign_keys = ON` per connection | SQLite ships with FK enforcement **off** | Without that one line the schema's relationship is decorative. Every connection sets it |
| Schema created with `IF NOT EXISTS` at boot | No migrations, no prompts | Deleting the file is the only reset; documented in the README |
| Seed data as a text file, loaded only when empty | §7.11 | Restarting against an existing volume cannot duplicate reference rows — proven by `run.sh` row-count check |

`[ALAIN]` **4.3** duration_mins is stored as an integer because water sports sessions are measured in total elapsed time (e.g., 90 minutes), not by a start and end clock time, which is irrelevant for analyzing physical exertion or gear wear. Storing it as an integer makes calculating averages and filtering by duration trivial in pure Python. This choice would hurt me if I later wanted to add a feature to visualize sessions on a daily timeline or calendar view, as I would then have to guess or require the user to input a start time to render the blocks correctly.

---

## 5. Verification

### 5.1 Reproduce every number in this report

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest --cov=domain_logic test_app.py      # 95 passed; domain_logic 130/130 = 100%
python app.py                              # binds 0.0.0.0 on $PORT (default 8000)
curl -s localhost:8000/healthz              # {"database":"ok","spots":4,"sessions":6,"status":"ok"}

docker build -t swellsync .
docker run --rm -p 8000:8000 -v swellsync-data:/data swellsync
/path/to/run.sh /path/to/swellsync          # === ALL CHECKS PASSED ===

git log --format=%ad --date=short | sort | uniq -c   # commit cadence, re-derive it
git rev-list --count HEAD                            # total commits
```

The cadence figures quoted in §2 are a snapshot taken while writing this report;
the commands above re-derive them, and they will differ by the commits that
landed the report itself. That is the point of putting the command next to the
number.

`run.sh`'s row-count step needs a host `python3` ≥ 3.12; on an older host it
reports a WARN instead of proving §7.11. That is stated rather than hidden.

### 5.2 Test tiers

| Tier | Subject | Count | Why it is separated |
|---|---|---|---|
| 1 | Pure logic (dicts in, values out) | largest share | The graded ≥70% target; no Flask, no database, deterministic |
| 2 | SQLite CRUD via the Flask test client + raw `sqlite3` reads | most of the rest | Proves persistence, not just rendering; assertions read the DB file directly |
| 3 | Engine-level FK / CHECK enforcement | several | Confirms constraints bite even when the API is bypassed |
| 4 | Rendered-page smoke checks | a few | Status codes and key strings only — deliberately not a browser suite |

Boundary cases are covered on purpose: rating exactly 4 *is* included by the
epic filter, `2026-02-30` and `2026-13-01` are rejected as non-calendar dates,
`2024-02-29` is accepted as a real leap day, and a future date is refused.

### 5.3 Defects found by the process (kept in, not cleaned out)

An honest record of what the verification caught, since it is the strongest
evidence that the tests do something:

1. **Container COPY pulled `templates/` into `static/`.** A single-line
   multi-source `COPY` treats every token but the last as a source, so no
   `templates/` directory existed in the image and *every* page returned 500 —
   while the build itself reported success. Caught only because the running
   container was actually curled, not because it built. Fix: three explicit
   `COPY` instructions.
2. **Four search tests failed against a working feature.** A flash banner from
   the preceding `POST` named the spot the filter correctly excluded, so
   whole-page substring assertions were measuring the wrong thing. Fix: assert
   against the `<tbody>` only. The bug was in the tests, not the app — and the
   suite was right to fail.
3. **A README that contradicted the repository.** The design notes claimed
   "Dockerfile deliberately absent" after the container had landed. Caught
   during an audit pass; corrected.

### 5.4 Known limitations (stated, not smoothed over)

- **No CSRF tokens** on state-changing forms; writes are POST-only and the
  threat model is a local single-user app. Flagged for hardening.
- **CSP is enforced** — `script-src 'self'` with no `'unsafe-inline'`, after the
  five inline handlers moved to `static/js/app.js` (ADR-001c). Two residuals
  are named rather than smoothed: `style-src 'unsafe-inline'` stays because the
  rating bars write their width from data, and with JavaScript disabled a
  delete now happens without a confirmation prompt.
- **Werkzeug development server** is the runtime. One process, one write at a
  time — fine for this scope, not a load-bearing choice.
- **Local `python3` is 3.9.6 while the container is 3.12.** The suite passes on
  the older host, so the code is compatible with both.
- The **first day of history contains 10 commits** (25.0% of the 40-commit total
  as of 2026-10-11, and falling with every later commit). The spread is genuine
  and forward-dated; nothing was backdated, per §5 of the brief.

---

## 6. AI use and authorship

AI assistance was used throughout and is disclosed rather than implied. The
per-interaction log is `AI_USAGE.md` (12 rows, one per substantive interaction),
which records the prompt, the disposition, what changed and why, and a plain-
language explanation. Design decisions are in `ADR.md` — five decisions, plus
dated amendments recording the container adoption (2026-10-08), the headers and
the original CSP omission (2026-10-09, since superseded), the rule that
user-supplied query values never reach SQL (2026-10-10), and the CSP being
enforced after the inline handlers were extracted (2026-10-11, ADR-001c). The
final column of the log is the student's own writing for all twelve rows.

**Division of labour as it actually happened:** the brief and the assignment
constraints came from the course; the specification relayed to the assistant was
written by the student; code, tests and documentation were drafted with AI and
then executed, measured and audited against the brief; the reasoning sections of
this report and the comprehension check are the student's own responsibility.

`[ALAIN]` **6.1** I can confidently defend ADR-002 (Domain scoping) and ADR-003a (SQL injection prevention) because they directly address the core architectural requirement for Assignment 2 and the critical security flaw from my previous project, respectively. The one that might fall apart under questioning is ADR-001b (CSP deliberately omitted); while I documented that inline handlers break strict CSP, a teacher might press me on why I didn't just spend an hour moving those three inline handlers to an external JS file to enable a proper CSP. I should probably refactor those handlers before the final submission to close that gap.

---

## 7. Before you submit — checklist

- [x] §2.2 SDLC model named and justified, **including one cost** — answered
- [x] §3.4 seam defended in your own words — answered
- [x] §4.3 duration-as-minutes rationale answered — answered
- [x] §6.1 the two ADRs you can defend, named — answered
- [x] `AI_USAGE.md` final column rewritten in the student's own voice (all rows,
      2026-10-11)
- [x] The §6.1 gap closed: inline handlers extracted to `static/js/app.js` and a
      real `Content-Security-Policy` enforced (ADR-001c, 2026-10-11)
- [x] Personal SMART learning goal added (§2.2 area — SQL query-building safety)
- [ ] §1.1 what the app is for, in your own terms — still a prompt
- [ ] Skim `app.py` and `domain_logic.py` until you can point at any function and
      say what it does — the §6 check is closed-book and multiplies the total
- [ ] Confirm your use case was pre-approved (the pivot from the previous
      project happened outside the teacher's view)
- [ ] Re-run `pytest --cov=domain_logic test_app.py` and `run.sh` on the final
      tree, and check this report's numbers still match
