# Buy List + Out-of-Stock (re-buy loop) — Design Spec

- **Date:** 2026-06-22
- **Status:** Approved design, pending spec review
- **Roadmap:** implements Phases 1 + 1b of `.context/ROADMAP.md` (derived from `.context/cork-dork-deep-dive.md`)

## 1. Goal

Add a **Buy List (wishlist)** and an **Out-of-Stock** view to Wine Tracker, connected by a **re-buy loop**: wines that hit `quantity == 0` can be re-bought (added to the wishlist) in one tap, and wishlist items can be moved into the cellar. This is a feature Cork Dork lacks and is architecturally blocked from (it is bottle-discrete with no quantity); our quantity + timeline model makes it natural, so this is a leapfrog rather than a catch-up.

## 2. Guiding principle: AI runs once, at capture

The expensive part (AI label/enrichment analysis) happens **once**, when an item is first captured, and the enrichment data then **travels with the item** through the loop. It is **not** re-run on move/restock. The only exception is a deliberate **vintage change** (see §6).

## 3. Scope

**In scope**
- `buy_list` table (separate from `wines`).
- Single "Buy List" nav hub with two tabs: **Wishlist** and **Out of stock**.
- Add to wishlist via **label photo → AI** (reusing `/api/analyze-wine`) or **manual** entry.
- **Re-buy**: one-tap from an out-of-stock wine → new wishlist item (copies enrichment, no AI).
- **Move to cellar**: editable confirm dialog → create or restock (reusing `_find_duplicate_wine()` + timeline), with the conditional vintage re-run rule.
- "Out of stock" quick filter on the existing Cellar page.
- All new strings in **7 languages**.

**Out of scope (later roadmap phases)**
- Vivino enrichment / auto-enrich on add (Phase 2).
- Barcode scanning (Phase 5).
- HA "out-of-stock count" REST sensor.
- "Running low" threshold (we chose `quantity == 0` only — decision Q1/A).
- Multi-critic AI ratings.

## 4. Data model

New table created in `init_db()` with the existing `CREATE TABLE IF NOT EXISTS` pattern (placed after `filter_presets`). Columns mirror the enrichment-bearing wine fields so a move is a clean copy with no AI re-run:

```sql
CREATE TABLE IF NOT EXISTS buy_list (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    year          INTEGER,
    type          TEXT,
    region        TEXT,
    grape         TEXT,
    price         REAL,                 -- expected / target price
    notes         TEXT,
    image         TEXT,
    bottle_format REAL DEFAULT 0.75,
    desired_qty   INTEGER DEFAULT 1,
    added_at      TEXT,
    -- enrichment carried from capture-time AI so move/restock needs no re-run:
    drink_from    INTEGER,
    drink_until   INTEGER,
    maturity_data TEXT,                 -- JSON
    taste_profile TEXT,                 -- JSON
    food_pairings TEXT                  -- JSON
)
```

Future column additions use the same `PRAGMA table_info` + `ALTER TABLE` migration loop already used for `wines`.

**Images:** wishlist images are saved to the existing `UPLOAD_DIR` with the same upload handling as wines. On **move-to-cellar create**, the image file is **copied** to a new filename and assigned to the new wine, so deleting the wishlist row never orphans a cellar wine's image. Deleting a wishlist item deletes only its own image file.

## 5. Routes

Follows existing conventions: form-POST mutations that redirect, plus small AJAX for one-tap actions (mirroring the existing qty-change AJAX). No new AI endpoints — reuses `/api/analyze-wine` and `/api/reanalyze-wine`.

| Route | Method | Purpose |
|---|---|---|
| `/buy-list` | GET | Render the hub (wishlist items + out-of-stock wines). |
| `/buy-list/add` | POST | Create a wishlist item (supports image upload; fields may come pre-filled from `/api/analyze-wine`). |
| `/buy-list/edit/<id>` | POST | Update a wishlist item. |
| `/buy-list/delete/<id>` | POST | Delete a wishlist item (+ its image file). |
| `/buy-list/move/<id>` | POST | Move to cellar: applies the vintage re-run rule (§6), then `_find_duplicate_wine()` → restock or create, logs timeline, copies image, deletes the wishlist row. |
| `/buy-list/rebuy/<wine_id>` | POST | One-tap: copy a cellar wine's fields **incl. enrichment** into a new wishlist item (`desired_qty=1`). AJAX. |

Out-of-stock data is a simple `SELECT * FROM wines WHERE quantity = 0` (server-rendered into the hub).

## 6. AI behavior (capture-once + vintage re-run)

