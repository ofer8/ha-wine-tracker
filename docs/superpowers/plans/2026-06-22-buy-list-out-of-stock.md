# Buy List + Out-of-Stock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Buy List (wishlist) and an Out-of-Stock view to Wine Tracker, connected by a re-buy loop, reusing the existing add/analyze/restock machinery.

**Architecture:** A new `buy_list` SQLite table holds wishlist items (mirroring the enrichment-bearing wine fields). A new server-rendered `/buy-list` page exposes two tabs (Wishlist, Out of stock). Mutations are thin Flask routes that reuse existing helpers (`save_image`, `_find_duplicate_wine`, the timeline-insert pattern, `_analyze_wine_from_context`). AI runs once at capture; the move-to-cellar route re-runs AI only when the vintage changed.

**Tech Stack:** Python 3.12, Flask, SQLite, Jinja2 server-rendered templates, vanilla JS. Tests: pytest.

## Global Constraints

- Python 3.12. Run tests from repo root: `.venv/bin/python -m pytest wine-tracker/tests/`
- Spec: `docs/superpowers/specs/2026-06-22-buy-list-out-of-stock-design.md`
- Out of stock means `quantity == 0` only (no running-low threshold).
- AI runs once at capture. The move route re-runs AI **only** when the submitted `year` differs from the item's `original_year`.
- Every new user-facing string must be added to **all 7 languages** (de/en/fr/it/es/pt/nl) in `wine-tracker/app/translations.py`.
- Every template URL must be prefixed with `{{ ingress }}`.
- Plain hyphens only in user-facing text - no em/en-dashes (`STYLE_GUIDE.md`).
- Do **not** modify `/api/summary` (stays English for HA sensors).
- Do **not** bump `version`/`APP_VERSION` - that is a release-time step.
- Reuse, do not reimplement: `save_image(file)`, `_find_duplicate_wine(db, name, year, bottle_format, region, grape, wine_type)`, `_analyze_wine_from_context(opts, image_b64, media_type, wine_context)`, `_load_image_b64(image_filename)`, `_is_ai_configured(opts)`, `is_ajax()`, `stats_json()`, `ingress_redirect(endpoint)`, `load_options()`, and the timeline insert `INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)`.
- `app.py` already imports `os, json, uuid, shutil, sqlite3`, and `from datetime import datetime, date`. No new imports needed except where a step says so.

---

### Task 1: `buy_list` table + migration

**Files:**
- Modify: `wine-tracker/app/app.py` (inside `init_db()`, after the `filter_presets` CREATE TABLE near line 569, before `db.commit()`)
- Test: `wine-tracker/tests/test_buy_list.py` (new)

**Interfaces:**
- Produces: a `buy_list` table with columns `id, name, year, type, region, grape, price, notes, image, bottle_format, desired_qty, added_at, drink_from, drink_until, maturity_data, taste_profile, food_pairings`.

- [ ] **Step 1: Write the failing test**

Create `wine-tracker/tests/test_buy_list.py`:
```python
"""Tests for the Buy List + Out-of-Stock feature."""
import io
import json
import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

APP_DIR = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, APP_DIR)

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


class TestSchema:
    def test_buy_list_table_exists_with_all_columns(self, db):
        cols = _columns(db, "buy_list")
        expected = {
            "id", "name", "year", "type", "region", "grape", "price",
            "notes", "image", "bottle_format", "desired_qty", "added_at",
            "drink_from", "drink_until", "maturity_data", "taste_profile",
            "food_pairings",
        }
        assert expected <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestSchema -v`
Expected: FAIL (`sqlite3.OperationalError: no such table: buy_list`)

- [ ] **Step 3: Add the table to `init_db()`**

In `wine-tracker/app/app.py`, immediately after the `filter_presets` `CREATE TABLE IF NOT EXISTS` block and before `db.commit()`:
```python
        # ── buy_list (wishlist) table ─────────────────────────────────────
        db.execute("""
            CREATE TABLE IF NOT EXISTS buy_list (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                year          INTEGER,
                type          TEXT,
                region        TEXT,
                grape         TEXT,
                price         REAL,
                notes         TEXT,
                image         TEXT,
                bottle_format REAL DEFAULT 0.75,
                desired_qty   INTEGER DEFAULT 1,
                added_at      TEXT,
                drink_from    INTEGER,
                drink_until   INTEGER,
                maturity_data TEXT,
                taste_profile TEXT,
                food_pairings TEXT
            )
        """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestSchema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_buy_list.py
git commit -m "Add buy_list table"
```

---

### Task 2: i18n keys for Buy List (all 7 languages)

**Files:**
- Modify: `wine-tracker/app/translations.py` (add keys inside each of the 7 language dicts)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces translation keys: `nav_buy_list, buy_list_title, tab_wishlist, tab_out_of_stock, btn_add_to_wishlist, label_desired_qty, btn_move_to_cellar, btn_rebuy, empty_wishlist, empty_out_of_stock, move_dialog_title, scan_label` in every language.

- [ ] **Step 1: Write the failing test**

Append to `wine-tracker/tests/test_buy_list.py`:
```python
class TestTranslations:
    def test_buy_list_keys_in_all_languages(self):
        import translations
        keys = [
            "nav_buy_list", "buy_list_title", "tab_wishlist", "tab_out_of_stock",
            "btn_add_to_wishlist", "label_desired_qty", "btn_move_to_cellar",
            "btn_rebuy", "empty_wishlist", "empty_out_of_stock",
            "move_dialog_title", "scan_label",
        ]
        for lang in ("de", "en", "fr", "it", "es", "pt", "nl"):
            for key in keys:
                assert key in translations.TRANSLATIONS[lang], f"{key} missing in {lang}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestTranslations -v`
Expected: FAIL (AssertionError, key missing)

- [ ] **Step 3: Add the keys to each language dict**

In `wine-tracker/app/translations.py`, add the following block near the wine-type keys inside each language's dict. Use the matching language column.

