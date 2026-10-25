"""Small body movements: a swing when carried, a landing squash, a mood reaction; all from the drawings she has."""
import random
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from claude_pet import body, claude_client
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
    window = PetWindow(ASSETS, 220)
    window.set_body_motion(True)  # the window alone starts still; these tests are about the movements themselves
    window.clock = Clock()
    window._swing_at = window.clock.now
    yield window
    window.close()


# ---- the movements ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(body.DURATIONS))
def test_every_movement_starts_and_ends_at_rest_and_stays_small(kind):
    duration = body.DURATIONS[kind]
    assert body.pose(kind, -0.01, 187, 220) is None and body.pose(kind, duration, 187, 220) is None
    for i in range(200):
        dx, dy, angle, sx, sy = body.pose(kind, duration * i / 200, 187, 220, -1)
        assert abs(dx) <= 4 and -0.08 * 220 <= dy <= 0.5 and abs(angle) <= 2
        assert 0.85 <= sx <= 1.08 and 0.85 <= sy <= 1.07  # the rebound stretches a little
    last = body.pose(kind, duration * 0.995, 187, 220)
    assert abs(last[0]) < 0.5 and abs(last[1]) < 1.5 and abs(last[2]) < 0.2 and abs(last[4] - 1) < 0.01


def test_a_landing_squashes_first_then_springs_back():
    _dx, _dy, _a, sx, sy = body.pose("land", 0.0, 187, 220)
    assert sy < 0.9 and sx > 1.05  # flattened by the impact
    stretched = [body.pose("land", t / 100, 187, 220)[4] for t in range(10, 30)]
    assert max(stretched) > 1.0  # and a little stretch on the rebound


def test_a_hop_leaves_the_ground():
    assert min(body.pose("hop", t / 100, 187, 220)[1] for t in range(55)) < -0.05 * 220


def test_the_swing_follows_the_drag_and_settles():
    angle = speed = 0.0
    for _ in range(40):  # carried to the right
        angle, speed = body.swing_step(angle, speed, 600.0, 0.06)
    assert 2 < angle < body.SWING_MAX + 1
    hand = QPointF(100, 50)
    feet = body.about_hand(hand, angle).map(QPointF(100, 250))
    assert feet.x() < 100  # her feet hang back, to the left of where she is held
    for _ in range(200):
        angle, speed = body.swing_step(angle, speed, 0.0, 0.06)
    assert body.settled(angle, speed)


def test_the_swing_never_passes_the_limit():
    angle = speed = 0.0
    for _ in range(100):
        angle, speed = body.swing_step(angle, speed, -1e6, 0.06, limit=3.0)
        assert abs(angle) <= 3.0


def test_the_limit_leaves_her_inside_the_window():
    assert body.swing_limit(320, 187, 220) == body.SWING_LIMIT
    assert 0 < body.swing_limit(320, 272, 320) < 7  # a big pet in a window just wider than her
    assert body.swing_limit(340, 340, 400) == 0


# ---- the window ------------------------------------------------------------------------------------------
def _hidden_pixels(window) -> int:
    """Opaque pixels in her outermost columns: she has left the window there."""
    img = window.grab().toImage()
    top = int(img.height() * window.bubble_area / window.height())
    return sum(img.pixelColor(x, y).alpha() > 40 for y in range(top, img.height()) for x in (0, img.width() - 1))


@pytest.mark.parametrize("height", [160, 220, 260, 320, 400])
def test_a_full_swing_stays_inside_the_window(app, height):
    window = PetWindow(ASSETS, height)
    window.set_body_motion(True)
    for mood in ("panic", "idle", "sad"):
        window.mood = mood
        window.swing = 0
        before = _hidden_pixels(window)
        window._hand = QPointF(window.width() / 2, window.height() - window.sprites[mood].height())
        for side in (-1, 1):
            window.swing = side * window._swing_limit()
            assert _hidden_pixels(window) <= before, (height, mood, side)
    window.close()


def test_at_rest_she_is_drawn_exactly_as_before(window):
    still = window.grab().toImage()
    window.set_body_motion(False)
    assert window.grab().toImage() == still
    assert window.body_transform() is None


