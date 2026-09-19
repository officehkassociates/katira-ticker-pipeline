"""
scrapers/cbdt_scraper.py
------------------------
CBDT (Central Board of Direct Taxes) notifications, circulars and press
releases are published via the Income Tax Department's own RSS feeds,
confirmed from its official "Subscribe to Tax Feeds" page
(incometaxindia.gov.in/tax-feeds). As with RBI/SEBI/MCA, RSS is used
here instead of scraping HTML, since it's the stable, sanctioned way to
pull this content.
"""

from __future__ import annotations

import logging
from typing import List

import feedparser

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.cbdt")

CBDT_FEEDS = {
    "Press Releases": "https://wmstatic-prd.incometaxindia.gov.in/press-release-rss-feed/-/asset_publisher/bxhj/rss",
    "Miscellaneous Communications": "https://wmstatic-prd.incometaxindia.gov.in/miscellaneous-communications-rss-feed/-/asset_publisher/bxhj/rss",
}


def scrape() -> List[FeedItem]:
    items: List[FeedItem] = []
    session = build_session()

    for category, feed_url in CBDT_FEEDS.items():
        try:
            resp = session.get(feed_url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("CBDT feed '%s' fetch failed: %s", category, exc)
            continue

        parsed = feedparser.parse(resp.content)
        if parsed.bozo:
            logger.warning("CBDT feed '%s' parsed with warnings: %s", category, parsed.bozo_exception)

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
                    source="CBDT",
                    title=title,
                    url=url,
                    type=item_type,
                    event_date=event_date,
                    published_at=published,
                    raw_snippet=summary[:280],
                )
            )

    logger.info("CBDT: parsed %d items", len(items))
    return items


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)
