import threading
import time
from pathlib import Path

import pytest

from claude_pet import claude_client
from claude_pet.capture import WindowInfo
from claude_pet.config import Config
from claude_pet.persona import MOODS

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402
from claude_pet.controller import Outcome  # noqa: E402
from claude_pet.pet_window import PetWindow  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
OK = claude_client.ClaudeResult(True, "talk|好")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_window_says_and_types(app):
    window = PetWindow(Path("missing-folder"), 160)
    assert set(window.sprites) == set(MOODS)
    window.say("angry", "排版！")
    assert window.mood == "angry" and window.visible_text == ""
    for _ in range(3):
        window._type_next()
    assert window.visible_text == "排版！"
    window.grab()  # paints the bubble and placeholder sprite offscreen
    window.clear_bubble()
    assert window.mood == "idle" and window.full_text == ""


def calm_machine(monkeypatch, idle=0.0, fullscreen=False, busy=False):
    """Pin the real-machine signals (input idle, full screen) so tests never depend on this computer."""
    state = {"idle": idle, "fullscreen": fullscreen, "busy": busy}
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: state["idle"])
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _info: state["fullscreen"])
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: state["busy"])
    return state


def make_controller(app, tmp_path, monkeypatch, sync=True, **config):
    """Controller whose Claude step is recorded instead of run; by default the worker runs inline."""
    config = {"dwell_sec": 0, **config}
    calm_machine(monkeypatch)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(**config), SPRITES, tmp_path / "config.json")
    calls = []

    def fake_ask(job, snapshot):
        calls.append((snapshot, job.user_message))
        return OK, True

    monkeypatch.setattr(ctrl, "_ask_claude", fake_ask)
    if sync:
        ctrl._spawn = lambda fn: fn()
    return ctrl, calls


def fake_window(monkeypatch, info):
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: info)
    monkeypatch.setattr(controller_module.capture, "window_info", lambda _hwnd: info)


def test_blocked_window_is_never_captured(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "Bitwarden", "Bitwarden.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured a blocked window"))
    ctrl.tick(force=True)
    assert calls == [] and "私密" in ctrl.window.full_text and not ctrl.busy


def test_paused_pet_does_not_capture(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, paused=True)
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured while paused"))
    ctrl.tick()
    ctrl.tick(force=True)
    assert calls == []
    ctrl.tick(force=True, user_message="你好")  # talking while paused sends text only
    assert len(calls) == 1 and calls[0][0].jpeg is None and calls[0][1] == "你好"


def test_unchanged_screen_is_skipped_but_poke_is_not(app, tmp_path, monkeypatch):
    from PIL import Image

    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "main.py - VS Code", "Code.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: Image.new("RGB", (800, 600), "white"))
    ctrl.tick()
    ctrl.tick()
    assert len(calls) == 1 and calls[0][0].jpeg
    ctrl.tick(force=True)
    assert len(calls) == 2


def test_own_window_is_not_the_target(app, tmp_path, monkeypatch):
    import os

    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "Claude Pet", "python.exe", os.getpid(), (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured itself"))
    ctrl.tick(force=True)
    assert calls == []


def test_unidentified_process_is_never_captured(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "Alice", "", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured unknown process"))
    ctrl.tick(force=True)
    assert calls == []


def test_window_that_turns_private_during_capture_is_discarded(app, tmp_path, monkeypatch):
    from PIL import Image

    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    before = WindowInfo(1, "新闻 - Edge", "msedge.exe", 4242, (0, 0, 800, 600))
    after = WindowInfo(1, "招商银行 - Edge", "msedge.exe", 4242, (0, 0, 800, 600))
    lookups = iter([before, after])
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: before)
    monkeypatch.setattr(controller_module.capture, "window_info", lambda _hwnd: next(lookups))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: Image.new("RGB", (800, 600), "white"))
    ctrl.tick(force=True)
    assert calls == []


