/**
 * Rufus Browser Demo — Service Worker (v2)
 *
 * Scope: same-origin requests only.
 *
 * Cross-origin CDN fetches (Pyodide WASM/JS from jsDelivr, Transformers.js,
 * HuggingFace config/tokenizer JSON) are intentionally NOT intercepted.
 * Those CDNs set Cache-Control: public, max-age=31536000, immutable, so the
 * browser's own HTTP cache handles them after the first visit — no need to
 * duplicate them in SW Cache Storage, and doing so caused Chrome extension
 * message-channel errors (browser extensions intercept SW fetch events for
 * cross-origin requests and fail to respond asynchronously).
 *
 * Model weight blobs (.safetensors, ONNX data) are already cached by
 * Transformers.js in IndexedDB — we skip those too.
 *
 * Offline readiness after first full online session:
 *   - App shell (index.html, worker.js, icons, wheel)  → SW Cache Storage ✓
 *   - Pyodide WASM + stdlib                            → browser HTTP cache ✓
 *   - Transformers.js + micropip packages              → browser HTTP cache ✓
 *   - ML model weights (~350 MB Qwen, ~23 MB MiniLM)  → Transformers.js IndexedDB ✓
 */

const VERSION = "3";
const CACHE   = `rufus-demo-sw-v${VERSION}`;

// App shell — fetched at install time so they're available offline immediately.
// All paths are same-origin (relative to the SW's own URL).
const PRECACHE = [
  "./",
  "./index.html",
  "./worker.js",
  "./manifest.json",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

// Synthetic 204 response for favicon — avoids a 404 network round-trip that
// can crash the SW when the server's statusText contains non-ISO-8859-1 chars.
const FAVICON_RESPONSE = new Response(null, { status: 204, statusText: "No Content" });

// ── Install: precache the app shell ──────────────────────────────────────────
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())   // activate immediately, no page reload needed
  );
});

// ── Activate: evict stale cache versions ─────────────────────────────────────
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function isSameOrigin(url) {
  try { return new URL(url).origin === self.location.origin; }
  catch { return false; }
}

// ── Fetch: cache-first, same-origin only ─────────────────────────────────────
self.addEventListener("fetch", event => {
  const { request } = event;
  if (request.method !== "GET") return;
  if (!isSameOrigin(request.url)) return;  // let browser HTTP cache handle CDN

  // Short-circuit favicon — no icon file exists; return a silent 204 rather
  // than letting the 404 propagate through (server statusText may contain
  // non-ISO-8859-1 chars that crash the Response constructor).
  if (new URL(request.url).pathname === "/favicon.ico") {
    event.respondWith(Promise.resolve(FAVICON_RESPONSE.clone()));
    return;
  }

  event.respondWith(
    caches.open(CACHE).then(async cache => {
      // 1. Cache hit → return immediately (works offline)
      const cached = await cache.match(request);
      if (cached) return cached;

      // 2. Cache miss → fetch from network, cache on success
      try {
        const fresh = await fetch(request);
        if (fresh.ok) cache.put(request, fresh.clone());
        return fresh;
      } catch {
        // Offline and not cached → plain ASCII statusText (ISO-8859-1 required)
        return new Response("offline", {
          status: 503,
          statusText: "Service Unavailable",
          headers: { "Content-Type": "text/plain" },
        });
      }
    })
  );
});
