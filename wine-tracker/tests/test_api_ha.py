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
    assert out["taste_profile"] is None        # unset AI field stays None in full mode


def test_serialize_wine_full_malformed_json_becomes_none(db):
    wid = _insert(db, name="A", maturity_data="{not valid json")
    out = api_queries.serialize_wine(_get_row(db, wid), full=True)
    assert out["maturity_data"] is None


def test_serialize_wine_image_path_none_when_no_image(db):
    wid = _insert(db, name="A", image=None)
    out = api_queries.serialize_wine(_get_row(db, wid))
    assert out["image_path"] is None


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


def test_drink_window_same_year_entering_and_leaving(db):
    # A one-year window (drink_from == drink_until == current year) is both
    # entering and leaving this year, and is ready now.
    _insert(db, name="OneYear", quantity=1, drink_from=2026, drink_until=2026)
    dw = api_queries.compute_drink_window(db, 2026)
    assert dw["entering_this_year"] == 1
    assert dw["leaving_this_year"] == 1
    assert dw["counts"]["ready"] == 1
    assert dw["ready"][0]["name"] == "OneYear"


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
    assert "ready_now" in data
    assert "entering_this_year" in data
    assert "leaving_this_year" in data


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


def test_wines_pagination_offset(client, db):
    for i in range(3):
        _insert(db, name=f"W{i}")
    # default name sort asc -> W0, W1, W2; offset=1 limit=2 -> W1, W2
    resp = client.get("/api/wines?sort=name&order=asc&limit=2&offset=1")
    data = json.loads(resp.data)
    assert data["count"] == 3            # total before pagination
    assert data["returned"] == 2
    assert [w["name"] for w in data["wines"]] == ["W1", "W2"]


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
