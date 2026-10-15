"""Claude Code link: the pet reacts to what Claude Code is doing.

Idea from dsh-pet-indesktop's agent link (MIT; no code copied). Claude Code hooks append one line,
"<event name> <session id>", to %APPDATA%/ClaudePet/agent-events/claude.log. The hook reads the
event JSON from stdin only in memory and only to pull out the session id; prompts, code, commands
and file contents are never written anywhere. Tool categories come from hook matchers.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

EVENT_FILE_REL = r"ClaudePet\agent-events\claude.log"  # under %APPDATA%
MAX_EVENT_FILE = 256 * 1024
ORDER_RE = re.compile(r"^[0-9]{1,20}\Z")  # ASCII digits only ("²" is a digit to str.isdigit)
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")  # as the hook writes it; "-" = none

_OWN_TOOLS = "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell|Read|Grep|Glob|LS|WebFetch|WebSearch|Task|Agent"
# (hook event, matcher or None, label written to the event file)
HOOK_SPECS = [
    ("SessionStart", None, "start"),
    ("UserPromptSubmit", None, "prompt"),
    ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit", "edit"),
    ("PreToolUse", "Bash|PowerShell", "run"),
    ("PreToolUse", "Read|Grep|Glob|LS", "read"),
    ("PreToolUse", "WebFetch|WebSearch", "web"),
    ("PreToolUse", "Task|Agent", "agent"),
    ("PreToolUse", f"^(?!({_OWN_TOOLS})$)", "tool"),  # any other tool (regex: not one of the above)
    # A tool finished (also after the user approved it): no longer waiting for approval.
    ("PostToolUse", None, "after"),
    ("PostToolUseFailure", None, "after"),
    ("Notification", "permission_prompt", "permission"),
    ("Notification", "idle_prompt|agent_needs_input", "waiting"),
    ("Stop", None, "done"),
    ("StopFailure", None, "error"),
    ("SessionEnd", None, "end"),
]
LABELS = {label for _e, _m, label in HOOK_SPECS}
_TURN_ENDS = {"done", "error", "end"}


class HooksError(Exception):
    pass


class _CreatedMeanwhile(Exception):
    """settings.json appeared between our check and our create: treat it like a concurrent save."""


class SettingsFormatError(HooksError):
    """settings.json cannot be used as it is. `reason` says why, without claiming what was written."""

    def __init__(self, path: Path, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{path.name} {reason}，没有修改它")


def claude_settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def hook_handler(label: str) -> dict:
    """Exec form (no shell; works without Git Bash), async so Claude Code never waits for it.

    stdin is read as UTF-8 and parsed as JSON in memory; only the top-level "session_id" of a JSON
    object is used, in any key order, so text inside a prompt or tool input can never be picked up.
    If parsing fails, the id is taken only when the JSON *starts* with that key (\x22 is a double quote).
    The script contains no double quotes, so no command-line quoting layer can change it.

    Line: "<label> <session or -> <process start time>". Hooks run async and may finish out of order;
    the start time follows the order Claude Code fired them, so a late older event can be dropped.
    """
    script = (
        "$t = [Diagnostics.Process]::GetCurrentProcess().StartTime.ToFileTimeUtc(); "
        "$r = New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8); "
        "$i = $r.ReadToEnd(); $s = '-'; $p = '^[A-Za-z0-9_-]{8,80}\\z'; "
        "try { $o = ConvertFrom-Json $i; "
        "if ($i.TrimStart().StartsWith('{') -and $o.GetType().Name -ceq 'PSCustomObject' "
        "-and $o.session_id -is [string] -and $o.session_id -cmatch $p) { $s = $o.session_id } } "
        "catch { if ($i -match '^\\s*\\{\\s*\\x22session_id\\x22\\s*:\\s*\\x22([A-Za-z0-9_-]{8,80})\\x22') "
        "{ $s = $Matches[1] } }; "
        f"Add-Content -LiteralPath (Join-Path $env:APPDATA '{EVENT_FILE_REL}') -Value ('{label} ' + $s + ' ' + $t)"
    )
    return {
        "type": "command",
        "command": "powershell.exe",
        "args": ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        "async": True,
        "timeout": 15,
    }


def _legacy_handler_v4(label: str) -> dict:
    script = (
        "$r = New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8); "
        "$i = $r.ReadToEnd(); $s = ''; $p = '^[A-Za-z0-9_-]{8,80}\\z'; "
        "try { $o = ConvertFrom-Json $i; "
        "if ($i.TrimStart().StartsWith('{') -and $o.GetType().Name -ceq 'PSCustomObject' "
        "-and $o.session_id -is [string] -and $o.session_id -cmatch $p) { $s = $o.session_id } } "
        "catch { if ($i -match '^\\s*\\{\\s*\\x22session_id\\x22\\s*:\\s*\\x22([A-Za-z0-9_-]{8,80})\\x22') "
        "{ $s = $Matches[1] } }; "
        f"Add-Content -LiteralPath (Join-Path $env:APPDATA '{EVENT_FILE_REL}') -Value ('{label} ' + $s)"
    )
    return {"type": "command", "command": "powershell.exe",
            "args": ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            "async": True, "timeout": 15}


def _legacy_handler_v3(label: str) -> dict:
    script = (
        "$i = [Console]::In.ReadToEnd(); $s = ''; "
        "if ($i -match '^\\s*\\{\\s*\\x22session_id\\x22\\s*:\\s*\\x22([A-Za-z0-9_-]{8,80})\\x22') "
        "{ $s = $Matches[1] }; "
        f"Add-Content -LiteralPath (Join-Path $env:APPDATA '{EVENT_FILE_REL}') -Value ('{label} ' + $s)"
    )
    return {"type": "command", "command": "powershell.exe",
            "args": ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            "async": True, "timeout": 15}


def _legacy_handler_v1(label: str) -> dict:
    script = f"Add-Content -LiteralPath (Join-Path $env:APPDATA '{EVENT_FILE_REL}') -Value '{label}'"
    return {"type": "command", "command": "powershell.exe",
            "args": ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            "async": True, "timeout": 15}


def _legacy_handler_v2(label: str) -> dict:
    script = (
        "$i = [Console]::In.ReadToEnd(); $s = ''; "
        "if ($i -match 'session_id\\W{1,4}([A-Za-z0-9_-]{8,80})') { $s = $Matches[1] }; "
        f"Add-Content -LiteralPath (Join-Path $env:APPDATA '{EVENT_FILE_REL}') -Value ('{label} ' + $s)"
    )
    return {"type": "command", "command": "powershell.exe",
            "args": ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            "async": True, "timeout": 15}


_OURS = [make(label) for make in (hook_handler, _legacy_handler_v1, _legacy_handler_v2, _legacy_handler_v3,
                                              _legacy_handler_v4) for label in sorted(LABELS)]


def _is_ours(handler: object) -> bool:
    """Only a handler identical to one we write counts as ours; anything else is the user's."""
    return isinstance(handler, dict) and handler in _OURS


