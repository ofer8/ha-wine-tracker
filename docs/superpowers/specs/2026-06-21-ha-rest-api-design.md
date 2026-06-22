# Extended HA read-only REST API — design

**Date:** 2026-06-21
**Status:** Approved (pending implementation)

## Problem

The only machine-readable endpoint built for Home Assistant is `GET /api/summary`
(`app.py:3134`), which returns total bottle count + a by-type breakdown. The ROADMAP calls for
an *"Extended REST API — more endpoints (single wine, stats, collection export) for dashboards &
automations."* Everything richer that the UI shows (total value, liters, average age, drink
windows, the full collection) is computed server-side only for HTML rendering (e.g. the `/stats`
page at `app.py:1227`) and is not reachable as JSON.

This adds a small set of **read-only** JSON endpoints aimed at Home Assistant: rich stats,
drink-window buckets, and a filterable collection list + single-wine detail. They let users build
many sensors from one poll and drive drink-window notifications.

## Decisions (from brainstorming)

1. **Consumer:** Home Assistant sensors/automations — read-only. No write endpoints.
2. **Scope:** four endpoints — `/api/stats`, `/api/drink-window`, `/api/wines`, `/api/wines/<id>`.
3. **Auth:** no new mechanism. The endpoints inherit the existing `check_auth` rule (`app.py:345`),
   exactly like `/api/summary`: open when `AUTH_ENABLED=false` (the standard HA add-on), session-gated
   when `AUTH_ENABLED=true` (standalone Docker). No API token.
4. **Labels:** wine `type` is returned as the **English** canonical label everywhere (following
   `/api/summary`, `app.py:3142`), so HA automations are stable regardless of UI language.
5. **Structure:** a new pure-Python module `wine-tracker/app/api_queries.py` holds all
   query/aggregation logic; `app.py` gains four thin route handlers that call it and `jsonify`.
6. **List vs detail:** `/api/wines` returns a **light** projection (omits the large AI JSON blobs);
   `/api/wines/<id>` returns the **full** record including parsed AI JSON.

## Conventions followed

- Response envelope: success `{"ok": true, ...}`, error `{"ok": false, "error": "..."}` + HTTP code
  (the dominant pattern, e.g. `/api/wine/<id>` at `app.py:3125`).
- Type → English via `TRANSLATIONS["en"].get(f"wine_type_{raw}", raw)`. Canonical stored keys are
  `WINE_TYPES = ["Rotwein","Weisswein","Rosé","Schaumwein","Dessertwein","Likörwein","Anderes"]`
  → `Red Wine / White Wine / Rosé / Sparkling Wine / Dessert Wine / Fortified Wine / Other`.
- **Lenient query params:** bad/unknown params never 400 — they fall back to defaults. A sensor that
  sends a typo'd filter still gets data, not an error.
- Flat `/api/` prefix (consistent with existing endpoints). No `/v1/` versioning.

## Module: `wine-tracker/app/api_queries.py` (pure, no Flask)

Imports only `from translations import TRANSLATIONS`. All functions take an open sqlite3
connection (`sqlite3.Row` factory) and plain values, so they are unit-testable without HTTP.

```python
def type_en(raw):                       # "Rotwein" -> "Red Wine"; unknown/empty -> raw or None
def serialize_wine(row, full=False):    # dict(row) + English type + image_path; full parses AI JSON, else drops it
def compute_stats(db, current_year):    # -> dict of aggregates (no envelope, no currency)
def compute_drink_window(db, current_year):  # -> dict of buckets + counts + scalars
def query_wines(db, params):            # params: any mapping with .get() (request.args or dict) -> {count, returned, wines}
```

`serialize_wine` rules:
- `type` is replaced with its English label (raw stored value is **not** also returned — decision 4).
- `image_path` = `"/uploads/<image>"` when `image` is set, else `null` (`image` filename kept too).
- `full=True`: parse `maturity_data` / `taste_profile` / `food_pairings` from JSON text to objects
  (same logic as `wine_json`, `app.py:594`).
- `full=False`: those three keys are **omitted** entirely.

## Endpoint 1 — `GET /api/stats`

Route: `data = compute_stats(db, datetime.now().year)`, then add `currency` from
`HA_OPTIONS`, return `jsonify(ok=True, **data)`.

Aggregates (SQL mirrors `app.py:1233-1305`; floats rounded — money/liters to 2 dp, age/rating to 1 dp):