`"de"`:
```python
    "nav_buy_list": "Einkaufsliste",
    "buy_list_title": "Einkaufsliste",
    "tab_wishlist": "Wunschliste",
    "tab_out_of_stock": "Ausverkauft",
    "btn_add_to_wishlist": "Zur Wunschliste",
    "label_desired_qty": "Wunschmenge",
    "btn_move_to_cellar": "In den Keller",
    "btn_rebuy": "Nachkaufen",
    "empty_wishlist": "Deine Wunschliste ist leer.",
    "empty_out_of_stock": "Nichts ist ausverkauft.",
    "move_dialog_title": "Zum Keller hinzufügen",
    "scan_label": "Etikett scannen",
```
`"en"`:
```python
    "nav_buy_list": "Buy List",
    "buy_list_title": "Buy List",
    "tab_wishlist": "Wishlist",
    "tab_out_of_stock": "Out of Stock",
    "btn_add_to_wishlist": "Add to Wishlist",
    "label_desired_qty": "Desired quantity",
    "btn_move_to_cellar": "Move to Cellar",
    "btn_rebuy": "Re-buy",
    "empty_wishlist": "Your wishlist is empty.",
    "empty_out_of_stock": "Nothing is out of stock.",
    "move_dialog_title": "Add to Cellar",
    "scan_label": "Scan label",
```
`"fr"`:
```python
    "nav_buy_list": "Liste d'achat",
    "buy_list_title": "Liste d'achat",
    "tab_wishlist": "Liste de souhaits",
    "tab_out_of_stock": "Épuisé",
    "btn_add_to_wishlist": "Ajouter à la liste",
    "label_desired_qty": "Quantité souhaitée",
    "btn_move_to_cellar": "Déplacer vers la cave",
    "btn_rebuy": "Racheter",
    "empty_wishlist": "Votre liste de souhaits est vide.",
    "empty_out_of_stock": "Rien n'est épuisé.",
    "move_dialog_title": "Ajouter à la cave",
    "scan_label": "Scanner l'étiquette",
```
`"it"`:
```python
    "nav_buy_list": "Lista acquisti",
    "buy_list_title": "Lista acquisti",
    "tab_wishlist": "Lista desideri",
    "tab_out_of_stock": "Esaurito",
    "btn_add_to_wishlist": "Aggiungi alla lista",
    "label_desired_qty": "Quantità desiderata",
    "btn_move_to_cellar": "Sposta in cantina",
    "btn_rebuy": "Ricompra",
    "empty_wishlist": "La tua lista dei desideri è vuota.",
    "empty_out_of_stock": "Niente è esaurito.",
    "move_dialog_title": "Aggiungi alla cantina",
    "scan_label": "Scansiona etichetta",
```
`"es"`:
```python
    "nav_buy_list": "Lista de compra",
    "buy_list_title": "Lista de compra",
    "tab_wishlist": "Lista de deseos",
    "tab_out_of_stock": "Agotado",
    "btn_add_to_wishlist": "Anadir a la lista",
    "label_desired_qty": "Cantidad deseada",
    "btn_move_to_cellar": "Mover a la bodega",
    "btn_rebuy": "Volver a comprar",
    "empty_wishlist": "Tu lista de deseos esta vacia.",
    "empty_out_of_stock": "No hay nada agotado.",
    "move_dialog_title": "Anadir a la bodega",
    "scan_label": "Escanear etiqueta",
```
`"pt"`:
```python
    "nav_buy_list": "Lista de compras",
    "buy_list_title": "Lista de compras",
    "tab_wishlist": "Lista de desejos",
    "tab_out_of_stock": "Esgotado",
    "btn_add_to_wishlist": "Adicionar à lista",
    "label_desired_qty": "Quantidade desejada",
    "btn_move_to_cellar": "Mover para a adega",
    "btn_rebuy": "Comprar de novo",
    "empty_wishlist": "A sua lista de desejos está vazia.",
    "empty_out_of_stock": "Nada esgotado.",
    "move_dialog_title": "Adicionar à adega",
    "scan_label": "Digitalizar rótulo",
```
`"nl"`:
```python
    "nav_buy_list": "Inkooplijst",
    "buy_list_title": "Inkooplijst",
    "tab_wishlist": "Verlanglijst",
    "tab_out_of_stock": "Uitverkocht",
    "btn_add_to_wishlist": "Aan verlanglijst",
    "label_desired_qty": "Gewenste hoeveelheid",
    "btn_move_to_cellar": "Naar de kelder",
    "btn_rebuy": "Opnieuw kopen",
    "empty_wishlist": "Je verlanglijst is leeg.",
    "empty_out_of_stock": "Niets is uitverkocht.",
    "move_dialog_title": "Aan kelder toevoegen",
    "scan_label": "Etiket scannen",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestTranslations -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/translations.py wine-tracker/tests/test_buy_list.py
git commit -m "Add buy-list i18n keys (7 languages)"
```

---

### Task 3: Buy-list helpers + `GET /buy-list` page + nav links

**Files:**
- Modify: `wine-tracker/app/app.py` (add helpers + the route; place after the `index()` route, before `/add`)
- Create: `wine-tracker/app/templates/buy_list.html`
- Modify: `wine-tracker/app/templates/index.html`, `chat.html`, `timeline.html`, `stats.html` (nav links)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: `buy_list_row_to_dict(row)` (dict); `query_out_of_stock(db)` -> list of wine dicts where `quantity == 0`; route `GET /buy-list` rendering `buy_list.html` with `items` (wishlist) and `out_of_stock` (wine dicts).
- Consumes: `get_db()`, the `inject_globals` context (`t`, `ingress`, `ai_enabled`, `wine_types`, `currency`).

- [ ] **Step 1: Write the failing test**

Append to `wine-tracker/tests/test_buy_list.py`:
```python
class TestBuyListPage:
    def test_page_loads(self, client):
        resp = client.get("/buy-list")
        assert resp.status_code == 200

    def test_page_has_both_tabs(self, client):
        resp = client.get("/buy-list")
        assert b'data-tab="wishlist"' in resp.data
        assert b'data-tab="out-of-stock"' in resp.data

    def test_out_of_stock_lists_only_zero_qty(self, client, db):
        db.execute(
            "INSERT INTO wines (name, quantity, type, bottle_format) VALUES (?,?,?,?)",
            ("EmptyWine", 0, "Rotwein", 0.75),
        )
        db.execute(
            "INSERT INTO wines (name, quantity, type, bottle_format) VALUES (?,?,?,?)",
            ("StockedWine", 3, "Rotwein", 0.75),
        )
        db.commit()
        resp = client.get("/buy-list")
        assert b"EmptyWine" in resp.data
        assert b"StockedWine" not in resp.data

    def test_nav_link_present_on_cellar(self, client):
        resp = client.get("/")
        assert b'href="' in resp.data and b'/buy-list' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListPage -v`
Expected: FAIL (404 for `/buy-list`)

- [ ] **Step 3: Add helpers + route to `app.py`**

After the `index()` route in `wine-tracker/app/app.py`:
```python
def buy_list_row_to_dict(row):
    return dict(row)


def query_out_of_stock(db):
    rows = db.execute(
        "SELECT * FROM wines WHERE quantity = 0 ORDER BY type, name, year"
    ).fetchall()
    return [dict(r) for r in rows]


@app.route("/buy-list")
def buy_list_page():
    db = get_db()
    items = [
        buy_list_row_to_dict(r)
        for r in db.execute(
            "SELECT * FROM buy_list ORDER BY added_at DESC, id DESC"
        ).fetchall()
    ]
    out_of_stock = query_out_of_stock(db)
    return render_template("buy_list.html", items=items, out_of_stock=out_of_stock)
```

- [ ] **Step 4: Create `buy_list.html`**

