"""Small head movements: nod, tilt, duck."""
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QTransform

from claude_pet import claude_client, head
from claude_pet import controller as controller_module
from claude_pet.config import Config, load_config
from claude_pet.pet_window import PetWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "sprites"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def window(app):
    window = PetWindow(ASSETS, 300)
    window.set_head_motion(True)  # off by default; these tests are about the movements themselves
    window.clock = Clock()
    window._phase = 0.0
    yield window
    window.close()


def _image(window) -> QImage:
    return window.grab().toImage()


def _diff(a: QImage, b: QImage, top: int, bottom: int) -> int:
    worst = 0
    for y in range(top, bottom, 2):
        for x in range(0, a.width(), 2):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            worst = max(worst, abs(ca.red() - cb.red()), abs(ca.green() - cb.green()), abs(ca.alpha() - cb.alpha()))
    return worst


def test_the_head_mask_keeps_the_body_and_side_hair_still():
    mask = head.head_mask(200, 400)
    neck, band = head.NECK * 400, head.BAND * 400
    assert mask.pixelColor(100, 10).alpha() == 255  # the crown moves with her head
    assert mask.pixelColor(100, int(neck + band)).alpha() == 0  # the body does not
    low_hair = int((head.LOW_START + head.LOW_FADE) * 400) + 2  # above the cut, where side hair stays still
    assert low_hair < neck - band / 2 and mask.pixelColor(2, low_hair).alpha() == 0  # long hair far at her side


def test_standing_still_is_exactly_the_sprite(window):
    sprite = window.sprites["idle"]
    still = head.compose([sprite], window._mask(), QTransform())
    original = sprite.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    assert _diff(still, original, 0, original.height()) <= 1


def test_poses_over_time():
    assert head.pose("nod", 0.0, 300) == (0.0, 0.0, 1.0)
    angle, dy, scale = head.pose("nod", head.DURATIONS["nod"] / 2, 300)
    assert angle == pytest.approx(0.5) and dy == pytest.approx(3.0) and scale == 1.0
    assert head.pose("tilt", 1.0, 300, -1)[0] == pytest.approx(-1.5)
    _angle, dy, scale = head.pose("duck", 0.5, 300)
    assert dy == pytest.approx(3.6) and scale == pytest.approx(0.975)
    for kind, length in head.DURATIONS.items():
        assert head.pose(kind, length, 300) is None and head.pose(kind, -0.1, 300) is None


def test_she_nods_as_she_starts_to_talk_and_the_body_stays_put(window):
    window.say("talk", "主人好～")
    nod = window._head
    window._head = None
    before = _image(window)  # the same moment, head still
    window._head = nod
    window.clock.now += head.DURATIONS["nod"] / 2
    assert window.head_pose() is not None
    during = _image(window)
    feet = window.height() - 4
    assert _diff(before, during, feet - 120, feet) <= 2  # the lower body does not move
    assert _diff(before, during, feet - 300, feet - 220) > 20  # the head does
    window.clock.now += head.DURATIONS["nod"]
    window._animate()
    assert window._head is None and window.head_pose() is None


