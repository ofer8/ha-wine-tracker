# Extended HA Read-Only REST API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four read-only JSON endpoints for Home Assistant — `/api/stats`, `/api/drink-window`, `/api/wines` (filterable list), `/api/wines/<id>` (detail).

**Architecture:** All query/aggregation logic lives in a new pure module `wine-tracker/app/api_queries.py` (no Flask imports — every function takes an open `sqlite3` connection and returns plain dicts/lists, so it's unit-testable without HTTP). `app.py` gains four thin route handlers that call those functions and wrap the result in `jsonify`. No schema change, no new dependencies.

**Tech Stack:** Python 3 / Flask 3 / SQLite (`sqlite3` stdlib) / pytest.

## Global Constraints

- **Response envelope:** success `{"ok": true, ...}`; error `{"ok": false, "error": "..."}` + HTTP status. Routes use `jsonify(ok=True, **data)`.
- **Wine `type` is always the English canonical label** via `TRANSLATIONS["en"].get(f"wine_type_{raw}", raw)`. Stored keys: `Rotwein/Weisswein/Rosé/Schaumwein/Dessertwein/Likörwein/Anderes` → `Red Wine/White Wine/Rosé/Sparkling Wine/Dessert Wine/Fortified Wine/Other`. The raw value is **not** also returned.
- **Lenient query params:** unknown/uninterpretable params fall back to defaults — never return 400 for a bad filter/sort.
- **Auth:** no new mechanism. The endpoints inherit `check_auth` (`app.py:345`), exactly like `/api/summary`. All four are GET, so `check_readonly` never blocks them.
- **Flat `/api/` prefix** (no versioning). Do **not** modify `/api/summary`, `/api/wine/<id>`, `/api/timeline`, or the `/stats` page.
- **Commit style:** plain imperative subject (matches repo history, no `feat:` prefix), end every commit message with the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Run tests from** the `wine-tracker/` directory: `cd wine-tracker && python -m pytest`.

---

### Task 1: `api_queries` module — `type_en`, `resolve_type_filter`, `serialize_wine`

These three helpers are the shared building blocks every endpoint uses. This task also creates the new test file and its insert helper.

**Files:**
- Create: `wine-tracker/app/api_queries.py`
- Create: `wine-tracker/tests/test_api_ha.py`

**Interfaces:**
- Consumes: `from translations import TRANSLATIONS` (existing module).
- Produces:
  - `type_en(raw: str | None) -> str | None`
  - `resolve_type_filter(value: str | None) -> str | None`
  - `serialize_wine(row: sqlite3.Row, full: bool = False) -> dict`
  - Test helper `_insert(db, **fields) -> int` (in `test_api_ha.py`, reused by later tasks).

- [ ] **Step 1: Write the failing tests**

Create `wine-tracker/tests/test_api_ha.py`:

```python
"""Tests for the read-only Home Assistant REST API (api_queries + routes)."""
import json

import api_queries


# ── shared insert helper ───────────────────────────────────────────────────────
_WINE_DEFAULTS = {
    "name": "Wine", "year": None, "type": None, "region": None,
    "quantity": 1, "rating": 0, "notes": None, "image": None,
    "added": "2026-01-01", "purchased_at": None, "price": None,
    "drink_from": None, "drink_until": None, "location": None,
    "grape": None, "vivino_id": None, "bottle_format": 0.75,
    "maturity_data": None, "taste_profile": None, "food_pairings": None,
}


def _insert(db, **fields):
    """Insert one wines row, commit, return its id. Unspecified columns use defaults."""
    cols = dict(_WINE_DEFAULTS)
    cols.update(fields)
    names = ",".join(cols)
    placeholders = ",".join("?" * len(cols))
    cur = db.execute(f"INSERT INTO wines ({names}) VALUES ({placeholders})", tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def _get_row(db, wine_id):
    return db.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()


# ── type_en ─────────────────────────────────────────────────────────────────────
def test_type_en_translates_known_keys():
    assert api_queries.type_en("Rotwein") == "Red Wine"
    assert api_queries.type_en("Weisswein") == "White Wine"
    assert api_queries.type_en("Anderes") == "Other"


def test_type_en_passes_through_unknown_and_none():
    assert api_queries.type_en("Glühwein") == "Glühwein"
    assert api_queries.type_en(None) is None
    assert api_queries.type_en("") == ""


# ── resolve_type_filter ─────────────────────────────────────────────────────────
def test_resolve_type_filter_maps_english_to_key():
    assert api_queries.resolve_type_filter("Red Wine") == "Rotwein"
    assert api_queries.resolve_type_filter("red wine") == "Rotwein"   # case-insensitive
    assert api_queries.resolve_type_filter("Other") == "Anderes"


def test_resolve_type_filter_passthrough_unknown():
    assert api_queries.resolve_type_filter("Rotwein") == "Rotwein"    # raw key still works
    assert api_queries.resolve_type_filter("Foo") == "Foo"
    assert api_queries.resolve_type_filter(None) is None


# ── serialize_wine ──────────────────────────────────────────────────────────────
def test_serialize_wine_light_omits_ai_blobs(db):
    wid = _insert(db, name="A", type="Rotwein", image="x.jpg",
                  maturity_data='{"k": 1}', taste_profile='{"body": 2}',
                  food_pairings='["cheese"]')
    out = api_queries.serialize_wine(_get_row(db, wid), full=False)
    assert out["type"] == "Red Wine"
    assert out["image_path"] == "/uploads/x.jpg"
    assert "maturity_data" not in out
    assert "taste_profile" not in out
    assert "food_pairings" not in out


def test_serialize_wine_full_parses_ai_blobs(db):
    wid = _insert(db, name="A", type="Weisswein",
                  maturity_data='{"k": 1}', food_pairings='["cheese"]')
    out = api_queries.serialize_wine(_get_row(db, wid), full=True)
    assert out["type"] == "White Wine"
    assert out["maturity_data"] == {"k": 1}        # parsed to object, not string
    assert out["food_pairings"] == ["cheese"]


def test_serialize_wine_image_path_none_when_no_image(db):
    wid = _insert(db, name="A", image=None)
    out = api_queries.serialize_wine(_get_row(db, wid))
    assert out["image_path"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -v`
Expected: collection/import error — `ModuleNotFoundError: No module named 'api_queries'` (the module doesn't exist yet).

- [ ] **Step 3: Create the `api_queries` module**

Create `wine-tracker/app/api_queries.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/api_queries.py wine-tracker/tests/test_api_ha.py
git commit -m "Add api_queries module with type + serialize helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `compute_stats` + `GET /api/stats`

**Files:**
- Modify: `wine-tracker/app/api_queries.py` (add `compute_stats`)
- Modify: `wine-tracker/app/app.py` (add `import api_queries` near line 18; add route before the `# ── Main ──` comment, ~line 3150)
- Modify: `wine-tracker/tests/test_api_ha.py` (add stats tests)

**Interfaces:**
- Consumes: `type_en` (Task 1).
- Produces: `compute_stats(db, current_year: int) -> dict` with keys `total_bottles, distinct_wines, out_of_stock, total_liters, total_value, avg_price, avg_age, avg_rating, by_type, by_region, by_grape, by_decade`. The route adds `currency` and `ok`.

- [ ] **Step 1: Write the failing tests**

Append to `wine-tracker/tests/test_api_ha.py`:

```python
# ── compute_stats / /api/stats ──────────────────────────────────────────────────
def test_stats_empty_db(client):
    resp = client.get("/api/stats")
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert data["total_bottles"] == 0
    assert data["distinct_wines"] == 0
    assert data["by_type"] == []
    assert data["by_region"] == []
    assert data["currency"] == "CHF"


def test_stats_aggregates(db):
    _insert(db, name="A", type="Rotwein", region="Bordeaux", grape="Merlot",
            quantity=2, price=10.0, year=2018, bottle_format=0.75, rating=4)
    _insert(db, name="B", type="Rotwein", region="Bordeaux", grape="Merlot",
            quantity=3, price=20.0, year=2012, bottle_format=1.5, rating=2)
    s = api_queries.compute_stats(db, 2026)
    assert s["total_bottles"] == 5
    assert s["distinct_wines"] == 2
    assert s["total_liters"] == round(2 * 0.75 + 3 * 1.5, 2)   # 6.0
    assert s["total_value"] == round(2 * 10.0 + 3 * 20.0, 2)   # 80.0
    assert s["avg_age"] == round(((2026 - 2018) + (2026 - 2012)) / 2, 1)  # 11.0
    assert s["avg_rating"] == 3.0


def test_stats_by_type_uses_english(db):
    _insert(db, name="A", type="Rotwein", quantity=2)
    _insert(db, name="B", type="Weisswein", quantity=1)
    s = api_queries.compute_stats(db, 2026)
    types = {row["type"]: row["bottles"] for row in s["by_type"]}
    assert types == {"Red Wine": 2, "White Wine": 1}


def test_stats_excludes_empty_dimensions(db):
    _insert(db, name="A", type=None, region="", grape=None, quantity=1)
    s = api_queries.compute_stats(db, 2026)
    assert s["by_type"] == []
    assert s["by_region"] == []
    assert s["by_grape"] == []


def test_stats_by_decade(db):
    _insert(db, name="A", year=2018, quantity=1)
    _insert(db, name="B", year=2012, quantity=2)
    _insert(db, name="C", year=2003, quantity=1)
    s = api_queries.compute_stats(db, 2026)
    decades = {row["decade"]: row["bottles"] for row in s["by_decade"]}
    assert decades == {2010: 3, 2000: 1}


def test_stats_out_of_stock(db):
    _insert(db, name="A", quantity=0)
    _insert(db, name="B", quantity=2)
    s = api_queries.compute_stats(db, 2026)
    assert s["out_of_stock"] == 1
    assert s["total_bottles"] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k stats -v`
Expected: FAIL — `AttributeError: module 'api_queries' has no attribute 'compute_stats'` (and the route test 404s).

- [ ] **Step 3a: Add `compute_stats` to `api_queries.py`**

Append to `wine-tracker/app/api_queries.py`:

```python
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
```

- [ ] **Step 3b: Wire the route into `app.py`**

Add the import. Find (`app.py:15-18`):

```python
from export_import import (
    build_export_zip, export_filename,
    parse_import_file, match_wines, apply_import, ImportError as WineImportError,
)
```

Add immediately after it:

```python
import api_queries
```

Then add the route immediately **before** the `# ── Main ──` section comment (`app.py:~3150`, right after the `api_summary` function):

```python
@app.route("/api/stats")
def api_stats():
    db = get_db()
    data = api_queries.compute_stats(db, datetime.now().year)
    data["currency"] = HA_OPTIONS.get("currency", "CHF")
    return jsonify(ok=True, **data)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k stats -v`
Expected: PASS (6 stats tests).

- [ ] **Step 5: Run the full test file**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -v`
Expected: PASS (14 tests total so far).

- [ ] **Step 6: Commit**

```bash
git add wine-tracker/app/api_queries.py wine-tracker/app/app.py wine-tracker/tests/test_api_ha.py
git commit -m "Add GET /api/stats endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `compute_drink_window` + `GET /api/drink-window`

**Files:**
- Modify: `wine-tracker/app/api_queries.py` (add `_dw_entry`, `compute_drink_window`)
- Modify: `wine-tracker/app/app.py` (add route before `# ── Main ──`)
- Modify: `wine-tracker/tests/test_api_ha.py` (add drink-window tests)

**Interfaces:**
- Consumes: `type_en` (Task 1).
- Produces: `compute_drink_window(db, current_year: int) -> dict` with keys `current_year, ready_now, entering_this_year, leaving_this_year, counts, ready, too_young, past_peak, unknown`. Each bucket is a list of entries `{id, name, year, type, quantity, drink_from, drink_until, location}`.

- [ ] **Step 1: Write the failing tests**

Append to `wine-tracker/tests/test_api_ha.py`:

```python
# ── compute_drink_window / /api/drink-window ────────────────────────────────────
def test_drink_window_buckets_both_bounds(db):
    _insert(db, name="Ready", type="Rotwein", quantity=1, drink_from=2022, drink_until=2028)
    _insert(db, name="Young", quantity=1, drink_from=2030, drink_until=2035)
    _insert(db, name="Past", quantity=1, drink_from=2010, drink_until=2020)
    _insert(db, name="Unknown", quantity=1)
    dw = api_queries.compute_drink_window(db, 2026)
    assert dw["counts"] == {"ready": 1, "too_young": 1, "past_peak": 1, "unknown": 1}
    assert dw["ready_now"] == 1
    assert dw["ready"][0]["name"] == "Ready"
    assert dw["ready"][0]["type"] == "Red Wine"        # English label
    assert dw["too_young"][0]["name"] == "Young"
    assert dw["past_peak"][0]["name"] == "Past"
    assert dw["unknown"][0]["name"] == "Unknown"


def test_drink_window_one_sided_bounds(db):
    _insert(db, name="OnlyFromReady", quantity=1, drink_from=2025, drink_until=None)
    _insert(db, name="OnlyFromYoung", quantity=1, drink_from=2030, drink_until=None)
    _insert(db, name="OnlyUntilReady", quantity=1, drink_from=None, drink_until=2026)
    _insert(db, name="OnlyUntilPast", quantity=1, drink_from=None, drink_until=2020)
    dw = api_queries.compute_drink_window(db, 2026)
    names = lambda bucket: {e["name"] for e in dw[bucket]}
    assert names("ready") == {"OnlyFromReady", "OnlyUntilReady"}
    assert names("too_young") == {"OnlyFromYoung"}
    assert names("past_peak") == {"OnlyUntilPast"}


def test_drink_window_entering_and_leaving(db):
    _insert(db, name="Entering", quantity=1, drink_from=2026, drink_until=2030)
    _insert(db, name="Leaving", quantity=1, drink_from=2020, drink_until=2026)
    dw = api_queries.compute_drink_window(db, 2026)
    assert dw["entering_this_year"] == 1
    assert dw["leaving_this_year"] == 1


def test_drink_window_excludes_out_of_stock(db):
    _insert(db, name="Empty", quantity=0, drink_from=2022, drink_until=2028)
    dw = api_queries.compute_drink_window(db, 2026)
    assert dw["counts"] == {"ready": 0, "too_young": 0, "past_peak": 0, "unknown": 0}


def test_drink_window_route(client, db):
    _insert(db, name="Ready", quantity=1, drink_from=2022, drink_until=2028)
    resp = client.get("/api/drink-window")
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert "current_year" in data
    assert set(data["counts"]) == {"ready", "too_young", "past_peak", "unknown"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k drink_window -v`
Expected: FAIL — `AttributeError: module 'api_queries' has no attribute 'compute_drink_window'`.

- [ ] **Step 3a: Add `compute_drink_window` to `api_queries.py`**

Append to `wine-tracker/app/api_queries.py`:

```python
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
```

- [ ] **Step 3b: Wire the route into `app.py`**

Add immediately after the `api_stats` route (before `# ── Main ──`):

```python
@app.route("/api/drink-window")
def api_drink_window():
    db = get_db()
    return jsonify(ok=True, **api_queries.compute_drink_window(db, datetime.now().year))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k drink_window -v`
Expected: PASS (5 drink-window tests).

- [ ] **Step 5: Run the full test file**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -v`
Expected: PASS (19 tests total so far).

- [ ] **Step 6: Commit**

```bash
git add wine-tracker/app/api_queries.py wine-tracker/app/app.py wine-tracker/tests/test_api_ha.py
git commit -m "Add GET /api/drink-window endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `query_wines` + `GET /api/wines` (filterable list)

**Files:**
- Modify: `wine-tracker/app/api_queries.py` (add `_int_or_none`, `_SORT_COLUMNS`, `query_wines`)
- Modify: `wine-tracker/app/app.py` (add route before `# ── Main ──`)
- Modify: `wine-tracker/tests/test_api_ha.py` (add list tests)

**Interfaces:**
- Consumes: `serialize_wine`, `resolve_type_filter` (Task 1).
- Produces: `query_wines(db, params) -> dict` with keys `count` (total matching, pre-pagination), `returned` (page size), `wines` (list of light records). `params` is any mapping with `.get()` (Flask `request.args` or a plain dict).

- [ ] **Step 1: Write the failing tests**

Append to `wine-tracker/tests/test_api_ha.py`:

```python
# ── query_wines / /api/wines ────────────────────────────────────────────────────
def test_wines_list_light_projection(client, db):
    _insert(db, name="A", type="Rotwein", image="a.jpg", maturity_data='{"k":1}',
            taste_profile='{"b":2}', food_pairings='["x"]')
    resp = client.get("/api/wines")
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["returned"] == 1
    w = data["wines"][0]
    assert w["type"] == "Red Wine"
    assert w["image_path"] == "/uploads/a.jpg"
    assert "maturity_data" not in w
    assert "taste_profile" not in w
    assert "food_pairings" not in w


def test_wines_filter_type_english(client, db):
    _insert(db, name="Red", type="Rotwein")
    _insert(db, name="White", type="Weisswein")
    resp = client.get("/api/wines?type=Red Wine")
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["wines"][0]["name"] == "Red"


def test_wines_filter_region_substring(client, db):
    _insert(db, name="A", region="Bordeaux, FR")
    _insert(db, name="B", region="Tuscany, IT")
    resp = client.get("/api/wines?region=Bordeaux")
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["wines"][0]["name"] == "A"


def test_wines_filter_grape_year_rating(client, db):
    _insert(db, name="A", grape="Merlot", year=2018, rating=5)
    _insert(db, name="B", grape="Syrah", year=2020, rating=2)
    assert json.loads(client.get("/api/wines?grape=Merlot").data)["count"] == 1
    assert json.loads(client.get("/api/wines?year=2020").data)["count"] == 1
    assert json.loads(client.get("/api/wines?min_rating=3").data)["count"] == 1


def test_wines_filter_in_stock(client, db):
    _insert(db, name="Full", quantity=2)
    _insert(db, name="Empty", quantity=0)
    resp = client.get("/api/wines?in_stock=true")
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["wines"][0]["name"] == "Full"


def test_wines_sort_year_desc(client, db):
    _insert(db, name="Old", year=2018)
    _insert(db, name="New", year=2020)
    resp = client.get("/api/wines?sort=year&order=desc")
    data = json.loads(resp.data)
    assert [w["year"] for w in data["wines"]] == [2020, 2018]


def test_wines_invalid_sort_falls_back(client, db):
    _insert(db, name="A")
    resp = client.get("/api/wines?sort=banana&order=sideways")
    data = json.loads(resp.data)
    assert resp.status_code == 200
    assert data["ok"] is True


def test_wines_pagination(client, db):
    for i in range(3):
        _insert(db, name=f"W{i}")
    resp = client.get("/api/wines?limit=2")
    data = json.loads(resp.data)
    assert data["count"] == 3
    assert data["returned"] == 2
    assert len(data["wines"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k "wines_" -v`
Expected: FAIL — the `/api/wines` route doesn't exist (404 → `KeyError`/assertion failures).

- [ ] **Step 3a: Add `query_wines` to `api_queries.py`**

Append to `wine-tracker/app/api_queries.py`:

```python
_SORT_COLUMNS = {
    "name": "name", "year": "year", "rating": "rating",
    "price": "price", "added": "added", "quantity": "quantity",
}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def query_wines(db, params):
    """Filter / sort / paginate the collection.

    `params` is any mapping with .get() (Flask request.args or a plain dict).
    Unknown or uninterpretable params are ignored (lenient — never raises).
    Returns {count, returned, wines} where `wines` are light records.
    """
    where, args = [], []

    type_val = params.get("type")
    if type_val:
        where.append("type = ?")
        args.append(resolve_type_filter(type_val))

    region = params.get("region")
    if region:
        where.append("region LIKE ?")
        args.append(f"%{region}%")

    grape = params.get("grape")
    if grape:
        where.append("grape LIKE ?")
        args.append(f"%{grape}%")

    year = _int_or_none(params.get("year"))
    if year is not None:
        where.append("year = ?")
        args.append(year)

    if str(params.get("in_stock", "")).lower() in ("1", "true", "yes"):
        where.append("quantity > 0")

    min_rating = _int_or_none(params.get("min_rating"))
    if min_rating is not None:
        where.append("rating >= ?")
        args.append(min_rating)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.execute(f"SELECT COUNT(*) FROM wines{where_sql}", args).fetchone()[0]

    sort_col = _SORT_COLUMNS.get((params.get("sort") or "").lower(), "name")
    order = "DESC" if (params.get("order") or "").lower() == "desc" else "ASC"
    order_sql = f" ORDER BY {sort_col} {order}, name COLLATE NOCASE ASC"

    limit = _int_or_none(params.get("limit"))
    offset = _int_or_none(params.get("offset")) or 0
    limit_sql, page_args = "", list(args)
    if limit is not None and 1 <= limit <= 500:
        limit_sql = " LIMIT ? OFFSET ?"
        page_args.extend([limit, max(offset, 0)])

    rows = db.execute(
        f"SELECT * FROM wines{where_sql}{order_sql}{limit_sql}", page_args
    ).fetchall()
    wines = [serialize_wine(r, full=False) for r in rows]
    return {"count": total, "returned": len(wines), "wines": wines}
```

Note: `sort_col` and `order` are drawn from fixed whitelists, never interpolated from raw user input, so the f-string SQL is injection-safe. All value filters are parameterized.

- [ ] **Step 3b: Wire the route into `app.py`**

Add immediately after the `api_drink_window` route (before `# ── Main ──`):

```python
@app.route("/api/wines")
def api_wines_list():
    db = get_db()
    return jsonify(ok=True, **api_queries.query_wines(db, request.args))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k "wines_" -v`
Expected: PASS (8 list tests).

- [ ] **Step 5: Run the full test file**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -v`
Expected: PASS (27 tests total so far).

- [ ] **Step 6: Commit**

```bash
git add wine-tracker/app/api_queries.py wine-tracker/app/app.py wine-tracker/tests/test_api_ha.py
git commit -m "Add GET /api/wines filterable list endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `GET /api/wines/<id>` (detail) + auth regression

**Files:**
- Modify: `wine-tracker/app/app.py` (add route before `# ── Main ──`)
- Modify: `wine-tracker/tests/test_api_ha.py` (add detail + auth tests)

**Interfaces:**
- Consumes: `serialize_wine` (Task 1). No new `api_queries` function.
- Produces: route `GET /api/wines/<int:wine_id>` → `{"ok": true, "wine": <full record>}` or `404 {"ok": false, "error": "not_found"}`.

- [ ] **Step 1: Write the failing tests**

Append to `wine-tracker/tests/test_api_ha.py`:

```python
# ── /api/wines/<id> detail ──────────────────────────────────────────────────────
def test_wine_detail_full_record(client, db):
    wid = _insert(db, name="A", type="Rotwein", image="a.jpg",
                  maturity_data='{"k": 1}', food_pairings='["cheese"]')
    resp = client.get(f"/api/wines/{wid}")
    data = json.loads(resp.data)
    assert data["ok"] is True
    w = data["wine"]
    assert w["type"] == "Red Wine"
    assert w["image_path"] == "/uploads/a.jpg"
    assert w["maturity_data"] == {"k": 1}        # parsed, present in detail
    assert w["food_pairings"] == ["cheese"]


def test_wine_detail_not_found(client):
    resp = client.get("/api/wines/999999")
    data = json.loads(resp.data)
    assert resp.status_code == 404
    assert data["ok"] is False
    assert data["error"] == "not_found"


# ── auth gate (mirrors test_api.py auth pattern) ────────────────────────────────
def test_api_requires_auth_when_enabled():
    import app as wine_app
    wine_app.init_db()
    wine_app.AUTH_ENABLED = True
    try:
        c = wine_app.app.test_client()
        assert c.get("/api/stats").status_code == 401
        assert c.get("/api/wines").status_code == 401
        assert c.get("/api/drink-window").status_code == 401
        assert c.get("/api/wines/1").status_code == 401
    finally:
        wine_app.AUTH_ENABLED = False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k "detail or requires_auth" -v`
Expected: FAIL — `/api/wines/<id>` route returns 404 for the existing wine too (no route yet) / the detail assertions fail.

- [ ] **Step 3: Add the detail route to `app.py`**

Add immediately after the `api_wines_list` route (before `# ── Main ──`):

```python
@app.route("/api/wines/<int:wine_id>")
def api_wines_detail(wine_id):
    db = get_db()
    row = db.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()
    if not row:
        return jsonify(ok=False, error="not_found"), 404
    return jsonify(ok=True, wine=api_queries.serialize_wine(row, full=True))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd wine-tracker && python -m pytest tests/test_api_ha.py -k "detail or requires_auth" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite (regression check)**

Run: `cd wine-tracker && python -m pytest -q`
Expected: PASS — all pre-existing tests plus the new `test_api_ha.py` (30 new tests). No failures.

- [ ] **Step 6: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_api_ha.py
git commit -m "Add GET /api/wines/<id> detail endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs + version bump

No tests — the deliverable is documentation and a synchronized version bump.

**Files:**
- Modify: `README.md` (the "Home Assistant Sensor (Optional)" section, ~line 278)
- Modify: `CHANGELOG.md` (add `## 1.11.0` at top, under `# Changelog`)
- Modify: `wine-tracker/CHANGELOG.md` (identical content — keep the two in sync)
- Modify: `wine-tracker/config.yaml:3` (`version: "1.10.0"` → `"1.11.0"`)
- Modify: `wine-tracker/app/app.py:146` (`APP_VERSION = "1.10.0"` → `"1.11.0"`)

- [ ] **Step 1: Expand the README "Home Assistant Sensor" section**

In `README.md`, replace the existing single sensor example block (the fenced yaml under "## Home Assistant Sensor (Optional)" plus the line after it) with:

````markdown
The add-on exposes read-only JSON endpoints for dashboards and automations. All return
`{"ok": true, ...}` and use **English** wine-type labels regardless of the UI language.

| Endpoint | Returns |
|----------|---------|
| `/api/summary` | total bottle count + by-type breakdown (legacy, unchanged) |
| `/api/stats` | totals, liters, value, average age/rating, breakdowns by type/region/grape/decade |
| `/api/drink-window` | wines bucketed `ready` / `too_young` / `past_peak` / `unknown`, plus year-boundary counts |
| `/api/wines` | the collection as JSON, filterable & sortable (`?type=`, `?region=`, `?in_stock=true`, `?sort=year&order=desc`, `?limit=`) |
| `/api/wines/<id>` | one wine, full detail incl. maturity / taste / pairings |

### Stock & value sensor

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: "Wine Cellar"
    resource: "http://localhost:5050/api/stats"
    value_template: "{{ value_json.total_bottles }}"
    unit_of_measurement: "bottles"
    json_attributes:
      - total_liters
      - total_value
      - avg_age
      - by_type
    scan_interval: 3600
```

### Drink-window sensor + notification

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: "Wines Ready to Drink"
    resource: "http://localhost:5050/api/drink-window"
    value_template: "{{ value_json.ready_now }}"
    unit_of_measurement: "wines"
    json_attributes:
      - entering_this_year
      - leaving_this_year
    scan_interval: 86400

automation:
  - alias: "Wine entering its drink window"
    trigger:
      - platform: numeric_state
        entity_id: sensor.wines_ready_to_drink
        attribute: entering_this_year
        above: 0
    action:
      - service: notify.notify
        data:
          message: >
            {{ state_attr('sensor.wines_ready_to_drink', 'entering_this_year') }}
            wine(s) just entered their optimal drinking window.
```

> **Note (standalone Docker):** when `AUTH_ENABLED=true`, these endpoints require a logged-in
> session, so an unauthenticated REST sensor receives `401`. In the Home Assistant add-on
> (the default), access is gated by HA and the sensors work as shown.
````

- [ ] **Step 2: Add the CHANGELOG entry (both files, identical)**

In **both** `CHANGELOG.md` and `wine-tracker/CHANGELOG.md`, insert this block between `# Changelog` and `## 1.10.0`:

```markdown
## 1.11.0

- **Extended read-only REST API** - new JSON endpoints for Home Assistant dashboards & automations: `/api/stats` (totals, liters, value, average age/rating, breakdowns by type/region/grape/decade), `/api/drink-window` (wines bucketed ready / too young / past peak, with year-boundary counts for notifications), `/api/wines` (the filterable, sortable collection) and `/api/wines/<id>` (single-wine detail). All use English wine-type labels regardless of UI language. The existing `/api/summary` is unchanged. Resolves the "Extended REST API" roadmap item.
- **Tests** - added 30 tests for the new API query helpers and routes.
```

- [ ] **Step 3: Bump the version (three references in sync)**

In `wine-tracker/config.yaml` line 3:

```yaml
version: "1.11.0"
```

In `wine-tracker/app/app.py` line 146:

```python
APP_VERSION = "1.11.0"
```

- [ ] **Step 4: Verify versions are consistent**

Run: `cd /Users/ofer/conductor/workspaces/ha-wine-tracker/cairo && grep -rn "1.11.0" wine-tracker/config.yaml wine-tracker/app/app.py CHANGELOG.md wine-tracker/CHANGELOG.md`
Expected: one match in each file (two in app.py is fine only if APP_VERSION is the only literal — confirm it's the version line).

- [ ] **Step 5: Run the full suite once more**

Run: `cd wine-tracker && python -m pytest -q`
Expected: PASS (full suite green — the version-string change must not break the export test that reads `APP_VERSION`).

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md wine-tracker/CHANGELOG.md wine-tracker/config.yaml wine-tracker/app/app.py
git commit -m "Document HA REST API and bump version to 1.11.0

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- `/api/stats` → Task 2 ✓ · `/api/drink-window` → Task 3 ✓ · `/api/wines` (light, filter/sort/paginate) → Task 4 ✓ · `/api/wines/<id>` (full) → Task 5 ✓
- Pure module `api_queries.py` + thin routes → Tasks 1–5 ✓
- English `type` everywhere → `type_en` / `serialize_wine` (Task 1), asserted in Tasks 2–5 ✓
- Lenient params (no 400) → `query_wines` + `test_wines_invalid_sort_falls_back` (Task 4) ✓
- Auth inherited, no new code → `test_api_requires_auth_when_enabled` (Task 5) ✓
- Light list omits AI blobs / detail parses them → Tasks 1, 4, 5 ✓
- Docs (README + CHANGELOG) → Task 6 ✓

**Placeholder scan:** No TBD/TODO; every code and test step contains complete code; every run step has an exact command + expected outcome.

**Type consistency:** `type_en`, `resolve_type_filter`, `serialize_wine`, `compute_stats`, `compute_drink_window`, `_dw_entry`, `query_wines`, `_int_or_none`, `_SORT_COLUMNS` are named identically wherever referenced across tasks. Route function names (`api_stats`, `api_drink_window`, `api_wines_list`, `api_wines_detail`) are unique and don't collide with existing routes (`api_summary`, `api_get_wine` at `/api/wine/<id>`).

**Edge cases covered by tests:** empty DB; NULL/empty type-region-grape excluded from breakdowns; one-sided drink windows; out-of-stock exclusion; year-boundary entering/leaving; invalid sort fallback; pagination count-vs-returned; 404 on missing wine; auth 401 gate.
