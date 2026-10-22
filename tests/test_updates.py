"""Checking GitHub for a newer release: never sends anything, tells 主人 once per new version."""
import http.client
import io
import json
import random
import urllib.error
from pathlib import Path

import pytest

from claude_pet import __version__, claude_client, updates
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
DAY = updates.CHECK_EVERY_SEC
NOW = 1_800_000_000.0


@pytest.mark.parametrize(("candidate", "current", "newer"), [
    ("0.1.12", "0.1.11", True), ("v0.2", "0.1.11", True), ("0.1.11", "0.1.11", False), ("0.1.10", "0.1.11", False),
    ("1.0", "0.9.9", True), ("0.1.11.1", "0.1.11", True), ("0.1.11.0", "0.1.11", False),
    ("0.1.12-beta", "0.1.11", False), ("latest", "0.1.11", False), ("", "0.1.11", False), ("1", "0.1", False),
])
def test_is_newer(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def opener_for(body, seen=None):
    def opener(request, timeout):
        if seen is not None:
            seen.append((request, timeout))
        if isinstance(body, Exception):
            raise body
        if body == "too large":
            return Answer(b"x" * (updates.MAX_BYTES + 1))
        return Answer(body if isinstance(body, bytes) else json.dumps(body).encode())
    return opener


def test_fetch_latest_reads_only_the_public_release():
    seen = []
    assert updates.fetch_latest(opener_for({"tag_name": "v0.1.12", "body": "说明"}, seen)) == "0.1.12"
    (request, timeout), = seen
    assert request.full_url == updates.LATEST_URL and request.get_method() == "GET" and request.data is None
    assert request.get_header("User-agent") == f"desk-sister/{__version__}" and timeout == updates.TIMEOUT_SEC


@pytest.mark.parametrize("body", [
    {"tag_name": "v0.1.12", "prerelease": True}, {"tag_name": "v0.1.12", "draft": True}, {"tag_name": "nightly"},
    {"tag_name": 12}, {}, [], b"not json", b"\xff\xfe", "too large",
    urllib.error.URLError("offline"), OSError("reset"), TimeoutError(), http.client.IncompleteRead(b"{"),
    urllib.error.HTTPError(updates.LATEST_URL, 403, "rate limited", {}, None),
])
def test_fetch_latest_gives_up_quietly(body):
    assert updates.fetch_latest(opener_for(body)) is None


def test_config_cleans_update_fields():
    config = Config(check_updates=None, update_checked_at=float("nan"), update_seen="soon").normalized()
    assert (config.check_updates, config.update_checked_at, config.update_seen) == (True, 0.0, "")
    config = Config(check_updates=False, update_checked_at=NOW, update_seen="0.1.12").normalized()
    assert (config.check_updates, config.update_checked_at, config.update_seen) == (False, NOW, "0.1.12")


# ---- the pet -----------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    latest = {"version": "0.9.0", "calls": 0}

    def fetch():
        latest["calls"] += 1
        return latest["version"]

    monkeypatch.setattr(updates, "fetch_latest", fetch)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01"), SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("no model calls here"))
    ctrl._clock, ctrl._now = Clock(100.0), Clock(NOW)
    ctrl._spawn = lambda fn: fn()
    ctrl._rng = random.Random(1)
    yield ctrl, latest
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def beat(ctrl, seconds=0.0):
    ctrl._clock.now += seconds
    ctrl._now.now += seconds
    ctrl._heartbeat()


def test_no_check_before_start_then_one_shortly_after(pet):
    ctrl, latest = pet
    beat(ctrl, 3600)
    assert latest["calls"] == 0  # not started
    ctrl.start()
    ctrl.window.clear_bubble()
    beat(ctrl, 10)
    assert latest["calls"] == 0
    beat(ctrl, controller_module.UPDATE_FIRST_DELAY_SEC)
    assert latest["calls"] == 1 and ctrl.update_available == "0.9.0" and ctrl.config.update_checked_at == ctrl._now()
    assert "v0.9.0" in ctrl.window.full_text and ctrl.config.update_seen == "0.9.0"  # told once
    ctrl.window.clear_bubble()
    beat(ctrl, DAY - 60)
    assert latest["calls"] == 1  # once a day
    beat(ctrl, 120)
    assert latest["calls"] == 2 and ctrl.window.full_text == ""  # the same version is not told again
    latest["version"] = "0.9.1"
    beat(ctrl, DAY)
    assert "v0.9.1" in ctrl.window.full_text


def test_nothing_newer(pet):
    ctrl, latest = pet
    latest["version"] = __version__
    ctrl.start()
    ctrl.window.clear_bubble()
    beat(ctrl, 60)
    assert latest["calls"] == 1 and ctrl.update_available == "" and ctrl.window.full_text == ""
    assert ctrl.update_status == f"已是最新版（{__version__}）"


def test_a_failed_check_is_tried_again_after_an_hour(pet):
    ctrl, latest = pet
    latest["version"] = None
    ctrl.start()
    beat(ctrl, 60)
    assert latest["calls"] == 1 and ctrl.config.update_checked_at == 0.0 and "检查失败" in ctrl.update_status
    beat(ctrl, updates.RETRY_SEC - 120)
    assert latest["calls"] == 1
    beat(ctrl, 120)
    assert latest["calls"] == 2


def test_a_crashing_check_is_not_left_running(pet, monkeypatch):
    ctrl, _latest = pet

    def crash():
        raise RuntimeError("bug")

    monkeypatch.setattr(updates, "fetch_latest", crash)
    ctrl.check_updates_now()
    assert not ctrl.update_checking and "检查失败" in ctrl.update_status


def test_a_withdrawn_release_is_not_announced(pet):
    ctrl, latest = pet
    ctrl.start()
    ctrl.window.say("talk", "我在说话")
    beat(ctrl, 60)  # 0.9.0 found; the news waits for the bubble
    latest["version"] = __version__
    ctrl.check_updates_now()
    ctrl.window.clear_bubble()
    beat(ctrl, 1)
    assert ctrl.window.full_text == "" and ctrl.config.update_seen == ""


def test_a_failed_check_soon_after_a_good_one_is_retried_in_an_hour(pet):
    ctrl, latest = pet
    ctrl.start()
    beat(ctrl, 60)
    assert latest["calls"] == 1
    beat(ctrl, 3600)
    latest["version"] = None
    ctrl.check_updates_now()
    assert latest["calls"] == 2
    latest["version"] = "0.9.0"
    beat(ctrl, updates.RETRY_SEC + 1)
    assert latest["calls"] == 3
    beat(ctrl, updates.RETRY_SEC + 1)
    assert latest["calls"] == 3  # back to once a day


def test_a_version_found_but_not_told_is_told_after_a_restart(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(updates, "fetch_latest", lambda: pytest.fail("checked less than a day ago"))
    for seen, told in (("", True), ("0.9.0", False), ("0.9.1", False)):
        config = Config(greeted_on="2099-01-01", update_checked_at=NOW - 60, update_latest="0.9.0", update_seen=seen)
        ctrl = controller_module.PetController(app, config, SPRITES, tmp_path / "config.json")
        ctrl._clock, ctrl._now = Clock(100.0), Clock(NOW)
        assert ctrl.update_available == "0.9.0" and "v0.9.0" in ctrl.update_status
        ctrl.start()
        ctrl.window.clear_bubble()
        beat(ctrl, 60)
        assert ("v0.9.0" in ctrl.window.full_text) is told
        assert ctrl.config.update_seen == (seen or "0.9.0")
    config = Config(update_latest=__version__)
    ctrl = controller_module.PetController(app, config, SPRITES, tmp_path / "config.json")
    assert ctrl.update_available == "" and ctrl.update_status == f"已是最新版（{__version__}）"


def test_an_older_release_after_a_newer_one_is_not_told_again(pet):
    ctrl, latest = pet
    ctrl.start()
    for version, told in (("0.9.0", True), ("0.9.1", True), ("0.9.0", False)):
        latest["version"] = version
        ctrl.window.clear_bubble()
        ctrl.check_updates_now()
        beat(ctrl, 1)
        assert (f"v{version}" in ctrl.window.full_text) is told
    assert ctrl.config.update_seen == "0.9.1"


def test_a_day_old_check_from_the_last_run_counts(pet):
    ctrl, latest = pet
    ctrl.config.update_checked_at = NOW - 3600
    ctrl.start()
    beat(ctrl, 60)
    assert latest["calls"] == 0
    ctrl.config.update_checked_at = NOW + DAY  # the clock was set back: check again
    beat(ctrl, 1)
    assert latest["calls"] == 1


def test_switched_off_only_the_button_checks(pet):
    ctrl, latest = pet
    ctrl.set_check_updates(False)
    ctrl.start()
    beat(ctrl, DAY)
    assert latest["calls"] == 0
    ctrl.check_updates_now()
    assert latest["calls"] == 1 and ctrl.update_available == "0.9.0"


def test_the_news_waits_while_she_may_not_talk(pet):
    ctrl, _latest = pet
    ctrl.start()
    ctrl.window.say("talk", "我在说话")
    beat(ctrl, 60)
    assert ctrl.window.full_text == "我在说话" and ctrl.config.update_seen == ""
    ctrl.window.clear_bubble()
    ctrl.quiet = True
    ctrl._announce_update()
    assert ctrl.window.full_text == ""
    ctrl.quiet = False
    beat(ctrl, 1)
    assert "v0.9.0" in ctrl.window.full_text and ctrl.config.update_seen == "0.9.0"


def test_about_page(pet):
    ctrl, latest = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    assert window.updates_box.isChecked() and window.update_label.text() == ""
    window.updates_box.setChecked(False)
    assert ctrl.config.check_updates is False
    window.check_now.click()
    assert latest["calls"] == 1
    assert updates.RELEASES_PAGE in window.update_label.text() and "v0.9.0" in window.update_label.text()
    ctrl.update_checking = True
    window.refresh()
    assert not window.check_now.isEnabled()
