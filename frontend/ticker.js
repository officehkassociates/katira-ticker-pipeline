/**
 * frontend/ticker.js
 * ------------------
 * Fetches the two feeds from the backend API and renders them into the
 * scrolling ticker tracks. No frameworks -- vanilla JS.
 *
 * How the infinite-scroll illusion works:
 *   1. We render the item list into the track TWICE, back to back.
 *   2. The CSS animation (`ticker-scroll` in ticker.css) translates the
 *      track from 0 to -50% of its own width -- i.e. exactly the width
 *      of ONE copy of the list.
 *   3. The instant it reaches -50%, the animation loops back to 0%,
 *      which is pixel-identical to what's on screen (copy #2 is now
 *      sitting where copy #1 started) -- so the loop is seamless.
 *   4. Animation duration is scaled to content width so longer item
 *      lists scroll at a consistent *speed* rather than a fixed *time*.
 */

const API_BASE = window.TICKER_API_BASE || "http://localhost:4000";
const PIXELS_PER_SECOND = 60; // tune scroll speed here

async function fetchJSON(path) {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} responded ${res.status}`);
  return res.json();
}

function formatEventDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/**
 * Builds one <a> ticker item. Shared by both tickers so the news feed
 * and the dates feed look consistent.
 */
function renderItem(item, { showEventDate }) {
  const a = document.createElement("a");
  a.className = "ticker-item";
  a.href = item.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer"; // security best-practice for target=_blank links

  const badge = document.createElement("span");
  badge.className = "src-badge";
  badge.textContent = item.source;
  a.appendChild(badge);

  const label = document.createElement("span");
  label.textContent = item.title;
  a.appendChild(label);

  if (showEventDate && item.event_date) {
    const dateSpan = document.createElement("span");
    dateSpan.className = "event-date";
    dateSpan.textContent = `\u2022 ${formatEventDate(item.event_date)}`;
    a.appendChild(dateSpan);
  }

  return a;
}

/**
 * Populates a ticker track: clears the "Loading..." placeholder, renders
 * the item list twice for the seamless-loop trick, and sets the CSS
 * custom property that controls animation duration based on content width.
 */
function populateTicker(trackEl, items, { showEventDate }) {
  trackEl.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("span");
    empty.className = "ticker-loading";
    empty.textContent = "No updates available right now.";
    trackEl.appendChild(empty);
    return;
  }

  // Render the list TWICE back-to-back (see file header comment).
  for (let copy = 0; copy < 2; copy++) {
    items.forEach((item) => {
      trackEl.appendChild(renderItem(item, { showEventDate }));
    });
  }

  // Scale animation duration to actual rendered width so scroll *speed*
  // stays constant regardless of how many items are loaded.
  requestAnimationFrame(() => {
    const singleCopyWidth = trackEl.scrollWidth / 2;
    const durationSeconds = Math.max(20, singleCopyWidth / PIXELS_PER_SECOND);
    trackEl.style.setProperty("--ticker-duration", `${durationSeconds}s`);
  });
}

async function loadNewsTicker() {
  const track = document.getElementById("news-track");
  try {
    const { items } = await fetchJSON("/api/news");
    populateTicker(track, items, { showEventDate: false });
  } catch (err) {
    console.error("Failed to load news ticker:", err);
    track.innerHTML = '<span class="ticker-loading">Unable to load news right now.</span>';
  }
}

async function loadDatesTicker() {
  const track = document.getElementById("dates-track");
  try {
    const { items } = await fetchJSON("/api/dates");
    populateTicker(track, items, { showEventDate: true });
  } catch (err) {
    console.error("Failed to load dates ticker:", err);
    track.innerHTML = '<span class="ticker-loading">Unable to load compliance dates right now.</span>';
  }
}

// Initial load
loadNewsTicker();
loadDatesTicker();

// Refresh in-browser every 10 minutes so a ticker left open overnight
// picks up the 6 AM scrape without the visitor needing to reload the page.
// (The API itself caches for 5 minutes server-side, so this is cheap.)
setInterval(loadNewsTicker, 10 * 60 * 1000);
setInterval(loadDatesTicker, 10 * 60 * 1000);
