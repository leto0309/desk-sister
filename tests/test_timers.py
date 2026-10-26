"""The focus timer (pomodoro) and reminders: counted on the wall clock, said by her, shown at her feet."""
import datetime
import json
import random
from pathlib import Path

import pytest

from claude_pet import bedtime, claude_client, i18n, persona, persona_en, timers
from claude_pet.config import Config, load_config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402
from claude_pet.reminder_dialog import ReminderDialog  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
T0 = datetime.datetime(2026, 11, 3, 14, 0).timestamp()  # a Tuesday, 14:00 local time


# ---- the pomodoro ----------------------------------------------------------------------------------------
def test_focus_then_a_break_then_focus_again():
    pomo = timers.Pomodoro()
    pomo.start(T0, 25 * 60)
    assert pomo.running and pomo.phase == "focus" and pomo.left(T0 + 60) == 24 * 60
    assert pomo.due(T0 + 25 * 60 - 1, 1500, 300) is None
    assert pomo.due(T0 + 25 * 60, 1500, 300) == "focus_done" and pomo.phase == "break" and pomo.done == 1
    assert pomo.due(T0 + 30 * 60, 1500, 300) == "break_done" and pomo.phase == "focus"
    assert pomo.left(T0 + 30 * 60) == 25 * 60
    assert pomo.stop() == 1 and not pomo.running and pomo.left(T0) == 0


def test_pausing_freezes_the_time_left():
    pomo = timers.Pomodoro()
    pomo.start(T0, 1500)
    pomo.pause(T0 + 600)
    assert pomo.paused and pomo.left(T0 + 5000) == 900 and pomo.due(T0 + 5000, 1500, 300) is None
    pomo.resume(T0 + 5000)
    assert not pomo.paused and pomo.left(T0 + 5000) == 900
    assert pomo.due(T0 + 5900, 1500, 300) == "focus_done"


def test_after_the_pc_slept_the_next_period_starts_from_waking():
    pomo = timers.Pomodoro()
    pomo.start(T0, 1500)
    later = T0 + 3 * 3600  # asleep for hours: one line, then a whole break from now
    assert pomo.due(later, 1500, 300) == "focus_done" and pomo.left(later) == 300
    assert pomo.due(later + 1, 1500, 300) is None


@pytest.mark.parametrize("seconds, text", [(1500, "25:00"), (299.2, "5:00"), (59, "0:59"), (0, "0:00"),
                                           (3600, "1:00:00"), (3725, "1:02:05"), (-3, "0:00")])
def test_time_left_text(seconds, text):
    assert timers.left_text(seconds) == text


def test_when_a_reminder_is_due():
    assert timers.due_in(T0, 30) == T0 + 1800 and timers.due_in(T0, 0) == T0 + 60
    assert timers.clock_text(timers.due_at(T0, 15, 30)) == "15:30"
    assert timers.due_at(T0, 15, 30) - T0 == 5400  # later today
    tomorrow = timers.due_at(T0, 9, 0)  # passed today: tomorrow
    assert datetime.datetime.fromtimestamp(tomorrow) == datetime.datetime(2026, 11, 4, 9, 0)
    assert timers.due_at(T0, 14, 0) > T0  # the very minute now: tomorrow, never "now"


# ---- reminders -------------------------------------------------------------------------------------------
def test_reminders_are_kept_in_order_and_survive_a_restart(tmp_path):
    path = tmp_path / "reminders.json"
    store = timers.Reminders(path)
    late = store.add(T0 + 3600, "开会")
    early = store.add(T0 + 600, "  喝口水  ")
    assert [r.text for r in store.items] == ["喝口水", "开会"] and store.next() == early
    again = timers.Reminders(path)
    assert [(r.due, r.text, r.id) for r in again.items] == [(early.due, "喝口水", early.id), (late.due, "开会", late.id)]
    assert again.cancel(early.id) == early and again.cancel("nope") is None
    assert [r.text for r in timers.Reminders(path).items] == ["开会"]


def test_a_due_reminder_stays_saved_until_it_is_finished(tmp_path):
    path = tmp_path / "r.json"
    store = timers.Reminders(path)
    first = store.add(T0 - 300, "刚错过")
    store.add(T0 + 60, "还没到")
    assert store.due_now(T0) == first and store.due_now(T0) == first  # asked again: still there
    assert [r.text for r in timers.Reminders(path).items] == ["刚错过", "还没到"]  # a restart now keeps it
    store.finish(first.id)
    assert store.due_now(T0) is None and [r.text for r in timers.Reminders(path).items] == ["还没到"]


