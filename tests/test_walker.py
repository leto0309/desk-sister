"""Strolling along the bottom of the screen."""
import random
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QObject, QPoint, QRect

from claude_pet import controller as controller_module
from claude_pet import walker as walker_module
from claude_pet.config import Config, load_config
from claude_pet.walker import DISTANCE, Walker, plan_stroll

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


def test_landing_puts_her_on_the_floor_and_on_the_screen(app, monkeypatch):
    for y in (FLOOR - 5, 0, FLOOR + 10):
        walker, window, _clock, _arrived, _ = make(app, monkeypatch, x=1500, y=y)
        walker.land_now()
        assert window.y() == FLOOR and window.x() == AREA.width() - 300  # kept on screen
    walker, window, _clock, arrived, _ = make(app, monkeypatch, x=1500, y=FLOOR + 10)
    walker.fall_to_floor()  # from below the floor: straight onto it, no fall
    assert not walker.falling and window.y() == FLOOR


def test_a_long_fall_reaches_its_top_speed_and_never_goes_faster(app, monkeypatch):
    tall = QRect(0, 0, 1600, 3000)
    floor = tall.height() - 380
    walker, window, clock, arrived, _ = make(app, monkeypatch, y=0, area=tall)
    walker.fall_to_floor()
    speeds = []
    while walker.falling and len(speeds) < 500:
        clock.now += 0.033
        walker.step()
        speeds.append(walker._vy)
    assert max(speeds) == walker_module.TOP_SPEED  # 2620 px is far enough to hit the cap
    assert window.y() == floor and arrived == [(window.x(), floor)]


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


def test_switching_it_on_up_the_screen_brings_her_down(pet):
    ctrl, _saved = pet
    clock = Clock()
    ctrl.walker.clock = clock
    ctrl.set_walking(False)
    ctrl.window.move(QPoint(600, 100))
    ctrl.set_walking(True)
    assert ctrl.walker.falling
    _fall_steps(ctrl, clock)
    floor = AREA.height() - ctrl.window.height()
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (600, floor)


def test_a_drop_near_the_floor_lands_her_on_it_and_is_remembered(pet):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    clock = Clock()
    ctrl.walker.clock = clock
    ctrl.window.move(QPoint(400, floor - 40))
    ctrl.window.moved.emit(400, floor - 40)
    assert ctrl.walker.falling and ctrl.config.y != floor  # on her way down, not yet remembered
    heights = []
    for _ in range(40):
        clock.now += 0.033
        ctrl.walker.step()
        heights.append(ctrl.window.y())
        if not ctrl.walker.falling:
            break
    assert heights == sorted(heights) and len(heights) > 2  # falls, faster and faster, never back up
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (400, floor)


def test_a_drop_from_high_up_falls_all_the_way_down(pet):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    clock = Clock()
    ctrl.walker.clock = clock
    ctrl.window.move(QPoint(400, -50))  # from the very top (a little above it, even)
    ctrl.window.moved.emit(400, -50)
    assert ctrl.walker.falling and ctrl.config.y != floor
    heights = []
    while ctrl.walker.falling and len(heights) < 200:
        clock.now += 0.033
        ctrl.walker.step()
        heights.append(ctrl.window.y())
    steps = [b - a for a, b in zip(heights, heights[1:])]
    assert steps and min(steps) >= 0 and max(steps) <= walker_module.TOP_SPEED * 0.033 + 1
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (400, floor)


def test_without_walking_she_stays_where_she_is_put(pet):
    ctrl, _saved = pet
    ctrl.set_walking(False)
    ctrl.window.move(QPoint(400, 100))
    ctrl.window.moved.emit(400, 100)
    assert not ctrl.walker.falling and (ctrl.config.x, ctrl.config.y) == (400, 100)


def test_a_drop_below_the_floor_puts_her_straight_on_it(pet):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(400, floor + 30))  # over the taskbar
    ctrl.window.moved.emit(400, floor + 30)
    assert not ctrl.walker.falling and ctrl.window.y() == floor and ctrl.config.y == floor


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
    walker.land_now()
    assert window.x() == area.x() and window.y() == floor


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


@pytest.mark.parametrize("offset", [4, -300])
def test_starting_with_walking_on_puts_her_on_the_floor(pet, monkeypatch, offset):
    ctrl, _saved = pet
    floor = AREA.height() - ctrl.window.height()
    monkeypatch.setattr(ctrl, "_place_window", lambda: ctrl.window.move(QPoint(500, floor + offset)))
    monkeypatch.setattr(ctrl, "_register_hotkey", lambda: None)
    ctrl.start()
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (500, floor)
    ctrl.shutdown()


