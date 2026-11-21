"""CSV parsing and cleaning: empty rows, bad ratings, duplicates, HTML, injection flag."""
import csv
import hashlib
import io
import re

TAGS = re.compile(r"<[^>]+>")
INJECTION = re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)
REQUIRED_COLUMNS = {"review_id", "product", "review_text"}


def normalize(text):
    """Strip HTML tags and collapse whitespace."""
    return re.sub(r"\s+", " ", TAGS.sub(" ", text or "")).strip()


def text_hash(text):
    return hashlib.sha256(normalize(text).casefold().encode("utf-8")).hexdigest()


def parse_rating(value):
    """Return an int 1-5, or None for missing/invalid ratings."""
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return int(number) if number in (1, 2, 3, 4, 5) else None


def clean_csv(raw: bytes):
    """Return a list of review dicts with status: ok | empty | duplicate."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

    rows, seen = [], {}
    for i, row in enumerate(reader, start=1):
        text = normalize(row.get("review_text"))
        review = {
            "review_id": (row.get("review_id") or f"row{i}").strip(),
            "product": (row.get("product") or "Unknown").strip(),
            "rating": parse_rating(row.get("rating")),
            "date": (row.get("date") or "").strip(),
            "text": text,
            "hash": text_hash(text),
            "status": "ok",
            "duplicate_of": None,
            "injection_attempt": bool(INJECTION.search(text)),
            "analysis": None,
        }
        if not text:
            review["status"] = "empty"
        elif review["hash"] in seen:
            review["status"], review["duplicate_of"] = "duplicate", seen[review["hash"]]
        else:
            seen[review["hash"]] = review["review_id"]
        rows.append(review)
    return rows