def test_a_failed_save_changes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    store = timers.Reminders(path)
    kept = store.add(T0 + 60, "留着")

    def locked(_items):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(store, "_write", locked)
    with pytest.raises(OSError):
        store.add(T0 + 120, "存不上")
    with pytest.raises(OSError):
        store.cancel(kept.id)
    assert store.items == [kept]
    store.finish(kept.id)  # said: gone from the list even if the file could not follow (logged)
    assert store.items == []


def test_limits(tmp_path):
    store = timers.Reminders(tmp_path / "r.json")
    assert store.add(T0, "   ") is None
    assert len(store.add(T0, "长" * 500).text) == timers.MAX_TEXT
    for i in range(timers.MAX_REMINDERS - 1):
        assert store.add(T0 + i, f"第 {i} 个")
    assert store.add(T0, "满了") is None and len(store.items) == timers.MAX_REMINDERS


@pytest.mark.parametrize("content", ["not json", '{"a": 1}', '[{"due": "x", "text": "a", "id": "1"}, 3, null]',
                                     '[{"due": NaN, "text": "a", "id": "1"}]', '[{"due": 1e300, "text": "a", "id": "1"}]',
                                     '[{"due": -1, "text": "a", "id": "1"}]'])
def test_a_damaged_file_gives_no_reminders_and_no_crash(tmp_path, content):
    path = tmp_path / "r.json"
    path.write_text(content, encoding="utf-8")
    assert timers.Reminders(path).items == []


def test_a_good_entry_survives_bad_neighbours(tmp_path):
    path = tmp_path / "r.json"
    huge = '{"due": 1' + "0" * 400 + ', "text": "太大", "id": "2"}'
    path.write_text("[" + json.dumps({"due": T0, "text": "好的", "id": "1"}) + ', {"text": "缺时间"}, ' + huge + "]",
                    encoding="utf-8")
    assert [r.text for r in timers.Reminders(path).items] == ["好的"]


# ---- her lines -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("table", [persona.TIMER_TALK, persona_en.TIMER_TALK])
def test_timer_lines_never_talk_of_sleep_or_rest_and_fill_their_fields(table):
    for kind, choices in table.items():
        for mood, text in choices:
            filled = text.format(25, 5, 3) if kind not in ("reminder", "missed") else text.format("喝水", "14:30")
            assert mood in persona.MOODS and not bedtime.mentions(filled) and "{" not in filled, (kind, text)


# ---- the pet ---------------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: False)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01", self_talk=False), SPRITES,
                                           tmp_path / "config.json")
    ctrl._rng = random.Random(1)
    ctrl._now = Clock()
    ctrl._summarize_day_if_due = lambda: None
    yield ctrl
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def beat(ctrl, seconds=1.0):
    ctrl._now.now += seconds
    ctrl._update_timers()
    ctrl._refresh_status()


def test_a_focus_period_counts_down_at_her_feet_and_ends_with_a_line(pet):
    pet.start_focus()
    assert "25 分钟" in pet.window.full_text
    pet.window.clear_bubble()
    beat(pet)
    assert pet.window.status == "专注 24:59"
    beat(pet, 25 * 60)
    assert "5 分钟" in pet.window.full_text and pet.window._hide_bubble.interval() == controller_module.TIMER_HOLD_MS
    assert pet.window.status.startswith("放松 ")
    pet.window.clear_bubble()
    beat(pet, 5 * 60)
    assert "25 分钟" in pet.window.full_text and pet.window.status.startswith("专注 ")


def test_pause_resume_stop(pet):
    pet.start_focus()
    beat(pet, 60)
    pet.toggle_focus_pause()
    assert "24:00" in pet.window.full_text and pet.window.status == "专注 24:00（暂停）"
    beat(pet, 3600)
    assert pet.window.status == "专注 24:00（暂停）"
    pet.toggle_focus_pause()
    assert pet.pomodoro.running and not pet.pomodoro.paused
    pet.stop_focus()
    assert "0 个" in pet.window.full_text and not pet.pomodoro.running and pet.window.status == ""


