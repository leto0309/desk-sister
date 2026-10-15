"""Glue: timer -> capture -> privacy/change checks -> background Claude call -> pet window."""
from __future__ import annotations

import logging
import os
import random
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon

from . import agent_link, api_client, capture, claude_client, credstore, persona
from .autostart import FOREIGN as AUTOSTART_FOREIGN
from .autostart import ON as AUTOSTART_ON
from .autostart import Autostart, AutostartError
from .memory import CompanionMemory, classify_activity
from .config import INTERVAL_CHOICES, MODEL_CHOICES, Config, app_data_dir, save_config
from .pet_window import PetWindow

log = logging.getLogger("claude_pet")

CHANGE_THRESHOLD = 0.02
HOTKEY_ID = 0xC1A0
AUTH_CHECK_TTL = 1800
AUTOSTART_LABEL = "开机自启"
MEMORY_TALK_CHANCE = 0.25  # share of self-talk turns that mention today's main activity (if >= 1 h)
MEMORY_FLUSH_SEC = 60
SELF_TALK_GAP_SEC = 60  # never talk to herself within a minute of saying anything
WAKE_IDLE_SEC = 5
NOTICE_AWAKE_SEC = 120  # after a Claude Code notice wakes her, she stays awake this long  # input within this many seconds wakes her
ERROR_MAX = 80  # characters of an error reason shown under the pet
AUTOSTART_QUIT_GRACE_MS = 30_000  # longest wait for a running autostart change when quitting
INTERVAL_LABELS = {30: "30 秒", 60: "1 分钟", 90: "90 秒", 120: "2 分钟", 300: "5 分钟", 600: "10 分钟"}


@dataclass
class Snapshot:
    window: capture.WindowInfo | None
    jpeg: bytes | None
    fingerprint: object | None


@dataclass
class Job:
    """Everything the worker needs, copied on the UI thread so the worker never reads live state."""
    generation: int
    force: bool
    user_message: str | None
    may_capture: bool
    hwnd: int
    blocklist: list[str]
    last_fingerprint: object | None
    need_auth: bool
    claude: str
    model: str
    recent: list[str]
    call: claude_client.ClaudeCall
    # Automatic jobs re-check "full screen?" right before capturing and before calling the model,
    # because the user may go full screen after the job was started. None for pokes / chat.
    quiet_check: object | None = None
    allowlist: list[str] | None = None  # None: blocklist mode
    memory_context: str = ""
    backend: str = "subscription"  # or "api": call is then an api_client.ApiCall


@dataclass
class Outcome:
    generation: int
    kind: str  # cancelled | quiet | blocked | no_window | unchanged | reply
    force: bool = False
    detail: str = ""  # for "blocked": blocked | not_allowed | unknown
    fingerprint: object | None = None
    result: claude_client.ClaudeResult | None = None
    auth_ok: bool | None = None
    window: capture.WindowInfo | None = None  # the window that was actually looked at


def error_summary(result: claude_client.ClaudeResult, timeout_sec: int) -> str:
    """One short line for the status text under the pet."""
    if result.timed_out:
        return f"超时（{timeout_sec} 秒内没有回复）"
    if result.not_subscription:
        return f"不是订阅登录：{result.error}"[:ERROR_MAX]
    if result.no_api_key:
        return "还没有设置 API Key（右键「调用方式」）"
    lines = [line.strip() for line in (result.error or "").splitlines() if line.strip()]
    text = lines[0] if lines else "未知错误"
    return text if len(text) <= ERROR_MAX else text[: ERROR_MAX - 1] + "…"


def full_screen_now(fallback_hwnd: int = 0) -> bool:
    """Is a full-screen app / presentation in front right now? Safe to call from the worker thread.

    Reads the current foreground window (the user may have switched since the job started);
    only when that is the pet itself (or unknown) does it fall back to the last watched window.
    """
    try:
        info = capture.foreground_window()
        if info is None or info.pid == os.getpid():
            info = capture.window_info(fallback_hwnd) if fallback_hwnd else None
        return capture.notification_busy() or capture.is_fullscreen(info)
    except OSError:
        return False


def refusal(info: capture.WindowInfo, blocklist: list[str], allowlist: list[str] | None = None) -> str | None:
    """Why this window must not be captured (unknown | not_allowed | blocked), or None when it may."""
    # An unidentified process cannot be checked against the lists, so it is never captured.
    if not info.process_name:
        log.info("window of unidentified process skipped")
        return "unknown"
    if allowlist is not None and not capture.matches_allowlist(allowlist, info.process_name, info.title):
        log.info("window not in the allowlist skipped")
        return "not_allowed"
    if capture.is_blocked(info.title, info.process_name, blocklist):  # applies in both modes
        log.info("blocked window skipped")
        return "blocked"
    return None


def allowed(info: capture.WindowInfo, blocklist: list[str], allowlist: list[str] | None = None) -> bool:
    return refusal(info, blocklist, allowlist) is None


NOTHING = Snapshot(None, None, None)
# At most one capture may be in flight. PrintWindow on a hung window can block forever; when the
# watchdog gives up on such a job, later jobs skip capturing instead of piling up threads and GDI objects.
_capture_slot = threading.Semaphore(1)


def take_snapshot(hwnd: int, blocklist: list[str], stopped=lambda: False,
                  allowlist: list[str] | None = None) -> tuple[Snapshot, str | None]:
    """Return the window shot and None, or a refusal reason when privacy rules forbid looking.
    May block: worker only.

    `stopped` is polled before each step, so a pause that arrives first means no screenshot is taken.
    """
    if stopped():
        return NOTHING, None
    if not _capture_slot.acquire(blocking=False):
        log.warning("previous capture still stuck; skipping this one")
        return NOTHING, None
    try:
        return _take_snapshot(hwnd, blocklist, stopped, allowlist)
    finally:
        _capture_slot.release()


def _take_snapshot(hwnd: int, blocklist: list[str], stopped, allowlist: list[str] | None) -> tuple[Snapshot, str | None]:
    try:
        info = capture.window_info(hwnd)
    except OSError:
        log.exception("window lookup failed")
        info = None
    if info is None or info.minimized or info.pid == os.getpid():
        return Snapshot(info, None, None), None
    reason = refusal(info, blocklist, allowlist)
    if reason:
        return Snapshot(info, None, None), reason
    if stopped():
        return NOTHING, None
    try:
        image = capture.capture_window(info)
    except OSError:
        log.exception("capture failed")
        image = None
    if image is None or stopped():
        return Snapshot(info, None, None), None
    # Re-check after capturing: the title (e.g. a browser tab) may have changed meanwhile.
    try:
        after = capture.window_info(info.hwnd)
    except OSError:
        after = None
    if after is None or after.pid != info.pid:
        return Snapshot(info, None, None), "unknown"
    reason = refusal(after, blocklist, allowlist)
    if reason:
        return Snapshot(info, None, None), reason
    return Snapshot(after, capture.to_jpeg(image), capture.fingerprint(image)), None


