"""Tiny SQLite key/value cache keyed by a hash of the review text."""
import json
import sqlite3


class Cache:
    def __init__(self, path="cache.db"):
        self.path = path
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)")

    def get(self, key):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))