def test_hung_capture_does_not_freeze_the_ui(app, tmp_path, monkeypatch):
    """PrintWindow on a hung window may never return: tick, pause and the late result stay harmless."""
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, sync=False)
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    release = threading.Event()

    def hung_capture(_info):
        release.wait(20)
        from PIL import Image
        return Image.new("RGB", (800, 600), "white")

    monkeypatch.setattr(controller_module.capture, "capture_window", hung_capture)
    started = time.monotonic()
    ctrl.tick(force=True)
    assert time.monotonic() - started < 1 and ctrl.busy
    ctrl.toggle_pause()  # works while the capture is stuck
    assert ctrl.config.paused and not ctrl.busy
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    assert calls == []  # the stale job never reached Claude
    assert "好" != ctrl.window.full_text


def test_watchdog_abandons_a_stuck_job(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    call = FakeCall()
    ctrl.current_call, ctrl.busy = call, True
    ctrl.generation += 1
    ctrl._watchdog(ctrl.generation - 1)  # an older job: ignored
    assert ctrl.busy
    ctrl._watchdog(ctrl.generation)
    assert call.cancelled and not ctrl.busy and ctrl.window.mood == "panic"


class FakeCall:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def test_pause_and_quit_cancel_inflight_call_and_drop_late_reply(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    for stop in (ctrl.toggle_pause, ctrl.shutdown):
        ctrl.config.paused = False
        call = FakeCall()
        ctrl.current_call, ctrl.busy = call, True
        ctrl.generation += 1
        stale = ctrl.generation
        stop()
        assert call.cancelled and not ctrl.busy
        ctrl.window.clear_bubble()
        ctrl._on_reply(Outcome(stale, "reply", result=claude_client.ClaudeResult(True, "happy|迟到的回复"), auth_ok=True))
        assert "迟到的回复" not in ctrl.window.full_text and list(ctrl.recent) == []


def test_reply_updates_window_and_history(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    ctrl.busy = True
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|代码好整齐～"), auth_ok=True))
    assert not ctrl.busy and ctrl.window.mood == "happy" and list(ctrl.recent) == ["代码好整齐～"]
    assert ctrl.auth_ok_until > 0
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(False, error="timeout", timed_out=True)))
    assert ctrl.window.mood == "panic" and len(ctrl.recent) == 1


def test_not_subscription_result_is_reported(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    result = claude_client.ClaudeResult(False, error="api key", not_subscription=True)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=result, auth_ok=False))
    assert "订阅" in ctrl.window.full_text and ctrl.auth_ok_until == 0.0


