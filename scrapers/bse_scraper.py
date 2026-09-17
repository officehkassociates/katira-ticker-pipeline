"""
scrapers/bse_scraper.py
-----------------------
BSE's own site (bseindia.com) calls internal JSON endpoints for its
"Corporate Announcements" and "Forthcoming Corporate Actions" pages.
Unlike NSE, BSE's API is generally reachable with a plain requests
session + browser-style headers (no mandatory cookie warm-up), but we
still route through build_session() for a consistent User-Agent and
retry behaviour.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.bse")

BSE_ANNOUNCEMENTS_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
BSE_CORP_ACTIONS_API = "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w"


def scrape(days_back: int = 7, days_ahead: int = 30) -> List[FeedItem]:
    items: List[FeedItem] = []
    session = build_session()
    session.headers.update({
        "Referer": "https://www.bseindia.com/corporates/ann.html",
        "Origin": "https://www.bseindia.com",
    })

    today = date.today()

    # --- Latest corporate announcements (news-style items) ---
    # Announcements are things that ALREADY happened, so this needs to look
    # BACKWARD (past N days -> today), unlike corporate actions below which
    # look forward. An earlier version of this scraper used the same
    # forward-looking date range for both, which meant this query was
    # asking for announcements in the future -- BSE correctly returned
    # "No Record Found!" (a plain string, not a JSON object) for that.
    ann_from = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    ann_to = today.strftime("%Y%m%d")
    try:
        resp = session.get(
            BSE_ANNOUNCEMENTS_API,
            params={
                "pageno": 1,
                "strCat": -1,
                "strPrevDate": ann_from,
                "strScrip": "",
                "strSearch": "P",
                "strToDate": ann_to,
                "strType": "C",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()

        # BSE returns a plain string ("No Record Found!") when there's
        # nothing matching, and (per its docs/observed behaviour) a dict
        # with a "Table" key when there is data -- handle both rather than
        # assuming payload is always a dict.
        if isinstance(payload, dict):
            rows = payload.get("Table", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []  # e.g. the "No Record Found!" string case
            logger.info("BSE announcements: no records for %s-%s", ann_from, ann_to)

        for row in rows[:40]:
            company = row.get("SLONGNAME", "") or row.get("SCRIP_CD", "")
            headline = clean_text(row.get("NEWSSUB", "") or row.get("HEADLINE", ""))
            title = f"{company}: {headline}" if headline else company
            pdf_link = row.get("ATTACHMENTNAME", "")
            url = (
                f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf_link}"
                if pdf_link else "https://www.bseindia.com/corporates/ann.html"
            )
            news_dt = row.get("News_submission_dt") or row.get("DissemDT")

            item_type, event_date = classify(title, headline)
            items.append(
                FeedItem(
                    source="BSE",
                    title=title[:300],
                    url=url,
                    type=item_type,
                    event_date=event_date,
                    published_at=news_dt,
                    raw_snippet=headline[:280],
                )
            )
    except Exception as exc:
        logger.warning("BSE announcements fetch failed: %s", exc)

    # --- Forthcoming corporate actions (AGM/EGM/dividend/book-closure dates) ---
    act_from = today.strftime("%Y%m%d")
    act_to = (today + timedelta(days=days_ahead)).strftime("%Y%m%d")
    try:
        resp = session.get(
            BSE_CORP_ACTIONS_API,
            params={
                "Fdate": act_from,
                "Todate": act_to,
                "Purposecode": "",
                "ddlcategory": "",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()

        # Confirmed from a live response: this endpoint returns a plain
        # JSON list directly (each item already a row dict) -- NOT wrapped
        # in {"Table": [...]}. Field names confirmed from a real sample:
        # scrip_code, short_name, long_name, Ex_date ("13 Jul 2026"),
        # exdate ("20260713"), Purpose, RD_Date, payment_date.
        rows = payload if isinstance(payload, list) else payload.get("Table", [])

        for row in rows:
            company = row.get("short_name", "") or row.get("long_name", "")
            purpose = clean_text(row.get("Purpose", ""))
            # Prefer the compact "exdate" (YYYYMMDD) field -- unambiguous
            # to parse -- and fall back to the human-readable "Ex_date"
            # ("13 Jul 2026" style) if it's ever missing.
            ex_date_raw = row.get("exdate") or row.get("Ex_date")
            title = f"{company}: {purpose}" if purpose else f"{company}: Corporate Action"

            event_date_iso = _normalise_bse_date(ex_date_raw)
            items.append(
                FeedItem(
                    source="BSE",
                    title=clean_text(title),
                    url="https://www.bseindia.com/corporates/corporate_act.aspx",
                    type="date" if event_date_iso else "news",
                    event_date=event_date_iso,
                    published_at=None,
                    raw_snippet=purpose[:280],
                )
            )
    except Exception as exc:
        logger.warning("BSE corporate actions fetch failed: %s", exc)

    logger.info("BSE: parsed %d items", len(items))
    return items


def _normalise_bse_date(raw: str | None) -> str | None:
    """BSE dates arrive in a couple of confirmed formats: '20260713'
    (the compact 'exdate' field) or '13 Jul 2026' (the 'Ex_date' field).
    A couple of other formats are kept as a defensive fallback in case a
    different BSE endpoint ever supplies a differently-shaped date.
    """
    if not raw:
        return None
    from datetime import datetime
    raw = str(raw).strip()
    for fmt in ("%Y%m%d", "%d %b %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)