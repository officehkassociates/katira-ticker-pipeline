-- ============================================================
-- Katira & Associates -- Regulatory Ticker Data Store
-- SQLite schema (works unchanged on Postgres/MySQL with minor
-- type tweaks -- see notes at bottom of file).
-- ============================================================

CREATE TABLE IF NOT EXISTS items (
    -- Deterministic hash of (source + url) -- see scrapers/common.py:make_id()
    -- Used as the dedup key: re-running the scraper never creates duplicates.
    id            TEXT PRIMARY KEY,

    -- One of: MCA, SEBI, RBI, BSE, NSE
    source        TEXT NOT NULL,

    -- Headline / circular title, cleaned of extra whitespace
    title         TEXT NOT NULL,

    -- Canonical deep link back to the original portal page/PDF
    url           TEXT NOT NULL,

    -- 'news'  -> goes into the "Latest Regulatory News" ticker
    -- 'date'  -> goes into the "Important Financial & Compliance Dates" ticker
    type          TEXT NOT NULL CHECK (type IN ('news', 'date')),

    -- Only populated when type = 'date'. ISO-8601 (YYYY-MM-DD).
    -- This is the date *extracted from the text* (e.g. "last date for filing
    -- is 30th September 2026" -> 2026-09-30), NOT the publish date.
    event_date    TEXT,

    -- Publish date reported by the source itself (RSS pubDate, BSE/NSE
    -- announcement date, etc). ISO-8601. Used for sorting/"latest first".
    published_at  TEXT,

    -- When our scraper fetched/inserted this row (ISO-8601 UTC timestamp)
    fetched_at    TEXT NOT NULL,

    -- Short excerpt (RSS summary / announcement subject) kept for
    -- debugging the date-extraction logic and for optional tooltip text.
    raw_snippet   TEXT
);

-- Fast "give me latest 20 news items" / "give me upcoming dates" queries
CREATE INDEX IF NOT EXISTS idx_items_type_published
    ON items (type, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_items_event_date
    ON items (event_date);

CREATE INDEX IF NOT EXISTS idx_items_source
    ON items (source);

-- ============================================================
-- Notes for migrating to Postgres:
--   - TEXT -> keep as TEXT or use VARCHAR
--   - Add: fetched_at TIMESTAMPTZ, event_date DATE, published_at TIMESTAMPTZ
--   - CHECK constraint syntax is identical in Postgres
--   - For MySQL 8+: same schema works; use DATETIME instead of TIMESTAMPTZ
-- ============================================================
