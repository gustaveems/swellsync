# Evidence: the boot lock and the SQL users script (ADR-007a)

Run on 2026-11-24 against SQL Server 2022 (`mcr.microsoft.com/mssql/server:2022-latest`)
in a throwaway container, from `python:3.12-slim` with `pymssql==2.3.13`. The
test server, its network and its data were deleted afterwards. Passwords below
were for that container only.

## 1. Two replicas booting at the same time

Two threads stand in for two replicas. Each opens its own connection with
`db.connect` and runs the real `db.migrate` from `services/sessions/db.py`
against an empty database. Each holds on for 3 seconds after migrating, so the
other one arrives while the first is still busy.

```text
=== without the lock
replica-A migration applied: 001_init.sql
replica-A migration applied: 002_sessions_updated_at.sql
replica-A -> (['001_init.sql', '002_sessions_updated_at.sql'], 3.2)
replica-B -> ('FAILED: (2714, b"There is already an object named \'schema_migrations\' in the database. ...', 0.1)
schema_migrations: ['001_init.sql', '002_sessions_updated_at.sql']

=== with the lock
21:34:36,706 replica-B boot lock taken
21:34:36,740 replica-B migration applied: 001_init.sql
21:34:36,758 replica-B migration applied: 002_sessions_updated_at.sql
21:34:39,790 replica-A boot lock taken
21:34:39,799 replica-A migrations: nothing to apply
replica-A -> ([], 6.1)
replica-B -> (['001_init.sql', '002_sessions_updated_at.sql'], 3.1)
schema_migrations: ['001_init.sql', '002_sessions_updated_at.sql']
```

Without the lock, the second replica crashed at boot. On Azure, that is a
container restart loop until the first one finishes. With the lock, replica A
waited about 3 seconds for B, then found nothing to apply. Neither crashed, and
each migration is recorded once.

## 2. `scripts/azure/create_sql_users.py`

Two partially contained databases with the deployed names were created, the
script was run, then run again with a new spots password. Each user then tried
to log in.

```text
--- first run
gamsoulas-ieu2024-spots-db: user spots_app ready with roles db_ddladmin, db_datareader, db_datawriter
gamsoulas-ieu2024-sessions-db: user sessions_app ready with roles db_ddladmin, db_datareader, db_datawriter
--- second run, spots password rotated
gamsoulas-ieu2024-spots-db: user spots_app ready with roles db_ddladmin, db_datareader, db_datawriter
gamsoulas-ieu2024-sessions-db: user sessions_app ready with roles db_ddladmin, db_datareader, db_datawriter

spots_app, old password, spots db:      REFUSED (18456)
spots_app, new password, spots db:      OK roles=['db_datareader', 'db_datawriter', 'db_ddladmin'] ddl=ok
spots_app, new password, sessions db:   REFUSED (18456)
sessions_app, sessions db:              OK roles=['db_datareader', 'db_datawriter', 'db_ddladmin'] ddl=ok
sessions_app, spots db:                 REFUSED (18456)
spots_app, master (no server login):    REFUSED (18456)
```

* The second run gave no error, so running the script again is safe.
* After the rotation the old password is refused and the new one works.
* Each user has exactly the three roles. It can create a table (migrations need
  that), cannot open the other service's database, and has no server login.

The script was not run against Azure. The live users were created by hand with
the same statements (README, step 5) and are unchanged.
