# Add-Flow Duplicate Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /add` detect when an incoming wine matches one already in the cellar and let the user merge (bump quantity) or insert separately, instead of always inserting a duplicate.

**Architecture:** Two-phase `/add` driven by a new optional `dup_action` form field. Phase one (no `dup_action`) runs a match query and returns `{ok:false, duplicate:{...}}` without inserting when a match exists. The frontend shows a confirm dialog whose buttons re-POST the same form with `dup_action=merge` (+`dup_target_id`) or `dup_action=separate`. Merge bumps the existing wine's quantity and logs a `restocked` timeline entry. Covers all add paths (AI, Vivino, manual) since they all submit `wineForm` to `/add`.

**Tech Stack:** Python 3.12 / Flask, SQLite, vanilla JS templates (Jinja2), pytest. All Python commands run from `wine-tracker/`.

## Global Constraints

- All Python work runs from the `wine-tracker/` directory.
- Match rule: `name` (whitespace-trimmed, case-insensitive) **AND** `year` **AND** `bottle_format`. A different vintage or bottle size is NOT a match.
- Merge changes **quantity only**; all other form fields are ignored on merge.
- The match query must match regardless of quantity (so empty-bottle placeholders restock).
- `/edit` and `/duplicate` routes must NOT gain dedup behavior. Only `/add`.
- Every user-facing string goes through `app/translations.py` for all 7 languages (`de, en, fr, it, es, pt, nl`) — no hardcoded UI text.
- UI/CSS must reuse existing theme-aware classes (`modal-overlay`, `modal`, `modal-header`, `btn-cancel`, etc.) per `STYLE_GUIDE.md` — no hardcoded theme colors.
- Restock timeline entry mirrors the existing edit-route pattern (`app/app.py:905-909`): `INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?, "restocked", <added_qty>, datetime.now().isoformat())`.

---

## File Structure

- `wine-tracker/app/app.py` — `/add` route (`app.py:755-811`): add `dup_action` branching, the match query, and the merge branch. Add a small helper `_find_duplicate_wine(db, name, year, bottle_format)`.
- `wine-tracker/app/translations.py` — new keys in all 7 language dicts.
- `wine-tracker/app/templates/index.html` — new confirm-dialog modal markup (next to `deleteModal`, ~line 227).
- `wine-tracker/app/templates/_wine_edit_modal.html` — extend the `wineForm` submit handler (`_wine_edit_modal.html:836-854`) to intercept the duplicate response; add the dialog-button handler functions.
- `wine-tracker/tests/test_routes.py` — new backend tests.

---

### Task 1: Backend — match helper + two-phase `/add`

**Files:**
- Modify: `wine-tracker/app/app.py` (route `add()` at `app.py:755-811`; add helper just above it)
- Test: `wine-tracker/tests/test_routes.py`

**Interfaces:**
- Consumes: `get_db()`, `wine_json(id)`, `stats_json()`, `is_ajax()`, `datetime`, `date` (all already imported/defined in `app.py`).
- Produces:
  - `_find_duplicate_wine(db, name, year, bottle_format) -> sqlite3.Row | None` — returns the most-recent matching wine row or `None`.
  - `POST /add` now reads form field `dup_action` (`""` | `"separate"` | `"merge"`) and `dup_target_id` (int, required when `dup_action="merge"`).
  - Phase-one duplicate response shape: `{"ok": false, "duplicate": {"id", "name", "year", "bottle_format", "quantity", "location"}}` (HTTP 200).
  - Merge success response: `{"ok": true, "wine": <wine_json>, "stats": <stats_json>}`.

- [ ] **Step 1: Write the failing tests**

Add to `wine-tracker/tests/test_routes.py`:

```python
def _add_wine(client, **overrides):
    data = {
        "name": "Château Test", "year": "2018", "type": "Rotwein",
        "region": "Bordeaux, FR", "quantity": "1", "rating": "0",
        "bottle_format": "0.75",
    }
    data.update(overrides)
    return client.post("/add", data=data,
                       headers={"X-Requested-With": "XMLHttpRequest"})


def test_add_no_existing_inserts_normally(client, db):
    resp = _add_wine(client, quantity="2")
    body = json.loads(resp.data)
    assert body["ok"] is True
    rows = db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()
    assert rows["c"] == 1


def test_add_matching_wine_returns_duplicate_without_inserting(client, db):
    _add_wine(client, quantity="3")
    resp = _add_wine(client, quantity="1")
    body = json.loads(resp.data)
    assert body["ok"] is False
    assert body["duplicate"]["name"] == "Château Test"
    assert body["duplicate"]["year"] == 2018
    assert body["duplicate"]["quantity"] == 3
    # Still only ONE row — phase one must not insert
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 1


def test_add_merge_bumps_quantity_and_logs_restock(client, db):
    first = json.loads(_add_wine(client, quantity="3").data)
    target_id = first["wine"]["id"]
    resp = _add_wine(client, quantity="2", dup_action="merge",
                     dup_target_id=str(target_id))
    body = json.loads(resp.data)
    assert body["ok"] is True
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 1
    qty = db.execute("SELECT quantity FROM wines WHERE id=?", (target_id,)).fetchone()["quantity"]
    assert qty == 5
    restock = db.execute(
        "SELECT quantity FROM timeline WHERE wine_id=? AND action='restocked'",
        (target_id,)).fetchone()
    assert restock["quantity"] == 2


def test_add_separate_inserts_second_row(client, db):
    _add_wine(client, quantity="1")
    resp = _add_wine(client, quantity="1", dup_action="separate")
    assert json.loads(resp.data)["ok"] is True
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 2


def test_add_match_is_case_and_whitespace_insensitive(client, db):
    _add_wine(client, name="Château Test", quantity="1")
    resp = _add_wine(client, name="  château test ", quantity="1")
    assert json.loads(resp.data)["ok"] is False


def test_add_different_year_is_not_a_match(client, db):
    _add_wine(client, year="2018", quantity="1")
    resp = _add_wine(client, year="2019", quantity="1")
    assert json.loads(resp.data)["ok"] is True
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 2


def test_add_different_bottle_format_is_not_a_match(client, db):
    _add_wine(client, bottle_format="0.75", quantity="1")
    resp = _add_wine(client, bottle_format="1.5", quantity="1")
    assert json.loads(resp.data)["ok"] is True
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 2


def test_add_null_vintage_wines_match(client, db):
    _add_wine(client, year="", quantity="1")
    resp = _add_wine(client, year="", quantity="1")
    assert json.loads(resp.data)["ok"] is False
    assert db.execute("SELECT COUNT(*) AS c FROM wines").fetchone()["c"] == 1


def test_add_merge_restocks_empty_bottle(client, db):
    first = json.loads(_add_wine(client, quantity="1").data)
    target_id = first["wine"]["id"]
    db.execute("UPDATE wines SET quantity=0 WHERE id=?", (target_id,))
    db.commit()
    _add_wine(client, quantity="2", dup_action="merge", dup_target_id=str(target_id))
    qty = db.execute("SELECT quantity FROM wines WHERE id=?", (target_id,)).fetchone()["quantity"]
    assert qty == 2
```

Make sure `import json` is present at the top of `test_routes.py` (it is used elsewhere; add if missing).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd wine-tracker && pytest tests/test_routes.py -k "test_add_no_existing or test_add_matching or test_add_merge or test_add_separate or test_add_match_is_case or test_add_different or test_add_null or test_add_merge_restocks" -v`
Expected: FAIL (new behavior not implemented — e.g. `test_add_matching_wine_returns_duplicate_without_inserting` fails because `ok` is `True`).

- [ ] **Step 3: Add the `_find_duplicate_wine` helper**

Insert directly above `@app.route("/add", methods=["POST"])` (currently `app.py:755`):

```python
def _find_duplicate_wine(db, name, year, bottle_format):
    """Return the most-recent wine matching name (trimmed, case-insensitive),
    year, and bottle_format -- regardless of quantity -- or None."""
    return db.execute(
        """SELECT id, name, year, bottle_format, quantity, location
           FROM wines
           WHERE TRIM(name) = TRIM(?) COLLATE NOCASE
             AND year IS ?
             AND bottle_format = ?
           ORDER BY id DESC
           LIMIT 1""",
        (name, year, bottle_format),
    ).fetchone()