def test_moods_get_their_reaction_once(window):
    for mood, kind in body.REACTIONS.items():
        window.set_mood("idle")
        window._body = None
        window.set_mood(mood)
        assert window._body[0] == kind
    window._body = None
    window.set_mood("sad")  # no change of mood: nothing new
    assert window._body is None
    window.say("sad", "唉……")  # but a line said in that mood shows it
    assert window._body[0] == "slump"
    window._body = None
    window.say("think", "嗯……")  # thinking has no body reaction
    assert window._body is None


def test_still_while_asleep_walking_held_in_full_screen_or_switched_off(window):
    window.set_mood("sleep")
    window.start_body("hop")
    assert window._body is None
    window.set_mood("idle")
    window.set_walking(1)
    window.start_body("hop")
    assert window._body is None
    window.set_walking(0)
    window.calm = True
    window.set_mood("happy")
    assert window._body is None
    window.calm = False
    window.set_body_motion(False)
    window.start_body("land")
    assert window._body is None


def test_a_movement_under_way_stops_when_she_falls_asleep(window):
    window.start_body("slump")
    assert window.body_pose() is not None
    window.set_mood("sleep")
    assert window.body_pose() is None and window._body is None


def test_a_mood_reaction_waits_for_the_landing(window):
    window.start_body("land")
    window.set_mood("happy")
    assert window._body[0] == "land" and window._body_next == "hop"
    window.clock.now += body.DURATIONS["land"] + 0.01
    window._move_body(window.clock.now)
    assert window._body[0] == "hop" and window._body_next is None


def test_movements_end_by_themselves(window):
    window.start_body("shiver")
    window.clock.now += body.DURATIONS["shiver"]
    window._move_body(window.clock.now)
    assert window._body is None and window.body_transform() is None


def _press(window, local: QPoint):
    pos = QPointF(local)
    glob = QPointF(window.mapToGlobal(local))

    def event(kind, at_global, buttons):
        return QMouseEvent(kind, pos, at_global, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)

    window.mousePressEvent(event(QEvent.Type.MouseButtonPress, glob, Qt.MouseButton.LeftButton))
    return lambda dx: window.mouseMoveEvent(event(QEvent.Type.MouseMove, glob + QPointF(dx, 0), Qt.MouseButton.LeftButton)), \
        lambda: window.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, glob, Qt.MouseButton.NoButton))


