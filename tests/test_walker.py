"""Strolling along the bottom of the screen."""
import random
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QObject, QPoint, QRect

from claude_pet import controller as controller_module
from claude_pet import walker as walker_module
from claude_pet.config import Config, load_config
from claude_pet.walker import DISTANCE, SNAP, Walker, plan_stroll

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
AREA = QRect(0, 0, 1600, 860)  # a work area above a 40 px taskbar


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeWindow(QObject):
    def __init__(self, x, y, w=300, h=380):
        super().__init__()
        self._x, self._y, self._w, self._h = x, y, w, h
        self.directions = []

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h

    def geometry(self):
        return QRect(self._x, self._y, self._w, self._h)

    def move(self, point):
        self._x, self._y = point.x(), point.y()

    def set_walking(self, direction):
        self.directions.append(direction)

    def screen(self):
        return None


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


FLOOR = AREA.height() - 380


def make(app, monkeypatch, x=600, y=FLOOR, can=True, seed=1, area=AREA):
    monkeypatch.setattr(Walker, "work_area", lambda self: area)
    window, clock, arrived, allowed = FakeWindow(x, y), Clock(), [], [can]
    walker = Walker(window, lambda: allowed[0], lambda wx, wy: arrived.append((wx, wy)), random.Random(seed), clock)
    return walker, window, clock, arrived, allowed


def walk_to_the_end(walker, clock, limit=400):
    for _ in range(limit):
        if not walker.walking:
            return
        clock.now += 0.033
        walker.step()


def test_a_stroll_stays_on_the_screen_and_turns_back_at_an_edge():
    rng = random.Random(3)
    for _ in range(200):
        x = rng.uniform(0, 1300)
        target = plan_stroll(x, 0, 1300, rng)
        if target is not None:
            assert 0 <= target <= 1300 and DISTANCE[0] <= abs(target - x) <= DISTANCE[1]
    assert plan_stroll(5, 0, 1300, random.Random(0)) > 5  # at the left edge: always to the right
    assert plan_stroll(1295, 0, 1300, random.Random(0)) < 1295
    assert plan_stroll(20, 0, 50, random.Random(0)) is None  # no room for a real stroll
    for seed in range(20):  # 60 px either way is less than the shortest stroll
        assert plan_stroll(60, 0, 120, random.Random(seed)) is None


def test_she_walks_along_the_floor_to_her_target_and_rests_again(app, monkeypatch):
    walker, window, clock, arrived, _ = make(app, monkeypatch)
    walker.set_enabled(True)
    assert walker._rest.isActive() and not walker._frame.isActive()  # no frames while standing
    walker.start_stroll()
    assert walker.walking and walker._frame.isActive() and window.directions[-1] in (-1, 1)
    target = walker.target
    walk_to_the_end(walker, clock)
    assert window.x() == round(target) and window.y() == FLOOR  # only sideways, along the floor
    assert arrived == [(window.x(), FLOOR)] and window.directions[-1] == 0
    assert not walker._frame.isActive() and walker._rest.isActive()


def test_she_walks_at_an_even_pace(app, monkeypatch):
    walker, window, clock, _arrived, _ = make(app, monkeypatch)
    walker.set_enabled(True)
    walker.start_stroll()
    start = window.x()
    for _ in range(30):  # one second
        clock.now += 1 / 30
        walker.step()
    assert abs(abs(window.x() - start) - walker_module.SPEED) <= 2


def test_she_stops_at_once_when_something_else_starts(app, monkeypatch):
    walker, window, clock, arrived, allowed = make(app, monkeypatch)
    walker.set_enabled(True)
    walker.start_stroll()
    clock.now += 0.5
    walker.step()
    allowed[0] = False  # she starts talking, is grabbed, falls asleep...
    walker.step()
    assert not walker.walking and not walker._frame.isActive() and arrived == [(window.x(), FLOOR)]


def test_she_never_sets_off_when_she_should_not_or_is_off_the_floor(app, monkeypatch):
    walker, window, _clock, arrived, _ = make(app, monkeypatch, can=False)
    walker.set_enabled(True)
    walker.start_stroll()
    assert not walker.walking and walker._rest.isActive() and arrived == []
    walker, window, _clock, arrived, _ = make(app, monkeypatch, y=FLOOR - 200)  # dragged up the screen
    walker.set_enabled(True)
    walker.start_stroll()
    assert not walker.walking and window.y() == FLOOR - 200


