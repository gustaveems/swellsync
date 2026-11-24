"""Create, or update, the contained database user for each service.

Each service reaches only its own database, as its own user. Before this script
the users were created by hand with the SQL in the README. Running it again is
safe: an existing user keeps its roles and gets the password from the
environment, so it is also how a password is rotated.

Passwords come from the environment, never from the command line, so they stay
out of the shell history:

    export SQL_ADMIN_PASSWORD=... SPOTS_DB_PASSWORD=... SESSIONS_DB_PASSWORD=...
    python scripts/azure/create_sql_users.py \\
        --server gamsoulas-ieu2024-sql2.database.windows.net --admin swellsyncadmin

The server firewall must let this machine in while it runs (README, step 5).
After a rotation, update the `db-url` secret of the matching Container App.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import pymssql

# service -> (database user, environment variable holding its password)
SERVICES = {
    "spots": ("spots_app", "SPOTS_DB_PASSWORD"),
    "sessions": ("sessions_app", "SESSIONS_DB_PASSWORD"),
}
# Enough to run the migrations at boot and to read and write rows, nothing more.
ROLES = ("db_ddladmin", "db_datareader", "db_datawriter")
# Identifiers cannot be query parameters, so they are checked instead.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def statements(user: str) -> list[str]:
    """The T-SQL run in one service database. %s is the password, quoted by pymssql."""
    if not _NAME_RE.match(user):
        raise ValueError(f"unexpected user name: {user!r}")
    create = (
        f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '{user}')"
        f" CREATE USER [{user}] WITH PASSWORD = %s"
        f" ELSE ALTER USER [{user}] WITH PASSWORD = %s"
    )
    return [create] + [f"ALTER ROLE {role} ADD MEMBER [{user}]" for role in ROLES]


def apply(server: str, admin: str, admin_password: str, database: str, user: str, password: str):
    if not _NAME_RE.match(database):
        raise ValueError(f"unexpected database name: {database!r}")
    conn = pymssql.connect(server=server, user=admin, password=admin_password,
                           database=database, login_timeout=30, autocommit=True)
    try:
        cur = conn.cursor()
        create, *grants = statements(user)
        cur.execute(create, (password, password))
        for grant in grants:
            cur.execute(grant)
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", required=True, help="SQL server host name")
    parser.add_argument("--admin", required=True, help="SQL admin login")
    parser.add_argument("--prefix", default="gamsoulas-ieu2024",
                        help="database names are <prefix>-<service>-db")
    parser.add_argument("--only", choices=sorted(SERVICES), help="one service instead of both")
    args = parser.parse_args(argv)

    needed = ["SQL_ADMIN_PASSWORD"] + [env for _, env in SERVICES.values()]
    if args.only:
        needed = ["SQL_ADMIN_PASSWORD", SERVICES[args.only][1]]
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        print("missing environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2

    for service, (user, env) in SERVICES.items():
        if args.only and service != args.only:
            continue
        database = f"{args.prefix}-{service}-db"
        apply(args.server, args.admin, os.environ["SQL_ADMIN_PASSWORD"],
              database, user, os.environ[env])
        print(f"{database}: user {user} ready with roles {', '.join(ROLES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
