import random
from pathlib import Path

import pytest

from claude_pet import claude_client, persona
from claude_pet.config import Config, load_config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
LATE_NIGHT = {text for first, last, lines in persona.TIME_TALK if first == 23 for _mood, text in lines}
LUNCH = {text for first, last, lines in persona.TIME_TALK if first == 11 for _mood, text in lines}


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ctrl(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("self-talk must never call Claude"))
    now = [10_000.0]
    ctrl._clock = lambda: now[0]
    ctrl._hour = lambda: 15
    ctrl._rng = random.Random(7)
    ctrl.now = now
    return ctrl


def test_lines_follow_the_hour_and_sleep():
    rng = random.Random(1)
    night = {persona.self_talk_line(1, False, [], rng).text for _ in range(300)}
    afternoon = {persona.self_talk_line(15, False, [], rng).text for _ in range(300)}
    noon = {persona.self_talk_line(12, False, [], rng).text for _ in range(300)}
    assert night & LATE_NIGHT and not afternoon & LATE_NIGHT  # late-night lines wrap past midnight
    assert noon & LUNCH and not afternoon & LUNCH
    dreams = {persona.self_talk_line(15, True, [], rng) for _ in range(50)}
    assert {r.text for r in dreams} <= {text for _m, text in persona.SLEEP_TALK}
    assert {r.mood for r in dreams} == {"sleep"}
    for mood, _text in persona.SELF_TALK + persona.SLEEP_TALK:
        assert mood in persona.MOODS


def test_recent_lines_are_avoided_until_everything_was_said():
    rng = random.Random(3)
    all_dreams = [text for _m, text in persona.SLEEP_TALK]
    for _ in range(30):
        assert persona.self_talk_line(15, True, all_dreams[:-1], rng).text == all_dreams[-1]
    assert persona.self_talk_line(15, True, all_dreams, rng).text in all_dreams  # all recent: still talks


def test_she_talks_to_herself_without_calling_claude(ctrl):
    ctrl.window.last_said_at = float("-inf")
    assert ctrl.maybe_self_talk()
    assert ctrl.window.full_text and ctrl.window.full_text in {t for _m, t in persona.SELF_TALK + [x for *_h, ls in persona.TIME_TALK for x in ls]}
    assert list(ctrl.self_talk_recent) == [ctrl.window.full_text]


def test_she_stays_quiet_when_something_else_is_going_on(ctrl):
    ctrl.window.say("talk", "正在说的话")
    assert not ctrl.maybe_self_talk()  # a bubble is on screen
    ctrl.window.clear_bubble()
    assert not ctrl.maybe_self_talk()  # said something less than a minute ago
    ctrl.now[0] += 61
    for flag in ("busy", "quit_pending"):  # full screen is covered with a real check further below
        setattr(ctrl, flag, True)
        assert not ctrl.maybe_self_talk(), flag
        setattr(ctrl, flag, False)
    ctrl.config.self_talk = False
    assert not ctrl.maybe_self_talk()
    ctrl.config.self_talk = True
    assert ctrl.maybe_self_talk()


def test_asleep_she_only_murmurs(ctrl):
    ctrl.asleep = True
    assert ctrl.maybe_self_talk()
    assert ctrl.window.mood == "sleep" and "Zzz" in ctrl.window.full_text
    ctrl.window.clear_bubble()
    assert ctrl.window.mood == "sleep"  # still asleep after the murmur


def test_schedule_uses_the_configured_range_and_the_menu_switch(ctrl):
    ctrl.config.self_talk_min_sec, ctrl.config.self_talk_max_sec = 200, 400
    for _ in range(20):
        ctrl._schedule_self_talk()
        assert ctrl.self_talk_timer.isActive() and 200_000 <= ctrl.self_talk_timer.interval() <= 400_000
    action = next(a for a in ctrl.tray.contextMenu().actions() if a.text() == "自言自语")
    assert action.isChecked()
    action.trigger()  # switch off
    assert not ctrl.config.self_talk and not ctrl.self_talk_timer.isActive()
    action.trigger()  # and back on
    assert ctrl.config.self_talk and ctrl.self_talk_timer.isActive()
    ctrl.shutdown()
    assert not ctrl.self_talk_timer.isActive()


def test_tick_reschedules_even_when_skipped(ctrl):
    ctrl.busy = True
    ctrl._self_talk_tick()
    assert ctrl.self_talk_timer.isActive()


def test_self_talk_settings_are_clamped(tmp_path):
    import json

    path = tmp_path / "c.json"
    path.write_text(json.dumps({"self_talk": 0, "self_talk_min_sec": 1, "self_talk_max_sec": 5}), encoding="utf-8")
    config = load_config(path)
    assert (config.self_talk, config.self_talk_min_sec, config.self_talk_max_sec) == (False, 30, 30)
    path.write_text(json.dumps({"self_talk_min_sec": 500, "self_talk_max_sec": 99999}), encoding="utf-8")
    config = load_config(path)
    assert (config.self_talk_min_sec, config.self_talk_max_sec) == (500, 7200)
    assert (Config().self_talk, Config().self_talk_min_sec, Config().self_talk_max_sec) == (True, 180, 600)


def test_going_full_screen_between_heartbeats_still_silences_her(ctrl, monkeypatch):
    from claude_pet.capture import WindowInfo

    video = WindowInfo(5, "movie", "PotPlayer.exe", 4545, (0, 0, 1920, 1080))
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: video)
    monkeypatch.setattr(controller_module.capture, "window_info", lambda _hwnd: video)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda info: info is not None and info.hwnd == 5)
    assert not ctrl.quiet  # the last heartbeat saw no full screen
    ctrl._self_talk_tick()
    assert ctrl.quiet and ctrl.window.full_text == ""  # checked on the spot: stays silent
    assert ctrl.self_talk_timer.isActive()  # and tries again later
    ctrl.config.quiet_fullscreen = False
    ctrl.quiet = False
    assert ctrl.maybe_self_talk()  # with quiet mode switched off she may talk over full screen