Create `wine-tracker/app/templates/buy_list.html`. The header mirrors `index.html`'s header pattern (logo + nav-links + nav-menu + bottom-tab-bar). Include the new Buy List nav entries in all three nav regions.
```html
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@mdi/font@7/css/materialdesignicons.min.css">
<link rel="stylesheet" href="{{ ingress }}/static/style.css">
<script>
(function(){var n=localStorage.getItem('wine-theme-name')||'homeassistant';if(n&&n!=='classic')document.documentElement.setAttribute('data-theme',n);var s=localStorage.getItem('wine-theme')||'system';var e=s==='system'?(window.matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'):s;if(e==='light')document.documentElement.classList.add('light');})();
</script>
<title>{{ t.buy_list_title }}</title>
</head>
<body>
<header>
  <a class="nav-brand" href="{{ ingress }}/"><img src="{{ ingress }}/static/logo.png" alt="Wine Tracker" class="nav-logo"></a>
  <nav class="nav-links">
    <a class="nav-link" href="{{ ingress }}/">{{ t.nav_cellar }}</a>
    <a class="nav-link active" href="{{ ingress }}/buy-list">{{ t.nav_buy_list }}</a>
    <a class="nav-link" href="{{ ingress }}/timeline">{{ t.timeline }}</a>
    <a class="nav-link" href="{{ ingress }}/stats">{{ t.stats_title }}</a>
  </nav>
  <button class="nav-hamburger" onclick="toggleNavMenu(event)" aria-label="Menu"><i class="mdi mdi-menu"></i></button>
  <div class="nav-menu" id="navMenu">
    <a href="{{ ingress }}/" class="nav-menu-item">{{ t.nav_cellar }}</a>
    <a href="{{ ingress }}/buy-list" class="nav-menu-item active">{{ t.nav_buy_list }}</a>
    <a href="{{ ingress }}/timeline" class="nav-menu-item">{{ t.timeline }}</a>
    <a href="{{ ingress }}/stats" class="nav-menu-item">{{ t.stats_title }}</a>
  </div>
  <div class="header-spacer"></div>
</header>

<main class="container">
  <div class="buy-list-tabs">
    <button class="bl-tab active" data-tab="wishlist" onclick="blSelectTab('wishlist')">{{ t.tab_wishlist }} ({{ items|length }})</button>
    <button class="bl-tab" data-tab="out-of-stock" onclick="blSelectTab('out-of-stock')">{{ t.tab_out_of_stock }} ({{ out_of_stock|length }})</button>
  </div>

  <section id="blPanelWishlist" class="bl-panel">
    <button class="btn-primary" onclick="openWishlistAdd()"><i class="mdi mdi-plus"></i> {{ t.btn_add_to_wishlist }}</button>
    {% if items %}
    <div class="bl-grid">
      {% for it in items %}
      <div class="card bl-card" data-id="{{ it.id }}">
        {% if it.image %}<img src="{{ ingress }}/uploads/{{ it.image }}" alt="" class="bl-thumb">{% endif %}
        <div class="bl-card-body">
          <div class="bl-name">{{ it.name }}{% if it.year %} ({{ it.year }}){% endif %}</div>
          <div class="bl-meta">{{ it.region or '' }}{% if it.grape %} - {{ it.grape }}{% endif %}</div>
          <div class="bl-meta">{% if it.price %}{{ it.price }} {{ currency }}{% endif %} - {{ t.label_desired_qty }}: {{ it.desired_qty }}</div>
        </div>
        <div class="bl-actions">
          <button class="btn-small" onclick='openMoveToCellar({{ it|tojson }})'>{{ t.btn_move_to_cellar }}</button>
          <button class="btn-small" onclick='openWishlistEdit({{ it|tojson }})'><i class="mdi mdi-pencil"></i></button>
          <button class="btn-small btn-danger" onclick="removeWishlistItem({{ it.id }})"><i class="mdi mdi-close"></i></button>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p class="bl-empty">{{ t.empty_wishlist }}</p>
    {% endif %}
  </section>

  <section id="blPanelOutOfStock" class="bl-panel" style="display:none">
    {% if out_of_stock %}
    <div class="bl-grid">
      {% for w in out_of_stock %}
      <div class="card bl-card" data-wine-id="{{ w.id }}">
        {% if w.image %}<img src="{{ ingress }}/uploads/{{ w.image }}" alt="" class="bl-thumb">{% endif %}
        <div class="bl-card-body">
          <div class="bl-name">{{ w.name }}{% if w.year %} ({{ w.year }}){% endif %}</div>
          <div class="bl-meta">{{ w.region or '' }}{% if w.grape %} - {{ w.grape }}{% endif %}</div>
        </div>
        <div class="bl-actions">
          <button class="btn-small" onclick="rebuyWine({{ w.id }}, this)"><i class="mdi mdi-cart-plus"></i> {{ t.btn_rebuy }}</button>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p class="bl-empty">{{ t.empty_out_of_stock }}</p>
    {% endif %}
  </section>
</main>

<nav class="bottom-tab-bar">
  <a class="tab-item" href="{{ ingress }}/"><i class="mdi mdi-bottle-wine"></i><span>{{ t.nav_cellar }}</span></a>
  <a class="tab-item active" href="{{ ingress }}/buy-list"><i class="mdi mdi-cart-outline"></i><span>{{ t.nav_buy_list }}</span></a>
  <a class="tab-item" href="{{ ingress }}/timeline"><i class="mdi mdi-clock-outline"></i><span>{{ t.timeline }}</span></a>
  <a class="tab-item" href="{{ ingress }}/stats"><i class="mdi mdi-chart-box"></i><span>{{ t.stats_title }}</span></a>
</nav>

<script>
const INGRESS = "{{ ingress }}";
function toggleNavMenu(e){ if(e) e.stopPropagation(); document.getElementById('navMenu').classList.toggle('open'); }
function blSelectTab(tab){
  document.querySelectorAll('.bl-tab').forEach(function(b){ b.classList.toggle('active', b.dataset.tab===tab); });
  document.getElementById('blPanelWishlist').style.display = (tab==='wishlist') ? '' : 'none';
  document.getElementById('blPanelOutOfStock').style.display = (tab==='out-of-stock') ? '' : 'none';
}
</script>
{% include "_buy_list_modals.html" %}
</body>
</html>
```
(`_buy_list_modals.html` is created in Tasks 8 and 9. Create it now as an empty placeholder file so the include resolves: `touch wine-tracker/app/templates/_buy_list_modals.html`.)

- [ ] **Step 5: Add the nav link to the other page headers**

In each of `index.html`, `chat.html`, `timeline.html`, `stats.html`, add a Buy List entry in all three nav regions, immediately after the Cellar entry. Use the `active` class only where it is the current page (none of these four are the buy-list page, so no `active`).

`.nav-links` region - add after the cellar `<a ...>{{ t.nav_cellar }}</a>`:
```html
    <a class="nav-link" href="{{ ingress }}/buy-list">{{ t.nav_buy_list }}</a>
```
`.nav-menu` region - add after the cellar `nav-menu-item`:
```html
    <a href="{{ ingress }}/buy-list" class="nav-menu-item">{{ t.nav_buy_list }}</a>
```
`.bottom-tab-bar` region - add after the cellar `tab-item`:
```html
  <a class="tab-item" href="{{ ingress }}/buy-list"><i class="mdi mdi-cart-outline"></i><span>{{ t.nav_buy_list }}</span></a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListPage -v`
Expected: PASS (all 4)