```

- [ ] **Step 4: Rewrite the `add()` route to be two-phase**

Replace the body of `add()` (`app.py:756-811`) with:

```python
def add():
    db = get_db()
    dup_action = request.form.get("dup_action", "").strip()

    # Normalize the same values the matcher and INSERT use.
    name = request.form["name"].strip()
    year = request.form.get("year") or None
    bottle_format_raw = request.form.get("bottle_format", "").strip()
    bottle_format = float(bottle_format_raw) if bottle_format_raw else 0.75
    qty = int(request.form.get("quantity", 1))

    # ── Merge: bump an existing wine's quantity, log a restock ──
    if dup_action == "merge":
        target_id = request.form.get("dup_target_id", "").strip()
        target = db.execute(
            "SELECT id, quantity FROM wines WHERE id=?", (target_id,)
        ).fetchone() if target_id else None
        if not target:
            return jsonify({"ok": False, "error": "merge_target_missing"}), 400
        db.execute(
            "UPDATE wines SET quantity = quantity + ? WHERE id=?",
            (qty, target["id"]),
        )
        db.execute(
            "INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
            (target["id"], "restocked", qty, datetime.now().isoformat()),
        )
        db.commit()
        if is_ajax():
            return jsonify({"ok": True, "wine": wine_json(target["id"]), "stats": stats_json()})
        return redirect(g.get("ingress", "") + url_for("index"))

    # ── Phase one: unless the user already chose "separate", look for a dup ──
    if dup_action != "separate":
        existing = _find_duplicate_wine(db, name, year, bottle_format)
        if existing:
            return jsonify({"ok": False, "duplicate": {
                "id": existing["id"],
                "name": existing["name"],
                "year": existing["year"],
                "bottle_format": existing["bottle_format"],
                "quantity": existing["quantity"],
                "location": existing["location"],
            }})

    # ── Insert (no match, or user chose "separate") ──
    image = save_image(request.files.get("image"))
    # If no new image uploaded but AI already saved one, use that
    if not image:
        ai_img = request.form.get("ai_image", "").strip()
        if ai_img and os.path.isfile(os.path.join(UPLOAD_DIR, ai_img)):
            image = ai_img
    price_raw = request.form.get("price", "").strip()
    vivino_raw = request.form.get("vivino_id", "").strip()
    maturity_data_raw = request.form.get("maturity_data", "").strip() or None
    taste_profile_raw = request.form.get("taste_profile", "").strip() or None
    food_pairings_raw = request.form.get("food_pairings", "").strip() or None
    cur = db.execute(
        """INSERT INTO wines
           (name, year, type, region, quantity, rating, notes, image, added,
            purchased_at, price, drink_from, drink_until, location, grape, vivino_id, bottle_format,
            maturity_data, taste_profile, food_pairings)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            year,
            request.form.get("type"),
            request.form.get("region", "").strip(),
            qty,
            int(request.form.get("rating", 0)),
            request.form.get("notes", "").strip(),
            image,
            str(date.today()),
            request.form.get("purchased_at", "").strip() or None,
            float(price_raw) if price_raw else None,
            request.form.get("drink_from") or None,
            request.form.get("drink_until") or None,
            request.form.get("location", "").strip() or None,
            request.form.get("grape", "").strip() or None,
            int(vivino_raw) if vivino_raw else None,
            bottle_format,
            maturity_data_raw,
            taste_profile_raw,
            food_pairings_raw,
        ),
    )
    db.commit()
    new_id = cur.lastrowid
    db.execute(
        "INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
        (new_id, "added", qty, datetime.now().isoformat()),
    )
    db.commit()
    if is_ajax():
        return jsonify({"ok": True, "wine": wine_json(new_id), "stats": stats_json()})
    path = g.get("ingress", "") + url_for("index") + f"?new={new_id}"
    return redirect(path)
```

Note: this preserves the original insert logic verbatim except that `name`, `year`, `bottle_format`, and `qty` are now computed once at the top and reused.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd wine-tracker && pytest tests/test_routes.py -k "test_add_no_existing or test_add_matching or test_add_merge or test_add_separate or test_add_match_is_case or test_add_different or test_add_null or test_add_merge_restocks" -v`
Expected: PASS (all 9).

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `cd wine-tracker && pytest tests/ -q`
Expected: PASS (pre-existing add tests still green; the `sample_wine` fixture adds a unique wine so it is unaffected).

- [ ] **Step 7: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_routes.py
git commit -m "Add duplicate detection to /add route (merge/separate/detect)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Translations for the confirm dialog

**Files:**
- Modify: `wine-tracker/app/translations.py` (all 7 language dicts)
- Test: `wine-tracker/tests/test_routes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: 5 new keys in every language dict: `dup_detect_title`, `dup_detect_body`, `dup_detect_merge`, `dup_detect_separate`, `dup_detect_cancel`. `dup_detect_body` contains the placeholder tokens `{qty}`, `{name}`, `{year}`, `{format}`, `{location}` which the frontend substitutes; `dup_detect_merge` contains `{n}` for the resulting quantity.

- [ ] **Step 1: Write the failing test**

Add to `wine-tracker/tests/test_routes.py`:

```python
def test_translations_have_dup_detect_keys():
    import translations
    keys = ["dup_detect_title", "dup_detect_body", "dup_detect_merge",
            "dup_detect_separate", "dup_detect_cancel"]
    for lang, d in translations.TRANSLATIONS.items():
        for k in keys:
            assert k in d, f"{lang} missing {k}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd wine-tracker && pytest tests/test_routes.py::test_translations_have_dup_detect_keys -v`
Expected: FAIL with AssertionError "de missing dup_detect_title".

- [ ] **Step 3: Add the keys to each language dict**

In `app/translations.py`, add these entries inside each language block (place them near the existing `dup_*` / delete keys for consistency). Use the exact values below.

German (`"de"`):
```python
    "dup_detect_title": "Wein bereits vorhanden",
    "dup_detect_body": "Du hast bereits {qty}x {name} {year} ({format}l) in {location}.",
    "dup_detect_merge": "Zum vorhandenen hinzufügen (jetzt {n})",
    "dup_detect_separate": "Als separaten Eintrag hinzufügen",
    "dup_detect_cancel": "Abbrechen",
```

English (`"en"`):
```python
    "dup_detect_title": "Wine already in cellar",
    "dup_detect_body": "You already have {qty}x {name} {year} ({format}l) in {location}.",
    "dup_detect_merge": "Add to existing (now {n})",
    "dup_detect_separate": "Add as separate entry",
    "dup_detect_cancel": "Cancel",
```

French (`"fr"`):
```python
    "dup_detect_title": "Vin déjà en cave",
    "dup_detect_body": "Vous avez déjà {qty}x {name} {year} ({format}l) dans {location}.",
    "dup_detect_merge": "Ajouter à l'existant (désormais {n})",
    "dup_detect_separate": "Ajouter comme entrée séparée",
    "dup_detect_cancel": "Annuler",
```

Italian (`"it"`):
```python
    "dup_detect_title": "Vino già in cantina",
    "dup_detect_body": "Hai già {qty}x {name} {year} ({format}l) in {location}.",
    "dup_detect_merge": "Aggiungi all'esistente (ora {n})",
    "dup_detect_separate": "Aggiungi come voce separata",
    "dup_detect_cancel": "Annulla",
```

Spanish (`"es"`):
```python
    "dup_detect_title": "Vino ya en la bodega",
    "dup_detect_body": "Ya tienes {qty}x {name} {year} ({format}l) en {location}.",
    "dup_detect_merge": "Añadir al existente (ahora {n})",
    "dup_detect_separate": "Añadir como entrada separada",
    "dup_detect_cancel": "Cancelar",
```

Portuguese (`"pt"`):
```python
    "dup_detect_title": "Vinho já na adega",
    "dup_detect_body": "Você já tem {qty}x {name} {year} ({format}l) em {location}.",
    "dup_detect_merge": "Adicionar ao existente (agora {n})",
    "dup_detect_separate": "Adicionar como entrada separada",
    "dup_detect_cancel": "Cancelar",
```

Dutch (`"nl"`):
```python
    "dup_detect_title": "Wijn al in kelder",
    "dup_detect_body": "Je hebt al {qty}x {name} {year} ({format}l) in {location}.",
    "dup_detect_merge": "Aan bestaande toevoegen (nu {n})",
    "dup_detect_separate": "Als aparte vermelding toevoegen",
    "dup_detect_cancel": "Annuleren",
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd wine-tracker && pytest tests/test_routes.py::test_translations_have_dup_detect_keys -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/translations.py wine-tracker/tests/test_routes.py
git commit -m "Add dup-detect dialog strings for all 7 languages

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend — confirm dialog markup + submit interception

**Files:**
- Modify: `wine-tracker/app/templates/index.html` (add modal markup after `deleteModal`, ~line 227)
- Modify: `wine-tracker/app/templates/_wine_edit_modal.html` (submit handler at lines 836-854; add handler functions)

**Interfaces:**
- Consumes: backend phase-one response `{ok:false, duplicate:{id,name,year,bottle_format,quantity,location}}`; `window.T` translation dict; existing `openModal(id)` / `closeModal(id)` (`index.html:692,711`); existing `window._onWineSaved(data)` success path.
- Produces: a `#dupDetectModal` overlay; JS functions `showDupDetectDialog(form, dup)`, `dupMerge()`, `dupSeparate()` on `window`.

- [ ] **Step 1: Add the dialog markup**

In `index.html`, immediately after the `deleteModal` block (after line 227, before the WINE VIEW MODAL comment), add:

```html
<!-- ═══════════════ DUPLICATE-DETECT MODAL ═══════════════ -->
<div class="modal-overlay" id="dupDetectModal">
  <div class="modal" style="max-width:380px">
    <div class="modal-header">
      {{ t.dup_detect_title }}
      <button class="modal-close" onclick="closeModal('dupDetectModal')">×</button>
    </div>
    <div class="delete-confirm-body">
      <div class="delete-confirm-icon"><i class="mdi mdi-bottle-wine"></i></div>
      <div class="delete-confirm-msg" id="dupDetectBody"></div>
    </div>
    <div class="delete-confirm-actions" style="flex-direction:column; gap:8px">
      <button class="btn-submit" id="dupMergeBtn" onclick="dupMerge()" style="width:100%"></button>
      <button class="btn-cancel" onclick="dupSeparate()" style="width:100%">{{ t.dup_detect_separate }}</button>
      <button class="btn-cancel" onclick="closeModal('dupDetectModal')" style="width:100%">{{ t.dup_detect_cancel }}</button>
    </div>
  </div>
</div>
```

(Reuses existing theme-aware classes `modal-overlay`, `modal`, `modal-header`, `delete-confirm-body`, `delete-confirm-actions`, `btn-submit` (the primary Save-button class, `_wine_edit_modal.html:145` / `style.css:870`), `btn-cancel`.)

- [ ] **Step 2: Intercept the duplicate response in the submit handler**

In `_wine_edit_modal.html`, replace the submit handler body (lines 836-854) with:

```javascript
var _dupPendingForm = null;
var _dupPending = null;

document.getElementById('wineForm').addEventListener('submit', function(e) {
  e.preventDefault();
  var form = this;
  submitWineForm(form, null);
});

function submitWineForm(form, dupAction, targetId) {
  var fd = new FormData(form);
  if (dupAction) {
    fd.set('dup_action', dupAction);
    if (targetId != null) fd.set('dup_target_id', targetId);
  }
  fetch(form.action, {
    method: 'POST', body: fd,
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    // Duplicate detected on an /add submit -> ask the user.
    if (!data.ok && data.duplicate) {
      showDupDetectDialog(form, data.duplicate);
      return;
    }
    if (!data.ok) return;
    closeModal('dupDetectModal');
    closeModal('wineModal');
    if (typeof window._onWineSaved === 'function') {
      window._onWineSaved(data);
    } else {
      window.location.reload();
    }
  });
}

function showDupDetectDialog(form, dup) {
  _dupPendingForm = form;
  _dupPending = dup;
  var addedQty = parseInt(new FormData(form).get('quantity') || '1', 10) || 1;
  var fmt = String(dup.bottle_format != null ? dup.bottle_format : '');
  var body = (window.T.dup_detect_body || '')
    .replace('{qty}', dup.quantity)
    .replace('{name}', dup.name || '')
    .replace('{year}', dup.year || '')
    .replace('{format}', fmt)
    .replace('{location}', dup.location || '-');
  document.getElementById('dupDetectBody').textContent = body;
  document.getElementById('dupMergeBtn').textContent =
    (window.T.dup_detect_merge || '').replace('{n}', dup.quantity + addedQty);
  openModal('dupDetectModal');
}

function dupMerge() {
  if (_dupPendingForm && _dupPending) {
    submitWineForm(_dupPendingForm, 'merge', _dupPending.id);
  }
}

function dupSeparate() {
  if (_dupPendingForm) {
    submitWineForm(_dupPendingForm, 'separate');
  }
}
```

Note: `closeModal('dupDetectModal')` is called on success so the dialog closes after a merge/separate completes. The `dupDetectModal` lives in `index.html` and `openModal`/`closeModal` are global, so they are reachable from this included template.

- [ ] **Step 3: Manual verification (no automated frontend test in this repo)**

Run the dev server and exercise the flow:

```bash
cd /Users/ofer/conductor/workspaces/ha-wine-tracker/riyadh && ./scripts/run-dev.sh
```

Then in the browser at http://localhost:5050:
1. Add a wine "Verify Wine" 2018, 0.75l, qty 2 → it appears.
2. Add "Verify Wine" 2018, 0.75l, qty 1 again → the duplicate dialog appears showing "You already have 2x Verify Wine 2018 (0.75l) in ...", merge button reads "Add to existing (now 3)".
3. Click merge → card quantity becomes 3, no second card.
4. Repeat add, click "Add as separate entry" → a second card appears.
5. Add a different vintage 2019 → inserts directly, no dialog.

Expected: all five behave as described. Stop the server with Ctrl-C.

- [ ] **Step 4: Run the full test suite (ensure backend still green)**

Run: `cd wine-tracker && pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/templates/index.html wine-tracker/app/templates/_wine_edit_modal.html
git commit -m "Add duplicate-detect confirm dialog to the add flow

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** match rule (Task 1 helper + tests), two-phase `/add` (Task 1), merge = quantity only + restock timeline (Task 1), empty-bottle restock (Task 1 test), all 7 languages (Task 2), three-button dialog reusing theme classes (Task 3), `/edit` & `/duplicate` untouched (only `add()` changed). All covered.
- **Edit route unaffected:** the new `submitWineForm` is shared by add and edit, but `dup_action` is only ever sent by the dialog buttons, and the backend only inspects `dup_action` in `/add`. `/edit` ignores unknown form fields. Edit submits therefore behave exactly as before.
- **Placeholder scan:** none.
- **Type consistency:** `_find_duplicate_wine` returns a Row consumed only inside `add()`; frontend `dup.id`/`dup.quantity` match the JSON keys produced in Task 1; `{n}`/`{qty}`/`{format}` tokens in Task 2 match the `.replace(...)` calls in Task 3.
- **Button class verified:** the primary Save button uses `btn-submit` (`_wine_edit_modal.html:145`, `style.css:870`); the dialog's merge button reuses it.