| Flow | AI behavior |
|---|---|
| Add to wishlist **via label photo** | `/api/analyze-wine` runs **once**; fills visible fields + stores enrichment JSON (`drink_from/until`, `maturity_data`, `taste_profile`, `food_pairings`) on the wishlist row. |
| Add to wishlist **manually** | No AI; enrichment left empty. |
| **Re-buy** (out-of-stock → wishlist) | Copies the wine's existing fields **including enrichment**; the bottle already had AI run when it first entered the cellar → **no AI call**. |
| **Move to cellar**, year unchanged | Carry stored enrichment over verbatim → **no AI call**. |
| **Move to cellar**, **year changed** by user | Re-run `/api/reanalyze-wine` with the new year + context (+ image if present) to regenerate vintage-dependent enrichment, then create/restock. |

**The rule (exact):** on `/buy-list/move/<id>`, the submitted `year` is compared to the wishlist item's original `year` (passed as a hidden `original_year`). Different → re-analyze with the new year; same → no AI.

Edge cases:
- **Year changed but no AI provider configured:** proceed with the carried (now-stale-for-the-new-vintage) enrichment; do not block the move. User can edit later.
- **Restock path (duplicate found):** the existing cellar wine keeps its own enrichment; the wishlist item's enrichment is not used to overwrite it. Quantity increases by `desired_qty`; timeline `restocked`.
- **Create path (no duplicate):** new wine gets the wishlist fields + (possibly re-analyzed) enrichment; quantity = `desired_qty`; timeline `added`.

## 7. UI

- **Nav:** one new item **"Buy List"** added to the top nav links, hamburger `nav-menu`, and the mobile `bottom-tab-bar` (a 5th tab) across the four page headers (`index.html`, `chat.html`, `timeline.html`, `stats.html`), following the existing duplicated-header pattern.
- **`buy_list.html`** — its own header (same pattern) + two client-side tabs:
  - **Wishlist tab:** item cards (mirroring wine cards) with **Edit**, **Remove**, **Move to cellar**; a prominent **"+ Add to wishlist"** opening a modal that reuses `_wine_form_fields.html` **plus the label camera/upload + "Analyze label"** control (same UX as add-bottle, calling `/api/analyze-wine`) and a `desired_qty` field.
  - **Out of stock tab:** cellar wines with `quantity == 0`; each row has one-tap **"Re-buy"** (→ wishlist) and a link to the wine.
  - **Move-to-cellar dialog:** editable confirm form pre-filled from the item (incl. enrichment); fields **price / quantity / year** editable; no AI runs on open. On confirm it posts to `/buy-list/move/<id>` (carrying a hidden `original_year`), and the **vintage re-run rule (§6) is applied server-side** in that route — so the AI only fires when the user actually changed the year.
- **Cellar page:** add an **"Out of stock"** entry to the existing filter dropdown that filters cards client-side on `data-quantity == 0` (near-free second entry point).

## 8. Conventions

- All new user-facing strings added to **all 7 languages** in `translations.py` (nav label, tab labels, buttons, dialog title, `desired_qty` label, empty states, confirmations).
- Every template URL prefixed with `{{ ingress }}`.
- Plain hyphens, no em/en-dashes (`STYLE_GUIDE.md`).
- `/api/summary` left untouched (stays English for HA sensors).
- Version bump + cross-file sync happens at **release time** per `CLAUDE.md`, not during the build.

## 9. Testing (TDD; `wine-tracker/tests/`, fresh temp DB per test via `conftest.py`)

1. `init_db()` creates the `buy_list` table with all columns.
2. `POST /buy-list/add` inserts a row; `GET /buy-list` renders it.
3. `POST /buy-list/edit/<id>` updates; `POST /buy-list/delete/<id>` removes the row and its image file.
4. `POST /buy-list/move/<id>` — **create path:** no existing match → new wine with `quantity == desired_qty`, timeline `added`, wishlist row deleted.
5. `POST /buy-list/move/<id>` — **restock path:** matching wine exists (incl. an out-of-stock one) → quantity increases by `desired_qty`, timeline `restocked`, wishlist row deleted.
6. `POST /buy-list/move/<id>` — **same year** → no reanalyze call (mock asserts not called); **changed year** → reanalyze invoked with the new year (mock asserts called).
7. `POST /buy-list/rebuy/<wine_id>` creates a wishlist row copying the wine's fields incl. enrichment.
8. Out-of-stock query/section includes only `quantity == 0` wines.

AI endpoints are reused and mocked in tests (no new AI surface to test beyond the move-dialog year-diff branch).

## 10. Reuse summary (what we are NOT building new)

- Wine form fields → `_wine_form_fields.html`.
- Label photo → AI → `/api/analyze-wine` (existing).
- Vintage re-analyze → `/api/reanalyze-wine` (existing).
- Restock-or-create + timeline → existing `/add` logic + `_find_duplicate_wine()`.
- Image upload/storage → existing `UPLOAD_DIR` handling.

New: one table, one page/template, six thin routes, client-side tab + dialog JS, translations.
