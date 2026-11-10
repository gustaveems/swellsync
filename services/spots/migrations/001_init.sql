-- 001: Spot Directory schema. Owned by the spots service only.
CREATE TABLE spots (
    id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    name            NVARCHAR(100)  NOT NULL,
    location        NVARCHAR(150)  NOT NULL,
    ideal_wind_dir  NVARCHAR(60)   NULL,
    ideal_swell_ft  FLOAT          NULL,
    created_at      DATETIME2      NOT NULL CONSTRAINT df_spots_created DEFAULT SYSUTCDATETIME()
);
GO
CREATE INDEX idx_spots_name ON spots (name);