class PetController(QObject):
    reply_ready = Signal(object)
    thinking = Signal(int)
    autostart_done = Signal(bool, str)
    autostart_state = Signal(int, str)

    def __init__(self, app: QApplication, config: Config, sprite_folder: Path, config_file: Path | None = None,
                 autostart: Autostart | None = None, memory: CompanionMemory | None = None) -> None:
        super().__init__()
        self.app = app
        self.config = config
        self.config_file = config_file
        self.window = PetWindow(sprite_folder, config.sprite_height)
        self.recent: deque[str] = deque(maxlen=6)
        self.busy = False
        self.asleep = False
        self.last_fingerprint = None
        self._clock = time.monotonic
        # Calm-observer state (ideas from dsh-pet-indesktop's proactive watcher):
        self.target_since = self._clock()   # when the watched window last changed (dwell gate)
        self.consecutive_failures = 0       # failure breaker
        self.auto_paused_until = 0.0
        self.quiet = False                  # a full-screen app / presentation is in front
        self.deferred: persona.Reply | None = None  # a reply that arrived while quiet
        self.last_gate: str | None = None
        # Local self-talk: no Claude call, so no quota and no screenshot.
        self._rng = random.Random()
        self._hour = lambda: time.localtime().tm_hour
        self.self_talk_recent: deque[str] = deque(maxlen=8)
        self.self_talk_timer = QTimer(self, singleShot=True, timeout=self._self_talk_tick)
        # Companion memory: in-memory only unless the app hands in a file-backed one.
        self.memory = memory if memory is not None else CompanionMemory(None)
        # Claude Code link: hooks write event names to a local file; the pet only reads that file.
        self.claude_state = agent_link.ClaudeCodeState()
        self.claude_settings = agent_link.claude_settings_path()
        self.claude_tail: agent_link.EventTail | None = None
        self._confirm = self._ask_confirm
        self._ask_secret = self._ask_secret_dialog
        # The API key only ever moves between Windows Credential Manager and the request (test seams).
        self._load_key = credstore.load_secret
        self._save_key = credstore.save_secret
        self._delete_key = credstore.delete_secret
        # Claude Code notices wait apart from automatic replies: pausing the screen-watching never drops them.
        # Claude Code notices not shown yet, the newest per session ("" = unknown session).
        self.pending_notices: dict[str, agent_link.Notice] = {}
        self.notice_generation = -1  # automatic replies from requests up to this one are older than a notice
        self.awake_until = 0.0
        if config.claude_link:
            self._open_claude_tail()
        self._memory_tick_at = self._clock()
        self._memory_flush_at = self._clock()
        self.window.clock = lambda: self._clock()
        self.claude = claude_client.find_claude(config.claude_path)
        self.last_external_hwnd = 0
        # Each request gets a generation number; pausing or quitting bumps it so late replies are dropped.
        self.generation = 0
        self.current_call: claude_client.ClaudeCall | api_client.ApiCall | None = None
        self.auth_ok_until = 0.0

        self.reply_ready.connect(self._on_reply)
        self.thinking.connect(self._on_thinking)
        self.autostart = autostart
        self.autostart_busy = False
        self.autostart_reading = False
        # Bumped whenever a change starts: a state read that began earlier is stale and is ignored.
        self.autostart_version = 0
        self.quit_pending = False
        self._quit = app.quit
        self.last_error = ""
        self._open_path = getattr(os, "startfile", None) or (lambda _path: None)
        self.autostart_done.connect(self._on_autostart_done)
        self.autostart_state.connect(self._on_autostart_state)
        self.window.poked.connect(self.poke)
        self.window.context_menu_requested.connect(self._show_menu)
        self.window.moved.connect(self._remember_position)
        self.window.hotkey_pressed.connect(self.toggle_pause)

        self.timer = QTimer(self, timeout=self.tick)
        # Remembers the user's window, so menus or dialogs of the pet never become the thing it looks at.
        self.focus_tracker = QTimer(self, interval=1000, timeout=self._heartbeat)
        self.tray = QSystemTrayIcon(QIcon(self.window.sprites["idle"]), self)
        self.tray.setToolTip("Desk Sister")
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray)

    # ---- lifecycle ---------------------------------------------------
    def start(self) -> None:
        self._place_window()
        self.window.show()
        self.tray.show()
        self._register_hotkey()
        self.timer.start(self.config.interval_sec * 1000)
        self.focus_tracker.start()
        self._schedule_self_talk()
        self._refresh_status()
        if self.config.backend == "subscription" and not self.claude:
            self.window.say(*self._reply_tuple(persona.fallback("no_claude")))
        else:
            self.window.say("happy", "主人好～我是 Claude。我会安静待在这里，偶尔看看你在忙什么。")
            # First look once the dwell gate can pass, so she does not wait a whole interval.
            QTimer.singleShot(max(8, self.config.dwell_sec + 1) * 1000, self.tick)

    def shutdown(self) -> None:
        self._cancel_inflight()
        self.timer.stop()
        self.focus_tracker.stop()
        self.self_talk_timer.stop()
        self._flush_memory()
        self._unregister_hotkey()
        self.tray.hide()
        self._save()

    def _place_window(self) -> None:
        screen = self.app.primaryScreen().availableGeometry()
        x, y = self.config.x, self.config.y
        if x is None or y is None or not any(s.availableGeometry().contains(QPoint(x + 40, y + 40)) for s in self.app.screens()):
            x = screen.right() - self.window.width() - 20
            y = screen.bottom() - self.window.height()
        self.window.move(x, y)

    # ---- the loop ----------------------------------------------------
    # The UI thread only decides whether to start a job. Everything that can block (PrintWindow on a
    # hung window, `claude auth status`, the model call) runs on a worker thread and reports back via
    # a queued signal; a generation number lets pause/quit/watchdog discard anything that arrives late.
    def tick(self, force: bool = False, user_message: str | None = None) -> None:
        if self.busy or self.quit_pending:
            return
        if self.config.paused and not user_message:
            if force:
                self.window.say("sad", "我现在闭着眼睛呢，没在看哦～（Ctrl+Alt+P 恢复）")
            return
        if self.config.backend == "subscription" and not self.claude:
            self.claude = claude_client.find_claude(self.config.claude_path)
            if not self.claude:
                if force:
                    self.window.say(*self._reply_tuple(persona.fallback("no_claude")))
                return
        self._track_foreground()
        if force:
            self._wake(announce=False)
        else:
            self._update_quiet()
            gate = self._auto_gate()
            if gate != self.last_gate:  # logged on change only, so the log says why she is quiet
                log.info("automatic looks %s", f"skipped: {gate}" if gate else "allowed again")
                self.last_gate = gate
            if gate:
                self._refresh_status()
                return
        cwd = app_data_dir()
        cwd.mkdir(parents=True, exist_ok=True)
        self.generation += 1
        if self.config.backend == "api":
            call = api_client.ApiCall(self.config.timeout_sec, load_key=self._load_key)
        else:
            call = claude_client.ClaudeCall(self.config.timeout_sec, cwd=str(cwd))
        job = Job(
            generation=self.generation, force=force, user_message=user_message,
            may_capture=not self.config.paused, hwnd=self.last_external_hwnd,
            blocklist=list(self.config.blocklist), last_fingerprint=self.last_fingerprint,
            need_auth=time.monotonic() >= self.auth_ok_until, claude=self.claude, model=self.config.model,
            recent=list(self.recent), call=call,
            quiet_check=None if force or not self.config.quiet_fullscreen else partial(full_screen_now, self.last_external_hwnd),
            allowlist=self._allowlist(),
            memory_context=self._memory_context(),
            backend=self.config.backend,
        )
        self.current_call = call
        self.busy = True
        self._refresh_status()
        # Whatever happens on the worker (even a PrintWindow that never returns), the pet recovers.
        QTimer.singleShot((self.config.timeout_sec * 2 + 60) * 1000, partial(self._watchdog, job.generation, force))
        self._spawn(partial(self._work, job))

    def poke(self) -> None:
        if self.busy:
            self.window.say("think", "等一下下，我还在想上一句……")
            return
        self.tick(force=True)

    def chat(self) -> None:
        text, ok = QInputDialog.getText(None, "和 Claude 说话", "想对她说什么？")
        if ok and text.strip():
            if self.busy:
                self.window.say("think", "等一下下，我还在想上一句……")
                return
            self.tick(force=True, user_message=text.strip()[:300])

    @staticmethod
    def _spawn(fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _track_foreground(self) -> None:
        try:
            info = capture.foreground_window()
        except OSError:
            return
        if info is not None and info.pid != os.getpid():
            if info.hwnd != self.last_external_hwnd:
                self.target_since = self._clock()
            self.last_external_hwnd = info.hwnd

    def _auto_gate(self) -> str | None:
        """Why an automatic (timer) look must not happen now; None when it may. Pokes skip this."""
        now = self._clock()
        if self.asleep:
            return "asleep"
        if self.quiet:
            return "quiet (full screen)"
        if now < self.auto_paused_until:
            return "paused after repeated failures"
        if self.config.claude_link and self.claude_state.busy:
            return "Claude Code is working"
        if now - self.target_since < self.config.dwell_sec:
            return "dwell"
        return None

    # ---- heartbeat (1 s, UI thread, cheap Win32 queries only) ----------------
    def _heartbeat(self) -> None:
        self._track_foreground()
        self._update_quiet()
        self._update_sleep()
        self._update_claude_link()
        self._flush_deferred()
        self._update_memory()
        if self.auto_paused_until and self._clock() >= self.auto_paused_until:
            self.auto_paused_until = 0.0
            self.consecutive_failures = 0
            log.info("automatic looks resumed after the failure pause")
        self._refresh_status()

    # ---- Claude Code link ---------------------------------------------------
    @staticmethod
    def _claude_event_file() -> Path:
        """The file the hooks append to. It must be appendable, or every hook write fails (OSError)."""
        path = app_data_dir() / "agent-events" / "claude.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab"):
            pass
        return path

    def _open_claude_tail(self) -> None:
        try:
            path = self._claude_event_file()
        except OSError:
            log.exception("could not create the Claude Code event folder")
            path = app_data_dir() / "agent-events" / "claude.log"  # reading a missing file is harmless
        self.claude_tail = agent_link.EventTail(path)

    def _update_claude_link(self) -> None:
        if not self.config.claude_link or self.claude_tail is None:
            return
        now = self._clock()
        for label, session in self.claude_tail.read_new():
            if session and label not in ("permission", "waiting"):  # (those replace or repeat the notice)
                # The session moved on (a new turn, a tool, its end): its unshown news is old. Not only
                # "prompt": that one may arrive late and be dropped as out of order.
                self.pending_notices.pop(session, None)
            for notice in self.claude_state.feed(label, now, session):
                self.pending_notices.pop(session, None)
                self.pending_notices[session] = notice  # newest last
        self.claude_state.tick(now)
        if not self.quiet:  # held back while something is full screen
            self._show_pending_notice()

    @property
    def deferred_notice(self) -> persona.Reply | None:
        """The notice that would be shown now: judged on the sessions' state after every event read so
        far, so a "waiting for you" that was already answered is never shown. Asking for approval
        comes first, then waiting for a reply, an error, a finished task; the newest wins a tie."""
        rank = {"permission": 0, "waiting": 1, "error": 2, "done": 3}
        best = None
        for session, notice in reversed(self.pending_notices.items()):
            if not self.claude_state.still_relevant(notice.kind, session):
                continue
            if best is None or rank.get(notice.kind, 9) < rank.get(best.kind, 9):
                best = notice
        return persona.Reply(best.mood, best.text) if best else None

    def _show_pending_notice(self) -> bool:
        """A local notice (no Claude call) wakes her. One bubble at a time: the most important one."""
        reply = self.deferred_notice
        self.pending_notices.clear()
        if reply is None:
            return False
        self._say_notice(reply)
        return True

    def _say_notice(self, reply: persona.Reply) -> None:
        # Anything older than this notice must not cover it: a held automatic comment, an older held
        # notice, or an automatic look already running (its generation is <= the current one).
        self.deferred = None
        self.pending_notices.clear()
        self.notice_generation = self.generation
        self._wake(announce=False)
        self.awake_until = self._clock() + NOTICE_AWAKE_SEC  # do not doze off over the notice
        self.window.say(reply.mood, reply.text)

    @staticmethod
    def _ask_confirm(title: str, text: str) -> bool:
        answer = QMessageBox.question(None, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _refresh_claude_link_action(self) -> None:
        # Checked = the pet is listening, so it can always be switched off from here.
        self.claude_link_action.setChecked(self.config.claude_link)
        broken = self.config.claude_link and not agent_link.is_installed(self.claude_settings)
        self.claude_link_action.setText("Claude Code 联动" + ("（hook 未找到或 settings.json 异常）" if broken else ""))

    def set_claude_link(self, enabled: bool) -> None:
        if enabled:
            text = (f"要开启 Claude Code 联动吗？\n\n这会修改 {self.claude_settings}：添加几条 hook。"
                    "如果文件已存在，会先备份为 settings.json.claude-pet-backup-<时间戳>（保留最近 5 份）。\n\n"
                    "hook 只从 Claude Code 的事件数据里取出会话编号，往本地文件写“事件名 + 会话编号 + 时间”"
                    "（例如“在改文件”“等你批准”）；你的提示词、代码和命令内容不会被保存。"
                    "\n\n关闭联动时，只移除这些 hook。")
            if not self._confirm("Claude Code 联动", text):
                self.claude_link_action.setChecked(False)
                return
            try:
                self._claude_event_file()  # first, so a failure leaves settings.json untouched
            except OSError as exc:
                log.warning("could not prepare the Claude Code event file: %s", exc)
                self.claude_link_action.setChecked(False)
                self.window.say("sad", f"没能开启联动：事件文件写不进去（{exc}）")
                return
            try:
                backup = agent_link.install_hooks(self.claude_settings)
            except (agent_link.HooksError, OSError) as exc:
                log.warning("could not install Claude Code hooks: %s", exc)
                self.claude_link_action.setChecked(False)
                self.window.say("sad", f"没能开启联动：{exc}")
                return
            self.config.claude_link = True
            self._open_claude_tail()
            self._save()
            self.claude_link_action.setChecked(True)
            saved = f"原来的设置备份在 {backup.name}。" if backup else ""
            self.window.say("happy", f"联动开启啦！Claude Code 妹妹在忙什么我都会知道～{saved}（已经开着的会话可能要重开才生效）")
            return
        self.config.claude_link = False
        self.claude_tail = None
        self.claude_state = agent_link.ClaudeCodeState()
        self.pending_notices.clear()
        self.awake_until = 0.0
        self._save()
        self.claude_link_action.setChecked(False)
        try:
            agent_link.uninstall_hooks(self.claude_settings)
        except (agent_link.HooksError, OSError) as exc:
            log.warning("could not remove Claude Code hooks: %s", exc)
            self.window.say("sad", f"我不再看联动了，但没能从 settings.json 移除 hook：{exc}")
            return
        self.window.say("happy", "好的，联动关掉了，hook 也移除了。")
        self._refresh_status()

    # ---- companion memory ---------------------------------------------------
    def _allowlist(self) -> list[str] | None:
        return list(self.config.allowlist) if self.config.watch_mode == "allowlist" else None

    def _watchable_window(self) -> capture.WindowInfo | None:
        """The window in front, if privacy rules allow looking at it (refused windows are never recorded)."""
        try:
            info = capture.window_info(self.last_external_hwnd) if self.last_external_hwnd else None
        except OSError:
            return None
        if info is None or info.minimized or refusal(info, self.config.blocklist, self._allowlist()):
            return None
        return info

    def _memory_context(self) -> str:
        if not self.config.companion_memory:
            return ""
        info = self._watchable_window()
        return self.memory.context(classify_activity(info.process_name, info.title) if info else None)

    def _update_memory(self) -> None:
        now = self._clock()
        elapsed = min(5.0, max(0.0, now - self._memory_tick_at))  # timers may lag; never count a big jump
        self._memory_tick_at = now
        if self.config.companion_memory and not self.asleep:
            info = self._watchable_window()
            if info is not None:
                self.memory.add_time(classify_activity(info.process_name, info.title), elapsed)
        if now - self._memory_flush_at >= MEMORY_FLUSH_SEC:
            self._memory_flush_at = now
            self._flush_memory()

    def _flush_memory(self) -> None:
        try:
            self.memory.flush()
        except OSError:
            log.exception("could not save companion memory")

    def set_companion_memory(self, enabled: bool) -> None:
        if not enabled:
            self._cancel_inflight()  # a request carrying the memory summary must not go out after this
        self.config.companion_memory = bool(enabled)
        self.memory_action.setChecked(self.config.companion_memory)
        self._save()

    def clear_companion_memory(self) -> None:
        # Cancel first: an in-flight request still holds the old summary, and its reply would record again.
        self._cancel_inflight()
        try:
            self.memory.clear()
        except OSError as exc:
            log.exception("could not clear companion memory")
            self.window.say("sad", f"记忆在我这儿清空了，但 memory.json 没能改写（{exc}），我稍后会再试。")
            return
        self.window.say("happy", "好的，陪伴记忆都清空啦……（翻到新的一页）")

    def _update_quiet(self) -> None:
        if not self.config.quiet_fullscreen:
            quiet = False
        else:
            quiet = full_screen_now(self.last_external_hwnd)
        if quiet == self.quiet:
            return
        self.quiet = quiet
        log.info("quiet mode %s", "on (full screen)" if quiet else "off")

    def _flush_deferred(self) -> None:
        """Say held-back lines once nothing is full screen. Claude Code notices go first and wake her;
        an automatic reply waits while she sleeps and is dropped if watching was paused."""
        if self.pending_notices and not self.quiet and self._show_pending_notice():
            return  # (a held notice that was answered meanwhile is simply dropped)
        if self.deferred is None or self.quiet or self.asleep:
            return
        reply, self.deferred = self.deferred, None
        if self.config.paused or self.quit_pending:
            return
        self.window.say(*self._reply_tuple(reply))

    def _update_sleep(self) -> None:
        try:
            idle = capture.idle_seconds()
        except OSError:
            idle = None
        if idle is None:
            return
        if not self.asleep and not self.busy and idle >= self.config.sleep_after_sec and self._clock() >= self.awake_until:
            self.asleep = True
            reply = persona.pick(persona.SLEEP_LINES)
            if self.quiet:
                self.window.set_mood(reply.mood)
            else:
                self.window.say(reply.mood, reply.text)
        elif self.asleep and idle < WAKE_IDLE_SEC:
            # A held-back reply doubles as the greeting (said by _flush_deferred right after).
            self._wake(announce=not self.quiet and self.deferred is None)

    def _wake(self, announce: bool) -> None:
        if not self.asleep:
            return
        self.asleep = False
        self.target_since = self._clock()  # fresh dwell after coming back
        if announce:
            self.window.say(*self._reply_tuple(persona.pick(persona.WAKE_LINES)))
        else:
            self.window.set_mood("idle")

    # ---- worker thread ---------------------------------------------------
    def _work(self, job: Job) -> None:
        try:
            outcome = self._evaluate(job)
        except Exception as exc:  # never leave the pet busy because of an unexpected error
            log.exception("worker failed")
            error = f"internal: {type(exc).__name__}: {exc}"
            outcome = Outcome(job.generation, "reply", force=job.force, result=claude_client.ClaudeResult(False, error=error))
        self.reply_ready.emit(outcome)

    def _evaluate(self, job: Job) -> Outcome:
        if job.call.cancelled:  # paused or quit before this worker even started
            return Outcome(job.generation, "cancelled")
        if job.quiet_check is not None and job.quiet_check():
            return Outcome(job.generation, "quiet")
        if job.may_capture:
            snapshot, reason = take_snapshot(job.hwnd, job.blocklist, lambda: job.call.cancelled, job.allowlist)
        else:
            snapshot, reason = NOTHING, None
        if job.call.cancelled:
            return Outcome(job.generation, "cancelled")
        if reason:
            if not job.user_message:
                return Outcome(job.generation, "blocked", force=job.force, detail=reason)
            snapshot = NOTHING  # answer what the user said, without looking at that window
        if snapshot.jpeg is None and not job.user_message:
            return Outcome(job.generation, "no_window", force=job.force)
        if not job.force and snapshot.fingerprint is not None:
            if capture.change_ratio(job.last_fingerprint, snapshot.fingerprint) < CHANGE_THRESHOLD:
                return Outcome(job.generation, "unchanged")
        result, auth_ok = self._ask_claude(job, snapshot)
        if result.cancelled and result.error == "quiet":
            return Outcome(job.generation, "quiet")
        return Outcome(job.generation, "reply", force=job.force, fingerprint=snapshot.fingerprint, result=result,
                       auth_ok=auth_ok, window=snapshot.window if snapshot.jpeg is not None else None)

    def _ask_claude(self, job: Job, snapshot: Snapshot) -> tuple[claude_client.ClaudeResult, bool | None]:
        self.thinking.emit(job.generation)
        started = time.monotonic()
        auth_ok = None
        if job.backend == "subscription" and job.need_auth:
            # Nothing is sent unless the CLI would use a claude.ai subscription login.
            auth_ok, reason = job.call.check_subscription(job.claude)
            if job.call.cancelled:
                return claude_client.ClaudeResult(False, error="cancelled", cancelled=True), None
            if reason == claude_client.LAUNCH_PENDING:
                log.warning("subscription check skipped: %s", reason)
                return claude_client.ClaudeResult(False, error=reason), None
            if not auth_ok:
                log.warning("subscription check failed: %s", reason)
                return claude_client.ClaudeResult(False, error=reason, not_subscription=True), False
        if job.quiet_check is not None and job.quiet_check():
            # Went full screen while the subscription was checked: skip quietly, not a failure.
            return claude_client.ClaudeResult(False, error="quiet", cancelled=True), auth_ok
        window = snapshot.window
        text = persona.build_user_text(
            window.title if window else "", window.process_name if window else "", time.strftime("%H:%M"),
            job.recent, job.user_message, has_image=snapshot.jpeg is not None, memory=job.memory_context,
        )
        if job.backend == "api":
            result = job.call.ask(job.model, persona.SYSTEM_PROMPT, text, snapshot.jpeg)
        else:
            args = claude_client.build_args(job.claude, job.model, persona.SYSTEM_PROMPT)
            result = job.call.run(args, claude_client.build_message(text, snapshot.jpeg))
        source = "api" if job.backend == "api" else "claude"
        log.info("%s call ok=%s in %.1fs", source, result.ok, time.monotonic() - started)
        if not result.ok:
            log.warning("%s error: %s", source, result.error[:300])
        return result, auth_ok

    # ---- back on the UI thread -------------------------------------------
    def _on_thinking(self, generation: int) -> None:
        if generation == self.generation and self.busy:
            self.window.set_mood("think")
            self._refresh_status()

    def _watchdog(self, generation: int, force: bool = True) -> None:
        if generation == self.generation and self.busy:
            log.warning("request %d did not finish; abandoning it", generation)
            self.last_error = "任务卡住，已放弃"
            self._cancel_inflight()
            if not force and generation <= self.notice_generation:
                return  # an automatic look older than a Claude Code notice: never cover the notice
            self.window.say(*self._reply_tuple(persona.fallback("timeout")))

    def _cancel_inflight(self) -> None:
        self.deferred = None
        if self.current_call is not None:
            self.current_call.cancel()
            self.current_call = None
        self.generation += 1
        self.busy = False
        self._refresh_status()

    def _on_reply(self, outcome: Outcome) -> None:
        if outcome.generation != self.generation:
            return  # paused, quit or abandoned while this job was running
        self.current_call = None
        self.busy = False
        self._refresh_status()
        if outcome.kind in ("cancelled", "quiet"):
            return
        if outcome.kind == "blocked":
            if outcome.force:
                kind = "not_allowed" if outcome.detail == "not_allowed" else "blocked"
                self.window.say(*self._reply_tuple(persona.fallback(kind)))
            return
        if outcome.kind == "no_window":
            if outcome.force:
                self.window.say("think", "主人现在好像没有打开什么窗口呢……")
            return
        if outcome.kind == "unchanged":
            return
        result = outcome.result
        if result is not None and result.cancelled:
            return  # never shown, so its screenshot must not count as "already seen"
        if outcome.fingerprint is not None:
            self.last_fingerprint = outcome.fingerprint
        if outcome.auth_ok:
            self.auth_ok_until = time.monotonic() + AUTH_CHECK_TTL
        if result.cancelled:
            return
        if result.no_api_key:
            reply = persona.fallback("no_api_key")
        elif result.bad_api_key:
            reply = persona.fallback("bad_api_key")
        elif result.not_subscription:
            reply = persona.fallback("not_subscription")
        elif result.ok:
            parsed = persona.parse_reply(result.text)
            if parsed:
                self.recent.append(parsed.text)
            reply = parsed or persona.fallback("empty")
        else:
            reply = persona.fallback("timeout" if result.timed_out else "error")
        # Shown under her until the next successful reply, so a screenshot carries the cause.
        self.last_error = "" if result.ok else error_summary(result, self.config.timeout_sec)
        if result.ok and outcome.window is not None and self.config.companion_memory:
            window = outcome.window
            self.memory.record_look(window.process_name, classify_activity(window.process_name, window.title))
        self._count_result(result.ok)
        if not outcome.force and outcome.generation <= self.notice_generation:
            self._refresh_status()  # started before a Claude Code notice was shown: never cover it
            return
        if self.quiet and not outcome.force:
            self.deferred = reply  # keep it for when the full-screen app is gone
            self._refresh_status()
            return
        self._refresh_status()
        self.window.say(*self._reply_tuple(reply))

    def _count_result(self, ok: bool) -> None:
        """Failure breaker: after N failures in a row, automatic looks pause; pokes still work."""
        if ok:
            if self.auto_paused_until:
                log.info("automatic looks resumed after a successful reply")
            self.consecutive_failures = 0
            self.auto_paused_until = 0.0
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.config.failure_limit and not self.auto_paused_until:
            self.auto_paused_until = self._clock() + self.config.failure_pause_min * 60
            log.warning("automatic looks paused for %d min after %d failures in a row",
                        self.config.failure_pause_min, self.consecutive_failures)

    @staticmethod
    def _reply_tuple(reply: persona.Reply) -> tuple[str, str]:
        return reply.mood, reply.text

    # ---- menus -------------------------------------------------------
    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("戳她一下（立即评论）", self.poke)
        menu.addAction("和她说话…", self.chat)
        self.pause_action = QAction("暂停观察 (Ctrl+Alt+P)", menu, checkable=True, checked=self.config.paused)
        self.pause_action.triggered.connect(lambda _checked: self.toggle_pause())
        menu.addAction(self.pause_action)
        scope_menu = menu.addMenu("观察范围")
        scope_group = QActionGroup(scope_menu)
        self.watch_mode_actions = {}
        for mode, label in (("blocklist", "除黑名单外都看"), ("allowlist", "只看白名单")):
            action = QAction(label, scope_menu, checkable=True, checked=self.config.watch_mode == mode)
            action.triggered.connect(partial(self.set_watch_mode, mode))
            scope_group.addAction(action)
            scope_menu.addAction(action)
            self.watch_mode_actions[mode] = action
        scope_menu.addSeparator()
        self.allowlist_action = QAction("把当前程序加入白名单", scope_menu)
        self.allowlist_action.triggered.connect(self.toggle_current_in_allowlist)
        scope_menu.addAction(self.allowlist_action)
        menu.aboutToShow.connect(self._refresh_allowlist_action)
        self._refresh_allowlist_action()
        self.claude_link_action = QAction("Claude Code 联动", menu, checkable=True, checked=self.config.claude_link)
        self.claude_link_action.triggered.connect(self.set_claude_link)
        menu.addAction(self.claude_link_action)
        menu.aboutToShow.connect(self._refresh_claude_link_action)
        memory_menu = menu.addMenu("陪伴记忆")
        self.memory_action = QAction("记住主人在做什么", memory_menu, checkable=True, checked=self.config.companion_memory)
        self.memory_action.triggered.connect(self.set_companion_memory)
        memory_menu.addAction(self.memory_action)
        memory_menu.addAction("清空陪伴记忆", self.clear_companion_memory)
        self.self_talk_action = QAction("自言自语", menu, checkable=True, checked=self.config.self_talk)
        self.self_talk_action.triggered.connect(self.set_self_talk)
        menu.addAction(self.self_talk_action)

        interval_menu = menu.addMenu("评论间隔")
        group = QActionGroup(interval_menu)
        for seconds in INTERVAL_CHOICES:
            action = QAction(INTERVAL_LABELS[seconds], interval_menu, checkable=True, checked=seconds == self.config.interval_sec)
            action.triggered.connect(partial(self.set_interval, seconds))
            group.addAction(action)
            interval_menu.addAction(action)

        backend_menu = menu.addMenu("调用方式")
        backend_group = QActionGroup(backend_menu)
        self.backend_actions: dict[str, QAction] = {}
        for backend, label in (("subscription", "Claude Code 订阅（默认）"), ("api", "Anthropic API Key（按量付费）")):
            action = QAction(label, backend_menu, checkable=True, checked=backend == self.config.backend)
            action.triggered.connect(partial(self.set_backend, backend))
            backend_group.addAction(action)
            backend_menu.addAction(action)
            self.backend_actions[backend] = action
        backend_menu.addSeparator()
        backend_menu.addAction("设置 API Key…", self.set_api_key)
        backend_menu.addAction("清除已保存的 API Key", self.clear_api_key)

        model_menu = menu.addMenu("模型")
        model_group = QActionGroup(model_menu)
        for model in MODEL_CHOICES:
            label = {"haiku": "Haiku（快，省额度）", "sonnet": "Sonnet（更聪明，较慢）"}[model]
            action = QAction(label, model_menu, checkable=True, checked=model == self.config.model)
            action.triggered.connect(partial(self.set_model, model))
            model_group.addAction(action)
            model_menu.addAction(action)

        self.autostart_action = QAction(AUTOSTART_LABEL, menu, checkable=True)
        self.autostart_action.setEnabled(False)  # until the first (background) state read finishes
        self.autostart_action.triggered.connect(self.set_autostart)
        menu.addAction(self.autostart_action)
        # Re-read every time the menu opens: the user may have changed it in Task Manager meanwhile.
        menu.aboutToShow.connect(self._refresh_autostart)
        self._refresh_autostart()

        menu.addAction("打开日志文件夹", self.open_log_folder)
        menu.addSeparator()
        menu.addAction("退出", self.request_quit)
        return menu

    @staticmethod
    def _spawn_autostart(fn) -> None:
        # Not a daemon: a shortcut being created or deleted is finished even if the app is quitting.
        threading.Thread(target=fn, daemon=False).start()

    def _refresh_autostart(self) -> None:
        if self.autostart is None or self.autostart_busy or self.autostart_reading:
            return
        self.autostart_reading = True
        autostart = self.autostart
        version = self.autostart_version

        def read() -> None:
            # Checking who the shortcut belongs to needs PowerShell, so it is read off the UI thread.
            try:
                state = autostart.state()
            except (OSError, subprocess.SubprocessError):
                log.exception("autostart state unreadable")
                state = "unknown"
            self.autostart_state.emit(version, state)

        self._spawn_autostart(read)

    def _on_autostart_state(self, version: int, state: str) -> None:
        if version != self.autostart_version:
            return  # read before a change started; the read after that change decides
        self.autostart_reading = False
        if self.autostart_busy:
            return
        foreign = state == AUTOSTART_FOREIGN
        self.autostart_action.setChecked(state == AUTOSTART_ON)
        self.autostart_action.setEnabled(not foreign)
        self.autostart_action.setText(AUTOSTART_LABEL + ("（同名快捷方式属于其他程序）" if foreign else ""))

    def set_autostart(self, enabled: bool) -> None:
        if self.autostart is None or self.autostart_busy:
            return
        self.autostart_busy = True
        self.autostart_version += 1
        self.autostart_reading = False  # any read in flight is now stale
        self.autostart_action.setEnabled(False)
        autostart = self.autostart

        def work() -> None:
            # Creating the shortcut goes through PowerShell (about a second), so it stays off the UI thread.
            try:
                if enabled:
                    autostart.enable()
                else:
                    autostart.disable()
                message = "好的，以后开机我就会自动来陪主人啦～" if enabled else "好的，开机时我就不自己跑出来了。"
                self.autostart_done.emit(True, message)
            except (AutostartError, OSError, subprocess.SubprocessError) as exc:
                log.warning("autostart change failed: %s", exc)
                self.autostart_done.emit(False, f"呜…开机自启没设置成功：{exc}")

        self._spawn_autostart(work)

    def _on_autostart_done(self, ok: bool, message: str) -> None:
        self.autostart_busy = False
        self.autostart_action.setEnabled(True)
        self.window.say("happy" if ok else "sad", message)
        if self.quit_pending:
            self._quit()
            return
        self._refresh_autostart()

    def request_quit(self) -> None:
        """Quit, but let a running autostart change finish first so the shortcut is not left half-done."""
        if self.autostart_busy:
            # Stop observing right away; only the shortcut change is allowed to finish.
            self.quit_pending = True
            self.timer.stop()
            self.focus_tracker.stop()
            self._cancel_inflight()
            self.window.say("think", "等我把开机自启设置好就走～")
            QTimer.singleShot(AUTOSTART_QUIT_GRACE_MS, self._quit)
            return
        self._quit()

    def _show_menu(self, pos: QPoint) -> None:
        self.tray.contextMenu().popup(pos)

    def _on_tray(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.window.show()
            self.window.raise_()

    def toggle_pause(self) -> None:
        self.config.paused = not self.config.paused
        self.pause_action.setChecked(self.config.paused)
        if self.config.paused:
            self._cancel_inflight()
            self.window.say("sad", "好的，我先闭上眼睛，不偷看了。需要我的时候再叫我～")
        else:
            self.window.say("happy", "我回来啦！继续陪着主人～")
            self.last_fingerprint = None
        self._refresh_status()
        self._save()

    def set_interval(self, seconds: int, _checked: bool = True) -> None:
        self.config.interval_sec = seconds
        self.timer.start(seconds * 1000)
        self._save()

    # ---- watch scope ---------------------------------------------------------
    def set_watch_mode(self, mode: str, _checked: bool = True) -> None:
        if mode != self.config.watch_mode:
            self._cancel_inflight()  # a job started under the old scope must not upload anything
        self.config.watch_mode = mode
        self.watch_mode_actions[mode].setChecked(True)
        self._save()
        if mode == "allowlist" and not self.config.allowlist:
            self.window.say("think", "白名单还是空的哦～右键「观察范围」，把想让我看的程序加进来吧。")
        elif mode == "allowlist":
            self.window.say("happy", f"好的，以后我只看白名单里的 {len(self.config.allowlist)} 项～")
        else:
            self.window.say("happy", "好的，除了黑名单里的窗口，我都会看看～")

    def _current_window(self) -> capture.WindowInfo | None:
        """The window the user was in before opening the menu."""
        try:
            return capture.window_info(self.last_external_hwnd) if self.last_external_hwnd else None
        except OSError:
            return None

    def _current_program(self) -> str:
        info = self._current_window()
        return info.process_name if info is not None else ""

    def _current_title(self) -> str:
        info = self._current_window()
        return info.title if info is not None else ""

    def _exact_rules(self, name: str) -> list[str]:
        """Entries that name exactly this program (escaped literal, or the plain name for old configs)."""
        forms = {capture.literal_rule(name).casefold(), name.casefold()}
        return [rule for rule in self.config.allowlist if rule.casefold() in forms]

    def _refresh_allowlist_action(self) -> None:
        name = self._current_program()
        listed = bool(self._exact_rules(name)) if name else False
        if not name:
            self.allowlist_action.setText("把当前程序加入白名单（没有可加入的窗口）")
            self.allowlist_action.setEnabled(False)
        elif listed:
            self.allowlist_action.setText(f"从白名单移除「{name}」")
            self.allowlist_action.setEnabled(True)
        elif capture.matches_allowlist(self.config.allowlist, name, self._current_title()):
            self.allowlist_action.setText(f"「{name}」已被白名单规则匹配（在 config.json 修改）")
            self.allowlist_action.setEnabled(False)
        else:
            self.allowlist_action.setText(f"把「{name}」加入白名单")
            self.allowlist_action.setEnabled(True)

    def toggle_current_in_allowlist(self) -> None:
        name = self._current_program()
        if not name:
            return
        exact = self._exact_rules(name)
        if exact:
            self.config.allowlist = [rule for rule in self.config.allowlist if rule not in exact]
            self._cancel_inflight()  # tightened: a job started under the old list must not upload
            # Checked with the real title too, so title: rules that still match are reported.
            title = self._current_title()
            still = [rule for rule in self.config.allowlist if capture.matches_allowlist([rule], name, title)]
            if still:
                rules = "、".join(still)
                self.window.say("think", f"移掉了「{name}」这一条，但规则 {rules} 仍然匹配它，要在 config.json 里改哦。")
            else:
                self.window.say("happy", f"好的，「{name}」移出白名单了。")
        else:
            self.config.allowlist = self.config.allowlist + [capture.literal_rule(name)]
            hint = "" if self.config.watch_mode == "allowlist" else "（切到「只看白名单」后生效）"
            self.window.say("happy", f"记住啦，「{name}」加入白名单～{hint}")
        self._save()
        self._refresh_allowlist_action()

    def set_self_talk(self, enabled: bool) -> None:
        self.config.self_talk = bool(enabled)
        self.self_talk_action.setChecked(self.config.self_talk)
        self._schedule_self_talk()
        self._save()

    # ---- local self-talk -------------------------------------------------
    def _schedule_self_talk(self) -> None:
        if not self.config.self_talk or self.quit_pending:
            self.self_talk_timer.stop()
            return
        delay = self._rng.uniform(self.config.self_talk_min_sec, self.config.self_talk_max_sec)
        self.self_talk_timer.start(int(delay * 1000))

    def _self_talk_tick(self) -> None:
        try:
            self.maybe_self_talk()
        finally:
            self._schedule_self_talk()

    def maybe_self_talk(self) -> bool:
        """Say one local line if nothing else is going on. Never calls Claude."""
        if self.config.self_talk:
            # Fresh look, not the last heartbeat's: the user may have gone full screen a moment ago.
            self._track_foreground()
            self._update_quiet()
        if not self.config.self_talk or self.quit_pending or self.busy or self.quiet:
            return False
        if self.window.full_text:  # a bubble is still on screen
            return False
        if self._clock() - self.window.last_said_at < SELF_TALK_GAP_SEC:
            return False
        line = None
        if self.config.companion_memory and not self.asleep and self._rng.random() < MEMORY_TALK_CHANCE:
            top = self.memory.top_today(3600)
            if top is not None:
                line = persona.memory_talk_line(*top)
                if line.text in self.self_talk_recent:
                    line = None  # same figure as a recent line: say something else
        if line is None:
            line = persona.self_talk_line(self._hour(), self.asleep, list(self.self_talk_recent), self._rng)
        self.self_talk_recent.append(line.text)
        self.window.say(line.mood, line.text)
        return True

    # ---- how Claude is called ------------------------------------------
    @staticmethod
    def _ask_secret_dialog(title: str, label: str) -> tuple[str, bool]:
        return QInputDialog.getText(None, title, label, QLineEdit.EchoMode.Password)

    def _sync_backend_actions(self) -> None:
        for backend, action in self.backend_actions.items():
            action.setChecked(backend == self.config.backend)

    def _has_key(self) -> bool:
        try:
            return bool(self._load_key())
        except OSError:
            return False

    def set_backend(self, backend: str, _checked: bool = True) -> None:
        if backend == self.config.backend:
            self._sync_backend_actions()
            return
        if backend == "api":
            text = ("要改用你自己的 Anthropic API Key 吗？\n\n"
                    "API 按用量收费，费用记在这个 Key 所属的账户上（不是 Claude 订阅）。"
                    "她每次看屏幕或回答都会调用一次 API；评论间隔越短、选 Sonnet，花费越多。\n\n"
                    "Key 只保存在本机的 Windows 凭据管理器里，不会写进配置文件或日志。")
            if not self._confirm("切换到 API Key 模式", text):
                self._sync_backend_actions()
                return
            if not self._has_key() and not self.set_api_key():
                self._sync_backend_actions()
                return
        self._cancel_inflight()  # a request of the old kind must not come back
        self.config.backend = backend
        self.last_error = ""
        self.consecutive_failures = 0
        self.auto_paused_until = 0.0
        self._save()
        self._sync_backend_actions()
        self._refresh_status()
        if backend == "api":
            self.window.say("happy", "好的，之后我用主人的 API Key 来思考～（按量计费，记得留意用量哦）")
        else:
            self.window.say("happy", "好的，之后我用 Claude Code 的订阅登录来思考～")

    def set_api_key(self) -> bool:
        """Ask for a key and keep it in Windows Credential Manager. True when one was saved."""
        key, ok = self._ask_secret("设置 API Key", "粘贴你的 Anthropic API Key（只保存在本机 Windows 凭据管理器）：")
        key = (key or "").strip()
        if not ok or not key:
            return False
        if not api_client.looks_like_key(key):
            self.window.say("think", "这串看起来不像 API Key 呢……（不能有空格或中文）我没有保存。")
            return False
        try:
            self._save_key(key)
        except OSError as exc:
            log.warning("could not save the API key: %s", exc)
            self.window.say("sad", f"没能保存 API Key：{exc}")
            return False
        self.last_error = ""
        self._refresh_status()
        self.window.say("happy", "API Key 收好啦，锁在 Windows 凭据管理器里～")
        return True

    def clear_api_key(self) -> None:
        try:
            removed = self._delete_key()
        except OSError as exc:
            self.window.say("sad", f"没能清除 API Key：{exc}")
            return
        if self.config.backend == "api":
            self._cancel_inflight()
        tail = "（现在是 API Key 模式，要再设置一个 Key 才能继续看屏幕）" if self.config.backend == "api" else ""
        self.window.say("happy", ("已经清除保存的 API Key。" if removed else "本来就没有保存 API Key 哦。") + tail)

    def set_model(self, model: str, _checked: bool = True) -> None:
        self.config.model = model
        self._save()

    def _remember_position(self, x: int, y: int) -> None:
        self.config.x, self.config.y = x, y
        self._save()

    def _refresh_status(self) -> None:
        if self.config.paused:
            self.window.set_status("已暂停")
        elif self.busy:
            self.window.set_status("思考中…")
        elif self.quiet:
            held = self.deferred is not None or self.deferred_notice is not None
            self.window.set_status("全屏中，先不打扰" + ("（攒了一句）" if held else ""))
        elif self.auto_paused_until:
            resume = time.strftime("%H:%M", time.localtime(time.time() + max(0.0, self.auto_paused_until - self._clock())))
            reason = f"｜原因：{self.last_error}" if self.last_error else ""
            self.window.set_status(f"连续失败 {self.consecutive_failures} 次，{resume} 前不自动看{reason}")
        elif self.last_error:
            self.window.set_status("原因：" + self.last_error)
        elif self.config.claude_link and self.claude_state.status():
            self.window.set_status(self.claude_state.status())
        elif self.asleep:
            self.window.set_status("睡着了…动一下鼠标叫醒她")
        else:
            self.window.set_status("")

    def open_log_folder(self) -> None:
        folder = app_data_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._open_path(str(folder))
        except OSError as exc:
            log.warning("could not open log folder: %s", exc)
            self.window.say("sad", f"打不开日志文件夹：{folder}")

    def _save(self) -> None:
        try:
            save_config(self.config, self.config_file)
        except OSError:
            log.exception("could not save config")

    # ---- hotkey ------------------------------------------------------
    def _register_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        mod_alt, mod_control, mod_norepeat = 0x0001, 0x0002, 0x4000
        hwnd = int(self.window.winId())
        if not ctypes.windll.user32.RegisterHotKey(hwnd, HOTKEY_ID, mod_alt | mod_control | mod_norepeat, ord("P")):
            log.warning("Ctrl+Alt+P is already taken by another program")

    def _unregister_hotkey(self) -> None:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.UnregisterHotKey(int(self.window.winId()), HOTKEY_ID)
