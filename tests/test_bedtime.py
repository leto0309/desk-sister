"""Bedtime reminders: at most once a night (or every two hours, or never), shared by comments and self-talk."""
import random
import time
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from claude_pet import bedtime, claude_client, persona
from claude_pet import controller as controller_module
from claude_pet.claude_client import ClaudeResult
from claude_pet.config import Config, load_config

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


def at(day: int, hour: int, minute: int = 0) -> float:
    """A local wall-clock time in October 2026."""
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


def test_the_night_runs_from_the_chosen_hour_to_five():
    assert [h for h in range(24) if bedtime.is_night(h, 23)] == [0, 1, 2, 3, 4, 23]
    assert [h for h in range(24) if bedtime.is_night(h, 21)] == [0, 1, 2, 3, 4, 21, 22, 23]
    assert [h for h in range(24) if bedtime.is_night(h, 1)] == [1, 2, 3, 4]


def test_after_midnight_is_still_the_same_night():
    assert bedtime.night_of(at(20, 23, 30)) == bedtime.night_of(at(21, 2)) == bedtime.night_of(at(21, 4, 59))
    assert bedtime.night_of(at(21, 23)) != bedtime.night_of(at(21, 2))


def test_once_a_night_every_two_hours_or_never():
    first = at(20, 23, 10)
    assert bedtime.may_remind("nightly", first, 0)
    assert not bedtime.may_remind("nightly", at(21, 3), first)  # same night, after midnight
    assert bedtime.may_remind("nightly", at(21, 23, 5), first)  # the next night
    assert not bedtime.may_remind("every_2h", first + 7199, first)
    assert bedtime.may_remind("every_2h", first + 7200, first)
    assert bedtime.may_remind("every_2h", first - 60, first)  # clock set back: never blocked for good
    assert not bedtime.may_remind("off", first, 0)


def test_what_counts_as_a_reminder():
    for text in ("主人早点休息吧", "熬夜伤身", "该睡了～", "晚安！"):
        assert bedtime.mentions(text)
    assert not bedtime.mentions("这段代码缩进好整齐")


def test_the_model_is_told_whether_it_may_bring_it_up():
    plain = persona.build_user_text("t", "p.exe", "15:00", [])
    assert persona.build_user_text("t", "p.exe", "15:00", [], bedtime="") == plain  # the day is unchanged
    assert bedtime.MAY in persona.build_user_text("t", "p.exe", "23:30", [], bedtime="ok")
    allowed_not = persona.build_user_text("t", "p.exe", "23:30", [], bedtime="no")
    assert bedtime.MAY_NOT in allowed_not and bedtime.MAY not in allowed_not
    assert "23 点" not in persona.SYSTEM_PROMPT and "不要主动催主人睡觉" in persona.SYSTEM_PROMPT


def test_settings_are_kept_and_broken_values_fall_back(tmp_path):
    assert (Config().bedtime_reminder, Config().night_start_hour, Config().bedtime_reminded_at) == ("nightly", 23, 0.0)
    path = tmp_path / "config.json"
    path.write_text('{"bedtime_reminder": "every_2h", "night_start_hour": 1, "bedtime_reminded_at": 1790000000.5}',
                    encoding="utf-8")
    config = load_config(path)
    assert (config.bedtime_reminder, config.night_start_hour, config.bedtime_reminded_at) == ("every_2h", 1, 1790000000.5)
    path.write_text('{"bedtime_reminder": "often", "night_start_hour": 17, "bedtime_reminded_at": "soon",'
                    ' "interval_sec": 120}', encoding="utf-8")
    config = load_config(path)
    assert (config.bedtime_reminder, config.night_start_hour, config.bedtime_reminded_at) == ("nightly", 23, 0.0)
    assert config.interval_sec == 120  # one broken value never resets the rest


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append(config.bedtime_reminded_at))
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json")
    clock = {"now": at(20, 23, 30), "hour": 23}
    ctrl._now = lambda: clock["now"]
    ctrl._hour = lambda: clock["hour"]
    ctrl._rng = random.Random(4)
    return ctrl, clock, saved


def test_a_night_comment_about_sleep_starts_the_wait(pet, monkeypatch):
    ctrl, clock, saved = pet
    asked = []
    monkeypatch.setattr(ctrl, "_spawn", lambda fn: fn())
    monkeypatch.setattr(ctrl, "_work", lambda job: asked.append(job.bedtime) or ctrl.reply_ready.emit(
        controller_module.Outcome(job.generation, "reply", force=True,
                                  result=ClaudeResult(True, "sad|主人，已经很晚了，早点休息吧"))))
    ctrl.tick(force=True, user_message="在吗")
    assert asked == ["ok"] and ctrl.config.bedtime_reminded_at == clock["now"] and saved[-1] == clock["now"]
    clock["now"] += 3600
    clock["hour"] = 0
    ctrl.tick(force=True, user_message="还在吗")
    assert asked == ["ok", "no"]  # the same night: the model is told not to bring it up
    clock["now"] = at(21, 15)
    clock["hour"] = 15
    ctrl.tick(force=True, user_message="下午好")
    assert asked[-1] == ""  # daytime: nothing said about it