def _parse(raw: bytes | None, path: Path) -> dict:
    if raw is None:
        return {}
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SettingsFormatError(path, f"不是有效的 JSON（{exc}）") from exc
    if not isinstance(data, dict):
        raise SettingsFormatError(path, "的内容不是 JSON 对象")
    hooks = data.get("hooks", {})
    shape_ok = isinstance(hooks, dict) and all(
        isinstance(groups, list) and all(
            isinstance(group, dict)
            and isinstance(group.get("hooks"), list)
            and all(isinstance(h, dict) for h in group["hooks"])
            and isinstance(group.get("matcher", ""), str)
            for group in groups
        )
        for groups in hooks.values()
    )
    if not shape_ok:
        raise SettingsFormatError(path, "里的 hooks 格式不是预期的样子")
    return data


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HooksError(f"读不了 {path}：{exc}") from exc


def _strip_ours(data: dict) -> bool:
    """Remove our handlers (and groups/events left empty). True if anything changed."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    changed = False
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group["hooks"] if not _is_ours(h)]
            if len(kept) != len(group["hooks"]):
                changed = True
                if not kept:
                    continue
                group = {**group, "hooks": kept}
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if changed and not hooks:
        del data["hooks"]
    return changed


def _add_ours(data: dict) -> bool:
    _strip_ours(data)
    hooks = data.setdefault("hooks", {})
    for event, matcher, label in HOOK_SPECS:
        group = {"hooks": [hook_handler(label)]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)
    return True


_settings_lock = threading.Lock()


BACKUP_KEEP = 5


def _backups(path: Path) -> list[Path]:
    """Our backups in the current naming (20-digit nanosecond stamp), oldest first. Other names are left alone."""
    prefix = path.name + ".claude-pet-backup-"
    found = [b for b in path.parent.glob(prefix + "*")
             if re.fullmatch(r"[0-9]{20}", b.name[len(prefix):])]  # ASCII only: isdigit() also takes "²", "１"
    return sorted(found, key=lambda b: int(b.name[len(prefix):]))


def _new_backup_path(path: Path) -> Path:
    """Zero-padded nanosecond stamps: names sort chronologically and a newer one is never reused."""
    newest = _backups(path)
    stamp = time.time_ns()
    if newest:
        stamp = max(stamp, int(newest[-1].name.rsplit("-", 1)[-1]) + 1)
    while True:
        candidate = path.with_name(f"{path.name}.claude-pet-backup-{stamp:020d}")
        if not candidate.exists():
            return candidate
        stamp += 1


def _prune_backups(path: Path) -> None:
    for old in _backups(path)[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _swap(path: Path, temp: Path, backup: Path) -> None:
    """Atomically put temp in place of path; the replaced file becomes backup (Windows: ReplaceFileW)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        replace_file = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
        replace_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                 ctypes.c_void_p, ctypes.c_void_p]
        replace_file.restype = wintypes.BOOL
        if not replace_file(str(path), str(temp), str(backup), 0, None, None):
            raise OSError(ctypes.get_last_error(), "ReplaceFileW failed")
        return
    backup.write_bytes(path.read_bytes())
    os.replace(temp, path)