def test_a_due_line_waits_for_her_bubble_and_for_full_screen(pet, monkeypatch):
    pet.reminders.add(T0 + 10, "喝口水")
    pet.window.say("talk", "我在说别的")
    beat(pet, 11)
    assert pet.window.full_text == "我在说别的"  # one bubble at a time
    pet.window.clear_bubble()
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    pet._update_quiet()
    beat(pet)
    assert pet.window.full_text == ""  # held while something is full screen
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: False)
    pet._update_quiet()
    beat(pet)
    assert "喝口水" in pet.window.full_text


def test_a_reminder_wakes_her(pet):
    pet.asleep = True
    pet.window.set_mood("sleep")
    pet.reminders.add(T0 + 5, "开会")
    beat(pet, 6)
    assert not pet.asleep and "开会" in pet.window.full_text


def test_two_due_at_once_are_said_one_after_the_other(pet):
    pet.reminders.add(T0 + 5, "第一件")
    pet.reminders.add(T0 + 6, "第二件")
    beat(pet, 10)
    assert "第一件" in pet.window.full_text
    pet.window.clear_bubble()
    beat(pet)
    assert "第二件" in pet.window.full_text


def test_held_in_full_screen_it_says_when_it_was_for_or_is_dropped(pet, monkeypatch):
    pet.reminders.add(T0 + 10, "喝口水")
    pet.reminders.add(T0 + 20, "很久以前的事")
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    pet._update_quiet()
    beat(pet, 11)
    beat(pet, 600)  # ten minutes of a game
    assert pet.window.full_text == "" and len(pet.reminders.items) == 2  # waiting, and still saved
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: False)
    pet._update_quiet()
    beat(pet)
    assert "14:00" in pet.window.full_text and "喝口水" in pet.window.full_text  # late: says when it was for
    pet.window.clear_bubble()
    pet._now.now += timers.FORGET_AFTER_SEC  # the next one now waited half a day
    beat(pet)
    assert pet.window.full_text == "" and pet.reminders.items == []


def test_a_reminder_due_in_full_screen_survives_a_restart(pet, monkeypatch, tmp_path):
    pet.reminders.add(T0 + 10, "交报告")
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    pet._update_quiet()
    beat(pet, 30)
    assert [r.text for r in timers.Reminders(tmp_path / "reminders.json").items] == ["交报告"]


def test_stopping_the_timer_drops_its_unsaid_line(pet):
    pet.start_focus()
    pet.window.say("talk", "我在说别的")
    beat(pet, 25 * 60)
    assert pet.window.full_text == "我在说别的" and pet.pomodoro.phase == "break"  # held, the timer moved on
    pet.stop_focus()
    pet.window.clear_bubble()
    beat(pet)
    assert pet.window.full_text == ""  # no "back in 5 minutes" for a timer that has stopped


def test_saving_trouble_is_told_not_hidden(pet, monkeypatch):
    kept = pet.reminders.add(T0 + 3600, "留着")

    def locked(_items):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(pet.reminders, "_write", locked)
    pet._ask_reminder = lambda clock: (clock() + 60, "存不上")
    pet.add_reminder()
    assert "没存上" in pet.window.full_text and pet.reminders.items == [kept]
    pet.cancel_reminder(kept.id)
    assert "没能取消" in pet.window.full_text and pet.reminders.items == [kept]


def test_a_reminder_missed_while_she_was_closed_says_when_it_was_for(pet):
    pet.reminders.add(T0 - 3600, "交报告")
    beat(pet)
    assert "13:00" in pet.window.full_text and "交报告" in pet.window.full_text


def test_adding_and_cancelling_from_the_menu(pet):
    pet._ask_reminder = lambda clock: (timers.due_in(clock(), 30), "看一眼烤箱")
    pet.add_reminder()
    assert "14:30" in pet.window.full_text and "看一眼烤箱" in pet.window.full_text
    assert pet.window.status == "提醒 14:30"
    pet._ask_reminder = lambda clock: (timers.due_at(clock(), 9, 0), "早会")
    pet.add_reminder()
    assert "明天 09:00" in pet.window.full_text and pet.window.status == "提醒 14:30（共 2 个）"
    pet._fill_timer_menu()
    labels = [a.text() for a in pet.timer_menu.actions() if not a.isSeparator()]
    assert labels == ["开始专注（25 分钟）", "添加提醒…", "取消提醒：14:30 看一眼烤箱", "取消提醒：09:00 早会"]
    pet.timer_menu.actions()[-2].trigger()
    assert [r.text for r in pet.reminders.items] == ["早会"] and "14:30" in pet.window.full_text
    pet._ask_reminder = lambda clock: None  # cancelled dialog
    pet.add_reminder()
    assert len(pet.reminders.items) == 1


