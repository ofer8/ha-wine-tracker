# Duplicate detection on the add flow — design

**Date:** 2026-06-21
**Status:** Approved (pending implementation)

## Problem

Adding a wine via the AI label feature (or Vivino search, or manually) always inserts
a new row through `POST /add`. There is no check against the existing cellar, so re-adding
a wine you already own produces a second card instead of bumping its quantity. Deduplication
currently exists **only** in the ZIP/CSV restore path (`match_wines()` in `export_import.py`),
never in the normal add flow.

This adds opt-in duplicate detection to `POST /add` so the user is asked what to do when an
incoming wine matches one already in the cellar.

## Scope

- Lives entirely in `POST /add`, so it covers **all** add paths (AI, Vivino, manual) at once.
- `/edit` and `/duplicate` are untouched. (`/duplicate` is intentional cloning.)
- No schema change. No new columns.

## Matching rule

A wine is "the same" when **all three** match:

- `name` — case-insensitive, whitespace-trimmed on both sides
- `year` (vintage)
- `bottle_format`

A different vintage **or** a different bottle size is a distinct cellar entry and does **not** match.

Match query (most-recent first, first row wins):

```sql
SELECT id, name, year, bottle_format, quantity, location
FROM wines
WHERE TRIM(name) = TRIM(?) COLLATE NOCASE
  AND year IS ?
  AND bottle_format = ?
ORDER BY id DESC
LIMIT 1
```

Notes:
- Matches **regardless of quantity**, so an empty-bottle placeholder (quantity 0) of the same
  wine gets restocked rather than duplicated.
- `year IS ?` handles the NULL-vintage case correctly (`NULL IS NULL` is true in SQLite).
- `bottle_format` defaults to `0.75` on insert when the form value is empty; the form always
  submits a value, so the comparison is stable.
- If multiple separate entries share the same name/year/format (e.g. different storage
  locations), the most recent one is offered. The dialog shows its `location` so the user can
  choose "Add as separate entry" if it is the wrong one. Resolving multi-match precisely is out
  of scope for v1.

## Mechanism — two-phase `/add`

`/add` gains one optional form field, `dup_action`:

| `dup_action` | Behavior |
|---|---|
| _(empty, default)_ | Run the match query. **If a match exists, do not insert** — return `{"ok": false, "duplicate": {...}}`. If no match, insert as today. |
| `"separate"` | Skip the check entirely; insert a new row as today. |
| `"merge"` (with `dup_target_id`) | Increment the target wine's `quantity` by the form quantity, log a `restocked` timeline entry, return `{"ok": true, "wine": ..., "stats": ...}`. |

The `duplicate` payload returned in phase one:

```json
{
  "ok": false,
  "duplicate": {
    "id": 12,
    "name": "Château Test",
    "year": 2018,
    "bottle_format": 0.75,
    "quantity": 3,
    "location": "Keller A"
  }
}
```

### Merge semantics (decision: quantity only)

On `merge`, only the quantity changes. All other form fields (notes, rating, maturity data,
price, location, image, etc.) are **ignored** — the existing card stays the source of truth.
Enriching an existing wine is already covered by the separate "Reload missing data" feature.

Increment amount = the `quantity` field from the form (so adding 2 bottles bumps 3 → 5).
The timeline entry mirrors the existing edit-route pattern (`app.py:905-909`):

```python
db.execute(
    "INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
    (target_id, "restocked", added_qty, datetime.now().isoformat()),
)
```

### Readonly / auth

`merge` and `separate` are write operations and must pass the same `check_readonly()` /
`check_auth()` gates the rest of `/add` already enforces. No special-casing needed since they
flow through the same route.

## Frontend — add-form submit (`index.html`)

The existing add-form submit posts a `FormData` to `/add` via fetch and updates the UI on
`ok:true`. Change the response handling:

1. On `{ok:false, duplicate}` → show a confirm dialog (reusing the app's existing modal/dialog
   styling, theme-aware per `STYLE_GUIDE.md`) showing:
   `You already have {quantity}× {name} {year} ({bottle_format}l) in {location}.`
   with three buttons:
   - **Add to existing (now N)** → re-POST the same FormData with `dup_action=merge` and
     `dup_target_id=<id>`.
   - **Add as separate entry** → re-POST the same FormData with `dup_action=separate`.
   - **Cancel** → close dialog, leave the add form open and untouched.
2. On `{ok:false}` with any other error → existing error handling, unchanged.
3. On `{ok:true}` → existing success handling, unchanged.

All three button labels and the dialog body text go through `translations.py` for all 7
languages (new keys, e.g. `dup_detect_title`, `dup_detect_body`, `dup_detect_merge`,
`dup_detect_separate`, `dup_detect_cancel`).

## Tests (`tests/test_routes.py`)

- No existing wine → `/add` inserts normally, `ok:true` (regression).
- Matching wine, no `dup_action` → `ok:false` with correct `duplicate` payload; **no new row** inserted.
- `dup_action=merge` + `dup_target_id` → target quantity increased by form quantity; a
  `restocked` timeline row is written; no new wine row.
- `dup_action=separate` → a second row is inserted despite the match.
- Case-insensitive + whitespace match: `"  château test "` matches `"Château Test"`.
- Different `year` → no match (inserts).
- Different `bottle_format` → no match (inserts).
- NULL-vintage match: two wines with `year=NULL`, same name/format → match.
- Empty-bottle restock: existing match with `quantity=0`, merge → quantity becomes the form qty.

## Out of scope

- Field backfill on merge (option B from brainstorming) — explicitly rejected for v1.
- Multi-match disambiguation UI.
- Dedup on `/edit`.
- Changing the import (`match_wines`) behavior.
