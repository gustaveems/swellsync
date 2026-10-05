# AI Usage Log — SwellSync

> **Read this first.** This log records every substantive AI interaction on
> the project, as required by the course syllabus. The final column ("In my
> own words…") is still assistant-written prose — **it is the one part meant
> to be replaced by the student's own voice before submission.** Commit
> hashes reference this repository's history (`git log --oneline`).

| | |
|---|---|
| **Project** | SwellSync — Surf & Sail Session Logger (Assignment 1) |
| **AI tool** | Qwen Code — terminal-based coding agent |
| **Interaction dates** | 2026-10-05 · one working session · 5 logged interactions |
| **Verified results** | 58/58 pytest tests passing · `domain_logic.py` line coverage **100%** (requirement: ≥ 70%) · live HTTP smoke test on `0.0.0.0:$PORT` |

| Date/commit | Tool | Prompt | Disposition | What changed & why | In my own words, how this works |
|---|---|---|---|---|---|
| 2026-10-05 / 8a18e4f, a76364d, 512d962 | Qwen Code | "Build SwellSync per Assignment 1: Flask + SQLite, two domains (Spot Directory, Session Tracker), pure business-logic functions, single process, under 6 dependencies, no Docker/CI/Terraform." | Accepted, pending review | Generated `requirements.txt` (3 direct dependencies), `domain_logic.py`, and `app.py` — the three files that carry the assignment's hard constraints: the dependency cap, the domain seam, and the single-process runtime. | One Python file boots the whole product: on startup it creates the SQLite file under `DATA_DIR` (tables via `IF NOT EXISTS`, so nothing is ever migrated by hand), then serves pages that read and write the two tables. All the math — averages, the rating ≥ 4 quality filter, form validation — lives in a separate module with zero Flask imports, so it tests like plain Python functions. |
| 2026-10-05 / 2631795 | Qwen Code | "Write a pytest suite: cover `calculate_spot_stats`, `filter_ideal_sessions`, `validate_session_data` plus SQLite CRUD; business-logic coverage must be ≥ 70%." | Accepted, pending review | Generated `test_app.py`. Two tiers: pure-function tests over dicts, plus CRUD driven through the Flask test client against a temporary `DATA_DIR`, with rows re-read via raw `sqlite3` so assertions never depend on rendered HTML. Engine-level foreign-key and CHECK-constraint tests included. | The first layer feeds plain dictionaries into the business functions — that is where the 70% coverage requirement is earned, because those functions import nothing. The second layer submits real forms through Flask's test client, then opens the database file directly to prove the rows actually landed. |
| 2026-10-05 / e709981 | Qwen Code | "Add the UI: Jinja2 templates for dashboard, spots, sessions, edit pages; keep it one static stylesheet, no build step." | Accepted, pending review | Generated `templates/` (base layout, shared macros, dashboard, spot list/detail/edit, session list/edit, 404) and `static/css/style.css`. Deletes are POST-only with confirm dialogs; no JavaScript is generated from user data. | Every page extends one base template, so the nav, flash messages, and styling are defined exactly once. A small macro file renders the rating stars and the "1h 30m" duration format, keeping every session table identical. The stylesheet is served by Flask itself — no npm, no bundler, nothing to build. |
| 2026-10-05 / 7467bb9 | Qwen Code | "Produce the process documents: ADR.md with exactly 5 entries, the AI_USAGE.md table, and README.md with env vars, run command, and the exact coverage command." | Accepted, pending review | Generated `ADR.md` (framework choice, domain seam, SQLite schema, testing strategy, deliberately omitted weather API), this log, and `README.md` including the required command `pytest --cov=domain_logic test_app.py`. | The ADR explains why, not what: each entry records the situation, the choice, and the trade-off. The most load-bearing one is the seam — Domain 1's code never mentions sessions, and the database's foreign key is what actually stops a spot from being deleted while sessions still reference it. |
| 2026-10-05 / 7ebf90c | Qwen Code | "Verify everything: create a venv, install requirements, run the coverage command, and boot the server on 0.0.0.0 to smoke-test the pages." | Accepted, pending review | Executed the full suite — 58 passed, `domain_logic` coverage 100%, up from 95% after adding gap-closing validation tests — and a live HTTP smoke test: pages 200, custom 404 on unknown routes, create-form 302 with the row persisted. | Verification is part of the deliverable: the exact command from the README was run in a clean virtual environment, and the server was actually started, bound to 0.0.0.0, and requested over HTTP before the work was called done. |

---

**Note on scope of assistance:** AI generated the initial drafts of the code,
tests, and documentation. Every fact above — coverage numbers, smoke-test
results, commit hashes — comes from commands actually executed against this
repository. Outstanding before submission: a human review of the generated
files, and a student-voice rewrite of the final column.
