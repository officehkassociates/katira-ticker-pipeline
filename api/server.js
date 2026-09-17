/**
 * api/server.js
 * --------------
 * Minimal Express API that reads the SQLite database populated by the
 * Python scrapers and exposes it to the frontend ticker.
 *
 * Endpoints:
 *   GET /api/news       -> latest "news" items, newest first
 *   GET /api/dates       -> upcoming "date" items, soonest first
 *   GET /api/health      -> simple uptime/DB-connectivity check
 *
 * Why a separate Node API instead of having the frontend hit SQLite
 * directly: SQLite is a file, not a network service -- something has to
 * sit in front of it to serve JSON over HTTP, handle CORS, and cache
 * responses. Express is the lightest reasonable choice here; if you'd
 * rather not run a Node process at all, swap this file for a single
 * Firebase Cloud Function or a Vercel/Netlify serverless function that
 * does the same three queries -- the SQL is identical either way.
 */

const express = require("express");
const cors = require("cors");
const path = require("path");
const Database = require("better-sqlite3");

const DB_PATH = path.join(__dirname, "..", "db", "regulatory_feed.db");
const PORT = process.env.PORT || 4000;

const app = express();
app.use(cors());

// better-sqlite3 opens the file read-only from the API's perspective in
// practice (only main.py ever writes), so a single shared connection is
// safe and fast -- no connection pool needed for this workload.
const db = new Database(DB_PATH, { readonly: true, fileMustExist: true });

// Simple in-memory cache: the DB only changes once a day (the 6 AM cron),
// so there's no reason to hit disk on every page load / ticker refresh.
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
let cache = { news: null, dates: null, newsAt: 0, datesAt: 0 };

function getNews() {
  if (cache.news && Date.now() - cache.newsAt < CACHE_TTL_MS) return cache.news;
  const rows = db
    .prepare(
      `SELECT id, source, title, url, published_at, fetched_at
       FROM items
       WHERE type = 'news'
       ORDER BY COALESCE(published_at, fetched_at) DESC
       LIMIT 50`
    )
    .all();
  cache.news = rows;
  cache.newsAt = Date.now();
  return rows;
}

function getDates() {
  if (cache.dates && Date.now() - cache.datesAt < CACHE_TTL_MS) return cache.dates;
  const rows = db
    .prepare(
      `SELECT id, source, title, url, event_date, fetched_at
       FROM items
       WHERE type = 'date'
         AND event_date IS NOT NULL
         AND event_date >= date('now', '-1 day')
       ORDER BY event_date ASC
       LIMIT 50`
    )
    .all();
  cache.dates = rows;
  cache.datesAt = Date.now();
  return rows;
}

app.get("/api/news", (req, res) => {
  try {
    res.json({ items: getNews() });
  } catch (err) {
    console.error("GET /api/news failed:", err);
    res.status(500).json({ error: "Failed to read news feed" });
  }
});

app.get("/api/dates", (req, res) => {
  try {
    res.json({ items: getDates() });
  } catch (err) {
    console.error("GET /api/dates failed:", err);
    res.status(500).json({ error: "Failed to read dates feed" });
  }
});

app.get("/api/health", (req, res) => {
  try {
    db.prepare("SELECT 1").get();
    res.json({ status: "ok", db: "connected" });
  } catch (err) {
    res.status(500).json({ status: "error", db: "unreachable" });
  }
});

app.listen(PORT, () => {
  console.log(`Ticker API listening on http://localhost:${PORT}`);
});
