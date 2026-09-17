"""
scrapers/rbi_scraper.py
-----------------------
RBI publishes an official RSS feed of Press Releases / Notifications, so
we use that directly instead of scraping HTML -- it's stable, legal, and
doesn't trigger RBI's CAPTCHA-protected pages (see m.rbi.org.in, which
throws a "prove you are human" challenge on some routes).

Feed directory: https://rbi.org.in/Scripts/rss.aspx
We use the "Press Releases" and "Notifications" feeds.
"""

from __future__ import annotations

import logging
from typing import List

import feedparser

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.rbi")

RBI_FEEDS = {
    # RBI's RSS directory groups feeds by category; these two cover the
    # content the ticker cares about. If RBI changes these paths, check
    # https://rbi.org.in/Scripts/rss.aspx for the current list.
    "Press Releases": "https://www.rbi.org.in/pressreleases_rss.xml",
    "Notifications": "https://www.rbi.org.in/notifications_rss.xml",
}


def scrape() -> List[FeedItem]:
    items: List[FeedItem] = []
    # A plain session is enough for the RSS endpoint (no JS/anti-bot on feeds),
    # but we still use build_session() for a consistent, polite User-Agent.
    session = build_session()

    for category, feed_url in RBI_FEEDS.items():
        try:
            resp = session.get(feed_url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("RBI feed '%s' fetch failed: %s", category, exc)
            continue

        parsed = feedparser.parse(resp.content)
        if parsed.bozo:
            logger.warning("RBI feed '%s' parsed with warnings: %s", category, parsed.bozo_exception)

        for entry in parsed.entries:
            title = clean_text(entry.get("title", ""))
            url = entry.get("link", "")
            summary = clean_text(entry.get("summary", ""))
            published = entry.get("published", "") or entry.get("updated", "")
            if not title or not url:
                continue

            item_type, event_date = classify(title, summary)
            items.append(
                FeedItem(
                    source="RBI",
                    title=title,
                    url=url,
                    type=item_type,
                    event_date=event_date,
                    published_at=published,
                    raw_snippet=summary[:280],
                )
            )

    logger.info("RBI: parsed %d items", len(items))
    return items


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)