def test_the_menu_follows_the_timer(pet):
    pet.start_focus()
    pet._fill_timer_menu()
    assert [a.text() for a in pet.timer_menu.actions()][:2] == ["暂停计时", "结束番茄钟"]
    pet.toggle_focus_pause()
    pet._fill_timer_menu()
    assert pet.timer_menu.actions()[0].text() == "继续计时"


def test_a_full_list_is_refused_kindly(pet):
    for i in range(timers.MAX_REMINDERS):
        pet.reminders.add(T0 + 3600 + i, f"第 {i} 个")
    pet._ask_reminder = lambda clock: (clock() + 60, "再来一个")
    pet.add_reminder()
    assert "先取消几个" in pet.window.full_text and len(pet.reminders.items) == timers.MAX_REMINDERS


def test_minutes_from_the_settings(pet):
    pet.set_focus_minutes(50)
    pet.set_break_minutes(500)
    assert (pet.config.focus_min, pet.config.break_min) == (50, timers.BREAK_RANGE[1])
    pet.open_settings()
    window = pet.settings_window
    assert window.focus_spin.value() == 50
    window.focus_spin.setValue(30)
    window.break_spin.setValue(10)
    assert (pet.config.focus_min, pet.config.break_min) == (30, 10)


def test_config_cleans_the_minutes(tmp_path):
    assert (Config().focus_min, Config().break_min) == (25, 5)
    path = tmp_path / "config.json"
    path.write_text('{"focus_min": "lots", "break_min": 0, "watch_mode": "allowlist"}', encoding="utf-8")
    config = load_config(path)
    assert (config.focus_min, config.break_min, config.watch_mode) == (25, 1, "allowlist")


def test_in_english(pet):
    i18n.set_language("en")
    pet.start_focus()
    assert "25 minutes" in pet.window.full_text
    beat(pet)
    assert pet.window.status == "Focus 24:59"


# ---- the dialog ------------------------------------------------------------------------------------------
def test_the_dialog_needs_some_text_and_works_out_when(app):
    dialog = ReminderDialog(None, T0)
    assert not dialog.ok_button.isEnabled() and dialog.chosen(T0) is None
    dialog.text.setText("  喝口水 ")
    assert dialog.ok_button.isEnabled()
    dialog.minutes.setValue(45)
    assert dialog.chosen(T0) == (T0 + 45 * 60, "喝口水")
    dialog.time.setTime(dialog.time.time().fromString("08:15", "HH:mm"))
    assert dialog.at_time.isChecked()  # changing the time picks that way
    due, _text = dialog.chosen(T0)
    assert datetime.datetime.fromtimestamp(due) == datetime.datetime(2026, 11, 4, 8, 15)
    dialog.close()


