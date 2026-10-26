"""The day's summary: once a day from the chosen hour, from the companion memory's time per activity."""
import random
import time
from pathlib import Path

import pytest

from claude_pet import bedtime, claude_client, i18n, persona, persona_en
from claude_pet.config import Config
from claude_pet.memory import ACTIVITIES

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


def test_summary_line_lists_the_top_three_and_a_word_on_the_first():
    seconds = {"看视频": 2400, "写代码": 11520, "聊天": 900, "听音乐": 700, "上网": 300}
    tails = set()
    for seed in range(30):
        text = persona.summary_line(seconds, random.Random(seed)).text
        head = "今天的小结：写代码约 3.2 小时、看视频约 40 分钟、聊天约 15 分钟。"
        assert text.startswith(head)
        tails.add(text[len(head):])
    assert tails == set(persona.SUMMARY_TAILS["写代码"])  # each of the main activity's tails, now and then


def test_every_activity_has_several_tails():
    assert set(persona.SUMMARY_TAILS) == set(ACTIVITIES)
    assert all(len(tails) >= 2 for tails in persona.SUMMARY_TAILS.values())


@pytest.mark.parametrize("seconds", [{}, {"写代码": 1700}, {"写代码": 500, "看视频": 500, "聊天": 500, "上网": 500}])
def test_too_little_is_no_summary(seconds):
    assert persona.summary_line(seconds) is None  # under half an hour, or nothing reaching 10 minutes


def test_summaries_never_mention_sleep():
    for activity, tails in persona.SUMMARY_TAILS.items():
        assert not bedtime.mentions(persona.summary_line({activity: 7200}).text)
        assert not [tail for tail in tails if bedtime.mentions(tail)]


def test_config_cleans_summary_fields():
    config = Config(daily_summary_hour=19, summary_on=5).normalized()
    assert (config.daily_summary_hour, config.summary_on) == (21, "")
    config = Config(daily_summary_hour=True).normalized()
    assert config.daily_summary_hour == 21
    config = Config(daily_summary_hour=0, summary_on="2026-10-23").normalized()
    assert (config.daily_summary_hour, config.summary_on) == (0, "2026-10-23")


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def at(day, hour, minute=0):
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False), ("foreground_window", lambda: None)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    config = Config(greeted_on="2026-10-23", check_updates=False, self_talk=False)
    ctrl = controller_module.PetController(app, config, SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("no model calls here"))
    wall = Clock(at(23, 20, 30))
    ctrl._clock, ctrl._now, ctrl._rng = Clock(100.0), wall, random.Random(1)
    ctrl.memory.now = wall
    ctrl.memory.day = ctrl.memory._today()
    ctrl.memory.seconds = {"写代码": 11520, "看视频": 2400}
    ctrl.window.clear_bubble()
    yield ctrl, wall
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def summary(ctrl):
    return ctrl.window.full_text.startswith("今天的小结：")


def test_from_the_chosen_hour_once_a_day(pet):
    ctrl, wall = pet
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""  # 20:30, the summary is from 21:00
    wall.now = at(23, 21, 0)
    ctrl._heartbeat()
    assert summary(ctrl) and ctrl.config.summary_on == "2026-10-23"
    ctrl.window.clear_bubble()
    wall.now = at(23, 22)
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""
    wall.now = at(24, 21)  # the next evening
    assert ctrl.memory.today_seconds() == {}  # a new day in the memory too
    ctrl.memory.seconds = {"打游戏": 3600}
    ctrl._heartbeat()
    assert ctrl.window.full_text in {f"今天的小结：打游戏约 1.0 小时。{tail}" for tail in persona.SUMMARY_TAILS["打游戏"]}


