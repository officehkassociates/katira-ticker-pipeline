"""
main.py
-------
Orchestrator: runs every source scraper, merges the results, and upserts
them into SQLite (deduping automatically via items.id).

Usage:
    python main.py                # run all sources
    python main.py --sources RBI,SEBI   # run a subset (useful for debugging
                                          one flaky portal without waiting
                                          on the others)

This is the single entry point the cron job / GitHub Action calls every
morning at 6:00 AM IST.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Callable, List

from scrapers.common import FeedItem, upsert_items
from scrapers import rbi_scraper, sebi_scraper, mca_scraper, bse_scraper, nse_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

SCRAPERS: dict[str, Callable[[], List[FeedItem]]] = {
    "RBI": rbi_scraper.scrape,
    "SEBI": sebi_scraper.scrape,
    "MCA": mca_scraper.scrape,
    "BSE": bse_scraper.scrape,
    "NSE": nse_scraper.scrape,
}


def run(selected_sources: List[str]) -> None:
    all_items: List[FeedItem] = []
    failures: List[str] = []

    for name in selected_sources:
        scrape_fn = SCRAPERS[name]
        started = time.time()
        try:
            items = scrape_fn()
            all_items.extend(items)
            logger.info("%s: OK (%d items, %.1fs)", name, len(items), time.time() - started)
        except Exception as exc:
            # One portal failing (e.g. MCA under maintenance) must never
            # take down the whole run -- the other four sources still
            # need to update the ticker today.
            logger.error("%s: FAILED -- %s", name, exc, exc_info=True)
            failures.append(name)

    inserted = upsert_items(all_items)
    logger.info(
        "Run complete: %d items processed, %d NEW rows inserted, %d source(s) failed (%s)",
        len(all_items), inserted, len(failures), ", ".join(failures) or "none",
    )

    # Non-zero exit if EVERY source failed -- lets the GitHub Action mark
    # the run as failed and notify you, while a partial failure (1-4
    # sources down) still exits 0 since the ticker still got fresh data.
    if failures and len(failures) == len(selected_sources):
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run regulatory ticker scrapers")
    parser.add_argument(
        "--sources",
        default="RBI,SEBI,MCA,BSE,NSE",
        help="Comma-separated list of sources to run (default: all)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    selected = [s.strip().upper() for s in args.sources.split(",") if s.strip()]
    unknown = set(selected) - set(SCRAPERS)
    if unknown:
        logger.error("Unknown source(s): %s. Valid: %s", unknown, list(SCRAPERS))
        sys.exit(2)
    run(selected)
