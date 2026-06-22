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
        assert b'href="' in resp.data and b'/buy-list' in resp.data
