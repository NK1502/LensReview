"""Dashboard numbers: summary cards, rating/sentiment agreement, topic fallback."""
from collections import Counter

EXPECTED = {1: "negative", 2: "negative", 3: "neutral", 4: "positive", 5: "positive"}


def rating_mismatch(review):
    """True when stars and text point in opposite directions (e.g. 5 stars, negative text)."""
    a, rating = review["analysis"], review["rating"]
    if not a or rating is None:
        return False
    return {EXPECTED[rating], a["sentiment"]} == {"positive", "negative"}


def summarize(reviews):
    analysed = [r for r in reviews if r["status"] == "ok" and r["analysis"]]
    n = len(analysed)
    counts = Counter(r["analysis"]["sentiment"] for r in analysed)
    rated = [r for r in analysed if r["rating"] is not None]
    agree = sum(EXPECTED[r["rating"]] == r["analysis"]["sentiment"] for r in rated)
    pct = lambda x, total: round(100 * x / total) if total else 0
    return {
        "total_rows": len(reviews),
        "analysed": n,
        "empty": sum(r["status"] == "empty" for r in reviews),
        "duplicates": sum(r["status"] == "duplicate" for r in reviews),
        "failed": sum(r["status"] == "analysis_failed" for r in reviews),
        "positive_pct": pct(counts["positive"], n),
        "neutral_pct": pct(counts["neutral"], n),
        "negative_pct": pct(counts["negative"], n),
        "needs_reply": sum(r["analysis"]["needs_reply"] for r in analysed),
        "rating_agreement_pct": pct(agree, len(rated)),
        "mismatches": sum(rating_mismatch(r) for r in analysed),
    }


def split_summaries(reviews):
    ok = [r for r in reviews if r["status"] == "ok" and r["analysis"]]
    neg = [r["analysis"]["summary"] for r in ok if r["analysis"]["sentiment"] == "negative"]
    pos = [r["analysis"]["summary"] for r in ok if r["analysis"]["sentiment"] == "positive"]
    return neg, pos


def topic_fallback(reviews):
    """Used if the theme LLM call fails: count topics instead."""
    ok = [r for r in reviews if r["status"] == "ok" and r["analysis"]]
    out = {}
    for key, sentiment in (("complaints", "negative"), ("praises", "positive")):
        c = Counter(t for r in ok if r["analysis"]["sentiment"] == sentiment for t in r["analysis"]["topics"])
        out[key] = [f"{t} ({n} reviews)" for t, n in c.most_common(3)]
    return out