def test_switching_off_stops_her_and_every_timer(app, monkeypatch):
    walker, _window, clock, arrived, _ = make(app, monkeypatch)
    walker.set_enabled(True)
    walker.start_stroll()
    clock.now += 0.2
    walker.step()
    walker.set_enabled(False)
    assert not walker.walking and not walker._frame.isActive() and not walker._rest.isActive()
    assert len(arrived) == 1  # where she stopped is remembered


def test_a_drop_near_the_floor_lands_on_it(app, monkeypatch):
    walker, window, _clock, _arrived, _ = make(app, monkeypatch, y=FLOOR - SNAP + 5)
    assert walker.snap_to_floor() and window.y() == FLOOR
    walker, window, _clock, _arrived, _ = make(app, monkeypatch, y=FLOOR - SNAP - 50)
    assert not walker.snap_to_floor() and window.y() == FLOOR - SNAP - 50  # left where she was put
    walker, window, _clock, _arrived, _ = make(app, monkeypatch, x=1500, y=FLOOR + 10)
    assert walker.snap_to_floor() and window.y() == FLOOR and window.x() == AREA.width() - 300  # kept on screen


def test_a_stalled_ui_never_makes_her_jump(app, monkeypatch):
    walker, window, clock, _arrived, _ = make(app, monkeypatch)
    walker.set_enabled(True)
    walker.start_stroll()
    start = window.x()
    clock.now += 30  # the UI thread was busy for half a minute
    walker.step()
    assert abs(window.x() - start) <= walker_module.SPEED * 0.25 + 1


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _i: False)
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append(config.walking))
    monkeypatch.setattr(Walker, "work_area", lambda self: AREA)
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json")
    ctrl.window.move(QPoint(600, AREA.height() - ctrl.window.height()))
    return ctrl, saved


def test_she_only_walks_when_nothing_else_is_going_on(pet):
    ctrl, _saved = pet
    ctrl.window.clear_bubble()
    assert ctrl._can_walk()
    ctrl.window.say("happy", "在说话")
    assert not ctrl._can_walk()
    ctrl.window.clear_bubble()
    for setting in ("paused",):
        setattr(ctrl.config, setting, True)
        assert not ctrl._can_walk()
        setattr(ctrl.config, setting, False)
    for flag in ("quiet", "asleep", "quit_pending"):
        setattr(ctrl, flag, True)
        assert not ctrl._can_walk()
        setattr(ctrl, flag, False)
    ctrl.window._press_pos = QPoint(1, 1)  # being dragged
    assert not ctrl._can_walk()
    ctrl.window._press_pos = None
    ctrl.config.walking = False
    assert not ctrl._can_walk()


def test_the_menu_and_the_settings_switch_walking(pet):
    ctrl, saved = pet
    ctrl.set_walking(False)
    assert not ctrl.config.walking and not ctrl.walking_action.isChecked() and not ctrl.walker.enabled
    ctrl.open_settings()
    window = ctrl.settings_window
    assert not window.walking_box.isChecked()
    window.walking_box.setChecked(True)
    assert ctrl.config.walking and ctrl.walking_action.isChecked() and ctrl.walker.enabled and saved[-1] is True
    window.close()


def test_switching_it_on_away_from_the_floor_says_how_to_start(pet):
    ctrl, _saved = pet
    ctrl.set_walking(False)
    ctrl.window.move(QPoint(600, 100))
    ctrl.set_walking(True)
    assert "最下面" in ctrl.window.full_text


def test_a_drop_near_the_floor_lands_her_on_it_and_is_remembered(pet):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(400, floor - 40))
    ctrl.window.moved.emit(400, floor - 40)
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (400, floor)
    ctrl.window.move(QPoint(400, 100))
    ctrl.window.moved.emit(400, 100)
    assert (ctrl.config.x, ctrl.config.y) == (400, 100)


def test_resizing_keeps_her_on_the_floor(pet):
    ctrl, _saved = pet
    ctrl.set_sprite_height(320)
    assert ctrl.walker.on_floor()
    ctrl.set_sprite_height(150)
    assert ctrl.walker.on_floor()