def _before_replace(path: Path) -> None:
    """Test seam: called after the stale check, right before the file is replaced."""


def _before_commit(path: Path) -> None:
    """Test seam: called after the new content is prepared, right before the stale check."""


def _commit(path: Path, content: bytes) -> tuple[bytes | None, Path | None]:
    """Write content in place of path. Returns (bytes actually replaced, the backup holding them)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".claude-pet.tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:  # bytes: no newline translation, so it compares exactly
            handle.write(content)
        if not path.exists():
            _before_replace(path)
            try:
                os.rename(temp, path)  # unlike os.replace, never overwrites a file someone just created
            except FileExistsError as exc:
                raise _CreatedMeanwhile() from exc
            return None, None
        backup = _new_backup_path(path)
        _before_replace(path)
        _swap(path, temp, backup)
        # 2. The swap succeeded: settings.json HAS changed. If the backup cannot be read, say so truthfully.
        for wait in (0, 0.2, 0.5, 1.0):
            time.sleep(wait)
            try:
                return backup.read_bytes(), backup
            except OSError as exc:
                last = exc
        raise HooksError(f"{path.name} 已被桌宠改动，但读不了被替换的版本（{last}）；它保存在 {backup}，请检查")
    finally:
        if temp.exists():
            temp.unlink()


def _render(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _modify(path: Path, change) -> tuple[bool, Path | None]:
    """Read, change and replace settings.json without silently losing another program's save.

    - Before replacing: if the file changed since it was read, redo the change on the new version.
    - After replacing: the replaced version is in its own new backup file. If it was not the version
      we read, someone saved in between; apply our change to their version and replace again.
    - Backups are never deleted mid-way; if recovery cannot finish, the error names the backup.
    Returns (changed, backup of the user's version that was replaced).
    """
    with _settings_lock:
        base = _read(path)
        for _attempt in range(3):
            data = _parse(base, path)
            if not change(data):
                return False, None
            written = _render(data)
            _before_commit(path)
            current = _read(path)
            if current != base:
                base = current  # someone saved meanwhile: redo on their version
                continue
            try:
                replaced, backup = _commit(path, written)
            except _CreatedMeanwhile:
                base = _read(path)  # someone created it first: redo on their version
                continue
            if replaced == base:
                _prune_backups(path)
                return True, backup
            # A save slipped in between the check and the replace. Their version is safe in its backup and
            # the file now holds what we wrote; apply our change to their version and swap again.
            theirs, theirs_backup, ours_on_disk = replaced, backup, written
            try:
                data = _parse(theirs, path)
                change(data)
                restored = _render(data)
                if _read(path) != ours_on_disk:
                    raise HooksError("文件又被改动了")
                try:
                    replaced, newer_backup = _commit(path, restored)
                except _CreatedMeanwhile as exc:
                    raise HooksError("文件被删除后又被重新创建") from exc
                if replaced == ours_on_disk:
                    if newer_backup is not None:
                        try:
                            newer_backup.unlink()  # it only held our own intermediate write
                        except OSError:
                            pass  # harmless leftover; the commit itself succeeded
                    _prune_backups(path)
                    return True, theirs_backup
                # Yet another save, made on top of our intermediate version: it may lack the first save's
                # change, so merging it blindly could lose that. Stop and name both versions.
                raise HooksError(f"又有程序保存了一次，那次的版本在 {newer_backup}")
            except (HooksError, OSError, ValueError) as exc:
                # The file WAS changed by us; say so, and where the other program's version is kept.
                detail = exc.reason if isinstance(exc, SettingsFormatError) else exc
                raise HooksError(
                    f"{path.name} 已被桌宠改动，但同时有其他程序保存了它，未能把两边合并（{detail}）。"
                    f"那个程序保存的版本在 {theirs_backup}，请对照检查。"
                ) from exc
        raise HooksError(f"{path.name} 一直在被其他程序修改，没有改动它，稍后再试")


def is_installed(path: Path) -> bool:
    try:
        data = _parse(_read(path), path)
    except HooksError:
        return False
    return any(_is_ours(h) for groups in data.get("hooks", {}).values() for g in groups for h in g["hooks"])


def install_hooks(path: Path) -> Path | None:
    """Add our hooks (idempotent). Returns the backup of the replaced file (None if there was none)."""
    return _modify(path, _add_ours)[1]


def uninstall_hooks(path: Path) -> bool:
    """Remove only our hooks. True if the file was changed (the replaced version is backed up)."""
    return _modify(path, _strip_ours)[0]


class EventTail:
    """Reads "<label> <session> <order>" lines appended since the last call (starts at the current end).
    Events of a session that were fired before one already handled are dropped (hooks finish out of order).

    A large file is rotated by rename, never truncated in place: Windows refuses to rename a file a
    hook is still writing, and whatever reached the old file before the rename is read from it.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.offset = path.stat().st_size
        except OSError:
            self.offset = 0
        self._partial = b""
        # Per session: start time of the newest hook process handled, and whether it ended the turn.
        self._latest: dict[str, tuple[int, bool]] = {}
        self.rotated = self.path.with_name(self.path.name + ".1")
        self._pending_rotated: int | None = None  # read offset in the rotated file, while unread data remains
        self._rotated_cleanup = False  # read completely, but not deleted yet
        try:
            self.rotated.unlink()  # leftovers from an earlier run are old news
        except OSError:
            pass

    def _read_from(self, path: Path, start: int) -> bytes:
        with path.open("rb") as handle:
            handle.seek(start)
            return handle.read()

    def _parse(self, chunk: bytes) -> list[tuple[str, str]]:
        lines = (self._partial + chunk).split(b"\n")
        self._partial = lines.pop()  # incomplete last line (no newline yet)
        events = []
        for raw in lines:
            parts = raw.decode("utf-8", "replace").strip().lstrip("﻿").split()
            if not parts or parts[0] not in LABELS:
                continue
            session = parts[1] if len(parts) > 1 and SESSION_RE.match(parts[1]) else ""
            order = int(parts[2]) if len(parts) > 2 and ORDER_RE.match(parts[2]) else 0
            if session and order:
                latest, ended = self._latest.get(session, (0, False))
                final = parts[0] in _TURN_ENDS
                if order < latest or (order == latest and ended and not final):
                    continue  # fired before (or with) an event of this session already handled: stale
                self._latest.pop(session, None)
                # newest last, so the oldest sessions are dropped first; a tie never undoes an end
                self._latest[session] = (order, final or (order == latest and ended))
                while len(self._latest) > 500:
                    del self._latest[next(iter(self._latest))]
            events.append((parts[0], session))
        return events

    def _cleanup_rotated(self) -> None:
        if not self._rotated_cleanup:
            return
        try:
            self.rotated.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return  # try again later; its events were already delivered
        self._rotated_cleanup = False

    def read_new(self) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if self._pending_rotated is not None:  # finish the old file first, keeping the order
            try:
                chunk = self._read_from(self.rotated, self._pending_rotated)
            except OSError:
                return []  # retry next time; nothing is lost or reordered
            events = self._parse(chunk)
            self._pending_rotated, self._rotated_cleanup = None, True
        self._cleanup_rotated()
        try:
            size = self.path.stat().st_size
        except OSError:
            return events
        if size < self.offset:  # replaced by someone else
            self.offset, self._partial = 0, b""
        if size > self.offset:
            try:
                chunk = self._read_from(self.path, self.offset)
            except OSError:
                return events
            self.offset += len(chunk)
            events += self._parse(chunk)
        if self.offset > MAX_EVENT_FILE and not self._partial and not self._rotated_cleanup:
            try:
                os.replace(self.path, self.rotated)
            except OSError:
                return events  # a hook is writing right now; rotate on a later call
            self._pending_rotated, self.offset = self.offset, 0
            try:
                chunk = self._read_from(self.rotated, self._pending_rotated)  # appended before the rename
            except OSError:
                return events  # kept pending: read again (from the same offset) on the next call
            events += self._parse(chunk)
            self._pending_rotated, self._rotated_cleanup = None, True
            self._cleanup_rotated()
        return events


WORKING_TEXT = {
    "edit": "Claude Code 在改文件…",
    "run": "Claude Code 在跑命令…",
    "read": "Claude Code 在读代码…",
    "web": "Claude Code 在查资料…",
    "agent": "Claude Code 派出了子代理…",
    "tool": "Claude Code 在用工具…",
}
NOTICES = {
    "permission": ("panic", "主人主人，Claude Code 妹妹在等你批准操作！"),
    "waiting": ("talk", "Claude Code 妹妹在等你回话哦～"),
    "done": ("happy", "Claude Code 妹妹那边做完啦，去看看吧～"),
    "error": ("sad", "Claude Code 妹妹那边好像出错了……去看一眼吧。"),
}
DONE_MIN_SEC = 20  # only announce turns that took a while
STALE_SEC = 600    # no event for this long while not idle: assume it is over


@dataclass
class Notice:
    kind: str  # permission | waiting | done | error
    mood: str
    text: str


class SessionState:
    """What one Claude Code session is doing."""

    def __init__(self) -> None:
        self.phase = "idle"  # idle | thinking | working | permission | waiting
        self.activity = ""
        self.turn_started = 0.0
        self.last_event = 0.0

    @property
    def busy(self) -> bool:
        return self.phase in ("thinking", "working")

    def feed(self, label: str, now: float) -> list[Notice]:
        self.last_event = now
        notices: list[Notice] = []
        if label == "prompt":
            self.phase, self.activity, self.turn_started = "thinking", "", now
        elif label in WORKING_TEXT:
            if not self.turn_started:
                self.turn_started = now
            self.phase, self.activity = "working", label
        elif label == "after":
            # A tool just finished, so a turn is running (also when it was waiting for approval, or when
            # this turn's prompt arrived late and was dropped). EventTail already dropped any "after"
            # fired before this session's last done/end, so a finished turn is never revived.
            if not self.turn_started:
                self.turn_started = now
            if self.phase != "working":
                self.phase = "working"
        elif label in ("permission", "waiting"):
            if self.phase != label:
                notices.append(Notice(label, *NOTICES[label]))
            self.phase = label
        elif label == "done":
            if self.turn_started and now - self.turn_started >= DONE_MIN_SEC:
                notices.append(Notice("done", *NOTICES["done"]))
            self.phase, self.activity, self.turn_started = "idle", "", 0.0
        elif label == "error":
            notices.append(Notice("error", *NOTICES["error"]))
            self.phase, self.activity, self.turn_started = "idle", "", 0.0
        elif label in ("start", "end"):
            self.phase, self.activity, self.turn_started = "idle", "", 0.0
        return notices

    def status(self) -> str:
        if self.phase == "thinking":
            return "Claude Code 在思考…"
        if self.phase == "working":
            return WORKING_TEXT.get(self.activity, "Claude Code 在干活…")
        if self.phase == "permission":
            return "Claude Code 在等你批准"
        if self.phase == "waiting":
            return "Claude Code 在等你回话"
        return ""


class ClaudeCodeState:
    """All Claude Code sessions, each tracked on its own; busy if any session is."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.last_session = ""

    @property
    def busy(self) -> bool:
        return any(s.busy for s in self.sessions.values())

    def feed(self, label: str, now: float, session: str = "") -> list[Notice]:
        if not session:
            # Source unknown (the event JSON did not start with session_id): it must not reset or end any
            # known session, so only the things the user should hear about are kept.
            return [Notice(label, *NOTICES[label])] if label in ("permission", "waiting", "error") else []
        key = session
        state = self.sessions.setdefault(key, SessionState())
        notices = state.feed(label, now)
        self.last_session = key
        if label == "end":
            del self.sessions[key]
        return notices

    def still_relevant(self, kind: str, session: str) -> bool:
        """A held permission/waiting notice is stale once its session has moved on (or ended)."""
        if kind not in ("permission", "waiting") or not session:
            return True
        state = self.sessions.get(session)
        return state is not None and state.phase == kind

    def tick(self, now: float) -> None:
        for key, state in list(self.sessions.items()):
            if now - state.last_event > STALE_SEC:
                del self.sessions[key]  # silent for long: over (and forgotten)

    def status(self) -> str:
        """Waiting for the user wins; then the most recently active busy session; then any busy one."""
        for phase in ("permission", "waiting"):
            for state in self.sessions.values():
                if state.phase == phase:
                    return state.status()
        recent = self.sessions.get(self.last_session)
        if recent is not None and recent.busy:
            return recent.status()
        busy = [s for s in self.sessions.values() if s.busy]
        return max(busy, key=lambda s: s.last_event).status() if busy else ""
