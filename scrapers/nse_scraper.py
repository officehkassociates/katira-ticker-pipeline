"""
scrapers/nse_scraper.py
-----------------------
NSE has no public RSS, but nseindia.com's own front-end calls internal
JSON APIs (the same ones powering the "Corporate Actions" / "Corporate
Announcements" pages). These reject requests with no session cookies or
a non-browser User-Agent, so we:

  1. GET the NSE homepage first ("warm-up") purely to receive the cookies
     NSE's WAF issues on a normal page load.
  2. Reuse that same session (with cookies) to call the JSON endpoint.

This is NSE's own public data, just not exposed as a documented API --
treat it gently: one request per run, no parallel hammering, and back
off completely if NSE starts returning 403s (see NSE_BLOCKED_NOTE below).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.nse")

NSE_HOME = "https://www.nseindia.com/"
NSE_CORP_ACTIONS_API = "https://www.nseindia.com/api/corporates-corporateActions"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements"

NSE_BLOCKED_NOTE = (
    "NSE periodically hardens its bot-detection (rotating cookie names, "
    "TLS fingerprinting, etc). If this scraper starts returning 401/403 "
    "consistently, the practical fix is to swap this function's transport "
    "for a headless-browser session (Playwright) that hits nseindia.com "
    "with a real browser fingerprint, then reads the same JSON endpoints "
    "via page.evaluate(fetch(...)) from inside that authenticated page."
)


def _session_for_nse():
    session = build_session(warm_up_url=NSE_HOME)
    # NSE's API additionally expects these to look like an XHR from its
    # own front-end -- harmless to send, and it materially improves the
    # success rate versus a bare GET.
    session.headers.update({
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
        "X-Requested-With": "XMLHttpRequest",
    })
    return session


def scrape(days_ahead: int = 30) -> List[FeedItem]:
    items: List[FeedItem] = []
    session = _session_for_nse()

    from_date = date.today().strftime("%d-%m-%Y")
    to_date = (date.today() + timedelta(days=days_ahead)).strftime("%d-%m-%Y")

    # --- Forthcoming corporate actions (dividends, AGMs, book closures, etc.) ---
    try:
        resp = session.get(
            NSE_CORP_ACTIONS_API,
            params={"index": "equities", "from_date": from_date, "to_date": to_date},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()

        for row in payload:
            symbol = row.get("symbol", "")
            company = row.get("comp", "") or symbol
            purpose = clean_text(row.get("subject", "") or row.get("purpose", ""))
            ex_date = row.get("exDate") or row.get("recDate")  # already DD-MMM-YYYY
            title = f"{company}: {purpose}" if purpose else f"{company}: Corporate Action"

            # These rows already carry a structured date from NSE itself,
            # so we don't need classify()/regex date-mining here -- we
            # trust the source field directly and label it type='date'.
            event_date_iso = _normalise_nse_date(ex_date)

            items.append(
                FeedItem(
                    source="NSE",
                    title=clean_text(title),
                    url="https://www.nseindia.com/companies-listing/corporate-filings-actions",
                    type="date" if event_date_iso else "news",
                    event_date=event_date_iso,
                    published_at=None,
                    raw_snippet=purpose[:280],
                )
            )
    except Exception as exc:
        logger.warning("NSE corporate actions fetch failed: %s. %s", exc, NSE_BLOCKED_NOTE)

    # --- Latest corporate announcements (general news-style items) ---
    try:
        resp = session.get(
            NSE_ANNOUNCEMENTS_API,
            params={"index": "equities"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()

        for row in payload[:40]:  # cap: only need "latest" for a news ticker
            company = row.get("sm_name", "") or row.get("symbol", "")
            desc = clean_text(row.get("desc", "") or row.get("attchmntText", ""))
            title = f"{company}: {desc}" if desc else company
            attachment = row.get("attchmntFile", "")
            an_dt = row.get("an_dt")  # e.g. "08-Jul-2026 18:32:11"

            item_type, event_date = classify(title, desc)
            items.append(
                FeedItem(
                    source="NSE",
                    title=title[:300],
                    url=attachment or "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                    type=item_type,
                    event_date=event_date,
                    published_at=an_dt,
                    raw_snippet=desc[:280],
                )
            )
    except Exception as exc:
        logger.warning("NSE announcements fetch failed: %s. %s", exc, NSE_BLOCKED_NOTE)

    logger.info("NSE: parsed %d items", len(items))
    return items


def _normalise_nse_date(raw: str | None) -> str | None:
    """NSE dates typically look like '30-Sep-2026' -> convert to ISO."""
    if not raw:
        return None
    from datetime import datetime
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)
