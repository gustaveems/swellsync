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

SwellSync is a single-process web application for logging surf and sailing
sessions against a directory of spots. It exists to demonstrate a small,
shippable system that satisfies a strict deployment contract: one container,
one process, one SQLite file, no background services.

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
| 2026-10-11 | 3 | This report; ADR amendments closing the date-span rule; log row |

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

`[ALAIN]` **2.2 — the SDLC choice (required).** Name the model you are claiming
and justify it. To make the claim arguable rather than decorative, answer:
- Which model is this — strict Waterfall, iterative-incremental, XP-style with
  tests first, or something else? Be specific and pick one.
- Why does that model fit *this* project? Cite the assignment's own constraints
  (fixed contract, 6 dependencies max, no infrastructure, closed-book check)
  rather than generic virtues.
- What is one thing the model cost you, and one situation where it would have
  been the wrong choice? (A justification without a cost is not a
  justification.)

### 2.2 SMART goals

A goal is only useful here if it can be checked without asking anyone's opinion.

| # | Goal | Specific / Measurable | Achieved | Time-bound |
|---|---|---|---|---|
| 1 | Core business logic is tested | `domain_logic.py` line coverage ≥ 70% | **100%** (130/130 statements, 0 missed) | by 2026-10-05 |
| 2 | The app satisfies the deployment contract | course `run.sh` reports `ALL CHECKS PASSED` | **PASSED**, re-run 2026-10-11 after the docs changes | by 2026-10-08 |
| 3 | Keep the dependency surface small | fewer than 6 direct dependencies | **3** (`flask==3.1.3`, `pytest==8.4.2`, `pytest-cov==7.1.0`) | from 2026-10-05 |
| 4 | Start fast enough to orchestrate | container answers on `$PORT` well under 2 s | **0.15–0.32 s** cold boot measured 2026-10-11 | by 2026-10-08 |
| 5 | Show real development history | ≥ 12 commits over ≥ 6 distinct calendar days, no day > 40% | **36 commits / 7 days**, largest day 27.8% | 2026-10-05 → 10-11 |
| 6 | Keep no unwritten decisions | `ADR.md` with 5 entries spanning ≥ 3 commit dates | **5 decisions + 3 dated amendments**, across 4 dates (2026-10-05, -08, -09, -10) | by 2026-10-10 |

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

`[ALAIN]` **3.4** Explain the seam in your own words and defend it: what does
keeping Domain 1 ignorant of `sessions` buy you, and what would break if the
spot-delete route simply counted children first? Say plainly if you think the
benefit here is thin — that is a better answer than borrowed confidence.

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

`[ALAIN]` **4.3** Why is `duration_mins` an integer number of minutes rather
than a time-of-day pair, and where would that choice hurt you?

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
- **No CSP**, because templates still use a few inline event handlers; a strict
  policy would break them and a permissive one would be theatre. Documented in
  the README rather than quietly omitted.
- **Werkzeug development server** is the runtime. One process, one write at a
  time — fine for this scope, not a load-bearing choice.
- **Local `python3` is 3.9.6 while the container is 3.12.** The suite passes on
  the older host, so the code is compatible with both.
- The **first day of history contains 10 commits** (27.8% of the 36-commit total
  as of 2026-10-11, and falling with every later commit). The spread is genuine
  and forward-dated; nothing was backdated, per §5 of the brief.

---

## 6. AI use and authorship

AI assistance was used throughout and is disclosed rather than implied. The
per-interaction log is `AI_USAGE.md` (11 rows, one per substantive interaction),
which records the prompt, the disposition, what changed and why, and a plain-
language explanation. Design decisions are in `ADR.md` — five decisions, plus
dated amendments recording the container adoption (2026-10-08), the deliberate
omission of CSP (2026-10-09) and the rule that user-supplied query values never
reach SQL (2026-10-10). The final column of the log is the student's own writing
for rows 1–5; later rows are still assistant-drafted and require rewriting —
stated in that file itself.

**Division of labour as it actually happened:** the brief and the assignment
constraints came from the course; the specification relayed to the assistant was
written by the student; code, tests and documentation were drafted with AI and
then executed, measured and audited against the brief; the reasoning sections of
this report and the comprehension check are the student's own responsibility.

`[ALAIN]` **6.1** Which two decisions in `ADR.md` could you defend right now
without notes, and which one would fall apart if a teacher asked "why"? Fix that
one first.

---

## 7. Before you submit — checklist

- [ ] §2.2 SDLC model named and justified, **including one cost**
- [ ] §2.3 personal SMART goal added
- [ ] §3.4 seam defended in your own words
- [ ] §4.3 duration-as-minutes rationale answered
- [ ] §6.1 the two ADRs you can defend, named
- [ ] `AI_USAGE.md` rows 6–10 rewritten in your own voice
- [ ] Skim `app.py` and `domain_logic.py` until you can point at any function and
      say what it does — the §6 check is closed-book and multiplies the total
- [ ] Confirm your use case was pre-approved (the pivot from the previous
      project happened outside the teacher's view)
- [ ] Re-run `pytest --cov=domain_logic test_app.py` and `run.sh` on the final
      tree, and check this report's numbers still match
