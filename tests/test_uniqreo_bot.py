"""Unit tests for uniqreo/bot.py's ops-group control panel: per-thread button
resolution, button-press routing, and the subprocess start/stop job tracking
(no real pyrogram Client or subprocess involved). uniqreo/bot.py is the single
merged bot process (uniqueization, /upload, lead funnel, control panel)."""
import asyncio

import pytest

import bot


@pytest.fixture
def temp_profiles_db(tmp_path, monkeypatch):
    """Redirects the shared SQLite file to a scratch path so profile-binding
    tests never touch the real data/followups.db."""
    db_file = tmp_path / "followups.db"
    monkeypatch.setattr(bot, "DB_FILE", str(db_file))
    bot.init_db()
    return db_file


def test_resolve_thread_button_map_all_threads_configured():
    button_map = bot.resolve_thread_button_map(10, 20, 30)
    assert button_map == {
        10: [[bot.STATS_BUTTON]],
        20: [[bot.START_WARMUP_BUTTON, bot.STOP_WARMUP_BUTTON]],
        30: [[bot.START_SPY_BUTTON, bot.STOP_SPY_BUTTON]],
    }


def test_resolve_thread_button_map_skips_unset_threads():
    button_map = bot.resolve_thread_button_map(None, 0, 30)
    assert button_map == {30: [[bot.START_SPY_BUTTON, bot.STOP_SPY_BUTTON]]}


def test_resolve_thread_button_map_merges_warmup_and_spy_into_one_thread():
    # The whole point: pointing WARMUP_THREAD_ID and SPY_THREAD_ID at the same
    # numeric thread (one chat for both) must not let one set of buttons
    # silently overwrite the other, which a naive dict-assignment would do.
    button_map = bot.resolve_thread_button_map(None, 55, 55)
    assert button_map == {
        55: [
            [bot.START_WARMUP_BUTTON, bot.STOP_WARMUP_BUTTON],
            [bot.START_SPY_BUTTON, bot.STOP_SPY_BUTTON],
        ]
    }


def test_resolve_thread_button_map_includes_autoupload_button_for_upload_thread():
    button_map = bot.resolve_thread_button_map(None, None, None, upload_thread=77)
    assert button_map == {77: [[bot.START_AUTOUPLOAD_BUTTON]]}


def test_resolve_thread_button_map_upload_thread_defaults_to_omitted():
    # Existing 3-arg callers (and any thread config without UPLOAD_THREAD_ID
    # set) must not get a stray autoupload button.
    button_map = bot.resolve_thread_button_map(10, 20, 30)
    assert 77 not in button_map
    assert all(bot.START_AUTOUPLOAD_BUTTON not in row for rows in button_map.values() for row in rows)


def test_parse_thread_id_variants():
    assert bot.parse_thread_id("42") == 42
    assert bot.parse_thread_id(None) is None
    assert bot.parse_thread_id("") is None
    assert bot.parse_thread_id("not-a-number") is None


def test_route_button_press_matches_correct_thread():
    button_map = {20: [[bot.START_WARMUP_BUTTON, bot.STOP_WARMUP_BUTTON]], 30: [[bot.START_SPY_BUTTON]]}
    assert bot.route_button_press(bot.START_WARMUP_BUTTON, 20, button_map) == "start_warmup"
    assert bot.route_button_press(bot.STOP_WARMUP_BUTTON, 20, button_map) == "stop_warmup"
    assert bot.route_button_press(bot.START_SPY_BUTTON, 30, button_map) == "start_spy"


def test_route_button_press_matches_autoupload_button():
    button_map = {40: [[bot.START_AUTOUPLOAD_BUTTON]]}
    assert bot.route_button_press(bot.START_AUTOUPLOAD_BUTTON, 40, button_map) == "start_autoupload"


def test_route_button_press_ignores_button_text_in_wrong_thread():
    # The "start warmup" label sent in the spy thread must not match anything -
    # keeps each thread's keyboard from accidentally controlling another thread.
    button_map = {20: [[bot.START_WARMUP_BUTTON]], 30: [[bot.START_SPY_BUTTON]]}
    assert bot.route_button_press(bot.START_WARMUP_BUTTON, 30, button_map) is None


def test_route_button_press_ignores_unrecognized_text():
    button_map = {20: [[bot.START_WARMUP_BUTTON]]}
    assert bot.route_button_press("random text", 20, button_map) is None
    assert bot.route_button_press(bot.START_WARMUP_BUTTON, None, button_map) is None