- [ ] **Step 7: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/app/templates/ wine-tracker/tests/test_buy_list.py
git commit -m "Add /buy-list page, helpers, and nav links"
```

---

### Task 4: `POST /buy-list/add`

**Files:**
- Modify: `wine-tracker/app/app.py` (add route after `buy_list_page`)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: route `POST /buy-list/add`. Reads form fields `name (required), year, type, region, grape, price, notes, bottle_format, desired_qty, maturity_data, taste_profile, food_pairings, ai_image`, plus optional `image` file upload. Inserts one `buy_list` row. AJAX -> `{"ok": True, "id": <new_id>}`; non-AJAX -> redirect to `/buy-list`.
- Consumes: `save_image`, `get_db`, `is_ajax`, `ingress_redirect`.

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestBuyListAdd:
    def test_add_minimal(self, client, db):
        resp = client.post("/buy-list/add", data={"name": "Wishlist Wine", "desired_qty": "2"}, headers=AJAX)
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["ok"] is True
        row = db.execute("SELECT name, desired_qty FROM buy_list WHERE id=?", (body["id"],)).fetchone()
        assert row[0] == "Wishlist Wine"
        assert row[1] == 2

    def test_add_carries_enrichment(self, client, db):
        resp = client.post("/buy-list/add", data={
            "name": "AI Wine", "year": "2019", "type": "Rotwein",
            "maturity_data": '{"peak": [2025, 2030]}',
            "food_pairings": '["Steak"]',
        }, headers=AJAX)
        body = json.loads(resp.data)
        row = db.execute("SELECT maturity_data, food_pairings FROM buy_list WHERE id=?", (body["id"],)).fetchone()
        assert row[0] == '{"peak": [2025, 2030]}'
        assert row[1] == '["Steak"]'

    def test_add_requires_name(self, client):
        resp = client.post("/buy-list/add", data={"desired_qty": "1"}, headers=AJAX)
        assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListAdd -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement the route**

After `buy_list_page` in `app.py`:
```python
def _buy_list_form_values():
    """Pull the buy_list field values out of request.form (+ image)."""
    name = request.form.get("name", "").strip()
    bottle_format_raw = request.form.get("bottle_format", "").strip()
    price_raw = request.form.get("price", "").strip()
    image = save_image(request.files.get("image"))
    if not image:
        ai_img = request.form.get("ai_image", "").strip()
        if ai_img and os.path.isfile(os.path.join(UPLOAD_DIR, ai_img)):
            image = ai_img
    return {
        "name": name,
        "year": request.form.get("year") or None,
        "type": request.form.get("type") or None,
        "region": request.form.get("region", "").strip() or None,
        "grape": request.form.get("grape", "").strip() or None,
        "price": float(price_raw) if price_raw else None,
        "notes": request.form.get("notes", "").strip() or None,
        "image": image,
        "bottle_format": float(bottle_format_raw) if bottle_format_raw else 0.75,
        "desired_qty": int(request.form.get("desired_qty", 1) or 1),
        "drink_from": request.form.get("drink_from") or None,
        "drink_until": request.form.get("drink_until") or None,
        "maturity_data": request.form.get("maturity_data", "").strip() or None,
        "taste_profile": request.form.get("taste_profile", "").strip() or None,
        "food_pairings": request.form.get("food_pairings", "").strip() or None,
    }