```json
{
  "ok": true,
  "currency": "CHF",
  "total_bottles": 42,          // SUM(quantity)
  "distinct_wines": 18,         // COUNT(*) wine entries
  "out_of_stock": 2,            // COUNT(*) WHERE quantity = 0  (empty placeholders)
  "total_liters": 31.5,         // SUM(quantity * COALESCE(bottle_format, 0.75))
  "total_value": 1234.5,        // SUM(quantity * price) WHERE price > 0
  "avg_price": 29.4,            // AVG(price) WHERE price > 0
  "avg_age": 6.2,               // AVG(current_year - year) WHERE year > 0
  "avg_rating": 3.8,            // AVG(rating) WHERE rating > 0
  "by_type":   [{"type": "Red Wine", "bottles": 20, "wines": 8}, ...],   // GROUP BY type, English, qty desc
  "by_region": [{"region": "Bordeaux", "bottles": 12}, ...],             // GROUP BY region, qty desc
  "by_grape":  [{"grape": "Merlot", "bottles": 9}, ...],                 // GROUP BY grape, qty desc
  "by_decade": [{"decade": 2010, "bottles": 15}, ...]                    // (year/10)*10, asc
}
```

- `by_type` / `by_region` / `by_grape` exclude rows whose field is NULL/empty (matches the `/stats` donut).
- Empty cellar → scalars `0` / `0.0`, breakdowns `[]`, `ok: true`.
- Flat top-level scalars so HA `json_attributes` can read them directly.

## Endpoint 2 — `GET /api/drink-window`

Route: `jsonify(ok=True, **compute_drink_window(db, datetime.now().year))`.
Considers only **in-stock** wines (`quantity > 0`). `drink_from` / `drink_until` are INTEGER years.

Bucketing for current year `Y`:

| Window state | Bucket |
|---|---|
| both set, `from ≤ Y ≤ until` | `ready` |
| both set, `Y < from` | `too_young` |
| both set, `Y > until` | `past_peak` |
| only `from` set: `Y ≥ from` → `ready`, else `too_young` | (no upper bound) |
| only `until` set: `Y ≤ until` → `ready`, else `past_peak` | (no lower bound) |
| neither set | `unknown` |

Sort within buckets: `ready` by `drink_until` asc (soonest to expire first), `too_young` by
`drink_from` asc, `past_peak` by `drink_until` asc, `unknown` by name.

```json
{
  "ok": true,
  "current_year": 2026,
  "ready_now": 12,              // == len(ready), convenience scalar for value_template
  "entering_this_year": 1,      // count of in-stock wines with drink_from == 2026
  "leaving_this_year": 2,       // count of in-stock wines with drink_until == 2026
  "counts": {"ready": 12, "too_young": 5, "past_peak": 2, "unknown": 3},
  "ready":     [{"id":1,"name":"…","year":2018,"type":"Red Wine","quantity":2,"drink_from":2022,"drink_until":2028,"location":"Keller A"}, ...],
  "too_young": [ ... ],
  "past_peak": [ ... ],
  "unknown":   [ ... ]
}
```

Each entry: `{id, name, year, type (English), quantity, drink_from, drink_until, location}`.

## Endpoint 3 — `GET /api/wines`

Route: `jsonify(ok=True, **query_wines(db, request.args))`.

Filters (all optional, ANDed, lenient — ignored if blank/uninterpretable):

| Param | Effect |
|---|---|
| `type` | English label (case-insensitive) resolved back to the stored key; falls back to raw match. `type = ?` |
| `region` | substring, case-insensitive: `region LIKE %v%` |
| `grape` | substring, case-insensitive: `grape LIKE %v%` |
| `year` | exact `year = ?` (int; ignored if non-numeric) |
| `in_stock` | `true`/`1` → `quantity > 0` |
| `min_rating` | `rating >= ?` (int; ignored if non-numeric) |

Sort: `sort` ∈ {`name`,`year`,`rating`,`price`,`added`,`quantity`} (default `name`, invalid → `name`);
`order` ∈ {`asc`,`desc`} (default `asc`). Secondary sort by `name` for stable ordering.

Pagination: `limit` (int 1–500; otherwise no limit), `offset` (int ≥ 0; default 0). `count` is the
total matching the filters **before** limit/offset; `returned` is the page size.

