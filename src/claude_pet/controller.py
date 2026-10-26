"""Glue: timer -> capture -> privacy/change checks -> background Claude call -> pet window."""
from __future__ import annotations

import datetime
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
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon

from .i18n import N_, tr
from . import __version__, agent_link, i18n, api_client, bedtime, capture, claude_client, days, codex_client, credstore, openai_client, persona, providers, reminder_dialog, timers, updates, voice
from .providers import ANTHROPIC, CLAUDE_CLI, CODEX_CLI, OPENAI_COMPATIBLE, PROVIDERS
from .autostart import FOREIGN as AUTOSTART_FOREIGN
from .autostart import ON as AUTOSTART_ON
from .autostart import Autostart, AutostartError
from .memory import CompanionMemory, classify_activity
from .config import BLINK_CHOICES, Config, app_data_dir, save_config
from .pet_window import PetWindow
from .walker import Walker

log = logging.getLogger("claude_pet")

CHANGE_THRESHOLD = 0.02
HOTKEY_ID = 0xC1A0
UPDATE_RESULTS = {  # what the about page says after a swap, by the restart helper's note
    "updated": N_("已更新到 {version}。"),
    "restored": N_("上次下载的新版没能换上，现在用的还是原来的版本（{version}），可以再试一次。"),
    "failed": N_("上次的更新没有完成，请到下载页手动下载新版。"),
}
UPDATE_NOTE_RETRY_SEC = 2.0  # the restart helper's note, held open at start: tried again this often
UPDATE_FIRST_DELAY_SEC = 30.0  # the first update check, a little after start
PAT_MEMORY_SEC = 60.0  # pats this close together count as one petting session
TIMER_HOLD_MS = 20000  # a due timer or reminder stays on screen this long
DROP_MEMORY_SEC = 20.0  # drops this close together are being dragged about
DROPS_TO_COMPLAIN = 3
LONG_CARRY_SEC = 4.0  # carried at least this long: dizzy
POKE_COOLDOWN_SEC = 30.0  # clicks this soon after a click's look get a local line, not another look
PAT_COOLDOWN_SEC = 5.0  # one reaction per head pat, however long the rubbing goes on
RESIZE_SETTLE_MS = 1200  # resizing has stopped when nothing changed for this long
SIZE_SHOWN_SEC = 2.5  # how long her height stays under her feet after Ctrl + wheel
AUTH_CHECK_TTL = 1800
AUTOSTART_LABEL = N_("开机自启")
MEMORY_TALK_CHANCE = 0.25  # share of self-talk turns that mention today's main activity (if >= 1 h)
MEMORY_FLUSH_SEC = 60
SELF_TALK_GAP_SEC = 60  # never talk to herself within a minute of saying anything
WAKE_IDLE_SEC = 5
NOTICE_AWAKE_SEC = 120  # after a Claude Code notice wakes her, she stays awake this long  # input within this many seconds wakes her
ERROR_MAX = 80  # characters of an error reason shown under the pet
AUTOSTART_QUIT_GRACE_MS = 30_000  # longest wait for a running autostart change when quitting
INTERVAL_LABELS = {30: N_("30 秒"), 60: N_("1 分钟"), 90: N_("90 秒"), 120: N_("2 分钟"), 300: N_("5 分钟"), 600: N_("10 分钟")}


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
    backend: str = "subscription"  # a providers.PROVIDERS key
    kind: str = CLAUDE_CLI  # how that provider is called; decides which call object `call` is
    codex: str = ""  # the Codex CLI, for CODEX_CLI
    tier: str = "haiku"  # fast / smarter; Codex turns it into a reasoning effort
    bedtime: str = ""  # at night: "ok" (may remind 主人 to rest) or "no"; "" during the day


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
        return tr("超时（{0} 秒内没有回复）", timeout_sec)
    if result.not_subscription:
        return tr("不是订阅登录：{0}", result.error)[:ERROR_MAX]
    if result.no_api_key:
        return tr("还没有设置 API Key（设置里的「调用方式」页）")
    lines = [line.strip() for line in (result.error or "").splitlines() if line.strip()]
    text = lines[0] if lines else tr("未知错误")
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
    codex_found = Signal(object, object)  # (path or None, what to do next)
    update_found = Signal(object, bool)  # (latest released version or None, asked by 主人)
    download_progress = Signal(int, int)  # (bytes so far, of)
    download_done = Signal(object, object)  # (the verified exe or None, its version or an i18n.Msg why not)

    def __init__(self, app: QApplication, config: Config, sprite_folder: Path, config_file: Path | None = None,
                 autostart: Autostart | None = None, memory: CompanionMemory | None = None) -> None:
        super().__init__()
        self.app = app
        self.config = config
        self.config_file = config_file
        i18n.set_language(config.language)  # before any text is made
        self.window = PetWindow(sprite_folder, config.sprite_height)
        self.window.set_blink(config.blink)
        self.window.set_talk_mouth(config.talk_mouth)
        self.window.set_head_motion(config.head_motion)
        self.window.set_body_motion(config.body_motion)
        self.voice = voice.Player(app_data_dir() / "voice")
        self.window.spoke.connect(self._speak)
        self.window.hushed.connect(self.voice.stop)
        self.window.lifted.connect(lambda: self._effect("lift"))
        self.pomodoro = timers.Pomodoro()
        self.reminders = timers.Reminders(app_data_dir() / "reminders.json")
        self.focus_log = timers.FocusLog(app_data_dir() / "focus.json")
        self._focus_event: str | None = None  # the timer's latest news, waiting for her to be free to say it
        self._ask_reminder = reminder_dialog.ask
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
        self._now = time.time  # wall clock, for the bedtime reminder that survives restarts
        self.self_talk_recent: deque[str] = deque(maxlen=8)
        self.self_talk_timer = QTimer(self, singleShot=True, timeout=self._self_talk_tick)
        # Companion memory: in-memory only unless the app hands in a file-backed one.
        self.memory = memory if memory is not None else CompanionMemory(None)
        # Claude Code link: hooks write event names to a local file; the pet only reads that file.
        self.claude_state = agent_link.ClaudeCodeState()
        self.claude_settings = agent_link.claude_settings_path()
        self.claude_tail: agent_link.EventTail | None = None
        self._confirm = self._ask_confirm
        self.settings_window = None  # built the first time it is opened
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
        self.codex: str | None = None  # found when Codex mode is first used
        codex_client.schedule_cleanup(sweep=True)  # screenshots a crash left in %TEMP%, in the background
        self.last_external_hwnd = 0
        # Each request gets a generation number; pausing or quitting bumps it so late replies are dropped.
        self.generation = 0
        self.current_call: claude_client.ClaudeCall | api_client.ApiCall | None = None
        self.auth_ok_until = 0.0

        self.reply_ready.connect(self._on_reply)
        self.codex_found.connect(self._on_codex_found)
        self.update_found.connect(self._on_update_found)
        self.download_progress.connect(self._on_download_progress)
        self.download_done.connect(self._on_download_done)
        self._codex_searching = False
        self._codex_request: tuple | None = None  # what to do once the Codex search is done
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
        self.window.poked.connect(self._on_poked)
        self.window.context_menu_requested.connect(self._show_menu)
        self.window.moved.connect(self._on_user_dropped)
        self.walker = Walker(self.window, self._can_walk, self._remember_position, self._rng,
                             edge=self._on_edge, landed=self._on_landed)
        self.window.patted.connect(self._on_patted)
        self._last_pat = float("-inf")
        self._pat_count = 0
        self._last_poke_look = float("-inf")  # when a click last made her look at the screen
        self._pokes_since_look = 0  # pats in this petting session, for shy and then mock-annoyed replies
        self._drops: list[float] = []  # recent drops after a drag
        self._greeting_due = ""  # the day (YYYY-MM-DD) whose first hello had to wait
        self.update_available = ""  # a newer released version, once a check found one
        self._update_status: str | i18n.Msg = ""  # what the about page says about the last check
        self.update_checking = False
        self._update_from = float("inf")  # no automatic check before start() (then one shortly after)
        self._update_announce = False
        self._update_retry = False  # the last check failed: the next one is due an hour later, not a day
        self._take_update(self.config.update_latest)  # found by an earlier run, maybe not told yet
        self.download_state = ""  # "", "downloading" or "ready" (verified, waiting for the restart)
        self._download_text: str | i18n.Msg = ""  # progress or outcome, for the about page
        self._download_cancel = threading.Event()
        self._download_path: Path | None = None
        self._download_sha = ""
        self._download_installer = False  # the download is the installer, not the exe
        self._download_percent = -1
        self._launch_restart = updates.launch_restart
        self._update_note_retry = False
        self._update_note_retry_at = 0.0
        self._resize_from: int | None = None  # her height before the current burst of resizing
        self._resize_done = QTimer(self, singleShot=True, interval=RESIZE_SETTLE_MS, timeout=self._on_resized)
        self.window.hotkey_pressed.connect(self.toggle_pause)
        self.window.resize_wheel.connect(self.resize_by_wheel)
        self._size_shown_until = float("-inf")  # her height under her feet, briefly, after Ctrl + wheel

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
        if self.config.walking:  # walking: she lives on the bottom of the screen
            self.walker.land_now()
            self._remember_position(self.window.x(), self.window.y())
        self.tray.show()
        self._register_hotkey()
        self.timer.start(self.config.interval_sec * 1000)
        self.focus_tracker.start()
        self._schedule_self_talk()
        self._update_from = self._clock() + UPDATE_FIRST_DELAY_SEC
        self._remove_update_leftovers()
        self.walker.set_enabled(self.config.walking)
        self._refresh_status()
        if self.config.backend == "subscription" and not self.claude:
            self.window.say(*self._reply_tuple(persona.fallback("no_claude")))
            today = self._today().isoformat()
            if self.config.greeted_on != today:
                self._greeting_due = today  # after the notice
        else:
            if not self._greet_if_new_day():  # the first hello of the day, or the usual one
                self.window.say("happy", tr("主人好～我是 Claude。我会安静待在这里，偶尔看看你在忙什么。"))
            # First look once the dwell gate can pass, so she does not wait a whole interval.
            QTimer.singleShot(max(8, self.config.dwell_sec + 1) * 1000, self.tick)

    @property
    def _cleanup_running(self) -> bool:
        return codex_client.cleanup_running()

    def shutdown(self) -> None:
        self._cancel_inflight()
        self.focus_log.flush(float("inf"))  # one last try for anything a locked file kept from being saved
        self.voice.stop()
        self._download_cancel.set()
        self.walker.set_enabled(False)
        if codex_client.has_pending():
            codex_client.schedule_cleanup()
        codex_client.wait_cleanup(1.0)  # quitting never hangs; leftovers are swept at the next start
        if codex_client.has_pending():
            log.warning("temporary Codex screenshot folders are still locked; they are removed at the next start")
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
                self.window.say("sad", tr("我现在闭着眼睛呢，没在看哦～（Ctrl+Alt+P 恢复）"))
            return
        provider = self._provider()
        if provider.kind == CODEX_CLI and not self.codex:
            self._find_codex(("tick", force, user_message))  # searched off the UI thread; ticks again when found
            return
        if provider.kind == CLAUDE_CLI and not self.claude:
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
        key = partial(self._load_key, provider.vault_entry)  # read on the worker, never kept in the Job
        if provider.kind == ANTHROPIC:
            call = api_client.ApiCall(self.config.timeout_sec, load_key=key)
        elif provider.kind == OPENAI_COMPATIBLE:
            call = openai_client.OpenAICompatCall(provider, self.config.timeout_sec, load_key=key)
        elif provider.kind == CODEX_CLI:
            call = codex_client.CodexCall(self.config.timeout_sec, cwd=str(cwd))
        else:
            call = claude_client.ClaudeCall(self.config.timeout_sec, cwd=str(cwd))
        job = Job(
            bedtime=self._bedtime(), generation=self.generation, force=force, user_message=user_message,
            may_capture=not self.config.paused, hwnd=self.last_external_hwnd,
            blocklist=list(self.config.blocklist), last_fingerprint=self.last_fingerprint,
            need_auth=time.monotonic() >= self.auth_ok_until, claude=self.claude,
            model=providers.model_for(provider, self.config.model, self.config.custom_models.get(provider.id, "")),
            recent=list(self.recent), call=call,
            quiet_check=None if force or not self.config.quiet_fullscreen else partial(full_screen_now, self.last_external_hwnd),
            allowlist=self._allowlist(),
            memory_context=self._memory_context(),
            backend=provider.id, kind=provider.kind, codex=self.codex or "", tier=self.config.model,
        )
        self.current_call = call
        self.busy = True
        self._refresh_status()
        # Whatever happens on the worker (even a PrintWindow that never returns), the pet recovers.
        QTimer.singleShot((self.config.timeout_sec * 2 + 60) * 1000, partial(self._watchdog, job.generation, force))
        self._spawn(partial(self._work, job))

    def poke(self) -> None:
        """The menu's 「戳她一下（立即评论）」: always a fresh look."""
        if self.busy:
            self.window.say("think", tr("等一下下，我还在想上一句……"))
            return
        self.tick(force=True)

    def _on_poked(self) -> None:
        """A click on her: a fresh look, but clicks soon after one get a local line instead (no model call),
        a little more flustered with each."""
        if self.busy:
            self.window.say("think", tr("等一下下，我还在想上一句……"))
            return
        now = self._clock()
        if now - self._last_poke_look < POKE_COOLDOWN_SEC:
            self._pokes_since_look += 1
            self._react(("poke", "poke_again", "poke_annoyed")[min(self._pokes_since_look, 3) - 1])
            return
        generation = self.generation
        self.tick(force=True)
        if self.busy and self.generation != generation:  # she really is looking (not paused, not unable to)
            self._last_poke_look, self._pokes_since_look = now, 0

    def chat(self) -> None:
        text, ok = QInputDialog.getText(None, tr("和 Claude 说话"), tr("想对她说什么？"))
        if ok and text.strip():
            if self.busy:
                self.window.say("think", tr("等一下下，我还在想上一句……"))
                return
            self.tick(force=True, user_message=text.strip()[:300])

    def _find_codex(self, then: tuple) -> None:
        """PATH may hold a slow or offline network share: the search never runs on the UI thread.
        Only the latest request waits for it (a message from the user is never replaced by an automatic
        look), and it is dropped if the pet is paused, switched or quit meanwhile."""
        old = self._codex_request
        user_waiting = old is not None and old[0] == "tick" and old[2] and then[0] == "tick" and not then[2]
        if not user_waiting:
            self._codex_request = (*then, self.generation, self.config.backend)
        if self._codex_searching:
            return
        self._codex_searching = True
        self._spawn(lambda: self.codex_found.emit(codex_client.find_codex(), None))

    def _on_codex_found(self, path, _unused=None) -> None:
        self._codex_searching = False
        self.codex = path or None
        request, self._codex_request = self._codex_request, None
        if request is None or self.quit_pending:
            return
        *then, generation, backend = request
        if generation != self.generation or backend != self.config.backend:
            return  # paused, switched or cancelled meanwhile: never sent late
        if then[0] == "switch":
            if self.codex:
                self.set_backend("codex")
            else:
                self.window.say(*self._reply_tuple(persona.fallback("no_codex")))
        elif self.codex:
            self.tick(then[1], then[2])
        elif then[1]:
            self.window.say(*self._reply_tuple(persona.fallback("no_codex")))

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
        if codex_client.has_pending():  # a Codex screenshot that was still locked: try again (in the background)
            codex_client.schedule_cleanup()
        self._track_foreground()
        self._update_quiet()
        self._update_sleep()
        self._update_claude_link()
        self._flush_deferred()
        self._update_memory()
        if self._greeting_due and not self.asleep and not self.window.full_text:
            if self._greeting_due == self._today().isoformat():
                self._greet_if_new_day()  # one that had to wait (full screen, quitting) comes now
            else:
                self._greeting_due = ""  # owed for a day that is over: wait for the next meeting
        self._update_timers()
        self._summarize_day_if_due()
        self._retry_update_note()
        self._check_updates_if_due()
        if self._update_announce:
            self._announce_update()
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

    def claude_link_broken(self) -> bool:
        """Switched on, but the hooks are gone or settings.json cannot be read (shown in the settings window)."""
        return self.config.claude_link and not agent_link.is_installed(self.claude_settings)

    def set_claude_link(self, enabled: bool) -> None:
        if enabled:
            text = (tr("要开启 Claude Code 联动吗？\n\n这会修改 {0}：添加几条 hook。如果文件已存在，会先备份为 settings.json.claude-pet-backup-<时间戳>（保留最近 5 份）。\n\nhook 只从 Claude Code 的事件数据里取出会话编号，往本地文件写“事件名 + 会话编号 + 时间”（例如“在改文件”“等你批准”）；你的提示词、代码和命令内容不会被保存。\n\n关闭联动时，只移除这些 hook。", self.claude_settings))
            if not self._confirm(tr("Claude Code 联动"), text):
                return
            try:
                self._claude_event_file()  # first, so a failure leaves settings.json untouched
            except OSError as exc:
                log.warning("could not prepare the Claude Code event file: %s", exc)
                self.window.say("sad", tr("没能开启联动：事件文件写不进去（{0}）", exc))
                return
            try:
                backup = agent_link.install_hooks(self.claude_settings)
            except (agent_link.HooksError, OSError) as exc:
                log.warning("could not install Claude Code hooks: %s", exc)
                self.window.say("sad", tr("没能开启联动：{0}", exc))
                return
            self.config.claude_link = True
            self._open_claude_tail()
            self._save()
            saved = tr("原来的设置备份在 {0}。", backup.name) if backup else ""
            self.window.say("happy", tr("联动开启啦！Claude Code 妹妹在忙什么我都会知道～{0}（已经开着的会话可能要重开才生效）", saved))
            return
        self.config.claude_link = False
        self.claude_tail = None
        self.claude_state = agent_link.ClaudeCodeState()
        self.pending_notices.clear()
        self.awake_until = 0.0
        self._save()
        try:
            agent_link.uninstall_hooks(self.claude_settings)
        except (agent_link.HooksError, OSError) as exc:
            log.warning("could not remove Claude Code hooks: %s", exc)
            self.window.say("sad", tr("我不再看联动了，但没能从 settings.json 移除 hook：{0}", exc))
            return
        self.window.say("happy", tr("好的，联动关掉了，hook 也移除了。"))
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
        self._save()

    def clear_companion_memory(self) -> None:
        # Cancel first: an in-flight request still holds the old summary, and its reply would record again.
        self._cancel_inflight()
        try:
            self.memory.clear()
        except OSError as exc:
            log.exception("could not clear companion memory")
            self.window.say("sad", tr("记忆在我这儿清空了，但 memory.json 没能改写（{0}），我稍后会再试。", exc))
            return
        self.window.say("happy", tr("好的，陪伴记忆都清空啦……（翻到新的一页）"))

    def _update_quiet(self) -> None:
        if not self.config.quiet_fullscreen:
            quiet = False
        else:
            quiet = full_screen_now(self.last_external_hwnd)
        if quiet == self.quiet:
            return
        self.quiet = quiet
        self.window.calm = quiet
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
        self._note_bedtime(reply.text)  # only what she really said counts

    def _update_sleep(self) -> None:
        try:
            idle = capture.idle_seconds()
        except OSError:
            idle = None
        if idle is None:
            return
        if not self.asleep and not self.busy and idle >= self.config.sleep_after_sec and self._clock() >= self.awake_until:
            self.asleep = True
            reply = persona.pick(persona.lines("SLEEP_LINES"))
            if self.quiet:
                self.window.set_mood(reply.mood)
            else:
                self.window.say(reply.mood, reply.text)
                self._effect("snore")  # once, as she drops off (after her line, which has no voice asleep)
        elif self.asleep and idle < WAKE_IDLE_SEC:
            # A held-back reply doubles as the greeting (said by _flush_deferred right after).
            self._wake(announce=not self.quiet and self.deferred is None)

    def _wake(self, announce: bool) -> None:
        if not self.asleep:
            return
        self.asleep = False
        self.target_since = self._clock()  # fresh dwell after coming back
        if not announce:
            today = self._today().isoformat()
            if self.config.greeted_on != today:
                self._greeting_due = today  # said once she may talk
            self.window.set_mood("idle")
        elif not self._greet_if_new_day():
            self.window.say(*self._reply_tuple(persona.pick(persona.lines("WAKE_LINES"))))

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
        # Codex: checked before every call (the login can change any time; a cached "yes" could bill an API key).
        if (job.kind == CLAUDE_CLI and job.need_auth) or job.kind == CODEX_CLI:
            # Nothing is sent unless the CLI would use the subscription login (claude.ai / ChatGPT), never an API key.
            if job.kind == CLAUDE_CLI:
                auth_ok, reason = job.call.check_subscription(job.claude)
            else:
                auth_ok, reason = job.call.check_login(job.codex)
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
            bedtime=job.bedtime,
        )
        if job.kind == CLAUDE_CLI:
            args = claude_client.build_args(job.claude, job.model, persona.system_prompt())
            result = job.call.run(args, claude_client.build_message(text, snapshot.jpeg))
        elif job.kind == CODEX_CLI:
            result = job.call.ask(job.codex, job.model, persona.system_prompt(), text, snapshot.jpeg,
                                  effort=codex_client.EFFORTS.get(job.tier, "low"))
        else:
            result = job.call.ask(job.model, persona.system_prompt(), text, snapshot.jpeg)
        source = "claude" if job.kind == CLAUDE_CLI else job.backend
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
            self.last_error = tr("任务卡住，已放弃")
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
                self.window.say("think", tr("主人现在好像没有打开什么窗口呢……"))
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
            reply = persona.fallback("not_chatgpt" if self._provider().kind == CODEX_CLI else "not_subscription")
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
        self._note_bedtime(reply.text)  # only what she really said counts

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

    # ---- focus timer and reminders ---------------------------------------
    def _update_timers(self) -> None:
        """Each second. The timer moves on to its next period on time; what is due is said once her bubble is free,
        one line at a time. In full-screen quiet it waits; a due line wakes her, so it is there when 主人 looks back.
        A reminder stays saved until it is said, and whether it was missed is judged when it is said."""
        now = self._now()
        ended = self.pomodoro.ends_at  # when the period really ran out (the PC may have slept past it)
        event = self.pomodoro.due(now, self.config.focus_min * 60, self.config.break_min * 60)
        if event == "focus_done":
            self.focus_log.add(ended, self.pomodoro.focus_sec)
        self.focus_log.flush(now)  # (a locked file: tried again now and then)
        if event:
            log.info("focus timer: %s", event)
            self._focus_event = event  # a newer one replaces one never said
        if self.quiet or self.quit_pending or self.window.full_text:
            return
        reply = self._focus_reply(now)
        self._focus_event = None
        while reply is None:
            reminder = self.reminders.due_now(now)
            if reminder is None:
                return
            self.reminders.finish(reminder.id)
            late = now - reminder.due
            if late > timers.FORGET_AFTER_SEC:
                log.info("dropped a reminder missed by %.0f hours", late / 3600)
                continue
            reply = persona.timer_line("missed" if late > timers.MISSED_AFTER_SEC else "reminder", self._rng,
                                       reminder.text, timers.clock_text(reminder.due))
        if self.asleep:
            self._wake(announce=False)
        self.window.say(reply.mood, reply.text, hold_ms=TIMER_HOLD_MS)

    def _focus_reply(self, now: float) -> persona.Reply | None:
        """Worded when said, from the time really left: a line held back a while still tells the truth."""
        event = self._focus_event
        if event is None or not self.pomodoro.running or self.pomodoro.paused:
            return None  # (paused: her pause line already told the time left; "in N minutes" would not come true)
        left = max(1, -int(-self.pomodoro.left(now) // 60))  # whole minutes, rounded up
        if event == "focus_done":
            return persona.timer_line(event, self._rng, self.config.focus_min, left, self.pomodoro.done)
        return persona.timer_line(event, self._rng, left, self.config.break_min, self.pomodoro.done)

    def _timer_status(self) -> str:
        now = self._now()
        if self.pomodoro.running:
            left = timers.left_text(self.pomodoro.left(now))
            text = tr("专注 {0}", left) if self.pomodoro.phase == "focus" else tr("放松 {0}", left)
            return text + (tr("（暂停）") if self.pomodoro.paused else "")
        upcoming = self.reminders.next()
        if upcoming is None:
            return ""
        count = len(self.reminders.items)
        when = timers.clock_text(upcoming.due)
        return tr("提醒 {0}", when) if count == 1 else tr("提醒 {0}（共 {1} 个）", when, count)

    def _fill_timer_menu(self) -> None:
        menu = self.timer_menu
        menu.clear()
        done, _seconds = self.focus_log.on(datetime.date.fromtimestamp(self._now()))
        if done:
            menu.addAction(tr("今天已完成 {0} 个番茄", done)).setEnabled(False)
        if not self.pomodoro.running:
            menu.addAction(tr("开始专注（{0} 分钟）", self.config.focus_min), self.start_focus)
        else:
            menu.addAction(tr("继续计时") if self.pomodoro.paused else tr("暂停计时"), self.toggle_focus_pause)
            menu.addAction(tr("结束番茄钟"), self.stop_focus)
        menu.addSeparator()
        menu.addAction(tr("添加提醒…"), self.add_reminder)
        for reminder in self.reminders.items:
            text = reminder.text if len(reminder.text) <= 18 else reminder.text[:17] + "…"
            menu.addAction(tr("取消提醒：{0} {1}", timers.clock_text(reminder.due), text),
                           lambda _checked=False, ident=reminder.id: self.cancel_reminder(ident))

    def start_focus(self) -> None:
        self.pomodoro.start(self._now(), self.config.focus_min * 60)
        self._focus_event = None
        self.window.say(*self._reply_tuple(persona.timer_line("start", self._rng, self.config.focus_min)))
        self._refresh_status()

    def toggle_focus_pause(self) -> None:
        if not self.pomodoro.running:
            return
        now = self._now()
        if self.pomodoro.paused:
            self.pomodoro.resume(now)
            self.window.say("happy", tr("继续计时～还剩 {0}。", timers.left_text(self.pomodoro.left(now))))
        else:
            self.pomodoro.pause(now)
            self.window.say("talk", tr("好，先暂停，还剩 {0}。", timers.left_text(self.pomodoro.left(now))))
        self._refresh_status()

    def stop_focus(self) -> None:
        if not self.pomodoro.running:
            return
        done = self.pomodoro.stop()
        self._focus_event = None  # its unsaid "back in 5 minutes" would not come true now
        self.window.say(*self._reply_tuple(persona.timer_line("stopped", self._rng, self.config.focus_min,
                                                              self.config.break_min, done)))
        self._refresh_status()

    def add_reminder(self) -> None:
        chosen = self._ask_reminder(self._now)
        if chosen is None:
            return
        due, text = chosen
        try:
            reminder = self.reminders.add(due, text)
        except OSError as exc:
            log.warning("could not save a reminder: %s", exc)
            self.window.say("sad", tr("提醒没存上（{0}），这次没有设好……", exc.strerror or type(exc).__name__))
            return
        if reminder is None:
            self.window.say("think", tr("提醒已经有 {0} 个了，先取消几个吧～", timers.MAX_REMINDERS))
            return
        when = timers.clock_text(due)
        today = datetime.date.fromtimestamp(self._now())
        day = datetime.date.fromtimestamp(due)
        if day == today:
            self.window.say("happy", tr("好，{0} 提醒主人：{1}", when, reminder.text))
        elif day == today + datetime.timedelta(days=1):
            self.window.say("happy", tr("好，明天 {0} 提醒主人：{1}", when, reminder.text))
        else:
            self.window.say("happy", tr("好，{0} 月 {1} 日 {2} 提醒主人：{3}", day.month, day.day, when, reminder.text))
        self._refresh_status()

    def cancel_reminder(self, ident: str) -> None:
        try:
            reminder = self.reminders.cancel(ident)
        except OSError as exc:
            log.warning("could not save reminders: %s", exc)
            self.window.say("sad", tr("没能取消（{0}），提醒还在……", exc.strerror or type(exc).__name__))
            return
        if reminder is not None:
            self.window.say("talk", tr("好，{0} 的提醒取消了。", timers.clock_text(reminder.due)))
        self._refresh_status()

    def set_focus_minutes(self, minutes: int) -> None:
        """Takes effect from the next focus period."""
        self.config.focus_min = min(max(int(minutes), timers.FOCUS_RANGE[0]), timers.FOCUS_RANGE[1])
        self._save()

    def set_break_minutes(self, minutes: int) -> None:
        self.config.break_min = min(max(int(minutes), timers.BREAK_RANGE[0]), timers.BREAK_RANGE[1])
        self._save()

    # ---- menus -------------------------------------------------------
    def _build_menu(self) -> QMenu:
        """Only what is wanted at hand; everything else lives in the settings window."""
        menu = QMenu()
        menu.addAction(tr("戳她一下（立即评论）"), self.poke)
        menu.addAction(tr("和她说话…"), self.chat)
        self.timer_menu = menu.addMenu(tr("番茄钟与提醒"))
        self.timer_menu.aboutToShow.connect(self._fill_timer_menu)
        self._fill_timer_menu()
        menu.addAction(tr("设置…"), self.open_settings)
        self.pause_action = QAction(tr("暂停观察 (Ctrl+Alt+P)"), menu, checkable=True, checked=self.config.paused)
        self.pause_action.triggered.connect(lambda _checked: self.toggle_pause())
        menu.addAction(self.pause_action)
        # About the window in front right now, so it stays here (shown in "only the allowlist" mode).
        self.allowlist_action = QAction(tr("把当前程序加入白名单"), menu)
        self.allowlist_action.triggered.connect(self.toggle_current_in_allowlist)
        menu.addAction(self.allowlist_action)
        menu.aboutToShow.connect(self._refresh_allowlist_action)
        self._refresh_allowlist_action()
        menu.addSeparator()
        menu.addAction(tr("退出"), self.request_quit)
        # The autostart switch is in the settings window; its state is read in the background.
        self.autostart_on, self.autostart_enabled, self.autostart_text = False, False, tr(AUTOSTART_LABEL)
        self._refresh_autostart()
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
        self.autostart_on, self.autostart_enabled = state == AUTOSTART_ON, not foreign
        self.autostart_text = tr(AUTOSTART_LABEL) + (tr("（同名快捷方式属于其他程序）") if foreign else "")
        self._sync_settings()  # last: the window copies on, enabled and the text

    def set_autostart(self, enabled: bool) -> None:
        if self.autostart is None or self.autostart_busy:
            return
        self.autostart_busy = True
        self.autostart_version += 1
        self.autostart_reading = False  # any read in flight is now stale
        self.autostart_enabled = False
        autostart = self.autostart

        def work() -> None:
            # Creating the shortcut goes through PowerShell (about a second), so it stays off the UI thread.
            try:
                if enabled:
                    autostart.enable()
                else:
                    autostart.disable()
                message = tr("好的，以后开机我就会自动来陪主人啦～") if enabled else tr("好的，开机时我就不自己跑出来了。")
                self.autostart_done.emit(True, message)
            except (AutostartError, OSError, subprocess.SubprocessError) as exc:
                log.warning("autostart change failed: %s", exc)
                self.autostart_done.emit(False, tr("呜…开机自启没设置成功：{0}", exc))

        self._spawn_autostart(work)

    def _on_autostart_done(self, ok: bool, message: str) -> None:
        self.autostart_busy = False
        self.autostart_enabled = True
        self._sync_settings()
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
            self.window.say("think", tr("等我把开机自启设置好就走～"))
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
            self.window.say("sad", tr("好的，我先闭上眼睛，不偷看了。需要我的时候再叫我～"))
        else:
            self.window.say("happy", tr("我回来啦！继续陪着主人～"))
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
        self._refresh_allowlist_action()
        self._save()
        if mode == "allowlist" and not self.config.allowlist:
            self.window.say("think", tr("白名单还是空的哦～打开想让我看的程序，右键选「把它加入白名单」，或在设置的「观察范围」页添加吧。"))
        elif mode == "allowlist":
            self.window.say("happy", tr("好的，以后我只看白名单里的 {0} 项～", len(self.config.allowlist)))
        else:
            self.window.say("happy", tr("好的，除了黑名单里的窗口，我都会看看～"))

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
        self.allowlist_action.setVisible(self.config.watch_mode == "allowlist")
        name = self._current_program()
        listed = bool(self._exact_rules(name)) if name else False
        if not name:
            self.allowlist_action.setText(tr("把当前程序加入白名单（没有可加入的窗口）"))
            self.allowlist_action.setEnabled(False)
        elif listed:
            self.allowlist_action.setText(tr("从白名单移除「{0}」", name))
            self.allowlist_action.setEnabled(True)
        elif capture.matches_allowlist(self.config.allowlist, name, self._current_title()):
            self.allowlist_action.setText(tr("「{0}」已被白名单规则匹配（在 config.json 修改）", name))
            self.allowlist_action.setEnabled(False)
        else:
            self.allowlist_action.setText(tr("把「{0}」加入白名单", name))
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
                rules = tr("、").join(still)
                self.window.say("think", tr("移掉了「{0}」这一条，但规则 {1} 仍然匹配它，要在 config.json 里改哦。", name, rules))
            else:
                self.window.say("happy", tr("好的，「{0}」移出白名单了。", name))
        else:
            self.config.allowlist = self.config.allowlist + [capture.literal_rule(name)]
            hint = "" if self.config.watch_mode == "allowlist" else tr("（切到「只看白名单」后生效）")
            self.window.say("happy", tr("记住啦，「{0}」加入白名单～{1}", name, hint))
        self._save()
        self._refresh_allowlist_action()

    def set_blink(self, rate: str) -> None:
        if rate in BLINK_CHOICES:
            self.config.blink = rate
            self.window.set_blink(rate)
            self._save()

    def _hushed(self) -> bool:
        """Asleep, in full-screen quiet or quitting: no voice at all, not even a preview."""
        return self.asleep or self.quiet or self.quit_pending

    def _speak(self, mood: str, text: str, char_ms: int) -> None:
        """Her Animalese babble for a line, if chosen; never while asleep, muted or quitting."""
        if not self.config.voice or mood == "sleep" or self._hushed():
            self.voice.stop()
            return
        self.voice.say(text, mood, self.config.voice_style, self.config.voice_volume, char_ms)

    def _effect(self, name: str) -> None:
        """A little sound for what happened to her: with her voice switched on, never in full-screen quiet."""
        if self.config.voice and not self.quiet and not self.quit_pending:
            self.voice.effect(name, self.config.voice_style, self.config.voice_volume)

    def set_voice(self, enabled: bool) -> None:
        self.config.voice = bool(enabled)
        if not self.config.voice:
            self.voice.stop()
        self._save()

    def set_voice_style(self, style: str) -> None:
        if style in voice.STYLES:
            self.config.voice_style = style
            self._save()

    def set_voice_volume(self, volume: int) -> None:
        self.config.voice_volume = min(max(int(volume), 0), 100)
        self._save()

    def preview_voice(self) -> None:
        """The settings' 「试听」: a sample line in the chosen voice, even while her voice is off (but not while hushed)."""
        if self._hushed():
            self.voice.stop()
            return
        self.voice.say(tr("主人好～我是 Claude。我会安静待在这里，偶尔看看你在忙什么。"), "happy",
                       self.config.voice_style, self.config.voice_volume, 35)

    def set_body_motion(self, enabled: bool) -> None:
        self.config.body_motion = bool(enabled)
        self.window.set_body_motion(self.config.body_motion)
        self._save()

    def set_head_motion(self, enabled: bool) -> None:
        self.config.head_motion = bool(enabled)
        self.window.set_head_motion(self.config.head_motion)
        self._save()

    def set_talk_mouth(self, enabled: bool) -> None:
        self.config.talk_mouth = bool(enabled)
        self.window.set_talk_mouth(self.config.talk_mouth)
        self._save()

    def set_walking(self, enabled: bool) -> None:
        self.config.walking = bool(enabled)
        self.walker.set_enabled(self.config.walking)
        self._save()
        if self.config.walking and not self.walker.on_floor() and not self.walker.falling:
            self._on_dropped(self.window.x(), self.window.y())  # down she goes, to walk on the bottom

    def _can_walk(self) -> bool:
        """She sets off (and keeps walking) only when nothing else is going on with her."""
        return (self.config.walking and not self.config.paused and not self.quiet and not self.asleep
                and not self.quit_pending and not self.window.full_text and self.window.mood != "sleep"
                and not self.window.grabbed)

    def _on_dropped(self, x: int, y: int) -> None:
        if self.config.walking:
            self.walker.fall_to_floor()
            if self.walker.falling:
                return  # on her way down: remembered once she lands
        self._remember_position(self.window.x(), self.window.y())

    # ---- reactions to what 主人 does with her ------------------------------
    def _react(self, kind: str, chance: float = 1.0) -> None:
        if self.quit_pending or self.quiet or self._rng.random() >= chance:
            return
        self.window.say(*self._reply_tuple(persona.interaction_line(kind, self._rng)))

    def _on_patted(self) -> None:
        self._effect("pat")  # every pat; what she says has its own cooldown
        now = self._clock()
        since = now - self._last_pat
        if since < PAT_COOLDOWN_SEC:
            return
        self._last_pat = now
        self._pat_count = 1 if since >= PAT_MEMORY_SEC else self._pat_count + 1
        self._react(("pat", "pat_shy", "pat_annoyed")[min(self._pat_count, 3) - 1])

    def _on_user_dropped(self, x: int, y: int) -> None:
        """She was dragged and let go: dragged about a lot, or carried for long, she says so."""
        now = self._clock()
        self._drops = [t for t in self._drops if now - t <= DROP_MEMORY_SEC] + [now]
        if len(self._drops) >= DROPS_TO_COMPLAIN:
            self._drops = []
            self._react("drag_many")
        elif self.window.carried_for >= LONG_CARRY_SEC:
            self._react("carry_long")
        self._on_dropped(x, y)

    def _today(self) -> datetime.date:
        stamp = time.localtime(self._now())
        return datetime.date(stamp.tm_year, stamp.tm_mon, stamp.tm_mday)

    def _greet_if_new_day(self) -> bool:
        """Her first words to 主人 today (a birthday or festival wish on those days); once a day.

        True when it is said now or held back until she may talk (the caller then says nothing else);
        False when today's hello is already done."""
        stamp = time.localtime(self._now())
        today = datetime.date(stamp.tm_year, stamp.tm_mon, stamp.tm_mday)
        if self.config.greeted_on == today.isoformat():
            self._greeting_due = ""
            return False
        if self.quit_pending or self.quiet:
            self._greeting_due = today.isoformat()  # later today, when she may talk
            return True
        self._greeting_due = ""
        line = persona.greeting_line(stamp.tm_hour, days.festival(today),
                                     days.is_birthday(today, self.config.birthday), self._rng, stamp.tm_wday)
        self.window.say(*self._reply_tuple(line))
        self.config.greeted_on = today.isoformat()
        self._save()
        return True

    def _summarize_day_if_due(self) -> None:
        """Once a day from the chosen hour, the first time she may talk: today's time per activity (from the
        companion memory) and the focus timer's periods (said even with the memory off)."""
        hour = self.config.daily_summary_hour
        if not hour:
            return
        if time.localtime(self._now()).tm_hour < hour:
            return
        today = self._today().isoformat()
        if self.config.summary_on == today:
            return
        if self.quit_pending or self.quiet or self.asleep or self.window.full_text:
            return  # later, when she may talk
        activities = self.memory.today_seconds() if self.config.companion_memory else {}
        line = persona.summary_line(activities, self._rng, self.focus_log.on(self._today()))
        if line is None:
            return  # too little yet: maybe later today
        self.config.summary_on = today
        self._save()
        self.window.say(*self._reply_tuple(line))

    def set_daily_summary(self, hour: int) -> None:
        if hour in persona.SUMMARY_HOURS:
            self.config.daily_summary_hour = hour
            self._save()

    # ---- updates -------------------------------------------------------------
    def _check_updates_if_due(self) -> None:
        if not self.config.check_updates or self.update_checking or self._clock() < self._update_from:
            return
        recent = 0 <= self._now() - self.config.update_checked_at < updates.CHECK_EVERY_SEC
        if recent and not self._update_retry:
            return  # (a check time in the future means the clock was set back: check again)
        self._start_update_check(asked=False)

    def check_updates_now(self) -> None:
        if not self.update_checking:
            self._start_update_check(asked=True)

    def _start_update_check(self, asked: bool) -> None:
        self.update_checking = True
        self.update_status = i18n.Msg("正在检查…")
        self._sync_settings()
        def check() -> None:
            try:
                version = updates.fetch_latest()
            except Exception:  # never leave the check stuck as running
                log.exception("update check crashed")
                version = None
            self.update_found.emit(version, asked)

        self._spawn(check)

    def _on_update_found(self, version: str | None, _asked: bool) -> None:
        self.update_checking = False
        if version is None:
            self._update_from = self._clock() + updates.RETRY_SEC
            self._update_retry = True
            self.update_status = i18n.Msg("检查失败（网络不通或 GitHub 暂时连不上），过一会儿会再试。")
        else:
            self._update_retry = False
            self.config.update_checked_at = self._now()
            self.config.update_latest = version
            self._save()
            self._take_update(version)
        self._sync_settings()

    def _take_update(self, version: str) -> None:
        """Show what the latest release is; a version newer than any she has told about is told once."""
        if version and updates.is_newer(version):
            self.update_available = version
            self.update_status = i18n.Msg("有新版本 v{0}", version)
            seen = self.config.update_seen
            self._update_announce = not seen or updates.is_newer(version, seen)
        else:
            self.update_available = ""
            self._update_announce = False  # (a release withdrawn meanwhile is not told)
            self.update_status = i18n.Msg("已是最新版（{0}）", __version__) if version else ""

    def _announce_update(self) -> None:
        """Tell 主人 about a new version once, when she may talk."""
        if self.quit_pending or self.quiet or self.asleep or self.window.full_text:
            return
        self._update_announce = False
        seen = self.config.update_seen
        if not seen or updates.is_newer(self.update_available, seen):  # the record only goes up
            self.config.update_seen = self.update_available
        self._save()
        where = tr("点「下载并更新」就能换上") if self._exe_path() else tr("可以打开下载页")
        self.window.say("happy", tr("主人，我有新版本 v{0} 啦～在设置 → 关于里{1}。", self.update_available, where))

    # Kept as i18n.Msg and translated when read: the about page follows a language switch.
    @property
    def update_status(self) -> str:
        return str(self._update_status)

    @update_status.setter
    def update_status(self, value: str | i18n.Msg) -> None:
        self._update_status = value

    @property
    def download_text(self) -> str:
        return str(self._download_text)

    @download_text.setter
    def download_text(self, value: str | i18n.Msg) -> None:
        self._download_text = value

    # ---- self-update (the packaged exe only) --------------------------------
    @staticmethod
    def _exe_path() -> Path | None:
        return Path(sys.executable) if getattr(sys, "frozen", False) else None

    @property
    def can_self_update(self) -> bool:
        return self._exe_path() is not None and bool(self.update_available or self.download_state)

    def _remove_update_leftovers(self) -> None:
        exe = self._exe_path()
        if exe is None:
            return
        try:
            result = updates.remove_leftovers(exe.parent)
            if result:
                log.info("last update: %s", result)
            self.download_text = i18n.Msg(UPDATE_RESULTS[result], version=__version__) if result in UPDATE_RESULTS else ""
        except OSError:
            log.exception("could not remove an old update download")
        # The restart helper waits for its note to go (that is how it knows this copy is up): if it is held
        # open right now, keep trying while she runs.
        self._update_note_retry = (exe.parent / updates.RESULT_NAME).exists()

    def _retry_update_note(self) -> None:
        exe = self._exe_path()
        if not self._update_note_retry or exe is None or self._clock() < self._update_note_retry_at:
            return
        self._update_note_retry_at = self._clock() + UPDATE_NOTE_RETRY_SEC
        self._update_note_retry = not updates.remove_note(exe.parent)

    def update_action(self) -> None:
        """The about page's button: download, cancel, or restart into the downloaded version."""
        if self.download_state == "downloading":
            self._download_cancel.set()
        elif self.download_state == "ready":
            self._offer_restart()
        elif self.update_available and self._exe_path() is not None:
            self._start_download()

    def _uses_installer(self) -> bool:
        exe = self._exe_path()
        return exe is not None and updates.uses_installer(exe, getattr(sys, "_MEIPASS", None),
                                                          os.environ.get("LOCALAPPDATA"))

    def _start_download(self) -> None:
        folder = self._exe_path().parent
        installer = self._download_installer = self._uses_installer()
        name = updates.SETUP_NAME if installer else updates.ASSET_NAME
        final_name = updates.SETUP_UPDATE_NAME if installer else updates.UPDATE_NAME
        self.download_state, self.download_text, self._download_percent = "downloading", i18n.Msg("正在准备下载…"), -1
        self._download_cancel = cancel = threading.Event()

        def run() -> None:
            try:
                asset = updates.fetch_asset(name=name)
                if asset is None:
                    self.download_done.emit(None, i18n.Msg("读不到新版的下载信息，请稍后再试，或到下载页手动下载。"))
                    return
                if not updates.is_newer(asset.version):
                    self.download_done.emit(None, i18n.Msg("已是最新版（{0}）。", __version__))
                    return
                path = updates.download(asset, folder, cancel.is_set, self.download_progress.emit,
                                        final_name=final_name)
                self._download_sha = asset.sha256
            except updates.Cancelled:
                self.download_done.emit(None, i18n.Msg("已取消下载。"))
            except PermissionError:
                self.download_done.emit(None, i18n.Msg("exe 所在的文件夹不能写入，请到下载页手动下载。"))
            except ValueError as exc:
                log.warning("update download refused: %s", exc)
                self.download_done.emit(None, i18n.Msg("下载的文件和 GitHub 公布的大小或校验值不一致，已删除。"))
            except Exception as exc:  # network and anything else: never leave the button stuck
                log.warning("update download failed: %s", exc)
                self.download_done.emit(None, i18n.Msg("下载失败（网络中断？），请稍后再试。"))
            else:
                self.download_done.emit(path, asset.version)

        self._spawn(run)
        self._sync_settings()

    def _on_download_progress(self, got: int, total: int) -> None:
        percent = got * 100 // max(1, total)
        if self.download_state != "downloading" or percent == self._download_percent:
            return
        self._download_percent = percent
        self.download_text = i18n.Msg("正在下载 {0}%（{1:.1f} / {2:.1f} MB）", percent, got / 1048576, total / 1048576)
        self._sync_settings()

    def _on_download_done(self, path, text: str) -> None:
        if path is not None and self._download_cancel.is_set():  # cancelled while the result was on its way
            text = i18n.Msg("已取消下载。")
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:  # held open (a virus scan?): removed at the next start
                log.warning("could not remove a cancelled update download", exc_info=True)
                text = i18n.Msg("已取消下载（下载的文件暂时删不掉，下次启动时会清理）。")
            path = None
        if path is None:
            self.download_state, self.download_text = "", text
            self._sync_settings()
            return
        self.download_state, self._download_path = "ready", Path(path)
        self.download_text = i18n.Msg("v{0} 已下载并校验好。", text)
        self._sync_settings()
        self._offer_restart()

    def _offer_restart(self) -> None:
        if self.quit_pending:
            return
        if self._confirm(tr("更新 Desk Sister"), tr("新版已下载并校验好。现在重启换成新版吗？\n她会先退出，几秒后自己回来。")):
            self._apply_update()
        else:
            self.download_text = i18n.Msg("新版已下载好，点「重启并更新」就会换上。")
            self._sync_settings()

    def _apply_update(self) -> None:
        exe, path = self._exe_path(), self._download_path
        try:
            intact = exe is not None and path is not None and updates.file_sha256(path) == self._download_sha
        except OSError:
            intact = False
        if not intact:  # gone or changed since it was checked: never installed
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    log.exception("could not remove a changed update download")
            self.download_state, self.download_text = "", i18n.Msg("下载的文件不见了或被改动过，请重新下载。")
            self._sync_settings()
            return
        wait = [os.getpid()]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and not updates.one_folder(exe, meipass):  # single-file: its launcher holds the exe too
            wait.append(os.getppid())
        script = updates.SETUP_SCRIPT if self._download_installer else updates.RESTART_SCRIPT
        try:
            self._launch_restart(updates.restart_env(claude_client.environ_snapshot(), exe, path,
                                                     self._download_sha, wait), script)
        except OSError as exc:
            log.warning("could not start the update helper: %s", exc)
            self.download_text = i18n.Msg("没能启动更新程序，请到下载页手动下载。")
            self._sync_settings()
            return
        log.info("restarting into the downloaded update")
        self.request_quit()

    def set_language(self, choice: str) -> None:
        """Switch her language now: the menu and an open settings window are rebuilt; lines follow at once."""
        if choice not in i18n.CHOICES:
            return
        self.config.language = choice
        self._save()
        before = i18n.current()
        if i18n.set_language(choice) != before:
            self._cancel_inflight()  # a reply on its way is in the old language: dropped, the next look asks anew
        self.tray.setContextMenu(self._build_menu())
        self._refresh_allowlist_action()
        if self.settings_window is not None:
            visible, geometry = self.settings_window.isVisible(), self.settings_window.geometry()
            self.settings_window.close()
            self.settings_window.deleteLater()
            self.settings_window = None
            if visible:
                self.open_settings()
                self.settings_window.setGeometry(geometry)
                self.settings_window.nav.setCurrentRow(0)
        self._refresh_status()

    def set_check_updates(self, enabled: bool) -> None:
        self.config.check_updates = bool(enabled)
        self._save()

    def set_birthday(self, month: int, day: int, enabled: bool) -> None:
        self.config.birthday = days.clean_birthday(f"{month:02d}-{day:02d}") if enabled else ""
        self._save()

    def _on_landed(self) -> None:
        self.window.start_body("land")  # first: a reaction that follows waits for the squash to settle
        self._effect("land")  # before her words, which carry it on
        if not self.window.full_text:
            self._react("land", 0.5)

    def _on_edge(self) -> None:
        if not self.window.full_text:
            self._react("edge", 0.25)

    def _on_resized(self) -> None:
        before, self._resize_from = self._resize_from, None
        height = self.config.sprite_height
        if before is None or height == before:
            return
        if height > before:
            self._react("max" if height >= 600 else "grow")
        else:
            self._react("min" if height <= 100 else "shrink")

    # ---- bedtime reminders ------------------------------------------------
    def _bedtime(self) -> str:
        """"" during the day; at night "ok" when one more reminder to rest is due, else "no"."""
        if not bedtime.is_night(self._hour(), self.config.night_start_hour):
            return ""
        due = bedtime.may_remind(self.config.bedtime_reminder, self._now(), self.config.bedtime_reminded_at)
        return "ok" if due else "no"

    def _note_bedtime(self, text: str) -> None:
        """Whatever she said at night about sleep or rest was the reminder: the next one waits."""
        if self._bedtime() and bedtime.mentions(text):
            self.config.bedtime_reminded_at = self._now()
            self._save()

    def set_bedtime_reminder(self, mode: str) -> None:
        if mode in bedtime.MODES:
            self.config.bedtime_reminder = mode
            self._save()

    def set_night_start(self, hour: int) -> None:
        if hour in bedtime.NIGHT_STARTS:
            self.config.night_start_hour = hour
            self._save()

    def set_self_talk(self, enabled: bool) -> None:
        self.config.self_talk = bool(enabled)
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
            line = persona.self_talk_line(self._hour(), self.asleep, list(self.self_talk_recent), self._rng,
                                          bedtime=self._bedtime())
        self.self_talk_recent.append(line.text)
        self._note_bedtime(line.text)
        self.window.say(line.mood, line.text)
        return True

    # ---- how Claude is called ------------------------------------------
    @staticmethod
    def _ask_secret_dialog(title: str, label: str) -> tuple[str, bool]:
        return QInputDialog.getText(None, title, label, QLineEdit.EchoMode.Password)

    def _provider(self, provider_id: str | None = None) -> providers.Provider:
        return PROVIDERS.get(provider_id or self.config.backend, PROVIDERS["subscription"])

    def _has_key(self, provider_id: str | None = None) -> bool:
        provider = self._provider(provider_id)
        if not provider.needs_key:
            return False
        try:
            return bool(self._load_key(provider.vault_entry))
        except OSError:
            return False

    def set_backend(self, backend: str, _checked: bool = True) -> None:
        if backend == self.config.backend or backend not in PROVIDERS:
            self._sync_settings()
            return
        provider = PROVIDERS[backend]
        if provider.paid:
            text = (tr("要改用你自己的 {0} API Key 吗？\n\nAPI 按用量收费，费用记在这个 Key 所属的 {1} 账户上。她每次看屏幕或回答都会调用一次 API，截图会发给这家公司；评论间隔越短、选「更聪明」的模型，花费越多。\n\nKey 只保存在本机的 Windows 凭据管理器里，不会写进配置文件或日志。", provider.company, provider.company))
            if not self._confirm(tr("切换到 {0}", provider.label), text):
                self._sync_settings()
                return
            if not self._has_key(backend) and not self.set_api_key(backend):
                self._sync_settings()
                return
        elif provider.kind == CODEX_CLI:
            if not self.codex:
                self._sync_settings()
                self._find_codex(("switch",))  # searched off the UI thread; asks again once found
                return
            text = (tr("要改用 Codex（你自己的 ChatGPT 订阅）吗？\n\n她会通过本机已登录的 Codex CLI 思考，只接受 ChatGPT 订阅登录，不会改用 API Key 计费。Codex 的命令、浏览器、电脑操作等工具都会被关闭。\n\n注意：Codex CLI 只能从文件读取图片，所以每次看屏幕时，截图会短暂写入你自己的临时文件夹，调用结束（包括失败或取消）后删除；若文件正被别的程序占用，会保留到能删时为止，桌宠每秒、退出和启动时都会重试。其他调用方式的截图只在内存里。\n\n用订阅额度运行第三方程序以 OpenAI 现行条款为准。"))
            if not self._confirm(tr("切换到 Codex（ChatGPT 订阅）"), text):
                self._sync_settings()
                return
        self._cancel_inflight()  # a request of the old kind must not come back
        self.config.backend = backend
        self.auth_ok_until = 0.0  # the next call checks the new login
        self.last_error = ""
        self.consecutive_failures = 0
        self.auto_paused_until = 0.0
        self._save()
        self._sync_settings()
        self._refresh_status()
        if provider.paid:
            self.window.say("happy", tr("好的，之后我用主人的 {0} API Key 来思考～（按量计费，记得留意用量哦）", provider.company))
        elif provider.kind == CODEX_CLI:
            self.window.say("happy", tr("好的，之后我借 Codex 的 ChatGPT 订阅来思考～"))
        else:
            self.window.say("happy", tr("好的，之后我用 Claude Code 的订阅登录来思考～"))

    def set_custom_model(self, provider_id: str, model_id: str) -> bool:
        """A model ID that overrides the tier for one provider ("" goes back to the presets)."""
        model_id = model_id.strip()
        if provider_id not in PROVIDERS or (model_id and not providers.MODEL_ID.match(model_id)):
            self.window.say("think", tr("这个模型名看起来不对呢……（只能有字母、数字和 . _ - : / @）我没有改。"))
            return False
        models = dict(self.config.custom_models)
        if model_id:
            models[provider_id] = model_id
        else:
            models.pop(provider_id, None)
        if models == self.config.custom_models:
            return True
        if provider_id == self.config.backend:
            self._cancel_inflight()
        self.config.custom_models = models
        self._save()
        return True

    def set_api_key(self, provider_id: str | None = None) -> bool:
        """Ask for a key and keep it in Windows Credential Manager. True when one was saved."""
        provider = self._provider(provider_id)
        if not provider.needs_key:
            self.window.say("think", tr("现在的调用方式用的是订阅登录，不需要 API Key 哦。"))
            return False
        key, ok = self._ask_secret(tr("设置 {0} API Key", provider.company),
                                   tr("粘贴你的 {0} API Key（只保存在本机 Windows 凭据管理器）：", provider.company))
        key = (key or "").strip()
        if not ok or not key:
            return False
        if not api_client.looks_like_key(key):
            self.window.say("think", tr("这串看起来不像 API Key 呢……（不能有空格或中文）我没有保存。"))
            return False
        try:
            self._save_key(key, provider.vault_entry)
        except OSError as exc:
            log.warning("could not save the API key: %s", exc)
            self.window.say("sad", tr("没能保存 API Key：{0}", exc))
            return False
        self.last_error = ""
        self._refresh_status()
        self._sync_settings()  # the key lives outside config.json, so no save announces it
        self.window.say("happy", tr("API Key 收好啦，锁在 Windows 凭据管理器里～"))
        return True

    def clear_api_key(self, provider_id: str | None = None) -> None:
        provider = self._provider(provider_id)
        if not provider.needs_key:
            self.window.say("think", tr("现在的调用方式用的是订阅登录，没有保存 API Key。"))
            return
        try:
            removed = self._delete_key(provider.vault_entry)
        except OSError as exc:
            self.window.say("sad", tr("没能清除 API Key：{0}", exc))
            return
        current = provider.id == self.config.backend
        if current:
            self._cancel_inflight()
        self._sync_settings()
        tail = tr("（现在正用它，要再设置一个 Key 才能继续看屏幕）") if current else ""
        self.window.say("happy", (tr("已经清除保存的 API Key。") if removed else tr("本来就没有保存 API Key 哦。")) + tail)

    def set_model(self, model: str, _checked: bool = True) -> None:
        self.config.model = model
        self._save()

    def _remember_position(self, x: int, y: int) -> None:
        self.config.x, self.config.y = x, y
        self._save()

    def _refresh_status(self) -> None:
        if self._clock() < self._size_shown_until and not self.last_error and not self.auto_paused_until:
            # Just resized with Ctrl + wheel: show the height for a moment over any state but an error.
            self.window.set_status(tr("身高 {0} 像素", self.config.sprite_height))
        elif self.config.paused:
            self.window.set_status(tr("已暂停"))
        elif self.busy:
            self.window.set_status(tr("思考中…"))
        elif self.quiet:
            held = self.deferred is not None or self.deferred_notice is not None
            self.window.set_status(tr("全屏中，先不打扰") + (tr("（攒了一句）") if held else ""))
        elif self.auto_paused_until:
            resume = time.strftime("%H:%M", time.localtime(time.time() + max(0.0, self.auto_paused_until - self._clock())))
            reason = tr("｜原因：{0}", self.last_error) if self.last_error else ""
            self.window.set_status(tr("连续失败 {0} 次，{1} 前不自动看{2}", self.consecutive_failures, resume, reason))
        elif self.last_error:
            self.window.set_status(tr("原因：") + self.last_error)
        elif self.config.claude_link and self.claude_state.status():
            self.window.set_status(self.claude_state.status())
        elif self.asleep:
            self.window.set_status(tr("睡着了…动一下鼠标叫醒她"))
        else:
            self.window.set_status("")
        timer = self._timer_status()
        if timer:
            self.window.set_status(f"{timer}｜{self.window.status}" if self.window.status else timer)

    def open_log_folder(self) -> None:
        folder = app_data_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._open_path(str(folder))
        except OSError as exc:
            log.warning("could not open log folder: %s", exc)
            self.window.say("sad", tr("打不开日志文件夹：{0}", folder))

    def _save(self) -> None:
        try:
            save_config(self.config, self.config_file)
        except OSError:
            log.exception("could not save config")
        self._sync_settings()

    # ---- settings window ---------------------------------------------------
    def open_settings(self) -> None:
        if self.settings_window is None:
            from .settings_window import SettingsWindow  # Qt widgets only when first needed

            self.settings_window = SettingsWindow(self)
        self._refresh_autostart()  # it may have been changed in Task Manager meanwhile
        self.settings_window.refresh()
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _sync_settings(self) -> None:
        """A change from the menu (or anywhere) shows up in an open settings window too."""
        if self.settings_window is not None and self.settings_window.isVisible():
            self.settings_window.refresh()

    def set_rules(self, kind: str, rules: list[str]) -> None:
        """Replace the blocklist or allowlist (settings window). Empty and duplicate entries are dropped."""
        if kind not in ("blocklist", "allowlist"):
            raise ValueError(kind)
        cleaned: list[str] = []
        for rule in rules:
            rule = rule.strip()
            if rule and rule.casefold() not in {r.casefold() for r in cleaned}:
                cleaned.append(rule)
        if cleaned == getattr(self.config, kind):
            return
        self._cancel_inflight()  # a job started under the old rules must not upload anything
        setattr(self.config, kind, cleaned)
        self._save()

    def set_quiet_fullscreen(self, enabled: bool) -> None:
        self.config.quiet_fullscreen = bool(enabled)
        self._update_quiet()
        self._save()

    def set_dwell(self, seconds: int) -> None:
        self.config.dwell_sec = min(max(int(seconds), 0), 600)
        self._save()

    def set_self_talk_range(self, min_sec: int, max_sec: int) -> None:
        low = min(max(int(min_sec), 30), 3600)
        self.config.self_talk_min_sec = low
        self.config.self_talk_max_sec = min(max(int(max_sec), low), 7200)
        self._schedule_self_talk()
        self._save()

    def set_sleep_after(self, seconds: int) -> None:
        self.config.sleep_after_sec = min(max(int(seconds), 60), 86400)
        self._save()

    def resize_by_wheel(self, notches: int) -> None:
        """Ctrl + wheel over her: 10 px a notch, the same path as the settings slider."""
        height = min(max(self.config.sprite_height + 10 * notches, 100), 600)
        if height != self.config.sprite_height:
            self.set_sprite_height(height)
        self._size_shown_until = self._clock() + SIZE_SHOWN_SEC
        self._refresh_status()
        QTimer.singleShot(int(SIZE_SHOWN_SEC * 1000) + 100, self._refresh_status)

    def set_sprite_height(self, height: int) -> None:
        self.walker.stop()  # a new size changes the window's width: she stands still for it
        if self._resize_from is None:
            self._resize_from = self.config.sprite_height
        self._resize_done.start()  # she says something once the resizing has settled
        self.config.sprite_height = min(max(int(height), 100), 600)
        self.window.set_sprite_height(self.config.sprite_height)
        self._remember_position(self.window.x(), self.window.y())  # saves too

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
