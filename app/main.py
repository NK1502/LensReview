"""HTTP server (standard library only): upload -> clean -> batch analyse (cache) -> dashboard JSON."""
import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import insights, llm
from .cache import Cache
from .cleaning import clean_csv

BATCH_SIZE = 5
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"

cache = Cache(os.getenv("CACHE_PATH", "cache.db"))
STATE = {"reviews": [], "themes": None, "log": None}  # single-user, in-memory


def load_env(path=".env"):
    """Minimal .env loader so no extra dependency is needed."""
    if os.path.exists(path):
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def analyse_all(rows):
    """Fill row['analysis'] using the cache first, then batched LLM calls."""
    calls = hits = 0
    unique = [r for r in rows if r["status"] == "ok"]
    todo = []
    for r in unique:
        cached = cache.get(r["hash"])
        if cached:
            r["analysis"], hits = cached, hits + 1
        else:
            todo.append(r)
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        results, n = llm.analyse_batch(batch)
        calls += n
        for r in batch:
            result = results.get(r["review_id"])
            if result:
                r["analysis"] = result
                cache.put(r["hash"], result)
            else:
                r["status"] = "analysis_failed"
    originals = {r["review_id"]: r for r in rows}
    for r in rows:
        if r["status"] == "duplicate":
            r["analysis"] = originals[r["duplicate_of"]]["analysis"]
    return calls, hits


def build_themes(rows):
    """Top 3 complaints/praises via one LLM call (cached); falls back to topic counts."""
    neg, pos = insights.split_summaries(rows)
    key = "themes:" + hashlib.sha256(json.dumps([neg, pos]).encode()).hexdigest()
    cached = cache.get(key)
    if cached:
        return cached, 0
    try:
        themes = llm.extract_themes(neg, pos)
        cache.put(key, themes)
        return themes, 1
    except (llm.LLMError, ValueError, AttributeError):
        return insights.topic_fallback(rows), 1


def payload():
    rows = STATE["reviews"]
    table = [
        {**{k: r[k] for k in ("review_id", "product", "rating", "date", "text", "status",
                              "duplicate_of", "injection_attempt", "analysis")},
         "mismatch": insights.rating_mismatch(r)}
        for r in rows
    ]
    return {"summary": insights.summarize(rows), "themes": STATE["themes"],
            "log": STATE["log"], "reviews": table}


def handle_upload(raw):
    start = time.time()
    rows = clean_csv(raw)  # raises ValueError on a bad file
    calls, hits = analyse_all(rows)
    STATE["reviews"] = rows
    STATE["themes"], theme_calls = build_themes(rows)
    STATE["log"] = {"ai_calls": calls + theme_calls, "cache_hits": hits,
                    "seconds": round(time.time() - start, 1)}
    return payload()


def handle_reply(review_id):
    review = next((r for r in STATE["reviews"] if r["review_id"] == review_id), None)
    if not review or not review["analysis"]:
        return 404, {"detail": "Review not found or not analysed"}
    try:
        return 200, {"reply": llm.suggest_reply(review)}
    except llm.LLMError as exc:
        return 502, {"detail": f"AI service error: {exc}"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            return None
        return self.rfile.read(length)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/dashboard":
            self._send(200, payload())
        else:
            self._send(404, {"detail": "Not found"})

    def do_POST(self):
        body = self._read_body()
        if body is None:
            return self._send(413, {"detail": "File too large (max 5 MB)"})
        if self.path == "/api/upload":
            try:
                self._send(200, handle_upload(body))
            except ValueError as exc:
                self._send(400, {"detail": str(exc)})
        elif self.path == "/api/reply":
            try:
                review_id = json.loads(body)["review_id"]
            except (ValueError, KeyError, TypeError):
                return self._send(400, {"detail": "Expected JSON with review_id"})
            self._send(*handle_reply(review_id))
        else:
            self._send(404, {"detail": "Not found"})


def main():
    load_env()
    port = int(os.getenv("PORT", "8000"))
    print(f"ReviewLens running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
