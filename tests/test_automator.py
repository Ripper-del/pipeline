"""Unit tests for tiktok_scraper/automator.py: profile-ID resolution and the
multi-profile rotation loop (using a fake run_automation, no real Playwright)."""
import asyncio

import pytest
import automator


def test_parse_profile_ids_prefers_cli_list():
    assert automator.parse_profile_ids("a, b,c", "z", "x,y", "w") == ["a", "b", "c"]


def test_parse_profile_ids_falls_back_to_single_cli():
    assert automator.parse_profile_ids(None, "z", "x,y", "w") == ["z"]


def test_parse_profile_ids_falls_back_to_env_list():
    assert automator.parse_profile_ids(None, None, "x, y", "w") == ["x", "y"]


def test_parse_profile_ids_falls_back_to_env_single():
    assert automator.parse_profile_ids(None, None, None, "w") == ["w"]


def test_parse_profile_ids_defaults_to_local_chromium():
    assert automator.parse_profile_ids(None, None, None, None) == [None]


def test_parse_profile_ids_blank_cli_list_falls_back_to_local():
    assert automator.parse_profile_ids("  , ,", None, None, None) == [None]


def test_run_automation_for_profiles_continues_after_one_failure(monkeypatch):
    calls = []

    async def fake_run_automation(mode, profile_id, geo, limit, api_url, headless):
        calls.append(profile_id)
        if profile_id == "bad":
            raise automator.AutomationError("boom")

    async def fake_sleep(_seconds):
        pass

    monkeypatch.setattr(automator, "run_automation", fake_run_automation)
    monkeypatch.setattr(automator.asyncio, "sleep", fake_sleep)

    asyncio.run(automator.run_automation_for_profiles(
        "warmup", ["good1", "bad", "good2"], "US", 5, "http://x", True,
        delay_min=0, delay_max=0,
    ))
    assert calls == ["good1", "bad", "good2"]


def test_run_automation_for_profiles_raises_when_all_fail(monkeypatch):
    async def fake_run_automation(*a, **kw):
        raise automator.AutomationError("boom")

    async def fake_sleep(_seconds):
        pass

    monkeypatch.setattr(automator, "run_automation", fake_run_automation)
    monkeypatch.setattr(automator.asyncio, "sleep", fake_sleep)

    with pytest.raises(automator.AutomationError):
        asyncio.run(automator.run_automation_for_profiles(
            "warmup", ["a", "b"], "US", 5, "http://x", True,
            delay_min=0, delay_max=0,
        ))


def test_run_automation_for_profiles_single_profile_succeeds(monkeypatch):
    calls = []

    async def fake_run_automation(mode, profile_id, geo, limit, api_url, headless):
        calls.append(profile_id)

    monkeypatch.setattr(automator, "run_automation", fake_run_automation)

    # No sleep should even be attempted for a single-profile "rotation".
    asyncio.run(automator.run_automation_for_profiles(
        "spy", [None], "DE", 10, "http://x", True,
    ))
    assert calls == [None]
