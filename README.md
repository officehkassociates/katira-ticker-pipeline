# Regulatory Ticker Pipeline -- Katira & Associates

An automated pipeline that scrapes MCA, SEBI, RBI, BSE and NSE every
morning and powers two scrolling tickers on the website:

1. **Latest Regulatory News & Circulars**
2. **Important Financial & Compliance Dates**

---

## 1. Architecture Overview

```
 GitHub Actions   06:00 IST cron   Python scrapers (main.py)
        |                                    |
        |                                    v  writes
        |                            SQLite DB (regulatory_feed.db)
        |                                    |
        |                                    v  reads
        |                            Express API (api/server.js)
        |                                    |
        |                                    v  fetch()
        |                            Ticker widget (HTML/CSS/JS) on your site
```

**Why this stack:**

| Layer | Choice | Reason |
|---|---|---|
| Scraping | Python (`requests`, `feedparser`, `BeautifulSoup`, `Playwright`) | Best library ecosystem for both RSS parsing and, where unavoidable, headless-browser scraping. |
| Storage | SQLite | Zero infrastructure -- a single file, committed alongside the code. Upgrade to Postgres (Supabase/Neon free tiers) only once you need concurrent writers or >~100k rows. |
| API | Node.js + Express + `better-sqlite3` | Thin read layer between the DB and the browser. Swappable for a single Firebase Cloud Function / Vercel serverless function with no change to the SQL. |
| Frontend | Vanilla HTML/CSS/JS | No framework needed for a ticker widget -- a 10-second copy-paste into any page, including a plain static site like katira-website. |
| Scheduling | GitHub Actions cron | Free for public/private repos within generous limits, no server to maintain, logs and failure alerts built in. |

### Handling anti-scraping measures

This is the part that determines whether the pipeline survives contact
with these five portals, so the strategy is deliberately different per
source rather than one generic scraper for everything:

- **RBI, SEBI, MCA** all publish **official RSS feeds**
  (`rbi.org.in/Scripts/rss.aspx`, `sebi.gov.in/rss.html`,
  `mca.gov.in/.../rss-feeds.html`). RSS is the right tool here, not HTML
  scraping: it's stable across site redesigns, doesn't render via
  JavaScript, and isn't behind the CAPTCHA some RBI HTML pages show. The
  scrapers use these feeds as the primary path.

- **MCA fallback:** if the RSS feed is ever down, MCA's HTML homepage is
  an Angular SPA that returns almost no content to a plain `requests.get()`
  -- BeautifulSoup alone cannot see anything that renders client-side.
  `mca_scraper.py` falls back to **Playwright** (headless Chromium),
  which executes the JS so you can query the *rendered* DOM.

- **NSE and BSE** don't publish RSS for corporate actions, but their own
  websites call internal JSON APIs to render those pages. We call the
  same JSON endpoints directly:
  - **NSE** requires a session cookie obtained from a normal page load
    first (`build_session(warm_up_url=...)` in `common.py`) -- calling
    the JSON API cold returns 401. This is the most common reason an
    NSE scraper "randomly" stops working: NSE periodically rotates its
    bot-detection. The documented fallback in `nse_scraper.py` is to
    move the whole request through Playwright (a real browser
    fingerprint) if the plain-session approach starts failing.
  - **BSE**'s equivalent API is generally reachable with just
    browser-style headers, no cookie dance required.

- **General resilience rules applied everywhere:**
  - A realistic desktop `User-Agent` (the default `requests` UA is
    blocked outright by several of these portals).
  - Retries with exponential backoff (`tenacity`) for transient 5xx/
    timeout errors -- these portals do rate-limit and occasionally blip.
  - One request per portal per run, at 6 AM (low-traffic time) -- this
    is a daily-digest ticker, not real-time trading data, so there is no
    reason to poll aggressively and risk an IP ban.
  - Each source scraper is wrapped so **one portal failing never blocks
    the other four** (`main.py` catches per-source exceptions).