def test_pause_before_the_worker_runs_takes_no_screenshot(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured after pause"))
    pending = []
    ctrl._spawn = pending.append
    ctrl.tick(force=True)
    ctrl.toggle_pause()
    pending[0]()  # the worker only starts now
    assert calls == []


def test_stuck_captures_do_not_pile_up(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, sync=False)
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    release = threading.Event()
    captures = []

    def never_returns(_info):
        captures.append(1)
        release.wait(30)
        return None

    monkeypatch.setattr(controller_module.capture, "capture_window", never_returns)
    before = threading.active_count()
    try:
        for _ in range(4):
            ctrl.tick(force=True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and ctrl.busy:
                app.processEvents()
                time.sleep(0.02)
            if ctrl.busy:
                ctrl._watchdog(ctrl.generation)  # the stuck job is abandoned
        assert len(captures) == 1  # later jobs skipped capturing instead of starting another PrintWindow
        assert threading.active_count() <= before + 1
        assert calls == []
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while threading.active_count() > before and time.monotonic() < deadline:
            time.sleep(0.05)


def test_pending_launch_is_an_error_not_a_subscription_problem(app, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json")

    class PendingCall:
        cancelled = False

        def check_subscription(self, _exe):
            return False, claude_client.LAUNCH_PENDING

        def run(self, *_a):
            pytest.fail("must not call the model after the auth step failed")

    job = controller_module.Job(
        generation=ctrl.generation, force=True, user_message="hi", may_capture=False, hwnd=0, blocklist=[],
        last_fingerprint=None, need_auth=True, claude="claude.exe", model="haiku", recent=[],
        call=PendingCall(),
    )
    result, auth_ok = ctrl._ask_claude(job, controller_module.NOTHING)
    assert not result.ok and not result.not_subscription and auth_ok is None
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=result, auth_ok=auth_ok))
    assert "订阅" not in ctrl.window.full_text and ctrl.window.mood == "panic"


class FakeAutostart:
    def __init__(self, enabled=False, fail=False, state=None, gate=None):
        self.enabled, self.fail, self.forced_state, self.gate, self.calls = enabled, fail, state, gate, []

    def state(self):
        return self.forced_state or ("on" if self.enabled else "off")

    def enable(self):
        self.calls.append("enable")
        if self.fail:
            raise controller_module.AutostartError("被占用")
        self.enabled = True

    def disable(self):
        self.calls.append("disable")
        if self.gate is not None:
            self.gate.wait(10)
        self.enabled = False


def autostart_controller(app, tmp_path, monkeypatch, fake, sync=True):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    if sync:
        monkeypatch.setattr(controller_module.PetController, "_spawn_autostart", staticmethod(lambda fn: fn()))
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json", autostart=fake)
    quits = []
    ctrl._quit = lambda: quits.append(1)
    return ctrl, quits


def test_autostart_menu_toggle(app, tmp_path, monkeypatch):
    fake = FakeAutostart(enabled=True)
    ctrl, _quits = autostart_controller(app, tmp_path, monkeypatch, fake)
    assert ctrl.autostart_action.isChecked() and ctrl.autostart_action.isEnabled()
    ctrl.set_autostart(False)
    assert fake.calls == ["disable"] and not ctrl.autostart_action.isChecked() and ctrl.autostart_action.isEnabled()
    assert ctrl.window.mood == "happy"
    fake.enabled = True  # changed outside the app (e.g. Task Manager); the menu re-reads on open
    ctrl.tray.contextMenu().aboutToShow.emit()
    assert ctrl.autostart_action.isChecked()


def test_foreign_shortcut_shows_as_blocked_not_checked(app, tmp_path, monkeypatch):
    ctrl, _quits = autostart_controller(app, tmp_path, monkeypatch, FakeAutostart(state="foreign"))
    action = ctrl.autostart_action
    assert not action.isChecked() and not action.isEnabled() and "其他程序" in action.text()


def test_autostart_failure_is_reported_and_state_stays_true(app, tmp_path, monkeypatch):
    ctrl, _quits = autostart_controller(app, tmp_path, monkeypatch, FakeAutostart(enabled=False, fail=True))
    ctrl.set_autostart(True)
    assert not ctrl.autostart_action.isChecked() and ctrl.window.mood == "sad" and "没设置成功" in ctrl.window.full_text


def test_quit_waits_for_a_running_autostart_change(app, tmp_path, monkeypatch):
    gate = threading.Event()
    fake = FakeAutostart(enabled=True, gate=gate)
    ctrl, quits = autostart_controller(app, tmp_path, monkeypatch, fake)
    monkeypatch.setattr(controller_module.PetController, "_spawn_autostart", staticmethod(lambda fn: threading.Thread(target=fn).start()))
    ctrl.set_autostart(False)  # disable() now blocks until the gate opens
    ctrl.request_quit()
    assert quits == [] and ctrl.quit_pending
    gate.set()
    deadline = time.monotonic() + 5
    while not quits and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert quits == [1] and fake.calls == ["disable"] and not fake.enabled


def test_quit_is_immediate_when_idle(app, tmp_path, monkeypatch):
    ctrl, quits = autostart_controller(app, tmp_path, monkeypatch, FakeAutostart())
    ctrl.request_quit()
    assert quits == [1]


def test_without_autostart_support_the_item_is_disabled(app, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json")
    assert not ctrl.autostart_action.isEnabled()
    ctrl.set_autostart(True)  # ignored


class SlowReadAutostart(FakeAutostart):
    """The first state() read sees the old value, then stalls until released."""

    def __init__(self, gate):
        super().__init__(enabled=True)
        self.read_gate, self.reads = gate, 0

    def state(self):
        self.reads += 1
        value = super().state()
        if self.reads == 2:  # the read started by opening the menu
            self.read_gate.wait(10)
        return value


def pump(app, until, seconds=5):
    deadline = time.monotonic() + seconds
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def test_stale_state_read_cannot_recheck_a_removed_autostart(app, tmp_path, monkeypatch):
    gate = threading.Event()
    fake = SlowReadAutostart(gate)
    ctrl, _quits = autostart_controller(app, tmp_path, monkeypatch, fake)  # first read: sync, "on"
    assert ctrl.autostart_action.isChecked()
    threads = []

    def spawn(fn):
        thread = threading.Thread(target=fn)
        threads.append(thread)
        thread.start()

    monkeypatch.setattr(controller_module.PetController, "_spawn_autostart", staticmethod(spawn))
    ctrl.tray.contextMenu().aboutToShow.emit()  # read #2 captures "on" and stalls
    pump(app, lambda: fake.reads >= 2)
    ctrl.set_autostart(False)  # the change overtakes the stalled read
    pump(app, lambda: not ctrl.autostart_busy and fake.reads >= 3 and not ctrl.autostart_reading)
    gate.set()  # now the stale "on" arrives
    for thread in threads:
        thread.join(10)
    pump(app, lambda: False, seconds=0.5)
    assert fake.calls == ["disable"] and not fake.enabled
    assert not ctrl.autostart_action.isChecked()


def test_waiting_to_quit_stops_observing(app, tmp_path, monkeypatch):
    gate = threading.Event()
    fake = FakeAutostart(enabled=True, gate=gate)
    ctrl, quits = autostart_controller(app, tmp_path, monkeypatch, fake)
    ctrl.timer.start(60_000)
    ctrl.focus_tracker.start()
    assert ctrl.timer.isActive() and ctrl.focus_tracker.isActive()
    call = FakeCall()
    ctrl.current_call, ctrl.busy = call, True
    monkeypatch.setattr(controller_module.PetController, "_spawn_autostart", staticmethod(lambda fn: threading.Thread(target=fn).start()))
    ctrl.set_autostart(False)
    ctrl.request_quit()
    assert call.cancelled and not ctrl.timer.isActive() and not ctrl.focus_tracker.isActive()
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured while quitting"))
    ctrl._spawn = lambda fn: fn()
    ctrl.tick(force=True)
    ctrl.poke()
    gate.set()
    pump(app, lambda: bool(quits))
    assert quits == [1]


def test_failure_reason_is_shown_under_her_until_the_next_success(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    error = "no result in CLI output; API Error: 529 overloaded\nsecond line"
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(False, error=error)))
    assert ctrl.window.mood == "panic"
    assert ctrl.window.status == "原因：no result in CLI output; API Error: 529 overloaded"
    ctrl.window.grab()  # the two-line status text paints
    ctrl.busy = True
    ctrl._refresh_status()
    assert ctrl.window.status == "思考中…"  # busy/paused take priority over the reason
    ctrl.busy = False
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|好啦")))
    assert ctrl.window.status == ""


def test_failure_reasons_are_short_and_specific():
    summary = controller_module.error_summary
    assert summary(claude_client.ClaudeResult(False, error="timeout", timed_out=True), 120) == "超时（120 秒内没有回复）"
    assert summary(claude_client.ClaudeResult(False, error="not logged in", not_subscription=True), 120).startswith("不是订阅登录")
    long = summary(claude_client.ClaudeResult(False, error="x" * 500), 120)
    assert len(long) == controller_module.ERROR_MAX and long.endswith("…")
    assert summary(claude_client.ClaudeResult(False, error=""), 120) == "未知错误"


def test_worker_exception_reason_reaches_the_status(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    fake_window(monkeypatch, WindowInfo(1, "main.py", "Code.exe", 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module, "take_snapshot", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    ctrl.tick(force=True)
    assert ctrl.window.status == "原因：internal: RuntimeError: boom" and ctrl.window.mood == "panic"


def test_watchdog_reason_is_shown(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    ctrl.current_call, ctrl.busy = FakeCall(), True
    ctrl._watchdog(ctrl.generation)
    assert ctrl.window.status == "原因：任务卡住，已放弃"


def test_open_log_folder_menu_item(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    opened = []
    ctrl._open_path = opened.append
    labels = [action.text() for action in ctrl.tray.contextMenu().actions()]
    assert "打开日志文件夹" in labels
    next(a for a in ctrl.tray.contextMenu().actions() if a.text() == "打开日志文件夹").trigger()
    assert opened == [str(tmp_path)]
    ctrl._open_path = lambda _p: (_ for _ in ()).throw(OSError("denied"))
    ctrl.open_log_folder()
    assert "打不开日志文件夹" in ctrl.window.full_text


def test_long_reasons_fit_in_two_lines_and_keep_their_start(app):
    from PySide6.QtGui import QFontMetrics

    from claude_pet.pet_window import STATUS_MARGIN, fit_lines

    window = PetWindow(SPRITES, 220)
    metrics = QFontMetrics(window.status_font)
    width = window.width() - 2 * STATUS_MARGIN
    cases = {
        "chinese": "原因：" + "订阅额度已经用完请稍后再试" * 6,  # about 80 CJK characters, no spaces
        "path": r"原因：C:\Users\someone\AppData\Roaming\Claude\claude-code\2.1.295\d2e29494ec83\claude.exe_missing",
        "words": "原因：cannot start claude: [WinError 2] The system cannot find the file specified at all today",
    }
    def squash(text):
        return text.replace(" ", "").replace("…", "")

    for name, text in cases.items():
        lines = fit_lines(text, metrics, width)
        assert 1 <= len(lines) <= 2, name
        assert all(metrics.horizontalAdvance(line) <= width for line in lines), name
        assert lines[0].startswith("原因："), name
        complete = squash("".join(lines)) == squash(text)
        assert complete != lines[-1].endswith("…"), name  # ellipsis exactly when something was cut
        window.set_status(text)
        assert window.status_lines() == lines
        window.grab()  # paints with the same layout

    # Built from the real font metrics, so they hold at any DPI or font substitution.
    two_lines = "原因：cannot start claude"
    while metrics.horizontalAdvance(two_lines) < width * 1.3:
        two_lines += " retry"
    lines = fit_lines(two_lines, metrics, width)
    assert len(lines) == 2 and not lines[-1].endswith("…") and squash("".join(lines)) == squash(two_lines)
    overflow = "原因：" + "额度不足" * 200
    lines = fit_lines(overflow, metrics, width)
    assert len(lines) == 2 and lines[-1].endswith("…") and lines[0].startswith("原因：额度不足")
    assert fit_lines("原因：短", metrics, width) == ["原因：短"]
    assert fit_lines("", metrics, width) == []


# ---- calm observer: dwell gate, failure breaker, full-screen quiet, input-idle sleep --------
def clocked(ctrl, start=1000.0):
    now = [start]
    ctrl._clock = lambda: now[0]
    ctrl.target_since = start
    return now


def white_window(monkeypatch, title="main.py - VS Code", process="Code.exe", hwnd=1):
    from PIL import Image

    fake_window(monkeypatch, WindowInfo(hwnd, title, process, 4242, (0, 0, 800, 600)))
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: Image.new("RGB", (800, 600), "white"))


def test_dwell_gate_waits_for_the_same_window_but_pokes_do_not(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, dwell_sec=20)
    now = clocked(ctrl)
    white_window(monkeypatch)
    ctrl.last_external_hwnd = 0  # a new window arrives now
    ctrl.tick()
    assert calls == []  # just switched to it
    now[0] += 10
    ctrl.tick()
    assert calls == []
    ctrl.poke()
    assert len(calls) == 1  # pokes are never gated
    now[0] += 11
    ctrl.last_fingerprint = None
    ctrl.tick()
    assert len(calls) == 2  # 21 s on the same window


def test_failure_breaker_pauses_automatic_looks_until_success_or_timeout(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, failure_limit=3, failure_pause_min=30)
    now = clocked(ctrl)
    white_window(monkeypatch)
    fail = claude_client.ClaudeResult(False, error="API Error: 529 overloaded")
    for _ in range(3):
        ctrl._on_reply(Outcome(ctrl.generation, "reply", result=fail))
    assert ctrl.consecutive_failures == 3 and ctrl.auto_paused_until == now[0] + 1800
    assert "连续失败 3 次" in ctrl.window.status and "529" in ctrl.window.status
    ctrl.tick()
    assert calls == []  # automatic looks are paused
    ctrl.poke()
    assert len(calls) == 1  # but she still answers a poke
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|好了")))
    assert ctrl.consecutive_failures == 0 and ctrl.auto_paused_until == 0.0  # and a success lifts the pause
    for _ in range(3):
        ctrl._on_reply(Outcome(ctrl.generation, "reply", result=fail))
    now[0] += 1801
    ctrl._heartbeat()
    assert ctrl.auto_paused_until == 0.0 and ctrl.consecutive_failures == 0  # the pause also expires
    cancelled = claude_client.ClaudeResult(False, error="cancelled", cancelled=True)
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=cancelled))
    assert ctrl.consecutive_failures == 0  # cancellations are not failures


def test_full_screen_means_no_look_and_replies_wait(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    machine = calm_machine(monkeypatch, fullscreen=True)
    white_window(monkeypatch)
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured a full-screen app"))
    ctrl.tick()
    assert calls == [] and ctrl.quiet and "全屏" in ctrl.window.status
    ctrl.window.clear_bubble()
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|攒着的话")))
    assert ctrl.window.full_text == "" and "攒了一句" in ctrl.window.status  # held back
    machine["fullscreen"] = False
    ctrl._heartbeat()
    assert not ctrl.quiet and ctrl.window.full_text == "攒着的话" and ctrl.deferred is None
    machine["busy"] = True  # Windows itself reports a presentation or D3D full screen
    ctrl._heartbeat()
    assert ctrl.quiet
    poked = claude_client.ClaudeResult(True, "talk|你戳我啦")
    ctrl._on_reply(Outcome(ctrl.generation, "reply", force=True, result=poked))
    assert ctrl.window.full_text == "你戳我啦"  # an answer to a poke is shown right away


def test_quiet_mode_can_be_switched_off(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, quiet_fullscreen=False)
    calm_machine(monkeypatch, fullscreen=True, busy=True)
    white_window(monkeypatch)
    ctrl.tick()
    assert len(calls) == 1 and not ctrl.quiet


def test_sleeps_on_real_input_idle_and_wakes_on_input(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch, sleep_after_sec=600)
    machine = calm_machine(monkeypatch, idle=599)
    white_window(monkeypatch)
    ctrl._heartbeat()
    assert not ctrl.asleep
    machine["idle"] = 601  # a video may keep playing, but nobody touched the PC for 10 minutes
    ctrl._heartbeat()
    assert ctrl.asleep and ctrl.window.mood == "sleep" and "睡着" in ctrl.window.status
    ctrl.tick()
    assert calls == []  # asleep: no screenshots, no quota
    machine["idle"] = 1
    ctrl._heartbeat()
    assert not ctrl.asleep and ctrl.window.mood in ("happy", "talk")  # greeted on waking
    machine["idle"] = 700
    ctrl._heartbeat()
    assert ctrl.asleep
    ctrl.poke()  # a poke wakes her and still looks
    assert not ctrl.asleep and len(calls) == 1


def test_unknown_idle_never_puts_her_to_sleep(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: None)
    ctrl._heartbeat()
    assert not ctrl.asleep



def test_going_full_screen_after_the_job_started_stops_capture(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    machine = calm_machine(monkeypatch)
    white_window(monkeypatch)
    pending = []
    ctrl._spawn = pending.append
    ctrl.tick()  # the gate passed: not full screen yet
    machine["fullscreen"] = True  # the user starts a full-screen video before the worker runs
    monkeypatch.setattr(controller_module.capture, "capture_window", lambda _i: pytest.fail("captured after going full screen"))
    pending[0]()
    assert calls == [] and not ctrl.busy and ctrl.consecutive_failures == 0


def test_going_full_screen_during_the_subscription_check_skips_the_model_call(app, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    machine = calm_machine(monkeypatch)
    ctrl = controller_module.PetController(app, Config(), SPRITES, tmp_path / "config.json")

    class Call:
        cancelled = False

        def check_subscription(self, _exe):
            machine["fullscreen"] = True  # full screen starts while auth status runs
            return True, ""

        def run(self, *_a):
            pytest.fail("called the model after going full screen")

    job = controller_module.Job(
        generation=ctrl.generation, force=False, user_message=None, may_capture=True, hwnd=1, blocklist=[],
        last_fingerprint=None, need_auth=True, claude="claude.exe", model="haiku", recent=[], call=Call(),
        quiet_check=lambda: machine["fullscreen"],
    )
    result, _auth = ctrl._ask_claude(job, controller_module.NOTHING)
    assert result.cancelled and not result.ok
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=result))
    assert ctrl.consecutive_failures == 0  # a quiet skip is not a failure


def test_held_back_reply_survives_sleeping_through_full_screen(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch, sleep_after_sec=600)
    machine = calm_machine(monkeypatch, fullscreen=True)
    ctrl._heartbeat()
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|攒着的话")))
    machine["idle"] = 700
    ctrl._heartbeat()
    assert ctrl.asleep and ctrl.deferred is not None
    machine["idle"], machine["fullscreen"] = 1, False  # mouse moves, full screen ends, same heartbeat
    ctrl._heartbeat()
    assert not ctrl.asleep and ctrl.window.full_text == "攒着的话"  # not replaced by a wake greeting


def test_pausing_drops_a_held_back_reply(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch)
    machine = calm_machine(monkeypatch, fullscreen=True)
    ctrl._heartbeat()
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|旧评论")))
    assert ctrl.deferred is not None
    ctrl.toggle_pause()
    machine["fullscreen"] = False
    ctrl._heartbeat()
    assert ctrl.deferred is None and "旧评论" not in ctrl.window.full_text



def test_full_screen_recheck_follows_the_current_foreground_window(app, tmp_path, monkeypatch):
    calm_machine(monkeypatch)
    a = WindowInfo(1, "notes", "Notepad.exe", 4242, (0, 0, 800, 600))
    b = WindowInfo(2, "game", "Game.exe", 4343, (0, 0, 1920, 1080))
    front = {"info": a}
    monkeypatch.setattr(controller_module.capture, "foreground_window", lambda: front["info"])
    monkeypatch.setattr(controller_module.capture, "window_info", lambda hwnd: a if hwnd == 1 else b)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda info: info is not None and info.hwnd == 2)
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    assert controller_module.full_screen_now(1) is False
    front["info"] = b  # the user switched to a full-screen game after the job (bound to A) started
    assert controller_module.full_screen_now(1) is True
    import os
    front["info"] = WindowInfo(9, "Claude Pet", "python.exe", os.getpid(), (0, 0, 300, 400))
    assert controller_module.full_screen_now(2) is True  # the pet itself in front: fall back to the watched window


def test_held_back_reply_waits_while_she_still_sleeps(app, tmp_path, monkeypatch):
    ctrl, _calls = make_controller(app, tmp_path, monkeypatch, sleep_after_sec=600)
    machine = calm_machine(monkeypatch, fullscreen=True)
    ctrl._heartbeat()
    ctrl._on_reply(Outcome(ctrl.generation, "reply", result=claude_client.ClaudeResult(True, "happy|攒着的话")))
    machine["idle"] = 700
    ctrl._heartbeat()
    assert ctrl.asleep
    machine["fullscreen"] = False  # the video ends by itself; nobody touches the PC
    ctrl._heartbeat()
    assert ctrl.asleep and ctrl.deferred is not None and "攒着的话" not in ctrl.window.full_text
    machine["idle"] = 1  # now the user is back
    ctrl._heartbeat()
    assert not ctrl.asleep and ctrl.window.full_text == "攒着的话" and ctrl.deferred is None


def test_a_quiet_skip_does_not_mark_the_screen_as_seen(app, tmp_path, monkeypatch):
    ctrl, calls = make_controller(app, tmp_path, monkeypatch)
    white_window(monkeypatch)
    skipped = (claude_client.ClaudeResult(False, error="quiet", cancelled=True), None)
    real_ask = ctrl._ask_claude
    monkeypatch.setattr(ctrl, "_ask_claude", lambda job, snapshot: skipped)
    ctrl.tick()  # captured, but went full screen before the model call
    assert ctrl.last_fingerprint is None and ctrl.consecutive_failures == 0 and not ctrl.busy
    monkeypatch.setattr(ctrl, "_ask_claude", real_ask)
    ctrl.tick()  # same, unchanged screen after full screen ended: still gets its comment
    assert len(calls) == 1
