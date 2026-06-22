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