def test_a_damaged_file_is_kept_aside_not_lost(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{oops", encoding="utf-8")
    store = timers.Reminders(path)
    assert store.items == [] and (tmp_path / "r.json.bad").read_text(encoding="utf-8") == "{oops"
    assert store.add(T0, "新的") and [r.text for r in timers.Reminders(path).items] == ["新的"]


def test_a_file_that_could_not_be_read_is_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    timers.Reminders(path).add(T0 + 600, "原来的")
    real_bytes = Path.read_bytes
    held = {"on": True}

    def read(self):
        if held["on"] and self == path:
            raise PermissionError(32, "being used by another process")
        return real_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    store = timers.Reminders(path)
    assert store.unreadable and store.items == []
    with pytest.raises(OSError):
        store.add(T0 + 60, "新的")  # refused: writing now would wipe "原来的"
    held["on"] = False  # the other program let go
    assert store.add(T0 + 60, "新的")
    assert [r.text for r in timers.Reminders(path).items] == ["新的", "原来的"]


def test_a_late_timer_line_tells_the_time_really_left(pet, monkeypatch):
    pet.start_focus()
    pet.window.clear_bubble()
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: True)
    pet._update_quiet()
    beat(pet, 25 * 60)
    beat(pet, 4 * 60)  # four minutes of the break went by in full screen
    monkeypatch.setattr(controller_module, "full_screen_now", lambda _h=0: False)
    pet._update_quiet()
    beat(pet)
    assert "1 分钟后" in pet.window.full_text and "5 分钟后" not in pet.window.full_text


def test_a_bad_time_in_the_file_never_stops_the_menu(app, tmp_path, monkeypatch, pet):
    (tmp_path / "reminders.json").write_text(
        json.dumps([{"due": -1, "text": "坏的", "id": "x"}, {"due": T0 + 60, "text": "好的", "id": "y"}]), encoding="utf-8")
    pet.reminders = timers.Reminders(tmp_path / "reminders.json")
    pet._fill_timer_menu()
    assert [r.text for r in pet.reminders.items] == ["好的"]


@pytest.mark.parametrize("raw", [b"\xff\xfe[\x00]\x00", b"[{\"due\": 1, \"text\": \"\xe4\"}]"])
def test_a_file_that_is_not_utf8_is_kept_aside(tmp_path, raw):
    path = tmp_path / "r.json"
    path.write_bytes(raw)
    store = timers.Reminders(path)
    assert store.items == [] and not store.unreadable and (tmp_path / "r.json.bad").read_bytes() == raw


def test_reminders_come_back_once_the_file_can_be_read(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    timers.Reminders(path).add(T0 + 60, "原来的")
    real_bytes = Path.read_bytes
    held = {"on": True}

    def read(self):
        if held["on"] and self == path:
            raise PermissionError(32, "being used by another process")
        return real_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    store = timers.Reminders(path)
    assert store.unreadable and store.due_now(T0 + 120) is None
    held["on"] = False
    assert store.due_now(T0 + 121) is None  # not every second: after a pause
    reminder = store.due_now(T0 + 120 + timers.RETRY_READ_SEC)
    assert reminder is not None and reminder.text == "原来的"


def test_a_held_timer_line_is_dropped_if_the_timer_is_paused(pet):
    pet.start_focus()
    pet.window.say("talk", "我在说别的")
    beat(pet, 25 * 60)
    pet.toggle_focus_pause()  # paused during the break, before her "back in 5 minutes"
    pet.window.clear_bubble()
    beat(pet)
    assert pet.window.full_text == ""


# ---- the focus log ---------------------------------------------------------------------------------------
def test_the_log_counts_each_day_and_keeps_sixty(tmp_path):
    path = tmp_path / "focus.json"
    log = timers.FocusLog(path)
    log.add(T0, 1500)
    log.add(T0 + 600, 1500)
    day = datetime.date(2026, 11, 3)
    assert log.on(day) == (2, 3000.0) and log.on(day + datetime.timedelta(days=1)) == (0, 0.0)
    assert timers.FocusLog(path).on(day) == (2, 3000.0)  # kept across a restart
    log.add(T0 + 61 * 86400, 1500)  # two months later: the old days go
    assert timers.FocusLog(path).on(day) == (0, 0.0)


def test_a_period_counts_for_the_day_it_ends(tmp_path):
    log = timers.FocusLog(tmp_path / "focus.json")
    midnight = datetime.datetime(2026, 11, 4, 0, 5).timestamp()
    log.add(midnight, 1500)  # began before midnight, finished after it
    assert log.on(datetime.date(2026, 11, 4)) == (1, 1500.0)


@pytest.mark.parametrize("content", ["oops", "[1, 2]", '{"2026-11-03": {"count": "x"}, "nope": {"count": 1, "seconds": 1}}',
                                     '{"2026-11-03": {"count": -1, "seconds": 5}}'])
def test_a_damaged_log_starts_afresh(tmp_path, content):
    path = tmp_path / "focus.json"
    path.write_text(content, encoding="utf-8")
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (0, 0.0)


def test_an_unreadable_log_is_not_written_over(tmp_path, monkeypatch):
    path = tmp_path / "focus.json"
    timers.FocusLog(path).add(T0, 1500)
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError(32, "in use"))
                        if self == path else real(self))
    log = timers.FocusLog(path)
    log.add(T0 + 60, 1500)
    monkeypatch.setattr(Path, "read_bytes", real)
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (1, 1500.0)


def test_finished_focus_periods_are_logged_and_shown_in_the_menu(pet):
    pet.set_focus_minutes(30)
    pet.start_focus()
    pet.window.clear_bubble()
    beat(pet, 30 * 60)  # one done
    pet.window.clear_bubble()
    beat(pet, 5 * 60)  # the break: not counted
    pet.window.clear_bubble()
    pet.toggle_focus_pause()
    pet.stop_focus()  # a period stopped half way: not counted
    assert pet.focus_log.on(datetime.date(2026, 11, 3)) == (1, 1800.0)
    pet._fill_timer_menu()
    first = pet.timer_menu.actions()[0]
    assert first.text() == "今天已完成 1 个番茄" and not first.isEnabled()