**What this pipeline deliberately does NOT do:** solve CAPTCHAs
programmatically, spoof/rotate residential IPs to evade a hard block, or
bypass paid data terminals (e.g. the roughly Rs. 3 lakh/year BSE/NSE bulk
announcement feeds that data vendors sell). If a portal hard-blocks the
approach above, the correct fix is a licensed data vendor for that one
feed, not more aggressive scraping.

---

## 2. Project Structure

```
pipeline/
  main.py                    - orchestrator, run this daily
  requirements.txt
  db/
    schema.sql               - SQLite schema
    regulatory_feed.db       - created on first run
  scrapers/
    common.py                - session, dedup, date extraction, DB writes
    rbi_scraper.py
    sebi_scraper.py
    mca_scraper.py
    bse_scraper.py
    nse_scraper.py
  api/
    server.js                - Express API -> /api/news, /api/dates
    package.json
  frontend/
    ticker.html               - drop-in demo page
    ticker.css
    ticker.js
  .github/workflows/
    daily-scrape.yml          - 6:00 AM IST cron
```

---

## 3. Database Schema

See `db/schema.sql`. Summary:

```sql
CREATE TABLE items (
    id            TEXT PRIMARY KEY,   -- sha256(source|url), first 32 chars -- dedup key
    source        TEXT NOT NULL,      -- MCA | SEBI | RBI | BSE | NSE
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    type          TEXT NOT NULL,      -- 'news' | 'date'
    event_date    TEXT,               -- YYYY-MM-DD, only when type='date'
    published_at  TEXT,               -- source's own publish date
    fetched_at    TEXT NOT NULL,      -- when our scraper stored it
    raw_snippet   TEXT
);
```

**Dedup mechanism:** `id` is a deterministic hash of `(source, url)`.
Every insert uses `INSERT OR IGNORE`, so re-running the scraper (or the
cron job firing twice) never creates duplicate rows -- SQLite silently
skips any `id` already present.

**News vs. Dates classification:** `scrapers/common.py:classify()` only
labels an item `type='date'` when the text contains BOTH a deadline
keyword ("last date", "due date", "record date", "w.e.f.", "extended
till", etc.) AND `dateparser` successfully extracts a concrete calendar
date from the surrounding text. This two-factor check stops a routine
announcement that merely mentions a month name from polluting the dates
ticker. For BSE/NSE, corporate actions already carry a structured date
field from the source itself, so those are classified directly without
the keyword/regex step.

---

## 4. Verify the scrapers actually work, before you automate anything

Run this locally (on a machine with normal internet access) before wiring
up the cron job or deploying the API. This confirms each of the five
portals is reachable and returning parseable data *today*, since RSS
paths and JSON API shapes on government/exchange sites do drift over
time.

```bash
cd pipeline
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Test one source at a time first -- easier to spot which portal (if any)
# needs a fix than reading five scrapers' output interleaved.
python main.py --sources RBI
python main.py --sources SEBI
python main.py --sources MCA
python main.py --sources BSE
python main.py --sources NSE
```

**What to look for in the output:**
- A line like `RBI: OK (12 items, 1.3s)` -- means it worked.
- `RBI: FAILED -- <error>` -- means that portal needs attention. The
  error message tells you which layer broke:
  - `HTTPError 404` on an RSS scraper -> the feed URL moved; check the
    portal's RSS directory page (linked in that scraper's docstring)
    and update the one URL in the `_FEEDS` dict.
  - `403` / `401` on NSE -> NSE's bot detection rotated; see the
    `NSE_BLOCKED_NOTE` in `nse_scraper.py` for the Playwright fallback.
  - `ModuleNotFoundError: playwright` -> run
    `python -m playwright install chromium` (only needed for the MCA
    fallback path, so this only matters if MCA's RSS feed is down).

Once all five run clean individually, run the full combined job once:

```bash
python main.py
```

Then inspect what actually landed in the database:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('db/regulatory_feed.db')
for row in conn.execute('SELECT source, type, title, event_date FROM items ORDER BY fetched_at DESC LIMIT 20'):
    print(row)
"
```

Confirm the `type` classification looks right (a few genuine deadlines
tagged `date`, general announcements tagged `news`) before you trust it
to run unattended every morning. Only once this looks correct should you
push the repo and let `.github/workflows/daily-scrape.yml` take over.

---

## 5. Deploying the API

Two ready-to-use configs are included so you don't have to hand-write
either platform's setup:

### Option A -- Render (`render.yaml`, included)
1. Push this repo to GitHub.
2. In Render: **New -> Blueprint**, point it at the repo. Render reads
   `render.yaml` automatically and provisions the Node service from `api/`.
3. Render gives you a URL like `https://katira-ticker-api.onrender.com`.
   Optionally map a custom domain (e.g. `api.katira.co.in`) to it under
   **Custom Domains** in Render's dashboard.
4. Free-tier note: the service sleeps after ~15 minutes idle and takes a
   few seconds to wake on the next request -- fine for a once-daily feed,
   but the very first visitor after a quiet night may see a brief load.

### Option B -- Railway (`Procfile`, included)
1. Push this repo to GitHub.
2. In Railway: **New Project -> Deploy from GitHub repo**.
3. Set **Root Directory** to `api` in the service's settings (important --
   `package.json` lives in `api/`, not the repo root).
