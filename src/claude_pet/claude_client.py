"""Calls the local Claude Code CLI (`claude -p`) on the user's existing subscription.

The image travels inside a stream-json user message, so the CLI needs no tools at all:
every tool is disabled and no customisations (CLAUDE.md, hooks, MCP, plugins) are loaded.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

# Anything that could route the CLI to a paid backend (API keys, Bedrock/Vertex/Foundry, custom endpoints)
# is removed from the child environment; only the subscription login remains usable.
_STRIP_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_SKIP_", "OPENAI_", "AZURE_OPENAI_")
_STRIP_NAMES = ("AWS_BEARER_TOKEN_BEDROCK", "CODEX_API_KEY")  # the Codex CLI must use the ChatGPT login too
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class ClaudeResult:
    ok: bool
    text: str = ""
    error: str = ""
    timed_out: bool = False
    cancelled: bool = False
    not_subscription: bool = False
    no_api_key: bool = False  # API Key mode: no key saved yet
    bad_api_key: bool = False  # API Key mode: the key was rejected


def _version_key(path: Path) -> tuple[int, ...]:
    for part in path.parts[::-1]:
        if re.fullmatch(r"\d+(\.\d+)+", part):
            return tuple(int(n) for n in part.split("."))
    return (0,)


def find_claude(configured: str = "") -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude.exe",
        home / "ai-dev-factory" / "tools" / "claude" / "claude.exe",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        bundled = sorted((Path(appdata) / "Claude" / "claude-code").glob("*/*/claude.exe"), key=_version_key, reverse=True)
        candidates.extend(bundled)
    return next((str(c) for c in candidates if c.is_file()), None)


def _prefix(executable: str | list[str]) -> list[str]:
    return [executable] if isinstance(executable, str) else list(executable)


def build_args(executable: str | list[str], model: str, system_prompt: str) -> list[str]:
    return _prefix(executable) + [
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--tools", "",
        "--safe-mode",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--model", model,
        "--system-prompt", system_prompt,
    ]


def build_message(text: str, jpeg: bytes | None = None) -> str:
    content: list[dict] = []
    if jpeg:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")},
        })
    content.append({"type": "text", "text": text})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False) + "\n"


def parse_stream(stdout: str) -> ClaudeResult:
    """Return the final `result` event; assistant text is a fallback if the CLI died before it."""
    assistant: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                return ClaudeResult(False, error=str(event.get("result") or event.get("subtype") or "error"))
            return ClaudeResult(True, text=str(event.get("result") or ""))
        if event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    assistant.append(block.get("text", ""))
    if assistant:
        return ClaudeResult(True, text="".join(assistant))
    return ClaudeResult(False, error="no result in CLI output")


ENV_LOCK = threading.Lock()  # held by anything that changes os.environ for a moment or copies it


def environ_snapshot() -> dict[str, str]:
    with ENV_LOCK:  # never a half-changed environment (an API client may hide OPENAI_* meanwhile)
        return dict(os.environ)


def child_env() -> dict[str, str]:
    env = {
        k: v for k, v in environ_snapshot().items()
        if not k.upper().startswith(_STRIP_PREFIXES) and k.upper() not in _STRIP_NAMES
    }
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


def _parse_auth_status(stdout: str) -> tuple[bool, str]:
    try:
        status = json.loads(stdout)
    except ValueError:
        return False, "auth status unreadable"
    if not isinstance(status, dict) or not status.get("loggedIn"):
        return False, "not logged in"
    if status.get("authMethod") != "claude.ai" or status.get("apiProvider") != "firstParty":
        return False, f"auth {status.get('authMethod')}/{status.get('apiProvider')} is not a claude.ai subscription"
    return True, ""


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _CREATE_SUSPENDED = 0x4
    _PROCESS_ACCESS = 0x0001 | 0x0100 | 0x0800  # TERMINATE | SET_QUOTA | SUSPEND_RESUME
    _JOB_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_KILL_ON_CLOSE = 0x2000

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit), ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _spawn(args: list[str], cwd: str | None, cancelled: threading.Event) -> tuple[subprocess.Popen, int | None]:
        """Start suspended, put the process in a kill-on-close Job Object, then resume it.

        Every descendant (e.g. the real CLI started by a claude.cmd launcher) joins the job,
        so terminating or closing the job ends the whole tree even after the launcher exits.
        A cancel that arrives while CreateProcess is slow is honoured before the process ever runs.
        """
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
        if not _k32.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            _k32.CloseHandle(job)
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        try:
            proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", env=child_env(), cwd=cwd,
                creationflags=_NO_WINDOW | _CREATE_SUSPENDED,
            )
        except OSError:
            _k32.CloseHandle(job)
            raise
        handle = _k32.OpenProcess(_PROCESS_ACCESS, False, proc.pid)
        assigned = bool(handle) and bool(_k32.AssignProcessToJobObject(job, handle))
        stop = cancelled.is_set()
        resumed = assigned and not stop and _ntdll.NtResumeProcess(handle) == 0
        if handle:
            _k32.CloseHandle(handle)
        if not resumed:
            proc.kill()
            proc.communicate()
            _k32.CloseHandle(job)
            if stop:
                raise _Cancelled
            raise OSError("could not place claude in a job object")
        return proc, job

    def _terminate(proc: subprocess.Popen, job: int | None) -> None:
        if job:
            _k32.TerminateJobObject(job, 1)
        elif proc.poll() is None:
            proc.kill()

    def _close_job(job: int | None) -> None:
        if job:
            _k32.CloseHandle(job)  # kill-on-close: anything still alive in the tree ends here
else:  # pragma: no cover - the pet targets Windows
    def _spawn(args: list[str], cwd: str | None, cancelled: threading.Event) -> tuple[subprocess.Popen, int | None]:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=child_env(), cwd=cwd, start_new_session=True,
        )
        return proc, None

    def _terminate(proc: subprocess.Popen, job: int | None) -> None:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass

    def _close_job(job: int | None) -> None:
        pass


class _Cancelled(Exception):
    pass


class _TimedOut(Exception):
    pass


class _LaunchPending(Exception):
    pass


LAUNCH_PENDING = "previous claude launch still pending"
# Process creation runs outside the session lock, so cancel() can return while CreateProcess is
# still blocked (e.g. claude on a slow network share). This slot spans every session and is only
# released when that creation really finishes, so repeated cancel-and-retry cannot pile them up.
_spawn_slot = threading.Semaphore(1)


class ClaudeCall:
    """A cancellable session: the subscription check and the model call both run inside it.

    cancel() may come from another thread at any moment; once cancelled, no further process starts
    and the running process tree is terminated.
    """

    def __init__(self, timeout: float, cwd: str | None = None) -> None:
        self.timeout, self.cwd = timeout, cwd
        # The lock only guards registering/terminating/closing the current job: short, never held
        # across process creation or waiting, so cancel() from the UI thread returns at once.
        self._lock = threading.Lock()
        self._current: tuple[subprocess.Popen, int | None] | None = None
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            # Under the lock, so the job handle cannot be closed (and reused) while we terminate it.
            if self._current is not None:
                _terminate(*self._current)

    def _run(self, args: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]:
        if self._cancelled.is_set():
            raise _Cancelled
        if not _spawn_slot.acquire(blocking=False):
            raise _LaunchPending
        try:
            proc, job = _spawn(args, self.cwd, self._cancelled)
        finally:
            _spawn_slot.release()
        with self._lock:
            self._current = (proc, job)
            # A cancel that slipped in between spawn and registration found nothing to terminate.
            if self._cancelled.is_set():
                _terminate(proc, job)
        # On Windows communicate() writes all of stdin synchronously before its own timeout starts;
        # a CLI that never reads (with a screenshot larger than the pipe buffer) would block that write
        # forever. This independent deadline ends the job tree, which breaks the pipe and frees the write.
        expired = threading.Event()

        def on_deadline() -> None:
            expired.set()
            with self._lock:
                if self._current is not None and self._current[0] is proc:
                    _terminate(proc, job)

        deadline = threading.Timer(timeout, on_deadline)
        deadline.daemon = True
        try:
            deadline.start()
            try:
                stdout, stderr = proc.communicate(stdin_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                with self._lock:
                    _terminate(proc, job)
                try:
                    proc.communicate(timeout=5)  # bounded: the whole tree is gone, so the pipes close
                except subprocess.TimeoutExpired:
                    pass
                raise _TimedOut from None
            if self._cancelled.is_set():
                raise _Cancelled
            if expired.is_set():
                raise _TimedOut
            return proc.returncode, stdout or "", stderr or ""
        finally:
            deadline.cancel()
            with self._lock:
                self._current = None
                _close_job(job)

    def check_subscription(self, executable: str | list[str], timeout: float = 30) -> tuple[bool, str]:
        """Ask the CLI how it would authenticate; only a first-party claude.ai login is accepted."""
        try:
            _code, stdout, _err = self._run(_prefix(executable) + ["auth", "status"], "", timeout)
        except _Cancelled:
            return False, "cancelled"
        except _LaunchPending:
            return False, LAUNCH_PENDING
        except _TimedOut:
            return False, "auth status timed out"
        except OSError as exc:
            return False, f"auth status unavailable: {type(exc).__name__}"
        return _parse_auth_status(stdout)

    def run(self, args: list[str], message: str) -> ClaudeResult:
        try:
            code, stdout, stderr = self._run(args, message, self.timeout)
        except _Cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        except _LaunchPending:
            return ClaudeResult(False, error=LAUNCH_PENDING)
        except _TimedOut:
            return ClaudeResult(False, error="timeout", timed_out=True)
        except OSError as exc:
            return ClaudeResult(False, error=f"cannot start claude: {exc}")
        if code != 0:
            # A non-zero exit is a failure even if some assistant text arrived first.
            detail = stderr.strip().splitlines()[-1:] or [f"exit code {code}"]
            return ClaudeResult(False, error=f"{parse_stream(stdout).error or 'failed'}; {detail[0]}")
        return parse_stream(stdout)


def check_subscription(executable: str | list[str], timeout: float = 30) -> tuple[bool, str]:
    return ClaudeCall(timeout).check_subscription(executable, timeout)


def run_claude(args: list[str], message: str, timeout: float, cwd: str | None = None) -> ClaudeResult:
    return ClaudeCall(timeout, cwd).run(args, message)
