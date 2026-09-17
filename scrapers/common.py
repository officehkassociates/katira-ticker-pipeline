"""
scrapers/common.py
-------------------
Shared utilities used by every source-specific scraper:

  * a requests.Session with browser-like headers + automatic retries
    (needed because MCA/NSE/BSE actively reject default python-requests
    user agents)
  * make_id()          -> deterministic dedup key
  * extract_event_date() -> pulls a real-world date out of free text like
                            "...last date for filing is 30th September 2026..."
  * classify()         -> decides whether an item belongs in the "news"
                            ticker or the "important dates" ticker
  * upsert_items()     -> writes a batch of items into SQLite, silently
                            skipping ones we've already stored (dedup)

Keeping this logic in one place means every scraper behaves consistently
and a bug fix (e.g. a better date regex) only has to happen once.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests
from dateparser.search import search_dates
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scrapers.common")

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "regulatory_feed.db"

# ----------------------------------------------------------------
# Browser-like session
# ----------------------------------------------------------------
# Several portals (MCA, NSE in particular) reject requests that don't
# look like they came from a real browser, and NSE specifically requires
# you to hit a "warm-up" page first to receive session cookies before
# its JSON API will respond. build_session() centralises that dance.

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}


def build_session(warm_up_url: Optional[str] = None) -> requests.Session:
    """Return a requests.Session pre-loaded with browser-like headers.

    If warm_up_url is given, we GET it first (ignoring the body) purely to
    collect the cookies the site sets on a normal page load -- this is
    required for NSE's JSON endpoints, which 401 if called cold.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if warm_up_url:
        try:
            session.get(warm_up_url, timeout=15)
        except requests.RequestException as exc:
            logger.warning("Warm-up request to %s failed: %s", warm_up_url, exc)
    return session


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def fetch(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with retries + exponential backoff. Raises after 3 failed attempts.

    Portals like RBI/MCA occasionally rate-limit or return transient 5xx
    errors -- retrying with backoff clears the vast majority of these
    without giving up on a whole day's run over one blip.
    """
    resp = session.get(url, timeout=25, **kwargs)
    resp.raise_for_status()
    return resp


# ----------------------------------------------------------------
# Dedup
# ----------------------------------------------------------------

def make_id(source: str, url: str, title: str = "") -> str:
    """Deterministic primary key: same (source, url, title) always -> same id.

    This is what makes re-running the scraper safe every morning --
    INSERT OR IGNORE on this id means a circular we've already stored
    is never duplicated, no matter how many times the cron job runs.

    IMPORTANT: title is included, not just (source, url). Some sources
    (BSE/NSE corporate actions in particular) don't provide a unique
    per-item URL -- every corporate action on a given day points at the
    same generic listing page. Hashing only (source, url) would then
    treat every distinct action that day as "the same item" and only
    keep the first one. Including the title (which does differ per
    company/action) fixes that without changing behaviour for sources
    that DO have unique URLs (RBI/SEBI/MCA RSS items).
    """
    raw = f"{source.strip().lower()}|{url.strip().lower()}|{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ----------------------------------------------------------------
# Date extraction & classification
# ----------------------------------------------------------------

# Phrases that strongly signal "this text contains an actionable deadline"
# rather than just a publish date or an incidental date reference.
DATE_SIGNAL_PATTERNS = re.compile(
    r"(last date|due date|on or before|with effect from|w\.e\.f\.?|"
    r"deadline|extended (?:up ?to|till|to)|record date|book closure|"
    r"ex-date|ex date|shall come into force|applicable from|"
    r"to be filed by|filing date|cut-?off date)",
    re.IGNORECASE,
)

# Settings passed to dateparser -- PREFER_DATES_FROM='future' means that
# an ambiguous "30 September" found in a circular published in July is
# resolved to the *next* occurrence of that date, which is what a
# "compliance deadline" reader wants; STRICT parsing skips lone years,
# lone "2026" style false positives, etc.
_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "STRICT_PARSING": False,
    "RETURN_AS_TIMEZONE_AWARE": False,
}


def extract_event_date(text: str) -> Optional[str]:
    """Search free text for a real calendar date and return it as YYYY-MM-DD.

    Returns None if no confident date is found. We deliberately require
    dateparser to find *something* AND (for classify() below) a deadline
    keyword to be present, which avoids false positives like a circular
    number that merely contains "2026".
    """
    if not text:
        return None
    try:
        found = search_dates(text, settings=_DATEPARSER_SETTINGS, languages=["en"])
    except Exception as exc:  # dateparser can throw on odd unicode input
        logger.debug("date search failed: %s", exc)
        return None
    if not found:
        return None
    # search_dates returns [(matched_text, datetime), ...]; take the first
    # confident hit -- circulars typically lead with the operative date.
    _, dt = found[0]
    return dt.strftime("%Y-%m-%d")


def classify(title: str, summary: str = "") -> tuple[str, Optional[str]]:
    """Decide ticker type ('news' vs 'date') and extract event_date if any.

    Logic: only classify as an "important date" item when BOTH
      (a) a deadline-signal phrase is present, and
      (b) dateparser can actually pull out a concrete date
    Otherwise it's regular "news" -- this two-factor check is what keeps
    routine announcements ("RBI releases Financial Stability Report") out
    of the dates ticker just because they mention a month name.
    """
    combined = f"{title}. {summary}"
    if DATE_SIGNAL_PATTERNS.search(combined):
        event_date = extract_event_date(combined)
        if event_date:
            return "date", event_date
    return "news", None


# ----------------------------------------------------------------
# Data model + storage
# ----------------------------------------------------------------

@dataclass
class FeedItem:
    source: str          # MCA / SEBI / RBI / BSE / NSE
    title: str
    url: str
    type: str             # 'news' | 'date'
    event_date: Optional[str]
    published_at: Optional[str]
    raw_snippet: str = ""

    def to_row(self) -> dict:
        row = asdict(self)
        row["id"] = make_id(self.source, self.url, self.title)
        row["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return row


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # safer for concurrent reads (API server)
    schema_path = DB_PATH.parent / "schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    return conn


def upsert_items(items: Iterable[FeedItem]) -> int:
    """Insert new items, silently skipping duplicates. Returns rows actually inserted."""
    conn = get_connection()
    inserted = 0
    with conn:
        for item in items:
            row = item.to_row()
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO items
                    (id, source, title, url, type, event_date, published_at, fetched_at, raw_snippet)
                VALUES
                    (:id, :source, :title, :url, :type, :event_date, :published_at, :fetched_at, :raw_snippet)
                """,
                row,
            )
            inserted += cur.rowcount
    conn.close()
    return inserted


def clean_text(text: str) -> str:
    """Collapse whitespace/newlines that RSS/HTML text often carries."""
    return re.sub(r"\s+", " ", text or "").strip()