def test_a_comment_that_does_not_mention_sleep_leaves_the_reminder_due(pet, monkeypatch):
    ctrl, _clock, _saved = pet
    monkeypatch.setattr(ctrl, "_spawn", lambda fn: fn())
    monkeypatch.setattr(ctrl, "_work", lambda job: ctrl.reply_ready.emit(
        controller_module.Outcome(job.generation, "reply", force=True, result=ClaudeResult(True, "happy|代码好整齐"))))
    ctrl.tick(force=True, user_message="看看")
    assert ctrl.config.bedtime_reminded_at == 0.0 and ctrl._bedtime() == "ok"


def test_self_talk_shares_the_same_reminder(pet, monkeypatch):
    ctrl, clock, _saved = pet
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("self-talk never calls a model"))
    ctrl.config.bedtime_reminded_at = clock["now"] - 60  # a comment just reminded
    said = []
    for _ in range(80):
        ctrl.window.clear_bubble()
        ctrl.window.last_said_at = float("-inf")
        assert ctrl.maybe_self_talk()
        said.append(ctrl.window.full_text)
    assert not any(bedtime.mentions(text) for text in said)  # nothing about sleep or rest this night
    ctrl.config.bedtime_reminded_at = 0.0  # nothing yet tonight: a go-to-bed line may come, then it waits
    for _ in range(200):
        ctrl.window.clear_bubble()
        ctrl.window.last_said_at = float("-inf")
        ctrl.maybe_self_talk()
        if bedtime.mentions(ctrl.window.full_text):
            break
    assert ctrl.config.bedtime_reminded_at == clock["now"] and ctrl._bedtime() == "no"


def test_off_means_never_at_night(pet):
    ctrl, _clock, _saved = pet
    ctrl.set_bedtime_reminder("off")
    assert ctrl._bedtime() == "no"
    ctrl.set_bedtime_reminder("sometimes")  # unknown: ignored
    assert ctrl.config.bedtime_reminder == "off"


def test_the_settings_page_sets_both_choices(pet):
    ctrl, clock, _saved = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    assert window.bedtime_combo.currentData() == "nightly" and window.night_combo.currentData() == 23
    window.bedtime_combo.setCurrentIndex(window.bedtime_combo.findData("every_2h"))
    window.night_combo.setCurrentIndex(window.night_combo.findData(1))
    assert (ctrl.config.bedtime_reminder, ctrl.config.night_start_hour) == ("every_2h", 1)
    clock["hour"] = 23
    assert ctrl._bedtime() == ""  # with the night starting at 1:00, 23:00 is not night yet
    window.close()


def test_implausible_reminder_times_are_forgotten_not_fatal(tmp_path):
    path = tmp_path / "config.json"
    for value in ("1", "true", "1e12", "-5"):
        path.write_text('{"bedtime_reminded_at": %s}' % value, encoding="utf-8")
        assert load_config(path).bedtime_reminded_at == 0.0
    assert bedtime.may_remind("nightly", at(20, 23), 1e18)  # never raises, even if handed one directly


def test_the_night_follows_the_wall_clock(monkeypatch):
    class Shifted(bedtime.datetime.datetime):  # a fall-back night: 4:30 local is 6 h after 23:30 local
        @classmethod
        def fromtimestamp(cls, ts):
            return {1: cls(2026, 10, 31, 23, 30), 2: cls(2026, 11, 1, 4, 30)}[ts]

    monkeypatch.setattr(bedtime.datetime, "datetime", Shifted)
    assert bedtime.night_of(1) == bedtime.night_of(2) == "2026-10-31"


def _arrive(ctrl, text):
    """A sleep-mentioning reply to an automatic look comes back from the model."""
    ctrl.generation += 1
    ctrl.busy = True
    ctrl._on_reply(controller_module.Outcome(ctrl.generation, "reply", force=False, result=ClaudeResult(True, text)))


def test_a_reply_she_never_says_is_no_reminder(pet):
    ctrl, clock, _saved = pet
    ctrl.quiet = True  # full screen: the reply is held back
    _arrive(ctrl, "sad|主人早点休息吧")
    assert ctrl.deferred is not None and ctrl.config.bedtime_reminded_at == 0.0
    _arrive(ctrl, "happy|这段代码好整齐")  # replaced by a later one: the first is never said
    ctrl.quiet = False
    ctrl._flush_deferred()
    assert ctrl.window.full_text == "这段代码好整齐" and ctrl.config.bedtime_reminded_at == 0.0
    ctrl.quiet = True
    _arrive(ctrl, "sad|主人早点休息吧")
    ctrl.config.paused = True  # paused before the full-screen program closed: dropped unsaid
    ctrl.quiet = False
    ctrl._flush_deferred()
    assert ctrl.config.bedtime_reminded_at == 0.0
    ctrl.config.paused = False
    ctrl.quiet = True
    _arrive(ctrl, "sad|主人早点休息吧")
    ctrl.quiet = False
    ctrl._flush_deferred()  # said after all: now it counts
    assert ctrl.window.full_text == "主人早点休息吧" and ctrl.config.bedtime_reminded_at == clock["now"]


def test_a_reply_dropped_for_a_claude_code_notice_is_no_reminder(pet):
    ctrl, clock, _saved = pet
    ctrl.notice_generation = ctrl.generation + 1  # a notice was shown while this look was running
    _arrive(ctrl, "sad|主人早点休息吧")
    assert ctrl.window.full_text != "主人早点休息吧" and ctrl.config.bedtime_reminded_at == 0.0
    ctrl.notice_generation = -1
    _arrive(ctrl, "sad|主人早点休息吧")
    assert ctrl.window.full_text == "主人早点休息吧" and ctrl.config.bedtime_reminded_at == clock["now"]