def _insert_buy_list(db, vals):
    cur = db.execute(
        """INSERT INTO buy_list
           (name, year, type, region, grape, price, notes, image, bottle_format,
            desired_qty, added_at, drink_from, drink_until,
            maturity_data, taste_profile, food_pairings)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            vals["name"], vals["year"], vals["type"], vals["region"], vals["grape"],
            vals["price"], vals["notes"], vals["image"], vals["bottle_format"],
            vals["desired_qty"], datetime.now().isoformat(),
            vals["drink_from"], vals["drink_until"],
            vals["maturity_data"], vals["taste_profile"], vals["food_pairings"],
        ),
    )
    db.commit()
    return cur.lastrowid


@app.route("/buy-list/add", methods=["POST"])
def buy_list_add():
    db = get_db()
    vals = _buy_list_form_values()
    if not vals["name"]:
        return jsonify({"ok": False, "error": "name_required"}), 400
    new_id = _insert_buy_list(db, vals)
    if is_ajax():
        return jsonify({"ok": True, "id": new_id})
    return ingress_redirect("buy_list_page")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListAdd -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_buy_list.py
git commit -m "Add POST /buy-list/add"
```

---

### Task 5: `POST /buy-list/edit/<id>` and `POST /buy-list/delete/<id>`

**Files:**
- Modify: `wine-tracker/app/app.py`
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: `POST /buy-list/edit/<int:item_id>` (updates the row; same form fields as add; AJAX -> `{"ok": True}`) and `POST /buy-list/delete/<int:item_id>` (deletes the row and its image file unless another buy_list/wines row uses it; AJAX -> `{"ok": True}`).

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestBuyListEditDelete:
    def _add(self, client, **extra):
        data = {"name": "X", "desired_qty": "1"}
        data.update(extra)
        return json.loads(client.post("/buy-list/add", data=data, headers=AJAX).data)["id"]

    def test_edit_updates_fields(self, client, db):
        item_id = self._add(client)
        resp = client.post(f"/buy-list/edit/{item_id}", data={"name": "Renamed", "desired_qty": "4", "price": "20"}, headers=AJAX)
        assert json.loads(resp.data)["ok"] is True
        row = db.execute("SELECT name, desired_qty, price FROM buy_list WHERE id=?", (item_id,)).fetchone()
        assert row[0] == "Renamed" and row[1] == 4 and row[2] == 20.0

    def test_delete_removes_row(self, client, db):
        item_id = self._add(client)
        resp = client.post(f"/buy-list/delete/{item_id}", headers=AJAX)
        assert json.loads(resp.data)["ok"] is True
        assert db.execute("SELECT COUNT(*) FROM buy_list WHERE id=?", (item_id,)).fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListEditDelete -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement the routes**

After `buy_list_add` in `app.py`:
```python
@app.route("/buy-list/edit/<int:item_id>", methods=["POST"])
def buy_list_edit(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM buy_list WHERE id=?", (item_id,)).fetchone()
    if not item:
        return jsonify({"ok": False, "error": "not_found"}), 404
    vals = _buy_list_form_values()
    if not vals["name"]:
        return jsonify({"ok": False, "error": "name_required"}), 400
    # Keep the existing image if no new one was provided.
    image = vals["image"] or item["image"]
    db.execute(
        """UPDATE buy_list SET name=?, year=?, type=?, region=?, grape=?, price=?,
           notes=?, image=?, bottle_format=?, desired_qty=?,
           drink_from=?, drink_until=?, maturity_data=?, taste_profile=?, food_pairings=?
           WHERE id=?""",
        (
            vals["name"], vals["year"], vals["type"], vals["region"], vals["grape"],
            vals["price"], vals["notes"], image, vals["bottle_format"], vals["desired_qty"],
            vals["drink_from"], vals["drink_until"],
            vals["maturity_data"], vals["taste_profile"], vals["food_pairings"],
            item_id,
        ),
    )
    db.commit()
    if is_ajax():
        return jsonify({"ok": True})
    return ingress_redirect("buy_list_page")


def _delete_buy_list_image_if_unused(db, image, exclude_item_id):
    """Remove an image file only if no wine and no other buy_list row references it."""
    if not image:
        return
    in_wines = db.execute("SELECT COUNT(*) FROM wines WHERE image=?", (image,)).fetchone()[0]
    in_buy = db.execute(
        "SELECT COUNT(*) FROM buy_list WHERE image=? AND id!=?", (image, exclude_item_id)
    ).fetchone()[0]
    if in_wines == 0 and in_buy == 0:
        try:
            os.remove(os.path.join(UPLOAD_DIR, image))
        except FileNotFoundError:
            pass


@app.route("/buy-list/delete/<int:item_id>", methods=["POST"])
def buy_list_delete(item_id):
    db = get_db()
    item = db.execute("SELECT image FROM buy_list WHERE id=?", (item_id,)).fetchone()
    if item:
        _delete_buy_list_image_if_unused(db, item["image"], item_id)
        db.execute("DELETE FROM buy_list WHERE id=?", (item_id,))
        db.commit()
    if is_ajax():
        return jsonify({"ok": True})
    return ingress_redirect("buy_list_page")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestBuyListEditDelete -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_buy_list.py
git commit -m "Add POST /buy-list/edit and /buy-list/delete"
```

---

### Task 6: `POST /buy-list/rebuy/<wine_id>` (out-of-stock -> wishlist)

**Files:**
- Modify: `wine-tracker/app/app.py`
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: `POST /buy-list/rebuy/<int:wine_id>` - copies a cellar wine's fields (incl. enrichment) into a new `buy_list` row, `desired_qty=1`, copying the image to a new file. AJAX -> `{"ok": True, "id": <new_id>}`.
- Consumes: `_insert_buy_list`.

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestRebuy:
    def test_rebuy_copies_wine_into_wishlist(self, client, db):
        db.execute(
            """INSERT INTO wines (name, year, type, region, grape, quantity, price,
               bottle_format, drink_from, drink_until, maturity_data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("Gone Wine", 2018, "Rotwein", "Rioja", "Tempranillo", 0, 25.0, 0.75,
             2022, 2030, '{"peak": [2024, 2028]}'),
        )
        db.commit()
        wine_id = db.execute("SELECT id FROM wines WHERE name='Gone Wine'").fetchone()[0]
        resp = client.post(f"/buy-list/rebuy/{wine_id}", headers=AJAX)
        body = json.loads(resp.data)
        assert body["ok"] is True
        row = db.execute(
            "SELECT name, year, region, grape, price, desired_qty, drink_from, maturity_data FROM buy_list WHERE id=?",
            (body["id"],),
        ).fetchone()
        assert row["name"] == "Gone Wine"
        assert row["year"] == 2018
        assert row["grape"] == "Tempranillo"
        assert row["desired_qty"] == 1
        assert row["drink_from"] == 2022
        assert row["maturity_data"] == '{"peak": [2024, 2028]}'

    def test_rebuy_unknown_wine_404(self, client):
        resp = client.post("/buy-list/rebuy/99999", headers=AJAX)
        assert resp.status_code == 404
```
(The `db` fixture sets `conn.row_factory = sqlite3.Row` in `conftest.py`, so `row["col"]` key access works as written.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestRebuy -v`
Expected: FAIL (404 for the route itself)

- [ ] **Step 3: Implement the route**

After `buy_list_delete` in `app.py`:
```python
def _copy_image_file(image):
    """Copy an UPLOAD_DIR image to a fresh filename. Returns new name or None."""
    if not image:
        return None
    src = os.path.join(UPLOAD_DIR, image)
    if not os.path.exists(src):
        return None
    ext = image.rsplit(".", 1)[-1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    shutil.copy2(src, os.path.join(UPLOAD_DIR, new_name))
    return new_name


@app.route("/buy-list/rebuy/<int:wine_id>", methods=["POST"])
def buy_list_rebuy(wine_id):
    db = get_db()
    wine = db.execute("SELECT * FROM wines WHERE id=?", (wine_id,)).fetchone()
    if not wine:
        return jsonify({"ok": False, "error": "not_found"}), 404
    vals = {
        "name": wine["name"],
        "year": wine["year"],
        "type": wine["type"],
        "region": wine["region"],
        "grape": wine["grape"],
        "price": wine["price"],
        "notes": wine["notes"],
        "image": _copy_image_file(wine["image"]),
        "bottle_format": wine["bottle_format"] if wine["bottle_format"] is not None else 0.75,
        "desired_qty": 1,
        "drink_from": wine["drink_from"],
        "drink_until": wine["drink_until"],
        "maturity_data": wine["maturity_data"],
        "taste_profile": wine["taste_profile"],
        "food_pairings": wine["food_pairings"],
    }
    new_id = _insert_buy_list(db, vals)
    if is_ajax():
        return jsonify({"ok": True, "id": new_id})
    return ingress_redirect("buy_list_page")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestRebuy -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_buy_list.py
git commit -m "Add POST /buy-list/rebuy"
```

---

### Task 7: `POST /buy-list/move/<id>` (move to cellar, with vintage re-run)

**Files:**
- Modify: `wine-tracker/app/app.py`
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: `POST /buy-list/move/<int:item_id>`. Form fields: `name, year, type, region, grape, price, notes, bottle_format, quantity` (the number of bottles to add; prefilled from `desired_qty`), `original_year` (hidden), plus carried `maturity_data, taste_profile, food_pairings`. Behaviour: if `year != original_year` and AI configured, re-run `_analyze_wine_from_context` and overwrite the four vintage-dependent enrichment fields; then `_find_duplicate_wine` -> restock (UPDATE quantity, timeline `restocked`) or create (INSERT, timeline `added`, image copied); then delete the buy_list row. AJAX -> `{"ok": True, "wine_id": <id>, "restocked": <bool>}`.
- Consumes: `_find_duplicate_wine`, `_is_ai_configured`, `_load_image_b64`, `_analyze_wine_from_context`, `_copy_image_file`, `_delete_buy_list_image_if_unused`.

- [ ] **Step 1: Write the failing tests**

Append:
```python
class TestMoveToCellar:
    def _add_item(self, client, db, **extra):
        data = {"name": "Move Wine", "year": "2018", "type": "Rotwein",
                "bottle_format": "0.75", "desired_qty": "2"}
        data.update(extra)
        return json.loads(client.post("/buy-list/add", data=data, headers=AJAX).data)["id"]

    def _move(self, client, item_id, **form):
        base = {"name": "Move Wine", "year": "2018", "type": "Rotwein",
                "bottle_format": "0.75", "quantity": "2", "original_year": "2018"}
        base.update(form)
        return client.post(f"/buy-list/move/{item_id}", data=base, headers=AJAX)

    def test_move_creates_new_wine(self, client, db):
        item_id = self._add_item(client, db)
        resp = self._move(client, item_id)
        body = json.loads(resp.data)
        assert body["ok"] is True and body["restocked"] is False
        w = db.execute("SELECT quantity FROM wines WHERE id=?", (body["wine_id"],)).fetchone()
        assert w[0] == 2
        assert db.execute("SELECT COUNT(*) FROM buy_list WHERE id=?", (item_id,)).fetchone()[0] == 0
        action = db.execute(
            "SELECT action FROM timeline WHERE wine_id=? ORDER BY id DESC LIMIT 1", (body["wine_id"],)
        ).fetchone()[0]
        assert action == "added"

    def test_move_restocks_existing(self, client, db):
        db.execute(
            "INSERT INTO wines (name, year, type, quantity, bottle_format) VALUES (?,?,?,?,?)",
            ("Move Wine", 2018, "Rotwein", 0, 0.75),
        )
        db.commit()
        existing_id = db.execute("SELECT id FROM wines WHERE name='Move Wine'").fetchone()[0]
        item_id = self._add_item(client, db)
        resp = self._move(client, item_id)
        body = json.loads(resp.data)
        assert body["ok"] is True and body["restocked"] is True
        assert body["wine_id"] == existing_id
        assert db.execute("SELECT quantity FROM wines WHERE id=?", (existing_id,)).fetchone()[0] == 2
        action = db.execute(
            "SELECT action FROM timeline WHERE wine_id=? ORDER BY id DESC LIMIT 1", (existing_id,)
        ).fetchone()[0]
        assert action == "restocked"

    def test_move_same_year_does_not_call_ai(self, client, db):
        item_id = self._add_item(client, db)
        with patch("app._analyze_wine_from_context") as mock_ai:
            self._move(client, item_id, year="2018", original_year="2018")
            mock_ai.assert_not_called()

    def test_move_changed_year_calls_ai_when_configured(self, client, db, monkeypatch):
        import app as wine_app
        opts = dict(wine_app.HA_OPTIONS)
        opts.update({"ai_provider": "anthropic", "anthropic_api_key": "sk-test"})
        monkeypatch.setattr(wine_app, "HA_OPTIONS", opts)
        item_id = self._add_item(client, db)
        with patch("app._is_ai_configured", return_value=True), \
             patch("app._load_image_b64", return_value=(None, "image/jpeg")), \
             patch("app._analyze_wine_from_context", return_value={"drink_from": 2030, "drink_until": 2040}) as mock_ai:
            resp = self._move(client, item_id, year="2020", original_year="2018")
            mock_ai.assert_called_once()
        body = json.loads(resp.data)
        w = db.execute("SELECT drink_from, drink_until FROM wines WHERE id=?", (body["wine_id"],)).fetchone()
        assert w[0] == 2030 and w[1] == 2040
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestMoveToCellar -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement the route**

After `buy_list_rebuy` in `app.py`:
```python
@app.route("/buy-list/move/<int:item_id>", methods=["POST"])
def buy_list_move(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM buy_list WHERE id=?", (item_id,)).fetchone()
    if not item:
        return jsonify({"ok": False, "error": "not_found"}), 404

    name = request.form.get("name", item["name"]).strip()
    year = request.form.get("year") or None
    wine_type = request.form.get("type") or item["type"]
    region = request.form.get("region", item["region"] or "").strip() or None
    grape = request.form.get("grape", item["grape"] or "").strip() or None
    notes = request.form.get("notes", item["notes"] or "").strip() or None
    price_raw = request.form.get("price", "").strip()
    price = float(price_raw) if price_raw else item["price"]
    bf_raw = request.form.get("bottle_format", "").strip()
    bottle_format = float(bf_raw) if bf_raw else (item["bottle_format"] or 0.75)
    qty = int(request.form.get("quantity", item["desired_qty"] or 1) or 1)
    original_year = request.form.get("original_year") or None

    # Enrichment carried from the wishlist item by default.
    drink_from = item["drink_from"]
    drink_until = item["drink_until"]
    maturity_data = item["maturity_data"]
    taste_profile = item["taste_profile"]
    food_pairings = item["food_pairings"]

    # Vintage re-run rule: only when the user actually changed the year.
    if year and str(year) != str(original_year or ""):
        opts = load_options()
        if _is_ai_configured(opts):
            try:
                image_b64, media_type = _load_image_b64(item["image"])
                fields = _analyze_wine_from_context(
                    opts, image_b64, media_type,
                    {"name": name, "year": year, "type": wine_type, "region": region, "grape": grape},
                )
                if fields.get("drink_from") is not None:
                    drink_from = fields["drink_from"]
                if fields.get("drink_until") is not None:
                    drink_until = fields["drink_until"]
                if fields.get("maturity_data") is not None:
                    maturity_data = json.dumps(fields["maturity_data"])
                if fields.get("taste_profile") is not None:
                    taste_profile = json.dumps(fields["taste_profile"])
                if fields.get("food_pairings") is not None:
                    food_pairings = json.dumps(fields["food_pairings"])
            except Exception:
                app.logger.exception("buy_list move re-analyze failed; carrying stored enrichment")

    existing = _find_duplicate_wine(db, name, year, bottle_format, region, grape, wine_type)
    if existing:
        db.execute("UPDATE wines SET quantity = quantity + ? WHERE id=?", (qty, existing["id"]))
        db.execute(
            "INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
            (existing["id"], "restocked", qty, datetime.now().isoformat()),
        )
        wine_id = existing["id"]
        restocked = True
    else:
        new_image = _copy_image_file(item["image"])
        cur = db.execute(
            """INSERT INTO wines
               (name, year, type, region, quantity, rating, notes, image, added,
                price, drink_from, drink_until, grape, bottle_format,
                maturity_data, taste_profile, food_pairings)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name, year, wine_type, region, qty, 0, notes, new_image, str(date.today()),
                price, drink_from, drink_until, grape, bottle_format,
                maturity_data, taste_profile, food_pairings,
            ),
        )
        wine_id = cur.lastrowid
        db.execute(
            "INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
            (wine_id, "added", qty, datetime.now().isoformat()),
        )
        restocked = False

    _delete_buy_list_image_if_unused(db, item["image"], item_id)
    db.execute("DELETE FROM buy_list WHERE id=?", (item_id,))
    db.commit()

    if is_ajax():
        return jsonify({"ok": True, "wine_id": wine_id, "restocked": restocked})
    return ingress_redirect("buy_list_page")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestMoveToCellar -v`
Expected: PASS (4)

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/app.py wine-tracker/tests/test_buy_list.py
git commit -m "Add POST /buy-list/move with vintage re-run rule"
```

---

### Task 8: Wishlist add/edit modal UI (camera + analyze)

**Files:**
- Create/replace: `wine-tracker/app/templates/_buy_list_modals.html` (the empty placeholder from Task 3)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Consumes: `t`, `wine_types`, `currency`, `ai_enabled`, `INGRESS` (defined in `buy_list.html`).
- Produces: `openWishlistAdd()`, `openWishlistEdit(item)`, `removeWishlistItem(id)`, and a hidden `<form id="wishlistForm">` posting to `/buy-list/add` or `/buy-list/edit/<id>`. The label-photo control posts to `/api/analyze-wine` and fills the form (mirrors `_wine_edit_modal.html`'s `startAiAnalysis`/`populateFormFromAi`).

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestWishlistModal:
    def test_add_modal_markup_present(self, client):
        resp = client.get("/buy-list")
        assert b'id="wishlistForm"' in resp.data
        assert b'id="blDesiredQty"' in resp.data
        assert b'openWishlistAdd' in resp.data

    def test_scan_control_present_when_ai_enabled(self, client, monkeypatch):
        import app as wine_app
        monkeypatch.setattr(wine_app, "_is_ai_configured", lambda opts: True)
        resp = client.get("/buy-list")
        assert b'blScanInput' in resp.data
        assert b'/api/analyze-wine' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestWishlistModal -v`
Expected: FAIL (markup absent)

- [ ] **Step 3: Write `_buy_list_modals.html`**

Replace the placeholder file `wine-tracker/app/templates/_buy_list_modals.html` with:
```html
<div id="wishlistModal" class="modal" style="display:none">
  <div class="modal-box">
    <h3 id="wishlistModalTitle">{{ t.btn_add_to_wishlist }}</h3>

    {% if ai_enabled %}
    <div class="bl-scan-row">
      <label class="btn-secondary">
        <i class="mdi mdi-camera"></i> {{ t.scan_label }}
        <input id="blScanInput" type="file" accept="image/*" capture="environment" style="display:none" onchange="blScanLabel(this.files[0])">
      </label>
      <span id="blScanLoading" style="display:none">...</span>
    </div>
    {% endif %}

    <form id="wishlistForm" onsubmit="return submitWishlist(event)" enctype="multipart/form-data">
      <input type="hidden" name="ai_image" id="blAiImage" value="">
      <input type="hidden" name="maturity_data" id="blMaturity" value="">
      <input type="hidden" name="taste_profile" id="blTaste" value="">
      <input type="hidden" name="food_pairings" id="blPairings" value="">
      <div><label>{{ t.label_name }}</label><input type="text" name="name" id="blName" required></div>
      <div class="row2">
        <div><label>{{ t.label_vintage }}</label><input type="number" name="year" id="blYear" min="1900" max="2099"></div>
        <div><label>{{ t.label_desired_qty }}</label><input type="number" name="desired_qty" id="blDesiredQty" min="1" value="1"></div>
      </div>
      <div class="row2">
        <div><label>{{ t.label_type }}</label>
          <select name="type" id="blType">
            <option value="">{{ t.type_select_default }}</option>
            {% for wt in wine_types %}<option value="{{ wt }}">{{ wt | wine_type }}</option>{% endfor %}
          </select>
        </div>
        <div><label>{{ t.label_region }}</label><input type="text" name="region" id="blRegion"></div>
      </div>
      <div class="row2">
        <div><label>{{ t.label_grape }}</label><input type="text" name="grape" id="blGrape"></div>
        <div><label>{{ t.label_price }} ({{ currency }})</label><input type="number" name="price" id="blPrice" min="0" step="0.01"></div>
      </div>
      <div class="row2">
        <div><label>{{ t.label_drink_from }}</label><input type="number" name="drink_from" id="blDrinkFrom" min="2000" max="2099"></div>
        <div><label>{{ t.label_drink_until }}</label><input type="number" name="drink_until" id="blDrinkUntil" min="2000" max="2099"></div>
      </div>
      <div><label>{{ t.label_notes }}</label><textarea name="notes" id="blNotes"></textarea></div>
      <div class="form-footer">
        <button type="button" class="btn-cancel" onclick="closeWishlistModal()">{{ t.btn_cancel }}</button>
        <button type="submit" class="btn-primary">{{ t.btn_save }}</button>
      </div>
    </form>
  </div>
</div>

<script>
let _wishlistEditId = null;

function _blResetForm() {
  document.getElementById('wishlistForm').reset();
  ['blAiImage','blMaturity','blTaste','blPairings'].forEach(function(id){ document.getElementById(id).value=''; });
}
function openWishlistAdd() {
  _wishlistEditId = null;
  _blResetForm();
  document.getElementById('wishlistModalTitle').textContent = "{{ t.btn_add_to_wishlist }}";
  document.getElementById('wishlistModal').style.display = 'flex';
}
function openWishlistEdit(item) {
  _wishlistEditId = item.id;
  _blResetForm();
  document.getElementById('wishlistModalTitle').textContent = "{{ t.btn_edit if t.btn_edit is defined else 'Edit' }}";
  document.getElementById('blName').value = item.name || '';
  document.getElementById('blYear').value = item.year || '';
  document.getElementById('blDesiredQty').value = item.desired_qty || 1;
  document.getElementById('blType').value = item.type || '';
  document.getElementById('blRegion').value = item.region || '';
  document.getElementById('blGrape').value = item.grape || '';
  document.getElementById('blPrice').value = item.price || '';
  document.getElementById('blDrinkFrom').value = item.drink_from || '';
  document.getElementById('blDrinkUntil').value = item.drink_until || '';
  document.getElementById('blNotes').value = item.notes || '';
  document.getElementById('blMaturity').value = item.maturity_data || '';
  document.getElementById('blTaste').value = item.taste_profile || '';
  document.getElementById('blPairings').value = item.food_pairings || '';
  document.getElementById('wishlistModal').style.display = 'flex';
}
function closeWishlistModal() { document.getElementById('wishlistModal').style.display = 'none'; }

function blScanLabel(file) {
  if (!file) return;
  document.getElementById('blScanLoading').style.display = '';
  const fd = new FormData();
  fd.append('image', file);
  fetch(INGRESS + '/api/analyze-wine', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function(r){ return r.json(); })
    .then(function(data){
      document.getElementById('blScanLoading').style.display = 'none';
      if (!data.ok) { if (data.image_filename) document.getElementById('blAiImage').value = data.image_filename; return; }
      const f = data.fields || {};
      if (f.name) document.getElementById('blName').value = f.name;
      if (f.vintage) document.getElementById('blYear').value = f.vintage;
      if (f.wine_type) document.getElementById('blType').value = f.wine_type;
      if (f.region) document.getElementById('blRegion').value = f.region;
      if (f.grape) document.getElementById('blGrape').value = f.grape;
      if (f.price) document.getElementById('blPrice').value = f.price;
      if (f.drink_from) document.getElementById('blDrinkFrom').value = f.drink_from;
      if (f.drink_until) document.getElementById('blDrinkUntil').value = f.drink_until;
      if (f.notes) document.getElementById('blNotes').value = f.notes;
      if (f.maturity_data) document.getElementById('blMaturity').value = JSON.stringify(f.maturity_data);
      if (f.taste_profile) document.getElementById('blTaste').value = JSON.stringify(f.taste_profile);
      if (f.food_pairings) document.getElementById('blPairings').value = JSON.stringify(f.food_pairings);
      if (data.image_filename) document.getElementById('blAiImage').value = data.image_filename;
    })
    .catch(function(){ document.getElementById('blScanLoading').style.display = 'none'; });
}

function submitWishlist(e) {
  e.preventDefault();
  const form = document.getElementById('wishlistForm');
  const fd = new FormData(form);
  const url = _wishlistEditId ? (INGRESS + '/buy-list/edit/' + _wishlistEditId) : (INGRESS + '/buy-list/add');
  fetch(url, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function(r){ return r.json(); })
    .then(function(data){ if (data.ok) location.reload(); });
  return false;
}

function removeWishlistItem(id) {
  fetch(INGRESS + '/buy-list/delete/' + id, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function(r){ return r.json(); })
    .then(function(data){ if (data.ok) location.reload(); });
}
</script>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestWishlistModal -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/templates/_buy_list_modals.html wine-tracker/tests/test_buy_list.py
git commit -m "Add wishlist add/edit modal with label scan"
```

---

### Task 9: Move-to-cellar confirm dialog UI

**Files:**
- Modify: `wine-tracker/app/templates/_buy_list_modals.html` (append the move dialog + `openMoveToCellar`, `rebuyWine`)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: `openMoveToCellar(item)` (opens a prefilled form with a hidden `original_year`, posts to `/buy-list/move/<id>`), `rebuyWine(wineId, btn)` (posts to `/buy-list/rebuy/<id>`).

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestMoveDialogUI:
    def test_move_dialog_markup_present(self, client):
        resp = client.get("/buy-list")
        assert b'id="moveForm"' in resp.data
        assert b'id="moveOriginalYear"' in resp.data
        assert b'openMoveToCellar' in resp.data
        assert b'rebuyWine' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestMoveDialogUI -v`
Expected: FAIL

- [ ] **Step 3: Append the move dialog to `_buy_list_modals.html`**

Add before the final `</script>`-less end of the file (i.e. after the wishlist `<script>` block, append a new block):
```html
<div id="moveModal" class="modal" style="display:none">
  <div class="modal-box">
    <h3>{{ t.move_dialog_title }}</h3>
    <form id="moveForm" onsubmit="return submitMove(event)">
      <input type="hidden" name="original_year" id="moveOriginalYear" value="">
      <input type="hidden" name="maturity_data" id="moveMaturity" value="">
      <input type="hidden" name="taste_profile" id="moveTaste" value="">
      <input type="hidden" name="food_pairings" id="movePairings" value="">
      <input type="hidden" name="bottle_format" id="moveBottleFormat" value="0.75">
      <div><label>{{ t.label_name }}</label><input type="text" name="name" id="moveName" required></div>
      <div class="row2">
        <div><label>{{ t.label_vintage }}</label><input type="number" name="year" id="moveYear" min="1900" max="2099"></div>
        <div><label>{{ t.label_quantity }}</label><input type="number" name="quantity" id="moveQty" min="1" value="1"></div>
      </div>
      <div class="row2">
        <div><label>{{ t.label_type }}</label>
          <select name="type" id="moveType">
            <option value="">{{ t.type_select_default }}</option>
            {% for wt in wine_types %}<option value="{{ wt }}">{{ wt | wine_type }}</option>{% endfor %}
          </select>
        </div>
        <div><label>{{ t.label_price }} ({{ currency }})</label><input type="number" name="price" id="movePrice" min="0" step="0.01"></div>
      </div>
      <div class="row2">
        <div><label>{{ t.label_region }}</label><input type="text" name="region" id="moveRegion"></div>
        <div><label>{{ t.label_grape }}</label><input type="text" name="grape" id="moveGrape"></div>
      </div>
      <div class="form-footer">
        <button type="button" class="btn-cancel" onclick="closeMoveModal()">{{ t.btn_cancel }}</button>
        <button type="submit" class="btn-primary">{{ t.btn_move_to_cellar }}</button>
      </div>
    </form>
  </div>
</div>

<script>
let _moveItemId = null;
function openMoveToCellar(item) {
  _moveItemId = item.id;
  document.getElementById('moveOriginalYear').value = item.year || '';
  document.getElementById('moveName').value = item.name || '';
  document.getElementById('moveYear').value = item.year || '';
  document.getElementById('moveQty').value = item.desired_qty || 1;
  document.getElementById('moveType').value = item.type || '';
  document.getElementById('movePrice').value = item.price || '';
  document.getElementById('moveRegion').value = item.region || '';
  document.getElementById('moveGrape').value = item.grape || '';
  document.getElementById('moveBottleFormat').value = item.bottle_format || 0.75;
  document.getElementById('moveMaturity').value = item.maturity_data || '';
  document.getElementById('moveTaste').value = item.taste_profile || '';
  document.getElementById('movePairings').value = item.food_pairings || '';
  document.getElementById('moveModal').style.display = 'flex';
}
function closeMoveModal() { document.getElementById('moveModal').style.display = 'none'; }
function submitMove(e) {
  e.preventDefault();
  const fd = new FormData(document.getElementById('moveForm'));
  fetch(INGRESS + '/buy-list/move/' + _moveItemId, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function(r){ return r.json(); })
    .then(function(data){ if (data.ok) location.reload(); });
  return false;
}
function rebuyWine(wineId, btn) {
  if (btn) btn.disabled = true;
  fetch(INGRESS + '/buy-list/rebuy/' + wineId, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function(r){ return r.json(); })
    .then(function(data){ if (data.ok) location.reload(); });
}
</script>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestMoveDialogUI -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wine-tracker/app/templates/_buy_list_modals.html wine-tracker/tests/test_buy_list.py
git commit -m "Add move-to-cellar confirm dialog and re-buy button"
```

---

### Task 10: Out-of-stock quick filter on the Cellar page

**Files:**
- Modify: `wine-tracker/app/templates/index.html` (add a filter option in the filter dropdown + a small JS filter)
- Test: `wine-tracker/tests/test_buy_list.py`

**Interfaces:**
- Produces: a clickable "Out of stock" filter on `/` that shows only cards with `data-quantity="0"`. Uses the existing card markup (`data-quantity` attribute already present per `index.html`).

- [ ] **Step 1: Write the failing test**

Append:
```python
class TestCellarOutOfStockFilter:
    def test_filter_option_present(self, client):
        resp = client.get("/")
        assert b'filterOutOfStock' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestCellarOutOfStockFilter -v`
Expected: FAIL

- [ ] **Step 3: Add the filter control + JS to `index.html`**

In `index.html`, inside the filter dropdown (`<div class="filter-dropdown" id="filterDropdown">`), after the type `filter-list`, add:
```html
      <hr class="filter-divider">
      <label class="filter-option" data-special="oos">
        <input type="radio" name="wineSpecial" value="oos" onchange="filterOutOfStock()"> {{ t.tab_out_of_stock }}
      </label>
```
Then add this function inside the page's existing `<script>` (near the other filter functions):
```javascript
function filterOutOfStock() {
  document.querySelectorAll('.card[data-id]').forEach(function(card){
    card.style.display = (card.dataset.quantity === '0') ? '' : 'none';
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest wine-tracker/tests/test_buy_list.py::TestCellarOutOfStockFilter -v`
Expected: PASS

- [ ] **Step 5: Run the FULL suite**

Run: `.venv/bin/python -m pytest wine-tracker/tests/ -v`
Expected: PASS (all tests, including the pre-existing suite)

- [ ] **Step 6: Commit**

```bash
git add wine-tracker/app/templates/index.html wine-tracker/tests/test_buy_list.py
git commit -m "Add out-of-stock quick filter to cellar page"
```

---

## Self-Review

**Spec coverage check (each spec section -> task):**
- buy_list table + enrichment columns -> Task 1.
- 7-language strings -> Task 2 (+ reused existing keys where present).
- GET /buy-list hub, two tabs, out-of-stock = qty 0, nav -> Task 3.
- Add to wishlist (manual + label photo via /api/analyze-wine) -> Tasks 4 (route) + 8 (modal/scan).
- Edit/Delete wishlist -> Task 5.
- Re-buy (out-of-stock -> wishlist, copies enrichment, no AI) -> Task 6.
- Move to cellar (restock-or-create, timeline, image copy, vintage re-run rule) -> Task 7 (route) + 9 (dialog).
- Out-of-stock filter on cellar page -> Task 10.
- Conventions (ingress, hyphens, /api/summary untouched, no version bump) -> Global Constraints, honored per task.

**Placeholder scan:** No TBD/TODO. Each code step contains complete code. The one runtime caveat (Task 6 `sqlite3.Row` access) is called out with the exact fix.

**Type/name consistency:** `_buy_list_form_values` / `_insert_buy_list` / `_copy_image_file` / `_delete_buy_list_image_if_unused` are defined in Tasks 4-6 and reused in Tasks 5-7 with matching signatures. Route names (`buy_list_page`, `buy_list_add`, `buy_list_edit`, `buy_list_delete`, `buy_list_rebuy`, `buy_list_move`) are consistent across `ingress_redirect("buy_list_page")` calls and tests. Template element IDs referenced by JS (`wishlistForm`, `blDesiredQty`, `blScanInput`, `moveForm`, `moveOriginalYear`) match the tests.

**Note on `db` fixture row access:** verified - `conftest.py`'s `db` fixture sets `conn.row_factory = sqlite3.Row`, so both index (`row[0]`) and key (`row["name"]`) access used in the tests work.
