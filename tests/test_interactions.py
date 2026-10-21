"""Reactions to what 主人 does with her: head pats, being picked up and dropped, the screen edge, resizing."""
import random
import time
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from claude_pet import bedtime, claude_client, persona
from claude_pet import controller as controller_module
from claude_pet.config import Config
from claude_pet.pet_window import PetWindow
from claude_pet.walker import Walker

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Clock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


def hover(window, x, y, buttons=Qt.MouseButton.NoButton):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(window.x() + x, window.y() + y),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    window.mouseMoveEvent(event)


def rub(window, clock, xs, y, dt=0.03, step=8):
    """Move the mouse through the x positions in small steps, as a real hand does."""
    x = xs[0]
    hover(window, x, y)
    for target in xs[1:]:
        while x != target:
            x += max(-step, min(step, target - x))
            clock.now += dt
            hover(window, x, y)


@pytest.fixture
def window(app):
    window = PetWindow(SPRITES, 220)
    window.clock = Clock()
    pats = []
    window.patted.connect(lambda: pats.append(window.clock.now))
    yield window, pats
    window.close()


def test_rubbing_her_head_is_a_pat(window):
    win, pats = window
    head = win.head_rect()
    y, left = head.center().y(), head.center().x() - 30
    rub(win, win.clock, [left, left + 40, left, left + 40, left, left + 40], y)
    assert len(pats) == 1


def test_short_slow_or_low_rubbing_is_no_pat(window):
    win, pats = window
    head = win.head_rect()
    y, left = head.center().y(), head.center().x() - 30
    rub(win, win.clock, [left, left + 6, left, left + 6, left, left + 6, left], y, step=2)  # too short
    rub(win, win.clock, [left, left + 40, left, left + 40, left, left + 40], y, dt=0.2)  # too slow
    body = head.bottom() + 60
    rub(win, win.clock, [left, left + 40, left, left + 40, left, left + 40], body)  # on her dress, not her head
    assert pats == []


def test_she_looks_flustered_while_carried_and_calms_down_after(window):
    win, _pats = window
    win.set_mood("happy")
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(100, 300), QPointF(100, 300),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.mousePressEvent(press)
    hover(win, 160, 300, Qt.MouseButton.LeftButton)
    assert win.mood == "panic"
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(160, 300), QPointF(160, 300),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    win.mouseReleaseEvent(release)
    assert win.mood == "happy"
    win.say("talk", "我在说话")  # a line shows her own mood; carrying her does not change it
    win.mousePressEvent(press)
    hover(win, 160, 300, Qt.MouseButton.LeftButton)
    win.mouseReleaseEvent(release)
    assert win.mood == "talk"


def test_a_stroll_to_the_screen_edge_tells_the_pet(app, monkeypatch):
    from test_walker import AREA, FLOOR, FakeWindow

    monkeypatch.setattr(Walker, "work_area", lambda self: AREA)
    right = AREA.width() - 300
    for seed in range(50):
        window, clock, edges = FakeWindow(right - 120, FLOOR), Clock(), []
        walker = Walker(window, lambda: True, lambda *_: None, random.Random(seed), clock, edge=lambda: edges.append(1))
        walker.set_enabled(True)
        walker.start_stroll()
        if walker.target == right:
            break
    else:
        pytest.fail("no seed walked to the edge")
    while walker.walking:
        clock.now += 0.033
        walker.step()
    assert window.x() == right and edges == [1]


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(sprite_height=220), SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("reactions never call a model"))
    clock = Clock()
    ctrl._clock = clock
    ctrl._rng = random.Random(2)
    return ctrl, clock


def lines(kind):
    return {text for _mood, text in persona.INTERACTION_TALK[kind]}