def test_carried_she_swings_from_where_she_is_held_and_settles_after(window):
    window.show()
    hand = QPoint(window.width() // 2, window.height() - 200)
    move, release = _press(window, hand)
    assert window._hand == QPointF(hand)
    for step in range(1, 12):  # dragged to the right, a frame at a time
        move(step * 30)
        window.clock.now += 0.06
        window._move_body(window.clock.now)
    assert window.swing > 2  # hanging back from the way she is carried
    assert window.body_pose() is None  # no mood reaction while held (picked up: panic, but held)
    release()
    for _ in range(200):
        window.clock.now += 0.06
        window._move_body(window.clock.now)
    assert window.swing == 0.0


def test_no_swing_with_body_movements_off(window):
    window.set_body_motion(False)
    window.show()
    move, release = _press(window, QPoint(window.width() // 2, window.height() - 200))
    for step in range(1, 8):
        move(step * 30)
        window.clock.now += 0.06
        window._move_body(window.clock.now)
    release()
    assert window.swing == 0.0


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01"), ASSETS, tmp_path / "config.json")
    ctrl._rng = random.Random(1)
    yield ctrl
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def test_on_by_default_and_saved(tmp_path):
    assert Config().body_motion is True
    path = tmp_path / "config.json"
    path.write_text('{"body_motion": false}', encoding="utf-8")
    assert load_config(path).body_motion is False  # switched off stays off
    path = tmp_path / "config.json"
    path.write_text('{"body_motion": true}', encoding="utf-8")
    assert load_config(path).body_motion is True
    path.write_text('{"body_motion": "yes", "watch_mode": "allowlist"}', encoding="utf-8")
    config = load_config(path)
    assert config.body_motion is True and config.watch_mode == "allowlist"


def test_landing_squashes_before_her_reaction(pet):
    pet.set_body_motion(True)
    pet._on_landed()
    assert pet.window._body[0] == "land"


def test_full_screen_quiet_keeps_her_body_still(pet, monkeypatch):
    pet.set_body_motion(True)
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    pet._update_quiet()
    assert pet.window.calm
    pet._on_landed()
    assert pet.window._body is None
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: False)
    pet._update_quiet()
    assert not pet.window.calm


def test_settings_switch(pet):
    pet.open_settings()
    box = pet.settings_window.body_box
    assert box.isChecked() and pet.window.body_motion  # on from the start
    box.setChecked(False)
    assert not pet.config.body_motion and not pet.window.body_motion
    box.setChecked(True)
    assert pet.config.body_motion and pet.window.body_motion


def test_the_tremble_shows_at_the_frame_rate():
    frames = [body.pose("shiver", n * 0.06, 187, 220)[0] for n in range(int(body.DURATIONS["shiver"] / 0.06))]
    signs = [x > 0 for x in frames if abs(x) > 0.3]
    assert sum(a != b for a, b in zip(signs, signs[1:])) >= 4  # side to side several times, not one slow drift


@pytest.mark.parametrize("hush", ["calm", "sleep"])
def test_no_swing_in_full_screen_quiet_or_asleep(window, hush):
    window.show()
    move, release = _press(window, QPoint(window.width() // 2, window.height() - 200))
    for step in range(1, 6):
        move(step * 30)
        window.clock.now += 0.06
        window._move_body(window.clock.now)
    assert window.swing and window.body_transform() is not None
    if hush == "calm":
        window.calm = True
    else:
        window.mood = "sleep"
    assert window.body_transform() is None  # not drawn from this moment
    window.clock.now += 0.06
    window._move_body(window.clock.now)
    assert window.swing == 0.0
    move(300)
    window.clock.now += 0.06
    window._move_body(window.clock.now)
    assert window.swing == 0.0  # nor while still carried
    release()


def test_a_poke_reaction_is_not_lost_to_the_release(window):
    window.poked.connect(lambda: window.say("happy", "嘿嘿"))
    window.show()
    _move, release = _press(window, QPoint(window.width() // 2, window.height() - 150))
    assert window._body is None
    release()
    assert window._body is not None and window._body[0] == "hop"


def _outside(window) -> int:
    """Opaque pixels drawn outside the window: paint onto a bigger canvas, shifted in by a margin."""
    from PySide6.QtGui import QImage, QPainter

    margin = 60
    canvas = QImage(window.width() + 2 * margin, window.height() + 2 * margin, QImage.Format.Format_ARGB32)
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.translate(margin, margin)
    painter.setClipping(False)
    whole = window.body_transform()
    sprite = window._sprite_rect()
    if whole is not None:
        painter.setTransform(whole, True)
    painter.drawPixmap(int(sprite.x()), int(sprite.y()), window._sprite())
    painter.end()
    inside = (margin, margin, margin + window.width(), margin + window.height())
    return sum(canvas.pixelColor(x, y).alpha() > 40
               for y in range(0, canvas.height(), 2) for x in range(0, canvas.width(), 2)
               if not (inside[0] <= x < inside[2] and inside[1] <= y < inside[3]))


@pytest.mark.parametrize("height", [160, 220, 260, 320])
@pytest.mark.parametrize("where", ["top", "side", "bubble", "feet"])
def test_held_anywhere_a_full_swing_stays_inside(app, height, where):
    window = PetWindow(ASSETS, height)
    window.set_body_motion(True)
    window.mood = "panic"
    rect = window._sprite_rect()
    at = {"top": QPointF(window.width() / 2, rect.top()), "side": QPointF(5, rect.center().y()),
          "bubble": QPointF(20, 120), "feet": QPointF(rect.right(), rect.bottom())}[where]
    window._hand = window._clamped_hand(at)
    assert rect.contains(window._hand)
    for side in (-1, 1):
        window.swing = side * window._swing_limit()
        assert _outside(window) == 0, (height, where, side)
    window.close()
