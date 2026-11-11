-- 001: Session Tracker schema. Owned by the sessions service only.
-- spot_id is a plain reference to spots.id in the spots service's database.
-- There is no foreign key across the seam; the sessions service checks that a
-- spot exists over HTTP before it writes (see ADR-6 in ADR.md).
CREATE TABLE sessions (
    id                   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    spot_id              INT           NOT NULL,
    session_date         DATE          NOT NULL,
    duration_mins        INT           NOT NULL CONSTRAINT ck_sessions_duration CHECK (duration_mins > 0),
    wave_or_wind_rating  INT           NULL CONSTRAINT ck_sessions_rating CHECK (wave_or_wind_rating BETWEEN 1 AND 5),
    gear_used            NVARCHAR(120) NULL,
    notes                NVARCHAR(2000) NULL,
    created_at           DATETIME2     NOT NULL CONSTRAINT df_sessions_created DEFAULT SYSUTCDATETIME()
);
GO
CREATE INDEX idx_sessions_spot_id ON sessions (spot_id);
GO
CREATE INDEX idx_sessions_date ON sessions (session_date);