def test_a_pat_gets_one_happy_line_then_a_pause(pet):
    ctrl, clock = pet
    ctrl.window.patted.emit()
    assert ctrl.window.full_text in lines("pat")
    ctrl.window.clear_bubble()
    clock.now += 2
    ctrl.window.patted.emit()
    assert ctrl.window.full_text == ""  # still rubbing: no second line yet
    clock.now += controller_module.PAT_COOLDOWN_SEC
    ctrl.window.patted.emit()
    assert ctrl.window.full_text in lines("pat_shy")  # the second pat in a row


@pytest.mark.parametrize(("start", "heights", "kind"), [
    (220, [230, 250, 270], "grow"),
    (220, [210, 190], "shrink"),
    (560, [580, 600], "max"),
    (130, [110, 100], "min"),
])
def test_resizing_gets_one_line_once_it_settles(pet, start, heights, kind):
    ctrl, _clock = pet
    ctrl.config.sprite_height = start
    ctrl.window.clear_bubble()
    for height in heights:
        ctrl.set_sprite_height(height)
    assert ctrl._resize_done.isActive() and ctrl.window.full_text == ""  # not while still resizing
    ctrl._on_resized()
    assert ctrl.window.full_text in lines(kind)
    ctrl.window.clear_bubble()
    ctrl._on_resized()
    assert ctrl.window.full_text == ""  # one line per burst


def test_resizing_back_and_forth_to_the_same_size_says_nothing(pet):
    ctrl, _clock = pet
    ctrl.window.clear_bubble()
    ctrl.set_sprite_height(260)
    ctrl.set_sprite_height(220)
    ctrl._on_resized()
    assert ctrl.window.full_text == ""


def test_no_reactions_in_full_screen_quiet_mode(pet):
    ctrl, _clock = pet
    ctrl.window.clear_bubble()
    ctrl.quiet = True
    ctrl.window.patted.emit()
    ctrl.set_sprite_height(300)
    ctrl._on_resized()
    assert ctrl.window.full_text == ""


def test_edge_and_landing_lines_come_now_and_then(pet, monkeypatch):
    ctrl, _clock = pet
    ctrl.window.clear_bubble()
    monkeypatch.setattr(ctrl._rng, "random", lambda: 0.1)
    ctrl._on_edge()
    assert ctrl.window.full_text in lines("edge")
    ctrl.window.clear_bubble()
    ctrl._on_landed()
    assert ctrl.window.full_text in lines("land")
    ctrl.window.clear_bubble()
    monkeypatch.setattr(ctrl._rng, "random", lambda: 0.9)  # most of the time she just keeps quiet
    ctrl._on_edge()
    ctrl._on_landed()
    assert ctrl.window.full_text == ""
    monkeypatch.setattr(ctrl._rng, "random", lambda: 0.1)
    ctrl.window.say("talk", "正在说的话")
    ctrl._on_edge()
    assert ctrl.window.full_text == "正在说的话"  # never cuts her off


def test_no_reaction_line_is_a_bedtime_reminder():
    for entries in persona.INTERACTION_TALK.values():
        for mood, text in entries:
            assert mood in persona.MOODS and not bedtime.mentions(text)


# ---- more lines: pats in a row, dragging about, the day's first hello ------------------------------------
def test_pats_in_a_row_get_shy_then_mock_annoyed_and_settle_after_a_minute(pet):
    ctrl, clock = pet
    for kind in ("pat", "pat_shy", "pat_annoyed", "pat_annoyed"):
        ctrl.window.clear_bubble()
        ctrl.window.patted.emit()
        assert ctrl.window.full_text in lines(kind)
        clock.now += controller_module.PAT_COOLDOWN_SEC + 1
    clock.now += controller_module.PAT_MEMORY_SEC
    ctrl.window.clear_bubble()
    ctrl.window.patted.emit()
    assert ctrl.window.full_text in lines("pat")


def drop(ctrl, clock, held=0.5):
    """Pick her up, carry her for `held` seconds and let go."""
    win = ctrl.window
    win.clock = clock
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(100, 300), QPointF(100, 300),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.mousePressEvent(press)
    hover(win, 160, 300, Qt.MouseButton.LeftButton)
    clock.now += held
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(160, 300), QPointF(160, 300),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    win.mouseReleaseEvent(release)


