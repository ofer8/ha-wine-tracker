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
        assert b'href="/buy-list"' in resp.data


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


def _jpeg_upload(name="x.jpg"):
    buf = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (12, 12), (120, 30, 30)).save(buf, "JPEG")
    buf.seek(0)
    return (buf, name)


class TestBuyListEditImage:
    def test_edit_replacing_image_deletes_old_unused(self, client, db, upload_dir):
        # Add an item with an image.
        resp = client.post(
            "/buy-list/add",
            data={"name": "img", "desired_qty": "1", "image": _jpeg_upload("a.jpg")},
            headers=AJAX,
        )
        body = json.loads(resp.data)
        assert body["ok"] is True
        item_id = body["id"]

        row = db.execute("SELECT image FROM buy_list WHERE id=?", (item_id,)).fetchone()
        old_image = row["image"]
        assert old_image, "Expected image to be saved"
        old_path = os.path.join(upload_dir, old_image)
        assert os.path.exists(old_path), "Old image file should exist before edit"

        # Edit with a new image.
        resp2 = client.post(
            f"/buy-list/edit/{item_id}",
            data={"name": "img", "desired_qty": "1", "image": _jpeg_upload("b.jpg")},
            headers=AJAX,
        )
        assert json.loads(resp2.data)["ok"] is True

        # Old file must be deleted; new file must exist; DB must reflect new name.
        assert not os.path.exists(old_path), "Old image file should be deleted after replacement"
        row2 = db.execute("SELECT image FROM buy_list WHERE id=?", (item_id,)).fetchone()
        new_image = row2["image"]
        assert new_image != old_image, "DB should store the new image filename"
        assert os.path.exists(os.path.join(upload_dir, new_image)), "New image file should exist"

    def test_edit_keeps_shared_image(self, client, db, upload_dir):
        # Create a shared image file on disk.
        shared_filename = "shared.jpg"
        shared_path = os.path.join(upload_dir, shared_filename)
        open(shared_path, "w").close()

        # Insert two buy_list rows that both reference the same image.
        db.execute(
            "INSERT INTO buy_list (name, desired_qty, image) VALUES (?, ?, ?)",
            ("SharedWine1", 1, shared_filename),
        )
        db.execute(
            "INSERT INTO buy_list (name, desired_qty, image) VALUES (?, ?, ?)",
            ("SharedWine2", 1, shared_filename),
        )
        db.commit()

        first_id = db.execute(
            "SELECT id FROM buy_list WHERE name='SharedWine1'"
        ).fetchone()["id"]

        # Edit the first row with a new image.
        resp = client.post(
            f"/buy-list/edit/{first_id}",
            data={"name": "SharedWine1", "desired_qty": "1", "image": _jpeg_upload("c.jpg")},
            headers=AJAX,
        )
        assert json.loads(resp.data)["ok"] is True

        # shared.jpg must still exist because SharedWine2 still references it.
        assert os.path.exists(shared_path), "Shared image must not be deleted while still referenced"

    def test_edit_missing_item_404(self, client):
        resp = client.post("/buy-list/edit/99999", data={"name": "x"}, headers=AJAX)
        assert resp.status_code == 404


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


class TestMoveDialogUI:
    def test_move_dialog_markup_present(self, client):
        resp = client.get("/buy-list")
        assert b'id="moveForm"' in resp.data
        assert b'id="moveOriginalYear"' in resp.data
        assert b'openMoveToCellar' in resp.data
        assert b'rebuyWine' in resp.data


class TestCellarOutOfStockFilter:
    def test_filter_option_present(self, client):
        resp = client.get("/")
        assert b'filterOutOfStock' in resp.data