def test_walking_is_on_by_default_and_kept_in_the_config(tmp_path):
    assert Config().walking is True
    path = tmp_path / "config.json"
    path.write_text('{"walking": false}', encoding="utf-8")
    assert load_config(path).walking is False


def test_walking_right_mirrors_her(app):
    from claude_pet.pet_window import PetWindow

    window = PetWindow(SPRITES, 200)
    assert window._sprite() is window.sprites["idle"]
    window.set_walking(1)
    mirrored = window._sprite()
    assert mirrored is not window.sprites["idle"] and mirrored.size() == window.sprites["idle"].size()
    window.set_walking(-1)
    assert window._sprite() is window.sprites["idle"]
    window.grab()  # paints while walking without errors
    window.close()


def test_rests_last_25_to_70_seconds(app, monkeypatch):
    walker, *_ = make(app, monkeypatch)
    walker.set_enabled(True)
    for _ in range(50):
        walker.rest()
        assert 25000 <= walker._rest.interval() <= 70000


def test_a_second_monitor_or_left_taskbar_keeps_her_on_that_work_area(app, monkeypatch):
    area = QRect(1920, 0, 1280, 984)  # right-hand monitor, or a work area starting after a left taskbar
    floor = area.height() - 380
    walker, window, clock, _arrived, _ = make(app, monkeypatch, x=1930, y=floor, area=area)
    for seed in range(10):
        walker.rng = random.Random(seed)
        walker.set_enabled(True)
        walker.start_stroll()
        walk_to_the_end(walker, clock)
        assert area.x() <= window.x() <= area.x() + area.width() - window.width() and window.y() == floor
    walker, window, _clock, _arrived, _ = make(app, monkeypatch, x=100, y=floor + 20, area=area)
    assert walker.snap_to_floor() and window.x() == area.x() and window.y() == floor


def test_a_wider_window_mid_walk_never_jumps_or_leaves_the_screen(app, monkeypatch):
    walker, window, clock, _arrived, _ = make(app, monkeypatch, x=1100)
    walker.set_enabled(True)
    walker.rng = random.Random(0)
    walker.start_stroll()
    clock.now += 0.1
    walker.step()
    window._w, window._x = 510, window.x() - 95  # resized under her feet (wider, recentred)
    before = window.x()
    clock.now += 0.033
    walker.step()
    assert abs(window.x() - before) <= 3  # goes on from where she is
    walk_to_the_end(walker, clock)
    assert 0 <= window.x() <= AREA.width() - 510


def test_resizing_mid_walk_stops_her_inside_the_screen(pet):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(AREA.width() - ctrl.window.width() - 100, floor))
    ctrl.window.clear_bubble()
    ctrl.walker.set_enabled(True)
    ctrl.walker.rng = random.Random(0)
    for _ in range(50):
        ctrl.walker.start_stroll()
        if ctrl.walker.walking:
            break
    assert ctrl.walker.walking
    ctrl.walker.step()
    ctrl.window.set_walking(1)
    ctrl.window._sprite()  # a mirrored sprite of the old size is cached
    before, old_width = ctrl.window.geometry(), ctrl.window.width()
    ctrl.set_sprite_height(600)  # the window gets wider
    assert not ctrl.walker.walking and ctrl.walker.on_floor()
    assert ctrl.window._mirrored == {}  # the mirrored sprites of the old size are gone
    grown = ctrl.window.width() - old_width
    assert grown > 0 and abs(ctrl.window.geometry().center().x() - before.center().x()) <= 1  # stopped where she was
    assert ctrl.window.x() + ctrl.window.width() <= before.right() + 1 + (grown + 1) // 2


def test_resizing_to_a_wider_window_keeps_her_on_the_floor(pet):
    ctrl, _saved = pet
    width = ctrl.window.width()
    ctrl.set_sprite_height(600)
    assert ctrl.window.width() > width and ctrl.walker.on_floor()


def test_starting_just_off_the_floor_puts_her_on_it(pet, monkeypatch):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    monkeypatch.setattr(ctrl, "_place_window", lambda: ctrl.window.move(QPoint(500, floor + 4)))
    monkeypatch.setattr(ctrl, "_register_hotkey", lambda: None)
    ctrl.start()
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (500, floor)
    ctrl.shutdown()