def test_dragged_about_three_times_she_complains(pet):
    ctrl, clock = pet
    ctrl.window.clear_bubble()
    drop(ctrl, clock)
    clock.now += 5
    drop(ctrl, clock)
    assert ctrl.window.full_text == ""
    clock.now += 5
    drop(ctrl, clock)
    assert ctrl.window.full_text in lines("drag_many")
    ctrl.window.clear_bubble()
    clock.now += 5
    drop(ctrl, clock)
    assert ctrl.window.full_text == ""  # counted afresh after complaining
    clock.now += controller_module.DROP_MEMORY_SEC + 1
    drop(ctrl, clock)
    drop(ctrl, clock)
    assert ctrl.window.full_text == ""  # the earlier drop is forgotten


def test_carried_for_long_she_is_dizzy(pet):
    ctrl, clock = pet
    ctrl.window.clear_bubble()
    drop(ctrl, clock, held=controller_module.LONG_CARRY_SEC - 1)
    assert ctrl.window.full_text == ""
    clock.now += controller_module.DROP_MEMORY_SEC + 1
    drop(ctrl, clock, held=controller_module.LONG_CARRY_SEC + 1)
    assert ctrl.window.full_text in lines("carry_long")


def test_moving_her_from_the_settings_does_not_count_as_a_drag(pet):
    ctrl, clock = pet
    ctrl.window.clear_bubble()
    for _ in range(4):
        ctrl._on_dropped(ctrl.window.x(), ctrl.window.y())
    assert ctrl.window.full_text == "" and ctrl._drops == []


def at(year, month, day, hour):
    return lambda: time.mktime((year, month, day, hour, 0, 0, 0, 0, -1))


def greetings(part):
    return {text for _mood, text in persona.GREETINGS[part]}


INTRO = "主人好～我是 Claude。我会安静待在这里，偶尔看看你在忙什么。"


def test_first_start_of_the_day_greets_and_a_restart_does_not(pet):
    ctrl, _clock = pet
    ctrl._now = at(2026, 10, 21, 8)
    ctrl.start()
    assert ctrl.window.full_text in greetings("morning") and ctrl.config.greeted_on == "2026-10-21"
    ctrl.window.clear_bubble()
    ctrl.start()
    assert ctrl.window.full_text == INTRO
    ctrl._now = at(2026, 10, 22, 14)
    ctrl.start()
    assert ctrl.window.full_text in greetings("day")


@pytest.mark.parametrize(("when", "birthday", "text"), [
    ((2026, 10, 1, 9), "", persona.FESTIVAL_LINES["国庆节"][1]),
    ((2027, 2, 6, 20), "", persona.FESTIVAL_LINES["春节"][1]),
    ((2026, 10, 1, 9), "10-01", persona.BIRTHDAY_LINE[1]),  # her birthday wish wins over the festival
    ((2026, 5, 3, 9), "05-03", persona.BIRTHDAY_LINE[1]),
])
def test_festivals_and_the_birthday_replace_the_greeting(pet, when, birthday, text):
    ctrl, _clock = pet
    ctrl.config.birthday = birthday
    ctrl._now = at(*when)
    ctrl.start()
    assert ctrl.window.full_text == text


def test_waking_up_on_a_new_day_greets_instead_of_the_wake_line(pet):
    ctrl, _clock = pet
    ctrl.config.greeted_on = "2026-10-20"
    ctrl._now = at(2026, 10, 21, 7)
    ctrl.asleep = True
    ctrl._wake(announce=True)
    assert ctrl.window.full_text in greetings("morning")
    ctrl.asleep = True
    ctrl._wake(announce=True)
    assert ctrl.window.full_text in {text for _mood, text in persona.WAKE_LINES}


