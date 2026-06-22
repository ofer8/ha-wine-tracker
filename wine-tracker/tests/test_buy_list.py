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
