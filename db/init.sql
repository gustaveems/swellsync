-- Local bootstrap: one database and one login per service. Idempotent; run once
-- per compose up by the db-init one-off service.
--
-- Passed in by sqlcmd -v: SPOTS_DB_PASSWORD, SESSIONS_DB_PASSWORD.
-- The login is server-level. Its user exists only in its own database, so it
-- cannot connect to the other service's database (guest access is disabled).
-- A password change for an existing login needs ALTER LOGIN; this script does not do it.

IF DB_ID(N'spots_db') IS NULL CREATE DATABASE spots_db;
IF DB_ID(N'sessions_db') IS NULL CREATE DATABASE sessions_db;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'spots_app')
    CREATE LOGIN spots_app WITH PASSWORD = N'$(SPOTS_DB_PASSWORD)', CHECK_POLICY = ON;
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'sessions_app')
    CREATE LOGIN sessions_app WITH PASSWORD = N'$(SESSIONS_DB_PASSWORD)', CHECK_POLICY = ON;
GO

USE spots_db;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'spots_app')
    CREATE USER spots_app FOR LOGIN spots_app;
IF ISNULL(IS_ROLEMEMBER(N'db_owner', N'spots_app'), 0) = 0
    ALTER ROLE db_owner ADD MEMBER spots_app;
GO

USE sessions_db;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'sessions_app')
    CREATE USER sessions_app FOR LOGIN sessions_app;
IF ISNULL(IS_ROLEMEMBER(N'db_owner', N'sessions_app'), 0) = 0
    ALTER ROLE db_owner ADD MEMBER sessions_app;
GO