def test_pats_keep_escalating_until_a_quiet_minute(pet):
    ctrl, clock = pet
    said = []
    for gap in (0, 6, 6, 55, 59.9, 60, 6):
        clock.now += gap
        ctrl.window.clear_bubble()
        ctrl.window.patted.emit()
        said.append(next(kind for kind in ("pat", "pat_shy", "pat_annoyed") if ctrl.window.full_text in lines(kind)))
    assert said == ["pat", "pat_shy", "pat_annoyed", "pat_annoyed", "pat_annoyed", "pat", "pat_shy"]


@pytest.mark.parametrize("why", ["quiet", "quit_pending"])
def test_a_greeting_that_has_to_wait_comes_once_she_may_talk(pet, why):
    ctrl, _clock = pet
    ctrl._now = at(2026, 10, 21, 15)
    setattr(ctrl, why, True)
    ctrl.window.clear_bubble()
    ctrl.start()
    assert ctrl.window.full_text == "" and ctrl.config.greeted_on == ""  # neither the hello nor the intro
    ctrl.asleep = True
    ctrl._wake(announce=True)
    assert ctrl.window.full_text == ""  # nor the wake line
    ctrl.window.clear_bubble()
    setattr(ctrl, why, False)
    ctrl._heartbeat()  # no longer full screen / quitting
    assert ctrl.window.full_text in greetings("day") and ctrl.config.greeted_on == "2026-10-21"
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""


def test_without_claude_code_the_hello_comes_after_the_notice(pet):
    ctrl, _clock = pet
    ctrl.claude = None
    ctrl.config.birthday = "10-21"
    ctrl._now = at(2026, 10, 21, 9)
    ctrl.start()
    assert ctrl.window.full_text == persona.fallback("no_claude").text
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    assert ctrl.window.full_text == persona.BIRTHDAY_LINE[1]
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    ctrl.start()
    assert ctrl.window.full_text == persona.fallback("no_claude").text  # the hello only once


def test_a_quiet_wake_owes_the_hello_only_for_that_day(pet):
    ctrl, _clock = pet
    ctrl.config.greeted_on = "2026-10-21"
    ctrl._now = at(2026, 10, 21, 23)
    ctrl.asleep = True
    ctrl._wake(announce=False)  # already greeted today: nothing owed
    ctrl._now = at(2026, 10, 22, 0)
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""
    ctrl.config.greeted_on = "2026-10-20"
    ctrl._now = at(2026, 10, 21, 23)
    ctrl.asleep = True
    ctrl._wake(announce=False)  # owed today, but the bubble outlasts midnight
    ctrl.window.say("talk", "还没说完")
    ctrl._heartbeat()
    ctrl._now = at(2026, 10, 22, 0)
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    assert ctrl.window.full_text == "" and ctrl._greeting_due == ""


def test_a_new_day_while_she_is_awake_waits_for_the_next_meeting(pet):
    ctrl, _clock = pet
    ctrl.config.greeted_on = "2026-10-20"
    ctrl._now = at(2026, 10, 21, 0)
    ctrl.window.clear_bubble()
    ctrl._heartbeat()
    assert ctrl.window.full_text == ""


def test_set_birthday(pet):
    ctrl, _clock = pet
    ctrl.set_birthday(2, 29, True)
    assert ctrl.config.birthday == "02-29"
    ctrl.set_birthday(2, 31, True)
    assert ctrl.config.birthday == ""
    ctrl.set_birthday(5, 3, False)
    assert ctrl.config.birthday == ""


def test_new_lines_never_mention_sleep():
    texts = [text for kind in ("pat_shy", "pat_annoyed", "drag_many", "carry_long")
             for _mood, text in persona.INTERACTION_TALK[kind]]
    texts += [text for part in persona.GREETINGS.values() for _mood, text in part]
    texts += [text for _mood, text in persona.FESTIVAL_LINES.values()] + [persona.BIRTHDAY_LINE[1]]
    assert not [text for text in texts if bedtime.mentions(text)]