def test_the_menu_shows_no_count_on_a_day_without_pomodoros(pet):
    pet._fill_timer_menu()
    assert pet.timer_menu.actions()[0].text() == "开始专注（25 分钟）"


def test_a_period_that_ran_out_while_the_pc_slept_counts_for_its_own_day(pet):
    pet._now.now = datetime.datetime(2026, 11, 3, 23, 30).timestamp()
    pet.start_focus()
    pet.window.clear_bubble()
    beat(pet, 9 * 3600)  # due at 23:55, but the PC slept until morning
    assert pet.focus_log.on(datetime.date(2026, 11, 3)) == (1, 1500.0)
    assert pet.focus_log.on(datetime.date(2026, 11, 4)) == (0, 0.0)


def test_what_is_finished_while_the_log_is_locked_is_saved_once_it_is_free(tmp_path, monkeypatch):
    path = tmp_path / "focus.json"
    timers.FocusLog(path).add(T0, 1500)  # one from before
    real = Path.read_bytes
    held = {"on": True}

    def read(self):
        if held["on"] and self == path:
            raise PermissionError(32, "in use")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    log = timers.FocusLog(path)
    log.add(T0 + 60, 1500)  # still locked: kept in memory, the file untouched
    held["on"] = False
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (1, 1500.0)
    log.add(T0 + 120, 1500)  # free again: the old one, the waiting one and this one
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (3, 4500.0)
    assert log.on(datetime.date(2026, 11, 3)) == (3, 4500.0)


def test_the_last_period_is_saved_once_the_log_is_free_without_another(pet, tmp_path, monkeypatch):
    path = tmp_path / "focus.json"
    real = Path.read_bytes
    held = {"on": True}

    def read(self):
        if held["on"] and self == path:
            raise PermissionError(32, "in use")
        return real(self)

    path.write_text('{"2026-11-02": {"count": 2, "seconds": 3000}}', encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", read)
    pet.focus_log = timers.FocusLog(path)
    pet.start_focus()
    pet.window.clear_bubble()
    beat(pet, 25 * 60)  # finished while the file is locked
    pet.stop_focus()  # and no more periods today
    held["on"] = False
    beat(pet, timers.RETRY_READ_SEC + 1)  # the heartbeat tries again by itself
    saved = timers.FocusLog(path)
    assert saved.on(datetime.date(2026, 11, 3)) == (1, 1500.0) and saved.on(datetime.date(2026, 11, 2)) == (2, 3000.0)
    beat(pet, timers.RETRY_READ_SEC + 1)
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (1, 1500.0)  # saved once, not twice


def test_quitting_makes_a_last_try(pet, tmp_path, monkeypatch):
    path = tmp_path / "focus.json"
    real = Path.read_bytes
    held = {"on": True}
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError(32, "in use"))
                        if held["on"] and self == path else real(self))
    path.write_text("{}", encoding="utf-8")
    pet.focus_log = timers.FocusLog(path)
    pet.focus_log.add(T0, 1500)
    held["on"] = False
    pet.shutdown()
    assert timers.FocusLog(path).on(datetime.date(2026, 11, 3)) == (1, 1500.0)


def test_a_log_locked_at_start_comes_back_by_itself(pet, tmp_path, monkeypatch):
    path = tmp_path / "focus.json"
    path.write_text('{"2026-11-03": {"count": 3, "seconds": 4500}}', encoding="utf-8")
    real = Path.read_bytes
    held = {"on": True}
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError(32, "in use"))
                        if held["on"] and self == path else real(self))
    pet.focus_log = timers.FocusLog(path)
    assert pet.focus_log.on(datetime.date(2026, 11, 3)) == (0, 0.0)
    held["on"] = False
    beat(pet, timers.RETRY_READ_SEC + 1)  # no new period: the heartbeat reads it again anyway
    assert pet.focus_log.on(datetime.date(2026, 11, 3)) == (3, 4500.0)
    pet._fill_timer_menu()
    assert pet.timer_menu.actions()[0].text() == "今天已完成 3 个番茄"
    assert path.read_text(encoding="utf-8") == '{"2026-11-03": {"count": 3, "seconds": 4500}}'  # read, not rewritten