def test_route_button_press_works_for_combined_warmup_spy_thread():
    button_map = bot.resolve_thread_button_map(None, 55, 55)
    assert bot.route_button_press(bot.START_WARMUP_BUTTON, 55, button_map) == "start_warmup"
    assert bot.route_button_press(bot.STOP_WARMUP_BUTTON, 55, button_map) == "stop_warmup"
    assert bot.route_button_press(bot.START_SPY_BUTTON, 55, button_map) == "start_spy"
    assert bot.route_button_press(bot.STOP_SPY_BUTTON, 55, button_map) == "stop_spy"


def test_has_configured_profiles(monkeypatch):
    monkeypatch.delenv("ADSPOWER_PROFILE_IDS", raising=False)
    monkeypatch.delenv("ADSPOWER_PROFILE_ID", raising=False)
    assert bot.has_configured_profiles() is False

    monkeypatch.setenv("ADSPOWER_PROFILE_ID", "p1")
    assert bot.has_configured_profiles() is True


def test_format_stats_reply_contains_values():
    text = bot.format_stats_reply({"count": 4, "charged_total": 20.0, "hold_total": 1.5})
    assert "4" in text
    assert "20.00" in text
    assert "1.50" in text


class _FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = -15


def test_start_job_launches_and_tracks_process(monkeypatch):
    fake_proc = _FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(bot.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    running_jobs = {}
    started = asyncio.run(bot.start_job(running_jobs, "warmup", ["--mode", "warmup"], "/tmp"))
    assert started is True
    assert running_jobs["warmup"] is fake_proc


def test_start_job_refuses_double_start(monkeypatch):
    fake_proc = _FakeProcess()  # returncode None -> still running

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise AssertionError("should not spawn a second process while one is still running")

    monkeypatch.setattr(bot.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    running_jobs = {"warmup": fake_proc}
    started = asyncio.run(bot.start_job(running_jobs, "warmup", ["--mode", "warmup"], "/tmp"))
    assert started is False


def test_start_job_allows_restart_after_previous_run_finished(monkeypatch):
    finished_proc = _FakeProcess()
    finished_proc.returncode = 0  # already exited
    new_proc = _FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return new_proc

    monkeypatch.setattr(bot.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    running_jobs = {"warmup": finished_proc}
    started = asyncio.run(bot.start_job(running_jobs, "warmup", ["--mode", "warmup"], "/tmp"))
    assert started is True
    assert running_jobs["warmup"] is new_proc


def test_stop_job_terminates_running_process():
    fake_proc = _FakeProcess()
    running_jobs = {"spy": fake_proc}
    stopped = asyncio.run(bot.stop_job(running_jobs, "spy"))
    assert stopped is True
    assert fake_proc.terminated is True


def test_stop_job_noop_when_nothing_running():
    running_jobs = {}
    stopped = asyncio.run(bot.stop_job(running_jobs, "spy"))
    assert stopped is False


def test_stop_job_noop_when_already_finished():
    finished_proc = _FakeProcess()
    finished_proc.returncode = 0
    running_jobs = {"spy": finished_proc}
    stopped = asyncio.run(bot.stop_job(running_jobs, "spy"))
    assert stopped is False
    assert finished_proc.terminated is False


def test_add_and_get_user_profiles(temp_profiles_db):
    bot.add_profile(111, "profileA")
    bot.add_profile(111, "profileB")
    bot.add_profile(222, "profileC")

    assert set(bot.get_user_profiles(111)) == {"profileA", "profileB"}
    assert bot.get_user_profiles(222) == ["profileC"]


def test_add_profile_is_idempotent(temp_profiles_db):
    bot.add_profile(111, "profileA")
    bot.add_profile(111, "profileA")
    assert bot.get_user_profiles(111) == ["profileA"]


def test_remove_profile(temp_profiles_db):
    bot.add_profile(111, "profileA")
    bot.add_profile(111, "profileB")
    bot.remove_profile(111, "profileA")
    assert bot.get_user_profiles(111) == ["profileB"]


def test_remove_profile_noop_when_not_bound(temp_profiles_db):
    bot.add_profile(111, "profileA")
    bot.remove_profile(111, "not-bound")
    assert bot.get_user_profiles(111) == ["profileA"]


def test_get_user_profiles_empty_for_unknown_user(temp_profiles_db):
    assert bot.get_user_profiles(999) == []