def test_a_pat_makes_her_duck(window):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    pats = []
    window.patted.connect(lambda: pats.append(1))
    rect = window.head_rect()
    y, x = rect.center().y(), rect.center().x() - 30
    for target in [x, x + 40, x, x + 40, x, x + 40]:  # rubbing her head back and forth
        for step in range(0, 41, 8):
            px = target - 40 + step if target > x else target + 40 - step
            window.clock.now += 0.02
            event = QMouseEvent(QEvent.Type.MouseMove, QPointF(px, y), QPointF(px, y), Qt.MouseButton.NoButton,
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            window.mouseMoveEvent(event)
    assert pats and window._head is not None and window._head[0] == "duck"
    window.clock.now += 0.5
    assert window.head_pose()[2] < 1


@pytest.mark.parametrize("why", ["asleep", "held"])
def test_a_movement_under_way_stops_when_she_falls_asleep_or_is_picked_up(window, why):
    window.mood = "idle"
    window.start_head("tilt")
    window.clock.now += 1.0
    assert window.head_pose() is not None
    if why == "asleep":
        window.mood = "sleep"
    else:
        window._press_pos = QPoint(1, 1)
    assert window.head_pose() is None
    window._animate()
    assert window._head is None  # gone for good, not resumed afterwards
    window.mood, window._press_pos = "idle", None
    assert window.head_pose() is None


def test_the_mask_follows_a_sprite_of_another_width(window):
    from PySide6.QtGui import QPixmap

    window.mood = "idle"
    assert window._mask().size() == window.sprites["idle"].size()
    wide = QPixmap(window.sprites["think"].width() + 40, window.sprites["think"].height())
    wide.fill()
    window.sprites["think"] = wide
    window.mood = "think"
    assert window._mask().size() == wide.size()


@pytest.mark.parametrize("why", ["off", "walking", "asleep", "held"])
def test_no_head_movement_when_it_does_not_fit(window, why):
    if why == "off":
        window.set_head_motion(False)
    elif why == "walking":
        window.set_walking(1)
    elif why == "asleep":
        window.mood = "sleep"
    else:
        window._press_pos = QPoint(1, 1)
    window.start_head("nod")
    window.clock.now += 0.2
    assert window.head_pose() is None


def test_switching_it_off_stops_a_movement_at_once(window):
    window.start_head("tilt")
    window.clock.now += 1.0
    assert window.head_pose() is not None
    window.set_head_motion(False)
    assert window.head_pose() is None


def test_an_idle_tilt_now_and_then(window):
    window.mood = "idle"
    window.clear_bubble()
    window.mood = "idle"
    window.clock.now = window._next_tilt + 0.01
    window._animate()
    assert window._head is not None and window._head[0] == "tilt"
    assert head.TILT_EVERY[0] <= window._next_tilt - window.clock.now <= head.TILT_EVERY[1]
    window._head = None
    window.say("happy", "在说话")  # a nod starts; no tilt while she is talking
    window._head = None
    window.clock.now = window._next_tilt + 0.01
    window._animate()
    assert window._head is None


def test_resizing_stops_the_movement_and_makes_a_new_mask(window):
    window.start_head("tilt")
    window._mask()
    window.set_sprite_height(200)
    assert window._head is None and window._head_mask is None
    assert window._mask().size() == window.sprites["idle"].size()


def test_the_setting_is_kept_and_a_broken_value_means_on(tmp_path):
    assert Config().head_motion is False  # off unless chosen
    path = tmp_path / "config.json"
    path.write_text('{"head_motion": true}', encoding="utf-8")
    assert load_config(path).head_motion is True
    path.write_text('{"head_motion": null, "interval_sec": 120}', encoding="utf-8")
    assert load_config(path).head_motion is False and load_config(path).interval_sec == 120


def test_the_settings_page_switches_head_movements(app, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(head_motion=False), ASSETS, tmp_path / "config.json")
    assert ctrl.window.head_motion is False
    ctrl.open_settings()
    page = ctrl.settings_window
    assert not page.head_box.isChecked()
    page.head_box.setChecked(True)
    assert ctrl.config.head_motion is True and ctrl.window.head_motion is True
    page.close()


@pytest.mark.parametrize("why", ["walking", "asleep", "held"])
def test_a_movement_stopped_for_a_moment_never_comes_back(window, why):
    window.mood = "idle"
    window.start_head("tilt")
    window.clock.now += 1.0
    if why == "walking":
        window.set_walking(1)
    elif why == "asleep":
        window.mood = "sleep"
    else:
        window._press_pos = QPoint(1, 1)
    assert window.head_pose() is None  # no animation tick in between
    window.set_walking(0)
    window.mood, window._press_pos = "idle", None
    assert window.head_pose() is None


def test_a_tilt_does_not_resume_after_a_short_walk(window):
    window._bob.stop()  # no animation tick at all, only real painting
    window.mood = "idle"
    window.start_head("tilt")
    window.clock.now += 1.0
    window.set_walking(1)
    window.grab()
    window.set_walking(0)
    assert window.head_pose() is None


def test_a_new_window_does_not_move_its_head(app):
    window = PetWindow(ASSETS, 200)
    window.start_head("nod")
    assert window.head_motion is False and window.head_pose() is None
    window.close()

