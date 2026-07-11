"""
diagnose_bse.py
----------------
One-off diagnostic: calls BSE's two JSON endpoints exactly like
bse_scraper.py does, but instead of assuming the response shape, prints
out what actually came back -- the Python type (dict/list/str) and a
readable preview -- so we can fix the real code against real data
instead of guessing.

Usage:
    python diagnose_bse.py

Safe to delete once bse_scraper.py is fixed and working.
"""

import json
from datetime import date, timedelta

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/corporates/ann.html",
    "Origin": "https://www.bseindia.com",
    "Accept": "application/json, text/plain, */*",
}

session = requests.Session()
session.headers.update(HEADERS)

from_date = date.today().strftime("%Y%m%d")
to_date = (date.today() + timedelta(days=30)).strftime("%Y%m%d")


def inspect(label, url, params):
    print("=" * 100)
    print(f"{label}")
    print(f"URL: {url}")
    print(f"PARAMS: {params}")
    print("-" * 100)
    try:
        resp = session.get(url, params=params, timeout=20)
        print("HTTP status:", resp.status_code)
        print("Content-Type header:", resp.headers.get("Content-Type"))

        # Try to parse as JSON; if that fails, show the raw text instead
        try:
            data = resp.json()
        except ValueError:
            print("Response was NOT valid JSON. First 500 characters of raw text:")
            print(resp.text[:500])
            return

        print("Parsed JSON top-level Python type:", type(data).__name__)

        if isinstance(data, dict):
            print("Top-level dict keys:", list(data.keys()))
            for key, value in data.items():
                print(f"  - data[{key!r}] is type {type(value).__name__}", end="")
                if isinstance(value, list):
                    print(f", length {len(value)}")
                    if value:
                        print(f"    First item preview: {json.dumps(value[0], indent=2)[:600]}")
                else:
                    print()
        elif isinstance(data, list):
            print(f"Top-level list, length {len(data)}")
            if data:
                print("First item preview:")
                print(json.dumps(data[0], indent=2)[:600])
        else:
            print("Raw value preview:", str(data)[:500])

    except Exception as exc:
        print("Request failed with exception:", repr(exc))
    print("=" * 100)
    print()


inspect(
    "BSE ANNOUNCEMENTS",
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w",
    {
        "pageno": 1,
        "strCat": -1,
        "strPrevDate": from_date,
        "strScrip": "",
        "strSearch": "P",
        "strToDate": to_date,
        "strType": "C",
    },
)

inspect(
    "BSE CORPORATE ACTIONS",
    "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w",
    {
        "Fdate": from_date,
        "Todate": to_date,
        "Purposecode": "",
        "ddlcategory": "",
    },
)

print("Done. Copy everything above and send it back.")