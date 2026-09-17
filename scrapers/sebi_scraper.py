"""
scrapers/sebi_scraper.py
------------------------
SEBI publishes RSS feeds for Press Releases, Circulars and Orders
(directory: https://www.sebi.gov.in/rss.html). Using RSS avoids the
dynamic, JS-rendered listing pages on sebi.gov.in, which paginate via
client-side calls that are awkward (and fragile) to scrape directly.
"""

from __future__ import annotations

import logging
from typing import List

import feedparser

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.sebi")

SEBI_FEEDS = {
    # SEBI publishes a single combined RSS feed -- it already includes
    # Press Releases, Circulars, and Orders together, so there is no
    # separate "circulars-only" feed to point to. (An earlier version of
    # this scraper guessed at a second URL that turned out not to exist --
    # fixed here to the one real, confirmed feed.)
    "All Updates": "https://www.sebi.gov.in/sebirss.xml",
}


def scrape() -> List[FeedItem]:
    items: List[FeedItem] = []
    session = build_session()

    for category, feed_url in SEBI_FEEDS.items():
        try:
            resp = session.get(feed_url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("SEBI feed '%s' fetch failed: %s", category, exc)
            continue

        parsed = feedparser.parse(resp.content)
        if parsed.bozo:
            logger.warning("SEBI feed '%s' parsed with warnings: %s", category, parsed.bozo_exception)

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
                    source="SEBI",
                    title=title,
                    url=url,
                    type=item_type,
                    event_date=event_date,
                    published_at=published,
                    raw_snippet=summary[:280],
                )
            )

    logger.info("SEBI: parsed %d items", len(items))
    return items


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)