```
GET /api/wines?type=Red%20Wine&in_stock=true&sort=year&order=desc&limit=50
→ { "ok": true, "count": 18, "returned": 18, "wines": [ <light record>, ... ] }
```

Light record = **every `wines` column except** `maturity_data` / `taste_profile` / `food_pairings`,
with `type` in English and `image_path` added — i.e. `serialize_wine(row, full=False)`. Concretely:
`id, name, year, type (English), region, quantity, rating, notes, image, image_path, added,
purchased_at, price, drink_from, drink_until, location, grape, vivino_id, bottle_format`. The three
AI JSON blobs are returned **only** by `/api/wines/<id>`.

## Endpoint 4 — `GET /api/wines/<int:wine_id>`

```python
row = db.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()
if not row:
    return jsonify(ok=False, error="not_found"), 404
return jsonify(ok=True, wine=api_queries.serialize_wine(row, full=True))
```

Full record = every column, `type` in English, `image_path` added, and `maturity_data` /
`taste_profile` / `food_pairings` parsed from JSON text into objects. This is a **new** endpoint;
the existing `/api/wine/<id>` (singular, raw type) stays untouched for the UI's JS.

## Auth / readonly

No code changes. `check_auth` (`app.py:345`) already gates every `/api/*` path uniformly. All four
endpoints are GET, so `check_readonly` (`app.py:358`) never blocks them. Behavior is identical to
`/api/summary` today (decision 3).

## Tests — `wine-tracker/tests/test_api_ha.py`

Reuse existing fixtures (`client`, `db`, `sample_wine`, `_patch_env`). Two layers: direct calls to
`api_queries` pure functions for boundary logic, plus Flask-client calls for the routes/envelope.

**stats**
- Empty DB → all scalars 0, breakdowns `[]`, `ok:true`, `currency` present.
- Populated → correct `total_bottles`, `total_liters`, `total_value`, `avg_age`, `avg_rating`.
- `by_type` uses English (`"Red Wine"`); `by_region` / `by_grape` / `by_decade` correct & ordered.
- NULL/empty type, region, grape excluded from breakdowns.

**drink-window** (drive `current_year` via the pure function for determinism)
- `from ≤ Y ≤ until` → `ready`; `Y < from` → `too_young`; `Y > until` → `past_peak`; no window → `unknown`.
- one-sided windows (only `from`, only `until`) bucket per the table.
- `entering_this_year` / `leaving_this_year` counted on year boundaries.
- `quantity = 0` excluded. `counts`, `ready_now`, English labels correct.

**wines list**
- Returns all; light projection (asserts `maturity_data`/`taste_profile`/`food_pairings` keys absent).
- `type=Red Wine` matches `Rotwein` rows; `region`/`grape` substring; `year`; `in_stock=true` excludes qty 0; `min_rating`.
- `sort=year&order=desc` ordering; invalid `sort` → falls back, still `ok:true` (no 400).
- `limit`/`offset` → `count` vs `returned`. `image_path` present when image set. English `type` per record.

**wines detail**
- Existing id → `ok:true`, `type` English, `image_path`, `maturity_data` parsed to an object (not a string).
- Missing id → `404`, `{"ok": false, "error": "not_found"}`.

**auth regression**
- With `AUTH_ENABLED=true` and no session, `GET /api/stats` → `401` (mirrors the existing
  `/api/summary` auth-gate test pattern in `test_api.py`).

## Docs

- **README.md** "Home Assistant Sensor" section: add a `/api/stats` REST sensor (with
  `json_attributes`), a `/api/drink-window` template sensor + a "wines entering their window"
  notification automation, and a one-line mention of `/api/wines` for markdown-card lists.
- **CHANGELOG.md**: add an entry for the new endpoints (next minor, 1.11.0).
- **wine-tracker/DOCS.md**: mirror the sensor examples if it documents the API (optional).

## Out of scope

- Any write endpoint (create / update / delete / consume / restock) — read-only v1.
- API-token / bearer auth — explicitly rejected (decision 3).
- `/v1/` versioning prefix.
- Refactoring the `/stats` HTML page to share `compute_stats` (touching working UI = risk, no payoff).
- CORS headers (no separate-origin frontend in scope).
- Changing `/api/summary`, `/api/wine/<id>`, or `/api/timeline`.
- OpenAPI/Swagger discovery endpoint.
- Returning the raw stored `type` alongside English (decision 4 chose English-only).