4. Generate a public domain under **Settings -> Networking**.

Whichever you pick, the very last step is the same: take that live URL
and put it into your website's ticker config:

```html
<script>window.TICKER_API_BASE = "https://<your-actual-api-url>";</script>
```

---

## 6. Running It (local dev reference)


### Local setup

```bash
cd pipeline
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the MCA fallback path

python main.py                      # scrapes all 5 sources
python main.py --sources RBI,SEBI   # debug a subset

cd api && npm install && npm start  # serves http://localhost:4000/api/news etc.
```

Then open `frontend/ticker.html` in a browser, or embed the two
`.ticker-block` divs from that file into your existing site, along with
`ticker.css`/`ticker.js`. Set `window.TICKER_API_BASE` before loading
`ticker.js` if the API isn't on `localhost:4000`:

```html
<script>window.TICKER_API_BASE = "https://api.katira.co.in";</script>
<script src="ticker.js"></script>
```

### Automating it: GitHub Actions (recommended starting point)

`.github/workflows/daily-scrape.yml` runs `python main.py` every day at
**00:30 UTC = 6:00 AM IST**, then commits the refreshed
`regulatory_feed.db` back into the repo. This is the simplest possible
"serverless cron" -- no AWS account needed. Push this repo to GitHub and
it runs automatically.

**Where to host the pieces long-term:**
- API (`api/server.js`): any small Node host (Render, Railway, a small
  VPS), or rewrite the 3 queries as a single Firebase Cloud Function.
- Frontend ticker: it's static HTML/CSS/JS -- it already lives happily
  inside your existing `katira-website` static site.

### Alternative: AWS Lambda

Package `main.py` (+ dependencies, via a Lambda layer or container image,
since Playwright needs Chromium binaries) as a Lambda function and
trigger it with an EventBridge schedule:

```
cron(30 0 * * ? *)     -- 00:30 UTC = 06:00 IST
```

Lambda's execution-time and layer-size limits are why GitHub Actions is
the easier starting point; Lambda is worth the extra setup once you need
tighter AWS integration (e.g. writing to DynamoDB/RDS instead of SQLite).

---

## 5. Extending / maintaining

- **A feed URL 404s:** RSS feed slugs (especially SEBI's) change during
  site redesigns. Check the portal's own RSS directory page (linked in
  each scraper's docstring) and update the one dict entry -- no other
  code needs to change.
- **NSE/BSE JSON endpoint changes shape:** these are undocumented,
  internal APIs, so a field name changing is the most likely future
  break. Field-name assumptions are isolated in one function per
  scraper, so a fix is a small, localized diff.
- **Adding more sources later** (IRDAI, PFRDA, other exchange circulars):
  add a new `scrapers/<name>.py` exposing a `scrape() -> List[FeedItem]`
  function, then add one line to the `SCRAPERS` dict in `main.py`.
  Nothing else needs to change, since `FeedItem`/`classify()`/
  `upsert_items()` all live in `common.py`.