def test_starting_with_walking_off_keeps_her_place(pet, monkeypatch):
    ctrl, _saved = pet
    ctrl.config.walking = False
    monkeypatch.setattr(ctrl, "_place_window", lambda: ctrl.window.move(QPoint(500, 120)))
    monkeypatch.setattr(ctrl, "_register_hotkey", lambda: None)
    ctrl.start()
    assert ctrl.window.y() == 120
    ctrl.shutdown()


def _fall_steps(ctrl, clock, limit=60):
    for _ in range(limit):
        if not ctrl.walker.falling:
            return
        clock.now += 0.033
        ctrl.walker.step()


def test_a_click_on_the_way_down_only_holds_her_for_a_moment(pet):
    ctrl, _saved = pet
    clock = Clock()
    ctrl.walker.clock = clock
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(400, floor - 70))
    ctrl.window.moved.emit(400, floor - 70)
    clock.now += 0.033
    ctrl.walker.step()
    ctrl.window._press_pos = QPoint(1, 1)  # pressed: she hangs there
    held = ctrl.window.y()
    for _ in range(5):
        clock.now += 0.033
        ctrl.walker.step()
    assert ctrl.window.y() == held and ctrl.walker.falling
    ctrl.window._press_pos = None  # a click, not a drag: she falls on and lands
    _fall_steps(ctrl, clock)
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (400, floor)


def test_dragged_away_on_the_way_down_she_falls_from_the_new_place(pet):
    ctrl, _saved = pet
    clock = Clock()
    ctrl.walker.clock = clock
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(400, floor - 70))
    ctrl.window.moved.emit(400, floor - 70)
    clock.now += 0.033
    ctrl.walker.step()
    ctrl.window.move(QPoint(300, 100))  # caught and carried up the screen
    ctrl.window.moved.emit(300, 100)
    assert ctrl.walker.falling and ctrl.window.y() == 100  # a new fall, from where she was let go
    _fall_steps(ctrl, clock, 200)
    assert ctrl.window.y() == floor and (ctrl.config.x, ctrl.config.y) == (300, floor)


def _drop_from(ctrl, clock, x, y):
    ctrl.walker.clock = clock
    ctrl.window.move(QPoint(x, y))
    ctrl.window.moved.emit(x, y)
    clock.now += 0.033
    ctrl.walker.step()


def test_switching_walking_off_on_the_way_down_leaves_her_there(pet):
    ctrl, _saved = pet
    clock = Clock()
    _drop_from(ctrl, clock, 400, 100)
    assert ctrl.walker.falling
    ctrl.set_walking(False)
    here = ctrl.window.y()
    assert not ctrl.walker.falling and not ctrl.walker._frame.isActive() and ctrl.config.y == here
    ctrl.window.move(QPoint(500, 200))  # put somewhere else afterwards
    ctrl.window.moved.emit(500, 200)
    for _ in range(5):
        clock.now += 0.033
        ctrl.walker.step()
    assert ctrl.window.y() == 200 and (ctrl.config.x, ctrl.config.y) == (500, 200)


def test_a_quick_drop_below_the_floor_mid_stroll_ends_the_stroll(pet):
    ctrl, _saved = pet
    clock = Clock()
    ctrl.walker.clock = clock
    ctrl.window.clear_bubble()
    ctrl.walker.set_enabled(True)
    ctrl.walker.rng = random.Random(0)
    for _ in range(50):
        ctrl.walker.start_stroll()
        if ctrl.walker.walking:
            break
    assert ctrl.walker.walking
    floor = AREA.height() - ctrl.window.height()
    ctrl.window.move(QPoint(300, floor + 30))  # pressed, dragged below the floor, released: no frame in between
    ctrl.window.moved.emit(300, floor + 30)
    assert not ctrl.walker.walking and ctrl.window.walking == 0 and ctrl.window.y() == floor
    assert ctrl.walker._rest.isActive()  # the next stroll will come
    ctrl.walker.start_stroll()
    assert ctrl.walker.walking or ctrl.walker._rest.isActive()


@pytest.mark.parametrize("height", [320, 120])
def test_resizing_on_the_way_down_never_jumps(pet, height):
    ctrl, _saved = pet
    clock = Clock()
    _drop_from(ctrl, clock, 400, 50)
    ctrl.set_sprite_height(height)  # her feet stay; the window's top moves
    after = ctrl.window.y()
    clock.now += 0.033
    ctrl.walker.step()
    assert 0 <= ctrl.window.y() - after <= walker_module.TOP_SPEED * 0.05 + 1  # on down from there, no jump back
    _fall_steps(ctrl, clock, 200)
    floor = AREA.height() - ctrl.window.height()
    assert ctrl.window.y() == floor and ctrl.config.y == floor

