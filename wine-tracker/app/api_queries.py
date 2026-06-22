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
