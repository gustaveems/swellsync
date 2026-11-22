-- 002: record when each session was last changed.
-- Forward-only and data-preserving (ADR-007). The column is added as NULL,
-- every existing row is backfilled from created_at, and only then is the
-- column made NOT NULL. No row is deleted and no existing value changes.
ALTER TABLE sessions ADD updated_at DATETIME2 NULL;
GO
UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL;
GO
ALTER TABLE sessions ALTER COLUMN updated_at DATETIME2 NOT NULL;
GO
ALTER TABLE sessions ADD CONSTRAINT df_sessions_updated DEFAULT SYSUTCDATETIME() FOR updated_at;
