"""
scrapers/mca_scraper.py
-----------------------
MCA publishes an RSS feed (see mca.gov.in/content/mca/global/en/
notifications-tender/rss-feeds.html) covering Press Releases, Notices &
Circulars. That's our primary path.

MCA's HTML "Latest Updates" page is a JavaScript-rendered Angular app,
so if the RSS feed is ever unavailable we fall back to Playwright
(headless Chromium) rather than requests/BeautifulSoup, since a plain
HTTP GET returns an near-empty shell with no news content.
"""

from __future__ import annotations

import logging
from typing import List

import feedparser

from .common import FeedItem, classify, clean_text, build_session

logger = logging.getLogger("scrapers.mca")

MCA_FEED_URL = "https://www.mca.gov.in/bin1/rss/mcarss.xml"
MCA_FALLBACK_URL = "https://www.mca.gov.in/content/mca/global/en/home.html"


def _scrape_via_rss() -> List[FeedItem]:
    items: List[FeedItem] = []
    session = build_session()
    resp = session.get(MCA_FEED_URL, timeout=20)
    resp.raise_for_status()

    parsed = feedparser.parse(resp.content)
    if parsed.bozo:
        logger.warning("MCA feed parsed with warnings: %s", parsed.bozo_exception)

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
                source="MCA",
                title=title,
                url=url,
                type=item_type,
                event_date=event_date,
                published_at=published,
                raw_snippet=summary[:280],
            )
        )
    return items


def _scrape_via_playwright() -> List[FeedItem]:
    """Fallback path: render the JS-heavy MCA homepage with headless Chromium
    and pull the "Latest Updates" ticker items out of the rendered DOM.

    Only invoked if the RSS feed is unreachable. Requires:
        pip install playwright && playwright install chromium
    """
    from playwright.sync_api import sync_playwright  # imported lazily -- optional dep

    items: List[FeedItem] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page.goto(MCA_FALLBACK_URL, wait_until="networkidle", timeout=45000)

        # MCA's "Whats New" / update strip renders as <a> tags inside a
        # marquee/list widget once Angular hydrates. Selector kept loose
        # (any anchor inside the update panel) since MCA's markup/class
        # names change with site redesigns more often than the feed does.
        anchors = page.query_selector_all("marquee a, .whatsnew a, .update-panel a")
        for a in anchors:
            title = clean_text(a.inner_text())
            href = a.get_attribute("href") or ""
            if not title or not href:
                continue
            if href.startswith("/"):
                href = "https://www.mca.gov.in" + href
            item_type, event_date = classify(title)
            items.append(
                FeedItem(
                    source="MCA",
                    title=title,
                    url=href,
                    type=item_type,
                    event_date=event_date,
                    published_at=None,
                    raw_snippet="",
                )
            )
        browser.close()
    return items


def scrape() -> List[FeedItem]:
    try:
        items = _scrape_via_rss()
        if items:
            logger.info("MCA: parsed %d items via RSS", len(items))
            return items
        logger.warning("MCA RSS returned zero items, falling back to Playwright")
    except Exception as exc:
        logger.warning("MCA RSS fetch failed (%s), falling back to Playwright", exc)

    try:
        items = _scrape_via_playwright()
        logger.info("MCA: parsed %d items via Playwright fallback", len(items))
        return items
    except Exception as exc:
        logger.error("MCA Playwright fallback also failed: %s", exc)
        return []


if __name__ == "__main__":
    for it in scrape():
        print(it.type, "|", it.title, "|", it.event_date)
