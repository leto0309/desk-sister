"""Ctrl + mouse wheel over her changes her height."""
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from claude_pet import claude_client
from claude_pet import controller as controller_module
from claude_pet.config import Config
from claude_pet.pet_window import PetWindow

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wheel(window, delta: int, modifiers=CTRL) -> bool:
    event = QWheelEvent(QPointF(50, 300), QPointF(50, 300), QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    window.wheelEvent(event)
    return event.isAccepted()


def test_ctrl_wheel_notches_become_resize_steps(app):
    window = PetWindow(SPRITES, 200)
    steps = []
    window.resize_wheel.connect(steps.append)
    assert wheel(window, 120) and wheel(window, -240)
    assert steps == [1, -2]
    for _ in range(3):  # a touchpad scrolls in small pieces: one notch only once they add up
        wheel(window, 40)
    assert steps == [1, -2, 1]
    wheel(window, 60)
    assert not wheel(window, 120, NONE)  # without Ctrl the wheel is not hers
    wheel(window, 60)  # the half notch before the plain scroll was dropped
    assert steps == [1, -2, 1]
    window.close()


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append(config.sprite_height))
    ctrl = controller_module.PetController(app, Config(sprite_height=220), SPRITES, tmp_path / "config.json")
    now = [1000.0]
    ctrl._clock = lambda: now[0]
    ctrl.window.move(QPoint(400, 300))
    return ctrl, saved, now


def test_each_notch_is_ten_pixels_and_her_feet_stay(pet):
    ctrl, saved, _now = pet
    feet = ctrl.window.geometry().bottom()
    ctrl.window.resize_wheel.emit(3)
    assert ctrl.config.sprite_height == 250 and ctrl.window.sprite_height == 250 and saved[-1] == 250
    assert ctrl.window.geometry().bottom() == feet
    ctrl.resize_by_wheel(-5)
    assert ctrl.config.sprite_height == 200 and ctrl.window.geometry().bottom() == feet


def test_the_size_stays_within_the_settings_range(pet):
    ctrl, saved, _now = pet
    ctrl.resize_by_wheel(100)
    assert ctrl.config.sprite_height == 600
    count = len(saved)
    ctrl.resize_by_wheel(1)  # already at the top: nothing to save
    assert ctrl.config.sprite_height == 600 and len(saved) == count
    ctrl.resize_by_wheel(-100)
    assert ctrl.config.sprite_height == 100


def test_a_walk_stops_and_the_settings_slider_follows(pet):
    ctrl, _saved, _now = pet
    stopped = []
    ctrl.walker.stop = lambda: stopped.append(1)
    ctrl.open_settings()
    ctrl.resize_by_wheel(2)
    assert stopped and ctrl.settings_window.size_slider.value() == 240
    ctrl.settings_window.close()


def test_her_height_shows_briefly_but_never_hides_an_error(pet):
    ctrl, _saved, now = pet
    ctrl.resize_by_wheel(1)
    assert ctrl.window.status == "身高 230 像素"
    now[0] += controller_module.SIZE_SHOWN_SEC + 0.1
    ctrl._refresh_status()
    assert ctrl.window.status == ""
    ctrl.last_error = "网络错误"
    ctrl.resize_by_wheel(1)
    assert ctrl.window.status == "原因：网络错误"


@pytest.mark.parametrize("state", ["paused", "busy", "quiet"])
def test_her_height_shows_over_a_lasting_state_for_a_moment(pet, state):
    ctrl, _saved, now = pet
    if state == "paused":
        ctrl.config.paused = True
    else:
        setattr(ctrl, state, True)
    ctrl.resize_by_wheel(1)
    assert ctrl.window.status == "身高 230 像素"
    now[0] += controller_module.SIZE_SHOWN_SEC + 0.1
    ctrl._refresh_status()
    assert ctrl.window.status in ("已暂停", "思考中…") or ctrl.window.status.startswith("全屏中")


def test_a_failure_pause_is_never_covered(pet):
    ctrl, _saved, _now = pet
    ctrl.auto_paused_until = ctrl._clock() + 600
    ctrl.consecutive_failures = 3
    ctrl.resize_by_wheel(1)
    assert ctrl.window.status.startswith("连续失败")