def test_it_waits_until_she_may_talk(pet):
    ctrl, wall = pet
    wall.now = at(23, 21)
    ctrl.window.say("talk", "我在说话")
    ctrl._heartbeat()
    assert ctrl.config.summary_on == ""
    ctrl.window.clear_bubble()
    ctrl.asleep = True
    ctrl._summarize_day_if_due()
    ctrl.asleep = False
    ctrl.quiet = True
    ctrl._summarize_day_if_due()
    ctrl.quiet = False
    ctrl.quit_pending = True
    ctrl._summarize_day_if_due()
    ctrl.quit_pending = False
    assert ctrl.window.full_text == "" and ctrl.config.summary_on == ""
    ctrl._summarize_day_if_due()
    assert summary(ctrl)


def test_too_little_today_waits_for_more(pet):
    ctrl, wall = pet
    wall.now = at(23, 21)
    ctrl.memory.seconds = {"写代码": 1200}
    ctrl._heartbeat()
    assert ctrl.window.full_text == "" and ctrl.config.summary_on == ""
    ctrl.memory.seconds = {"写代码": 2400}
    ctrl._heartbeat()
    assert summary(ctrl)


def test_off_or_without_memory_nothing(pet):
    ctrl, wall = pet
    wall.now = at(23, 23)
    ctrl.set_daily_summary(0)
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""
    ctrl.set_daily_summary(18)
    ctrl.config.companion_memory = False
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""
    ctrl.set_daily_summary(19)  # not a choice: unchanged
    assert ctrl.config.daily_summary_hour == 18


def test_a_restart_does_not_repeat_it(pet):
    ctrl, wall = pet
    wall.now = at(23, 21)
    ctrl.config.summary_on = "2026-10-23"
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""


def test_settings_row(pet):
    ctrl, _wall = pet
    ctrl.open_settings()
    window = ctrl.settings_window
    assert window.summary_combo.currentData() == 21 and window.summary_combo.isEnabled()
    window.summary_combo.setCurrentIndex(window.summary_combo.findData(0))
    assert ctrl.config.daily_summary_hour == 0
    window.memory_box.setChecked(False)
    assert window.summary_combo.isEnabled()  # the focus timer's part needs no memory


# ---- the focus timer's part ------------------------------------------------------------------------------
def test_the_summary_tells_the_pomodoros_too():
    line = persona.summary_line({"写代码": 3 * 3600.0}, random.Random(1), (4, 100 * 60.0))
    assert line.text.startswith("今天的小结：写代码约 3.0 小时；专注了 4 个番茄（约 1.7 小时）。")


def test_a_day_with_only_pomodoros_still_has_a_summary():
    assert persona.summary_line({}, random.Random(1)) is None
    line = persona.summary_line({"写代码": 60.0}, random.Random(1), (1, 25 * 60.0))  # too little activity to tell
    assert line.text.startswith("今天的小结：专注了 1 个番茄（约 25 分钟）。")
    assert line.text.split("。", 1)[1] in persona.SUMMARY_FOCUS_TAILS


def test_the_pomodoro_part_in_english():
    i18n.set_language("en")
    line = persona.summary_line({"写代码": 3 * 3600.0}, random.Random(1), (1, 25 * 60.0))
    assert "coding about 3.0 hours, 1 pomodoro of focus (about 25 minutes)" in line.text
    line = persona.summary_line({}, random.Random(1), (3, 80 * 60.0))
    assert line.text.startswith("Today's summary: 3 pomodoros of focus (about 1.3 hours).")
    assert line.text.split(". ", 1)[1] in persona_en.SUMMARY_FOCUS_TAILS


def test_without_memory_only_the_pomodoros_are_told(pet):
    ctrl, wall = pet
    wall.now = at(23, 23)
    ctrl.config.companion_memory = False
    ctrl.focus_log.add(wall.now - 3600, 25 * 60.0)
    ctrl._heartbeat()
    assert ctrl.window.full_text.startswith("今天的小结：专注了 1 个番茄")
    assert "写代码" not in ctrl.window.full_text  # the memory's numbers stay out when it is off
