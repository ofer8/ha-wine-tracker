"""Pure query/aggregation helpers for the read-only Home Assistant REST API.

No Flask imports — every function takes an open sqlite3 connection (with a
sqlite3.Row row_factory) and returns plain dict/list data, so they are
unit-testable without an HTTP layer. The routes in app.py wrap these in jsonify().
"""
import json

from translations import TRANSLATIONS

_EN = TRANSLATIONS["en"]

# Reverse lookup: lower-cased English label -> stored key, e.g. "red wine" -> "Rotwein".
_EN_TO_KEY = {
    label.lower(): key[len("wine_type_"):]
    for key, label in _EN.items()
    if key.startswith("wine_type_")
}

_AI_JSON_FIELDS = ("maturity_data", "taste_profile", "food_pairings")


def type_en(raw):
    """Translate a stored wine-type key ('Rotwein') to its English label ('Red Wine').

    Unknown or falsy values are returned unchanged (None stays None, "" stays "").
    """
    if not raw:
        return raw
    return _EN.get(f"wine_type_{raw}", raw)


def resolve_type_filter(value):
    """Map an English type label back to its stored key for filtering.

    'Red Wine' -> 'Rotwein' (case-insensitive). Unknown values pass through
    unchanged, so raw stored keys still work as a filter.
    """
    if not value:
        return value
    return _EN_TO_KEY.get(value.strip().lower(), value)


def serialize_wine(row, full=False):
    """Convert a wines row (sqlite3.Row) to a JSON-ready dict.

    - `type` is replaced with its English label.
    - `image_path` is added ('/uploads/<image>' or None).
    - full=True: the three AI JSON-text columns are parsed into objects.
    - full=False: those three columns are omitted entirely.
    """
    d = dict(row)
    d["type"] = type_en(d.get("type"))
    image = d.get("image")
    d["image_path"] = f"/uploads/{image}" if image else None
    if full:
        for key in _AI_JSON_FIELDS:
            raw = d.get(key)
            if raw:
                try:
                    d[key] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[key] = None
    else:
        for key in _AI_JSON_FIELDS:
            d.pop(key, None)
    return d


def compute_stats(db, current_year):
    """Aggregate cellar statistics. Returns a flat dict (no envelope, no currency)."""
    totals = db.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS bottles, COUNT(*) AS wines FROM wines"
    ).fetchone()
    out_of_stock = db.execute(
        "SELECT COUNT(*) FROM wines WHERE quantity = 0"
    ).fetchone()[0]
    liters = db.execute(
        "SELECT COALESCE(SUM(quantity * COALESCE(bottle_format, 0.75)), 0) FROM wines"
    ).fetchone()[0]
    value = db.execute(
        "SELECT COALESCE(SUM(quantity * price), 0) AS total, AVG(price) AS avg "
        "FROM wines WHERE price IS NOT NULL AND price > 0"
    ).fetchone()
    avg_age = db.execute(
        "SELECT AVG(? - year) FROM wines WHERE year IS NOT NULL AND year > 0",
        (current_year,),
    ).fetchone()[0]
    avg_rating = db.execute(
        "SELECT AVG(rating) FROM wines WHERE rating > 0"
    ).fetchone()[0]

    by_type = [
        {"type": type_en(r["type"]), "bottles": r["bottles"], "wines": r["wines"]}
        for r in db.execute(
            "SELECT type, COALESCE(SUM(quantity), 0) AS bottles, COUNT(*) AS wines "
            "FROM wines WHERE type IS NOT NULL AND type != '' "
            "GROUP BY type ORDER BY bottles DESC"
        ).fetchall()
    ]
    by_region = [
        {"region": r["region"], "bottles": r["bottles"]}
        for r in db.execute(
            "SELECT region, COALESCE(SUM(quantity), 0) AS bottles "
            "FROM wines WHERE region IS NOT NULL AND region != '' "
            "GROUP BY region ORDER BY bottles DESC"
        ).fetchall()
    ]
    by_grape = [
        {"grape": r["grape"], "bottles": r["bottles"]}
        for r in db.execute(
            "SELECT grape, COALESCE(SUM(quantity), 0) AS bottles "
            "FROM wines WHERE grape IS NOT NULL AND grape != '' "
            "GROUP BY grape ORDER BY bottles DESC"
        ).fetchall()
    ]
    by_decade = [
        {"decade": int(r["decade"]), "bottles": r["bottles"]}
        for r in db.execute(
            "SELECT (year / 10) * 10 AS decade, COALESCE(SUM(quantity), 0) AS bottles "
            "FROM wines WHERE year IS NOT NULL AND year > 0 "
            "GROUP BY decade ORDER BY decade ASC"
        ).fetchall()
    ]

    return {
        "total_bottles": totals["bottles"],
        "distinct_wines": totals["wines"],
        "out_of_stock": out_of_stock,
        "total_liters": round(liters, 2),
        "total_value": round(value["total"], 2),
        "avg_price": round(value["avg"], 2) if value["avg"] is not None else 0.0,
        "avg_age": round(avg_age, 1) if avg_age is not None else 0.0,
        "avg_rating": round(avg_rating, 1) if avg_rating is not None else 0.0,
        "by_type": by_type,
        "by_region": by_region,
        "by_grape": by_grape,
        "by_decade": by_decade,
    }


_FAR_YEAR = 9999  # sort sentinel so None drink years sort last without comparing None


def _dw_entry(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "year": row["year"],
        "type": type_en(row["type"]),
        "quantity": row["quantity"],
        "drink_from": row["drink_from"],
        "drink_until": row["drink_until"],
        "location": row["location"],
    }


def compute_drink_window(db, current_year):
    """Bucket in-stock wines (quantity > 0) by drinking-window state for current_year."""
    rows = db.execute(
        "SELECT id, name, year, type, quantity, drink_from, drink_until, location "
        "FROM wines WHERE quantity > 0"
    ).fetchall()

    ready, too_young, past_peak, unknown = [], [], [], []
    entering = leaving = 0
    for r in rows:
        frm, until = r["drink_from"], r["drink_until"]
        if frm is None and until is None:
            unknown.append(r)
            continue
        if frm == current_year:
            entering += 1
        if until == current_year:
            leaving += 1
        if frm is not None and current_year < frm:
            too_young.append(r)
        elif until is not None and current_year > until:
            past_peak.append(r)
        else:
            ready.append(r)

    ready.sort(key=lambda r: r["drink_until"] if r["drink_until"] is not None else _FAR_YEAR)
    too_young.sort(key=lambda r: r["drink_from"] if r["drink_from"] is not None else _FAR_YEAR)
    past_peak.sort(key=lambda r: r["drink_until"] if r["drink_until"] is not None else _FAR_YEAR)
    unknown.sort(key=lambda r: (r["name"] or "").lower())

    return {
        "current_year": current_year,
        "ready_now": len(ready),
        "entering_this_year": entering,
        "leaving_this_year": leaving,
        "counts": {
            "ready": len(ready),
            "too_young": len(too_young),
            "past_peak": len(past_peak),
            "unknown": len(unknown),
        },
        "ready": [_dw_entry(r) for r in ready],
        "too_young": [_dw_entry(r) for r in too_young],
        "past_peak": [_dw_entry(r) for r in past_peak],
        "unknown": [_dw_entry(r) for r in unknown],
    }
