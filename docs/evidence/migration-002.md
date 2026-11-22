# Migration 002 — evidence

**Migration:** `services/sessions/migrations/002_sessions_updated_at.sql`
**What it changes:** adds `updated_at` to the `sessions` table, which already holds
data. The column is added as NULL, every existing row is backfilled from
`created_at`, then the column is made NOT NULL with a default. Session edits set it
(`UPDATE ... updated_at = SYSUTCDATETIME()` in `services/sessions/app.py`).

**Where it ran:** SQL Server 2022 (Developer, `mcr.microsoft.com/mssql/server:2022-latest`)
from `docker-compose.yml`, in a separate compose project so no other local data was
touched. Run on 2026-11-22.

**How:**
1. Boot the stack with only `001_init.sql` present, so the service creates the table
   and seeds six sessions.
2. Add `002_sessions_updated_at.sql`, rebuild the sessions image and restart it. The
   runner applies 002 at boot.
3. Edit session 1 through the API and check that `updated_at` moves and
   `created_at` does not.
4. Restart again and check that nothing is applied twice.

**Result:**
* Six rows before, six rows after. No row lost, no existing value changed.
* All six rows backfilled: `updated_at = created_at` for every row.
* `updated_at` is NOT NULL with the default `df_sessions_updated`.
* An edit through the API moved `updated_at` from 17:25:55 to 17:26:11 and left
  `created_at` alone.
* The third boot logged `migrations: nothing to apply`.

The same behaviour is pinned by `services/sessions/tests/test_migrations.py` in CI.

## Raw output

The log below is the script's output, unedited. It holds no credentials.

```text
=== step 1: boot with migration 001 only (2026-11-22T17:25:21Z)
--- sessions service log (boot 1)
sessions-1  | 2026-11-22 17:25:55,628 INFO db migration applied: 001_init.sql
sessions-1  | 2026-11-22 17:25:55,687 INFO sessions seeded 6 sessions
--- schema_migrations
version|applied_at
-------|----------
001_init.sql|2026-11-22 17:25:55.6234380

(1 rows affected)
--- sessions columns
name
----
id
spot_id
session_date
duration_mins
wave_or_wind_rating
gear_used
notes
created_at

(8 rows affected)
--- rows before 002
id|spot_id|session_date|duration_mins|created_at
--|-------|------------|-------------|----------
1|1|2026-09-14|75|2026-11-22 17:25:55.6756342
2|1|2026-09-28|45|2026-11-22 17:25:55.6800332
3|3|2026-10-02|120|2026-11-22 17:25:55.6800332
4|3|2026-10-03|90|2026-11-22 17:25:55.6800332
5|4|2026-10-05|60|2026-11-22 17:25:55.6800332
6|2|2026-10-06|30|2026-11-22 17:25:55.6843192

(6 rows affected)
=== step 2: add 002, rebuild and restart sessions (2026-11-22T17:26:01Z)
--- sessions service log (boot 2)
sessions-1  | 2026-11-22 17:26:06,199 INFO db migration applied: 002_sessions_updated_at.sql
--- schema_migrations
version|applied_at
-------|----------
001_init.sql|2026-11-22 17:25:55.6234380
002_sessions_updated_at.sql|2026-11-22 17:26:06.1965407

(2 rows affected)
--- rows after 002 (count and backfill check)
rows_total|backfilled_from_created_at
----------|--------------------------
6|6

(1 rows affected)
id|spot_id|session_date|duration_mins|created_at|updated_at
--|-------|------------|-------------|----------|----------
1|1|2026-09-14|75|2026-11-22 17:25:55.6756342|2026-11-22 17:25:55.6756342
2|1|2026-09-28|45|2026-11-22 17:25:55.6800332|2026-11-22 17:25:55.6800332
3|3|2026-10-02|120|2026-11-22 17:25:55.6800332|2026-11-22 17:25:55.6800332
4|3|2026-10-03|90|2026-11-22 17:25:55.6800332|2026-11-22 17:25:55.6800332
5|4|2026-10-05|60|2026-11-22 17:25:55.6800332|2026-11-22 17:25:55.6800332
6|2|2026-10-06|30|2026-11-22 17:25:55.6843192|2026-11-22 17:25:55.6843192

(6 rows affected)
--- column is now NOT NULL with a default
name|is_nullable|default_name
----|-----------|------------
updated_at|0|df_sessions_updated

(1 rows affected)
=== step 3: edit session 1 through the API (2026-11-22T17:26:11Z)
{"date":"2026-11-01","duration_mins":75,"gear_used":"Shortboard 6ft6","id":1,"notes":"evidence edit","spot_id":1,"spot_name":"Ocean Beach North","wave_or_wind_rating":4}

id|duration_mins|created_at|updated_at
--|-------------|----------|----------
1|75|2026-11-22 17:25:55.6756342|2026-11-22 17:26:11.7963262

(1 rows affected)
=== step 4: third boot applies nothing
sessions-1  | 2026-11-22 17:26:06,199 INFO db migration applied: 002_sessions_updated_at.sql
sessions-1  | 2026-11-22 17:26:13,621 INFO db migrations: nothing to apply
=== done (2026-11-22T17:26:18Z)
```
