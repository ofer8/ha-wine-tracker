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
