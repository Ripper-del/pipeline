"""Unit tests for uniqreo/core/config.py's ADMIN_TELEGRAM_IDS parsing (the
allow-list that gates the /upload command). Uses importlib.reload since the
parsing runs as module-level code driven by an env var."""
import importlib

import dotenv

import core.config as config


def _reload_with_admin_ids(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ADMIN_TELEGRAM_IDS", raising=False)
    else:
        monkeypatch.setenv("ADMIN_TELEGRAM_IDS", value)
    # config.py calls load_dotenv() at import time, which would otherwise
    # re-populate ADMIN_TELEGRAM_IDS from a real local .env file on reload
    # and mask the "unset" case this test is exercising.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    importlib.reload(config)
    return config.ADMIN_TELEGRAM_IDS


def test_unset_admin_ids_fails_closed_to_empty_set(monkeypatch):
    assert _reload_with_admin_ids(monkeypatch, None) == set()


def test_empty_string_fails_closed_to_empty_set(monkeypatch):
    assert _reload_with_admin_ids(monkeypatch, "") == set()


def test_parses_comma_separated_ids(monkeypatch):
    assert _reload_with_admin_ids(monkeypatch, "111, 222,333") == {111, 222, 333}


def test_ignores_invalid_entries_but_keeps_valid_ones(monkeypatch):
    assert _reload_with_admin_ids(monkeypatch, "111,not-a-number,222") == {111, 222}
